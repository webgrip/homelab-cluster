import type { BotIndex } from './caches.ts';
import type { Profile } from './config.ts';
import { guessLanguage, keywordTerms, mentionsAny, textHash } from './text.ts';
import type { Language } from './text.ts';
import { UpstreamError } from './upstream.ts';
import type { QueryResult, Row } from './upstream.ts';

export type Scope = 'all' | 'notes' | 'docs';

export const SCOPES: readonly Scope[] = ['all', 'notes', 'docs'];

export type SourceKind = 'doc' | 'note' | 'capture' | 'topic';

export interface Source {
  key: string;
  ref: string;
  document: string;
  kind: SourceKind;
  title: string;
  docKind: string;
  date: string | null;
  url: string | null;
  text: string;
  chunk: number | null;
  score: number;
  similar: number;
  bot: boolean;
  legRanks: Record<string, number>;
}

export interface Related {
  ref: string;
  name: string;
  description: string | null;
}

export type Degraded = 'keyword-only' | 'embedding-contract-mismatch' | null;

export interface LegReport {
  rows: number;
  seconds: number;
  keys: string[];
  failed: string | null;
}

export interface SearchResult {
  profile: Profile;
  sources: Source[];
  related: Related[];
  graphCommit: string | null;
  degraded: Degraded;
  language: Language;
  terms: string[];
  mode: 'fused' | 'keyword_only' | 'meaning_only' | 'none';
  embedSeconds: number;
  legSeconds: number[];
  legs: Record<string, LegReport>;
}

export interface SearchRequest {
  question: string;
  scope: Scope;
  limit: number;
  profile: Profile;
  snapshot: string | null;
}

export interface SearchDeps {
  stored: (name: string, params: Record<string, unknown>, snapshot: string | null, signal: AbortSignal) => Promise<QueryResult>;
  embed: (text: string, signal: AbortSignal) => Promise<number[]>;
  bots: (snapshot: string | null, signal: AbortSignal) => Promise<BotIndex>;
  contractOk: () => boolean;
}

export const RRF_K = 60;
export const BOT_WEIGHT = 0.3;
export const KEYWORD_WEIGHT: Record<Language, number> = { en: 1.0, nl: 0.6 };
export const MEANING_WEIGHT = 1.0;
export const MAX_CHUNKS_PER_DOCUMENT = 2;
export const SHORT_CHUNK_CHARS = 80;
export const RELATED_TOPICS = 5;
export const MAX_LEGS_IN_FLIGHT = 8;

type Family = 'docs' | 'notes' | 'captures' | 'topics';

interface Leg {
  name: string;
  query: string;
  meaning: boolean;
  family: Family;
}

export const LEGS: readonly Leg[] = [
  { name: 'docs_vec', query: 'rt_doc_passages_vec', meaning: true, family: 'docs' },
  { name: 'docs_kw', query: 'rt_doc_passages_bm25', meaning: false, family: 'docs' },
  { name: 'notes_vec', query: 'rt_note_passages_vec', meaning: true, family: 'notes' },
  { name: 'notes_kw', query: 'rt_note_passages_bm25', meaning: false, family: 'notes' },
  { name: 'captures_vec', query: 'rt_captures_vec', meaning: true, family: 'captures' },
  { name: 'captures_kw', query: 'rt_captures_bm25', meaning: false, family: 'captures' },
  { name: 'topics_vec', query: 'rt_topics_vec', meaning: true, family: 'topics' },
  { name: 'topics_kw', query: 'rt_topics_bm25', meaning: false, family: 'topics' },
];

export const P0_QUERIES: readonly string[] = ['recall_notes', 'recall_passages', 'recall_topics'];

export const READ_QUERIES: readonly string[] = ['rt_artifact_card', 'rt_note_card', 'rt_note_text', 'rt_passage_window'];

export const REQUIRED_QUERIES: readonly string[] = [...P0_QUERIES, ...LEGS.map((leg) => leg.query), ...READ_QUERIES, 'rt_artifact_authors'];

const FAMILIES_BY_SCOPE: Record<Scope, readonly Family[]> = {
  all: ['docs', 'notes', 'captures', 'topics'],
  notes: ['notes', 'captures', 'topics'],
  docs: ['docs', 'topics'],
};

function text(row: Row, column: string): string {
  const value = row[column];
  return typeof value === 'string' ? value : '';
}

function optional(row: Row, column: string): string | null {
  const value = row[column];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function chunkOf(row: Row): number | null {
  const value = row['p.chunk_index'];
  return typeof value === 'number' && Number.isInteger(value) ? value : null;
}

function candidate(family: Exclude<Family, 'topics'>, row: Row): Source | null {
  if (family === 'docs') {
    const id = text(row, 'p.@id');
    const slug = text(row, 'a.slug');
    if (id.length === 0 || slug.length === 0) return null;
    const chunk = chunkOf(row);
    return {
      key: id,
      ref: `doc:${slug}#${chunk ?? 0}`,
      document: slug,
      kind: 'doc',
      title: text(row, 'a.name'),
      docKind: text(row, 'a.kind'),
      date: optional(row, 'a.timestamp'),
      url: optional(row, 'a.url'),
      text: text(row, 'p.text'),
      chunk,
      score: 0,
      similar: 0,
      bot: false,
      legRanks: {},
    };
  }
  if (family === 'notes') {
    const id = text(row, 'p.@id');
    const slug = text(row, 'n.slug');
    if (id.length === 0 || slug.length === 0) return null;
    const chunk = chunkOf(row);
    return {
      key: id,
      ref: `note:${slug}#${chunk ?? 0}`,
      document: slug,
      kind: 'note',
      title: text(row, 'n.name'),
      docKind: text(row, 'n.kind'),
      date: optional(row, 'n.updatedAt'),
      url: null,
      text: text(row, 'p.text'),
      chunk,
      score: 0,
      similar: 0,
      bot: false,
      legRanks: {},
    };
  }
  const slug = text(row, 'n.slug');
  if (slug.length === 0) return null;
  return {
    key: slug,
    ref: `note:${slug}`,
    document: slug,
    kind: 'capture',
    title: text(row, 'n.name'),
    docKind: text(row, 'n.kind'),
    date: optional(row, 'n.updatedAt'),
    url: null,
    text: text(row, 'n.content'),
    chunk: null,
    score: 0,
    similar: 0,
    bot: false,
    legRanks: {},
  };
}

export function fuse(legResults: readonly { leg: Leg; rows: readonly Row[]; weight: number }[]): Source[] {
  const byKey = new Map<string, Source>();
  for (const { leg, rows, weight } of legResults) {
    if (leg.family === 'topics') continue;
    rows.forEach((row, index) => {
      const found = candidate(leg.family as Exclude<Family, 'topics'>, row);
      if (found === null) return;
      const rank = index + 1;
      const existing = byKey.get(found.key) ?? found;
      existing.score += weight / (RRF_K + rank);
      existing.legRanks[leg.name] = rank;
      byKey.set(found.key, existing);
    });
  }
  return [...byKey.values()];
}

function byScore(left: Source, right: Source): number {
  return right.score - left.score || (left.key < right.key ? -1 : left.key > right.key ? 1 : 0);
}

function newer(left: Source, right: Source): boolean {
  return (left.date ?? '') > (right.date ?? '');
}

export function collapse(fused: readonly Source[], bots: BotIndex, question: string): Source[] {
  const namesBot = mentionsAny(question, bots.names);
  const weighted = fused.map((source) => {
    const bot = source.kind === 'doc' && bots.artifacts.has(source.document);
    return { ...source, bot, score: bot && !namesBot ? source.score * BOT_WEIGHT : source.score };
  });
  const long = weighted.filter((source) => source.kind === 'capture' || source.text.trim().length > SHORT_CHUNK_CHARS);
  const pool = (long.length > 0 ? long : weighted).sort(byScore);
  const groups = new Map<string, Source>();
  for (const source of pool) {
    const hash = textHash(source.text);
    const kept = groups.get(hash);
    if (kept === undefined) {
      groups.set(hash, { ...source });
      continue;
    }
    const merged = newer(source, kept) ? { ...source, score: kept.score, legRanks: { ...source.legRanks, ...kept.legRanks } } : kept;
    merged.similar = kept.similar + 1;
    groups.set(hash, merged);
  }
  const perDocument = new Map<string, number>();
  const collapsed: Source[] = [];
  for (const source of [...groups.values()].sort(byScore)) {
    const seen = perDocument.get(source.document) ?? 0;
    if (seen >= MAX_CHUNKS_PER_DOCUMENT) continue;
    perDocument.set(source.document, seen + 1);
    collapsed.push(source);
  }
  return collapsed;
}

export function relatedTopics(legResults: readonly { leg: Leg; rows: readonly Row[]; weight: number }[]): Related[] {
  const scores = new Map<string, { related: Related; score: number }>();
  for (const { leg, rows, weight } of legResults) {
    if (leg.family !== 'topics') continue;
    rows.forEach((row, index) => {
      const slug = text(row, 't.slug');
      if (slug.length === 0) return;
      const entry = scores.get(slug) ?? { related: { ref: `topic:${slug}`, name: text(row, 't.name'), description: optional(row, 't.description') }, score: 0 };
      entry.score += weight / (RRF_K + index + 1);
      scores.set(slug, entry);
    });
  }
  return [...scores.entries()]
    .sort((left, right) => right[1].score - left[1].score || (left[0] < right[0] ? -1 : 1))
    .slice(0, RELATED_TOPICS)
    .map(([, entry]) => entry.related);
}

export function interleave<T>(lists: readonly (readonly T[])[]): T[] {
  const merged: T[] = [];
  const longest = Math.max(0, ...lists.map((list) => list.length));
  for (let position = 0; position < longest; position += 1) {
    for (const list of lists) {
      const item = list[position];
      if (item !== undefined) merged.push(item);
    }
  }
  return merged;
}

function p0Sources(notes: readonly Row[], passages: readonly Row[], topics: readonly Row[]): Source[] {
  const noteSources = notes.flatMap((row): Source[] => {
    const slug = text(row, 'n.slug');
    if (slug.length === 0) return [];
    return [{ key: slug, ref: `note:${slug}`, document: slug, kind: slug.startsWith('nt-') ? 'capture' : 'note', title: text(row, 'n.name'), docKind: text(row, 'n.kind'),
      date: null, url: null, text: text(row, 'n.content'), chunk: null, score: 0, similar: 0, bot: false, legRanks: {} }];
  });
  const passageSources = passages.flatMap((row): Source[] => {
    const slug = text(row, 'a.slug');
    if (slug.length === 0) return [];
    const chunk = chunkOf(row);
    return [{ key: `${slug}#${chunk ?? 0}`, ref: `doc:${slug}#${chunk ?? 0}`, document: slug, kind: 'doc', title: text(row, 'a.name'), docKind: '',
      date: null, url: null, text: text(row, 'p.text'), chunk, score: 0, similar: 0, bot: false, legRanks: {} }];
  });
  const topicSources = topics.flatMap((row): Source[] => {
    const slug = text(row, 't.slug');
    if (slug.length === 0) return [];
    return [{ key: slug, ref: `topic:${slug}`, document: slug, kind: 'topic', title: text(row, 't.name'), docKind: 'topic',
      date: null, url: null, text: text(row, 't.description'), chunk: null, score: 0, similar: 0, bot: false, legRanks: {} }];
  });
  const merged = interleave([noteSources, passageSources, topicSources]);
  merged.forEach((source, index) => {
    source.score = 1 / (index + 1);
  });
  return merged;
}

function pickCommit(results: readonly (QueryResult | null)[]): string | null {
  for (const result of results) if (result?.graphCommit) return result.graphCommit;
  return null;
}

async function runP0(request: SearchRequest, deps: SearchDeps, signal: AbortSignal): Promise<SearchResult> {
  const params = { q: request.question };
  const [notes, passages, topics] = await Promise.all(P0_QUERIES.map((name) => deps.stored(name, params, request.snapshot, signal)));
  const legs: Record<string, LegReport> = {};
  P0_QUERIES.forEach((name, index) => {
    const result = [notes, passages, topics][index]!;
    legs[name] = { rows: result.rows.length, seconds: result.seconds, keys: [], failed: null };
  });
  return {
    profile: 'p0',
    sources: p0Sources(notes!.rows, passages!.rows, topics!.rows).slice(0, request.limit),
    related: [],
    graphCommit: pickCommit([notes!, passages!, topics!]),
    degraded: null,
    language: guessLanguage(request.question),
    terms: keywordTerms(request.question),
    mode: 'fused',
    embedSeconds: 0,
    legSeconds: [notes!.seconds, passages!.seconds, topics!.seconds],
    legs,
  };
}

async function limited<T>(tasks: readonly (() => Promise<T>)[], inFlight: number): Promise<PromiseSettledResult<T>[]> {
  const results: PromiseSettledResult<T>[] = new Array(tasks.length);
  let next = 0;
  const worker = async (): Promise<void> => {
    while (next < tasks.length) {
      const index = next;
      next += 1;
      try {
        results[index] = { status: 'fulfilled', value: await tasks[index]!() };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(inFlight, tasks.length) }, worker));
  return results;
}

async function runP1(request: SearchRequest, deps: SearchDeps, signal: AbortSignal): Promise<SearchResult> {
  const language = guessLanguage(request.question);
  const terms = keywordTerms(request.question);
  let degraded: Degraded = null;
  let vector: number[] | null = null;
  const embedStarted = performance.now();
  if (!deps.contractOk()) {
    degraded = 'embedding-contract-mismatch';
  } else {
    try {
      vector = await deps.embed(request.question, signal);
    } catch (error) {
      if (signal.aborted) throw error;
      degraded = 'keyword-only';
    }
  }
  const embedSeconds = (performance.now() - embedStarted) / 1000;
  const families = FAMILIES_BY_SCOPE[request.scope];
  const planned = LEGS.filter((leg) => families.includes(leg.family) && (leg.meaning ? vector !== null : terms.length > 0));
  const keywordString = terms.join(' ');
  const outcomes = await limited(
    planned.map((leg) => () => deps.stored(leg.query, leg.meaning ? { v: vector } : { k: keywordString }, request.snapshot, signal)),
    MAX_LEGS_IN_FLIGHT,
  );
  const legs: Record<string, LegReport> = {};
  const legResults: { leg: Leg; rows: readonly Row[]; weight: number }[] = [];
  const fulfilled: QueryResult[] = [];
  outcomes.forEach((outcome, index) => {
    const leg = planned[index]!;
    if (outcome.status === 'rejected') {
      const reason = outcome.reason;
      if (reason instanceof UpstreamError && reason.unavailable) throw reason;
      if (!(reason instanceof UpstreamError)) throw reason;
      legs[leg.name] = { rows: 0, seconds: 0, keys: [], failed: reason.outcome };
      return;
    }
    fulfilled.push(outcome.value);
    legs[leg.name] = { rows: outcome.value.rows.length, seconds: outcome.value.seconds, keys: [], failed: null };
    legResults.push({ leg, rows: outcome.value.rows, weight: leg.meaning ? MEANING_WEIGHT : KEYWORD_WEIGHT[language] });
  });
  if (planned.length > 0 && fulfilled.length === 0) throw new UpstreamError('omnigraph', 0, 'server_error');
  let bots: BotIndex = { artifacts: new Set(), names: [] };
  try {
    bots = await deps.bots(request.snapshot, signal);
  } catch (error) {
    if (signal.aborted) throw error;
  }
  const collapsed = collapse(fuse(legResults), bots, request.question);
  for (const { leg, rows } of legResults) {
    legs[leg.name]!.keys = rows.map((row) => text(row, leg.family === 'captures' ? 'n.slug' : leg.family === 'topics' ? 't.slug' : 'p.@id'));
  }
  const mode = vector !== null && terms.length > 0 ? 'fused' : vector !== null ? 'meaning_only' : terms.length > 0 ? 'keyword_only' : 'none';
  return {
    profile: 'p1',
    sources: collapsed.slice(0, request.limit),
    related: relatedTopics(legResults),
    graphCommit: pickCommit(fulfilled),
    degraded,
    language,
    terms,
    mode,
    embedSeconds,
    legSeconds: fulfilled.map((result) => result.seconds),
    legs,
  };
}

export async function search(request: SearchRequest, deps: SearchDeps, signal: AbortSignal): Promise<SearchResult> {
  return request.profile === 'p0' ? runP0(request, deps, signal) : runP1(request, deps, signal);
}
