/* papelera.js — la papelera única (app/trash.py): restaurar, borrar del todo o vaciar */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  let entries = [], filter = '';

  async function load() {
    try { entries = (await api('/api/trash', { quiet: true })).entries; } catch {
      $('trashList').innerHTML = `<li>${emptyState({ iconName: 'wifi-off', title: 'No se pudo cargar la papelera', compact: true })}</li>`;
      return;
    }
    paint();
  }

  function left(e) {
    const days = Math.max(0, Math.ceil((e.expires_at * 1000 - Date.now()) / 86400000));
    return days <= 1 ? 'se vacía mañana' : `quedan ${days} días`;
  }

  function paint() {
    const labels = [...new Set(entries.map((e) => e.label))];
    $('trashFilter').innerHTML = labels.length > 1 ? [['', 'Todo'], ...labels.map((l) => [l, l[0].toUpperCase() + l.slice(1) + 's'])]
      .map(([k, l]) => `<button type="button" class="chip" data-f="${escapeHtml(k)}" aria-pressed="${filter === k}">${escapeHtml(l)}</button>`).join('') : '';
    const list = entries.filter((e) => !filter || e.label === filter);
    $('trashEmpty').hidden = !entries.length;  // oculto (no deshabilitado) cuando no hay nada
    $('trashList').innerHTML = list.length ? list.map((e) => `<li class="list-row trash-row">
        <span class="tile tile-sm" data-section="papelera" aria-hidden="true">${icon(e.icon, 'icon-sm')}</span>
        <span class="row-main"><span class="row-title">${escapeHtml(e.title || `${e.label[0].toUpperCase()}${e.label.slice(1)}${e.count > 1 ? 's' : ''} borrad${e.label === 'nota' ? 'a' : 'o'}${e.count > 1 ? 's' : ''}`)}</span>
          <span class="row-sub">${escapeHtml(e.label)}${e.count > 1 ? ` · ${e.count} elementos` : ''} · borrado ${timeAgo(e.created_at)} · ${left(e)}</span></span>
        <button type="button" class="btn btn-tinted btn-sm" data-restore="${e.db}/${e.token}">${icon('archive-restore', 'icon-sm')}<span class="hide-mobile">Restaurar</span><span class="sr-only show-mobile">Restaurar</span></button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-remove="${e.db}/${e.token}" aria-label="Borrar del todo «${escapeHtml(e.title || '')}»">${icon('x', 'icon-sm')}</button></li>`).join('')
      : `<li>${emptyState({ iconName: 'trash-2', title: 'La papelera está vacía', text: 'Lo que borres aparecerá aquí 30 días.', compact: true })}</li>`;
  }

  $('trashFilter').addEventListener('click', (e) => { const b = e.target.closest('[data-f]'); if (b) { filter = b.dataset.f; paint(); } });
  $('trashList').addEventListener('click', async (e) => {
    const r = e.target.closest('[data-restore]'), d = e.target.closest('[data-remove]');
    if (r) {
      r.classList.add('is-loading');
      try { const res = await api(`/api/trash/${r.dataset.restore}/restore`, { method: 'POST' }); toast(res.restored ? 'Restaurado' : 'Ya estaba (no se duplica)'); } catch {}
      load();
    }
    if (d) {
      const ok = await uiConfirm('¿Borrar del todo?', 'Ya no se podrá recuperar.', { confirmLabel: 'Borrar', danger: true });
      if (!ok) return;
      await api(`/api/trash/${d.dataset.remove}`, { method: 'DELETE' });
      load();
    }
  });
  $('trashEmpty').addEventListener('click', async () => {
    const ok = await uiConfirm('¿Vaciar la papelera?', `Se borrarán del todo ${entries.length} entradas. No se puede deshacer.`, { confirmLabel: 'Vaciar', danger: true });
    if (!ok) return;
    const r = await api('/api/trash', { method: 'DELETE' });
    toast(`${r.removed} entradas borradas`);
    load();
  });
  load();
})();
