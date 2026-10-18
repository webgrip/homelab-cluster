import { createSign } from 'node:crypto';
import { readFileSync } from 'node:fs';

const USER_AGENT = 'webgrip-renovate-github-app-token-ploeg-hq';
const GITHUB_API_VERSION = '2022-11-28';

class MintFailure extends Error {}
class AppCredentialsAbsent extends Error {}

function env(name, fallback) {
  const value = process.env[name] ?? fallback;
  if (value === undefined || value === '') {
    throw new MintFailure('environment variable ' + name + ' is required');
  }
  return value;
}

function log(message) {
  process.stdout.write(message + '\n');
}

async function request(method, url, headers, body) {
  const requestHeaders = { 'user-agent': USER_AGENT, ...headers };
  if (body !== undefined) {
    requestHeaders['content-type'] = 'application/json';
  }
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(30000),
    });
  } catch (error) {
    throw new MintFailure(method + ' ' + url + ' failed: ' + error.name);
  }
  const text = await response.text();
  let parsed = null;
  try {
    parsed = text ? JSON.parse(text) : null;
  } catch {
    parsed = null;
  }
  return { status: response.status, body: parsed };
}

function serviceAccountToken() {
  return readFileSync(env('SERVICE_ACCOUNT_TOKEN_PATH', '/var/run/secrets/kubernetes.io/serviceaccount/token'), 'utf8').trim();
}

async function readAppCredentials() {
  const vault = env('VAULT_ADDR').replace(/\/$/, '');
  const role = env('VAULT_ROLE');
  const path = env('APP_SECRET_PATH');
  const login = await request('POST', vault + '/v1/auth/kubernetes/login', {}, { role, jwt: serviceAccountToken() });
  if (login.status !== 200 || !login.body?.auth?.client_token) {
    throw new MintFailure('OpenBao kubernetes login for role ' + role + ' returned ' + login.status);
  }
  const read = await request('GET', vault + '/v1/secret/data/' + path, { 'x-vault-token': login.body.auth.client_token });
  if (read.status === 404) {
    throw new AppCredentialsAbsent('secret/' + path + ' does not exist');
  }
  if (read.status === 403) {
    throw new MintFailure('OpenBao denied reading secret/' + path + ' (403)');
  }
  if (read.status !== 200) {
    throw new MintFailure('OpenBao read of secret/' + path + ' returned ' + read.status);
  }
  const data = read.body?.data?.data;
  if (!data) {
    throw new AppCredentialsAbsent('secret/' + path + ' has no live version');
  }
  const app = {
    appId: String(data.app_id ?? '').trim(),
    installationId: String(data.installation_id ?? '').trim(),
    privateKey: String(data.private_key ?? ''),
  };
  if (!(app.appId && app.installationId && app.privateKey.trim())) {
    throw new AppCredentialsAbsent('secret/' + path + ' lacks app_id, installation_id or private_key');
  }
  return app;
}

function base64url(text) {
  return Buffer.from(text).toString('base64url');
}

function appJwt(appId, privateKey, nowSeconds) {
  const header = base64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const claims = base64url(JSON.stringify({ iat: nowSeconds - 60, exp: nowSeconds + 540, iss: appId }));
  const signature = createSign('RSA-SHA256').update(header + '.' + claims).sign(privateKey).toString('base64url');
  return header + '.' + claims + '.' + signature;
}

function githubHeaders(bearer) {
  return {
    accept: 'application/vnd.github+json',
    'x-github-api-version': GITHUB_API_VERSION,
    authorization: 'Bearer ' + bearer,
  };
}

async function mintInstallationToken(app) {
  const api = env('GITHUB_API', 'https://api.github.com').replace(/\/$/, '');
  const jwt = appJwt(app.appId, app.privateKey, Math.floor(Date.now() / 1000));
  const response = await request(
    'POST',
    api + '/app/installations/' + app.installationId + '/access_tokens',
    githubHeaders(jwt),
    { repositories: env('GITHUB_REPOSITORIES').split(','), permissions: JSON.parse(env('TOKEN_PERMISSIONS')) },
  );
  if (response.status !== 201 || !response.body?.token) {
    const reason = typeof response.body?.message === 'string' ? ': ' + response.body.message : '';
    throw new MintFailure('GitHub refused an installation token for installation ' + app.installationId + ' (' + response.status + ')' + reason);
  }
  return { token: response.body.token, expiresAt: response.body.expires_at ?? '' };
}

async function writeRuntimeSecret(minted) {
  const api = env('KUBERNETES_API', 'https://kubernetes.default.svc').replace(/\/$/, '');
  const namespace = env('NAMESPACE');
  const name = env('RUNTIME_SECRET_NAME');
  const collection = api + '/api/v1/namespaces/' + namespace + '/secrets';
  const headers = { authorization: 'Bearer ' + serviceAccountToken() };
  const manifest = {
    apiVersion: 'v1',
    kind: 'Secret',
    type: 'Opaque',
    metadata: {
      name,
      namespace,
      labels: { 'app.kubernetes.io/name': 'renovate-github-app-token-ploeg-hq' },
      annotations: { 'renovate.webgrip.io/token-expires-at': minted.expiresAt },
    },
    data: { RENOVATE_TOKEN: Buffer.from(minted.token).toString('base64') },
  };
  let response = await request('PUT', collection + '/' + name, headers, manifest);
  if (response.status === 404) {
    response = await request('POST', collection, headers, manifest);
  }
  if (response.status !== 200 && response.status !== 201) {
    throw new MintFailure('writing Secret ' + namespace + '/' + name + ' returned ' + response.status);
  }
  return namespace + '/' + name;
}

async function run() {
  let app;
  try {
    app = await readAppCredentials();
  } catch (error) {
    if (error instanceof AppCredentialsAbsent) {
      log('app credentials absent: ' + error.message + '; no token minted. Owner step: docs/techdocs/docs/runbooks/github-app-ploeg-hq.md');
      return 0;
    }
    throw error;
  }
  const minted = await mintInstallationToken(app);
  const target = await writeRuntimeSecret(minted);
  log('installation token for ' + env('GITHUB_REPOSITORIES') + ' written to Secret ' + target + ' (expires ' + minted.expiresAt + ')');
  return 0;
}

try {
  process.exitCode = await run();
} catch (error) {
  log('mint failed: ' + (error instanceof MintFailure ? error.message : 'unexpected ' + error.name));
  process.exitCode = 1;
}
