import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SRC = process.argv[2];
const JOB_URL = '/webgrip/twente.dev/actions/runs/12/jobs/1/attempt/1';
const ART_URL = '/webgrip/twente.dev/actions/runs/12/artifacts';
const OTHER_URL = '/webgrip/twente.dev/actions/runs/12/jobs/1/rerun';

function jobPayload(status) {
  return JSON.stringify({ state: { run: { done: false, jobs: [{ status: 'success' }, { status }] } }, logs: { stepsLog: [] } });
}

function boot() {
  const listeners = {};
  const host = {
    attrs: {
      'data-job-index': '1',
      'data-initial-artifacts-response': JSON.stringify({ artifacts: [] }),
      'data-initial-post-response': JSON.stringify({ state: { run: { jobs: [{ status: 'running' }] } } }),
      'data-workflow-source-url': '',
    },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
  };
  const net = { job: 0, artifacts: 0, other: 0 };
  let jobStatus = 'running';
  const realFetch = (input) => {
    const url = String(input);
    if (url === JOB_URL) { net.job++; return Promise.resolve(new Response(jobPayload(jobStatus), { status: 200 })); }
    if (url === ART_URL) { net.artifacts++; return Promise.resolve(new Response(JSON.stringify({ artifacts: ['x'] }), { status: 200 })); }
    net.other++; return Promise.resolve(new Response('{}', { status: 200 }));
  };
  const document = {
    readyState: 'complete',
    visibilityState: 'visible',
    getElementById: (id) => (id === 'repo-action-view' ? host : null),
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener: (t, fn) => { (listeners[t] ||= []).push(fn); },
    createElement: () => ({ style: {}, setAttribute() {}, classList: { add() {}, contains: () => false }, appendChild() {}, remove() {} }),
    fonts: null,
  };
  const win = {
    fetch: realFetch, document, Response, Promise, JSON, Date, Math, parseInt, console,
    location: { pathname: '/webgrip/twente.dev/actions/runs/12/jobs/1' },
    localStorage: { getItem: () => null, setItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    setInterval: () => 0, clearInterval() {}, setTimeout: () => 0,
    addEventListener() {}, requestAnimationFrame() {},
  };
  win.window = win;
  const ctx = vm.createContext(win);
  vm.runInContext(fs.readFileSync(SRC, 'utf8'), ctx, { filename: SRC });
  const fire = (t) => (listeners[t] || []).forEach((fn) => fn({ target: { closest: (sel) => (sel === '.action-view-body' ? {} : null) } }));
  return { win, net, document, fire, stats: win.__wgPipeline.poll, setJobStatus: (s) => { jobStatus = s; } };
}

const results = [];
const check = async (name, fn) => {
  try { await fn(); results.push(['PASS', name]); }
  catch (e) { results.push(['FAIL', name + ' :: ' + e.message]); }
};

await check('MUST-PASS: governor installed and reports stats', async () => {
  const t = boot();
  assert.ok(t.stats, 'no stats object exposed on window.__wgPipeline.poll');
  assert.notEqual(t.win.fetch, undefined);
});

await check('MUST-PASS: unrelated URLs pass through untouched', async () => {
  const t = boot();
  await t.win.fetch(OTHER_URL);
  assert.equal(t.net.other, 1);
});

await check('MUST-PASS: visible + viewed job RUNNING polls every tick (no throttle)', async () => {
  const t = boot();
  for (let i = 0; i < 5; i++) await t.win.fetch(JOB_URL);
  assert.equal(t.net.job, 5, `expected 5 job fetches, got ${t.net.job}`);
});

await check('MUST-FIRE: hidden tab makes ZERO network calls and rejects with TypeError', async () => {
  const t = boot();
  t.document.visibilityState = 'hidden';
  for (const u of [JOB_URL, ART_URL, JOB_URL, ART_URL]) {
    await assert.rejects(() => t.win.fetch(u), (e) => e.name === 'TypeError');
  }
  assert.equal(t.net.job + t.net.artifacts, 0, 'network was hit while hidden');
  assert.equal(t.stats.hiddenSkipped, 4);
});

await check('MUST-FIRE: viewed job FINISHED throttles job polls to 1 per 5s', async () => {
  const t = boot();
  t.setJobStatus('success');
  await t.win.fetch(JOB_URL);
  await new Promise((r) => setImmediate(r));
  let rejected = 0;
  for (let i = 0; i < 6; i++) {
    try { await t.win.fetch(JOB_URL); } catch (e) { if (e.name === 'TypeError') rejected++; }
  }
  assert.equal(t.net.job, 1, `expected 1 job fetch, got ${t.net.job}`);
  assert.equal(rejected, 6);
});

await check('MUST-PASS: FAILED viewed job also counts as finished (throttled)', async () => {
  const t = boot();
  t.setJobStatus('failure');
  await t.win.fetch(JOB_URL);
  await new Promise((r) => setImmediate(r));
  await t.win.fetch(JOB_URL).catch(() => {});
  assert.equal(t.net.job, 1);
});

await check('MUST-FIRE: artifacts served from cache within TTL (seeded from page attr)', async () => {
  const t = boot();
  for (let i = 0; i < 10; i++) {
    const r = await t.win.fetch(ART_URL);
    assert.deepEqual(await r.json(), { artifacts: [] });
  }
  assert.equal(t.net.artifacts, 0, 'artifacts endpoint was hit despite fresh cache');
  assert.equal(t.stats.artifactsFromCache, 10);
});

await check('MUST-PASS: click in the run view reopens the gate immediately', async () => {
  const t = boot();
  t.setJobStatus('success');
  await t.win.fetch(JOB_URL);
  await new Promise((r) => setImmediate(r));
  await t.win.fetch(JOB_URL).catch(() => {});
  assert.equal(t.net.job, 1);
  t.fire('click');
  await t.win.fetch(JOB_URL);
  assert.equal(t.net.job, 2, 'gate did not reopen after a click');
});

await check('MUST-PASS: becoming visible again reopens the gate and refetches artifacts', async () => {
  const t = boot();
  await t.win.fetch(ART_URL);
  assert.equal(t.net.artifacts, 0);
  t.document.visibilityState = 'hidden';
  await t.win.fetch(ART_URL).catch(() => {});
  t.document.visibilityState = 'visible';
  t.fire('visibilitychange');
  await t.win.fetch(ART_URL);
  assert.equal(t.net.artifacts, 1, 'artifacts not refreshed after returning to the tab');
});

let bad = 0;
for (const [s, n] of results) { if (s === 'FAIL') bad++; console.log(`${s}  ${n}`); }
console.log(`\n${results.length - bad}/${results.length} passed`);
process.exit(bad ? 1 : 0);
