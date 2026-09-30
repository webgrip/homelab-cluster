export type Labels = Record<string, string>;

type Kind = 'gauge' | 'counter' | 'histogram';

interface Sample {
  labels: Labels;
  value: number;
}

interface HistogramSample {
  labels: Labels;
  counts: number[];
  sum: number;
  count: number;
}

interface Family {
  help: string;
  kind: Kind;
  buckets: readonly number[];
  samples: Map<string, Sample>;
  histograms: Map<string, HistogramSample>;
}

export const LATENCY_BUCKETS: readonly number[] = [0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 8];

function labelKey(labels: Labels): string {
  return Object.keys(labels)
    .sort()
    .map((name) => `${name}=${labels[name]}`)
    .join('\u0000');
}

function escapeLabel(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\n/g, '\\n').replace(/"/g, '\\"');
}

function renderLabels(labels: Labels, extra: Labels = {}): string {
  const merged = { ...labels, ...extra };
  const rendered = Object.keys(merged)
    .sort()
    .map((name) => `${name}="${escapeLabel(merged[name]!)}"`)
    .join(',');
  return rendered.length > 0 ? `{${rendered}}` : '';
}

function formatNumber(value: number): string {
  if (value === Number.POSITIVE_INFINITY) return '+Inf';
  return Number.isFinite(value) ? String(value) : '0';
}

export class MetricRegistry {
  private readonly families = new Map<string, Family>();

  declare(name: string, kind: Kind, help: string, buckets: readonly number[] = LATENCY_BUCKETS): void {
    if (!this.families.has(name)) this.families.set(name, { help, kind, buckets, samples: new Map(), histograms: new Map() });
  }

  private family(name: string, kind: Kind): Family {
    const family = this.families.get(name);
    if (family === undefined) throw new Error(`metric ${name} was never declared`);
    if (family.kind !== kind) throw new Error(`metric ${name} is a ${family.kind}, not a ${kind}`);
    return family;
  }

  set(name: string, labels: Labels, value: number): void {
    this.family(name, 'gauge').samples.set(labelKey(labels), { labels, value });
  }

  increment(name: string, labels: Labels, by = 1): void {
    const family = this.family(name, 'counter');
    const key = labelKey(labels);
    family.samples.set(key, { labels, value: (family.samples.get(key)?.value ?? 0) + by });
  }

  observe(name: string, labels: Labels, value: number): void {
    const family = this.family(name, 'histogram');
    const key = labelKey(labels);
    let sample = family.histograms.get(key);
    if (sample === undefined) {
      sample = { labels, counts: family.buckets.map(() => 0), sum: 0, count: 0 };
      family.histograms.set(key, sample);
    }
    family.buckets.forEach((bound, index) => {
      if (value <= bound) sample.counts[index]! += 1;
    });
    sample.sum += value;
    sample.count += 1;
  }

  value(name: string, labels: Labels): number {
    return this.families.get(name)?.samples.get(labelKey(labels))?.value ?? 0;
  }

  render(): string {
    const lines: string[] = [];
    for (const [name, family] of this.families) {
      lines.push(`# HELP ${name} ${family.help}`);
      lines.push(`# TYPE ${name} ${family.kind}`);
      if (family.kind === 'histogram') {
        for (const sample of family.histograms.values()) {
          family.buckets.forEach((bound, index) => {
            lines.push(`${name}_bucket${renderLabels(sample.labels, { le: formatNumber(bound) })} ${sample.counts[index]}`);
          });
          lines.push(`${name}_bucket${renderLabels(sample.labels, { le: '+Inf' })} ${sample.count}`);
          lines.push(`${name}_sum${renderLabels(sample.labels)} ${formatNumber(sample.sum)}`);
          lines.push(`${name}_count${renderLabels(sample.labels)} ${sample.count}`);
        }
        continue;
      }
      for (const { labels, value } of family.samples.values()) {
        lines.push(`${name}${renderLabels(labels)} ${formatNumber(value)}`);
      }
    }
    return `${lines.join('\n')}\n`;
  }
}

export const METRICS = {
  calls: 'brain_tools_calls_total',
  latency: 'brain_tools_latency_seconds',
  searches: 'brain_tools_searches_total',
  upstream: 'brain_tools_upstream_requests_total',
  catalogComplete: 'brain_tools_catalog_complete',
  catalogMissing: 'brain_tools_catalog_missing_queries',
  catalogChecked: 'brain_tools_catalog_checked_timestamp_seconds',
  contractOk: 'brain_tools_embedding_contract_ok',
  cacheRows: 'brain_tools_cache_rows',
  cacheRefreshed: 'brain_tools_cache_refreshed_timestamp_seconds',
  responseChars: 'brain_tools_response_chars',
  build: 'brain_tools_build_info',
} as const;

export const CHAR_BUCKETS: readonly number[] = [500, 1000, 2000, 4000, 6000, 12000, 50000];

export function declareMetrics(registry: MetricRegistry): void {
  registry.declare(METRICS.calls, 'counter', 'Tool calls by tool, surface (mcp or rest) and outcome');
  registry.declare(METRICS.latency, 'histogram', 'Tool call latency in seconds by tool and surface');
  registry.declare(METRICS.searches, 'counter', 'Searches by profile and mode (fused, keyword_only, meaning_only)');
  registry.declare(METRICS.upstream, 'counter', 'Requests to Omnigraph and LiteLLM by upstream and outcome');
  registry.declare(METRICS.catalogComplete, 'gauge', '1 when every stored query brain-tools needs is served to act-brain-reader');
  registry.declare(METRICS.catalogMissing, 'gauge', 'How many stored queries brain-tools needs are missing from the catalog');
  registry.declare(METRICS.catalogChecked, 'gauge', 'Unix time of the last successful catalog check');
  registry.declare(METRICS.contractOk, 'gauge', '1 when the embedding contract matches the schema @embed model and dimensions');
  registry.declare(METRICS.cacheRows, 'gauge', 'Rows held by each cache at head');
  registry.declare(METRICS.cacheRefreshed, 'gauge', 'Unix time each cache was last refreshed at head');
  registry.declare(METRICS.responseChars, 'histogram', 'Characters of the text a tool returns, by tool', CHAR_BUCKETS);
  registry.declare(METRICS.build, 'gauge', 'Build information');
}
