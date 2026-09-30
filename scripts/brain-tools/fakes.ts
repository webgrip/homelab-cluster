import { createServer } from 'node:http';
import type { IncomingMessage, Server, ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { Caches } from '../../kubernetes/apps/ai/brain-tools/app/server/caches.ts';
import type { Profile } from '../../kubernetes/apps/ai/brain-tools/app/server/config.ts';
import { createMcpHandler } from '../../kubernetes/apps/ai/brain-tools/app/server/mcp.ts';
import { MetricRegistry, declareMetrics } from '../../kubernetes/apps/ai/brain-tools/app/server/metrics.ts';
import { createRestHandler } from '../../kubernetes/apps/ai/brain-tools/app/server/rest.ts';
import { REQUIRED_QUERIES } from '../../kubernetes/apps/ai/brain-tools/app/server/search.ts';
import { BrainService } from '../../kubernetes/apps/ai/brain-tools/app/server/service.ts';
import { Embedder, Omnigraph } from '../../kubernetes/apps/ai/brain-tools/app/server/upstream.ts';

export type Row = Record<string, unknown>;

export const MODEL = 'granite-embedding-97m-multilingual-r2';
export const COMMIT = '01M3SYNTHETICCOMMIT00000000';

export function schemaWith(model: string, dimensions = 384): string {
  return [
    'node Note {\n    slug: String @key\n    content: String? @index\n    embedding: Vector(DIM)? @embed("content", model="MODEL")\n}',
    'node Passage {\n    text: String @index\n    embedding: Vector(DIM)? @embed("text", model="MODEL")\n}',
    'node Topic {\n    slug: String @key\n    name: String @index\n    embedding: Vector(DIM)? @embed("name", model="MODEL")\n}',
  ]
    .join('\n\n')
    .replaceAll('MODEL', model)
    .replaceAll('DIM', String(dimensions));
}

export interface Call {
  name: string;
  params: Record<string, unknown>;
  snapshot: string | null;
}

export class FakeOmnigraph {
  rows: Record<string, Row[]> = {};
  catalog: string[] = [...REQUIRED_QUERIES];
  schema = schemaWith(MODEL);
  failWith: number | null = null;
  delayMs = 0;
  calls: Call[] = [];
  private server: Server | null = null;

  async start(): Promise<string> {
    this.server = createServer((request: IncomingMessage, response: ServerResponse) => {
      const chunks: Buffer[] = [];
      request.on('data', (chunk: Buffer) => chunks.push(chunk));
      request.on('end', () => {
        setTimeout(() => this.answer(request, Buffer.concat(chunks).toString('utf8'), response), this.delayMs);
      });
    });
    await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve));
    return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`;
  }

  private answer(request: IncomingMessage, body: string, response: ServerResponse): void {
    const send = (status: number, payload: unknown): void => {
      response.writeHead(status, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify(payload));
    };
    if (request.headers['authorization'] !== 'Bearer reader-token-0123456789') {
      send(401, { error: 'unauthorized' });
      return;
    }
    if (this.failWith !== null) {
      send(this.failWith, { error: 'failing on purpose' });
      return;
    }
    const url = request.url ?? '';
    if (request.method === 'GET' && url === '/graphs/brain/queries') {
      send(200, { queries: this.catalog.map((name) => ({ name, tool_name: name, mutation: false, params: [] })) });
      return;
    }
    if (request.method === 'GET' && url === '/graphs/brain/schema') {
      send(200, { schema_source: this.schema });
      return;
    }
    const match = /^\/graphs\/brain\/queries\/([a-z_0-9]+)$/.exec(url);
    if (request.method === 'POST' && match !== null) {
      const name = match[1]!;
      const parsed = JSON.parse(body || '{}') as { params?: Record<string, unknown>; snapshot?: string };
      this.calls.push({ name, params: parsed.params ?? {}, snapshot: parsed.snapshot ?? null });
      if (!this.catalog.includes(name)) {
        send(404, { error: `no stored query ${name}` });
        return;
      }
      const rows = this.rows[name] ?? [];
      send(200, { query_name: name, target: { branch: 'main' }, row_count: rows.length, rows, graph_commit_id: parsed.snapshot ?? COMMIT });
      return;
    }
    send(404, { error: 'not found' });
  }

  calledWith(name: string): Call[] {
    return this.calls.filter((call) => call.name === name);
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => this.server?.close(() => resolve()));
  }
}

export class FakeLiteLLM {
  inputs: string[] = [];
  failWith: number | null = null;
  vector: number[] = Array.from({ length: 384 }, (_, index) => (index % 7) - 3);
  private server: Server | null = null;

  async start(): Promise<string> {
    this.server = createServer((request, response) => {
      const chunks: Buffer[] = [];
      request.on('data', (chunk: Buffer) => chunks.push(chunk));
      request.on('end', () => {
        const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as { input?: string[] };
        this.inputs.push(...(parsed.input ?? []));
        if (this.failWith !== null) {
          response.writeHead(this.failWith, { 'Content-Type': 'application/json' });
          response.end('{"error":{"type":"failing"}}');
          return;
        }
        response.writeHead(200, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ data: [{ index: 0, embedding: this.vector }] }));
      });
    });
    await new Promise<void>((resolve) => this.server!.listen(0, '127.0.0.1', resolve));
    return `http://127.0.0.1:${(this.server.address() as AddressInfo).port}`;
  }

  async stop(): Promise<void> {
    await new Promise<void>((resolve) => this.server?.close(() => resolve()));
  }
}

export interface Rig {
  omnigraph: FakeOmnigraph;
  litellm: FakeLiteLLM;
  service: BrainService;
  registry: MetricRegistry;
  logs: string[];
  mcpUrl: string;
  restUrl: string;
  stop: () => Promise<void>;
}

export interface RigOptions {
  profile?: Profile;
  deadlineMs?: number;
  contractModel?: string;
  explorerUrl?: string | null;
}

export async function rig(options: RigOptions = {}): Promise<Rig> {
  const omnigraph = new FakeOmnigraph();
  const litellm = new FakeLiteLLM();
  const omnigraphUrl = await omnigraph.start();
  const litellmUrl = await litellm.start();
  const registry = new MetricRegistry();
  declareMetrics(registry);
  const record = (upstream: string, outcome: string): void => registry.increment('brain_tools_upstream_requests_total', { upstream, outcome });
  const client = new Omnigraph({ baseUrl: omnigraphUrl, graph: 'brain', token: 'reader-token-0123456789', record });
  const contract = { model: options.contractModel ?? MODEL, dimensions: 384 };
  const embedder = new Embedder({ baseUrl: litellmUrl, key: 'sk-test', model: contract.model, dimensions: 384, record });
  const logs: string[] = [];
  const deadlineMs = options.deadlineMs ?? 4000;
  const service = new BrainService({
    omnigraph: client,
    embedder,
    caches: new Caches({ omnigraph: client, deadlineMs }),
    contract,
    registry,
    explorerUrl: options.explorerUrl === undefined ? 'https://graph.example.test' : options.explorerUrl,
    defaultProfile: options.profile ?? 'p1',
    deadlineMs,
    log: (event) => logs.push(JSON.stringify(event)),
  });
  const mcp = createServer(createMcpHandler({ service, name: 'brain-tools', version: 'test' }));
  const rest = createServer(createRestHandler({ service, registry }));
  await new Promise<void>((resolve) => mcp.listen(0, '127.0.0.1', resolve));
  await new Promise<void>((resolve) => rest.listen(0, '127.0.0.1', resolve));
  return {
    omnigraph,
    litellm,
    service,
    registry,
    logs,
    mcpUrl: `http://127.0.0.1:${(mcp.address() as AddressInfo).port}/mcp`,
    restUrl: `http://127.0.0.1:${(rest.address() as AddressInfo).port}`,
    stop: async () => {
      mcp.closeAllConnections();
      rest.closeAllConnections();
      await Promise.all([new Promise((resolve) => mcp.close(resolve)), new Promise((resolve) => rest.close(resolve)), omnigraph.stop(), litellm.stop()]);
    },
  };
}

export function docRow(slug: string, chunk: number, text: string, extra: Partial<Record<string, unknown>> = {}): Row {
  return {
    'p.@id': `${slug}#${chunk}`,
    'a.slug': slug,
    'a.name': `Title of ${slug.split('/').pop()}`,
    'a.kind': 'document',
    'a.url': `https://forge.example.test/${slug}`,
    'a.timestamp': '2026-09-01T08:00:00',
    'p.chunk_index': chunk,
    'p.text': text,
    ...extra,
  };
}

export function noteRow(tail: string, chunk: number, text: string, extra: Partial<Record<string, unknown>> = {}): Row {
  return {
    'p.@id': `obsidian-file/${tail}#${chunk}`,
    'a.slug': `obsidian-file/${tail}`,
    'n.slug': `obsidian/${tail}`,
    'n.name': `Note ${tail}`,
    'n.kind': 'idea',
    'n.updatedAt': '2026-09-02T08:00:00',
    'p.chunk_index': chunk,
    'p.text': text,
    ...extra,
  };
}

export function captureRow(slug: string, text: string): Row {
  return { 'n.slug': slug, 'n.name': `Capture ${slug}`, 'n.kind': 'idea', 'n.updatedAt': '2026-09-03T08:00:00', 'n.content': text };
}

export function topicRow(slug: string, name: string): Row {
  return { 't.slug': slug, 't.name': name, 't.description': `About ${name}` };
}

export const LONG = (seed: string): string => `${seed} ` + 'filler words that make this chunk comfortably longer than eighty characters in total. '.repeat(2);

export async function postJson(url: string, body: unknown, headers: Record<string, string> = {}): Promise<{ status: number; json: any; text: string }> {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...headers }, body: typeof body === 'string' ? body : JSON.stringify(body) });
  const text = await response.text();
  let json: any = null;
  try {
    json = text.length > 0 ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  return { status: response.status, json, text };
}

export async function getJson(url: string): Promise<{ status: number; json: any }> {
  const response = await fetch(url);
  const text = await response.text();
  return { status: response.status, json: text.length > 0 ? JSON.parse(text) : null };
}

export async function callTool(rigged: Rig, name: string, args: Record<string, unknown>): Promise<any> {
  const reply = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 7, method: 'tools/call', params: { name, arguments: args } });
  return reply.json.result;
}
