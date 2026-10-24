import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omnigraph_rehearsal as rehearsal

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "kubernetes/apps/ai/omnigraph/app"
DEPLOYMENT = "omnigraph-next"
BUNDLE_CONFIGMAP = "omnigraph-next-bundle"
INIT_CONTAINER = "apply-and-optimize"
SERVER_CONTAINER = "omnigraph"
MOUNTED_BUNDLE = "/etc/omnigraph/bundle"
SERVER_IMAGE = re.compile(r"/omnigraph-server:v(?P<version>[0-9][^@\s]*)@")
PROBE_GRAPH, PROBE_TYPE = "brain", "Passage"
BRANCHED_GRAPH = "memory"
OPEN_BRANCH = "rehearsal-open"


class Failure(Exception):
    pass


def say(status, stage, detail=""):
    print(f"{status:<5} {stage}{': ' + detail if detail else ''}", flush=True)


def documents(app_dir):
    proc = subprocess.run(["kustomize", "build", str(app_dir)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise Failure(f"kustomize build failed: {proc.stderr[-800:]}")
    return rehearsal.yaml_documents(proc.stdout)


def named(docs, kind, name, generated=False):
    for doc in docs:
        if doc.get("kind") == kind and (doc["metadata"]["name"] == name or (generated and doc["metadata"]["name"].startswith(name + "-"))):
            return doc
    raise Failure(f"the render has no {kind} {name}")


def container(pod_spec, name, init):
    for entry in pod_spec.get("initContainers" if init else "containers") or []:
        if entry["name"] == name:
            return entry
    raise Failure(f"{DEPLOYMENT} has no {'init ' if init else ''}container {name}")


def plain_env(entry):
    return {e["name"]: str(e["value"]) for e in entry.get("env") or [] if "value" in e}


def binaries(version, explicit):
    if explicit:
        return Path(explicit)
    proc = subprocess.run(["mise", "where", f"github:ModernRelay/omnigraph@{version}"], capture_output=True, text=True)
    if proc.returncode != 0:
        proc = subprocess.run(["mise", "install", f"github:ModernRelay/omnigraph@{version}"], capture_output=True, text=True)
        proc = subprocess.run(["mise", "where", f"github:ModernRelay/omnigraph@{version}"], capture_output=True, text=True)
    path = Path(proc.stdout.strip())
    if not (path / "omnigraph").exists():
        raise Failure(f"no omnigraph {version} binaries: install them with mise or pass --bin-dir")
    return path


class Cluster:
    def __init__(self, workdir, bin_dir, files, init_env, embed_url, bootstrap_text):
        self.workdir = workdir
        self.bin_dir = bin_dir
        self.state = workdir / "state"
        self.source = workdir / "source"
        for path in (self.state, self.source, workdir / "tmp", workdir / "home"):
            path.mkdir()
        self.files = dict(files)
        self.files["bootstrap.sh"] = bootstrap_text
        self.embed_url = embed_url
        self.env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(workdir / "home"),
            "TMPDIR": str(workdir / "tmp"),
            **init_env,
            "OMNIGRAPH_HOME": str(workdir / "home"),
            "OMNIGRAPH_BUNDLE_DIR": str(workdir / "bundle"),
            "OMNIGRAPH_STATE_DIR": str(self.state),
            "OMNIGRAPH_EMBED_BASE_URL": embed_url,
            "OMNIGRAPH_EMBED_API_KEY": "rehearsal",
        }
        self.operator = init_env.get("OMNIGRAPH_OPERATOR_ACTOR", "act-gitops")

    def write_source(self, edits=None):
        shutil.rmtree(self.source)
        self.source.mkdir()
        for name, text in self.files.items():
            if name == "cluster.yaml":
                text = re.sub(r"(?m)^storage:.*$", f"storage: file://{self.state}", text)
                text = re.sub(r"(?m)^(\s+base_url:).*$", rf"\g<1> {self.embed_url}", text)
            if name == "bootstrap.sh":
                text = text.replace(MOUNTED_BUNDLE, str(self.source))
            if edits and name in edits:
                text = edits[name](text)
            (self.source / name).write_text(text)

    def boot(self, label, edits=None):
        self.write_source(edits)
        bundle = self.workdir / "bundle"
        shutil.rmtree(bundle, ignore_errors=True)
        bundle.mkdir()
        started = time.monotonic()
        proc = subprocess.run(["sh", str(self.source / "bootstrap.sh")], env=self.env, capture_output=True, text=True, timeout=900)
        output = proc.stdout + proc.stderr
        if proc.returncode != 0:
            raise Failure(f"{label}: bootstrap.sh exited {proc.returncode}, which stops every graph:\n{rehearsal.tail(output, 20)}")
        if self.retained_lock():
            raise Failure(f"{label}: bootstrap.sh left the cluster lock held, so the server cannot take writer admission")
        return output, time.monotonic() - started

    def cli(self, *argv, check=True):
        proc = subprocess.run([str(self.bin_dir / "omnigraph"), *argv], env=self.env, capture_output=True, text=True, timeout=600)
        if check and proc.returncode != 0:
            raise Failure(f"omnigraph {' '.join(argv[:3])} exited {proc.returncode}: {(proc.stderr or proc.stdout)[-600:]}")
        return proc

    def retained_lock(self):
        proc = self.cli("cluster", "status", "--target", f"file://{self.state}", "--json", check=False)
        try:
            return json.loads(proc.stdout).get("lock_id")
        except json.JSONDecodeError:
            return None

    def owned(self, *argv):
        try:
            return self.cli(*argv)
        finally:
            lock = self.retained_lock()
            if lock:
                self.cli("cluster", "force-unlock", lock, "--target", f"file://{self.state}")

    def load(self, graph_id, units, prefix):
        rows = 0
        for path in rehearsal.write_load_files(units, self.workdir, f"{prefix}-{graph_id}"):
            self.owned("load", "--target", f"file://{self.state}", "--graph", graph_id, "--branch", "main", "--mode", "merge", "--data", str(path), "--as", self.operator)
            rows += sum(1 for _ in path.open())
        return rows

    def open_branch(self, graph_id):
        self.owned("branch", "create", OPEN_BRANCH, "--from", "main", "--target", f"file://{self.state}", "--graph", graph_id, "--as", self.operator)

    def vectorless(self, graph_id, type_name):
        exported = self.cli("export", "--target", f"file://{self.state}", "--graph", graph_id, "--type", type_name).stdout
        return sum(1 for line in exported.splitlines() if not json.loads(line).get("data", {}).get("embedding"))


class Server:
    def __init__(self, cluster, server_env, tokens):
        self.port = rehearsal.free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        tokens_file = cluster.workdir / "tokens.json"
        tokens_file.write_text(json.dumps(tokens))
        self.log_path = cluster.workdir / "server.log"
        self.log = self.log_path.open("w")
        self.process = subprocess.Popen(
            [str(cluster.bin_dir / "omnigraph-server"), "--cluster", f"file://{cluster.state}", "--bind", f"127.0.0.1:{self.port}", "--require-all-graphs"],
            env={**cluster.env, **server_env, "OMNIGRAPH_SERVER_BEARER_TOKENS_FILE": str(tokens_file)},
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self, graph_count, timeout=120):
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise Failure(f"omnigraph-server exited {self.process.returncode} before serving:\n{rehearsal.tail(self.log_path.read_text())}")
            try:
                with urllib.request.urlopen(f"{self.base}/readyz", timeout=5) as response:
                    ready = json.loads(response.read())
                    last = json.dumps(ready)
                    if ready.get("ready") and ready.get("ready_graph_count") == graph_count and not ready.get("blocked_graph_count"):
                        return
            except (OSError, json.JSONDecodeError):
                pass
            time.sleep(0.5)
        raise Failure(f"omnigraph-server did not serve all {graph_count} graphs within {timeout}s (last readyz: {last})")

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.log.close()


def stage(name, action):
    started = time.monotonic()
    try:
        detail = action()
    except Failure as failure:
        say("FAIL", name, str(failure))
        raise
    say("ok", name, f"{detail} ({time.monotonic() - started:.1f}s)")


def without_graph(graph_id, schema_file, query_file, policy_name, policy_file):
    def edit(text):
        text = text.replace(f"  {graph_id}:\n    embedding_provider: litellm\n    schema: {schema_file}\n    queries:\n      - {query_file}\n", "")
        return text.replace(f"  {policy_name}:\n    file: {policy_file}\n    applies_to:\n      - {graph_id}\n", "")
    return edit


def run(args):
    docs = documents(Path(args.app_dir))
    deployment = named(docs, "Deployment", DEPLOYMENT)
    pod_spec = deployment["spec"]["template"]["spec"]
    init = container(pod_spec, INIT_CONTAINER, init=True)
    server = container(pod_spec, SERVER_CONTAINER, init=False)
    images = {SERVER_IMAGE.search(c["image"])["version"] for c in (init, server) if SERVER_IMAGE.search(c["image"])}
    if len(images) != 1:
        raise Failure(f"{DEPLOYMENT}'s init container and server must run one digest-pinned omnigraph-server version, found {sorted(images) or 'none'}")
    version = images.pop()
    bin_dir = binaries(version, args.bin_dir)
    files = dict(named(docs, "ConfigMap", BUNDLE_CONFIGMAP, generated=True).get("data") or {})
    bootstrap_text = Path(args.bootstrap).read_text() if args.bootstrap else files["bootstrap.sh"]
    init_env = plain_env(init)
    for required in ("OMNIGRAPH_BACKFILL_MAX_ROWS", "OMNIGRAPH_BACKFILL_DEADLINE_SECONDS", "OMNIGRAPH_CLEANUP_OLDER_THAN", "OMNIGRAPH_HOME"):
        if required not in init_env:
            raise Failure(f"{DEPLOYMENT}'s init container sets no {required}")
    bundle = rehearsal.Bundle({k: v for k, v in files.items() if k != "bootstrap.sh"}, "omnigraph-next")
    graph_count = len(bundle.graphs())
    rehearsal.HTTP_CONTRACT_HEADERS["Omnigraph-Http-Api"] = ".".join(version.split(".")[:2])
    embedder = rehearsal.FakeEmbedder(model=init_env.get("OMNIGRAPH_EMBED_MODEL", "rehearsal"))
    embed_url = embedder.start()
    tokens = {actor: secrets.token_hex(16) for actor in bundle.policy_actors()}
    server_env = {**plain_env(server), "OMNIGRAPH_EMBED_API_KEY": "rehearsal"}
    running = None
    with tempfile.TemporaryDirectory(prefix="omnigraph-next-") as scratch:
        try:
            cluster = Cluster(Path(scratch), bin_dir, files, init_env, embed_url, bootstrap_text)
            say("info", "omnigraph", f"{version} from {bin_dir}")

            def fresh():
                output, elapsed = cluster.boot("fresh root")
                if "omnigraph bundle applied" not in output:
                    raise Failure(f"a fresh root did not report the bundle applied:\n{rehearsal.tail(output)}")
                return f"{graph_count} graphs created in {elapsed:.1f}s"

            stage("create on an empty volume", fresh)
            cap = int(init_env["OMNIGRAPH_BACKFILL_MAX_ROWS"])
            extra = cap + int(init_env.get("OMNIGRAPH_BACKFILL_PART_ROWS", "100"))

            def seed():
                rows = 0
                for graph_id in bundle.graphs():
                    wanted = {PROBE_TYPE: extra} if graph_id == PROBE_GRAPH else {}
                    rows += cluster.load(graph_id, rehearsal.seed_rows(bundle.schema(graph_id), wanted), "seed")
                cluster.open_branch(BRANCHED_GRAPH)
                return f"{rows} rows over every type, {extra + 1} vectorless {PROBE_GRAPH} {PROBE_TYPE}, branch {OPEN_BRANCH} on {BRANCHED_GRAPH}"

            stage("seed", seed)

            def restart():
                before = cluster.vectorless(PROBE_GRAPH, PROBE_TYPE)
                output, elapsed = cluster.boot("restart")
                if "omnigraph bundle applied" not in output:
                    raise Failure(f"a restart without changes did not apply the bundle:\n{rehearsal.tail(output)}")
                after = cluster.vectorless(PROBE_GRAPH, PROBE_TYPE)
                if before - after != cap:
                    raise Failure(f"the backfill cap is {cap}; {before} vectorless rows became {after}:\n{rehearsal.tail(output)}")
                cleaned = set(re.findall(r"cleanup \S*/graphs/([A-Za-z0-9_-]+)\.omni \(remove anything older than", output))
                if cleaned != set(bundle.graphs()):
                    raise Failure(f"cleanup ran on {sorted(cleaned)}, every graph is {sorted(bundle.graphs())}")
                return f"applied, {cap} rows embedded, {after} left for writers, every graph cleaned, {elapsed:.1f}s"

            stage("restart with a backlog", restart)

            def schema_change_with_branch():
                edits = {f"{BRANCHED_GRAPH}.pg": lambda text: text.replace("  title: String\n", "  title: String\n  rehearsal_note: String?\n", 1)}
                output, _ = cluster.boot("schema change", edits)
                if "omnigraph bundle not applied: the plan is refused" not in output:
                    raise Failure(f"a schema change while {BRANCHED_GRAPH} has a branch must be skipped, not applied or fatal:\n{rehearsal.tail(output)}")
                return "skipped with a reason, last applied state kept"

            stage("schema change while a branch is open", schema_change_with_branch)

            def removal():
                edits = {"cluster.yaml": without_graph("webgrip-notes", "tenant-notes.pg", "tenant-notes.gq", "webgrip-notes-access", "webgrip-notes.policy.yaml")}
                output, _ = cluster.boot("graph removal", edits)
                if "omnigraph bundle not applied: it deletes graph.webgrip-notes" not in output:
                    raise Failure(f"removing a graph without approved-deletions must be skipped:\n{rehearsal.tail(output)}")
                if not (cluster.state / "graphs/webgrip-notes.omni").exists():
                    raise Failure("the unapproved removal deleted webgrip-notes' storage")
                return "skipped, storage kept"

            stage("graph removed without approval", removal)

            def broken():
                edits = {"brain.gq": lambda text: text + "\nquery broken_rehearsal() { match { $x: NoSuchType } return { $x.slug } }\n"}
                output, _ = cluster.boot("broken bundle", edits)
                if "omnigraph bundle not applied" not in output:
                    raise Failure(f"a bundle that does not validate must be skipped:\n{rehearsal.tail(output)}")
                return "skipped"

            stage("bundle that does not validate", broken)

            def serve():
                nonlocal running
                running = Server(cluster, server_env, tokens)
                running.wait_ready(graph_count)
                return f"all {graph_count} graphs ready"

            stage("serve", serve)

            def smoke():
                totals = []
                for graph_id in sorted(bundle.graphs()):
                    actor, can_write = rehearsal.choose_smoke_actor(bundle.policy_for(graph_id))
                    if not actor:
                        raise Failure(f"{graph_id}: no actor may read and invoke queries")
                    try:
                        reads, writes = rehearsal.smoke_graph(running, bundle, graph_id, tokens[actor], can_write)
                    except rehearsal.Finding as finding:
                        raise Failure(str(finding)) from finding
                    totals.append(f"{graph_id} {reads}+{writes} as {actor}")
                return "; ".join(totals)

            stage("invoke every stored query", smoke)
        finally:
            if running:
                running.stop()
            embedder.stop()
    say("PASS", "omnigraph-next", f"bootstrap.sh on {version} creates, restarts, skips refused bundles and serves every stored query")


def main():
    parser = argparse.ArgumentParser(description="Rehearse the omnigraph-next (0.14) bootstrap on a throwaway cluster with the pinned binaries.")
    parser.add_argument("--app-dir", default=str(APP_DIR))
    parser.add_argument("--bin-dir", help="directory holding omnigraph and omnigraph-server of the pinned version; defaults to mise's install")
    parser.add_argument("--bootstrap", help="a bootstrap.sh to rehearse instead of the rendered one")
    args = parser.parse_args()
    try:
        run(args)
    except Failure as failure:
        say("FAIL", "omnigraph-next", str(failure).splitlines()[0])
        sys.exit(1)


if __name__ == "__main__":
    main()
