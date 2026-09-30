import type { ReadView } from './render.ts';
import type { QueryResult, Row } from './upstream.ts';

export const MAX_REF_CHARS = 300;
export const MAX_AROUND = 1;

export type ParsedRef =
  | { kind: 'doc'; slug: string; chunk: number }
  | { kind: 'note'; slug: string; chunk: number | null }
  | { kind: 'entity'; prefix: string; slug: string }
  | { kind: 'invalid' };

const SLUG = /^[A-Za-z0-9][A-Za-z0-9._\/@+-]{0,280}$/;
const ENTITY_PREFIXES = new Set(['topic', 'person', 'project', 'org']);

export function parseRef(raw: string): ParsedRef {
  const ref = raw.trim();
  if (ref.length === 0 || ref.length > MAX_REF_CHARS) return { kind: 'invalid' };
  const colon = ref.indexOf(':');
  if (colon <= 0) return { kind: 'invalid' };
  const prefix = ref.slice(0, colon);
  const rest = ref.slice(colon + 1);
  const hash = rest.lastIndexOf('#');
  const slug = hash >= 0 ? rest.slice(0, hash) : rest;
  const chunkText = hash >= 0 ? rest.slice(hash + 1) : null;
  if (!SLUG.test(slug)) return { kind: 'invalid' };
  if (chunkText !== null && !/^\d{1,5}$/.test(chunkText)) return { kind: 'invalid' };
  const chunk = chunkText === null ? null : Number(chunkText);
  if (prefix === 'doc') return { kind: 'doc', slug, chunk: chunk ?? 0 };
  if (prefix === 'note') return { kind: 'note', slug, chunk };
  if (ENTITY_PREFIXES.has(prefix)) return { kind: 'entity', prefix, slug };
  return { kind: 'invalid' };
}

export function shadowArtifact(noteSlug: string): string | null {
  return noteSlug.startsWith('obsidian/') ? `obsidian-file/${noteSlug.slice('obsidian/'.length)}` : null;
}

export type Stored = (name: string, params: Record<string, unknown>, snapshot: string | null, signal: AbortSignal) => Promise<QueryResult>;

export interface ReadOutcome {
  view: ReadView | null;
  graphCommit: string | null;
}

function field(row: Row | undefined, column: string): string | null {
  const value = row?.[column];
  return typeof value === 'string' && value.length > 0 ? value : null;
}

function passagesOf(rows: readonly Row[]): { chunk: number; text: string }[] {
  return rows.flatMap((row) => {
    const chunk = row['p.chunk_index'];
    const text = row['p.text'];
    return typeof chunk === 'number' && typeof text === 'string' ? [{ chunk, text }] : [];
  });
}

async function passageWindow(stored: Stored, artifact: string, focus: number, around: number, snapshot: string | null, signal: AbortSignal): Promise<QueryResult> {
  return stored('rt_passage_window', { slug: artifact, lo: Math.max(0, focus - around), hi: focus + around }, snapshot, signal);
}

export async function readRef(ref: Extract<ParsedRef, { kind: 'doc' | 'note' }>, around: number, stored: Stored, snapshot: string | null, signal: AbortSignal): Promise<ReadOutcome> {
  const reach = Math.max(0, Math.min(MAX_AROUND, around));
  if (ref.kind === 'doc') {
    const [card, passages] = await Promise.all([
      stored('rt_artifact_card', { slug: ref.slug }, snapshot, signal),
      passageWindow(stored, ref.slug, ref.chunk, reach, snapshot, signal),
    ]);
    const row = card.rows[0];
    if (row === undefined) return { view: null, graphCommit: card.graphCommit };
    return {
      view: {
        ref: `doc:${ref.slug}#${ref.chunk}`,
        document: ref.slug,
        title: field(row, 'a.name') ?? ref.slug,
        kind: field(row, 'a.kind') ?? 'document',
        date: field(row, 'a.timestamp'),
        url: field(row, 'a.url'),
        passages: passagesOf(passages.rows),
        focus: ref.chunk,
      },
      graphCommit: card.graphCommit ?? passages.graphCommit,
    };
  }
  const shadow = shadowArtifact(ref.slug);
  if (shadow !== null) {
    const focus = ref.chunk ?? 0;
    const [card, passages] = await Promise.all([
      stored('rt_note_card', { slug: ref.slug }, snapshot, signal),
      passageWindow(stored, shadow, focus, reach, snapshot, signal),
    ]);
    const row = card.rows[0];
    if (row === undefined) return { view: null, graphCommit: card.graphCommit };
    if (passages.rows.length === 0) return readWhole(ref.slug, stored, snapshot, signal);
    return {
      view: {
        ref: `note:${ref.slug}#${focus}`,
        document: ref.slug,
        title: field(row, 'n.name') ?? ref.slug,
        kind: field(row, 'n.kind') ?? 'note',
        date: field(row, 'n.updatedAt'),
        url: null,
        passages: passagesOf(passages.rows),
        focus,
      },
      graphCommit: card.graphCommit ?? passages.graphCommit,
    };
  }
  return readWhole(ref.slug, stored, snapshot, signal);
}

async function readWhole(slug: string, stored: Stored, snapshot: string | null, signal: AbortSignal): Promise<ReadOutcome> {
  const note = await stored('rt_note_text', { slug }, snapshot, signal);
  const row = note.rows[0];
  if (row === undefined) return { view: null, graphCommit: note.graphCommit };
  return {
    view: {
      ref: `note:${slug}`,
      document: slug,
      title: field(row, 'n.name') ?? slug,
      kind: field(row, 'n.kind') ?? 'note',
      date: field(row, 'n.updatedAt'),
      url: null,
      passages: [{ chunk: 0, text: field(row, 'n.content') ?? '' }],
      focus: null,
    },
    graphCommit: note.graphCommit,
  };
}
