#!/usr/bin/env python3
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import math
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

EXTRACTOR = "v1"
DERIVED = "derived/"
STATE_PREFIX = "derived/distill/"
OWNED_EDGE_PREFIX = "derived:"
ENTITY_PREFIXES = {
    "Topic": "derived/topic/",
    "Person": "derived/person/",
    "Organization": "derived/org/",
    "Place": "derived/place/",
    "Area": "derived/area/",
}
ENTITY_TYPES = tuple(ENTITY_PREFIXES)
IMPORTER_PREFIXES = ("obsidian/", "forge/")
MAX_INPUT_CHARS = 12000
MAX_TOPICS = 6
MAX_ALIASES = 8
MERGE_CANDIDATES = 3
ROWS_PER_LOAD_FILE = 2000
BYTES_PER_LOAD_FILE = 16 * 1024 * 1024
STATEMENTS_PER_PRUNE_FILE = 500
HTTP_TIMEOUT_SECONDS = 120
EMBED_BATCH = 64
EMBEDDING_DIMENSION = 384
FAILED_SHARE_THAT_FAILS_THE_RUN = 0.2
SAME_TOPIC_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["same"], "properties": {"same": {"type": "boolean"}}}

EXIT_OK = 0
EXIT_NOTHING_VISIBLE = 5
EXIT_LLM_UNREACHABLE = 6

EDGE_FOR = {
    ("Note", "Topic"): "NoteAboutTopic",
    ("Note", "Person"): "NoteAboutPerson",
    ("Note", "Organization"): "NoteAboutOrganization",
    ("Note", "Project"): "NoteAboutProject",
    ("Note", "Place"): "NoteAboutPlace",
    ("Note", "Area"): "NoteAboutArea",
    ("Artifact", "Topic"): "ArtifactAboutTopic",
    ("Artifact", "Person"): "MentionsPerson",
    ("Artifact", "Organization"): "ArtifactAboutOrganization",
    ("Artifact", "Project"): "ArtifactAboutProject",
    ("Project", "Topic"): "ProjectAboutTopic",
    ("Project", "Area"): "ProjectInArea",
}
MENTION_EDGES = frozenset({"MentionsPerson"})
IMPORTER_MANAGED = {
    "forge/": frozenset({"NoteAboutProject", "ArtifactForProject", "ArtifactFromPerson", "NoteFromArtifact", "ProjectForOrganization"}),
    "obsidian/": frozenset({"RelatedNote"}),
}
TOPIC_EDGES = ("NoteAboutTopic", "ArtifactAboutTopic", "ProjectAboutTopic")
RELATED = "TopicRelatedTopic"
LEGAL_SUFFIX = re.compile(r"\b(b\.?\s?v\.?|n\.?\s?v\.?|inc\.?|ltd\.?|llc|gmbh|vof|v\.o\.f\.)$")


@dataclass
class Settings:
    model: str
    embed_model: str
    candidate_similarity: float
    same_similarity: float
    related_min_documents: int
    max_documents: int
    max_spend_usd: float
    workers: int


@dataclass
class Counts:
    documents: int = 0
    pending: int = 0
    processed: int = 0
    failed: int = 0
    skipped_budget: int = 0
    sources_gone: int = 0
    edges_added: int = 0
    edges_removed: int = 0
    entities_created: int = 0
    entities_deleted: int = 0
    topics_created: int = 0
    aliases_added: int = 0
    topics_merged: int = 0
    merge_questions: int = 0
    merge_failures: int = 0
    related_written: int = 0
    related_removed: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0

    def line(self):
        return " ".join(f"{key}={round(value, 4) if isinstance(value, float) else value}" for key, value in self.__dict__.items())


@dataclass
class Document:
    slug: str
    type: str
    title: str
    text: str
    digest: str
    project: str | None = None


@dataclass
class Entity:
    type: str
    slug: str
    name: str
    data: dict
    derived: bool
    vector: list | None = None
    dirty: bool = False
    new: bool = False


@dataclass
class Edge:
    type: str
    source: str
    target: str
    id: str | None = None
    data: dict = field(default_factory=dict)

    @property
    def owned(self):
        return bool(self.id) and self.id.startswith(OWNED_EDGE_PREFIX)


@dataclass
class Plan:
    counts: Counts
    prune_statements: list
    node_rows: list
    edge_rows: list
    state_rows: list


class ExtractionFailed(Exception):
    pass


class LLMUnreachable(Exception):
    pass


class FailClosed(Exception):
    def __init__(self, exit_code, message):
        super().__init__(message)
        self.exit_code = exit_code


def ascii_fold(text):
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def slug_segment(text):
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(text)).strip("-")[:80].strip("-")


def name_key(text):
    folded = ascii_fold(text).strip()
    folded = LEGAL_SUFFIX.sub("", folded).strip()
    folded = re.sub(r"^(the|de|het|een|a|an)\s+", "", folded)
    key = re.sub(r"[^a-z0-9]+", "", folded)
    if len(key) > 4 and key.endswith("ies"):
        return key[:-3] + "y"
    if len(key) > 4 and key.endswith("s") and not key.endswith("ss"):
        return key[:-1]
    return key


def sha256(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def edge_id(edge_type, source, target):
    return f"{OWNED_EDGE_PREFIX}{edge_type}:{source}>{target}"


def gq_string(value):
    return json.dumps(value, ensure_ascii=False)


def iso_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rows(snapshot_dir, name):
    path = Path(snapshot_dir) / f"{name}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("rows", [])


def column(row, name):
    for key, value in row.items():
        if key.split(".", 1)[-1] == name:
            return value
    return None


def compose(kind, title, parts):
    body = "\n\n".join(part.strip() for part in parts if part and part.strip())
    text = f"Document kind: {kind}\nTitle: {title}\n\n{body}"
    return text[:MAX_INPUT_CHARS]


@dataclass
class Graph:
    documents: dict
    entities: dict
    state: dict
    edges: list


def read_graph(snapshot_dir):
    documents = {}
    artifacts = {row["n.slug"]: row for row in rows(snapshot_dir, "distill_artifacts") if row.get("n.slug")}
    for row in rows(snapshot_dir, "distill_notes"):
        slug = row.get("n.slug")
        if not slug or slug.startswith(DERIVED):
            continue
        tags = ", ".join(row.get("n.tags") or [])
        text = compose("Obsidian note" if slug.startswith("obsidian/") else "note", row.get("n.name") or slug, [f"Tags: {tags}" if tags else "", row.get("n.content")])
        documents[slug] = Document(slug, "Note", row.get("n.name") or slug, text, sha256(text))
    for slug, row in artifacts.items():
        if slug.startswith(DERIVED):
            continue
        text = compose(f"Forgejo {row.get('n.kind') or 'document'}" if slug.startswith("forge/") else row.get("n.kind") or "document", row.get("n.name") or slug, [row.get("n.content")])
        project = slug.split("/", 3)
        owning = "/".join(project[:3]) if slug.startswith("forge/") and len(project) > 3 else None
        documents[slug] = Document(slug, "Artifact", row.get("n.name") or slug, text, sha256(text), project=owning)
    for row in rows(snapshot_dir, "distill_projects"):
        slug = row.get("n.slug")
        if not slug or slug.startswith(DERIVED):
            continue
        readme = artifacts.get(f"{slug}/readme", {})
        tags = ", ".join(row.get("n.tags") or [])
        text = compose("project", row.get("n.name") or slug, [row.get("n.brief"), f"Tags: {tags}" if tags else "", row.get("n.description"), readme.get("n.content")])
        documents[slug] = Document(slug, "Project", row.get("n.name") or slug, text, sha256(text), project=slug)
    entities = {}
    for node_type, query in (("Person", "distill_people"), ("Organization", "distill_orgs"), ("Place", "distill_places"), ("Area", "distill_areas"), ("Topic", "distill_topics"), ("Project", "distill_projects")):
        for row in rows(snapshot_dir, query):
            slug = row.get("n.slug")
            if not slug:
                continue
            data = {key.split(".", 1)[1]: value for key, value in row.items() if key != "n.embedding"}
            entities[slug] = Entity(node_type, slug, data.get("name") or slug, data, slug.startswith(DERIVED), vector=row.get("n.embedding"))
    state = {}
    for row in rows(snapshot_dir, "distill_state"):
        if row.get("n.source"):
            state[row["n.source"]] = {key.split(".", 1)[1]: value for key, value in row.items()}
    edges = []
    for path in sorted(Path(snapshot_dir).glob("edge_*.json")):
        edge_type = path.stem.split("_", 2)[1]
        for row in json.loads(path.read_text(encoding="utf-8")).get("rows", []):
            data = {"documents": row["e.documents"]} if row.get("e.documents") is not None else {}
            edges.append(Edge(edge_type, row["s.@id"], row["t.@id"], id=row.get("e.@id"), data=data))
    unique = {}
    for edge in edges:
        unique[edge.id or (edge.type, edge.source, edge.target)] = edge
    return Graph(documents=documents, entities=entities, state=state, edges=list(unique.values()))


class LiteLLM:
    def __init__(self, base_url, key, counts):
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.counts = counts

    def post(self, path, body):
        request = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode("utf-8"),
                                         headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                cost = response.headers.get("x-litellm-response-cost")
                return json.loads(response.read().decode("utf-8")), float(cost) if cost else 0.0
        except urllib.error.HTTPError as error:
            error.close()
            raise ExtractionFailed(f"litellm {path} answered HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise LLMUnreachable(f"litellm {path} not reachable: {error}") from error

    def embed(self, model, texts):
        vectors = []
        for start in range(0, len(texts), EMBED_BATCH):
            body, _ = self.post("/v1/embeddings", {"model": model, "input": texts[start:start + EMBED_BATCH]})
            batch = sorted(body.get("data") or [], key=lambda item: item.get("index", 0))
            if len(batch) != len(texts[start:start + EMBED_BATCH]):
                raise ExtractionFailed("embedding response is missing vectors")
            vectors.extend(item["embedding"] for item in batch)
        return vectors

    def same_topic(self, model, system, pair):
        try:
            return self.ask_same_topic(model, system, pair)
        except (ExtractionFailed, LLMUnreachable):
            self.counts.merge_failures += 1
            return False

    def ask_same_topic(self, model, system, pair):
        body, cost = self.post("/v1/chat/completions", {
            "model": model,
            "temperature": 0,
            "max_tokens": 1000,
            "reasoning_effort": "low",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": f"A: {pair[0]}\nB: {pair[1]}"}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "same_topic", "strict": True, "schema": SAME_TOPIC_SCHEMA}},
        })
        self.counts.cost_usd += cost
        usage = body.get("usage") or {}
        self.counts.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.counts.completion_tokens += int(usage.get("completion_tokens") or 0)
        content = ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
        try:
            return json.loads(content).get("same") is True
        except (TypeError, ValueError, AttributeError):
            return False

    def extract(self, model, system, schema, text):
        body, cost = self.post("/v1/chat/completions", {
            "model": model,
            "temperature": 0,
            "max_tokens": 4000,
            "reasoning_effort": "low",
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "document_entities", "strict": True, "schema": schema}},
        })
        usage = body.get("usage") or {}
        choice = (body.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content")
        return content, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0), cost


def parse_extraction(content, schema):
    if not isinstance(content, str) or not content.strip():
        raise ExtractionFailed("empty extraction")
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ExtractionFailed("extraction is not JSON") from error
    if not isinstance(data, dict):
        raise ExtractionFailed("extraction is not an object")
    properties = schema["properties"]
    clean = {}
    for key, spec in properties.items():
        items = data.get(key) or []
        if not isinstance(items, list):
            raise ExtractionFailed(f"extraction field {key} is not a list")
        item_spec = spec["items"]
        if item_spec.get("type") == "string":
            allowed = set(item_spec.get("enum") or [])
            clean[key] = sorted({item for item in items if isinstance(item, str) and (not allowed or item in allowed)})
            continue
        kept = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
                continue
            entry = {"name": re.sub(r"\s+", " ", name.strip()), "about": item.get("about") is True}
            for prop, prop_spec in item_spec["properties"].items():
                if prop in ("name", "about"):
                    continue
                value = item.get(prop)
                if prop_spec.get("enum"):
                    value = value if value in prop_spec["enum"] else None
                elif prop_spec.get("type") == "array":
                    value = [alias.strip() for alias in value if isinstance(alias, str) and alias.strip()][:MAX_ALIASES] if isinstance(value, list) else []
                elif prop_spec.get("type") == "string":
                    value = value.strip()[:300] if isinstance(value, str) else ""
                entry[prop] = value
            kept.append(entry)
        clean[key] = kept
    clean["topics"] = [topic for topic in clean["topics"] if topic["about"]][:MAX_TOPICS]
    return clean


def unit(vector):
    norm = math.sqrt(sum(value * value for value in vector))
    return tuple(value / norm for value in vector) if norm else None


def dot(left, right):
    return math.sumprod(left, right)


class Resolver:
    def __init__(self, entities, settings, embedder):
        self.settings = settings
        self.embedder = embedder
        self.entities = entities
        self.by_key = {}
        self.topic_units = {}
        self.name_vectors = {}
        self.merged = {}
        for entity in sorted(entities.values(), key=lambda item: (not item.derived, item.slug)):
            self.index(entity)

    def prepare(self, extractions):
        missing = []
        for extraction in extractions:
            for topic in extraction["topics"]:
                if self.exact("Topic", [topic["name"]] + list(topic.get("aliases") or [])) is None and topic["name"] not in self.name_vectors:
                    self.name_vectors[topic["name"]] = None
                    missing.append(topic["name"])
        if missing:
            for name, vector in zip(missing, self.embedder(missing)):
                self.name_vectors[name] = vector

    def keys_for(self, entity):
        keys = {name_key(entity.name)}
        if entity.type == "Topic":
            keys |= {name_key(alias) for alias in entity.data.get("aliases") or []}
        if entity.type == "Person":
            first, last = entity.data.get("first_name"), entity.data.get("last_name")
            if first and last:
                keys.add(name_key(f"{first} {last}"))
        if entity.type == "Project":
            repo = entity.name.split("/")[-1]
            keys.add(name_key(repo))
        return {key for key in keys if key}

    def index(self, entity):
        if entity.type == "Topic" and entity.vector and entity.slug not in self.topic_units:
            normalised = unit(entity.vector)
            if normalised:
                self.topic_units[entity.slug] = normalised
        for key in self.keys_for(entity):
            self.by_key.setdefault((entity.type, key), [])
            if entity.slug not in self.by_key[(entity.type, key)]:
                self.by_key[(entity.type, key)].append(entity.slug)

    def exact(self, entity_type, names):
        for name in names:
            candidates = self.by_key.get((entity_type, name_key(name)), [])
            if entity_type == "Project" and len(candidates) > 1:
                preferred = [slug for slug in candidates if not set(self.entities[slug].data.get("tags") or []) & {"mirror", "fork"}]
                candidates = preferred if len(preferred) == 1 else []
            if candidates:
                return self.entities[candidates[0]]
        return None

    def merge_candidates(self):
        ranked = {}
        for entity in sorted(self.entities.values(), key=lambda item: item.slug):
            if entity.type != "Topic" or not entity.new or entity.slug in self.merged:
                continue
            probe = self.topic_units.get(entity.slug)
            if probe is None:
                continue
            scored = []
            for slug, candidate in self.topic_units.items():
                other = self.entities[slug]
                if slug == entity.slug or slug in self.merged or (other.new and slug > entity.slug):
                    continue
                similarity = dot(probe, candidate)
                if similarity >= self.settings.candidate_similarity:
                    scored.append((similarity, slug))
            if scored:
                ranked[entity.slug] = sorted(scored, reverse=True)[:MERGE_CANDIDATES]
        return ranked

    def merge_similar(self, same_topic, counts):
        ranked = self.merge_candidates()
        questions = sorted({(slug, other) for slug, scored in ranked.items() for similarity, other in scored if similarity < self.settings.same_similarity})
        answers = same_topic([(self.describe(slug), self.describe(other)) for slug, other in questions]) if questions else []
        confirmed = {pair for pair, same in zip(questions, answers) if same}
        counts.merge_questions += len(questions)
        for slug in sorted(ranked):
            for similarity, other in ranked[slug]:
                target = self.canonical(other)
                if target == slug or self.canonical(slug) != slug:
                    continue
                if similarity >= self.settings.same_similarity or (slug, other) in confirmed:
                    keeper = self.entities[target]
                    duplicate = self.entities[slug]
                    self.merged[slug] = target
                    self.topic_units.pop(slug, None)
                    self.add_aliases(keeper, [duplicate.name] + list(duplicate.data.get("aliases") or []), counts)
                    counts.topics_merged += 1
                    break

    def describe(self, slug):
        entity = self.entities[slug]
        description = entity.data.get("description")
        return f"{entity.name} ({description})" if description else entity.name

    def resolve_topic(self, topic, now, counts):
        names = [topic["name"]] + list(topic.get("aliases") or [])
        found = self.exact("Topic", names)
        if found is not None:
            self.absorb_duplicates(found, names, counts)
            self.add_aliases(found, names, counts)
            return found
        slug = self.fresh_slug("Topic", topic["name"])
        aliases = sorted({alias for alias in topic.get("aliases") or [] if name_key(alias) != name_key(topic["name"])})[:MAX_ALIASES]
        entity = Entity("Topic", slug, topic["name"], {"slug": slug, "name": topic["name"], "description": topic.get("description") or None,
                                                         "aliases": aliases, "createdAt": now}, True, vector=self.name_vectors.get(topic["name"]), dirty=True, new=True)
        self.register(entity, counts)
        counts.topics_created += 1
        return entity

    def canonical(self, slug):
        while slug in self.merged:
            slug = self.merged[slug]
        return slug

    def absorb_duplicates(self, keeper, names, counts):
        if not keeper.derived:
            return
        for name in names:
            for slug in list(self.by_key.get(("Topic", name_key(name)), [])):
                duplicate = self.entities.get(slug)
                if duplicate is None or slug == keeper.slug or not duplicate.derived or slug in self.merged:
                    continue
                self.merged[slug] = keeper.slug
                self.topic_units.pop(slug, None)
                for key in self.keys_for(duplicate):
                    self.by_key[("Topic", key)] = [item for item in self.by_key.get(("Topic", key), []) if item != slug]
                self.add_aliases(keeper, [duplicate.name] + list(duplicate.data.get("aliases") or []), counts)
                counts.topics_merged += 1

    def add_aliases(self, entity, names, counts):
        if not entity.derived or entity.type != "Topic":
            return
        known = {name_key(entity.name)} | {name_key(alias) for alias in entity.data.get("aliases") or []}
        aliases = list(entity.data.get("aliases") or [])
        for name in names:
            if name_key(name) and name_key(name) not in known and len(aliases) < MAX_ALIASES:
                aliases.append(name)
                known.add(name_key(name))
                counts.aliases_added += 1
                entity.dirty = True
        entity.data["aliases"] = aliases
        self.index(entity)

    def fresh_slug(self, entity_type, name):
        base = ENTITY_PREFIXES[entity_type] + (slug_segment(name) or sha256(name)[:12])
        slug, suffix = base, 2
        while slug in self.entities:
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug

    def register(self, entity, counts):
        self.entities[entity.slug] = entity
        self.index(entity)
        counts.entities_created += 1

    def resolve_named(self, entity_type, item, now, counts, may_create):
        found = self.exact(entity_type, [item["name"]])
        if found is not None or not may_create:
            return found
        slug = self.fresh_slug(entity_type, item["name"])
        data = {"slug": slug, "name": item["name"], "createdAt": now}
        if entity_type == "Person":
            data.update({"relation": item.get("relation") or "acquaintance", "brief": "Named in Ryan's documents; created by the distiller"})
        elif entity_type == "Organization":
            data.update({"kind": item.get("kind") or "company", "brief": "Named in Ryan's documents; created by the distiller"})
        elif entity_type == "Place":
            data.update({"kind": item.get("kind") or "other", "brief": "Named in Ryan's documents; created by the distiller"})
        entity = Entity(entity_type, slug, item["name"], data, True, dirty=True, new=True)
        self.register(entity, counts)
        return entity

    def resolve_area(self, kind, now, counts):
        for entity in sorted(self.entities.values(), key=lambda item: (item.derived, item.slug)):
            if entity.type == "Area" and entity.data.get("kind") == kind:
                return entity
        slug = ENTITY_PREFIXES["Area"] + kind
        entity = Entity("Area", slug, kind.capitalize(), {"slug": slug, "name": kind.capitalize(), "kind": kind, "status": "active",
                                                          "brief": "Area of life or work; created by the distiller", "createdAt": now}, True, dirty=True, new=True)
        self.register(entity, counts)
        return entity


def importer_owns(edge_type, source):
    return any(source.startswith(prefix) and edge_type in managed for prefix, managed in IMPORTER_MANAGED.items())


def desired_links(document, extraction, resolver, now, counts):
    links = set()

    def link(target_type, entity):
        if entity is None:
            return
        edge_type = EDGE_FOR.get((document.type, target_type))
        if edge_type is None or importer_owns(edge_type, document.slug) or entity.slug == document.slug:
            return
        if target_type == "Project" and document.project and entity.slug == document.project:
            return
        links.add((edge_type, entity.slug))

    for topic in extraction["topics"]:
        link("Topic", resolver.resolve_topic(topic, now, counts))
    for key, entity_type in (("people", "Person"), ("organizations", "Organization"), ("places", "Place")):
        for item in extraction[key]:
            if not item["about"] and (document.type, entity_type) not in (("Artifact", "Person"),):
                continue
            link(entity_type, resolver.resolve_named(entity_type, item, now, counts, may_create=item["about"]))
    for item in extraction["projects"]:
        if item["about"]:
            link("Project", resolver.exact("Project", [item["name"]]))
    for kind in extraction["areas"]:
        if (document.type, "Area") in EDGE_FOR:
            link("Area", resolver.resolve_area(kind, now, counts))
    return links


def run_extractions(documents, client, settings, system, schema, counts):
    results = {}
    queue = iter(documents)
    remaining = len(documents)
    unreachable = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=settings.workers) as pool:
        inflight = {}
        while True:
            while len(inflight) < settings.workers and counts.cost_usd < settings.max_spend_usd:
                document = next(queue, None)
                if document is None:
                    break
                remaining -= 1
                inflight[pool.submit(client.extract, settings.model, system, schema, document.text)] = document
            if not inflight:
                break
            done, _ = concurrent.futures.wait(inflight, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                document = inflight.pop(future)
                try:
                    content, prompt_tokens, completion_tokens, cost = future.result()
                    counts.prompt_tokens += prompt_tokens
                    counts.completion_tokens += completion_tokens
                    counts.cost_usd += cost
                    results[document.slug] = parse_extraction(content, schema)
                    counts.processed += 1
                except LLMUnreachable:
                    unreachable += 1
                    counts.failed += 1
                except ExtractionFailed:
                    counts.failed += 1
            if unreachable >= settings.workers and not results:
                for future in inflight:
                    future.cancel()
                raise FailClosed(EXIT_LLM_UNREACHABLE, "litellm not reachable; nothing was extracted")
    counts.skipped_budget += remaining
    return results


def pending_documents(graph, settings):
    pending = []
    for slug, document in graph.documents.items():
        state = graph.state.get(slug)
        if state is None or state.get("content_sha256") != document.digest or state.get("extractor") != extractor_version(settings):
            pending.append(document)
    order = {"Note": 0, "Project": 1, "Artifact": 2}
    pending.sort(key=lambda document: (order[document.type], document.slug))
    return pending


def extractor_version(settings):
    return f"{EXTRACTOR}:{settings.model}"


def related_pairs(edges_by_source, settings, live_topics):
    counts = {}
    for targets in edges_by_source.values():
        topics = sorted({target for target in targets if target in live_topics})
        for index, left in enumerate(topics):
            for right in topics[index + 1:]:
                counts[(left, right)] = counts.get((left, right), 0) + 1
    return {pair: count for pair, count in counts.items() if count >= settings.related_min_documents}


def edge_key(edge):
    return edge.id or f"{edge.type}:{edge.source}>{edge.target}"


def build_plan(graph, extractions, resolver, settings, counts, now, same_topic):
    prune_edges, prune_nodes, prune_state = [], [], []
    node_rows, edge_rows, state_rows = [], [], []
    live_edges = {edge_key(edge): edge for edge in graph.edges}
    by_source = {}
    for key, edge in live_edges.items():
        by_source.setdefault(edge.source, set()).add(key)
    for source in sorted(set(graph.state) - set(graph.documents)):
        prune_state.append(f"delete Distillation where slug = {gq_string(STATE_PREFIX + source)}")
        counts.sources_gone += 1
    resolver.prepare(extractions[slug] for slug in sorted(extractions))
    wanted_by_document = {slug: desired_links(graph.documents[slug], extractions[slug], resolver, now, counts) for slug in sorted(extractions)}
    resolver.merge_similar(same_topic, counts)
    for slug in sorted(by_source):
        if slug in wanted_by_document:
            continue
        for key in sorted(by_source[slug]):
            edge = live_edges[key]
            if edge.owned and edge.type != RELATED and resolver.canonical(edge.target) != edge.target:
                wanted_by_document[slug] = {(other.type, other.target) for other in (live_edges[item] for item in by_source[slug]) if other.owned and other.type != RELATED}
                break
    for slug in sorted(wanted_by_document):
        document = graph.documents.get(slug)
        wanted = {(edge_type, resolver.canonical(target)) for edge_type, target in wanted_by_document[slug]}
        mine = [live_edges[key] for key in by_source.get(slug, ())]
        owned = {(edge.type, edge.target): edge for edge in mine if edge.owned and edge.type != RELATED}
        foreign = {(edge.type, edge.target) for edge in mine if not edge.owned}
        for pair in sorted(set(owned) - (wanted - foreign)):
            edge = owned[pair]
            live_edges.pop(edge_key(edge))
            prune_edges.append(f"delete {edge.type} where @id = {gq_string(edge.id)}")
            counts.edges_removed += 1
        for edge_type, target in sorted(wanted - set(owned) - foreign):
            identifier = edge_id(edge_type, slug, target)
            live_edges[identifier] = Edge(edge_type, slug, target, id=identifier)
            edge_rows.append({"edge": edge_type, "id": identifier, "from": slug, "to": target})
            counts.edges_added += 1
        if slug not in extractions:
            continue
        existing = graph.state.get(slug) or {}
        state_rows.append({"type": "Distillation", "data": {
            "slug": STATE_PREFIX + slug, "source": slug, "content_sha256": document.digest, "extractor": extractor_version(settings),
            "processedAt": now, "createdAt": iso_timestamp(existing.get("createdAt")) or now, "updatedAt": now}})
    referenced = {}
    for edge in live_edges.values():
        if edge.type == RELATED and edge.owned:
            continue
        for endpoint in (edge.source, edge.target):
            referenced[endpoint] = referenced.get(endpoint, 0) + 1
    doomed = set()
    for entity in sorted(resolver.entities.values(), key=lambda item: item.slug):
        if not entity.derived or entity.type not in ENTITY_TYPES or referenced.get(entity.slug):
            continue
        doomed.add(entity.slug)
        if entity.new:
            counts.entities_created -= 1
            counts.topics_created -= entity.type == "Topic"
        else:
            prune_nodes.append(f"delete {entity.type} where slug = {gq_string(entity.slug)}")
            counts.entities_deleted += 1
    for key in [key for key, edge in live_edges.items() if edge.source in doomed or edge.target in doomed]:
        live_edges.pop(key)
    for entity in sorted(resolver.entities.values(), key=lambda item: (item.type, item.slug)):
        if not entity.derived or not entity.dirty or entity.slug in doomed:
            continue
        data = {key: value for key, value in entity.data.items() if value is not None and key not in ("@id", "embedding")}
        data["createdAt"] = iso_timestamp(data.get("createdAt")) or now
        data["updatedAt"] = now
        if entity.type == "Topic":
            entity.vector = entity.vector or resolver.name_vectors.get(entity.name) or resolver.embedder([entity.name])[0]
            data["embedding"] = entity.vector
        node_rows.append({"type": entity.type, "data": data})
    live_topics = {slug for slug, entity in resolver.entities.items() if entity.type == "Topic" and slug not in doomed}
    topic_links = {}
    for edge in live_edges.values():
        if edge.type in TOPIC_EDGES:
            topic_links.setdefault(edge.source, set()).add(edge.target)
    wanted_related = related_pairs(topic_links, settings, live_topics)
    current_related = {(edge.source, edge.target): edge for edge in live_edges.values() if edge.type == RELATED and edge.owned}
    for pair in sorted(set(current_related) - set(wanted_related)):
        prune_edges.append(f"delete {RELATED} where @id = {gq_string(current_related[pair].id)}")
        counts.related_removed += 1
    for pair, documents in sorted(wanted_related.items()):
        current = current_related.get(pair)
        if current is not None and current.data.get("documents") == documents:
            continue
        edge_rows.append({"edge": RELATED, "id": edge_id(RELATED, *pair), "from": pair[0], "to": pair[1], "data": {"documents": documents}})
        counts.related_written += 1
    return Plan(counts=counts, prune_statements=prune_edges + prune_nodes + prune_state, node_rows=node_rows, edge_rows=edge_rows, state_rows=state_rows)


def batched(rows_to_write):
    batch, size = [], 0
    for row in rows_to_write:
        line = json.dumps(row, ensure_ascii=False) + "\n"
        encoded = len(line.encode("utf-8"))
        if batch and (len(batch) >= ROWS_PER_LOAD_FILE or size + encoded > BYTES_PER_LOAD_FILE):
            yield batch
            batch, size = [], 0
        batch.append(line)
        size += encoded
    if batch:
        yield batch


def write_plan(plan, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for index in range(0, len(plan.prune_statements), STATEMENTS_PER_PRUNE_FILE):
        body = "\n".join(f"    {statement}" for statement in plan.prune_statements[index:index + STATEMENTS_PER_PRUNE_FILE])
        (out / f"prune-{index // STATEMENTS_PER_PRUNE_FILE:04d}.gq").write_text(f"query distill_prune() {{\n{body}\n}}\n", encoding="utf-8")
    number = 0
    for group in (plan.node_rows, plan.edge_rows, plan.state_rows):
        for batch in batched(group):
            (out / f"load-{number:04d}.ndjson").write_text("".join(batch), encoding="utf-8")
            number += 1
    attempted = plan.counts.processed + plan.counts.failed
    if attempted and plan.counts.failed / attempted > FAILED_SHARE_THAT_FAILS_THE_RUN:
        (out / "failed").write_text(f"{plan.counts.failed} of {attempted} extractions failed\n", encoding="utf-8")


def known_projects_block(graph):
    names = sorted({entity.name for entity in graph.entities.values() if entity.type == "Project" and not set(entity.data.get("tags") or []) & {"mirror", "fork"}})
    return "\n".join(f"- {name}" for name in names)


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Plan the distillation of brain documents into topics and entities.")
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--litellm-url", required=True)
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--schema-file", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--embed-model", required=True)
    parser.add_argument("--merge-prompt-file", required=True)
    parser.add_argument("--candidate-similarity", type=float, required=True)
    parser.add_argument("--same-similarity", type=float, required=True)
    parser.add_argument("--related-min-documents", type=int, required=True)
    parser.add_argument("--max-documents", type=int, required=True)
    parser.add_argument("--max-spend-usd", type=float, required=True)
    parser.add_argument("--workers", type=int, default=6)
    return parser.parse_args(argv)


def run(args, now, client_factory=LiteLLM):
    settings = Settings(args.model, args.embed_model, args.candidate_similarity, args.same_similarity, args.related_min_documents, args.max_documents, args.max_spend_usd, args.workers)
    graph = read_graph(args.snapshot_dir)
    counts = Counts(documents=len(graph.documents))
    if not graph.documents and graph.state:
        raise FailClosed(EXIT_NOTHING_VISIBLE, "the snapshot holds no documents; refusing to remove every distilled link")
    key = Path(args.key_file).read_text(encoding="utf-8").strip()
    client = client_factory(args.litellm_url, key, counts)
    schema = json.loads(Path(args.schema_file).read_text(encoding="utf-8"))
    system = Path(args.prompt_file).read_text(encoding="utf-8") + known_projects_block(graph) + "\n"
    pending = pending_documents(graph, settings)
    counts.pending = len(pending)
    selected = pending[:settings.max_documents]
    extractions = run_extractions(selected, client, settings, system, schema, counts) if selected else {}
    counts.skipped_budget += len(pending) - len(selected)
    embedder = lambda texts: client.embed(settings.embed_model, texts)
    resolver = Resolver(graph.entities, settings, embedder)
    merge_system = Path(args.merge_prompt_file).read_text(encoding="utf-8")

    def same_topic(pairs):
        with concurrent.futures.ThreadPoolExecutor(max_workers=settings.workers) as pool:
            return list(pool.map(lambda pair: client.same_topic(settings.model, merge_system, pair), pairs))

    plan = build_plan(graph, extractions, resolver, settings, counts, now, same_topic)
    write_plan(plan, args.out)
    return plan


def main(argv):
    args = parse_args(argv)
    try:
        plan = run(args, utc_now())
    except FailClosed as error:
        print(f"distill refused: {error}", file=sys.stderr)
        return error.exit_code
    except (LLMUnreachable, ExtractionFailed) as error:
        print(f"distill refused: {error}", file=sys.stderr)
        return EXIT_LLM_UNREACHABLE
    print(f"distill plan: {plan.counts.line()}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
