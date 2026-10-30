/* ==========================================================================
   status.js — estado de las conexiones (window.Status)
   Punto en «Conexiones» (barra lateral y Ajustes): verde si todo va bien, ámbar o
   rojo si algo falla. El diálogo lista ESP32, calendario (iCloud y ESP32) y copias
   con la hora del último contacto y su botón (Reintentar, Sincronizar, Copia ahora).
   Se consulta /api/status al cargar y cada 2 minutos con la pestaña visible.
   ========================================================================== */
(function () {
  'use strict';
  const GOOD = new Set(['online', 'ok', 'idle', 'syncing', 'connecting', 'disabled']);
  let last = null;

  async function refresh() {
    try { last = await api('/api/status', { quiet: true }); } catch { return null; }
    const worst = last.items.some((i) => ['error', 'sin-copias'].includes(i.state)) ? 'error'
      : last.items.some((i) => !GOOD.has(i.state)) ? 'warn' : 'ok';
    document.querySelectorAll('[data-status-dot]').forEach((d) => {
      d.hidden = false;
      d.dataset.state = worst;
      d.title = worst === 'ok' ? 'Todo conectado' : `${last.problems} con problemas`;
    });
    if (dlg?.open) paint();
    return last;
  }

  const when = (ts) => (ts ? `${timeAgo(ts)} · ${new Date(ts * 1000).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}` : 'nunca');
  let dlg = null;
  function paint() {
    dlg.querySelector('.status-list').innerHTML = last.items.map((i) => `<li class="status-row" data-state="${i.state}">
        <span class="tile tile-sm" data-section="gestion" aria-hidden="true">${icon(i.icon, 'icon-sm')}</span>
        <span class="row-main"><span class="row-title">${escapeHtml(i.name)} <span class="status-pill" data-state="${GOOD.has(i.state) ? 'ok' : i.state === 'error' || i.state === 'sin-copias' ? 'error' : 'warn'}">${escapeHtml(i.label)}</span></span>
          <span class="row-sub">Último contacto: ${escapeHtml(when(i.last_ok))}${i.detail ? ` · ${escapeHtml(String(i.detail).slice(0, 140))}` : ''}</span></span>
        ${i.action ? `<button type="button" class="btn btn-sm" data-act-url="${escapeHtml(i.action.url)}" data-act-method="${i.action.method}">${escapeHtml(i.action.label)}</button>` : ''}</li>`).join('');
  }
  async function open() {
    closeModal('moreSheet');
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'modal';
      dlg.innerHTML = `<div class="modal-header"><h2>Conexiones</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
        <div class="modal-body"><ul class="list status-list" aria-live="polite"><li class="small muted">Comprobando…</li></ul></div>`;
      document.body.appendChild(dlg);
      wireAllDialogs();
      dlg.addEventListener('click', async (e) => {
        const b = e.target.closest('[data-act-url]');
        if (!b) return;
        b.classList.add('is-loading');
        try { await api(b.dataset.actUrl, { method: b.dataset.actMethod }); toast(`${b.textContent.trim()}: hecho`, { type: 'info' }); } catch {}
        b.classList.remove('is-loading');
        setTimeout(refresh, 2500);
      });
    }
    openModal(dlg);
    if (last) paint();
    refresh();
  }

  document.addEventListener('click', (e) => { if (e.target.closest('[data-open-status]')) { e.preventDefault(); open(); } });
  setTimeout(refresh, 1500);
  setInterval(() => { if (!document.hidden) refresh(); }, 120000);
  window.Status = { open, refresh, get last() { return last; } };
})();
