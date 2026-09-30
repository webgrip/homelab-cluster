import { createHash } from 'node:crypto';

export type Language = 'nl' | 'en';

const ENGLISH = new Set(
  (
    'a about above after again against all am an and any are as at be because been before being below between both but by can could did do does doing done down during each ' +
    'few for from further had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not now of off on ' +
    'once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too ' +
    'under until up very was we were what when where which while who whom why will with would you your yours yourself yourselves ' +
    'tell show find give list explain describe know knew anything something everything thing things did does do say said about me my ryan ryans'
  ).split(/\s+/),
);

const DUTCH = new Set(
  (
    'aan al alle als alles andere ben bij daar dan dat de der deze die dit doch doen door dus een eens en er ge geen geweest haar had heb hebben heeft hem het hier hij hoe hun ' +
    'iemand iets ik in is ja je jij jou jouw kan kon kunnen maar me meer men met mij mijn moet na naar niet niets nog nu of om omdat ons onze ook op over reeds te tegen toch ' +
    'toen tot u uit uw van veel voor waren was wat we wel werd wezen wie wij wil worden wordt zal ze zei zelf zich zij zijn zo zonder zou ' +
    'welke waar wanneer waarom hoeveel heb hebt vertel geef laat zie weet wist iets over mij ryan'
  ).split(/\s+/),
);

export function words(text: string): string[] {
  return text.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
}

export function guessLanguage(question: string): Language {
  let dutch = 0;
  let english = 0;
  for (const word of words(question)) {
    if (DUTCH.has(word) && !ENGLISH.has(word)) dutch += 1;
    if (ENGLISH.has(word) && !DUTCH.has(word)) english += 1;
  }
  return dutch > english ? 'nl' : 'en';
}

export const MAX_KEYWORDS = 16;

export function keywordTerms(question: string): string[] {
  const seen = new Set<string>();
  for (const word of words(question)) {
    if (word.length < 2 && !/\p{N}/u.test(word)) continue;
    if (ENGLISH.has(word) || DUTCH.has(word)) continue;
    seen.add(word);
    if (seen.size >= MAX_KEYWORDS) break;
  }
  return [...seen];
}

export function textHash(text: string): string {
  const normalised = text
    .normalize('NFKC')
    .toLowerCase()
    .replace(/\p{N}+/gu, '#')
    .replace(/\s+/g, ' ')
    .trim();
  return createHash('sha256').update(normalised).digest('hex').slice(0, 16);
}

export function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

export function snippet(text: string, terms: readonly string[], max: number): string {
  const flat = collapseWhitespace(text);
  if (flat.length <= max) return flat;
  const lower = flat.toLowerCase();
  let hit = -1;
  for (const term of terms) {
    const at = lower.indexOf(term);
    if (at >= 0 && (hit < 0 || at < hit)) hit = at;
  }
  const start = hit < 0 ? 0 : Math.max(0, Math.min(hit - Math.floor(max / 3), flat.length - max));
  const body = flat.slice(start, start + max - (start > 0 ? 1 : 0) - 1);
  return `${start > 0 ? '…' : ''}${body}…`;
}

export function mentionsAny(question: string, names: readonly string[]): boolean {
  const asked = new Set(words(question));
  return names.some((name) => words(name).some((word) => word.length >= 4 && asked.has(word)));
}
