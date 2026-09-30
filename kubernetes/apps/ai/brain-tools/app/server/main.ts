import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import process from 'node:process';
import { Caches } from './caches.ts';
import { ConfigError, loadConfig } from './config.ts';
import { ContractError, parseContract } from './contract.ts';
import type { EmbeddingContract } from './contract.ts';
import { createMcpHandler } from './mcp.ts';
import { METRICS, MetricRegistry, declareMetrics } from './metrics.ts';
import { createRestHandler } from './rest.ts';
import { BrainService } from './service.ts';
import { Embedder, Omnigraph } from './upstream.ts';

function log(event: Record<string, unknown>): void {
  process.stdout.write(`${JSON.stringify({ time: new Date().toISOString(), ...event })}\n`);
}

function readContract(path: string): EmbeddingContract | null {
  try {
    return parseContract(readFileSync(path, 'utf8'));
  } catch (error) {
    log({ event: 'embedding_contract_unreadable', reason: error instanceof ContractError ? error.message : 'the contract file cannot be read' });
    return null;
  }
}

function start(): void {
  let config;
  try {
    config = loadConfig(process.env);
  } catch (error) {
    if (error instanceof ConfigError) {
      process.stderr.write(`brain-tools: ${error.message}\n`);
      process.exit(1);
    }
    throw error;
  }
  const registry = new MetricRegistry();
  declareMetrics(registry);
  registry.set(METRICS.build, { version: config.version, profile: config.defaultProfile }, 1);
  const record = (upstream: string, outcome: string): void => registry.increment(METRICS.upstream, { upstream, outcome });
  const contract = readContract(config.contractFile);
  const omnigraph = new Omnigraph({ baseUrl: config.omnigraphUrl, graph: config.graph, token: config.readerToken, record });
  const embedder = new Embedder({ baseUrl: config.litellmUrl, key: config.litellmKey, model: contract?.model ?? '', dimensions: contract?.dimensions ?? 0, record });
  const caches = new Caches({ omnigraph, deadlineMs: config.deadlineMs });
  const service = new BrainService({
    omnigraph,
    embedder,
    caches,
    contract,
    registry,
    explorerUrl: config.explorerUrl,
    defaultProfile: config.defaultProfile,
    deadlineMs: config.deadlineMs,
    log,
  });
  const mcp = createServer(createMcpHandler({ service, name: 'brain-tools', version: config.version }));
  const rest = createServer(createRestHandler({ service, registry }));
  for (const server of [mcp, rest]) {
    server.requestTimeout = config.deadlineMs + 5_000;
    server.headersTimeout = 10_000;
    server.keepAliveTimeout = 65_000;
  }
  mcp.listen(config.mcpListen.port, config.mcpListen.host, () => log({ event: 'listening', surface: 'mcp', port: config.mcpListen.port }));
  rest.listen(config.restListen.port, config.restListen.host, () => log({ event: 'listening', surface: 'rest', port: config.restListen.port }));
  let wasReady: boolean | null = null;
  const check = (): void => {
    service
      .checkCatalog()
      .then((catalog) => {
        if (service.ready !== wasReady) log({ event: 'catalog', ready: service.ready, reachable: catalog.reachable, missing: catalog.missing.length, embedding_contract_ok: service.contractOk });
        wasReady = service.ready;
      })
      .catch(() => undefined);
  };
  const refresh = (): void => {
    service.refreshCaches().catch(() => undefined);
  };
  check();
  refresh();
  const catalogTimer = setInterval(check, config.catalogRefreshMs);
  const cacheTimer = setInterval(refresh, config.cacheRefreshMs);
  const stop = (): void => {
    clearInterval(catalogTimer);
    clearInterval(cacheTimer);
    mcp.close();
    rest.close();
    setTimeout(() => process.exit(0), 5_000).unref();
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
}

start();
