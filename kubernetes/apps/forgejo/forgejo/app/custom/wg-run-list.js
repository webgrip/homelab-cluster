(function () {
  'use strict';

  var WG_RUN_LIST_VERSION = '1.0.0';
  var REQUEST_CONCURRENCY = 3;
  var CONFIRM_WINDOW_MS = 4000;
  var TOAST_MS = 6000;
  var CANCELLABLE = { running: 1, waiting: 1, blocked: 1 };
  var RERUNNABLE = { success: 1, failure: 1, cancelled: 1, skipped: 1 };
  var ICON_STATUS = [
    ['octicon-check-circle-fill', 'success'],
    ['octicon-x-circle-fill', 'failure'],
    ['octicon-skip', 'skipped'],
    ['octicon-stop', 'cancelled'],
    ['octicon-clock', 'waiting'],
    ['octicon-blocked', 'blocked'],
    ['octicon-meter', 'running'],
  ];
  var ICON_STOP = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M5.75 4h4.5c.966 0 1.75.784 1.75 1.75v4.5A1.75 1.75 0 0 1 10.25 12h-4.5A1.75 1.75 0 0 1 4 10.25v-4.5C4 4.784 4.784 4 5.75 4Z"/></svg>';
  var ICON_RERUN = '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z"/></svg>';
  var ACTIONS = {
    cancel: { endpoint: 'cancel', label: 'Stop', icon: ICON_STOP, eligible: CANCELLABLE, pastTense: 'Stopped' },
    rerun: { endpoint: 'rerun', label: 'Re-run', icon: ICON_RERUN, eligible: RERUNNABLE, pastTense: 'Re-ran' },
  };

  var selected = new Set();
  var busy = new Set();
  var lastToggledPath = null;
  var pendingConfirm = null;
  var focusKeyBeforeSwap = null;
  var bar = null;
  var liveRegion = null;
  var toastTimer = null;
  var decorateQueued = false;

  function runPathOf(row) {
    var link = row.querySelector('a.flex-item-title');
    if (!link) return null;
    var m = new URL(link.getAttribute('href'), location.href).pathname.match(/^(.*[/]actions[/]runs[/]\d+)/);
    return m ? m[1] : null;
  }

  function runNumberOf(path) {
    return path.slice(path.lastIndexOf('/') + 1);
  }

  function statusOf(row) {
    var leading = row.querySelector('.flex-item-leading');
    if (!leading) return 'unknown';
    for (var i = 0; i < ICON_STATUS.length; i++) {
      if (leading.querySelector('.' + ICON_STATUS[i][0])) return ICON_STATUS[i][1];
    }
    return 'unknown';
  }

  function actionFor(status) {
    if (CANCELLABLE[status]) return 'cancel';
    if (RERUNNABLE[status]) return 'rerun';
    return null;
  }

  function readRows() {
    return Array.prototype.slice.call(document.querySelectorAll('.run-list > .flex-item')).map(function (row) {
      var path = runPathOf(row);
      var status = statusOf(row);
      return { el: row, path: path, status: status === 'unknown' ? 'failure' : status };
    }).filter(function (r) { return r.path; });
  }

  function setIfChanged(el, prop, value) {
    if (el[prop] !== value) el[prop] = value;
  }

  function setAttrIfChanged(el, name, value) {
    if (value === null) {
      if (el.hasAttribute(name)) el.removeAttribute(name);
    } else if (el.getAttribute(name) !== value) {
      el.setAttribute(name, value);
    }
  }

  function ensureRowCheckbox(row) {
    var box = row.el.querySelector(':scope > .wg-run-select-cell input');
    if (!box) {
      var cell = document.createElement('label');
      cell.className = 'wg-run-select-cell';
      box = document.createElement('input');
      box.type = 'checkbox';
      box.className = 'wg-run-select';
      box.setAttribute('data-wg-focus', 'select:' + row.path);
      box.setAttribute('aria-label', 'Select run #' + runNumberOf(row.path));
      cell.appendChild(box);
      row.el.insertBefore(cell, row.el.firstChild);
    }
    box.dataset.wgPath = row.path;
    setIfChanged(box, 'checked', selected.has(row.path));
  }

  function ensureRowButton(row) {
    var trailing = row.el.querySelector(':scope > .flex-item-trailing');
    if (!trailing) return;
    var kind = actionFor(row.status);
    var button = trailing.querySelector(':scope > .wg-run-action');
    if (!kind) {
      if (button) button.remove();
      return;
    }
    if (!button) {
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'wg-run-action';
      trailing.insertBefore(button, trailing.firstChild);
    }
    var action = ACTIONS[kind];
    if (button.dataset.wgAction !== kind) {
      button.dataset.wgAction = kind;
      button.innerHTML = action.icon + '<span>' + action.label + '</span>';
      button.setAttribute('data-wg-focus', 'action:' + row.path);
      button.setAttribute('aria-label', action.label + ' run #' + runNumberOf(row.path));
    }
    button.dataset.wgPath = row.path;
    setIfChanged(button, 'disabled', busy.has(row.path));
  }

  function ensureHead(rows) {
    var list = document.querySelector('.run-list');
    if (!list) return;
    var head = list.previousElementSibling;
    if (!head || !head.classList.contains('wg-run-list-head')) {
      head = document.createElement('div');
      head.className = 'wg-run-list-head';
      head.innerHTML =
        '<label class="wg-run-select-cell"><input type="checkbox" class="wg-run-select-all" data-wg-focus="select-all" aria-label="Select all runs on this page"></label>' +
        '<span class="wg-run-head-label">Select</span>' +
        '<button type="button" class="wg-run-quick" data-wg-quick="all" data-wg-focus="quick:all">All</button>' +
        '<button type="button" class="wg-run-quick" data-wg-quick="active" data-wg-focus="quick:active">Active</button>' +
        '<button type="button" class="wg-run-quick" data-wg-quick="failure" data-wg-focus="quick:failure">Failed</button>' +
        '<button type="button" class="wg-run-quick" data-wg-quick="cancelled" data-wg-focus="quick:cancelled">Cancelled</button>';
      list.parentNode.insertBefore(head, list);
    }
    var all = head.querySelector('.wg-run-select-all');
    var picked = rows.filter(function (r) { return selected.has(r.path); }).length;
    setIfChanged(all, 'checked', rows.length > 0 && picked === rows.length);
    setIfChanged(all, 'indeterminate', picked > 0 && picked < rows.length);
    setIfChanged(all, 'disabled', rows.length === 0);
    var counts = { all: rows.length, active: 0, failure: 0, cancelled: 0 };
    rows.forEach(function (r) {
      if (CANCELLABLE[r.status]) counts.active++;
      if (r.status === 'failure') counts.failure++;
      if (r.status === 'cancelled') counts.cancelled++;
    });
    Array.prototype.forEach.call(head.querySelectorAll('.wg-run-quick'), function (b) {
      var n = counts[b.dataset.wgQuick];
      setAttrIfChanged(b, 'data-wg-count', String(n));
      setIfChanged(b, 'disabled', n === 0);
    });
  }

  function pruneSelection(rows) {
    var present = new Set(rows.map(function (r) { return r.path; }));
    selected.forEach(function (p) { if (!present.has(p)) selected.delete(p); });
  }

  function decorate() {
    decorateQueued = false;
    var rows = readRows();
    pruneSelection(rows);
    rows.forEach(function (row) {
      ensureRowCheckbox(row);
      ensureRowButton(row);
      setAttrIfChanged(row.el, 'data-wg-selected', selected.has(row.path) ? '1' : null);
      setAttrIfChanged(row.el, 'data-wg-busy', busy.has(row.path) ? '1' : null);
    });
    ensureHead(rows);
    renderBar(rows);
  }

  function queueDecorate() {
    if (decorateQueued) return;
    decorateQueued = true;
    Promise.resolve().then(decorate);
  }

  function eligibleSelection(rows, kind) {
    return rows.filter(function (r) {
      return selected.has(r.path) && !busy.has(r.path) && ACTIONS[kind].eligible[r.status];
    });
  }

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement('div');
    bar.className = 'wg-run-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Bulk run actions');
    bar.hidden = true;
    bar.innerHTML =
      '<span class="wg-run-bar-count"></span>' +
      '<button type="button" class="wg-run-bar-action" data-wg-bulk="cancel">' + ICON_STOP + '<span></span></button>' +
      '<button type="button" class="wg-run-bar-action" data-wg-bulk="rerun">' + ICON_RERUN + '<span></span></button>' +
      '<button type="button" class="wg-run-bar-clear">Clear</button>';
    document.body.appendChild(bar);
    bar.addEventListener('click', onBarClick);
    return bar;
  }

  function renderBar(rows) {
    ensureBar();
    var count = selected.size;
    bar.hidden = count === 0;
    if (count === 0) return;
    bar.querySelector('.wg-run-bar-count').textContent = count + ' selected';
    Object.keys(ACTIONS).forEach(function (kind) {
      var button = bar.querySelector('[data-wg-bulk="' + kind + '"]');
      var n = eligibleSelection(rows, kind).length;
      var confirming = pendingConfirm && pendingConfirm.kind === kind;
      button.querySelector('span').textContent = confirming
        ? 'Confirm ' + ACTIONS[kind].label.toLowerCase() + ' ' + n
        : ACTIONS[kind].label + ' ' + n;
      setAttrIfChanged(button, 'data-wg-confirming', confirming ? '1' : null);
      setIfChanged(button, 'disabled', n === 0);
    });
  }

  function ensureLiveRegion() {
    if (liveRegion) return liveRegion;
    liveRegion = document.createElement('div');
    liveRegion.className = 'wg-run-toast';
    liveRegion.setAttribute('role', 'status');
    liveRegion.setAttribute('aria-live', 'polite');
    document.body.appendChild(liveRegion);
    return liveRegion;
  }

  function announce(message, isError) {
    ensureLiveRegion();
    liveRegion.textContent = message;
    liveRegion.setAttribute('data-wg-error', isError ? '1' : '0');
    liveRegion.setAttribute('data-wg-visible', '1');
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { liveRegion.setAttribute('data-wg-visible', '0'); }, TOAST_MS);
  }

  function errorMessageFrom(response) {
    return response.text().then(function (text) {
      var message = null;
      try { message = JSON.parse(text).errorMessage; } catch (e) { }
      if (message) return message;
      if (response.status === 403 || response.status === 404) return 'no permission to change runs here';
      return 'HTTP ' + response.status;
    });
  }

  function postRunAction(path, kind) {
    var csrf = (window.config && window.config.csrfToken) || '';
    return fetch(path + '/' + ACTIONS[kind].endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-Csrf-Token': csrf, Accept: 'application/json' },
    }).then(function (response) {
      if (response.ok) return { path: path, ok: true };
      return errorMessageFrom(response).then(function (message) { return { path: path, ok: false, message: message }; });
    }, function (e) {
      return { path: path, ok: false, message: String((e && e.message) || e) };
    });
  }

  function inPool(items, worker, limit) {
    var next = 0;
    var results = new Array(items.length);
    function pull() {
      if (next >= items.length) return Promise.resolve();
      var k = next++;
      return worker(items[k]).then(function (r) { results[k] = r; return pull(); });
    }
    var lanes = [];
    for (var i = 0; i < Math.min(limit, items.length); i++) lanes.push(pull());
    return Promise.all(lanes).then(function () { return results; });
  }

  function refreshList() {
    document.dispatchEvent(new Event('simulate-polling-interval'));
  }

  function summarize(kind, results) {
    var ok = results.filter(function (r) { return r.ok; });
    var failed = results.filter(function (r) { return !r.ok; });
    var parts = [];
    if (ok.length) parts.push(ACTIONS[kind].pastTense + ' ' + ok.length + (ok.length === 1 ? ' run' : ' runs'));
    if (failed.length) {
      var reasons = {};
      failed.forEach(function (r) { reasons[r.message] = (reasons[r.message] || []).concat('#' + runNumberOf(r.path)); });
      Object.keys(reasons).forEach(function (m) { parts.push(reasons[m].join(', ') + ' failed: ' + m); });
    }
    announce(parts.join(' · '), failed.length > 0);
  }

  function perform(kind, paths) {
    if (!paths.length) return Promise.resolve([]);
    paths.forEach(function (p) { busy.add(p); });
    queueDecorate();
    return inPool(paths, function (p) { return postRunAction(p, kind); }, REQUEST_CONCURRENCY).then(function (results) {
      results.forEach(function (r) {
        busy.delete(r.path);
        if (r.ok) selected.delete(r.path);
      });
      summarize(kind, results);
      queueDecorate();
      refreshList();
      return results;
    });
  }

  function clearConfirm() {
    if (pendingConfirm) window.clearTimeout(pendingConfirm.timer);
    pendingConfirm = null;
  }

  function onBarClick(e) {
    var clear = e.target.closest('.wg-run-bar-clear');
    if (clear) {
      clearConfirm();
      selected.clear();
      queueDecorate();
      return;
    }
    var button = e.target.closest('[data-wg-bulk]');
    if (!button || button.disabled) return;
    var kind = button.dataset.wgBulk;
    var targets = eligibleSelection(readRows(), kind).map(function (r) { return r.path; });
    if (targets.length > 1 && !(pendingConfirm && pendingConfirm.kind === kind)) {
      clearConfirm();
      pendingConfirm = { kind: kind, timer: window.setTimeout(function () { pendingConfirm = null; queueDecorate(); }, CONFIRM_WINDOW_MS) };
      queueDecorate();
      return;
    }
    clearConfirm();
    perform(kind, targets);
  }

  function toggleRange(rows, fromPath, toPath, checked) {
    var paths = rows.map(function (r) { return r.path; });
    var a = paths.indexOf(fromPath);
    var b = paths.indexOf(toPath);
    if (a === -1 || b === -1) return false;
    paths.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (p) {
      if (checked) selected.add(p); else selected.delete(p);
    });
    return true;
  }

  function onRowSelectClick(box, shiftKey) {
    var path = box.dataset.wgPath;
    clearConfirm();
    if (!(shiftKey && lastToggledPath && toggleRange(readRows(), lastToggledPath, path, box.checked))) {
      if (box.checked) selected.add(path); else selected.delete(path);
    }
    lastToggledPath = path;
    queueDecorate();
  }

  function selectWhere(predicate) {
    clearConfirm();
    selected.clear();
    readRows().forEach(function (r) { if (predicate(r)) selected.add(r.path); });
    queueDecorate();
  }

  var QUICK = {
    all: function () { return true; },
    active: function (r) { return CANCELLABLE[r.status]; },
    failure: function (r) { return r.status === 'failure'; },
    cancelled: function (r) { return r.status === 'cancelled'; },
  };

  function onDocumentClick(e) {
    var box = e.target.closest('.run-list .wg-run-select');
    if (box) { onRowSelectClick(box, e.shiftKey); return; }
    var all = e.target.closest('.wg-run-select-all');
    if (all) { selectWhere(all.checked ? QUICK.all : function () { return false; }); return; }
    var quick = e.target.closest('.wg-run-quick');
    if (quick) { selectWhere(QUICK[quick.dataset.wgQuick]); return; }
    var action = e.target.closest('.run-list .wg-run-action');
    if (action && !action.disabled) {
      e.preventDefault();
      perform(action.dataset.wgAction, [action.dataset.wgPath]);
    }
  }

  function onKeydown(e) {
    if (e.key !== 'Escape' || selected.size === 0) return;
    if (e.target.closest && e.target.closest('input[type="text"], textarea, [contenteditable="true"]')) return;
    clearConfirm();
    selected.clear();
    queueDecorate();
  }

  function rememberFocus() {
    var el = document.activeElement;
    focusKeyBeforeSwap = el && el.getAttribute ? el.getAttribute('data-wg-focus') : null;
  }

  function restoreFocus() {
    if (!focusKeyBeforeSwap) return;
    var key = focusKeyBeforeSwap;
    focusKeyBeforeSwap = null;
    var target = Array.prototype.find.call(document.querySelectorAll('[data-wg-focus]'), function (el) {
      return el.getAttribute('data-wg-focus') === key;
    });
    if (target && document.activeElement !== target) target.focus({ preventScroll: true });
  }

  function isSignedIn() {
    return !!document.querySelector('#navbar a[href$="/notifications"], #mobile-notifications-icon');
  }

  function init() {
    if (!/^[/][^/]+[/][^/]+[/]actions[/]?$/.test(location.pathname)) return;
    if (!document.querySelector('.run-list') || !isSignedIn()) return;
    try {
      window.__wgRunList = {
        version: WG_RUN_LIST_VERSION,
        selected: selected,
        busy: busy,
        decorate: decorate,
        internals: { actionFor: actionFor, statusOf: statusOf, runPathOf: runPathOf, inPool: inPool },
      };
    } catch (e) { }
    document.addEventListener('click', onDocumentClick);
    document.addEventListener('keydown', onKeydown);
    document.body.addEventListener('htmx:beforeSwap', rememberFocus);
    document.body.addEventListener('htmx:afterSettle', function () { decorate(); restoreFocus(); });
    var container = document.querySelector('.page-content.actions') || document.body;
    new MutationObserver(function (mutations) {
      var foreign = mutations.some(function (m) {
        return !(m.target.closest && m.target.closest('.wg-run-select-cell, .wg-run-action, .wg-run-list-head'));
      });
      if (foreign) queueDecorate();
    }).observe(container, { childList: true, subtree: true });
    decorate();
  }

  try {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  } catch (e) {
    console.debug('[wg-run-list]', e);
  }
})();
