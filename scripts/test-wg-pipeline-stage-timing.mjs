import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SRC = process.argv[2];

function boot() {
  const win = {
    fetch: () => Promise.resolve(new Response('', { status: 404 })),
    document: { readyState: 'complete', getElementById: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] },
    Response, Promise, JSON, Date, Math, parseInt, isNaN, console,
    location: { pathname: '/' },
    localStorage: { getItem: () => null, setItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    setInterval: () => 0, clearInterval() {}, setTimeout: () => 0, addEventListener() {}, requestAnimationFrame() {},
  };
  win.window = win;
  vm.runInContext(fs.readFileSync(SRC, 'utf8'), vm.createContext(win), { filename: SRC });
  return win.__wgPipeline;
}

const RUN_743_TASKS = [
  { id: 46844, run_number: 743, name: 'Ploeg - Distribute (Harbor)', status: 'running', run_started_at: '2026-10-03T10:18:01Z', updated_at: '2026-10-03T10:22:23Z' },
  { id: 46843, run_number: 743, name: 'Ploeg - Publish Helm chart (Harbor)', status: 'success', run_started_at: '2026-10-03T10:17:50Z', updated_at: '2026-10-03T10:17:57Z' },
  { id: 46842, run_number: 743, name: 'Vloer - Publish VS Code extension', status: 'success', run_started_at: '2026-10-03T10:17:02Z', updated_at: '2026-10-03T10:17:45Z' },
  { id: 46841, run_number: 743, name: 'Vloer - Build, gate and sign images (Harbor)-1', status: 'running', run_started_at: '2026-10-03T10:14:19Z', updated_at: '2026-10-03T10:22:20Z' },
  { id: 46840, run_number: 743, name: 'Vloer - Build, gate and sign images (Harbor)', status: 'success', run_started_at: '2026-10-03T10:11:51Z', updated_at: '2026-10-03T10:16:58Z' },
  { id: 46839, run_number: 743, name: 'Vloer - Publish Helm chart (Harbor)', status: 'success', run_started_at: '2026-10-03T10:11:35Z', updated_at: '2026-10-03T10:11:46Z' },
  { id: 46837, run_number: 742, name: 'checks', status: 'failure', run_started_at: '2026-10-03T10:11:10Z', updated_at: '2026-10-03T10:14:11Z' },
  { id: 46835, run_number: 743, name: 'site-release-tag', status: 'success', run_started_at: '2026-10-03T10:10:28Z', updated_at: '2026-10-03T10:10:28Z' },
  { id: 46834, run_number: 743, name: 'parse-release-tag', status: 'success', run_started_at: '2026-10-03T10:10:24Z', updated_at: '2026-10-03T10:10:24Z' },
];
const NOW = Date.parse('2026-10-03T10:23:00Z');
const STATUS = Object.fromEntries(RUN_743_TASKS.map((t) => [t.name, t.status]));

const results = [];
const check = async (name, fn) => {
  try { await fn(); results.push(['PASS', name]); } catch (e) { results.push(['FAIL', name + ': ' + e.message]); }
};

const wallOf = (timing, timings, names, statusOf = (n) => STATUS[n] || 'blocked') =>
  timing.stageWallClock(names.map((_, i) => i), (i) => names[i], (i) => statusOf(names[i]), timings, NOW);

await check('only tasks of the viewed run count, a rerun keeps the newest attempt', async () => {
  const { timing } = boot();
  const rerun = { id: 46900, run_number: 743, name: 'parse-release-tag', status: 'success', run_started_at: '2026-10-03T10:30:00Z', updated_at: '2026-10-03T10:30:05Z' };
  const timings = timing.latestTaskTimings(RUN_743_TASKS.concat([rerun]), 743);
  assert.equal(timings.checks, undefined);
  assert.equal(timings['parse-release-tag'].start, Date.parse('2026-10-03T10:30:00Z'));
  assert.equal(timings['Ploeg - Distribute (Harbor)'].finished, false);
});

await check('finished stage spans first start to last finish, not the sum of durations', async () => {
  const { timing } = boot();
  const timings = timing.latestTaskTimings(RUN_743_TASKS, 743);
  const wall = wallOf(timing, timings, ['Vloer - Publish Helm chart (Harbor)', 'Vloer - Build, gate and sign images (Harbor)', 'Vloer - Publish VS Code extension', 'Ploeg - Publish Helm chart (Harbor)']);
  assert.equal(wall.live, false);
  assert.equal(wall.seconds, 6 * 60 + 22);
});

await check('stage with a running job counts up to now, ignoring the stale heartbeat', async () => {
  const { timing } = boot();
  const timings = timing.latestTaskTimings(RUN_743_TASKS, 743);
  const wall = wallOf(timing, timings, ['Vloer - Publish Helm chart (Harbor)', 'Ploeg - Distribute (Harbor)']);
  assert.equal(wall.live, true);
  assert.equal(wall.seconds, 11 * 60 + 25);
});

await check('finished jobs next to a not-yet-started one keep the stage live', async () => {
  const { timing } = boot();
  const timings = timing.latestTaskTimings(RUN_743_TASKS, 743);
  const wall = wallOf(timing, timings, ['parse-release-tag', 'Ploeg - Sign & Attest (Harbor)']);
  assert.equal(wall.live, true);
  assert.equal(wall.seconds, 12 * 60 + 36);
});

await check('stage where nothing has started shows no wall clock', async () => {
  const { timing } = boot();
  const timings = timing.latestTaskTimings(RUN_743_TASKS, 743);
  assert.equal(wallOf(timing, timings, ['Ploeg - Sign & Attest (Harbor)', 'Vloer - Verify and publish all destinations']), null);
});

await check('matrix duplicate of a plain job joins its caller node, not a stage-1 orphan', async () => {
  const { graph } = boot();
  const yjobs = [
    { id: 'parse', label: 'parse-release-tag', needs: [], childItems: [] },
    { id: 'build', label: 'Vloer - Build, gate and sign images (Harbor)', needs: ['parse'], childItems: [] },
  ];
  const orphans = graph.assignIndices(yjobs, ['parse-release-tag', 'Vloer - Build, gate and sign images (Harbor)', 'Vloer - Build, gate and sign images (Harbor)-1']);
  assert.deepEqual(JSON.parse(JSON.stringify(orphans)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(yjobs[1].indices)), [1, 2]);
});

await check('a reusable child with the dedup suffix still lands at its nesting depth', async () => {
  const { graph } = boot();
  const yjobs = [{ id: 'unit', label: 'Unit Tests', needs: [], childItems: [{ label: 'Unit Tests', depth: 1 }] }];
  graph.assignIndices(yjobs, ['Unit Tests', 'Unit Tests-1']);
  assert.equal(yjobs[0].depthByIndex[1], 1);
});

results.forEach(([s, n]) => console.log(s, n));
if (results.some(([s]) => s === 'FAIL')) process.exit(1);
