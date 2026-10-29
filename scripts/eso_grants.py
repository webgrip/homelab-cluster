#!/usr/bin/env python3
import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

GRANTS_FILE = Path("kubernetes/apps/security/openbao/bootstrap/eso-grants.txt")
STORES_FILE = Path("kubernetes/apps/security/external-secrets/tenants/stores.generated.yaml")
OPENBAO_ADDR = "http://openbao.security.svc.cluster.local:8200"
READ_SERVICE_ACCOUNT = "eso-openbao"
PUSH_SERVICE_ACCOUNT = "eso-openbao-push"
TOKEN_AUDIENCE = "openbao"
KV_STORE = "openbao"
DATABASE_STORE = "openbao-db"
PUSH_STORE = "openbao-push"
ACCESS_BY_STORE = {KV_STORE: "read", DATABASE_STORE: "database", PUSH_STORE: "push"}
FLUX_KUSTOMIZE_GROUP = "kustomize.toolkit.fluxcd.io/"
FLUX_ROOT = Path("kubernetes/flux/cluster/ks.yaml")


class TolerantLoader(yaml.SafeLoader):
    pass


TolerantLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


@dataclass(frozen=True, order=True)
class Grant:
    namespace: str
    access: str
    path: str

    def line(self):
        return f"{self.namespace} {self.access} {self.path}"


@dataclass(frozen=True)
class Reference:
    source: str
    namespace: str
    access: str
    path: str
    store_kind: str

    def grant(self):
        return Grant(self.namespace, self.access, self.path)


class InventoryError(Exception):
    pass


def load_documents(path):
    with open(path, encoding="utf-8") as handle:
        return [document for document in yaml.load_all(handle, Loader=TolerantLoader) if isinstance(document, dict)]


def kustomization_file(directory):
    for name in ("kustomization.yaml", "kustomization.yml", "Kustomization"):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def is_flux_kustomization(document):
    return document.get("kind") == "Kustomization" and str(document.get("apiVersion", "")).startswith(FLUX_KUSTOMIZE_GROUP)


class Tree:
    def __init__(self, root):
        self.root = root
        self.placements = []
        self.visited = set()
        for document in load_documents(root / FLUX_ROOT):
            if is_flux_kustomization(document):
                self.follow_flux(document)

    def follow_flux(self, document):
        spec = document.get("spec") or {}
        directory = (self.root / str(spec.get("path", ""))).resolve()
        self.walk_directory(directory, spec.get("targetNamespace"))

    def walk_directory(self, directory, namespace):
        key = (directory, namespace)
        if key in self.visited:
            return
        self.visited.add(key)
        kustomization_path = kustomization_file(directory)
        if kustomization_path is None:
            for path in sorted(directory.rglob("*.y*ml")):
                self.place(path, namespace)
            return
        kustomization = load_documents(kustomization_path)[0]
        namespace = namespace or kustomization.get("namespace")
        for entry in kustomization.get("resources") or []:
            target = (directory / entry).resolve()
            if target.is_dir():
                self.walk_directory(target, namespace)
            elif target.is_file():
                self.place(target, namespace)
        for entry in kustomization.get("components") or []:
            self.walk_directory((directory / entry).resolve(), namespace)

    def place(self, path, namespace):
        for document in load_documents(path):
            if is_flux_kustomization(document):
                self.follow_flux(document)
            else:
                self.placements.append((path, namespace, document))


def store_ref(reference):
    if not isinstance(reference, dict):
        return None, None
    kind = reference.get("kind", "SecretStore")
    if kind not in ("ClusterSecretStore", "SecretStore"):
        return None, None
    return kind, reference.get("name")


def external_secret_paths(document, source):
    spec = document.get("spec") or {}
    default_store = store_ref(spec.get("secretStoreRef"))
    for entry in spec.get("data") or []:
        kind, store = store_ref((entry.get("sourceRef") or {}).get("storeRef"))
        if store is None:
            kind, store = default_store
        if store in (KV_STORE, DATABASE_STORE):
            yield ACCESS_BY_STORE[store], (entry.get("remoteRef") or {}).get("key"), kind
    for entry in spec.get("dataFrom") or []:
        source_ref = entry.get("sourceRef") or {}
        if source_ref.get("generatorRef"):
            continue
        kind, store = store_ref(source_ref.get("storeRef"))
        if store is None:
            kind, store = default_store
        if store not in (KV_STORE, DATABASE_STORE):
            continue
        if entry.get("find"):
            raise InventoryError(f"{source}: dataFrom.find reads paths no policy can list; name each path with extract or data")
        yield ACCESS_BY_STORE[store], (entry.get("extract") or {}).get("key"), kind


def push_secret_paths(document):
    spec = document.get("spec") or {}
    kinds = [kind for kind, name in map(store_ref, spec.get("secretStoreRefs") or []) if name == PUSH_STORE]
    for kind in kinds:
        for entry in spec.get("data") or []:
            yield "push", ((entry.get("match") or {}).get("remoteRef") or {}).get("remoteKey"), kind


def references(root):
    found = []
    for path, forced_namespace, document in Tree(root).placements:
        relative = path.relative_to(root).as_posix()
        kind = document.get("kind")
        if kind == "ExternalSecret":
            paths = list(external_secret_paths(document, relative))
        elif kind == "PushSecret":
            paths = list(push_secret_paths(document))
        else:
            continue
        name = (document.get("metadata") or {}).get("name")
        namespace = forced_namespace or (document.get("metadata") or {}).get("namespace")
        if not namespace:
            raise InventoryError(f"{relative}: cannot tell which namespace {kind}/{name} lands in")
        for access, remote, store_kind in paths:
            if not remote or "$" in remote:
                raise InventoryError(f"{relative}: {kind}/{name} reads a path that is not a literal: {remote!r}")
            found.append(Reference(relative, namespace, access, remote.strip("/"), store_kind))
    return found


def committed_grants(root):
    path = root / GRANTS_FILE
    if not path.is_file():
        return set()
    grants = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 3 or fields[1] not in ACCESS_BY_STORE.values():
            raise InventoryError(f"{GRANTS_FILE}:{number}: expected '<namespace> read|database|push <path>', got {line!r}")
        grants.add(Grant(*fields))
    return grants


def render_grants(grants):
    return "".join(f"{grant.line()}\n" for grant in sorted(grants))


def store_document(namespace, name, service_account, role, mount, version):
    return {
        "apiVersion": "external-secrets.io/v1",
        "kind": "SecretStore",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "provider": {
                "vault": {
                    "server": OPENBAO_ADDR,
                    "path": mount,
                    "version": version,
                    "auth": {"kubernetes": {"mountPath": "kubernetes", "role": role, "serviceAccountRef": {"name": service_account, "audiences": [TOKEN_AUDIENCE]}}},
                }
            }
        },
    }


def service_account_document(namespace, name):
    return {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {"name": name, "namespace": namespace, "labels": {"app.kubernetes.io/managed-by": "eso-grants"}},
        "automountServiceAccountToken": False,
    }


def render_stores(grants):
    documents = []
    for namespace in sorted({grant.namespace for grant in grants}):
        accesses = {grant.access for grant in grants if grant.namespace == namespace}
        if accesses & {"read", "database"}:
            documents.append(service_account_document(namespace, READ_SERVICE_ACCOUNT))
        if "read" in accesses:
            documents.append(store_document(namespace, KV_STORE, READ_SERVICE_ACCOUNT, f"eso-read-{namespace}", "secret", "v2"))
        if "database" in accesses:
            documents.append(store_document(namespace, DATABASE_STORE, READ_SERVICE_ACCOUNT, f"eso-read-{namespace}", "database", "v1"))
        if "push" in accesses:
            documents.append(service_account_document(namespace, PUSH_SERVICE_ACCOUNT))
            documents.append(store_document(namespace, PUSH_STORE, PUSH_SERVICE_ACCOUNT, f"eso-push-{namespace}", "secret", "v2"))
    return "".join("---\n" + yaml.safe_dump(document, sort_keys=False) for document in documents)


def check(root, found):
    granted = committed_grants(root)
    needed = {reference.grant() for reference in found}
    problems = []
    for reference in sorted(found, key=lambda item: (item.namespace, item.source, item.path)):
        if reference.grant() not in granted:
            problems.append(f"{reference.source}: namespace {reference.namespace} needs {reference.access} on {reference.path}, which {GRANTS_FILE} does not grant")
    for source in sorted({reference.source for reference in found if reference.store_kind == "ClusterSecretStore"}):
        problems.append(f"{source}: names a ClusterSecretStore; OpenBao is reached only through the namespace's own SecretStore (ADR-0087)")
    for grant in sorted(granted - needed):
        problems.append(f"{GRANTS_FILE}: '{grant.line()}' is granted but nothing in namespace {grant.namespace} uses it")
    stores = root / STORES_FILE
    if not stores.is_file() or stores.read_text(encoding="utf-8") != render_stores(granted):
        problems.append(f"{STORES_FILE} does not match {GRANTS_FILE}")
    return problems


CLUSTER_STORE_REF = re.compile(
    r"(?P<lead>kind:\s*)ClusterSecretStore(?P<tail>\s*,\s*name:\s*(?:openbao|openbao-db|openbao-push)\s*[,}])"
    r"|(?P<blocklead>kind:\s*)ClusterSecretStore(?P<blocktail>[ \t]*\n[ \t]*name:\s*(?:openbao|openbao-db|openbao-push)[ \t]*$)"
    r"|(?P<namefirst>name:\s*(?:openbao|openbao-db|openbao-push)\s*,\s*kind:\s*)ClusterSecretStore",
    re.MULTILINE,
)


def to_namespaced_store(match):
    if match.group("lead") is not None:
        return f"{match.group('lead')}SecretStore{match.group('tail')}"
    if match.group("blocklead") is not None:
        return f"{match.group('blocklead')}SecretStore{match.group('blocktail')}"
    return f"{match.group('namefirst')}SecretStore"


def move(root, found, namespaces):
    namespaces_by_file = {}
    for reference in found:
        namespaces_by_file.setdefault(reference.source, set()).add(reference.namespace)
    still_on_cluster = {reference.source for reference in found if reference.store_kind == "ClusterSecretStore"}
    moved, skipped = [], []
    for source in sorted(still_on_cluster):
        landing = namespaces_by_file[source]
        if not landing & namespaces:
            continue
        if not landing <= namespaces:
            skipped.append(f"{source} also lands in {', '.join(sorted(landing - namespaces))}")
            continue
        path = root / source
        text = path.read_text(encoding="utf-8")
        rewritten = CLUSTER_STORE_REF.sub(to_namespaced_store, text)
        if rewritten == text:
            raise InventoryError(f"{source}: names a ClusterSecretStore in a shape --move cannot rewrite; edit it by hand")
        path.write_text(rewritten, encoding="utf-8")
        moved.append(source)
    after = [reference for reference in references(root) if reference.source in moved and reference.store_kind == "ClusterSecretStore"]
    if after:
        raise InventoryError(f"{after[0].source}: still names a ClusterSecretStore after --move; edit it by hand")
    return moved, skipped


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Inventory which OpenBao paths each namespace's ExternalSecrets and PushSecrets use, and keep the per-namespace grants and SecretStores in step with it."
    )
    parser.add_argument("root", type=Path, nargs="?", default=Path("."))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="rewrite the grants file and the generated SecretStores from the manifests")
    mode.add_argument("--summary", action="store_true", help="print grants per namespace")
    mode.add_argument("--move", nargs="+", metavar="NAMESPACE", help="point these namespaces' ExternalSecrets and PushSecrets at their own SecretStore")
    return parser.parse_args(argv)


def main(argv):
    arguments = parse_args(argv)
    root = arguments.root.resolve()
    try:
        found = references(root)
        if arguments.write:
            grants = {reference.grant() for reference in found}
            (root / GRANTS_FILE).write_text(render_grants(grants), encoding="utf-8")
            (root / STORES_FILE).parent.mkdir(parents=True, exist_ok=True)
            (root / STORES_FILE).write_text(render_stores(grants), encoding="utf-8")
            print(f"wrote {len(grants)} grants for {len({grant.namespace for grant in grants})} namespaces")
            return 0
        if arguments.move:
            moved, skipped = move(root, found, set(arguments.move))
            for source in moved:
                print(f"moved   {source}")
            for reason in skipped:
                print(f"skipped {reason}")
            return 0
        if arguments.summary:
            grants = sorted({reference.grant() for reference in found})
            for namespace in sorted({grant.namespace for grant in grants}):
                counts = {access: sum(1 for grant in grants if grant.namespace == namespace and grant.access == access) for access in ACCESS_BY_STORE.values()}
                on_cluster = len({reference.source for reference in found if reference.namespace == namespace and reference.store_kind == "ClusterSecretStore"})
                print(f"{namespace:24} read={counts['read']:3} database={counts['database']:2} push={counts['push']:3} files-on-cluster-store={on_cluster:3}")
            return 0
        problems = check(root, found)
    except (InventoryError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s); run `python3 scripts/eso_grants.py --write` and review the grant diff", file=sys.stderr)
        return 1
    print(f"{len(found)} references, all granted to their own namespace")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
