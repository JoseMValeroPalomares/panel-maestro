/* ==========================================================================
   atrasadas.js — tareas atrasadas con acciones (window.Atrasadas, P-1)
     En todas las páginas: si hay tareas con fecha pasada sin hacer (y sin «hoy no»), un aviso discreto en la franja
     bajo la cabecera («3 tareas atrasadas · Revisar») que abre una hoja con una fila por tarea.
     Atrasadas.rows(lista)       HTML de las filas (la tarjeta de Hoy usa las mismas)
     Atrasadas.wire(contenedor)  botones y teclado de esas filas: flechas, C completar, P posponer, H hoy no, Supr borrar
     Atrasadas.open()            la hoja (también con ?atrasadas=1, que es lo que abre la notificación del escritorio)
   Datos: GET /api/items/atrasadas y POST /api/items/atrasadas/accion (app/atrasadas.py).
   ========================================================================== */
(function () {
  'use strict';
  const esc = (s) => escapeHtml(String(s ?? ''));
  const HIDE = 'atrasadas-oculto';  // aviso cerrado en esta pestaña (vuelve si cambia el número)
  let data = null, sheet = null;

  const fecha = (iso, opts = { weekday: 'short', day: 'numeric', month: 'short' }) => new Date(iso + 'T00:00').toLocaleDateString('es-ES', opts);
  const hace = (n) => (n === 1 ? 'ayer' : `hace ${n} días`);

  function rows(list) {
    return list.map((t) => `<li class="late-row${t.callada ? ' is-quiet' : ''}" data-late="${t.id}" tabindex="-1"
        aria-label="${esc(t.title)}, ${hace(t.dias)}${t.callada ? ', callada hasta mañana' : ''}">
      <div class="late-main">
        <a class="late-title" href="${esc(t.href)}">${esc(t.title)}</a>
        <span class="late-meta tiny">${t.parent ? `<span class="muted">${esc(t.parent)} ·</span> ` : ''}<span class="late-when tabular">${hace(t.dias)} · ${fecha(t.due_date, { day: 'numeric', month: 'short' })}${t.due_time ? ` ${t.due_time}` : ''}</span>${t.callada ? ' <span class="muted">· callada hasta mañana</span>' : ''}</span>
      </div>
      ${window.Ctx ? Ctx.chip(t, { link: false }) : ''}
      <div class="late-actions" role="group" aria-label="Acciones">
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-late-act="completar" aria-label="Completar «${esc(t.title)}»" data-tip="Completar (C)" aria-keyshortcuts="C">${icon('check', 'icon-sm')}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-late-act="posponer" aria-haspopup="menu" aria-expanded="false" aria-label="Posponer «${esc(t.title)}»" data-tip="Posponer (P)" aria-keyshortcuts="P">${icon('calendar-clock', 'icon-sm')}</button>
        ${t.callada ? '' : `<button type="button" class="btn btn-ghost btn-icon btn-sm" data-late-act="hoy_no" aria-label="Hoy no: callar «${esc(t.title)}» hasta mañana" data-tip="Hoy no (H)" aria-keyshortcuts="H">${icon('bell-off', 'icon-sm')}</button>`}
        <button type="button" class="btn btn-ghost btn-icon btn-sm late-del" data-late-act="borrar" aria-label="Borrar «${esc(t.title)}»" data-tip="Borrar (Supr)" aria-keyshortcuts="Delete">${icon('trash-2', 'icon-sm')}</button>
      </div></li>`).join('');
  }

  /* ---------- Acciones ---------- */
  const MSG = { completar: 'Hecha', hoy_no: 'Callada hasta mañana', borrar: 'Borrada' };
  async function act(id, action, value) {
    let res;
    try { res = await api('/api/items/atrasadas/accion', { method: 'POST', body: { ids: [id], action, value } }); } catch { return false; }
    if (action === 'borrar') undoToast(MSG.borrar, res, refresh);
    else if (action === 'posponer') toast(`Pospuesta al ${fecha(res.due_date, { weekday: 'long', day: 'numeric', month: 'long' })}`, { type: 'info', duration: 2200 });
    else toast(MSG[action], { type: 'info', duration: 1600 });
    await refresh();
    return true;
  }

  function postponeMenu(anchor, id) {
    const o = data?.opciones || {};
    return new Promise((resolve) => {
      let picked = false;
      const pick = (v) => { picked = true; resolve(v); };
      openMenu(anchor, [
        { label: `Mañana · ${fecha(o.manana)}`, icon: 'sunrise', onClick: () => pick('manana') },
        { label: `Sábado · ${fecha(o.sabado, { day: 'numeric', month: 'short' })}`, icon: 'calendar', onClick: () => pick('sabado') },
        { label: 'Elegir fecha…', icon: 'calendar-days', onClick: () => { picked = true; askDate(id).then(resolve); } },
      ]);
      // cerrar el menú sin elegir: nada
      const watch = setInterval(() => { if (!document.querySelector('.menu')) { clearInterval(watch); if (!picked) resolve(null); } }, 200);
    });
  }

  function askDate() {
    return new Promise((resolve) => {
      const dlg = document.createElement('dialog');
      dlg.className = 'modal modal-sm';
      dlg.setAttribute('aria-labelledby', 'lateDateT');
      const min = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
      dlg.innerHTML = `<form method="dialog" class="late-date-form">
        <div class="modal-header"><h2 id="lateDateT">Posponer a…</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
        <div class="modal-body"><label class="field"><span class="field-label">Fecha</span><input type="date" class="input" name="d" value="${data?.opciones?.manana || min}" required></label></div>
        <div class="modal-footer"><button type="button" class="btn" data-close>Cancelar</button><button type="submit" class="btn btn-primary">Posponer</button></div></form>`;
      document.body.appendChild(dlg);
      wireAllDialogs();
      let value = null;
      dlg.querySelector('form').addEventListener('submit', (e) => { e.preventDefault(); value = e.target.d.value || null; closeModal(dlg); });
      openModal(dlg, { focus: 'input', onClose: () => { dlg.remove(); resolve(value); } });
    });
  }

  /* ---------- Filas: botones y teclado ---------- */
  // La fila «actual» es la única parada de Tab de la lista, con su enlace y sus botones
  function current(row) {
    row.closest('.late-list')?.querySelectorAll('.late-row').forEach((r) => {
      const on = r === row;
      r.tabIndex = on ? 0 : -1;
      r.querySelectorAll('a, button').forEach((x) => { x.tabIndex = on ? 0 : -1; });
    });
  }
  function wire(box) {
    if (box.__lateWired) return;
    box.__lateWired = true;
    const list = () => [...box.querySelectorAll('.late-row')];
    const focusRow = (row) => {
      if (!row) return;
      current(row);
      row.focus();
    };
    // Entre filas, flechas; con Tab se entra en la fila actual y en sus botones (no en los de las demás)
    box.addEventListener('focusin', (e) => {
      const row = e.target.closest('.late-row');
      if (row) current(row);
    });
    async function run(row, action, anchor) {
      const id = Number(row.dataset.late);
      const rowsNow = list(), at = rowsNow.indexOf(row);
      let value;
      if (action === 'posponer') {
        value = await postponeMenu(anchor || row.querySelector('[data-late-act="posponer"]'), id);
        if (!value) { focusRow(row); return; }
      }
      row.classList.add('is-busy');
      const ok = await act(id, action, value);
      row.classList.remove('is-busy');
      if (!ok) { focusRow(row); return; }
      // el foco sigue en la fila que ocupa su sitio (o la anterior)
      requestAnimationFrame(() => {
        const after = list();
        focusRow(after.find((r) => r.dataset.late === String(id)) || after[Math.min(at, after.length - 1)]);
      });
    }
    box.addEventListener('click', (e) => {
      const b = e.target.closest('[data-late-act]');
      if (!b) return;
      e.preventDefault();
      run(b.closest('.late-row'), b.dataset.lateAct, b);
    });
    box.addEventListener('keydown', (e) => {
      const row = e.target.closest('.late-row');
      if (!row || e.ctrlKey || e.metaKey || e.altKey) return;
      const rs = list(), i = rs.indexOf(row);
      const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
      const map = { c: 'completar', p: 'posponer', h: 'hoy_no', Delete: 'borrar' };
      if (k === 'ArrowDown' || k === 'ArrowUp') { e.preventDefault(); focusRow(rs[(i + (k === 'ArrowDown' ? 1 : rs.length - 1)) % rs.length]); }
      else if (k === 'Home' || k === 'End') { e.preventDefault(); focusRow(k === 'Home' ? rs[0] : rs[rs.length - 1]); }
      else if (k === 'Enter' && e.target === row) { e.preventDefault(); row.querySelector('.late-title').click(); }
      else if (map[k] && (k !== 'h' || row.querySelector('[data-late-act="hoy_no"]'))) {
        e.preventDefault();
        e.stopPropagation();  // la C no abre la captura rápida
        run(row, map[k]);
      }
    });
  }

  /* ---------- Hoja ---------- */
  function paintSheet() {
    if (!sheet) return;
    const list = data?.atrasadas || [];
    const body = sheet.querySelector('[data-late-body]');
    const active = document.activeElement?.closest?.('.late-row')?.dataset.late;
    sheet.querySelector('[data-late-count]').textContent = list.length ? `${list.length} sin hacer${data.pendientes !== list.length ? ` · ${list.length - data.pendientes} calladas hoy` : ''}` : '';
    if (!list.length) {
      body.innerHTML = `<div class="late-empty">${icon('circle-check')}<p><b>Nada atrasado.</b> Todo lo que tenía fecha está hecho o pospuesto.</p></div>`;
      sheet.querySelector('[data-late-all]').hidden = true;
      return;
    }
    sheet.querySelector('[data-late-all]').hidden = !data.pendientes;
    body.innerHTML = `<ul class="late-list" aria-describedby="lateKeys">${rows(list)}</ul>`;
    const row = body.querySelector(`[data-late="${active}"]`) || body.querySelector('.late-row');
    if (row) current(row);
  }

  async function open() {
    if (!data) await load();
    if (sheet) { paintSheet(); openModal(sheet, { focus: '.late-row[tabindex="0"]' }); return; }
    sheet = document.createElement('dialog');
    sheet.className = 'modal late-sheet';
    sheet.setAttribute('aria-labelledby', 'lateTitle');
    sheet.innerHTML = `<div class="modal-header"><div><h2 id="lateTitle">Tareas atrasadas</h2><p class="modal-sub tabular" data-late-count></p></div>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body" data-late-body></div>
      <div class="modal-footer"><p class="tiny muted late-keys hide-mobile" id="lateKeys"><span><kbd>↑</kbd><kbd>↓</kbd> moverse</span> <span><kbd>C</kbd> completar</span> <span><kbd>P</kbd> posponer</span> <span><kbd>H</kbd> hoy no</span> <span><kbd>Supr</kbd> borrar</span></p>
        <span class="spacer"></span><button type="button" class="btn" data-late-all>${icon('bell-off', 'icon-sm')}Hoy no a todas</button></div>`;
    document.body.appendChild(sheet);
    wireAllDialogs();
    wire(sheet.querySelector('[data-late-body]'));
    sheet.querySelector('[data-late-all]').addEventListener('click', async () => {
      const ids = (data?.atrasadas || []).filter((t) => !t.callada).map((t) => t.id);
      if (!ids.length) return;
      try { await api('/api/items/atrasadas/accion', { method: 'POST', body: { ids, action: 'hoy_no' } }); } catch { return; }
      toast('Calladas hasta mañana', { type: 'info', duration: 1800 });
      await refresh();
      closeModal(sheet);
    });
    paintSheet();
    openModal(sheet, { focus: '.late-row[tabindex="0"]', onClose: () => {
      if (new URLSearchParams(location.search).has('atrasadas')) {
        const u = new URL(location.href); u.searchParams.delete('atrasadas'); history.replaceState(history.state, '', u);
      }
    } });
  }

  /* ---------- Aviso en la franja ---------- */
  function paintNotice() {
    const slot = window.topSlot?.('atrasadas', 2);
    if (!slot) return;
    const n = data?.pendientes || 0;
    let hidden = false;
    try { hidden = sessionStorage.getItem(HIDE) === String(n); } catch {}
    if (!n || hidden) { slot.innerHTML = ''; slot.hidden = true; return; }
    slot.hidden = false;
    slot.innerHTML = `<div class="late-notice" role="status">
      <button type="button" class="late-notice-open" data-late-open aria-haspopup="dialog">${icon('clock-alert', 'icon-sm')}<span><b class="tabular">${n}</b> ${n === 1 ? 'tarea atrasada' : 'tareas atrasadas'}</span><span class="late-notice-go">Revisar</span></button>
      <button type="button" class="btn btn-ghost btn-icon btn-sm late-notice-x" data-late-hide aria-label="Ocultar el aviso de atrasadas en esta pestaña" data-tip="Ocultar aquí">${icon('x', 'icon-sm')}</button></div>`;
  }

  async function load() {
    const ctx = window.Ctx ? Ctx.active() : 'todo';
    try { data = await api(`/api/items/atrasadas?contexto=${encodeURIComponent(ctx)}`, { quiet: true }); } catch { return null; }
    paintNotice();
    paintSheet();
    return data;
  }
  // Tras una acción: la lista, Hoy (que escucha «atrasadas:changed») y el almacén de tareas si la página lo usa
  async function refresh() {
    await load();
    document.dispatchEvent(new CustomEvent('atrasadas:changed', { detail: data }));
    if (window.Items?.state?.loaded) Items.load().catch(() => {});
  }

  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-late-open]')) { e.preventDefault(); open(); }
    if (e.target.closest('[data-late-hide]')) {
      try { sessionStorage.setItem(HIDE, String(data?.pendientes || 0)); } catch {}
      paintNotice();
      document.getElementById('main')?.focus({ preventScroll: true });
    }
  });
  document.addEventListener('contexto:changed', () => load());
  onDataChange(/^\/api\/(items|notes|routines|bulk\/notes)/, load);

  window.Atrasadas = { rows, wire, current, open, load, get data() { return data; } };
  // Al abrir el panel: después de pintar lo importante de la página
  const start = () => load().then(() => { if (new URLSearchParams(location.search).has('atrasadas')) open(); });
  (window.Prefs?.ready || Promise.resolve()).then(start, start);
})();
