/* =====================================================================
   Universidad (/universidad): una sección por asignatura, como las categorías del Baúl, con sus
   temas debajo (construidos desde su carpeta, en solo lectura), entregas y exámenes, horario de
   clases y sus tareas. Nada vive aparte: las tareas son las de Items (contexto «universidad»),
   las clases y exámenes son eventos del calendario y los apuntes, notas normales.
   API: /api/uni (app/universidad.py). Abrir y copiar ruta: Ctx.openFolder / Ctx.copyPath.
   ===================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  const ESTADOS = { 'sin-ver': { label: 'Sin ver', icon: 'circle-dashed' }, estudiando: { label: 'Estudiando', icon: 'circle-dot' }, repasado: { label: 'Repasado', icon: 'circle-check' } };
  const NEXT = { 'sin-ver': 'estudiando', estudiando: 'repasado', repasado: 'sin-ver' };
  const GRUPOS = { teoria: 'Teoría', practicas: 'Prácticas', otros: 'Otros' };
  const FOLD_KEY = 'uni-plegados';
  const TAB_KEY = 'uni-pestana';
  const DIAS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];

  let V = { asignaturas: [], temas: [], raiz: '', raiz_ok: false };
  let R = { clases_hoy: [], proximas: [], medias: {} };
  let tab = 'temas', asigFilter = Number(new URLSearchParams(location.search).get('asignatura')) || 0, estado = '', q = '';
  let itemView = null;

  const folded = () => new Set(Prefs.get(FOLD_KEY, []));
  const color = (a) => Ctx.color(a?.color);
  const asig = (id) => V.asignaturas.find((a) => a.id === id);
  const activas = () => V.asignaturas.filter((a) => !a.archivada);
  const norm = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const fmtDay = (iso) => new Date(iso + 'T00:00').toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' });
  // «GABD · Práctica 4» junto a la etiqueta GABD: sin la sigla repetida (el texto guardado no cambia)
  const sinSigla = (t, code) => (code ? String(t).replace(new RegExp(`^\\s*${code.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*(prácticas)?\\s*[·:\\-]\\s*`, 'i'), '') : t);
  const countdown = (d) => (d === 0 ? 'hoy' : d === 1 ? 'mañana' : d < 0 ? `hace ${-d} d` : `en ${d} días`);

  /* ---------- Carga ---------- */
  async function load() {
    try {
      [V, R] = await Promise.all([api('/api/uni', { quiet: true }), api('/api/uni/resumen', { quiet: true })]);
    } catch {
      showState($('uniContent'), loadFailed('No se pudo cargar Universidad', true), load);
      return;
    }
    if (asigFilter && !asig(asigFilter)) asigFilter = 0;
    renderSummary();
    renderChips();
    render();
  }
  onDataChange(/^\/api\/(uni|items|calendar|notes)/, () => { clearTimeout(load.t); load.t = setTimeout(load, 300); });

  /* ---------- Resumen de arriba ---------- */
  function renderSummary() {
    const hoy = R.clases_hoy || [];
    $('uniToday').innerHTML = hoy.length ? `<ul class="uni-mini-list">${hoy.map((c) => `<li>
        <span class="tabular uni-time">${c.start.slice(11, 16)}–${(c.end || '').slice(11, 16)}</span>
        <span class="ctx-dot" style="background:${c.color ? Ctx.color(c.color) : 'var(--tile-universidad)'}"></span><span class="grow ellipsis">${esc(c.asignatura_nombre || c.title)}</span>
        ${c.location ? `<span class="tiny muted">${icon('map-pin', 'icon-sm')}${esc(c.location)}</span>` : ''}</li>`).join('')}</ul>`
      : `<p class="small muted">Hoy no hay clases${V.asignaturas.length ? '' : ' (aún no hay asignaturas)'}. <button type="button" class="link-btn" data-goto-tab="horario">Ver el horario</button></p>`;
    const next = R.proximas || [];
    $('uniNext').innerHTML = next.length ? `<ul class="uni-mini-list">${next.slice(0, 5).map((e) => `<li class="${e.dias <= 2 ? 'is-soon' : ''}">
        <span class="ctx-dot" style="background:${Ctx.color(e.color)}"></span>
        <span class="grow ellipsis"><b>${esc(e.asignatura || '')}</b> ${esc(sinSigla(e.titulo, e.asignatura))}</span>
        <span class="tag${e.tipo === 'examen' ? ' uni-exam' : ''}">${e.tipo === 'examen' ? 'Examen' : 'Entrega'}</span>
        <span class="tiny tabular uni-count">${countdown(e.dias)}</span></li>`).join('')}</ul>`
      : '<p class="small muted">Nada pendiente con fecha. Marca una tarea como «Entrega» o crea un examen en el calendario.</p>';
    const badge = $('uniNextBadge');
    badge.textContent = next.length;
    badge.hidden = !next.length;
  }

  /* ---------- Chips de asignatura (como las categorías del Baúl) ---------- */
  function renderChips() {
    const list = activas();
    $('uniChips').innerHTML = `<button type="button" class="chip" data-asig="0" aria-pressed="${!asigFilter}">Todas</button>`
      + list.map((a) => `<button type="button" class="chip" data-asig="${a.id}" aria-pressed="${a.id === asigFilter}"><span class="dot" style="color:${color(a)}"></span>${esc(a.codigo)}</button>`).join('');
  }
  $('uniChips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-asig]');
    if (!b) return;
    asigFilter = Number(b.dataset.asig);
    const u = new URL(location.href);
    if (asigFilter) u.searchParams.set('asignatura', asigFilter); else u.searchParams.delete('asignatura');
    history.replaceState(null, '', u);
    renderChips();
    render();
  });
  $('uniEstado').addEventListener('click', (e) => {
    const b = e.target.closest('[data-estado]');
    if (!b) return;
    estado = b.dataset.estado;
    $('uniEstado').querySelectorAll('[data-estado]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    render();
  });
  for (const id of ['uniSearch', 'uniSearchMobile']) $(id).addEventListener('input', (e) => { q = e.target.value.trim(); render(); });

  /* ---------- Pestañas ---------- */
  function setTab(t) {
    tab = t;
    Prefs.set(TAB_KEY, t);
    const u = new URL(location.href);  // la pestaña también en la URL (enlazable)
    if (t === 'temas') u.searchParams.delete('pestana'); else u.searchParams.set('pestana', t);
    history.replaceState(null, '', u);
    document.querySelectorAll('.main-tab[data-tab]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.tab === t)));
    $('uniEstado').hidden = t !== 'temas';
    render();
  }
  document.querySelectorAll('.main-tab[data-tab]').forEach((b) => b.addEventListener('click', () => setTab(b.dataset.tab)));
  document.addEventListener('click', (e) => { const g = e.target.closest('[data-goto-tab]'); if (g) setTab(g.dataset.gotoTab); });

  function render() {
    const content = $('uniContent');
    $('uniTareas').hidden = tab !== 'tareas';
    content.hidden = tab === 'tareas';
    if (tab === 'tareas') return renderTareas();
    if (!V.asignaturas.length) {
      content.innerHTML = emptyState({ iconName: 'school', title: 'Tu universidad, por asignaturas',
        text: V.raiz ? 'Crea tus asignaturas a partir de las carpetas de la raíz: cada subcarpeta o PDF suelto será un tema. Nada se toca en el disco.'
          : 'Primero elige la carpeta raíz donde guardas todo de la universidad (Ajustes). Luego cada asignatura sale de una carpeta.',
        actionLabel: V.raiz ? 'Crear desde las carpetas' : 'Elegir la carpeta raíz', action: 'start' });
      content.querySelector('[data-empty-action=start]')?.addEventListener('click', () => (V.raiz ? openWizard() : openSettings()));
      return;
    }
    if (tab === 'temas') content.innerHTML = temasHTML();
    else if (tab === 'entregas') renderEntregas(content);
    else if (tab === 'horario') renderHorario(content);
    if (tab === 'temas') wireSortables();
  }

  /* ---------- Temas: una sección por asignatura ---------- */
  function visibleTemas(a) {
    return V.temas.filter((t) => t.asignatura_id === a.id && (!estado || t.estado === estado)
      && (!q || norm(`${t.titulo} ${t.nombre || ''}`).includes(norm(q))));
  }

  function temasHTML() {
    const closed = folded();
    const list = activas().filter((a) => !asigFilter || a.id === asigFilter);
    const html = list.map((a) => {
      const temas = visibleTemas(a);
      if ((q || estado) && !temas.length) return '';
      const key = `a:${a.id}`;
      const open = !closed.has(key);
      const prox = a.proxima;
      const groups = Object.keys(GRUPOS).map((g) => ({ g, items: temas.filter((t) => t.grupo === g) })).filter((x) => x.items.length);
      const total = V.temas.filter((t) => t.asignatura_id === a.id && !t.falta);
      const rep = total.filter((t) => t.estado === 'repasado').length;
      return `<section class="uni-subject" data-asig="${a.id}" style="--subj:${color(a)}" aria-labelledby="uni-h-${a.id}">
        <header class="uni-subject-head">
          <h2 class="cat-header" id="uni-h-${a.id}"><button type="button" class="group-toggle" data-fold="${key}" aria-expanded="${open}" aria-controls="uni-b-${a.id}">${icon('chevron-down', 'icon-sm chev')}<span class="dot" style="background:${color(a)}"></span><span class="uni-code">${esc(a.codigo)}</span><span class="uni-name">${esc(a.nombre)}</span><span class="count">${total.length}</span></button></h2>
          <div class="uni-meta small">
            ${a.profesor ? `<span>${icon('user', 'icon-sm')}${esc(a.profesor)}</span>` : ''}
            ${a.aula ? `<span>${icon('map-pin', 'icon-sm')}${esc(a.aula)}</span>` : ''}
            ${total.length ? `<span class="tabular" title="Temas repasados">${icon('circle-check', 'icon-sm')}${rep}/${total.length}</span>` : ''}
            ${a.tareas_abiertas ? `<button type="button" class="link-btn" data-subj-tareas="${a.id}">${icon('list-todo', 'icon-sm')}${a.tareas_abiertas} tareas</button>` : ''}
            ${a.media ? `<span class="tabular" title="Media ponderada de lo evaluado (${a.media.peso_evaluado} % de la nota)">${icon('star', 'icon-sm')}${String(a.media.media).replace('.', ',')}</span>` : ''}
            ${prox ? `<span class="uni-prox${prox.tipo === 'examen' ? ' is-exam' : ''}">${icon(prox.tipo === 'examen' ? 'triangle-alert' : 'flag', 'icon-sm')}${esc(sinSigla(prox.titulo, a.codigo))} · ${fmtDay(prox.fecha)}</span>` : ''}
            ${(a.enlaces || []).map((l) => `<a class="uni-link" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${icon('external-link', 'icon-sm')}${esc(l.titulo)}</a>`).join('')}
          </div>
          <div class="uni-actions">
            ${a.carpeta ? `<button type="button" class="btn btn-tinted btn-sm" data-open-asig="${a.id}" title="Abrir la carpeta en el portátil">${icon('folder-open', 'icon-sm')}<span class="hide-mobile">Abrir carpeta</span><span class="sr-only show-mobile">Abrir la carpeta de ${esc(a.codigo)}</span></button>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-copy-asig="${a.id}" aria-label="Copiar la ruta de ${esc(a.codigo)}" title="Copiar ruta">${icon('copy', 'icon-sm')}</button>` : ''}
            <button type="button" class="btn btn-ghost btn-icon btn-sm" data-class-note="${a.id}" aria-label="Nota de la clase de hoy de ${esc(a.codigo)}" title="Nota de clase (plantilla)">${icon('notebook-pen', 'icon-sm')}</button>
            <button type="button" class="btn btn-ghost btn-icon btn-sm" data-asig-menu="${a.id}" aria-label="Más acciones de ${esc(a.codigo)}" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
          </div>
        </header>
        <div class="uni-subject-body" id="uni-b-${a.id}" ${open ? '' : 'hidden'}>
          ${!a.carpeta && !total.length ? `<p class="small muted uni-hint">Sin carpeta. <button type="button" class="link-btn" data-asig-edit="${a.id}">Elige su carpeta</button> para traer sus temas, o añade temas a mano.</p>` : ''}
          ${groups.map(({ g, items }) => `<div class="uni-group"><h3 class="uni-group-title">${GRUPOS[g]} <span class="count">${items.length}</span></h3>
            <ul class="uni-grid" data-asig="${a.id}" data-grupo="${g}" aria-label="${esc(a.codigo)} · ${GRUPOS[g]}">${items.map(temaCard).join('')}</ul></div>`).join('')}
          <button type="button" class="btn btn-ghost btn-sm uni-add-tema" data-add-tema="${a.id}">${icon('plus', 'icon-sm')}Tema a mano</button>
        </div>
      </section>`;
    }).join('');
    return html || emptyState({ iconName: 'search', title: 'Sin resultados', text: 'Prueba con otra búsqueda o quita los filtros.' });
  }

  function temaCard(t) {
    const e = ESTADOS[t.estado] || ESTADOS['sin-ver'];
    return `<li class="uni-tema${t.falta ? ' is-missing' : ''}" data-id="${t.id}" data-estado="${t.estado}">
      <div class="uni-tema-top">
        <button type="button" class="drag-handle" data-drag-handle aria-label="Mover «${esc(t.titulo)}»">${icon('grip-vertical', 'icon-sm')}</button>
        <span class="uni-tema-kind" aria-hidden="true">${icon(t.tipo === 'carpeta' ? 'folder' : t.tipo === 'archivo' ? 'file-text' : 'pencil', 'icon-sm')}</span>
        <span class="uni-tema-title" title="${esc(t.nombre || t.titulo)}">${esc(t.titulo)}</span>
      </div>
      ${t.falta ? `<p class="tiny uni-missing">${icon('triangle-alert', 'icon-sm')}Ya no está en la carpeta</p>` : ''}
      <div class="uni-tema-meta">
        <button type="button" class="uni-estado no-drag" data-estado-btn="${t.id}" title="Cambiar estado (${e.label} → ${ESTADOS[NEXT[t.estado]].label})">${icon(e.icon, 'icon-sm')}${e.label}</button>
        ${t.note_id ? `<a class="card-link no-drag" href="/?note=${encodeURIComponent(t.note_id)}" title="Abrir los apuntes">${icon('notebook-pen', 'icon-sm')}Apuntes</a>`
          : `<button type="button" class="link-btn tiny no-drag" data-tema-nota="${t.id}">${icon('file-plus', 'icon-sm')}Apuntes</button>`}
        ${t.tareas ? `<span class="tiny muted tabular" title="Tareas abiertas de este tema">${icon('list-todo', 'icon-sm')}${t.tareas}</span>` : ''}
        <span class="grow"></span>
        ${t.ruta_abs ? `<button type="button" class="btn btn-ghost btn-icon btn-sm no-drag" data-open-tema="${t.id}" aria-label="Abrir «${esc(t.titulo)}»" title="Abrir ${t.tipo === 'carpeta' ? 'la carpeta' : 'el archivo'}">${icon('folder-open', 'icon-sm')}</button>` : ''}
        <button type="button" class="btn btn-ghost btn-icon btn-sm no-drag" data-copy-prompt="${t.id}" aria-label="Copiar el prompt para que una IA te explique «${esc(t.titulo)}»" title="Copiar prompt para la IA">${icon('clipboard-copy', 'icon-sm')}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm no-drag" data-tema-menu="${t.id}" aria-label="Más acciones de «${esc(t.titulo)}»" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
      </div></li>`;
  }

  // Ordenar temas a mano: dentro de su asignatura (las rutas son de su carpeta); entre grupos cambia el grupo
  function wireSortables() {
    $('uniContent').querySelectorAll('.uni-grid').forEach((list) => {
      Sortable.create(list, {
        group: 'uni-temas', items: '.uni-tema', handle: '[data-drag-handle]', label: list.getAttribute('aria-label'),
        id: (el) => Number(el.dataset.id), data: { asig: Number(list.dataset.asig), grupo: list.dataset.grupo },
        accepts: (ctx) => (ctx.to.data.asig === ctx.from.data.asig ? true : 'Un tema se queda en su asignatura'),
        onDrop: async (ctx) => {
          const body = { before_id: ctx.beforeId ? Number(ctx.beforeId) : 0 };
          if (ctx.to.data.grupo !== ctx.from.data.grupo) body.grupo = ctx.to.data.grupo;
          await api(`/api/uni/temas/${ctx.id}`, { method: 'PATCH', quiet: true, body });
          load();
        },
      });
    });
  }

  /* ---------- Clics de las secciones ---------- */
  $('uniContent').addEventListener('click', async (e) => {
    const t = e.target.closest('button, a');
    if (!t) return;
    const d = t.dataset;
    if (d.fold) {
      const set = folded(), open = t.getAttribute('aria-expanded') !== 'true';
      if (open) set.delete(d.fold); else set.add(d.fold);
      Prefs.set(FOLD_KEY, [...set]);
      t.setAttribute('aria-expanded', String(open));
      $(t.getAttribute('aria-controls')).hidden = !open;
      return;
    }
    if (d.openAsig) return Ctx.openFolder('asignatura', d.openAsig);
    if (d.copyAsig) return Ctx.copyPath(asig(Number(d.copyAsig))?.ruta_abs);
    if (d.openTema) return Ctx.openFolder('tema', d.openTema);
    if (d.copyPrompt) { const tm = V.temas.find((x) => x.id === Number(d.copyPrompt)); return copyPrompt(asig(tm.asignatura_id), tm); }
    if (d.asigEdit) return openAsigDialog(asig(Number(d.asigEdit)));
    if (d.subjTareas) { asigFilter = Number(d.subjTareas); renderChips(); return setTab('tareas'); }
    if (d.classNote) return classNote(Number(d.classNote));
    if (d.addTema) return addTema(Number(d.addTema));
    if (d.temaNota) return temaNota(Number(d.temaNota), t);
    if (d.estadoBtn) {
      const tema = V.temas.find((x) => x.id === Number(d.estadoBtn));
      tema.estado = NEXT[tema.estado];
      render();
      await api(`/api/uni/temas/${tema.id}`, { method: 'PATCH', quiet: true, body: { estado: tema.estado } });
      return;
    }
    if (d.asigMenu) return asigMenu(t, asig(Number(d.asigMenu)));
    if (d.temaMenu) return temaMenu(t, V.temas.find((x) => x.id === Number(d.temaMenu)));
  });

  function asigMenu(btn, a) {
    openMenu(btn, [
      { label: 'Editar', icon: 'pencil', onClick: () => openAsigDialog(a) },
      a.carpeta && { label: 'Sincronizar con carpeta', icon: 'folder-sync', onClick: () => syncOne(a) },
      { label: 'Copiar prompt para la IA', icon: 'clipboard-copy', onClick: () => copyPrompt(a, null) },
      { label: 'Tareas de la asignatura', icon: 'list-todo', onClick: () => { asigFilter = a.id; renderChips(); setTab('tareas'); } },
      { label: 'Ver sus notas', icon: 'notebook-pen', onClick: () => { location.href = `/buscar?q=${encodeURIComponent(a.codigo)}`; } },
      a.carpeta && { label: 'Copiar ruta', icon: 'copy', onClick: () => Ctx.copyPath(a.ruta_abs) },
      { label: 'Archivar (fin de cuatrimestre)', icon: 'archive', onClick: async () => {
        await api(`/api/uni/asignaturas/${a.id}`, { method: 'PATCH', body: { archivada: true } });
        toast(`${a.codigo} archivada: sus tareas y notas siguen ahí`, { action: { label: 'Deshacer', onClick: () => api(`/api/uni/asignaturas/${a.id}`, { method: 'PATCH', body: { archivada: false } }).then(load) } });
        load();
      } },
    ].filter(Boolean));
  }

  function temaMenu(btn, t) {
    openMenu(btn, [
      t.ruta_abs && { label: t.tipo === 'carpeta' ? 'Abrir la carpeta' : 'Abrir el archivo', icon: 'folder-open', onClick: () => Ctx.openFolder('tema', t.id) },
      t.ruta_abs && { label: 'Copiar ruta', icon: 'copy', onClick: () => Ctx.copyPath(t.ruta_abs) },
      t.tipo === 'carpeta' && { label: 'Ver sus archivos', icon: 'folder-tree', onClick: () => showRecursos(t) },
      { label: t.note_id ? 'Abrir los apuntes' : 'Crear los apuntes', icon: 'notebook-pen', onClick: () => temaNota(t.id) },
      { label: 'Copiar prompt para la IA', icon: 'clipboard-copy', onClick: () => copyPrompt(asig(t.asignatura_id), t) },
      { label: 'Nueva tarea de este tema', icon: 'square-check', onClick: () => newTask({ asignatura_id: t.asignatura_id, temas: [t.id] }, `Repasar ${t.titulo}`) },
      { label: 'Cambiar el nombre', icon: 'pencil', onClick: async () => {
        const v = await uiPrompt('Nombre del tema', { value: t.titulo, confirmLabel: 'Guardar', message: t.nombre ? `En la carpeta: ${t.nombre}` : '' });
        if (v?.trim()) { await api(`/api/uni/temas/${t.id}`, { method: 'PATCH', body: { titulo: v.trim() } }); load(); }
      } },
      ...Object.entries(GRUPOS).filter(([g]) => g !== t.grupo).map(([g, l]) => ({ label: `Pasar a ${l}`, icon: 'move', onClick: () => api(`/api/uni/temas/${t.id}`, { method: 'PATCH', body: { grupo: g } }).then(load) })),
      (t.falta || t.tipo === 'manual') && { label: 'Quitar de la lista', icon: 'trash-2', danger: true, onClick: async () => {
        if (t.tipo === 'manual' && !(await uiConfirm(`¿Quitar «${t.titulo}»?`, 'Lo añadiste a mano: no volverá al sincronizar. Sus apuntes, si tiene, no se borran.', { confirmLabel: 'Quitar', danger: true }))) return;
        const res = await api(`/api/uni/temas/${t.id}`, { method: 'DELETE' });
        undoToast('Tema quitado (ningún archivo se ha tocado)', res, load);
        load();
      } },
    ].filter(Boolean));
  }

  // El prompt de siempre para que una IA explique un tema (editable en Ajustes); se copia en el mismo clic
  function copyPrompt(a, t) {
    const text = (V.prompt || '').replaceAll('{asignatura}', a ? a.nombre : '').replaceAll('{tema}', t ? t.titulo : 'el tema que te paso');
    copyText(text).then((ok) => toast(ok ? 'Prompt copiado: pégalo en la IA junto a las diapositivas' : 'No se pudo copiar', { type: ok ? 'success' : 'error' }));
  }

  async function temaNota(id, btn) {
    btn?.classList.add('is-loading');
    try {
      const r = await api(`/api/uni/temas/${id}/nota`, { method: 'POST' });
      location.href = `/?note=${encodeURIComponent(r.note_id)}`;
    } finally { btn?.classList.remove('is-loading'); }
  }

  async function classNote(asigId) {
    const temas = V.temas.filter((t) => t.asignatura_id === asigId && !t.falta);
    const res = await formDialog('Nota de clase', `
      <label class="field"><span class="field-label">Fecha</span><input name="fecha" type="date" class="input" value="${new Date().toISOString().slice(0, 10)}"></label>
      <label class="field"><span class="field-label">Tema (opcional)</span><select name="tema" class="select"><option value="">—</option>${temas.map((t) => `<option value="${t.id}">${esc(t.titulo)}</option>`).join('')}</select></label>
      <p class="tiny muted">Plantilla con fecha, tema, apuntes, dudas ({{duda}}), lo importante y lo pendiente.</p>`, 'Crear nota');
    if (!res) return;
    const r = await api(`/api/uni/asignaturas/${asigId}/nota-clase`, { method: 'POST', body: { fecha: res.fecha, tema_id: Number(res.tema) || null } });
    location.href = `/?note=${encodeURIComponent(r.note_id)}`;
  }

  async function addTema(asigId) {
    const res = await formDialog('Tema a mano', `
      <label class="field"><span class="field-label">Título</span><input name="titulo" class="input" maxlength="200" required placeholder="Repaso del parcial…"></label>
      <label class="field"><span class="field-label">Grupo</span><select name="grupo" class="select">${Object.entries(GRUPOS).map(([g, l]) => `<option value="${g}">${l}</option>`).join('')}</select></label>`, 'Añadir');
    if (!res?.titulo?.trim()) return;
    await api(`/api/uni/asignaturas/${asigId}/temas`, { method: 'POST', body: { titulo: res.titulo.trim(), grupo: res.grupo } });
    load();
  }

  async function showRecursos(t) {
    const r = await api(`/api/uni/temas/${t.id}/recursos`);
    const fmt = (b) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);
    formDialog(t.titulo, r.recursos.length ? `<ul class="list uni-res">${r.recursos.map((x) => `<li class="list-row">${icon(x.carpeta ? 'folder' : 'file-text', 'icon-sm')}<span class="grow ellipsis">${esc(x.nombre)}</span>${x.carpeta ? '' : `<span class="tiny muted tabular">${fmt(x.bytes)}</span>`}</li>`).join('')}</ul>
      <p class="tiny muted">Solo lectura: el panel no cambia nada en tus carpetas. Abre la carpeta para trabajar con ellos.</p>` : '<p class="small muted">Carpeta vacía.</p>', 'Abrir la carpeta').then((ok) => { if (ok) Ctx.openFolder('tema', t.id); });
  }

  async function syncOne(a) {
    try {
      const r = await api(`/api/uni/asignaturas/${a.id}/sync`, { method: 'POST' });
      toast(`${a.codigo}: ${r.nuevos} nuevos${r.faltan ? `, ${r.faltan} ya no están (marcados)` : ''}${r.vuelven ? `, ${r.vuelven} vuelven` : ''}`);
      load();
    } catch { /* api ya avisa */ }
  }

  $('uniSyncAll').addEventListener('click', async (e) => {
    const b = e.currentTarget;
    b.classList.add('is-loading');
    try {
      const r = await api('/api/uni/sync', { method: 'POST' });
      const res = Object.entries(r.resultado);
      const nuevos = res.reduce((n, [, x]) => n + (x.nuevos || 0), 0);
      const errores = res.filter(([, x]) => x.error);
      toast(res.length ? `${nuevos} temas nuevos${errores.length ? ` · ${errores.map(([k, x]) => `${k}: ${x.error}`).join(' · ')}` : ''}` : 'Ninguna asignatura tiene carpeta', { type: errores.length ? 'info' : 'success' });
      load();
    } catch { /* api ya avisa */ } finally { b.classList.remove('is-loading'); }
  });

  /* ---------- Entregas y exámenes ---------- */
  async function renderEntregas(content) {
    const list = activas().filter((a) => !asigFilter || a.id === asigFilter);
    content.innerHTML = '<span class="skeleton skeleton-card"></span>';
    const datos = await Promise.all(list.map((a) => api(`/api/uni/asignaturas/${a.id}/entregas`, { quiet: true }).then((r) => [a, r]).catch(() => [a, { entregas: [], media: null }])));
    if (tab !== 'entregas') return;
    const hoy = new Date().toISOString().slice(0, 10);
    content.innerHTML = `<div class="row uni-toolbar"><button type="button" class="btn btn-tinted btn-sm" data-new-entrega>${icon('plus', 'icon-sm')}Entrega o examen</button>
      <span class="tiny muted">Las entregas son tareas; los exámenes, eventos del calendario. Aquí se ven juntos.</span></div>`
      + datos.map(([a, r]) => {
        const items = r.entregas.filter((x) => x.tipo !== 'tarea' || x.fecha);
        return `<section class="uni-subject" style="--subj:${color(a)}"><h2 class="cat-header"><span class="dot" style="background:${color(a)}"></span><span class="uni-code">${esc(a.codigo)}</span><span class="uni-name">${esc(a.nombre)}</span><span class="count">${items.length}</span>
            ${r.media ? `<span class="grow"></span><span class="small tabular uni-media" title="Media ponderada de lo que ya tiene nota">${icon('star', 'icon-sm')}Media ${String(r.media.media).replace('.', ',')} · ${r.media.peso_evaluado} % evaluado</span>` : ''}</h2>
          ${items.length ? `<ul class="list uni-entregas">${items.map((x) => {
            const dias = x.fecha ? Math.round((new Date(x.fecha + 'T00:00') - new Date(hoy + 'T00:00')) / 864e5) : null;
            return `<li class="list-row${x.hecho ? ' is-done' : ''}" data-origen="${x.origen}" data-id="${x.id}">
              ${x.origen === 'tarea' ? `<button type="button" class="card-check small-check${x.hecho ? ' done' : ''}" data-ent-done role="checkbox" aria-checked="${x.hecho}" aria-label="${x.hecho ? 'Volver a pendiente' : 'Hecha'}: ${esc(x.titulo)}">${icon('check', 'icon-sm')}</button>` : `<span class="uni-ev-ico" aria-hidden="true">${icon(x.tipo === 'examen' ? 'triangle-alert' : 'calendar', 'icon-sm')}</span>`}
              <span class="row-main"><span class="row-title">${esc(sinSigla(x.titulo, a.codigo))}</span>
                <span class="row-sub">${x.fecha ? `${fmtDay(x.fecha)}${x.hora ? ` · ${x.hora}` : ''}` : 'sin fecha'}${x.temas?.length ? ` · ${x.temas.length} temas` : ''}</span></span>
              <span class="tag${x.tipo === 'examen' ? ' uni-exam' : ''}">${x.tipo === 'examen' ? 'Examen' : x.tipo === 'entrega' ? 'Entrega' : 'Tarea'}</span>
              ${dias !== null && !x.hecho ? `<span class="tiny tabular uni-count${dias <= 2 ? ' is-soon' : ''}">${countdown(dias)}</span>` : ''}
              <span class="tiny tabular muted" title="Peso en la nota final">${x.peso ? `${String(x.peso).replace('.', ',')} %` : ''}</span>
              <span class="tiny tabular uni-nota" title="Nota obtenida">${x.nota !== null && x.nota !== undefined ? String(x.nota).replace('.', ',') : ''}</span>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-ent-edit aria-label="Peso, nota y temas de «${esc(x.titulo)}»">${icon('pencil', 'icon-sm')}</button></li>`;
          }).join('')}</ul>` : '<p class="small muted uni-hint">Nada todavía.</p>'}</section>`;
      }).join('');
    content.querySelector('[data-new-entrega]').addEventListener('click', newEntrega);
    content.querySelectorAll('[data-ent-done]').forEach((b) => b.addEventListener('click', async () => {
      const li = b.closest('li');
      await Items.ready();
      await Items.setDone(Number(li.dataset.id), b.getAttribute('aria-checked') !== 'true');
      load();
    }));
    content.querySelectorAll('[data-ent-edit]').forEach((b) => b.addEventListener('click', () => {
      const li = b.closest('li');
      const [, r] = datos.find(([, r2]) => r2.entregas.some((x) => x.origen === li.dataset.origen && x.id === Number(li.dataset.id)));
      editEntrega(r.entregas.find((x) => x.origen === li.dataset.origen && x.id === Number(li.dataset.id)));
    }));
  }

  async function newEntrega() {
    const list = activas();
    const res = await formDialog('Entrega o examen', `
      <div class="choice-chips" role="radiogroup" aria-label="Tipo"><label class="choice-chip"><input type="radio" name="tipo" value="entrega" checked><span>Entrega (tarea)</span></label>
        <label class="choice-chip"><input type="radio" name="tipo" value="examen"><span>Examen (evento)</span></label></div>
      <label class="field"><span class="field-label">Asignatura</span><select name="asig" class="select">${list.map((a) => `<option value="${a.id}" ${a.id === asigFilter ? 'selected' : ''}>${esc(a.codigo)} · ${esc(a.nombre)}</option>`).join('')}</select></label>
      <label class="field"><span class="field-label">Qué</span><input name="titulo" class="input" required maxlength="300" placeholder="Práctica 5 / Parcial 2…"></label>
      <div class="row"><label class="field grow"><span class="field-label">Fecha</span><input name="fecha" type="date" class="input" required></label>
        <label class="field"><span class="field-label">Hora</span><input name="hora" type="time" class="input"></label>
        <label class="field"><span class="field-label">Peso (%)</span><input name="peso" type="number" min="0" max="100" step="0.5" class="input"></label></div>`, 'Crear');
    if (!res?.titulo?.trim() || !res.fecha) return;
    const a = Number(res.asig);
    const peso = res.peso === '' ? null : Number(res.peso);
    if (res.tipo === 'examen') {
      const start = res.hora ? `${res.fecha}T${res.hora}` : res.fecha;
      await api('/api/calendar/events', { method: 'POST', body: { title: `${asig(a)?.codigo} · ${res.titulo.trim()}`, start, all_day: !res.hora, kind: 'examen', asignatura_id: a, peso } });
    } else {
      await api('/api/items', { method: 'POST', body: { text: res.titulo.trim(), type: 'tarea', asignatura_id: a, uni_tipo: 'entrega', due_date: res.fecha, due_time: res.hora || null, peso } });
    }
    toast('Creado: sale en el calendario y en Hoy el día que toca');
    load();
  }

  async function editEntrega(x) {
    const temas = V.temas.filter((t) => t.asignatura_id === x.asignatura_id && !t.falta);
    const res = await formDialog(x.titulo, `
      <div class="row"><label class="field grow"><span class="field-label">Peso en la nota final (%)</span><input name="peso" type="number" min="0" max="100" step="0.5" class="input" value="${x.peso ?? ''}"></label>
        <label class="field grow"><span class="field-label">Nota obtenida (0–10)</span><input name="nota" type="number" min="0" max="10" step="0.01" class="input" value="${x.nota ?? ''}"></label></div>
      ${temas.length ? `<fieldset class="field"><legend class="field-label">Temas que entran</legend><div class="uni-temas-pick">${temas.map((t) => `<label class="row tiny"><input type="checkbox" class="checkbox" name="tema" value="${t.id}" ${x.temas.includes(t.id) ? 'checked' : ''}>${esc(t.titulo)}</label>`).join('')}</div></fieldset>` : ''}`, 'Guardar');
    if (!res) return;
    const body = { peso: res.peso === '' ? -1 : Number(res.peso), nota: res.nota === '' ? -1 : Number(res.nota), temas: res.tema };
    await api(x.origen === 'tarea' ? `/api/items/${x.id}` : `/api/calendar/events/${x.id}`, { method: 'PATCH', body });
    load();
  }

  /* ---------- Horario: clases (eventos que se repiten) ---------- */
  async function renderHorario(content) {
    content.innerHTML = '<span class="skeleton skeleton-card"></span>';
    let clases = [], rut = [];
    try {
      [{ clases }, { rutinas: rut }] = await Promise.all([api('/api/uni/horario', { quiet: true }), api('/api/uni/horario/rutinas', { quiet: true })]);
    } catch { showState(content, loadFailed('No se pudo cargar el horario', true), () => renderHorario(content)); return; }
    if (tab !== 'horario') return;
    clases = clases.filter((c) => !asigFilter || c.asignatura_id === asigFilter);
    const byDay = DIAS.slice(0, 5).map((_, d) => clases.filter((c) => (c.repeat?.freq === 'weekly' ? c.repeat.days.includes(d) : true))
      .sort((a, b) => a.start.slice(11).localeCompare(b.start.slice(11))));
    const extra = clases.some((c) => c.repeat?.freq === 'weekly' && c.repeat.days.some((d) => d > 4));
    content.innerHTML = `${rut.length ? `<div class="panel uni-convert"><div class="panel-body">
        <p class="small">${icon('repeat', 'icon-sm')} Tu horario está ahora en una rutina: ${rut.map((r) => `<b>${esc(r.rutina ? `${r.rutina} › ` : '')}${esc(r.titulo)}</b> (${esc(r.hora)}, ${r.duracion || 60} min)`).join(', ')}.
          Pásalo a clases del calendario para que salga con su asignatura en el calendario, Hoy y la Waybar (el bloque va a la papelera; se puede deshacer).</p>
        <div class="row">${rut.map((r) => `<button type="button" class="btn btn-tinted btn-sm" data-convert="${r.id}">${icon('calendar-clock', 'icon-sm')}Convertir «${esc(r.titulo)}» en clases</button>`).join('')}</div></div></div>` : ''}
      <div class="row uni-toolbar"><button type="button" class="btn btn-tinted btn-sm" data-new-clase>${icon('plus', 'icon-sm')}Clase</button>
        <span class="tiny muted">Cada clase es un evento del calendario que se repite hasta el fin del cuatrimestre.</span></div>
      ${clases.length ? `<div class="uni-week${extra ? ' has-weekend' : ''}" role="table" aria-label="Horario semanal">${(extra ? DIAS : DIAS.slice(0, 5)).map((dn, d) => {
        const list = d < 5 ? byDay[d] : clases.filter((c) => c.repeat?.days?.includes(d));
        return `<div class="uni-day" role="row"><h3 class="uni-day-name" role="columnheader">${['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][d]}</h3>
          ${list.map((c) => `<button type="button" class="uni-class" role="cell" data-clase="${c.id}" style="--subj:${c.color ? Ctx.color(c.color) : 'var(--tile-universidad)'}">
            <span class="tabular tiny">${c.start.slice(11, 16)}–${(c.end || '').slice(11, 16)}</span>
            <span class="uni-class-name">${esc(c.asignatura || c.title)}</span>${c.location ? `<span class="tiny muted">${esc(c.location)}</span>` : ''}</button>`).join('') || '<span class="tiny muted">—</span>'}</div>`;
      }).join('')}</div>` : emptyState({ iconName: 'calendar-clock', title: 'Sin clases', text: 'Añade tus clases (o convierte la rutina) y saldrán en el calendario, Hoy, Rutinas y la Waybar.', compact: true })}`;
    content.querySelector('[data-new-clase]').addEventListener('click', () => claseDialog());
    content.querySelectorAll('[data-convert]').forEach((b) => b.addEventListener('click', async () => {
      const r = await api(`/api/uni/clases/desde-rutina/${b.dataset.convert}`, { method: 'POST' });
      toast('Ahora es una clase del calendario', { action: { label: 'Deshacer', onClick: async () => {
        await api(`/api/calendar/events/${r.event_id}`, { method: 'DELETE' });
        await api('/api/items/undo', { method: 'POST', body: { token: r.undo } });
        load();
      } } });
      Items.load?.().catch(() => {});
      renderHorario(content);
    }));
    content.querySelectorAll('[data-clase]').forEach((b) => b.addEventListener('click', () => claseDialog(clases.find((c) => c.id === Number(b.dataset.clase)))));
  }

  async function claseDialog(c = null) {
    const list = activas();
    const days = c?.repeat?.freq === 'weekly' ? c.repeat.days : c ? [0, 1, 2, 3, 4, 5, 6] : [0];
    const res = await formDialog(c ? 'Clase' : 'Nueva clase', `
      <label class="field"><span class="field-label">Asignatura</span><select name="asig" class="select"><option value="">— Sin asignatura —</option>${list.map((a) => `<option value="${a.id}" ${(c ? c.asignatura_id === a.id : a.id === asigFilter) ? 'selected' : ''}>${esc(a.codigo)} · ${esc(a.nombre)}</option>`).join('')}</select></label>
      ${c ? `<label class="field"><span class="field-label">Título</span><input name="titulo" class="input" value="${esc(c.title)}"></label>` : ''}
      ${dayPicker({ days, legend: 'Días' })}
      <div class="row"><label class="field grow"><span class="field-label">Empieza</span><input name="inicio" type="time" class="input" required value="${c ? c.start.slice(11, 16) : '08:30'}"></label>
        <label class="field grow"><span class="field-label">Termina</span><input name="fin" type="time" class="input" required value="${c ? (c.end || '').slice(11, 16) : '10:30'}"></label></div>
      <label class="field"><span class="field-label">Aula</span><input name="aula" class="input" maxlength="120" value="${esc(c?.location || '')}"></label>
      <div class="row"><label class="field grow"><span class="field-label">Desde</span><input name="desde" type="date" class="input" value="${c ? c.start.slice(0, 10) : ''}"></label>
        <label class="field grow"><span class="field-label">Hasta (fin del cuatrimestre)</span><input name="hasta" type="date" class="input" value="${c?.repeat_until || ''}"></label></div>`,
    c ? 'Guardar' : 'Crear', c ? { danger: 'Borrar la clase' } : {});
    if (res === 'danger') {
      const r = await api(`/api/calendar/events/${c.id}`, { method: 'DELETE' });
      toast('Clase en la papelera', { action: { label: 'Deshacer', onClick: () => api(`/api/trash/brain/${r.trash}/restore`, { method: 'POST' }).then(load) } });
      return load();
    }
    if (!res) return;
    const dlgDays = res.__days;
    if (!dlgDays.length) { toast('Elige al menos un día', { type: 'info' }); return; }
    if (c) {
      await api(`/api/calendar/events/${c.id}`, { method: 'PATCH', body: {
        title: res.titulo, start: `${res.desde || c.start.slice(0, 10)}T${res.inicio}`, end: `${res.desde || c.start.slice(0, 10)}T${res.fin}`, location: res.aula,
        repeat: dlgDays.length === 7 ? { freq: 'daily' } : { freq: 'weekly', days: dlgDays }, repeat_until: res.hasta || '',
        asignatura_id: Number(res.asig) || 0, ...(Number(res.asig) ? {} : { contexto: 'universidad' }) } });
    } else {
      await api('/api/uni/clases', { method: 'POST', body: { asignatura_id: Number(res.asig) || null, dias: dlgDays, inicio: res.inicio, fin: res.fin, aula: res.aula || null, desde: res.desde || null, hasta: res.hasta || null } });
    }
    load();
  }

  /* ---------- Tareas (la lista común, fija en Universidad) ---------- */
  function renderTareas() {
    const where = $('uniCaptureWhere');
    where.innerHTML = `<option value="universidad">Universidad (sin asignatura)</option>${activas().map((a) => `<option value="a:${a.id}" ${a.id === asigFilter ? 'selected' : ''}>${esc(a.codigo)}</option>`).join('')}`;
    if (!itemView) {
      itemView = ItemList.mount($('uniItemList'), { variant: 'page', filters: { contexto: 'universidad', asignatura: asigFilter || null } });
    } else itemView.setFilters({ asignatura: asigFilter || null });
  }
  $('uniCapture').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = $('uniCaptureText');
    const text = input.value.trim();
    if (!text) return;
    await Items.capture(/^\s*[tireg]\s*:/i.test(text) ? text : `t: ${text}`, 'tarea', Ctx.whereToPatch($('uniCaptureWhere').value));
    input.value = '';
  });

  async function newTask(where, text) {
    await Items.ready();
    const v = await uiPrompt('Nueva tarea', { value: text, confirmLabel: 'Crear' });
    if (!v?.trim()) return;
    await Items.create({ text: v.trim(), type: 'tarea', ...where });
    toast('Tarea creada');
    load();
  }

  /* ---------- Asignaturas: crear y editar ---------- */
  async function openAsigDialog(a = null) {
    let carpetas = [];
    if (V.raiz_ok) carpetas = (await api('/api/uni/carpetas', { quiet: true }).catch(() => ({ carpetas: [] }))).carpetas;
    const res = await formDialog(a ? `Editar ${a.codigo}` : 'Nueva asignatura', `
      <div class="row"><label class="field"><span class="field-label">Sigla</span><input name="codigo" class="input uni-code-input" required maxlength="20" value="${esc(a?.codigo || '')}" placeholder="GABD…"></label>
        <label class="field grow"><span class="field-label">Nombre</span><input name="nombre" class="input" required maxlength="120" value="${esc(a?.nombre || '')}" placeholder="Gestión y Administración de Bases de Datos…"></label></div>
      <label class="field"><span class="field-label">Carpeta (dentro de la raíz)</span>
        <input name="carpeta" class="input" list="uniCarpetas" maxlength="1000" value="${esc(a?.carpeta || '')}" placeholder="${V.raiz ? 'Tercero/Bases de datos…' : 'Primero elige la raíz en Ajustes'}">
        <datalist id="uniCarpetas">${carpetas.map((c) => `<option value="${esc(c.ruta)}">${c.temas} temas</option>`).join('')}</datalist>
        <span class="field-hint">Relativa a ${esc(V.raiz || 'la carpeta raíz')}. Solo se lee.</span></label>
      <div class="row"><label class="field grow"><span class="field-label">Profesor</span><input name="profesor" class="input" maxlength="200" value="${esc(a?.profesor || '')}"></label>
        <label class="field grow"><span class="field-label">Aula</span><input name="aula" class="input" maxlength="120" value="${esc(a?.aula || '')}"></label></div>
      <div class="row"><label class="field grow"><span class="field-label">Alias para @menciones</span><input name="alias" class="input" maxlength="300" value="${esc((a?.alias || []).join(', '))}" placeholder="bd, bases…"></label>
        <label class="field"><span class="field-label">Cuatrimestre</span><input name="semestre" class="input" maxlength="40" value="${esc(a?.semestre || '')}" placeholder="2026-27 · 1.º…"></label></div>
      <fieldset class="field"><legend class="field-label">Color</legend><div class="uni-colors">${Array.from({ length: 10 }, (_, i) => `<label class="uni-color" style="--c:var(--cat-${i})"><input type="radio" name="color" value="cat-${i}" ${(a?.color || `cat-${V.asignaturas.length % 10}`) === `cat-${i}` ? 'checked' : ''}><span class="sr-only">Color ${i + 1}</span></label>`).join('')}</div></fieldset>
      <label class="field"><span class="field-label">Enlaces (uno por línea: «Moodle https://…»)</span><textarea name="enlaces" class="textarea" rows="2" maxlength="5000">${esc((a?.enlaces || []).map((l) => `${l.titulo} ${l.url}`).join('\n'))}</textarea></label>`, a ? 'Guardar' : 'Crear');
    if (!res) return;
    const enlaces = res.enlaces.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
      const m = l.match(/^(.*?)\s*(https?:\/\/\S+)$/i);
      return m ? { titulo: m[1] || 'Enlace', url: m[2] } : null;
    }).filter(Boolean);
    const body = { codigo: res.codigo.trim(), nombre: res.nombre.trim(), carpeta: res.carpeta.trim(), profesor: res.profesor, aula: res.aula,
      alias: res.alias.split(',').map((x) => x.trim()).filter(Boolean), semestre: res.semestre, color: res.color, enlaces };
    try {
      if (a) await api(`/api/uni/asignaturas/${a.id}`, { method: 'PATCH', body });
      else {
        const r = await api('/api/uni/asignaturas', { method: 'POST', body });
        if (body.carpeta) await api(`/api/uni/asignaturas/${r.id}/sync`, { method: 'POST', quiet: true }).catch(() => {});
      }
    } catch { return; }
    await Ctx.load(true);
    load();
  }
  $('uniAdd').addEventListener('click', () => openAsigDialog());

  /* Asistente: asignaturas a partir de las subcarpetas de la raíz (solo lectura) */
  async function openWizard() {
    let carpetas = [];
    try { carpetas = (await api('/api/uni/carpetas')).carpetas; } catch { return; }
    const usadas = new Set(V.asignaturas.map((a) => a.carpeta));
    const libres = carpetas.filter((c) => !usadas.has(c.ruta) && c.temas > 0);
    if (!libres.length) { uiAlert('Nada nuevo', 'Todas las carpetas con contenido ya son asignaturas.'); return; }
    const sigla = (n) => n.split(/[\s_-]+/).filter((w) => w.length > 2 || /^[A-Z]/.test(w)).map((w) => w[0]).join('').toUpperCase().slice(0, 6) || n.slice(0, 4).toUpperCase();
    const res = await formDialog('Asignaturas desde las carpetas', `
      <p class="small muted">Marca las carpetas de este cuatrimestre y pon su sigla (la que usarás con @). Cada subcarpeta o PDF suelto será un tema. Nada se toca en el disco.</p>
      <ul class="list uni-wizard">${libres.map((c, i) => `<li class="list-row uni-wiz-row" style="padding-left:${(c.nivel - 1) * 16 + 8}px">
        <input type="checkbox" class="checkbox" name="w${i}" id="uw${i}" ${c.nivel > 1 ? '' : ''}>
        <label for="uw${i}" class="grow ellipsis" title="${esc(c.ruta)}">${icon('folder', 'icon-sm')}${esc(c.ruta)} <span class="tiny muted">${c.temas} temas</span></label>
        <input class="input input-sm uni-code-input" name="c${i}" maxlength="20" value="${esc(sigla(c.nombre))}" aria-label="Sigla de ${esc(c.ruta)}">
        <input class="input input-sm" name="n${i}" maxlength="120" value="${esc(c.sugerido)}" aria-label="Nombre de ${esc(c.ruta)}"></li>`).join('')}</ul>`, 'Crear las marcadas');
    if (!res) return;
    let n = 0;
    for (let i = 0; i < libres.length; i++) {
      if (!res[`w${i}`]) continue;
      try {
        const r = await api('/api/uni/asignaturas', { method: 'POST', body: { codigo: res[`c${i}`].trim(), nombre: res[`n${i}`].trim(), carpeta: libres[i].ruta } });
        await api(`/api/uni/asignaturas/${r.id}/sync`, { method: 'POST', quiet: true }).catch(() => {});
        n++;
      } catch { /* el aviso ya sale (sigla repetida…) */ }
    }
    await Ctx.load(true);
    await load();
    if (n) { toast(`${n} asignaturas creadas`); openPropuesta(); }
  }

  /* Propuesta: llevar a Universidad lo que ya hay (se confirma en bloque) */
  async function openPropuesta() {
    const p = await api('/api/uni/propuesta');
    if (!p.items.length && !p.eventos.length) { toast('Nada que mover: ninguna tarea ni evento coincide con tus asignaturas', { type: 'info' }); return; }
    const opts = (sel) => activas().map((a) => `<option value="${a.id}" ${a.id === sel ? 'selected' : ''}>${esc(a.codigo)}</option>`).join('');
    const res = await formDialog('Pasar a Universidad', `
      <p class="small muted">Estas tareas y eventos parecen de tus asignaturas (por su categoría o la sigla del principio). Marca las que quieras mover; se puede deshacer.</p>
      ${p.items.length ? `<h3 class="uni-group-title">Tareas <span class="count">${p.items.length}</span></h3><ul class="list uni-wizard">${p.items.map((x, i) => `<li class="list-row">
        <input type="checkbox" class="checkbox" name="i${i}" id="up${i}" checked><label for="up${i}" class="grow ellipsis">${esc(x.titulo)}${x.fecha ? ` <span class="tiny muted">${fmtDay(x.fecha)}</span>` : ''}${x.hecho ? ' <span class="tiny muted">(hecha)</span>' : ''}</label>
        <select class="select input-sm" name="ia${i}" aria-label="Asignatura">${opts(x.asignatura.id)}</select>
        <select class="select input-sm" name="it${i}" aria-label="Tipo"><option value="">Tarea</option><option value="entrega" ${x.uni_tipo === 'entrega' ? 'selected' : ''}>Entrega</option><option value="examen" ${x.uni_tipo === 'examen' ? 'selected' : ''}>Examen</option></select></li>`).join('')}</ul>` : ''}
      ${p.eventos.length ? `<h3 class="uni-group-title">Eventos <span class="count">${p.eventos.length}</span></h3><ul class="list uni-wizard">${p.eventos.map((x, i) => `<li class="list-row">
        <input type="checkbox" class="checkbox" name="e${i}" id="upe${i}" checked><label for="upe${i}" class="grow ellipsis">${esc(x.titulo)} <span class="tiny muted">${fmtDay(x.fecha)}</span></label>
        <select class="select input-sm" name="ea${i}" aria-label="Asignatura">${opts(x.asignatura.id)}</select></li>`).join('')}</ul>` : ''}`, 'Mover las marcadas');
    if (!res) return;
    const body = {
      items: p.items.map((x, i) => (res[`i${i}`] ? { id: x.id, asignatura_id: Number(res[`ia${i}`]), uni_tipo: res[`it${i}`] || null } : null)).filter(Boolean),
      eventos: p.eventos.map((x, i) => (res[`e${i}`] ? { id: x.id, asignatura_id: Number(res[`ea${i}`]) } : null)).filter(Boolean),
    };
    const r = await api('/api/uni/propuesta/aplicar', { method: 'POST', body });
    toast(`${r.items} tareas y ${r.eventos} eventos pasan a Universidad`, { action: { label: 'Deshacer', onClick: () => api('/api/uni/propuesta/deshacer', { method: 'POST' }).then(() => { Items.load?.(); load(); }) } });
    Items.load?.().catch(() => {});
    load();
  }

  /* Ajustes: carpeta raíz, raíz de proyectos y contexto de la Waybar */
  async function openSettings() {
    const a = await api('/api/contextos/ajustes');
    const res = await formDialog('Ajustes de Universidad', `
      <label class="field"><span class="field-label">Carpeta raíz de la universidad</span><input name="uni_raiz" class="input" maxlength="1000" value="${esc(a.uni_raiz)}" placeholder="/run/media/jose/474DE33309C01BF8/Uja…">
        <span class="field-hint">Ruta en este equipo (el servidor del panel). Solo se lee; si el disco no está montado no se marca nada.</span></label>
      <label class="field"><span class="field-label">Carpeta raíz de los proyectos</span><input name="proyectos_raiz" class="input" maxlength="1000" value="${esc(a.proyectos_raiz)}"></label>
      <label class="field"><span class="field-label">Prompt para la IA («Copiar prompt» en cada tema)</span><textarea name="uni_prompt" class="textarea" rows="5" maxlength="5000">${esc(a.uni_prompt)}</textarea>
        <span class="field-hint">{asignatura} y {tema} se cambian por los suyos. Vacío = el de siempre.</span></label>
      <label class="field"><span class="field-label">Contexto de la Waybar</span><select name="waybar_contexto" class="select">${[['activo', 'El activo en el panel'], ['todo', 'Todo'], ['puntual', 'Puntual'], ['universidad', 'Universidad'], ['proyectos', 'Proyectos']].map(([v, l]) => `<option value="${v}" ${a.waybar_contexto === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <p class="tiny muted">Para abrir carpetas desde el navegador, instala el abridor en el portátil: <code>scripts/desktop/abrir/instalar.sh</code>.</p>`, 'Guardar');
    if (!res) return;
    try { await api('/api/contextos/ajustes', { method: 'PUT', body: res }); } catch { return; }
    toast('Ajustes guardados');
    load();
  }

  $('uniMenu').addEventListener('click', (e) => openMenu(e.currentTarget, [
    { label: 'Asignaturas desde las carpetas', icon: 'folder-tree', onClick: openWizard },
    { label: 'Pasar tareas y eventos a Universidad', icon: 'move', onClick: openPropuesta },
    { label: 'Archivadas', icon: 'archive', onClick: showArchived },
    { label: 'Ajustes (carpeta raíz, prompt, Waybar)', icon: 'settings', onClick: openSettings },
  ]));

  function showArchived() {
    const arch = V.asignaturas.filter((a) => a.archivada);
    formDialog('Asignaturas archivadas', arch.length ? `<ul class="list">${arch.map((a) => `<li class="list-row"><span class="ctx-dot" style="background:${color(a)}"></span><span class="grow">${esc(a.codigo)} · ${esc(a.nombre)}</span>
      <button type="button" class="btn btn-sm" data-unarchive="${a.id}">Recuperar</button></li>`).join('')}</ul>` : '<p class="small muted">Ninguna.</p>', null, {
      onOpen: (dlg) => dlg.querySelectorAll('[data-unarchive]').forEach((b) => b.addEventListener('click', async () => {
        await api(`/api/uni/asignaturas/${b.dataset.unarchive}`, { method: 'PATCH', body: { archivada: false } });
        closeModal(dlg);
        load();
      })),
    });
  }

  /* ---------- Diálogo de formulario genérico: resuelve con los campos o null ---------- */
  function formDialog(title, body, okLabel, { danger, onOpen } = {}) {
    return new Promise((resolve) => {
      const dlg = document.createElement('dialog');
      dlg.className = 'modal modal-sm uni-dialog';
      const id = 'ud' + Math.random().toString(36).slice(2, 7);
      dlg.setAttribute('aria-labelledby', id);
      dlg.innerHTML = `<div class="modal-header"><h2 id="${id}">${esc(title)}</h2>
          <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
        <form class="modal-body stack" id="${id}f" autocomplete="off">${body}</form>
        <div class="modal-footer">${danger ? `<button type="button" class="btn btn-danger" data-danger>${esc(danger)}</button><span class="spacer"></span>` : ''}
          <button type="button" class="btn" data-close>${okLabel ? 'Cancelar' : 'Cerrar'}</button>
          ${okLabel ? `<button type="submit" form="${id}f" class="btn btn-primary">${esc(okLabel)}</button>` : ''}</div>`;
      document.body.appendChild(dlg);
      wireAllDialogs?.();
      let result = null;
      const f = dlg.querySelector('form');
      f.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!f.reportValidity()) return;
        const out = {};
        [...f.elements].forEach((el) => {
          if (!el.name) return;
          if (el.type === 'checkbox' && el.name === 'tema') { (out.tema ||= []).push(...(el.checked ? [Number(el.value)] : [])); return; }
          if (el.type === 'checkbox') { out[el.name] = el.checked; return; }
          if (el.type === 'radio') { if (el.checked) out[el.name] = el.value; return; }
          out[el.name] = el.value;
        });
        if (f.querySelector('[data-day]')) out.__days = [...f.querySelectorAll('[data-day]')].filter((c) => c.checked).map((c) => Number(c.dataset.day));
        out.tema ||= [];
        result = out;
        closeModal(dlg);
      });
      dlg.querySelector('[data-danger]')?.addEventListener('click', () => { result = 'danger'; closeModal(dlg); });
      openModal(dlg, { focus: 'input:not([type=hidden]), select, [data-close]', onClose: () => { dlg.remove(); resolve(result); } });
      onOpen?.(dlg);
    });
  }

  /* ---------- Arranque ---------- */
  const urlTab = new URLSearchParams(location.search).get('pestana');
  if (['entregas', 'horario', 'tareas'].includes(urlTab)) setTab(urlTab);
  else Prefs.ready?.then(() => { const t = Prefs.get(TAB_KEY, 'temas'); if (t !== tab && ['temas', 'entregas', 'horario', 'tareas'].includes(t)) setTab(t); }).catch(() => {});
  document.addEventListener('prefs:changed', () => { if (tab === 'temas') render(); });
  Ctx.load().catch(() => {});
  load();
})();
