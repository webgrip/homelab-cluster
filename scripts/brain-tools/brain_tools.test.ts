import assert from 'node:assert/strict';
import { after, before, beforeEach, describe, test } from 'node:test';
import { checkContract, parseContract } from '../../kubernetes/apps/ai/brain-tools/app/server/contract.ts';
import { ConfigError, loadConfig } from '../../kubernetes/apps/ai/brain-tools/app/server/config.ts';
import { parseRef } from '../../kubernetes/apps/ai/brain-tools/app/server/read.ts';
import { PRIVACY, SEARCH_MAX_CHARS } from '../../kubernetes/apps/ai/brain-tools/app/server/render.ts';
import { interleave } from '../../kubernetes/apps/ai/brain-tools/app/server/search.ts';
import { guessLanguage, keywordTerms, snippet, textHash } from '../../kubernetes/apps/ai/brain-tools/app/server/text.ts';
import { COMMIT, LONG, MODEL, callTool, captureRow, docRow, getJson, noteRow, postJson, rig, schemaWith, topicRow } from './fakes.ts';
import type { Rig } from './fakes.ts';

const SNAPSHOT = '01M3SNAPSHOTPINNED000000000';

function seedSearch(rigged: Rig): void {
  rigged.omnigraph.rows = {
    rt_doc_passages_vec: [
      docRow('forge/acme/app/doc/runbook', 0, LONG('runbook zero kustomization')),
      docRow('forge/acme/app/pull/7', 0, LONG('Bump dependency 1.2.3 for the kustomization'), { 'a.timestamp': '2026-08-01T08:00:00' }),
      docRow('forge/acme/app/issue/8', 0, LONG('Bump dependency 1.2.4 for the kustomization'), { 'a.timestamp': '2026-08-05T08:00:00' }),
      docRow('forge/acme/app/doc/runbook', 1, LONG('runbook one kustomization')),
      docRow('forge/acme/app/doc/runbook', 2, LONG('runbook two kustomization')),
      docRow('forge/acme/app/doc/short', 0, 'Too short to keep.'),
    ],
    rt_doc_passages_bm25: [docRow('forge/acme/app/doc/runbook', 0, LONG('runbook zero kustomization'))],
    rt_note_passages_vec: [noteRow('garden', 0, LONG('garden kustomization note'))],
    rt_note_passages_bm25: [],
    rt_captures_vec: [captureRow('nt-20260901-abc', 'a short captured thought about kustomization')],
    rt_captures_bm25: [],
    rt_topics_vec: [topicRow('derived/topic/flux', 'Flux'), topicRow('derived/topic/gitops', 'GitOps')],
    rt_topics_bm25: [topicRow('derived/topic/flux', 'Flux')],
    rt_artifact_authors: [
      { 'a.slug': 'forge/acme/app/pull/7', 'u.slug': 'forge/user/renovate', 'u.name': 'renovate' },
      { 'a.slug': 'forge/acme/app/issue/8', 'u.slug': 'forge/user/renovate', 'u.name': 'renovate' },
      { 'a.slug': 'forge/acme/app/doc/runbook', 'u.slug': 'forge/user/alice', 'u.name': 'Alice' },
    ],
  };
}

describe('text', () => {
  test('keyword terms drop Dutch and English stopwords and punctuation', () => {
    assert.deepEqual(keywordTerms('How does Ryan use the Flux kustomization?'), ['use', 'flux', 'kustomization']);
    assert.deepEqual(keywordTerms('Wat weet ik over de tuin en het water?'), ['tuin', 'water']);
    assert.deepEqual(keywordTerms('what is the'), []);
  });

  test('language is guessed from stopwords', () => {
    assert.equal(guessLanguage('Wat heb ik over de tuin geschreven?'), 'nl');
    assert.equal(guessLanguage('What did I write about the garden?'), 'en');
  });

  test('the text hash ignores case, spacing and numbers', () => {
    assert.equal(textHash('Bump dependency 1.2.3  now'), textHash('bump dependency 1.2.4 now'));
    assert.notEqual(textHash('bump dependency now'), textHash('bump another dependency now'));
  });

  test('a snippet stays within its budget and centres on a term', () => {
    const text = `${'lead '.repeat(300)}target ${'tail '.repeat(300)}`;
    const cut = snippet(text, ['target'], 600);
    assert.ok(cut.length <= 600, `snippet is ${cut.length} characters`);
    assert.ok(cut.includes('target'));
  });

  test('interleave takes one item of each list in turn', () => {
    assert.deepEqual(interleave([['n1', 'n2'], ['p1', 'p2', 'p3'], ['t1']]), ['n1', 'p1', 't1', 'n2', 'p2', 'p3']);
  });
});

describe('contract and config', () => {
  test('the contract matches a schema that embeds with its model and dimensions', () => {
    const contract = parseContract(JSON.stringify({ model: MODEL, dimensions: 384 }));
    assert.equal(checkContract(contract, schemaWith(MODEL)).ok, true);
    assert.equal(checkContract(contract, schemaWith('other-model')).ok, false);
    assert.equal(checkContract(contract, schemaWith(MODEL, 768)).ok, false);
    assert.equal(checkContract(contract, 'node Passage {\n text: String\n}').ok, false);
  });

  test('config refuses a missing or malformed token and a wrong profile', () => {
    assert.throws(() => loadConfig({}), ConfigError);
    assert.throws(() => loadConfig({ OMNIGRAPH_TOKEN: 'short' }), ConfigError);
    assert.throws(() => loadConfig({ OMNIGRAPH_TOKEN: 'reader-token-0123456789', BRAIN_TOOLS_PROFILE: 'p9' }), ConfigError);
    const config = loadConfig({ OMNIGRAPH_TOKEN: 'reader-token-0123456789', BRAIN_EXPLORER_URL: 'https://graph.example.test/' });
    assert.equal(config.explorerUrl, 'https://graph.example.test');
    assert.equal(config.deadlineMs, 8000);
  });

  test('refs parse into kinds and anything else is refused', () => {
    assert.deepEqual(parseRef('doc:forge/acme/app/doc/runbook#2'), { kind: 'doc', slug: 'forge/acme/app/doc/runbook', chunk: 2 });
    assert.deepEqual(parseRef('note:obsidian/garden#0'), { kind: 'note', slug: 'obsidian/garden', chunk: 0 });
    assert.deepEqual(parseRef('note:nt-20260901-abc'), { kind: 'note', slug: 'nt-20260901-abc', chunk: null });
    assert.equal(parseRef('topic:derived/topic/flux').kind, 'entity');
    assert.equal(parseRef('MATCH (n) RETURN n').kind, 'invalid');
    assert.equal(parseRef('doc:x#abc').kind, 'invalid');
  });
});

describe('search p1', () => {
  let rigged: Rig;
  before(async () => {
    rigged = await rig();
  });
  after(async () => {
    await rigged.stop();
  });
  beforeEach(async () => {
    seedSearch(rigged);
    rigged.omnigraph.calls = [];
    rigged.omnigraph.failWith = null;
    rigged.omnigraph.delayMs = 0;
    rigged.omnigraph.catalog = [...(await import('../../kubernetes/apps/ai/brain-tools/app/server/search.ts')).REQUIRED_QUERIES];
    rigged.omnigraph.schema = schemaWith(MODEL);
    rigged.litellm.failWith = null;
    rigged.litellm.inputs = [];
    rigged.logs.length = 0;
    await rigged.service.checkCatalog();
  });

  test('fuses every leg, keeps at most two chunks a document and drops short chunks', async () => {
    const { status, json } = await getJson(`${rigged.restUrl}/api/search?q=${encodeURIComponent('the Flux kustomization')}&limit=40`);
    assert.equal(status, 200);
    const documents = json.results.map((result: any) => result.document);
    assert.equal(documents.filter((document: string) => document === 'forge/acme/app/doc/runbook').length, 2);
    assert.ok(!documents.includes('forge/acme/app/doc/short'));
    assert.ok(documents.includes('obsidian/garden'));
    assert.ok(documents.includes('nt-20260901-abc'));
    assert.equal(json.results[0].ref, 'doc:forge/acme/app/doc/runbook#0');
    assert.deepEqual(json.related.map((topic: any) => topic.ref).slice(0, 2), ['topic:derived/topic/flux', 'topic:derived/topic/gitops']);
    assert.equal(json.graph_commit, COMMIT);
    assert.equal(json.mode, 'fused');
  });

  test('clones collapse into the newest copy with a similar count', async () => {
    const { json } = await getJson(`${rigged.restUrl}/api/search?q=kustomization&limit=40`);
    const clones = json.results.filter((result: any) => result.document.startsWith('forge/acme/app/pull/') || result.document.startsWith('forge/acme/app/issue/'));
    assert.equal(clones.length, 1);
    assert.equal(clones[0].document, 'forge/acme/app/issue/8');
    assert.equal(clones[0].similar, 1);
  });

  test('bot-authored documents sink unless the question names the bot', async () => {
    const plain = (await getJson(`${rigged.restUrl}/api/search?q=kustomization&limit=40&debug=1`)).json;
    const botPosition = plain.results.findIndex((result: any) => result.document === 'forge/acme/app/issue/8');
    const notePosition = plain.results.findIndex((result: any) => result.document === 'obsidian/garden');
    assert.ok(botPosition > notePosition, `bot document at ${botPosition}, note at ${notePosition}`);
    const named = (await getJson(`${rigged.restUrl}/api/search?q=${encodeURIComponent('renovate kustomization')}&limit=40`)).json;
    const namedPosition = named.results.findIndex((result: any) => result.document === 'forge/acme/app/issue/8');
    assert.ok(namedPosition < botPosition, `named bot document at ${namedPosition}, unnamed at ${botPosition}`);
  });

  test('keyword legs get the question without stopwords and meaning legs one shared vector', async () => {
    await getJson(`${rigged.restUrl}/api/search?q=${encodeURIComponent('How does Ryan use the Flux kustomization?')}`);
    const keyword = rigged.omnigraph.calledWith('rt_doc_passages_bm25');
    assert.equal(keyword.length, 1);
    assert.equal(keyword[0]!.params['k'], 'use flux kustomization');
    const vectors = rigged.omnigraph.calls.filter((call) => call.name.endsWith('_vec')).map((call) => JSON.stringify(call.params['v']));
    assert.equal(vectors.length, 4);
    assert.equal(new Set(vectors).size, 1);
    assert.equal(rigged.litellm.inputs.length, 1);
    const norm = Math.sqrt((JSON.parse(vectors[0]!) as number[]).reduce((sum, value) => sum + value * value, 0));
    assert.ok(Math.abs(norm - 1) < 1e-9);
  });

  test('Dutch questions weigh keywords at 0.6, so a meaning hit beats a keyword hit', async () => {
    rigged.omnigraph.rows = {
      rt_doc_passages_vec: [docRow('forge/acme/app/doc/zz-meaning', 0, LONG('meaning only'))],
      rt_doc_passages_bm25: [docRow('forge/acme/app/doc/aa-keyword', 0, LONG('keyword only'))],
    };
    const dutch = (await getJson(`${rigged.restUrl}/api/search?q=${encodeURIComponent('wat weet ik over de tuin')}&scope=docs`)).json;
    assert.equal(dutch.results[0].document, 'forge/acme/app/doc/zz-meaning');
    const english = (await getJson(`${rigged.restUrl}/api/search?q=${encodeURIComponent('what do I know about the garden')}&scope=docs`)).json;
    assert.equal(english.results[0].document, 'forge/acme/app/doc/aa-keyword');
  });

  test('scope docs runs no note or capture legs', async () => {
    await getJson(`${rigged.restUrl}/api/search?q=kustomization&scope=docs`);
    const names = new Set(rigged.omnigraph.calls.map((call) => call.name));
    assert.ok(!names.has('rt_note_passages_vec') && !names.has('rt_captures_bm25'));
    assert.ok(names.has('rt_doc_passages_vec'));
  });

  test('an embedding failure falls back to keywords and says so', async () => {
    rigged.litellm.failWith = 503;
    const { status, json } = await getJson(`${rigged.restUrl}/api/search?q=kustomization`);
    assert.equal(status, 200);
    assert.equal(json.degraded, 'keyword-only');
    assert.equal(json.mode, 'keyword_only');
    assert.ok(!rigged.omnigraph.calls.some((call) => call.name.endsWith('_vec')));
    assert.match(json.text, /degraded: keyword-only/);
    assert.equal(rigged.registry.value('brain_tools_searches_total', { profile: 'p1', mode: 'keyword_only' }) >= 1, true);
  });

  test('an embedding contract that disagrees with the schema turns meaning legs off', async () => {
    rigged.omnigraph.schema = schemaWith('another-model');
    await rigged.service.checkCatalog();
    const { json } = await getJson(`${rigged.restUrl}/api/search?q=kustomization`);
    assert.equal(json.degraded, 'embedding-contract-mismatch');
    assert.equal(rigged.litellm.inputs.length, 0);
    assert.ok(!rigged.omnigraph.calls.some((call) => call.name.endsWith('_vec')));
    assert.equal((await getJson(`${rigged.restUrl}/readyz`)).json.embedding_contract_ok, false);
  });

  test('a pinned snapshot reaches every stored query, the bot cache included', async () => {
    await getJson(`${rigged.restUrl}/api/search?q=kustomization&snapshot=${SNAPSHOT}`);
    assert.ok(rigged.omnigraph.calls.length >= 8);
    for (const call of rigged.omnigraph.calls) assert.equal(call.snapshot, SNAPSHOT, `${call.name} ran unpinned`);
    assert.equal(rigged.omnigraph.calledWith('rt_artifact_authors').length, 1);
  });

  test('head searches reuse the bot cache', async () => {
    await rigged.service.refreshCaches();
    rigged.omnigraph.calls = [];
    await getJson(`${rigged.restUrl}/api/search?q=kustomization`);
    await getJson(`${rigged.restUrl}/api/search?q=kustomization`);
    assert.equal(rigged.omnigraph.calledWith('rt_artifact_authors').length, 0);
  });

  test('an unavailable Omnigraph gives the teaching error, not an answer', async () => {
    rigged.omnigraph.failWith = 503;
    const result = await callTool(rigged, 'search', { query: 'kustomization' });
    assert.equal(result.isError, true);
    assert.match(result.content[0].text, /brain is unavailable/);
    assert.match(result.content[0].text, /do not answer from memory/);
    const rest = await getJson(`${rigged.restUrl}/api/search?q=kustomization`);
    assert.equal(rest.status, 503);
  });

  test('a slow Omnigraph is cut off at the deadline', async () => {
    const slow = await rig({ deadlineMs: 300 });
    try {
      seedSearch(slow);
      slow.omnigraph.delayMs = 1500;
      const started = Date.now();
      const result = await callTool(slow, 'search', { query: 'kustomization' });
      assert.ok(Date.now() - started < 1400, 'the deadline did not stop the call');
      assert.equal(result.isError, true);
      assert.match(result.content[0].text, /did not answer in time/);
    } finally {
      await slow.stop();
    }
  });

  test('the answer stays under 6,000 characters and cuts the lowest ranks first', async () => {
    rigged.omnigraph.rows = {
      rt_doc_passages_vec: Array.from({ length: 20 }, (_, index) => docRow(`forge/acme/app/doc/long-${String(index).padStart(2, '0')}`, 0, `${'abcdefghijklmnopqrstuvwxyz'[index]}q kustomization ${'word '.repeat(400)}`)),
    };
    const result = await callTool(rigged, 'search', { query: 'kustomization', limit: 20 });
    const text: string = result.content[0].text;
    assert.ok(text.length <= SEARCH_MAX_CHARS, `answer is ${text.length} characters`);
    assert.equal(result.structuredContent.truncated, true);
    assert.match(text, /doc:forge\/acme\/app\/doc\/long-00#0/);
    assert.doesNotMatch(text, /long-19/);
    assert.ok(text.includes(PRIVACY));
    assert.ok(text.includes(`graph ${COMMIT}`));
  });

  test('REST reports what the default search tool would return', async () => {
    const { json } = await getJson(`${rigged.restUrl}/api/search?q=kustomization&limit=40`);
    const tool = await callTool(rigged, 'search', { query: 'kustomization' });
    assert.ok(Math.abs(json.tool_chars - tool.content[0].text.length) < 12);
  });

  test('logs carry counts and timings, never the question or a slug', async () => {
    await getJson(`${rigged.restUrl}/api/search?q=${encodeURIComponent('zebracorn sentinel kustomization')}`);
    await callTool(rigged, 'read', { ref: 'note:obsidian/garden#0' });
    const joined = rigged.logs.join('\n');
    assert.ok(rigged.logs.length >= 2);
    assert.doesNotMatch(joined, /zebracorn/);
    assert.doesNotMatch(joined, /obsidian\/garden|forge\/acme/);
  });
});

describe('search p0 replica', () => {
  test('interleaves recall_notes, recall_passages and recall_topics by rank without collapsing', async () => {
    const rigged = await rig({ profile: 'p0' });
    try {
      rigged.omnigraph.rows = {
        recall_notes: [{ 'n.slug': 'obsidian/a', 'n.name': 'A', 'n.kind': 'idea', 'n.content': 'x' }, { 'n.slug': 'obsidian/b', 'n.name': 'B', 'n.kind': 'idea', 'n.content': 'x' }],
        recall_passages: [
          { 'a.slug': 'forge/r/doc/x', 'a.name': 'X', 'p.chunk_index': 3, 'p.text': 'short' },
          { 'a.slug': 'forge/r/doc/x', 'a.name': 'X', 'p.chunk_index': 4, 'p.text': 'short' },
          { 'a.slug': 'forge/r/doc/x', 'a.name': 'X', 'p.chunk_index': 5, 'p.text': 'short' },
        ],
        recall_topics: [{ 't.slug': 'derived/topic/t', 't.name': 'T', 't.description': null, 't.aliases': null }],
      };
      await rigged.service.checkCatalog();
      const { json } = await getJson(`${rigged.restUrl}/api/search?q=question&limit=40&snapshot=${SNAPSHOT}`);
      assert.deepEqual(json.results.map((result: any) => result.ref), [
        'note:obsidian/a', 'doc:forge/r/doc/x#3', 'topic:derived/topic/t', 'note:obsidian/b', 'doc:forge/r/doc/x#4', 'doc:forge/r/doc/x#5',
      ]);
      for (const name of ['recall_notes', 'recall_passages', 'recall_topics']) {
        const calls = rigged.omnigraph.calledWith(name);
        assert.equal(calls.length, 1);
        assert.deepEqual(calls[0]!.params, { q: 'question' });
        assert.equal(calls[0]!.snapshot, SNAPSHOT);
      }
      assert.equal(rigged.litellm.inputs.length, 0);
    } finally {
      await rigged.stop();
    }
  });
});

describe('read', () => {
  let rigged: Rig;
  before(async () => {
    rigged = await rig();
    await rigged.service.checkCatalog();
  });
  after(async () => {
    await rigged.stop();
  });

  test('a doc ref opens its chunk with one neighbour on each side', async () => {
    rigged.omnigraph.calls = [];
    rigged.omnigraph.rows = {
      rt_artifact_card: [{ 'a.slug': 'forge/acme/app/doc/runbook', 'a.name': 'Runbook', 'a.kind': 'document', 'a.url': 'https://forge.example.test/runbook', 'a.timestamp': '2026-09-01T08:00:00' }],
      rt_passage_window: [1, 2, 3].map((chunk) => ({ 'p.@id': `forge/acme/app/doc/runbook#${chunk}`, 'p.chunk_index': chunk, 'p.text': `chunk ${chunk} text` })),
    };
    const result = await callTool(rigged, 'read', { ref: 'doc:forge/acme/app/doc/runbook#2' });
    assert.equal(result.isError, false);
    assert.deepEqual(rigged.omnigraph.calledWith('rt_passage_window')[0]!.params, { slug: 'forge/acme/app/doc/runbook', lo: 1, hi: 3 });
    assert.match(result.content[0].text, /chunk 2, asked/);
    assert.match(result.content[0].text, /link: https:\/\/forge\.example\.test\/runbook/);
    assert.deepEqual(result.structuredContent.chunks, [1, 2, 3]);
  });

  test('an Obsidian note ref reads its shadow artifact, and a capture its own text', async () => {
    rigged.omnigraph.calls = [];
    rigged.omnigraph.rows = {
      rt_note_card: [{ 'n.slug': 'obsidian/garden', 'n.name': 'Garden', 'n.kind': 'idea', 'n.updatedAt': '2026-09-02T08:00:00' }],
      rt_passage_window: [{ 'p.@id': 'obsidian-file/garden#0', 'p.chunk_index': 0, 'p.text': 'Garden › Soil' }],
      rt_note_text: [{ 'n.slug': 'nt-20260901-abc', 'n.name': 'Capture', 'n.kind': 'idea', 'n.updatedAt': '2026-09-03T08:00:00', 'n.content': 'captured text' }],
    };
    await callTool(rigged, 'read', { ref: 'note:obsidian/garden#0' });
    assert.equal(rigged.omnigraph.calledWith('rt_passage_window')[0]!.params['slug'], 'obsidian-file/garden');
    const capture = await callTool(rigged, 'read', { ref: 'note:nt-20260901-abc' });
    assert.match(capture.content[0].text, /captured text/);
    assert.match(capture.content[0].text, /link: https:\/\/graph\.example\.test\/\?graph=brain&node=nt-20260901-abc/);
  });

  test('entity refs, unknown refs and missing refs teach the next step', async () => {
    rigged.omnigraph.rows = {};
    assert.match((await callTool(rigged, 'read', { ref: 'topic:derived/topic/flux' })).content[0].text, /search with its name/);
    assert.match((await callTool(rigged, 'read', { ref: 'MATCH (n) RETURN n' })).content[0].text, /exactly as search returned them/);
    const missing = await callTool(rigged, 'read', { ref: 'doc:forge/acme/app/doc/gone#0' });
    assert.equal(missing.isError, true);
    assert.match(missing.content[0].text, /Search again/);
    assert.match((await callTool(rigged, 'read', { ref: 'doc:forge/acme/app/doc/runbook#0', around: 3 })).content[0].text, /around must be/);
  });

  test('a long note is cut to 4,000 characters', async () => {
    rigged.omnigraph.rows = { rt_note_text: [{ 'n.slug': 'nt-long', 'n.name': 'Long', 'n.kind': 'idea', 'n.updatedAt': null, 'n.content': 'word '.repeat(3000) }] };
    const result = await callTool(rigged, 'read', { ref: 'note:nt-long' });
    assert.ok(result.content[0].text.length <= 4000, `read is ${result.content[0].text.length} characters`);
    assert.equal(result.structuredContent.truncated, true);
  });
});

describe('mcp protocol', () => {
  let rigged: Rig;
  before(async () => {
    rigged = await rig();
    seedSearch(rigged);
    await rigged.service.checkCatalog();
  });
  after(async () => {
    await rigged.stop();
  });

  test('initialize echoes a known protocol version and lists two read-only tools', async () => {
    const init = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 't', version: '1' } } });
    assert.equal(init.status, 200);
    assert.equal(init.json.result.protocolVersion, '2025-03-26');
    assert.deepEqual(init.json.result.capabilities, { tools: { listChanged: false } });
    const unknown = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 2, method: 'initialize', params: { protocolVersion: '1999-01-01' } });
    assert.equal(unknown.json.result.protocolVersion, '2025-06-18');
    const notified = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', method: 'notifications/initialized' });
    assert.equal(notified.status, 202);
    const listed = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 3, method: 'tools/list' });
    assert.deepEqual(listed.json.result.tools.map((tool: any) => tool.name), ['search', 'read']);
    for (const tool of listed.json.result.tools) assert.equal(tool.annotations.readOnlyHint, true);
  });

  test('a tool call returns text and structured content', async () => {
    const result = await callTool(rigged, 'search', { query: 'kustomization' });
    assert.equal(result.isError, false);
    assert.equal(result.content[0].type, 'text');
    assert.ok(Array.isArray(result.structuredContent.results));
  });

  test('bad input is refused with a lesson, not a crash', async () => {
    assert.match((await callTool(rigged, 'search', { query: '' })).content[0].text, /1 to 500 characters/);
    assert.match((await callTool(rigged, 'search', { query: 'x'.repeat(501) })).content[0].text, /1 to 500 characters/);
    assert.match((await callTool(rigged, 'search', { query: 'x', scope: 'everything' })).content[0].text, /scope must be/);
    assert.match((await callTool(rigged, 'search', { query: 'x', limit: 21 })).content[0].text, /limit must be/);
    assert.match((await callTool(rigged, 'search', { query: 'x', limit: 0 })).content[0].text, /limit must be/);
    const snapshot = await callTool(rigged, 'search', { query: 'kustomization', snapshot: 'not a commit' });
    assert.equal(snapshot.isError, false);
    const unknownTool = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 4, method: 'tools/call', params: { name: 'mutate', arguments: {} } });
    assert.equal(unknownTool.json.error.code, -32602);
    const unknownMethod = await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 5, method: 'resources/list' });
    assert.equal(unknownMethod.json.error.code, -32601);
  });

  test('transport rules: POST only, no browser origins, bounded bodies, JSON only', async () => {
    assert.equal((await fetch(rigged.mcpUrl)).status, 405);
    assert.equal((await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 1, method: 'ping' }, { Origin: 'https://evil.example' })).status, 403);
    assert.equal((await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 1, method: 'ping', params: { pad: 'x'.repeat(20000) } })).status, 413);
    const broken = await postJson(rigged.mcpUrl, '{not json');
    assert.equal(broken.status, 400);
    assert.equal(broken.json.error.code, -32700);
    assert.equal((await postJson(rigged.mcpUrl, { jsonrpc: '2.0', id: 1, method: 'ping' })).json.result !== undefined, true);
  });

  test('REST refuses profile and snapshot values it does not know', async () => {
    assert.equal((await getJson(`${rigged.restUrl}/api/search?q=x&profile=p9`)).status, 400);
    assert.equal((await getJson(`${rigged.restUrl}/api/search?q=x&snapshot=bad!`)).status, 400);
    assert.equal((await getJson(`${rigged.restUrl}/api/other`)).status, 404);
  });
});

describe('readiness and metrics', () => {
  test('readyz fails while a needed stored query is missing and passes once it is served', async () => {
    const rigged = await rig();
    try {
      rigged.omnigraph.catalog = rigged.omnigraph.catalog.filter((name) => name !== 'rt_doc_passages_vec');
      await rigged.service.checkCatalog();
      const missing = await getJson(`${rigged.restUrl}/readyz`);
      assert.equal(missing.status, 503);
      assert.deepEqual(missing.json.missing_queries, ['rt_doc_passages_vec']);
      assert.match(rigged.registry.render(), /brain_tools_catalog_complete 0/);
      rigged.omnigraph.catalog.push('rt_doc_passages_vec');
      await rigged.service.checkCatalog();
      assert.equal((await getJson(`${rigged.restUrl}/readyz`)).status, 200);
      rigged.omnigraph.failWith = 503;
      await rigged.service.checkCatalog();
      assert.equal((await getJson(`${rigged.restUrl}/readyz`)).status, 503);
    } finally {
      await rigged.stop();
    }
  });

  test('metrics expose call latency buckets and upstream outcomes', async () => {
    const rigged = await rig();
    try {
      seedSearch(rigged);
      await rigged.service.checkCatalog();
      await callTool(rigged, 'search', { query: 'kustomization' });
      const text = await (await fetch(`${rigged.restUrl}/metrics`)).text();
      assert.match(text, /brain_tools_latency_seconds_bucket\{le="1",surface="mcp",tool="search"\} 1/);
      assert.match(text, /brain_tools_calls_total\{outcome="ok",surface="mcp",tool="search"\} 1/);
      assert.match(text, /brain_tools_upstream_requests_total\{outcome="ok",upstream="omnigraph"\}/);
      assert.match(text, /brain_tools_embedding_contract_ok 1/);
    } finally {
      await rigged.stop();
    }
  });
});
