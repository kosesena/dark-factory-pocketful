/* Pocketful browser app: vanilla JS, client-rendered per route. No network beyond this origin. */
(function () {
  'use strict';
  const TOKEN_KEY = 'pf_token';
  const path = location.pathname.replace(/\/+$/, '') || '/';
  const PUBLIC = path === '/login' || path === '/signup';
  const S = { token: localStorage.getItem(TOKEN_KEY), me: null };
  const CFG = { currency: 'EUR', mu: 2 };
  const app = document.getElementById('app');

  /* ---------- helpers ---------- */
  function h(tag, props, ...kids) {
    const e = document.createElement(tag);
    if (props) for (const [k, v] of Object.entries(props)) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v;
      else if (k === 't') e.setAttribute('data-testid', v);
      else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : String(v));
    }
    for (const c of kids.flat()) {
      if (c == null || c === false) continue;
      e.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return e;
  }
  function uid() {
    const a = new Uint8Array(16);
    (window.crypto || {}).getRandomValues ? crypto.getRandomValues(a) : a.forEach((_, i) => a[i] = Math.random() * 256);
    return Array.from(a, b => b.toString(16).padStart(2, '0')).join('');
  }
  function fmtDecimal(n) {
    const mu = CFG.mu; let s = String(n);
    if (mu === 0) return s;
    s = s.padStart(mu + 1, '0');
    return s.slice(0, -mu) + '.' + s.slice(-mu);
  }
  function fmt(n, cur) { return fmtDecimal(n) + ' ' + (cur || CFG.currency); }
  /* decimal text -> minor units, or an error message (nothing is rounded) */
  function parseAmount(text) {
    const t = String(text).trim();
    const m = /^(\d+)(?:\.(\d+))?$/.exec(t);
    if (!m) return { error: 'Enter an amount as a number, like ' + (CFG.mu ? '15.00' : '15') + '.' };
    const frac = m[2] || '';
    if (frac.length > CFG.mu) {
      return { error: CFG.mu === 0 ? 'This currency has no decimals; enter a whole number.'
        : 'Use at most ' + CFG.mu + ' decimal places.' };
    }
    const digits = (m[1] + frac.padEnd(CFG.mu, '0')).replace(/^0+(?=\d)/, '');
    const n = Number(digits);
    if (n < 1) return { error: 'Enter an amount greater than zero.' };
    return { minor: n };
  }
  function fmtTime(iso) {
    const d = new Date(iso);
    return isNaN(d) ? iso : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  }
  function until(iso) {
    const s = Math.round((new Date(iso) - Date.now()) / 1000);
    if (isNaN(s)) return '';
    if (Math.abs(s) > 30 * 86400) return 'on ' + fmtTime(iso);
    const a = Math.abs(s), w = a >= 86400 ? Math.round(a / 86400) + ' d' : a >= 3600 ? Math.round(a / 3600) + ' h'
      : a >= 60 ? Math.round(a / 60) + ' min' : a + ' s';
    return s >= 0 ? 'in ' + w : w + ' ago';
  }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  const MESSAGES = {
    insufficient_funds: 'Not enough available funds for that amount.',
    not_found: "We couldn't find that — check the handle.",
    self_payment: "You can't send money to yourself.",
    self_request: "You can't request money from yourself.",
    request_not_pending: 'That request is no longer pending.',
    forbidden: "You're not allowed to do that.",
    authorization_not_open: 'That hold is no longer open.',
    authorization_expired: 'That hold has expired.',
    capture_exceeds_authorization: 'That is more than the amount still held.',
    email_taken: 'That email is already registered.',
    handle_taken: 'A user with the handle derived from this email already exists.',
    unauthenticated: 'Those details do not match an account.',
  };
  function msgFor(r) {
    const e = r && r.data && r.data.error;
    return (e && MESSAGES[e.code]) || (e && e.message) || 'Something went wrong. Please try again.';
  }

  async function api(method, url, opts) {
    const o = opts || {};
    const headers = { Accept: 'application/json' };
    if (S.token) headers.Authorization = 'Bearer ' + S.token;
    if (o.body !== undefined) headers['Content-Type'] = 'application/json';
    if (o.key) headers['Idempotency-Key'] = o.key;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), o.timeout || 12000);
    try {
      const res = await fetch(url, { method, headers, body: o.body, signal: ctl.signal, cache: 'no-store' });
      const text = await res.text();
      let data = null;
      if (text) data = JSON.parse(text);
      if (res.status === 401 && !PUBLIC && !o.noAuthRedirect) { signOut(); }
      return { status: res.status, ok: res.status < 400, data, uncertain: res.status >= 500 };
    } catch (e) {
      return { status: 0, ok: false, network: true, uncertain: true };
    } finally { clearTimeout(timer); }
  }
  function signOut() {
    localStorage.removeItem(TOKEN_KEY); S.token = null;
    location.replace('/login');
  }

  /* one in-flight attempt per action; the idempotency key is reused only when the
     previous attempt with the same body may have committed */
  const attempts = {};
  function startAttempt(name, body, reuse) {
    const a = attempts[name];
    const att = a && a.body === body && reuse.includes(a.state) ? a : { body, key: uid(), state: 'new' };
    att.state = 'pending'; attempts[name] = att;
    return att;
  }

  function slot() { return h('div', { class: 'slot', 'aria-live': 'polite' }); }
  function setAlert(el, kind, testid, text) {
    el.replaceChildren();
    if (!kind) return;
    el.append(h('div', { class: 'alert ' + kind, t: testid, role: kind === 'error' ? 'alert' : 'status' }, h('span', null, text)));
  }
  function field(id, label, input, hint) {
    input.id = id;
    return h('div', { class: 'field' }, h('label', { for: id }, label), input, hint && h('span', { class: 'hint' }, hint));
  }
  function makeRefresher(load, apply, fail) {
    let seq = 0;
    return async function () {
      const my = ++seq; let r;
      try { r = await load(); } catch (e) { if (my === seq && fail) fail(e); return; }
      if (my !== seq) return; /* latest refresh wins: a slower earlier read is dropped */
      apply(r);
    };
  }
  function need(r) {
    if (r.network || r.status >= 500 || !r.ok) throw new Error('load failed');
    return r.data;
  }
  function loadingBlock() {
    return h('div', { class: 'loading', 'aria-busy': 'true' }, h('span', { class: 'skeleton' }), h('span', { class: 'skeleton' }), h('span', { class: 'skeleton' }));
  }
  function errorBlock(retry, what) {
    return h('div', { class: 'alert error' }, h('span', null, "We couldn't load " + what + '. '),
      h('button', { class: 'btn link', type: 'button', onclick: retry }, 'Try again'));
  }

  /* ---------- shell ---------- */
  const whoSlot = h('div', { class: 'who' });
  function renderWho() {
    whoSlot.replaceChildren();
    if (!S.me) return;
    whoSlot.append(
      h('span', { class: 'who-name', t: 'current-user' }, S.me.display_name),
      h('span', { class: 'who-handle', t: 'current-handle' }, S.me.handle),
      h('button', { class: 'btn secondary small', t: 'logout-button', type: 'button', onclick: signOut }, 'Log out'));
  }
  function shell(content) {
    const links = [['/', 'Wallet'], ['/requests', 'Requests'], ['/authorizations', 'Holds'], ['/split', 'Split']];
    app.replaceChildren(
      h('header', { class: 'topbar' }, h('div', { class: 'topbar-in' },
        h('a', { class: 'brand', href: '/' }, 'Pocketful'),
        S.token && h('nav', { class: 'nav', 'aria-label': 'Main' },
          links.map(([href, label]) => h('a', { href, 'aria-current': href === path ? 'page' : null }, label))),
        whoSlot)),
      h('main', null, content));
  }
  function applyMe(me) {
    S.me = me; CFG.currency = me.currency; CFG.mu = me.minor_units; renderWho();
  }

  /* ---------- balance card ---------- */
  function balanceCard(opts) {
    const body = h('div', { class: 'bal-body' }, h('span', { class: 'skeleton', style: 'height:44px;width:60%' }));
    const extra = h('div', { class: 'actions' });
    if (opts.refresh) extra.append(h('button', { class: 'btn secondary small', t: 'wallet-refresh', type: 'button', onclick: opts.refresh }, 'Refresh'));
    const el = h('section', { class: 'card felt balance' + (opts.compact ? ' compact' : ''), 'aria-label': 'Balance' }, body, opts.refresh ? extra : null);
    return {
      el,
      update(me) {
        body.replaceChildren(
          h('div', { class: 'label' }, 'Available to spend'),
          h('div', { class: 'headline', t: 'wallet-available', 'data-amount': me.available }, fmt(me.available, me.currency)),
          h('div', { class: 'secondary' },
            h('div', null, h('span', { class: 'k' }, 'Total balance'), h('b', { t: 'wallet-balance', 'data-amount': me.total }, fmt(me.total, me.currency))),
            me.held > 0 && h('div', { class: 'held' }, h('span', { class: 'k' }, 'Held for others'), h('b', { t: 'wallet-held', 'data-amount': me.held }, fmt(me.held, me.currency)))));
      },
      fail(retry) { body.replaceChildren(errorBlock(retry, 'your balance')); },
    };
  }

  /* ---------- reusable forms ---------- */
  function normHandle(v) { return v.trim().replace(/^@/, ''); }
  function visSelect(t) {
    return h('select', { t }, h('option', { value: 'public' }, 'Public'), h('option', { value: 'private' }, 'Private'));
  }

  function moneyForm(cfg) {
    /* cfg: {name, title, sub, testPrefix, handleLabel, handleField, button, verbDone, endpoint, withVisibility,
             keepValues, reuseOnSuccess, errTest, uncertainTest, successTest, onDone} */
    const p = cfg.testPrefix;
    const handle = h('input', { t: p + '-handle', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: 'e.g. bob' });
    const amount = h('input', { t: p + '-amount', inputmode: 'decimal', autocomplete: 'off', class: 'num', placeholder: '0.00' });
    const note = h('input', { t: p + '-note', maxlength: '200', placeholder: 'What is it for? (optional)' });
    const vis = cfg.withVisibility ? visSelect(p + '-visibility') : null;
    const msg = slot();
    const btn = h('button', { class: 'btn', t: p + '-submit', type: 'submit' }, cfg.button);
    const form = h('form', { novalidate: true, onsubmit: onSubmit },
      field(p + '-handle-in', cfg.handleLabel, handle),
      h('div', { class: 'row2' }, field(p + '-amount-in', 'Amount (' + CFG.currency + ')', amount), vis ? field(p + '-vis-in', 'Visibility', vis) : h('span')),
      field(p + '-note-in', 'Note', note),
      msg, btn);
    async function onSubmit(ev) {
      ev.preventDefault();
      const to = normHandle(handle.value);
      if (!to) return setAlert(msg, 'error', cfg.errTest, 'Enter the handle of the person.');
      const a = parseAmount(amount.value);
      if (a.error) return setAlert(msg, 'error', cfg.errTest, a.error);
      const payload = { [cfg.handleField]: to, amount: a.minor, note: note.value };
      if (vis) payload.visibility = vis.value;
      const bodyStr = JSON.stringify(payload);
      const att = startAttempt(cfg.name, bodyStr, cfg.reuseOnSuccess ? ['uncertain', 'success'] : ['uncertain']);
      btn.disabled = true;
      let r;
      try { r = await api('POST', cfg.endpoint, { body: bodyStr, key: att.key }); } finally { btn.disabled = false; }
      if (r.uncertain) {
        att.state = 'uncertain';
        setAlert(msg, 'uncertain', cfg.uncertainTest, "We didn't get a reply, so we can't tell whether this went through. Press " + cfg.button + ' again to retry; it will only be sent once.');
        cfg.onDone && cfg.onDone(false);
        return;
      }
      if (r.ok) {
        att.state = 'success';
        setAlert(msg, 'success', cfg.successTest, cfg.verbDone(r.data, r.status));
        if (!cfg.keepValues) { handle.value = ''; amount.value = ''; note.value = ''; }
        cfg.onDone && cfg.onDone(true);
      } else {
        att.state = 'failed';
        setAlert(msg, 'error', cfg.errTest, msgFor(r));
        cfg.onDone && cfg.onDone(false);
      }
    }
    return h('section', { class: 'card', 'aria-label': cfg.title },
      h('h2', null, cfg.title), cfg.sub && h('p', { class: 'sub' }, cfg.sub), form);
  }

  function authorizeCard(onDone) {
    return moneyForm({
      name: 'authorize', title: 'Reserve money for someone', sub: 'Holds the amount so it can be collected later. Nothing moves until it is captured.',
      testPrefix: 'authorize', handleLabel: 'Recipient handle', handleField: 'to_handle', button: 'Place hold', endpoint: '/authorizations',
      withVisibility: true, keepValues: false, reuseOnSuccess: false, errTest: 'authorize-error', uncertainTest: 'authorize-uncertain',
      successTest: 'authorize-success', verbDone: d => 'Holding ' + fmt(d.amount, d.currency) + ' for @' + d.to_handle + '.', onDone });
  }

  /* ---------- pages ---------- */
  async function loadMeIfNeeded() {
    const r = await api('GET', '/me');
    if (r.ok) applyMe(r.data);
    return r;
  }

  function pageHome() {
    const bal = balanceCard({ refresh: () => refresh() });
    const feed = h('div', { class: 'feed' }, loadingBlock());
    const refresh = makeRefresher(
      () => Promise.all([api('GET', '/me'), api('GET', '/activity?limit=200')]).then(([m, a]) => [need(m), need(a)]),
      ([me, act]) => { applyMe(me); bal.update(me); renderFeed(feed, act.payments, me); },
      () => { bal.fail(refresh); feed.replaceChildren(errorBlock(refresh, 'the activity feed')); });
    const pay = moneyForm({
      name: 'pay', title: 'Send money', testPrefix: 'pay', handleLabel: 'Recipient handle', handleField: 'to_handle', button: 'Pay',
      endpoint: '/payments', withVisibility: true, keepValues: true, reuseOnSuccess: true, errTest: 'pay-error',
      uncertainTest: 'pay-uncertain', successTest: 'pay-success',
      verbDone: (d, st) => (st === 200 ? 'Already sent: ' : 'Sent ') + fmt(d.amount, d.currency) + ' to @' + d.to_handle + '.',
      onDone: () => refresh() });
    const reqf = moneyForm({
      name: 'request', title: 'Request money', sub: 'Ask someone to pay you. They choose whether it is public.', testPrefix: 'request', handleLabel: 'Who should pay?',
      handleField: 'payer_handle', button: 'Send request', endpoint: '/requests', withVisibility: false, keepValues: false, reuseOnSuccess: false,
      errTest: 'request-error', uncertainTest: 'request-uncertain', successTest: 'request-success',
      verbDone: d => 'Requested ' + fmt(d.amount, d.currency) + ' from @' + d.payer_handle + '.' });
    const auth = authorizeCard(() => refresh());
    shell(h('div', { class: 'grid two' },
      h('div', { class: 'col' }, bal.el, pay, reqf, auth),
      h('div', { class: 'col' }, h('section', { class: 'card', 'aria-label': 'Activity' },
        h('div', { class: 'head-row' }, h('h2', null, 'Activity')), feed))));
    refresh();
  }

  function renderFeed(el, payments, me) {
    if (!payments.length) {
      el.replaceChildren(h('div', { class: 'empty', t: 'empty-activity' }, h('strong', null, 'Nothing here yet'), 'Payments you send, receive or that are public will show up here.'));
      return;
    }
    el.replaceChildren(h('ul', { class: 'list', t: 'activity-list' }, payments.map(p => {
      const sent = p.from_user_id === me.user_id, got = p.to_user_id === me.user_id;
      const tags = [];
      if (p.settlement_id) tags.push(h('span', { class: 'pill info' }, 'Settlement'));
      if (p.request_id) tags.push(h('span', { class: 'pill info' }, 'Request paid'));
      if (p.authorization_id) tags.push(h('span', { class: 'pill info' }, 'Capture'));
      return h('li', { class: 'item', t: 'activity-item-' + p.payment_id, 'data-visibility': p.visibility },
        h('div', { class: 'item-top' },
          h('div', { class: 'item-main', t: 'activity-parties-' + p.payment_id }, p.from_handle + ' → ' + p.to_handle),
          h('div', { class: 'amount ' + (got ? 'in' : 'out'), t: 'activity-amount-' + p.payment_id }, fmt(p.amount, p.currency))),
        h('div', { class: 'note', t: 'activity-note-' + p.payment_id }, p.note),
        h('div', { class: 'item-meta' },
          h('span', { class: 'pill ' + (got ? 'success' : sent ? 'neutral' : 'public') }, got ? 'Received' : sent ? 'Sent' : 'Between others'),
          h('span', { class: 'pill ' + p.visibility }, cap(p.visibility)), tags,
          h('time', { datetime: p.created_at }, fmtTime(p.created_at))));
    })));
  }

  function pageRequests() {
    const bal = balanceCard({ compact: true });
    const err = slot();
    const body = h('div', null, loadingBlock());
    const visPick = {};
    async function act(kind, r) {
      const url = '/requests/' + encodeURIComponent(r.request_id) + '/' + kind;
      let res;
      if (kind === 'pay') {
        const bodyStr = JSON.stringify({ visibility: visPick[r.request_id].value });
        const att = startAttempt('rpay:' + r.request_id, bodyStr, ['uncertain']);
        res = await api('POST', url, { body: bodyStr, key: att.key });
        att.state = res.uncertain ? 'uncertain' : res.ok ? 'success' : 'failed';
      } else res = await api('POST', url);
      if (res.uncertain) setAlert(err, 'uncertain', 'request-uncertain', "We didn't get a reply, so we can't tell whether that went through. The list below is refreshed; try again if it is still pending.");
      else if (!res.ok) setAlert(err, 'error', 'request-error', msgFor(res));
      else setAlert(err);
      refresh();
    }
    const refresh = makeRefresher(
      () => Promise.all([api('GET', '/me'), api('GET', '/requests?limit=200')]).then(([m, q]) => [need(m), need(q)]),
      ([me, q]) => { applyMe(me); bal.update(me); renderRequests(body, q.requests, me, act, visPick); },
      () => { bal.fail(refresh); body.replaceChildren(errorBlock(refresh, 'your requests')); });
    shell(h('div', { class: 'grid' }, bal.el,
      h('section', { class: 'card', 'aria-label': 'Requests' }, h('h2', null, 'Requests'), err, body)));
    refresh();
  }

  function renderRequests(el, list, me, act, visPick) {
    const inc = list.filter(r => r.payer_id === me.user_id), out = list.filter(r => r.requester_id === me.user_id);
    const none = !list.length;
    const item = (r, incoming) => {
      const actions = [];
      if (incoming && r.status === 'pending') {
        const v = visPick[r.request_id] = h('select', { id: 'rv-' + r.request_id, 'aria-label': 'Visibility' },
          h('option', { value: 'public' }, 'Public'), h('option', { value: 'private' }, 'Private'));
        actions.push(h('div', { class: 'field' }, h('label', { for: 'rv-' + r.request_id }, 'Show it as'), v),
          h('button', { class: 'btn small', t: 'request-pay-' + r.request_id, type: 'button', onclick: ev => lock(ev, () => act('pay', r)) }, 'Pay'),
          h('button', { class: 'btn danger small', t: 'request-decline-' + r.request_id, type: 'button', onclick: ev => lock(ev, () => act('decline', r)) }, 'Decline'));
      }
      if (!incoming && r.status === 'pending') {
        actions.push(h('button', { class: 'btn danger small', t: 'request-cancel-' + r.request_id, type: 'button', onclick: ev => lock(ev, () => act('cancel', r)) }, 'Cancel request'));
      }
      return h('li', { class: 'item', t: 'request-item-' + r.request_id, 'data-status': r.status },
        h('div', { class: 'item-top' },
          h('div', { class: 'item-main' }, incoming ? '@' + r.requester_handle + ' asks you to pay' : 'You asked @' + r.payer_handle),
          h('div', { class: 'amount', t: 'request-amount-' + r.request_id }, fmt(r.amount, r.currency))),
        h('div', { class: 'note' }, r.note),
        h('div', { class: 'item-meta' }, h('span', { class: 'pill ' + r.status }, cap(r.status)), h('time', { datetime: r.created_at }, fmtTime(r.created_at))),
        actions.length ? h('div', { class: 'item-actions' }, actions) : null);
    };
    const section = (title, items, testid, incoming) => h('div', null,
      h('h3', { class: 'sect-title' }, title),
      h('ul', { class: 'list', t: testid }, items.map(r => item(r, incoming))),
      !items.length && !none ? h('p', { class: 'sub' }, 'Nothing here.') : null);
    el.replaceChildren(...[
      none ? h('div', { class: 'empty', t: 'empty-requests' }, h('strong', null, 'No requests yet'), 'Requests you send or receive will appear here.') : null,
      section('Asking you to pay', inc, 'incoming-list', true), section('You asked', out, 'outgoing-list', false)].filter(Boolean));
  }
  async function lock(ev, fn) {
    const b = ev.currentTarget; b.disabled = true;
    try { await fn(); } finally { b.disabled = false; }
  }

  function shares(amount, n) {
    const base = Math.floor(amount / n), extra = amount % n;
    return Array.from({ length: n }, (_, i) => base + (i < extra ? 1 : 0));
  }

  function pageSplit() {
    const bal = balanceCard({ compact: true });
    const amount = h('input', { t: 'split-amount', inputmode: 'decimal', autocomplete: 'off', class: 'num', placeholder: '0.00' });
    const handles = h('input', { t: 'split-handles', autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', placeholder: 'ada, bob, cy' });
    const note = h('input', { t: 'split-note', maxlength: '200', placeholder: 'What was it for? (optional)' });
    const preview = h('div', { class: 'preview', t: 'split-preview', 'aria-live': 'polite' });
    const msg = slot();
    const btn = h('button', { class: 'btn', t: 'split-submit', type: 'submit' }, 'Split and request');
    const parsed = () => {
      const list = handles.value.split(',').map(normHandle).filter(Boolean);
      const a = amount.value.trim() ? parseAmount(amount.value) : null;
      return { list, a };
    };
    function drawPreview() {
      const { list, a } = parsed();
      preview.replaceChildren();
      if (!list.length || !a || a.error) {
        preview.append(h('span', { class: 'hint' }, a && a.error ? a.error : 'Enter an amount and handles to preview each share.'));
        return;
      }
      if (new Set(list).size !== list.length) { preview.append(h('span', { class: 'hint' }, 'Each handle can appear only once.')); return; }
      const sh = shares(a.minor, list.length);
      preview.append(h('span', { class: 'hint' }, 'Shares (extra pennies go to the first people listed)'),
        ...list.map((hd, i) => h('div', { class: 'share' }, h('span', null, (S.me && hd === S.me.handle) ? hd + ' (you)' : hd),
          h('span', { class: 'amount', t: 'split-share-' + hd }, fmt(sh[i])))));
    }
    [amount, handles].forEach(i => i.addEventListener('input', drawPreview));
    async function onSubmit(ev) {
      ev.preventDefault();
      const { list, a } = parsed();
      if (a === null || a.error) return setAlert(msg, 'error', 'split-error', a ? a.error : 'Enter the total amount.');
      if (!list.length) return setAlert(msg, 'error', 'split-error', 'Enter at least one handle, separated by commas.');
      if (new Set(list).size !== list.length) return setAlert(msg, 'error', 'split-error', 'Each handle can appear only once.');
      const bodyStr = JSON.stringify({ amount: a.minor, participant_handles: list, note: note.value });
      const att = startAttempt('split', bodyStr, ['uncertain']);
      btn.disabled = true;
      let r;
      try { r = await api('POST', '/splits', { body: bodyStr, key: att.key }); } finally { btn.disabled = false; }
      if (r.uncertain) {
        att.state = 'uncertain';
        return setAlert(msg, 'uncertain', 'split-uncertain', "We didn't get a reply, so we can't tell whether the split was created. Press the button again to retry; it will only be created once.");
      }
      if (!r.ok) { att.state = 'failed'; return setAlert(msg, 'error', 'split-error', msgFor(r)); }
      att.state = 'success';
      const d = r.data;
      setAlert(msg, 'success', 'split-success', d.requests.length ? 'Requested ' + d.requests.length + (d.requests.length === 1 ? ' share' : ' shares') + ' of ' + fmt(d.amount, d.currency) + '. Follow them under Requests.' : 'Nothing to request: you are the only participant.');
    }
    shell(h('div', { class: 'grid two' }, h('div', { class: 'col' }, bal.el),
      h('section', { class: 'card', 'aria-label': 'Split a bill' }, h('h2', null, 'Split a bill'),
        h('p', { class: 'sub' }, 'You already paid. Ask everyone else for their equal share.'),
        h('form', { novalidate: true, onsubmit: onSubmit },
          field('split-amount-in', 'Total you paid (' + CFG.currency + ')', amount),
          field('split-handles-in', 'People to split with', handles, 'Handles separated by commas, in order. Include yourself to keep a share.'),
          field('split-note-in', 'Note', note),
          h('div', null, h('div', { class: 'sect-title' }, 'Preview'), preview),
          msg, btn))));
    const refresh = makeRefresher(() => api('GET', '/me').then(need), me => { applyMe(me); bal.update(me); drawPreview(); }, () => bal.fail(refresh));
    drawPreview();
    refresh();
  }

  function pageAuthorizations() {
    const bal = balanceCard({ compact: true });
    const err = slot();
    const body = h('div', null, loadingBlock());
    const form = authorizeCard(() => refresh());
    async function act(kind, a, inputs) {
      const url = '/authorizations/' + encodeURIComponent(a.authorization_id) + '/' + kind;
      let res;
      if (kind === 'capture') {
        const amt = parseAmount(inputs.amount.value);
        if (amt.error) return setAlert(err, 'error', 'authorization-error', amt.error);
        const payload = { amount: amt.minor };
        if (inputs.keep.checked) payload.final = false;
        const bodyStr = JSON.stringify(payload);
        const att = startAttempt('capture:' + a.authorization_id, bodyStr, ['uncertain']);
        res = await api('POST', url, { body: bodyStr, key: att.key });
        att.state = res.uncertain ? 'uncertain' : res.ok ? 'success' : 'failed';
      } else res = await api('POST', url);
      if (res.uncertain) setAlert(err, 'uncertain', 'authorization-uncertain', "We didn't get a reply, so we can't tell whether that went through. The list is refreshed; try again if it is still open.");
      else if (!res.ok) setAlert(err, 'error', 'authorization-error', msgFor(res));
      else setAlert(err);
      refresh();
    }
    const refresh = makeRefresher(
      () => Promise.all([api('GET', '/me'), api('GET', '/authorizations?limit=200')]).then(([m, q]) => [need(m), need(q)]),
      ([me, q]) => { applyMe(me); bal.update(me); renderAuths(body, q.authorizations, me, act); },
      () => { bal.fail(refresh); body.replaceChildren(errorBlock(refresh, 'your holds')); });
    shell(h('div', { class: 'grid two' }, h('div', { class: 'col' }, bal.el, form),
      h('section', { class: 'card', 'aria-label': 'Holds' }, h('h2', null, 'Holds'),
        h('p', { class: 'sub' }, 'Money reserved now and collected later. Held money cannot be spent elsewhere.'), err, body)));
    refresh();
  }

  function renderAuths(el, list, me, act) {
    if (!list.length) {
      el.replaceChildren(h('div', { class: 'empty', t: 'empty-authorizations' }, h('strong', null, 'No holds yet'), 'When you reserve money for someone, or they reserve it for you, it appears here.'));
      return;
    }
    el.replaceChildren(h('ul', { class: 'list', t: 'authorization-list' }, list.map(a => {
      const id = a.authorization_id, incoming = a.to_user_id === me.user_id, open = a.status === 'open';
      const inputs = {};
      const actions = [];
      if (open && incoming) {
        inputs.amount = h('input', { t: 'authorization-capture-amount-' + id, id: 'ca-' + id, inputmode: 'decimal', class: 'num', value: fmtDecimal(a.remaining_amount) });
        inputs.keep = h('input', { type: 'checkbox', id: 'ck-' + id, t: 'authorization-keep-open-' + id });
        actions.push(field2('ca-' + id, 'Amount to collect', inputs.amount),
          h('button', { class: 'btn small', t: 'authorization-capture-' + id, type: 'button', onclick: ev => lock(ev, () => act('capture', a, inputs)) }, 'Collect'),
          h('label', { class: 'check', for: 'ck-' + id }, inputs.keep, 'Keep the rest held'));
      }
      if (open && !incoming) {
        actions.push(h('button', { class: 'btn danger small', t: 'authorization-void-' + id, type: 'button', onclick: ev => lock(ev, () => act('void', a)) }, 'Release hold'));
      }
      return h('li', { class: 'item', t: 'authorization-item-' + id, 'data-status': a.status },
        h('div', { class: 'item-top' },
          h('div', { class: 'item-main' }, incoming ? '@' + a.from_handle + ' is holding for you' : 'You are holding for @' + a.to_handle),
          h('div', { class: 'amount', t: 'authorization-amount-' + id }, fmt(a.amount, a.currency))),
        h('div', { class: 'note' }, a.note),
        h('div', { class: 'item-meta' },
          h('span', { class: 'pill ' + a.status }, a.status === 'open' ? 'Open' : cap(a.status)),
          h('span', { class: 'pill ' + a.visibility }, cap(a.visibility)),
          open ? h('span', null, 'Still held: ', h('b', null, fmt(a.remaining_amount, a.currency))) : null,
          a.status === 'captured' ? h('span', null, 'Collected: ', h('b', { t: 'authorization-captured-' + id }, fmt(a.captured_amount, a.currency))) : null,
          a.status !== 'captured' && a.captured_amount > 0 ? h('span', null, 'Collected so far: ', h('b', null, fmt(a.captured_amount, a.currency))) : null),
        h('div', { class: 'item-meta' },
          h('span', null, open ? 'Expires ' + until(a.expires_at) : a.status === 'expired' ? 'Expired ' + until(a.expires_at) : 'Was due ' + until(a.expires_at)),
          h('time', { t: 'authorization-expires-' + id, datetime: a.expires_at, title: fmtTime(a.expires_at) }, a.expires_at)),
        actions.length ? h('div', { class: 'item-actions' }, actions) : null);
    })));
  }
  function field2(id, label, input) { return h('div', { class: 'field' }, h('label', { for: id }, label), input); }

  /* ---------- auth pages ---------- */
  function pageAuth(kind) {
    const signup = kind === 'signup';
    const p = signup ? 'signup' : 'login';
    const email = h('input', { t: p + '-email', type: 'email', autocomplete: 'email', autocapitalize: 'none' });
    const pw = h('input', { t: p + '-password', type: 'password', autocomplete: signup ? 'new-password' : 'current-password' });
    const name = signup ? h('input', { t: 'signup-display-name', autocomplete: 'name' }) : null;
    const msg = slot();
    const btn = h('button', { class: 'btn', t: p + '-submit', type: 'submit' }, signup ? 'Create account' : 'Log in');
    async function onSubmit(ev) {
      ev.preventDefault();
      const payload = signup ? { email: email.value.trim(), password: pw.value, display_name: name.value } : { email: email.value.trim(), password: pw.value };
      btn.disabled = true;
      let r;
      try { r = await api('POST', signup ? '/auth/signup' : '/auth/login', { body: JSON.stringify(payload) }); } finally { btn.disabled = false; }
      if (r.ok) {
        S.token = r.data.token; localStorage.setItem(TOKEN_KEY, S.token);
        location.assign('/');
      } else if (r.uncertain) setAlert(msg, 'error', 'auth-error', "We couldn't reach the service. Please try again.");
      else setAlert(msg, 'error', 'auth-error', msgFor(r));
    }
    shell(h('section', { class: 'card narrow', 'aria-label': signup ? 'Sign up' : 'Log in' },
      h('h2', null, signup ? 'Create your wallet' : 'Welcome back'),
      h('p', { class: 'sub' }, signup ? 'Sign up to send, request and split money by handle.' : 'Log in to your Pocketful wallet.'),
      h('form', { novalidate: true, onsubmit: onSubmit },
        signup ? field(p + '-name-in', 'Display name', name) : null,
        field(p + '-email-in', 'Email', email),
        field(p + '-pw-in', 'Password', pw, signup ? 'At least 8 characters.' : null),
        msg, btn),
      h('p', { class: 'switch' }, signup ? 'Already have an account? ' : 'New here? ',
        h('a', { href: signup ? '/login' : '/signup' }, signup ? 'Log in' : 'Create an account'))));
    if (S.token) loadMeIfNeeded();
  }

  /* ---------- boot ---------- */
  if (!PUBLIC && !S.token) { location.replace('/login'); return; }
  if (path === '/login') pageAuth('login');
  else if (path === '/signup') pageAuth('signup');
  else if (path === '/requests') pageRequests();
  else if (path === '/split') pageSplit();
  else if (path === '/authorizations') pageAuthorizations();
  else pageHome();
})();
