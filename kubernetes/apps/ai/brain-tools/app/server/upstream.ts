export type Row = Record<string, unknown>;

export type UpstreamName = 'omnigraph' | 'litellm';

export type UpstreamOutcome = 'ok' | 'client_error' | 'not_found' | 'server_error' | 'unreachable' | 'timeout';

export class UpstreamError extends Error {
  readonly upstream: UpstreamName;
  readonly status: number;
  readonly outcome: UpstreamOutcome;

  constructor(upstream: UpstreamName, status: number, outcome: UpstreamOutcome) {
    super(`${upstream} ${outcome}${status > 0 ? ` (HTTP ${status})` : ''}`);
    this.upstream = upstream;
    this.status = status;
    this.outcome = outcome;
  }

  get unavailable(): boolean {
    return this.outcome === 'server_error' || this.outcome === 'unreachable' || this.outcome === 'timeout';
  }
}

export type Recorder = (upstream: UpstreamName, outcome: UpstreamOutcome) => void;

export interface QueryResult {
  rows: Row[];
  graphCommit: string | null;
  seconds: number;
}

function outcomeFor(status: number): UpstreamOutcome {
  if (status === 404) return 'not_found';
  if (status >= 500) return 'server_error';
  return 'client_error';
}

function isTimeout(error: unknown): boolean {
  return error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
}

async function exchange(
  upstream: UpstreamName,
  fetchImpl: typeof fetch,
  record: Recorder,
  target: string,
  init: RequestInit,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(target, init);
  } catch (error) {
    const outcome: UpstreamOutcome = isTimeout(error) ? 'timeout' : 'unreachable';
    record(upstream, outcome);
    throw new UpstreamError(upstream, 0, outcome);
  }
  let text: string;
  try {
    text = await response.text();
  } catch (error) {
    const outcome: UpstreamOutcome = isTimeout(error) ? 'timeout' : 'unreachable';
    record(upstream, outcome);
    throw new UpstreamError(upstream, response.status, outcome);
  }
  if (!response.ok) {
    const outcome = outcomeFor(response.status);
    record(upstream, outcome);
    throw new UpstreamError(upstream, response.status, outcome);
  }
  record(upstream, 'ok');
  if (text.length === 0) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new UpstreamError(upstream, response.status, 'server_error');
  }
}

const QUERY_NAME = /^[a-z][a-z0-9_]{0,63}$/;

export interface OmnigraphOptions {
  baseUrl: string;
  graph: string;
  token: string;
  record: Recorder;
  fetch?: typeof fetch;
}

export class Omnigraph {
  private readonly baseUrl: string;
  private readonly graph: string;
  private readonly token: string;
  private readonly record: Recorder;
  private readonly fetchImpl: typeof fetch;

  constructor(options: OmnigraphOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.graph = options.graph;
    this.token = options.token;
    this.record = options.record;
    this.fetchImpl = options.fetch ?? fetch;
  }

  private headers(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}`, Accept: 'application/json' };
  }

  async stored(name: string, params: Record<string, unknown>, snapshot: string | null, signal: AbortSignal): Promise<QueryResult> {
    if (!QUERY_NAME.test(name)) throw new Error(`refusing to invoke a stored query named '${name}'`);
    const started = performance.now();
    const body = snapshot === null ? { params } : { params, snapshot };
    const result = (await exchange('omnigraph', this.fetchImpl, this.record, `${this.baseUrl}/graphs/${this.graph}/queries/${name}`, {
      method: 'POST',
      headers: { ...this.headers(), 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })) as { rows?: Row[]; graph_commit_id?: string | null } | null;
    return {
      rows: Array.isArray(result?.rows) ? result.rows : [],
      graphCommit: typeof result?.graph_commit_id === 'string' ? result.graph_commit_id : null,
      seconds: (performance.now() - started) / 1000,
    };
  }

  async catalog(signal: AbortSignal): Promise<Set<string>> {
    const result = (await exchange('omnigraph', this.fetchImpl, this.record, `${this.baseUrl}/graphs/${this.graph}/queries`, {
      method: 'GET',
      headers: this.headers(),
      signal,
    })) as { queries?: { name?: unknown }[] } | null;
    return new Set((result?.queries ?? []).map((entry) => entry.name).filter((name): name is string => typeof name === 'string'));
  }

  async schemaSource(signal: AbortSignal): Promise<string> {
    const result = (await exchange('omnigraph', this.fetchImpl, this.record, `${this.baseUrl}/graphs/${this.graph}/schema`, {
      method: 'GET',
      headers: this.headers(),
      signal,
    })) as { schema_source?: unknown } | null;
    return typeof result?.schema_source === 'string' ? result.schema_source : '';
  }
}

export interface EmbedderOptions {
  baseUrl: string;
  key: string | null;
  model: string;
  dimensions: number;
  record: Recorder;
  fetch?: typeof fetch;
}

export function l2Normalise(vector: readonly number[]): number[] {
  const norm = Math.sqrt(vector.reduce((sum, value) => sum + value * value, 0));
  return norm > 0 ? vector.map((value) => value / norm) : [...vector];
}

export class Embedder {
  private readonly baseUrl: string;
  private readonly key: string | null;
  private readonly model: string;
  private readonly dimensions: number;
  private readonly record: Recorder;
  private readonly fetchImpl: typeof fetch;

  constructor(options: EmbedderOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.key = options.key;
    this.model = options.model;
    this.dimensions = options.dimensions;
    this.record = options.record;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async embed(text: string, signal: AbortSignal): Promise<number[]> {
    if (this.key === null) throw new UpstreamError('litellm', 0, 'client_error');
    const result = (await exchange('litellm', this.fetchImpl, this.record, `${this.baseUrl}/v1/embeddings`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${this.key}`, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ model: this.model, input: [text], dimensions: this.dimensions }),
      signal,
    })) as { data?: { embedding?: unknown }[] } | null;
    const vector = result?.data?.[0]?.embedding;
    if (!Array.isArray(vector) || vector.length !== this.dimensions || !vector.every((value) => typeof value === 'number' && Number.isFinite(value))) {
      throw new UpstreamError('litellm', 200, 'server_error');
    }
    return l2Normalise(vector as number[]);
  }
}
