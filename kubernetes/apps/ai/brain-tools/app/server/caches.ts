import type { Omnigraph, Row } from './upstream.ts';

export const BOT_LOGIN = /(renovate|dependabot|bot$|\[bot\]|-ci$|^webgrip-ci)/i;

export interface BotIndex {
  artifacts: Set<string>;
  names: string[];
}

function loginOf(personSlug: string): string {
  return personSlug.slice(personSlug.lastIndexOf('/') + 1);
}

export function botIndex(rows: readonly Row[]): BotIndex {
  const artifacts = new Set<string>();
  const names = new Set<string>();
  for (const row of rows) {
    const artifact = row['a.slug'];
    const person = row['u.slug'];
    if (typeof artifact !== 'string' || typeof person !== 'string') continue;
    const login = loginOf(person);
    if (!BOT_LOGIN.test(login)) continue;
    artifacts.add(artifact);
    names.add(login);
    const name = row['u.name'];
    if (typeof name === 'string' && name.length > 0) names.add(name);
  }
  return { artifacts, names: [...names] };
}

export interface CacheOptions {
  omnigraph: Omnigraph;
  deadlineMs: number;
  pinnedEntries?: number;
}

export class Caches {
  private readonly omnigraph: Omnigraph;
  private readonly deadlineMs: number;
  private readonly pinnedEntries: number;
  private head: BotIndex | null = null;
  private headRefreshedAt = 0;
  private readonly pinned = new Map<string, Promise<BotIndex>>();

  constructor(options: CacheOptions) {
    this.omnigraph = options.omnigraph;
    this.deadlineMs = options.deadlineMs;
    this.pinnedEntries = options.pinnedEntries ?? 4;
  }

  private async load(snapshot: string | null, signal: AbortSignal): Promise<BotIndex> {
    const result = await this.omnigraph.stored('rt_artifact_authors', {}, snapshot, signal);
    return botIndex(result.rows);
  }

  async refreshHead(): Promise<BotIndex> {
    const index = await this.load(null, AbortSignal.timeout(this.deadlineMs * 4));
    this.head = index;
    this.headRefreshedAt = Date.now();
    return index;
  }

  get headRows(): number {
    return this.head?.artifacts.size ?? 0;
  }

  get headAge(): number {
    return this.headRefreshedAt;
  }

  async bots(snapshot: string | null, signal: AbortSignal): Promise<BotIndex> {
    if (snapshot === null) return this.head ?? (await this.refreshHead());
    let entry = this.pinned.get(snapshot);
    if (entry === undefined) {
      entry = this.load(snapshot, signal);
      this.pinned.set(snapshot, entry);
      entry.catch(() => this.pinned.delete(snapshot));
      while (this.pinned.size > this.pinnedEntries) {
        const oldest = this.pinned.keys().next().value;
        if (oldest === undefined) break;
        this.pinned.delete(oldest);
      }
    }
    return entry;
  }
}
