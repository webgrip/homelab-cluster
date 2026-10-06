import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..', '..', '..');
const CR = join(ROOT, 'kubernetes/apps/observability/grafana/app/dashboards/today.generated.yaml');
const FRAMES = JSON.parse(readFileSync(join(HERE, 'fixtures/frames.json'), 'utf8'));
const NOW = Date.parse('2026-10-03T14:45:00+02:00');

function shippedPanel() {
  const doc = readFileSync(CR, 'utf8');
  const lines = [];
  for (const line of doc.slice(doc.indexOf('  json: |-\n') + 11).split('\n')) {
    if (line && !line.startsWith('    ')) break;
    lines.push(line.slice(4));
  }
  return JSON.parse(lines.join('\n').split('$$').join('$')).panels[0];
}

class SafeString {
  constructor(s) { this.s = s; }
  toString() { return this.s; }
}

function render(series, now = NOW) {
  const helpers = {};
  const context = {
    data: {},
    panelData: { series },
    handlebars: { SafeString, registerHelper: (name, fn) => { helpers[name] = fn; } },
    grafana: {},
  };
  const realNow = Date.now;
  Date.now = () => now;
  try {
    new Function('context', shippedPanel().options.helpers)(context);
  } finally {
    Date.now = realNow;
  }
  return { wall: context.data.wall, helpers };
}

const without = (...refs) => FRAMES.filter((f) => !refs.includes(f.refId));
const replace = (ref, frame) => without(ref).concat([Object.assign({ refId: ref }, frame)]);

test('the shipped panel is a Business Text panel in data mode with inline rendering', () => {
  const panel = shippedPanel();
  assert.equal(panel.type, 'marcusolsson-dynamictext-panel');
  assert.equal(panel.options.renderMode, 'data');
  assert.equal(panel.options.wrap, false);
  assert.equal(panel.gridPos.h, 24);
  assert.ok(!panel.options.styles.includes('$'));
  assert.deepEqual(panel.targets.map((t) => t.refId).sort(),
    ['AGENTS', 'AGENT_PRS', 'AGING', 'ALERTS', 'CI_AGE', 'CI_FAILED', 'CI_NOW', 'FEED', 'FLOW', 'FLUX', 'GLIDE', 'PROBES',
      'PULLS', 'RUN_KEYS', 'SPEND', 'STAGES', 'TRUNK_RED', 'WEEK', 'WINS']);
});

test('the week clock counts Monday to Sunday in Amsterdam time', () => {
  const { wall } = render(FRAMES);
  assert.equal(wall.week.line, 'Week 40 · 28 Sep – 4 Oct · day 6 of 7');
  assert.deepEqual(wall.week.cells.map((c) => c.cls), ['done', 'done', 'done', 'done', 'done', 'today', '']);
  const { wall: monday } = render(FRAMES, Date.parse('2026-09-28T00:30:00+02:00'));
  assert.equal(monday.week.line, 'Week 40 · 28 Sep – 4 Oct · day 1 of 7');
});

test('the headline counts commits landed on trunks this week and what merged and shipped', () => {
  const { wall } = render(FRAMES);
  assert.equal(wall.shipped.n, 4);
  assert.equal(wall.shipped.word, 'commits landed this week');
  const facts = wall.shipped.facts.map((f) => (f.pre || '') + f.b + f.txt);
  assert.deepEqual(facts, ['1 repository', '1 pull request merged', '1 release', 'this time last week 0']);
});

test('the feed reads each commit with its type, its trunk CI verdict and a link', () => {
  const { wall } = render(FRAMES);
  assert.deepEqual(wall.feed.map((r) => [r.type, r.title, r.ci.txt]), [
    ['docs', 'the Today wall (#2)', '✗ red'],
    ['fix', 'the wall reconciles after the datasource', '✓ green'],
    ['feat', 'a Today wall for the homelab', 'in a push'],
    ['ci', 'lint on every push', 'no CI'],
  ]);
  assert.equal(wall.feed[1].where, 'homelab-cluster · flux');
  assert.equal(wall.feed[0].who, 'RG');
  assert.equal(wall.feed[0].agent, false);
  assert.match(wall.feed[0].url, /^https:\/\/forgejo\.webgrip\.dev\/webgrip\/homelab-cluster\/commit\/46ff6f99/);
  assert.equal(wall.feed[0].t, '14:29');
});

test('a commit by a bot author is marked even when the pusher is a person', () => {
  const feed = FRAMES.find((f) => f.refId === 'FEED');
  const authors = feed.fields.find((f) => f.name === 'author');
  const bot = JSON.parse(JSON.stringify(feed));
  bot.fields.find((f) => f.name === 'author').values = authors.values.map(() => 'renovate[bot]');
  const { wall } = render(replace('FEED', bot));
  assert.ok(wall.feed.every((r) => r.agent));
  assert.equal(wall.feed[0].who, 'RE');
});

test('every board shows its stages, and an empty board is named on the quiet line', () => {
  const { wall } = render(FRAMES);
  const byName = Object.fromEntries(wall.cards.map((c) => [c.name, c.stations.map((s) => s.n)]));
  assert.deepEqual(byName['Homelab Roadmap'], [2, 2, 1, 1, 2]);
  assert.deepEqual(byName.Unfold, [0, 1, 1, 2, 1]);
  assert.deepEqual(byName['CI/CD'], [1, 0, 0, 0, 0]);
  assert.deepEqual(wall.quiet, ['Vellum']);
  assert.equal(wall.cards[0].meta, '1 do-next');
});

test('wins name agent pull requests merged and the tickets closed, and skip a streak of one', () => {
  const { wall } = render(FRAMES);
  assert.deepEqual(wall.wins.map((w) => [w.k, w.v]), [
    ['Agent pull requests merged', '1'],
    ['Closed on the boards', '3'],
  ]);
  assert.equal(wall.wins[0].s, 'unfold #88 feat(vloer): link a Run by URL');
  const streak = { fields: [
    { name: 'kind', type: 'string', values: ['streak'] },
    { name: 'repo', type: 'string', values: ['glide'] },
    { name: 'workflow', type: 'string', values: ['ci.yaml'] },
    { name: 'value', type: 'number', values: [42] }] };
  const { wall: streaky } = render(replace('WINS', streak));
  assert.equal(streaky.wins[0].v, '42');
  assert.equal(streaky.wins[0].bars.length, 30);
});

test('could-use-a-hand orders alerts first, caps at five and says how many more', () => {
  const { wall } = render(FRAMES);
  assert.deepEqual(wall.hand.map((a) => a.k), [
    'Alerts firing', 'Trunk red', 'Unfold waits on you', 'Reviews waiting', 'Pull request pipelines red',
  ]);
  assert.equal(wall.hand[0].cls, 'alarm');
  assert.equal(wall.hand[0].v, '1 critical alert · 3 warning');
  assert.equal(wall.hand[1].v, 'homelab-cluster · lint.yaml');
  assert.equal(wall.hand[1].s, 'red for 3h');
  assert.equal(wall.more, 1);
});

test('a calm estate asks for nothing', () => {
  const calm = without('ALERTS', 'TRUNK_RED', 'GLIDE', 'PULLS', 'STAGES');
  const { wall } = render(calm);
  assert.deepEqual(wall.hand, []);
  assert.equal(wall.more, 0);
});

test('a silent Forgejo database is said out loud instead of reading as a quiet week', () => {
  const { wall } = render(without('FEED', 'WEEK'));
  assert.equal(wall.available, false);
  assert.deepEqual(wall.foot[0], { txt: 'Forgejo database not answering', cls: 'alarm' });
});

test('a stale CI exporter turns the footer amber then vermillion', () => {
  const age = (s) => replace('CI_AGE', { fields: [
    { name: 'Time', type: 'time', values: [0] }, { name: 'Value', type: 'number', values: [s] }] });
  assert.equal(render(age(240)).wall.foot[1].cls, '');
  assert.equal(render(age(1200)).wall.foot[1].cls, 'warn');
  assert.equal(render(age(4000)).wall.foot[1].cls, 'alarm');
});

test('a push over the import size is named but kept out of the headline and the comparison', () => {
  const week = JSON.parse(JSON.stringify(FRAMES.find((f) => f.refId === 'WEEK')));
  week.fields.find((f) => f.name === 'imported').values = [1119];
  const { wall } = render(replace('WEEK', week));
  assert.equal(wall.shipped.n, 4);
  assert.equal(wall.shipped.facts.at(-1).pre + wall.shipped.facts.at(-1).b + wall.shipped.facts.at(-1).txt,
    'not counted: 1119 imported in pushes over 100');
});

test('each board card carries this week\'s flow, its lead time and how long work has sat in a stage', () => {
  const { wall } = render(FRAMES);
  const roadmap = wall.cards.find((c) => c.name === 'Homelab Roadmap');
  assert.deepEqual([roadmap.flow.arrived, roadmap.flow.closed, roadmap.flow.cls], [6, 2, 'warn']);
  assert.equal(roadmap.flow.last, 'last week by now +4 / −3');
  assert.equal(roadmap.lead, '85% closed within 10d · 28d');
  const reviewing = roadmap.stations.find((st) => st.lbl === 'Reviewing');
  assert.deepEqual([reviewing.sub, reviewing.late], ['oldest 14d', true]);
  const doing = roadmap.stations.find((st) => st.lbl === 'Doing');
  assert.deepEqual([doing.sub, doing.late], ['oldest 3d', false]);
  const unfold = wall.cards.find((c) => c.name === 'Unfold');
  assert.deepEqual([unfold.flow.arrived, unfold.flow.closed, unfold.flow.cls], [2, 1, '']);
});

test('the machine band shows CI now, the agents, the spend per project and the error rates', () => {
  const { wall } = render(FRAMES);
  const m = wall.machine;
  assert.deepEqual([m.ci.v, m.ci.lines.map((l) => l.txt)], ['2', ['0 jobs queued', '3 runner pods']]);
  assert.equal(m.agents.v, '8');
  assert.equal(m.agents.unit, 'Runs · 1 running · 5 work items');
  assert.deepEqual(m.agents.lines.map((l) => l.txt),
    ['5 builder · 3 reviewer', '2 PRs opened · 1 merged · 4 open', '90% of closed agent PRs merged · 28d']);
  assert.equal(m.spend.v, 'USD 2.45');
  assert.equal(m.spend.unit, '62.9M tokens · today USD 0.42');
  assert.deepEqual(m.spend.projects.map((p) => [p.name, p.usd, p.tokens]), [
    ['Unfold', 'USD 1.20', '40.0M'],
    ['Unfold · homelab-cluster', 'USD 0.80', '20.0M'],
    ['Omnigraph', 'USD 0.40', '1.9M'],
    ['Unfold · earlier Run', 'USD 0.05', '1.0M'],
  ]);
  assert.deepEqual(m.errors.rates.map((r) => [r.k, r.v, r.cls]), [
    ['CI jobs', '12%', 'warn'], ['Agent Runs', '29%', 'warn'], ['Model calls', '1.4%', '']]);
  assert.equal(m.errors.rates[2].s, 'worst Omnigraph 1.7%');
});

test('a silent LiteLLM ledger is said, and an idle machine reads as idle rather than broken', () => {
  const { wall } = render(without('SPEND', 'RUN_KEYS', 'AGENTS', 'AGENT_PRS', 'CI_NOW', 'CI_FAILED'));
  assert.equal(wall.machine.spend.known, false);
  assert.equal(wall.machine.ci.unit, 'not reporting');
  assert.equal(wall.machine.agents.v, '0');
  assert.deepEqual(wall.machine.errors.rates, []);
});

test('text reaching markdown-it is escaped', () => {
  const { helpers } = render(FRAMES);
  assert.equal(helpers.wallText('fix: *bold* [x](y) <b>').toString(),
    'fix: &#42;bold&#42; &#91;x&#93;(y) &#60;b&#62;');
});
