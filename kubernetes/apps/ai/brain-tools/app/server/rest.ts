import type { IncomingMessage, ServerResponse } from 'node:http';
import type { MetricRegistry } from './metrics.ts';
import { MAX_BODY_BYTES, readBody } from './mcp.ts';
import type { BrainService, ToolResponse } from './service.ts';

export interface RestOptions {
  service: BrainService;
  registry: MetricRegistry;
}

function sendJson(response: ServerResponse, status: number, body: unknown): void {
  response.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  response.end(JSON.stringify(body));
}

function toolBody(result: ToolResponse): Record<string, unknown> {
  return result.isError ? { ...result.structured, outcome: result.outcome } : { ...result.structured, outcome: result.outcome, text: result.text };
}

async function argumentsOf(request: IncomingMessage, query: URLSearchParams): Promise<Record<string, unknown> | null> {
  if (request.method === 'GET') return Object.fromEntries(query.entries());
  const body = await readBody(request, MAX_BODY_BYTES);
  if (body === null) return null;
  if (body.trim().length === 0) return {};
  const parsed: unknown = JSON.parse(body);
  return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
}

export function createRestHandler(options: RestOptions): (request: IncomingMessage, response: ServerResponse) => void {
  const { service, registry } = options;
  return (request, response) => {
    const url = new URL(request.url ?? '/', 'http://brain-tools.local');
    const path = url.pathname;
    if (request.method === 'GET' && path === '/healthz') {
      response.writeHead(200, { 'Content-Type': 'text/plain' });
      response.end('ok\n');
      return;
    }
    if (request.method === 'GET' && path === '/readyz') {
      sendJson(response, service.ready ? 200 : 503, {
        ready: service.ready,
        omnigraph_reachable: service.catalog.reachable,
        missing_queries: service.catalog.missing,
        embedding_contract_ok: service.contractOk,
        embedding_contract_reason: service.contractReason,
      });
      return;
    }
    if (request.method === 'GET' && path === '/metrics') {
      response.writeHead(200, { 'Content-Type': 'text/plain; version=0.0.4; charset=utf-8' });
      response.end(registry.render());
      return;
    }
    const tool = path === '/api/search' ? 'search' : path === '/api/read' ? 'read' : null;
    if (tool === null) {
      sendJson(response, 404, { error: 'not_found', message: 'brain-tools REST serves /api/search, /api/read, /metrics, /healthz and /readyz' });
      return;
    }
    if (request.method !== 'GET' && request.method !== 'POST') {
      response.writeHead(405, { Allow: 'GET, POST' });
      response.end();
      return;
    }
    argumentsOf(request, url.searchParams)
      .then(async (args) => {
        if (args === null) {
          sendJson(response, 400, { error: 'invalid', message: `send a JSON object of at most ${MAX_BODY_BYTES} bytes` });
          return;
        }
        const result = tool === 'search' ? await service.search(args, 'rest') : await service.read(args, 'rest');
        sendJson(response, result.status, toolBody(result));
      })
      .catch(() => {
        if (!response.headersSent) sendJson(response, 400, { error: 'invalid', message: 'the request body is not JSON' });
      });
  };
}
