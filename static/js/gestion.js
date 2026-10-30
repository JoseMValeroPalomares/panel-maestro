/* ==========================================================================
   gestion.js — tabla reutilizable de gestión masiva (notas, platos, ingredientes)
   Cada entidad describe cómo cargar, filtrar, pintar y qué API de lote usa.
   ========================================================================== */
(function () {
  'use strict';

  const STATUS_LABELS = { 'por-escribir': 'Por escribir', 'en-desarrollo': 'En desarrollo', 'consolidado': 'Consolidado' };
  const FRANJAS = { desayuno: 'Desayuno', comida: 'Comida', merienda: 'Merienda', cena: 'Cena' };
  const nf = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });
  const collator = new Intl.Collator('es', { sensitivity: 'base', numeric: true });

  const tagList = (tags) => tags.length ? `<span class="tags">${tags.map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('')}</span>` : '<span class="subtle">—</span>';
  const splitTags = (raw) => (Array.isArray(raw) ? raw : String(raw || '').split(',')).map((t) => t.trim()).filter(Boolean);
  const plural = (n, one, many) => `${nf.format(n)} ${n === 1 ? one : many}`;
  // «3 notas borradas» / «1 plato borrado»: participio que concuerda con la entidad
  const done = (n, c, verb) => `${plural(n, c.one, c.many)} ${verb}${c.fem ? 'a' : 'o'}${n === 1 ? '' : 's'}`;

  const ENTITIES = {
    notas: {
      one: 'nota', many: 'notas', fem: true, key: 'id', bulk: '/api/bulk/notes', undo: '/api/bulk/notes/undo', icon: 'notebook-pen',
      importHint: 'Columnas: title (obligatoria), id, category, status, tags (separadas por comas), content. Se identifican por id; si falta, se genera a partir del título.',
      async load() {
        const { notes } = await api('/api/notes');
        return notes.filter((n) => n.status !== 'indice').map((n) => ({
          ...n, tags: splitTags(n.tags), area: (n.category || 'General').split(/\s+-\s+|->|\//)[0].trim(),
        }));
      },
      search: (r) => `${r.title} ${r.category} ${r.tags.join(' ')}`,
      select: { label: 'Área', all: 'Todas las áreas', value: (r) => r.area },
      chips: [['all', 'Todas'], ...Object.entries(STATUS_LABELS)], chip: (r, v) => (r.status || 'por-escribir') === v,
      sort: 'title',
      columns: [
        { key: 'title', label: 'Título', main: true, sort: (r) => r.title,
          html: (r) => `<span class="cell-title">${r.encrypted ? icon('lock', 'icon-sm') : ''}<a href="/?note=${encodeURIComponent(r.id)}">${escapeHtml(r.title || r.id)}</a></span>`,
          sub: (r) => [STATUS_LABELS[r.status] || 'Por escribir', r.category, r.tags.join(', ')].filter(Boolean).join(' · ') },
        { key: 'category', label: 'Categoría', sort: (r) => r.category, html: (r) => escapeHtml(r.category || '—') },
        { key: 'status', label: 'Estado', sort: (r) => r.status,
          html: (r) => `<span class="status"><span class="status-dot" data-status="${escapeHtml(r.status || 'por-escribir')}"></span>${STATUS_LABELS[r.status] || 'Por escribir'}</span>` },
        { key: 'tags', label: 'Etiquetas', tags: true, html: (r) => tagList(r.tags) },
      ],
      editFields: (rows) => `
        ${field('Categoría', `<input class="input" name="category" list="dlCategory" placeholder="Sin cambios" maxlength="200" autocomplete="off">
          <datalist id="dlCategory">${unique(rows.map((r) => r.category)).map((c) => `<option value="${escapeHtml(c)}">`).join('')}</datalist>`)}
        ${field('Estado', `<select class="select" name="status"><option value="">Sin cambios</option>${Object.entries(STATUS_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>`)}
        ${tagFields()}`,
      editBody: (fd) => ({ category: fd.get('category').trim() || null, status: fd.get('status') || null, ...tagBody(fd) }),
    },

    platos: {
      one: 'plato', many: 'platos', key: 'id', bulk: '/comidas/api/bulk/meals', undo: '/comidas/api/bulk/undo', icon: 'utensils-crossed',
      importHint: 'Columnas: nombre (obligatoria), franja, tags, gramos_recomendados, es_racion_unica (0/1), instrucciones (separadas por |) e ingredientes como «Arroz: 80 g; Huevo: 2 ud». Los ingredientes tienen que existir ya.',
      async load() {
        const { meals } = await api('/comidas/api/meals');
        return meals.map((m) => ({ ...m, tags: splitTags(m.tags) }));
      },
      search: (r) => `${r.nombre} ${r.tags.join(' ')}`,
      select: null,
      chips: [['all', 'Todas'], ...Object.entries(FRANJAS)], chip: (r, v) => r.franja === v,
      sort: 'nombre',
      columns: [
        { key: 'nombre', label: 'Plato', main: true, sort: (r) => r.nombre,
          html: (r) => `<span class="cell-title">${escapeHtml(r.nombre)}</span>`,
          sub: (r) => [FRANJAS[r.franja] || r.franja, `${nf.format(r.kcal_total)} kcal`, plural(r.n_ingredientes, 'ingrediente', 'ingredientes')].join(' · ') },
        { key: 'franja', label: 'Franja', sort: (r) => r.franja, html: (r) => escapeHtml(FRANJAS[r.franja] || r.franja) },
        { key: 'kcal', label: 'kcal/ración', num: true, sort: (r) => r.kcal_total, html: (r) => nf.format(r.kcal_total) },
        { key: 'prot', label: 'Proteína', num: true, sec: true, sort: (r) => r.macros_racion?.proteinas ?? 0, html: (r) => `${nf.format(r.macros_racion?.proteinas ?? 0)} g` },
        { key: 'gramos', label: 'Ración', num: true, sec: true, sort: (r) => r.gramos_recomendados, html: (r) => `${nf.format(r.gramos_recomendados || 0)} g` },
        { key: 'n', label: 'Ingr.', num: true, sec: true, sort: (r) => r.n_ingredientes, html: (r) => nf.format(r.n_ingredientes) },
        { key: 'tags', label: 'Etiquetas', tags: true, html: (r) => tagList(r.tags) },
      ],
      editFields: () => `
        ${field('Franja', `<select class="select" name="franja"><option value="">Sin cambios</option>${Object.entries(FRANJAS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>`)}
        ${tagFields()}`,
      editBody: (fd) => ({ franja: fd.get('franja') || null, ...tagBody(fd) }),
    },

    ingredientes: {
      one: 'ingrediente', many: 'ingredientes', key: 'id', bulk: '/comidas/api/bulk/ingredients', undo: '/comidas/api/bulk/undo', icon: 'salad',
      importHint: 'Columnas: nombre (obligatoria), categoria, kcal_100g, proteinas_100g, carbohidratos_100g, grasas_100g, grasas_saturadas_100g, azucares_100g, sal_100g, gramos_por_unidad, unidad_nombre. Se identifican por nombre; al sobrescribir solo cambian las columnas que traiga el archivo.',
      async load() {
        const { ingredients } = await api('/comidas/api/ingredients');
        return ingredients;
      },
      search: (r) => `${r.nombre} ${r.categoria}`,
      select: { label: 'Categoría', all: 'Todas las categorías', value: (r) => r.categoria || 'General' },
      chips: [['all', 'Todos'], ['bad', 'kcal que no cuadran'], ['unit', 'Con unidades']],
      chip: (r, v) => (v === 'bad' ? !r.kcal_check?.ok : !!r.gramos_por_unidad),
      sort: 'nombre',
      columns: [
        { key: 'nombre', label: 'Ingrediente', main: true, sort: (r) => r.nombre,
          html: (r) => `<span class="cell-title">${escapeHtml(r.nombre)}${r.kcal_check?.ok === false ? `<span class="warn" title="Las kcal no cuadran con 4·P + 4·C + 9·G">${icon('triangle-alert', 'icon-sm')}<span class="sr-only">kcal incoherentes</span></span>` : ''}</span>`,
          sub: (r) => [r.categoria, `${nf.format(r.kcal_100g)} kcal`, `P ${nf.format(r.proteinas_100g)} · C ${nf.format(r.carbohidratos_100g)} · G ${nf.format(r.grasas_100g)}`].join(' · ') },
        { key: 'categoria', label: 'Categoría', sort: (r) => r.categoria, html: (r) => escapeHtml(r.categoria || '—') },
        { key: 'kcal', label: 'kcal', num: true, sort: (r) => r.kcal_100g, html: (r) => nf.format(r.kcal_100g) },
        { key: 'p', label: 'Prot.', num: true, sort: (r) => r.proteinas_100g, html: (r) => nf.format(r.proteinas_100g) },
        { key: 'c', label: 'Hidr.', num: true, sec: true, sort: (r) => r.carbohidratos_100g, html: (r) => nf.format(r.carbohidratos_100g) },
        { key: 'g', label: 'Grasa', num: true, sec: true, sort: (r) => r.grasas_100g, html: (r) => nf.format(r.grasas_100g) },
        { key: 'u', label: 'Unidad', sec: true, sort: (r) => r.gramos_por_unidad || 0,
          html: (r) => (r.gramos_por_unidad ? `${escapeHtml(r.unidad_nombre || 'ud')} = ${nf.format(r.gramos_por_unidad)} g` : '<span class="subtle">—</span>') },
      ],
      editFields: (rows) => `
        ${field('Categoría', `<input class="input" name="categoria" list="dlCat" placeholder="Sin cambios" maxlength="60" autocomplete="off">
          <datalist id="dlCat">${unique(rows.map((r) => r.categoria)).map((c) => `<option value="${escapeHtml(c)}">`).join('')}</datalist>`)}`,
      editBody: (fd) => ({ categoria: fd.get('categoria').trim() || null }),
    },
  };

  function field(label, control) {
    return `<label class="field"><span class="field-label">${label}</span>${control}</label>`;
  }
  function tagFields() {
    return field('Añadir etiquetas', '<input class="input" name="tags_add" placeholder="separadas por comas" autocomplete="off">') +
      field('Quitar etiquetas', '<input class="input" name="tags_remove" placeholder="separadas por comas" autocomplete="off">');
  }
  function tagBody(fd) {
    return { tags_add: splitTags(fd.get('tags_add')), tags_remove: splitTags(fd.get('tags_remove')) };
  }
  function colClass(col) {
    return [col.main && 'col-main', col.num && 'num', col.sec && 'col-sec', col.tags && 'col-tags'].filter(Boolean).join(' ');
  }
  function unique(values) {
    return [...new Set(values.filter(Boolean))].sort(collator.compare);
  }

  /* ---------- Estado ---------- */
  const state = { entity: 'notas', rows: [], view: [], selected: new Set(), anchor: null, sortKey: null, sortDir: 1, chip: 'all', select: '', q: '' };
  const $ = (id) => document.getElementById(id);
  const cfg = () => ENTITIES[state.entity];

  /* ---------- Carga y filtrado ---------- */
  async function load() {
    $('tableBody').innerHTML = `<tr><td colspan="9">${skeletonRows(6)}</td></tr>`;
    try {
      state.rows = await cfg().load();
    } catch {
      state.rows = [];
    }
    const valid = new Set(state.rows.map((r) => String(r[cfg().key])));
    state.selected = new Set([...state.selected].filter((id) => valid.has(id)));
    renderFilters();
    apply();
  }

  function renderFilters() {
    const c = cfg();
    const sel = $('filterSelect');
    if (c.select) {
      const opts = unique(state.rows.map(c.select.value));
      if (state.select && !opts.includes(state.select)) state.select = '';
      sel.innerHTML = `<option value="">${c.select.all}</option>` + opts.map((o) => `<option${o === state.select ? ' selected' : ''}>${escapeHtml(o)}</option>`).join('');
      sel.setAttribute('aria-label', c.select.label);
      sel.hidden = false;
    } else {
      sel.hidden = true;
    }
    $('filterChips').innerHTML = c.chips.map(([v, label]) => {
      const n = v === 'all' ? state.rows.length : state.rows.filter((r) => c.chip(r, v)).length;
      return `<button type="button" class="chip" data-chip="${v}" aria-pressed="${state.chip === v}">${escapeHtml(label)} <span class="chip-count">${n}</span></button>`;
    }).join('');
    $('filterSearch').placeholder = `Buscar ${c.many}…`;
  }

  function normalize(s) {
    return String(s ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  }

  function apply() {
    const c = cfg();
    const q = normalize(state.q);
    let view = state.rows.filter((r) =>
      (!q || normalize(c.search(r)).includes(q)) &&
      (state.chip === 'all' || c.chip(r, state.chip)) &&
      (!state.select || !c.select || c.select.value(r) === state.select));
    const col = c.columns.find((x) => x.key === (state.sortKey || c.sort));
    if (col?.sort) {
      view = view.slice().sort((a, b) => {
        const va = col.sort(a), vb = col.sort(b);
        const cmp = typeof va === 'number' && typeof vb === 'number' ? va - vb : collator.compare(String(va ?? ''), String(vb ?? ''));
        return cmp * state.sortDir;
      });
    }
    state.view = view;
    $('btnSaveFilter').disabled = !filtersActive();
    render();
  }

  /* ---------- Pintado ---------- */
  function render() {
    const base = cfg();
    // una columna de etiquetas que nadie usa solo quita sitio: se oculta hasta que haya alguna
    const c = { ...base, columns: base.columns.filter((col) => !col.tags || state.rows.some((r) => r.tags?.length)) };
    const sortKey = state.sortKey || c.sort;
    $('tableHead').innerHTML = `<th class="col-check" scope="col"><span class="check-hit"><input type="checkbox" class="checkbox" id="checkAll" aria-label="Seleccionar todo lo visible"></span></th>` +
      c.columns.map((col) => {
        const cls = colClass(col);
        if (!col.sort) return `<th scope="col" class="${cls}">${col.label}</th>`;
        const sort = col.key === sortKey ? (state.sortDir === 1 ? 'ascending' : 'descending') : 'none';
        return `<th scope="col" class="${cls}" aria-sort="${sort}"><button type="button" data-sort="${col.key}">${col.label}${icon('chevron-up', 'icon-sm')}</button></th>`;
      }).join('');

    const body = $('tableBody');
    const empty = $('tableEmpty');
    if (!state.view.length) {
      body.innerHTML = '';
      empty.hidden = false;
      empty.innerHTML = state.rows.length
        ? emptyState({ iconName: 'filter', title: 'Nada coincide con el filtro', text: 'Prueba con otra búsqueda o quita los filtros.', compact: true })
        : emptyState({ iconName: c.icon, title: `Aún no hay ${c.many}`, text: 'Puedes importarlos desde un CSV o JSON.', compact: true });
    } else {
      empty.hidden = true;
      body.innerHTML = state.view.map((r) => {
        const id = String(r[c.key]);
        const on = state.selected.has(id);
        return `<tr data-id="${escapeHtml(id)}" aria-selected="${on}">
          <td class="col-check"><span class="check-hit"><input type="checkbox" class="checkbox" data-row-check ${on ? 'checked' : ''} aria-label="Seleccionar ${escapeHtml(c.columns[0].sort(r))}"></span></td>
          ${c.columns.map((col) => `<td class="${colClass(col)}">${col.html(r)}${col.main && col.sub ? `<span class="m-sub">${escapeHtml(col.sub(r))}</span>` : ''}</td>`).join('')}
        </tr>`;
      }).join('');
    }
    const shown = state.view.length, total = state.rows.length;
    $('countLine').textContent = shown === total ? plural(total, c.one, c.many) : `${nf.format(shown)} de ${plural(total, c.one, c.many)}`;
    syncSelection();
  }

  function syncSelection() {
    const c = cfg();
    const n = state.selected.size;
    document.querySelectorAll('#tableBody tr[data-id]').forEach((tr) => {
      const on = state.selected.has(tr.dataset.id);
      tr.setAttribute('aria-selected', String(on));
      const cb = tr.querySelector('[data-row-check]');
      if (cb) cb.checked = on;
    });
    const all = $('checkAll');
    if (all) {
      const visibleSel = state.view.filter((r) => state.selected.has(String(r[c.key]))).length;
      all.checked = visibleSel > 0 && visibleSel === state.view.length;
      all.indeterminate = visibleSel > 0 && visibleSel < state.view.length;
      all.disabled = !state.view.length;
    }
    $('selectionBar').hidden = n === 0;
    document.body.classList.toggle('has-selection', n > 0);
    $('selCount').textContent = `${nf.format(n)} ${n === 1 ? 'seleccionado' : 'seleccionados'}`;
  }

  /* ---------- Selección (clic, Mayús + clic, todo) ---------- */
  function toggleRow(id, { range = false } = {}) {
    const ids = state.view.map((r) => String(r[cfg().key]));
    if (range && state.anchor && ids.includes(state.anchor)) {
      const [a, b] = [ids.indexOf(state.anchor), ids.indexOf(id)].sort((x, y) => x - y);
      const turnOn = state.selected.has(state.anchor);
      ids.slice(a, b + 1).forEach((x) => (turnOn ? state.selected.add(x) : state.selected.delete(x)));
    } else {
      state.selected.has(id) ? state.selected.delete(id) : state.selected.add(id);
      state.anchor = id;
    }
    syncSelection();
  }

  function selectedIds() {
    const key = cfg().key;
    return state.rows.filter((r) => state.selected.has(String(r[key]))).map((r) => r[key]);
  }

  function clearSelection() {
    state.selected.clear();
    state.anchor = null;
    syncSelection();
  }

  /* ---------- Acciones ---------- */
  function openEdit() {
    const c = cfg();
    const rows = state.rows;
    $('editTitle').textContent = `Editar ${plural(state.selected.size, c.one, c.many)}`;
    $('editSub').textContent = 'Se aplica a toda la selección.';
    $('editFields').innerHTML = c.editFields(rows);
    openModal('editModal');
  }

  async function submitEdit(e) {
    e.preventDefault();
    const c = cfg();
    const body = { ids: selectedIds(), ...c.editBody(new FormData($('editForm'))) };
    const changes = Object.entries(body).filter(([k, v]) => k !== 'ids' && (Array.isArray(v) ? v.length : v != null));
    if (!changes.length) { closeModal('editModal'); return; }
    const btn = $('editSubmit');
    btn.classList.add('is-loading');
    try {
      const res = await api(`${c.bulk}/update`, { method: 'POST', body });
      closeModal('editModal');
      toast(done(res.updated, c, 'actualizad'));
      await load();
    } finally {
      btn.classList.remove('is-loading');
    }
  }

  async function duplicate() {
    const c = cfg();
    const res = await api(`${c.bulk}/duplicate`, { method: 'POST', body: { ids: selectedIds() } });
    toast(plural(res.created.length, 'copia creada', 'copias creadas'));
    await load();
  }

  async function remove() {
    const c = cfg();
    const ids = selectedIds();
    const ok = await uiConfirm(`¿Borrar ${plural(ids.length, c.one, c.many)}?`,
      'Podrás deshacerlo durante unos días desde el aviso que aparece después.', { confirmLabel: 'Borrar', danger: true });
    if (!ok) return;
    const res = await api(`${c.bulk}/delete`, { method: 'POST', body: { ids } });
    clearSelection();
    await load();
    if (!res.deleted) return;
    toast(done(res.deleted, c, 'borrad'), {
      duration: 12000,
      action: { label: 'Deshacer', onClick: async () => {
        const r = await api(`${c.undo}/${res.undo_token}`, { method: 'POST' });
        toast(done(r.restored, c, 'restaurad'));
        await load();
      } },
    });
  }

  function exportMenu(anchor, onlySelected) {
    const c = cfg();
    const ids = onlySelected ? selectedIds().join(',') : '';
    const go = (format) => {
      const url = `${c.bulk}/export?format=${format}${ids ? `&ids=${encodeURIComponent(ids)}` : ''}`;
      const a = document.createElement('a');
      a.href = url;
      a.download = '';
      document.body.appendChild(a);
      a.click();
      a.remove();
    };
    const what = onlySelected ? 'la selección' : `tod${c.fem ? 'a' : 'o'}s l${c.fem ? 'a' : 'o'}s ${c.many}`;
    openMenu(anchor, [
      { label: `CSV · ${what}`, icon: 'table', onClick: () => go('csv') },
      { label: `JSON · ${what}`, icon: 'code', onClick: () => go('json') },
    ]);
  }

  /* ---------- Importación con vista previa ---------- */
  const imp = { mode: 'skip', previewed: false };

  function openImport() {
    const c = cfg();
    $('importTitle').textContent = `Importar ${c.many}`;
    $('importSub').textContent = 'Primero verás qué se va a crear, sobrescribir u omitir.';
    $('importHint').textContent = c.importHint;
    $('importFile').value = '';
    $('importPreview').hidden = true;
    $('importPreviewBtn').disabled = true;
    $('importRun').disabled = true;
    imp.previewed = false;
    openModal('importModal');
  }

  async function sendImport(dryRun) {
    const file = $('importFile').files[0];
    if (!file) return null;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('mode', imp.mode);
    fd.append('dry_run', dryRun ? 'true' : 'false');
    return api(`${cfg().bulk}/import`, { method: 'POST', body: fd });
  }

  function renderPreview(res, done) {
    const list = (items, cls = '') => items.slice(0, 50).map((x) => `<li class="${cls}">${escapeHtml(typeof x === 'string' ? x : `Fila ${x.fila}: ${x.error || x.aviso}`)}</li>`).join('') +
      (items.length > 50 ? `<li>… y ${items.length - 50} más</li>` : '');
    const el = $('importPreview');
    el.hidden = false;
    el.innerHTML = `
      <p class="counts"><span>${done ? 'Creados' : 'Nuevos'}: ${res.crear.length}</span><span>${done ? 'Sobrescritos' : 'Se sobrescriben'}: ${res.sobrescribir.length}</span>
        <span>Omitidos: ${res.omitir.length}</span><span class="${res.errores.length ? 'err' : ''}">Con errores: ${res.errores.length}</span></p>
      ${res.errores.length ? `<ul>${list(res.errores, 'err')}</ul>` : ''}
      ${res.avisos?.length ? `<p class="tiny muted">Avisos</p><ul>${list(res.avisos)}</ul>` : ''}
      ${!done && res.crear.length + res.sobrescribir.length === 0 ? '<p class="muted">No hay nada que importar con estas opciones.</p>' : ''}`;
  }

  async function previewImport() {
    const btn = $('importPreviewBtn');
    btn.classList.add('is-loading');
    try {
      const res = await sendImport(true);
      renderPreview(res, false);
      imp.previewed = true;
      $('importRun').disabled = res.crear.length + res.sobrescribir.length === 0;
    } finally {
      btn.classList.remove('is-loading');
    }
  }

  async function runImport() {
    const btn = $('importRun');
    btn.classList.add('is-loading');
    try {
      const res = await sendImport(false);
      closeModal('importModal');
      toast(`Importación hecha: ${res.crear.length} nuevos, ${res.sobrescribir.length} sobrescritos`);
      await load();
    } finally {
      btn.classList.remove('is-loading');
    }
  }

  /* ---------- Filtros guardados (por pestaña) ---------- */
  let saved = [];
  function filtersActive() {
    return !!(state.q || state.select || state.chip !== 'all' || state.sortKey);
  }
  async function loadSaved() {
    const scope = state.entity;
    const { filters } = await api(`/api/saved-filters?scope=${scope}`, { quiet: true }).catch(() => ({ filters: [] }));
    if (scope !== state.entity) return;
    saved = filters;
    $('savedChips').innerHTML = filters.map((f) => `<span class="chip saved-chip">
      <button type="button" data-apply="${f.id}">${icon('bookmark', 'icon-sm')} ${escapeHtml(f.name)}</button>
      <button type="button" class="x" data-del="${f.id}" aria-label="Quitar «${escapeHtml(f.name)}»">${icon('x')}</button></span>`).join('');
  }
  async function saveFilter() {
    const name = (await uiPrompt('Guardar filtro', { label: 'Nombre', value: state.q, confirmLabel: 'Guardar' }))?.trim();
    if (!name) return;
    const params = { q: state.q, select: state.select, chip: state.chip, sortKey: state.sortKey, sortDir: state.sortDir };
    await api('/api/saved-filters', { method: 'POST', body: { scope: state.entity, name, params } });
    toast('Filtro guardado');
    loadSaved();
  }
  function applySaved(f) {
    Object.assign(state, { q: f.params.q || '', select: f.params.select || '', chip: f.params.chip || 'all',
      sortKey: f.params.sortKey || null, sortDir: f.params.sortDir || 1 });
    $('filterSearch').value = state.q;
    renderFilters();
    apply();
  }

  /* ---------- Pestañas ---------- */
  function setEntity(name, { push = true } = {}) {
    if (!ENTITIES[name]) name = 'notas';
    state.entity = name;
    state.selected.clear();
    state.anchor = null;
    state.sortKey = null;
    state.sortDir = 1;
    state.chip = 'all';
    state.select = '';
    state.q = '';
    $('filterSearch').value = '';
    document.querySelectorAll('[role=tab][data-entity]').forEach((t) => {
      const on = t.dataset.entity === name;
      t.setAttribute('aria-selected', String(on));
      t.tabIndex = on ? 0 : -1;
    });
    $('gestionPanel').setAttribute('aria-labelledby', `tab-${name}`);
    if (push) history.replaceState(null, '', `#${name}`);
    load();
    loadSaved();
  }

  /* ---------- Eventos ---------- */
  function wire() {
    document.querySelectorAll('[role=tab][data-entity]').forEach((t) => {
      t.addEventListener('click', () => setEntity(t.dataset.entity));
      t.addEventListener('keydown', (e) => {
        if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
        const tabs = [...document.querySelectorAll('[role=tab][data-entity]')];
        const next = tabs[(tabs.indexOf(t) + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
        next.focus();
        setEntity(next.dataset.entity);
      });
    });
    let searchTimer;
    $('filterSearch').addEventListener('input', (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.q = e.target.value; apply(); }, 120);
    });
    $('filterSelect').addEventListener('change', (e) => { state.select = e.target.value; apply(); });
    $('filterChips').addEventListener('click', (e) => {
      const chip = e.target.closest('[data-chip]');
      if (!chip) return;
      state.chip = chip.dataset.chip;
      $('filterChips').querySelectorAll('[data-chip]').forEach((c) => c.setAttribute('aria-pressed', String(c === chip)));
      apply();
    });

    $('tableHead').addEventListener('click', (e) => {
      const sortBtn = e.target.closest('[data-sort]');
      if (sortBtn) {
        const key = sortBtn.dataset.sort;
        if ((state.sortKey || cfg().sort) === key) state.sortDir *= -1;
        else { state.sortKey = key; state.sortDir = 1; }
        apply();
      }
    });
    $('tableHead').addEventListener('change', (e) => {
      if (e.target.id !== 'checkAll') return;
      const key = cfg().key;
      state.view.forEach((r) => (e.target.checked ? state.selected.add(String(r[key])) : state.selected.delete(String(r[key]))));
      syncSelection();
    });

    const body = $('tableBody');
    // Mayús + clic: el navegador cambiaría la casilla antes de que la tratemos, así que se gestiona en click
    body.addEventListener('click', (e) => {
      const tr = e.target.closest('tr[data-id]');
      if (!tr || e.target.closest('a, button:not([data-row-check])')) return;
      if (e.target.matches('[data-row-check]')) {
        e.preventDefault();
        setTimeout(() => toggleRow(tr.dataset.id, { range: e.shiftKey }));
        return;
      }
      if (window.getSelection()?.toString()) return;
      toggleRow(tr.dataset.id, { range: e.shiftKey });
    });
    body.addEventListener('mousedown', (e) => { if (e.shiftKey) e.preventDefault(); }); // sin seleccionar texto

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && state.selected.size && !document.querySelector('dialog[open]') && !document.querySelector('.menu')) clearSelection();
    });

    $('selClear').addEventListener('click', clearSelection);
    $('selEdit').addEventListener('click', openEdit);
    $('selDuplicate').addEventListener('click', duplicate);
    $('selDelete').addEventListener('click', remove);
    $('selExport').addEventListener('click', (e) => exportMenu(e.currentTarget, true));
    $('btnExportAll').addEventListener('click', (e) => exportMenu(e.currentTarget, false));
    $('btnImport').addEventListener('click', openImport);
    $('btnSaveFilter').addEventListener('click', saveFilter);
    $('savedChips').addEventListener('click', async (e) => {
      const ap = e.target.closest('[data-apply]');
      if (ap) applySaved(saved.find((f) => String(f.id) === ap.dataset.apply));
      const del = e.target.closest('[data-del]');
      if (del) { await api(`/api/saved-filters/${del.dataset.del}`, { method: 'DELETE' }); loadSaved(); }
    });
    $('editForm').addEventListener('submit', submitEdit);

    $('importFile').addEventListener('change', () => {
      $('importPreviewBtn').disabled = !$('importFile').files.length;
      $('importRun').disabled = true;
      $('importPreview').hidden = true;
    });
    document.querySelectorAll('#importModal [data-mode]').forEach((b) => b.addEventListener('click', () => {
      imp.mode = b.dataset.mode;
      document.querySelectorAll('#importModal [data-mode]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      if (imp.previewed) previewImport();
    }));
    $('importPreviewBtn').addEventListener('click', previewImport);
    $('importRun').addEventListener('click', runImport);
    window.addEventListener('hashchange', () => setEntity(location.hash.slice(1), { push: false }));
  }

  wire();
  setEntity(location.hash.slice(1) || 'notas', { push: false });
})();
