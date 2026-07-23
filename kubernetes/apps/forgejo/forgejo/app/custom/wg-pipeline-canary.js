/* Pipeline DAG for the Actions run view — v3.
   Data: the embedded run/job JSON (data-initial-post-response) + the workflow
   YAML at the run's commit + the reusable workflows each job `uses:` (all raw
   same-origin fetches). Forgejo expands reusable-workflow jobs into separate
   run jobs; v3 merges each caller with its expanded children into one node
   (worst status, real duration, click-through to the child that has logs).
   Layout: longest-path layering + two-pass barycenter. Live: 5s rail resync
   (re-matches by name if the job list grows mid-run). Hover highlights the
   full upstream/downstream chain. Fails silent if anything doesn't parse.
   NOTE: this file is a Go template — never write two adjacent open braces. */
(function () {
  'use strict';

  var WG_VERSION = '3.2.0';
  try { window.__wgPipeline = { version: WG_VERSION }; } catch (e) { }

  var RANK = { failure: 7, unknown: 7, cancelled: 6, running: 5, blocked: 4, waiting: 4, success: 3, skipped: 2 };
  var ICON_STATUS = [
    ['octicon-check-circle-fill', 'success'],
    ['octicon-x-circle-fill', 'failure'],
    ['octicon-skip', 'skipped'],
    ['octicon-stop', 'cancelled'],
    ['octicon-clock', 'waiting'],
    ['octicon-blocked', 'blocked'],
    ['octicon-meter', 'running'],
  ];

  function stripQ(s) {
    var m = s.match(/^"(.*)"$/) || s.match(/^'(.*)'$/);
    return m ? m[1] : s;
  }

  function parseDur(s) {
    if (!s) return 0;
    var total = 0, m, re = /(\d+)([hms])/g;
    while ((m = re.exec(s))) total += parseInt(m[1], 10) * (m[2] === 'h' ? 3600 : m[2] === 'm' ? 60 : 1);
    return total;
  }

  /* Line-based extraction of jobs.<id>.{name,needs,uses} — not a YAML parser,
     but workflow files are shallow enough (verified against the erfbeeld +
     webgrip/workflows files). Job-level `uses:` only; step-level sits deeper
     than bodyIndent and is ignored. */
  function parseWorkflowJobs(text) {
    var lines = text.split(/\r?\n/);
    var jobs = [];
    var i = 0;
    while (i < lines.length && !/^jobs:\s*(#.*)?$/.test(lines[i])) i++;
    i++;
    var jobIndent = -1, bodyIndent = -1, needsIndent = -1;
    var cur = null, inNeeds = false;
    for (; i < lines.length; i++) {
      var line = lines[i];
      if (/^\s*(#|$)/.test(line)) continue;
      var indent = line.match(/^ */)[0].length;
      if (indent === 0) break;
      if (jobIndent === -1) jobIndent = indent;
      var m;
      if (indent === jobIndent && (m = line.match(/^ *([A-Za-z0-9_.-]+):\s*(#.*)?$/))) {
        cur = { id: m[1], name: null, needs: [], uses: null };
        jobs.push(cur);
        bodyIndent = -1;
        inNeeds = false;
        continue;
      }
      if (!cur) continue;
      if (inNeeds) {
        if (indent > needsIndent && (m = line.match(/^ *- *([^#]+?)\s*$/))) {
          cur.needs.push(stripQ(m[1]));
          continue;
        }
        inNeeds = false;
      }
      if (bodyIndent === -1 && indent > jobIndent) bodyIndent = indent;
      if (indent !== bodyIndent) continue;
      if ((m = line.match(/^ *name: *(.+?)\s*$/))) {
        cur.name = stripQ(m[1]);
      } else if ((m = line.match(/^ *uses: *(\S+)\s*(#.*)?$/))) {
        cur.uses = stripQ(m[1]);
      } else if ((m = line.match(/^ *needs: *\[([^\]]*)\]/))) {
        cur.needs = m[1].split(',').map(function (s) { return stripQ(s.trim()); }).filter(Boolean);
      } else if (/^ *needs:\s*(#.*)?$/.test(line)) {
        inNeeds = true;
        needsIndent = indent;
      } else if ((m = line.match(/^ *needs: *([^#[]+?)\s*(#.*)?$/))) {
        cur.needs = [stripQ(m[1])];
      }
    }
    return jobs;
  }

  function labelOf(j) {
    return (j.name && !/[$][{]/.test(j.name)) ? j.name : j.id;
  }

  function nameMatches(runName, label) {
    return runName === label || runName.indexOf(label + ' (') === 0 || runName.indexOf(label + ' / ') === 0;
  }

  /* Fetch text with a sessionStorage cache so revisits render instantly.
     Commit-pinned raw URLs are immutable (cache forever); branch/tag refs
     get a 10-minute TTL. */
  function cachedText(url) {
    var key = 'wg-yml:' + url;
    var immutable = url.indexOf('/raw/commit/') !== -1;
    try {
      var hit = sessionStorage.getItem(key);
      if (hit) {
        var obj = JSON.parse(hit);
        if (immutable || Date.now() - obj.t < 600000) return Promise.resolve(obj.x);
      }
    } catch (e) { }
    return fetch(url, { credentials: 'same-origin' }).then(function (r) {
      if (!r.ok) return null;
      return r.text().then(function (t) {
        try { sessionStorage.setItem(key, JSON.stringify({ t: Date.now(), x: t })); } catch (e) { }
        return t;
      });
    });
  }

  /* Fetch text from the first URL that answers 200; null if none do. */
  function fetchFirstOk(urls) {
    if (!urls.length) return Promise.resolve(null);
    return cachedText(urls[0])
      .then(function (t) { return t !== null ? t : fetchFirstOk(urls.slice(1)); })
      .catch(function () { return fetchFirstOk(urls.slice(1)); });
  }

  /* uses: "owner/repo/path@ref" (cross-repo) or "./path" (same repo at the
     run's commit) → candidate raw URLs. */
  function reusableURLs(uses, selfRawBase) {
    if (uses.indexOf('./') === 0) {
      return selfRawBase ? [selfRawBase + uses.slice(2)] : [];
    }
    var at = uses.lastIndexOf('@');
    if (at === -1) return [];
    var ref = uses.slice(at + 1);
    var parts = uses.slice(0, at).split('/');
    if (parts.length < 3) return [];
    var base = '/' + parts[0] + '/' + parts[1] + '/raw/';
    var path = parts.slice(2).join('/');
    var urls = [];
    if (/^[0-9a-f]{40}$/.test(ref)) urls.push(base + 'commit/' + ref + '/' + path);
    urls.push(base + 'branch/' + ref + '/' + path);
    urls.push(base + 'tag/' + ref + '/' + path);
    return urls;
  }

  /* Two matching passes over run-job names: primary labels first (so a
     caller's own name always wins), then reusable child labels merge the
     expanded jobs into their caller. Returns leftover orphan descriptors. */
  function assignIndices(yjobs, names) {
    var used = [];
    yjobs.forEach(function (yj) { yj.indices = []; });
    yjobs.forEach(function (yj) {
      names.forEach(function (nm, idx) {
        if (used[idx]) return;
        if (nameMatches(nm, yj.label)) { yj.indices.push(idx); used[idx] = true; }
      });
    });
    yjobs.forEach(function (yj) {
      (yj.childLabels || []).forEach(function (cl) {
        names.forEach(function (nm, idx) {
          if (used[idx]) return;
          if (nameMatches(nm, cl)) { yj.indices.push(idx); used[idx] = true; }
        });
      });
    });
    var orphans = [];
    names.forEach(function (nm, idx) {
      if (!used[idx]) orphans.push({ name: nm, idx: idx });
    });
    return orphans;
  }

  function aggStatus(yj, statuses) {
    var best = '';
    yj.indices.forEach(function (idx) {
      var s = statuses[idx] || 'unknown';
      if ((RANK[s] || 0) > (RANK[best] || 0)) best = s;
    });
    return best || 'waiting';
  }

  function computeDepth(yjobs) {
    var byId = Object.create(null);
    yjobs.forEach(function (j) { byId[j.id] = j; });
    function depth(j, seen) {
      if (j._d != null) return j._d;
      if (seen[j.id]) return 0;
      seen[j.id] = true;
      var d = 0;
      j.needs.forEach(function (nid) {
        var p = byId[nid];
        if (p) d = Math.max(d, depth(p, seen) + 1);
      });
      j._d = d;
      return d;
    }
    yjobs.forEach(function (j) { depth(j, Object.create(null)); });
    return byId;
  }

  function orderStages(stages, byId) {
    var childrenOf = Object.create(null);
    stages.flat().forEach(function (j) {
      j.needs.forEach(function (nid) {
        if (byId[nid]) (childrenOf[nid] = childrenOf[nid] || []).push(j.id);
      });
    });
    function posMap(stage) {
      var pos = Object.create(null);
      stage.forEach(function (j, i) { pos[j.id] = i; });
      return pos;
    }
    function mean(ids, pos, fallback) {
      var vals = ids.filter(function (id) { return pos[id] != null; }).map(function (id) { return pos[id]; });
      if (!vals.length) return fallback;
      return vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
    }
    for (var round = 0; round < 2; round++) {
      for (var s = 1; s < stages.length; s++) {
        var pos = posMap(stages[s - 1]);
        stages[s].sort(function (a, b) {
          return mean(a.needs, pos, 1e3) - mean(b.needs, pos, 1e3);
        });
      }
      for (var t = stages.length - 2; t >= 0; t--) {
        var cpos = posMap(stages[t + 1]);
        stages[t].sort(function (a, b) {
          var fa = a.orphan ? 1e6 : 1e3, fb = b.orphan ? 1e6 : 1e3;
          return mean(childrenOf[a.id] || [], cpos, fa) - mean(childrenOf[b.id] || [], cpos, fb);
        });
      }
    }
  }

  function railRead() {
    var items = document.querySelectorAll('.action-view-left .job-brief-item');
    if (!items.length) return null;
    return Array.prototype.map.call(items, function (item) {
      var status = 'unknown';
      for (var k = 0; k < ICON_STATUS.length; k++) {
        if (item.querySelector('svg.' + ICON_STATUS[k][0])) { status = ICON_STATUS[k][1]; break; }
      }
      var nm = item.querySelector('.job-brief-name');
      var dur = item.querySelector('.step-summary-duration');
      return {
        name: nm ? nm.textContent.trim() : '',
        status: status,
        duration: dur ? dur.textContent.trim() : '',
      };
    });
  }

  function build(host, run, yjobs) {
    yjobs.forEach(function (j) { j.label = labelOf(j); });
    var runNames = run.jobs.map(function (j) { return j.name; });
    assignIndices(yjobs, runNames).forEach(function (o) {
      yjobs.push({ id: ' run' + o.idx, label: o.name, needs: [], uses: null, indices: [o.idx], orphan: true });
    });

    var byId = computeDepth(yjobs);
    var edges = [];
    yjobs.forEach(function (j) {
      j.needs.forEach(function (nid) {
        if (byId[nid]) edges.push({ from: nid, to: j.id });
      });
    });
    if (!edges.length) return;

    var stages = [];
    yjobs.forEach(function (j) {
      (stages[j._d] = stages[j._d] || []).push(j);
    });
    orderStages(stages, byId);

    /* transitive chains for hover emphasis */
    var upAdj = Object.create(null), downAdj = Object.create(null);
    edges.forEach(function (e) {
      (downAdj[e.from] = downAdj[e.from] || []).push(e.to);
      (upAdj[e.to] = upAdj[e.to] || []).push(e.from);
    });
    function collect(id, adj, set) {
      (adj[id] || []).forEach(function (n) {
        if (!set[n]) { set[n] = true; collect(n, adj, set); }
      });
    }
    var chainCache = Object.create(null);
    function chainOf(id) {
      if (!chainCache[id]) {
        var set = Object.create(null);
        set[id] = true;
        collect(id, upAdj, set);
        collect(id, downAdj, set);
        chainCache[id] = set;
      }
      return chainCache[id];
    }

    var selectedIdx = parseInt(host.getAttribute('data-job-index'), 10);

    var section = document.createElement('section');
    section.className = 'wg-pipeline';
    if (localStorage.getItem('wg-pipeline-collapsed') === '1') section.classList.add('wg-collapsed');

    var header = document.createElement('div');
    header.className = 'wg-pipeline-header';
    header.innerHTML = '<span class="wg-caret">&#9662;</span>' +
      '<span class="wg-run-status wg-status-waiting"><span class="wg-node-dot"></span></span>' +
      '<span>Pipeline</span>' +
      '<span class="wg-pipeline-meta">' + run.jobs.length + ' jobs &middot; ' + stages.length + ' stages</span>';
    header.addEventListener('click', function () {
      section.classList.toggle('wg-collapsed');
      localStorage.setItem('wg-pipeline-collapsed', section.classList.contains('wg-collapsed') ? '1' : '0');
      draw();
    });
    section.appendChild(header);

    var scroll = document.createElement('div');
    scroll.className = 'wg-pipeline-scroll';
    var canvas = document.createElement('div');
    canvas.className = 'wg-pipeline-canvas';
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'wg-pipeline-edges');
    var stagesEl = document.createElement('div');
    stagesEl.className = 'wg-pipeline-stages';
    canvas.appendChild(svg);
    canvas.appendChild(stagesEl);
    scroll.appendChild(canvas);
    section.appendChild(scroll);

    var nodeEls = Object.create(null);
    var statuses = run.jobs.map(function (j) { return j.status; });
    var durations = run.jobs.map(function (j) { return j.duration; });

    stages.forEach(function (stage, si) {
      var col = document.createElement('div');
      col.className = 'wg-stage';
      col.setAttribute('data-label', 'Stage ' + (si + 1));
      stage.forEach(function (j) {
        var a = document.createElement('a');
        var dot = document.createElement('span');
        dot.className = 'wg-node-dot';
        var body = document.createElement('span');
        body.className = 'wg-node-body';
        var name = document.createElement('span');
        name.className = 'wg-node-name';
        name.textContent = j.label;
        var meta = document.createElement('span');
        meta.className = 'wg-node-meta';
        body.appendChild(name);
        body.appendChild(meta);
        a.appendChild(dot);
        a.appendChild(body);
        a.addEventListener('mouseenter', function () { emphasize(j.id, true); });
        a.addEventListener('mouseleave', function () { emphasize(j.id, false); });
        col.appendChild(a);
        nodeEls[j.id] = a;
      });
      stagesEl.appendChild(col);
    });

    var edgePaths = [];
    function emphasize(id, on) {
      var chain = chainOf(id);
      edgePaths.forEach(function (ep) {
        ep.el.classList.toggle('wg-edge-hl', on && !!(chain[ep.from] && chain[ep.to]));
      });
      yjobs.forEach(function (j) {
        var el = nodeEls[j.id];
        if (el) el.classList.toggle('wg-dim', on && !chain[j.id]);
      });
    }

    function updateNodes() {
      yjobs.forEach(function (j) {
        var el = nodeEls[j.id];
        if (!el) return;
        var st = aggStatus(j, statuses);
        j._st = st;
        var cls = 'wg-node wg-status-' + st;
        if (j.orphan) cls += ' wg-orphan';
        if (j.indices.indexOf(selectedIdx) !== -1) cls += ' wg-selected';
        if (el.classList.contains('wg-dim')) cls += ' wg-dim';
        el.className = cls;

        /* real work usually lives in the expanded child job — link and show
           the constituent with the longest duration */
        var bestIdx = j.indices.length ? j.indices[0] : -1;
        var bestDur = -1;
        j.indices.forEach(function (idx) {
          var d = parseDur(durations[idx]);
          if (d > bestDur) { bestDur = d; bestIdx = idx; }
        });
        if (bestIdx !== -1) el.href = run.link + '/jobs/' + bestIdx;

        var metaEl = el.querySelector('.wg-node-meta');
        var dTxt = (bestDur > 0) ? durations[bestIdx] : '';
        metaEl.textContent = st + (dTxt ? ' · ' + dTxt : '');

        var tip = j.label + ' · ' + st + (dTxt ? ' · ' + dTxt : '');
        if (j.indices.length > 1) {
          tip += '\ncontains: ' + j.indices.map(function (idx) {
            return (run.jobs[idx] ? run.jobs[idx].name : railNameAt(idx)) + ' [' + (statuses[idx] || '?') + ']';
          }).join(', ');
        }
        if (j.orphan) tip += '\nnot in the workflow at this commit (older attempt)';
        el.title = tip;
      });
      var overall = '';
      yjobs.forEach(function (j) {
        if ((RANK[j._st] || 0) > (RANK[overall] || 0)) overall = j._st;
      });
      var runDot = section.querySelector('.wg-run-status');
      if (runDot) runDot.className = 'wg-run-status wg-status-' + (overall || 'waiting');
    }

    var lastRail = null;
    function railNameAt(idx) {
      return (lastRail && lastRail[idx]) ? lastRail[idx].name : 'job #' + idx;
    }

    function draw() {
      if (section.classList.contains('wg-collapsed')) return;
      edgePaths = [];
      svg.setAttribute('width', canvas.scrollWidth);
      svg.setAttribute('height', canvas.scrollHeight);
      svg.innerHTML = '<defs><marker id="wg-arrow" viewBox="0 0 10 10" refX="8.5" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">' +
        '<path d="M 0 1.5 L 8.5 5 L 0 8.5 z" style="fill: var(--color-text-light-3)"/></marker></defs>';
      edges.forEach(function (e) {
        var p = nodeEls[e.from], c = nodeEls[e.to];
        if (!p || !c) return;
        var x1 = p.offsetLeft + p.offsetWidth, y1 = p.offsetTop + p.offsetHeight / 2;
        var x2 = c.offsetLeft, y2 = c.offsetTop + c.offsetHeight / 2;
        var dx = Math.max(26, (x2 - x1) / 2);
        var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M' + x1 + ' ' + y1 + ' C' + (x1 + dx) + ' ' + y1 + ', ' + (x2 - dx) + ' ' + y2 + ', ' + (x2 - 2) + ' ' + y2);
        var cls = 'wg-edge';
        var target = byId[e.to];
        if (target && target._st === 'running') cls += ' wg-edge-flow';
        else if (target && (target._st === 'failure' || target._st === 'unknown')) cls += ' wg-edge-fail';
        path.setAttribute('class', cls);
        path.setAttribute('marker-end', 'url(#wg-arrow)');
        svg.appendChild(path);
        edgePaths.push({ from: e.from, to: e.to, el: path });
      });
    }

    function apply(read) {
      if (read) {
        /* the job list can grow mid-run as Forgejo expands reusable children —
           re-match by name whenever the rail size changes */
        if (!lastRail || read.length !== lastRail.length) {
          assignIndices(yjobs.filter(function (j) { return !j.orphan; }), read.map(function (r) { return r.name; }));
          yjobs.forEach(function (j) {
            if (j.orphan) {
              j.indices = [];
              read.forEach(function (r, idx) {
                if (nameMatches(r.name, j.label)) j.indices.push(idx);
              });
            }
          });
        }
        lastRail = read;
        statuses = read.map(function (r) { return r.status; });
        durations = read.map(function (r) { return r.duration; });
      }
      updateNodes();
      draw();
      decorateRail();
    }

    /* Group the stock JOBS rail: reorder topologically to mirror the graph
       (flex `order`, no DOM moves — Vue keeps ownership) and indent expanded
       reusable-children under their caller. data-* attrs + inline styles only:
       Vue's class patching would wipe added classes, but leaves these alone. */
    function decorateRail() {
      var items = document.querySelectorAll('.action-view-left .job-brief-item');
      if (!items.length) return;
      var plan = Object.create(null);
      var seq = 0;
      stages.forEach(function (stage) {
        stage.forEach(function (j) {
          if (!j.indices.length) return;
          var caller = j.indices[0];
          for (var k = 0; k < j.indices.length; k++) {
            var idx = j.indices[k];
            var nm = lastRail ? (lastRail[idx] || {}).name : (run.jobs[idx] || {}).name;
            if (nm && nameMatches(nm, j.label)) { caller = idx; break; }
          }
          seq += 10;
          plan[caller] = { order: seq, child: false };
          var off = 0;
          j.indices.forEach(function (idx) {
            if (idx === caller) return;
            off++;
            plan[idx] = { order: seq + off, child: true };
          });
        });
      });
      Array.prototype.forEach.call(items, function (item, idx) {
        var p = plan[idx];
        item.style.order = p ? p.order : 9000 + idx;
        if (p && p.child) item.setAttribute('data-wg-child', '');
        else item.removeAttribute('data-wg-child');
      });
    }

    host.parentNode.insertBefore(section, host);
    apply(null);

    /* the rail is Vue-rendered a beat after DOMContentLoaded — retry the
       decoration briefly so finished runs (no 5s resync) still get grouped */
    var railTries = 0;
    var railWait = window.setInterval(function () {
      railTries++;
      var items = document.querySelectorAll('.action-view-left .job-brief-item');
      if (items.length || railTries > 20) {
        window.clearInterval(railWait);
        if (items.length) decorateRail();
      }
    }, 250);

    window.addEventListener('resize', function () { window.requestAnimationFrame(draw); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { draw(); });

    if (!run.done) {
      var timer = window.setInterval(function () {
        var read = railRead();
        if (read) apply(read);
        var allDone = read && read.every(function (r) {
          return r.status === 'success' || r.status === 'failure' || r.status === 'skipped' || r.status === 'cancelled' || r.status === 'unknown';
        });
        if (allDone) window.clearInterval(timer);
      }, 5000);
    }
  }

  function init() {
    try {
      var host = document.getElementById('repo-action-view');
      if (!host) return;
      var data = JSON.parse(host.getAttribute('data-initial-post-response') || 'null');
      var run = data && data.state && data.state.run;
      if (!run || !run.jobs || run.jobs.length < 2) return;
      var src = host.getAttribute('data-workflow-source-url') || '';
      if (src.indexOf('/src/commit/') === -1) return;
      var selfRawBase = src.replace('/src/commit/', '/raw/commit/').replace(/[^/]+$/, '');

      /* immediate shell so the panel doesn't pop in late / shift the layout */
      var shell = document.createElement('section');
      shell.className = 'wg-pipeline';
      if (localStorage.getItem('wg-pipeline-collapsed') === '1') shell.classList.add('wg-collapsed');
      shell.innerHTML = '<div class="wg-pipeline-header"><span class="wg-caret">&#9662;</span>' +
        '<span>Pipeline</span><span class="wg-pipeline-meta">loading&hellip;</span></div>';
      host.parentNode.insertBefore(shell, host);

      cachedText(src.replace('/src/commit/', '/raw/commit/'))
        .then(function (yaml) {
          if (yaml === null) throw new Error('workflow fetch failed');
          var yjobs = parseWorkflowJobs(yaml);
          var targets = Object.create(null);
          yjobs.forEach(function (j) {
            if (j.uses) targets[j.uses] = null;
          });
          var keys = Object.keys(targets);
          return Promise.all(keys.map(function (u) {
            return fetchFirstOk(reusableURLs(u, selfRawBase)).then(function (text) {
              targets[u] = text ? parseWorkflowJobs(text).map(labelOf) : [];
            });
          })).then(function () {
            yjobs.forEach(function (j) {
              if (j.uses) j.childLabels = targets[j.uses] || [];
            });
            shell.remove();
            build(host, run, yjobs);
          });
        })
        .catch(function (e) { shell.remove(); console.debug('[wg-pipeline]', e); });
    } catch (e) {
      console.debug('[wg-pipeline]', e);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
