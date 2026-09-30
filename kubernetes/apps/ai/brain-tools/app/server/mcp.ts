import type { IncomingMessage, ServerResponse } from 'node:http';
import { DEFAULT_LIMIT, MAX_LIMIT, MAX_QUESTION_CHARS } from './service.ts';
import type { BrainService, ToolResponse } from './service.ts';
import { MAX_AROUND, MAX_REF_CHARS } from './read.ts';
import { SCOPES } from './search.ts';

export const PROTOCOL_VERSIONS: readonly string[] = ['2025-06-18', '2025-03-26', '2024-11-05'];
export const MAX_BODY_BYTES = 16 * 1024;

export const INSTRUCTIONS =
  "Ryan's second brain: his Obsidian notes, his captures and his Forgejo repositories' docs, ADRs, issues and pull requests. " +
  'Use search first for any question about his work, notes, decisions, people or projects, then read a ref for more context. ' +
  'Cite the link of every source you use. Say plainly when the brain has nothing; do not answer from general knowledge unless asked. ' +
  'Private: never copy brain content into git, tickets or public pages.';

export interface ToolDefinition {
  name: string;
  title: string;
  description: string;
  inputSchema: Record<string, unknown>;
  annotations: Record<string, unknown>;
}

export const TOOLS: readonly ToolDefinition[] = [
  {
    name: 'search',
    title: 'Search the brain',
    description:
      "Search Ryan's second brain (Obsidian notes, captures, and the docs, ADRs, issues and pull requests of his Forgejo repositories). " +
      'Use it first for any question about his work, notes, decisions, people or projects. ' +
      'Pass the question or 2 to 8 key words in plain Dutch or English, never a query language. ' +
      'Returns numbered sources, best first, each with a ref, a link and a snippet; cite the link, and open a source with read(ref).',
    inputSchema: {
      type: 'object',
      properties: {
        query: { type: 'string', minLength: 1, maxLength: MAX_QUESTION_CHARS, description: 'The question or key words, in Dutch or English' },
        scope: { type: 'string', enum: [...SCOPES], default: 'all', description: 'all, notes (Obsidian notes and captures) or docs (Forgejo documents, issues and pull requests)' },
        limit: { type: 'integer', minimum: 1, maximum: MAX_LIMIT.mcp, default: DEFAULT_LIMIT, description: 'How many sources to return' },
      },
      required: ['query'],
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true, openWorldHint: false, idempotentHint: true },
  },
  {
    name: 'read',
    title: 'Read a brain source',
    description:
      'Open a source that search returned, by its ref exactly as given (doc:<slug>#<chunk> or note:<slug>#<chunk>), with its neighbouring chunks. ' +
      'Use it instead of guessing when a snippet is not enough.',
    inputSchema: {
      type: 'object',
      properties: {
        ref: { type: 'string', minLength: 1, maxLength: MAX_REF_CHARS, description: 'A ref exactly as search returned it' },
        around: { type: 'integer', minimum: 0, maximum: MAX_AROUND, default: MAX_AROUND, description: 'Neighbouring chunks to include on each side' },
      },
      required: ['ref'],
      additionalProperties: false,
    },
    annotations: { readOnlyHint: true, openWorldHint: false, idempotentHint: true },
  },
];

interface JsonRpcRequest {
  jsonrpc?: unknown;
  id?: unknown;
  method?: unknown;
  params?: unknown;
}

type JsonRpcId = string | number | null;

export interface JsonRpcReply {
  jsonrpc: '2.0';
  id: JsonRpcId;
  result?: unknown;
  error?: { code: number; message: string };
}

function reply(id: JsonRpcId, result: unknown): JsonRpcReply {
  return { jsonrpc: '2.0', id, result };
}

function fault(id: JsonRpcId, code: number, message: string): JsonRpcReply {
  return { jsonrpc: '2.0', id, error: { code, message } };
}

function validId(id: unknown): id is string | number {
  return typeof id === 'string' || (typeof id === 'number' && Number.isFinite(id));
}

function toolResult(response: ToolResponse): Record<string, unknown> {
  return { content: [{ type: 'text', text: response.text }], structuredContent: response.structured, isError: response.isError };
}

export interface McpOptions {
  service: BrainService;
  name: string;
  version: string;
}

export async function handleMessage(message: JsonRpcRequest, options: McpOptions): Promise<JsonRpcReply | null> {
  if (message === null || typeof message !== 'object' || Array.isArray(message)) return fault(null, -32600, 'Invalid Request');
  if (message.jsonrpc !== '2.0' || typeof message.method !== 'string') return fault(validId(message.id) ? message.id : null, -32600, 'Invalid Request');
  if (!('id' in message)) return null;
  if (!validId(message.id)) return fault(null, -32600, 'Invalid Request: id must be a string or a number');
  const id = message.id;
  const params = (message.params ?? {}) as Record<string, unknown>;
  switch (message.method) {
    case 'initialize': {
      const asked = typeof params['protocolVersion'] === 'string' ? params['protocolVersion'] : '';
      return reply(id, {
        protocolVersion: PROTOCOL_VERSIONS.includes(asked) ? asked : PROTOCOL_VERSIONS[0],
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: options.name, version: options.version },
        instructions: INSTRUCTIONS,
      });
    }
    case 'ping':
      return reply(id, {});
    case 'tools/list':
      return reply(id, { tools: TOOLS });
    case 'tools/call': {
      const name = params['name'];
      const args = params['arguments'];
      if (args !== undefined && (args === null || typeof args !== 'object' || Array.isArray(args))) return fault(id, -32602, 'Invalid params: arguments must be an object');
      const input = (args ?? {}) as Record<string, unknown>;
      if (name === 'search') return reply(id, toolResult(await options.service.search(input, 'mcp')));
      if (name === 'read') return reply(id, toolResult(await options.service.read(input, 'mcp')));
      return fault(id, -32602, `Unknown tool: ${typeof name === 'string' ? name.slice(0, 64) : 'none'}. The tools are search and read.`);
    }
    default:
      return fault(id, -32601, 'Method not found');
  }
}

export function readBody(request: IncomingMessage, limit: number): Promise<string | null> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    let size = 0;
    let over = false;
    request.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > limit) {
        over = true;
        return;
      }
      chunks.push(chunk);
    });
    request.on('end', () => resolve(over ? null : Buffer.concat(chunks).toString('utf8')));
    request.on('error', reject);
  });
}

function send(response: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
  const payload = body === undefined ? '' : JSON.stringify(body);
  response.writeHead(status, { ...(payload.length > 0 ? { 'Content-Type': 'application/json' } : {}), ...headers });
  response.end(payload);
}

export function createMcpHandler(options: McpOptions): (request: IncomingMessage, response: ServerResponse) => void {
  return (request, response) => {
    const path = (request.url ?? '/').split('?')[0];
    if (path === '/healthz' && request.method === 'GET') {
      response.writeHead(200, { 'Content-Type': 'text/plain' });
      response.end('ok\n');
      return;
    }
    if (path !== '/mcp' && path !== '/mcp/') {
      send(response, 404, { error: 'not found' });
      return;
    }
    if (request.method !== 'POST') {
      send(response, 405, fault(null, -32000, 'Method not allowed: this server is stateless and only answers POST'), { Allow: 'POST' });
      return;
    }
    if (request.headers['origin'] !== undefined) {
      send(response, 403, fault(null, -32000, 'Browser origins are refused'));
      return;
    }
    readBody(request, MAX_BODY_BYTES)
      .then(async (body) => {
        if (body === null) {
          send(response, 413, fault(null, -32600, `Request body over ${MAX_BODY_BYTES} bytes`));
          return;
        }
        let parsed: unknown;
        try {
          parsed = JSON.parse(body);
        } catch {
          send(response, 400, fault(null, -32700, 'Parse error'));
          return;
        }
        if (Array.isArray(parsed)) {
          if (parsed.length === 0) {
            send(response, 400, fault(null, -32600, 'Invalid Request: empty batch'));
            return;
          }
          const replies = (await Promise.all(parsed.map((item) => handleMessage(item as JsonRpcRequest, options)))).filter((item): item is JsonRpcReply => item !== null);
          if (replies.length === 0) send(response, 202, undefined);
          else send(response, 200, replies);
          return;
        }
        const answer = await handleMessage(parsed as JsonRpcRequest, options);
        if (answer === null) send(response, 202, undefined);
        else send(response, 200, answer);
      })
      .catch(() => {
        if (!response.headersSent) send(response, 500, fault(null, -32603, 'Internal error'));
      });
  };
}
