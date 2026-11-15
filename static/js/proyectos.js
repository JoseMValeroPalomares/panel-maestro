/* =====================================================================
   Proyectos (/proyectos y /proyectos/<slug>): tarjetas con estado, versión actual, progreso y
   tareas abiertas; dentro, Tareas (lista o columnas por hacer / en curso / hecho), Versiones,
   Ideas, Esquemas, Bitácora y Enlaces. Las tareas e ideas son las de siempre (Items, contexto
   «proyectos» con proyecto_id); los esquemas, tableros del Inbox; la bitácora, una nota.
   API: /api/proyectos (app/proyectos.py).
   ===================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  const root = $('pjRoot');
  const slug = decodeURIComponent(location.pathname.split('/')[2] || '');
  const ESTADOS = { idea: 'Idea', 'en-curso': 'En curso', pausado: 'Pausado', terminado: 'Terminado' };
  const TABS = [['tareas', 'Tareas', 'list-todo'], ['versiones', 'Versiones', 'milestone'], ['ideas', 'Ideas', 'lightbulb'],
    ['esquemas', 'Esquemas', 'shapes'], ['bitacora', 'Bitácora', 'notebook-pen'], ['enlaces', 'Enlaces', 'link']];
  const VIEW_KEY = 'proyecto-vista-tareas';
  const fmtDay = (iso) => (iso ? new Date(iso + 'T00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
  const color = (c) => Ctx.color(c);
  let P = null, tab = new URLSearchParams(location.search).get('pestana') || 'tareas';

  /* ---------- Lista de proyectos ---------- */
  async function loadList() {
    let data;
    try { data = await api('/api/proyectos', { quiet: true }); } catch { showState(root, loadFailed('No se pudieron cargar los proyectos', true), loadList); return; }
    const list = data.proyectos;
    if (!list.length) {
      root.innerHTML = emptyState({ iconName: 'rocket', title: 'Construye tus proyectos', text: 'Un proyecto junta sus tareas, ideas, versiones, esquemas y una bitácora. Captura con «#nombre» desde cualquier sitio.', actionLabel: 'Crear el primero', action: 'new' });
      root.querySelector('[data-empty-action=new]')?.addEventListener('click', () => projectDialog());
      return;
    }
    const groups = Object.keys(ESTADOS).map((e) => [e, list.filter((p) => p.estado === e)]).filter(([, l]) => l.length);
    root.innerHTML = groups.map(([e, l]) => `<section class="pj-section" aria-labelledby="pj-s-${e}"><h2 class="cat-header" id="pj-s-${e}">${ESTADOS[e]}<span class="count">${l.length}</span></h2>
      <ul class="pj-grid">${l.map(card).join('')}</ul></section>`).join('');
  }

  function card(p) {
    const v = p.version_actual;
    return `<li class="pj-card" style="--pj:${color(p.color)}"><a class="pj-card-link" href="/proyectos/${encodeURIComponent(p.slug)}">
      <div class="pj-card-top"><span class="pj-mark" aria-hidden="true">${icon('rocket', 'icon-sm')}</span>
        <h3 class="pj-card-title">${esc(p.nombre)}</h3><span class="tag pj-estado" data-estado="${p.estado}">${ESTADOS[p.estado]}</span></div>
      ${p.descripcion ? `<p class="pj-desc small">${esc(p.descripcion)}</p>` : ''}
      <div class="pj-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${p.progreso}" aria-label="Progreso de ${esc(p.nombre)}"><span style="width:${p.progreso}%"></span></div>
      <div class="pj-card-meta tiny">
        <span>${icon('milestone', 'icon-sm')}${v ? `${esc(v.nombre)}${v.fecha_objetivo ? ` · ${fmtDay(v.fecha_objetivo)}` : ''}` : p.ultima_version ? esc(p.ultima_version.nombre) : 'Sin versión'}</span>
        <span class="tabular">${icon('list-todo', 'icon-sm')}${p.tareas_abiertas} abiertas</span>
        ${p.ideas ? `<span class="tabular">${icon('lightbulb', 'icon-sm')}${p.ideas}</span>` : ''}
        <span class="tabular">${p.progreso} %</span></div></a></li>`;
  }

  /* ---------- Un proyecto ---------- */
  async function loadProject() {
    try { P = await api(`/api/proyectos/${encodeURIComponent(slug)}`, { quiet: true }); } catch (e) {
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
    root.innerHTML = `<header class="pj-head" style="--pj:${color(P.color)}">
        <div class="pj-head-main">
          <p class="pj-desc">${P.descripcion ? esc(P.descripcion) : '<span class="muted">Sin descripción</span>'}</p>
          <div class="pj-card-meta small">
            <span class="tag pj-estado" data-estado="${P.estado}">${ESTADOS[P.estado]}</span>
            <span>${icon('milestone', 'icon-sm')}${v ? `${esc(v.nombre)} · ${v.hechas}/${v.total}` : 'Sin versión abierta'}</span>
            <span class="tabular">${icon('list-todo', 'icon-sm')}${P.tareas_abiertas} abiertas · ${P.tareas_hechas} hechas</span>
            <span class="ctx-chip"><span class="ctx-dot" style="background:${color(P.color)}"></span>#${esc(P.slug)}</span>
          </div>
          <div class="pj-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${P.progreso}" aria-label="Progreso"><span style="width:${P.progreso}%"></span></div>
        </div>
        ${P.carpeta ? `<div class="pj-head-actions"><button type="button" class="btn btn-tinted btn-sm" data-open-folder>${icon('folder-open', 'icon-sm')}<span class="hide-mobile">Abrir carpeta</span><span class="sr-only show-mobile">Abrir la carpeta</span></button></div>` : ''}
      </header>
      <div class="segmented pj-tabs" role="tablist" aria-label="Partes del proyecto">${TABS.map(([k, l, ic]) => `<button type="button" role="tab" data-tab="${k}" aria-selected="${k === tab}">${icon(ic, 'icon-sm')}${l}</button>`).join('')}</div>
      <div id="pjBody" class="pj-body"></div>`;
    root.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', () => { tab = b.dataset.tab; renderProject(); history.replaceState(null, '', `?pestana=${tab}`); }));
    root.querySelector('[data-open-folder]')?.addEventListener('click', () => Ctx.openFolder('proyecto', P.id));
    ({ tareas: renderTareas, versiones: renderVersiones, ideas: renderIdeas, esquemas: renderEsquemas, bitacora: renderBitacora, enlaces: renderEnlaces }[tab] || renderTareas)($('pjBody'));
  }

  /* Captura dentro del proyecto: lo nuevo va a él (y a la versión abierta si se elige) */
  function captureHTML(type) {
    const vers = P.versiones.filter((v) => v.estado === 'abierta');
    return `<form class="capture-panel pj-capture" data-pj-capture="${type}" autocomplete="off">
      <label class="sr-only" for="pjCap-${type}">${type === 'idea' ? 'Nueva idea' : 'Nueva tarea'} de ${esc(P.nombre)}</label>
      <input id="pjCap-${type}" class="input" maxlength="2000" placeholder="${type === 'idea' ? 'Nueva idea…' : 'Nueva tarea (p. ej. «arreglar login viernes»)…'}">
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

  /* Tareas: la lista común o columnas por hacer / en curso / hecho */
  function renderTareas(box) {
    const mode = Prefs.get(VIEW_KEY, 'columnas');
    box.innerHTML = `<div class="row pj-toolbar">${captureHTML('tarea')}
        <div class="segmented" role="group" aria-label="Vista"><button type="button" data-mode="lista" aria-pressed="${mode === 'lista'}">${icon('list', 'icon-sm')}Lista</button>
          <button type="button" data-mode="columnas" aria-pressed="${mode === 'columnas'}">${icon('square-kanban', 'icon-sm')}Columnas</button></div></div>
      <div id="pjTasks"></div>`;
    wireCapture(box);
    box.querySelectorAll('[data-mode]').forEach((b) => b.addEventListener('click', () => { Prefs.set(VIEW_KEY, b.dataset.mode); renderTareas(box); }));
    if (mode === 'lista') {
      ItemList.mount($('pjTasks'), { variant: 'page', filters: { contexto: 'proyectos', proyecto: P.id, type: 'tarea', status: 'all' } });
    } else Items.ready().then(() => kanban($('pjTasks'))).catch(() => {});
  }

  function kanban(el) {
    const mine = Items.state.items.filter((i) => i.proyecto_id === P.id && !i.parent_id && i.type === 'tarea');
    const cols = [['todo', 'Por hacer', mine.filter((i) => !i.done && !i.en_curso)], ['doing', 'En curso', mine.filter((i) => !i.done && i.en_curso)],
      ['done', 'Hecho', mine.filter((i) => i.done)]];
    const vname = (id) => P.versiones.find((v) => v.id === id)?.nombre;
    el.innerHTML = `<div class="pj-kanban">${cols.map(([k, l, items]) => `<section class="pj-col" data-col="${k}" aria-labelledby="pjc-${k}">
      <h3 class="pj-col-title" id="pjc-${k}">${l}<span class="count">${items.length}</span>${k === 'done' && items.length ? `<span class="grow"></span><button type="button" class="btn btn-ghost btn-sm" data-clear-done title="Las cerradas siguen en el registro de su versión">${icon('trash-2', 'icon-sm')}Borrar</button>` : ''}</h3>
      <ul class="pj-col-list" data-col="${k}" data-empty="Suelta aquí" aria-label="${l}">${items.map((it) => {
        const kids = Items.children(it.id);
        return `<li class="pj-task${it.done ? ' is-done' : ''}" data-id="${it.id}">
          <button type="button" class="drag-handle" data-drag-handle aria-label="Mover «${esc(it.text.slice(0, 40))}»">${icon('grip-vertical', 'icon-sm')}</button>
          <div class="pj-task-body"><a class="pj-task-title" href="/tareas?item=${it.id}">${esc(it.text.split('\n')[0])}</a>
            <div class="pj-task-meta tiny">${it.version_id ? `<span class="tag">${icon('milestone', 'icon-sm')}${esc(vname(it.version_id) || '')}</span>` : ''}
              ${kids.length ? `<span class="tabular">${icon('list-checks', 'icon-sm')}${kids.filter((x) => x.done).length}/${kids.length}</span>` : ''}
              ${it.due_date ? `<span>${icon('calendar', 'icon-sm')}${fmtDay(it.due_date)}</span>` : ''}
              ${it.priority ? `<span class="tag prio" data-prio="${esc(it.priority)}">${esc(it.priority)}</span>` : ''}</div></div></li>`;
      }).join('')}</ul></section>`).join('')}</div>
      <p class="tiny muted pj-hint">Lo hecho se guarda aunque cierres la versión (y queda en su registro de cambios); «Borrar» lo quita con deshacer. Arrastra entre columnas (o con el teclado: Alt + flechas). Los pasos van dentro de su tarea, como en Tareas.</p>`;
    el.querySelector('[data-clear-done]')?.addEventListener('click', async () => {
      const ids = cols[2][2].map((i) => i.id);
      if (!(await uiConfirm(`¿Borrar ${ids.length} tareas hechas?`, 'Van a la papelera (30 días) y puedes deshacerlo ahora. Los registros de cambios de las versiones no cambian.', { confirmLabel: 'Borrar', danger: true }))) return;
      await Items.remove(ids, { label: `${ids.length} tareas hechas borradas` });
      await refresh();
      kanban(el);
    });
    el.querySelectorAll('.pj-col-list').forEach((list) => Sortable.create(list, {
      group: 'pj-kanban', items: '.pj-task', handle: '[data-drag-handle]', label: list.getAttribute('aria-label'),
      id: (n) => Number(n.dataset.id), data: { col: list.dataset.col },
      onDrop: async (ctx) => {
        const id = Number(ctx.id), to = ctx.to.data.col;
        if (Items.get(id)?.origin === 'inbox' && (ctx.beforeId || ctx.to.data.col === ctx.from.data.col)) await Items.move(id, { target: 'inbox', parent_id: null, before_id: ctx.beforeId ? Number(ctx.beforeId) : null }).catch(() => {});
        if (to !== ctx.from.data.col) await Items.update(id, to === 'done' ? { done: true } : { done: false, en_curso: to === 'doing' });
        await refresh();
        kanban(el);
      },
    }));
  }
  document.addEventListener('items:changed', () => { if (P && tab === 'tareas' && Prefs.get(VIEW_KEY, 'columnas') === 'columnas' && $('pjTasks') && !document.querySelector('.is-dragging')) kanban($('pjTasks')); });

  function renderIdeas(box) {
    box.innerHTML = `${captureHTML('idea')}<div id="pjIdeas"></div>`;
    wireCapture(box);
    ItemList.mount($('pjIdeas'), { variant: 'page', filters: { contexto: 'proyectos', proyecto: P.id, type: 'idea' } });
  }

  /* Versiones: crear, asignar tareas, progreso y cerrar con registro de cambios */
  function renderVersiones(box) {
    const vs = [...P.versiones].reverse();
    box.innerHTML = `<div class="row pj-toolbar"><button type="button" class="btn btn-tinted btn-sm" data-new-version>${icon('plus', 'icon-sm')}Versión</button>
      <span class="tiny muted">Asigna tareas a una versión; al cerrarla, sus tareas hechas forman el registro de cambios.</span></div>
      ${vs.length ? `<ul class="pj-versions">${vs.map((v) => `<li class="pj-version${v.estado === 'cerrada' ? ' is-closed' : ''}" data-v="${v.id}">
        <div class="pj-version-head"><h3>${esc(v.nombre)}</h3>
          <span class="tag">${v.estado === 'cerrada' ? `${icon('circle-check', 'icon-sm')}Cerrada` : 'Abierta'}</span>
          ${v.fecha_objetivo ? `<span class="small muted">${icon('calendar', 'icon-sm')}${fmtDay(v.fecha_objetivo)}</span>` : ''}
          <span class="grow"></span><span class="small tabular">${v.hechas}/${v.total} · ${v.progreso} %</span>
          ${v.estado === 'abierta' ? `<button type="button" class="btn btn-sm" data-assign>${icon('list-plus', 'icon-sm')}<span class="hide-mobile">Asignar tareas</span></button>
            <button type="button" class="btn btn-tinted btn-sm" data-close-v>${icon('circle-check', 'icon-sm')}Cerrar</button>` : `<button type="button" class="btn btn-ghost btn-sm" data-edit-log>${icon('pencil', 'icon-sm')}Editar registro</button>`}
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-v-menu aria-label="Más acciones de ${esc(v.nombre)}" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button></div>
        <div class="pj-progress"><span style="width:${v.progreso}%"></span></div>
        ${v.changelog ? `<div class="md pj-log">${renderMd(v.changelog)}</div>` : ''}
        ${v.estado === 'abierta' ? `<ul class="pj-vtasks">${Items.state.items.filter((i) => i.version_id === v.id && !i.parent_id).map((i) => `<li class="${i.done ? 'is-done' : ''}">${icon(i.done ? 'circle-check' : 'circle', 'icon-sm')}${esc(i.text.split('\n')[0])}</li>`).join('')}</ul>` : ''}
      </li>`).join('')}</ul>` : emptyState({ iconName: 'milestone', title: 'Sin versiones', text: 'Crea la primera (v0.1) con una fecha objetivo.', compact: true })}`;
    box.querySelector('[data-new-version]').addEventListener('click', newVersion);
    box.querySelectorAll('[data-v]').forEach((li) => {
      const v = P.versiones.find((x) => x.id === Number(li.dataset.v));
      li.querySelector('[data-assign]')?.addEventListener('click', () => assignTasks(v));
      li.querySelector('[data-close-v]')?.addEventListener('click', () => closeVersion(v));
      li.querySelector('[data-edit-log]')?.addEventListener('click', () => editLog(v));
      li.querySelector('[data-v-menu]')?.addEventListener('click', (e) => openMenu(e.currentTarget, [
        { label: 'Cambiar nombre o fecha', icon: 'pencil', onClick: () => editVersion(v) },
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

  async function newVersion() {
    const last = P.versiones[P.versiones.length - 1]?.nombre || 'v0.0';
    const m = last.match(/^v(\d+)\.(\d+)/);
    const sug = m ? `v${m[1]}.${Number(m[2]) + 1}` : 'v0.1';
    const res = await form('Nueva versión', `<div class="row"><label class="field"><span class="field-label">Nombre</span><input name="nombre" class="input" required maxlength="30" value="${sug}"></label>
      <label class="field grow"><span class="field-label">Fecha objetivo</span><input name="fecha" type="date" class="input"></label></div>`, 'Crear');
    if (!res) return;
    try { await api(`/api/proyectos/${P.id}/versiones`, { method: 'POST', body: { nombre: res.nombre, fecha_objetivo: res.fecha || null } }); } catch { return; }
    reload();
  }

  async function editVersion(v) {
    const res = await form(v.nombre, `<div class="row"><label class="field"><span class="field-label">Nombre</span><input name="nombre" class="input" required maxlength="30" value="${esc(v.nombre)}"></label>
      <label class="field grow"><span class="field-label">Fecha objetivo</span><input name="fecha" type="date" class="input" value="${v.fecha_objetivo || ''}"></label></div>`, 'Guardar');
    if (!res) return;
    try { await api(`/api/proyectos/versiones/${v.id}`, { method: 'PATCH', body: { nombre: res.nombre, fecha_objetivo: res.fecha || '' } }); } catch { return; }
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

  /* Esquemas: los tableros del Inbox de este proyecto */
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

  /* Bitácora: una nota del proyecto (decisiones y cambios, con [[tarea:N]]) */
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

  /* Enlaces: repositorio, carpeta (abrir o copiar), Git (solo lectura) y los que quieras */
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

  /* ---------- Crear y editar ---------- */
  async function projectDialog(p = null) {
    const res = await form(p ? `Editar ${p.nombre}` : 'Nuevo proyecto', `
      <label class="field"><span class="field-label">Nombre</span><input name="nombre" class="input" required maxlength="120" value="${esc(p?.nombre || '')}" placeholder="Panel Maestro…"></label>
      <label class="field"><span class="field-label">Descripción</span><textarea name="descripcion" class="textarea" rows="2" maxlength="5000">${esc(p?.descripcion || '')}</textarea></label>
      <div class="row"><label class="field grow"><span class="field-label">Estado</span><select name="estado" class="select">${Object.entries(ESTADOS).map(([k, l]) => `<option value="${k}" ${(p?.estado || 'en-curso') === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
        <label class="field grow"><span class="field-label">Carpeta (en la raíz de proyectos)</span><input name="carpeta" class="input" maxlength="1000" value="${esc(p?.carpeta || '')}" placeholder="panel-maestro…"></label></div>
      <label class="field"><span class="field-label">Repositorio (URL)</span><input name="repo_url" class="input" type="url" maxlength="1000" value="${esc(p?.repo_url || '')}" placeholder="https://github.com/…"></label>
      <fieldset class="field"><legend class="field-label">Color</legend><div class="uni-colors pj-colors">${Array.from({ length: 10 }, (_, i) => `<label class="uni-color" style="--c:var(--cat-${i})"><input type="radio" name="color" value="cat-${i}" ${(p?.color || 'cat-3') === `cat-${i}` ? 'checked' : ''}><span class="sr-only">Color ${i + 1}</span></label>`).join('')}</div></fieldset>
      <label class="field"><span class="field-label">Enlaces (uno por línea: «Docs https://…»)</span><textarea name="enlaces" class="textarea" rows="2" maxlength="5000">${esc((p?.enlaces || []).map((l) => `${l.titulo} ${l.url}`).join('\n'))}</textarea></label>`, p ? 'Guardar' : 'Crear');
    if (!res) return;
    const enlaces = res.enlaces.split('\n').map((l) => l.trim().match(/^(.*?)\s*(https?:\/\/\S+)$/i)).filter(Boolean).map((m) => ({ titulo: m[1] || 'Enlace', url: m[2] }));
    const body = { nombre: res.nombre.trim(), descripcion: res.descripcion, estado: res.estado, carpeta: res.carpeta.trim(), repo_url: res.repo_url.trim(), color: res.color, enlaces };
    try {
      if (p) { await api(`/api/proyectos/${p.id}`, { method: 'PATCH', body }); reload(); } else {
        const r = await api('/api/proyectos', { method: 'POST', body });
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

  function form(title, body, okLabel) {
    return new Promise((resolve) => {
      const dlg = document.createElement('dialog');
      dlg.className = 'modal modal-sm';
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

  onDataChange(/^\/api\/proyectos/, () => { if (!slug) loadList(); });
  if (slug) loadProject(); else loadList();
})();
