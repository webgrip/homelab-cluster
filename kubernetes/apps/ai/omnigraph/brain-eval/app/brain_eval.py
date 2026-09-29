#!/usr/bin/env python3
import argparse
import datetime
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HARNESS_VERSION = "1"
CATEGORY_QUOTA = {
    "docs-en": 6,
    "notes-nl": 6,
    "notes-en": 4,
    "cross-lingual": 4,
    "about": 6,
    "connect": 4,
    "temporal": 3,
    "unanswerable": 3,
}
CATEGORIES = tuple(CATEGORY_QUOTA)
SPLITS = ("dev", "holdout")
LANGUAGES = ("nl", "en")
ORIGINS = ("drafted", "ryan", "synthetic")
TEMPORAL_KINDS = ("recent_notes", "recent_docs", "open_threads")
RETRIEVAL_METRICS = ("recall_at_5", "recall_at_8", "hit_at_1", "mrr_at_8", "ndcg_at_8", "candidate_recall_at_40")
ANSWER_METRICS = ("key_fact_recall", "faithfulness", "citation_precision", "abstention_accuracy", "tool_error_rate", "tool_calls", "usd_per_answer", "latency_seconds")
TOOL_METRICS = ("about_top1", "connect_path_found")
PROFILES = ("p0", "p1", "p2", "p3", "b0", "tools", "e1-raw", "e1-prefixed")
MODES = ("retrieval", "answer", "gate", "experiment", "candidates", "calibration")
LATENCY_STAGES = ("leg", "case", "answer", "judge")
QUANTILES = ("0.5", "0.95")
VECTOR_TYPES = ("Note", "Passage", "Topic")
SYNTHETIC_CATEGORY = "synthetic"
TOOL_OUTPUT_LIMIT = 12000
MAX_TOOL_TURNS = 6
CANDIDATE_POOL_DEPTH = 40
SENTINEL_PHRASE = "quillfeather sentinel 7c1e"
DUTCH_STOPWORDS = frozenset("de het een en van in is dat op te zijn voor met niet aan er maar om ook als dan bij nog wat hoe wie waar waarom welke heb heeft ik mijn je jij we wij ze zij hun over naar uit door kan moet".split())
ENGLISH_STOPWORDS = frozenset("the a an and of in is that on to be for with not at there but also as then by what how who where why which have has i my you we they their about from out through can must do does did".split())
CASE_KEY_ORDER = ("id", "split", "category", "language", "provisional", "origin", "answerable", "question", "expected", "key_facts", "temporal", "entities", "beyond_first_1024_tokens", "notes")
METRIC_LABELS = {
    "brain_eval_score": {"metric": set(RETRIEVAL_METRICS + ANSWER_METRICS + TOOL_METRICS), "profile": set(PROFILES), "category": set(CATEGORIES) | {"all"}, "split": set(SPLITS) | {"all"}, "mode": {"retrieval", "answer", "experiment"}},
    "brain_eval_cost_usd": {"mode": set(MODES)},
    "brain_eval_latency_seconds": {"stage": set(LATENCY_STAGES), "quantile": set(QUANTILES), "profile": set(PROFILES)},
    "brain_eval_payload_chars": {"profile": set(PROFILES), "quantile": set(QUANTILES)},
    "brain_eval_missing_vectors_ratio": {"type": set(VECTOR_TYPES)},
    "brain_eval_stale_cases": {},
    "brain_eval_scored_cases": {"mode": set(MODES), "profile": set(PROFILES)},
    "brain_eval_cases": {"split": set(SPLITS), "state": {"provisional", "curated"}},
    "brain_eval_set_provisional": {},
    "brain_eval_calibration_grades": {},
    "brain_eval_judge_control_ok": {},
    "brain_eval_judge_agreement": {},
    "brain_eval_run_valid": {"mode": set(MODES)},
    "brain_eval_store_provisional": {},
    "brain_eval_public_repo_leaks": {},
    "brain_eval_last_success_timestamp_seconds": {"mode": set(MODES)},
}


class EvalError(Exception):
    pass


class CaseFormatError(EvalError):
    pass


class SpendCapReached(EvalError):
    pass


class UpstreamError(EvalError):
    def __init__(self, service, status, code=""):
        super().__init__(f"{service} answered HTTP {status}{' ' + code if code else ''}")
        self.service = service
        self.status = status
        self.code = code


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, sort_keys=True), flush=True)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_graph_time(text):
    if text is None:
        return None
    value = str(text).strip()
    if len(value) == 10:
        value += "T00:00:00"
    value = value.replace("Z", "")
    if "+" in value[10:]:
        value = value[: value.index("+", 10)]
    return datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.timezone.utc)


def json_string(value):
    return json.dumps(value, ensure_ascii=False)


def yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json_string(str(value))


def dump_case(case):
    lines = []
    for key in CASE_KEY_ORDER:
        if key not in case:
            continue
        value = case[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            lines.append(f"{key}:")
            for item in value:
                if isinstance(item, dict):
                    for index, (item_key, item_value) in enumerate(item.items()):
                        lines.append(f"{'  - ' if index == 0 else '    '}{item_key}: {yaml_scalar(item_value)}")
                else:
                    lines.append(f"  - {yaml_scalar(item)}")
        elif isinstance(value, dict):
            if not value:
                lines.append(f"{key}: {{}}")
                continue
            lines.append(f"{key}:")
            for item_key, item_value in value.items():
                lines.append(f"  {item_key}: {yaml_scalar(item_value)}")
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    return "\n".join(lines) + "\n"


def strip_plain_comment(raw):
    match = re.search(r"\s#", raw)
    return raw[: match.start()] if match else raw


def split_flow_items(body, where):
    items, current, quote = [], "", None
    index = 0
    while index < len(body):
        char = body[index]
        if quote:
            current += char
            if char == "\\" and quote == '"' and index + 1 < len(body):
                current += body[index + 1]
                index += 1
            elif char == quote:
                if quote == "'" and body[index + 1: index + 2] == "'":
                    current += "'"
                    index += 1
                else:
                    quote = None
        elif char in "\"'":
            quote = char
            current += char
        elif char == ",":
            items.append(current)
            current = ""
        elif char in "[]{}":
            raise CaseFormatError(f"{where}: nested flow collections are not supported")
        else:
            current += char
        index += 1
    if quote:
        raise CaseFormatError(f"{where}: unterminated quote")
    if current.strip():
        items.append(current)
    return [parse_scalar(item, where) for item in items]


def parse_scalar(raw, where):
    text = raw.strip()
    if text == "" or text.startswith("#"):
        return None
    if text.startswith('"'):
        try:
            value, end = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError as error:
            raise CaseFormatError(f"{where}: bad double-quoted string ({error.msg})") from None
        rest = text[end:].strip()
        if rest and not rest.startswith("#"):
            raise CaseFormatError(f"{where}: text after a quoted string")
        return value
    if text.startswith("'"):
        value, index = "", 1
        while index < len(text):
            if text[index] == "'":
                if text[index + 1: index + 2] == "'":
                    value += "'"
                    index += 2
                    continue
                rest = text[index + 1:].strip()
                if rest and not rest.startswith("#"):
                    raise CaseFormatError(f"{where}: text after a quoted string")
                return value
            value += text[index]
            index += 1
        raise CaseFormatError(f"{where}: unterminated single-quoted string")
    text = strip_plain_comment(text).strip()
    if text.startswith("[") and text.endswith("]"):
        return split_flow_items(text[1:-1], where)
    if text == "{}":
        return {}
    if text.startswith("{") or text.startswith("&") or text.startswith("*") or text.startswith("!"):
        raise CaseFormatError(f"{where}: anchors, tags and flow mappings are not supported")
    if text in ("null", "~", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[-+]?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"[-+]?[0-9]*\.[0-9]+([eE][-+]?[0-9]+)?", text):
        return float(text)
    return text


def indent_of(line):
    return len(line) - len(line.lstrip(" "))


def meaningful(line):
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


KEY_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):(?:\s+(?P<value>.*))?$")


def read_block_scalar(lines, start, parent_indent, style, where):
    collected = []
    index = start
    block_indent = None
    while index < len(lines):
        line = lines[index]
        if line.strip() == "":
            collected.append("")
            index += 1
            continue
        current = indent_of(line)
        if current <= parent_indent:
            break
        if block_indent is None:
            block_indent = current
        if current < block_indent:
            raise CaseFormatError(f"{where}: a block scalar line is indented less than its first line")
        collected.append(line[block_indent:])
        index += 1
    while collected and collected[-1] == "":
        collected.pop()
    chomp = style.endswith("-")
    if style.startswith(">"):
        text = ""
        for line in collected:
            if line == "":
                text += "\n"
            elif text and not text.endswith("\n"):
                text += " " + line
            else:
                text += line
    else:
        text = "\n".join(collected)
    return (text if chomp else text + "\n"), index


def read_nested(lines, start, parent_indent, where):
    index = start
    while index < len(lines) and not meaningful(lines[index]):
        index += 1
    if index >= len(lines) or indent_of(lines[index]) <= parent_indent:
        return None, index
    child_indent = indent_of(lines[index])
    if lines[index].strip().startswith("- ") or lines[index].strip() == "-":
        items = []
        while index < len(lines):
            line = lines[index]
            if not meaningful(line):
                index += 1
                continue
            current = indent_of(line)
            if current < child_indent:
                break
            if current != child_indent or not (line.strip().startswith("- ") or line.strip() == "-"):
                raise CaseFormatError(f"{where} line {index + 1}: unexpected indentation in a list")
            body = line.strip()[2:]
            match = KEY_LINE.match(body)
            if match and not body.startswith(('"', "'")):
                item = {match.group("key"): parse_scalar(match.group("value") or "", f"{where} line {index + 1}")}
                index += 1
                item_indent = child_indent + 2
                while index < len(lines):
                    follow = lines[index]
                    if not meaningful(follow):
                        index += 1
                        continue
                    if indent_of(follow) != item_indent or follow.strip().startswith("- "):
                        break
                    follow_match = KEY_LINE.match(follow.strip())
                    if not follow_match:
                        raise CaseFormatError(f"{where} line {index + 1}: expected key: value inside a list item")
                    item[follow_match.group("key")] = parse_scalar(follow_match.group("value") or "", f"{where} line {index + 1}")
                    index += 1
                items.append(item)
            else:
                items.append(parse_scalar(body, f"{where} line {index + 1}"))
                index += 1
        return items, index
    mapping = {}
    while index < len(lines):
        line = lines[index]
        if not meaningful(line):
            index += 1
            continue
        current = indent_of(line)
        if current < child_indent:
            break
        if current != child_indent:
            raise CaseFormatError(f"{where} line {index + 1}: unexpected indentation in a mapping")
        match = KEY_LINE.match(line.strip())
        if not match:
            raise CaseFormatError(f"{where} line {index + 1}: expected key: value")
        mapping[match.group("key")] = parse_scalar(match.group("value") or "", f"{where} line {index + 1}")
        index += 1
    return mapping, index


def load_case(text, where="case"):
    lines = text.replace("\r\n", "\n").split("\n")
    case = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not meaningful(line) or line.strip() == "---":
            index += 1
            continue
        if indent_of(line):
            raise CaseFormatError(f"{where} line {index + 1}: unexpected indentation at the top level")
        match = KEY_LINE.match(line.rstrip())
        if not match:
            raise CaseFormatError(f"{where} line {index + 1}: expected key: value")
        key, value = match.group("key"), match.group("value")
        if key in case:
            raise CaseFormatError(f"{where} line {index + 1}: duplicate key {key}")
        stripped_value = strip_plain_comment(value or "").strip()
        if stripped_value in ("|", "|-", ">", ">-"):
            case[key], index = read_block_scalar(lines, index + 1, 0, stripped_value, f"{where} line {index + 1}")
            continue
        if value is None or stripped_value == "":
            nested, index = read_nested(lines, index + 1, 0, where)
            case[key] = nested
            continue
        case[key] = parse_scalar(value, f"{where} line {index + 1}")
        index += 1
    return case


def validate_case(case, where):
    problems = []
    for key in ("id", "split", "category", "language", "answerable", "question"):
        if case.get(key) in (None, ""):
            problems.append(f"missing {key}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,31}", str(case.get("id", ""))):
        problems.append("id must be 1-32 lowercase letters, digits or dashes")
    if case.get("split") not in SPLITS:
        problems.append(f"split must be one of {', '.join(SPLITS)}")
    if case.get("category") not in CATEGORIES + (SYNTHETIC_CATEGORY,):
        problems.append(f"category must be one of {', '.join(CATEGORIES)}")
    if case.get("language") not in LANGUAGES:
        problems.append("language must be nl or en")
    if not isinstance(case.get("answerable"), bool):
        problems.append("answerable must be true or false")
    if case.get("origin", "drafted") not in ORIGINS:
        problems.append(f"origin must be one of {', '.join(ORIGINS)}")
    expected = case.get("expected") or []
    if not isinstance(expected, list):
        problems.append("expected must be a list")
        expected = []
    for item in expected:
        if not isinstance(item, dict) or not isinstance(item.get("slug"), str) or item.get("grade") not in (1, 2):
            problems.append("every expected item needs a slug and a grade of 1 or 2")
            break
    facts = case.get("key_facts") or []
    if not isinstance(facts, list) or not all(isinstance(fact, str) and fact.strip() for fact in facts):
        problems.append("key_facts must be a list of text")
    temporal = case.get("temporal")
    if temporal is not None:
        if not isinstance(temporal, dict) or temporal.get("kind") not in TEMPORAL_KINDS or not isinstance(temporal.get("days"), int) or temporal["days"] < 1:
            problems.append(f"temporal needs a kind of {', '.join(TEMPORAL_KINDS)} and whole days")
    if case.get("answerable") is True and not expected and temporal is None:
        problems.append("an answerable case needs expected documents or a temporal expectation")
    if case.get("answerable") is True and not facts and temporal is None:
        problems.append("an answerable case needs 1 to 4 key facts")
    if len(facts) > 4:
        problems.append("at most 4 key facts")
    if case.get("answerable") is False and expected:
        problems.append("an unanswerable case expects no documents")
    if problems:
        raise CaseFormatError(f"{where}: " + "; ".join(problems))
    return case


def load_cases(cases_dir):
    cases = []
    seen = set()
    for path in sorted(Path(cases_dir).glob("*.yaml")):
        case = validate_case(load_case(path.read_text(encoding="utf-8"), path.name), path.name)
        if case["id"] in seen:
            raise CaseFormatError(f"{path.name}: duplicate case id {case['id']}")
        seen.add(case["id"])
        case.setdefault("provisional", False)
        case.setdefault("origin", "drafted")
        cases.append(case)
    return cases


def synthetic_cases():
    runbook = "forge/webgrip/homelab-cluster/doc/docs/techdocs/docs/runbooks/omnigraph"
    return [
        {
            "id": "syn-schema-branches", "split": "dev", "category": SYNTHETIC_CATEGORY, "language": "en", "origin": "synthetic", "answerable": True,
            "question": "According to the Omnigraph runbook, why must open branches be drained before a schema change is pushed?",
            "expected": [{"slug": runbook, "grade": 2}],
            "key_facts": ["cluster apply refuses a schema change while a graph has a branch other than main", "the init container then stops every graph"],
        },
        {
            "id": "syn-merge-actor", "split": "dev", "category": SYNTHETIC_CATEGORY, "language": "en", "origin": "synthetic", "answerable": True,
            "question": "Which Omnigraph actors may merge branches into main on the brain graph?",
            "expected": [{"slug": runbook, "grade": 2}],
            "key_facts": ["act-ryan may merge", "act-review may merge"],
        },
        {
            "id": "syn-sentinel", "split": "dev", "category": SYNTHETIC_CATEGORY, "language": "en", "origin": "synthetic", "answerable": False,
            "question": f"What did the {SENTINEL_PHRASE} say about the zebra kite?",
            "expected": [],
            "key_facts": [f"the {SENTINEL_PHRASE} is not in the brain"],
        },
    ]


CONTROL_CASE = {
    "question": "Which port does the synthetic widget service listen on?",
    "answerable": True,
    "key_facts": ["the widget service listens on port 7431"],
    "tool_outputs": "search result 1: [doc:synthetic-widget-runbook#0] Synthetic widget runbook. The widget service listens on port 7431 and is written in Go. Restart it with the widget-restart job.",
}
CONTROL_ANSWERS = {
    "supported": "The widget service listens on port 7431 [doc:synthetic-widget-runbook#0].",
    "unsupported": "The widget service listens on port 9000 and is written in Rust [doc:synthetic-widget-runbook#0].",
}


def language_of(text):
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    dutch = sum(word in DUTCH_STOPWORDS for word in words)
    english = sum(word in ENGLISH_STOPWORDS for word in words)
    return "nl" if dutch > english else "en"


def ngrams(text, size=5):
    words = re.findall(r"\w+", unicodedata.normalize("NFKC", text).lower())
    return {tuple(words[index: index + size]) for index in range(len(words) - size + 1)}


def shares_ngram(candidate, source, size=5):
    return bool(ngrams(candidate, size) & ngrams(source, size))


class Equivalence:
    def __init__(self, note_to_artifact):
        self.note_to_artifact = dict(note_to_artifact)
        self.artifact_to_note = {artifact: note for note, artifact in self.note_to_artifact.items()}

    def canonical(self, slug):
        if slug.startswith("obsidian-file/"):
            return self.artifact_to_note.get(slug, "obsidian/" + slug[len("obsidian-file/"):])
        artifact = self.note_to_artifact.get(slug)
        if artifact is None or artifact.startswith("obsidian-file/"):
            return slug
        return artifact

    def canonical_ranking(self, slugs):
        ranked, seen = [], set()
        for slug in slugs:
            doc = self.canonical(slug)
            if doc not in seen:
                seen.add(doc)
                ranked.append(doc)
        return ranked

    def canonical_expectation(self, expected):
        grades = {}
        for item in expected:
            doc = self.canonical(item["slug"])
            grades[doc] = max(grades.get(doc, 0), int(item["grade"]))
        return grades


def recall_at(ranked, relevant, k):
    if not relevant:
        return None
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def hit_at_1(ranked, relevant):
    if not relevant:
        return None
    return 1.0 if ranked[:1] and ranked[0] in relevant else 0.0


def mrr_at(ranked, relevant, k):
    if not relevant:
        return None
    for position, doc in enumerate(ranked[:k], start=1):
        if doc in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at(ranked, grades, k):
    if not grades:
        return None
    dcg = sum((2 ** grades.get(doc, 0) - 1) / math.log2(position + 1) for position, doc in enumerate(ranked[:k], start=1))
    ideal = sorted(grades.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(position + 1) for position, grade in enumerate(ideal, start=1))
    return dcg / idcg if idcg else None


def retrieval_scores(ranked, grades):
    relevant = {doc for doc, grade in grades.items() if grade >= 1}
    return {
        "recall_at_5": recall_at(ranked, relevant, 5),
        "recall_at_8": recall_at(ranked, relevant, 8),
        "hit_at_1": hit_at_1(ranked, relevant),
        "mrr_at_8": mrr_at(ranked, relevant, 8),
        "ndcg_at_8": ndcg_at(ranked, grades, 8),
        "candidate_recall_at_40": recall_at(ranked, relevant, CANDIDATE_POOL_DEPTH),
    }


def quantile(values, q):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def mean_or_none(values):
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def aggregate(case_results, metrics):
    table = {}
    for split in SPLITS + ("all",):
        for category in CATEGORIES + ("all",):
            chosen = [result for result in case_results
                      if (split == "all" or result["split"] == split) and (category == "all" or result["category"] == category)]
            if not chosen:
                continue
            row = {}
            for metric in metrics:
                value = mean_or_none([result["metrics"].get(metric) for result in chosen])
                if value is not None:
                    row[metric] = round(value, 6)
            if row:
                row["cases"] = len(chosen)
                table[f"{category}|{split}"] = row
    return table


def is_retrieval_scorable(case):
    return case["category"] != "unanswerable" and case.get("answerable", True)


class Spend:
    def __init__(self, cap_usd):
        self.cap = cap_usd
        self.total = 0.0
        self.calls = 0

    def add(self, cost):
        self.calls += 1
        self.total += cost
        if self.cap is not None and self.total > self.cap:
            raise SpendCapReached(f"spend {self.total:.4f} USD passed the cap of {self.cap:.2f} USD after {self.calls} calls")


def http_json(url, *, method="POST", payload=None, headers=None, timeout=60, service="upstream"):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        body = error.read()
        code = ""
        try:
            parsed = json.loads(body)
            code = str(parsed.get("code") or (parsed.get("error") or {}).get("type") or "") if isinstance(parsed, dict) else ""
        except (json.JSONDecodeError, AttributeError):
            pass
        raise UpstreamError(service, error.code, code) from None
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
        raise UpstreamError(service, 0, type(error).__name__) from None


class Omnigraph:
    def __init__(self, base, graph, token, timeout=60):
        self.base = base.rstrip("/")
        self.graph = graph
        self.token = token
        self.timeout = timeout
        self.calls = []

    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def post(self, path, payload, retries=2):
        for attempt in range(retries + 1):
            try:
                started = time.monotonic()
                _, _, body = http_json(f"{self.base}/graphs/{self.graph}/{path}", payload=payload, headers=self.headers(), timeout=self.timeout, service="omnigraph")
                self.calls.append(time.monotonic() - started)
                return json.loads(body)
            except UpstreamError as error:
                if error.status in (0, 502, 503, 504) and attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise

    def stored(self, name, params, snapshot):
        started = time.monotonic()
        payload = {"params": params}
        if snapshot:
            payload["snapshot"] = snapshot
        result = self.post(f"queries/{urllib.request.quote(name)}", payload)
        return result.get("rows") or [], time.monotonic() - started

    def inline(self, source, params=None, snapshot=None):
        payload = {"query": source, "params": params or {}}
        if snapshot:
            payload["snapshot"] = snapshot
        return self.post("query", payload)

    def head(self):
        result = self.inline("query head() {\n  match {\n    $p: Project\n  }\n  return { $p.slug }\n  limit 1\n}")
        commit = result.get("graph_commit_id")
        if not commit:
            raise EvalError("omnigraph returned no graph_commit_id for the head read")
        return commit

    def commit_time(self, commit_id):
        _, _, body = http_json(f"{self.base}/graphs/{self.graph}/commits/{commit_id}", method="GET", headers=self.headers(), timeout=self.timeout, service="omnigraph")
        created = json.loads(body).get("created_at")
        return datetime.datetime.fromtimestamp(created / 1_000_000, tz=datetime.timezone.utc)

    def stored_catalog(self):
        _, _, body = http_json(f"{self.base}/graphs/{self.graph}/queries", method="GET", headers=self.headers(), timeout=self.timeout, service="omnigraph")
        return {query["name"] for query in json.loads(body).get("queries", [])}

    def export_rows(self, type_names):
        request = urllib.request.Request(f"{self.base}/graphs/{self.graph}/export", data=json.dumps({"type_names": list(type_names)}).encode(),
                                         method="POST", headers={"content-type": "application/json", **self.headers()})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                buffer = b""
                while True:
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    buffer += chunk
                    parts = buffer.split(b"\n")
                    buffer = parts.pop()
                    for part in parts:
                        if part.strip():
                            yield json.loads(part)
                if buffer.strip():
                    yield json.loads(buffer)
        except urllib.error.HTTPError as error:
            raise UpstreamError("omnigraph", error.code) from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
            raise UpstreamError("omnigraph", 0, type(error).__name__) from None


SLUG_TYPES = ("Note", "Artifact", "Topic", "Person", "Project", "Organization")


def scan_source(type_name, columns):
    variable = "$x"
    returned = ", ".join(f"{variable}.{column}" for column in columns)
    return f"query scan() {{\n  match {{\n    {variable}: {type_name}\n  }}\n  return {{ {returned} }}\n}}"


NOTE_ARTIFACT_SOURCE = "query note_artifacts() {\n  match {\n    $n: Note\n    $n noteFromArtifact $a\n  }\n  return { $n.slug, $a.slug }\n}"
ARTIFACT_PROJECT_SOURCE = "query artifact_projects() {\n  match {\n    $a: Artifact\n    $a artifactForProject $p\n  }\n  return { $a.slug, $p.slug }\n}"
ARTIFACT_AUTHOR_SOURCE = "query artifact_authors() {\n  match {\n    $a: Artifact\n    $a artifactFromPerson $u\n  }\n  return { $a.slug, $u.slug }\n}"


class Catalog:
    def __init__(self, slugs, equivalence):
        self.slugs = slugs
        self.equivalence = equivalence
        self.all = set().union(*slugs.values()) if slugs else set()

    @classmethod
    def read(cls, omnigraph, snapshot):
        slugs = {}
        for type_name in SLUG_TYPES:
            rows = omnigraph.inline(scan_source(type_name, ["slug"]), snapshot=snapshot).get("rows") or []
            slugs[type_name] = {row["x.slug"] for row in rows}
        pairs = omnigraph.inline(NOTE_ARTIFACT_SOURCE, snapshot=snapshot).get("rows") or []
        return cls(slugs, Equivalence({row["n.slug"]: row["a.slug"] for row in pairs}))

    def missing(self, case):
        return [item["slug"] for item in case.get("expected") or [] if item["slug"] not in self.all]


def open_state(content):
    for line in (content or "").split("\n")[:12]:
        if line.strip().lower().startswith("state:"):
            return line.split(":", 1)[1].strip().lower() == "open"
    return False


DEPENDENCY_TITLE = re.compile(r"(chore\(deps\)|fix\(deps\)|update (dependency|module|image|helm release|docker tag)|lock file maintenance|\brenovate\b)", re.I)
BOT_LOGIN = re.compile(r"(renovate|dependabot|bot$|\[bot\]|-ci$|^webgrip-ci)", re.I)


def temporal_expectation(case, scans, now):
    spec = case["temporal"]
    since = now - datetime.timedelta(days=int(spec["days"]))
    grades = {}
    if spec["kind"] == "recent_notes":
        for row in scans["notes"]:
            slug = row["x.slug"]
            if slug.startswith(("derived/", "forge/")):
                continue
            updated = parse_graph_time(row.get("x.updatedAt"))
            if updated and since <= updated <= now:
                grades[slug] = 1
    elif spec["kind"] == "recent_docs":
        for row in scans["artifacts"]:
            slug = row["x.slug"]
            if slug.startswith("obsidian-file/") or row.get("x.kind") != "document":
                continue
            stamp = parse_graph_time(row.get("x.timestamp"))
            if stamp and since <= stamp <= now:
                grades[slug] = 1
    else:
        project = spec.get("project")
        in_project = {pair["a.slug"] for pair in scans["artifact_projects"] if pair["p.slug"] == project} if project else None
        bots = {pair["a.slug"] for pair in scans["artifact_authors"] if BOT_LOGIN.search(pair["u.slug"].rsplit("/", 1)[-1])}
        for row in scans["artifacts"]:
            slug = row["x.slug"]
            if row.get("x.kind") != "post" or not open_state(row.get("x.content")):
                continue
            if in_project is not None and slug not in in_project:
                continue
            if not spec.get("include_dependency_updates") and (slug in bots or DEPENDENCY_TITLE.search(row.get("x.name") or "")):
                continue
            stamp = parse_graph_time(row.get("x.timestamp"))
            if stamp and since <= stamp <= now:
                grades[slug] = 1
    return grades


def temporal_scans(omnigraph, snapshot, kinds):
    scans = {"notes": [], "artifacts": [], "artifact_projects": [], "artifact_authors": []}
    if "recent_notes" in kinds:
        scans["notes"] = omnigraph.inline(scan_source("Note", ["slug", "updatedAt"]), snapshot=snapshot).get("rows") or []
    if kinds & {"recent_docs", "open_threads"}:
        columns = ["slug", "kind", "timestamp", "name"] + (["content"] if "open_threads" in kinds else [])
        scans["artifacts"] = omnigraph.inline(scan_source("Artifact", columns), snapshot=snapshot).get("rows") or []
    if "open_threads" in kinds:
        scans["artifact_projects"] = omnigraph.inline(ARTIFACT_PROJECT_SOURCE, snapshot=snapshot).get("rows") or []
        scans["artifact_authors"] = omnigraph.inline(ARTIFACT_AUTHOR_SOURCE, snapshot=snapshot).get("rows") or []
    return scans


@dataclass
class Retrieved:
    ranked: list
    payload_chars: int
    leg_seconds: list = field(default_factory=list)


def interleave(*ranked_lists):
    merged = []
    for position in range(max((len(items) for items in ranked_lists), default=0)):
        for items in ranked_lists:
            if position < len(items):
                merged.append(items[position])
    return merged


def profile_p0(omnigraph, question, snapshot):
    notes, note_seconds = omnigraph.stored("recall_notes", {"q": question}, snapshot)
    passages, passage_seconds = omnigraph.stored("recall_passages", {"q": question}, snapshot)
    topics, topic_seconds = omnigraph.stored("recall_topics", {"q": question}, snapshot)
    ranked = interleave([row["n.slug"] for row in notes], [row["a.slug"] for row in passages], [row["t.slug"] for row in topics])
    payload = len(json.dumps(notes, ensure_ascii=False)) + len(json.dumps(passages, ensure_ascii=False)) + len(json.dumps(topics, ensure_ascii=False))
    return Retrieved(ranked, payload, [note_seconds, passage_seconds, topic_seconds])


PROFILE_RUNNERS = {"p0": profile_p0}
P0_QUERIES = ("recall_notes", "recall_passages", "recall_topics")


LEAK_SHINGLE_WORDS = 8
LEAK_MIN_PHRASE_WORDS = 5
LEAK_MAX_FILE_BYTES = 2 * 1024 * 1024


def normalised_words(text):
    return re.findall(r"\w+", unicodedata.normalize("NFKC", str(text or "")).lower())


def leak_shingles(text):
    words = normalised_words(text)
    if len(words) >= LEAK_SHINGLE_WORDS:
        return {" ".join(words[index: index + LEAK_SHINGLE_WORDS]) for index in range(len(words) - LEAK_SHINGLE_WORDS + 1)}
    if len(words) >= LEAK_MIN_PHRASE_WORDS:
        return {" ".join(words)}
    return set()


def public_repo_leaks(cases, public_dir):
    owners = {}
    for case in cases:
        if case.get("category") in ("temporal", SYNTHETIC_CATEGORY) or case.get("origin") == "synthetic":
            continue
        for shingle in leak_shingles(case.get("question")):
            owners.setdefault(shingle, set()).add(case["id"])
    lengths = {len(shingle.split(" ")) for shingle in owners}
    leaked, files = set(), 0
    for path in Path(public_dir).rglob("*"):
        if ".git" in path.parts or not path.is_file() or path.stat().st_size > LEAK_MAX_FILE_BYTES:
            continue
        files += 1
        words = normalised_words(path.read_bytes().decode("utf-8", errors="ignore"))
        for size in lengths:
            for index in range(len(words) - size + 1):
                owner = owners.get(" ".join(words[index: index + size]))
                if owner:
                    leaked |= owner
    return len(leaked), len(owners), files


VECTOR_PROBE = [1.0] + [0.0] * 383


def count_source(type_name):
    return f"query total() {{\n  match {{\n    $x: {type_name}\n  }}\n  return {{ count($x) as n }}\n}}"


def vector_ids_source(type_name):
    return f"query with_vectors($v: Vector(384)) {{\n  match {{\n    $x: {type_name}\n  }}\n  return {{ $x.@id }}\n  order {{ nearest($x.embedding, $v) }}\n  limit 1000000\n}}"


def missing_vector_ratios(omnigraph, snapshot, types=VECTOR_TYPES):
    ratios = {}
    for type_name in types:
        with_vector = {row["x.@id"] for row in omnigraph.inline(vector_ids_source(type_name), {"v": VECTOR_PROBE}, snapshot=snapshot).get("rows") or []}
        if type_name == "Note":
            rows = omnigraph.inline(scan_source("Note", ["slug", "content"]), snapshot=snapshot).get("rows") or []
            with_text = {row["x.slug"] for row in rows if str(row.get("x.content") or "").strip()}
            ratios[type_name] = (len(with_text - with_vector) / len(with_text)) if with_text else 0.0
        else:
            rows = omnigraph.inline(count_source(type_name), snapshot=snapshot).get("rows") or [{}]
            total = int(rows[0].get("n") or 0)
            ratios[type_name] = (max(total - len(with_vector), 0) / total) if total else 0.0
    return ratios


class MetricSink:
    def __init__(self):
        self.lines = []

    def add(self, name, labels, value):
        allowed = METRIC_LABELS.get(name)
        if allowed is None:
            raise EvalError(f"metric {name} is not in the allowlist")
        for label, label_value in labels.items():
            if label not in allowed:
                raise EvalError(f"label {label} is not allowed on {name}")
            if label_value not in allowed[label]:
                raise EvalError(f"label value {label_value!r} is not allowed for {name}.{label}")
        if value is None or (isinstance(value, float) and not math.isfinite(value)):
            return
        rendered = ",".join(f'{label}="{labels[label]}"' for label in sorted(labels))
        self.lines.append(f"{name}{{{rendered}}} {float(value):.6g}" if labels else f"{name} {float(value):.6g}")

    def text(self):
        return "\n".join(self.lines) + ("\n" if self.lines else "")


def push_metrics(url, text, timestamp_ms=None):
    if not text.strip():
        return
    body = text
    if timestamp_ms is not None:
        body = "\n".join(f"{line} {timestamp_ms}" for line in text.strip().split("\n")) + "\n"
    request = urllib.request.Request(url, data=body.encode(), method="POST", headers={"content-type": "text/plain"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in (200, 204):
                raise UpstreamError("vmagent", response.status)
    except urllib.error.HTTPError as error:
        raise UpstreamError("vmagent", error.code) from None
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
        raise UpstreamError("vmagent", 0, type(error).__name__) from None


def add_aggregate_metrics(sink, table, profile, mode):
    for key, row in table.items():
        category, split = key.split("|")
        for metric, value in row.items():
            if metric == "cases":
                continue
            sink.add("brain_eval_score", {"metric": metric, "profile": profile, "category": category, "split": split, "mode": mode}, value)


class LiteLLM:
    def __init__(self, base, key, spend, timeout=120):
        self.base = base.rstrip("/")
        self.key = key
        self.spend = spend
        self.timeout = timeout

    def post(self, path, payload):
        last = None
        for attempt in range(4):
            try:
                _, headers, body = http_json(f"{self.base}{path}", payload=payload, headers={"Authorization": f"Bearer {self.key}"}, timeout=self.timeout, service="litellm")
                lowered = {key.lower(): value for key, value in headers.items()}
                cost = float(lowered.get("x-litellm-response-cost") or 0.0)
                self.spend.add(cost)
                return json.loads(body), cost
            except UpstreamError as error:
                last = error
                if error.status in (0, 429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(2 ** attempt * 2)
                    continue
                raise
        raise last

    def chat(self, payload):
        return self.post("/v1/chat/completions", {"disable_fallbacks": True, **payload})

    def embed(self, model, texts, dimensions):
        result, _ = self.post("/v1/embeddings", {"model": model, "input": list(texts), "dimensions": dimensions})
        vectors = [item["embedding"] for item in sorted(result["data"], key=lambda item: item["index"])]
        return [normalise(vector) for vector in vectors]


def normalise(vector):
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right))


class McpClient:
    def __init__(self, url, key, timeout=60):
        self.url = url
        self.key = key
        self.timeout = timeout
        self.session = None
        self.next_id = 1
        self.protocol = "2025-06-18"

    def rpc(self, method, params, notify=False):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        request_id = None
        if not notify:
            request_id = self.next_id
            self.next_id += 1
            body["id"] = request_id
        headers = {"Authorization": f"Bearer {self.key}", "content-type": "application/json", "accept": "application/json, text/event-stream"}
        if self.session:
            headers["mcp-session-id"] = self.session
        if method != "initialize":
            headers["mcp-protocol-version"] = self.protocol
        request = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("mcp-session-id")
                if session:
                    self.session = session
                content_type = (response.headers.get("content-type") or "").lower()
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as error:
            raise UpstreamError("litellm-mcp", error.code) from None
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as error:
            raise UpstreamError("litellm-mcp", 0, type(error).__name__) from None
        if notify:
            return None
        messages = []
        if "text/event-stream" in content_type:
            for line in raw.split("\n"):
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if payload:
                        messages.append(json.loads(payload))
        elif raw.strip():
            parsed = json.loads(raw)
            messages = parsed if isinstance(parsed, list) else [parsed]
        for message in messages:
            if message.get("id") == request_id:
                if "error" in message:
                    raise EvalError(f"MCP {method} answered error {message['error'].get('code')}")
                return message.get("result") or {}
        raise EvalError(f"MCP {method} returned no response")

    def initialize(self):
        result = self.rpc("initialize", {"protocolVersion": self.protocol, "capabilities": {}, "clientInfo": {"name": "brain-eval", "version": HARNESS_VERSION}})
        self.protocol = result.get("protocolVersion") or self.protocol
        self.rpc("notifications/initialized", {}, notify=True)
        return result

    def tools(self):
        tools, cursor = [], None
        while True:
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(item.get("text", "") for item in result.get("content") or [] if item.get("type") == "text")
        return text, bool(result.get("isError"))


def openai_tools(mcp_tools):
    mapping, tools = {}, []
    for tool in mcp_tools:
        name = re.sub(r"[^a-zA-Z0-9_-]", "_", tool["name"])[:64]
        mapping[name] = tool["name"]
        tools.append({"type": "function", "function": {"name": name, "description": (tool.get("description") or "")[:1024],
                                                       "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}}}})
    return tools, mapping


def cut(text, limit=TOOL_OUTPUT_LIMIT):
    return text if len(text) <= limit else text[:limit]


@dataclass
class Answer:
    text: str
    tool_calls: int
    tool_errors: int
    turns: int
    cost: float
    seconds: float
    tool_outputs: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


def answer_case(question, llm, mcp, tools, mapping, *, model, prompt, temperature=0.2, max_turns=MAX_TOOL_TURNS):
    messages = ([{"role": "system", "content": prompt}] if prompt else []) + [{"role": "user", "content": question}]
    started = time.monotonic()
    calls = errors = turns = prompt_tokens = completion_tokens = 0
    cost = 0.0
    outputs = []
    final = ""
    while True:
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": 1500}
        if tools:
            payload["tools"] = tools
            if turns >= max_turns:
                payload["tool_choice"] = "none"
        response, call_cost = llm.chat(payload)
        cost += call_cost
        usage = response.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        message = (response.get("choices") or [{}])[0].get("message") or {}
        requested = message.get("tool_calls") or []
        if not requested or turns >= max_turns:
            final = message.get("content") or ""
            break
        turns += 1
        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": requested})
        for call in requested:
            calls += 1
            function = call.get("function") or {}
            try:
                arguments = json.loads(function.get("arguments") or "{}")
                text, failed = mcp.call(mapping.get(function.get("name"), function.get("name")), arguments)
            except (json.JSONDecodeError, EvalError) as error:
                text, failed = f"tool call failed: {type(error).__name__}", True
            errors += int(failed)
            text = cut(text)
            outputs.append(text)
            messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": text})
    return Answer(final, calls, errors, turns, cost, time.monotonic() - started, cut("\n\n".join(outputs)), prompt_tokens, completion_tokens)


JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["key_facts", "claims", "citations", "abstained"],
    "properties": {
        "key_facts": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["index", "present"],
                                                  "properties": {"index": {"type": "integer"}, "present": {"type": "boolean"}}}},
        "claims": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["grounded"],
                                               "properties": {"grounded": {"type": "boolean"}}}},
        "citations": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["supported"],
                                                  "properties": {"supported": {"type": "boolean"}}}},
        "abstained": {"type": "boolean"},
    },
}


def parse_json_content(response):
    content = ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n|\n```$", "", content)
    return json.loads(content)


def judge_answer(llm, prompt, *, model, question, answerable, key_facts, answer, tool_outputs):
    user = json.dumps({"question": question, "answerable": answerable, "key_facts": [{"index": index, "fact": fact} for index, fact in enumerate(key_facts)],
                       "answer": answer, "tool_outputs": cut(tool_outputs)}, ensure_ascii=False)
    started = time.monotonic()
    response, cost = llm.chat({"model": model, "temperature": 0, "max_tokens": 1200, "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                               "response_format": {"type": "json_schema", "json_schema": {"name": "brain_eval_judgement", "strict": True, "schema": JUDGE_SCHEMA}}})
    verdict = parse_json_content(response)
    return verdict, cost, time.monotonic() - started


def judged_scores(verdict, key_facts, answerable):
    present = {item["index"]: bool(item["present"]) for item in verdict.get("key_facts") or [] if isinstance(item.get("index"), int)}
    claims = verdict.get("claims") or []
    citations = verdict.get("citations") or []
    abstained = bool(verdict.get("abstained"))
    key_fact_recall = (sum(present.get(index, False) for index in range(len(key_facts))) / len(key_facts)) if (answerable and key_facts) else None
    faithfulness = (sum(bool(claim.get("grounded")) for claim in claims) / len(claims)) if claims else (1.0 if abstained else None)
    if citations:
        citation_precision = sum(bool(citation.get("supported")) for citation in citations) / len(citations)
    elif claims:
        citation_precision = 0.0
    else:
        citation_precision = None
    return {
        "key_fact_recall": key_fact_recall,
        "faithfulness": faithfulness,
        "citation_precision": citation_precision,
        "abstention_accuracy": 1.0 if abstained == (not answerable) else 0.0,
        "abstained": abstained,
        "key_facts_present": [present.get(index, False) for index in range(len(key_facts))],
    }


def control_score(scores):
    parts = [value for value in (scores["key_fact_recall"], scores["faithfulness"]) if value is not None]
    return sum(parts) / len(parts) if parts else 0.0


def run_control_pair(llm, prompt, model):
    results = {}
    for label, answer in CONTROL_ANSWERS.items():
        verdict, _, _ = judge_answer(llm, prompt, model=model, question=CONTROL_CASE["question"], answerable=True, key_facts=CONTROL_CASE["key_facts"],
                                     answer=answer, tool_outputs=CONTROL_CASE["tool_outputs"])
        results[label] = control_score(judged_scores(verdict, CONTROL_CASE["key_facts"], True))
    ok = results["supported"] >= 0.8 and results["unsupported"] <= 0.2
    return ok, results


def sign_test_p(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def decide(baseline, candidate, categories, *, min_delta=0.05, min_net_wins=3, max_category_losses=1, guardrails=None):
    shared = sorted(set(baseline) & set(candidate))
    deltas = {case: candidate[case] - baseline[case] for case in shared if baseline[case] is not None and candidate[case] is not None}
    wins = sum(1 for delta in deltas.values() if delta > 1e-9)
    losses = sum(1 for delta in deltas.values() if delta < -1e-9)
    per_category = {}
    for case, delta in deltas.items():
        if delta < -1e-9:
            per_category[categories[case]] = per_category.get(categories[case], 0) + 1
    mean_delta = sum(deltas.values()) / len(deltas) if deltas else 0.0
    reasons = []
    if mean_delta < min_delta:
        reasons.append(f"mean delta {mean_delta:+.3f} is under {min_delta:+.2f}")
    if wins - losses < min_net_wins:
        reasons.append(f"net wins {wins - losses} are under {min_net_wins}")
    worst = [category for category, count in per_category.items() if count > max_category_losses]
    if worst:
        reasons.append("categories losing more than one case: " + ", ".join(sorted(worst)))
    for name, holds in (guardrails or {}).items():
        if not holds:
            reasons.append(f"guardrail failed: {name}")
    return {"adopt": not reasons, "mean_delta": round(mean_delta, 6), "wins": wins, "losses": losses, "cases": len(deltas),
            "sign_test_p": round(sign_test_p(wins, losses), 6), "category_losses": per_category, "reasons": reasons}


def case_state(case):
    return "provisional" if case.get("provisional") or case.get("origin") == "drafted" else "curated"


def set_is_provisional(cases, calibration_grades):
    ryan = sum(1 for case in cases if case.get("origin") == "ryan")
    return any(case_state(case) == "provisional" for case in cases) or ryan < 6 or calibration_grades < 10 or len(cases) < sum(CATEGORY_QUOTA.values())


def add_set_metrics(sink, cases, calibration_grades):
    for split in SPLITS:
        for state in ("provisional", "curated"):
            sink.add("brain_eval_cases", {"split": split, "state": state}, sum(1 for case in cases if case["split"] == split and case_state(case) == state))
    sink.add("brain_eval_set_provisional", {}, 1.0 if set_is_provisional(cases, calibration_grades) else 0.0)
    sink.add("brain_eval_calibration_grades", {}, calibration_grades)


@dataclass
class Workspace:
    repo: Path
    out: Path
    store_kind: str

    @classmethod
    def open(cls, repo, out):
        repo, out = Path(repo), Path(out)
        out.mkdir(parents=True, exist_ok=True)
        kind_file = repo.parent / "store-kind"
        kind = kind_file.read_text().strip() if kind_file.exists() else "none"
        return cls(repo, out, kind)

    def result_path(self, day, name):
        folder = self.repo / "results" / day
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}.json"
        counter = 2
        while path.exists():
            path = folder / f"{name}-{counter}.json"
            counter += 1
        return path

    def write_result(self, day, name, document):
        path = self.result_path(day, name)
        path.write_text(json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def commit_message(self, text):
        (self.out / "commit-message").write_text(text + "\n", encoding="utf-8")

    def cases(self):
        folder = self.repo / "cases"
        return load_cases(folder) if folder.is_dir() else []

    def calibration_files(self):
        folder = self.repo / "calibration"
        return sorted(path for path in folder.glob("*.json")) if folder.is_dir() else []


def read_secret(path):
    value = Path(path).read_text(encoding="utf-8").strip()
    if not value:
        raise EvalError(f"secret file {Path(path).name} is empty")
    return value


def select_cases(cases, args):
    chosen = [case for case in cases if not args.split or case["split"] == args.split]
    if args.limit_cases:
        chosen = chosen[: args.limit_cases]
    return chosen


def run_retrieval(args, workspace, sink, omnigraph, cases, profiles, run_label="retrieval"):
    snapshot = args.snapshot or omnigraph.head()
    snapshot_time = omnigraph.commit_time(snapshot)
    catalog = Catalog.read(omnigraph, snapshot)
    served = omnigraph.stored_catalog()
    absent = [name for name in P0_QUERIES if name not in served]
    if "p0" in profiles and absent:
        raise EvalError(f"stored queries missing for act-brain-eval: {', '.join(absent)}")
    stale, excluded, scorable = [], [], []
    for case in cases:
        if catalog.missing(case):
            stale.append(case["id"])
        elif case.get("temporal") is None and not is_retrieval_scorable(case):
            if case["category"] != SYNTHETIC_CATEGORY:
                excluded.append((case["id"], "unanswerable"))
        else:
            scorable.append(case)
    kinds = {case["temporal"]["kind"] for case in scorable if case.get("temporal")}
    scans = temporal_scans(omnigraph, snapshot, kinds) if kinds else None
    grades_by_case = {}
    for case in scorable:
        if case.get("temporal"):
            grades = temporal_expectation(case, scans, snapshot_time)
            if not grades:
                excluded.append((case["id"], "temporal-empty"))
                continue
        else:
            grades = catalog.equivalence.canonical_expectation(case.get("expected") or [])
        grades_by_case[case["id"]] = grades
    sentinel_runs = 0
    documents = {}
    for profile in profiles:
        runner = PROFILE_RUNNERS[profile]
        results, legs, case_seconds, payloads = [], [], [], []
        for case in cases:
            if case["id"] not in grades_by_case and case.get("category") != SYNTHETIC_CATEGORY:
                continue
            started = time.monotonic()
            retrieved = runner(omnigraph, case["question"], snapshot)
            case_seconds.append(time.monotonic() - started)
            legs.extend(retrieved.leg_seconds)
            payloads.append(retrieved.payload_chars)
            if case["id"] not in grades_by_case:
                sentinel_runs += 1
                continue
            ranked = catalog.equivalence.canonical_ranking(retrieved.ranked)
            results.append({"id": case["id"], "category": case["category"], "split": case["split"], "state": case_state(case),
                            "metrics": retrieval_scores(ranked, grades_by_case[case["id"]]), "ranked": ranked[:10],
                            "expected": grades_by_case[case["id"]], "payload_chars": retrieved.payload_chars, "seconds": round(time.monotonic() - started, 4)})
        table = aggregate(results, RETRIEVAL_METRICS)
        add_aggregate_metrics(sink, table, profile, "retrieval")
        sink.add("brain_eval_scored_cases", {"mode": "retrieval", "profile": profile}, len(results))
        for q in QUANTILES:
            sink.add("brain_eval_latency_seconds", {"stage": "leg", "quantile": q, "profile": profile}, quantile(legs, float(q)))
            sink.add("brain_eval_latency_seconds", {"stage": "case", "quantile": q, "profile": profile}, quantile(case_seconds, float(q)))
            sink.add("brain_eval_payload_chars", {"profile": profile, "quantile": q}, quantile(payloads, float(q)))
        overall = table.get("all|all", {})
        log("retrieval scored", profile=profile, snapshot=snapshot, scored=len(results), stale=len(stale), excluded=len(excluded),
            ndcg_at_8=overall.get("ndcg_at_8"), recall_at_8=overall.get("recall_at_8"), hit_at_1=overall.get("hit_at_1"), mrr_at_8=overall.get("mrr_at_8"),
            leg_p95_seconds=round(quantile(legs, 0.95) or 0, 4), payload_p95_chars=quantile(payloads, 0.95))
        documents[profile] = {"profile": profile, "aggregates": table, "cases": results}
    sink.add("brain_eval_stale_cases", {}, len(stale))
    run = {"mode": run_label, "harness_version": HARNESS_VERSION, "snapshot": snapshot, "snapshot_time": snapshot_time.isoformat(),
           "started": utc_now().isoformat(), "stale_cases": stale, "excluded_cases": excluded, "sentinel_runs": sentinel_runs,
           "store": workspace.store_kind if workspace else "none"}
    return run, documents, grades_by_case


def run_answers(args, workspace, sink, cases, llm, arm, repeats, judge_prompt):
    mcp_server, prompt_file = ARMS[arm]
    prompt = Path(args.prompts_dir, prompt_file).read_text(encoding="utf-8") if prompt_file else None
    mcp = McpClient(f"{args.litellm_url.rstrip('/')}/{mcp_server}/mcp", llm.key)
    mcp.initialize()
    tools, mapping = openai_tools(mcp.tools())
    log("answer tools listed", arm=arm, tools=len(tools))
    results = []
    answer_seconds, judge_seconds = [], []
    records = []
    for repeat in range(repeats):
        for case in cases:
            answer = answer_case(case["question"], llm, mcp, tools, mapping, model=args.answer_model, prompt=prompt)
            verdict, _, seconds = judge_answer(llm, judge_prompt, model=args.judge_model, question=case["question"], answerable=case["answerable"],
                                               key_facts=case.get("key_facts") or [], answer=answer.text, tool_outputs=answer.tool_outputs)
            scores = judged_scores(verdict, case.get("key_facts") or [], case["answerable"])
            answer_seconds.append(answer.seconds)
            judge_seconds.append(seconds)
            metrics = {key: scores[key] for key in ("key_fact_recall", "faithfulness", "citation_precision", "abstention_accuracy")}
            metrics.update({"tool_error_rate": (answer.tool_errors / answer.tool_calls) if answer.tool_calls else None, "tool_calls": float(answer.tool_calls),
                            "usd_per_answer": answer.cost, "latency_seconds": answer.seconds})
            results.append({"id": case["id"], "repeat": repeat, "category": case["category"], "split": case["split"], "state": case_state(case), "metrics": metrics})
            records.append({"case": case, "answer": answer, "scores": scores, "arm": arm, "repeat": repeat})
            log("answer judged", arm=arm, case=case["id"], repeat=repeat, tool_calls=answer.tool_calls, tool_errors=answer.tool_errors, turns=answer.turns,
                seconds=round(answer.seconds, 2), spend_usd=round(llm.spend.total, 4))
    table = aggregate(results, ANSWER_METRICS)
    add_aggregate_metrics(sink, table, arm, "answer")
    sink.add("brain_eval_scored_cases", {"mode": "answer", "profile": arm}, len(results))
    for q in QUANTILES:
        sink.add("brain_eval_latency_seconds", {"stage": "answer", "quantile": q, "profile": arm}, quantile(answer_seconds, float(q)))
        sink.add("brain_eval_latency_seconds", {"stage": "judge", "quantile": q, "profile": arm}, quantile(judge_seconds, float(q)))
    overall = table.get("all|all", {})
    log("answers scored", arm=arm, answers=len(results), key_fact_recall=overall.get("key_fact_recall"), faithfulness=overall.get("faithfulness"),
        citation_precision=overall.get("citation_precision"), abstention_accuracy=overall.get("abstention_accuracy"), spend_usd=round(llm.spend.total, 4))
    return {"profile": arm, "aggregates": table, "cases": results}, records


ARMS = {"b0": ("omnigraph_brain_eval", None), "tools": ("brain_tools_read", "brain.prompt.txt")}


def write_calibration_templates(workspace, records, limit=10):
    graded = len(workspace.calibration_files())
    pending_dir = workspace.repo / "calibration" / "pending"
    if graded >= limit:
        return 0
    pending_dir.mkdir(parents=True, exist_ok=True)
    existing = len(list(pending_dir.glob("*.json")))
    written = 0
    for record in records:
        if graded + existing + written >= limit:
            break
        case = record["case"]
        if record["repeat"] or case.get("origin") == "synthetic":
            continue
        path = pending_dir / f"{case['id']}-{record['arm']}.json"
        if path.exists():
            continue
        path.write_text(json.dumps({
            "case_id": case["id"], "arm": record["arm"], "question": case["question"], "answerable": case["answerable"],
            "key_facts": case.get("key_facts") or [], "answer": record["answer"].text, "tool_outputs": record["answer"].tool_outputs,
            "grade": {"key_facts_present": [None] * len(case.get("key_facts") or []), "faithful": None, "abstained": None},
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written += 1
    return written


def calibration_agreement(llm, judge_prompt, judge_model, files):
    matches = total = graded = 0
    for path in files:
        item = json.loads(path.read_text(encoding="utf-8"))
        grade = item.get("grade") or {}
        human_facts = grade.get("key_facts_present") or []
        if grade.get("faithful") is None or grade.get("abstained") is None or any(value is None for value in human_facts):
            continue
        graded += 1
        verdict, _, _ = judge_answer(llm, judge_prompt, model=judge_model, question=item["question"], answerable=item["answerable"],
                                     key_facts=item.get("key_facts") or [], answer=item["answer"], tool_outputs=item.get("tool_outputs") or "")
        scores = judged_scores(verdict, item.get("key_facts") or [], item["answerable"])
        for human, machine in zip(human_facts, scores["key_facts_present"]):
            total += 1
            matches += int(bool(human) == bool(machine))
        total += 2
        matches += int(bool(grade["faithful"]) == ((scores["faithfulness"] or 0) >= 0.8))
        matches += int(bool(grade["abstained"]) == scores["abstained"])
    return (matches / total if total else None), graded


def dated(args):
    return (args.day or utc_now().strftime("%Y-%m-%d"))


def finish(args, workspace, sink, mode, summary):
    sink.add("brain_eval_run_valid", {"mode": mode}, 1.0)
    sink.add("brain_eval_store_provisional", {}, 1.0 if workspace and workspace.store_kind == "provisional" else 0.0)
    if workspace:
        (workspace.out / "metrics.prom").write_text(sink.text(), encoding="utf-8")
        (workspace.out / "mode").write_text(mode + "\n", encoding="utf-8")
        workspace.commit_message(summary)
    log("run complete", mode=mode, metric_lines=len(sink.lines))


def invalid_run(args, mode, reason):
    sink = MetricSink()
    sink.add("brain_eval_run_valid", {"mode": mode}, 0.0)
    if args.vmagent_url and not args.dry_run:
        try:
            push_metrics(args.vmagent_url, sink.text())
        except UpstreamError as error:
            log("metrics push failed", reason=str(error))
    log("run invalid", mode=mode, reason=reason)


def omnigraph_client(args):
    return Omnigraph(args.omnigraph_url, "brain", read_secret(args.omnigraph_token_file))


def litellm_client(args, cap):
    return LiteLLM(args.litellm_url, read_secret(args.litellm_key_file), Spend(cap))


def cases_for_run(args, workspace):
    if args.synthetic:
        return synthetic_cases()
    cases = workspace.cases()
    if not cases:
        raise EvalError("the eval repo holds no cases yet: run the candidates job first")
    return cases


def command_retrieval(args):
    workspace = Workspace.open(args.repo_dir, args.out_dir)
    sink = MetricSink()
    omnigraph = omnigraph_client(args)
    all_cases = cases_for_run(args, workspace)
    cases = select_cases(all_cases, args) + ([] if args.synthetic else [case for case in synthetic_cases() if case["id"] == "syn-sentinel"])
    if not args.synthetic:
        add_set_metrics(sink, all_cases, len(workspace.calibration_files()))
    if args.scratch_stale:
        scratch = json.loads(json.dumps(next(case for case in cases if case.get("expected"))))
        scratch["id"] = "scratch-stale"
        scratch["expected"][0]["slug"] = scratch["expected"][0]["slug"] + "-renamed"
        cases.append(scratch)
    run, documents, _ = run_retrieval(args, workspace, sink, omnigraph, cases, args.profile)
    if args.missing_vectors:
        ratios = missing_vector_ratios(omnigraph, run["snapshot"])
        for type_name, ratio in ratios.items():
            sink.add("brain_eval_missing_vectors_ratio", {"type": type_name}, ratio)
        log("vector coverage", **{f"missing_{type_name.lower()}_ratio": round(ratio, 6) for type_name, ratio in ratios.items()})
    if args.public_repo_dir and Path(args.public_repo_dir).is_dir() and not args.synthetic:
        leaked, shingles, files = public_repo_leaks(all_cases, args.public_repo_dir)
        sink.add("brain_eval_public_repo_leaks", {}, leaked)
        log("public repo leak check", cases_found=leaked, phrases_checked=shingles, files_scanned=files)
    run["provisional"] = set_is_provisional(all_cases, len(workspace.calibration_files())) if not args.synthetic else True
    if args.dry_run or args.synthetic:
        log("dry run: nothing written", scored={profile: len(document["cases"]) for profile, document in documents.items()})
        return 0
    for profile, document in documents.items():
        workspace.write_result(dated(args), f"retrieval-{profile}", {"run": run, **document})
    finish(args, workspace, sink, "retrieval", f"results: retrieval {', '.join(args.profile)} at graph commit {run['snapshot']}")
    return 0


def command_answer(args):
    workspace = Workspace.open(args.repo_dir, args.out_dir)
    sink = MetricSink()
    judge_prompt = Path(args.prompts_dir, "judge.prompt.txt").read_text(encoding="utf-8")
    llm = litellm_client(args, args.max_spend_usd)
    ok, control = run_control_pair(llm, judge_prompt, args.judge_model)
    log("judge control pair", ok=ok, supported=round(control["supported"], 3), unsupported=round(control["unsupported"], 3))
    if not ok:
        failure = MetricSink()
        failure.add("brain_eval_judge_control_ok", {}, 0.0)
        failure.add("brain_eval_run_valid", {"mode": "answer"}, 0.0)
        if args.vmagent_url and not args.dry_run:
            push_metrics(args.vmagent_url, failure.text())
        raise EvalError("the judge control pair failed: answer scores are not published")
    sink.add("brain_eval_judge_control_ok", {}, 1.0)
    if args.control_only:
        if args.vmagent_url and not args.dry_run:
            push_metrics(args.vmagent_url, sink.text())
        log("control pair only", spend_usd=round(llm.spend.total, 4))
        return 0
    all_cases = cases_for_run(args, workspace)
    if not args.synthetic and os.environ.get("BRAIN_EVAL_MCP_ARGUMENTS_REDACTED") != "true":
        raise EvalError("answer mode on real cases waits until LiteLLM stops keeping MCP tool arguments (VIK-1403); set BRAIN_EVAL_MCP_ARGUMENTS_REDACTED=true once it ships")
    cases = select_cases(all_cases, args)
    documents = {}
    all_records = []
    for arm in args.arm:
        document, records = run_answers(args, workspace, sink, cases, llm, arm, args.repeats, judge_prompt)
        documents[arm] = document
        all_records.extend(records)
    sink.add("brain_eval_cost_usd", {"mode": "answer"}, llm.spend.total)
    if not args.synthetic:
        add_set_metrics(sink, all_cases, len(workspace.calibration_files()))
        agreement, graded = calibration_agreement(llm, judge_prompt, args.judge_model, workspace.calibration_files())
        if agreement is not None:
            sink.add("brain_eval_judge_agreement", {}, agreement)
        log("judge calibration", graded=graded, agreement=None if agreement is None else round(agreement, 3))
    if args.dry_run or args.synthetic:
        log("dry run: nothing written", answers={arm: len(document["cases"]) for arm, document in documents.items()}, spend_usd=round(llm.spend.total, 4))
        return 0
    written = write_calibration_templates(workspace, all_records)
    run = {"mode": "answer", "harness_version": HARNESS_VERSION, "started": utc_now().isoformat(), "answer_model": args.answer_model, "judge_model": args.judge_model,
           "repeats": args.repeats, "spend_usd": round(llm.spend.total, 6), "control": control, "calibration_templates_written": written,
           "provisional": set_is_provisional(all_cases, len(workspace.calibration_files())), "store": workspace.store_kind}
    for arm, document in documents.items():
        workspace.write_result(dated(args), f"answer-{arm}", {"run": run, **document})
    finish(args, workspace, sink, "answer", f"results: answer {', '.join(args.arm)} x{args.repeats}")
    return 0


def command_gate(args):
    workspace = Workspace.open(args.repo_dir, args.out_dir)
    sink = MetricSink()
    omnigraph = omnigraph_client(args)
    all_cases = cases_for_run(args, workspace)
    cases = select_cases(all_cases, args)
    run, documents, _ = run_retrieval(args, workspace, sink, omnigraph, cases, args.profile, run_label="gate")
    decisions = {}
    categories = {case["id"]: case["category"] for case in cases}
    if args.compare:
        for pair in args.compare:
            baseline, candidate = pair.split(":")
            if baseline in documents and candidate in documents:
                per_case = lambda profile: {result["id"]: result["metrics"]["ndcg_at_8"] for result in documents[profile]["cases"] if result["split"] == "dev"}
                decisions[pair] = decide(per_case(baseline), per_case(candidate), categories)
                log("gate decision", pair=pair, **{key: value for key, value in decisions[pair].items() if key != "category_losses"})
    answer_documents = {}
    if args.arm:
        judge_prompt = Path(args.prompts_dir, "judge.prompt.txt").read_text(encoding="utf-8")
        llm = litellm_client(args, args.max_spend_usd)
        ok, control = run_control_pair(llm, judge_prompt, args.judge_model)
        sink.add("brain_eval_judge_control_ok", {}, 1.0 if ok else 0.0)
        if not ok:
            raise EvalError("the judge control pair failed: gate answers are not scored")
        if not args.synthetic and os.environ.get("BRAIN_EVAL_MCP_ARGUMENTS_REDACTED") != "true":
            raise EvalError("answer mode on real cases waits until LiteLLM stops keeping MCP tool arguments (VIK-1403)")
        for arm in args.arm:
            answer_documents[arm], _ = run_answers(args, workspace, sink, cases, llm, arm, args.repeats, judge_prompt)
        sink.add("brain_eval_cost_usd", {"mode": "gate"}, llm.spend.total)
    if args.dry_run or args.synthetic:
        log("dry run: nothing written")
        return 0
    workspace.write_result(dated(args), "gate", {"run": run, "retrieval": documents, "answers": answer_documents, "decisions": decisions})
    finish(args, workspace, sink, "gate", f"results: gate {', '.join(args.profile + (args.arm or []))}")
    return 0


E1_POOL_SOURCE = """query e1_meaning($q: String) {
  match {
    $p: Passage
    $p passageOf $a
  }
  return { $p.@id, $a.slug, $p.text, $p.embedding }
  order { nearest($p.embedding, $q) }
  limit 40
}"""
E1_KEYWORD_SOURCE = """query e1_keywords($q: String) {
  match {
    $p: Passage
    $p passageOf $a
  }
  return { $p.@id, $a.slug, $p.text, $p.embedding }
  order { bm25($p.text, $q) desc }
  limit 40
}"""


def command_experiment(args):
    workspace = Workspace.open(args.repo_dir, args.out_dir)
    sink = MetricSink()
    omnigraph = omnigraph_client(args)
    contract = json.loads(Path(args.contract_file).read_text(encoding="utf-8"))
    llm = litellm_client(args, args.max_spend_usd)
    cases = [case for case in select_cases(cases_for_run(args, workspace), args) if case["split"] == "dev" and is_retrieval_scorable(case) and not case.get("temporal")]
    snapshot = args.snapshot or omnigraph.head()
    catalog = Catalog.read(omnigraph, snapshot)
    arms = {"e1-prefixed": {}, "e1-raw": {}}
    results = {"e1-prefixed": [], "e1-raw": []}
    for case in cases:
        if catalog.missing(case):
            continue
        grades = catalog.equivalence.canonical_expectation(case["expected"])
        pool = {}
        for source in (E1_POOL_SOURCE, E1_KEYWORD_SOURCE):
            for row in omnigraph.inline(source, {"q": case["question"]}, snapshot=snapshot).get("rows") or []:
                pool.setdefault(row["p.@id"], row)
        if not pool:
            continue
        query_vector = llm.embed(contract["model"], [case["question"]], contract["dimensions"])[0]
        rows = list(pool.values())
        raw_vectors = []
        for start in range(0, len(rows), 16):
            raw_vectors.extend(llm.embed(contract["model"], [row["p.text"].strip(contract["value_trim_characters"]) or " " for row in rows[start: start + 16]], contract["dimensions"]))
        prefixed = sorted(rows, key=lambda row: -cosine(query_vector, normalise(row["p.embedding"])) if row.get("p.embedding") else 1.0)
        raw = [row for _, row in sorted(zip(raw_vectors, rows), key=lambda pair: -cosine(query_vector, pair[0]))]
        for arm, ordered in (("e1-prefixed", prefixed), ("e1-raw", raw)):
            ranked = catalog.equivalence.canonical_ranking(row["a.slug"] for row in ordered)
            scores = retrieval_scores(ranked, grades)
            arms[arm][case["id"]] = scores["ndcg_at_8"]
            results[arm].append({"id": case["id"], "category": case["category"], "split": case["split"], "metrics": scores})
    for arm, rows in results.items():
        add_aggregate_metrics(sink, aggregate(rows, RETRIEVAL_METRICS), arm, "experiment")
    decision = decide(arms["e1-prefixed"], arms["e1-raw"], {case["id"]: case["category"] for case in cases})
    sink.add("brain_eval_cost_usd", {"mode": "experiment"}, llm.spend.total)
    log("experiment e1", cases=len(arms["e1-raw"]), **{key: value for key, value in decision.items() if key != "category_losses"})
    if args.dry_run or args.synthetic:
        return 0
    workspace.write_result(dated(args), "experiment-e1", {"run": {"mode": "experiment", "snapshot": snapshot, "harness_version": HARNESS_VERSION},
                                                          "decision": decision, "arms": results})
    finish(args, workspace, sink, "experiment", "results: experiment e1 raw versus prefixed vectors")
    return 0


def command_calibration(args):
    workspace = Workspace.open(args.repo_dir, args.out_dir)
    sink = MetricSink()
    judge_prompt = Path(args.prompts_dir, "judge.prompt.txt").read_text(encoding="utf-8")
    llm = litellm_client(args, args.max_spend_usd)
    agreement, graded = calibration_agreement(llm, judge_prompt, args.judge_model, workspace.calibration_files())
    if agreement is not None:
        sink.add("brain_eval_judge_agreement", {}, agreement)
    sink.add("brain_eval_calibration_grades", {}, graded)
    log("judge calibration", graded=graded, agreement=None if agreement is None else round(agreement, 3), spend_usd=round(llm.spend.total, 4))
    if args.dry_run:
        return 0
    finish(args, workspace, sink, "calibration", "results: judge calibration")
    return 0


def command_push_metrics(args):
    out = Path(args.out_dir)
    metrics_file = out / "metrics.prom"
    mode_file = out / "mode"
    if not metrics_file.exists() or not mode_file.exists():
        log("no metrics to push")
        return 0
    mode = mode_file.read_text().strip()
    sink = MetricSink()
    sink.add("brain_eval_last_success_timestamp_seconds", {"mode": mode}, time.time())
    push_metrics(args.vmagent_url, metrics_file.read_text(encoding="utf-8") + sink.text())
    log("metrics pushed", mode=mode, lines=len(metrics_file.read_text().strip().split("\n")) + 1)
    return 0


def command_candidates(args):
    import candidates

    return candidates.command_candidates(args)


def build_parser():
    parser = argparse.ArgumentParser(description="Score brain retrieval and answers against the private eval set.")
    parser.add_argument("--repo-dir", default="/work/repo")
    parser.add_argument("--out-dir", default="/work/out")
    parser.add_argument("--prompts-dir", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--omnigraph-url", default="http://omnigraph.ai.svc.cluster.local:8080")
    parser.add_argument("--omnigraph-token-file", default="/run/secrets/omnigraph/token")
    parser.add_argument("--litellm-url", default="http://litellm.ai.svc.cluster.local:4000")
    parser.add_argument("--litellm-key-file", default="/run/secrets/litellm/key")
    parser.add_argument("--contract-file", default="/etc/omnigraph-embedding-contract/contract.json")
    parser.add_argument("--vmagent-url", default="")
    parser.add_argument("--snapshot")
    parser.add_argument("--day")
    parser.add_argument("--split", choices=SPLITS)
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="run the public synthetic cases instead of the eval set")
    parser.add_argument("--answer-model", default="chat-default")
    parser.add_argument("--judge-model", default="claude-haiku-4-5")
    parser.add_argument("--draft-model", default="fireworks-gpt-oss-120b")
    parser.add_argument("--max-spend-usd", type=float, default=2.0)
    commands = parser.add_subparsers(dest="command", required=True)
    retrieval = commands.add_parser("retrieval")
    retrieval.add_argument("--profile", action="append", choices=sorted(PROFILE_RUNNERS), default=None)
    retrieval.add_argument("--missing-vectors", action="store_true")
    retrieval.add_argument("--public-repo-dir", help="a checkout of the public homelab-cluster repo to scan for case text")
    retrieval.add_argument("--scratch-stale", action="store_true", help="add a copy of one case with a renamed expected slug, to prove the stale check")
    retrieval.set_defaults(handler=command_retrieval)
    answer = commands.add_parser("answer")
    answer.add_argument("--arm", action="append", choices=sorted(ARMS), default=None)
    answer.add_argument("--repeats", type=int, default=1)
    answer.add_argument("--control-only", action="store_true")
    answer.set_defaults(handler=command_answer)
    gate = commands.add_parser("gate")
    gate.add_argument("--profile", action="append", choices=sorted(PROFILE_RUNNERS), default=None)
    gate.add_argument("--arm", action="append", choices=sorted(ARMS), default=None)
    gate.add_argument("--repeats", type=int, default=3)
    gate.add_argument("--compare", action="append", help="baseline:candidate profiles for the decision rule")
    gate.set_defaults(handler=command_gate)
    experiment = commands.add_parser("experiment")
    experiment.set_defaults(handler=command_experiment)
    calibration = commands.add_parser("calibration")
    calibration.set_defaults(handler=command_calibration)
    candidates = commands.add_parser("candidates")
    candidates.add_argument("--sources", type=int, default=30)
    candidates.add_argument("--seed", type=int, default=20260929)
    candidates.add_argument("--pool-model", default="claude-haiku-4-5")
    candidates.set_defaults(handler=command_candidates)
    push = commands.add_parser("push-metrics")
    push.set_defaults(handler=command_push_metrics)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "profile", "unset") is None:
        args.profile = ["p0"]
    if getattr(args, "arm", "unset") is None and args.command == "answer":
        args.arm = ["b0"]
    mode = args.command if args.command in MODES else "retrieval"
    try:
        return args.handler(args)
    except SpendCapReached as error:
        invalid_run(args, mode, str(error))
        return 3
    except (EvalError, UpstreamError) as error:
        invalid_run(args, mode, str(error))
        return 2
    except Exception as error:
        invalid_run(args, mode, f"unexpected {type(error).__name__} at {error_location(error)}")
        return 2


def error_location(error):
    frame = error.__traceback__
    while frame and frame.tb_next:
        frame = frame.tb_next
    return f"{Path(frame.tb_frame.f_code.co_filename).name}:{frame.tb_lineno}" if frame else "unknown"


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import brain_eval

    sys.exit(brain_eval.main())
