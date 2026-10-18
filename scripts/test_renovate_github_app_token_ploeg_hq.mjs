import { generateKeyPairSync, createVerify } from 'node:crypto';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const mintScript = process.env.MINT_SCRIPT;
const onlyCase = process.argv[2];
const { privateKey, publicKey } = generateKeyPairSync('rsa', { modulusLength: 2048 });
const privateKeyPem = privateKey.export({ type: 'pkcs1', format: 'pem' });
const installationToken = 'ghs_' + 'f'.repeat(36);
const vaultToken = 'hvs.' + 'v'.repeat(24);
const permissions = { contents: 'write', pull_requests: 'write', issues: 'write', workflows: 'write', checks: 'read', statuses: 'read', vulnerability_alerts: 'read', metadata: 'read' };
const work = mkdtempSync(join(tmpdir(), 'mint-'));
const serviceAccountTokenPath = join(work, 'token');
writeFileSync(serviceAccountTokenPath, 'service-account-jwt\n');

function verifyJwt(jwt) {
  const [header, claims, signature] = jwt.split('.');
  const valid = createVerify('RSA-SHA256').update(header + '.' + claims).verify(publicKey, Buffer.from(signature, 'base64url'));
  return valid ? JSON.parse(Buffer.from(claims, 'base64url').toString()) : null;
}

function fake(world) {
  const calls = [];
  const server = createServer((req, res) => {
    let raw = '';
    req.on('data', (chunk) => { raw += chunk; });
    req.on('end', () => {
      const body = raw ? JSON.parse(raw) : null;
      calls.push({ method: req.method, url: req.url, headers: req.headers, body });
      const reply = (status, payload) => {
        res.writeHead(status, { 'content-type': 'application/json' });
        res.end(payload === undefined ? '' : JSON.stringify(payload));
      };
      if (req.method === 'POST' && req.url === '/v1/auth/kubernetes/login') {
        if (body.role !== 'renovate-github-app-token-ploeg-hq' || body.jwt !== 'service-account-jwt') return reply(400, {});
        return reply(200, { auth: { client_token: vaultToken } });
      }
      if (req.method === 'GET' && req.url === '/v1/secret/data/github/ploeg-hq-renovate-app') {
        if (req.headers['x-vault-token'] !== vaultToken) return reply(403, {});
        if (world.vaultStatus !== 200) return reply(world.vaultStatus, {});
        return reply(200, { data: { data: { app_id: '424242', installation_id: '777', private_key: privateKeyPem } } });
      }
      if (req.method === 'POST' && req.url === '/app/installations/777/access_tokens') {
        const claims = verifyJwt((req.headers.authorization || '').replace(/^Bearer /, ''));
        if (!claims || claims.iss !== '424242') return reply(401, { message: 'A JSON web token could not be decoded' });
        if (world.githubStatus !== 201) return reply(world.githubStatus, { message: 'The permissions requested are not granted to this installation.' });
        return reply(201, { token: installationToken, expires_at: '2026-10-18T13:00:00Z' });
      }
      if (req.url === '/api/v1/namespaces/renovate/secrets/renovate-ploeg-hq-token' && req.method === 'PUT') {
        if (!world.secretExists) return reply(404, {});
        world.written = body;
        return reply(200, body);
      }
      if (req.url === '/api/v1/namespaces/renovate/secrets' && req.method === 'POST') {
        world.secretExists = true;
        world.written = body;
        return reply(201, body);
      }
      return reply(404, {});
    });
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, calls, url: 'http://127.0.0.1:' + server.address().port })));
}

async function mint(world) {
  const { server, calls, url } = await fake(world);
  const child = spawn(process.execPath, [mintScript], {
    env: {
      PATH: process.env.PATH,
      VAULT_ADDR: url,
      VAULT_ROLE: 'renovate-github-app-token-ploeg-hq',
      APP_SECRET_PATH: 'github/ploeg-hq-renovate-app',
      GITHUB_API: url,
      GITHUB_REPOSITORIES: 'ploeg',
      TOKEN_PERMISSIONS: JSON.stringify(permissions),
      KUBERNETES_API: url,
      NAMESPACE: 'renovate',
      RUNTIME_SECRET_NAME: 'renovate-ploeg-hq-token',
      SERVICE_ACCOUNT_TOKEN_PATH: serviceAccountTokenPath,
    },
  });
  let output = '';
  child.stdout.on('data', (chunk) => { output += chunk; });
  child.stderr.on('data', (chunk) => { output += chunk; });
  const code = await new Promise((resolve) => child.on('close', resolve));
  server.close();
  return { code, output, calls, world };
}

function expect(condition, message, result) {
  if (!condition) {
    throw new Error(message + '\n--- output ---\n' + result.output);
  }
}

const tokenRequests = (result) => result.calls.filter((call) => call.url.endsWith('/access_tokens'));

const cases = {
  async absent_credentials_exit_cleanly_and_mint_nothing() {
    const result = await mint({ vaultStatus: 404, githubStatus: 201, secretExists: true });
    expect(result.code === 0, 'absent credentials must exit 0', result);
    expect(tokenRequests(result).length === 0, 'absent credentials must not ask GitHub for a token', result);
    expect(result.world.written === undefined, 'absent credentials must not write the Secret', result);
    expect(result.output.includes('app credentials absent'), 'absent credentials must say so', result);
  },
  async present_credentials_write_a_scoped_token() {
    const result = await mint({ vaultStatus: 200, githubStatus: 201, secretExists: true });
    expect(result.code === 0, 'a successful mint must exit 0', result);
    const requests = tokenRequests(result);
    expect(requests.length === 1, 'exactly one token request', result);
    expect(JSON.stringify(requests[0].body.repositories) === '["ploeg"]', 'the token must be scoped to ploeg only', result);
    expect(JSON.stringify(requests[0].body.permissions) === JSON.stringify(permissions), 'the token must request exactly the configured permissions', result);
    const data = result.world.written?.data?.RENOVATE_TOKEN;
    expect(data && Buffer.from(data, 'base64').toString() === installationToken, 'the Secret must carry the minted token as RENOVATE_TOKEN', result);
  },
  async a_missing_secret_is_created() {
    const result = await mint({ vaultStatus: 200, githubStatus: 201, secretExists: false });
    expect(result.code === 0, 'creating the Secret must exit 0', result);
    expect(result.calls.some((call) => call.method === 'POST' && call.url === '/api/v1/namespaces/renovate/secrets'), 'a missing Secret must be created', result);
    expect(result.world.written !== undefined, 'the created Secret must carry the token', result);
  },
  async a_refused_token_fails_and_writes_nothing() {
    const result = await mint({ vaultStatus: 200, githubStatus: 422, secretExists: true });
    expect(result.code === 1, 'a refused token must exit 1', result);
    expect(result.world.written === undefined, 'a refused token must not write the Secret', result);
    expect(result.output.includes('not granted'), 'the failure must carry GitHub\'s reason', result);
  },
  async a_denied_openbao_read_fails() {
    const result = await mint({ vaultStatus: 403, githubStatus: 201, secretExists: true });
    expect(result.code === 1, 'a denied OpenBao read is a failure, not an absent App', result);
    expect(tokenRequests(result).length === 0, 'a denied read must not ask GitHub for a token', result);
  },
  async no_secret_value_reaches_the_log() {
    const result = await mint({ vaultStatus: 200, githubStatus: 201, secretExists: true });
    for (const value of [installationToken, vaultToken, privateKeyPem.split('\n')[1]]) {
      expect(!result.output.includes(value), 'a secret value was printed', result);
    }
  },
};

let failed = 0;
for (const [name, run] of Object.entries(cases)) {
  if (onlyCase && onlyCase !== name) continue;
  try {
    await run();
    console.log('ok   ' + name);
  } catch (error) {
    failed += 1;
    console.log('FAIL ' + name + ': ' + error.message);
  }
}
process.exitCode = failed ? 1 : 0;
