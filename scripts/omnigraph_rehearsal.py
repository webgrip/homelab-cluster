#!/usr/bin/env python3
import argparse
import hashlib
import http.server
import io
import json
import math
import os
import re
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_PATH = "kubernetes/apps/ai/omnigraph/app"
COMPONENTS_PATH = "kubernetes/components"
BUNDLE_CONFIGMAP = "omnigraph-bundle"
TOKENS_EXTERNALSECRET = "omnigraph-tokens"
DEPLOYMENT = "omnigraph"
INIT_CONTAINER = "apply-and-optimize"
SERVER_CONTAINER = "omnigraph"
SERVER_IMAGE = re.compile(r"/omnigraph-server:v?(?P<version>[0-9][^@\s]*)")
MISE_PIN = re.compile(r'^"github:ModernRelay/omnigraph"\s*=\s*"(?P<version>[^"]+)"', re.M)
RANKING_CALL = re.compile(r"\b(?:nearest|bm25|search|fuzzy)\(\s*\$(\w+)\.")
TYPE_BINDING = re.compile(r"^\$(\w+)\s*:\s*[A-Z]\w*")
OPEN_BRANCH = "rehearsal-open"
SEARCH_WORD = "rehearsal"
BACKFILL_CAPPED = re.compile(r"vector backfill capped: (\d+) (\S+) (\S+) rows left for writers")
REQUIRED_BUNDLE_FILES = ("cluster.yaml", "bootstrap.sh", "approved-deletions")
BUNDLE_KINDS = (".pg", ".gq", ".policy.yaml")
LOAD_FILE_ROWS = 3000


class Finding(Exception):
    pass


class Broken(Exception):
    pass


def say(status, stage, detail=""):
    print(f"{status:<5} {stage}{': ' + detail if detail else ''}", flush=True)


def run(argv, *, cwd=None, env=None, stdin_text=None, timeout=600, check=True):
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            input=stdin_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as error:
        raise Broken(f"{argv[0]} is not installed or not on PATH") from error
    except subprocess.TimeoutExpired as error:
        raise Finding(f"{' '.join(argv[:3])} did not finish within {timeout}s") from error
    if check and proc.returncode != 0:
        raise Finding(f"{' '.join(argv[:3])} exited {proc.returncode}: {tail(proc.stdout + proc.stderr)}")
    return proc


def tail(text, lines=15):
    kept = [line for line in text.strip().splitlines() if "lance::" not in line]
    return "\n".join(kept[-lines:])


def yaml_documents(text):
    try:
        import yaml
    except ImportError:
        out = run(["yq", "-o=json", "-I=0", "."], stdin_text=text).stdout
        return [json.loads(line) for line in out.splitlines() if line.strip() not in ("", "null")]
    return [doc for doc in yaml.safe_load_all(text) if doc]


def yaml_document(text):
    documents = yaml_documents(text)
    return documents[0] if documents else {}


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Rendered:
    def __init__(self, documents, label):
        self.documents = documents
        self.label = label

    def named(self, kind, name, generated=False):
        for document in self.documents:
            if document.get("kind") != kind:
                continue
            found = document["metadata"]["name"]
            if found == name or (generated and found.startswith(name + "-")):
                return document
        raise Finding(f"the {self.label} render has no {kind} {name}")

    def bundle_files(self):
        return dict(self.named("ConfigMap", BUNDLE_CONFIGMAP, generated=True).get("data") or {})

    def pod_spec(self):
        return self.named("Deployment", DEPLOYMENT)["spec"]["template"]["spec"]

    def container(self, name, init=False):
        key = "initContainers" if init else "containers"
        for container in self.pod_spec().get(key) or []:
            if container["name"] == name:
                return container
        raise Finding(f"the {self.label} Deployment has no {'init ' if init else ''}container {name}")

    def plain_env(self, name, init=False):
        return {
            entry["name"]: str(entry["value"])
            for entry in self.container(name, init).get("env") or []
            if "value" in entry
        }

    def server_images(self):
        spec = self.pod_spec()
        containers = (spec.get("initContainers") or []) + (spec.get("containers") or [])
        return {c["name"]: c["image"] for c in containers if "omnigraph-server" in c["image"]}

    def bundle_mount_path(self):
        volume_names = {
            volume["name"]
            for volume in self.pod_spec().get("volumes") or []
            if (volume.get("configMap") or {}).get("name", "").startswith(BUNDLE_CONFIGMAP)
        }
        for mount in self.container(INIT_CONTAINER, init=True).get("volumeMounts") or []:
            if mount["name"] in volume_names:
                return mount["mountPath"]
        raise Finding("the init container does not mount the omnigraph-bundle ConfigMap")

    def token_actors(self):
        secret = self.named("ExternalSecret", TOKENS_EXTERNALSECRET)
        template = secret["spec"]["target"]["template"]["data"]["tokens.json"]
        return set(json.loads(template))


def kustomize(app_dir, label):
    proc = run(["kustomize", "build", str(app_dir)], check=False)
    if proc.returncode != 0:
        raise Finding(f"kustomize build of the {label} bundle failed: {tail(proc.stderr)}")
    return Rendered(yaml_documents(proc.stdout), label)


def export_ref(repo_root, ref, into):
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "archive", "--format=tar", ref, "--", APP_PATH, COMPONENTS_PATH],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise Broken(f"git archive {ref} failed: {proc.stderr.decode(errors='replace').strip()}")
    with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as archive:
        archive.extractall(into, filter="data")
    return into / APP_PATH


class Bundle:
    def __init__(self, files, label):
        self.files = files
        self.label = label
        self.cluster = yaml_document(files.get("cluster.yaml", "")) or {}

    def graphs(self):
        return self.cluster.get("graphs") or {}

    def policy_bundles(self):
        return self.cluster.get("policies") or {}

    def referenced(self):
        names = set()
        for graph in self.graphs().values():
            names.add(graph["schema"])
            names.update(graph.get("queries") or [])
        for policy in self.policy_bundles().values():
            names.add(policy["file"])
        return names

    def query_files(self, graph_id):
        return list(self.graphs()[graph_id].get("queries") or [])

    def schema(self, graph_id):
        return parse_schema(self.files[self.graphs()[graph_id]["schema"]])

    def policy_for(self, graph_id):
        for policy in self.policy_bundles().values():
            if graph_id in (policy.get("applies_to") or []):
                return yaml_document(self.files[policy["file"]])
        return {}

    def policy_actors(self):
        actors = {}
        for policy in self.policy_bundles().values():
            document = yaml_document(self.files.get(policy["file"], "")) or {}
            for members in (document.get("groups") or {}).values():
                for actor in members or []:
                    actors.setdefault(actor, set()).add(policy["file"])
        return actors


def check_versions(repo_root, rendered):
    pin = MISE_PIN.search((repo_root / ".mise.toml").read_text())
    if not pin:
        raise Finding(".mise.toml does not pin github:ModernRelay/omnigraph")
    images = rendered.server_images()
    if not images:
        raise Finding("the omnigraph Deployment runs no omnigraph-server image")
    problems = []
    for container, image in sorted(images.items()):
        match = SERVER_IMAGE.search(image)
        if not match or match["version"] != pin["version"]:
            problems.append(f"container {container} runs {image}, mise pins omnigraph {pin['version']}")
    cli = run(["omnigraph", "--version"]).stdout.split()[-1]
    if cli != pin["version"]:
        problems.append(f"the omnigraph CLI on PATH is {cli}, mise pins {pin['version']}")
    if problems:
        raise Finding("; ".join(problems) + ". Bump the image and the mise pin in the same commit")
    return pin["version"]


def check_bundle_files(bundle):
    present = set(bundle.files)
    problems = [f"the ConfigMap does not carry {name}" for name in REQUIRED_BUNDLE_FILES if name not in present]
    referenced = bundle.referenced()
    for name in sorted(referenced - present):
        problems.append(f"cluster.yaml names {name}, but the omnigraph-bundle ConfigMap does not carry it: add it to the configMapGenerator")
    for name in sorted(present - referenced):
        if name.endswith(BUNDLE_KINDS):
            problems.append(f"the omnigraph-bundle ConfigMap carries {name}, but cluster.yaml does not use it")
    if problems:
        raise Finding("; ".join(problems))
    return len(referenced)


def blank_strings(text):
    out = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
                out.append(char)
                continue
            out.append("\n" if char == "\n" else " ")
        else:
            if char == '"':
                in_string = True
            out.append(char)
    return "".join(out)


def matching_brace(text, open_at):
    depth = 0
    for index in range(open_at, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    raise Finding("unbalanced braces")


def query_blocks(source):
    blank = blank_strings(source)
    for header in re.finditer(r"\bquery\s+(\w+)\s*\(([^)]*)\)", blank):
        open_at = blank.index("{", header.end())
        close_at = matching_brace(blank, open_at)
        yield header.group(1), header.group(2), blank[open_at + 1 : close_at], source[open_at + 1 : close_at]


def section(body, keyword):
    found = re.search(rf"\b{keyword}\s*\{{", body)
    if not found:
        return None
    open_at = found.end() - 1
    return body[open_at + 1 : matching_brace(body, open_at)]


def statements(block):
    return [line.strip() for line in re.split(r"[\n;]", block or "") if line.strip()]


def lint_query(file_name, name, body):
    problems = []
    for limit in re.finditer(r"\blimit\b\s*([^\s}]+)", body):
        if not limit.group(1).isdigit():
            problems.append(f"{file_name}:{name} uses limit {limit.group(1)}; v0.11 needs an integer literal")
    returned = section(body, "return")
    if returned and "rrf(" in returned:
        problems.append(f"{file_name}:{name} projects an rrf() score, which v0.11 cannot return")
    ranked = sorted(set(RANKING_CALL.findall(body)))
    if ranked:
        first = statements(section(body, "match"))
        binding = TYPE_BINDING.match(first[0]) if first else None
        first_variable = binding.group(1) if binding else None
        for variable in ranked:
            if variable != first_variable:
                shown = f"`{first[0]}`" if first else "nothing"
                problems.append(
                    f"{file_name}:{name} ranks ${variable} but binds {shown} first; "
                    f"bind `${variable}: <Type>` first in match{{}} (v0.11 errors on nearest/bm25 and silently stops ranking rrf otherwise)"
                )
    return problems


def lint_bundle(bundle):
    problems = []
    count = 0
    for graph_id in bundle.graphs():
        for file_name in bundle.query_files(graph_id):
            if file_name not in bundle.files:
                continue
            for name, _, body, _ in query_blocks(bundle.files[file_name]):
                count += 1
                problems.extend(lint_query(file_name, name, body))
    if problems:
        raise Finding("; ".join(sorted(set(problems))))
    return count


def check_actors_have_tokens(next_bundle, base_rendered, operator):
    known = base_rendered.token_actors() | {operator}
    problems = []
    for actor, files in sorted(next_bundle.policy_actors().items()):
        if actor not in known:
            problems.append(
                f"{', '.join(sorted(files))} grants {actor}, whose token the deployed omnigraph-tokens aggregator does not carry yet: "
                "push its token ExternalSecret and PushSecret first, wait for the aggregator to re-render, then push the policy"
            )
    if problems:
        raise Finding("; ".join(problems))
    return len(known)


def parse_type(text):
    optional = text.endswith("?")
    core = text[:-1] if optional else text
    if core.startswith("enum("):
        return {"kind": "enum", "values": [v.strip() for v in core[5:-1].split(",")], "optional": optional}
    vector = re.fullmatch(r"Vector\((\d+)\)", core)
    if vector:
        return {"kind": "vector", "dimensions": int(vector.group(1)), "optional": optional}
    listed = re.fullmatch(r"\[(\w+)\]", core)
    if listed:
        return {"kind": "list", "item": listed.group(1), "optional": optional}
    return {"kind": core, "optional": optional}


def split_type_and_annotations(rest):
    depth = 0
    for index, char in enumerate(rest):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "@" and depth == 0:
            return rest[:index].strip(), rest[index:]
    return rest.strip(), ""


def parse_properties(block):
    properties = {}
    for line in statements(block):
        if line.startswith("@"):
            continue
        field = re.match(r"(\w+)\s*:\s*(.+)$", line)
        if not field:
            continue
        type_text, annotations = split_type_and_annotations(field.group(2))
        spec = parse_type(type_text)
        spec["key"] = "@key" in annotations
        embed = re.search(r'@embed\("(\w+)"', annotations)
        spec["embed_source"] = embed.group(1) if embed else None
        properties[field.group(1)] = spec
    return properties


def parse_schema(source):
    blank = blank_strings(source)
    nodes = {}
    edges = {}
    for node in re.finditer(r"\bnode\s+(\w+)[^{]*\{", blank):
        close_at = matching_brace(blank, node.end() - 1)
        nodes[node.group(1)] = parse_properties(source[node.end() : close_at])
    for edge in re.finditer(r"\bedge\s+(\w+)\s*:\s*(\w+)\s*->\s*(\w+)([^\n{]*)(\{)?", blank):
        properties = {}
        if edge.group(5):
            close_at = matching_brace(blank, edge.end() - 1)
            properties = parse_properties(source[edge.end() : close_at])
        card = re.search(r"@card\((\d+)\.\.", edge.group(4))
        edges[edge.group(1)] = {
            "from": edge.group(2),
            "to": edge.group(3),
            "min": int(card.group(1)) if card else 0,
            "properties": properties,
        }
    return {"nodes": nodes, "edges": edges}


def key_field(properties):
    for name, spec in properties.items():
        if spec["key"]:
            return name
    return None


def row_key(type_name, index):
    return f"r-{type_name.lower()}-{index}"


def unit_vector(seed, dimensions):
    digest = hashlib.sha256(seed.encode()).digest()
    raw = [((digest[i % len(digest)] + i * 37) % 251) / 125.0 - 1.0 for i in range(dimensions)]
    norm = math.sqrt(sum(value * value for value in raw)) or 1.0
    return [round(value / norm, 6) for value in raw]


def synthetic_value(type_name, property_name, spec, index):
    kind = spec["kind"]
    if spec["key"]:
        return row_key(type_name, index)
    if kind == "String":
        return f"{SEARCH_WORD} {type_name} {property_name} {index} " + "tekst text " * 3
    if kind == "enum":
        return spec["values"][index % len(spec["values"])]
    if kind in ("I32", "I64", "U32", "U64"):
        return index + 1
    if kind in ("F32", "F64"):
        return 0.5
    if kind == "Bool":
        return True
    if kind == "Date":
        return f"2026-01-{(index % 28) + 1:02d}"
    if kind == "DateTime":
        return f"2026-01-{(index % 28) + 1:02d}T00:00:00Z"
    if kind == "list":
        return ["2026-01-01"] if spec["item"] == "Date" else [SEARCH_WORD]
    return None


def synthetic_node(type_name, properties, index, with_vectors, text_padding=0):
    data = {}
    for name, spec in properties.items():
        if spec["kind"] == "vector":
            if with_vectors:
                data[name] = unit_vector(f"{type_name}:{index}", spec["dimensions"])
            continue
        value = synthetic_value(type_name, name, spec, index)
        if value is None:
            continue
        if text_padding and spec["kind"] == "String" and not spec["key"]:
            value = (value + " ") * max(1, text_padding // max(1, len(value)))
        data[name] = value
    row = {"type": type_name, "data": data}
    if key_field(properties) is None:
        row["id"] = row_key(type_name, index)
    return row


def synthetic_edge_data(edge):
    return {
        name: synthetic_value("edge", name, spec, 0)
        for name, spec in edge["properties"].items()
        if spec["kind"] != "vector" and synthetic_value("edge", name, spec, 0) is not None
    }


def embed_types(schema):
    return {
        type_name
        for type_name, properties in schema["nodes"].items()
        if any(spec["kind"] == "vector" and spec["embed_source"] for spec in properties.values())
    }


def seed_rows(schema, extra_vectorless=None, text_padding=0):
    extra_vectorless = extra_vectorless or {}
    mandatory = {}
    for edge_name, edge in schema["edges"].items():
        if edge["min"] >= 1:
            mandatory.setdefault(edge["from"], []).append((edge_name, edge))
    embedding = embed_types(schema)
    independent, dependent = [], []
    for type_name, properties in schema["nodes"].items():
        indexes = [(0, True), (1, True)]
        if type_name in embedding:
            indexes.append((2, False))
            indexes.extend((3 + n, False) for n in range(extra_vectorless.get(type_name, 0)))
        for index, with_vectors in indexes:
            unit = [synthetic_node(type_name, properties, index, with_vectors, text_padding if index >= 3 else 0)]
            for edge_name, edge in mandatory.get(type_name, []):
                unit.append({"edge": edge_name, "from": row_key(type_name, index), "to": row_key(edge["to"], 0), **({"data": synthetic_edge_data(edge)} if edge["properties"] else {})})
            (dependent if type_name in mandatory else independent).append(unit)
    optional_edges = []
    for edge_name, edge in schema["edges"].items():
        if edge["min"] >= 1:
            continue
        target = 1 if edge["from"] == edge["to"] else 0
        row = {"edge": edge_name, "from": row_key(edge["from"], 0), "to": row_key(edge["to"], target)}
        if edge["properties"]:
            row["data"] = synthetic_edge_data(edge)
        optional_edges.append([row])
    return independent + dependent + optional_edges


def write_load_files(units, into, prefix):
    files = []
    batch = []
    for unit in units:
        if batch and len(batch) + len(unit) > LOAD_FILE_ROWS:
            files.append(batch)
            batch = []
        batch.extend(unit)
    if batch:
        files.append(batch)
    paths = []
    for number, rows in enumerate(files):
        path = into / f"{prefix}-{number:03d}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        paths.append(path)
    return paths


def rows_without_vector(state_dir, graph_id, type_name):
    exported = run(["omnigraph", "export", "--store", f"file://{state_dir}/graphs/{graph_id}.omni", "--type", type_name]).stdout
    missing = 0
    for line in exported.splitlines():
        row = json.loads(line)
        data = row.get("data", row)
        if not data.get("embedding"):
            missing += 1
    return missing


class FakeEmbedder:
    def __init__(self, model, tokens_per_second=0.0, scale=1.0):
        self.model = model
        self.tokens_per_second = tokens_per_second
        self.scale = scale
        self.inputs = []
        self.requests = 0
        self.lock = threading.Lock()
        self.server = None

    def start(self):
        embedder = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def reply(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    return

            def do_GET(self):
                self.reply(200, {"object": "list", "data": [{"id": embedder.model, "object": "model"}]})

            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
                inputs = request["input"] if isinstance(request["input"], list) else [request["input"]]
                with embedder.lock:
                    embedder.requests += 1
                    if len(embedder.inputs) < 5000:
                        embedder.inputs.extend(inputs)
                if embedder.tokens_per_second:
                    time.sleep(sum(len(text) for text in inputs) / 4.0 / embedder.tokens_per_second)
                dimensions = request.get("dimensions") or 384
                data = [
                    {"object": "embedding", "index": index, "embedding": [value * embedder.scale for value in unit_vector(text, dimensions)]}
                    for index, text in enumerate(inputs)
                ]
                self.reply(200, {"object": "list", "data": data, "model": request.get("model", embedder.model), "usage": {"prompt_tokens": 1, "total_tokens": 1}})

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def stop(self):
        if self.server:
            self.server.shutdown()


class Rehearsal:
    def __init__(self, workdir, embed_url, operator):
        self.workdir = workdir
        self.state = workdir / "state"
        self.state.mkdir()
        (workdir / "tmp").mkdir()
        self.embed_url = embed_url
        self.operator = operator

    def source_copy(self, bundle, label, mount_path):
        source = self.workdir / f"{label}-source"
        source.mkdir()
        for name, text in bundle.files.items():
            if name == "cluster.yaml":
                text = re.sub(r"(?m)^storage:.*$", f"storage: file://{self.state}", text)
                text = re.sub(r"(?m)^(\s+base_url:).*$", rf"\g<1> {self.embed_url}", text)
            if name == "bootstrap.sh":
                text = text.replace(mount_path, str(source))
            (source / name).write_text(text)
        return source

    def bootstrap(self, bundle, rendered, label):
        source = self.source_copy(bundle, label, rendered.bundle_mount_path())
        bundle_dir = self.workdir / f"{label}-bundle"
        bundle_dir.mkdir()
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(self.workdir)),
            "TMPDIR": str(self.workdir / "tmp"),
            **rendered.plain_env(INIT_CONTAINER, init=True),
            "OMNIGRAPH_BUNDLE_DIR": str(bundle_dir),
            "OMNIGRAPH_STATE_DIR": str(self.state),
            "OMNIGRAPH_EMBED_BASE_URL": self.embed_url,
            "OMNIGRAPH_EMBED_API_KEY": "rehearsal",
        }
        started = time.monotonic()
        proc = run(["sh", str(source / "bootstrap.sh")], env=env, check=False, timeout=900)
        elapsed = time.monotonic() - started
        output = proc.stdout + proc.stderr
        if proc.returncode != 0:
            raise Finding(f"bootstrap.sh of the {label} bundle exited {proc.returncode}, which stops every graph in the pod:\n{tail(output, 25)}")
        if "converged: true" not in output:
            raise Finding(f"bootstrap.sh of the {label} bundle never reported converged: true:\n{tail(output, 25)}")
        return bundle_dir, output, elapsed

    def store(self, graph_id):
        return f"file://{self.state}/graphs/{graph_id}.omni"

    def load(self, graph_id, units, prefix):
        paths = write_load_files(units, self.workdir, f"{prefix}-{graph_id}")
        rows = 0
        for path in paths:
            run(["omnigraph", "load", "--store", self.store(graph_id), "--branch", "main", "--mode", "merge", "--data", str(path), "--as", self.operator, "--quiet"])
            rows += sum(1 for _ in path.open())
        return rows

    def open_branch(self, graph_id):
        run(["omnigraph", "branch", "create", "--uri", self.store(graph_id), "--from", "main", "--as", self.operator, OPEN_BRANCH])


def choose_smoke_actor(policy):
    groups = policy.get("groups") or {}
    grants = {}
    for rule in policy.get("rules") or []:
        allow = rule.get("allow") or {}
        scope = allow.get("branch_scope") or allow.get("target_branch_scope") or "any"
        for actor in groups.get((allow.get("actors") or {}).get("group"), []) or []:
            for action in allow.get("actions") or []:
                grants.setdefault(actor, set()).add((action, scope))

    def holds(actor, action, scopes):
        return any((action, scope) in grants.get(actor, set()) for scope in scopes)

    for actor in sorted(grants):
        if holds(actor, "invoke_query", ("any",)) and holds(actor, "read", ("any",)) and holds(actor, "change", ("any", "unprotected")) and holds(actor, "branch_create", ("any", "unprotected")):
            return actor, True
    for actor in sorted(grants):
        if holds(actor, "invoke_query", ("any",)) and holds(actor, "read", ("any",)):
            return actor, False
    return None, False


ROLE_PRIORITY = {"endpoint": 0, "key": 1, "existing": 2, "edge_field": 3, "field": 4}


def param_roles(schema, source_body):
    found = {}
    variables = {}

    def note(param, role):
        found.setdefault(param, []).append(role)

    for binding in re.finditer(r"\$(\w+)\s*:\s*([A-Z]\w*)", source_body):
        variables[binding.group(1)] = binding.group(2)
    for block in re.finditer(r"(?:\$(\w+)\s*:\s*|\binsert\s+|\bupdate\s+)([A-Z]\w*)\s*(?:set\s*)?\{([^{}]*)\}", source_body):
        type_name = block.group(2)
        inserted = source_body[max(0, block.start() - 7) : block.start() + 7].strip().startswith("insert")
        for field, param in re.findall(r"(\w+)\s*:\s*\$(\w+)", block.group(3)):
            if type_name in schema["edges"]:
                edge = schema["edges"][type_name]
                if field in ("from", "to"):
                    note(param, ("endpoint", edge[field], field))
                else:
                    note(param, ("edge_field", type_name, field))
                continue
            spec = schema["nodes"].get(type_name, {}).get(field)
            note(param, ("key" if spec and spec["key"] else "field", type_name, field, inserted))
    for where in re.finditer(r"\b(?:update|delete)\s+([A-Z]\w*)[^{}]*?(?:\{[^{}]*\})?\s*where\s+(\w+)\s*=\s*\$(\w+)", source_body):
        note(where.group(3), ("existing", where.group(1), where.group(2)))
    for compare in re.finditer(r"\$(\w+)\.(\w+)\s*(?:!=|>=|<=|==|=|>|<|starts_with)\s*\$(\w+)", source_body):
        type_name = variables.get(compare.group(1))
        if type_name:
            note(compare.group(3), ("field", type_name, compare.group(2), False))
    return {param: min(roles, key=lambda role: ROLE_PRIORITY[role[0]]) for param, roles in found.items()}


def ordered_params(params, roles):
    return sorted(params, key=lambda param: ROLE_PRIORITY.get(roles.get(param["name"], ("field",))[0], 9), reverse=True)


def smoke_value(param, role, schema, inserted_keys):
    kind = param["kind"]
    if role and role[0] == "endpoint":
        type_name, side = role[1], role[2]
        if type_name in inserted_keys:
            return inserted_keys[type_name]
        return row_key(type_name, 1 if side == "from" else 0)
    if role and role[0] == "existing":
        return row_key(role[1], 1)
    if role and role[0] == "edge_field":
        spec = schema["edges"][role[1]]["properties"].get(role[2])
        if spec and spec["kind"] == "enum":
            return spec["values"][0]
    if role and role[0] == "key":
        type_name, inserted = role[1], role[3]
        if inserted:
            inserted_keys[type_name] = f"r-{type_name.lower()}-smoke"
            return inserted_keys[type_name]
        return row_key(type_name, 0)
    if role and role[0] == "field":
        spec = schema["nodes"].get(role[1], {}).get(role[2])
        if spec and spec["kind"] == "enum":
            return spec["values"][0]
    if kind == "string":
        return SEARCH_WORD
    if kind == "datetime":
        return "2026-01-01T00:00:00Z"
    if kind == "date":
        return "2026-01-01"
    if kind in ("int", "integer"):
        return 1
    if kind in ("float", "number"):
        return 0.5
    if kind in ("bool", "boolean"):
        return True
    if kind == "list":
        return ["2026-01-01"] if param.get("item_kind") == "date" else [SEARCH_WORD]
    if "vector" in kind:
        dimensions = param.get("dimension") or param.get("dimensions") or 384
        return unit_vector(SEARCH_WORD, int(dimensions))
    if param.get("nullable"):
        return None
    raise Finding(f"cannot synthesize a {kind} parameter {param['name']}")


def request(url, token, payload=None, method=None):
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode(errors="replace")


class Server:
    def __init__(self, bundle_dir, tokens, env, workdir):
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        tokens_file = workdir / "tokens.json"
        tokens_file.write_text(json.dumps(tokens))
        self.log = (workdir / "server.log").open("w")
        self.process = subprocess.Popen(
            ["omnigraph-server", "--cluster", str(bundle_dir), "--bind", f"127.0.0.1:{self.port}", "--require-all-graphs"],
            env={**env, "OMNIGRAPH_SERVER_BEARER_TOKENS_FILE": str(tokens_file)},
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )
        self.log_path = workdir / "server.log"

    def wait_ready(self, graph_count, timeout):
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise Finding(f"omnigraph-server exited {self.process.returncode} before serving:\n{tail(self.log_path.read_text())}")
            try:
                with urllib.request.urlopen(f"{self.base}/readyz", timeout=5) as response:
                    ready = json.loads(response.read())
                    last = json.dumps(ready)
                    if ready.get("ready") and ready.get("served_graph_count") == graph_count and not ready.get("quarantined_graph_count"):
                        return
            except (urllib.error.URLError, ConnectionError, json.JSONDecodeError):
                pass
            time.sleep(0.5)
        raise Finding(f"omnigraph-server did not serve all {graph_count} graphs within {timeout}s (last readyz: {last})")

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.log.close()


def declared_queries(bundle, graph_id):
    names = {}
    for file_name in bundle.query_files(graph_id):
        for name, _, _, source_body in query_blocks(bundle.files[file_name]):
            names[name] = source_body
    return names


def smoke_graph(server, bundle, graph_id, token, can_write):
    status, body = request(f"{server.base}/graphs/{graph_id}/queries", token)
    if status != 200:
        raise Finding(f"{graph_id}: the stored-query catalog answered HTTP {status}: {body[:300]}")
    catalog = {query["name"]: query for query in json.loads(body)["queries"]}
    declared = declared_queries(bundle, graph_id)
    missing = sorted(set(declared) - set(catalog))
    if missing:
        raise Finding(f"{graph_id}: declared stored queries are not served: {', '.join(missing)}")
    schema = bundle.schema(graph_id)
    failures = []
    reads = writes = 0
    for number, (name, query) in enumerate(sorted(catalog.items())):
        roles = param_roles(schema, declared.get(name, ""))
        inserted = {}
        params = {p["name"]: smoke_value(p, roles.get(p["name"]), schema, inserted) for p in ordered_params(query["params"], roles)}
        payload = {"params": params}
        if query.get("mutation"):
            if not can_write:
                continue
            branch = f"smoke-{number}"
            status, body = request(f"{server.base}/graphs/{graph_id}/branches", token, {"name": branch, "from": "main"})
            if status >= 300:
                failures.append(f"{name}: creating branch {branch} answered HTTP {status}: {body[:200]}")
                continue
            payload["branch"] = branch
            writes += 1
        else:
            reads += 1
        status, body = request(f"{server.base}/graphs/{graph_id}/queries/{name}", token, payload)
        if status >= 300:
            failures.append(f"{name}{' (mutation on a branch)' if query.get('mutation') else ''} answered HTTP {status}: {body[:300]}")
    if failures:
        raise Finding(f"{graph_id}: {len(failures)} stored queries fail when invoked: " + "; ".join(failures))
    return reads, writes


def check_every_type_filled(bundle, probe_graph, probe_type, state_dir, operator):
    starved = []
    for graph_id in bundle.graphs():
        for type_name in sorted(embed_types(bundle.schema(graph_id))):
            if (graph_id, type_name) == (probe_graph, probe_type):
                continue
            left = rows_without_vector(state_dir, graph_id, type_name)
            if left:
                starved.append(f"{graph_id} {type_name} ({left})")
    if starved:
        raise Finding(f"the startup backfill left seeded rows without a vector in small backlogs: {', '.join(starved)}; one large backlog must not starve the others")
    return len(starved)


def check_backfill(output, rendered, probe_graph, probe_type, extra, state_dir, operator):
    env = rendered.plain_env(INIT_CONTAINER, init=True)
    if "OMNIGRAPH_BACKFILL_MAX_ROWS" not in env or "OMNIGRAPH_BACKFILL_DEADLINE_SECONDS" not in env:
        raise Finding("the init container sets no OMNIGRAPH_BACKFILL_MAX_ROWS or OMNIGRAPH_BACKFILL_DEADLINE_SECONDS: the startup backfill is unbounded (VIK-1348)")
    cap = int(env["OMNIGRAPH_BACKFILL_MAX_ROWS"])
    seeded = extra + 1
    expected_left = max(0, seeded - cap)
    reported = {(m.group(2), m.group(3)): int(m.group(1)) for m in BACKFILL_CAPPED.finditer(output)}
    left = rows_without_vector(state_dir, probe_graph, probe_type)
    if left != expected_left or reported.get((probe_graph, probe_type), 0) != expected_left:
        raise Finding(
            f"{seeded} {probe_graph} {probe_type} rows lacked a vector and the cap is {cap}; expected {expected_left} left and a matching "
            f"'vector backfill capped' line, found {left} left and {reported.get((probe_graph, probe_type), 'no')} reported:\n{tail(output, 12)}"
        )
    return seeded - left, left


def stage(name, action):
    started = time.monotonic()
    try:
        detail = action()
    except Finding as finding:
        say("FAIL", name, str(finding))
        finding.reported = True
        raise
    say("ok", name, f"{detail} ({time.monotonic() - started:.1f}s)" if detail is not None else f"({time.monotonic() - started:.1f}s)")
    return detail


def rehearse(args):
    repo_root = Path(args.repo_root).resolve()
    next_app = Path(args.app_dir).resolve() if args.app_dir else repo_root / APP_PATH
    keep = args.keep
    with tempfile.TemporaryDirectory(prefix="omnigraph-rehearsal-") as scratch:
        workdir = Path(scratch)
        if args.base_app_dir:
            base_app = Path(args.base_app_dir).resolve()
            base_label = str(args.base_app_dir)
        else:
            base_app = export_ref(repo_root, args.base_ref, workdir / "base-tree")
            base_label = args.base_ref
        rendered = {}

        def render(label, app_dir):
            rendered[label] = kustomize(app_dir, label)
            return f"{len(rendered[label].bundle_files())} files in the rendered omnigraph-bundle ConfigMap"

        stage("render working bundle", lambda: render("working", next_app))
        stage(f"render deployed bundle ({base_label})", lambda: render("deployed", base_app))
        next_rendered = rendered["working"]
        base_rendered = rendered["deployed"]
        next_bundle = Bundle(next_rendered.bundle_files(), "working")
        base_bundle = Bundle(base_rendered.bundle_files(), "deployed")
        operator = next_rendered.plain_env(INIT_CONTAINER, init=True).get("OMNIGRAPH_OPERATOR_ACTOR", "act-gitops")
        stage("omnigraph versions", lambda: f"mise, image and CLI agree on {check_versions(repo_root, next_rendered)}")
        stage("bundle files", lambda: f"{check_bundle_files(next_bundle)} files named by cluster.yaml are all in the ConfigMap")
        if not args.no_lint:
            stage("query lint", lambda: f"{lint_bundle(next_bundle)} queries rank their first binding and use literal limits")
        stage("actor tokens", lambda: f"every policy actor has a deployed token ({check_actors_have_tokens(next_bundle, base_rendered, operator)} known)")
        embedder = FakeEmbedder(model=next_rendered.plain_env(INIT_CONTAINER, init=True).get("OMNIGRAPH_EMBED_MODEL", "rehearsal"))
        embed_url = embedder.start()
        server = None
        rehearsal_dir = Path(tempfile.mkdtemp(prefix="omnigraph-rehearsal-", dir=keep)) if keep else workdir / "cluster"
        if not keep:
            rehearsal_dir.mkdir()
        try:
            rehearsal = Rehearsal(rehearsal_dir, embed_url, operator)
            stage("create the deployed cluster", lambda: f"{len(base_bundle.graphs())} graphs, {rehearsal.bootstrap(base_bundle, base_rendered, 'deployed')[2]:.1f}s bootstrap")
            probe_graph, probe_type = args.backfill_probe.split(".")
            base_env = base_rendered.plain_env(INIT_CONTAINER, init=True)
            next_env = next_rendered.plain_env(INIT_CONTAINER, init=True)
            cap = int(next_env.get("OMNIGRAPH_BACKFILL_MAX_ROWS", base_env.get("OMNIGRAPH_BACKFILL_MAX_ROWS", "500")))
            part = int(next_env.get("OMNIGRAPH_BACKFILL_PART_ROWS", "100"))
            extra = cap + part if probe_graph in base_bundle.graphs() else 0

            def seed():
                rows = 0
                for graph_id in base_bundle.graphs():
                    schema = base_bundle.schema(graph_id)
                    wanted = {probe_type: extra} if graph_id == probe_graph else {}
                    rows += rehearsal.load(graph_id, seed_rows(schema, wanted), "seed")
                return f"{rows} synthetic rows over every node and edge type, vectors included, plus {extra + 1} vectorless {probe_graph} {probe_type} rows"

            stage("seed", seed)
            drained = set(args.drained or [])

            def open_branches():
                opened = [graph_id for graph_id in base_bundle.graphs() if graph_id not in drained]
                for graph_id in opened:
                    rehearsal.open_branch(graph_id)
                named = ", ".join(f"{graph_id}:{OPEN_BRANCH}" for graph_id in opened) or "none"
                return named + (f"; declared drained: {', '.join(sorted(drained))}" if drained else "")

            stage("open branches", open_branches)
            applied = {}

            def apply_working():
                applied["bundle_dir"], applied["output"], elapsed = rehearsal.bootstrap(next_bundle, next_rendered, "working")
                return f"bootstrap.sh converged in {elapsed:.1f}s with every graph's branch open"

            stage("apply the working bundle", apply_working)
            bundle_dir, output = applied["bundle_dir"], applied["output"]
            if extra:
                stage("capped backfill", lambda: "{} embedded, {} left for writers".format(*check_backfill(output, next_rendered, probe_graph, probe_type, extra, rehearsal.state, operator)))
                stage("small backlogs filled", lambda: "every other embedding type got its vectors" if check_every_type_filled(next_bundle, probe_graph, probe_type, rehearsal.state, operator) == 0 else "")
            tokens = {actor: secrets.token_hex(16) for actor in next_bundle.policy_actors()}
            server_env = {
                "PATH": os.environ["PATH"],
                "HOME": os.environ.get("HOME", str(workdir)),
                "TMPDIR": str(rehearsal_dir / "tmp"),
                **next_rendered.plain_env(SERVER_CONTAINER),
                "OMNIGRAPH_EMBED_API_KEY": "rehearsal",
            }
            server = Server(bundle_dir, tokens, server_env, rehearsal_dir)

            def serve():
                server.wait_ready(len(next_bundle.graphs()), 90)
                return f"all {len(next_bundle.graphs())} graphs ready"

            stage("serve", serve)

            def smoke():
                totals = []
                for graph_id in sorted(next_bundle.graphs()):
                    actor, can_write = choose_smoke_actor(next_bundle.policy_for(graph_id))
                    if not actor:
                        raise Finding(f"{graph_id}: no actor may read and invoke queries, so nothing can use its stored queries")
                    reads, writes = smoke_graph(server, next_bundle, graph_id, tokens[actor], can_write)
                    totals.append(f"{graph_id} {reads} reads + {writes} mutations as {actor}")
                return "; ".join(totals)

            stage("invoke every stored query", smoke)
        finally:
            if server:
                server.stop()
            embedder.stop()
    say("PASS", "rehearsal", "the working bundle applies over the deployed one with branches open and serves every stored query")


def backfill_drill(args):
    repo_root = Path(args.repo_root).resolve()
    app = Path(args.app_dir).resolve() if args.app_dir else repo_root / APP_PATH
    with tempfile.TemporaryDirectory(prefix="omnigraph-backfill-drill-") as scratch:
        workdir = Path(scratch)
        rendered = kustomize(app, "working")
        bundle = Bundle(rendered.bundle_files(), "working")
        operator = rendered.plain_env(INIT_CONTAINER, init=True).get("OMNIGRAPH_OPERATOR_ACTOR", "act-gitops")
        embedder = FakeEmbedder(rendered.plain_env(INIT_CONTAINER, init=True).get("OMNIGRAPH_EMBED_MODEL", "rehearsal"), args.tokens_per_second)
        embed_url = embedder.start()
        server = None
        try:
            (workdir / "cluster").mkdir()
            rehearsal = Rehearsal(workdir / "cluster", embed_url, operator)
            rehearsal.bootstrap(bundle, rendered, "first")
            probe_graph, probe_type = args.backfill_probe.split(".")
            rows = rehearsal.load(probe_graph, seed_rows(bundle.schema(probe_graph), {probe_type: args.rows}, text_padding=args.text_chars), "drill")
            before = rows_without_vector(rehearsal.state, probe_graph, probe_type)
            say("info", "seeded", f"{rows} rows; {before} {probe_graph} {probe_type} rows without a vector")
            started = time.monotonic()
            bundle_dir, output, elapsed = rehearsal.bootstrap(bundle, rendered, "restart")
            tokens = {actor: secrets.token_hex(16) for actor in bundle.policy_actors()}
            server_env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", str(workdir)), **rendered.plain_env(SERVER_CONTAINER), "OMNIGRAPH_EMBED_API_KEY": "rehearsal"}
            server = Server(bundle_dir, tokens, server_env, workdir / "cluster")
            server.wait_ready(len(bundle.graphs()), 300)
            serving = time.monotonic() - started
            after = rows_without_vector(rehearsal.state, probe_graph, probe_type)
            for line in output.splitlines():
                if "vector backfill" in line:
                    say("info", "bootstrap", line)
            say("info", "restart", f"init container {elapsed:.1f}s, serving after {serving:.1f}s; {before - after} rows embedded, {after} left for writers, {embedder.requests} embedding requests")
            if serving > args.budget_seconds:
                say("FAIL", "backfill drill", f"serving took {serving:.1f}s, over the {args.budget_seconds}s budget")
                raise Finding("over budget")
            say("PASS", "backfill drill", f"a restart with {before} vectorless {probe_type} rows serves in {serving:.1f}s (budget {args.budget_seconds}s)")
        finally:
            if server:
                server.stop()
            embedder.stop()


def lint_only(args):
    files = {Path(path).name: Path(path).read_text() for path in args.files}
    problems = []
    for name, text in files.items():
        for query, _, body, _ in query_blocks(text):
            problems.extend(lint_query(name, query, body))
    for problem in problems:
        say("FAIL", "query lint", problem)
    if problems:
        raise Finding("lint")
    say("PASS", "query lint", f"{len(files)} files")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rehearse an Omnigraph bundle change on a throwaway cluster before it reaches the pod.")
    commands = parser.add_subparsers(dest="command", required=True)
    rehearse_parser = commands.add_parser("rehearse", help="apply the working bundle over the deployed one with seeded rows and open branches, then invoke every stored query")
    rehearse_parser.add_argument("--repo-root", default=str(REPO_ROOT))
    rehearse_parser.add_argument("--app-dir", help="the kustomization to rehearse; defaults to the working tree's omnigraph app")
    rehearse_parser.add_argument("--base-ref", default=os.environ.get("OMNIGRAPH_REHEARSAL_BASE_REF", "origin/main"), help="git ref of the deployed bundle")
    rehearse_parser.add_argument("--base-app-dir", help="an already checked-out deployed kustomization, instead of --base-ref")
    rehearse_parser.add_argument("--drained", action="append", default=[g for g in os.environ.get("OMNIGRAPH_REHEARSAL_DRAINED", "").split(",") if g], help="a graph proven to have only main live; no branch is opened on it, so a schema change may apply")
    rehearse_parser.add_argument("--backfill-probe", default="brain.Passage")
    rehearse_parser.add_argument("--no-lint", action="store_true", help="skip the static query lint, to prove the live checks on their own")
    rehearse_parser.add_argument("--keep", help="keep the throwaway cluster under this directory")
    rehearse_parser.set_defaults(handler=rehearse)
    drill_parser = commands.add_parser("backfill-drill", help="time a restart with many vectorless rows against a throttled fake embedder")
    drill_parser.add_argument("--repo-root", default=str(REPO_ROOT))
    drill_parser.add_argument("--app-dir")
    drill_parser.add_argument("--rows", type=int, default=20000)
    drill_parser.add_argument("--text-chars", type=int, default=1400)
    drill_parser.add_argument("--tokens-per-second", type=float, default=1000.0)
    drill_parser.add_argument("--budget-seconds", type=int, default=180)
    drill_parser.add_argument("--backfill-probe", default="brain.Passage")
    drill_parser.set_defaults(handler=backfill_drill)
    lint_parser = commands.add_parser("lint", help="lint .gq files only")
    lint_parser.add_argument("files", nargs="+")
    lint_parser.set_defaults(handler=lint_only)
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except Finding as finding:
        if not getattr(finding, "reported", False):
            say("FAIL", "rehearsal", str(finding))
        return 1
    except Broken as broken:
        say("ERROR", "rehearsal", str(broken))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
