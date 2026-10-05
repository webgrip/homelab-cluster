const CONFIG = /*CONFIG*/ null;

const HOUR_S = 3600;
const DAY_S = 86400;
const WEEK_S = 7 * DAY_S;
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const TYPES = ['feat', 'fix', 'ci', 'chore', 'test', 'refactor', 'docs', 'perf', 'build', 'revert'];
const STATIONS = [
  { key: 'backlog', cls: 'b', lbl: 'Backlog' },
  { key: 'todo', cls: 't', lbl: 'To do' },
  { key: 'doing', cls: 'd', lbl: 'Doing' },
  { key: 'reviewing', cls: 'r', lbl: 'Reviewing' },
  { key: 'done', cls: 'p', lbl: 'Done this week' },
];
const CI_STATE = {
  success: { cls: 'ok', txt: '✓ green' },
  failure: { cls: 'bad', txt: '✗ red' },
  running: { cls: 'wait', txt: '● running' },
  cancelled: { cls: 'wait', txt: 'superseded' },
};
const MAX_ASKS = 5;
const STREAK_BARS = 30;
const CI_AGE_WARN_S = 900;
const CI_AGE_ALARM_S = 1800;
const AGENT_AUTHOR = /(\[bot\]|\bbot\b|renovate)/i;
const CONVENTIONAL = /^([a-z]+)(?:\(([^)]*)\))?!?:\s*(.+)/;

function values(field) {
  if (!field || field.values == null) return [];
  const v = field.values;
  if (Array.isArray(v)) return v;
  if (typeof v.toArray === 'function') return v.toArray();
  return Array.from(v);
}

function lastNumber(field) {
  const vs = values(field);
  for (let i = vs.length - 1; i >= 0; i--) {
    if (vs[i] !== null && vs[i] !== undefined && !Number.isNaN(Number(vs[i]))) return Number(vs[i]);
  }
  return null;
}

function isSeries(fields) {
  const numbers = fields.filter((f) => f.type === 'number');
  const labelled = numbers.some((f) => f.labels && Object.keys(f.labels).length);
  const timeAndValue = numbers.length === 1 && fields.length === 2 && fields.some((f) => f.type === 'time');
  return labelled || timeAndValue;
}

function rows(series, ref) {
  const out = [];
  for (const frame of series || []) {
    if (frame.refId !== ref) continue;
    const fields = frame.fields || [];
    if (isSeries(fields)) {
      for (const f of fields) {
        if (f.type === 'number') out.push(Object.assign({}, f.labels || {}, { value: lastNumber(f) }));
      }
      continue;
    }
    const n = Math.max(0, ...fields.map((f) => values(f).length));
    for (let i = 0; i < n; i++) {
      const row = {};
      for (const f of fields) row[f.name] = values(f)[i];
      out.push(row);
    }
  }
  return out;
}

function answered(series, ref) {
  return (series || []).some((f) => f.refId === ref && (f.fields || []).length > 0);
}

function scalar(series, ref) {
  const r = rows(series, ref);
  if (!r.length) return null;
  const v = r[0].value !== undefined ? r[0].value : r[0][Object.keys(r[0])[0]];
  return v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v);
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function plural(n, one, many) {
  return n + ' ' + (n === 1 ? one : many);
}

function duration(seconds) {
  const s = Math.max(0, Math.round(num(seconds)));
  if (s < 60) return s + 's';
  if (s < HOUR_S) return Math.floor(s / 60) + 'm ' + String(s % 60).padStart(2, '0') + 's';
  if (s < DAY_S) return Math.floor(s / HOUR_S) + 'h ' + String(Math.floor((s % HOUR_S) / 60)).padStart(2, '0') + 'm';
  return Math.floor(s / DAY_S) + 'd ' + Math.floor((s % DAY_S) / HOUR_S) + 'h';
}

function age(seconds) {
  const s = Math.max(0, num(seconds));
  if (s < HOUR_S) return Math.max(1, Math.round(s / 60)) + 'm';
  if (s < DAY_S) return Math.round(s / HOUR_S) + 'h';
  return Math.round(s / DAY_S) + 'd';
}

function zoned(ms, tz) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz, year: 'numeric', month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(new Date(ms));
  const out = {};
  for (const p of parts) out[p.type] = p.value;
  const y = Number(out.year);
  const m = Number(out.month);
  const d = Number(out.day);
  const weekday = DAY_NAMES[(new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7];
  return { year: y, month: MONTHS[m - 1], monthNumber: m, day: String(d), weekday: weekday,
    hour: out.hour.padStart(2, '0'), minute: out.minute.padStart(2, '0') };
}

function isoWeek(ms, tz) {
  const z = zoned(ms, tz);
  const date = new Date(Date.UTC(z.year, z.monthNumber - 1, Number(z.day)));
  const dayNumber = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - dayNumber + 3);
  const firstThursday = new Date(Date.UTC(date.getUTCFullYear(), 0, 4));
  return 1 + Math.round(((date - firstThursday) / 86400000 - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7);
}

function week(now, cfg) {
  const today = DAY_NAMES.indexOf(zoned(now, cfg.tz).weekday);
  const monday = zoned(now - today * DAY_S * 1000, cfg.tz);
  const sunday = zoned(now + (6 - today) * DAY_S * 1000, cfg.tz);
  return {
    line: 'Week ' + isoWeek(now, cfg.tz) + ' · ' + monday.day + ' ' + monday.month + ' – ' + sunday.day + ' ' +
      sunday.month + ' · day ' + (today + 1) + ' of 7',
    cells: DAY_NAMES.map((name, i) => ({ cls: i < today ? 'done' : i === today ? 'today' : '', name: name })),
    first: 'Mon ' + monday.day + ' ' + monday.month,
    last: 'Sun ' + sunday.day + ' ' + sunday.month,
  };
}

function initials(name) {
  const words = String(name || '?').replace(/\[bot\]/i, '').trim().split(/[\s._-]+/).filter(Boolean);
  if (!words.length) return '?';
  const first = words[0][0];
  const last = words.length > 1 ? words[words.length - 1][0] : (words[0][1] || '');
  return (first + last).toUpperCase();
}

function conventional(title) {
  const m = CONVENTIONAL.exec(String(title || ''));
  if (!m) return { type: 'other', scope: '', text: String(title || '') };
  return { type: TYPES.indexOf(m[1]) >= 0 ? m[1] : 'other', scope: m[2] || '', text: m[3] };
}

function clock(atSeconds, now, cfg) {
  const at = zoned(atSeconds * 1000, cfg.tz);
  const same = zoned(now, cfg.tz);
  const hm = at.hour + ':' + at.minute;
  if (at.day === same.day && at.month === same.month && now - atSeconds * 1000 < DAY_S * 1000) return hm;
  return at.weekday + ' ' + hm;
}

function feed(series, now, cfg) {
  return rows(series, 'FEED').map((r) => {
    const c = conventional(r.title);
    const agent = r.agent === true || r.agent === 't' || AGENT_AUTHOR.test(String(r.author || ''));
    const ci = r.ci ? CI_STATE[r.ci] || CI_STATE.cancelled
      : r.head === false || r.head === 'f' ? { cls: 'wait', txt: 'in a push' } : { cls: 'wait', txt: 'no CI' };
    return {
      t: clock(num(r.at), now, cfg),
      who: initials(r.author),
      agent: agent,
      type: c.type,
      title: c.text,
      where: r.repo + (c.scope ? ' · ' + c.scope : ''),
      ci: ci,
      url: cfg.forgejo + '/' + cfg.org + '/' + r.repo + '/commit/' + r.sha,
    };
  });
}

function shipped(series) {
  const w = rows(series, 'WEEK')[0] || {};
  const n = num(w.commits);
  const facts = [];
  if (num(w.repos)) facts.push({ b: String(num(w.repos)), txt: num(w.repos) === 1 ? ' repository' : ' repositories' });
  facts.push({ b: String(num(w.merged)), txt: num(w.merged) === 1 ? ' pull request merged' : ' pull requests merged' });
  if (num(w.releases)) facts.push({ b: String(num(w.releases)), txt: num(w.releases) === 1 ? ' release' : ' releases' });
  if (num(w.agent_commits)) facts.push({ b: String(num(w.agent_commits)), txt: ' by bot accounts', cls: 'agent' });
  facts.push({ pre: 'last week ', b: String(num(w.last_week)), txt: '', cls: 'muted' });
  return { n: n, word: n === 1 ? 'commit landed this week' : 'commits landed this week', facts: facts };
}

function boards(series, cfg) {
  const byId = {};
  for (const r of rows(series, 'STAGES')) byId[num(r.board)] = r;
  const cards = [];
  const quiet = [];
  for (const b of cfg.boards) {
    const r = byId[b.id] || {};
    const stations = STATIONS.map((s) => {
      const n = num(r[s.key]);
      return { cls: s.cls, lbl: s.lbl, n: n, fill: n > 0 ? 'full' : 'empty' };
    });
    const open = num(r.backlog) + num(r.todo) + num(r.doing) + num(r.reviewing);
    if (open + num(r.done) === 0) {
      quiet.push(b.name);
      continue;
    }
    cards.push({
      name: b.name, url: b.url, stations: stations, open: open,
      meta: num(r.do_next) ? plural(num(r.do_next), 'do-next', 'do-next') : plural(open, 'open ticket', 'open tickets'),
    });
  }
  return { cards: cards, quiet: quiet };
}

function wins(series, cfg) {
  const out = [];
  for (const r of rows(series, 'WINS')) {
    if (r.kind === 'fastest') {
      out.push({ k: 'Fastest push to green', v: duration(r.value), s: r.repo + ' · ' + r.workflow });
    } else if (r.kind === 'streak' && num(r.value) > 1) {
      const n = num(r.value);
      out.push({
        k: 'Longest green streak', v: String(n), unit: 'runs in a row', s: r.repo + ' · ' + r.workflow,
        bars: Array.from({ length: Math.min(n, STREAK_BARS) }, () => ({})),
      });
    }
  }
  const stages = rows(series, 'STAGES');
  const closed = stages.reduce((sum, r) => sum + num(r.done), 0);
  if (closed) {
    const names = {};
    for (const b of cfg.boards) names[b.id] = b.name;
    const split = stages.filter((r) => num(r.done)).map((r) => (names[num(r.board)] || 'board ' + r.board) + ' ' + num(r.done));
    out.push({ k: 'Closed on the boards', v: String(closed), unit: closed === 1 ? 'ticket' : 'tickets', s: split.join(' · ') });
  }
  return out;
}

function asks(series, now, cfg) {
  const out = [];
  const alerts = rows(series, 'ALERTS')[0] || {};
  const critical = num(alerts.critical);
  const warning = num(alerts.warning);
  if (critical) {
    out.push({ k: 'Alerts firing', v: plural(critical, 'critical alert', 'critical alerts') +
      (warning ? ' · ' + warning + ' warning' : ''), s: 'Fix or silence: the alert walls name each one', url: cfg.links.alerts, cls: 'alarm' });
  }
  const red = rows(series, 'TRUNK_RED').sort((a, b) => num(b.value) - num(a.value));
  if (red.length) {
    const worst = red[0];
    const since = num(worst.value) > 0 ? 'red for ' + age(worst.value) : 'not green in the exporter window';
    out.push({
      k: 'Trunk red', v: red.length === 1 ? worst.repo + ' · ' + worst.workflow : plural(red.length, 'trunk', 'trunks') + ' red',
      s: red.length === 1 ? since : worst.repo + ' ' + since, url: cfg.links.ci,
    });
  }
  const flux = scalar(series, 'FLUX');
  if (flux) out.push({ k: 'Flux not ready', v: plural(flux, 'object', 'objects'), s: 'Git is not what runs', url: cfg.links.gitops });
  const glide = {};
  for (const r of rows(series, 'GLIDE')) glide[r.state] = num(r.value);
  if (glide.needs_human) {
    out.push({ k: 'Glide waits on you', v: plural(glide.needs_human, 'work item', 'work items'),
      s: glide.awaiting_review ? glide.awaiting_review + ' more awaiting review' : 'needs a human decision', url: cfg.links.glide });
  }
  const stages = rows(series, 'STAGES');
  const reviewing = stages.reduce((sum, r) => sum + num(r.reviewing), 0);
  if (reviewing) {
    const oldest = Math.min.apply(null, stages.filter((r) => num(r.reviewing)).map((r) => num(r.oldest_review) || now / 1000));
    const names = {};
    for (const b of cfg.boards) names[b.id] = b.name;
    out.push({ k: 'Reviews waiting', v: plural(reviewing, 'ticket', 'tickets'), s: 'oldest waiting ' + age(now / 1000 - oldest),
      url: cfg.links.roadmap,
      chips: stages.filter((r) => num(r.reviewing)).map((r) => ({ c: names[num(r.board)] || 'board ' + r.board, n: num(r.reviewing) })) });
  }
  const pulls = rows(series, 'PULLS');
  const people = pulls.filter((p) => !(p.agent === true || p.agent === 't'));
  const bots = pulls.filter((p) => p.agent === true || p.agent === 't');
  const failing = pulls.filter((p) => p.ci === 'failure');
  if (people.length) {
    const oldest = people[0];
    out.push({ k: 'Pull requests open', v: plural(people.length, 'waiting to merge', 'waiting to merge'),
      s: 'oldest #' + oldest.number + ' ' + oldest.repo + ' · ' + age(now / 1000 - num(oldest.opened)), url: cfg.links.pulls });
  }
  if (failing.length) {
    out.push({ k: 'Pull request pipelines red', v: plural(failing.length, 'pull request', 'pull requests'),
      s: '#' + failing[0].number + ' ' + failing[0].repo + ' · ' + failing[0].title, url: cfg.links.pulls });
  }
  if (bots.length) {
    const stale = bots.filter((p) => now / 1000 - num(p.opened) > WEEK_S).length;
    out.push({ k: 'Bot pull requests', v: plural(bots.length, 'open', 'open'),
      s: stale ? stale + ' older than a week' : 'none older than a week', url: cfg.links.pulls });
  }
  return { shown: out.slice(0, MAX_ASKS), more: Math.max(0, out.length - MAX_ASKS) };
}

function foot(series, forgejoUp) {
  const out = [];
  out.push(forgejoUp ? { txt: 'Forgejo database live', cls: '' } : { txt: 'Forgejo database not answering', cls: 'alarm' });
  const ciAge = scalar(series, 'CI_AGE');
  if (ciAge === null) out.push({ txt: 'CI exporter not reporting', cls: 'warn' });
  else out.push({ txt: 'CI data ' + age(ciAge) + ' old', cls: ciAge > CI_AGE_ALARM_S ? 'alarm' : ciAge > CI_AGE_WARN_S ? 'warn' : '' });
  const probes = scalar(series, 'PROBES');
  if (probes === null || probes < 0) out.push({ txt: 'probes not reporting', cls: 'warn' });
  else out.push(probes >= 1 ? { txt: 'all probes up', cls: '' } : { txt: 'a probe is failing', cls: 'alarm' });
  const flux = scalar(series, 'FLUX');
  if (flux === 0) out.push({ txt: 'Flux in sync', cls: '' });
  return out;
}

function build(series, now, cfg) {
  const forgejoUp = answered(series, 'FEED') || answered(series, 'WEEK');
  const hand = asks(series, now, cfg);
  const where = boards(series, cfg);
  return {
    title: cfg.org,
    week: week(now, cfg),
    available: forgejoUp,
    notice: 'The Forgejo database did not answer, so nothing on this wall can say what landed. Check the forgejo-db ' +
      'datasource and the grafana_ro role before reading the rest as quiet.',
    shipped: shipped(series),
    cards: where.cards,
    quiet: where.quiet,
    wins: wins(series, cfg),
    feed: feed(series, now, cfg),
    hand: hand.shown,
    more: hand.more,
    foot: foot(series, forgejoUp),
    links: cfg.links,
  };
}

function wallText(value) {
  const s = value === null || value === undefined ? '' : String(value);
  const out = s.replace(/[&<>"'`=*_[\]\\~!#|]/g, (ch) => '&#' + ch.charCodeAt(0) + ';');
  return new context.handlebars.SafeString(out);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { build, rows, duration, age, initials, conventional, week, isoWeek };
}

if (typeof context !== 'undefined' && context && context.handlebars) {
  context.handlebars.registerHelper('wallText', wallText);
  context.data.wall = build((context.panelData && context.panelData.series) || [], Date.now(), CONFIG);
}
