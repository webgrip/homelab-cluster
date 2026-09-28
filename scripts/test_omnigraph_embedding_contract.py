#!/usr/bin/env python3
import copy
import json
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omnigraph_rehearsal as rehearsal

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "kubernetes/apps/ai/omnigraph/embed-step/app/contract.json"
BUNDLE = ROOT / "kubernetes/apps/ai/omnigraph/app/bundle"
DEPLOYMENT = ROOT / "kubernetes/apps/ai/omnigraph/app/deployment.yaml"
EMBED = re.compile(r"Vector\((\d+)\)\??\s*@embed\(\"(\w+)\"(?:,\s*model=\"([^\"]+)\")?")


def inputs_from_disk():
    return {
        "cluster": rehearsal.yaml_document((BUNDLE / "cluster.yaml").read_text()),
        "schemas": {path.name: path.read_text() for path in BUNDLE.glob("*.pg")},
        "deployment": rehearsal.yaml_document(DEPLOYMENT.read_text()),
    }


def init_env(deployment):
    for container in deployment["spec"]["template"]["spec"]["initContainers"]:
        if container["name"] == rehearsal.INIT_CONTAINER:
            return {entry["name"]: str(entry.get("value")) for entry in container.get("env") or []}
    return {}


def contract_problems(contract, inputs):
    problems = []
    provider = (inputs["cluster"].get("providers", {}).get("embedding", {}) or {}).get(contract["provider"])
    if not provider:
        problems.append(f"cluster.yaml declares no embedding provider {contract['provider']}")
    elif provider.get("model") != contract["model"]:
        problems.append(f"cluster.yaml provider {contract['provider']} serves {provider.get('model')}, the contract says {contract['model']}")
    graphs = inputs["cluster"].get("graphs") or {}
    if (graphs.get("brain") or {}).get("embedding_provider") != contract["provider"]:
        problems.append(f"the brain graph does not embed through {contract['provider']}")
    for graph_id, graph in sorted(graphs.items()):
        if graph.get("embedding_provider") != contract["provider"]:
            continue
        schema = inputs["schemas"].get(graph["schema"], "")
        embeds = EMBED.findall(schema)
        if not embeds:
            problems.append(f"{graph['schema']} ({graph_id}) has no @embed property")
        for dimensions, source, model in embeds:
            if model != contract["model"]:
                problems.append(f"{graph['schema']} embeds {source} with model {model or '(unset)'}, the contract says {contract['model']}")
            if int(dimensions) != contract["dimensions"]:
                problems.append(f"{graph['schema']} stores {source} vectors as Vector({dimensions}), the contract says {contract['dimensions']}")
    served = init_env(inputs["deployment"]).get("OMNIGRAPH_EMBED_MODEL")
    if served != contract["model"]:
        problems.append(f"the init container backfills with OMNIGRAPH_EMBED_MODEL={served}, the contract says {contract['model']}")
    return problems


def embed_text(contract, node_type, field, value):
    trimmed = value.strip(contract["value_trim_characters"])
    if not trimmed:
        return contract["empty_value_format"].format(type=node_type)
    return contract["text_format"].format(type=node_type, field=field, value=trimmed)


def parity_problems(contract):
    embedder = rehearsal.FakeEmbedder(contract["model"], scale=3.0)
    url = embedder.start()
    rows = [
        {"type": "Passage", "id": "p1", "field": "text", "value": "Een zin met \"quotes\"\nen een tweede regel"},
        {"type": "Note", "slug": "n1", "field": "content", "value": "A note body"},
        {"type": "Passage", "id": "p2", "field": "text", "value": " \n\tpadded   inner  spacing kept\r\n \u00a0\u3000"},
        {"type": "Passage", "id": "p3", "field": "text", "value": "\u001cseparators are not white space\u001f"},
        {"type": "Passage", "id": "p4", "field": "text", "value": " \n\u2028 "},
    ]
    problems = []
    try:
        with tempfile.TemporaryDirectory() as scratch:
            work = Path(scratch)
            lines = []
            for row in rows:
                data = {row["field"]: row["value"]}
                entry = {"type": row["type"], "data": data}
                if "id" in row:
                    entry["id"] = row["id"]
                else:
                    data["slug"] = row["slug"]
                lines.append(json.dumps(entry))
            (work / "in.jsonl").write_text("\n".join(lines) + "\n")
            spec = {"dimension": contract["dimensions"], "types": {row["type"]: {"target": "embedding", "fields": [row["field"]]} for row in rows}}
            (work / "spec.json").write_text(json.dumps(spec))
            env = {
                "PATH": rehearsal.os.environ["PATH"],
                "HOME": str(work),
                "OPENAI_API_KEY": "contract",
                "OMNIGRAPH_EMBED_PROVIDER": "openai-compatible",
                "OMNIGRAPH_EMBED_BASE_URL": url,
                "OMNIGRAPH_EMBED_MODEL": contract["model"],
            }
            subprocess.run(
                ["omnigraph", "embed", "--input", str(work / "in.jsonl"), "--output", str(work / "out.jsonl"), "--spec", str(work / "spec.json")],
                env=env, check=True, capture_output=True, text=True,
            )
            expected = [embed_text(contract, row["type"], row["field"], row["value"]) for row in rows]
            if sorted(embedder.inputs) != sorted(expected):
                problems.append(f"omnigraph embed sends {embedder.inputs!r}; the contract's text_format builds {expected!r}")
            for line in filter(None, (work / "out.jsonl").read_text().split("\n")):
                vector = json.loads(line)["data"]["embedding"]
                if len(vector) != contract["dimensions"]:
                    problems.append(f"omnigraph embed stored {len(vector)} dimensions, the contract says {contract['dimensions']}")
                norm = math.sqrt(sum(value * value for value in vector))
                if contract["l2_normalized"] != (abs(norm - 1.0) < 1e-3):
                    problems.append(f"omnigraph embed stores vectors of norm {norm:.4f}; the contract says l2_normalized={contract['l2_normalized']}")
    finally:
        embedder.stop()
    return problems


def self_test(contract, inputs):
    cases = []

    def case(label, want_fail, mutate_contract=None, mutate_inputs=None, parity=False):
        mutated_contract = copy.deepcopy(contract)
        mutated_inputs = copy.deepcopy(inputs)
        if mutate_contract:
            mutate_contract(mutated_contract)
        if mutate_inputs:
            mutate_inputs(mutated_inputs)
        problems = parity_problems(mutated_contract) if parity else contract_problems(mutated_contract, mutated_inputs)
        ok = bool(problems) == want_fail
        cases.append(ok)
        print(f"{'ok' if ok else 'WRONG':<5} expect={'fail' if want_fail else 'pass'}  {label}")
        for problem in problems[:2]:
            print(f"        {problem[:200]}")

    case("unchanged contract", False)
    case("unchanged contract against the pinned CLI", False, parity=True)
    case("contract names another model", True, lambda c: c.update(model="bge-m3"))
    case("contract names other dimensions", True, lambda c: c.update(dimensions=1024))
    case("brain.pg embeds with another model", True, mutate_inputs=lambda i: i["schemas"].update({"brain.pg": i["schemas"]["brain.pg"].replace('model="granite-embedding-97m-multilingual-r2"', 'model="bge-m3"', 1)}))
    case("cluster.yaml provider serves another model", True, mutate_inputs=lambda i: i["cluster"]["providers"]["embedding"]["litellm"].update(model="bge-m3"))
    case("init container backfills with another model", True, mutate_inputs=lambda i: [e.update(value="bge-m3") for c in i["deployment"]["spec"]["template"]["spec"]["initContainers"] for e in c.get("env", []) if e["name"] == "OMNIGRAPH_EMBED_MODEL"])
    case("contract text format without the type prefix", True, lambda c: c.update(text_format="{value}"), parity=True)
    case("contract without trimming", True, lambda c: c.update(value_trim_characters=""), parity=True)
    case("contract trims like Python str.strip, separators included", True, lambda c: c.update(value_trim_characters=c["value_trim_characters"] + "\u001c\u001d\u001e\u001f"), parity=True)
    case("contract keeps an empty field line", True, lambda c: c.update(empty_value_format="type: {type}\ntext: "), parity=True)
    case("contract claims unnormalized vectors", True, lambda c: c.update(l2_normalized=False), parity=True)
    return all(cases)


def main():
    contract = json.loads(CONTRACT.read_text())
    inputs = inputs_from_disk()
    problems = contract_problems(contract, inputs) + parity_problems(contract)
    for problem in problems:
        print(f"FAIL  embedding contract: {problem}")
    if problems:
        return 1
    print(f"PASS  embedding contract: {contract['model']} x {contract['dimensions']}, text {contract['text_format']!r} with trimmed values and {contract['empty_value_format']!r} when empty matches brain.pg, cluster.yaml, the init container and the pinned omnigraph embed")
    if "--self-test" in sys.argv:
        return 0 if self_test(contract, inputs) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
