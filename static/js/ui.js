/* ==========================================================================
   ui.js — piezas comunes de interfaz (script clásico, sin módulos)
   Expone: icon, escapeHtml, renderMarkdown, sanitizeHtml, api, parseTime, copyText, copied, toast, openModal, closeModal, uiConfirm,
   uiPrompt, openMenu, skeletonRows, emptyState, stateView, showState, openCapture, timeAgo, CATEGORY_COLORS
   Tooltips: cualquier elemento con data-tip (y los botones de solo icono con title) muestra un globo al pasar
   el ratón o con el foco del teclado.
   ========================================================================== */
(function () {
  'use strict';

  /* ---------- Utilidades ---------- */
  function escapeHtml(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  /* ---------- Markdown saneado (S-2): la única forma de pintar Markdown escrito por el usuario ----------
     Sin atributos data-* ni style: el despachador data-call (runCall) ejecuta funciones desde atributos, así que el
     contenido de una nota, una tarea o una bitácora no puede disparar acciones del panel. Lo que el panel añade
     (wikilinks, simulaciones) se inserta después de sanear. Requiere marked y DOMPurify cargados por la página. */
  const PURIFY = { USE_PROFILES: { html: true }, FORBID_ATTR: ['style'], ALLOW_DATA_ATTR: false };
  function sanitizeHtml(html) {
    return window.DOMPurify ? window.DOMPurify.sanitize(html, PURIFY) : escapeHtml(html);
  }
  function renderMarkdown(text, { inline = false, breaks = true } = {}) {
    const src = String(text ?? '');
    if (!window.marked || !window.DOMPurify) {
      return inline ? escapeHtml(src) : `<p>${escapeHtml(src).replace(/\n/g, '<br>')}</p>`;
    }
    const opts = { breaks, gfm: true };
    return sanitizeHtml(inline ? window.marked.parseInline(src, opts) : window.marked.parse(src, opts));
  }

  // Sprite con su versión (ver core/templating.asset): así nunca se mezcla con uno viejo en caché
  const ICONS = document.documentElement.dataset.icons || '/static/icons.svg';
  const ILLS = document.documentElement.dataset.ills || '/static/ilustraciones.svg';
  // Sin label es decorativo (lo nombra el botón o el texto de al lado); con label, el icono informa por sí solo.
  function icon(name, cls = '', { label = '' } = {}) {
    const a11y = label ? `role="img" aria-label="${escapeHtml(label)}"` : 'aria-hidden="true"';
    return `<svg class="icon ${cls}" ${a11y}><use href="${ICONS}#i-${name}"></use></svg>`;
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
    if (method !== 'GET') api.writes++;  // ver Calendar (peticiones compartidas, V-2)
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
    if (res.ok && method !== 'GET' && !body?.dry_run) publishChange(url, method);  // una vista previa no cambia nada
    if (!res.ok) {
      const msg = (data && (data.error || (typeof data.detail === 'string' && data.detail))) || `Error ${res.status}`;
      if (!quiet && res.status !== 401) toast(msg, { type: 'error' });
      const error = new Error(msg); error.status = res.status; error.data = data;
      throw error;
    }
    return data;
  }  api.writes = 0;


  /* ---------- Sincronía entre pestañas ----------
     Cada escritura que pasa por api() se anuncia en un BroadcastChannel; las otras
     pestañas del panel (Inbox, Tareas, Notas…) se enteran al instante, y al volver
     el foco a una pestaña se recarga por si algo cambió fuera (otro dispositivo). */
  const channel = 'BroadcastChannel' in window ? new BroadcastChannel('panel-datos') : null;
  const SYNC_PATHS = /^\/(api\/(items|inbox|notes|bulk\/notes|resources|prefs|contador)|comidas\/api)/;
  let lastLocalChange = 0;
  // Altas que crean tareas, ideas o rutinas por otra puerta: para las demás pestañas es un cambio en /api/items
  const AS_ITEMS = /^\/api\/(capture|routines\/rapida|routines\/\d+\/pasos|routine-templates\/apply)$/;
  function publishChange(url, method) {
    let path = new URL(url, location.href).pathname;
    if (AS_ITEMS.test(path)) path = '/api/items';
    if (!SYNC_PATHS.test(path) || path.endsWith('/reviewed') || path.endsWith('/latido')) return;
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
  // Copiar al portapapeles. Sin https (el móvil por la red local) el navegador no da navigator.clipboard
  // Hay que llamarla DIRECTAMENTE desde el manejador del clic (sin await antes): el método antiguo exige gesto del usuario.
  async function copyText(text) {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(text); return true; } catch { /* probamos a la antigua */ }
    }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.readOnly = true;
    ta.style.cssText = 'position:fixed;opacity:0;pointer-events:none';
    (document.querySelector('dialog[open]') || document.body).appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch { /* sin permiso */ }
    ta.remove();
    return ok;
  }

  /* El propio botón confirma la copia (G-9): su icono de copiar se convierte en un ✓ que se escribe, su texto rueda a
     «Copiado» (si lo tiene) y vuelve solo a los 1,8 s; se anuncia en una región viva. Devuelve ok para encadenar. */
  let copyLive = null;
  function copied(btn, ok = true, label = 'Copiado') {
    if (!ok || !btn) return ok;
    if (!copyLive) {
      copyLive = document.createElement('span');
      copyLive.className = 'sr-only'; copyLive.setAttribute('aria-live', 'polite');
      document.body.append(copyLive);
    }
    copyLive.textContent = ''; setTimeout(() => { copyLive.textContent = label; }, 30);
    const use = btn.querySelector('use[href$="#i-copy"], use[href$="#i-clipboard-copy"], use[href$="#i-check"]');
    const txt = [...btn.querySelectorAll(':scope > span:not(.sr-only)')].find((x) => x.textContent.trim());
    clearTimeout(btn._copiedT);
    if (!btn._copiedPrev) btn._copiedPrev = { href: use?.getAttribute('href'), text: txt?.textContent };
    btn.classList.add('is-copied');
    if (use) use.setAttribute('href', btn._copiedPrev.href.replace(/#i-(clipboard-)?copy$/, '#i-check'));
    if (txt && window.Mov) Mov.roll(txt, label); else if (txt) txt.textContent = label;
    btn._copiedT = setTimeout(() => {
      const prev = btn._copiedPrev;
      btn._copiedPrev = null;
      btn.classList.remove('is-copied');
      if (use && prev?.href) use.setAttribute('href', prev.href);
      if (txt && prev?.text != null) { if (window.Mov) Mov.roll(txt, prev.text); else txt.textContent = prev.text; }
    }, 1800);
    return ok;
  }

  // Hora escrita a mano, siempre en 24 h: «930», «9:30» o «17» → «09:30», «17:00»; vacío = sin hora; null = no se entiende
  function parseTime(v) {
    const t = String(v ?? '').trim();
    if (!t) return '';
    const m = t.match(/^(\d{1,2})(?:[:.,h ]?(\d{2}))?$/);
    if (!m || Number(m[1]) > 23 || Number(m[2] || 0) > 59) return null;
    return `${m[1].padStart(2, '0')}:${m[2] || '00'}`;
  }

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
    if (type === 'error') window.Sonido?.play('error');  // solo si el sonido está encendido (sonido.js)
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
    // Con un diálogo modal abierto lo de fuera es inerte y queda bajo el fondo: el aviso (y su «Deshacer») va dentro
    const modal = [...document.querySelectorAll('dialog[open]')].pop();
    let region = toastRegion;
    if (modal) {
      region = modal.querySelector(':scope > .toast-region');
      if (!region) {
        region = document.createElement('div');
        region.className = 'toast-region';
        region.setAttribute('role', 'status');
        region.setAttribute('aria-live', 'polite');
        modal.appendChild(region);
        // si el diálogo se cierra con el aviso aún visible (copiar y cerrar, guardar y cerrar…), el aviso sigue fuera
        modal.addEventListener('close', () => { toastRegion.append(...region.children); region.remove(); }, { once: true });
      }
    }
    region.appendChild(el);
    timer = setTimeout(dismiss, duration);
    return dismiss;
  }

  /* Aviso de un borrado que fue a la papelera: «Deshacer» lo restaura (POST /api/trash/{db}/{token}/restore) y
     llama a `after` para repintar. `res` es la respuesta del DELETE ({ undo_token, undo_db }). */
  function undoToast(message, res, after) {
    const token = res && res.undo_token;
    return toast(message, { action: token ? { label: 'Deshacer', onClick: async () => {
      try {
        const r = await api(`/api/trash/${res.undo_db || 'brain'}/${encodeURIComponent(token)}/restore`, { method: 'POST' });
        if (r && r.restored === 0) toast('No se pudo deshacer: ya existe algo igual', { type: 'info' });
        else toast('Restaurado');
      } catch { return; }
      if (after) await after();
    } } : null });
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
      if (opener && document.contains(opener) && typeof opener.focus === 'function') {
        opener.focus({ preventScroll: true });
        // Si el diálogo se quitó del documento con el cursor dentro, la selección se queda allí y lo que se escribe
        // en el campo que recupera el foco no entra (p. ej. la línea rápida del calendario tras «Más opciones»)
        if (/^(INPUT|TEXTAREA)$/.test(opener.tagName)) {
          try { const n = opener.value.length; opener.setSelectionRange(n, n); } catch { /* tipos sin selección (date, number…) */ }
        }
      }
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
      const pill = window.Mov ? Mov.glide(list, { className: 'glide-pill pick-pill' }) : null;
      if (pill) list.classList.add('has-glide');
      const paint = () => {
        const q = input.value;
        shown = all.map((x) => ({ x, s: Math.max(fuzzyScore(q, x.label), fuzzyScore(q, x.sub || '') * 0.6) }))
          .filter((r) => r.s > 0).sort((a, b) => b.s - a.s).slice(0, 50).map((r) => r.x);
        active = Math.min(active, Math.max(0, shown.length - 1));
        const pintar = () => { list.innerHTML = shown.length ? shown.map((x, i) => `<li role="option" id="${id}-o${i}" class="pick-row" data-i="${i}" data-key="${escapeHtml(`${x.label}|${x.sub || ''}`)}" aria-selected="${i === active}">
            ${x.icon ? `<span class="pick-icon" aria-hidden="true">${icon(x.icon, 'icon-sm')}</span>` : ''}
            <span class="row-main"><span class="row-title">${escapeHtml(x.label)}</span>${x.sub ? `<span class="row-sub">${escapeHtml(x.sub)}</span>` : ''}</span></li>`).join('')
          : `<li class="pick-empty muted small">${escapeHtml(empty)}</li>`; };
        if (window.Mov) Mov.flipList(list, '.pick-row', (el) => el.dataset.key, pintar); else pintar();
        input.setAttribute('aria-activedescendant', shown.length ? `${id}-o${active}` : '');
        list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
        pill?.to(list.querySelector('[aria-selected="true"]'));
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
    // Sale con un fundido corto (ds.css: .menu.is-leaving); el foco y el estado cambian ya
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || !el.isConnected) el.remove();
    else { el.classList.add('is-leaving'); el.inert = true; el.setAttribute('aria-hidden', 'true'); setTimeout(() => el.remove(), 120); }  // el que se va ya no existe para nadie
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
      if (item.icon) b.dataset.icon = item.icon;  // ds.css: cada icono hace su gesto al pasar (el + gira, la papelera…)
      b.style.setProperty('--i', String(Math.min(el.children.length, 10)));
      // checked: opción de un grupo (estado, prioridad…); la elegida lleva el icono de marca al final
      const choice = 'checked' in item;
      b.setAttribute('role', choice ? 'menuitemradio' : 'menuitem');
      if (choice) b.setAttribute('aria-checked', String(!!item.checked));
      b.innerHTML = (item.icon ? icon(item.icon) : '') + `<span>${escapeHtml(item.label)}</span>` +
        (choice ? `<span class="menu-check">${item.checked ? icon('check', 'icon-sm') : ''}</span>` : '');
      b.addEventListener('click', () => { closeMenu(); item.onClick?.(); });
      el.appendChild(b);
    });
    // Dentro de un diálogo modal todo lo de fuera es inerte: el menú va dentro del diálogo de su botón
    (anchor.closest('dialog[open]') || document.body).appendChild(el);
    const r = anchor.getBoundingClientRect();
    const mw = el.offsetWidth, mh = el.offsetHeight;
    let left = align === 'end' ? r.right - mw : r.left;
    left = Math.max(8, Math.min(left, window.innerWidth - mw - 8));
    let top = r.bottom + 6;
    if (top + mh > window.innerHeight - 8) top = Math.max(8, r.top - mh - 6);
    el.style.left = left + 'px';
    el.style.top = top + 'px';
    // Nace de su botón: el origen de la escala es el borde del menú más cercano al botón, a la altura de su centro
    const encima = top < r.top;
    el.style.transformOrigin = `${Math.max(0, Math.min(mw, r.left + r.width / 2 - left))}px ${encima ? mh : 0}px`;
    el.style.setProperty('--menu-dy', encima ? '6px' : '-6px');
    anchor.setAttribute('aria-expanded', 'true');
    const buttons = [...el.querySelectorAll('.menu-item')];
    // Una sola píldora viaja bajo la opción señalada (ratón o teclado) en vez de encenderse fila a fila
    const pill = window.Mov && !matchMedia('(hover: none)').matches ? Mov.glide(el, { className: 'glide-pill menu-pill' }) : null;
    if (pill) {
      el.classList.add('has-glide');
      const ir = (b) => { pill.to(b); pill.el.classList.toggle('is-danger', b.classList.contains('danger')); };
      el.addEventListener('pointerover', (e) => { const b = e.target.closest('.menu-item'); if (b) ir(b); });
      el.addEventListener('pointerleave', () => { const f = el.querySelector('.menu-item:focus-visible'); if (f) ir(f); else pill.hide(); });
      el.addEventListener('focusin', (e) => { if (e.target.matches('.menu-item:focus-visible')) ir(e.target); });
      el.addEventListener('scroll', () => pill.refresh(), { passive: true });
    }
    buttons[0]?.focus();
    if (pill && buttons[0]?.matches(':focus-visible')) pill.to(buttons[0]);
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
  /* ---------- Estados con ilustración: vacío, hecho, sin resultados, error y sin conexión ----------
     stateView devuelve el HTML; showState lo pinta en un elemento y conecta «Reintentar» (onRetry).
     El tono de la ilustración dice el tipo de mensaje; error y sin conexión se anuncian (role="alert"). */
  const STATES = { empty: ['vacio', 'accent'], done: ['hecho', 'success'], 'no-results': ['sin-resultados', 'accent'],
    error: ['error', 'danger'], offline: ['sin-conexion', 'warning'] };
  function stateView({ kind = 'empty', title, text = '', actionLabel = '', action = '', retry = false, compact = false }) {
    const [ill, tone] = STATES[kind] || STATES.empty;
    const alert = kind === 'error' || kind === 'offline' ? ' role="alert"' : '';
    const btn = retry ? `<button type="button" class="btn btn-tinted" data-state-retry>${icon('rotate-ccw')}Reintentar</button>`
      : actionLabel ? `<button type="button" class="btn btn-tinted" data-empty-action="${escapeHtml(action)}">${icon('plus')}${escapeHtml(actionLabel)}</button>` : '';
    return `<div class="empty state${compact ? ' empty-compact' : ''}" data-state-kind="${kind}" style="--ill-accent: var(--${tone})"${alert}>
      <svg class="ill" aria-hidden="true"><use href="${ILLS}#ill-${ill}"></use></svg>
      <h3>${escapeHtml(title)}</h3>${text ? `<p>${escapeHtml(text)}</p>` : ''}${btn}</div>`;
  }
  function showState(el, opts, onRetry) {
    if (!el) return;
    el.innerHTML = stateView({ ...opts, retry: !!onRetry || opts.retry });
    const b = el.querySelector('[data-state-retry]');
    if (b && onRetry) b.addEventListener('click', () => { b.classList.add('is-loading'); onRetry(); });
  }
  // Error de carga: «sin conexión» si el navegador no tiene red, «no se pudo cargar» si el panel falló
  const loadFailed = (title, compact = false) => (navigator.onLine === false
    ? { kind: 'offline', title: 'Sin conexión con el panel', text: 'Se actualizará al volver a la red de casa.', compact }
    : { kind: 'error', title, text: 'El panel no ha respondido. Tus datos están guardados.', compact });

  function emptyState({ iconName = 'inbox', title, text = '', actionLabel = '', action = '', compact = false }) {
    return `<div class="empty${compact ? ' empty-compact' : ''}">
      <div class="empty-icon">${icon(iconName)}</div>
      <h3>${escapeHtml(title)}</h3>
      ${text ? `<p>${escapeHtml(text)}</p>` : ''}
      ${actionLabel ? `<button type="button" class="btn btn-tinted" data-empty-action="${escapeHtml(action)}">${icon('plus')}${escapeHtml(actionLabel)}</button>` : ''}
    </div>`;
  }

  /* ---------- Cambio de sección fluido en todos los navegadores ----------
     Chrome y Safari 18.2+ hacen la transición entre páginas con @view-transition (ds.css). Donde no la hay (Firefox),
     el contenido se va al pulsar el enlace (la página nueva se pide a la vez: no se retrasa nada) y la nueva entra
     animada desde el primer pintado (theme-init.js lee la marca). Además, al apuntar a un enlace del menú o tocarlo,
     la página se pide por adelantado (<link rel=prefetch>), así llega antes. */
  (() => {
    const conTransicion = 'CSSViewTransitionRule' in window;
    const quieto = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
    const interno = (a, e) => {
      if (!a || !a.href || a.target && a.target !== '_self' || a.hasAttribute('download') || e?.defaultPrevented) return null;
      if (e && (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) return null;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin || u.pathname.startsWith('/api/') || u.pathname.startsWith('/static/')) return null;
      if (u.pathname === location.pathname && u.search === location.search) return null;  // misma página (o un ancla)
      return u;
    };
    // Salida (solo sin transición del navegador)
    document.addEventListener('click', (e) => {
      const a = e.target.closest?.('a[href]');
      const u = interno(a, e);
      if (!u || conTransicion || quieto()) return;
      setTimeout(() => {  // tras los manejadores de la pantalla: si alguno la cancela, no hay navegación
        if (e.defaultPrevented) return;
        try { sessionStorage.setItem('panel.nav-anim', String(Date.now())); } catch {}
        document.documentElement.classList.add('nav-saliendo');
        // Si al final no se navega (una descarga, un 204), la página no se queda desvanecida
        setTimeout(() => document.documentElement.classList.remove('nav-saliendo'), 3000);
      });
    });
    // Al volver con Atrás desde la caché, la página no puede seguir desvanecida
    window.addEventListener('pageshow', () => document.documentElement.classList.remove('nav-saliendo'));
    document.documentElement.addEventListener('animationend', (e) => {
      if (/^vt-(page-in|entra-)/.test(e.animationName)) document.documentElement.classList.remove('nav-entrando');
    });
    // Al irse, la posición de esta sección en el menú: la página nueva sabe así hacia qué lado entrar (theme-init.js)
    window.addEventListener('pagehide', () => {
      const i = document.documentElement.dataset.sec;
      try { if (i != null && Number(i) >= 0) sessionStorage.setItem('panel.sec', `${i}|${Date.now()}`); } catch {}
    });
    // Pedir por adelantado lo que se va a abrir (menú, pestañas, hoja «Más»)
    const pedidas = new Set();
    const adelantar = (a) => {
      const u = interno(a);
      if (!u || pedidas.has(u.href) || pedidas.size > 20 || navigator.connection?.saveData) return;
      pedidas.add(u.href);
      const l = document.createElement('link');
      l.rel = 'prefetch';
      l.href = u.href;
      document.head.appendChild(l);
    };
    const NAV = '.sidebar a[href], .tabbar a[href], #moreSheet a[href], .sidebar-brand';
    let espera = 0;
    document.addEventListener('pointerover', (e) => {
      const a = e.target.closest?.(NAV);
      if (!a || e.pointerType !== 'mouse') return;
      clearTimeout(espera);
      espera = setTimeout(() => adelantar(a), 80);  // pasar por encima sin pararse no pide nada
    });
    document.addEventListener('pointerdown', (e) => adelantar(e.target.closest?.(NAV)), { passive: true });
  })();

  /* ---------- Control segmentado con píldora que se desliza ----------
     Al pulsar otra opción de un .segmented, el fondo de la elegida viaja desde la anterior con un muelle (una copia
     del fondo que se anima de un sitio a otro y desaparece; el control no guarda estado y sirve aunque la pantalla
     lo repinte al momento). */
  (() => {
    if (!Element.prototype.animate) return;
    const MUELLE = getComputedStyle(document.documentElement).getPropertyValue('--spring').trim() || 'cubic-bezier(0.34, 1.36, 0.64, 1)';
    const ACTIVA = 'button[aria-pressed="true"], button[aria-selected="true"], button.active';
    document.addEventListener('click', (e) => {
      const b = e.target.closest?.('.segmented > button');
      if (!b || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      const seg = b.parentElement;
      const antes = seg.querySelector(`:scope > :is(${ACTIVA})`);
      if (!antes || antes === b) return;
      const ra = antes.getBoundingClientRect();
      const indice = [...seg.children].indexOf(b);
      requestAnimationFrame(() => {
        // La pantalla pudo repintar el control: se busca el nuevo en el mismo sitio
        const ahora = seg.isConnected ? seg : document.elementFromPoint(ra.left + 2, ra.top + 2)?.closest('.segmented');
        const nueva = ahora?.querySelector(`:scope > :is(${ACTIVA})`);
        if (!ahora || !nueva || ahora.children[indice] !== nueva) return;
        const rn = nueva.getBoundingClientRect(), rs = ahora.getBoundingClientRect();
        if (!rn.width) return;
        const cs = getComputedStyle(nueva);
        const pil = document.createElement('span');
        pil.className = 'seg-pill';
        pil.setAttribute('aria-hidden', 'true');
        Object.assign(pil.style, {
          left: `${rn.left - rs.left}px`, top: `${rn.top - rs.top}px`, width: `${rn.width}px`, height: `${rn.height}px`,
          background: cs.backgroundColor, boxShadow: cs.boxShadow, borderRadius: cs.borderRadius,
        });
        ahora.classList.add('seg-moviendo');
        ahora.prepend(pil);
        const dx = ra.left - rn.left, ex = ra.width / rn.width;
        const a = pil.animate([
          { transform: `translateX(${dx}px) scaleX(${ex})` },
          { transform: 'none' },
        ], { duration: 460, easing: MUELLE });
        a.onfinish = a.oncancel = () => { pil.remove(); ahora.classList.remove('seg-moviendo'); };
      });
    }, true);
  })();

  /* ---------- T-2 · Título compacto al desplazar (móvil) ----------
     En el móvil la cabecera se va con la página. Cuando su título deja de verse, arriba aparece una franja fina con el
     nombre de la sección (entra con un leve desenfoque hacia arriba, como el título grande de iOS); tocarla vuelve
     arriba. Es un elemento aparte fijado arriba: no cambia la cabecera, las hojas, el teclado ni «tirar para recargar». */
  (() => {
    const mq = matchMedia('(max-width: 767px)');
    const head = document.querySelector('.main > .page-header'), h1 = head?.querySelector('.page-title h1');
    if (!head || !h1 || !('IntersectionObserver' in window)) return;
    let bar = null;
    const mostrar = (on) => {
      if (on && !bar) {
        bar = document.createElement('button');
        bar.type = 'button';
        bar.className = 'mini-title';
        bar.setAttribute('aria-label', 'Volver arriba');
        bar.addEventListener('click', () => {
          const smooth = window.Mov && !Mov.reduce() ? 'smooth' : 'auto';
          [document.scrollingElement, document.querySelector('.main'), document.querySelector('.main > .page-body')].forEach((x) => x?.scrollTo?.({ top: 0, behavior: smooth }));
        });
        document.body.appendChild(bar);
      }
      if (!bar) return;
      if (on) bar.textContent = h1.textContent.trim();
      bar.classList.toggle('is-on', on);
      bar.tabIndex = on ? 0 : -1;
      bar.setAttribute('aria-hidden', String(!on));
    };
    new IntersectionObserver(([e]) => mostrar(mq.matches && !e.isIntersecting && e.boundingClientRect.top < 0), { threshold: 0 }).observe(h1);
    mq.addEventListener?.('change', () => { if (!mq.matches) mostrar(false); });
  })();

  /* ---------- Tirar para recargar (móvil) ----------
     En el móvil la página se desplaza dentro de .main, así que Safari no tiene su «tirar para recargar». Arrastrando
     hacia abajo desde arriba del todo, el contenido sigue al dedo como una goma (cada vez más dura) y un anillo se
     llena; pasada la marca la flecha se da la vuelta y al soltar se recarga la página. Antes de la marca, todo
     vuelve a su sitio con un muelle. No se activa dentro de diálogos, campos, lienzos ni zonas que se arrastran. */
  (() => {
    if (!matchMedia('(pointer: coarse)').matches || !Element.prototype.animate) return;
    const MARCA = 76, TOPE = 150;
    const EVITAR = 'dialog, input, textarea, select, [contenteditable="true"], canvas, svg.graph, [draggable="true"], .board, .board-canvas, .sortable-handle, [data-no-ptr]';
    let ini = null, tirado = 0, armado = false, ind = null, cuerpo = null;
    const goma = (d) => TOPE * (1 - Math.exp(-Math.max(0, d) / TOPE));
    const indicador = () => {
      if (ind) return ind;
      ind = document.createElement('div');
      ind.className = 'ptr';
      ind.setAttribute('aria-hidden', 'true');
      ind.innerHTML = '<svg viewBox="0 0 40 40"><circle class="ptr-pista" cx="20" cy="20" r="15"/><circle class="ptr-arco" cx="20" cy="20" r="15" pathLength="100" transform="rotate(-90 20 20)"/><path class="ptr-flecha" d="M20 13v14M15 22l5 5 5-5"/></svg>';
      const pb = main.querySelector(':scope > .page-body');
      ind.style.top = `${Math.round(pb ? pb.getBoundingClientRect().top : 56)}px`;
      document.body.appendChild(ind);
      return ind;
    };
    const pintar = (v) => {
      const p = Math.min(1, v / MARCA);
      const el = indicador();
      el.style.opacity = String(Math.min(1, v / 24));
      el.style.transform = `translate(-50%, ${Math.round(v * 0.55 - 44)}px) scale(${(0.6 + 0.4 * p).toFixed(3)})`;
      el.querySelector('.ptr-arco').style.strokeDasharray = `${(p * 100).toFixed(1)} 100`;
      if (cuerpo) cuerpo.style.transform = `translateY(${v.toFixed(1)}px)`;
    };
    const main = document.querySelector('.app > .main');
    if (!main) return;
    // Lo que se desplaza es el .page-body (las pantallas sin él, el propio .main)
    const scroller = () => main.querySelector(':scope > .page-body') || main;
    main.addEventListener('touchstart', (e) => {
      ini = null;
      if (e.touches.length !== 1 || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
      if (e.target.closest?.(EVITAR) || document.querySelector('dialog[open]')) return;
      // Un contenedor propio desplazado por dentro (una lista) tampoco
      for (let n = e.target; n && n !== main; n = n.parentElement) {
        if (n.scrollTop > 0) return;
      }
      if (scroller().scrollTop > 0) return;
      ini = { x: e.touches[0].clientX, y: e.touches[0].clientY, activo: false };
    }, { passive: true });
    main.addEventListener('touchmove', (e) => {
      if (!ini) return;
      const dx = e.touches[0].clientX - ini.x, dy = e.touches[0].clientY - ini.y;
      if (!ini.activo) {
        if (dy < 8 || Math.abs(dx) > dy || scroller().scrollTop > 0) { if (Math.abs(dx) > 8 || dy < -4) ini = null; return; }
        ini.activo = true;
        ini.y += 8;
        cuerpo = main.querySelector(':scope > .page-body') || main;
        cuerpo.style.willChange = 'transform';
      }
      e.preventDefault();
      tirado = goma(e.touches[0].clientY - ini.y);
      const pasa = tirado >= MARCA;
      if (pasa !== armado) {
        armado = pasa;
        indicador().classList.toggle('is-armado', pasa);
        if (pasa) navigator.vibrate?.(8);
      }
      pintar(tirado);
    }, { passive: false });
    const soltar = () => {
      if (!ini?.activo) { ini = null; return; }
      ini = null;
      const el = indicador();
      const c = cuerpo;
      if (armado) {
        el.classList.add('is-cargando');
        const hasta = 48;
        c.animate([{ transform: `translateY(${tirado}px)` }, { transform: `translateY(${hasta}px)` }], { duration: 220, easing: 'ease-out', fill: 'forwards' });
        pintar(hasta);
        c.style.transform = `translateY(${hasta}px)`;
        setTimeout(() => location.reload(), 380);
        return;
      }
      const v0 = tirado;
      const a = c.animate([{ transform: `translateY(${v0}px)` }, { transform: 'none' }], {
        duration: 520, easing: getComputedStyle(document.documentElement).getPropertyValue('--spring').trim() || 'ease-out',
      });
      c.style.transform = '';
      el.animate([{ opacity: el.style.opacity }, { opacity: 0 }], { duration: 160, fill: 'forwards' }).onfinish = () => {
        el.remove(); ind = null;
      };
      a.onfinish = a.oncancel = () => { c.style.willChange = ''; };
      tirado = 0; armado = false;
    };
    main.addEventListener('touchend', soltar);
    main.addEventListener('touchcancel', soltar);
  })();

  /* ---------- Plegables y <details> animados ----------
     Cualquier botón con aria-expanded que controla una zona (aria-controls, o los [data-il-fold] de ItemList) la abre
     y cierra con altura + fundido. Antes del clic (captura) se toma una foto de la zona (altura y display); después del
     clic (al final de la propagación, cuando la pantalla ya ha hecho su cambio, aunque haya repintado) se anima de la
     foto al estado nuevo. Al cerrar, la zona ya está oculta: se enseña un momento con su display de antes (inert) y se
     encoge. Los <details> igual, abriendo y cerrando a mano. Nada con «reducir movimiento». En una zona más alta que la
     ventana se anima solo lo que se ve (hasta 1,2 pantallas): lo de más abajo aparece o se va fuera de la vista. */
  (() => {
    const ABRIR_MS = 220, CERRAR_MS = 160;
    const tope = (h) => Math.min(h, Math.round(innerHeight * 1.2));
    const EXPO = 'cubic-bezier(0.16, 1, 0.3, 1)', SALIDA = 'cubic-bezier(0.2, 0.8, 0.2, 1)';
    const quieto = () => matchMedia('(prefers-reduced-motion: reduce)').matches || !Element.prototype.animate;
    const visible = (el) => !!el && el.isConnected && getComputedStyle(el).display !== 'none' && el.getClientRects().length > 0;
    const clave = (b) => b.dataset.ilFold != null ? `il:${b.dataset.ilFold}` : b.getAttribute('aria-controls') ? `id:${b.getAttribute('aria-controls')}` : null;
    const zonaDe = (b) => {
      if (b.dataset.ilFold != null) return b.closest('.il-group-head, .il-cat-head, .il-note-head')?.nextElementSibling || null;
      const id = b.getAttribute('aria-controls');
      return id ? document.getElementById(id) : null;
    };
    const botonDe = (k) => k.startsWith('il:') ? document.querySelector(`[data-il-fold="${CSS.escape(k.slice(3))}"]`)
      : document.querySelector(`[aria-controls="${CSS.escape(k.slice(3))}"][aria-expanded]`);
    const esPlegable = (b) => b && b.hasAttribute('aria-expanded') && !b.hasAttribute('aria-haspopup')
      && !['combobox', 'tab', 'menuitem'].includes(b.getAttribute('role')) && !b.closest('.menu, [role="menu"], [role="listbox"]');
    const pad = (cs) => ({ paddingTop: cs.paddingTop, paddingBottom: cs.paddingBottom });

    function abrir(el) {
      const h = tope(el.offsetHeight);
      if (!h) return;
      const cs = getComputedStyle(el);
      const prev = el.style.overflow;
      el.style.overflow = 'clip';
      const a = el.animate([
        { height: '0px', paddingTop: '0px', paddingBottom: '0px', opacity: 0 },
        { height: `${h}px`, ...pad(cs), opacity: 1 },
      ], { duration: ABRIR_MS, easing: EXPO });
      a.onfinish = a.oncancel = () => { el.style.overflow = prev; };
      // Lo de dentro entra en cascada desde la izquierda (tope 12) y, si tiene guía (árboles), la línea se traza
      el.classList.add('fold-opening');
      setTimeout(() => el.classList.remove('fold-opening'), 500);
      const hijos = [...el.children].filter((c) => c.getClientRects().length && !c.matches('script, template, datalist'));
      if (window.Mov && hijos.length > 1 && hijos.length < 80) {
        Mov.stagger(hijos.slice(0, 12), [{ opacity: 0, transform: 'translateX(-8px)' }, { opacity: 1, transform: 'none' }],
          { each: 22, duration: 300, easing: EXPO, delay: 30 });
      }
    }
    function cerrar(el, foto) {
      if (!foto.alto) return;
      el.style.setProperty('display', foto.display, 'important');
      el.style.overflow = 'clip';
      el.inert = true;
      const ariaAntes = el.getAttribute('aria-hidden');
      el.setAttribute('aria-hidden', 'true');  // ya está plegada: solo se ve marcharse
      const a = el.animate([
        { height: `${tope(foto.alto)}px`, paddingTop: foto.pt, paddingBottom: foto.pb, opacity: 1 },
        { height: '0px', paddingTop: '0px', paddingBottom: '0px', opacity: 0 },
      ], { duration: CERRAR_MS, easing: SALIDA });
      a.onfinish = a.oncancel = () => { el.style.removeProperty('display'); el.style.overflow = ''; el.inert = false;
        if (ariaAntes === null) el.removeAttribute('aria-hidden'); else el.setAttribute('aria-hidden', ariaAntes);
      };
    }

    let foto = null;
    document.addEventListener('click', (e) => {
      foto = null;
      if (quieto()) return;
      const b = e.target.closest?.('[aria-expanded]');
      if (!esPlegable(b)) return;
      const k = clave(b), z = k && zonaDe(b);
      if (!z) return;
      z.getAnimations().forEach((an) => an.cancel());  // otro clic a mitad: se parte del estado real, no del animado
      const cs = getComputedStyle(z);
      foto = { k, abierta: visible(z), alto: z.offsetHeight, display: cs.display, pt: cs.paddingTop, pb: cs.paddingBottom, zona: z };
    }, true);
    const despues = () => {
      const f = foto;
      foto = null;
      if (!f) return;
      const b = botonDe(f.k);
      const z = b && zonaDe(b);
      if (!z) return;
      const ahora = visible(z);
      if (ahora && !f.abierta) abrir(z);
      else if (!ahora && f.abierta) cerrar(z, f);
    };
    window.addEventListener('click', despues);  // burbuja en window: después de los manejadores de la pantalla

    // <details>: se abre y cierra a mano para poder medir (el evento toggle llega igual)
    document.addEventListener('click', (e) => {
      const s = e.target.closest?.('summary');
      const d = s?.parentElement;
      if (!d || d.tagName !== 'DETAILS' || s !== d.querySelector(':scope > summary') || quieto() || e.defaultPrevented) return;
      if (d.dataset.animando) { e.preventDefault(); return; }
      const cs = getComputedStyle(d);
      const cerrado = s.offsetHeight + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth);
      e.preventDefault();
      const desde = tope(d.offsetHeight);
      d.style.overflow = 'clip';
      d.dataset.animando = '1';
      const fin = () => { d.style.overflow = ''; delete d.dataset.animando; };
      if (d.open) {
        const a = d.animate([{ height: `${desde}px` }, { height: `${cerrado}px` }], { duration: CERRAR_MS, easing: SALIDA });
        a.onfinish = () => { d.open = false; fin(); };
        a.oncancel = fin;
      } else {
        d.open = true;
        const hasta = tope(d.offsetHeight);
        const a = d.animate([{ height: `${desde}px` }, { height: `${hasta}px` }], { duration: ABRIR_MS, easing: EXPO });
        a.onfinish = a.oncancel = fin;
      }
    }, true);
  })();

  /* ---------- Zonas de soltar archivos ([data-drop]) ----------
     Mientras se arrastran archivos por la ventana, <html> lleva .files-dragging y todas las zonas se encienden (borde
     de acento); encima de una, .is-over (la pone cada pantalla) la hace línea continua; al soltar, una onda sale de
     la zona. Solo es aspecto: cada pantalla sigue con sus propios manejadores de drop. */
  (() => {
    let depth = 0;
    const conArchivos = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
    const fin = () => { depth = 0; document.documentElement.classList.remove('files-dragging'); };
    window.addEventListener('dragenter', (e) => {
      if (!conArchivos(e)) return;
      depth++;
      if (document.querySelector('[data-drop]')) document.documentElement.classList.add('files-dragging');
    });
    window.addEventListener('dragleave', (e) => { if (conArchivos(e) && --depth <= 0) fin(); });
    window.addEventListener('dragend', fin);
    window.addEventListener('drop', (e) => {
      const z = e.target.closest?.('[data-drop]');
      fin();
      if (z && window.Mov && !Mov.reduce()) {
        z.animate([{ boxShadow: '0 0 0 0 color-mix(in srgb, var(--accent) 45%, transparent)' }, { boxShadow: '0 0 0 14px transparent' }], { duration: 560, easing: 'ease-out' });
        z.animate([{ scale: '0.98' }, { scale: '1' }], { duration: 420, easing: 'cubic-bezier(0.34, 1.7, 0.64, 1)' });
      }
    }, true);
  })();

  /* ---------- Micro-interacción común de las casillas (.card-check) ----------
     Al marcar como hecha, la casilla «entra» con un halo (ds.css: is-just-checked). Cada pantalla repinta a su manera
     (Hoy, Rutinas, Calendario, Universidad…), así que se recuerda qué casilla se pulsó (sus data-* y los del elemento
     que la contiene) y se anima la que aparezca marcada con esos datos en el siguiente segundo. Si encajan varias, no
     se anima ninguna (mejor nada que la equivocada). Las listas de ItemList van por su cuenta (Items.recent). */
  (() => {
    const VENTANA = 900;
    let last = null;
    const datos = (el) => (el ? [...el.attributes].filter((a) => a.name.startsWith('data-')).map((a) => `${a.name}=${a.value}`).sort().join('|') : '');
    const firma = (b) => `${datos(b)}#${datos(b.parentElement?.closest('[data-id],[data-key],[data-step],[data-item],[data-ev]'))}`;
    const pop = (el, ms) => {
      el.style.setProperty('--anim-t', `-${Math.round(ms)}ms`);
      el.classList.add('is-just-checked');
      setTimeout(() => el.classList.remove('is-just-checked'), VENTANA);
    };
    document.addEventListener('click', (e) => {
      const b = e.target.closest?.('.card-check');
      if (!b || b.disabled || b.classList.contains('done') || b.closest('.il-item')) return;
      last = { firma: firma(b), at: performance.now(), el: b };
      // Pantallas que solo cambian la clase en el sitio, sin repintar
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (last?.el.isConnected && last.el.classList.contains('done')) pop(last.el, performance.now() - last.at);
      }));
    }, true);
    new MutationObserver((muts) => {
      if (!last) return;
      const ms = performance.now() - last.at;
      if (ms > VENTANA) { last = null; return; }
      const encajan = [];
      for (const m of muts) for (const n of m.addedNodes) {
        if (n.nodeType !== 1) continue;
        const cs = n.matches('.card-check.done') ? [n] : n.querySelectorAll('.card-check.done');
        cs.forEach((c) => { if (!c.closest('.il-item') && firma(c) === last.firma) encajan.push(c); });
      }
      if (encajan.length === 1) pop(encajan[0], ms);
    }).observe(document.documentElement, { childList: true, subtree: true });
  })();

  /* ---------- Tema (sistema / claro / oscuro) ---------- */


  /* ---------- Tooltip (data-tip) ----------
     Un solo globo que vive en la capa superior (popover): no lo recorta un contenedor con overflow ni lo tapa un
     diálogo abierto. Sale al pasar el ratón (con retardo) o con el foco del teclado; nunca con el dedo. Los botones
     de solo icono con title lo adoptan solos (title → data-tip y, si les faltaba, aria-label): sin globo doble. */
  const ICON_ONLY = '.btn-icon, .tb-btn, .tool-btn';
  let tipEl = null, tipFor = null, tipTimer = 0;
  function adoptTitle(el) {
    if (!el?.matches?.(ICON_ONLY) || !el.hasAttribute('title')) return;
    const t = el.getAttribute('title');
    el.removeAttribute('title');
    if (!el.dataset.tip) el.dataset.tip = t;
    if (!el.hasAttribute('aria-label') && !el.hasAttribute('aria-labelledby')) el.setAttribute('aria-label', t);
  }
  // Gracia: tras ver un globo, el siguiente sale ya (y viaja desde donde estaba) durante TIP_GRACE ms
  const TIP_GRACE = 700;
  let tipOffAt = 0;
  function hideTip() {
    clearTimeout(tipTimer);
    if (!tipEl || !tipFor) return;
    tipFor = null;
    tipOffAt = performance.now();
    tipEl.classList.remove('is-on');
    // Se queda en la capa superior (invisible) durante la gracia, para poder viajar desde aquí al siguiente
    const quita = () => { if (!tipFor) { try { if (tipEl.matches(':popover-open')) tipEl.hidePopover(); } catch {} } };
    if (window.Mov && !Mov.reduce()) setTimeout(quita, TIP_GRACE + 50); else quita();
  }
  function showTip(el) {
    const text = el.dataset.tip;
    if (!text || !el.isConnected) return;
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'tip';
      tipEl.setAttribute('aria-hidden', 'true');  // el nombre accesible ya es el aria-label del control
      if ('popover' in tipEl) tipEl.popover = 'manual';
      document.body.appendChild(tipEl);
    }
    // Si aún se ve (o acaba de irse), el globo viaja al control nuevo y el texto se enfoca al llegar
    const viaja = tipEl.classList.contains('is-on') || performance.now() - tipOffAt < TIP_GRACE;
    tipEl.classList.toggle('is-moving', viaja);
    tipFor = el;
    if (tipEl.textContent !== text) {
      tipEl.textContent = text;
      if (viaja && window.Mov && !Mov.reduce()) tipEl.animate([{ filter: 'blur(1.5px)', opacity: 0.55 }, { filter: 'none', opacity: 1 }], { duration: 220, easing: 'ease-out' });
    }
    try { if (tipEl.popover && !tipEl.matches(':popover-open')) tipEl.showPopover(); } catch {}
    const r = el.getBoundingClientRect();
    const tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
    let top = r.top - th - 6;
    if (top < 4) top = r.bottom + 6;
    const left = Math.max(4, Math.min(r.left + r.width / 2 - tw / 2, window.innerWidth - tw - 4));
    tipEl.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    tipEl.classList.add('is-on');
  }
  document.addEventListener('pointerover', (e) => {
    if (e.pointerType === 'touch') return;
    const el = e.target.closest?.('[data-tip], [title]');
    if (!el) return;
    adoptTitle(el);
    if (!el.dataset.tip || el === tipFor) return;
    clearTimeout(tipTimer);
    const enGracia = tipFor || performance.now() - tipOffAt < TIP_GRACE;
    tipTimer = setTimeout(() => showTip(el), enGracia ? 0 : 450);
  });
  document.addEventListener('pointerout', (e) => {
    const el = e.target.closest?.('[data-tip]');
    if (el && !el.contains(e.relatedTarget)) hideTip();
  });
  document.addEventListener('focusin', (e) => {
    const el = e.target.closest?.('[data-tip], [title]');
    if (!el) return;
    adoptTitle(el);
    if (el.dataset.tip && el.matches(':focus-visible')) showTip(el);
  });
  document.addEventListener('focusout', hideTip);
  document.addEventListener('pointerdown', hideTip, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideTip(); }, true);
  window.addEventListener('scroll', hideTip, true);

  /* ---------- visualViewport: alto real con teclado móvil ---------- */
  function syncViewport() {
    const vv = window.visualViewport;
    const h = vv ? vv.height : window.innerHeight;
    document.documentElement.style.setProperty('--vvh', h + 'px');
    // Lo que tapa el teclado por abajo (0 sin teclado): las hojas inferiores suben solo eso. En iOS el teclado no
    // encoge la ventana (innerHeight), solo la vista visual; calcularlo así no depende de 100dvh, que Safari actualiza
    // a otro ritmo que visualViewport (la hoja «Más» podía quedar fuera de la pantalla).
    let kb = vv ? Math.round(window.innerHeight - vv.height - vv.offsetTop) : 0;
    if (!Number.isFinite(kb) || kb < 0) kb = 0;
    document.documentElement.style.setProperty('--kb', kb + 'px');
    // Solo con un teclado de verdad (> 120 px) las hojas usan --kb/--vvh; sin él van ancladas con valores fijos
    // (en iOS 26 la barra flotante de Safari mueve esas medidas y dejaba la hoja «Más» fuera de la pantalla)
    const conTeclado = kb > 120 && !!document.activeElement?.matches?.('input, textarea, select, [contenteditable="true"]');
    document.documentElement.classList.toggle('kb-open', conTeclado);
    colocarHojas();
  }
  /* ---------- Hojas inferiores del móvil colocadas con medidas reales ----------
     En el Safari de iOS 26 «position: fixed; bottom: 0» no apunta al borde de abajo de lo que se ve (barra flotante:
     WebKit 297779) y la hoja «Más» quedaba casi entera bajo la pantalla, con dos arreglos solo de CSS. Aquí la hoja se
     coloca desde ARRIBA en px con la vista visual (las mismas coordenadas que getBoundingClientRect): alto máximo =
     lo que se ve menos el margen de arriba, y su borde de abajo pegado al de lo que se ve (o al teclado). Se rehace si
     la vista cambia (barra de Safari, teclado) o la hoja cambia de alto. El CSS (bottom: 0) queda de respaldo. */
  const HOJA_FUERA = '.modal-full, .pdf-visor, .cook';
  const movil = matchMedia('(max-width: 767px)');
  let seguroArriba = null;
  function margenSeguro() {
    if (seguroArriba == null) {
      const p = document.createElement('div');
      p.style.cssText = 'position:fixed;top:0;left:0;width:0;visibility:hidden;pointer-events:none;height:env(safe-area-inset-top,0px)';
      document.body.appendChild(p);
      seguroArriba = p.offsetHeight || 0;
      p.remove();
    }
    return seguroArriba;
  }
  function soltarHoja(dlg) {
    for (const k of ['top', 'bottom', 'maxHeight']) dlg.style[k] = '';
    delete dlg.dataset.hojaPx;
  }
  function colocarHoja(dlg) {
    if (!dlg.open || !movil.matches || dlg.matches(HOJA_FUERA)) { if (dlg.dataset.hojaPx) soltarHoja(dlg); return; }
    const vv = window.visualViewport;
    const arriba = vv ? vv.offsetTop : 0;
    const abajo = vv ? vv.offsetTop + vv.height : window.innerHeight;
    const margen = dlg.classList.contains('palette') ? 40 : margenSeguro() + 12;
    const maxH = Math.max(160, Math.round(abajo - arriba - margen));
    dlg.style.bottom = 'auto';
    dlg.style.maxHeight = maxH + 'px';
    dlg.style.top = Math.round(arriba + margen) + 'px';
    const h = dlg.offsetHeight;
    dlg.style.top = Math.round(Math.max(arriba + margen, abajo - h)) + 'px';
    dlg.dataset.hojaPx = '1';
  }
  const colocarHojas = () => document.querySelectorAll('dialog.modal[open]').forEach(colocarHoja);
  const hojaRO = typeof ResizeObserver === 'function' ? new ResizeObserver((es) => es.forEach((e) => colocarHoja(e.target))) : null;
  new MutationObserver((ms) => {
    for (const m of ms) {
      const dlg = m.target;
      if (!dlg.matches?.('dialog.modal')) continue;
      if (dlg.open) { colocarHoja(dlg); hojaRO?.observe(dlg); } else { hojaRO?.unobserve(dlg); soltarHoja(dlg); }
    }
  }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['open'] });
  movil.addEventListener?.('change', colocarHojas);

  /* Diagnóstico (?diag-hoja en la URL): abre la hoja «Más» y enseña encima las medidas de la ventana y de la hoja,
     para una captura desde el iPhone si vuelve a salir mal */
  function diagnosticoHoja() {
    const dlg = document.getElementById('moreSheet');
    if (!dlg) return;
    openModal(dlg);
    const box = document.createElement('pre');
    box.setAttribute('popover', 'manual');
    box.style.cssText = 'margin:0;inset:auto;top:calc(env(safe-area-inset-top) + 8px);left:8px;right:8px;position:fixed;z-index:2147483647;padding:8px 10px;border:0;border-radius:10px;background:#000c;color:#0f0;font:11px/1.35 ui-monospace,monospace;white-space:pre-wrap';
    document.body.appendChild(box);
    const pintar = () => {
      const vv = window.visualViewport, r = dlg.getBoundingClientRect(), cs = getComputedStyle(dlg);
      box.textContent = [
        navigator.userAgent.replace(/^.*?\(/, '(').slice(0, 90),
        `inner ${innerWidth}×${innerHeight} · html ${document.documentElement.clientHeight} · screen ${screen.height}`,
        `vv ${vv ? `${Math.round(vv.height)} top ${Math.round(vv.offsetTop)} pageTop ${Math.round(vv.pageTop)}` : '—'} · scrollY ${scrollY}`,
        `safeTop ${margenSeguro()} · --kb ${cs.getPropertyValue('--kb')} · kb-open ${document.documentElement.classList.contains('kb-open')}`,
        `hoja top ${Math.round(r.top)} bottom ${Math.round(r.bottom)} alto ${Math.round(r.height)} · scrollH ${dlg.scrollHeight}`,
        `css top ${cs.top} bottom ${cs.bottom} maxH ${cs.maxHeight} pos ${cs.position}`,
        `transform ${cs.transform} · anim ${dlg.getAnimations().map((a) => `${a.animationName || '?'}:${a.playState}`).join(',') || 'ninguna'}`,
      ].join('\n');
    };
    try { box.showPopover(); } catch { /* sin popover: queda bajo el fondo del diálogo */ }
    pintar();
    setInterval(pintar, 500);
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
      const n = c.inbox?.pendientes ?? c.pendientes;  // solo lo que está por procesar en el Inbox
      const txt = n > 99 ? '99+' : String(n);
      document.querySelectorAll('[data-inbox-count]').forEach((el) => {
        const antes = el.hidden ? null : (el.dataset.rollValue ?? el.textContent);
        const visto = !el.hidden;
        el.hidden = n === 0;
        // Las cifras ruedan (sube = desde abajo) y la insignia da un saltito (scale suelto: la de las pestañas ya usa
        // transform para colocarse); si aparece de cero, solo entra
        if (visto && antes && antes !== txt && window.Mov) {
          Mov.roll(el, txt);
          if (!Mov.reduce()) el.animate([{ scale: '0.8' }, { scale: '1' }], { duration: 460, easing: 'cubic-bezier(0.34, 1.7, 0.64, 1)' });
        } else { el.textContent = txt; el.dataset.rollValue = txt; }
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

  /* ---------- Acciones declarativas (data-call) ----------
     Sustituyen a los manejadores «on…» en el HTML (la CSP ya no permite JS en línea):
       <button data-call="setMode" data-args='["edit"]'>          → setMode('edit')
       <button data-call="openNoteMenu" data-args='["$el"]'>      → openNoteMenu(este botón)
       <button data-call="closeModal;Palette.open" data-args='[["moreSheet"], []]'>  → varias, en orden
     El nombre se busca en window (admite «Objeto.método»). */
  function runCall(el) {
    const names = el.dataset.call.split(';').map((s) => s.trim()).filter(Boolean);
    let args = [];
    try { args = el.dataset.args ? JSON.parse(el.dataset.args) : []; } catch { console.error('data-args no es JSON:', el); return; }
    names.forEach((name, i) => {
      const list = names.length > 1 ? (args[i] || []) : args;
      let ctx = window, fn = window;
      for (const part of name.split('.')) { ctx = fn; fn = fn?.[part]; }
      if (typeof fn !== 'function') { console.error(`Acción desconocida: ${name}`); return; }
      fn.apply(ctx, list.map((a) => (a === '$el' ? el : a)));
    });
  }
  document.addEventListener('click', (e) => {
    const el = e.target.closest?.('[data-call]');
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    runCall(el);
  });

  /* ---------- Arranque del shell ---------- */
  function init() {
    syncViewport();
    window.visualViewport?.addEventListener('resize', syncViewport);
    window.visualViewport?.addEventListener('scroll', syncViewport);  // iOS: la vista se desplaza al abrir el teclado
    window.addEventListener('resize', syncViewport);
    wireAllDialogs();
    document.addEventListener('click', (e) => {
      const cap = e.target.closest('[data-open-capture]');
      if (cap) { e.preventDefault(); openCapture(); }
      const more = e.target.closest('[data-open-more]');
      // el foco no va al campo de la tecla de captura: la primera pulsación la cambiaría
      if (more) { e.preventDefault(); openModal('moreSheet', { focus: '[data-open-status]' }); }
    });
    if (new URLSearchParams(location.search).has('diag-hoja')) setTimeout(diagnosticoHoja, 300);
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
    wireTabbarPicker();
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
  // origen = {x, y} del clic: el tema nuevo se extiende en círculo desde ahí (city-that-lights-up, reinterpretado)
  function setTheme(name, origen = null) {
    const root = document.documentElement;
    const apply = () => {
      // La paleta propia sin CSS todavía (primera vez o en un navegador nuevo): se hace ahora con la guardada
      if (name === 'propia' && window.TemaPropio && !document.getElementById('themePropia')?.textContent) TemaPropio.apply(TemaPropio.saved());
      root.setAttribute('data-theme', name);
      try { localStorage.setItem('theme', name); } catch {}
      syncTheme();
      document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: name } }));
    };
    // Fundido de colores (sin él, un salto brusco); nada si se pide reducir el movimiento
    if (!document.startViewTransition || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { apply(); return; }
    const clase = origen ? 'theme-sweep' : 'theme-switching';
    if (origen) {
      const r = Math.hypot(Math.max(origen.x, innerWidth - origen.x), Math.max(origen.y, innerHeight - origen.y));
      root.style.setProperty('--sweep-x', `${Math.round(origen.x)}px`);
      root.style.setProperty('--sweep-y', `${Math.round(origen.y)}px`);
      root.style.setProperty('--sweep-r', `${Math.ceil(r)}px`);
    }
    root.classList.add(clase);
    // Cambiar de tema muy seguido (flechas en el selector) salta la transición anterior: no es un error
    const vt = document.startViewTransition(apply);
    vt.ready.catch(() => {});
    vt.finished.catch(() => {}).finally(() => root.classList.remove(clase));
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
    grid.addEventListener('click', (e) => {
      const b = e.target.closest('[data-theme-choice]');
      if (!b) return;
      const r = b.getBoundingClientRect();
      setTheme(b.dataset.themeChoice, e.clientX || e.clientY ? { x: e.clientX, y: e.clientY } : { x: r.left + r.width / 2, y: r.top + r.height / 2 });
    });
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
    // S-2 · En el carrusel del móvil, el tema actual se centra al abrir la hoja (y al elegir otro)
    const centrar = (smooth) => {
      if (getComputedStyle(grid).display !== 'flex') return;
      const cur = grid.querySelector('[aria-checked="true"]');
      if (cur) grid.scrollTo({ left: cur.offsetLeft - (grid.clientWidth - cur.offsetWidth) / 2, behavior: smooth && !window.Mov?.reduce() ? 'smooth' : 'auto' });
    };
    const hoja = grid.closest('dialog');
    if (hoja) new MutationObserver(() => { if (hoja.open) requestAnimationFrame(() => centrar(false)); }).observe(hoja, { attributes: true, attributeFilter: ['open'] });
    document.addEventListener('themechange', () => requestAnimationFrame(() => centrar(true)));
  }

  /* ---------- Pestañas del móvil (Ajustes) ----------
     Hasta TABBAR_MAX secciones en la barra de abajo, en el orden del menú; se guardan en Prefs («tabbar») y
     tabbar-init.js las coloca. Sin ninguna marcada vuelven las de por defecto. */
  function wireTabbarPicker() {
    const boxes = [...document.querySelectorAll('[data-tabbar-choice]')];
    const max = window.TABBAR_MAX || 4;
    const current = () => {
      const pref = Prefs.get('tabbar', null);
      if (Array.isArray(pref) && pref.length) return pref;
      return [...document.querySelectorAll('.tabbar a.tab[data-default]')].map((t) => t.dataset.section);
    };
    const paint = () => {
      const keys = current();
      boxes.forEach((b) => { b.checked = keys.includes(b.value); });
      const full = boxes.filter((b) => b.checked).length >= max;
      boxes.forEach((b) => { b.disabled = full && !b.checked; });
      window.applyTabbar?.(Prefs.get('tabbar', null));
    };
    boxes.forEach((b) => b.addEventListener('change', () => {
      const keys = boxes.filter((x) => x.checked).map((x) => x.value).slice(0, max);
      Prefs.set('tabbar', keys);
      paint();
    }));
    paint();
    Prefs.ready.then(paint);
    document.addEventListener('prefs:changed', paint);
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
  const prefsCached = Object.keys(prefs).length > 0;
  const Prefs = { get: prefGet, set: prefSet, load: prefsLoad, cached: prefsCached, get ready() { return prefsReady; } };
  const prefsReady = prefsLoad();
  onDataChange(/^\/api\/prefs/, prefsLoad);

  // Colores de categoría (Notas, Grafo, Baúl): variables del tema activo (--cat-0…9 en themes.css). Una categoría
  // tiene el mismo color en todas partes: el índice sale de un hash de su nombre (categoryIndex).
  const CATEGORY_COLORS = Array.from({ length: 10 }, (_, i) => `var(--cat-${i})`);
  function categoryIndex(cat) {
    let hash = 0;
    for (let i = 0; i < cat.length; i++) hash = (hash * 31 + cat.charCodeAt(i)) | 0;
    return Math.abs(hash) % CATEGORY_COLORS.length;
  }
  const categoryColor = (cat) => CATEGORY_COLORS[categoryIndex(String(cat ?? ''))];

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
  /* ---------- Franja bajo la cabecera (P-1, P-2) ----------
     Un sitio común, en todas las páginas, para lo que tiene que verse siempre: el contador en marcha (timer.js) y el
     aviso de tareas atrasadas (atrasadas.js). topSlot('nombre', orden) da (o crea) su hueco; la franja se oculta sola
     cuando todos sus huecos están vacíos o con hidden. */
  function topSlot(name, order = 0) {
    let strip = document.getElementById('topStrip');
    if (!strip) {
      const main = document.getElementById('main');
      if (!main) return null;
      strip = document.createElement('div');
      strip.id = 'topStrip';
      strip.className = 'topstrip';
      strip.hidden = true;
      const header = main.querySelector(':scope > .page-header');
      if (header) header.after(strip); else main.prepend(strip);
      new MutationObserver(() => {
        const empty = ![...strip.children].some((c) => !c.hidden && c.childElementCount);
        if (strip.hidden !== empty) strip.hidden = empty;  // solo si cambia: si no, el observador se llamaría sin fin
      }).observe(strip, { subtree: true, childList: true, attributes: true, attributeFilter: ['hidden'] });
      // La franja cambia de alto con un muelle cuando aparece, se va o cambia lo que lleva (el contador que arranca, el
      // aviso que se abre): una sola forma que se adapta (dynamic-island) en vez de saltar
      let alto = 0;
      new ResizeObserver(() => {
        const h = strip.hidden ? 0 : strip.offsetHeight;
        if (h !== alto && window.Mov && !Mov.reduce() && !strip.dataset.anim && h > 0) {
          strip.dataset.anim = '1';
          const a = strip.animate([{ height: `${alto}px`, opacity: alto ? 1 : 0, overflow: 'clip' }, { height: `${h}px`, opacity: 1, overflow: 'clip' }],
            { duration: 420, easing: getComputedStyle(document.documentElement).getPropertyValue('--spring-suave').trim() || 'ease-out' });
          a.onfinish = a.oncancel = () => { delete strip.dataset.anim; };
        }
        alto = h;
      }).observe(strip);
    }
    let slot = strip.querySelector(`:scope > [data-slot="${name}"]`);
    if (!slot) {
      slot = document.createElement('div');
      slot.dataset.slot = name;
      slot.className = `topstrip-slot topstrip-${name}`;
      slot.style.order = String(order);
      strip.appendChild(slot);
    }
    return slot;
  }

  /* ---------- Sesiones (S-7): cerrar las de los demás dispositivos; esta sigue abierta con una cookie nueva ---------- */
  async function closeAllSessions() {
    const ok = await uiConfirm('¿Cerrar las demás sesiones?',
      'Todos los navegadores donde hayas entrado (el móvil, otro ordenador) tendrán que volver a poner la contraseña. ' +
      'Este sigue dentro. La extensión y los atajos del escritorio usan su propio token y no se ven afectados.',
      { confirmLabel: 'Cerrar las demás', danger: true });
    if (!ok) return;
    try {
      await api('/api/sesiones/cerrar-todas', { method: 'POST' });
      toast('Sesiones cerradas en los demás dispositivos');
    } catch { /* api() ya avisa del error */ }
  }

  const everyNote = (rule, text) => (rule?.freq === 'interval' ? `Ahora: ${escapeHtml(text.toLowerCase())}. Marca días si prefieres días fijos.` : '');

  Object.assign(window, {
  dayPicker, readDays, repeatFromDays, everyNote,
    CATEGORY_COLORS, categoryIndex, categoryColor,
    icon, escapeHtml, renderMarkdown, sanitizeHtml, timeAgo, api, parseTime, copyText, copied, toast, undoToast, openModal, closeModal, uiConfirm, uiAlert, uiPrompt,
    openMenu, closeMenu, closeAllSessions, topSlot, skeletonRows, emptyState, stateView, showState, loadFailed, setTheme, openCapture, refreshInboxBadge, wireAllDialogs, onDataChange, Prefs, uiPick, fuzzyScore,
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
