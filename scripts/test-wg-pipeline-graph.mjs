import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const SRC = process.argv[2];
const REAL_WORKFLOW = process.argv[3];
const REAL_REUSABLE_DIR = process.argv[4];
const REAL_RUN_NAMES = process.argv[5];

const CALLER = `name: caller
on: push
jobs:
  static-analysis:
    name: "Static Analysis"
    uses: org/lib/.forgejo/workflows/static.yml@0000000000000000000000000000000000000000
  unit-tests:
    name: "Unit Tests"
    needs:
      - static-analysis
    uses: org/lib/.forgejo/workflows/tests.yml@0000000000000000000000000000000000000000
    with:
      node-version: "24"
      test-command: pnpm test
      job-name: Unit Tests
  content-validation:
    name: "Content Validation"
    needs: [static-analysis]
    uses: org/lib/.forgejo/workflows/tests.yml@0000000000000000000000000000000000000000
    with:
      test-command: REQUIRE_REAL_CONTENT=1 pnpm validate:content
      job-name: Content Validation
      smoke-paths: |
        /nl
        /en
  legacy:
    name: "Legacy"
    needs: [static-analysis]
    uses: org/lib/.forgejo/workflows/tests.yml@0000000000000000000000000000000000000000
  deploy-preview:
    name: "Deploy Preview"
    needs: [unit-tests]
    uses: org/lib/.forgejo/workflows/deploy.yml@0000000000000000000000000000000000000000
    with:
      environment: preview
  deploy-production:
    name: "Deploy Production"
    needs: [unit-tests]
    uses: org/lib/.forgejo/workflows/deploy.yml@0000000000000000000000000000000000000000
    with:
      environment: production
`;
const TESTS = `name: tests
on:
  workflow_call:
    inputs:
      node-version:
        description: 'x'
        required: false
        default: '22'
        type: string
      job-name:
        description: 'y'
        required: false
        default: 'Node.js test suite'
        type: string
jobs:
  tests-run:
    name: \${{ inputs.job-name }}
    runs-on: docker
    steps:
      - run: echo
`;
const STATIC = `name: static
on:
  workflow_call:
jobs:
  lint:
    name: 'Static Analysis (Prettier, ESLint)'
    runs-on: docker
    steps:
      - run: echo
`;
const DEPLOY = `name: deploy
on:
  workflow_call:
    inputs:
      environment:
        type: string
        required: true
jobs:
  preview:
    name: 'Deploy preview'
    runs-on: docker
    steps:
      - run: echo
  production:
    name: 'Deploy production'
    runs-on: docker
    steps:
      - run: echo
`;
const FIXTURE_FILES = { 'static.yml': STATIC, 'tests.yml': TESTS, 'deploy.yml': DEPLOY };

function boot(files) {
  const net = { fetches: 0 };
  const win = {
    fetch(input) {
      net.fetches++;
      const file = String(input).split('/').pop();
      const body = files[file];
      return Promise.resolve(new Response(body === undefined ? '' : body, { status: body === undefined ? 404 : 200 }));
    },
    document: { readyState: 'complete', getElementById: () => null, addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] },
    Response, Promise, JSON, Date, Math, parseInt, console,
    location: { pathname: '/' },
    localStorage: { getItem: () => null, setItem() {} },
    sessionStorage: { getItem: () => null, setItem() {} },
    setInterval: () => 0, clearInterval() {}, setTimeout: () => 0, addEventListener() {}, requestAnimationFrame() {},
  };
  win.window = win;
  const ctx = vm.createContext(win);
  vm.runInContext(fs.readFileSync(SRC, 'utf8'), ctx, { filename: SRC });
  return { graph: win.__wgPipeline.graph, net };
}

async function resolve(files, yaml, runNames) {
  const { graph, net } = boot(files);
  const yjobs = graph.parseWorkflowJobs(yaml);
  yjobs.forEach((j) => { j.label = (j.name && !/[$][{]/.test(j.name)) ? j.name : j.id; });
  await graph.attachChildItems(yjobs, '/org/app/raw/commit/deadbeef/.forgejo/workflows/');
  const orphans = graph.assignIndices(yjobs, runNames);
  const claimed = {};
  yjobs.forEach((j) => { claimed[j.id] = j.indices.map((i) => runNames[i] + '@' + j.depthByIndex[i]); });
  return { yjobs, orphans, claimed, net };
}

const plain = (x) => JSON.parse(JSON.stringify(x));
const results = [];
const check = async (name, fn) => {
  try { await fn(); results.push(['PASS', name]); } catch (e) { results.push(['FAIL', name + ': ' + e.message]); }
};

await check('caller with: is parsed, block scalars skipped', async () => {
  const { graph } = boot(FIXTURE_FILES);
  const jobs = graph.parseWorkflowJobs(CALLER);
  const cv = jobs.find((j) => j.id === 'content-validation');
  assert.deepEqual(plain({ ...cv.with }), { 'test-command': 'REQUIRE_REAL_CONTENT=1 pnpm validate:content', 'job-name': 'Content Validation', 'smoke-paths': '|' });
  assert.deepEqual(plain(cv.needs), ['static-analysis']);
  assert.equal(jobs.find((j) => j.id === 'unit-tests').with['node-version'], '24');
});

await check('workflow_call input defaults are read', async () => {
  const { graph } = boot(FIXTURE_FILES);
  assert.deepEqual(plain({ ...graph.parseWorkflowCallInputDefaults(TESTS) }), { 'node-version': '22', 'job-name': 'Node.js test suite' });
  assert.deepEqual(plain({ ...graph.parseWorkflowCallInputDefaults(STATIC) }), {});
});

await check('expression job names resolve per caller, default when with: omits it', async () => {
  const { yjobs } = await resolve(FIXTURE_FILES, CALLER, []);
  const label = (id) => yjobs.find((j) => j.id === id).childItems.map((c) => c.label);
  assert.deepEqual(plain(label('unit-tests')), ['Unit Tests']);
  assert.deepEqual(plain(label('content-validation')), ['Content Validation']);
  assert.deepEqual(plain(label('legacy')), ['Node.js test suite']);
  assert.deepEqual(plain(label('static-analysis')), ['Static Analysis (Prettier, ESLint)']);
});

await check('Forgejo -N duplicate suffix attaches the child to its caller, no orphans', async () => {
  const runNames = [
    'Static Analysis', 'Unit Tests', 'Content Validation', 'Legacy', 'Deploy Preview', 'Deploy Production',
    'Static Analysis (Prettier, ESLint)', 'Unit Tests-1', 'Content Validation-1', 'Node.js test suite',
    'Deploy preview', 'Deploy production', 'Deploy preview-1', 'Deploy production-1',
  ];
  const { orphans, claimed } = await resolve(FIXTURE_FILES, CALLER, runNames);
  assert.deepEqual(plain(orphans), []);
  assert.deepEqual(plain(claimed['unit-tests']), ['Unit Tests@0', 'Unit Tests-1@1']);
  assert.deepEqual(plain(claimed['content-validation']), ['Content Validation@0', 'Content Validation-1@1']);
  assert.deepEqual(plain(claimed['legacy']), ['Legacy@0', 'Node.js test suite@1']);
  assert.deepEqual(plain(claimed['deploy-preview']), ['Deploy Preview@0', 'Deploy preview@1', 'Deploy production@1']);
  assert.deepEqual(plain(claimed['deploy-production']), ['Deploy Production@0', 'Deploy preview-1@1', 'Deploy production-1@1']);
});

await check('suffix match never swallows a different job whose name merely starts alike', async () => {
  const files = { ...FIXTURE_FILES, 'tests.yml': TESTS.replace("default: 'Node.js test suite'", "default: 'Build'") };
  const { orphans } = await resolve(files, CALLER.replace(/job-name: .*\n/g, ''), ['Build', 'Build-check', 'Build-2']);
  assert.deepEqual(plain(orphans.map((o) => o.name)), ['Build-check']);
});

await check('one fetch per distinct reusable file even with several callers', async () => {
  const { net } = await resolve(FIXTURE_FILES, CALLER, []);
  assert.equal(net.fetches, 3);
});

if (REAL_WORKFLOW && REAL_REUSABLE_DIR && REAL_RUN_NAMES) {
  await check('real workflow: every run job attaches to a caller', async () => {
    const files = Object.fromEntries(fs.readdirSync(REAL_REUSABLE_DIR).map((f) => [f, fs.readFileSync(REAL_REUSABLE_DIR + '/' + f, 'utf8')]));
    const runNames = JSON.parse(fs.readFileSync(REAL_RUN_NAMES, 'utf8'));
    const { orphans, claimed } = await resolve(files, fs.readFileSync(REAL_WORKFLOW, 'utf8'), runNames);
    console.log(JSON.stringify(claimed, null, 1));
    assert.deepEqual(plain(orphans), []);
  });
}

results.forEach(([s, n]) => console.log(s, n));
if (results.some(([s]) => s === 'FAIL')) process.exit(1);
