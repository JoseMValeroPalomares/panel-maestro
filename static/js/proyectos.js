/* =====================================================================
   Proyectos (/proyectos y /proyectos/<slug>).
   Lista: tarjetas por estado, tablero por estado (arrastrar = cambiar estado) o cronología, con búsqueda,
   filtros (estado, prioridad, etiqueta) y orden. Dentro: cabecera con descripción Markdown, prioridad, fechas,
   etiquetas y progreso; pestañas Tareas (tablero agrupado por estado, versión o prioridad / lista ordenable /
   cronología), Versiones, Registro de cambios, Ideas, Esquemas, Bitácora y Enlaces. Cada tarea abre su ficha
   (proyectos-ficha.js). Las tareas e ideas son las de siempre (Items, contexto «proyectos» con proyecto_id);
   los esquemas, tableros del Inbox; la bitácora, una nota. API: /api/proyectos (app/proyectos.py).
   ===================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  const fold = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const root = $('pjRoot');
  const slug = decodeURIComponent(location.pathname.split('/')[2] || '');
  const ESTADOS = { idea: 'Idea', 'en-curso': 'En curso', pausado: 'Pausado', terminado: 'Terminado' };
  const PRIOS = { alta: 'Alta', media: 'Media', baja: 'Baja' };
  const PRIO_RANK = { alta: 0, media: 1, baja: 2 };
  const TABS = [['tareas', 'Tareas', 'list-todo'], ['versiones', 'Versiones', 'milestone'], ['cambios', 'Registro de cambios', 'history'],
    ['ideas', 'Ideas', 'lightbulb'], ['esquemas', 'Esquemas', 'shapes'], ['bitacora', 'Bitácora', 'notebook-pen'], ['enlaces', 'Enlaces', 'link']];
  const LIST_VIEWS = [['tarjetas', 'Tarjetas', 'layout-grid'], ['tablero', 'Tablero', 'square-kanban'], ['cronologia', 'Cronología', 'chart-gantt']];
  const TASK_VIEWS = [['versiones', 'Por versión', 'milestone'], ['columnas', 'Tablero', 'square-kanban'], ['lista', 'Tabla', 'table-2'], ['cronologia', 'Cronología', 'chart-gantt']];
  const GROUPS = [['estado', 'Estado'], ['version', 'Versión'], ['prioridad', 'Prioridad']];
  const SORTS = [['manual', 'Orden manual'], ['nombre', 'Nombre'], ['progreso', 'Progreso'], ['fin', 'Fecha de fin'], ['prioridad', 'Prioridad'], ['recientes', 'Más recientes']];
  const VIEW_KEY = 'proyecto.vista-tareas';  // clave nueva: «Por versión» es la de por defecto también para quien ya tenía otra
  const FOLD_TASKS = 'proyecto.subtareas-abiertas';  // { id: true/false }: por defecto, a la vista salvo en las tareas hechas
  const FOLD_VERS = 'proyecto.versiones-plegadas';  // { "v12" | "none": true/false }: las cerradas empiezan plegadas
  const fmtDay = (iso, year = true) => (iso ? new Date(iso + 'T00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short', ...(year ? { year: 'numeric' } : {}) }) : '');
  const todayIso = () => PjVistas.isoOf(new Date());
  const daysTo = (iso) => Math.round((new Date(iso + 'T00:00') - new Date(todayIso() + 'T00:00')) / 86400000);
  const color = (c) => Ctx.color(c);
  const pref = (k, d) => (window.Prefs ? Prefs.get(k, d) ?? d : d);  // null (preferencia borrada) = la de por defecto
  const setPref = (k, v) => window.Prefs?.set(k, v);
  let P = null, tab = new URLSearchParams(location.search).get('pestana') || 'tareas';
  let ALL = [];
  // Búsqueda y filtros viven en la URL (se pueden recargar, compartir y volver con Atrás)
  const qs = new URLSearchParams(location.search);
  const L = { q: qs.get('q') || '', estado: qs.get('estado') || '', prioridad: qs.get('prioridad') || '', etiqueta: qs.get('etiqueta') || '' };
  const T = { q: qs.get('tq') || '', prio: qs.get('tprio') || '', version: qs.get('tver') || '' };
  function syncUrl() {
    const u = new URLSearchParams();
    if (slug) {
      u.set('pestana', tab);
      if (tab === 'tareas') Object.entries({ tq: T.q, tprio: T.prio, tver: T.version }).forEach(([k, v]) => v && u.set(k, v));
    } else Object.entries(L).forEach(([k, v]) => v && u.set(k, v));
    const s = u.toString();
    history.replaceState(null, '', s ? `?${s}` : location.pathname);
  }

  /* ---------- Piezas comunes ---------- */
  const prioTag = (p) => (p ? `<span class="tag prio" data-prio="${esc(p)}">${icon('flag', 'icon-sm')}${PRIOS[p] || esc(p)}</span>` : '');
  const tagsHtml = (tags) => (tags?.length ? `<span class="pj-tags" translate="no">${tags.map((t) => `<span class="pj-tag">#${esc(t)}</span>`).join('')}</span>` : '');
  function datesHtml(p, done) {
    if (!p.fecha_inicio && !p.fecha_fin) return '';
    const left = p.fecha_fin ? daysTo(p.fecha_fin) : null;
    const late = left !== null && left < 0 && !done;
    const range = p.fecha_inicio && p.fecha_fin ? `${fmtDay(p.fecha_inicio, false)} – ${fmtDay(p.fecha_fin)}` : p.fecha_fin ? `Fin ${fmtDay(p.fecha_fin)}` : `Desde ${fmtDay(p.fecha_inicio)}`;
    const extra = left === null || done ? '' : late ? ` · vencido hace ${-left} d` : left === 0 ? ' · hoy' : left <= 14 ? ` · quedan ${left} d` : '';
    return `<span class="pj-dates${late ? ' is-late' : ''}">${icon('calendar-range', 'icon-sm')}${range}${extra}</span>`;
  }

  /* =====================================================================
     Lista de proyectos
     ===================================================================== */
  async function loadList() {
    let data;
    try { data = await api('/api/proyectos', { quiet: true }); } catch { showState(root, loadFailed('No se pudieron cargar los proyectos', true), loadList); return; }
    ALL = data.proyectos;
    if (!ALL.length) {
      root.innerHTML = emptyState({ iconName: 'rocket', title: 'Construye tus proyectos', text: 'Un proyecto junta sus tareas, ideas, versiones, esquemas y una bitácora. Captura con «#nombre» desde cualquier sitio.', actionLabel: 'Crear el primero', action: 'new' });
      root.querySelector('[data-empty-action=new]')?.addEventListener('click', () => projectDialog());
      return;
    }
    if (!$('pjList')) renderListShell();
    paintTagFilter();
    paintList();
  }

  function renderListShell() {
    const vista = pref('proyectos.vista', 'tarjetas'), orden = pref('proyectos.orden', 'manual');
    root.innerHTML = `<div class="pj-filters" role="search" aria-label="Buscar y filtrar proyectos">
        <div class="pj-search">${icon('search', 'icon-sm')}<label class="sr-only" for="pjSearch">Buscar proyectos</label>
          <input id="pjSearch" class="input" type="search" placeholder="Buscar…" autocomplete="off" aria-keyshortcuts="/"><kbd class="pj-kbd hide-mobile" aria-hidden="true">/</kbd></div>
        <label class="sr-only" for="pjFEstado">Estado</label><select id="pjFEstado" class="select input-sm"><option value="">Estado: todos</option>${Object.entries(ESTADOS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select>
        <label class="sr-only" for="pjFPrio">Prioridad</label><select id="pjFPrio" class="select input-sm"><option value="">Prioridad</option>${Object.entries(PRIOS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}<option value="-">Sin prioridad</option></select>
        <label class="sr-only" for="pjFTag">Etiqueta</label><select id="pjFTag" class="select input-sm"></select>
        <label class="sr-only" for="pjSort">Orden</label><select id="pjSort" class="select input-sm">${SORTS.map(([k, l]) => `<option value="${k}" ${orden === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <span class="grow"></span>
        <div class="segmented" role="group" aria-label="Vista (V)">${LIST_VIEWS.map(([k, l, ic]) => `<button type="button" data-lview="${k}" aria-pressed="${vista === k}" title="${l} (V)">${icon(ic, 'icon-sm')}<span class="hide-mobile">${l}</span><span class="sr-only show-mobile">${l}</span></button>`).join('')}</div>
      </div>
      <p class="sr-only" id="pjCount" role="status" aria-live="polite"></p>
      <div id="pjList"></div>`;
    $('pjSearch').value = L.q; $('pjFEstado').value = L.estado; $('pjFPrio').value = L.prioridad;
    $('pjSearch').addEventListener('input', (e) => { L.q = e.target.value; paintList(); });
    $('pjFEstado').addEventListener('change', (e) => { L.estado = e.target.value; paintList(); });
    $('pjFPrio').addEventListener('change', (e) => { L.prioridad = e.target.value; paintList(); });
    $('pjFTag').addEventListener('change', (e) => { L.etiqueta = e.target.value; paintList(); });
    $('pjSort').addEventListener('change', (e) => { setPref('proyectos.orden', e.target.value); paintList(); });
    root.querySelectorAll('[data-lview]').forEach((b) => b.addEventListener('click', () => setListView(b.dataset.lview)));
  }
  function setListView(v) {
    setPref('proyectos.vista', v);
    root.querySelectorAll('[data-lview]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lview === v)));
    paintList();
  }
  function paintTagFilter() {
    const sel = $('pjFTag');
    if (!sel) return;
    const tags = [...new Set(ALL.flatMap((p) => p.etiquetas || []))].sort((a, b) => a.localeCompare(b, 'es'));
    if (L.etiqueta && !tags.includes(L.etiqueta)) L.etiqueta = '';
    sel.innerHTML = `<option value="">Etiqueta</option>${tags.map((t) => `<option value="${esc(t)}" ${t === L.etiqueta ? 'selected' : ''}>#${esc(t)}</option>`).join('')}`;
    sel.hidden = !tags.length;
    sel.previousElementSibling.hidden = !tags.length;
  }

  function filtered() {
    const q = fold(L.q).trim();
    let list = ALL.filter((p) => (!L.estado || p.estado === L.estado)
      && (!L.prioridad || (L.prioridad === '-' ? !p.prioridad : p.prioridad === L.prioridad))
      && (!L.etiqueta || (p.etiquetas || []).includes(L.etiqueta))
      && (!q || fold(`${p.nombre} ${p.slug} ${p.descripcion || ''} ${(p.etiquetas || []).join(' ')}`).includes(q)));
    const by = {
      nombre: (a, b) => a.nombre.localeCompare(b.nombre, 'es', { sensitivity: 'base' }),
      progreso: (a, b) => b.progreso - a.progreso,
      fin: (a, b) => (a.fecha_fin || '9999').localeCompare(b.fecha_fin || '9999'),
      prioridad: (a, b) => (PRIO_RANK[a.prioridad] ?? 9) - (PRIO_RANK[b.prioridad] ?? 9),
      recientes: (a, b) => (b.created_at || 0) - (a.created_at || 0),
    }[pref('proyectos.orden', 'manual')];
    if (by) list = [...list].sort(by);
    return list;
  }

  function paintList() {
    const box = $('pjList');
    if (!box) return;
    const list = filtered();
    syncUrl();
    $('pjCount').textContent = `${list.length} de ${ALL.length} proyectos`;
    if (!list.length) {
      box.innerHTML = emptyState({ iconName: 'search', title: 'Nada coincide', text: 'Prueba con otra búsqueda o quita algún filtro.', actionLabel: 'Quitar filtros', action: 'clear', compact: true });
      box.querySelector('[data-empty-action=clear]')?.addEventListener('click', () => {
        Object.assign(L, { q: '', estado: '', prioridad: '', etiqueta: '' });
        $('pjSearch').value = ''; $('pjFEstado').value = ''; $('pjFPrio').value = ''; $('pjFTag').value = '';
        paintList();
      });
      return;
    }
    const vista = pref('proyectos.vista', 'tarjetas');
    if (vista === 'cronologia') {
      PjVistas.timeline(box, list.map((p) => ({
        id: p.id, label: p.nombre, sub: `${ESTADOS[p.estado]} · ${p.progreso} %`, color: color(p.color), done: p.estado === 'terminado',
        start: p.fecha_inicio || (p.created_at ? PjVistas.isoOf(new Date(p.created_at * 1000)) : null),
        end: p.fecha_fin || p.versiones.map((v) => v.fecha_objetivo).filter(Boolean).sort().pop() || null,
        href: `/proyectos/${encodeURIComponent(p.slug)}`,
      })), { pxPerDay: 5, label: 'Cronología de proyectos', empty: 'Pon fecha de inicio o de fin a un proyecto (Editar) para verlo aquí.' });
      return;
    }
    if (vista === 'tablero') {
      box.innerHTML = `<div class="pj-kanban pj-kanban-4">${Object.entries(ESTADOS).map(([e, l]) => {
        const items = list.filter((p) => p.estado === e);
        return `<section class="pj-col" aria-labelledby="pjb-${e}"><h2 class="pj-col-title" id="pjb-${e}">${l}<span class="count">${items.length}</span></h2>
          <ul class="pj-col-list" data-estado="${e}" data-empty="Suelta aquí" aria-label="${l}">${items.map((p) => card(p, true)).join('')}</ul></section>`;
      }).join('')}</div>
      <p class="tiny muted pj-hint">Arrastra un proyecto por su asa a otra columna para cambiar su estado (o con el teclado: Alt + flechas).</p>`;
      box.querySelectorAll('.pj-col-list').forEach((ul) => Sortable.create(ul, {
        group: 'pj-estados', items: '.pj-card', handle: '[data-drag-handle]', label: ul.getAttribute('aria-label'),
        id: (n) => Number(n.dataset.id), data: { estado: ul.dataset.estado },
        onDrop: async (ctx) => {
          const body = { before_id: ctx.beforeId ? Number(ctx.beforeId) : 0 };
          if (ctx.to.data.estado !== ctx.from.data.estado) body.estado = ctx.to.data.estado;
          try { await api(`/api/proyectos/${Number(ctx.id)}`, { method: 'PATCH', body }); } catch { /* api avisa */ }
          loadList();
        },
      }));
      return;
    }
    const groups = Object.keys(ESTADOS).map((e) => [e, list.filter((p) => p.estado === e)]).filter(([, l]) => l.length);
    box.innerHTML = groups.map(([e, l]) => `<section class="pj-section" aria-labelledby="pj-s-${e}"><h2 class="cat-header" id="pj-s-${e}">${ESTADOS[e]}<span class="count">${l.length}</span></h2>
      <ul class="pj-grid">${l.map((p) => card(p)).join('')}</ul></section>`).join('');
  }

  function card(p, draggable = false) {
    const v = p.version_actual;
    return `<li class="pj-card${draggable ? ' is-compact' : ''}" data-id="${p.id}" style="--pj:${color(p.color)}">
      ${draggable ? `<button type="button" class="drag-handle pj-card-handle" data-drag-handle aria-label="Mover «${esc(p.nombre)}»">${icon('grip-vertical', 'icon-sm')}</button>` : ''}
      <a class="pj-card-link" href="/proyectos/${encodeURIComponent(p.slug)}">
      <div class="pj-card-top"><span class="pj-mark" aria-hidden="true">${icon('rocket', 'icon-sm')}</span>
        <h3 class="pj-card-title">${esc(p.nombre)}</h3>${draggable ? '' : `<span class="tag pj-estado" data-estado="${p.estado}">${ESTADOS[p.estado]}</span>`}</div>
      ${p.descripcion && !draggable ? `<p class="pj-desc small">${esc(plain(p.descripcion))}</p>` : ''}
      ${p.prioridad || p.etiquetas?.length || p.fecha_inicio || p.fecha_fin ? `<div class="pj-card-meta tiny">${prioTag(p.prioridad)}${datesHtml(p, p.estado === 'terminado')}${tagsHtml(p.etiquetas)}</div>` : ''}
      <div class="pj-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${p.progreso}" aria-label="Progreso de ${esc(p.nombre)}"><span style="width:${p.progreso}%"></span></div>
      <div class="pj-card-meta tiny">
        <span>${icon('milestone', 'icon-sm')}${v ? `${esc(v.nombre)}${v.fecha_objetivo ? ` · ${fmtDay(v.fecha_objetivo, false)}` : ''}` : p.ultima_version ? esc(p.ultima_version.nombre) : 'Sin versión'}</span>
        <span class="tabular">${icon('list-todo', 'icon-sm')}${p.tareas_abiertas} abiertas</span>
        ${p.ideas ? `<span class="tabular">${icon('lightbulb', 'icon-sm')}${p.ideas}</span>` : ''}
        <span class="tabular">${p.progreso} %</span></div></a></li>`;
  }
  // Descripción en una línea para las tarjetas: sin marcas de Markdown
  const plain = (md) => String(md).replace(/^#+\s*/gm, '').replace(/[*_`>~]|\[( |x|X)\]|!?\[([^\]]*)\]\([^)]*\)/g, (m, c, t) => t ?? '').replace(/^\s*[-+]\s+/gm, '').replace(/\s+/g, ' ').trim();

  /* =====================================================================
     Un proyecto
     ===================================================================== */
  async function loadProject() {
    try { P = await api(`/api/proyectos/${encodeURIComponent(slug)}`, { quiet: true }); } catch {
      root.innerHTML = emptyState({ iconName: 'rocket', title: 'Proyecto no encontrado', text: 'Puede que se haya renombrado. Vuelve a la lista.' });
      return;
    }
    await Ctx.load().catch(() => {});
    $('pjHeading').textContent = P.nombre;
    document.title = `${P.nombre} · Panel`;
    $('pjBack').hidden = false;
    $('pjMenu').hidden = false;
    $('pjNew').hidden = true;
    renderProject();
  }

  function renderProject() {
    const v = P.version_actual;
    const long = (P.descripcion || '').length > 360 || (P.descripcion || '').split('\n').length > 6;
    root.innerHTML = `<header class="pj-head" style="--pj:${color(P.color)}">
        <div class="pj-head-main">
          <div class="pj-card-meta small">
            <span class="tag pj-estado" data-estado="${P.estado}">${ESTADOS[P.estado]}</span>
            ${prioTag(P.prioridad)}${datesHtml(P, P.estado === 'terminado')}
            <span>${icon('milestone', 'icon-sm')}${v ? `${esc(v.nombre)}${v.titulo ? ` · ${esc(v.titulo)}` : ''} · ${v.hechas}/${v.total}` : 'Sin versión abierta'}</span>
            <span class="tabular">${icon('list-todo', 'icon-sm')}${P.tareas_abiertas} abiertas · ${P.tareas_hechas} hechas</span>
            <span class="ctx-chip" translate="no"><span class="ctx-dot" style="background:${color(P.color)}"></span>#${esc(P.slug)}</span>
            ${tagsHtml(P.etiquetas)}
          </div>
          <div class="pj-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${P.progreso}" aria-label="Progreso"><span style="width:${P.progreso}%"></span></div>
          ${P.descripcion ? `<div class="md pj-head-desc${long ? ' is-clamped' : ''}" id="pjDesc">${renderMd(P.descripcion)}</div>
            ${long ? '<button type="button" class="btn btn-ghost btn-sm pj-more" data-more aria-controls="pjDesc" aria-expanded="false">Ver toda la descripción</button>' : ''}`
            : `<p class="small muted">Sin descripción. <button type="button" class="link-btn" data-edit-proj>Escribe de qué va</button> (admite Markdown).</p>`}
        </div>
        ${P.carpeta ? `<div class="pj-head-actions"><button type="button" class="btn btn-tinted btn-sm" data-open-folder>${icon('folder-open', 'icon-sm')}<span class="hide-mobile">Abrir carpeta</span><span class="sr-only show-mobile">Abrir la carpeta</span></button></div>` : ''}
      </header>
      <div class="segmented pj-tabs" role="tablist" aria-label="Partes del proyecto">${TABS.map(([k, l, ic], i) => `<button type="button" role="tab" id="pjtab-${k}" data-tab="${k}" aria-selected="${k === tab}" aria-controls="pjBody" tabindex="${k === tab ? 0 : -1}" title="${l} (${i + 1})">${icon(ic, 'icon-sm')}${l}</button>`).join('')}</div>
      <div id="pjBody" class="pj-body" role="tabpanel" aria-labelledby="pjtab-${tab}"></div>`;
    root.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => setTab(b.dataset.tab)));
    root.querySelector('.pj-tabs').addEventListener('keydown', (e) => {  // flechas entre pestañas
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const i = TABS.findIndex(([k]) => k === tab), n = (i + (e.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length;
      setTab(TABS[n][0]);
      root.querySelector(`[data-tab="${TABS[n][0]}"]`)?.focus();
    });
    root.querySelector('[data-more]')?.addEventListener('click', (e) => {
      const d = $('pjDesc'), open = d.classList.toggle('is-clamped');
      e.currentTarget.setAttribute('aria-expanded', String(!open));
      e.currentTarget.textContent = open ? 'Ver toda la descripción' : 'Ver menos';
    });
    root.querySelector('[data-edit-proj]')?.addEventListener('click', () => projectDialog(P));
    root.querySelector('[data-open-folder]')?.addEventListener('click', () => Ctx.openFolder('proyecto', P.id));
    ({ tareas: renderTareas, versiones: renderVersiones, cambios: renderCambios, ideas: renderIdeas, esquemas: renderEsquemas, bitacora: renderBitacora, enlaces: renderEnlaces }[tab] || renderTareas)($('pjBody'));
  }
  function setTab(k) {
    if (!TABS.some(([x]) => x === k)) return;
    tab = k;
    renderProject();
    syncUrl();
  }

  /* Captura dentro del proyecto: lo nuevo va a él (y a la versión abierta si se elige) */
  function captureHTML(type) {
    const vers = P.versiones.filter((v) => v.estado === 'abierta');
    return `<form class="capture-panel pj-capture" data-pj-capture="${type}" autocomplete="off">
      <label class="sr-only" for="pjCap-${type}">${type === 'idea' ? 'Nueva idea' : 'Nueva tarea'} de ${esc(P.nombre)}</label>
      <input id="pjCap-${type}" class="input" maxlength="2000" placeholder="${type === 'idea' ? 'Nueva idea…' : 'Nueva tarea (p. ej. «arreglar login viernes»)…'}" aria-keyshortcuts="N">
      ${type === 'tarea' && vers.length ? `<label class="sr-only" for="pjCapV">Versión</label><select id="pjCapV" class="select input-sm"><option value="">Sin versión</option>${vers.map((v, i) => `<option value="${v.id}" ${i === 0 ? 'selected' : ''}>${esc(v.nombre)}</option>`).join('')}</select>` : ''}
      <button type="submit" class="btn btn-primary">Guardar</button></form>`;
  }
  function wireCapture(box) {
    box.querySelector('[data-pj-capture]')?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = e.currentTarget, input = f.querySelector('input');
      const text = input.value.trim();
      if (!text) return;
      const type = f.dataset.pjCapture;
      const version = Number(f.querySelector('select')?.value) || null;
      if (/\s(hoy|mañana|lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo|\d{1,2}[/-]\d{1,2})\b/i.test(text)) {
        await Items.capture(`${type === 'idea' ? 'i' : 't'}: ${text}`, type, { proyecto_id: P.id });  // con fecha: la interpreta el servidor
        if (version) { await Items.load(); const it = Items.state.items.filter((i) => i.proyecto_id === P.id).sort((a, b) => b.id - a.id)[0]; if (it) await Items.update(it.id, { version_id: version }); }
      } else {
        await Items.create({ text, type, proyecto_id: P.id, ...(version ? { version_id: version } : {}) });
      }
      input.value = '';
      refresh();
    });
  }
  const refresh = () => api(`/api/proyectos/${encodeURIComponent(slug)}`, { quiet: true }).then((p) => { P = p; }).catch(() => {});

  /* ---------- Tareas: tablero / lista / cronología, con búsqueda y filtros ---------- */
  function renderTareas(box) {
    const mode = pref(VIEW_KEY, 'versiones'), group = pref('proyecto.agrupar', 'estado');
    const vers = P.versiones;
    box.innerHTML = `<div class="row pj-toolbar">${captureHTML('tarea')}</div>
      <div class="pj-filters pj-filters-tasks" role="search" aria-label="Buscar y filtrar tareas">
        <div class="pj-search">${icon('search', 'icon-sm')}<label class="sr-only" for="pjTq">Buscar tareas</label>
          <input id="pjTq" class="input" type="search" placeholder="Buscar tareas…" autocomplete="off" value="${esc(T.q)}" aria-keyshortcuts="/"><kbd class="pj-kbd hide-mobile" aria-hidden="true">/</kbd></div>
        <label class="sr-only" for="pjTPrio">Prioridad</label><select id="pjTPrio" class="select input-sm"><option value="">Prioridad</option>${Object.entries(PRIOS).map(([k, l]) => `<option value="${k}" ${T.prio === k ? 'selected' : ''}>${l}</option>`).join('')}<option value="-" ${T.prio === '-' ? 'selected' : ''}>Sin prioridad</option></select>
        ${vers.length ? `<label class="sr-only" for="pjTVer">Versión</label><select id="pjTVer" class="select input-sm"><option value="">Versión</option>${vers.map((v) => `<option value="${v.id}" ${String(T.version) === String(v.id) ? 'selected' : ''}>${esc(v.nombre)}</option>`).join('')}<option value="-" ${T.version === '-' ? 'selected' : ''}>Sin versión</option></select>` : ''}
        ${mode === 'columnas' ? `<label class="pj-group"><span class="small muted">Agrupar por</span><select id="pjTGroup" class="select input-sm">${GROUPS.map(([k, l]) => `<option value="${k}" ${group === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>` : ''}
        <span class="grow"></span>
        <div class="segmented" role="group" aria-label="Vista (V)">${TASK_VIEWS.map(([k, l, ic]) => `<button type="button" data-mode="${k}" aria-pressed="${mode === k}" title="${l} (V)">${icon(ic, 'icon-sm')}<span class="hide-mobile">${l}</span><span class="sr-only show-mobile">${l}</span></button>`).join('')}</div>
      </div>
      <p class="sr-only" id="pjTCount" role="status" aria-live="polite"></p>
      <div id="pjTasks"></div>`;
    wireCapture(box);
    $('pjTq').addEventListener('input', (e) => { T.q = e.target.value; paintTasks(); });
    $('pjTPrio').addEventListener('change', (e) => { T.prio = e.target.value; paintTasks(); });
    $('pjTVer')?.addEventListener('change', (e) => { T.version = e.target.value; paintTasks(); });
    $('pjTGroup')?.addEventListener('change', (e) => { setPref('proyecto.agrupar', e.target.value); paintTasks(); });
    box.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => { setPref(VIEW_KEY, b.dataset.mode); renderTareas(box); }));
    Items.ready().then(paintTasks).catch(() => {});
  }

  const mineAll = () => Items.state.items.filter((i) => i.proyecto_id === P.id && !i.parent_id && i.type === 'tarea');
  function mineFiltered() {
    const q = fold(T.q).trim();
    return mineAll().filter((i) => (!T.prio || (T.prio === '-' ? !i.priority : i.priority === T.prio))
      && (!T.version || (T.version === '-' ? !i.version_id : String(i.version_id) === String(T.version)))
      && (!q || fold(`${i.text} ${i.details || ''} ${Items.children(i.id).map((k) => k.text).join(' ')}`).includes(q)));
  }
  const extrasOf = (id) => P.extras?.[String(id)] || { comentarios: 0, adjuntos: 0 };
  const vname = (id) => P.versiones.find((v) => v.id === id)?.nombre;

  function paintTasks() {
    const el = $('pjTasks');
    if (!el || !P) return;
    const all = mineAll(), list = mineFiltered();
    syncUrl();
    const count = $('pjTCount');
    if (count) count.textContent = list.length === all.length ? `${all.length} tareas` : `${list.length} de ${all.length} tareas`;
    const mode = pref(VIEW_KEY, 'versiones');
    if (mode === 'lista') taskTable(el, list);
    else if (mode === 'cronologia') taskTimeline(el, list);
    else if (mode === 'columnas') kanban(el, list);
    else byVersion(el, list);
    if (all.length && !list.length) {
      el.insertAdjacentHTML('afterbegin', `<p class="pj-filter-note small">${icon('list-filter', 'icon-sm')}Ninguna de las ${all.length} tareas coincide con la búsqueda o los filtros. <button type="button" class="link-btn" data-clear-filters>Quitar filtros</button></p>`);
      el.querySelector('[data-clear-filters]').addEventListener('click', () => { Object.assign(T, { q: '', prio: '', version: '' }); renderTareas($('pjBody')); });
    }
  }

  function taskMeta(it, group) {
    const kids = Items.children(it.id), checks = PjFicha.checklist(it.details), ex = extrasOf(it.id);
    const late = it.due_date && !it.done && it.due_date < todayIso();
    return `${group !== 'prioridad' ? prioTag(it.priority) : ''}
      ${it.due_date ? `<span class="${late ? 'is-late' : ''}">${icon('calendar', 'icon-sm')}${fmtDay(it.due_date, false)}</span>` : ''}
      ${it.version_id && group !== 'version' ? `<span class="tag">${icon('milestone', 'icon-sm')}${esc(vname(it.version_id) || '')}</span>` : ''}
      ${it.en_curso && !it.done && group !== 'estado' ? `<span class="tag pj-doing">En curso</span>` : ''}
      ${kids.length ? `<span class="tabular" title="Subtareas">${icon('list-todo', 'icon-sm')}${kids.filter((x) => x.done).length}/${kids.length}</span>` : ''}
      ${checks.length ? `<span class="tabular" title="Checklist">${icon('list-checks', 'icon-sm')}${checks.filter((c) => c.hecha).length}/${checks.length}</span>` : ''}
      ${ex.comentarios ? `<span class="tabular" title="Comentarios">${icon('message-square', 'icon-sm')}${ex.comentarios}</span>` : ''}
      ${ex.adjuntos ? `<span class="tabular" title="Adjuntos">${icon('paperclip', 'icon-sm')}${ex.adjuntos}</span>` : ''}`;
  }

  function columnsFor(group, list) {
    if (group === 'version') {
      const vs = P.versiones.filter((v) => v.estado === 'abierta' || list.some((i) => i.version_id === v.id));
      return [['0', 'Sin versión', list.filter((i) => !i.version_id || !vs.some((v) => v.id === i.version_id))],
        ...vs.map((v) => [String(v.id), `${v.nombre}${v.titulo ? ` · ${v.titulo}` : ''}${v.estado === 'cerrada' ? ' (cerrada)' : ''}`, list.filter((i) => i.version_id === v.id)])];
    }
    if (group === 'prioridad') {
      return [['alta', 'Alta', list.filter((i) => i.priority === 'alta')], ['media', 'Media', list.filter((i) => i.priority === 'media')],
        ['baja', 'Baja', list.filter((i) => i.priority === 'baja')], ['', 'Sin prioridad', list.filter((i) => !PRIOS[i.priority])]];
    }
    return [['todo', 'Por hacer', list.filter((i) => !i.done && !i.en_curso)], ['doing', 'En curso', list.filter((i) => !i.done && i.en_curso)],
      ['done', 'Hecho', list.filter((i) => i.done)]];
  }

  function kanban(el, list) {
    const group = pref('proyecto.agrupar', 'estado');
    const cols = columnsFor(group, list);
    el.innerHTML = `<div class="pj-kanban" style="--cols:${cols.length}">${cols.map(([k, l, items]) => `<section class="pj-col" data-col="${esc(k)}" aria-labelledby="pjc-${esc(k) || 'none'}">
      <h3 class="pj-col-title" id="pjc-${esc(k) || 'none'}">${esc(l)}<span class="count">${items.length}</span>${group === 'estado' && k === 'done' && items.length ? `<span class="grow"></span><button type="button" class="btn btn-ghost btn-sm" data-clear-done title="Las cerradas siguen en el registro de su versión">${icon('trash-2', 'icon-sm')}Borrar</button>` : ''}</h3>
      <ul class="pj-col-list" data-col="${esc(k)}" data-empty="Suelta aquí" aria-label="${esc(l)}">${withVersionSeps(items, group).map((x) => (x.sep !== undefined ? `<li class="pj-vsep" aria-hidden="true">${icon('milestone', 'icon-sm')}${esc(x.sep)}</li>` : `<li class="pj-task${x.done ? ' is-done' : ''}" data-id="${x.id}">
          <button type="button" class="drag-handle" data-drag-handle aria-label="Mover «${esc(x.text.slice(0, 40))}»">${icon('grip-vertical', 'icon-sm')}</button>
          <div class="pj-task-body"><div class="pj-task-line">${foldBtn(x)}<button type="button" class="pj-task-title" data-open="${x.id}" aria-haspopup="dialog" title="Detalles: descripción, checklist, adjuntos y comentarios">${esc(x.text.split('\n')[0])}</button></div>
            <div class="pj-task-meta tiny">${taskMeta(x, group)}</div>${subsHTML(x)}</div>
          <input type="checkbox" class="checkbox pj-task-check" data-done="${x.id}" ${x.done ? 'checked' : ''} aria-label="Hecha: ${esc(x.text.split('\n')[0].slice(0, 60))}"></li>`)).join('')}</ul></section>`).join('')}</div>
      <p class="tiny muted pj-hint">Arrastra por el asa entre columnas para cambiar ${group === 'version' ? 'la versión' : group === 'prioridad' ? 'la prioridad' : 'el estado'} (o con el teclado: Alt + flechas). Las subtareas se marcan aquí mismo; clic en el título abre los detalles.</p>`;
    wireOpen(el);
    wireSubs(el);
    el.querySelector('[data-clear-done]')?.addEventListener('click', async () => {
      const ids = cols[2][2].map((i) => i.id);
      if (!(await uiConfirm(`¿Borrar ${ids.length} tareas hechas?`, 'Van a la papelera (30 días) y puedes deshacerlo ahora. Los registros de cambios de las versiones no cambian.', { confirmLabel: 'Borrar', danger: true }))) return;
      await Items.remove(ids, { label: `${ids.length} tareas hechas borradas` });
      await refresh();
      paintTasks();
    });
    el.querySelectorAll('.pj-col-list').forEach((ul) => Sortable.create(ul, {
      group: 'pj-kanban', items: '.pj-task', handle: '[data-drag-handle]', label: ul.getAttribute('aria-label'),
      id: (n) => Number(n.dataset.id), data: { col: ul.dataset.col },
      onDrop: async (ctx) => {
        const id = Number(ctx.id), to = ctx.to.data.col, moved = to !== ctx.from.data.col;
        if (Items.get(id)?.origin === 'inbox' && (ctx.beforeId || !moved)) await Items.move(id, { target: 'inbox', parent_id: null, before_id: ctx.beforeId ? Number(ctx.beforeId) : null }).catch(() => {});
        if (moved) {
          const patch = group === 'version' ? { version_id: Number(to) || 0 } : group === 'prioridad' ? { priority: to } : to === 'done' ? { done: true } : { done: false, en_curso: to === 'doing' };
          await Items.update(id, patch).catch(() => {});
        }
        await refresh();
        paintTasks();
      },
    }));
  }
  /* ---------- Subtareas a la vista (plegables, guardado en preferencias) ---------- */
  const foldMap = () => { const m = pref(FOLD_TASKS, {}); return m && typeof m === 'object' && !Array.isArray(m) ? m : {}; };
  const isOpen = (it) => foldMap()[it.id] ?? !it.done;
  const setOpen = (id, open) => setPref(FOLD_TASKS, { ...foldMap(), [id]: open });
  let addingSub = null;  // tarea con el campo de «nueva subtarea» abierto: sobrevive al repintado
  function foldBtn(it) {
    const kids = Items.children(it.id);
    if (!kids.length) return '';
    const open = isOpen(it);
    return `<button type="button" class="btn btn-ghost btn-icon btn-sm pj-fold" data-fold-task="${it.id}" aria-expanded="${open}" aria-controls="pjs-${it.id}" aria-label="${open ? 'Plegar' : 'Desplegar'} las subtareas de «${esc(it.text.split('\n')[0].slice(0, 40))}»">${icon('chevron-down', 'icon-sm')}</button>`;
  }
  function subsHTML(it) {
    const kids = Items.children(it.id);
    const open = isOpen(it) || addingSub === it.id;
    const adding = addingSub === it.id;
    return `${kids.length ? `<ul class="pj-subs" id="pjs-${it.id}" ${open ? '' : 'hidden'} aria-label="Subtareas de «${esc(it.text.split('\n')[0].slice(0, 60))}»">${kids.map((k) => `<li class="pj-sub${k.done ? ' is-done' : ''}">
        <input type="checkbox" class="checkbox" data-sub-done="${k.id}" ${k.done ? 'checked' : ''} aria-label="Hecha: ${esc(k.text.split('\n')[0])}">
        <button type="button" class="pj-sub-text" data-sub-edit="${k.id}" title="Cambiar el texto">${esc(k.text.split('\n')[0])}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm pj-sub-x" data-sub-del="${k.id}" aria-label="Borrar la subtarea «${esc(k.text.slice(0, 40))}»">${icon('x', 'icon-sm')}</button></li>`).join('')}</ul>` : ''}
      <form class="pj-sub-add" data-sub-add="${it.id}" autocomplete="off" ${adding ? '' : 'hidden'}><label class="sr-only" for="pjsa-${it.id}">Nueva subtarea de «${esc(it.text.split('\n')[0].slice(0, 60))}»</label>
        <input id="pjsa-${it.id}" class="input input-sm" maxlength="2000" placeholder="Nueva subtarea… (Enter para añadir, Esc para cerrar)"></form>`;
  }
  function wireSubs(el) {
    el.querySelectorAll('[data-fold-task]').forEach((b) => b.addEventListener('click', () => {
      const id = Number(b.dataset.foldTask), open = b.getAttribute('aria-expanded') !== 'true';
      setOpen(id, open);
      b.setAttribute('aria-expanded', String(open));
      b.setAttribute('aria-label', b.getAttribute('aria-label').replace(open ? 'Desplegar' : 'Plegar', open ? 'Plegar' : 'Desplegar'));
      const ul = $(`pjs-${id}`);
      if (ul) ul.hidden = !open;
    }));
    el.querySelectorAll('[data-sub-done]').forEach((cb) => cb.addEventListener('change', () => Items.setDone(Number(cb.dataset.subDone), cb.checked).then(refresh)));
    el.querySelectorAll('[data-sub-del]').forEach((b) => b.addEventListener('click', () => Items.remove(Number(b.dataset.subDel), { label: 'Subtarea borrada' })));
    el.querySelectorAll('[data-sub-edit]').forEach((sp) => sp.addEventListener('click', async () => {
      const k = Items.get(Number(sp.dataset.subEdit));
      if (!k) return;
      const v = await uiPrompt('Subtarea', { value: k.text.split('\n')[0], confirmLabel: 'Guardar' });
      if (v?.trim() && v.trim() !== k.text.split('\n')[0]) Items.update(k.id, { text: v.trim() }).catch(() => {});
    }));
    el.querySelectorAll('[data-add-sub]').forEach((b) => b.addEventListener('click', () => {
      const id = Number(b.dataset.addSub);
      addingSub = id;
      if (Items.get(id) && !isOpen(Items.get(id))) setOpen(id, true);
      $(`pjs-${id}`)?.removeAttribute('hidden');
      const f = el.querySelector(`[data-sub-add="${id}"]`);
      f.hidden = false;
      f.querySelector('input').focus();
    }));
    el.querySelectorAll('[data-sub-add]').forEach((f) => {
      const id = Number(f.dataset.subAdd), input = f.querySelector('input');
      if (addingSub === id) requestAnimationFrame(() => input.focus());
      input.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.preventDefault(); addingSub = null; f.hidden = true; el.querySelector(`[data-add-sub="${id}"]`)?.focus(); } });
      input.addEventListener('blur', () => setTimeout(() => { if (input.isConnected && addingSub === id && !input.value.trim() && !f.contains(document.activeElement)) { addingSub = null; f.hidden = true; } }, 150));
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const t = input.value.trim();
        if (!t) return;
        input.value = '';
        addingSub = id;
        try { await Items.create({ text: t, type: Items.get(id)?.type || 'tarea', parent_id: id }); } catch { input.value = t; }
      });
    });
  }
  // Dentro de una columna del tablero (por estado o prioridad), las tareas van por versión con un separador
  function withVersionSeps(items, group) {
    if (group === 'version' || !P.versiones.length) return items;
    const rank = (i) => { const n = P.versiones.findIndex((v) => v.id === i.version_id); return n < 0 ? 1e6 : n; };
    const sorted = items.map((x, i) => [x, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([x]) => x);
    const out = [];
    let last;
    for (const it of sorted) {
      const r = rank(it);
      if (r !== last) { out.push({ sep: r === 1e6 ? 'Sin versión' : P.versiones[r].nombre }); last = r; }
      out.push(it);
    }
    return out;
  }

  /* ---------- Por versión: una sección por versión, con hueco entre ellas ---------- */
  function byVersion(el, list) {
    const folds = pref(FOLD_VERS, {}) || {};
    const abiertas = P.versiones.filter((v) => v.estado !== 'cerrada');
    const cerradas = P.versiones.filter((v) => v.estado === 'cerrada').reverse();
    const known = new Set(P.versiones.map((v) => v.id));
    const sections = [
      ...abiertas.map((v) => ({ key: `v${v.id}`, v, items: list.filter((i) => i.version_id === v.id) })),
      { key: 'none', v: null, items: list.filter((i) => !i.version_id || !known.has(i.version_id)) },
      ...cerradas.map((v) => ({ key: `v${v.id}`, v, items: list.filter((i) => i.version_id === v.id) })),
    ].filter((s) => s.v || s.items.length || !P.versiones.length);
    const ordered = (items) => [...items.filter((i) => !i.done && i.en_curso), ...items.filter((i) => !i.done && !i.en_curso), ...items.filter((i) => i.done)];
    el.innerHTML = `<div class="pj-vlist">${sections.map(({ key, v, items }) => {
      const open = folds[key] ?? !(v && v.estado === 'cerrada');
      const hechas = items.filter((i) => i.done).length;
      const pct = items.length ? Math.round((100 * hechas) / items.length) : 0;
      const late = v?.fecha_objetivo && v.estado !== 'cerrada' && v.fecha_objetivo < todayIso() && hechas < items.length;
      return `<section class="pj-vsec${v?.estado === 'cerrada' ? ' is-closed' : ''}${v ? '' : ' is-none'}" data-vkey="${key}" aria-labelledby="pjvh-${key}">
        <header class="pj-vsec-head">
          <button type="button" class="pj-vsec-toggle" id="pjvh-${key}" data-fold-v="${key}" aria-expanded="${open}" aria-controls="pjvb-${key}">${icon('chevron-down', 'icon-sm chev')}
            <span class="pj-vsec-name">${v ? esc(v.nombre) : 'Sin versión'}</span>${v?.titulo ? `<span class="pj-vsec-title">${esc(v.titulo)}</span>` : ''}</button>
          ${v?.estado === 'cerrada' ? `<span class="tag">${icon('circle-check', 'icon-sm')}Cerrada</span>` : ''}
          ${v?.fecha_objetivo ? `<span class="small ${late ? 'is-late' : 'muted'}">${icon('calendar', 'icon-sm')}${fmtDay(v.fecha_objetivo)}</span>` : ''}
          <span class="grow"></span>
          <span class="small tabular muted">${hechas}/${items.length}</span>
          <span class="pj-progress pj-vsec-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}" aria-label="Progreso de ${v ? esc(v.nombre) : 'las tareas sin versión'}"><span style="width:${pct}%"></span></span>
        </header>
        <div class="pj-vsec-body" id="pjvb-${key}" ${open ? '' : 'hidden'}>
          <ul class="pj-vtasks-list" data-version="${v ? v.id : 0}" data-empty="Sin tareas: arrastra aquí una o créala arriba eligiendo ${v ? esc(v.nombre) : '«Sin versión»'}" aria-label="Tareas de ${v ? esc(v.nombre) : 'sin versión'}">${ordered(items).map((it) => `<li class="pj-vtask${it.done ? ' is-done' : ''}${it.en_curso && !it.done ? ' is-doing' : ''}" data-id="${it.id}">
            <div class="pj-vtask-row">
              <button type="button" class="drag-handle" data-drag-handle aria-label="Mover «${esc(it.text.slice(0, 40))}»">${icon('grip-vertical', 'icon-sm')}</button>
              <input type="checkbox" class="checkbox" data-done="${it.id}" ${it.done ? 'checked' : ''} aria-label="Hecha: ${esc(it.text.split('\n')[0].slice(0, 60))}">
              ${foldBtn(it) || '<span class="pj-fold-gap" aria-hidden="true"></span>'}
              <button type="button" class="pj-task-title" data-open="${it.id}" aria-haspopup="dialog" title="Detalles: descripción, checklist, adjuntos y comentarios">${esc(it.text.split('\n')[0])}</button>
              <span class="pj-task-meta tiny">${taskMeta(it, 'version')}</span>
              <button type="button" class="btn btn-ghost btn-icon btn-sm pj-add-sub" data-add-sub="${it.id}" aria-label="Añadir una subtarea a «${esc(it.text.split('\n')[0].slice(0, 40))}»" title="Añadir subtarea">${icon('list-plus', 'icon-sm')}</button>
            </div>${subsHTML(it)}</li>`).join('')}</ul>
        </div></section>`;
    }).join('')}</div>
    <p class="tiny muted pj-hint">Arrastra una tarea por el asa a otra versión para cambiarla (o con el teclado: Alt + flechas). Las subtareas se ven y se marcan aquí; ${icon('list-plus', 'icon-sm')} añade una. Clic en el título abre los detalles.</p>`;
    wireOpen(el);
    wireSubs(el);
    el.querySelectorAll('[data-fold-v]').forEach((b) => b.addEventListener('click', () => {
      const open = b.getAttribute('aria-expanded') !== 'true';
      setPref(FOLD_VERS, { ...(pref(FOLD_VERS, {}) || {}), [b.dataset.foldV]: open });
      b.setAttribute('aria-expanded', String(open));
      $(b.getAttribute('aria-controls')).hidden = !open;
    }));
    el.querySelectorAll('.pj-vtasks-list').forEach((ul) => Sortable.create(ul, {
      group: 'pj-versiones', items: '.pj-vtask', handle: '[data-drag-handle]', label: ul.getAttribute('aria-label'),
      id: (n) => Number(n.dataset.id), data: { version: Number(ul.dataset.version) },
      onDrop: async (ctx) => {
        const id = Number(ctx.id), to = ctx.to.data.version, moved = to !== ctx.from.data.version;
        if (Items.get(id)?.origin === 'inbox') await Items.move(id, { target: 'inbox', parent_id: null, before_id: ctx.beforeId ? Number(ctx.beforeId) : null }).catch(() => {});
        if (moved) await Items.update(id, { version_id: to || 0 }).catch(() => {});
        await refresh();
        paintTasks();
      },
    }));
  }

  function wireOpen(el) {
    el.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => openFicha(Number(b.dataset.open))));
    el.querySelectorAll('[data-done]').forEach((cb) => cb.addEventListener('change', () => Items.setDone(Number(cb.dataset.done), cb.checked).then(refresh)));
  }
  function openFicha(id) {
    PjFicha.open(id, {
      proyecto: P,
      onExtras: (itemId, n) => { P.extras = { ...(P.extras || {}), [String(itemId)]: n }; },
      onChange: () => refresh().then(() => { if (tab === 'tareas') paintTasks(); }),
    });
  }

  function taskTable(el, list) {
    const sort = pref('proyecto.orden-tareas', { key: 'estado', dir: 1 });
    const est = (i) => (i.done ? 2 : i.en_curso ? 0 : 1);
    const ESTL = ['En curso', 'Por hacer', 'Hecha'];
    PjVistas.table(el, list, {
      caption: `Tareas de ${P.nombre}`,
      sort,
      onOpen: openFicha,
      onSort: (s) => { setPref('proyecto.orden-tareas', s); paintTasks(); },
      columns: [
        { key: 'check', label: '<span class="sr-only">Hecha</span>', cls: 'pjt-check', render: (i) => `<input type="checkbox" class="checkbox" data-done="${i.id}" ${i.done ? 'checked' : ''} aria-label="Hecha: ${esc(i.text.split('\n')[0].slice(0, 60))}">` },
        { key: 'titulo', label: 'Tarea', sortable: true, cls: 'pjt-title', value: (i) => i.text, render: (i) => `<button type="button" class="pjt-open" data-open="${i.id}" aria-haspopup="dialog">${esc(i.text.split('\n')[0])}</button>` },
        { key: 'estado', label: 'Estado', sortable: true, value: est, render: (i) => `<span class="tag${i.en_curso && !i.done ? ' pj-doing' : ''}">${ESTL[est(i)]}</span>` },
        { key: 'prioridad', label: 'Prioridad', sortable: true, value: (i) => PRIO_RANK[i.priority] ?? null, render: (i) => prioTag(i.priority) || '<span class="muted">—</span>' },
        { key: 'fecha', label: 'Fecha', sortable: true, cls: 'tabular', value: (i) => i.due_date || null, render: (i) => (i.due_date ? `<span class="${!i.done && i.due_date < todayIso() ? 'is-late' : ''}">${fmtDay(i.due_date, false)}</span>` : '<span class="muted">—</span>') },
        { key: 'version', label: 'Versión', sortable: true, cls: 'hide-mobile', value: (i) => vname(i.version_id) || null, render: (i) => esc(vname(i.version_id) || '—') },
        { key: 'avance', label: 'Avance', sortable: true, cls: 'tabular hide-mobile', value: (i) => { const k = Items.children(i.id), c = PjFicha.checklist(i.details), t = k.length + c.length; return t ? (k.filter((x) => x.done).length + c.filter((x) => x.hecha).length) / t : null; },
          render: (i) => { const k = Items.children(i.id), c = PjFicha.checklist(i.details), t = k.length + c.length; return t ? `${k.filter((x) => x.done).length + c.filter((x) => x.hecha).length}/${t}` : '<span class="muted">—</span>'; } },
        { key: 'extras', label: '<span class="sr-only">Comentarios y adjuntos</span>', cls: 'tabular pjt-extras hide-mobile', render: (i) => { const ex = extrasOf(i.id); return `${ex.comentarios ? `<span title="Comentarios">${icon('message-square', 'icon-sm')}${ex.comentarios}</span>` : ''}${ex.adjuntos ? `<span title="Adjuntos">${icon('paperclip', 'icon-sm')}${ex.adjuntos}</span>` : ''}`; } },
      ],
    });
    if (!list.length && !mineAll().length) el.insertAdjacentHTML('beforeend', '<p class="small muted pj-hint">Aún no hay tareas: escribe la primera arriba.</p>');
    el.querySelectorAll('[data-done]').forEach((cb) => cb.addEventListener('change', () => Items.setDone(Number(cb.dataset.done), cb.checked).then(refresh)));
  }

  function taskTimeline(el, list) {
    PjVistas.timeline(el, list.map((i) => {
      const created = i.created_at ? PjVistas.isoOf(new Date(i.created_at * 1000)) : null;
      return { id: i.id, label: i.text.split('\n')[0], done: i.done, color: i.done ? 'var(--text-3)' : color(P.color),
        start: i.due_date && created && created < i.due_date ? created : i.due_date, end: i.due_date,
        sub: vname(i.version_id) || '' };
    }), { markers: P.versiones.filter((v) => v.fecha_objetivo).map((v) => ({ date: v.fecha_objetivo, label: v.nombre })), pxPerDay: 22,
      onOpen: openFicha, label: `Cronología de ${P.nombre}`, empty: 'Las tareas con fecha salen aquí, desde que se crearon hasta su fecha; las versiones con fecha objetivo, como hitos.' });
  }

  document.addEventListener('items:changed', () => { if (P && tab === 'tareas' && $('pjTasks') && !document.querySelector('.is-dragging')) paintTasks(); });

  function renderIdeas(box) {
    box.innerHTML = `${captureHTML('idea')}<div id="pjIdeas"></div>`;
    wireCapture(box);
    ItemList.mount($('pjIdeas'), { variant: 'page', filters: { contexto: 'proyectos', proyecto: P.id, type: 'idea' } });
  }

  /* ---------- Versiones: crear, asignar tareas, progreso y cerrar con registro de cambios ---------- */
  function renderVersiones(box) {
    const vs = [...P.versiones].reverse();
    box.innerHTML = `<div class="row pj-toolbar"><button type="button" class="btn btn-tinted btn-sm" data-new-version>${icon('plus', 'icon-sm')}Versión</button>
      <span class="tiny muted">Cada versión es un hito: título, descripción y fecha objetivo. Al cerrarla, sus tareas hechas forman el registro de cambios.</span></div>
      ${vs.length ? `<ul class="pj-versions">${vs.map((v) => `<li class="pj-version${v.estado === 'cerrada' ? ' is-closed' : ''}" data-v="${v.id}">
        <div class="pj-version-head"><h3>${esc(v.nombre)}${v.titulo ? ` <span class="pj-version-title">· ${esc(v.titulo)}</span>` : ''}</h3>
          <span class="tag">${v.estado === 'cerrada' ? `${icon('circle-check', 'icon-sm')}Cerrada` : 'Abierta'}</span>
          ${v.fecha_objetivo ? `<span class="small muted">${icon('calendar', 'icon-sm')}${fmtDay(v.fecha_objetivo)}</span>` : ''}
          <span class="grow"></span><span class="small tabular">${v.hechas}/${v.total} · ${v.progreso} %</span>
          ${v.estado === 'abierta' ? `<button type="button" class="btn btn-sm" data-assign>${icon('list-plus', 'icon-sm')}<span class="hide-mobile">Asignar tareas</span></button>
            <button type="button" class="btn btn-tinted btn-sm" data-close-v>${icon('circle-check', 'icon-sm')}Cerrar</button>` : `<button type="button" class="btn btn-ghost btn-sm" data-edit-log>${icon('pencil', 'icon-sm')}Editar registro</button>`}
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-v-menu aria-label="Más acciones de ${esc(v.nombre)}" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button></div>
        <div class="pj-progress"><span style="width:${v.progreso}%"></span></div>
        ${v.descripcion ? `<div class="md pj-version-desc">${renderMd(v.descripcion)}</div>` : ''}
        ${v.changelog ? `<div class="md pj-log">${renderMd(v.changelog)}</div>` : ''}
        ${v.estado === 'abierta' ? `<ul class="pj-vtasks">${Items.state.items.filter((i) => i.version_id === v.id && !i.parent_id).map((i) => `<li class="${i.done ? 'is-done' : ''}">${icon(i.done ? 'circle-check' : 'circle', 'icon-sm')}${esc(i.text.split('\n')[0])}</li>`).join('')}</ul>` : ''}
      </li>`).join('')}</ul>` : emptyState({ iconName: 'milestone', title: 'Sin versiones', text: 'Crea la primera (v0.1) con un título, una fecha objetivo y lo que quieres conseguir.', compact: true })}`;
    box.querySelector('[data-new-version]').addEventListener('click', newVersion);
    box.querySelectorAll('[data-v]').forEach((li) => {
      const v = P.versiones.find((x) => x.id === Number(li.dataset.v));
      li.querySelector('[data-assign]')?.addEventListener('click', () => assignTasks(v));
      li.querySelector('[data-close-v]')?.addEventListener('click', () => closeVersion(v));
      li.querySelector('[data-edit-log]')?.addEventListener('click', () => editLog(v));
      li.querySelector('[data-v-menu]')?.addEventListener('click', (e) => openMenu(e.currentTarget, [
        { label: 'Editar nombre, título, fecha o descripción', icon: 'pencil', onClick: () => editVersion(v) },
        v.estado === 'cerrada' && { label: 'Reabrir', icon: 'rotate-ccw', onClick: () => api(`/api/proyectos/versiones/${v.id}`, { method: 'PATCH', body: { estado: 'abierta' } }).then(reload) },
        { label: 'Borrar la versión', icon: 'trash-2', danger: true, onClick: async () => {
          if (!(await uiConfirm(`¿Borrar ${v.nombre}?`, 'Sus tareas no se borran: se quedan sin versión.', { confirmLabel: 'Borrar', danger: true }))) return;
          const res = await api(`/api/proyectos/versiones/${v.id}`, { method: 'DELETE' });
          reload();
          undoToast('Versión en la papelera', res, reload);
        } },
      ].filter(Boolean)));
    });
  }
  const renderMd = (t) => (window.marked && window.DOMPurify ? renderMarkdown(t, { breaks: false }) : `<pre>${esc(t)}</pre>`);
  const reload = async () => { await refresh(); await Ctx.load(true).catch(() => {}); await Items.load(); renderProject(); };

  const versionFields = (v) => `<div class="row"><label class="field"><span class="field-label">Nombre</span><input name="nombre" class="input" required maxlength="30" value="${esc(v.nombre)}"></label>
      <label class="field grow"><span class="field-label">Fecha objetivo</span><input name="fecha" type="date" class="input" value="${esc(v.fecha_objetivo || '')}"></label></div>
    <label class="field"><span class="field-label">Título (opcional)</span><input name="titulo" class="input" maxlength="120" value="${esc(v.titulo || '')}" placeholder="Tablero con columnas…"></label>
    <label class="field"><span class="field-label">Descripción (Markdown, opcional)</span><textarea name="descripcion" class="textarea" rows="4" maxlength="20000" placeholder="Qué entra en esta versión y por qué">${esc(v.descripcion || '')}</textarea></label>`;
  async function newVersion() {
    const last = P.versiones[P.versiones.length - 1]?.nombre || 'v0.0';
    const m = last.match(/^v(\d+)\.(\d+)/);
    const sug = m ? `v${m[1]}.${Number(m[2]) + 1}` : 'v0.1';
    const res = await form('Nueva versión', versionFields({ nombre: sug }), 'Crear');
    if (!res) return;
    try { await api(`/api/proyectos/${P.id}/versiones`, { method: 'POST', body: { nombre: res.nombre, fecha_objetivo: res.fecha || null, titulo: res.titulo, descripcion: res.descripcion } }); } catch { return; }
    reload();
  }
  async function editVersion(v) {
    const res = await form(v.nombre, versionFields(v), 'Guardar');
    if (!res) return;
    try { await api(`/api/proyectos/versiones/${v.id}`, { method: 'PATCH', body: { nombre: res.nombre, fecha_objetivo: res.fecha || '', titulo: res.titulo, descripcion: res.descripcion } }); } catch { return; }
    reload();
  }

  async function assignTasks(v) {
    await Items.ready();
    const cand = Items.state.items.filter((i) => i.proyecto_id === P.id && !i.parent_id && i.type === 'tarea' && (!i.version_id || i.version_id === v.id || P.versiones.find((x) => x.id === i.version_id)?.estado === 'cerrada' && !i.done));
    if (!cand.length) { toast('No hay tareas del proyecto sin versión', { type: 'info' }); return; }
    const res = await form(`Tareas de ${v.nombre}`, `<ul class="list pj-pick">${cand.map((i) => `<li class="list-row"><label class="row grow"><input type="checkbox" class="checkbox" name="t${i.id}" ${i.version_id === v.id ? 'checked' : ''}>
      <span class="${i.done ? 'muted' : ''}">${esc(i.text.split('\n')[0])}</span></label></li>`).join('')}</ul>`, 'Guardar');
    if (!res) return;
    for (const i of cand) {
      const want = !!res[`t${i.id}`];
      if (want !== (i.version_id === v.id)) await api(`/api/items/${i.id}`, { method: 'PATCH', quiet: true, body: { version_id: want ? v.id : 0 } });
    }
    reload();
  }

  async function closeVersion(v) {
    const prev = await api(`/api/proyectos/versiones/${v.id}/changelog`);
    const otras = P.versiones.filter((x) => x.estado === 'abierta' && x.id !== v.id);
    const abiertas = Items.state.items.filter((i) => i.version_id === v.id && !i.parent_id && !i.done).length;
    const res = await form(`Cerrar ${v.nombre}`, `
      <label class="field"><span class="field-label">Registro de cambios (puedes editarlo)</span><textarea name="log" class="textarea pj-log-edit" rows="10" maxlength="50000">${esc(prev.changelog)}</textarea></label>
      ${abiertas ? `<label class="field"><span class="field-label">${abiertas} tareas sin hacer pasan a</span><select name="mover" class="select"><option value="">Ninguna versión</option>${otras.map((x) => `<option value="${x.id}">${esc(x.nombre)}</option>`).join('')}</select></label>` : ''}`, 'Cerrar la versión');
    if (!res) return;
    const r = await api(`/api/proyectos/versiones/${v.id}/cerrar`, { method: 'POST', body: { mover_a: Number(res.mover) || null } });
    if (res.log.trim() !== r.changelog.trim()) await api(`/api/proyectos/versiones/${v.id}`, { method: 'PATCH', body: { changelog: res.log } });
    toast(`${v.nombre} cerrada`, { type: 'success' });
    reload();
  }

  async function editLog(v) {
    const res = await form(`Registro de ${v.nombre}`, `<textarea name="log" class="textarea pj-log-edit" rows="12" maxlength="50000" aria-label="Registro de cambios">${esc(v.changelog || '')}</textarea>`, 'Guardar');
    if (!res) return;
    await api(`/api/proyectos/versiones/${v.id}`, { method: 'PATCH', body: { changelog: res.log } });
    reload();
  }

  /* ---------- Registro de cambios: todas las versiones cerradas, de la más nueva a la más vieja ---------- */
  const dateOfClose = (v) => (v.cerrada_at ? PjVistas.isoOf(new Date(v.cerrada_at * 1000)) : null);
  // El registro generado empieza con su propia cabecera «## vX…»: aquí la pone la tarjeta
  const logBody = (v) => String(v.changelog || '').replace(/^\s*##\s+v[^\n]*\n+/, '').trim();
  function changelogMd() {
    const closed = P.versiones.filter((v) => v.estado === 'cerrada').sort((a, b) => (b.cerrada_at || 0) - (a.cerrada_at || 0));
    const open = P.versiones.filter((v) => v.estado === 'abierta');
    const parts = [`# Registro de cambios · ${P.nombre}`, '', 'Formato: una sección por versión, de la más nueva a la más vieja.', ''];
    const pend = open.flatMap((v) => Items.state.items.filter((i) => i.version_id === v.id && !i.parent_id && i.done));
    if (pend.length) parts.push('## [Sin publicar]', '', ...pend.map((i) => `- ${i.text.split('\n')[0]}`), '');
    closed.forEach((v) => {
      parts.push(`## [${v.nombre}] - ${dateOfClose(v) || ''}${v.titulo ? ` · ${v.titulo}` : ''}`, '');
      if (v.descripcion) parts.push(v.descripcion.trim(), '');
      if (logBody(v)) parts.push(logBody(v), '');
    });
    return parts.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
  }
  function renderCambios(box) {
    const closed = P.versiones.filter((v) => v.estado === 'cerrada').sort((a, b) => (b.cerrada_at || 0) - (a.cerrada_at || 0));
    const open = P.versiones.filter((v) => v.estado === 'abierta');
    const pend = open.map((v) => [v, Items.state.items.filter((i) => i.version_id === v.id && !i.parent_id && i.done)]).filter(([, l]) => l.length);
    box.innerHTML = `<div class="row pj-toolbar"><button type="button" class="btn btn-tinted btn-sm" data-copy-log ${closed.length || pend.length ? '' : 'disabled'}>${icon('copy', 'icon-sm')}Copiar como CHANGELOG.md</button>
        <span class="tiny muted">Lo que cambió en cada versión, de la más nueva a la más vieja. Se escribe solo al cerrar una versión (Versiones → Cerrar).</span></div>
      ${!closed.length && !pend.length ? emptyState({ iconName: 'history', title: 'Aún no hay cambios publicados', text: 'Cierra una versión con tareas hechas y su registro aparecerá aquí.', compact: true }) : `<ol class="pj-changelog">
        ${pend.map(([v, l]) => `<li class="pj-cl is-pending"><div class="pj-cl-rail" aria-hidden="true"></div><div class="pj-cl-body">
          <h3>${esc(v.nombre)} <span class="tag">Sin publicar</span></h3>${v.titulo ? `<p class="pj-version-title">${esc(v.titulo)}</p>` : ''}
          <ul class="pj-cl-list">${l.map((i) => `<li>${esc(i.text.split('\n')[0])}</li>`).join('')}</ul></div></li>`).join('')}
        ${closed.map((v) => `<li class="pj-cl"><div class="pj-cl-rail" aria-hidden="true"></div><div class="pj-cl-body">
          <h3>${esc(v.nombre)}${v.titulo ? ` <span class="pj-version-title">· ${esc(v.titulo)}</span>` : ''}</h3>
          <p class="tiny muted">${dateOfClose(v) ? `<time datetime="${dateOfClose(v)}">${fmtDay(dateOfClose(v))}</time>` : ''}${v.fecha_objetivo ? ` · objetivo ${fmtDay(v.fecha_objetivo)}` : ''} · ${v.hechas} tareas</p>
          ${v.descripcion ? `<div class="md pj-version-desc">${renderMd(v.descripcion)}</div>` : ''}
          ${logBody(v) ? `<div class="md pj-log">${renderMd(logBody(v))}</div>` : '<p class="small muted">Sin registro.</p>'}</div></li>`).join('')}</ol>`}`;
    box.querySelector('[data-copy-log]')?.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(changelogMd()); toast('CHANGELOG.md copiado', { type: 'success', duration: 1600 }); } catch { toast('No se pudo copiar', { type: 'error' }); }
    });
  }

  /* ---------- Esquemas: los tableros del Inbox de este proyecto ---------- */
  async function renderEsquemas(box) {
    const all = (await api('/api/boards', { quiet: true })).boards.filter((b) => b.proyecto_id === P.id);
    box.innerHTML = `<div class="row pj-toolbar"><button type="button" class="btn btn-tinted btn-sm" data-new-board>${icon('plus', 'icon-sm')}Esquema</button>
      <span class="tiny muted">Se dibujan en el Inbox; aquí están los de este proyecto.</span></div>
      ${all.length ? `<ul class="list">${all.map((b) => `<li><a class="list-row" href="/inbox?esquema=${b.id}">${icon('shapes', 'icon-sm')}<span class="row-main"><span class="row-title">${esc(b.name)}</span>
        <span class="row-sub">${timeAgo(b.updated_at)}</span></span>${icon('chevron-right', 'icon-sm')}</a></li>`).join('')}</ul>`
        : emptyState({ iconName: 'shapes', title: 'Sin esquemas', text: 'Crea uno (arquitectura, flujo, ideas) o asocia uno existente desde el Inbox: menú del tablero → «Contexto o proyecto…».', compact: true })}`;
    box.querySelector('[data-new-board]').addEventListener('click', async () => {
      const name = (await uiPrompt('Nuevo esquema', { label: 'Nombre', value: `${P.nombre} · `, confirmLabel: 'Crear' }))?.trim();
      if (!name) return;
      const r = await api('/api/boards', { method: 'POST', body: { name, proyecto_id: P.id } });
      location.href = `/inbox?esquema=${r.id}`;
    });
  }

  /* ---------- Bitácora: una nota del proyecto (decisiones y cambios, con [[tarea:N]]) ---------- */
  async function renderBitacora(box) {
    if (!P.note_id) {
      box.innerHTML = emptyState({ iconName: 'notebook-pen', title: 'Sin bitácora', text: 'Una nota del proyecto para apuntar decisiones, cambios y aprendizajes, enlazada a sus tareas.', actionLabel: 'Crear la bitácora', action: 'log', compact: true });
      box.querySelector('[data-empty-action=log]').addEventListener('click', async () => { const r = await api(`/api/proyectos/${P.id}/bitacora`, { method: 'POST' }); location.href = `/?note=${encodeURIComponent(r.note_id)}`; });
      return;
    }
    let note = null;
    try { note = await api(`/api/notes/${encodeURIComponent(P.note_id)}`, { quiet: true }); } catch { /* sin vista previa */ }
    box.innerHTML = `<div class="row pj-toolbar"><a class="btn btn-tinted btn-sm" href="/?note=${encodeURIComponent(P.note_id)}">${icon('pencil', 'icon-sm')}Escribir en la bitácora</a></div>
      <article class="panel pj-note"><div class="panel-body md">${note ? renderMd(note.content.slice(0, 6000)) : '<p class="muted">No se pudo leer la nota.</p>'}</div></article>`;
  }

  /* ---------- Enlaces: repositorio, carpeta (abrir o copiar), Git (solo lectura) y los que quieras ---------- */
  async function renderEnlaces(box) {
    box.innerHTML = `<div class="pj-links">
      <section class="panel"><div class="panel-header"><h2>${icon('link', 'icon-sm')}Enlaces</h2><span class="grow"></span><button type="button" class="btn btn-ghost btn-sm" data-edit-proj>${icon('pencil', 'icon-sm')}Editar</button></div>
        <div class="panel-body"><ul class="list">
          ${P.repo_url ? `<li><a class="list-row" href="${esc(P.repo_url)}" target="_blank" rel="noopener noreferrer">${icon('git-branch', 'icon-sm')}<span class="row-main"><span class="row-title">Repositorio</span><span class="row-sub">${esc(P.repo_url)}</span></span>${icon('external-link', 'icon-sm')}</a></li>` : ''}
          ${(P.enlaces || []).map((l) => `<li><a class="list-row" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">${icon('link', 'icon-sm')}<span class="row-main"><span class="row-title">${esc(l.titulo)}</span><span class="row-sub">${esc(l.url)}</span></span>${icon('external-link', 'icon-sm')}</a></li>`).join('')}
          ${P.carpeta ? `<li class="list-row">${icon('folder', 'icon-sm')}<span class="row-main"><span class="row-title">Carpeta</span><span class="row-sub">${esc(P.carpeta)}</span></span>
            <button type="button" class="btn btn-ghost btn-sm" data-open-folder>${icon('folder-open', 'icon-sm')}Abrir</button><button type="button" class="btn btn-ghost btn-icon btn-sm" data-copy aria-label="Copiar ruta">${icon('copy', 'icon-sm')}</button></li>` : ''}
          ${!P.repo_url && !P.carpeta && !(P.enlaces || []).length ? '<li class="list-row muted small">Añade el repositorio, la carpeta o enlaces con «Editar».</li>' : ''}
        </ul></div></section>
      <section class="panel"><div class="panel-header"><h2>${icon('git-commit-horizontal', 'icon-sm')}Git</h2><span class="tiny muted">solo lectura</span></div><div class="panel-body" id="pjGit"><span class="skeleton skeleton-line"></span></div></section></div>`;
    box.querySelector('[data-edit-proj]').addEventListener('click', () => projectDialog(P));
    box.querySelector('[data-open-folder]')?.addEventListener('click', () => Ctx.openFolder('proyecto', P.id));
    let abs = null;
    if (P.carpeta) api(`/api/abrir/proyecto/${P.id}`, { quiet: true }).then((r) => { abs = r.absoluta; }).catch(() => {});
    box.querySelector('[data-copy]')?.addEventListener('click', () => Ctx.copyPath(abs));
    const g = await api(`/api/proyectos/${P.id}/git`, { quiet: true }).catch(() => ({ disponible: false, motivo: 'No se pudo leer' }));
    $('pjGit').innerHTML = g.disponible ? `<p class="small"><b>${esc(g.rama)}</b> · último commit: ${esc(g.ultimo?.mensaje || '')}</p>
      <p class="tiny muted">${esc(g.ultimo?.hash || '')} · ${esc(g.ultimo?.autor || '')} · ${g.ultimo ? new Date(g.ultimo.fecha).toLocaleString('es-ES') : ''}</p>
      ${g.etiquetas.length ? `<div class="chips">${g.etiquetas.map((t) => `<span class="tag">${icon('tag', 'icon-sm')}${esc(t)}</span>`).join('')}</div>` : '<p class="tiny muted">Sin etiquetas de versión.</p>'}`
      : `<p class="small muted">${esc(g.motivo || 'Sin repositorio')}. Pon la carpeta del proyecto (relativa a la raíz de proyectos) para ver su último commit y sus etiquetas.</p>`;
  }

  /* =====================================================================
     Crear y editar
     ===================================================================== */
  async function projectDialog(p = null) {
    const res = await form(p ? `Editar ${p.nombre}` : 'Nuevo proyecto', `
      <label class="field"><span class="field-label">Nombre</span><input name="nombre" class="input" required maxlength="120" value="${esc(p?.nombre || '')}" placeholder="Panel Maestro…"></label>
      <label class="field"><span class="field-label">Descripción (Markdown)</span><textarea name="descripcion" class="textarea" rows="5" maxlength="20000" placeholder="Objetivo, alcance, enlaces… «- [ ]» para una lista de pendientes">${esc(p?.descripcion || '')}</textarea></label>
      <div class="row pj-form-row"><label class="field grow"><span class="field-label">Estado</span><select name="estado" class="select">${Object.entries(ESTADOS).map(([k, l]) => `<option value="${k}" ${(p?.estado || 'en-curso') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field grow"><span class="field-label">Prioridad</span><select name="prioridad" class="select"><option value="">Sin prioridad</option>${Object.entries(PRIOS).map(([k, l]) => `<option value="${k}" ${p?.prioridad === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div>
      <div class="row pj-form-row"><label class="field grow"><span class="field-label">Inicio</span><input name="fecha_inicio" type="date" class="input" value="${esc(p?.fecha_inicio || '')}"></label>
        <label class="field grow"><span class="field-label">Fin (objetivo)</span><input name="fecha_fin" type="date" class="input" value="${esc(p?.fecha_fin || '')}"></label></div>
      <label class="field"><span class="field-label">Etiquetas (separadas por comas)</span><input name="etiquetas" class="input" maxlength="600" value="${esc((p?.etiquetas || []).join(', '))}" placeholder="web, universidad, hardware…"></label>
      <div class="row pj-form-row"><label class="field grow"><span class="field-label">Carpeta (en la raíz de proyectos)</span><input name="carpeta" class="input" maxlength="1000" value="${esc(p?.carpeta || '')}" placeholder="panel-maestro…"></label>
        <label class="field grow"><span class="field-label">Repositorio (URL)</span><input name="repo_url" class="input" type="url" maxlength="1000" value="${esc(p?.repo_url || '')}" placeholder="https://github.com/…"></label></div>
      <fieldset class="field"><legend class="field-label">Color</legend><div class="uni-colors pj-colors">${Array.from({ length: 10 }, (_, i) => `<label class="uni-color" style="--c:var(--cat-${i})"><input type="radio" name="color" value="cat-${i}" ${(p?.color || 'cat-3') === `cat-${i}` ? 'checked' : ''}><span class="sr-only">Color ${i + 1}</span></label>`).join('')}</div></fieldset>
      <label class="field"><span class="field-label">Enlaces (uno por línea: «Docs https://…»)</span><textarea name="enlaces" class="textarea" rows="2" maxlength="5000">${esc((p?.enlaces || []).map((l) => `${l.titulo} ${l.url}`).join('\n'))}</textarea></label>`, p ? 'Guardar' : 'Crear', '');
    if (!res) return;
    if (res.fecha_inicio && res.fecha_fin && res.fecha_fin < res.fecha_inicio) { toast('El fin es anterior al inicio', { type: 'error' }); return; }
    const enlaces = res.enlaces.split('\n').map((l) => l.trim().match(/^(.*?)\s*(https?:\/\/\S+)$/i)).filter(Boolean).map((m) => ({ titulo: m[1] || 'Enlace', url: m[2] }));
    const body = { nombre: res.nombre.trim(), descripcion: res.descripcion, estado: res.estado, carpeta: res.carpeta.trim(), repo_url: res.repo_url.trim(), color: res.color, enlaces,
      prioridad: res.prioridad, fecha_inicio: res.fecha_inicio, fecha_fin: res.fecha_fin, etiquetas: res.etiquetas.split(',').map((t) => t.trim()).filter(Boolean) };
    try {
      if (p) { await api(`/api/proyectos/${p.id}`, { method: 'PATCH', body }); if (slug) reload(); else loadList(); } else {
        const r = await api('/api/proyectos', { method: 'POST', body: { ...body, prioridad: body.prioridad || null, fecha_inicio: body.fecha_inicio || null, fecha_fin: body.fecha_fin || null } });
        location.href = `/proyectos/${encodeURIComponent(r.slug)}`;
      }
    } catch { /* api avisa */ }
  }
  $('pjNew').addEventListener('click', () => projectDialog());
  $('pjMenu').addEventListener('click', (e) => openMenu(e.currentTarget, [
    { label: 'Editar el proyecto', icon: 'pencil', onClick: () => projectDialog(P) },
    ...Object.entries(ESTADOS).filter(([k]) => k !== P.estado).map(([k, l]) => ({ label: `Marcar «${l}»`, icon: 'flag', onClick: () => api(`/api/proyectos/${P.id}`, { method: 'PATCH', body: { estado: k } }).then(reload) })),
    P.carpeta && { label: 'Abrir la carpeta', icon: 'folder-open', onClick: () => Ctx.openFolder('proyecto', P.id) },
    { label: 'Ver en Tareas (contexto Proyectos)', icon: 'list-todo', onClick: () => { Ctx.set('proyectos'); location.href = '/tareas'; } },
  ].filter(Boolean)));

  function form(title, body, okLabel, size = 'modal-sm') {
    return new Promise((resolve) => {
      const dlg = document.createElement('dialog');
      dlg.className = `modal ${size}`;
      const id = 'pf' + Math.random().toString(36).slice(2, 7);
      dlg.setAttribute('aria-labelledby', id);
      dlg.innerHTML = `<div class="modal-header"><h2 id="${id}">${esc(title)}</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
        <form class="modal-body stack" id="${id}f" autocomplete="off">${body}</form>
        <div class="modal-footer"><button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="${id}f" class="btn btn-primary">${esc(okLabel)}</button></div>`;
      document.body.appendChild(dlg);
      wireAllDialogs?.();
      let result = null;
      const f = dlg.querySelector('form');
      f.addEventListener('submit', (e) => {
        e.preventDefault();
        if (!f.reportValidity()) return;
        result = {};
        [...f.elements].forEach((el) => {
          if (!el.name) return;
          if (el.type === 'checkbox') result[el.name] = el.checked;
          else if (el.type === 'radio') { if (el.checked) result[el.name] = el.value; } else result[el.name] = el.value;
        });
        closeModal(dlg);
      });
      openModal(dlg, { focus: 'input, textarea, select', onClose: () => { dlg.remove(); resolve(result); } });
    });
  }

  /* =====================================================================
     Atajos: N nuevo, / buscar, V vista, 1–7 pestañas
     ===================================================================== */
  const typing = (t) => /^(input|textarea|select)$/i.test(t?.tagName || '') || t?.isContentEditable;
  // «/» también es del panel (búsqueda global): aquí busca en la página, así que va antes, en captura
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || document.querySelector('dialog[open]')) return;
    const input = $('pjSearch') || (tab === 'tareas' ? $('pjTq') : null);
    if (!input) return;
    e.preventDefault(); e.stopPropagation();
    input.focus(); input.select();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || document.querySelector('dialog[open]')) return;
    const k = e.key.toLowerCase();
    if (k === 'n') {
      e.preventDefault();
      if (!slug) { projectDialog(); return; }
      if (tab !== 'tareas' && tab !== 'ideas') setTab('tareas');
      $(tab === 'ideas' ? 'pjCap-idea' : 'pjCap-tarea')?.focus();
      return;
    }
    if (k === 'v') {
      e.preventDefault();
      if (!slug) { const vs = LIST_VIEWS.map(([x]) => x), cur = pref('proyectos.vista', 'tarjetas'); setListView(vs[(vs.indexOf(cur) + 1) % vs.length]); return; }
      if (tab !== 'tareas') return;
      const vs = TASK_VIEWS.map(([x]) => x), cur = pref(VIEW_KEY, 'versiones');
      setPref(VIEW_KEY, vs[(vs.indexOf(cur) + 1) % vs.length]);
      renderTareas($('pjBody'));
      return;
    }
    if (slug && /^[1-7]$/.test(e.key)) { e.preventDefault(); setTab(TABS[Number(e.key) - 1][0]); }
  });
  // En un campo de búsqueda, Esc lo vacía y devuelve el foco a la página
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && (e.target.id === 'pjSearch' || e.target.id === 'pjTq') && e.target.value) {
      e.preventDefault();
      e.target.value = '';
      e.target.dispatchEvent(new Event('input'));
    }
  });

  onDataChange(/^\/api\/proyectos/, () => { if (!slug) loadList(); });
  if (slug) loadProject(); else loadList();
})();
