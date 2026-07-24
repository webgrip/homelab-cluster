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

  var WG_VERSION = '3.5.0';
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

  /* Fetch text from the first URL that answers 200, returning {text, url} for
     the winner (both null if none answer) — the url lets a nested `./`-relative
     `uses:` resolve against the reusable that contained it. */
  function fetchFirstOkWithUrl(urls) {
    if (!urls.length) return Promise.resolve({ text: null, url: null });
    return cachedText(urls[0])
      .then(function (t) { return t !== null ? { text: t, url: urls[0] } : fetchFirstOkWithUrl(urls.slice(1)); })
      .catch(function () { return fetchFirstOkWithUrl(urls.slice(1)); });
  }

  /* Fetch text from the first URL that answers 200; null if none do. */
  function fetchFirstOk(urls) {
    return fetchFirstOkWithUrl(urls).then(function (r) { return r.text; });
  }

  /* raw dir of a resolved reusable URL (strip the filename) so a nested
     `./sibling.yml` inside it resolves against its own repo+ref. */
  function rawDirOf(url) {
    return url ? url.replace(/[^/]+$/, '') : '';
  }

  var MAX_REUSABLE_DEPTH = 5;

  /* Resolve a job-level `uses:` to EVERY descendant job Forgejo will flatten
     into the run graph, as {label, depth} items. Forgejo expands a called
     reusable workflow's inner jobs into the caller (docs/.../
     forgejo-actions-engine.md), and those inner jobs can themselves `uses:`
     further reusables — so we follow the chain transitively, tagging each job
     with its nesting depth (caller's direct reusable = 1, its reusable = 2, …)
     so the rail can render the true call chain rather than flat siblings.
     `seen` guards cycles; MAX_REUSABLE_DEPTH bounds runaway. Fetches are cached
     (cachedText), so commit-pinned refs cost one request ever. */
  function resolveDescendants(uses, baseForRel, depth, seen) {
    if (!uses || depth > MAX_REUSABLE_DEPTH || seen[uses]) return Promise.resolve([]);
    seen[uses] = true;
    return fetchFirstOkWithUrl(reusableURLs(uses, baseForRel)).then(function (hit) {
      if (!hit.text) return [];
      var jobs = parseWorkflowJobs(hit.text);
      var childBase = rawDirOf(hit.url);
      return Promise.all(jobs.map(function (jj) {
        var self = [{ label: labelOf(jj), depth: depth }];
        if (!jj.uses) return self;
        return resolveDescendants(jj.uses, childBase, depth + 1, seen)
          .then(function (more) { return self.concat(more); });
      })).then(function (arrs) {
        return arrs.reduce(function (a, b) { return a.concat(b); }, []);
      });
    });
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
     caller's own name always wins at depth 0), then reusable descendants
     (childItems, each carrying its nesting depth) merge the flattened jobs into
     their caller. depthByIndex records how deep in the reusable-call chain each
     matched run job sits, so the rail can indent it correctly. Returns leftover
     orphan descriptors. */
  function assignIndices(yjobs, names) {
    var used = [];
    yjobs.forEach(function (yj) { yj.indices = []; yj.depthByIndex = Object.create(null); });
    yjobs.forEach(function (yj) {
      names.forEach(function (nm, idx) {
        if (used[idx]) return;
        if (nameMatches(nm, yj.label)) { yj.indices.push(idx); yj.depthByIndex[idx] = 0; used[idx] = true; }
      });
    });
    yjobs.forEach(function (yj) {
      (yj.childItems || []).forEach(function (ci) {
        names.forEach(function (nm, idx) {
          if (used[idx]) return;
          if (nameMatches(nm, ci.label)) { yj.indices.push(idx); yj.depthByIndex[idx] = ci.depth; used[idx] = true; }
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
    /* workflows without needs still get a panel: a flat status grid */
    var flat = !edges.length;

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
    section.id = 'wg-pipeline';
    section.className = flat ? 'wg-pipeline wg-pipeline-flat' : 'wg-pipeline';
    if (localStorage.getItem('wg-pipeline-collapsed') === '1') section.classList.add('wg-collapsed');

    var header = document.createElement('div');
    header.className = 'wg-pipeline-header';
    header.innerHTML = '<span class="wg-caret">&#9662;</span>' +
      '<span class="wg-run-status wg-status-waiting"><span class="wg-node-dot"></span></span>' +
      '<span>Pipeline</span>' +
      '<span class="wg-pipeline-meta">' + run.jobs.length + ' jobs' + (flat ? '' : ' &middot; ' + stages.length + ' stages') + '</span>';
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
        if (run.prMode) {
          /* PR-mode rows come from the deduped tasks API, so bestIdx is NOT the
             run's real job index — map the constituent's name to the run's
             ordered job list (run.jobIndex, fetched from the run-view endpoint)
             for a per-job deep link; fall back to the bare run page. */
          var prName = (bestIdx !== -1 && run.jobs[bestIdx]) ? run.jobs[bestIdx].name : null;
          var direct = (prName != null && run.jobUrlByName) ? run.jobUrlByName[prName] : null;
          var mapped = (prName != null && run.jobIndex) ? run.jobIndex[prName] : null;
          el.href = direct || (mapped != null ? run.link + '/jobs/' + mapped : run.link);
        } else if (bestIdx !== -1) {
          el.href = run.link + '/jobs/' + bestIdx;
        }

        var metaEl = el.querySelector('.wg-node-meta');
        var dTxt = (bestDur > 0) ? durations[bestIdx] : '';
        /* This node is a single logical step in the parent workflow; when it
           expands to a reusable-workflow chain, flag the job count so the node
           reads as composite (the full ordered chain is in the tooltip). */
        var nestedTxt = (j.indices.length > 1) ? ' · ' + j.indices.length + ' jobs' : '';
        metaEl.textContent = st + (dTxt ? ' · ' + dTxt : '') + nestedTxt;

        var tip = j.label + ' · ' + st + (dTxt ? ' · ' + dTxt : '');
        if (j.indices.length > 1) {
          /* ordered by nesting depth so it reads as the real call chain:
             caller → its reusable → that reusable's reusable → … */
          var ordered = j.indices.slice().sort(function (a, b) {
            return (j.depthByIndex[a] || 0) - (j.depthByIndex[b] || 0);
          });
          tip += '\nreusable-workflow chain:\n' + ordered.map(function (idx) {
            var nm = run.jobs[idx] ? run.jobs[idx].name : railNameAt(idx);
            var d = j.depthByIndex[idx] || 0;
            var indent = new Array(d + 1).join('  ');
            var dur = durations[idx] ? ' ' + durations[idx] : '';
            return indent + (d ? '└ ' : '') + nm + ' [' + (statuses[idx] || '?') + dur + ']';
          }).join('\n');
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
          /* keep the caller (depth 0) first, then its descendants in nesting
             order, each indented by its true reusable-call depth so the chain
             reads Distribute > (Harbor,fast) > (Registry,fast), not siblings. */
          var ordered = j.indices.slice().sort(function (a, b) {
            return (j.depthByIndex[a] || 0) - (j.depthByIndex[b] || 0);
          });
          seq += 100;
          ordered.forEach(function (idx, k) {
            plan[idx] = { order: seq + k, depth: j.depthByIndex[idx] || 0 };
          });
        });
      });
      Array.prototype.forEach.call(items, function (item, idx) {
        var p = plan[idx];
        item.style.order = p ? p.order : 9000 + idx;
        if (p && p.depth) {
          item.setAttribute('data-wg-child', '');
          item.style.marginLeft = (p.depth * 20) + 'px';
        } else {
          item.removeAttribute('data-wg-child');
          item.style.marginLeft = '';
        }
      });
    }

    host.parentNode.insertBefore(section, host);
    apply(null);

    /* the rail is Vue-rendered a beat after DOMContentLoaded — retry the
       decoration briefly so finished runs (no 5s resync) still get grouped */
    if (!run.prMode) {
      var railTries = 0;
      var railWait = window.setInterval(function () {
        railTries++;
        var items = document.querySelectorAll('.action-view-left .job-brief-item');
        if (items.length || railTries > 20) {
          window.clearInterval(railWait);
          if (items.length) decorateRail();
        }
      }, 250);
    }

    window.addEventListener('resize', function () { window.requestAnimationFrame(draw); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { draw(); });

    if (!run.done && !run.prMode) {
      var timer = window.setInterval(function () {
        var read = railRead();
        if (read) apply(read);
        var allDone = read && read.every(function (r) {
          return r.status === 'success' || r.status === 'failure' || r.status === 'skipped' || r.status === 'cancelled' || r.status === 'unknown';
        });
        if (allDone) window.clearInterval(timer);
      }, 5000);
    }
    return apply;
  }

  function apiJSON(url) {
    return fetch(url, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function fmtSecs(s) {
    if (s <= 0) return '';
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60);
    return (h ? h + 'h' : '') + (h || m ? m + 'm' : '') + sec + 's';
  }

  var TERMINAL = { success: 1, failure: 1, skipped: 1, cancelled: 1, unknown: 1 };

  /* PR pages: an Actions tab + the same pipeline panel, driven by the tasks
     API for the PR head commit (session-cookie auth; task rows only exist for
     jobs that started — yaml-only jobs render as waiting). */
  function initPR() {
    var m = location.pathname.match(/^[/]([^/]+)[/]([^/]+)[/]pulls[/](\d+)/);
    if (!m) return;
    var base = '/' + m[1] + '/' + m[2];
    var prLink = base + '/pulls/' + m[3];
    var onConversation = new RegExp('^[/][^/]+[/][^/]+[/]pulls[/]\\d+$').test(location.pathname);
    var tab = null, tabDot = null;

    /* Exposed for debugging (window.__wgPipeline.pr): why the panel did/didn't
       render for this PR — head sha, what the task scan saw, commit-status. */
    var diag = { sha: null, taskHit: false, scan: null, commitStatus: null, reason: null };
    try { window.__wgPipeline = window.__wgPipeline || {}; window.__wgPipeline.pr = diag; } catch (e) { }

    function taskRows(tasks, sha) {
      var mine = tasks.filter(function (t) { return t.head_sha === sha; });
      if (!mine.length) return null;
      var maxRun = 0;
      mine.forEach(function (t) { if (t.run_number > maxRun) maxRun = t.run_number; });
      var group = mine.filter(function (t) { return t.run_number === maxRun; });
      var wf = group[0].workflow_id;
      var byName = Object.create(null);
      group.forEach(function (t) {
        if (!byName[t.name] || t.id > byName[t.name].id) byName[t.name] = t;
      });
      var rows = Object.keys(byName).map(function (k) {
        var t = byName[k];
        var dur = '';
        if (TERMINAL[t.status] && t.run_started_at && t.updated_at) {
          dur = fmtSecs((new Date(t.updated_at) - new Date(t.run_started_at)) / 1000);
        }
        return { name: t.name, status: t.status, duration: dur };
      });
      var runLink = base + '/actions/runs/' + maxRun;
      return { rows: rows, workflow: wf, runLink: runLink, runNumber: maxRun };
    }

    /* The tasks API returns newest-first and is NOT sha-filterable, so a run
       for an older head can sit past the first page on a busy repo. Page deeper
       (up to 300 rows) before giving up, and record what we scanned for diag. */
    var lastScan = { scanned: 0, total: 0 };
    function fetchTasks(sha) {
      var MAX_PAGES = 6;
      function page(p, acc) {
        return apiJSON('/api/v1/repos/' + m[1] + '/' + m[2] + '/actions/tasks?limit=50&page=' + p).then(function (r) {
          var all = acc.concat((r && r.workflow_runs) || []);
          lastScan = { scanned: all.length, total: (r && r.total_count) || 0 };
          var hit = taskRows(all, sha);
          if (hit) return hit;
          if (!r || all.length >= lastScan.total || p >= MAX_PAGES) return null;
          return page(p + 1, all);
        });
      }
      return page(1, []);
    }

    /* commit-status API is sha-keyed (no pagination gap) and sees a run as soon
       as it is created — the reliable "does this commit have a run" source.
       context is "<workflow> / <job> (<event>)"; target_url is the job's page. */
    function parseCtx(context) {
      var name = String(context || '').replace(/\s*\([^)]*\)\s*$/, '');
      var slash = name.lastIndexOf(' / ');
      return slash !== -1 ? name.slice(slash + 3) : name;
    }
    function mapCommitState(s) {
      if (s === 'success') return 'success';
      if (s === 'pending') return 'running';
      if (s === 'failure' || s === 'error' || s === 'warning') return 'failure';
      return 'waiting';
    }
    function fetchCommitStatus(sha) {
      return apiJSON('/api/v1/repos/' + m[1] + '/' + m[2] + '/commits/' + sha + '/status?limit=100').then(function (d) {
        if (!d) return null;
        var sts = d.statuses || [];
        var runNumber = null, rows = [], jobUrl = Object.create(null), seen = Object.create(null);
        sts.forEach(function (s) {
          var mm = String(s.target_url || '').match(/[/]actions[/]runs[/](\d+)/);
          if (mm && runNumber == null) runNumber = parseInt(mm[1], 10);
          var nm = parseCtx(s.context);
          if (nm && !seen[nm]) {
            seen[nm] = 1;
            rows.push({ name: nm, status: mapCommitState(s.status || s.state), duration: '' });
            jobUrl[nm] = s.target_url || null;
          }
        });
        return { state: d.state, count: sts.length, runNumber: runNumber, rows: rows, jobUrl: jobUrl };
      });
    }

    function tabStatus(rows) {
      var worst = '';
      rows.forEach(function (r) {
        if ((RANK[r.status] || 0) > (RANK[worst] || 0)) worst = r.status;
      });
      if (tabDot) tabDot.className = 'wg-run-status wg-status-' + (worst || 'waiting');
      return worst;
    }

    /* Ordered job list from the run-view data source (same one the run page
       uses) → name→index map, so PR-mode nodes can deep-link to the exact job.
       Best-effort: any failure leaves nodes on the bare run link. */
    function fetchRunJobIndex(runNumber) {
      var csrf = (window.config && window.config.csrfToken) || '';
      return fetch('/' + m[1] + '/' + m[2] + '/actions/runs/' + runNumber + '/jobs/0', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Csrf-Token': csrf }, body: '{}',
      }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        var jobs = d && d.state && d.state.run && d.state.run.jobs;
        if (!jobs) return null;
        var map = Object.create(null);
        jobs.forEach(function (jb, idx) {
          if (jb && jb.name != null && map[jb.name] == null) map[jb.name] = idx;
        });
        return map;
      }).catch(function () { return null; });
    }

    /* Remove any panel we inserted earlier so a re-render (e.g. a flat fallback
       upgrading to the full graph, or a pending-run repoll) never stacks. */
    function clearPriorPanel() {
      var ex = document.getElementById('wg-pipeline');
      if (ex && ex.parentNode) ex.parentNode.removeChild(ex);
    }

    /* Place the panel just ABOVE the merge box (GitHub-like); fall back to
       below the PR description, then to the top of the content. */
    function panelHost() {
      var container = document.querySelector('.ui.pull.tabs.container');
      var mergeBox = document.querySelector('.timeline-item.comment.merge.box');
      var first = document.querySelector('.issue-content-left .timeline-item.comment.first');
      return mergeBox
        || (first && first.nextElementSibling)
        || first
        || (container && container.nextElementSibling);
    }

    /* Full render: workflow YAML → DAG, tasks rows → status/duration, run-view
       index → per-job deep links. Used when the tasks list yields the run. */
    function render(sha, hit) {
      tabStatus(hit.rows);
      if (tab) tab.title = hit.workflow + ' · run #' + hit.runNumber;
      if (!onConversation) return;

      var dirs = ['.forgejo/workflows/', '.github/workflows/', '.gitea/workflows/'];
      Promise.all([
        fetchFirstOk(dirs.map(function (d) { return base + '/raw/commit/' + sha + '/' + d + hit.workflow; })),
        fetchRunJobIndex(hit.runNumber),
      ]).then(function (res) {
        var yaml = res[0], jobIndex = res[1];
        if (!yaml) return;
        var yjobs = parseWorkflowJobs(yaml);
        var targets = Object.create(null);
        yjobs.forEach(function (j) { if (j.uses) targets[j.uses] = null; });
        var selfRawBase = base + '/raw/commit/' + sha + '/.forgejo/workflows/';
        return Promise.all(Object.keys(targets).map(function (u) {
          return resolveDescendants(u, selfRawBase, 1, Object.create(null)).then(function (labels) {
            targets[u] = labels;
          });
        })).then(function () {
          yjobs.forEach(function (j) { if (j.uses) j.childItems = targets[j.uses] || []; });
          var host = panelHost();
          if (!host) return;
          var allDone = hit.rows.every(function (r) { return TERMINAL[r.status]; });
          var run = { link: hit.runLink, done: true, prMode: true, status: 'unknown', jobs: hit.rows, jobIndex: jobIndex, commit: {} };
          clearPriorPanel();
          var applyFn = build(host, run, yjobs);
          if (!applyFn || allDone) return;
          var poll = window.setInterval(function () {
            fetchTasks(sha).then(function (h2) {
              if (!h2) return;
              applyFn(h2.rows);
              if (h2.rows.every(function (r) { return TERMINAL[r.status]; }) && tabStatus(h2.rows)) {
                window.clearInterval(poll);
              } else {
                tabStatus(h2.rows);
              }
            });
          }, 15000);
        });
      });
    }

    /* Fallback render when the tasks list didn't surface the run but commit
       status did: a flat status grid straight from the commit statuses (one
       synthesized node per job so nothing renders as an orphan), with per-job
       deep links from each status's target_url. No DAG/durations, but visible. */
    function renderFlat(cs) {
      tabStatus(cs.rows);
      if (tab) { tab.title = 'run #' + cs.runNumber + ' · ' + cs.state; if (cs.runNumber) tab.href = base + '/actions/runs/' + cs.runNumber; }
      if (!onConversation || !cs.rows.length) return;
      var host = panelHost();
      if (!host) return;
      var yjobs = cs.rows.map(function (r) { return { id: r.name, label: r.name, needs: [], uses: null }; });
      var run = { link: base + '/actions/runs/' + cs.runNumber, done: true, prMode: true, status: 'unknown', jobs: cs.rows, jobUrlByName: cs.jobUrl, commit: {} };
      clearPriorPanel();
      build(host, run, yjobs);
    }

    /* Discovery: commit status is the source of truth for whether a run exists;
       tasks give the richer graph when reachable. Poll while a run is pending
       or not-yet-created (queued), then settle on an honest tab state. */
    function attempt(sha, tries) {
      Promise.all([fetchCommitStatus(sha), fetchTasks(sha)]).then(function (res) {
        var cs = res[0], hit = res[1];
        diag.commitStatus = cs;
        diag.scan = lastScan;
        if (hit) { diag.taskHit = true; diag.runNumber = hit.runNumber; diag.reason = 'rendered from tasks'; render(sha, hit); return; }
        if (cs && cs.count) {
          diag.runNumber = cs.runNumber;
          diag.reason = 'run #' + cs.runNumber + ' (' + cs.state + ') found via commit-status; not in ' + lastScan.scanned + '/' + lastScan.total + ' tasks scanned → flat render';
          renderFlat(cs);
          if (/pending|running/.test(cs.state || '') && tries < 40) {
            window.setTimeout(function () { attempt(sha, tries + 1); }, 15000);
          }
          return;
        }
        /* no run/check yet — could be queued pre-status; poll briefly then settle */
        if (tries < 6) {
          if (tab) tab.title = 'Waiting for a runner to pick up the run…';
          window.setTimeout(function () { attempt(sha, tries + 1); }, 15000);
          return;
        }
        diag.reason = 'no Actions run/check for this commit (' + sha.slice(0, 10) + ')';
        if (tab) tab.title = 'No Actions run for this commit';
        if (tabDot) tabDot.className = 'wg-run-status wg-status-skipped';
      });
    }

    function startData() {
      apiJSON('/api/v1/repos/' + m[1] + '/' + m[2] + '/pulls/' + m[3]).then(function (pr) {
        var sha = pr && pr.head && pr.head.sha;
        diag.sha = sha;
        if (!sha) { diag.reason = 'PR API returned no head sha'; return; }
        attempt(sha, 0);
      });
    }

    /* Inject the "Actions" tab. Forgejo's tab bar is Vue-rendered a beat after
       DOMContentLoaded, so retry briefly until the menu exists (mirrors the
       rail-decoration retry) — otherwise the tab intermittently never appears. */
    function ensureTab(tries) {
      var menu = document.querySelector('.ui.pull.tabs.container .tabular.menu');
      if (menu) {
        if (!menu.querySelector('.wg-pr-tab')) {
          tab = document.createElement('a');
          tab.className = 'item wg-pr-tab';
          tab.href = prLink + '#wg-pipeline';
          tab.innerHTML = '<span class="wg-run-status wg-status-waiting"><span class="wg-node-dot"></span></span>Actions';
          menu.insertBefore(tab, menu.querySelector('.tw-ml-auto'));
          tabDot = tab.querySelector('.wg-run-status');
        }
        return;
      }
      if (tries >= 20) return;
      window.setTimeout(function () { ensureTab(tries + 1); }, 250);
    }

    ensureTab(0);
    startData();
  }

  function init() {
    try {
      var host = document.getElementById('repo-action-view');
      if (!host) { initPR(); return; }
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
            return resolveDescendants(u, selfRawBase, 1, Object.create(null)).then(function (labels) {
              targets[u] = labels;
            });
          })).then(function () {
            yjobs.forEach(function (j) {
              if (j.uses) j.childItems = targets[j.uses] || [];
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
