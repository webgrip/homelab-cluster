import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import brain_eval as be

SOURCE_PLAN = {
    "docs-en": 5,
    "notes-nl": 5,
    "notes-en": 3,
    "cross-lingual": 3,
    "about": 4,
    "connect": 3,
}
UNANSWERABLE_DRAFTS = 8
LONG_NOTE_CHARS = 6000
LATE_EXCERPT_START = 4500
EXCERPT_CHARS = 3500
POOL_DOCS = 25
SNIPPET_CHARS = 600
MIN_NOTE_CHARS = 300
MIN_DOC_CHARS = 400
ABOUT_MIN_DOCUMENTS = 10
PERSON_MIN_DOCUMENTS = 3
CONNECT_MIN_SHARED = 3

DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["question", "key_facts"],
                                                          "properties": {"question": {"type": "string"}, "key_facts": {"type": "array", "items": {"type": "string"}}}}}},
}
UNANSWERABLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["question", "language"],
                                                          "properties": {"question": {"type": "string"}, "language": {"type": "string", "enum": ["nl", "en"]}}}}},
}
POOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["grades"],
    "properties": {"grades": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["index", "grade"],
                                                       "properties": {"index": {"type": "integer"}, "grade": {"type": "integer", "enum": [0, 1, 2]}}}}},
}

LINKED_ARTIFACTS_SOURCE = "query linked_artifacts() {\n  match {\n    $t: Topic\n    $a artifactAboutTopic $t\n  }\n  return { $t.slug, $a.slug }\n}"
LINKED_NOTES_SOURCE = "query linked_notes() {\n  match {\n    $t: Topic\n    $n noteAboutTopic $t\n  }\n  return { $t.slug, $n.slug }\n}"
RELATED_TOPICS_SOURCE = "query related_topics() {\n  match {\n    $a: Topic\n    $a topicRelatedTopic $b\n  }\n  return { $a.slug, $b.slug }\n}"
PERSON_MENTIONS_SOURCE = "query person_mentions() {\n  match {\n    $u: Person\n    $a mentionsPerson $u\n  }\n  return { $u.slug, $a.slug }\n}"
PERSON_NOTES_SOURCE = "query person_notes() {\n  match {\n    $u: Person\n    $n noteAboutPerson $u\n  }\n  return { $u.slug, $n.slug }\n}"
POOL_LEGS = {
    "meaning_passages": ("query pool($q: String) {\n  match {\n    $p: Passage\n    $p passageOf $a\n  }\n  return { $a.slug, $a.name, $p.text }\n  order { nearest($p.embedding, $q) }\n  limit 10\n}", "a.slug", "a.name", "p.text"),
    "meaning_notes": ("query pool($q: String) {\n  match {\n    $n: Note\n  }\n  return { $n.slug, $n.name, $n.content }\n  order { nearest($n.embedding, $q) }\n  limit 10\n}", "n.slug", "n.name", "n.content"),
    "keyword_passages": ("query pool($q: String) {\n  match {\n    $p: Passage\n    $p passageOf $a\n  }\n  return { $a.slug, $a.name, $p.text }\n  order { bm25($p.text, $q) desc }\n  limit 10\n}", "a.slug", "a.name", "p.text"),
    "keyword_notes": ("query pool($q: String) {\n  match {\n    $n: Note\n  }\n  return { $n.slug, $n.name, $n.content }\n  order { bm25($n.content, $q) desc }\n  limit 10\n}", "n.slug", "n.name", "n.content"),
}


@dataclass
class Source:
    category: str
    question_language: str
    slug: str
    title: str
    excerpt: str
    kind: str
    beyond_first_1024_tokens: bool = False
    entities: list = field(default_factory=list)
    grade_two: list = field(default_factory=list)


@dataclass
class Candidate:
    source: Source
    paraphrase: int
    question: str
    key_facts: list
    answerable: bool = True
    temporal: dict = None
    expected: list = field(default_factory=list)
    pooled: int = 0
    pool_model: str = ""


def stripped(text):
    return (text or "").strip(" \t\n\r\f\v")


def export_type(omnigraph, type_name):
    return [row.get("data") or {} for row in omnigraph.export_rows([type_name]) if row.get("type") == type_name]


def pick(rng, items, count):
    items = list(items)
    rng.shuffle(items)
    return items[:count]


def note_sources(notes, rng):
    usable = [note for note in notes if str(note.get("slug", "")).startswith("obsidian/") and len(stripped(note.get("content"))) >= MIN_NOTE_CHARS
              and not str(note.get("name", "")).lower().startswith("untitled")]
    dutch = [note for note in usable if be.language_of(note["content"]) == "nl"]
    english = [note for note in usable if be.language_of(note["content"]) == "en"]
    long_dutch = [note for note in dutch if len(note["content"]) > LONG_NOTE_CHARS]
    chosen_long = pick(rng, long_dutch, 2)
    rest_dutch = [note for note in dutch if note not in chosen_long]
    sources = []
    for note in chosen_long:
        sources.append(Source("notes-nl", "nl", note["slug"], note["name"], note["content"][LATE_EXCERPT_START: LATE_EXCERPT_START + EXCERPT_CHARS], "note", True))
    for note in pick(rng, rest_dutch, SOURCE_PLAN["notes-nl"] - len(chosen_long) + 2):
        if len([s for s in sources if s.category == "notes-nl"]) < SOURCE_PLAN["notes-nl"]:
            sources.append(Source("notes-nl", "nl", note["slug"], note["name"], note["content"][:EXCERPT_CHARS], "note"))
        else:
            sources.append(Source("cross-lingual", "en", note["slug"], note["name"], note["content"][:EXCERPT_CHARS], "note"))
    for note in pick(rng, english, SOURCE_PLAN["notes-en"]):
        sources.append(Source("notes-en", "en", note["slug"], note["name"], note["content"][:EXCERPT_CHARS], "note"))
    return sources


def is_document(artifact):
    slug = str(artifact.get("slug", ""))
    return artifact.get("kind") == "document" and slug.startswith("forge/") and ("/doc/" in slug or "/adr/" in slug or slug.endswith("/readme"))


def doc_sources(artifacts, rng):
    usable = [artifact for artifact in artifacts if is_document(artifact) and len(stripped(artifact.get("content"))) >= MIN_DOC_CHARS
              and be.language_of(artifact["content"]) == "en"]
    per_repo, chosen = {}, []
    for artifact in pick(rng, usable, len(usable)):
        repo = "/".join(artifact["slug"].split("/")[1:3])
        if per_repo.get(repo, 0) >= 2:
            continue
        per_repo[repo] = per_repo.get(repo, 0) + 1
        chosen.append(artifact)
        if len(chosen) >= SOURCE_PLAN["docs-en"] + 1:
            break
    sources = [Source("docs-en", "en", artifact["slug"], artifact["name"], artifact["content"][:EXCERPT_CHARS], "doc") for artifact in chosen[: SOURCE_PLAN["docs-en"]]]
    for artifact in chosen[SOURCE_PLAN["docs-en"]:]:
        sources.append(Source("cross-lingual", "nl", artifact["slug"], artifact["name"], artifact["content"][:EXCERPT_CHARS], "doc"))
    return sources


def linked_documents(omnigraph, snapshot):
    linked = {}
    for source in (LINKED_ARTIFACTS_SOURCE, LINKED_NOTES_SOURCE):
        for row in omnigraph.inline(source, snapshot=snapshot).get("rows") or []:
            document = row.get("a.slug") or row.get("n.slug")
            linked.setdefault(row["t.slug"], set()).add(document)
    return linked


def about_sources(omnigraph, snapshot, topics, people, titles, rng):
    linked = linked_documents(omnigraph, snapshot)
    by_slug = {topic["slug"]: topic for topic in topics}
    hubs = [slug for slug, documents in linked.items() if len(documents) >= ABOUT_MIN_DOCUMENTS and slug in by_slug]
    sources = []
    for slug in pick(rng, hubs, SOURCE_PLAN["about"] - 1):
        topic = by_slug[slug]
        listing = "\n".join(f"- {titles.get(document, document)}" for document in sorted(linked[slug])[:12])
        excerpt = f"Topic: {topic.get('name')}\nDescription: {topic.get('description') or ''}\nAliases: {', '.join(topic.get('aliases') or [])}\nDocuments about it:\n{listing}"
        sources.append(Source("about", rng.choice(be.LANGUAGES), slug, topic.get("name") or slug, excerpt, "topic", entities=[slug], grade_two=[slug]))
    mentions = {}
    for source in (PERSON_MENTIONS_SOURCE, PERSON_NOTES_SOURCE):
        for row in omnigraph.inline(source, snapshot=snapshot).get("rows") or []:
            mentions.setdefault(row["u.slug"], set()).add(row.get("a.slug") or row.get("n.slug"))
    candidates = [person for person in people if person.get("relation") != "self" and not be.BOT_LOGIN.search(str(person.get("slug", "")).rsplit("/", 1)[-1])
                  and len(mentions.get(person.get("slug"), ())) >= PERSON_MIN_DOCUMENTS]
    for person in pick(rng, candidates, 1):
        listing = "\n".join(f"- {titles.get(document, document)}" for document in sorted(mentions[person["slug"]])[:12])
        excerpt = f"Person: {person.get('name')}\nAbout them: {person.get('brief') or ''}\nDocuments that mention them:\n{listing}"
        sources.append(Source("about", rng.choice(be.LANGUAGES), person["slug"], person.get("name") or person["slug"], excerpt, "person",
                              entities=[person["slug"]], grade_two=[person["slug"]]))
    return sources, linked


def connect_sources(omnigraph, snapshot, topics, linked, titles, rng):
    by_slug = {topic["slug"]: topic for topic in topics}
    pairs = []
    for row in omnigraph.inline(RELATED_TOPICS_SOURCE, snapshot=snapshot).get("rows") or []:
        left, right = row["a.slug"], row["b.slug"]
        if left < right and left in by_slug and right in by_slug:
            shared = linked.get(left, set()) & linked.get(right, set())
            if len(shared) >= CONNECT_MIN_SHARED:
                pairs.append((left, right, sorted(shared)))
    sources = []
    for left, right, shared in pick(rng, pairs, SOURCE_PLAN["connect"]):
        listing = "\n".join(f"- {titles.get(document, document)}" for document in shared[:10])
        excerpt = (f"Topic A: {by_slug[left].get('name')} ({by_slug[left].get('description') or ''})\n"
                   f"Topic B: {by_slug[right].get('name')} ({by_slug[right].get('description') or ''})\nDocuments about both:\n{listing}")
        sources.append(Source("connect", rng.choice(be.LANGUAGES), f"{left}|{right}", f"{by_slug[left].get('name')} / {by_slug[right].get('name')}", excerpt,
                              "pair", entities=[left, right], grade_two=shared[:5]))
    return sources


def draft_prompt(prompts_dir, name):
    return Path(prompts_dir, name).read_text(encoding="utf-8")


def draft_questions(llm, model, prompt, source, stricter=False):
    user = json.dumps({"kind": source.kind, "question_language": source.question_language, "title": source.title, "excerpt": source.excerpt,
                       "reminder": "Your previous questions repeated five or more consecutive words of the excerpt. Paraphrase every question completely." if stricter else ""},
                      ensure_ascii=False)
    response, _ = llm.chat({"model": model, "temperature": 0.7, "max_tokens": 1500, "reasoning_effort": "low",
                            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                            "response_format": {"type": "json_schema", "json_schema": {"name": "brain_eval_questions", "strict": True, "schema": DRAFT_SCHEMA}}})
    try:
        drafted = be.parse_json_content(response).get("questions") or []
    except (json.JSONDecodeError, AttributeError):
        return []
    usable = []
    for item in drafted[:2]:
        question = stripped(item.get("question"))
        facts = [stripped(fact) for fact in item.get("key_facts") or [] if stripped(fact)][:4]
        if question and facts:
            usable.append((question, facts))
    return usable


def draft_for_source(llm, model, prompt, source, counts):
    drafted = draft_questions(llm, model, prompt, source)
    if any(be.shares_ngram(question, source.excerpt) for question, _ in drafted):
        counts["regenerated"] += 1
        drafted = draft_questions(llm, model, prompt, source, stricter=True)
    kept = []
    for index, (question, facts) in enumerate(drafted):
        if be.shares_ngram(question, source.excerpt):
            counts["dropped_ngram"] += 1
            continue
        kept.append(Candidate(source, index, question, facts))
    return kept


def draft_unanswerable(llm, model, prompt, topic_names):
    user = json.dumps({"count": UNANSWERABLE_DRAFTS, "covered_topics": topic_names}, ensure_ascii=False)
    response, _ = llm.chat({"model": model, "temperature": 0.9, "max_tokens": 1500, "reasoning_effort": "low",
                            "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                            "response_format": {"type": "json_schema", "json_schema": {"name": "brain_eval_unanswerable", "strict": True, "schema": UNANSWERABLE_SCHEMA}}})
    try:
        items = be.parse_json_content(response).get("questions") or []
    except (json.JSONDecodeError, AttributeError):
        return []
    drafted = []
    for index, item in enumerate(items[:UNANSWERABLE_DRAFTS]):
        question = stripped(item.get("question"))
        if question:
            language = item.get("language") if item.get("language") in be.LANGUAGES else be.language_of(question)
            source = Source("unanswerable", language, f"unanswerable-{index}", "", "", "none")
            drafted.append(Candidate(source, 0, question, [], answerable=False))
    return drafted


TEMPORAL_TEMPLATES = (
    ("recent_notes", 7, "nl", "Wat heb ik de afgelopen {days} dagen in mijn notities opgeschreven?"),
    ("recent_notes", 14, "en", "What did I write in my notes over the last {days} days?"),
    ("recent_docs", 14, "en", "Which documents in my projects changed in the last {days} days?"),
    ("recent_docs", 30, "nl", "Welke documenten in mijn projecten zijn de afgelopen {days} dagen veranderd?"),
    ("open_threads", 365, "en", "Which issues and pull requests are still open in {project}?"),
    ("open_threads", 365, "nl", "Welke issues en pull requests staan nog open in {project}?"),
)


def temporal_candidates(omnigraph, snapshot, now, projects, rng):
    scans = be.temporal_scans(omnigraph, snapshot, {"recent_notes", "recent_docs", "open_threads"})
    open_counts = {}
    for project in projects:
        spec = {"kind": "open_threads", "days": 365, "project": project["slug"]}
        open_counts[project["slug"]] = len(be.temporal_expectation({"temporal": spec}, scans, now))
    busy = [project for project in projects if open_counts.get(project["slug"], 0) >= 2]
    chosen_projects = pick(rng, busy, 2)
    candidates = []
    for kind, days, language, template in TEMPORAL_TEMPLATES:
        spec = {"kind": kind, "days": days}
        name = ""
        if kind == "open_threads":
            if not chosen_projects:
                continue
            project = chosen_projects.pop(0)
            spec["project"] = project["slug"]
            name = project.get("name") or project["slug"]
        for widen in (1, 2, 4):
            probe = dict(spec, days=spec["days"] * widen) if kind != "open_threads" else spec
            if be.temporal_expectation({"temporal": probe}, scans, now):
                spec = probe
                break
        else:
            continue
        question = template.format(days=spec["days"], project=name)
        source = Source("temporal", language, f"temporal-{kind}", "", "", "temporal")
        candidates.append(Candidate(source, 0, question, [], temporal=spec))
    return candidates


def pool_documents(omnigraph, snapshot, catalog, question):
    ordered, snippets = [], {}

    def take(slug, title, text):
        doc = catalog.equivalence.canonical(slug)
        if doc not in snippets:
            snippets[doc] = (title or doc, stripped(text)[:SNIPPET_CHARS])
            ordered.append(doc)

    retrieved = be.profile_p0(omnigraph, question, snapshot)
    for slug in retrieved.ranked[:10]:
        take(slug, slug, "")
    for leg, (source, slug_column, title_column, text_column) in POOL_LEGS.items():
        for row in omnigraph.inline(source, {"q": question}, snapshot=snapshot).get("rows") or []:
            doc = catalog.equivalence.canonical(row[slug_column])
            if doc in snippets and not snippets[doc][1]:
                snippets[doc] = (row.get(title_column) or doc, stripped(row.get(text_column))[:SNIPPET_CHARS])
            take(row[slug_column], row.get(title_column), row.get(text_column))
    return [(doc, snippets[doc][0], snippets[doc][1]) for doc in ordered[:POOL_DOCS]]


def grade_pool(llm, model, prompt, question, pooled):
    if not pooled:
        return {}
    documents = [{"index": index, "title": title, "snippet": snippet} for index, (_, title, snippet) in enumerate(pooled)]
    response, _ = llm.chat({"model": model, "temperature": 0, "max_tokens": 1500, "messages": [
        {"role": "system", "content": prompt}, {"role": "user", "content": json.dumps({"question": question, "documents": documents}, ensure_ascii=False)}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "brain_eval_pool_grades", "strict": True, "schema": POOL_SCHEMA}}})
    try:
        grades = be.parse_json_content(response).get("grades") or []
    except (json.JSONDecodeError, AttributeError):
        return None
    return {pooled[item["index"]][0]: int(item["grade"]) for item in grades if isinstance(item.get("index"), int) and 0 <= item["index"] < len(pooled)}


def grade_with_fallback(llm, models, prompt, question, pooled, counts, refused):
    usable = [model for model in models if model not in refused] or models[-1:]
    for index, model in enumerate(usable):
        try:
            graded = grade_pool(llm, model, prompt, question, pooled)
            if model != models[0]:
                counts["pooled_by_fallback"] = counts.get("pooled_by_fallback", 0) + 1
            return graded, model
        except be.UpstreamError as error:
            if error.status != 429 or index == len(usable) - 1:
                raise
            refused.add(model)
    return None, ""


def expected_for(candidate, graded, catalog):
    grades = {}
    for slug in candidate.source.grade_two:
        grades[catalog.equivalence.canonical(slug)] = 2
    if candidate.source.kind in ("note", "doc"):
        grades[catalog.equivalence.canonical(candidate.source.slug)] = 2
    for doc, grade in (graded or {}).items():
        if grade >= 1 and doc not in grades:
            grades[doc] = grade
    return [{"slug": doc, "grade": grade} for doc, grade in sorted(grades.items(), key=lambda item: (-item[1], item[0]))[:8]]


def cut_to_quota(candidates, rng):
    chosen = []
    for category, quota in be.CATEGORY_QUOTA.items():
        pool = [candidate for candidate in candidates if candidate.source.category == category]
        firsts = [candidate for candidate in pool if candidate.paraphrase == 0]
        seconds = [candidate for candidate in pool if candidate.paraphrase != 0]
        rng.shuffle(firsts)
        rng.shuffle(seconds)
        if category == "notes-nl":
            firsts.sort(key=lambda candidate: not candidate.source.beyond_first_1024_tokens)
        picked = (firsts + seconds)[:quota]
        holdout = rng.randrange(len(picked)) if picked else None
        for index, candidate in enumerate(picked):
            chosen.append((candidate, "holdout" if index == holdout else "dev"))
    return chosen


def case_document(case_id, candidate, split):
    case = {"id": case_id, "split": split, "category": candidate.source.category, "language": candidate.source.question_language,
            "provisional": True, "origin": "drafted", "answerable": candidate.answerable, "question": candidate.question,
            "expected": candidate.expected if candidate.answerable and not candidate.temporal else [], "key_facts": candidate.key_facts}
    if candidate.temporal:
        case["temporal"] = candidate.temporal
    if candidate.source.entities:
        case["entities"] = candidate.source.entities
    if candidate.source.beyond_first_1024_tokens:
        case["beyond_first_1024_tokens"] = True
    return case


def command_candidates(args):
    workspace = be.Workspace.open(args.repo_dir, args.out_dir)
    cases_dir = workspace.repo / "cases"
    if cases_dir.is_dir() and any(cases_dir.glob("*.yaml")):
        raise be.EvalError("the eval repo already holds cases; candidates never overwrite them (move cases/ aside to redraft)")
    rng = random.Random(args.seed)
    omnigraph = be.omnigraph_client(args)
    llm = be.litellm_client(args, args.max_spend_usd)
    snapshot = omnigraph.head()
    now = omnigraph.commit_time(snapshot)
    catalog = be.Catalog.read(omnigraph, snapshot)
    counts = {"regenerated": 0, "dropped_ngram": 0, "dropped_unanswerable_found": 0, "dropped_pool_failed": 0}
    notes = export_type(omnigraph, "Note")
    artifacts = export_type(omnigraph, "Artifact")
    topics = export_type(omnigraph, "Topic")
    people = export_type(omnigraph, "Person")
    projects = export_type(omnigraph, "Project")
    titles = {row["slug"]: row.get("name") or row["slug"] for row in notes + artifacts if row.get("slug")}
    about, linked = about_sources(omnigraph, snapshot, topics, people, titles, rng)
    sources = note_sources(notes, rng) + doc_sources(artifacts, rng) + about + connect_sources(omnigraph, snapshot, topics, linked, titles, rng)
    del notes, artifacts
    be.log("candidate sources", **{category: sum(1 for source in sources if source.category == category) for category in be.CATEGORIES})
    draft = draft_prompt(args.prompts_dir, "draft.prompt.txt")
    candidates = []
    for source in sources:
        candidates.extend(draft_for_source(llm, args.draft_model, draft, source, counts))
    top_topics = sorted(topics, key=lambda topic: -len(linked.get(topic["slug"], ())))[:80]
    unanswerable = draft_unanswerable(llm, args.draft_model, draft_prompt(args.prompts_dir, "unanswerable.prompt.txt"), [topic.get("name") for topic in top_topics])
    pool_prompt = draft_prompt(args.prompts_dir, "pool.prompt.txt")
    kept = []
    refused_models = set()
    for candidate in candidates + unanswerable:
        pooled = pool_documents(omnigraph, snapshot, catalog, candidate.question)
        graded, candidate.pool_model = grade_with_fallback(llm, [args.pool_model, args.pool_fallback_model], pool_prompt, candidate.question, pooled, counts, refused_models)
        if graded is None:
            counts["dropped_pool_failed"] += 1
            continue
        candidate.pooled = len(pooled)
        if not candidate.answerable:
            if any(grade >= 1 for grade in graded.values()):
                counts["dropped_unanswerable_found"] += 1
                continue
        else:
            candidate.expected = expected_for(candidate, graded, catalog)
        kept.append(candidate)
    kept.extend(temporal_candidates(omnigraph, snapshot, now, projects, rng))
    chosen = cut_to_quota(kept, rng)
    shortfall = {category: quota - sum(1 for candidate, _ in chosen if candidate.source.category == category) for category, quota in be.CATEGORY_QUOTA.items()}
    day = be.dated(args)
    pool_path = workspace.repo / "candidates" / day / "pool.json"
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    pool_path.write_text(json.dumps({
        "snapshot": snapshot, "harness_version": be.HARNESS_VERSION, "seed": args.seed, "counts": counts, "shortfall": shortfall,
        "candidates": [{"category": candidate.source.category, "language": candidate.source.question_language, "source": candidate.source.slug,
                        "question": candidate.question, "key_facts": candidate.key_facts, "answerable": candidate.answerable, "temporal": candidate.temporal,
                        "expected": candidate.expected, "pooled_documents": candidate.pooled, "pool_model": candidate.pool_model, "paraphrase": candidate.paraphrase} for candidate in kept],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    cases_dir.mkdir(parents=True, exist_ok=True)
    for number, (candidate, split) in enumerate(chosen, start=1):
        case = be.validate_case(case_document(f"c{number:02d}", candidate, split), f"c{number:02d}")
        (cases_dir / f"c{number:02d}.yaml").write_text(be.dump_case(case), encoding="utf-8")
    sink = be.MetricSink()
    be.add_set_metrics(sink, workspace.cases(), len(workspace.calibration_files()))
    sink.add("brain_eval_cost_usd", {"mode": "candidates"}, llm.spend.total)
    be.log("candidates written", drafted=len(candidates), unanswerable_drafted=len(unanswerable), kept=len(kept), cases=len(chosen),
           holdout=sum(1 for _, split in chosen if split == "holdout"), spend_usd=round(llm.spend.total, 4), **counts,
           **{f"short_{category}": missing for category, missing in shortfall.items() if missing})
    if args.dry_run:
        return 0
    be.finish(args, workspace, sink, "candidates", f"candidates: {len(kept)} drafted, {len(chosen)} provisional cases at graph commit {snapshot}")
    return 0
