#!/usr/bin/env python3
import argparse
import datetime
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

EMBEDDED_FIELDS = {"Note": "content", "Passage": "text"}
BATCH_SIZE = 16
MAX_VALUE_CHARS = 8000
SIGNIFICANT_DIGITS = 8
HTTP_TIMEOUT_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 30
ESTIMATED_CHARS_PER_TOKEN = 4
MAIN_FILES = "load-*.ndjson"
HEAL_FILES = "heal-*.ndjson"
EMBED_PLAN = "embed-plan.json"
EMBED_REPORT = "embed-report.json"
METRIC_JOB = "omnigraph-embed-step"
WRITERS = frozenset({"vault-import", "forge-import"})
EXIT_OK = 0
EXIT_BAD_INPUT = 2


class EmbeddingUnavailable(Exception):
    pass


@dataclass
class Contract:
    model: str
    dimensions: int
    text_format: str
    trim: str
    normalised: bool

    @classmethod
    def load(cls, path):
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(raw["model"], int(raw["dimensions"]), raw["text_format"], raw["value_trim_characters"], bool(raw["l2_normalized"]))

    def text(self, type_name, value):
        trimmed = (value or "").strip(self.trim) if isinstance(value, str) else ""
        if not trimmed:
            return None
        return self.text_format.format(type=type_name, field=EMBEDDED_FIELDS[type_name], value=trimmed[:MAX_VALUE_CHARS].strip(self.trim))


@dataclass
class Counts:
    embedded: int = 0
    skipped: int = 0
    healed: int = 0
    heal_dropped: int = 0
    textless: int = 0
    tokens: int = 0
    batches: int = 0
    paced_seconds: float = 0.0

    def line(self):
        return " ".join(f"{key}={round(value, 1) if isinstance(value, float) else value}" for key, value in self.__dict__.items())


class Pacer:
    def __init__(self, tokens_per_second, clock=time.monotonic, sleep=time.sleep):
        self.rate = tokens_per_second
        self.clock = clock
        self.sleep = sleep
        self.started = clock()
        self.tokens = 0
        self.paused = 0.0

    def spend(self, tokens):
        self.tokens += tokens
        owed = self.tokens / self.rate - (self.clock() - self.started)
        if owed > 0:
            self.sleep(owed)
            self.paused += owed


class LiteLLMEmbedder:
    def __init__(self, url, key, contract, sleep=time.sleep):
        self.url = url.rstrip("/") + "/v1/embeddings"
        self.key = key
        self.contract = contract
        self.sleep = sleep

    def __call__(self, texts):
        body = json.dumps({"model": self.contract.model, "input": texts, "dimensions": self.contract.dimensions}).encode()
        for attempt in range(2):
            request = urllib.request.Request(self.url, data=body, method="POST",
                                             headers={"content-type": "application/json", "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                    payload = json.loads(response.read())
                break
            except urllib.error.HTTPError as error:
                retry_after = retry_after_seconds(error.headers.get("retry-after"))
                error.close()
                if error.code == 429 and attempt == 0 and retry_after is not None:
                    self.sleep(retry_after)
                    continue
                raise EmbeddingUnavailable(f"litellm answered HTTP {error.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                raise EmbeddingUnavailable(f"litellm not reachable ({type(error).__name__})") from None
        data = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in data]
        if len(vectors) != len(texts) or any(not isinstance(vector, list) or len(vector) != self.contract.dimensions for vector in vectors):
            raise EmbeddingUnavailable("litellm answered vectors of the wrong shape")
        usage = int((payload.get("usage") or {}).get("prompt_tokens") or 0)
        return vectors, usage or sum(len(text) for text in texts) // ESTIMATED_CHARS_PER_TOKEN


def retry_after_seconds(header):
    try:
        seconds = float(header)
    except (TypeError, ValueError):
        return None
    return seconds if 0 <= seconds <= MAX_RETRY_AFTER_SECONDS else None


def stored_vector(vector, normalise):
    if normalise:
        norm = math.sqrt(sum(value * value for value in vector))
        vector = [value / norm for value in vector] if norm > 0 else vector
    return [float(format(value, f".{SIGNIFICANT_DIGITS}g")) for value in vector]


def read_rows(path):
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.split("\n") if line.strip()]


def write_rows(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def embeddable(row):
    return row.get("type") in EMBEDDED_FIELDS and "embedding" not in (row.get("data") or {})


def row_key(row):
    data = row.get("data") or {}
    return f"{row['type']}|{row.get('id') or data.get('slug')}"


@dataclass
class Outcome:
    counts: Counts = field(default_factory=Counts)
    vectorless: list = field(default_factory=list)
    dropped: list = field(default_factory=list)
    reason: str | None = None


class EmbedStep:
    def __init__(self, contract, embedder, pacer, deadline_seconds, clock=time.monotonic):
        self.contract = contract
        self.embedder = embedder
        self.pacer = pacer
        self.deadline = clock() + deadline_seconds
        self.clock = clock
        self.outcome = Outcome()

    def available(self):
        if self.outcome.reason:
            return False
        if self.clock() >= self.deadline:
            self.outcome.reason = "deadline reached"
            return False
        return True

    def fill(self, rows):
        wanted = []
        for index, row in enumerate(rows):
            if not embeddable(row):
                continue
            text = self.contract.text(row["type"], row["data"].get(EMBEDDED_FIELDS[row["type"]]))
            if text is None:
                self.outcome.counts.textless += 1
                continue
            wanted.append((index, text))
        filled = set()
        for start in range(0, len(wanted), BATCH_SIZE):
            if not self.available():
                break
            batch = wanted[start:start + BATCH_SIZE]
            try:
                vectors, tokens = self.embedder([text for _, text in batch])
            except EmbeddingUnavailable as error:
                self.outcome.reason = str(error)
                break
            for (index, _), vector in zip(batch, vectors):
                rows[index]["data"]["embedding"] = stored_vector(vector, self.contract.normalised)
                filled.add(index)
            self.outcome.counts.tokens += tokens
            self.outcome.counts.batches += 1
            self.pacer.spend(tokens)
        return filled, [index for index, _ in wanted if index not in filled]

    def run_main(self, path):
        rows = read_rows(path)
        filled, missed = self.fill(rows)
        self.outcome.counts.embedded += len(filled)
        self.outcome.counts.skipped += len(missed)
        self.outcome.vectorless.extend(row_key(rows[index]) for index in missed)
        write_rows(path, rows)

    def run_heal(self, path):
        rows = read_rows(path)
        filled, _ = self.fill(rows)
        kept = [row for index, row in enumerate(rows) if index in filled]
        dropped = [row_key(row) for index, row in enumerate(rows) if index not in filled]
        self.outcome.counts.healed += len(kept)
        self.outcome.counts.heal_dropped += len(dropped)
        self.outcome.dropped.extend(dropped)
        if kept:
            write_rows(path, kept)
        else:
            path.unlink()


def iso_seconds(value):
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def summarise(plan, outcome, now):
    since = {}
    for item in plan.get("missing", []):
        since.setdefault(item["type"], []).append(iso_seconds(item["since"]))
    heal_since = plan.get("heal_since", {})
    for key in outcome.dropped:
        since.setdefault(key.split("|", 1)[0], []).append(iso_seconds(heal_since.get(key)) or now)
    for key in outcome.vectorless:
        since.setdefault(key.split("|", 1)[0], []).append(now)
    missing, oldest = {}, {}
    for type_name in EMBEDDED_FIELDS:
        stamps = [stamp for stamp in since.get(type_name, []) if stamp is not None]
        missing[type_name] = len(since.get(type_name, []))
        oldest[type_name] = round(max(now - min(stamps), 0.0), 3) if stamps else 0.0
    return {"writer": plan["writer"], "missing": missing, "oldest_missing_seconds": oldest,
            "counts": outcome.counts.__dict__, "reason": outcome.reason, "finished_at": now}


def embed(args, embedder=None, pacer=None, clock=time.monotonic):
    plan_dir = Path(args.plan)
    plan_file = plan_dir / EMBED_PLAN
    if not plan_file.exists():
        raise SystemExit(f"embed step refused: {plan_file} is missing; the planner did not finish")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if plan.get("writer") not in WRITERS:
        raise SystemExit("embed step refused: embed-plan.json names no known writer")
    contract = Contract.load(args.contract)
    if embedder is None:
        key = Path(args.key_file).read_text(encoding="utf-8").strip() if Path(args.key_file).exists() else ""
        embedder = LiteLLMEmbedder(args.litellm_url, key, contract)
    pacer = pacer or Pacer(args.tokens_per_second, clock=clock)
    step = EmbedStep(contract, embedder, pacer, args.deadline_seconds, clock=clock)
    for path in sorted(plan_dir.glob(MAIN_FILES)):
        step.run_main(path)
    for path in sorted(plan_dir.glob(HEAL_FILES)):
        step.run_heal(path)
    step.outcome.counts.paced_seconds = pacer.paused
    report = summarise(plan, step.outcome, time.time())
    (plan_dir / EMBED_REPORT).write_text(json.dumps(report), encoding="utf-8")
    return report


def metric_lines(report):
    writer = report["writer"]
    lines = []
    for type_name in EMBEDDED_FIELDS:
        labels = f'type="{type_name}",writer="{writer}"'
        lines.append(f"omnigraph_embed_rows_missing{{{labels}}} {report['missing'][type_name]}")
        lines.append(f"omnigraph_embed_oldest_missing_age_seconds{{{labels}}} {report['oldest_missing_seconds'][type_name]}")
    counts = report["counts"]
    for outcome in ("embedded", "skipped", "healed", "heal_dropped", "textless"):
        lines.append(f'omnigraph_embed_run_rows{{outcome="{outcome}",writer="{writer}"}} {counts[outcome]}')
    lines.append(f'omnigraph_embed_run_tokens{{writer="{writer}"}} {counts["tokens"]}')
    lines.append(f'omnigraph_embed_run_paced_seconds{{writer="{writer}"}} {counts["paced_seconds"]}')
    lines.append(f'omnigraph_embed_last_report_timestamp_seconds{{writer="{writer}"}} {int(report["finished_at"])}')
    return "\n".join(lines) + "\n"


def report(args, opener=urllib.request.urlopen):
    path = Path(args.plan) / EMBED_REPORT
    if not path.exists():
        print("embed report skipped: no embed-report.json; the embed step did not run", file=sys.stderr)
        return EXIT_OK
    summary = json.loads(path.read_text(encoding="utf-8"))
    url = args.vmagent_url.rstrip("/") + f"/api/v1/import/prometheus?extra_label=job={METRIC_JOB}"
    request = urllib.request.Request(url, data=metric_lines(summary).encode(), method="POST", headers={"content-type": "text/plain"})
    try:
        with opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"embed report not pushed: vmagent not reachable ({type(error).__name__}); the import itself succeeded", file=sys.stderr)
        return EXIT_OK
    if status >= 300:
        print(f"embed report not pushed: vmagent answered HTTP {status}; the import itself succeeded", file=sys.stderr)
        return EXIT_OK
    missing = " ".join(f"missing_{type_name.lower()}={count}" for type_name, count in summary["missing"].items())
    print(f"embed report pushed: writer={summary['writer']} {missing}")
    return EXIT_OK


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Fill Omnigraph Note and Passage vectors in a writer's plan before it is loaded, and report what is still vectorless.")
    commands = parser.add_subparsers(dest="command", required=True)
    fill = commands.add_parser("embed")
    fill.add_argument("--plan", required=True)
    fill.add_argument("--contract", required=True)
    fill.add_argument("--litellm-url", required=True)
    fill.add_argument("--key-file", required=True)
    fill.add_argument("--tokens-per-second", type=float, default=300.0)
    fill.add_argument("--deadline-seconds", type=float, required=True)
    push = commands.add_parser("report")
    push.add_argument("--plan", required=True)
    push.add_argument("--vmagent-url", required=True)
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    if args.command == "report":
        return report(args)
    summary = embed(args)
    counts = summary["counts"]
    missing = " ".join(f"missing_{type_name.lower()}={count}" for type_name, count in summary["missing"].items())
    print(f"embed step: writer={summary['writer']} " + " ".join(f"{key}={value}" for key, value in counts.items()) + f" {missing}")
    if summary["reason"] and counts["skipped"] + counts["heal_dropped"]:
        print(f"embedding skipped: {counts['skipped']} rows written without a vector and {counts['heal_dropped']} heals deferred ({summary['reason']})", file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
