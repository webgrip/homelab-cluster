#!/usr/bin/env python3
import argparse
import datetime
import hashlib
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SLUG_PREFIX = "obsidian/"
NOTE_KINDS = frozenset({"idea", "journal", "reflection", "insight", "principle", "preference", "quote", "dream", "question", "decision"})
DEFAULT_KIND = "idea"
MAX_NOTE_BYTES = 1024 * 1024
ROWS_PER_LOAD_FILE = 2000
BYTES_PER_LOAD_FILE = 16 * 1024 * 1024
DAILY_FOLDER_NAMES = frozenset({"daily", "daily notes", "dailies", "journal", "journals"})
TEMPLATE_FOLDER_NAMES = frozenset({"templates", "template"})
SAFE_SLUG = re.compile(r"^obsidian/[a-z0-9/-]+$")
ISO_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
FENCED_CODE = re.compile(r"^(```|~~~).*?^\1", re.M | re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")
INLINE_TAG = re.compile(r"(?:^|(?<=[\s(\[,;]))#([^\s#!@$%^&*()+=\[\]{};:'\",.<>?\\|`~]+)", re.M)
WIKILINK = re.compile(r"!?\[\[([^\]\n]+?)\]\]")

EXIT_OK = 0
EXIT_EMPTY_VAULT = 3


class FailClosed(Exception):
    def __init__(self, exit_code, message):
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class VaultNote:
    relpath: str
    slug: str
    name: str
    kind: str
    content: str | None
    when: str | None
    tags: list[str] | None
    created_at: str | None
    link_targets: list[str] = field(default_factory=list)

    def comparable(self):
        return (self.name, self.kind, self.content, self.when, self.tags)


@dataclass
class Counts:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    relinked: int = 0
    deleted: int = 0
    tagged_client: int = 0
    skipped_large: int = 0
    skipped_unreadable: int = 0

    def line(self):
        return " ".join(f"{key}={value}" for key, value in self.__dict__.items())


@dataclass
class Plan:
    counts: Counts
    prune_statements: list[str]
    node_rows: list[dict]
    edge_rows: list[dict]


CLIENT_TAG = "client"


def read_client_terms(path):
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return []
    return sorted({line.strip() for line in raw.splitlines() if line.strip()})


def client_matcher(terms):
    if not terms:
        return None
    alternatives = "|".join(re.escape(term) for term in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def ascii_fold(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def slug_segment(text):
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(text)).strip("-") or "untitled"


def base_slug(relpath):
    path = PurePosixPath(relpath).with_suffix("")
    return SLUG_PREFIX + "/".join(slug_segment(part) for part in path.parts)


def unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def inline_list(value):
    inner = value.strip()[1:-1]
    return [unquote(item) for item in inner.split(",") if unquote(item)]


def split_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    if lines[0].rstrip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].rstrip() in ("---", "..."):
            return parse_properties(lines[1:index]), "\n".join(lines[index + 1:])
    return {}, text


def parse_properties(lines):
    properties = {}
    current_key = None
    for line in lines:
        list_item = re.match(r"^\s*-\s+(.*)$", line)
        if list_item and current_key is not None:
            existing = properties.get(current_key)
            if not isinstance(existing, list):
                existing = []
            existing.append(unquote(list_item.group(1)))
            properties[current_key] = existing
            continue
        pair = re.match(r"^([A-Za-z0-9_ -]+?)\s*:\s*(.*)$", line)
        if not pair:
            continue
        current_key = pair.group(1).strip().lower()
        value = pair.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            properties[current_key] = inline_list(value)
        elif value:
            properties[current_key] = unquote(value)
        else:
            properties[current_key] = None
    return properties


def normalise_tag(tag):
    return tag.strip().lstrip("#").strip().lower()


def property_tags(properties):
    raw = properties.get("tags", properties.get("tag"))
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else re.split(r"[,\s]+", raw)
    return [normalise_tag(item) for item in items if normalise_tag(item)]


def inline_tags(body):
    scrubbed = INLINE_CODE.sub(" ", FENCED_CODE.sub(" ", body))
    found = []
    for match in INLINE_TAG.finditer(scrubbed):
        tag = normalise_tag(match.group(1).rstrip("/"))
        if tag and not re.fullmatch(r"[\d/]+", tag):
            found.append(tag)
    return found


def dedup(items):
    return list(dict.fromkeys(items))


def valid_date(value):
    if not isinstance(value, str):
        return None
    match = ISO_DATE.match(value.strip())
    if not match:
        return None
    try:
        return datetime.date.fromisoformat(match.group(1)).isoformat()
    except ValueError:
        return None


def utc_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def first_property(properties, *keys):
    for key in keys:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def configured_folder(vault, relative_config, key):
    try:
        folder = json.loads((vault / relative_config).read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(folder, str) and folder.strip().strip("/"):
        return folder.strip().strip("/").lower()
    return None


def under_folder(relpath, folder):
    return folder is not None and (relpath.lower() + "/").startswith(folder + "/")


def in_named_folder(relpath, names):
    return any(part.lower() in names for part in PurePosixPath(relpath).parts[:-1])


def link_target(raw):
    target = raw.split("|", 1)[0].split("#", 1)[0].split("^", 1)[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target.strip("/").lower()


@dataclass
class VaultScan:
    notes: dict[str, VaultNote]
    counts: Counts


def scan_vault(vault, client_pattern):
    vault = Path(vault)
    counts = Counts()
    daily_folder = configured_folder(vault, ".obsidian/daily-notes.json", "folder")
    template_folders = {
        configured_folder(vault, ".obsidian/templates.json", "folder"),
        configured_folder(vault, ".obsidian/plugins/templater-obsidian/data.json", "templates_folder"),
    } - {None}
    candidates = []
    for path in sorted(vault.rglob("*.md")):
        relpath = path.relative_to(vault).as_posix()
        if any(part.startswith(".") for part in PurePosixPath(relpath).parts):
            continue
        if in_named_folder(relpath, TEMPLATE_FOLDER_NAMES) or any(under_folder(relpath, folder) for folder in template_folders):
            continue
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_NOTE_BYTES:
            counts.skipped_large += 1
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            counts.skipped_unreadable += 1
            continue
        mentions_client = client_pattern is not None and bool(client_pattern.search(relpath) or client_pattern.search(text))
        counts.tagged_client += mentions_client
        candidates.append((relpath, text, mentions_client))
    slugs = assign_slugs([relpath for relpath, _, _ in candidates])
    notes = {}
    for relpath, text, mentions_client in candidates:
        note = to_note(relpath, text, slugs[relpath], daily_folder)
        if mentions_client:
            note.tags = dedup((note.tags or []) + [CLIENT_TAG])
        notes[note.slug] = note
    resolve_links(notes)
    return VaultScan(notes=notes, counts=counts)


def assign_slugs(relpaths):
    by_slug = {}
    for relpath in relpaths:
        by_slug.setdefault(base_slug(relpath), []).append(relpath)
    slugs = {}
    for slug, owners in by_slug.items():
        for relpath in owners:
            suffix = "" if len(owners) == 1 else "-" + hashlib.sha1(relpath.encode()).hexdigest()[:8]
            slugs[relpath] = slug + suffix
    return slugs


def to_note(relpath, text, slug, daily_folder):
    properties, body = split_frontmatter(text)
    stem = PurePosixPath(relpath).stem
    filename_date = valid_date(stem) if ISO_DATE.fullmatch(stem) else None
    is_daily = filename_date is not None or under_folder(relpath, daily_folder) or in_named_folder(relpath, DAILY_FOLDER_NAMES)
    declared_kind = first_property(properties, "kind", "type")
    if is_daily:
        kind = "journal"
    elif declared_kind and declared_kind.strip().lower() in NOTE_KINDS:
        kind = declared_kind.strip().lower()
    else:
        kind = DEFAULT_KIND
    content = body.strip("\n")
    tags = dedup(property_tags(properties) + inline_tags(body))
    title = first_property(properties, "title")
    note = VaultNote(
        relpath=relpath,
        slug=slug,
        name=title.strip() if title else stem,
        kind=kind,
        content=content if content.strip() else None,
        when=valid_date(first_property(properties, "date")) or valid_date(stem),
        tags=tags or None,
        created_at=utc_timestamp(first_property(properties, "created", "created_at", "date created", "creation date")),
    )
    note.link_targets = [link_target(match.group(1)) for match in WIKILINK.finditer(body)]
    return note


def resolve_links(notes):
    by_path = {}
    by_name = {}
    for note in sorted(notes.values(), key=lambda item: (item.relpath.count("/"), item.relpath)):
        path_key = str(PurePosixPath(note.relpath).with_suffix("")).lower()
        by_path[path_key] = note.slug
        by_name.setdefault(PurePosixPath(note.relpath).stem.lower(), note.slug)
    for note in notes.values():
        resolved = []
        for target in note.link_targets:
            slug = by_path.get(target) or (by_name.get(target) if "/" not in target else None)
            if slug and slug != note.slug:
                resolved.append(slug)
        note.link_targets = dedup(resolved)


def graph_rows(query_output):
    return json.loads(query_output).get("rows", [])


def existing_notes(rows):
    notes = {}
    for row in rows:
        if not SAFE_SLUG.fullmatch(row["n.slug"]):
            continue
        tags = row.get("n.tags") or None
        notes[row["n.slug"]] = {
            "comparable": (row.get("n.name"), row.get("n.kind"), row.get("n.content"), row.get("n.when"), tags),
            "created_at": utc_timestamp(row.get("n.createdAt")),
        }
    return notes


def existing_links(rows):
    links = {}
    for row in rows:
        links.setdefault(row["a.slug"], set()).add(row["b.slug"])
    return links


def build_plan(scan, graph_notes, graph_links, now):
    counts = scan.counts
    prune = []
    node_rows = []
    edge_rows = []
    for slug in sorted(set(graph_notes) - set(scan.notes)):
        prune.append(f'delete Note where slug = "{slug}"')
        counts.deleted += 1
    for slug, note in sorted(scan.notes.items()):
        existing = graph_notes.get(slug)
        if existing is None:
            counts.new += 1
        elif existing["comparable"] == note.comparable():
            counts.unchanged += 1
        else:
            counts.updated += 1
        if existing is None or existing["comparable"] != note.comparable():
            created_at = (existing or {}).get("created_at") or note.created_at or now
            node_rows.append({"type": "Note", "data": {
                "slug": slug, "name": note.name, "kind": note.kind, "content": note.content, "when": note.when,
                "tags": note.tags, "createdAt": created_at, "updatedAt": now}})
        current = graph_links.get(slug, set())
        current_vault_targets = {target for target in current if target.startswith(SLUG_PREFIX)}
        desired = set(note.link_targets)
        if desired == current_vault_targets:
            continue
        counts.relinked += 1
        if current:
            prune.append(f'delete RelatedNote where from = "{slug}"')
        kept_foreign = sorted(target for target in current if not target.startswith(SLUG_PREFIX))
        for target in sorted(desired) + kept_foreign:
            edge_rows.append({"edge": "RelatedNote", "from": slug, "to": target})
    return Plan(counts=counts, prune_statements=prune, node_rows=node_rows, edge_rows=edge_rows)


def chunked(rows):
    batch, size = [], 0
    for row in rows:
        line = json.dumps(row, ensure_ascii=False) + "\n"
        if batch and (len(batch) >= ROWS_PER_LOAD_FILE or size + len(line) > BYTES_PER_LOAD_FILE):
            yield batch
            batch, size = [], 0
        batch.append(line)
        size += len(line)
    if batch:
        yield batch


def write_plan(plan, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if plan.prune_statements:
        body = "\n".join(f"    {statement}" for statement in plan.prune_statements)
        (out / "prune.gq").write_text(f"query vault_prune() {{\n{body}\n}}\n", encoding="utf-8")
    index = 0
    for rows in (plan.node_rows, plan.edge_rows):
        for batch in chunked(rows):
            (out / f"load-{index:04d}.ndjson").write_text("".join(batch), encoding="utf-8")
            index += 1


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Plan an Obsidian vault import into the Omnigraph brain graph.")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--client-terms-file", required=True)
    parser.add_argument("--graph-notes", required=True)
    parser.add_argument("--graph-links", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def run(args, now):
    pattern = client_matcher(read_client_terms(args.client_terms_file))
    scan = scan_vault(args.vault, pattern)
    graph_notes = existing_notes(graph_rows(Path(args.graph_notes).read_text(encoding="utf-8")))
    if graph_notes and not scan.notes:
        raise FailClosed(EXIT_EMPTY_VAULT, "vault holds no importable notes; refusing to delete what the brain already has")
    graph_links = existing_links(graph_rows(Path(args.graph_links).read_text(encoding="utf-8")))
    plan = build_plan(scan, graph_notes, graph_links, now)
    write_plan(plan, args.out)
    return plan


def main(argv):
    args = parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        plan = run(args, now)
    except FailClosed as error:
        print(f"vault import refused: {error}", file=sys.stderr)
        return error.exit_code
    print(f"vault import plan: {plan.counts.line()}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
