import type { SearchResult, Source } from './search.ts';
import { collapseWhitespace, snippet } from './text.ts';

export const SEARCH_MAX_CHARS = 6000;
export const READ_MAX_CHARS = 4000;
export const SNIPPET_CHARS = 600;
export const PRIVACY = 'Private: cite, do not copy into git, tickets or public pages.';

export interface Footer {
  graphCommit: string | null;
  reranked: boolean;
  elapsedMs: number;
  degraded: string | null;
}

export function explorerLink(explorerUrl: string | null, slug: string): string | null {
  if (explorerUrl === null) return null;
  return `${explorerUrl}/?graph=brain&node=${encodeURIComponent(slug)}`;
}

export function linkFor(source: Pick<Source, 'url' | 'document' | 'kind'>, explorerUrl: string | null): string | null {
  if (source.url !== null && /^https?:\/\//.test(source.url)) return source.url;
  return explorerLink(explorerUrl, source.document);
}

export function footerLine(footer: Footer): string {
  const parts = [
    `graph ${footer.graphCommit ?? 'unknown'}`,
    `reranked: ${footer.reranked ? 'yes' : 'no'}`,
    `${footer.elapsedMs} ms`,
  ];
  if (footer.degraded !== null) parts.push(`degraded: ${footer.degraded}`);
  return `-- ${parts.join(' · ')} · ${PRIVACY}`;
}

function dateOnly(value: string | null): string | null {
  if (value === null) return null;
  const match = /^\d{4}-\d{2}-\d{2}/.exec(value);
  return match === null ? null : match[0];
}

export function sourceBlock(position: number, source: Source, terms: readonly string[], explorerUrl: string | null): string {
  const facts = [source.kind === 'doc' ? source.docKind || 'document' : source.kind, dateOnly(source.date)].filter((part) => part !== null && part.length > 0);
  const lines = [`[${position}] ${collapseWhitespace(source.title) || source.document} (${facts.join(', ')})`, `    ref: ${source.ref}`];
  const link = linkFor(source, explorerUrl);
  if (link !== null) lines.push(`    link: ${link}`);
  const body = snippet(source.text, terms, SNIPPET_CHARS);
  if (body.length > 0) lines.push(`    ${body}`);
  if (source.similar > 0) lines.push(`    (+${source.similar} similar)`);
  return lines.join('\n');
}

export interface Rendered {
  text: string;
  shown: number;
  truncated: boolean;
}

export const NO_RESULTS = 'No results in the brain for that. Try 2 to 4 key words, another wording, or the Dutch or English word. Say plainly that the brain has nothing on it; do not answer from memory.';

export function renderSearch(result: SearchResult, footer: Footer, explorerUrl: string | null, max = SEARCH_MAX_CHARS): Rendered {
  const tail = footerLine(footer);
  if (result.sources.length === 0) {
    const text = `${NO_RESULTS}\n${tail}`;
    return { text, shown: 0, truncated: false };
  }
  const header = `${result.sources.length} source${result.sources.length === 1 ? '' : 's'} from Ryan's brain, best first. Cite the link of every source you use; open one with read(ref).`;
  const related = result.related.length > 0 ? `Related topics: ${result.related.map((topic) => `${topic.name} (${topic.ref})`).join(', ')}` : '';
  const blocks = result.sources.map((source, index) => sourceBlock(index + 1, source, result.terms, explorerUrl));
  let shown = blocks.length;
  const assemble = (count: number, withRelated: boolean): string =>
    [header, ...blocks.slice(0, count), ...(withRelated && related.length > 0 ? [related] : []), tail].join('\n');
  let text = assemble(shown, true);
  let truncated = false;
  if (text.length > max) {
    truncated = true;
    text = assemble(shown, false);
    while (shown > 1 && text.length > max) {
      shown -= 1;
      text = assemble(shown, false);
    }
    if (text.length > max) text = `${text.slice(0, max - tail.length - 2)}…\n${tail}`;
  }
  return { text, shown, truncated };
}

export interface ReadPassage {
  chunk: number;
  text: string;
}

export interface ReadView {
  ref: string;
  document: string;
  title: string;
  kind: string;
  date: string | null;
  url: string | null;
  passages: ReadPassage[];
  focus: number | null;
}

export function renderRead(view: ReadView, footer: Footer, explorerUrl: string | null, max = READ_MAX_CHARS): Rendered {
  const tail = footerLine(footer);
  const facts = [view.kind, dateOnly(view.date)].filter((part): part is string => part !== null && part.length > 0);
  const link = linkFor({ url: view.url, document: view.document, kind: 'doc' }, explorerUrl);
  const head = [`${collapseWhitespace(view.title) || view.document} (${facts.join(', ')})`, `ref: ${view.ref}`, ...(link === null ? [] : [`link: ${link}`])];
  const budget = max - tail.length - head.join('\n').length - 8;
  const ordered = [...view.passages].sort((left, right) => left.chunk - right.chunk);
  const focusFirst = [...ordered].sort((left, right) => Math.abs(left.chunk - (view.focus ?? left.chunk)) - Math.abs(right.chunk - (view.focus ?? right.chunk)));
  const allowance = new Map<number, number>();
  let remaining = Math.max(0, budget);
  for (const passage of focusFirst) {
    const size = Math.min(passage.text.length + 16, remaining);
    allowance.set(passage.chunk, size);
    remaining -= size;
  }
  let truncated = false;
  const body = ordered
    .map((passage) => {
      const allowed = Math.max(0, (allowance.get(passage.chunk) ?? 0) - 16);
      if (allowed <= 0) {
        truncated = true;
        return null;
      }
      const cut = passage.text.length > allowed;
      if (cut) truncated = true;
      const label = view.passages.length > 1 || view.focus !== null ? `[chunk ${passage.chunk}${passage.chunk === view.focus ? ', asked' : ''}]\n` : '';
      return `${label}${cut ? `${passage.text.slice(0, Math.max(0, allowed - 1))}…` : passage.text}`;
    })
    .filter((part): part is string => part !== null);
  return { text: [...head, '', ...body, tail].join('\n'), shown: body.length, truncated };
}
