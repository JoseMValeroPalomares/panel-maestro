/* ==========================================================================
   backups.js — estado, listado, descarga, restauración y borrado de copias
   ========================================================================== */
(function () {
  'use strict';

  const KIND_LABELS = { diaria: 'Diaria', semanal: 'Semanal', manual: 'Manual', 'pre-restauracion': 'Antes de restaurar', 'cambio-sistema': 'Cambio de sistema', antigua: 'Formato antiguo' };
  const dateFmt = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' });
  const $ = (id) => document.getElementById(id);
  const state = { backups: [], kind: 'all', restoring: null };

  function bytes(n) {
    if (n == null) return '—';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${new Intl.NumberFormat('es-ES', { maximumFractionDigits: i ? 1 : 0 }).format(n)} ${units[i]}`;
  }
  const when = (ts) => (ts ? dateFmt.format(new Date(ts * 1000)) : '—');

  /* ---------- Estado ---------- */
  async function loadStatus() {
    const st = await api('/api/backups/status', { quiet: true });  // si falla, lo dice la tarjeta (firstLoad)
    const panel = $('statusPanel');
    panel.dataset.health = st.health;
    panel.setAttribute('aria-busy', 'false');
    const titles = {
      ok: 'Tus datos están protegidos',
      antigua: 'La última copia tiene más de un día',
      'sin-copias': 'Todavía no hay ninguna copia',
      error: 'La última copia automática falló',
    };
    $('healthIcon').innerHTML = icon(st.health === 'ok' ? 'shield-check' : 'triangle-alert');
    $('healthTitle').textContent = titles[st.health] || '';
    $('healthText').textContent = st.health === 'error'
      ? `${when(st.last_error.at)}: ${st.last_error.error}`
      : st.last ? `Última copia ${timeAgo(st.last.created_at)} (${KIND_LABELS[st.last.kind] || st.last.kind}).` : 'Haz la primera ahora; después se harán solas cada noche.';
    const facts = [
      ['Última copia', st.last ? when(st.last.created_at) : '—'],
      ['Próxima automática', st.next_run ? when(st.next_run) : 'Programador desactivado'],
      ['Copias guardadas', `${st.count} · ${bytes(st.total_bytes)}`],
      ['Libre en disco', bytes(st.disk_free_bytes)],
    ];
    $('statusFacts').innerHTML = facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${escapeHtml(v)}</dd></div>`).join('') + mirrorFact(st.mirror);
  }

  /* Espejo (PANEL_BACKUP_MIRROR): a todo el ancho, con la carpeta aparte en pequeño. Si falla es un aviso, no un error */
  function mirrorFact(m) {
    if (!m) return '';
    const text = m.state === 'ok' ? `${m.count} copias · la última ${m.last ? timeAgo(m.last.created_at) : '—'}${m.same_disk ? ' · en este mismo disco' : ''}`
      : m.state === 'pendiente' ? 'Listo: recibirá la próxima copia'
        : !m.available ? 'No disponible: ¿unidad sin montar?' : 'Falló la última copia al espejo';
    const why = m.state === 'error' && m.available && m.error ? `<span class="fact-note">${escapeHtml(m.error)}</span>` : '';
    return `<div class="fact-wide" data-state="${m.state}"><dt>Espejo</dt><dd>${escapeHtml(text)}${why}<span class="fact-note">${escapeHtml(m.dir)}</span></dd></div>`;
  }

  /* ---------- Listado ---------- */
  async function loadList() {
    const data = await api('/api/backups', { quiet: true });
    state.backups = data.backups;
    const r = data.retention;
    $('retentionNote').textContent = `Se conservan las ${r.diaria} últimas diarias, ${r.semanal} semanales, ${r.manual} manuales, ${r['pre-restauracion']} previas a restaurar y ${r['cambio-sistema']} de cambio de sistema. Las del formato antiguo no se borran solas.`;
    renderChips();
    renderList();
  }

  function renderChips() {
    const kinds = ['all', ...Object.keys(KIND_LABELS).filter((k) => state.backups.some((b) => b.kind === k))];
    if (!kinds.includes(state.kind)) state.kind = 'all';
    $('kindChips').innerHTML = kinds.map((k) => {
      const n = k === 'all' ? state.backups.length : state.backups.filter((b) => b.kind === k).length;
      return `<button type="button" class="chip" data-kind="${k}" aria-pressed="${state.kind === k}">${k === 'all' ? 'Todas' : KIND_LABELS[k]} <span class="chip-count">${n}</span></button>`;
    }).join('');
  }

  function renderList() {
    const list = $('backupList');
    const rows = state.backups.filter((b) => state.kind === 'all' || b.kind === state.kind);
    if (!rows.length) {
      list.innerHTML = `<li>${emptyState({ iconName: 'database-backup', title: 'No hay copias', text: 'Pulsa «Hacer copia ahora» para crear la primera.', compact: true })}</li>`;
      return;
    }
    list.innerHTML = rows.map((b) => `
      <li class="list-row" data-name="${escapeHtml(b.filename)}">
        <span class="tile" data-section="backups">${icon('archive-restore')}</span>
        <span class="row-main">
          <span class="row-title">${when(b.created_at)}</span>
          <span class="row-sub"><span class="kind" data-kind="${b.kind}">${KIND_LABELS[b.kind] || b.kind}</span> · ${bytes(b.size_bytes)} · ${timeAgo(b.created_at)}</span>
        </span>
        <span class="row-trail">
          <a class="btn btn-ghost btn-sm" href="/api/backups/${encodeURIComponent(b.filename)}/download" download>${icon('download', 'icon-sm')}<span class="hide-mobile">Descargar</span><span class="sr-only show-mobile">Descargar</span></a>
          <button type="button" class="btn btn-tinted btn-sm" data-restore>${icon('rotate-ccw', 'icon-sm')}Restaurar</button>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-more aria-label="Más acciones" aria-haspopup="menu">${icon('ellipsis')}</button>
        </span>
      </li>`).join('');
  }

  async function refresh() {
    await Promise.all([loadStatus(), loadList()]);
  }

  /* ---------- Acciones ---------- */
  async function backupNow(btn) {
    btn.classList.add('is-loading');
    btn.disabled = true;
    try {
      const res = await api('/api/backups/run', { method: 'POST' });
      toast(`Copia creada (${bytes(res.backup.size_bytes)})`);
      await refresh();
    } finally {
      btn.classList.remove('is-loading');
      btn.disabled = false;
    }
  }

  async function openRestore(name) {
    const b = state.backups.find((x) => x.filename === name);
    state.restoring = name;
    $('restoreSub').textContent = `${when(b.created_at)} · ${KIND_LABELS[b.kind] || b.kind}`;
    $('restoreForm').reset();
    $('restoreSubmit').disabled = true;
    openModal('restoreModal', { focus: '#restoreConfirm' });
    try {
      const { manifest } = await api(`/api/backups/${encodeURIComponent(name)}`, { quiet: true });
      const c = manifest.counts || {};
      const notas = document.querySelector('[data-count="notas"]');
      if (notas && c.notas != null) notas.textContent = ` · ${c.notas} notas en la copia (se quitan las creadas después)`;
      const versiones = document.querySelector('[data-count="versiones"]');
      if (versiones) versiones.textContent = c.versiones != null ? ` · ${c.versiones} versiones en la copia (solo añade las que falten)`
        : manifest.format < 2 ? ' · esta copia no las guarda' : ' · solo añade las que falten';
    } catch {}
  }

  function syncRestoreButton() {
    const parts = new FormData($('restoreForm')).getAll('parts');
    $('restoreSubmit').disabled = !(parts.length && $('restoreConfirm').value.trim().toUpperCase() === 'RESTAURAR');
  }

  async function submitRestore(e) {
    e.preventDefault();
    const fd = new FormData($('restoreForm'));
    const btn = $('restoreSubmit');
    btn.classList.add('is-loading');
    try {
      const res = await api(`/api/backups/${encodeURIComponent(state.restoring)}/restore`, {
        method: 'POST', body: { parts: fd.getAll('parts'), confirm: fd.get('confirm').trim().toUpperCase() },
      });
      closeModal('restoreModal');
      toast('Copia restaurada. El estado anterior quedó guardado como «Antes de restaurar».', { duration: 8000 });
      await refresh();
      return res;
    } finally {
      btn.classList.remove('is-loading');
    }
  }

  async function removeBackup(name) {
    const b = state.backups.find((x) => x.filename === name);
    const ok = await uiConfirm('¿Borrar esta copia?', `${when(b.created_at)} · ${bytes(b.size_bytes)}. No se puede deshacer.`, { confirmLabel: 'Borrar', danger: true });
    if (!ok) return;
    await api(`/api/backups/${encodeURIComponent(name)}`, { method: 'DELETE' });
    toast('Copia borrada');
    await refresh();
  }

  /* ---------- Eventos ---------- */
  $('btnBackupNow').addEventListener('click', (e) => backupNow(e.currentTarget));
  $('kindChips').addEventListener('click', (e) => {
    const chip = e.target.closest('[data-kind]');
    if (!chip) return;
    state.kind = chip.dataset.kind;
    renderChips();
    renderList();
  });
  $('backupList').addEventListener('click', (e) => {
    const row = e.target.closest('[data-name]');
    if (!row) return;
    const name = row.dataset.name;
    if (e.target.closest('[data-restore]')) openRestore(name);
    const more = e.target.closest('[data-more]');
    if (more) openMenu(more, [{ label: 'Borrar copia', icon: 'trash-2', danger: true, onClick: () => removeBackup(name) }]);
  });
  $('restoreForm').addEventListener('input', syncRestoreButton);
  $('restoreForm').addEventListener('change', syncRestoreButton);
  $('restoreForm').addEventListener('submit', submitRestore);

  // Si el panel no responde, se dice (nunca esqueletos eternos ni «no hay copias», que sería mentira)
  async function firstLoad() {
    $('backupList').innerHTML = `<li class="list-row">${skeletonRows(3)}</li>`;
    const [st, list] = await Promise.allSettled([loadStatus(), loadList()]);
    if (st.status === 'rejected') {
      const panel = $('statusPanel');
      panel.dataset.health = 'error';
      panel.setAttribute('aria-busy', 'false');
      $('healthIcon').innerHTML = icon('triangle-alert');
      $('healthTitle').textContent = 'No se pudo comprobar el estado de las copias';
      $('healthText').textContent = 'El panel no ha respondido. Tus datos y tus copias siguen donde estaban.';
    }
    if (list.status === 'rejected') {
      $('backupList').innerHTML = '<li></li>';
      showState($('backupList').firstElementChild, loadFailed('No se pudo cargar la lista de copias', true), firstLoad);
    }
  }
  firstLoad();
})();
