/* ProofDesk — small progressive-enhancement layer (no dependencies) */
(function () {
  'use strict';
  var root = document.documentElement;
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---- Theme toggle (persisted) ---- */
  function applyTheme(t) { root.setAttribute('data-theme', t); try { localStorage.setItem('pd-theme', t); } catch (e) {} }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-theme-toggle]');
    if (!b) return;
    applyTheme(root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
  });

  /* ---- Toasts: auto-dismiss + manual close ---- */
  document.querySelectorAll('.flash').forEach(function (f, i) {
    var x = document.createElement('button');
    x.type = 'button'; x.className = 'flash-x'; x.setAttribute('aria-label', 'Dismiss'); x.innerHTML = '&times;';
    f.appendChild(x);
    function close() { f.classList.add('out'); setTimeout(function () { f.remove(); }, 260); }
    x.addEventListener('click', close);
    if (!f.classList.contains('flash-error')) setTimeout(close, 6000 + i * 600);
  });

  /* ---- Count-up on stat numbers ---- */
  document.querySelectorAll('.stat .num').forEach(function (el) {
    var end = parseInt(el.textContent, 10);
    if (reduce || isNaN(end) || end < 2 || String(end) !== el.textContent.trim()) return;
    var t0 = null, dur = 700;
    function step(t) {
      if (!t0) t0 = t;
      var p = Math.min((t - t0) / dur, 1), eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(end * eased);
      if (p < 1) requestAnimationFrame(step);
    }
    el.textContent = '0'; requestAnimationFrame(step);
  });

  /* ---- Animate bar fills ---- */
  document.querySelectorAll('.bar > div').forEach(function (b) {
    var w = b.style.width; if (reduce || !w) return;
    b.style.width = '0'; requestAnimationFrame(function () { requestAnimationFrame(function () { b.style.width = w; }); });
  });

  /* ---- Live filter for any table with 6+ rows ---- */
  document.querySelectorAll('.card > table').forEach(function (tbl) {
    var rows = tbl.querySelectorAll('tbody tr');
    if (rows.length < 6) return;
    var wrap = document.createElement('div'); wrap.className = 'tbl-search';
    wrap.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg><input type="search" placeholder="Filter this table…" aria-label="Filter table">';
    tbl.parentNode.insertBefore(wrap, tbl);
    var empty = document.createElement('p'); empty.className = 'empty-state'; empty.hidden = true; empty.textContent = 'No rows match your filter.';
    tbl.parentNode.appendChild(empty);
    wrap.querySelector('input').addEventListener('input', function (e) {
      var q = e.target.value.toLowerCase().trim(), shown = 0;
      rows.forEach(function (r) { var m = !q || r.textContent.toLowerCase().indexOf(q) > -1; r.hidden = !m; if (m) shown++; });
      empty.hidden = shown > 0;
    });
  });

  /* ---- Submit buttons: loading state, prevents double-submit ---- */
  document.addEventListener('submit', function (e) {
    var f = e.target; if (f.dataset.busy) { e.preventDefault(); return; }
    var btn = e.submitter || f.querySelector('button[type=submit]');
    if (!btn) return;
    f.dataset.busy = '1'; btn.classList.add('is-loading');
    setTimeout(function () { delete f.dataset.busy; btn.classList.remove('is-loading'); }, 8000);
  });

  /* ---- Password show/hide ---- */
  document.querySelectorAll('input[type=password]').forEach(function (inp) {
    var w = document.createElement('div'); w.className = 'pw-wrap';
    inp.parentNode.insertBefore(w, inp); w.appendChild(inp);
    var b = document.createElement('button'); b.type = 'button'; b.className = 'pw-toggle'; b.textContent = 'Show'; b.setAttribute('aria-label', 'Show password');
    b.addEventListener('click', function () { var s = inp.type === 'password'; inp.type = s ? 'text' : 'password'; b.textContent = s ? 'Hide' : 'Show'; });
    w.appendChild(b);
  });

  /* ---- Demo account quick-fill (login page) ---- */
  document.querySelectorAll('[data-demo]').forEach(function (chip) {
    chip.addEventListener('click', function () {
      var em = document.getElementById('email'), pw = document.getElementById('password');
      if (!em || !pw) return;
      em.value = chip.dataset.demo; pw.value = 'Demo@1234'; pw.focus();
      document.querySelectorAll('[data-demo]').forEach(function (c) { c.classList.toggle('on', c === chip); });
    });
  });

  /* ---- Click-to-copy (record numbers etc.) ---- */
  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-copy]'); if (!c) return;
    e.preventDefault();
    var txt = c.dataset.copy;
    (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(function () {
      c.classList.add('copied'); setTimeout(function () { c.classList.remove('copied'); }, 1400);
    }).catch(function () {});
  });

  /* ---- Close mobile menu on outside tap / Esc ---- */
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') document.body.classList.remove('menu-open'); });
  document.addEventListener('click', function (e) {
    if (document.body.classList.contains('menu-open') && !e.target.closest('.sidebar') && !e.target.closest('.menu-btn')) document.body.classList.remove('menu-open');
  });

  /* ---- Role toggle on register: show category only for providers ---- */
  var role = document.getElementById('role'), cat = document.getElementById('category-field');
  if (role && cat) { var sync = function () { cat.style.display = role.value === 'provider' ? '' : 'none'; }; role.addEventListener('change', sync); sync(); }
})();
