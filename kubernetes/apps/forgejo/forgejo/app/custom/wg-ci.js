(function () {
  'use strict';

  var WG_CI_VERSION = '2.0.1';
  var CONSOLE_PATH = '/-/ci';
  var OAUTH_CONFIG_URL = '/assets/wg/wg-ci-oauth.json';
  var PANELS_URL = '/assets/wg/wg-ci-panels.json';
  var AUTH_KEY = 'wg-ci-auth';
  var PKCE_KEY = 'wg-ci-pkce';
  var THEME_KEY = 'wg-ci-theme';
  var PREFS_KEY = 'wg-ci-prefs';
  var TOKEN_SCOPES = 'read:repository read:user read:organization read:admin';
  var TOKEN_EARLY_REFRESH_MS = 60000;
  var API_BASE = '/-/ci/api';
  var STATE_POLL_MS = 2000;
  var STATE_POLL_LOADING_MS = 400;
  var OPTIMISTIC_HOLD_MS = 20000;
  var JOBS_INTERVAL_MS = 5000;
  var TICK_MS = 1000;
  var WINDOW_MS = 24 * 3600 * 1000;
  var CONFIRM_MS = 4000;
  var CONFIRM_ARM_GUARD_MS = 400;
  var ACTION_FLIP_GUARD_MS = 1500;
  var TOAST_MS = 4500;
  var STRIP_LENGTH = 20;
  var RUN_PAGE_SIZE = 150;
  var MIN_RENDER_GAP_MS = 250;
  var SHORT_DATE = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short' });
  var LONG_DAY = new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  var STAMP = new Intl.DateTimeFormat(undefined, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  var MAX_QUEUE_SAMPLE_MS = 6 * 3600 * 1000;
  var ACTIVE = { running: 1, waiting: 1, blocked: 1 };
  var QUEUED = { waiting: 1, blocked: 1 };
  var FINISHED = { success: 1, failure: 1, cancelled: 1, skipped: 1 };
  var STATUS_ORDER = { running: 0, waiting: 1, blocked: 2 };
  var STATUS_LABEL = {
    success: 'Succeeded', failure: 'Failed', cancelled: 'Cancelled', skipped: 'Skipped',
    waiting: 'Queued', blocked: 'Blocked', running: 'Running', unknown: 'Unknown',
  };
  var STATUS_FILTERS = [
    { key: 'all', label: 'All', test: function () { return true; } },
    { key: 'active', label: 'In progress', test: function (r) { return !!ACTIVE[r.status]; } },
    { key: 'failure', label: 'Failed', test: function (r) { return r.status === 'failure'; } },
    { key: 'success', label: 'Succeeded', test: function (r) { return r.status === 'success'; } },
    { key: 'cancelled', label: 'Cancelled', test: function (r) { return r.status === 'cancelled' || r.status === 'skipped'; } },
  ];
  var TABS = [
    { key: 'runs', label: 'Runs' },
    { key: 'repos', label: 'Repositories' },
    { key: 'runners', label: 'Runners' },
    { key: 'insights', label: 'Insights' },
  ];
  var INSIGHT_RANGES = [
    { key: '6h', label: '6 hours', from: 'now-6h' },
    { key: '24h', label: '24 hours', from: 'now-24h' },
    { key: '7d', label: '7 days', from: 'now-7d' },
    { key: '30d', label: '30 days', from: 'now-30d' },
  ];

  var PATHS = {
    success: '<path d="M8 16A8 8 0 1 1 8 0a8 8 0 0 1 0 16Zm3.78-9.72a.751.751 0 0 0-.018-1.042.751.751 0 0 0-1.042-.018L6.75 9.19 5.28 7.72a.751.751 0 0 0-1.042.018.751.751 0 0 0-.018 1.042l2 2a.75.75 0 0 0 1.06 0Z"/>',
    failure: '<path d="M2.343 13.657A8 8 0 1 1 13.658 2.343 8 8 0 0 1 2.343 13.657ZM6.03 4.97a.751.751 0 0 0-1.042.018.751.751 0 0 0-.018 1.042L6.94 8 4.97 9.97a.749.749 0 0 0 .326 1.275.749.749 0 0 0 .734-.215L8 9.06l1.97 1.97a.749.749 0 0 0 1.275-.326.749.749 0 0 0-.215-.734L9.06 8l1.97-1.97a.749.749 0 0 0-.326-1.275.749.749 0 0 0-.734.215L8 6.94Z"/>',
    cancelled: '<path d="M4.47.22A.749.749 0 0 1 5 0h6c.199 0 .389.079.53.22l4.25 4.25c.141.14.22.331.22.53v6a.749.749 0 0 1-.22.53l-4.25 4.25A.749.749 0 0 1 11 16H5a.749.749 0 0 1-.53-.22L.22 11.53A.749.749 0 0 1 0 11V5c0-.199.079-.389.22-.53Zm.84 1.28L1.5 5.31v5.38l3.81 3.81h5.38l3.81-3.81V5.31L10.69 1.5ZM8 4a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 1 0-2 1 1 0 0 1 0 2Z"/>',
    skipped: '<path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Zm9.78-2.22-5.5 5.5a.749.749 0 0 1-1.275-.326.749.749 0 0 1 .215-.734l5.5-5.5a.751.751 0 0 1 1.042.018.751.751 0 0 1 .018 1.042Z"/>',
    waiting: '<path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Zm7-3.25v2.992l2.028.812a.75.75 0 0 1-.557 1.392l-2.5-1A.751.751 0 0 1 7 8.25v-3.5a.75.75 0 0 1 1.5 0Z"/>',
    blocked: '<path d="M4.467.22a.749.749 0 0 1 .53-.22h6.006c.199 0 .389.079.53.22l4.247 4.247c.141.14.22.331.22.53v6.006a.749.749 0 0 1-.22.53l-4.247 4.247a.749.749 0 0 1-.53.22H4.997a.749.749 0 0 1-.53-.22L.22 11.533a.749.749 0 0 1-.22-.53V4.997c0-.199.079-.389.22-.53Zm.84 1.28L1.5 5.308v5.384L5.308 14.5h5.384l3.808-3.808V5.308L10.692 1.5ZM4 7.75A.75.75 0 0 1 4.75 7h6.5a.75.75 0 0 1 0 1.5h-6.5A.75.75 0 0 1 4 7.75Z"/>',
    running: '<path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z" opacity=".3"/><path d="M8 0a8 8 0 0 1 8 8h-1.5A6.5 6.5 0 0 0 8 1.5Z"/>',
    stop: '<path d="M5.75 4h4.5c.966 0 1.75.784 1.75 1.75v4.5A1.75 1.75 0 0 1 10.25 12h-4.5A1.75 1.75 0 0 1 4 10.25v-4.5C4 4.784 4.784 4 5.75 4Z"/>',
    rerun: '<path d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z"/>',
    external: '<path d="M3.75 2h3.5a.75.75 0 0 1 0 1.5h-3.5a.25.25 0 0 0-.25.25v8.5c0 .138.112.25.25.25h8.5a.25.25 0 0 0 .25-.25v-3.5a.75.75 0 0 1 1.5 0v3.5A1.75 1.75 0 0 1 12.25 14h-8.5A1.75 1.75 0 0 1 2 12.25v-8.5C2 2.784 2.784 2 3.75 2Zm6.854-1h4.146a.25.25 0 0 1 .25.25v4.146a.25.25 0 0 1-.427.177L13.03 4.03 9.28 7.78a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042l3.75-3.75-1.543-1.543A.25.25 0 0 1 10.604 1Z"/>',
    chevron: '<path d="M6.22 3.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L9.94 8 6.22 4.28a.75.75 0 0 1 0-1.06Z"/>',
    search: '<path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z"/>',
    close: '<path d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/>',
    branch: '<path d="M9.5 3.25a2.25 2.25 0 1 1 3 2.122V6A2.5 2.5 0 0 1 10 8.5H6a1 1 0 0 0-1 1v1.128a2.251 2.251 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.5 0v1.836A2.493 2.493 0 0 1 6 7h4a1 1 0 0 0 1-1v-.628A2.25 2.25 0 0 1 9.5 3.25Zm-6 0a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Zm8.25-.75a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM4.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Z"/>',
    pull: '<path d="M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z"/>',
    tag: '<path d="M1 7.775V2.75C1 1.784 1.784 1 2.75 1h5.025c.464 0 .91.184 1.238.513l6.25 6.25a1.75 1.75 0 0 1 0 2.474l-5.026 5.026a1.75 1.75 0 0 1-2.474 0l-6.25-6.25A1.752 1.752 0 0 1 1 7.775Zm1.5 0c0 .066.026.13.073.177l6.25 6.25a.25.25 0 0 0 .354 0l5.025-5.025a.25.25 0 0 0 0-.354l-6.25-6.25a.25.25 0 0 0-.177-.073H2.75a.25.25 0 0 0-.25.25ZM6 5a1 1 0 1 1 0 2 1 1 0 0 1 0-2Z"/>',
    schedule: '<path d="M4.75 0a.75.75 0 0 1 .75.75V2h5V.75a.75.75 0 0 1 1.5 0V2h1.25c.966 0 1.75.784 1.75 1.75v10.5A1.75 1.75 0 0 1 13.25 16H2.75A1.75 1.75 0 0 1 1 14.25V3.75C1 2.784 1.784 2 2.75 2H4V.75A.75.75 0 0 1 4.75 0ZM2.5 7.5v6.75c0 .138.112.25.25.25h10.5a.25.25 0 0 0 .25-.25V7.5Zm10.75-4H2.75a.25.25 0 0 0-.25.25V6h11V3.75a.25.25 0 0 0-.25-.25Z"/>',
    manual: '<path d="M9.504.43a1.516 1.516 0 0 1 2.437 1.713L10.415 5.5h2.123c1.57 0 2.346 1.909 1.22 3.004l-7.34 7.142a1.249 1.249 0 0 1-.871.354h-.302a1.25 1.25 0 0 1-1.157-1.723L5.633 10.5H3.462c-1.57 0-2.346-1.909-1.22-3.004L9.503.429Zm1.047 1.074L3.286 8.571A.25.25 0 0 0 3.462 9H6.75a.75.75 0 0 1 .694 1.034l-1.713 4.188 6.982-6.793A.25.25 0 0 0 12.538 7H9.25a.75.75 0 0 1-.683-1.06l2.008-4.418.003-.006a.036.036 0 0 0-.004-.009l-.006-.006-.008-.001c-.003 0-.006.002-.009.004Z"/>',
    commit: '<path d="M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z"/>',
    alert: '<path d="M6.457 1.047c.659-1.234 2.427-1.234 3.086 0l6.082 11.378A1.75 1.75 0 0 1 14.082 15H1.918a1.75 1.75 0 0 1-1.543-2.575Zm1.763.707a.25.25 0 0 0-.44 0L1.698 13.132a.25.25 0 0 0 .22.368h12.164a.25.25 0 0 0 .22-.368Zm.53 3.996v2.5a.75.75 0 0 1-1.5 0v-2.5a.75.75 0 0 1 1.5 0ZM9 11a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z"/>',
    pause: '<path d="M5.75 3a.75.75 0 0 1 .75.75v8.5a.75.75 0 0 1-1.5 0v-8.5A.75.75 0 0 1 5.75 3Zm4.5 0a.75.75 0 0 1 .75.75v8.5a.75.75 0 0 1-1.5 0v-8.5a.75.75 0 0 1 .75-.75Z"/>',
    play: '<path d="M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Zm4.879-2.773 4.264 2.559a.25.25 0 0 1 0 .428l-4.264 2.559A.25.25 0 0 1 6 10.559V5.442a.25.25 0 0 1 .379-.215Z"/>',
  };
  var EVENT_ICON = { push: 'commit', pull_request: 'pull', pull_request_target: 'pull', schedule: 'schedule', workflow_dispatch: 'manual', release: 'tag', create: 'tag' };
  var EVENT_LABEL = { push: 'push', pull_request: 'pull request', pull_request_target: 'pull request', schedule: 'schedule', workflow_dispatch: 'manual', release: 'release' };

  var state = {
    config: null,
    me: null,
    theme: null,
    repos: new Map(),
    runs: new Map(),
    runners: null,
    runnersNote: '',
    queue: null,
    jobs: new Map(),
    expanded: new Set(),
    selected: new Set(),
    busy: new Set(),
    failures: new Map(),
    actionShown: new Map(),
    confirm: null,
    focusKey: null,
    tab: 'runs',
    filters: { q: '', status: 'all', repo: '', event: '', mine: false, trunk: false },
    insightRange: '24h',
    runLimit: RUN_PAGE_SIZE,
    lastRenderAt: 0,
    insightsMounted: false,
    panels: null,
    reposDiscovered: false,
    optimistic: new Map(),
    stateVersion: 0,
    polling: false,
    lastPollAt: 0,
    apiError: null,
    lastSyncAt: 0,
    paused: false,
    authFailed: false,
    started: false,
  };
  var dom = {};
  var renderQueued = false;
  var toastTimer = null;

  function readJson(storage, key) {
    try { return JSON.parse(storage.getItem(key) || 'null'); } catch (e) { return null; }
  }

  function writeJson(storage, key, value) {
    try {
      if (value === null) storage.removeItem(key);
      else storage.setItem(key, JSON.stringify(value));
    } catch (e) { }
  }

  function esc(value) {
    return String(value === null || value === undefined ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function icon(name, size, className) {
    var px = size || 16;
    return '<svg class="wg-ci-icon' + (className ? ' ' + className : '') + '" viewBox="0 0 16 16" width="' + px +
      '" height="' + px + '" aria-hidden="true" fill="currentColor">' + (PATHS[name] || '') + '</svg>';
  }

  function plural(n, word, many) {
    return n + ' ' + (n === 1 ? word : (many || word + 's'));
  }

  function formatDuration(ms) {
    if (!(ms >= 0)) return '';
    var s = Math.round(ms / 1000);
    if (s < 60) return s + 's';
    var m = Math.floor(s / 60);
    if (m < 60) return m + 'm ' + String(s % 60).padStart(2, '0') + 's';
    var h = Math.floor(m / 60);
    if (h < 24) return h + 'h ' + String(m % 60).padStart(2, '0') + 'm';
    return Math.floor(h / 24) + 'd ' + (h % 24) + 'h';
  }

  function formatAgo(t, now) {
    if (!t) return '';
    var s = Math.max(0, Math.round(((now || Date.now()) - t) / 1000));
    if (s < 45) return 'just now';
    if (s < 3600) return Math.max(1, Math.round(s / 60)) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    if (s < 7 * 86400) return Math.round(s / 86400) + 'd ago';
    return SHORT_DATE.format(t);
  }

  function formatStamp(t) {
    if (!t) return '';
    return STAMP.format(t);
  }

  function startOfDay(t) {
    var d = new Date(t);
    d.setHours(0, 0, 0, 0);
    return d.getTime();
  }

  function dayLabel(dayStart, todayStart) {
    var diff = Math.round((todayStart - dayStart) / 86400000);
    if (diff <= 0) return 'Today';
    if (diff === 1) return 'Yesterday';
    return LONG_DAY.format(dayStart);
  }

  function groupOf(run, todayStart) {
    return ACTIVE[run.status] ? 'In progress' : dayLabel(startOfDay(run.created || todayStart), todayStart);
  }

  function percentile(values, fraction) {
    if (!values.length) return null;
    var sorted = values.slice().sort(function (a, b) { return a - b; });
    return sorted[Math.min(sorted.length - 1, Math.round(fraction * (sorted.length - 1)))];
  }

  function query(params) {
    if (!params) return '';
    var parts = [];
    Object.keys(params).forEach(function (k) {
      if (params[k] !== undefined && params[k] !== null && params[k] !== '') {
        parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(params[k]));
      }
    });
    return parts.length ? '?' + parts.join('&') : '';
  }

  function inPool(items, worker, limit) {
    var next = 0;
    var results = new Array(items.length);
    function pull() {
      if (next >= items.length) return Promise.resolve();
      var k = next++;
      return Promise.resolve().then(function () { return worker(items[k]); })
        .then(function (r) { results[k] = r; }, function (e) { results[k] = e; })
        .then(pull);
    }
    var lanes = [];
    for (var i = 0; i < Math.min(limit, items.length); i++) lanes.push(pull());
    return Promise.all(lanes).then(function () { return results; });
  }

  function AuthRequired(message) {
    this.message = message;
    this.authRequired = true;
  }

  function base64url(bytes) {
    var text = '';
    for (var i = 0; i < bytes.length; i++) text += String.fromCharCode(bytes[i]);
    return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function randomToken(length) {
    var bytes = new Uint8Array(length);
    crypto.getRandomValues(bytes);
    return base64url(bytes);
  }

  function challengeOf(verifier) {
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)).then(function (digest) {
      return base64url(new Uint8Array(digest));
    });
  }

  function withTokenLock(work) {
    if (navigator.locks && navigator.locks.request) return navigator.locks.request('wg-ci-token', work);
    return Promise.resolve().then(work);
  }

  function storeTokens(response) {
    var auth = {
      access: response.access_token,
      refresh: response.refresh_token,
      expiresAt: Date.now() + (Number(response.expires_in) || 3600) * 1000,
    };
    writeJson(localStorage, AUTH_KEY, auth);
    state.authFailed = false;
    return auth.access;
  }

  function tokenRequest(fields) {
    var body = new URLSearchParams();
    Object.keys(fields).forEach(function (k) { body.set(k, fields[k]); });
    return fetch('/login/oauth/access_token', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body.toString(),
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || !data.access_token) {
          writeJson(localStorage, AUTH_KEY, null);
          throw new AuthRequired(data.error_description || data.error || 'Forgejo did not issue a token (HTTP ' + res.status + ').');
        }
        return data;
      });
    });
  }

  function refreshToken(rejectedAccess) {
    return withTokenLock(function () {
      var auth = readJson(localStorage, AUTH_KEY);
      if (auth && auth.access !== rejectedAccess && auth.expiresAt - TOKEN_EARLY_REFRESH_MS > Date.now()) return auth.access;
      if (!auth || !auth.refresh) throw new AuthRequired('Connect the console to your Forgejo account.');
      return tokenRequest({ grant_type: 'refresh_token', refresh_token: auth.refresh, client_id: state.config.client_id })
        .then(storeTokens);
    });
  }

  function accessToken() {
    var auth = readJson(localStorage, AUTH_KEY);
    if (auth && auth.expiresAt - TOKEN_EARLY_REFRESH_MS > Date.now()) return Promise.resolve(auth.access);
    return refreshToken(auth ? auth.access : null);
  }

  function startSignIn() {
    var verifier = randomToken(48);
    var nonce = randomToken(16);
    writeJson(sessionStorage, PKCE_KEY, { verifier: verifier, state: nonce, back: location.search });
    return challengeOf(verifier).then(function (challenge) {
      location.assign('/login/oauth/authorize' + query({
        client_id: state.config.client_id,
        redirect_uri: state.config.redirect_uri,
        response_type: 'code',
        scope: TOKEN_SCOPES,
        code_challenge: challenge,
        code_challenge_method: 'S256',
        state: nonce,
      }));
    });
  }

  function finishSignIn() {
    var params = new URLSearchParams(location.search);
    if (!params.has('code') && !params.has('error')) return Promise.resolve(false);
    var pending = readJson(sessionStorage, PKCE_KEY);
    writeJson(sessionStorage, PKCE_KEY, null);
    history.replaceState(null, '', CONSOLE_PATH + ((pending && pending.back) || ''));
    if (params.has('error')) {
      return Promise.reject(new AuthRequired(params.get('error_description') || params.get('error')));
    }
    if (!pending || pending.state !== params.get('state')) {
      return Promise.reject(new AuthRequired('That sign-in answer belongs to another tab or an older attempt. Connect again.'));
    }
    return tokenRequest({
      grant_type: 'authorization_code',
      code: params.get('code'),
      client_id: state.config.client_id,
      redirect_uri: state.config.redirect_uri,
      code_verifier: pending.verifier,
    }).then(storeTokens).then(function () { return true; });
  }

  function apiResponse(path, params) {
    var url = '/api/v1' + path + query(params);
    function attempt(token, retried) {
      return fetch(url, { headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' } }).then(function (res) {
        if (res.status === 401 && !retried) return refreshToken(token).then(function (t) { return attempt(t, true); });
        if (res.status === 401) throw new AuthRequired('Forgejo no longer accepts the console token.');
        return res;
      });
    }
    return accessToken().then(function (t) { return attempt(t, false); });
  }

  function api(path, params) {
    return apiResponse(path, params).then(function (res) {
      if (!res.ok) {
        var error = new Error('HTTP ' + res.status + ' for ' + path);
        error.status = res.status;
        throw error;
      }
      return res.json().then(function (data) {
        return { data: data, total: Number(res.headers.get('X-Total-Count')) || null };
      });
    });
  }

  function loadStatic(url) {
    return fetch(url, { credentials: 'same-origin', cache: 'no-cache' }).then(function (res) {
      if (!res.ok) return null;
      return res.json().catch(function () { return null; });
    }, function () { return null; });
  }

  function consoleApi(path, init) {
    var options = init || {};
    function attempt(token, retried) {
      var headers = Object.assign({ Authorization: 'Bearer ' + token, Accept: 'application/json' }, options.headers || {});
      return fetch(API_BASE + path, { method: options.method || 'GET', headers: headers, body: options.body, cache: 'no-store' }).then(function (res) {
        if (res.status === 401 && !retried) return refreshToken(token).then(function (t) { return attempt(t, true); });
        if (res.status === 401) throw new AuthRequired('Forgejo no longer accepts the console token.');
        return res;
      });
    }
    return accessToken().then(function (t) { return attempt(t, false); });
  }

  function repoEntryFrom(info) {
    return {
      name: info.name,
      repo: { id: info.id, full_name: info.name, owner: { id: info.owner_id, login: info.owner }, default_branch: info.default_branch },
      loaded: info.loaded,
      error: info.error,
      total: info.total,
      lastActivity: info.lastActivity,
      quiet: info.quiet,
    };
  }

  function withOptimisticStatus(run, previous) {
    var pending = state.optimistic.get(run.key);
    if (!pending) return run;
    if (Date.now() > pending.until || run.updated !== pending.baseUpdated) {
      state.optimistic.delete(run.key);
      return run;
    }
    var shown = Object.assign({}, run);
    applyOptimisticStatus(shown, pending.kind);
    shown.updated = previous ? previous.updated : shown.updated;
    return shown;
  }

  function applySnapshot(snapshot) {
    var repos = new Map();
    (snapshot.repos || []).forEach(function (info) { repos.set(info.name, repoEntryFrom(info)); });
    var runs = new Map();
    (snapshot.runs || []).forEach(function (run) {
      var previous = state.runs.get(run.key);
      var shown = withOptimisticStatus(run, previous);
      if (previous && previous.status !== shown.status) state.jobs.delete(run.key);
      runs.set(run.key, shown);
    });
    state.repos = repos;
    state.runs = runs;
    state.reposDiscovered = !!snapshot.reposDiscovered;
    state.runners = snapshot.runners || null;
    state.runnersNote = snapshot.runnersNote || '';
    state.queue = snapshot.queue === undefined ? null : snapshot.queue;
    state.lastSyncAt = snapshot.syncedAt || state.lastSyncAt;
    if (snapshot.authFailed) throw new AuthRequired('Forgejo no longer accepts the console token.');
  }

  function pollState() {
    state.polling = true;
    state.lastPollAt = Date.now();
    return consoleApi('/state' + (state.stateVersion ? '?have=' + state.stateVersion : '')).then(function (res) {
      var synced = Number(res.headers.get('X-Synced-At'));
      if (synced) state.lastSyncAt = synced;
      if (res.status === 304) return;
      if (!res.ok) throw new Error('The console API answered HTTP ' + res.status + '.');
      return res.json().then(function (snapshot) {
        applySnapshot(snapshot);
        state.stateVersion = snapshot.version;
      });
    }).then(function () {
      state.apiError = null;
    }, function (e) {
      if (e && e.authRequired) throw e;
      state.apiError = (e && e.message) || String(e);
    }).finally(function () {
      state.polling = false;
      scheduleRender();
    });
  }

  function jobsFor(run) {
    var cached = state.jobs.get(run.key);
    if (cached && cached.pending) return;
    if (cached && Date.now() - cached.at < (ACTIVE[run.status] ? JOBS_INTERVAL_MS : 600000)) return;
    state.jobs.set(run.key, { at: cached ? cached.at : 0, data: cached ? cached.data : null, pending: true });
    fetch(run.path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ logCursors: [] }),
    }).then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    }).then(function (data) {
      state.jobs.set(run.key, { at: Date.now(), data: data && data.state && data.state.run, pending: false });
    }, function (e) {
      state.jobs.set(run.key, { at: Date.now(), data: null, error: (e && e.message) || String(e), pending: false });
    }).then(scheduleRender);
  }

  function postAction(path) {
    return fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    }).then(function (res) {
      if (res.ok) return { ok: true };
      return res.text().then(function (text) {
        var message = 'HTTP ' + res.status;
        try {
          var data = JSON.parse(text);
          message = data.message || data.error || message;
        } catch (e) {
          if (res.status === 403) message = 'Forgejo refused it (no write access to Actions here).';
          if (res.status === 404) message = 'Forgejo no longer has this run.';
        }
        return { ok: false, message: message };
      });
    }, function (e) {
      return { ok: false, message: String((e && e.message) || e) };
    });
  }

  function actionFor(run) {
    if (ACTIVE[run.status]) return 'cancel';
    if (FINISHED[run.status]) return 'rerun';
    return null;
  }

  function wakeRepo(name, runId) {
    consoleApi('/wake', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ repo: name, runId: runId }) })
      .then(function () { state.lastPollAt = 0; }, function () { return null; });
  }

  function performRunActions(keys, kind) {
    var runs = keys.map(function (k) { return state.runs.get(k); }).filter(function (r) { return r && actionFor(r) === kind; });
    if (!runs.length) return Promise.resolve();
    runs.forEach(function (r) { state.busy.add(r.key); state.failures.delete(r.key); });
    scheduleRender();
    return inPool(runs, function (run) {
      return postAction(run.path + '/' + kind).then(function (result) {
        state.busy.delete(run.key);
        if (!result.ok) state.failures.set(run.key, result.message);
        else {
          state.selected.delete(run.key);
          state.jobs.delete(run.key);
          state.optimistic.set(run.key, { kind: kind, until: Date.now() + OPTIMISTIC_HOLD_MS, baseUpdated: run.updated });
          applyOptimisticStatus(run, kind);
          wakeRepo(run.repo, run.id);
        }
        return result;
      });
    }, 3).then(function (results) {
      var ok = results.filter(function (r) { return r && r.ok; }).length;
      var failed = runs.length - ok;
      var verb = kind === 'cancel' ? 'Stopped' : 'Re-running';
      if (failed) toast(verb + ' ' + ok + ' of ' + plural(runs.length, 'run') + '. ' + failed + ' refused: hover the red rows for why.', true);
      else toast(verb + ' ' + plural(ok, 'run') + '.');
      scheduleRender();
      tickSoon();
    });
  }

  function rerunJob(run, index) {
    var key = run.key + ':' + index;
    state.busy.add(key);
    scheduleRender();
    return postAction(run.path + '/jobs/' + index + '/rerun').then(function (result) {
      state.busy.delete(key);
      if (!result.ok) toast('Could not re-run that job: ' + result.message, true);
      else {
        toast('Re-running the job.');
        state.jobs.delete(run.key);
        wakeRepo(run.repo, run.id);
        tickSoon();
      }
      scheduleRender();
    });
  }

  function toast(message, isError) {
    if (!dom.toast) return;
    dom.toast.textContent = message;
    dom.toast.classList.toggle('wg-ci-toast-error', !!isError);
    dom.toast.classList.add('wg-ci-toast-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { dom.toast.classList.remove('wg-ci-toast-on'); }, TOAST_MS);
  }

  function allRuns() {
    var list = [];
    state.runs.forEach(function (run) { list.push(run); });
    return list;
  }

  function matchesQuery(run, q) {
    if (!q) return true;
    var hay = [run.title, run.repo, run.workflow, run.ref, run.actor, run.event, '#' + run.number, run.sha.slice(0, 10)].join(' ').toLowerCase();
    return q.toLowerCase().split(/\s+/).every(function (word) { return !word || hay.indexOf(word) !== -1; });
  }

  function filteredRuns() {
    var f = state.filters;
    var statusTest = (STATUS_FILTERS.filter(function (s) { return s.key === f.status; })[0] || STATUS_FILTERS[0]).test;
    var me = state.me && state.me.login;
    return allRuns().filter(function (run) {
      if (!statusTest(run)) return false;
      if (f.repo && run.repo !== f.repo) return false;
      if (f.event && run.event !== f.event) return false;
      if (f.mine && run.actor !== me) return false;
      if (f.trunk && !run.trunk) return false;
      return matchesQuery(run, f.q);
    });
  }

  function sortRuns(runs) {
    return runs.sort(function (a, b) {
      var aa = ACTIVE[a.status] ? 0 : 1;
      var bb = ACTIVE[b.status] ? 0 : 1;
      if (aa !== bb) return aa - bb;
      if (aa === 0 && a.status !== b.status) return STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
      return (b.created - a.created) || (b.id - a.id);
    });
  }

  function queuedSince(run) {
    return Math.max(run.created || 0, run.updated || 0);
  }

  function computeStats() {
    var now = Date.now();
    var cutoff = now - WINDOW_MS;
    var running = 0;
    var queued = 0;
    var oldestQueued = 0;
    var runningRepos = new Set();
    var failed = 0;
    var failedRepos = new Set();
    var succeeded = 0;
    var durations = [];
    var waits = [];
    state.runs.forEach(function (run) {
      if (run.status === 'running') { running++; runningRepos.add(run.repo); }
      if (QUEUED[run.status]) {
        queued++;
        var since = queuedSince(run);
        if (since && (!oldestQueued || since < oldestQueued)) oldestQueued = since;
      }
      if (run.created < cutoff) return;
      if (run.status === 'failure') { failed++; failedRepos.add(run.repo); }
      if (run.status === 'success') succeeded++;
      if ((run.status === 'success' || run.status === 'failure') && run.duration > 0) durations.push(run.duration);
      var wait = run.started && run.created ? run.started - run.created : -1;
      if (wait >= 0 && wait < MAX_QUEUE_SAMPLE_MS) waits.push(wait);
    });
    var loading = 0;
    var errored = 0;
    var total = 0;
    state.repos.forEach(function (entry) {
      total++;
      if (!entry.loaded) loading++;
      if (entry.error) errored++;
    });
    var runnersOnline = 0;
    var runnersBusy = 0;
    var runnersOffline = 0;
    (state.runners || []).forEach(function (r) {
      if (r.status === 'active') { runnersBusy++; runnersOnline++; } else if (r.status === 'idle') runnersOnline++;
      else runnersOffline++;
    });
    return {
      running: running, runningRepos: runningRepos.size, queued: queued, oldestQueued: oldestQueued,
      failed: failed, failedRepos: failedRepos.size, succeeded: succeeded,
      rate: succeeded + failed ? succeeded / (succeeded + failed) : null,
      p50: percentile(durations, 0.5), p95: percentile(durations, 0.95),
      wait50: percentile(waits, 0.5), wait95: percentile(waits, 0.95),
      loading: loading, errored: errored, repoCount: total,
      runnersOnline: runnersOnline, runnersBusy: runnersBusy, runnersOffline: runnersOffline,
      queueJobs: state.queue ? state.queue.length : null,
    };
  }

  function tile(key, label, value, sub, tone, filterAction) {
    var tag = filterAction ? 'button' : 'div';
    var attrs = filterAction ? ' type="button" data-wg-tile="' + esc(filterAction) + '"' : '';
    return '<' + tag + ' class="wg-ci-tile' + (tone ? ' wg-ci-tone-' + tone : '') + '"' + attrs + ' data-key="' + key + '">' +
      '<span class="wg-ci-tile-label">' + esc(label) + '</span>' +
      '<span class="wg-ci-tile-value">' + value + '</span>' +
      '<span class="wg-ci-tile-sub">' + sub + '</span></' + tag + '>';
  }

  function renderStats() {
    var s = computeStats();
    var queuedFor = s.oldestQueued ? Date.now() - s.oldestQueued : 0;
    var coverage = !state.reposDiscovered ? 'finding repositories' : s.loading ? 'reading ' + (s.repoCount - s.loading) + ' of ' + s.repoCount + ' repositories' : 'across ' + plural(s.repoCount, 'repository', 'repositories');
    var runnerValue = state.runners ? s.runnersBusy + '<span class="wg-ci-tile-of">/' + s.runnersOnline + '</span>' : '&ndash;';
    var runnerSub = state.runners
      ? (s.queueJobs ? plural(s.queueJobs, 'job') + ' waiting' : 'busy of online') + (s.runnersOffline ? ' &middot; ' + s.runnersOffline + ' offline' : '')
      : esc(state.runnersNote || 'loading');
    var html = [
      tile('running', 'Running', String(s.running), s.running ? 'in ' + plural(s.runningRepos, 'repository', 'repositories') : 'nothing building', s.running ? 'running' : '', 'status:active'),
      tile('queued', 'Queued', String(s.queued), s.queued ? 'oldest waiting <span data-wg-elapsed="' + s.oldestQueued + '"></span>' : 'no backlog', s.queued && queuedFor > 300000 ? 'warn' : '', 'status:active'),
      tile('failed', 'Failed · 24h', String(s.failed), s.failed ? 'in ' + plural(s.failedRepos, 'repository', 'repositories') : 'none', s.failed ? 'bad' : '', 'status:failure'),
      tile('rate', 'Success · 24h', s.rate === null ? '&ndash;' : Math.round(s.rate * 100) + '<span class="wg-ci-tile-of">%</span>', s.succeeded + s.failed ? 'of ' + plural(s.succeeded + s.failed, 'finished run') : 'no finished runs', s.rate !== null && s.rate < 0.8 ? 'warn' : '', ''),
      tile('duration', 'Run time · 24h', s.p50 === null ? '&ndash;' : formatDuration(s.p50), s.p95 === null ? 'median' : 'median &middot; p95 ' + formatDuration(s.p95), '', ''),
      tile('wait', 'Queue wait · 24h', s.wait50 === null ? '&ndash;' : formatDuration(s.wait50), s.wait95 === null ? 'median' : 'median &middot; p95 ' + formatDuration(s.wait95), s.wait95 !== null && s.wait95 > 300000 ? 'warn' : '', ''),
      tile('runners', 'Runners busy', runnerValue, runnerSub, s.queueJobs && s.runnersOnline && s.runnersBusy >= s.runnersOnline ? 'warn' : '', 'tab:runners'),
    ].join('');
    if (dom.stats._html !== html) { dom.stats.innerHTML = html; dom.stats._html = html; }
    var note = coverage + (s.errored ? ' &middot; <span class="wg-ci-bad-text">' + plural(s.errored, 'repository', 'repositories') + ' failing to load</span>' : '') +
      (state.apiError ? ' &middot; <span class="wg-ci-bad-text">' + esc(state.apiError) + '</span>' : '');
    if (dom.coverage._html !== note) { dom.coverage.innerHTML = note; dom.coverage._html = note; }
  }

  function statusIcon(status, size) {
    var name = PATHS[status] ? status : 'waiting';
    return '<span class="wg-ci-status wg-ci-s-' + esc(status) + '" title="' + esc(STATUS_LABEL[status] || status) + '">' + icon(name, size || 16) + '</span>';
  }

  function refChip(run) {
    if (!run.ref) return '';
    var isPull = /^#\d+$/.test(run.ref);
    var href = isPull ? '/' + run.repo + '/pulls/' + run.ref.slice(1) : '/' + run.repo + '/src/branch/' + encodeURI(run.ref);
    return '<a class="wg-ci-chip' + (run.trunk ? ' wg-ci-chip-trunk' : '') + '" href="' + esc(href) + '" title="' + esc(isPull ? 'Pull request ' + run.ref : 'Branch ' + run.ref) + '">' +
      icon(isPull ? 'pull' : 'branch', 12) + '<span>' + esc(run.ref) + '</span></a>';
  }

  function runTiming(run) {
    if (run.status === 'running' && run.started) {
      return '<span class="wg-ci-time-main" data-wg-elapsed="' + run.started + '"></span>';
    }
    var since = queuedSince(run);
    if (QUEUED[run.status] && since) {
      return '<span class="wg-ci-time-main wg-ci-muted" title="Waiting since ' + esc(formatStamp(since)) + '">queued <span data-wg-elapsed="' + since + '"></span></span>';
    }
    return '<span class="wg-ci-time-main">' + (run.duration > 0 ? formatDuration(run.duration) : '') + '</span>';
  }

  function noteShownAction(key, kind) {
    var shown = state.actionShown.get(key);
    if (!shown || shown.kind !== kind) state.actionShown.set(key, { kind: kind, at: shown ? Date.now() : 0 });
  }

  function actionJustFlipped(key) {
    var shown = state.actionShown.get(key);
    return !!shown && Date.now() - shown.at < ACTION_FLIP_GUARD_MS;
  }

  function applyOptimisticStatus(run, kind) {
    var now = Date.now();
    if (kind === 'cancel') {
      run.status = 'cancelled';
      run.stopped = now;
    } else {
      run.status = 'waiting';
      run.started = 0;
      run.stopped = 0;
      run.duration = 0;
    }
    run.updated = now;
  }

  function rowAction(run) {
    var kind = actionFor(run);
    noteShownAction(run.key, kind);
    if (!kind) return '';
    var busy = state.busy.has(run.key);
    var armed = state.confirm && state.confirm.key === run.key && state.confirm.until > Date.now();
    var label = kind === 'cancel' ? (armed ? 'Stop run?' : 'Stop') : 'Re-run';
    return '<button type="button" class="wg-ci-act wg-ci-act-' + kind + (armed ? ' wg-ci-armed' : '') + '" data-wg-act="' + kind + '" data-wg-key="' + esc(run.key) + '"' +
      (busy ? ' disabled aria-busy="true"' : '') + ' aria-label="' + esc(label + ' run #' + run.number + ' in ' + run.repo) + '">' +
      icon(kind === 'cancel' ? 'stop' : 'rerun', 14) + '<span>' + label + '</span></button>';
  }

  function runRowHtml(run) {
    var selected = state.selected.has(run.key);
    var expanded = state.expanded.has(run.key);
    var failure = state.failures.get(run.key);
    var repoShort = run.repo.split('/')[1] || run.repo;
    var owner = run.repo.split('/')[0];
    var eventName = EVENT_LABEL[run.event] || run.event;
    var html = '<div class="wg-ci-run wg-ci-r-' + esc(run.status) + (selected ? ' wg-ci-selected' : '') + (expanded ? ' wg-ci-expanded' : '') +
      (failure ? ' wg-ci-refused' : '') + (state.focusKey === run.key ? ' wg-ci-focus' : '') + '" data-wg-row="' + esc(run.key) + '">' +
      '<label class="wg-ci-pick" title="Select">' + '<input type="checkbox" class="wg-ci-check" data-wg-select="' + esc(run.key) + '"' + (selected ? ' checked' : '') +
      ' aria-label="' + esc('Select run #' + run.number + ' in ' + run.repo) + '">' + statusIcon(run.status) + '</label>' +
      '<button type="button" class="wg-ci-disclose" data-wg-expand="' + esc(run.key) + '" aria-expanded="' + expanded + '" aria-label="Show jobs">' + icon('chevron', 12) + '</button>' +
      '<div class="wg-ci-run-main">' +
      '<a class="wg-ci-run-title" href="' + esc(run.path) + '">' + esc(run.title) + '</a>' +
      '<div class="wg-ci-run-meta">' +
      '<a class="wg-ci-repo" href="/' + esc(run.repo) + '/actions" title="' + esc(run.repo) + '"><span class="wg-ci-owner">' + esc(owner) + '/</span>' + esc(repoShort) + '</a>' +
      '<a class="wg-ci-workflow" href="/' + esc(run.repo) + '/actions?workflow=' + encodeURIComponent(run.workflow) + '">' + esc(run.workflow) + '</a>' +
      '<span class="wg-ci-num">#' + esc(run.number) + '</span>' + refChip(run) +
      (eventName ? '<span class="wg-ci-event" title="' + esc('Triggered by ' + eventName) + '">' + icon(EVENT_ICON[run.event] || 'play', 12) + esc(eventName) + '</span>' : '') +
      (run.actor ? '<span class="wg-ci-actor">' + (run.actorAvatar ? '<img src="' + esc(run.actorAvatar) + '" alt="" width="14" height="14" loading="lazy">' : '') + esc(run.actor) + '</span>' : '') +
      '</div>' + (failure ? '<div class="wg-ci-row-error" role="alert">' + icon('alert', 12) + esc(failure) + '</div>' : '') + '</div>' +
      '<div class="wg-ci-run-time">' + runTiming(run) +
      '<span class="wg-ci-time-sub" title="' + esc('Created ' + formatStamp(run.created)) + '" data-wg-since="' + (run.created || 0) + '"></span></div>' +
      '<div class="wg-ci-run-tools">' + rowAction(run) +
      '<a class="wg-ci-act wg-ci-act-open" href="' + esc(run.path) + '" target="_blank" rel="noopener" aria-label="Open run in a new tab">' + icon('external', 14) + '</a></div>' +
      '</div>';
    if (expanded) html += jobsHtml(run);
    return html;
  }

  function jobsHtml(run) {
    var cached = state.jobs.get(run.key);
    var body;
    if (!cached || (!cached.data && !cached.error)) {
      body = '<div class="wg-ci-jobs-note">Loading jobs&hellip;</div>';
    } else if (!cached.data) {
      body = '<div class="wg-ci-jobs-note wg-ci-bad-text">Could not load the jobs: ' + esc(cached.error) + '</div>';
    } else {
      var jobs = cached.data.jobs || [];
      body = jobs.map(function (job, index) {
        var busy = state.busy.has(run.key + ':' + index);
        return '<div class="wg-ci-job wg-ci-r-' + esc(job.status) + '">' + statusIcon(job.status, 14) +
          '<a class="wg-ci-job-name" href="' + esc(run.path + '/jobs/' + index) + '">' + esc(job.name) + '</a>' +
          '<span class="wg-ci-job-time">' + esc(job.duration || '') + '</span>' +
          (job.canRerun && FINISHED[job.status] ? '<button type="button" class="wg-ci-act wg-ci-act-rerun wg-ci-act-small" data-wg-job="' + index + '" data-wg-key="' + esc(run.key) + '"' + (busy ? ' disabled aria-busy="true"' : '') +
            ' aria-label="' + esc('Re-run job ' + job.name) + '">' + icon('rerun', 12) + '<span>Re-run job</span></button>' : '<span></span>') +
          '</div>';
      }).join('') || '<div class="wg-ci-jobs-note">This run has no jobs.</div>';
      var commit = cached.data.commit || {};
      body += '<div class="wg-ci-jobs-foot">' +
        (run.sha ? '<a href="/' + esc(run.repo) + '/commit/' + esc(run.sha) + '">' + icon('commit', 12) + esc(commit.shortSHA || run.sha.slice(0, 10)) + '</a>' : '') +
        (run.started ? '<span>started ' + esc(formatStamp(run.started)) + '</span>' : '') +
        (run.stopped ? '<span>finished ' + esc(formatStamp(run.stopped)) + '</span>' : '') +
        '</div>';
    }
    return '<div class="wg-ci-jobs">' + body + '</div>';
  }

  function patchList(container, items) {
    var existing = new Map();
    Array.prototype.forEach.call(container.children, function (child) { existing.set(child.getAttribute('data-key'), child); });
    var cursor = container.firstElementChild;
    items.forEach(function (item) {
      var node = existing.get(item.key);
      if (node) existing.delete(item.key);
      else {
        node = document.createElement('div');
        node.setAttribute('data-key', item.key);
        node.className = item.className || '';
      }
      if (node._html !== item.html) {
        node.innerHTML = item.html;
        node._html = item.html;
      }
      if (node !== cursor) container.insertBefore(node, cursor);
      else cursor = cursor.nextElementSibling;
    });
    existing.forEach(function (node) { node.remove(); });
  }

  function renderRuns(filtered) {
    var runs = sortRuns(filtered);
    var todayStart = startOfDay(Date.now());
    var groups = runs.map(function (run) { return groupOf(run, todayStart); });
    var counts = new Map();
    groups.forEach(function (label) { counts.set(label, (counts.get(label) || 0) + 1); });
    var shown = runs.slice(0, state.runLimit);
    var items = [];
    var group = null;
    shown.forEach(function (run, i) {
      var label = groups[i];
      if (label !== group) {
        group = label;
        items.push({ key: 'g:' + label, className: 'wg-ci-group', html: '<span>' + esc(label) + '</span><span class="wg-ci-group-count">' + counts.get(label) + '</span>' });
      }
      items.push({ key: run.key, className: 'wg-ci-item', html: runRowHtml(run) });
      if (state.expanded.has(run.key)) jobsFor(run);
    });
    if (runs.length > shown.length) {
      items.push({ key: 'more', className: 'wg-ci-more', html: '<button type="button" class="wg-ci-act" data-wg-more>Show ' + Math.min(RUN_PAGE_SIZE, runs.length - shown.length) + ' more of ' + (runs.length - shown.length) + '</button>' });
    }
    if (!runs.length) {
      var loading = !state.reposDiscovered || Array.from(state.repos.values()).some(function (e) { return !e.loaded; });
      items.push({
        key: 'empty', className: 'wg-ci-empty',
        html: loading && !state.runs.size ? '<span class="wg-ci-spinner"></span>Reading runs from every repository&hellip;'
          : state.runs.size ? 'No run matches these filters. <button type="button" class="wg-ci-link" data-wg-clear-filters>Clear filters</button>'
            : 'No repository you can see has run CI yet.',
      });
    }
    patchList(dom.runList, items);
    dom.runCount.textContent = plural(runs.length, 'run');
    var visibleKeys = runs.map(function (r) { return r.key; });
    var selectedVisible = visibleKeys.filter(function (k) { return state.selected.has(k); }).length;
    dom.selectAll.checked = !!visibleKeys.length && selectedVisible === visibleKeys.length;
    dom.selectAll.indeterminate = selectedVisible > 0 && selectedVisible < visibleKeys.length;
    dom.selectAll.disabled = !visibleKeys.length;
    renderBulk();
    renderFilterOptions();
  }

  function renderBulk() {
    var selected = Array.from(state.selected).map(function (k) { return state.runs.get(k); }).filter(Boolean);
    var stoppable = selected.filter(function (r) { return actionFor(r) === 'cancel'; }).length;
    var rerunnable = selected.filter(function (r) { return actionFor(r) === 'rerun'; }).length;
    var armed = state.confirm && state.confirm.key === 'bulk' && state.confirm.until > Date.now();
    var html = selected.length ? '<span class="wg-ci-bulk-count">' + plural(selected.length, 'run') + ' selected</span>' +
      '<button type="button" class="wg-ci-act wg-ci-act-cancel' + (armed ? ' wg-ci-armed' : '') + '" data-wg-bulk="cancel"' + (stoppable ? '' : ' disabled') + '>' + icon('stop', 14) +
      '<span>' + (armed ? 'Stop ' + stoppable + '? Click again' : 'Stop ' + stoppable) + '</span></button>' +
      '<button type="button" class="wg-ci-act wg-ci-act-rerun" data-wg-bulk="rerun"' + (rerunnable ? '' : ' disabled') + '>' + icon('rerun', 14) + '<span>Re-run ' + rerunnable + '</span></button>' +
      '<button type="button" class="wg-ci-act" data-wg-bulk="clear" aria-label="Clear selection">' + icon('close', 14) + '</button>' : '';
    if (dom.bulk._html !== html) { dom.bulk.innerHTML = html; dom.bulk._html = html; }
    dom.bulk.classList.toggle('wg-ci-bulk-on', !!selected.length);
    dom.root.toggleAttribute('data-wg-selecting', !!selected.length);
  }

  function renderFilterOptions() {
    var repos = new Map();
    var events = new Map();
    state.runs.forEach(function (run) {
      repos.set(run.repo, (repos.get(run.repo) || 0) + 1);
      if (run.event) events.set(run.event, (events.get(run.event) || 0) + 1);
    });
    var repoHtml = '<option value="">All repositories</option>' + Array.from(repos.keys()).sort().map(function (name) {
      return '<option value="' + esc(name) + '"' + (state.filters.repo === name ? ' selected' : '') + '>' + esc(name) + '</option>';
    }).join('');
    if (state.filters.repo && !repos.has(state.filters.repo)) repoHtml += '<option value="' + esc(state.filters.repo) + '" selected>' + esc(state.filters.repo) + '</option>';
    if (dom.repoSelect._html !== repoHtml) { dom.repoSelect.innerHTML = repoHtml; dom.repoSelect._html = repoHtml; }
    var eventHtml = '<option value="">Any event</option>' + Array.from(events.keys()).sort().map(function (name) {
      return '<option value="' + esc(name) + '"' + (state.filters.event === name ? ' selected' : '') + '>' + esc(EVENT_LABEL[name] || name) + '</option>';
    }).join('');
    if (dom.eventSelect._html !== eventHtml) { dom.eventSelect.innerHTML = eventHtml; dom.eventSelect._html = eventHtml; }
    Array.prototype.forEach.call(dom.statusSeg.querySelectorAll('button'), function (b) {
      var on = b.getAttribute('data-wg-status') === state.filters.status;
      b.classList.toggle('wg-ci-on', on);
      b.setAttribute('aria-pressed', String(on));
    });
    dom.mine.setAttribute('aria-pressed', String(state.filters.mine));
    dom.mine.classList.toggle('wg-ci-on', state.filters.mine);
    dom.trunk.setAttribute('aria-pressed', String(state.filters.trunk));
    dom.trunk.classList.toggle('wg-ci-on', state.filters.trunk);
  }

  function repoSummaries() {
    var byRepo = new Map();
    state.repos.forEach(function (entry) { byRepo.set(entry.name, { entry: entry, runs: [] }); });
    state.runs.forEach(function (run) { if (byRepo.has(run.repo)) byRepo.get(run.repo).runs.push(run); });
    var cutoff = Date.now() - WINDOW_MS;
    var out = [];
    byRepo.forEach(function (item) {
      var runs = item.runs.sort(function (a, b) { return b.created - a.created || b.number - a.number; });
      var trunk = runs.filter(function (r) { return r.trunk && FINISHED[r.status] && r.status !== 'skipped'; });
      var lastTrunk = trunk.filter(function (r) { return r.status !== 'cancelled'; })[0] || null;
      var streak = 0;
      for (var i = 0; i < trunk.length; i++) {
        if (trunk[i].status === 'cancelled') continue;
        if (trunk[i].status === 'failure') streak++;
        else break;
      }
      var recent = runs.filter(function (r) { return r.created >= cutoff; });
      var ok = recent.filter(function (r) { return r.status === 'success'; }).length;
      var bad = recent.filter(function (r) { return r.status === 'failure'; }).length;
      var durations = recent.filter(function (r) { return r.duration > 0 && (r.status === 'success' || r.status === 'failure'); }).map(function (r) { return r.duration; });
      out.push({
        entry: item.entry, runs: runs, lastTrunk: lastTrunk, streak: streak,
        active: runs.filter(function (r) { return ACTIVE[r.status]; }).length,
        rate: ok + bad ? ok / (ok + bad) : null, finished: ok + bad, median: percentile(durations, 0.5),
        last: runs[0] ? runs[0].created : 0,
      });
    });
    out.sort(function (a, b) {
      var ar = a.lastTrunk && a.lastTrunk.status === 'failure' ? 0 : 1;
      var br = b.lastTrunk && b.lastTrunk.status === 'failure' ? 0 : 1;
      if (ar !== br) return ar - br;
      if (!!a.active !== !!b.active) return a.active ? -1 : 1;
      return b.last - a.last;
    });
    return out;
  }

  function strip(runs) {
    var cells = runs.slice(0, STRIP_LENGTH).reverse().map(function (run) {
      return '<a class="wg-ci-cell wg-ci-c-' + esc(run.status) + '" href="' + esc(run.path) + '" title="' + esc('#' + run.number + ' ' + (STATUS_LABEL[run.status] || run.status) + ' · ' + run.workflow + ' · ' + run.ref + ' · ' + formatStamp(run.created)) + '"></a>';
    });
    while (cells.length < STRIP_LENGTH) cells.unshift('<span class="wg-ci-cell wg-ci-c-none"></span>');
    return '<span class="wg-ci-strip">' + cells.join('') + '</span>';
  }

  function renderRepos() {
    var rows = repoSummaries();
    var busy = rows.filter(function (r) { return r.runs.length || !r.entry.loaded || r.entry.error; });
    var quiet = rows.length - busy.length;
    var items = busy.map(function (r) {
      var trunkCell = r.lastTrunk
        ? statusIcon(r.lastTrunk.status, 14) + '<span>' + esc(r.lastTrunk.ref) + '</span>' + (r.streak > 1 ? '<span class="wg-ci-streak" title="Failed runs in a row on the default branch">' + r.streak + '&times;</span>' : '')
        : '<span class="wg-ci-muted">no trunk run loaded</span>';
      var html = '<a class="wg-ci-repo-name" href="/' + esc(r.entry.name) + '/actions"><span class="wg-ci-owner">' + esc(r.entry.name.split('/')[0]) + '/</span>' + esc(r.entry.name.split('/')[1]) + '</a>' +
        '<span class="wg-ci-repo-trunk">' + trunkCell + '</span>' +
        '<span class="wg-ci-repo-strip">' + (r.entry.error ? '<span class="wg-ci-bad-text" title="' + esc(r.entry.error) + '">' + icon('alert', 12) + ' not loading</span>' : !r.entry.loaded ? '<span class="wg-ci-muted">loading&hellip;</span>' : strip(r.runs)) + '</span>' +
        '<span class="wg-ci-num-cell' + (r.rate !== null && r.rate < 0.8 ? ' wg-ci-warn-text' : '') + '" title="' + esc(r.finished + ' finished in 24 hours') + '">' + (r.rate === null ? '&ndash;' : Math.round(r.rate * 100) + '%') + '</span>' +
        '<span class="wg-ci-num-cell">' + (r.median === null ? '&ndash;' : formatDuration(r.median)) + '</span>' +
        '<span class="wg-ci-num-cell">' + (r.active ? '<button type="button" class="wg-ci-link" data-wg-repo-active="' + esc(r.entry.name) + '">' + r.active + ' active</button>' : '') + '</span>' +
        '<span class="wg-ci-num-cell wg-ci-muted" data-wg-since="' + r.last + '"></span>' +
        '<button type="button" class="wg-ci-act wg-ci-act-filter" data-wg-repo-filter="' + esc(r.entry.name) + '" aria-label="' + esc('Show runs of ' + r.entry.name) + '">Runs' + icon('chevron', 12) + '</button>';
      return { key: 'r:' + r.entry.name, className: 'wg-ci-repo-row' + (r.lastTrunk && r.lastTrunk.status === 'failure' ? ' wg-ci-repo-red' : ''), html: html };
    });
    if (quiet) items.push({ key: 'quiet', className: 'wg-ci-quiet', html: plural(quiet, 'repository', 'repositories') + ' with Actions enabled had no run in the loaded window.' });
    if (!rows.length) items.push({ key: 'empty', className: 'wg-ci-empty', html: '<span class="wg-ci-spinner"></span>Finding repositories&hellip;' });
    patchList(dom.repoList, items);
  }

  function runnerScope(r) {
    if (r.repo_id) {
      var repo = Array.from(state.repos.values()).filter(function (e) { return e.repo.id === r.repo_id; })[0];
      return repo ? repo.name : 'repository ' + r.repo_id;
    }
    if (r.owner_id) {
      var owner = Array.from(state.repos.values()).filter(function (e) { return e.repo.owner && e.repo.owner.id === r.owner_id; })[0];
      return owner ? owner.repo.owner.login : 'owner ' + r.owner_id;
    }
    return 'instance';
  }

  function renderRunners() {
    var items = [];
    if (state.queue !== null) {
      var byLabel = new Map();
      state.queue.forEach(function (job) {
        var label = (job.runs_on || []).join(', ') || 'any';
        byLabel.set(label, (byLabel.get(label) || 0) + 1);
      });
      var queueHtml = '<div class="wg-ci-section-title">Waiting for a runner <span class="wg-ci-group-count">' + state.queue.length + '</span></div>' +
        (state.queue.length ? '<div class="wg-ci-queue">' + Array.from(byLabel.entries()).map(function (pair) {
          return '<span class="wg-ci-queue-chip"><strong>' + pair[1] + '</strong> on <code>' + esc(pair[0]) + '</code></span>';
        }).join('') + '</div>' : '<div class="wg-ci-muted wg-ci-pad">No job is waiting for a runner.</div>');
      items.push({ key: 'queue', className: 'wg-ci-queue-block', html: queueHtml });
    }
    if (!state.runners) {
      items.push({ key: 'empty', className: 'wg-ci-empty', html: state.runnersNote ? esc(state.runnersNote) : '<span class="wg-ci-spinner"></span>Reading runners&hellip;' });
      patchList(dom.runnerList, items);
      return;
    }
    var order = { active: 0, idle: 1, offline: 2 };
    var runners = state.runners.slice().sort(function (a, b) {
      return (order[a.status] - order[b.status]) || String(a.name).localeCompare(String(b.name));
    });
    items.push({ key: 'head', className: 'wg-ci-runner-head', html: '<span>Runner</span><span>Status</span><span>Labels</span><span>Scope</span><span>Version</span>' });
    runners.forEach(function (r) {
      var html = '<span class="wg-ci-runner-name"><span class="wg-ci-dot wg-ci-dot-' + esc(r.status) + '"></span>' + esc(r.name) +
        (r.ephemeral ? '<span class="wg-ci-tag">ephemeral</span>' : '') + '</span>' +
        '<span class="wg-ci-runner-status">' + esc(r.status === 'active' ? 'busy' : r.status) + '</span>' +
        '<span class="wg-ci-labels">' + (r.labels || []).map(function (l) { return '<code>' + esc(String(l).split(':')[0]) + '</code>'; }).join('') + '</span>' +
        '<span class="wg-ci-muted">' + esc(runnerScope(r)) + '</span>' +
        '<span class="wg-ci-muted">' + esc(r.version || '') + '</span>';
      items.push({ key: 'n:' + r.id, className: 'wg-ci-runner-row', html: html });
    });
    if (!runners.length) items.push({ key: 'none', className: 'wg-ci-empty', html: 'No runner is registered where this account can see it.' });
    patchList(dom.runnerList, items);
  }

  function grafanaBase() {
    var host = location.hostname;
    if (!/^forgejo\./.test(host)) return null;
    return location.protocol + '//' + host.replace(/^forgejo\./, 'grafana.') + (location.port ? ':' + location.port : '');
  }

  function prefersDark() {
    var theme = state.theme || 'forgejo-auto';
    if (/dark/.test(theme)) return true;
    if (/light/.test(theme)) return false;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function insightUrl(panelId, solo) {
    var base = grafanaBase();
    var range = INSIGHT_RANGES.filter(function (r) { return r.key === state.insightRange; })[0] || INSIGHT_RANGES[1];
    var dash = (state.panels && state.panels.dashboard) || 'forgejo-ci-console';
    return base + (solo ? '/d-solo/' : '/d/') + encodeURIComponent(dash) + '/console' + query({
      orgId: 1, from: range.from, to: 'now', panelId: solo ? panelId : undefined, viewPanel: solo ? undefined : 'panel-' + panelId,
      theme: prefersDark() ? 'dark' : 'light', refresh: '1m', 'var-repo': '$__all',
    });
  }

  function renderInsights() {
    var base = grafanaBase();
    if (!base) {
      dom.insights.innerHTML = '<div class="wg-ci-empty">Insights embed Grafana next to this Forgejo, and this host is not named forgejo.&lt;domain&gt;.</div>';
      return;
    }
    if (!state.panels) {
      dom.insights.innerHTML = '<div class="wg-ci-empty"><span class="wg-ci-spinner"></span>Loading panel list&hellip;</div>';
      return;
    }
    var ranges = INSIGHT_RANGES.map(function (r) {
      return '<button type="button" data-wg-range="' + r.key + '" class="' + (r.key === state.insightRange ? 'wg-ci-on' : '') + '" aria-pressed="' + (r.key === state.insightRange) + '">' + esc(r.label) + '</button>';
    }).join('');
    var key = state.insightRange + '|' + prefersDark();
    if (dom.insights._key === key) return;
    dom.insights._key = key;
    dom.insights.innerHTML = '<div class="wg-ci-insights-bar"><div class="wg-ci-seg" role="group" aria-label="Time range">' + ranges + '</div>' +
      '<span class="wg-ci-muted">Panels from Grafana. Blank? <a href="' + esc(base) + '/d/forgejo-ci" target="_blank" rel="noopener">Sign in to Grafana</a> once, then reload.</span>' +
      '<a class="wg-ci-act" href="' + esc(base) + '/d/forgejo-ci" target="_blank" rel="noopener">Full CI board' + icon('external', 12) + '</a></div>' +
      '<div class="wg-ci-insight-grid">' + state.panels.panels.map(function (p) {
        return '<figure class="wg-ci-insight' + (p.wide ? ' wg-ci-wide' : '') + '"><iframe title="' + esc(p.title) + '" src="' + esc(insightUrl(p.id, true)) + '" loading="lazy" referrerpolicy="no-referrer"></iframe>' +
          '<a class="wg-ci-insight-open" href="' + esc(insightUrl(p.id, false)) + '" target="_blank" rel="noopener" aria-label="' + esc('Open ' + p.title + ' in Grafana') + '">' + icon('external', 12) + '</a></figure>';
      }).join('') + '</div>';
  }

  function renderTabs(filtered) {
    var counts = {
      runs: filtered.length,
      repos: state.repos.size,
      runners: state.runners ? state.runners.filter(function (r) { return r.status !== 'offline'; }).length : null,
    };
    Array.prototype.forEach.call(dom.tabs.querySelectorAll('[data-wg-tab]'), function (b) {
      var key = b.getAttribute('data-wg-tab');
      var on = key === state.tab;
      b.classList.toggle('wg-ci-on', on);
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
      var badge = b.querySelector('.wg-ci-tab-count');
      if (badge) badge.textContent = counts[key] === null || counts[key] === undefined ? '' : counts[key];
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-wg-panel]'), function (p) {
      p.hidden = p.getAttribute('data-wg-panel') !== state.tab;
    });
  }

  function renderLive() {
    var now = Date.now();
    var errored = Array.from(state.repos.values()).some(function (e) { return e.error; });
    var mode = state.paused ? 'paused' : document.hidden ? 'idle' : errored || state.apiError ? 'warn' : state.lastSyncAt ? 'live' : 'idle';
    dom.live.setAttribute('data-wg-mode', mode);
    var age = state.lastSyncAt ? Math.round((now - state.lastSyncAt) / 1000) : null;
    var text = state.paused ? 'Paused' : age === null ? 'Connecting' : 'Live · ' + (age < 2 ? 'now' : age < 90 ? age + 's ago' : formatAgo(state.lastSyncAt));
    if (dom.liveText.textContent !== text) dom.liveText.textContent = text;
    dom.pause.innerHTML = icon(state.paused ? 'play' : 'pause', 14);
    dom.pause.setAttribute('aria-label', state.paused ? 'Resume live updates' : 'Pause live updates');
    dom.pause.title = state.paused ? 'Resume live updates' : 'Pause live updates';
  }

  function render() {
    renderQueued = false;
    if (!state.started) return;
    state.lastRenderAt = Date.now();
    var filtered = filteredRuns();
    renderStats();
    renderTabs(filtered);
    if (state.tab === 'runs') renderRuns(filtered);
    if (state.tab === 'repos') renderRepos();
    if (state.tab === 'runners') renderRunners();
    if (state.tab === 'insights') renderInsights();
    renderLive();
    tickClocks();
  }

  function scheduleRender() {
    if (renderQueued) return;
    renderQueued = true;
    setTimeout(render, Math.max(30, MIN_RENDER_GAP_MS - (Date.now() - state.lastRenderAt)));
  }

  function tickClocks() {
    var now = Date.now();
    Array.prototype.forEach.call(document.querySelectorAll('[data-wg-elapsed]'), function (el) {
      var t = Number(el.getAttribute('data-wg-elapsed'));
      var text = t ? formatDuration(now - t) : '';
      if (el.textContent !== text) el.textContent = text;
    });
    Array.prototype.forEach.call(document.querySelectorAll('[data-wg-since]'), function (el) {
      var t = Number(el.getAttribute('data-wg-since'));
      var text = formatAgo(t, now);
      if (el.textContent !== text) el.textContent = text;
    });
  }

  var tickTimer = null;
  var ticking = false;

  function tickSoon() {
    clearTimeout(tickTimer);
    tickTimer = setTimeout(tick, 300);
  }

  function stillLoading() {
    return !state.reposDiscovered || Array.from(state.repos.values()).some(function (e) { return !e.loaded; });
  }

  function pollInterval() {
    return stillLoading() ? STATE_POLL_LOADING_MS : STATE_POLL_MS;
  }

  function tick() {
    clearTimeout(tickTimer);
    tickTimer = setTimeout(tick, stillLoading() ? STATE_POLL_LOADING_MS : TICK_MS);
    if (state.confirm && state.confirm.until <= Date.now()) { state.confirm = null; scheduleRender(); }
    renderLive();
    tickClocks();
    if (state.paused || document.hidden || state.authFailed) return;
    state.expanded.forEach(function (key) {
      var run = state.runs.get(key);
      if (run && ACTIVE[run.status]) jobsFor(run);
    });
    if (state.polling || Date.now() - state.lastPollAt < pollInterval()) return;
    pollState().catch(function (e) {
      if (e && e.authRequired) showGate('expired', e.message);
    });
  }

  function savePrefs() {
    writeJson(localStorage, PREFS_KEY, { insightRange: state.insightRange });
    var params = new URLSearchParams();
    if (state.tab !== 'runs') params.set('tab', state.tab);
    var f = state.filters;
    if (f.status !== 'all') params.set('status', f.status);
    if (f.repo) params.set('repo', f.repo);
    if (f.event) params.set('event', f.event);
    if (f.mine) params.set('mine', '1');
    if (f.trunk) params.set('trunk', '1');
    if (f.q) params.set('q', f.q);
    var search = params.toString();
    history.replaceState(null, '', CONSOLE_PATH + (search ? '?' + search : ''));
  }

  function loadPrefs() {
    var prefs = readJson(localStorage, PREFS_KEY) || {};
    if (prefs.insightRange) state.insightRange = prefs.insightRange;
    var params = new URLSearchParams(location.search);
    var tab = params.get('tab');
    if (TABS.some(function (t) { return t.key === tab; })) state.tab = tab;
    var status = params.get('status');
    if (STATUS_FILTERS.some(function (s) { return s.key === status; })) state.filters.status = status;
    state.filters.repo = params.get('repo') || '';
    state.filters.event = params.get('event') || '';
    state.filters.mine = params.get('mine') === '1';
    state.filters.trunk = params.get('trunk') === '1';
    state.filters.q = params.get('q') || '';
  }

  function setFilter(name, value) {
    state.filters[name] = value;
    state.focusKey = null;
    state.runLimit = RUN_PAGE_SIZE;
    savePrefs();
    scheduleRender();
  }

  function setTab(tab) {
    state.tab = tab;
    savePrefs();
    scheduleRender();
  }

  function visibleRunKeys() {
    return sortRuns(filteredRuns()).map(function (r) { return r.key; });
  }

  function handleRunAction(button) {
    var kind = button.getAttribute('data-wg-act');
    var key = button.getAttribute('data-wg-key');
    var confirmPending = state.confirm && state.confirm.key === key && state.confirm.until > Date.now();
    if (actionJustFlipped(key) || (confirmPending && kind !== 'cancel')) {
      state.confirm = null;
      toast('That run changed state as you clicked. Check it and click again.', true);
      scheduleRender();
      return;
    }
    if (kind === 'cancel') {
      var armed = state.confirm && state.confirm.key === key && state.confirm.until > Date.now();
      if (!armed) {
        state.confirm = { key: key, until: Date.now() + CONFIRM_MS, armedAt: Date.now() };
        scheduleRender();
        return;
      }
      if (Date.now() - state.confirm.armedAt < CONFIRM_ARM_GUARD_MS) return;
      state.confirm = null;
    }
    performRunActions([key], kind);
  }

  function handleBulk(kind) {
    if (kind === 'clear') { state.selected.clear(); scheduleRender(); return; }
    var keys = Array.from(state.selected);
    if (kind === 'cancel') {
      var armed = state.confirm && state.confirm.key === 'bulk' && state.confirm.until > Date.now();
      if (!armed) {
        state.confirm = { key: 'bulk', until: Date.now() + CONFIRM_MS, armedAt: Date.now() };
        scheduleRender();
        return;
      }
      if (Date.now() - state.confirm.armedAt < CONFIRM_ARM_GUARD_MS) return;
      state.confirm = null;
    }
    performRunActions(keys, kind);
  }

  function toggleExpand(key) {
    if (state.expanded.has(key)) state.expanded.delete(key);
    else {
      state.expanded.add(key);
      var run = state.runs.get(key);
      if (run) jobsFor(run);
    }
    scheduleRender();
  }

  function onClick(event) {
    var target = event.target;
    var el;
    if ((el = target.closest('[data-wg-tab]'))) { setTab(el.getAttribute('data-wg-tab')); return; }
    if ((el = target.closest('[data-wg-act]'))) { handleRunAction(el); return; }
    if ((el = target.closest('[data-wg-bulk]'))) { handleBulk(el.getAttribute('data-wg-bulk')); return; }
    if ((el = target.closest('[data-wg-job]'))) {
      var run = state.runs.get(el.getAttribute('data-wg-key'));
      if (run) rerunJob(run, Number(el.getAttribute('data-wg-job')));
      return;
    }
    if ((el = target.closest('[data-wg-expand]'))) { toggleExpand(el.getAttribute('data-wg-expand')); return; }
    if ((el = target.closest('[data-wg-status]'))) { setFilter('status', el.getAttribute('data-wg-status')); return; }
    if ((el = target.closest('[data-wg-range]'))) {
      state.insightRange = el.getAttribute('data-wg-range');
      savePrefs();
      scheduleRender();
      return;
    }
    if ((el = target.closest('[data-wg-tile]'))) {
      var action = el.getAttribute('data-wg-tile').split(':');
      if (action[0] === 'tab') setTab(action[1]);
      else { state.tab = 'runs'; setFilter(action[0], action[1]); }
      return;
    }
    if ((el = target.closest('[data-wg-repo-filter]'))) {
      state.tab = 'runs';
      state.filters.status = 'all';
      setFilter('repo', el.getAttribute('data-wg-repo-filter'));
      return;
    }
    if ((el = target.closest('[data-wg-repo-active]'))) {
      state.tab = 'runs';
      state.filters.status = 'active';
      setFilter('repo', el.getAttribute('data-wg-repo-active'));
      return;
    }
    if (target.closest('[data-wg-clear-filters]')) {
      state.filters = { q: '', status: 'all', repo: '', event: '', mine: false, trunk: false };
      dom.search.value = '';
      savePrefs();
      scheduleRender();
      return;
    }
    if (target.closest('[data-wg-signin]')) { startSignIn(); return; }
    if (target.closest('[data-wg-more]')) { state.runLimit += RUN_PAGE_SIZE; scheduleRender(); return; }
    if (target.closest('[data-wg-pause]')) {
      state.paused = !state.paused;
      if (!state.paused) tickSoon();
      renderLive();
      return;
    }
    if (target.closest('[data-wg-mine]')) { setFilter('mine', !state.filters.mine); return; }
    if (target.closest('[data-wg-trunk]')) { setFilter('trunk', !state.filters.trunk); return; }
    var row = target.closest('.wg-ci-run');
    if (row && !target.closest('a, button, input, label')) {
      state.focusKey = row.getAttribute('data-wg-row');
      toggleExpand(state.focusKey);
    }
  }

  function onChange(event) {
    var target = event.target;
    if (target.matches('[data-wg-select]')) {
      var key = target.getAttribute('data-wg-select');
      if (event.shiftKey && state.lastToggled) selectRange(state.lastToggled, key, target.checked);
      else if (target.checked) state.selected.add(key);
      else state.selected.delete(key);
      state.lastToggled = key;
      scheduleRender();
    } else if (target === dom.selectAll) {
      var keys = visibleRunKeys();
      if (target.checked) keys.forEach(function (k) { state.selected.add(k); });
      else keys.forEach(function (k) { state.selected.delete(k); });
      scheduleRender();
    } else if (target === dom.repoSelect) setFilter('repo', target.value);
    else if (target === dom.eventSelect) setFilter('event', target.value);
  }

  function selectRange(fromKey, toKey, on) {
    var keys = visibleRunKeys();
    var a = keys.indexOf(fromKey);
    var b = keys.indexOf(toKey);
    if (a === -1 || b === -1) { if (on) state.selected.add(toKey); else state.selected.delete(toKey); return; }
    keys.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (k) { if (on) state.selected.add(k); else state.selected.delete(k); });
  }

  function moveFocus(delta) {
    var keys = visibleRunKeys();
    if (!keys.length) return;
    var i = keys.indexOf(state.focusKey);
    i = i === -1 ? (delta > 0 ? 0 : keys.length - 1) : Math.max(0, Math.min(keys.length - 1, i + delta));
    state.focusKey = keys[i];
    if (i >= state.runLimit) state.runLimit = i + RUN_PAGE_SIZE;
    render();
    var node = dom.runList.querySelector('[data-wg-row="' + CSS.escape(state.focusKey) + '"]');
    if (node) node.scrollIntoView({ block: 'nearest' });
  }

  function onKey(event) {
    var typing = event.target.matches('input[type="search"], input[type="text"], select, textarea');
    if (event.key === '/' && !typing) { event.preventDefault(); setTab('runs'); dom.search.focus(); dom.search.select(); return; }
    if (event.key === 'Escape') {
      if (typing) { event.target.blur(); return; }
      if (state.confirm) { state.confirm = null; scheduleRender(); return; }
      if (state.selected.size) { state.selected.clear(); scheduleRender(); return; }
      state.focusKey = null;
      scheduleRender();
      return;
    }
    if (typing || event.metaKey || event.ctrlKey || event.altKey || state.tab !== 'runs') return;
    var run = state.focusKey && state.runs.get(state.focusKey);
    if (event.key === 'j' || event.key === 'ArrowDown') { event.preventDefault(); moveFocus(1); }
    else if (event.key === 'k' || event.key === 'ArrowUp') { event.preventDefault(); moveFocus(-1); }
    else if (event.key === 'x' && run) {
      if (state.selected.has(run.key)) state.selected.delete(run.key); else state.selected.add(run.key);
      state.lastToggled = run.key;
      scheduleRender();
    } else if (event.key === 'Enter' && run) toggleExpand(run.key);
    else if (event.key === 'o' && run) window.open(run.path, '_blank', 'noopener');
  }

  function applyTheme(theme) {
    var name = /^[a-z0-9-]+$/.test(theme || '') ? theme : 'forgejo-auto';
    state.theme = name;
    writeJson(localStorage, THEME_KEY, name);
    var link = document.getElementById('wg-ci-theme');
    var href = '/assets/css/theme-' + name + '.css';
    if (link && link.getAttribute('href') !== href) link.setAttribute('href', href);
    document.documentElement.setAttribute('data-theme', name);
  }

  function shellHtml() {
    var tabs = TABS.map(function (t) {
      return '<button type="button" role="tab" class="wg-ci-tab" data-wg-tab="' + t.key + '" aria-controls="wg-ci-panel-' + t.key + '">' + esc(t.label) + '<span class="wg-ci-tab-count"></span></button>';
    }).join('');
    var statuses = STATUS_FILTERS.map(function (s) {
      return '<button type="button" data-wg-status="' + s.key + '" aria-pressed="false">' + esc(s.label) + '</button>';
    }).join('');
    return '<header class="wg-ci-top">' +
      '<a class="wg-ci-brand" href="/" aria-label="Forgejo home"><img src="/assets/img/logo.svg" width="26" height="26" alt=""></a>' +
      '<nav class="wg-ci-crumbs" aria-label="Breadcrumb"><a href="/">Forgejo</a><span aria-hidden="true">/</span><h1>CI</h1></nav>' +
      '<div class="wg-ci-top-right">' +
      '<span class="wg-ci-live" data-wg-mode="idle"><span class="wg-ci-live-dot"></span><span class="wg-ci-live-text">Connecting</span></span>' +
      '<button type="button" class="wg-ci-icon-btn" data-wg-pause></button>' +
      '<a class="wg-ci-me" href="/" hidden></a></div></header>' +
      '<main class="wg-ci-main">' +
      '<div class="wg-ci-gate" hidden></div>' +
      '<div class="wg-ci-body">' +
      '<section class="wg-ci-stats" aria-label="CI right now"></section>' +
      '<p class="wg-ci-coverage"></p>' +
      '<div class="wg-ci-tabs" role="tablist" aria-label="Views">' + tabs + '</div>' +
      '<section id="wg-ci-panel-runs" data-wg-panel="runs" role="tabpanel" class="wg-ci-card">' +
      '<div class="wg-ci-filters">' +
      '<label class="wg-ci-check-all" title="Select every run shown"><input type="checkbox" class="wg-ci-check" data-wg-select-all aria-label="Select every run shown"></label>' +
      '<div class="wg-ci-search">' + icon('search', 14) + '<input type="search" placeholder="Filter by title, repo, branch, #run" aria-label="Filter runs" autocomplete="off" spellcheck="false"><kbd>/</kbd></div>' +
      '<div class="wg-ci-seg" role="group" aria-label="Status">' + statuses + '</div>' +
      '<select class="wg-ci-select" data-wg-repo-select aria-label="Repository"></select>' +
      '<select class="wg-ci-select" data-wg-event-select aria-label="Event"></select>' +
      '<button type="button" class="wg-ci-toggle" data-wg-trunk aria-pressed="false" title="Only default-branch runs">' + icon('branch', 12) + 'Trunk</button>' +
      '<button type="button" class="wg-ci-toggle" data-wg-mine aria-pressed="false" title="Only runs you triggered">Mine</button>' +
      '<span class="wg-ci-run-count"></span></div>' +
      '<div class="wg-ci-run-list" role="list"></div>' +
      '<p class="wg-ci-keys"><kbd>j</kbd><kbd>k</kbd> move <kbd>x</kbd> select <kbd>Enter</kbd> jobs <kbd>o</kbd> open <kbd>Shift</kbd>+click range <kbd>Esc</kbd> clear</p>' +
      '</section>' +
      '<section id="wg-ci-panel-repos" data-wg-panel="repos" role="tabpanel" class="wg-ci-card" hidden>' +
      '<div class="wg-ci-repo-head"><span>Repository</span><span>Default branch</span><span>Last ' + STRIP_LENGTH + ' runs</span><span>Success · 24h</span><span>Median · 24h</span><span>Active</span><span>Last run</span><span></span></div>' +
      '<div class="wg-ci-repo-list"></div></section>' +
      '<section id="wg-ci-panel-runners" data-wg-panel="runners" role="tabpanel" class="wg-ci-card" hidden><div class="wg-ci-runner-list"></div></section>' +
      '<section id="wg-ci-panel-insights" data-wg-panel="insights" role="tabpanel" hidden><div class="wg-ci-insights"></div></section>' +
      '</div></main>' +
      '<div class="wg-ci-bulk" role="region" aria-label="Selected runs"></div>' +
      '<div class="wg-ci-toast" role="status" aria-live="polite"></div>';
  }

  function mountShell(root) {
    root.innerHTML = shellHtml();
    dom.root = root;
    dom.gate = root.querySelector('.wg-ci-gate');
    dom.body = root.querySelector('.wg-ci-body');
    dom.stats = root.querySelector('.wg-ci-stats');
    dom.coverage = root.querySelector('.wg-ci-coverage');
    dom.tabs = root.querySelector('.wg-ci-tabs');
    dom.runList = root.querySelector('.wg-ci-run-list');
    dom.repoList = root.querySelector('.wg-ci-repo-list');
    dom.runnerList = root.querySelector('.wg-ci-runner-list');
    dom.insights = root.querySelector('.wg-ci-insights');
    dom.search = root.querySelector('.wg-ci-search input');
    dom.statusSeg = root.querySelector('.wg-ci-filters .wg-ci-seg');
    dom.repoSelect = root.querySelector('[data-wg-repo-select]');
    dom.eventSelect = root.querySelector('[data-wg-event-select]');
    dom.selectAll = root.querySelector('[data-wg-select-all]');
    dom.mine = root.querySelector('[data-wg-mine]');
    dom.trunk = root.querySelector('[data-wg-trunk]');
    dom.runCount = root.querySelector('.wg-ci-run-count');
    dom.bulk = root.querySelector('.wg-ci-bulk');
    dom.toast = root.querySelector('.wg-ci-toast');
    dom.live = root.querySelector('.wg-ci-live');
    dom.liveText = root.querySelector('.wg-ci-live-text');
    dom.pause = root.querySelector('[data-wg-pause]');
    dom.me = root.querySelector('.wg-ci-me');
    dom.search.value = state.filters.q;
    dom.search.addEventListener('input', function () { setFilter('q', dom.search.value.trim()); });
    root.addEventListener('click', onClick);
    root.addEventListener('change', onChange);
    document.addEventListener('keydown', onKey);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) tickSoon(); renderLive(); });
    renderLive();
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { dom.insights._key = null; scheduleRender(); });
    }
  }

  function showGate(kind, message) {
    state.authFailed = kind !== 'none';
    if (kind === 'none') {
      dom.gate.hidden = true;
      dom.body.hidden = false;
      return;
    }
    var copy = {
      unprovisioned: ['The console is not provisioned yet', 'Its Forgejo OAuth application is created by the ci-console-oauth-provisioner CronJob, which writes ' + OAUTH_CONFIG_URL + '. Once that file exists, reload this page.', ''],
      signin: ['Connect the CI console', 'The console reads every repository you can see through the Forgejo API, so it needs a token for your account. Forgejo asks you once to authorize "CI console"; the token stays in this browser.', 'Connect to Forgejo'],
      expired: ['Reconnect the CI console', message || 'Forgejo stopped accepting the console token.', 'Reconnect'],
      failed: ['The console could not start', message || 'Something went wrong while connecting.', 'Try again'],
    }[kind];
    dom.gate.innerHTML = '<div class="wg-ci-gate-card"><h2>' + esc(copy[0]) + '</h2><p>' + esc(copy[1]) + '</p>' +
      (copy[2] ? '<button type="button" class="wg-ci-primary" data-wg-signin>' + esc(copy[2]) + '</button>' : '') + '</div>';
    dom.gate.hidden = false;
    dom.body.hidden = kind !== 'expired';
  }

  function loadMe() {
    return Promise.all([
      api('/user'),
      api('/user/settings').catch(function () { return { data: null }; }),
    ]).then(function (results) {
      state.me = results[0].data;
      if (results[1].data && results[1].data.theme) applyTheme(results[1].data.theme);
      if (state.me) {
        dom.me.hidden = false;
        dom.me.href = '/' + encodeURIComponent(state.me.login);
        dom.me.title = 'Signed in as ' + state.me.login;
        dom.me.innerHTML = '<img src="' + esc(state.me.avatar_url) + '" width="24" height="24" alt="' + esc(state.me.login) + '">';
      }
    });
  }

  function start() {
    showGate('none');
    state.started = true;
    scheduleRender();
    loadStatic(PANELS_URL).then(function (panels) { state.panels = panels; scheduleRender(); });
    tick();
    return loadMe();
  }

  function boot() {
    var root = document.getElementById('wg-ci');
    if (!root) return;
    root.setAttribute('data-wg-ci-version', WG_CI_VERSION);
    loadPrefs();
    mountShell(root);
    applyTheme(readJson(localStorage, THEME_KEY) || 'forgejo-auto');
    loadStatic(OAUTH_CONFIG_URL).then(function (config) {
      if (!config || !config.client_id) { showGate('unprovisioned'); return null; }
      state.config = {
        client_id: config.client_id,
        redirect_uri: config.redirect_uri || location.origin + CONSOLE_PATH,
      };
      return finishSignIn().then(function () {
        if (!readJson(localStorage, AUTH_KEY)) { showGate('signin'); return null; }
        return start();
      });
    }).catch(function (e) {
      if (e && e.authRequired) showGate(readJson(localStorage, AUTH_KEY) ? 'expired' : 'signin', e.message);
      else showGate('failed', (e && e.message) || String(e));
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
