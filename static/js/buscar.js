/* ==========================================================================
   buscar.js — búsqueda de texto completo (FTS5) con filtros y búsquedas guardadas
   ========================================================================== */
(function () {
  'use strict';

  const STATUS_LABELS = { 'por-escribir': 'Por escribir', 'en-desarrollo': 'En desarrollo', consolidado: 'Consolidado', indice: 'Índice' };
  const $ = (id) => document.getElementById(id);
  let seq = 0;

  // El servidor marca las coincidencias con \u0002…\u0003: se escapa todo y luego se convierten en <mark>
  function highlight(text, [open, close]) {
    return escapeHtml(text || '').split(open).join('<mark>').split(close).join('</mark>');
  }
  // Fragmento legible: sin la sintaxis de Markdown (#, **, tablas, citas…)
  const plain = (text) => String(text || '').replace(/[#*_`>|~]+/g, ' ').replace(/\s+/g, ' ').trim();

  function params() {
    return { q: $('q').value.trim(), status: $('fStatus').value, category: $('fCategory').value.trim() };
  }

  function syncUrl(p) {
    const qs = new URLSearchParams(Object.entries(p).filter(([, v]) => v));
    history.replaceState(null, '', qs.toString() ? `?${qs}` : location.pathname);
  }

  async function run() {
    const p = params();
    syncUrl(p);
    $('btnSaveFilter').disabled = !p.q;
    const my = ++seq;
    if (!p.q) { idle(p); return; }
    const data = await api(`/api/search?${new URLSearchParams(p)}`, { quiet: true }).catch(() => null);
    if (my !== seq || !data) return; // llegó una respuesta más nueva
    const marks = data.marks || ['\u0002', '\u0003'];
    $('resultInfo').textContent = data.total ? `${data.total} ${data.total === 1 ? 'nota' : 'notas'}${data.total >= 30 ? ' (las 30 más relevantes)' : ''}` : '';
    if (!data.notes.length && !data.inbox.length) {
      $('results').innerHTML = emptyState({ iconName: 'search', title: 'Sin resultados', text: 'Prueba con menos palabras o con el principio de una palabra.', compact: true });
      return;
    }
    let html = '';
    if (data.notes.length) {
      html += `<ul class="list result-list">${data.notes.map((n) => `<li><a class="list-row" href="/?note=${encodeURIComponent(n.id)}">
        <span class="row-main">
          <span class="row-title">${n.encrypted ? icon('lock', 'icon-sm') + ' ' : ''}${highlight(n.title_hl || n.title, marks)}</span>
          ${n.snippet ? `<span class="snippet">${highlight(plain(n.snippet), marks)}</span>` : ''}
          <span class="meta"><span class="status"><span class="status-dot" data-status="${escapeHtml(n.status)}"></span>${STATUS_LABELS[n.status] || ''}</span>
            <span class="tiny subtle">${escapeHtml(n.category || '')}</span>${n.tags.slice(0, 4).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</span>
        </span>${icon('chevron-right', 'icon-sm subtle')}</a></li>`).join('')}</ul>`;
    }
    if (data.inbox.length) {
      html += `<h2 class="section-title" style="margin-top:var(--sp-4)">En el Inbox</h2><ul class="list result-list">${data.inbox.map((i) => `<li><a class="list-row" href="/inbox">
        <span class="tile" data-section="inbox">${icon(i.item_type === 'tarea' ? 'square-check' : 'lightbulb')}</span>
        <span class="row-main"><span class="row-title">${escapeHtml(i.content.replace(/^---\s*/, ''))}</span>
        <span class="row-sub">${i.status === 'processed' ? 'Hecho' : 'Pendiente'} · ${timeAgo(i.created_at)}</span></span></a></li>`).join('')}</ul>`;
    }
    $('results').innerHTML = html;
    remember(p.q);
  }

  /* ---------- Sin texto: búsquedas recientes, áreas y notas recientes; con filtros, las notas que cumplen ---------- */
  const RECENT_KEY = 'buscar-recientes';
  let notes = null, recientes = null, rememberTimer = null;
  const area = (n) => (n.category || '').split(/\s+-\s+|->/)[0].trim();
  function recent() { try { return JSON.parse(localStorage.getItem(RECENT_KEY)) || []; } catch { return []; } }
  function remember(q) {  // solo cuando se queda un rato (no cada letra)
    clearTimeout(rememberTimer);
    rememberTimer = setTimeout(() => {
      const list = [q, ...recent().filter((x) => x.toLowerCase() !== q.toLowerCase())].slice(0, 8);
      try { localStorage.setItem(RECENT_KEY, JSON.stringify(list)); } catch {}
    }, 1500);
  }
  const noteRow = (n) => `<li><a class="list-row" href="/?note=${encodeURIComponent(n.id)}">
      <span class="row-main"><span class="row-title">${n.encrypted ? icon('lock', 'icon-sm') + ' ' : ''}${escapeHtml(n.title || n.id)}</span>
        <span class="meta"><span class="status"><span class="status-dot" data-status="${escapeHtml(n.status)}"></span>${STATUS_LABELS[n.status] || ''}</span>
          <span class="tiny subtle">${escapeHtml(n.category || '')}</span></span></span>${icon('chevron-right', 'icon-sm subtle')}</a></li>`;
  async function idle(p) {
    const my = seq;
    if (!notes) notes = (await api('/api/notes', { quiet: true }).catch(() => ({ notes: [] }))).notes;
    if (my !== seq) return;
    if (p.status || p.category) {  // filtros sin texto: lista directa
      const fold = (t) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      const cat = fold(p.category);
      const list = notes.filter((n) => (!p.status || n.status === p.status) && (!cat || fold(n.category || '').includes(cat)))
        .sort((a, b) => (a.title || '').localeCompare(b.title || '', 'es'));
      $('resultInfo').textContent = `${list.length} ${list.length === 1 ? 'nota' : 'notas'}`;
      $('results').innerHTML = list.length ? `<ul class="list result-list">${list.map(noteRow).join('')}</ul>`
        : emptyState({ iconName: 'search', title: 'Ninguna nota con esos filtros', compact: true });
      return;
    }
    if (!recientes) recientes = (await api('/api/notes-home', { quiet: true }).catch(() => ({ recientes: [] }))).recientes;
    if (my !== seq) return;
    $('resultInfo').textContent = '';
    // «Física» y «Fisica» son la misma área: se agrupan sin tildes y se muestra la grafía más usada
    const fold = (t) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
    const groups = {};
    notes.forEach((n) => { const a = area(n); if (!a) return; const g = (groups[fold(a)] ||= { n: 0, names: {} }); g.n++; g.names[a] = (g.names[a] || 0) + 1; });
    const areas = Object.fromEntries(Object.values(groups).map((g) => [Object.entries(g.names).sort((x, y) => y[1] - x[1])[0][0], g.n]));
    const qs = recent();
    $('results').innerHTML = `
      ${qs.length ? `<section class="idle-block" aria-labelledby="idleRecent"><h2 class="idle-h" id="idleRecent">Búsquedas recientes
          <button type="button" class="btn btn-ghost btn-sm" data-clear-recent>Borrar</button></h2>
        <div class="chips">${qs.map((q) => `<button type="button" class="chip" data-q="${escapeHtml(q)}">${icon('history', 'icon-sm')}${escapeHtml(q)}</button>`).join('')}</div></section>` : ''}
      <section class="idle-block" aria-labelledby="idleAreas"><h2 class="idle-h" id="idleAreas">Explorar por área</h2>
        <div class="chips">${Object.entries(areas).sort((a, b) => b[1] - a[1]).map(([a, n]) => `<button type="button" class="chip" data-area="${escapeHtml(a)}">${escapeHtml(a)} <span class="chip-count tabular">${n}</span></button>`).join('')}</div></section>
      ${recientes.length ? `<section class="idle-block" aria-labelledby="idleNotes"><h2 class="idle-h" id="idleNotes">Trabajaste hace poco en</h2>
        <ul class="list result-list">${recientes.map((n) => noteRow({ ...n, tags: [] })).join('')}</ul></section>` : ''}`;
  }
  $('results').addEventListener('click', (e) => {
    const q = e.target.closest('[data-q]'), a = e.target.closest('[data-area]');
    if (e.target.closest('[data-clear-recent]')) { try { localStorage.removeItem(RECENT_KEY); } catch {} run(); return; }
    if (q) { $('q').value = q.dataset.q; run(); $('q').focus(); }
    if (a) { $('fCategory').value = a.dataset.area; run(); }
  });

  /* ---------- Búsquedas guardadas ---------- */
  async function loadSaved() {
    const { filters } = await api('/api/saved-filters?scope=buscar', { quiet: true }).catch(() => ({ filters: [] }));
    const box = $('savedFilters');
    box.hidden = !filters.length;
    box.innerHTML = filters.map((f) => `<span class="chip saved-chip" data-id="${f.id}">
      <button type="button" data-apply="${f.id}" class="chip-label">${icon('bookmark', 'icon-sm')} ${escapeHtml(f.name)}</button>
      <button type="button" class="x" data-del="${f.id}" aria-label="Quitar «${escapeHtml(f.name)}»">${icon('x')}</button></span>`).join('');
    box._filters = filters;
  }

  async function saveCurrent() {
    const p = params();
    const name = (await uiPrompt('Guardar búsqueda', { label: 'Nombre', value: p.q, confirmLabel: 'Guardar' }))?.trim();
    if (!name) return;
    await api('/api/saved-filters', { method: 'POST', body: { scope: 'buscar', name, params: p } });
    toast('Búsqueda guardada');
    loadSaved();
  }

  /* ---------- Eventos ---------- */
  let timer;
  const debounced = () => { clearTimeout(timer); timer = setTimeout(run, 160); };
  $('q').addEventListener('input', debounced);
  $('fStatus').addEventListener('change', run);
  $('fCategory').addEventListener('input', debounced);
  $('searchForm').addEventListener('submit', (e) => { e.preventDefault(); run(); });
  $('btnSaveFilter').addEventListener('click', saveCurrent);
  $('savedFilters').addEventListener('click', async (e) => {
    const box = $('savedFilters');
    const apply = e.target.closest('[data-apply]');
    if (apply) {
      const f = box._filters.find((x) => String(x.id) === apply.dataset.apply);
      $('q').value = f.params.q || '';
      $('fStatus').value = f.params.status || '';
      $('fCategory').value = f.params.category || '';
      run();
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      await api(`/api/saved-filters/${del.dataset.del}`, { method: 'DELETE' });
      loadSaved();
    }
  });

  const init = new URLSearchParams(location.search);
  $('q').value = init.get('q') || '';
  $('fStatus').value = init.get('status') || '';
  $('fCategory').value = init.get('category') || '';
  api('/api/notes', { quiet: true }).then(({ notes }) => {
    const areas = [...new Set(notes.map((n) => (n.category || '').split(/\s+-\s+|->/)[0].trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es'));
    $('dlAreas').innerHTML = areas.map((a) => `<option value="${escapeHtml(a)}">`).join('');
  }).catch(() => {});
  loadSaved();
  run();
})();
