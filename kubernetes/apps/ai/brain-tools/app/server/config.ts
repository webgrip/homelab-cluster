import { readFileSync } from 'node:fs';

export type Profile = 'p0' | 'p1';

export const PROFILES: readonly Profile[] = ['p0', 'p1'];

export interface Listen {
  host: string;
  port: number;
}

export interface Config {
  omnigraphUrl: string;
  graph: string;
  readerToken: string;
  litellmUrl: string;
  litellmKey: string | null;
  contractFile: string;
  mcpListen: Listen;
  restListen: Listen;
  explorerUrl: string | null;
  defaultProfile: Profile;
  deadlineMs: number;
  catalogRefreshMs: number;
  cacheRefreshMs: number;
  version: string;
}

export class ConfigError extends Error {}

export type Env = Record<string, string | undefined>;

const TOKEN = /^[A-Za-z0-9._~+/=-]{16,4096}$/;
const GRAPH = /^[A-Za-z0-9_-]{1,64}$/;

function address(raw: string, name: string): Listen {
  const match = /^([A-Za-z0-9.:[\]-]+):(\d{1,5})$/.exec(raw);
  if (match === null) throw new ConfigError(`${name} must be host:port, got '${raw}'`);
  return { host: match[1]!, port: Number(match[2]) };
}

function url(raw: string, name: string): string {
  try {
    return new URL(raw).toString().replace(/\/+$/, '');
  } catch {
    throw new ConfigError(`${name} is not a URL: '${raw}'`);
  }
}

function positive(raw: string | undefined, fallback: number, name: string): number {
  if (raw === undefined || raw.trim().length === 0) return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) throw new ConfigError(`${name} must be a positive number, got '${raw}'`);
  return value;
}

function secret(env: Env, fileVar: string, valueVar: string, read: (path: string) => string): string | null {
  const file = env[fileVar];
  if (file !== undefined && file.length > 0) {
    try {
      return read(file).replace(/[\r\n]+$/, '');
    } catch {
      if (env[valueVar] === undefined) throw new ConfigError(`${fileVar} points at ${file}, which cannot be read`);
    }
  }
  return env[valueVar] ?? null;
}

export function loadConfig(env: Env, read: (path: string) => string = (path) => readFileSync(path, 'utf8')): Config {
  const readerToken = secret(env, 'OMNIGRAPH_TOKEN_FILE', 'OMNIGRAPH_TOKEN', read);
  if (readerToken === null) throw new ConfigError('no act-brain-reader token: set OMNIGRAPH_TOKEN_FILE or OMNIGRAPH_TOKEN');
  if (!TOKEN.test(readerToken)) throw new ConfigError('the act-brain-reader token must be 16 to 4096 characters of [A-Za-z0-9._~+/=-]');
  const litellmKey = secret(env, 'LITELLM_KEY_FILE', 'LITELLM_KEY', read);
  const graph = env['OMNIGRAPH_GRAPH'] ?? 'brain';
  if (!GRAPH.test(graph)) throw new ConfigError(`OMNIGRAPH_GRAPH must be a graph id, got '${graph}'`);
  const profile = env['BRAIN_TOOLS_PROFILE'] ?? 'p0';
  if (!PROFILES.includes(profile as Profile)) throw new ConfigError(`BRAIN_TOOLS_PROFILE must be one of ${PROFILES.join(', ')}, got '${profile}'`);
  const explorer = env['BRAIN_EXPLORER_URL']?.trim();
  return {
    omnigraphUrl: url(env['OMNIGRAPH_URL'] ?? 'http://omnigraph.ai.svc.cluster.local:8080', 'OMNIGRAPH_URL'),
    graph,
    readerToken,
    litellmUrl: url(env['LITELLM_URL'] ?? 'http://litellm.ai.svc.cluster.local:4000', 'LITELLM_URL'),
    litellmKey,
    contractFile: env['EMBEDDING_CONTRACT_FILE'] ?? '/etc/omnigraph-embedding-contract/contract.json',
    mcpListen: address(env['MCP_LISTEN'] ?? '0.0.0.0:8080', 'MCP_LISTEN'),
    restListen: address(env['REST_LISTEN'] ?? '0.0.0.0:8081', 'REST_LISTEN'),
    explorerUrl: explorer === undefined || explorer.length === 0 ? null : url(explorer, 'BRAIN_EXPLORER_URL'),
    defaultProfile: profile as Profile,
    deadlineMs: positive(env['BRAIN_TOOLS_DEADLINE_SECONDS'], 8, 'BRAIN_TOOLS_DEADLINE_SECONDS') * 1000,
    catalogRefreshMs: positive(env['BRAIN_TOOLS_CATALOG_REFRESH_SECONDS'], 30, 'BRAIN_TOOLS_CATALOG_REFRESH_SECONDS') * 1000,
    cacheRefreshMs: positive(env['BRAIN_TOOLS_CACHE_REFRESH_SECONDS'], 900, 'BRAIN_TOOLS_CACHE_REFRESH_SECONDS') * 1000,
    version: env['BRAIN_TOOLS_VERSION'] ?? '0.1.0',
  };
}
