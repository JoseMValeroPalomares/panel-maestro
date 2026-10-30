/* ==========================================================================
   ui.js — piezas comunes de interfaz (script clásico, sin módulos)
   Expone: icon, escapeHtml, api, toast, openModal, closeModal, uiConfirm,
   uiPrompt, openMenu, skeletonRows, emptyState, openCapture, timeAgo, CATEGORY_COLORS
   ========================================================================== */
(function () {
  'use strict';

  /* ---------- Utilidades ---------- */
  function escapeHtml(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  // Sprite con su versión (ver core/templating.asset): así nunca se mezcla con uno viejo en caché
  const ICONS = document.documentElement.dataset.icons || '/static/icons.svg';
  function icon(name, cls = '') {
    return `<svg class="icon ${cls}" aria-hidden="true"><use href="${ICONS}#i-${name}"></use></svg>`;
  }

  function timeAgo(epochSeconds) {
    if (!epochSeconds) return '';
    const diff = Date.now() / 1000 - epochSeconds;
    const rtf = new Intl.RelativeTimeFormat('es', { numeric: 'auto' });
    const steps = [[60, 'second'], [3600, 'minute', 60], [86400, 'hour', 3600], [604800, 'day', 86400],
      [2629800, 'week', 604800], [31557600, 'month', 2629800], [Infinity, 'year', 31557600]];
    for (const [limit, unit, div = 1] of steps) {
      if (Math.abs(diff) < limit) return rtf.format(-Math.round(diff / div), unit);
    }
    return '';
  }

  /* ---------- API ---------- */
  async function api(url, { method = 'GET', body, headers = {}, quiet = false, raw = false } = {}) {
    const opts = { method, headers: { ...headers } };
    if (body instanceof FormData) opts.body = body;
    else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
    let res;
    try {
      res = await fetch(url, opts);
    } catch (err) {
      if (!quiet) toast('Sin conexión con el panel', { type: 'error' });
      throw err;
    }
    if (raw) return res;
    let data = null;
    const text = await res.text();
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    if (res.ok && method !== 'GET') publishChange(url, method);
    if (!res.ok) {
      const msg = (data && (data.error || (typeof data.detail === 'string' && data.detail))) || `Error ${res.status}`;
      if (!quiet && res.status !== 401) toast(msg, { type: 'error' });
      const error = new Error(msg); error.status = res.status; error.data = data;
      throw error;
    }
    return data;
  }

  /* ---------- Sincronía entre pestañas ----------
     Cada escritura que pasa por api() se anuncia en un BroadcastChannel; las otras
     pestañas del panel (Inbox, Tareas, Notas…) se enteran al instante, y al volver
     el foco a una pestaña se recarga por si algo cambió fuera (otro dispositivo). */
  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('panel-datos') : null;
  const SYNC_PATHS = /^\/(api\/(items|inbox|notes|bulk\/notes|resources|prefs)|comidas\/api)/;
  let lastLocalChange = 0;
  function publishChange(url, method) {
    const path = new URL(url, location.href).pathname;
    if (!SYNC_PATHS.test(path) || path.endsWith('/reviewed')) return;
    lastLocalChange = Date.now();
    channel?.postMessage({ path, method, at: lastLocalChange });
  }
  function emitChange(detail) {
    document.dispatchEvent(new CustomEvent('panel:changed', { detail }));
  }
  channel?.addEventListener('message', (e) => emitChange({ ...e.data, remote: true }));
  let hiddenAt = 0;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > 1500) emitChange({ path: '*', reason: 'focus' });
  });
  /* onDataChange(/^\/api\/inbox/, recargar): se llama (agrupado) cuando otra pestaña
     cambia algo que encaja con el patrón, o al volver el foco. No interrumpe un arrastre. */
  function onDataChange(pattern, callback, { wait = 250 } = {}) {
    let timer = null;
    const run = () => {
      if (window.Sortable?.dragging) { timer = setTimeout(run, 400); return; }
      timer = null;
      callback();
    };
    document.addEventListener('panel:changed', (e) => {
      const p = e.detail?.path || '*';
      if (p !== '*' && !pattern.test(p)) return;
      clearTimeout(timer);
      timer = setTimeout(run, wait);
    });
  }

  /* ---------- Toasts ---------- */
  let toastRegion;
  function toast(message, { type = 'success', action = null, duration = 3600 } = {}) {
    if (!toastRegion) {
      toastRegion = document.querySelector('.toast-region');
      if (!toastRegion) {
        toastRegion = document.createElement('div');
        toastRegion.className = 'toast-region';
        document.body.appendChild(toastRegion);
      }
      toastRegion.setAttribute('role', 'status');
      toastRegion.setAttribute('aria-live', 'polite');
    }
    const el = document.createElement('div');
    el.className = 'toast' + (type === 'error' ? ' error' : '');
    el.innerHTML = icon(type === 'error' ? 'triangle-alert' : (type === 'info' ? 'info' : 'circle-check')) +
      `<span class="toast-msg">${escapeHtml(message)}</span>`;
    let timer;
    const dismiss = () => {
      clearTimeout(timer);
      el.classList.add('leaving');
      setTimeout(() => el.remove(), 200);
    };
    if (action) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'toast-action';
      btn.textContent = action.label;
      btn.addEventListener('click', () => { dismiss(); action.onClick(); });
      el.appendChild(btn);
      duration = Math.max(duration, 6000);
    }
    toastRegion.appendChild(el);
    timer = setTimeout(dismiss, duration);
    return dismiss;
  }

  /* ---------- Modal único (dialog nativo) ----------
     <dialog class="modal" id="x" aria-labelledby="x-title"> ... <button data-close> ...
     showModal() hace el resto de la página inerte (foco atrapado) y Esc lo cierra. */
  const openers = new WeakMap();
  const closeHandlers = new WeakMap();

  function resolveDialog(idOrEl) {
    return typeof idOrEl === 'string' ? document.getElementById(idOrEl) : idOrEl;
  }

  function openModal(idOrEl, { onClose, focus } = {}) {
    const dlg = resolveDialog(idOrEl);
    if (!dlg) return null;
    if (onClose) closeHandlers.set(dlg, onClose);
    if (!dlg.open) {
      openers.set(dlg, document.activeElement);
      dlg.showModal();
    }
    const target = focus ? dlg.querySelector(focus) : dlg.querySelector('[autofocus], input:not([type=hidden]):not([disabled]), textarea, select');
    if (target) setTimeout(() => target.focus({ preventScroll: true }), 30);
    return dlg;
  }

  function closeModal(idOrEl, result) {
    const dlg = resolveDialog(idOrEl);
    if (!dlg || !dlg.open) return;
    dlg.close(result ?? '');
  }

  function wireDialog(dlg) {
    if (dlg.__wired) return;
    dlg.__wired = true;
    if (!dlg.hasAttribute('aria-labelledby')) {
      const h = dlg.querySelector('h2');
      if (h) { h.id = h.id || dlg.id + '-title'; dlg.setAttribute('aria-labelledby', h.id); }
    }
    // Clic en el fondo (fuera de la caja) cierra; no si el gesto empezó dentro (selección de texto).
    let downInside = false;
    dlg.addEventListener('pointerdown', (e) => { downInside = e.target !== dlg; });
    dlg.addEventListener('click', (e) => {
      if (e.target === dlg && !downInside && !dlg.hasAttribute('data-static')) closeModal(dlg);
    });
    dlg.addEventListener('cancel', (e) => { if (dlg.hasAttribute('data-static')) e.preventDefault(); });
    dlg.addEventListener('close', () => {
      const handler = closeHandlers.get(dlg);
      closeHandlers.delete(dlg);
      if (handler) handler(dlg.returnValue);
      const opener = openers.get(dlg);
      if (opener && document.contains(opener) && typeof opener.focus === 'function') opener.focus({ preventScroll: true });
    });
    dlg.addEventListener('click', (e) => {
      const closer = e.target.closest('[data-close]');
      if (closer && dlg.contains(closer)) closeModal(dlg);
    });
  }

  function wireAllDialogs(root = document) {
    root.querySelectorAll('dialog.modal').forEach(wireDialog);
  }

  /* Diálogo genérico creado al vuelo (confirmar / pedir texto) */
  function buildDialog({ title, message, bodyHtml = '', confirmLabel = 'Aceptar', cancelLabel = 'Cancelar', danger = false, size = 'modal-sm' }) {
    const dlg = document.createElement('dialog');
    dlg.className = `modal ${size}`;
    dlg.innerHTML = `
      <div class="modal-header"><h2>${escapeHtml(title)}</h2></div>
      <div class="modal-body">
        ${message ? `<p class="muted">${escapeHtml(message)}</p>` : ''}
        ${bodyHtml}
      </div>
      <div class="modal-footer">
        ${cancelLabel ? `<button type="button" class="btn" value="cancel" data-role="cancel">${escapeHtml(cancelLabel)}</button>` : ''}
        <button type="button" class="btn ${danger ? 'btn-danger-solid' : 'btn-primary'}" data-role="ok">${escapeHtml(confirmLabel)}</button>
      </div>`;
    document.body.appendChild(dlg);
    wireDialog(dlg);
    return dlg;
  }

  function uiConfirm(title, message = '', { confirmLabel = 'Aceptar', danger = false, cancelLabel = 'Cancelar' } = {}) {
    return new Promise((resolve) => {
      const dlg = buildDialog({ title, message, confirmLabel, danger, cancelLabel });
      let result = false;
      dlg.querySelector('[data-role=ok]').addEventListener('click', () => { result = true; closeModal(dlg); });
      dlg.querySelector('[data-role=cancel]')?.addEventListener('click', () => closeModal(dlg));
      openModal(dlg, { focus: '[data-role=ok]', onClose: () => { dlg.remove(); resolve(result); } });
    });
  }

  function uiAlert(title, message = '') {
    return uiConfirm(title, message, { cancelLabel: '', confirmLabel: 'Entendido' });
  }

  function uiPrompt(title, { label = '', value = '', placeholder = '', confirmLabel = 'Aceptar', multiline = false, message = '' } = {}) {
    return new Promise((resolve) => {
      const id = 'p' + Math.random().toString(36).slice(2, 8);
      const control = multiline
        ? `<textarea id="${id}" class="textarea" rows="4" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value)}</textarea>`
        : `<input id="${id}" class="input" type="text" value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}" autocomplete="off">`;
      const dlg = buildDialog({
        title, message, confirmLabel,
        bodyHtml: `<label class="field" for="${id}">${label ? `<span class="field-label">${escapeHtml(label)}</span>` : ''}${control}</label>`,
      });
      const input = dlg.querySelector('#' + id);
      let result = null;
      const accept = () => { result = input.value; closeModal(dlg); };
      dlg.querySelector('[data-role=ok]').addEventListener('click', accept);
      dlg.querySelector('[data-role=cancel]').addEventListener('click', () => closeModal(dlg));
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (!multiline || e.ctrlKey || e.metaKey)) { e.preventDefault(); accept(); }
      });
      openModal(dlg, { focus: '#' + id, onClose: () => { dlg.remove(); resolve(result); } });
      if (!multiline) setTimeout(() => input.select(), 40);
    });
  }

  /* ---------- Búsqueda aproximada (selector, paleta de comandos) ----------
     fuzzyScore('gim', 'Gimnasio') > 0. Sin tildes ni mayúsculas; premia palabras enteras,
     inicios de palabra y letras seguidas. 0 = no encaja. */
  const fold = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  function fuzzyScore(query, text) {
    const q = fold(query).trim(), t = fold(text);
    if (!q) return 1;
    let total = 0;
    for (const word of q.split(/\s+/)) {
      const at = t.indexOf(word);
      if (at >= 0) { total += 10 + word.length * 2 + (at === 0 || /\W/.test(t[at - 1]) ? 8 : 0); continue; }
      // letras en orden (subsecuencia), con premio por seguidas
      // las letras deben quedar cerca (no más del doble del largo de la palabra) y dentro de una misma palabra
      let best = 0;
      for (let from = t.indexOf(word[0]); from >= 0; from = t.indexOf(word[0], from + 1)) {
        let i = from, run = 0, score = 0, ok = true;
        for (const ch of word) {
          const j = t.indexOf(ch, i);
          if (j < 0 || j - from > word.length * 2 || /\s/.test(t.slice(i, j))) { ok = false; break; }
          run = j === i ? run + 1 : 0;
          score += 1 + run;
          i = j + 1;
        }
        if (ok) best = Math.max(best, score);
      }
      if (!best) return 0;
      total += best;
    }
    return total;
  }

  /* ---------- Selector con autocompletado ----------
     uiPick({ title, placeholder, load: async () => [{ id, label, sub, icon }] }) → elemento o null.
     Flechas para moverse, Enter elige, Esc cierra. */
  function uiPick({ title, placeholder = 'Buscar…', load, empty = 'Nada coincide', confirmLabel = null }) {
    return new Promise((resolve) => {
      const id = 'pk' + Math.random().toString(36).slice(2, 8);
      const dlg = buildDialog({
        title, confirmLabel: confirmLabel || 'Elegir', size: 'modal-pick',
        bodyHtml: `<label class="search pick-search" for="${id}">${icon('search')}<span class="sr-only">${escapeHtml(placeholder)}</span>
          <input id="${id}" class="input" type="search" placeholder="${escapeHtml(placeholder)}" autocomplete="off"
            role="combobox" aria-expanded="true" aria-controls="${id}-list" aria-autocomplete="list"></label>
          <ul class="list pick-list" id="${id}-list" role="listbox" aria-label="${escapeHtml(title)}"><li class="pick-empty muted small">Cargando…</li></ul>`,
      });
      const input = dlg.querySelector('#' + id);
      const list = dlg.querySelector('.pick-list');
      let all = [], shown = [], active = 0, result = null;
      const paint = () => {
        const q = input.value;
        shown = all.map((x) => ({ x, s: Math.max(fuzzyScore(q, x.label), fuzzyScore(q, x.sub || '') * 0.6) }))
          .filter((r) => r.s > 0).sort((a, b) => b.s - a.s).slice(0, 50).map((r) => r.x);
        active = Math.min(active, Math.max(0, shown.length - 1));
        list.innerHTML = shown.length ? shown.map((x, i) => `<li role="option" id="${id}-o${i}" class="pick-row" data-i="${i}" aria-selected="${i === active}">
            ${x.icon ? `<span class="pick-icon" aria-hidden="true">${icon(x.icon, 'icon-sm')}</span>` : ''}
            <span class="row-main"><span class="row-title">${escapeHtml(x.label)}</span>${x.sub ? `<span class="row-sub">${escapeHtml(x.sub)}</span>` : ''}</span></li>`).join('')
          : `<li class="pick-empty muted small">${escapeHtml(empty)}</li>`;
        input.setAttribute('aria-activedescendant', shown.length ? `${id}-o${active}` : '');
        list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
      };
      const choose = (i) => { if (shown[i]) { result = shown[i]; closeModal(dlg); } };
      input.addEventListener('input', () => { active = 0; paint(); });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          if (shown.length) { active = (active + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length; paint(); }
        } else if (e.key === 'Enter') { e.preventDefault(); choose(active); }
      });
      list.addEventListener('click', (e) => { const row = e.target.closest('[data-i]'); if (row) choose(Number(row.dataset.i)); });
      dlg.querySelector('[data-role=ok]').addEventListener('click', () => choose(active));
      dlg.querySelector('[data-role=cancel]').addEventListener('click', () => closeModal(dlg));
      openModal(dlg, { focus: '#' + id, onClose: () => { dlg.remove(); resolve(result); } });
      Promise.resolve(load()).then((items) => { all = items || []; paint(); })
        .catch(() => { list.innerHTML = '<li class="pick-empty muted small">No se pudo cargar la lista</li>'; });
    });
  }

  /* ---------- Menú contextual ----------
     openMenu(anchor, [{label, icon, onClick, danger, separator}]) */
  let activeMenu = null;
  function closeMenu() {
    if (!activeMenu) return;
    const { el, anchor, cleanup } = activeMenu;
    activeMenu = null;
    cleanup();
    el.remove();
    anchor?.setAttribute('aria-expanded', 'false');
    anchor?.focus({ preventScroll: true });
  }
  function openMenu(anchor, items, { align = 'end' } = {}) {
    closeMenu();
    const el = document.createElement('div');
    el.className = 'menu';
    el.setAttribute('role', 'menu');
    items.forEach((item) => {
      if (item.separator) { el.insertAdjacentHTML('beforeend', '<div class="menu-sep" role="separator"></div>'); return; }
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'menu-item' + (item.danger ? ' danger' : '');
      b.setAttribute('role', 'menuitem');
      b.innerHTML = (item.icon ? icon(item.icon) : '') + `<span>${escapeHtml(item.label)}</span>`;
      b.addEventListener('click', () => { closeMenu(); item.onClick?.(); });
      el.appendChild(b);
    });
    document.body.appendChild(el);
    const r = anchor.getBoundingClientRect();
    const mw = el.offsetWidth, mh = el.offsetHeight;
    let left = align === 'end' ? r.right - mw : r.left;
    left = Math.max(8, Math.min(left, window.innerWidth - mw - 8));
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    el.style.left = left + 'px';
    el.style.top = top + 'px';
    anchor.setAttribute('aria-expanded', 'true');
    const buttons = [...el.querySelectorAll('.menu-item')];
    buttons[0]?.focus();
    const onKey = (e) => {
      const i = buttons.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); closeMenu(); }
      else if (e.key === 'ArrowDown') { e.preventDefault(); buttons[(i + 1) % buttons.length]?.focus(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); buttons[(i - 1 + buttons.length) % buttons.length]?.focus(); }
      else if (e.key === 'Tab') closeMenu();
    };
    const onDown = (e) => { if (!el.contains(e.target) && !anchor.contains(e.target)) closeMenu(); };
    document.addEventListener('keydown', onKey, true);
    setTimeout(() => document.addEventListener('pointerdown', onDown, true));
    window.addEventListener('resize', closeMenu, { once: true });
    activeMenu = { el, anchor, cleanup: () => { document.removeEventListener('keydown', onKey, true); document.removeEventListener('pointerdown', onDown, true); } };
    return el;
  }

  /* ---------- Estados de carga y vacíos ---------- */
  function skeletonRows(n = 6, cls = 'skeleton-row') {
    return Array.from({ length: n }, (_, i) =>
      `<span class="skeleton ${cls}" style="width:${88 - (i * 7) % 30}%"></span>`).join('');
  }
  function emptyState({ iconName = 'inbox', title, text = '', actionLabel = '', action = '', compact = false }) {
    return `<div class="empty${compact ? ' empty-compact' : ''}">
      <div class="empty-icon">${icon(iconName)}</div>
      <h3>${escapeHtml(title)}</h3>
      ${text ? `<p>${escapeHtml(text)}</p>` : ''}
      ${actionLabel ? `<button type="button" class="btn btn-tinted" data-empty-action="${escapeHtml(action)}">${icon('plus')}${escapeHtml(actionLabel)}</button>` : ''}
    </div>`;
  }

  /* ---------- Tema (sistema / claro / oscuro) ---------- */


  /* ---------- visualViewport: alto real con teclado móvil ---------- */
  function syncViewport() {
    const vv = window.visualViewport;
    const h = vv ? vv.height : window.innerHeight;
    document.documentElement.style.setProperty('--vvh', h + 'px');
  }
  // En táctil, el campo que recibe el foco dentro de un diálogo se centra cuando el teclado
  // ya ha encogido la hoja: así ni el campo ni el botón de guardar del pie quedan tapados
  document.addEventListener('focusin', (e) => {
    const el = e.target;
    if (!el.matches?.('input:not([type=checkbox]):not([type=radio]), textarea, select')) return;
    if (!window.matchMedia('(pointer: coarse)').matches || !el.closest('dialog.modal .modal-body')) return;
    setTimeout(() => { if (document.activeElement === el) el.scrollIntoView({ block: 'center', behavior: 'smooth' }); }, 320);
  });

  /* ---------- Captura rápida y contador (común a todas las pantallas) ----------
     El formulario lo conecta items.js (Items.wireCaptureForm): una sola forma de crear. */
  async function refreshInboxBadge() {
    try {
      const c = await api('/api/items/counts', { quiet: true });
      const n = c.pendientes;
      document.querySelectorAll('[data-inbox-count]').forEach((el) => {
        el.textContent = n > 99 ? '99+' : String(n);
        el.hidden = n === 0;
      });
    } catch {}
  }

  function openCapture(prefill = '') {
    const dlg = document.getElementById('captureModal');
    if (!dlg) return;
    const ta = dlg.querySelector('[data-capture-text]');
    if (prefill) ta.value = prefill;
    openModal(dlg, { focus: '[data-capture-text]' });
  }

  /* ---------- Arranque del shell ---------- */
  function init() {
    syncViewport();
    window.visualViewport?.addEventListener('resize', syncViewport);
    window.addEventListener('resize', syncViewport);
    wireAllDialogs();
    document.addEventListener('click', (e) => {
      const cap = e.target.closest('[data-open-capture]');
      if (cap) { e.preventDefault(); openCapture(); }
      const more = e.target.closest('[data-open-more]');
      // el foco no va al campo de la tecla de captura: la primera pulsación la cambiaría
      if (more) { e.preventDefault(); openModal('moreSheet', { focus: '[data-open-status]' }); }
    });
    // Atajo global: «/» fuera de campos de texto abre la búsqueda. Ctrl+K es la paleta (palette.js);
    // en el editor de notas Ctrl+K inserta un wikilink: ese listener marca defaultPrevented antes.
    document.addEventListener('keydown', (e) => {
      if (e.defaultPrevented) return;
      const tag = (e.target.tagName || '').toLowerCase();
      const typing = ['input', 'textarea', 'select'].includes(tag) || e.target.isContentEditable;
      // Ctrl/Cmd + K abre la paleta de comandos (palette.js); «/» va a la búsqueda de texto completo
      if (e.key === '/' && !typing && !document.querySelector('dialog[open]')) {
        e.preventDefault();
        const q = document.getElementById('q');
        if (location.pathname === '/buscar' && q) { q.focus(); q.select(); } else location.href = '/buscar';
      }
    });
    // Atajo global: "c" abre la captura rápida (fuera de campos de texto)
    document.addEventListener('keydown', (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      // Atajo de la captura rápida: «c» por defecto, configurable en Ajustes (Prefs 'capture-key')
      const key = String(Prefs.get('capture-key', 'c') || 'c').toLowerCase();
      if (e.key.toLowerCase() === key && !e.ctrlKey && !e.metaKey && !e.altKey && !['input', 'textarea', 'select'].includes(tag) &&
          !e.target.isContentEditable && !document.querySelector('dialog[open]')) {
        e.preventDefault();
        openCapture();
      }
    });
    const ck = document.getElementById('captureKeyInput');
    if (ck) {
      ck.value = Prefs.get('capture-key', 'c');
      ck.addEventListener('change', () => {
        const v = ck.value.trim().toLowerCase();
        // g abre los atajos «G + letra», e añade un paso y x selecciona en las listas
        if (!/^[a-zñ]$/.test(v) || 'gex'.includes(v)) { ck.value = Prefs.get('capture-key', 'c'); toast('Elige una letra que no sea G, E ni X', { type: 'info' }); return; }
        Prefs.set('capture-key', v);
        document.querySelectorAll('[data-open-capture]').forEach((b) => { b.title = `Captura rápida (${v.toUpperCase()})`; });
        toast(`Captura rápida con la tecla ${v.toUpperCase()}`);
      });
    }
    wireNavToggle();
    wireThemePicker();
    refreshInboxBadge();
    onDataChange(/^\/api\/(items|inbox|notes|bulk\/notes)/, refreshInboxBadge);
    if ('serviceWorker' in navigator && (location.protocol === 'https:' || ['localhost', '127.0.0.1'].includes(location.hostname) || window.isSecureContext)) {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {});
    }
    window.addEventListener('offline', () => toast('Sin conexión: verás lo último guardado', { type: 'info' }));
    window.addEventListener('online', () => toast('Conexión recuperada'));
  }

  /* ---------- Tema (selector en Ajustes) ----------
     theme-init.js lo aplica antes de pintar; aquí se cambia, se guarda y se avisa con «themechange». */
  function setTheme(name) {
    const root = document.documentElement;
    const apply = () => {
      root.setAttribute('data-theme', name);
      try { localStorage.setItem('theme', name); } catch {}
      syncTheme();
      document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: name } }));
    };
    // Fundido de colores (sin él, un salto brusco); nada si se pide reducir el movimiento
    if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { apply(); return; }
    root.classList.add('theme-switching');
    document.startViewTransition(apply).finished.finally(() => root.classList.remove('theme-switching'));
  }
  function syncTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'mocha';
    document.querySelectorAll('[data-theme-choice]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.themeChoice === current)));
    const meta = document.getElementById('themeColor');
    if (meta) meta.content = getComputedStyle(document.body).backgroundColor;
  }
  function wireThemePicker() {
    const grid = document.querySelector('.theme-grid');
    syncTheme();
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (document.documentElement.getAttribute('data-theme') === 'system') document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: 'system' } }));
      syncTheme();
    });
    if (!grid) return;
    grid.addEventListener('click', (e) => { const b = e.target.closest('[data-theme-choice]'); if (b) setTheme(b.dataset.themeChoice); });
    // Grupo de radio: flechas para moverse y elegir, un solo tabulador
    grid.addEventListener('keydown', (e) => {
      const opts = [...grid.querySelectorAll('[data-theme-choice]')];
      const i = opts.indexOf(document.activeElement);
      if (i < 0) return;
      const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      const next = opts[(i + step + opts.length) % opts.length];
      next.focus();
      setTheme(next.dataset.themeChoice);
    });
    const fixTabs = () => grid.querySelectorAll('[data-theme-choice]').forEach((b) => { b.tabIndex = b.getAttribute('aria-checked') === 'true' ? 0 : -1; });
    fixTabs();
    document.addEventListener('themechange', fixTabs);
  }

  /* ---------- Navegación lateral plegable a iconos ----------
     La preferencia se guarda en el servidor (Prefs 'nav': sobrevive a reiniciar y a cambiar de navegador) y en
     localStorage ('nav'), que theme-init.js aplica antes de pintar para que no parpadee. */
  function wireNavToggle() {
    const root = document.documentElement;
    const btn = document.querySelector('[data-nav-toggle]');
    if (!btn) return;
    const sync = () => {
      const collapsed = root.classList.contains('nav-collapsed');
      btn.setAttribute('aria-expanded', String(!collapsed));
      const label = collapsed ? 'Desplegar menú' : 'Plegar menú';
      btn.title = label + ' (Ctrl+.)';
      btn.setAttribute('aria-label', label);
    };
    const apply = (value) => {
      if (value !== 'collapsed' && value !== 'expanded') return;
      root.classList.toggle('nav-collapsed', value === 'collapsed');
      try { localStorage.setItem('nav', value); } catch {}
      sync();
    };
    const toggle = () => {
      const value = root.classList.contains('nav-collapsed') ? 'expanded' : 'collapsed';
      apply(value);
      Prefs.set('nav', value);
    };
    // Grupos del menú (Planificar, Conocimiento…): plegables y recordados; el de la página actual siempre abierto
    const groups = [...document.querySelectorAll('[data-nav-group]')];
    const paintGroups = () => {
      const folded = Prefs.get('nav-folded', {}) || {};
      groups.forEach((g) => {
        const off = !!folded[g.dataset.navGroup] && !g.classList.contains('is-here');
        g.classList.toggle('is-folded', off);
        g.querySelector('.sidebar-group-label').setAttribute('aria-expanded', String(!off));
      });
    };
    groups.forEach((g) => g.querySelector('.sidebar-group-label').addEventListener('click', () => {
      if (g.classList.contains('is-here')) return;
      const folded = { ...(Prefs.get('nav-folded', {}) || {}) };
      folded[g.dataset.navGroup] = !g.classList.contains('is-folded');
      Prefs.set('nav-folded', folded);
      paintGroups();
    }));
    Prefs.ready.then(paintGroups);
    document.addEventListener('prefs:changed', paintGroups);
    // lo guardado en el servidor manda (p. ej. plegado en otro navegador)
    Prefs.ready.then(() => apply(Prefs.get('nav')));
    document.addEventListener('prefs:changed', () => apply(Prefs.get('nav')));
    btn.addEventListener('click', toggle);
    document.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '.' && !e.altKey) { e.preventDefault(); toggle(); }
    });
    // Sin preferencia guardada, sigue el ancho de la ventana como antes
    window.matchMedia('(max-width: 1023px)').addEventListener('change', (m) => {
      let pref = null;
      try { pref = localStorage.getItem('nav'); } catch {}
      if (!pref) { root.classList.toggle('nav-collapsed', m.matches); sync(); }
    });
    sync();
  }

  /* ---------- Preferencias en el servidor (window.Prefs) ----------
     Plegados y demás estado de la interfaz que debe sobrevivir a reiniciar o cambiar de
     navegador: se guardan en /api/prefs. localStorage es solo la caché para pintar al
     instante; al cargar se pide la versión del servidor y, si cambió, se avisa con
     «prefs:changed» para repintar. */
  const PREFS_CACHE = 'prefs-cache';
  let prefs = {};
  try { prefs = JSON.parse(localStorage.getItem(PREFS_CACHE) || '{}') || {}; } catch {}
  const prefTimers = {};
  const prefPending = new Set();
  function cachePrefs() { try { localStorage.setItem(PREFS_CACHE, JSON.stringify(prefs)); } catch {} }
  function prefGet(key, fallback) { return key in prefs ? prefs[key] : fallback; }
  function prefSet(key, value) {
    prefs[key] = value;
    cachePrefs();
    prefPending.add(key);
    clearTimeout(prefTimers[key]);
    prefTimers[key] = setTimeout(async () => {
      try { await api(`/api/prefs/${encodeURIComponent(key)}`, { method: 'PUT', body: { value: prefs[key] }, quiet: true }); }
      catch { /* sin conexión: queda en la caché y se reenvía en la próxima carga */ return; }
      finally { prefPending.delete(key); }
      try { const dirty = JSON.parse(localStorage.getItem(PREFS_CACHE + ':dirty') || '[]').filter((k) => k !== key); localStorage.setItem(PREFS_CACHE + ':dirty', JSON.stringify(dirty)); } catch {}
    }, 350);
    try { const dirty = new Set(JSON.parse(localStorage.getItem(PREFS_CACHE + ':dirty') || '[]')); dirty.add(key); localStorage.setItem(PREFS_CACHE + ':dirty', JSON.stringify([...dirty])); } catch {}
  }
  // Plegados que antes vivían sueltos en localStorage: se suben una vez al servidor
  function legacyPrefs() {
    const out = {};
    try {
      const items = localStorage.getItem('items-fold');
      if (items) out['items-fold'] = JSON.parse(items) || {};
      const notes = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k?.startsWith('cat:') && localStorage.getItem(k) === 'collapsed') notes[k.slice(4)] = true;
      }
      if (Object.keys(notes).length) out['notes-fold'] = notes;
      const nav = localStorage.getItem('nav');
      if (nav === 'collapsed' || nav === 'expanded') out.nav = nav;
    } catch {}
    return out;
  }
  async function prefsLoad() {
    let server;
    try { server = (await api('/api/prefs', { quiet: true })).prefs || {}; } catch { return; }
    let dirty = [];
    try { dirty = JSON.parse(localStorage.getItem(PREFS_CACHE + ':dirty') || '[]'); } catch {}
    const before = JSON.stringify(prefs);
    const next = { ...server };
    // Lo cambiado aquí sin conexión (o aún sin enviar) gana y se reenvía
    [...new Set([...dirty, ...prefPending])].forEach((k) => { if (k in prefs) { next[k] = prefs[k]; prefSet(k, prefs[k]); } });
    Object.entries(legacyPrefs()).forEach(([k, v]) => { if (!(k in server) && !(k in next)) { next[k] = v; prefSet(k, v); } });
    prefs = next;
    cachePrefs();
    if (JSON.stringify(prefs) !== before) document.dispatchEvent(new CustomEvent('prefs:changed'));
  }
  const Prefs = { get: prefGet, set: prefSet, load: prefsLoad, get ready() { return prefsReady; } };
  const prefsReady = prefsLoad();
  onDataChange(/^\/api\/prefs/, prefsLoad);

  // Colores de categoría (Notas, Baúl): variables del tema activo (--cat-0…9 en themes.css)
  const CATEGORY_COLORS = Array.from({ length: 10 }, (_, i) => `var(--cat-${i})`);

  /* ---------- Días de la semana: L M X J V S D que se marcan y desmarcan ----------
     Una rutina y sus bloques eligen los días igual en todas partes: los 7 = cada día, algunos = esos días.
     La regla «cada N días» solo se crea escribiendo («r: regar cada 2 días»): se muestra sin días marcados
     y se conserva mientras no se marque ninguno. */
  const DAY_NAMES = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
  function dayPicker({ days = null, rule = null, legend = 'Días', hideLegend = false, note = '' } = {}) {
    if (rule) days = rule.freq === 'weekly' ? rule.days : rule.freq === 'interval' ? [] : null;
    return `<fieldset class="day-picker"><legend class="field-label${hideLegend ? ' sr-only' : ''}">${legend}</legend>
      <div class="day-options">${DAY_NAMES.map((n, i) => `<label class="day-option" title="${n.charAt(0).toUpperCase() + n.slice(1)}">
        <input type="checkbox" name="day${i}" data-day="${i}" aria-label="${n}" ${!days || days.includes(i) ? 'checked' : ''}><span aria-hidden="true">${(n === 'miércoles' ? 'X' : n[0]).toUpperCase()}</span></label>`).join('')}</div>
      ${note ? `<p class="tiny muted day-note">${note}</p>` : ''}</fieldset>`;
  }
  const readDays = (root) => [...root.querySelectorAll('[data-day]')].filter((c) => c.checked).map((c) => Number(c.dataset.day));
  // La regla que dicen los días marcados (`current`: la que tiene ahora). null = no hay ninguno marcado.
  function repeatFromDays(root, current = null) {
    const days = readDays(root);
    if (days.length === 7) return { freq: 'daily' };
    if (days.length) return { freq: 'weekly', days };
    return current?.freq === 'interval' ? current : null;
  }
  const everyNote = (rule, text) => (rule?.freq === 'interval' ? `Ahora: ${escapeHtml(text.toLowerCase())}. Marca días si prefieres días fijos.` : '');

  Object.assign(window, {
  dayPicker, readDays, repeatFromDays, everyNote,
    CATEGORY_COLORS,
    icon, escapeHtml, timeAgo, api, toast, openModal, closeModal, uiConfirm, uiAlert, uiPrompt,
    openMenu, closeMenu, skeletonRows, emptyState, setTheme, openCapture, refreshInboxBadge, wireAllDialogs, onDataChange, Prefs, uiPick, fuzzyScore,
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
