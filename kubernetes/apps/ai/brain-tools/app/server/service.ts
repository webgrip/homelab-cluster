import type { Caches } from './caches.ts';
import type { Profile } from './config.ts';
import { PROFILES } from './config.ts';
import { checkContract } from './contract.ts';
import type { EmbeddingContract } from './contract.ts';
import { METRICS } from './metrics.ts';
import type { MetricRegistry } from './metrics.ts';
import { MAX_AROUND, parseRef, readRef } from './read.ts';
import { linkFor, renderRead, renderSearch } from './render.ts';
import { REQUIRED_QUERIES, SCOPES, search } from './search.ts';
import type { Scope, SearchResult } from './search.ts';
import { snippet } from './text.ts';
import { UpstreamError } from './upstream.ts';
import type { Embedder, Omnigraph } from './upstream.ts';

export type Surface = 'mcp' | 'rest';

export type Outcome = 'ok' | 'empty' | 'invalid' | 'unavailable' | 'timeout' | 'not_found' | 'error';

export interface ToolResponse {
  text: string;
  structured: Record<string, unknown>;
  isError: boolean;
  outcome: Outcome;
  status: number;
}

export const MAX_QUESTION_CHARS = 500;
export const DEFAULT_LIMIT = 8;
export const MAX_LIMIT: Record<Surface, number> = { mcp: 20, rest: 40 };
const SNAPSHOT = /^[0-9A-Za-z]{10,64}$/;

export const MESSAGES = {
  unavailable: 'The brain is unavailable right now (it may be restarting). Tell Ryan you could not check his brain; do not answer from memory.',
  timeout: 'The brain did not answer in time. Tell Ryan you could not check his brain; do not answer from memory.',
  question: `Ask with a question or key words of 1 to ${MAX_QUESTION_CHARS} characters. Plain words work best, in Dutch or English; never a query language.`,
  scope: `scope must be one of ${SCOPES.join(', ')}.`,
  limit: (max: number) => `limit must be a whole number from 1 to ${max}.`,
  profile: `profile must be one of ${PROFILES.join(', ')}.`,
  snapshot: 'snapshot must be a graph commit id.',
  ref: 'Unknown ref. Use refs exactly as search returned them, such as doc:<slug>#<chunk> or note:<slug>#<chunk>.',
  entity: 'read opens doc: and note: refs. topic:, person:, project: and org: refs name an entity: search with its name instead.',
  notFound: 'Nothing in the brain has that ref any more (renamed or deleted since the search). Search again.',
  around: `around must be 0 or ${MAX_AROUND}.`,
  error: 'brain-tools failed on this request. Tell Ryan you could not check his brain; do not answer from memory.',
} as const;

export interface CatalogState {
  reachable: boolean;
  missing: string[];
  checkedAt: number;
}

export interface ServiceOptions {
  omnigraph: Omnigraph;
  embedder: Embedder;
  caches: Caches;
  contract: EmbeddingContract | null;
  registry: MetricRegistry;
  explorerUrl: string | null;
  defaultProfile: Profile;
  deadlineMs: number;
  log: (event: Record<string, unknown>) => void;
}

function invalid(message: string): ToolResponse {
  return { text: message, structured: { error: 'invalid', message }, isError: true, outcome: 'invalid', status: 400 };
}

function failure(error: unknown, signal: AbortSignal): ToolResponse {
  if (signal.aborted || (error instanceof UpstreamError && error.outcome === 'timeout')) {
    return { text: MESSAGES.timeout, structured: { error: 'timeout', message: MESSAGES.timeout }, isError: true, outcome: 'timeout', status: 504 };
  }
  if (error instanceof UpstreamError && (error.unavailable || error.status === 401 || error.status === 403 || error.outcome === 'not_found')) {
    return { text: MESSAGES.unavailable, structured: { error: 'unavailable', message: MESSAGES.unavailable }, isError: true, outcome: 'unavailable', status: 503 };
  }
  return { text: MESSAGES.error, structured: { error: 'error', message: MESSAGES.error }, isError: true, outcome: 'error', status: 500 };
}

function integer(value: unknown, fallback: number): number | null {
  if (value === undefined || value === null || value === '') return fallback;
  const parsed = typeof value === 'string' ? Number(value) : value;
  return typeof parsed === 'number' && Number.isInteger(parsed) ? parsed : null;
}

function truthy(value: unknown): boolean {
  return value === true || value === 'true' || value === '1';
}

export class BrainService {
  private readonly omnigraph: Omnigraph;
  private readonly embedder: Embedder;
  private readonly caches: Caches;
  private readonly contract: EmbeddingContract | null;
  private readonly registry: MetricRegistry;
  private readonly explorerUrl: string | null;
  private readonly defaultProfile: Profile;
  private readonly deadlineMs: number;
  private readonly log: (event: Record<string, unknown>) => void;
  catalog: CatalogState = { reachable: false, missing: [...REQUIRED_QUERIES], checkedAt: 0 };
  contractOk = false;
  contractReason: string | null = 'not checked yet';

  constructor(options: ServiceOptions) {
    this.omnigraph = options.omnigraph;
    this.embedder = options.embedder;
    this.caches = options.caches;
    this.contract = options.contract;
    this.registry = options.registry;
    this.explorerUrl = options.explorerUrl;
    this.defaultProfile = options.defaultProfile;
    this.deadlineMs = options.deadlineMs;
    this.log = options.log;
    if (options.contract === null) this.contractReason = 'the embedding contract could not be read';
  }

  get ready(): boolean {
    return this.catalog.reachable && this.catalog.missing.length === 0;
  }

  async checkCatalog(): Promise<CatalogState> {
    const signal = AbortSignal.timeout(this.deadlineMs);
    try {
      const served = await this.omnigraph.catalog(signal);
      this.catalog = { reachable: true, missing: REQUIRED_QUERIES.filter((name) => !served.has(name)), checkedAt: Date.now() };
      this.registry.set(METRICS.catalogChecked, {}, Math.floor(this.catalog.checkedAt / 1000));
    } catch {
      this.catalog = { reachable: false, missing: this.catalog.missing, checkedAt: this.catalog.checkedAt };
    }
    this.registry.set(METRICS.catalogComplete, {}, this.ready ? 1 : 0);
    this.registry.set(METRICS.catalogMissing, {}, this.catalog.missing.length);
    if (this.contract !== null) {
      try {
        const verdict = checkContract(this.contract, await this.omnigraph.schemaSource(signal));
        if (verdict.ok !== this.contractOk) this.log({ event: 'embedding_contract', ok: verdict.ok, reason: verdict.reason });
        this.contractOk = verdict.ok;
        this.contractReason = verdict.reason;
      } catch {
        this.contractReason = this.contractOk ? null : 'the schema could not be read';
      }
    }
    this.registry.set(METRICS.contractOk, {}, this.contractOk ? 1 : 0);
    return this.catalog;
  }

  async refreshCaches(): Promise<void> {
    try {
      await this.caches.refreshHead();
      this.registry.set(METRICS.cacheRows, { cache: 'bot_artifacts' }, this.caches.headRows);
      this.registry.set(METRICS.cacheRefreshed, { cache: 'bot_artifacts' }, Math.floor(this.caches.headAge / 1000));
    } catch (error) {
      this.log({ event: 'cache_refresh_failed', cache: 'bot_artifacts', reason: error instanceof UpstreamError ? error.outcome : 'error' });
    }
  }

  private finish(tool: string, surface: Surface, started: number, response: ToolResponse, extra: Record<string, unknown>): ToolResponse {
    const seconds = (performance.now() - started) / 1000;
    this.registry.increment(METRICS.calls, { tool, surface, outcome: response.outcome });
    this.registry.observe(METRICS.latency, { tool, surface }, seconds);
    if (!response.isError) this.registry.observe(METRICS.responseChars, { tool }, response.text.length);
    this.log({ event: 'call', tool, surface, outcome: response.outcome, ms: Math.round(seconds * 1000), ...extra });
    return response;
  }

  async search(args: Record<string, unknown>, surface: Surface): Promise<ToolResponse> {
    const started = performance.now();
    const question = typeof args['query'] === 'string' ? args['query'].trim() : typeof args['q'] === 'string' ? args['q'].trim() : '';
    if (question.length === 0 || question.length > MAX_QUESTION_CHARS) return this.finish('search', surface, started, invalid(MESSAGES.question), {});
    const scope = (args['scope'] ?? 'all') as Scope;
    if (!SCOPES.includes(scope)) return this.finish('search', surface, started, invalid(MESSAGES.scope), {});
    const limit = integer(args['limit'], DEFAULT_LIMIT);
    if (limit === null || limit < 1 || limit > MAX_LIMIT[surface]) return this.finish('search', surface, started, invalid(MESSAGES.limit(MAX_LIMIT[surface])), {});
    const profile = (surface === 'rest' ? args['profile'] ?? this.defaultProfile : this.defaultProfile) as Profile;
    if (!PROFILES.includes(profile)) return this.finish('search', surface, started, invalid(MESSAGES.profile), {});
    const snapshotRaw = surface === 'rest' ? args['snapshot'] : undefined;
    const snapshot = typeof snapshotRaw === 'string' && snapshotRaw.length > 0 ? snapshotRaw : null;
    if (snapshot !== null && !SNAPSHOT.test(snapshot)) return this.finish('search', surface, started, invalid(MESSAGES.snapshot), {});
    const debug = surface === 'rest' && truthy(args['debug']);
    const signal = AbortSignal.timeout(this.deadlineMs);
    let result: SearchResult;
    try {
      result = await search(
        { question, scope, limit, profile, snapshot },
        {
          stored: (name, params, pinned, legSignal) => this.omnigraph.stored(name, params, pinned, legSignal),
          embed: (text, embedSignal) => this.embedder.embed(text, embedSignal),
          bots: (pinned, botSignal) => this.caches.bots(pinned, botSignal),
          contractOk: () => this.contractOk,
        },
        signal,
      );
    } catch (error) {
      return this.finish('search', surface, started, failure(error, signal), { profile });
    }
    this.registry.increment(METRICS.searches, { profile, mode: result.mode });
    const elapsedMs = Math.round(performance.now() - started);
    const footer = { graphCommit: result.graphCommit, reranked: false, elapsedMs, degraded: result.degraded };
    const rendered = renderSearch(result, footer, this.explorerUrl);
    const toolRendered = surface === 'rest' && limit !== DEFAULT_LIMIT ? renderSearch({ ...result, sources: result.sources.slice(0, DEFAULT_LIMIT) }, footer, this.explorerUrl) : rendered;
    const structured: Record<string, unknown> = {
      profile: result.profile,
      graph_commit: result.graphCommit,
      degraded: result.degraded,
      reranked: false,
      mode: result.mode,
      elapsed_ms: elapsedMs,
      truncated: rendered.truncated,
      shown: rendered.shown,
      results: result.sources.map((source, index) => ({
        position: index + 1,
        ref: source.ref,
        document: source.document,
        kind: source.kind,
        title: source.title,
        doc_kind: source.docKind,
        date: source.date,
        link: linkFor(source, this.explorerUrl),
        snippet: snippet(source.text, result.terms, 600),
        similar: source.similar,
      })),
      related: result.related,
    };
    if (surface === 'rest') structured['tool_chars'] = toolRendered.text.length;
    if (debug) {
      structured['debug'] = {
        language: result.language,
        terms: result.terms,
        embed_seconds: result.embedSeconds,
        legs: result.legs,
        fused: result.sources.map((source) => ({ key: source.key, score: source.score, legs: source.legRanks, bot: source.bot })),
      };
    }
    const outcome: Outcome = result.sources.length === 0 ? 'empty' : 'ok';
    return this.finish('search', surface, started, { text: rendered.text, structured, isError: false, outcome, status: 200 }, {
      profile: result.profile,
      mode: result.mode,
      sources: result.sources.length,
      degraded: result.degraded,
      graph_commit: result.graphCommit,
    });
  }

  async read(args: Record<string, unknown>, surface: Surface): Promise<ToolResponse> {
    const started = performance.now();
    const raw = typeof args['ref'] === 'string' ? args['ref'] : '';
    const ref = parseRef(raw);
    if (ref.kind === 'invalid') return this.finish('read', surface, started, invalid(MESSAGES.ref), {});
    if (ref.kind === 'entity') return this.finish('read', surface, started, invalid(MESSAGES.entity), {});
    const around = integer(args['around'], MAX_AROUND);
    if (around === null || around < 0 || around > MAX_AROUND) return this.finish('read', surface, started, invalid(MESSAGES.around), {});
    const snapshotRaw = surface === 'rest' ? args['snapshot'] : undefined;
    const snapshot = typeof snapshotRaw === 'string' && snapshotRaw.length > 0 ? snapshotRaw : null;
    if (snapshot !== null && !SNAPSHOT.test(snapshot)) return this.finish('read', surface, started, invalid(MESSAGES.snapshot), {});
    const signal = AbortSignal.timeout(this.deadlineMs);
    try {
      const outcome = await readRef(ref, around, (name, params, pinned, readSignal) => this.omnigraph.stored(name, params, pinned, readSignal), snapshot, signal);
      if (outcome.view === null) {
        const response: ToolResponse = { text: MESSAGES.notFound, structured: { error: 'not_found', message: MESSAGES.notFound }, isError: true, outcome: 'not_found', status: 404 };
        return this.finish('read', surface, started, response, {});
      }
      const footer = { graphCommit: outcome.graphCommit, reranked: false, elapsedMs: Math.round(performance.now() - started), degraded: null };
      const rendered = renderRead(outcome.view, footer, this.explorerUrl);
      const view = outcome.view;
      const structured = {
        ref: view.ref,
        document: view.document,
        title: view.title,
        kind: view.kind,
        date: view.date,
        graph_commit: outcome.graphCommit,
        truncated: rendered.truncated,
        chunks: view.passages.map((passage) => passage.chunk).sort((left, right) => left - right),
      };
      return this.finish('read', surface, started, { text: rendered.text, structured, isError: false, outcome: 'ok', status: 200 }, { chunks: view.passages.length, graph_commit: outcome.graphCommit });
    } catch (error) {
      return this.finish('read', surface, started, failure(error, signal), {});
    }
  }
}
