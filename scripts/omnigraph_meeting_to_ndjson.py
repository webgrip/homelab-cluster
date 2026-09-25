#!/usr/bin/env python3
import argparse
import base64
import datetime
import hashlib
import hmac
import json
import re
import sys
import unicodedata

UNASSIGNED = {"name": "Unassigned", "side": "internal"}
MEETING_KINDS = {"kickoff", "status", "review", "workshop", "sales", "support", "incident", "other"}
SIDES = {"internal", "client", "third_party"}
PASSAGE_TARGET_CHARS = 1200


class ExtractionRejected(Exception):
    pass


def normalized(text):
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", folded).strip()


def opaque(key, prefix, material, length):
    digest = hmac.new(key, normalized(material).encode(), hashlib.sha256).hexdigest()
    return f"{prefix}{digest[:length]}"


def topic_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", normalized(name)).strip("-")


def passages(raw):
    blocks = [block.strip() for block in re.split(r"\n\s*\n", raw) if block.strip()]
    merged, current = [], ""
    for block in blocks:
        if current and len(current) + len(block) > PASSAGE_TARGET_CHARS:
            merged.append(current)
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current:
        merged.append(current)
    return merged


def require_verbatim(quote, raw, where):
    if quote is None:
        return None
    if normalized(quote) not in normalized(raw):
        raise ExtractionRejected(f"{where}: quote is not verbatim in the source: {quote!r}")
    return quote


def person_ids(key, attendees):
    ids = {}
    for person in attendees:
        if person["side"] not in SIDES:
            raise ExtractionRejected(f"attendee {person['name']!r}: side {person['side']!r} is not one of {sorted(SIDES)}")
        ids[normalized(person["name"])] = opaque(key, "p-", person.get("email") or person["name"], 12)
    return ids


def resolve(ids, name, where):
    if name is None:
        return "p-unassigned"
    found = ids.get(normalized(name))
    if found is None:
        raise ExtractionRejected(f"{where}: {name!r} is not an attendee")
    return found


def records(key, extraction, raw, source_kind, extractor, captured_at):
    meeting = extraction["meeting"]
    if meeting["kind"] not in MEETING_KINDS:
        raise ExtractionRejected(f"meeting kind {meeting['kind']!r} is not one of {sorted(MEETING_KINDS)}")
    datetime.date.fromisoformat(meeting["held_on"])
    raw_sha = hashlib.sha256(raw.encode()).hexdigest()
    meeting_id = f"m-{meeting['held_on']}-{opaque(key, '', raw_sha, 8)}"
    source_id = f"{meeting_id}/src"
    ids = person_ids(key, extraction["attendees"])
    out = [{"type": "Person", "data": {"slug": "p-unassigned", **UNASSIGNED}}]
    for person in extraction["attendees"]:
        data = {"slug": ids[normalized(person["name"])], "name": person["name"], "side": person["side"]}
        data.update({field: person[field] for field in ("email", "role") if person.get(field)})
        out.append({"type": "Person", "data": data})
    topics = {}
    for decision in extraction["decisions"]:
        topics[topic_slug(decision["topic"])] = decision["topic"]
    for slug, name in topics.items():
        out.append({"type": "Topic", "data": {"slug": slug, "name": name}})
    out.append({"type": "Meeting", "data": {
        "slug": meeting_id, "title": meeting["title"], "held_on": meeting["held_on"], "kind": meeting["kind"],
        "summary": meeting["summary"], "ingested_at": captured_at}})
    out.append({"type": "Source", "data": {
        "slug": source_id, "meeting": meeting_id, "kind": source_kind, "sha256": raw_sha, "extractor": extractor,
        "captured_at": captured_at, "raw": "base64:" + base64.b64encode(raw.encode()).decode()}})
    out.append({"edge": "RecordedIn", "from": meeting_id, "to": source_id})
    for index, text in enumerate(passages(raw)):
        chunk_id = f"{source_id}/c{index}"
        out.append({"type": "Chunk", "data": {"slug": chunk_id, "meeting": meeting_id, "seq": index, "text": text}})
        out.append({"edge": "ChunkOf", "from": chunk_id, "to": source_id})
    for person in extraction["attendees"]:
        role = "absent" if person.get("absent") else ("host" if person["side"] == "internal" else "attendee")
        out.append({"edge": "Attended", "from": ids[normalized(person["name"])], "to": meeting_id, "data": {"role": role}})
    for slug in topics:
        out.append({"edge": "MeetingAbout", "from": meeting_id, "to": slug})
    for index, decision in enumerate(extraction["decisions"], start=1):
        decision_id = f"{meeting_id}/d{index}"
        out.append({"type": "Decision", "data": {
            "slug": decision_id, "meeting": meeting_id, "statement": decision["statement"],
            "decided_on": meeting["held_on"], "status": decision.get("status", "agreed"),
            "quote": require_verbatim(decision.get("quote"), raw, decision_id)}})
        out.append({"edge": "DecidedIn", "from": decision_id, "to": meeting_id})
        out.append({"edge": "DecisionAbout", "from": decision_id, "to": topic_slug(decision["topic"])})
        for name in decision.get("agreed_with", []):
            out.append({"edge": "AgreedWith", "from": decision_id, "to": resolve(ids, name, decision_id)})
    for index, item in enumerate(extraction["action_items"], start=1):
        item_id = f"{meeting_id}/a{index}"
        if item.get("due"):
            datetime.date.fromisoformat(item["due"])
        out.append({"type": "ActionItem", "data": {
            "slug": item_id, "meeting": meeting_id, "title": item["title"], "status": "open",
            "due": item.get("due"), "quote": require_verbatim(item.get("quote"), raw, item_id)}})
        out.append({"edge": "RaisedIn", "from": item_id, "to": meeting_id})
        out.append({"edge": "OwnedBy", "from": item_id, "to": resolve(ids, item.get("owner"), item_id)})
    return meeting_id, out


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Turn one LLM meeting extraction plus its raw notes into Omnigraph load NDJSON.")
    parser.add_argument("--extraction", required=True)
    parser.add_argument("--raw", required=True)
    parser.add_argument("--client-key-file", required=True)
    parser.add_argument("--source-kind", default="notes")
    parser.add_argument("--extractor", required=True)
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    key = open(args.client_key_file, "rb").read().strip()
    extraction = json.load(open(args.extraction, encoding="utf-8"))
    raw = open(args.raw, encoding="utf-8").read()
    captured_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        meeting_id, out = records(key, extraction, raw, args.source_kind, args.extractor, captured_at)
    except (ExtractionRejected, KeyError, ValueError) as error:
        print(f"REJECTED {args.extraction}: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    sys.stdout.write("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in out))
    print(f"{meeting_id} {len(out)} records", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
