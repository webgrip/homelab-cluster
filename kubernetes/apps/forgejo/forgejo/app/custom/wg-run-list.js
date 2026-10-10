(function () {
  'use strict';

  var WG_RUN_LIST_VERSION = '4.0.0';
  var REQUEST_CONCURRENCY = 3;
  var CONFIRM_WINDOW_MS = 4000;
  var CONFIRM_ARM_GUARD_MS = 400;
  var SUCCESS_TOAST_MS = 4000;
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
  var ICON_STOP = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M5.75 4h4.5c.966 0 1.75.784 1.75 1.75v4.5A1.75 1.75 0 0 1 10.25 12h-4.5A1.75 1.75 0 0 1 4 10.25v-4.5C4 4.784 4.784 4 5.75 4Z"/></svg>';
  var ICON_RERUN = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M1.705 8.005a.75.75 0 0 1 .834.656 5.5 5.5 0 0 0 9.592 2.97l-1.204-1.204a.25.25 0 0 1 .177-.427h3.646a.25.25 0 0 1 .25.25v3.646a.25.25 0 0 1-.427.177l-1.38-1.38A7.002 7.002 0 0 1 1.05 8.84a.75.75 0 0 1 .656-.834ZM8 2.5a5.487 5.487 0 0 0-4.131 1.869l1.204 1.204A.25.25 0 0 1 4.896 6H1.25A.25.25 0 0 1 1 5.75V2.104a.25.25 0 0 1 .427-.177l1.38 1.38A7.002 7.002 0 0 1 14.95 7.16a.75.75 0 0 1-1.49.178A5.5 5.5 0 0 0 8 2.5Z"/></svg>';
  var ICON_CLOSE = '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M3.72 3.72a.75.75 0 0 1 1.06 0L8 6.94l3.22-3.22a.749.749 0 0 1 1.275.326.749.749 0 0 1-.215.734L9.06 8l3.22 3.22a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L8 9.06l-3.22 3.22a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042L6.94 8 3.72 4.78a.75.75 0 0 1 0-1.06Z"/></svg>';
  var ACTIONS = {
    cancel: { endpoint: 'cancel', verb: 'Stop', icon: ICON_STOP, eligible: CANCELLABLE, pastTense: 'Stopped', confirmsBulk: true },
    rerun: { endpoint: 'rerun', verb: 'Re-run', icon: ICON_RERUN, eligible: RERUNNABLE, pastTense: 'Re-running', confirmsBulk: false },
  };
  var ICON_CARET = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="m4.427 7.427 3.396 3.396a.25.25 0 0 0 .354 0l3.396-3.396A.25.25 0 0 0 11.396 7H4.604a.25.25 0 0 0-.177.427Z"/></svg>';
  var QUICK = [
    { key: 'all', label: 'All on this page', test: function () { return true; } },
    { key: 'active', label: 'Running', test: function (r) { return !!CANCELLABLE[r.status]; } },
    { key: 'failure', label: 'Failed', test: function (r) { return r.status === 'failure'; } },
    { key: 'cancelled', label: 'Cancelled', test: function (r) { return r.status === 'cancelled'; } },
    { key: 'finished', label: 'All finished', test: function (r) { return !!RERUNNABLE[r.status]; } },
  ];
  var OWN_NODES = '.wg-run-check, .wg-run-slot, .wg-run-tools, .wg-row-error';

  var selected = new Set();
  var busy = new Set();
  var failures = new Map();
  var menuOpen = false;
  var lastToggledPath = null;
  var pendingConfirm = null;
  var focusKeyBeforeSwap = null;
  var bar = null;
  var toast = null;
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
    if (!leading) return 'failure';
    for (var i = 0; i < ICON_STATUS.length; i++) {
      if (leading.querySelector('.' + ICON_STATUS[i][0])) return ICON_STATUS[i][1];
    }
    return 'failure';
  }

  function actionFor(status) {
    if (CANCELLABLE[status]) return 'cancel';
    if (RERUNNABLE[status]) return 'rerun';
    return null;
  }

  function readRows() {
    return Array.prototype.slice.call(document.querySelectorAll('.run-list > .flex-item')).map(function (row) {
      return { el: row, path: runPathOf(row), status: statusOf(row) };
    }).filter(function (r) { return r.path; });
  }

  function plural(n, word) {
    return n + ' ' + word + (n === 1 ? '' : 's');
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

  function el(tag, className, html) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (html) node.innerHTML = html;
    return node;
  }

  function ensureRowCheckbox(row) {
    var box = row.el.querySelector(':scope > .wg-run-check input');
    if (!box) {
      var cell = el('label', 'wg-run-check');
      box = el('input', 'wg-checkbox');
      box.type = 'checkbox';
      box.setAttribute('data-wg-focus', 'select:' + row.path);
      cell.appendChild(box);
      row.el.insertBefore(cell, row.el.firstChild);
    }
    box.dataset.wgPath = row.path;
    setAttrIfChanged(box, 'aria-label', 'Select run #' + runNumberOf(row.path) + ', ' + row.status);
    setIfChanged(box, 'checked', selected.has(row.path));
  }

  function ensureRowAction(row) {
    var slot = row.el.querySelector(':scope > .wg-run-slot');
    if (!slot) {
      slot = el('div', 'wg-run-slot');
      row.el.appendChild(slot);
    }
    var kind = actionFor(row.status);
    var button = slot.querySelector('button');
    if (!kind) {
      if (button) button.remove();
      return;
    }
    if (!button) {
      button = el('button', 'wg-row-action');
      button.type = 'button';
      slot.appendChild(button);
    }
    if (button.dataset.wgAction !== kind) {
      var label = ACTIONS[kind].verb + ' run #' + runNumberOf(row.path);
      button.dataset.wgAction = kind;
      button.innerHTML = ACTIONS[kind].icon + '<span class="wg-row-action-label">' + ACTIONS[kind].verb + '</span>';
      button.setAttribute('aria-label', label);
      button.setAttribute('data-wg-focus', 'action:' + row.path);
    }
    button.dataset.wgPath = row.path;
    setAttrIfChanged(button, 'aria-busy', busy.has(row.path) ? 'true' : null);
  }

  function ensureTools(rows) {
    var menu = document.querySelector('.ui.secondary.filter.menu');
    if (!menu) return;
    var tools = menu.querySelector(':scope > .wg-run-tools');
    if (!tools) {
      tools = el('div', 'wg-run-tools');
      var allLabel = el('label', 'wg-run-check-all');
      var all = el('input', 'wg-checkbox wg-select-all');
      all.type = 'checkbox';
      all.setAttribute('data-wg-focus', 'select-all');
      all.setAttribute('aria-label', 'Select all runs on this page');
      allLabel.appendChild(all);
      tools.appendChild(allLabel);
      var toggle = el('button', 'wg-select-menu-toggle', ICON_CARET);
      toggle.type = 'button';
      toggle.setAttribute('aria-haspopup', 'menu');
      toggle.setAttribute('aria-label', 'Select by status');
      toggle.setAttribute('data-wg-focus', 'select-menu');
      tools.appendChild(toggle);
      var popup = el('div', 'wg-select-menu');
      popup.setAttribute('role', 'menu');
      QUICK.forEach(function (q) {
        var item = el('button', 'wg-select-menu-item', '<span>' + q.label + '</span><span class="wg-select-menu-count"></span>');
        item.type = 'button';
        item.setAttribute('role', 'menuitem');
        item.dataset.wgQuick = q.key;
        item.setAttribute('data-wg-focus', 'quick:' + q.key);
        popup.appendChild(item);
      });
      tools.appendChild(popup);
      tools.appendChild(el('span', 'wg-run-tools-label'));
      menu.insertBefore(tools, menu.firstChild);
    }
    var all2 = tools.querySelector('.wg-select-all');
    var picked = rows.filter(function (r) { return selected.has(r.path); }).length;
    setIfChanged(all2, 'checked', rows.length > 0 && picked === rows.length);
    setIfChanged(all2, 'indeterminate', picked > 0 && picked < rows.length);
    setAttrIfChanged(tools.querySelector('.wg-select-menu-toggle'), 'aria-expanded', menuOpen ? 'true' : 'false');
    setIfChanged(tools.querySelector('.wg-select-menu'), 'hidden', !menuOpen);
    QUICK.forEach(function (q) {
      var item = tools.querySelector('[data-wg-quick="' + q.key + '"]');
      var n = rows.filter(q.test).length;
      var count = item.querySelector('.wg-select-menu-count');
      if (count.textContent !== String(n)) count.textContent = String(n);
      setIfChanged(item, 'disabled', n === 0);
    });
    var label = tools.querySelector('.wg-run-tools-label');
    var text = picked ? picked + ' of ' + plural(rows.length, 'run') + ' selected' : plural(rows.length, 'run');
    if (label.textContent !== text) label.textContent = text;
  }

  function setMenuOpen(open) {
    menuOpen = open;
    decorate();
    if (open) {
      var first = document.querySelector('.wg-select-menu-item:not(:disabled)');
      if (first) first.focus();
    }
  }

  function ensureRowError(row) {
    var main = row.el.querySelector(':scope > .flex-item-main');
    if (!main) return;
    var failure = failures.get(row.path);
    if (failure && failure.status !== row.status) {
      failures.delete(row.path);
      failure = null;
    }
    var badge = main.querySelector(':scope > .wg-row-error');
    if (!failure) {
      if (badge) badge.remove();
      return;
    }
    if (!badge) {
      badge = el('div', 'wg-row-error');
      badge.setAttribute('role', 'note');
      main.appendChild(badge);
    }
    var text = 'Could not ' + ACTIONS[failure.kind].verb.toLowerCase() + ': ' + failure.message;
    if (badge.textContent !== text) badge.textContent = text;
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
      ensureRowAction(row);
      ensureRowError(row);
      setAttrIfChanged(row.el, 'data-wg-failed', failures.has(row.path) ? '1' : null);
      setAttrIfChanged(row.el, 'data-wg-selected', selected.has(row.path) ? '1' : null);
      setAttrIfChanged(row.el, 'data-wg-busy', busy.has(row.path) ? '1' : null);
    });
    setAttrIfChanged(document.documentElement, 'data-wg-selecting', selected.size ? '1' : null);
    ensureTools(rows);
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
    bar = el('div', 'wg-bulk-bar');
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', 'Selected runs');
    bar.hidden = true;
    bar.innerHTML =
      '<button type="button" class="wg-icon-button wg-bulk-clear" aria-label="Clear selection" data-tooltip-content="Clear selection (Esc)">' + ICON_CLOSE + '</button>' +
      '<span class="wg-bulk-count"></span>' +
      '<span class="wg-bulk-divider" aria-hidden="true"></span>' +
      '<button type="button" class="wg-bulk-action" data-wg-bulk="cancel">' + ICON_STOP + '<span></span></button>' +
      '<button type="button" class="wg-bulk-action" data-wg-bulk="rerun">' + ICON_RERUN + '<span></span></button>' +
      '<span class="wg-bulk-none">Nothing here can be stopped or re-run</span>';
    document.body.appendChild(bar);
    bar.addEventListener('click', onBarClick);
    return bar;
  }

  function renderBar(rows) {
    ensureBar();
    var count = selected.size;
    setIfChanged(bar, 'hidden', count === 0);
    if (count === 0) return;
    bar.querySelector('.wg-bulk-count').textContent = count + ' selected';
    var anyEligible = false;
    Object.keys(ACTIONS).forEach(function (kind) {
      var button = bar.querySelector('[data-wg-bulk="' + kind + '"]');
      var n = eligibleSelection(rows, kind).length;
      var confirming = !!(pendingConfirm && pendingConfirm.kind === kind);
      anyEligible = anyEligible || n > 0;
      button.querySelector('span').textContent = confirming
        ? ACTIONS[kind].verb + ' ' + plural(n, 'run') + '?'
        : ACTIONS[kind].verb + ' ' + n;
      setIfChanged(button, 'hidden', n === 0);
      setAttrIfChanged(button, 'data-wg-confirming', confirming ? '1' : null);
    });
    setIfChanged(bar.querySelector('.wg-bulk-none'), 'hidden', anyEligible);
  }

  function ensureToast() {
    if (toast) return toast;
    toast = el('div', 'wg-toast');
    toast.setAttribute('role', 'status');
    toast.setAttribute('aria-live', 'polite');
    toast.innerHTML = '<span class="wg-toast-text"></span><button type="button" class="wg-icon-button wg-toast-close" aria-label="Dismiss">' + ICON_CLOSE + '</button>';
    toast.querySelector('.wg-toast-close').addEventListener('click', hideToast);
    document.body.appendChild(toast);
    return toast;
  }

  function hideToast() {
    if (toast) toast.removeAttribute('data-wg-visible');
  }

  function announce(message, isError) {
    ensureToast();
    toast.querySelector('.wg-toast-text').textContent = message;
    setAttrIfChanged(toast, 'data-wg-error', isError ? '1' : null);
    toast.setAttribute('data-wg-visible', '1');
    window.clearTimeout(toastTimer);
    if (!isError) toastTimer = window.setTimeout(hideToast, SUCCESS_TOAST_MS);
  }

  function errorMessageFrom(response) {
    return response.text().then(function (text) {
      var message = null;
      try { message = JSON.parse(text).errorMessage; } catch (e) { }
      if (message) return message;
      if (response.status === 403 || response.status === 404) return 'you lack write access to Actions here';
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
    var verb = ACTIONS[kind].verb.toLowerCase();
    if (!failed.length) {
      announce(ACTIONS[kind].pastTense + ' ' + (ok.length === 1 ? 'run #' + runNumberOf(ok[0].path) : plural(ok.length, 'run')), false);
      return;
    }
    if (results.length === 1) {
      announce('Could not ' + verb + ' run #' + runNumberOf(failed[0].path) + ': ' + failed[0].message, true);
      return;
    }
    var lead = ok.length ? ACTIONS[kind].pastTense + ' ' + ok.length + ' of ' + results.length + '. ' : '';
    var who = failed.length === 1
      ? 'Run #' + runNumberOf(failed[0].path) + ' could not ' + verb + "; it is marked below and still selected."
      : plural(failed.length, 'run') + ' could not ' + verb + '; they are marked below and still selected.';
    announce(lead + who, true);
  }

  function perform(kind, paths) {
    if (!paths.length) return Promise.resolve([]);
    hideToast();
    paths.forEach(function (p) { busy.add(p); });
    queueDecorate();
    return inPool(paths, function (p) { return postRunAction(p, kind); }, REQUEST_CONCURRENCY).then(function (results) {
      var statusByPath = {};
      readRows().forEach(function (row) { statusByPath[row.path] = row.status; });
      results.forEach(function (r) {
        busy.delete(r.path);
        if (r.ok) {
          selected.delete(r.path);
          failures.delete(r.path);
        } else {
          failures.set(r.path, { kind: kind, message: r.message, status: statusByPath[r.path] });
        }
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

  function clearSelection() {
    clearConfirm();
    selected.clear();
    queueDecorate();
  }

  function onBarClick(e) {
    if (e.target.closest('.wg-bulk-clear')) { clearSelection(); return; }
    var button = e.target.closest('[data-wg-bulk]');
    if (!button) return;
    var kind = button.dataset.wgBulk;
    var targets = eligibleSelection(readRows(), kind).map(function (r) { return r.path; });
    if (pendingConfirm && pendingConfirm.kind === kind && Date.now() - pendingConfirm.armedAt < CONFIRM_ARM_GUARD_MS) return;
    if (ACTIONS[kind].confirmsBulk && targets.length > 1 && !(pendingConfirm && pendingConfirm.kind === kind)) {
      clearConfirm();
      pendingConfirm = {
        kind: kind,
        armedAt: Date.now(),
        timer: window.setTimeout(function () { pendingConfirm = null; queueDecorate(); }, CONFIRM_WINDOW_MS),
      };
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

  function onRowCheckboxClick(box, shiftKey) {
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

  function onDocumentClick(e) {
    var box = e.target.closest('.run-list .wg-checkbox');
    if (box) { onRowCheckboxClick(box, e.shiftKey); return; }
    var all = e.target.closest('.wg-select-all');
    if (all) { selectWhere(function () { return all.checked; }); return; }
    if (e.target.closest('.wg-select-menu-toggle')) { setMenuOpen(!menuOpen); return; }
    var item = e.target.closest('.wg-select-menu-item');
    if (item) {
      var quick = QUICK.filter(function (q) { return q.key === item.dataset.wgQuick; })[0];
      menuOpen = false;
      selectWhere(quick.test);
      var toggle = document.querySelector('.wg-select-menu-toggle');
      if (toggle) toggle.focus();
      return;
    }
    if (menuOpen && !e.target.closest('.wg-select-menu')) { menuOpen = false; queueDecorate(); }
    var action = e.target.closest('.run-list .wg-run-slot button');
    if (action && action.getAttribute('aria-busy') !== 'true') {
      e.preventDefault();
      perform(action.dataset.wgAction, [action.dataset.wgPath]);
    }
  }

  function onKeydown(e) {
    if (menuOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      var items = Array.prototype.slice.call(document.querySelectorAll('.wg-select-menu-item:not(:disabled)'));
      var at = items.indexOf(document.activeElement);
      var next = items[(at + (e.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length];
      if (next) { e.preventDefault(); next.focus(); }
      return;
    }
    if (e.key !== 'Escape') return;
    if (e.target.closest && e.target.closest('input[type="text"], textarea, [contenteditable="true"]')) return;
    if (menuOpen) {
      menuOpen = false;
      decorate();
      var toggle = document.querySelector('.wg-select-menu-toggle');
      if (toggle) toggle.focus();
      return;
    }
    if (pendingConfirm) { clearConfirm(); queueDecorate(); return; }
    if (selected.size) clearSelection();
  }

  function rememberFocus() {
    var active = document.activeElement;
    focusKeyBeforeSwap = active && active.getAttribute ? active.getAttribute('data-wg-focus') : null;
  }

  function restoreFocus() {
    if (!focusKeyBeforeSwap) return;
    var key = focusKeyBeforeSwap;
    focusKeyBeforeSwap = null;
    var target = Array.prototype.find.call(document.querySelectorAll('[data-wg-focus]'), function (node) {
      return node.getAttribute('data-wg-focus') === key;
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
        return !(m.target.closest && m.target.closest(OWN_NODES));
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
