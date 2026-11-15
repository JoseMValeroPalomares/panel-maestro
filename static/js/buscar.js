/* ==========================================================================
   buscar.js — búsqueda única (FTS5): notas, tareas, Baúl y eventos agrupados por tipo,
   con filtros, contexto activo y búsquedas guardadas
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
    return { q: $('q').value.trim(), tipo: kind, status: $('fStatus').value, category: $('fCategory').value.trim() };
  }

  function syncUrl(p) {
    const qs = new URLSearchParams(Object.entries(p).filter(([, v]) => v));
    history.replaceState(null, '', qs.toString() ? `?${qs}` : location.pathname);
  }

  /* ---------- Resultados agrupados por tipo (F-3) ---------- */
  let kind = '';          // '' = todo; nota | item | recurso | evento
  let allCtx = false;     // «Buscar en todo» sin cambiar el contexto del panel
  const GROUPS = {
    notes: { kind: 'nota', title: 'Notas', icon: 'notebook-pen', section: 'notas' },
    items: { kind: 'item', title: 'Tareas, ideas y rutinas', icon: 'square-check', section: 'tareas' },
    resources: { kind: 'recurso', title: 'Baúl', icon: 'library', section: 'baul' },
    events: { kind: 'evento', title: 'Eventos', icon: 'calendar', section: 'calendario' },
  };
  const ITEM_ICON = { tarea: 'square-check', idea: 'lightbulb', rutina: 'repeat' };
  const ITEM_LABEL = { tarea: 'Tarea', idea: 'Idea', rutina: 'Rutina' };
  const CTX_LABEL = { puntual: 'Puntual', universidad: 'Universidad', proyectos: 'Proyectos' };
  const hasMark = (t, marks) => (t || '').includes(marks[0]);
  const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; } };
  const day = (iso) => { const d = new Date(`${iso.slice(0, 10)}T00:00`); return isNaN(d) ? iso : d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' }); };
  function when(e) {
    const d = new Date(e.start.slice(0, 10) + 'T00:00');
    let s = d.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
    if (!e.all_day && e.start.length > 10) s += ` · ${e.start.slice(11, 16)}`;
    return s + (e.repeat ? ' · se repite' : '');
  }
  const row = (href, tile, title, snippet, meta) => `<li><a class="list-row" href="${escapeHtml(href)}">
      ${tile}<span class="row-main"><span class="row-title">${title}</span>
        ${snippet ? `<span class="snippet">${snippet}</span>` : ''}
        ${meta ? `<span class="meta">${meta}</span>` : ''}</span>${icon('chevron-right', 'icon-sm subtle')}</a></li>`;
  const tile = (section, name) => `<span class="tile" data-section="${section}" aria-hidden="true">${icon(name)}</span>`;
  const RENDER = {
    notes: (n, m) => row(n.href, '', `${n.encrypted ? icon('lock', 'icon-sm') + ' ' : ''}${highlight(n.title_hl || n.title, m)}`,
      n.snippet ? highlight(plain(n.snippet), m) : '',
      `<span class="status"><span class="status-dot" data-status="${escapeHtml(n.status)}"></span>${STATUS_LABELS[n.status] || ''}</span>
       <span class="tiny subtle">${escapeHtml(n.category || '')}</span>${n.tags.slice(0, 4).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('')}`),
    items: (i, m) => row(i.href, tile('tareas', ITEM_ICON[i.type] || 'square-check'), highlight(i.title_hl || i.text, m),
      hasMark(i.snippet, m) ? highlight(plain(i.snippet), m) : '',
      `<span class="tiny subtle">${ITEM_LABEL[i.type] || 'Tarea'} · ${i.done ? 'hecha' : 'pendiente'}${i.parent_id ? ' · paso' : ''}${i.origin === 'nota' ? ' · en una nota' : ''}${i.due_date ? ` · ${escapeHtml(day(i.due_date))}` : ''}</span>`),
    resources: (r, m) => row(r.href, tile('baul', r.resource_type === 'youtube' ? 'youtube' : 'globe'), highlight(r.title_hl || r.title || r.url, m),
      hasMark(r.snippet, m) ? highlight(plain(r.snippet), m) : '',
      `<span class="tiny subtle">${[r.channel, r.category, r.resource_type === 'youtube' ? '' : host(r.url), r.watched ? 'visto' : r.watch_later ? 'para más tarde' : ''].filter(Boolean).map(escapeHtml).join(' · ')}</span>`),
    events: (e, m) => row(e.href, tile('calendario', 'calendar'), highlight(e.title_hl || e.title, m),
      hasMark(e.snippet, m) ? highlight(plain(e.snippet), m) : '',
      `<span class="tiny subtle">${escapeHtml(when(e))}${e.location ? ` · ${escapeHtml(e.location)}` : ''}</span>`),
  };

  function paintKinds(data) {
    document.querySelectorAll('#kindChips [data-kind]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.kind === kind)));
    document.querySelectorAll('#kindChips [data-count]').forEach((c) => {
      const key = Object.keys(GROUPS).find((k) => GROUPS[k].kind === c.dataset.count);
      const n = !data ? null : key ? data[key].length : data.total;
      // con un tipo elegido, los demás no se han buscado: sin número
      c.textContent = n == null || (kind && c.dataset.count !== kind && c.dataset.count !== '') ? '' : ` ${n}`;
    });
    $('noteTools').hidden = Boolean(kind && kind !== 'nota');
  }

  async function run() {
    const p = params();
    syncUrl(p);
    $('btnSaveFilter').disabled = !p.q;
    const my = ++seq;
    if (!p.q) { paintKinds(null); $('ctxNote').hidden = true; idle(p); return; }
    const ctx = allCtx ? 'todo' : (window.Ctx?.active() || 'todo');
    const query = { q: p.q, contexto: ctx, ...(p.tipo && { tipo: p.tipo }), ...(p.status && { status: p.status }), ...(p.category && { category: p.category }) };
    const data = await api(`/api/search?${new URLSearchParams(query)}`, { quiet: true }).catch(() => null);
    if (my !== seq) return; // llegó una respuesta más nueva
    if (!data) {
      $('resultInfo').textContent = '';
      $('results').innerHTML = stateView({ kind: 'error', title: 'No se pudo buscar', text: 'Comprueba la conexión con el panel.', retry: true, compact: true });
      $('results').querySelector('[data-state-retry]')?.addEventListener('click', run);
      return;
    }
    const marks = data.marks || ['\u0002', '\u0003'];
    paintKinds(kind ? null : data);
    if (kind) { const c = document.querySelector(`#kindChips [data-count="${kind}"]`); if (c) c.textContent = ` ${data.total}`; }
    const parts = Object.entries(GROUPS).filter(([k]) => data[k].length).map(([k, g]) => `${data[k].length} en ${g.title.split(',')[0].toLowerCase()}`);
    $('resultInfo').textContent = data.total ? `${data.total} ${data.total === 1 ? 'resultado' : 'resultados'}${parts.length > 1 ? ` (${parts.join(', ')})` : ''}` : '';
    // Contexto activo distinto de «Todo»: se dice, y se puede ampliar sin cambiarlo en el resto del panel
    const note = $('ctxNote');
    if (ctx !== 'todo' && data.fuera) {
      note.hidden = false;
      note.innerHTML = `${icon('filter', 'icon-sm')}<span>Solo en <strong>${CTX_LABEL[ctx] || ctx}</strong>: hay ${data.fuera} ${data.fuera === 1 ? 'resultado' : 'resultados'} más en otros contextos.</span><button type="button" class="btn btn-ghost btn-sm" data-all-ctx>Buscar en todo</button>`;
    } else if (allCtx && window.Ctx && Ctx.active() !== 'todo') {
      note.hidden = false;
      note.innerHTML = `${icon('layers', 'icon-sm')}<span>Buscando en todos los contextos.</span><button type="button" class="btn btn-ghost btn-sm" data-ctx-only>Solo en ${CTX_LABEL[Ctx.active()] || Ctx.active()}</button>`;
    } else note.hidden = true;
    if (!data.total) {
      $('results').innerHTML = stateView({ kind: 'no-results', title: 'Sin resultados', text: 'Prueba con menos palabras o con el principio de una palabra.', compact: true });
      return;
    }
    const order = Object.keys(GROUPS).filter((k) => data[k]?.length);  // siempre el mismo orden: notas, tareas, Baúl, eventos
    $('results').innerHTML = order.map((k) => {
      const g = GROUPS[k];
      return `<section class="result-group" aria-labelledby="rg-${k}">
        <h2 class="section-title result-group-title" id="rg-${k}">${tile(g.section, g.icon)}${g.title} <span class="section-sub tabular">${data[k].length}</span></h2>
        <ul class="list result-list">${data[k].map((x) => RENDER[k](x, marks)).join('')}</ul></section>`;
    }).join('');
    remember(p.q);
  }
  $('kindChips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-kind]');
    if (!b || b.dataset.kind === kind) return;
    kind = b.dataset.kind;
    if (kind && kind !== 'nota') { $('fStatus').value = ''; $('fCategory').value = ''; }
    run();
  });
  $('ctxNote').addEventListener('click', (e) => {
    if (e.target.closest('[data-all-ctx]')) { allCtx = true; run(); }
    if (e.target.closest('[data-ctx-only]')) { allCtx = false; run(); }
  });
  document.addEventListener('contexto:changed', () => { allCtx = false; run(); });

  /* ---------- Sin texto: búsquedas recientes, áreas y notas recientes; con filtros, las notas que cumplen ---------- */
  const RECENT_KEY = 'buscar-recientes';
  let notes = null, recientes = null, rememberTimer = null;
  // Una sola petición de la lista de notas para la portada de Buscar y las sugerencias de área (V-2)
  let notesReq = null;
  const allNotes = () => (notesReq ||= api('/api/notes', { quiet: true }).then((r) => r.notes).catch(() => { notesReq = null; return []; }));
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
    if (!notes) notes = await allNotes();
    if (my !== seq) return;
    if (p.status || p.category) {  // filtros sin texto: lista directa
      const fold = (t) => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      const cat = fold(p.category);
      const list = notes.filter((n) => (!p.status || n.status === p.status) && (!cat || fold(n.category || '').includes(cat)))
        .sort((a, b) => (a.title || '').localeCompare(b.title || '', 'es'));
      $('resultInfo').textContent = `${list.length} ${list.length === 1 ? 'nota' : 'notas'}`;
      $('results').innerHTML = list.length ? `<ul class="list result-list">${list.map(noteRow).join('')}</ul>`
        : stateView({ kind: 'no-results', title: 'Ninguna nota con esos filtros', text: 'Quita el filtro de estado o de área.', compact: true });
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
      kind = f.params.tipo || '';
      run();
    }
    const del = e.target.closest('[data-del]');
    if (del) {
      const res = await api(`/api/saved-filters/${del.dataset.del}`, { method: 'DELETE' });
      loadSaved();
      undoToast('Filtro borrado', res, loadSaved);
    }
  });

  const init = new URLSearchParams(location.search);
  $('q').value = init.get('q') || '';
  $('fStatus').value = init.get('status') || '';
  $('fCategory').value = init.get('category') || '';
  kind = ['nota', 'item', 'recurso', 'evento'].includes(init.get('tipo')) ? init.get('tipo') : '';
  allNotes().then((notes) => {
    const areas = [...new Set(notes.map((n) => (n.category || '').split(/\s+-\s+|->/)[0].trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es'));
    $('dlAreas').innerHTML = areas.map((a) => `<option value="${escapeHtml(a)}">`).join('');
  }).catch(() => {});
  loadSaved();
  run();
})();
