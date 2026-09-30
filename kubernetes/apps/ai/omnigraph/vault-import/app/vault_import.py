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
SHADOW_PREFIX = "obsidian-file/"
CHUNKER = "obsidian-chunks-v2"
CHUNK_CHARS = 1200
MIN_CHUNK_BUDGET = 400
MIN_CHUNKED_NOTE_CHARS = 80
NOTES_CHUNKED_PER_RUN = 300
CHUNK_CHARS_PER_RUN = 300_000
HEAL_ROWS_PER_RUN = 300
STATEMENTS_PER_PRUNE_FILE = 500
VECTOR_ALLOWANCE_BYTES = 384 * 16
EMBEDDED_TYPES = frozenset({"Note", "Passage"})
WRITER = "vault-import"
HEADING_SEPARATOR = " \u203a "
LINK_ID_PREFIX = "vault:NoteFromArtifact:"
NOTE_KINDS = frozenset({"idea", "journal", "reflection", "insight", "principle", "preference", "quote", "dream", "question", "decision"})
DEFAULT_KIND = "idea"
MAX_NOTE_BYTES = 1024 * 1024
ROWS_PER_LOAD_FILE = 2000
BYTES_PER_LOAD_FILE = 16 * 1024 * 1024
DAILY_FOLDER_NAMES = frozenset({"daily", "daily notes", "dailies", "journal", "journals"})
TEMPLATE_FOLDER_NAMES = frozenset({"templates", "template"})
SAFE_SLUG = re.compile(r"^obsidian/[a-z0-9/-]+$")
SAFE_SHADOW_SLUG = re.compile(r"^obsidian-file/[a-z0-9/-]+$")
MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")
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
    chunked_notes: int = 0
    chunk_deferred: int = 0
    passages_written: int = 0
    unchanged_chunks: int = 0
    passages_deleted: int = 0
    shadows_deleted: int = 0
    heal_planned: int = 0
    vectorless_left: int = 0
    link_conflicts: int = 0

    def line(self):
        return " ".join(f"{key}={value}" for key, value in self.__dict__.items())


@dataclass
class Plan:
    counts: Counts
    prune_groups: list[list[str]]
    node_rows: list[dict]
    passage_units: list[list[dict]]
    edge_rows: list[dict]
    heal_rows: list[dict] = field(default_factory=list)
    embed_plan: dict = field(default_factory=dict)

    @property
    def prune_statements(self):
        return [statement for group in self.prune_groups for statement in group]


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


def graph_rows(snapshot_dir, name):
    path = Path(snapshot_dir) / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("rows", [])


NOTE_FIELDS = ("slug", "name", "kind", "content", "when", "tags", "createdAt", "updatedAt")


def existing_notes(rows):
    notes = {}
    for row in rows:
        if not SAFE_SLUG.fullmatch(row["n.slug"]):
            continue
        tags = row.get("n.tags") or None
        stored = {key: row.get(f"n.{key}") for key in NOTE_FIELDS}
        stored["tags"] = tags
        stored["createdAt"] = utc_timestamp(stored["createdAt"])
        stored["updatedAt"] = utc_timestamp(stored["updatedAt"])
        notes[row["n.slug"]] = {
            "comparable": (row.get("n.name"), row.get("n.kind"), row.get("n.content"), row.get("n.when"), tags),
            "created_at": stored["createdAt"],
            "row": {key: value for key, value in stored.items() if value is not None},
        }
    return notes


def existing_links(rows):
    links = {}
    for row in rows:
        links.setdefault(row["a.slug"], set()).add(row["b.slug"])
    return links


@dataclass
class GraphState:
    notes: dict
    links: dict
    note_vectors: set
    shadows: dict
    passages: dict
    passage_vectors: set
    note_artifacts: dict


def read_graph(snapshot_dir):
    shadows = {}
    for row in graph_rows(snapshot_dir, "vault_shadow_artifacts"):
        if SAFE_SHADOW_SLUG.fullmatch(row.get("a.slug") or ""):
            shadows[row["a.slug"]] = {"content_sha256": row.get("a.content_sha256"), "createdAt": utc_timestamp(row.get("a.createdAt"))}
    passages = {}
    for row in graph_rows(snapshot_dir, "vault_passages"):
        passages.setdefault(row["a.slug"], {})[row["p.@id"]] = {
            "text": row.get("p.text"), "chunk_index": row.get("p.chunk_index"), "createdAt": utc_timestamp(row.get("p.createdAt"))}
    note_artifacts = {}
    for row in graph_rows(snapshot_dir, "vault_note_artifacts"):
        note_artifacts.setdefault(row["n.slug"], set()).add(row["a.slug"])
    return GraphState(
        notes=existing_notes(graph_rows(snapshot_dir, "vault_notes")),
        links=existing_links(graph_rows(snapshot_dir, "vault_links")),
        note_vectors={row["n.slug"] for row in graph_rows(snapshot_dir, "vault_notes_with_vectors")},
        shadows=shadows,
        passages=passages,
        passage_vectors={row["p.@id"] for row in graph_rows(snapshot_dir, "vault_passages_with_vectors")},
        note_artifacts=note_artifacts,
    )


def shadow_slug(note_slug):
    return SHADOW_PREFIX + note_slug[len(SLUG_PREFIX):]


def note_slug_of(shadow):
    return SLUG_PREFIX + shadow[len(SHADOW_PREFIX):]


def chunk_digest(note):
    return hashlib.sha256(f"{CHUNKER}\n{note.name}\n{note.content or ''}".encode("utf-8")).hexdigest()


def sections(content):
    heading = None
    body = []
    fenced = False
    for line in content.split("\n"):
        if FENCE.match(line):
            fenced = not fenced
        match = None if fenced else MARKDOWN_HEADING.match(line)
        if match:
            yield heading, "\n".join(body)
            heading, body = match.group(2).strip(), []
        else:
            body.append(line)
    yield heading, "\n".join(body)


def split_long(paragraph, budget):
    pieces = []
    while len(paragraph) > budget:
        cut = paragraph.rfind(" ", 0, budget)
        cut = cut if cut > budget // 2 else budget
        pieces.append(paragraph[:cut].strip())
        paragraph = paragraph[cut:].strip()
    if paragraph:
        pieces.append(paragraph)
    return pieces


def chunk_header(name, heading):
    header = name.strip() + (HEADING_SEPARATOR + heading if heading else "")
    return header[:CHUNK_CHARS - MIN_CHUNK_BUDGET - 1]


def chunk_note(name, content):
    if content is None or len(content.strip()) < MIN_CHUNKED_NOTE_CHARS:
        return []
    chunks = []
    header, body, budget = None, "", 0
    for heading, text in sections(content):
        paragraphs = [paragraph.strip("\n").rstrip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
        if not paragraphs:
            continue
        labelled = "\n\n".join(([heading] if heading else []) + paragraphs)
        if body and len(body) + 2 + len(labelled) <= budget:
            body = f"{body}\n\n{labelled}"
            continue
        if body:
            chunks.append(f"{header}\n{body}")
        header = chunk_header(name, heading)
        budget = CHUNK_CHARS - len(header) - 1
        body = ""
        for paragraph in paragraphs:
            for piece in split_long(paragraph, budget):
                if body and len(body) + 2 + len(piece) > budget:
                    chunks.append(f"{header}\n{body}")
                    body = piece
                else:
                    body = f"{body}\n\n{piece}" if body else piece
    if body:
        chunks.append(f"{header}\n{body}")
    return chunks


def passage_id(shadow, index):
    return f"{shadow}#{index}"


def link_id(note, shadow):
    return f"{LINK_ID_PREFIX}{note}>{shadow}"


def removal_group(graph, shadow, note=None):
    group = [f'delete Passage where @id = "{pid}"' for pid in sorted(graph.passages.get(shadow, {}))]
    if shadow in graph.shadows:
        group.append(f'delete Artifact where slug = "{shadow}"')
    if note is not None:
        group.append(f'delete Note where slug = "{note}"')
    return group


def plan_chunks(scan, graph, now, counts):
    prune_groups, node_rows, passage_units, edge_rows = [], [], [], []
    touched = set()
    work = []
    for slug, note in sorted(scan.notes.items()):
        shadow = shadow_slug(slug)
        chunks = chunk_note(note.name, note.content)
        stored = graph.passages.get(shadow, {})
        if not chunks:
            if shadow in graph.shadows or stored:
                prune_groups.append(removal_group(graph, shadow))
                touched.update(stored)
                counts.shadows_deleted += shadow in graph.shadows
                counts.passages_deleted += len(stored)
            continue
        wanted = {passage_id(shadow, index): (index, text) for index, text in enumerate(chunks)}
        changed = [(pid, index, text) for pid, (index, text) in wanted.items()
                   if (stored.get(pid) or {}).get("text") != text or (stored.get(pid) or {}).get("chunk_index") != index]
        removed = sorted(set(stored) - set(wanted))
        digest = chunk_digest(note)
        stale_shadow = (graph.shadows.get(shadow) or {}).get("content_sha256") != digest
        linked = graph.note_artifacts.get(slug, set())
        needs_link = shadow not in linked
        counts.unchanged_chunks += len(wanted) - len(changed)
        if changed or removed or stale_shadow or needs_link:
            work.append((slug, note, shadow, changed, removed, digest, stale_shadow, needs_link, linked, stored))
    work.sort(key=lambda item: (item[2] not in graph.shadows, item[0]))
    budget = CHUNK_CHARS_PER_RUN
    for index, (slug, note, shadow, changed, removed, digest, stale_shadow, needs_link, linked, stored) in enumerate(work):
        cost = sum(len(text) for _, _, text in changed)
        if counts.chunked_notes >= NOTES_CHUNKED_PER_RUN or (counts.chunked_notes and cost > budget):
            counts.chunk_deferred = len(work) - index
            break
        budget -= cost
        counts.chunked_notes += 1
        if stale_shadow or shadow not in graph.shadows:
            node_rows.append({"type": "Artifact", "data": {
                "slug": shadow, "name": note.name, "kind": "document", "source": "notes-app", "content_sha256": digest,
                "timestamp": now, "createdAt": (graph.shadows.get(shadow) or {}).get("createdAt") or now, "updatedAt": now}})
        for pid, chunk_index, text in changed:
            row = {"type": "Passage", "id": pid, "data": {"text": text, "chunk_index": chunk_index, "createdAt": now}}
            passage_units.append([row] if pid in stored else [row, {"edge": "PassageOf", "from": pid, "to": shadow}])
            touched.add(pid)
            counts.passages_written += 1
        if removed:
            prune_groups.append([f'delete Passage where @id = "{pid}"' for pid in removed])
            touched.update(removed)
            counts.passages_deleted += len(removed)
        if needs_link:
            if linked:
                counts.link_conflicts += 1
            else:
                edge_rows.append({"edge": "NoteFromArtifact", "id": link_id(slug, shadow), "from": slug, "to": shadow})
    return prune_groups, node_rows, passage_units, edge_rows, touched


def plan_heal(scan, graph, rewritten_notes, touched, counts, now):
    candidates = []
    for slug, stored in graph.notes.items():
        row = stored["row"]
        if slug in scan.notes and slug not in rewritten_notes and slug not in graph.note_vectors and str(row.get("content") or "").strip():
            candidates.append(("Note", slug, row.get("updatedAt") or row.get("createdAt")))
    for shadow, chunks in graph.passages.items():
        for pid, chunk in chunks.items():
            if pid not in graph.passage_vectors and pid not in touched and str(chunk.get("text") or "").strip():
                candidates.append(("Passage", pid, chunk.get("createdAt")))
    candidates.sort(key=lambda item: (item[2] or "", item[0], item[1]))
    chosen, rest = candidates[:HEAL_ROWS_PER_RUN], candidates[HEAL_ROWS_PER_RUN:]
    passage_rows = {pid: chunk for chunks in graph.passages.values() for pid, chunk in chunks.items()}
    heal_rows, heal_since = [], {}
    for type_name, identifier, since in chosen:
        if type_name == "Note":
            heal_rows.append({"type": "Note", "data": dict(graph.notes[identifier]["row"])})
        else:
            chunk = passage_rows[identifier]
            heal_rows.append({"type": "Passage", "id": identifier, "data": {
                "text": chunk["text"], "chunk_index": chunk["chunk_index"], "createdAt": chunk["createdAt"] or now}})
        heal_since[f"{type_name}|{identifier}"] = since or now
    counts.heal_planned = len(heal_rows)
    counts.vectorless_left = len(rest)
    return heal_rows, {"writer": WRITER, "missing": [{"type": type_name, "since": since or now} for type_name, _, since in rest], "heal_since": heal_since}


def build_plan(scan, graph, now):
    counts = scan.counts
    prune_groups = []
    node_rows = []
    edge_rows = []
    rewritten = set()
    pruned_passages = set()
    for slug in sorted(set(graph.notes) - set(scan.notes)):
        shadow = shadow_slug(slug)
        prune_groups.append(removal_group(graph, shadow, note=slug))
        pruned_passages.update(graph.passages.get(shadow, {}))
        counts.deleted += 1
        counts.shadows_deleted += shadow in graph.shadows
        counts.passages_deleted += len(graph.passages.get(shadow, {}))
    for shadow in sorted(set(graph.shadows) | set(graph.passages)):
        note = note_slug_of(shadow)
        if note not in scan.notes and note not in graph.notes:
            prune_groups.append(removal_group(graph, shadow))
            pruned_passages.update(graph.passages.get(shadow, {}))
            counts.shadows_deleted += shadow in graph.shadows
            counts.passages_deleted += len(graph.passages.get(shadow, {}))
    for slug, note in sorted(scan.notes.items()):
        existing = graph.notes.get(slug)
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
            rewritten.add(slug)
        current = graph.links.get(slug, set())
        current_vault_targets = {target for target in current if target.startswith(SLUG_PREFIX)}
        desired = set(note.link_targets)
        if desired == current_vault_targets:
            continue
        counts.relinked += 1
        if current:
            prune_groups.append([f'delete RelatedNote where from = "{slug}"'])
        kept_foreign = sorted(target for target in current if not target.startswith(SLUG_PREFIX))
        for target in sorted(desired) + kept_foreign:
            edge_rows.append({"edge": "RelatedNote", "from": slug, "to": target})
    chunk_prunes, shadow_rows, passage_units, link_rows, touched = plan_chunks(scan, graph, now, counts)
    heal_rows, embed_plan = plan_heal(scan, graph, rewritten, touched | pruned_passages, counts, now)
    return Plan(counts=counts, prune_groups=prune_groups + chunk_prunes, node_rows=node_rows + shadow_rows, passage_units=passage_units,
                edge_rows=edge_rows + link_rows, heal_rows=heal_rows, embed_plan=embed_plan)


def row_bytes(row, line):
    return len(line.encode("utf-8")) + (VECTOR_ALLOWANCE_BYTES if row.get("type") in EMBEDDED_TYPES else 0)


def batched_units(units):
    batch, rows, size = [], 0, 0
    for unit in units:
        lines = [json.dumps(row, ensure_ascii=False) + "\n" for row in unit]
        unit_size = sum(row_bytes(row, line) for row, line in zip(unit, lines))
        if batch and (rows + len(lines) > ROWS_PER_LOAD_FILE or size + unit_size > BYTES_PER_LOAD_FILE):
            yield batch
            batch, rows, size = [], 0, 0
        batch.extend(lines)
        rows += len(lines)
        size += unit_size
    if batch:
        yield batch


def prune_files(groups):
    batch = []
    for group in groups:
        if batch and len(batch) + len(group) > STATEMENTS_PER_PRUNE_FILE:
            yield batch
            batch = []
        batch.extend(group)
    if batch:
        yield batch


def write_plan(plan, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for number, statements in enumerate(prune_files(plan.prune_groups)):
        body = "\n".join(f"    {statement}" for statement in statements)
        (out / f"prune-{number:04d}.gq").write_text(f"query vault_prune() {{\n{body}\n}}\n", encoding="utf-8")
    index = 0
    for units in ([[row] for row in plan.node_rows], plan.passage_units, [[row] for row in plan.edge_rows]):
        for batch in batched_units(units):
            (out / f"load-{index:04d}.ndjson").write_text("".join(batch), encoding="utf-8")
            index += 1
    for number, batch in enumerate(batched_units([[row] for row in plan.heal_rows])):
        (out / f"heal-{number:04d}.ndjson").write_text("".join(batch), encoding="utf-8")
    (out / "embed-plan.json").write_text(json.dumps(plan.embed_plan), encoding="utf-8")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Plan an Obsidian vault import into the Omnigraph brain graph.")
    parser.add_argument("--vault", required=True)
    parser.add_argument("--client-terms-file", required=True)
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--out", required=True)
    return parser.parse_args(argv)


def run(args, now):
    pattern = client_matcher(read_client_terms(args.client_terms_file))
    scan = scan_vault(args.vault, pattern)
    graph = read_graph(args.snapshot_dir)
    if graph.notes and not scan.notes:
        raise FailClosed(EXIT_EMPTY_VAULT, "vault holds no importable notes; refusing to delete what the brain already has")
    plan = build_plan(scan, graph, now)
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
