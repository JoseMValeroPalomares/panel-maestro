/* ==========================================================================
   item-list.js — el componente de lista de tareas e ideas (window.ItemList)
   Lo usan el Inbox (panel junto al tablero) y la pestaña Tareas: mismos grupos
   (Inbox · Notas · Ideas), misma tarjeta, mismo arrastre, misma edición.

     const view = ItemList.mount(el, { variant: 'page' | 'sidebar', filters: { status: 'pending' } });
     view.setFilters({ q: 'pilas', type: 'tarea', category: 'Casa' });

   Datos y acciones: Items (items.js). Arrastre: Sortable (sortable.js).
   Teclado sobre una tarjeta: Enter edita · Espacio marca · Supr borra · ↑/↓ cambia
   de tarjeta · Alt+↑/↓ la mueve · Alt+←/→ la pasa al grupo de al lado ·
   Alt+Mayús+→ la mete como paso de la anterior · Alt+Mayús+← la saca · X selecciona.
   ========================================================================== */
(function () {
  'use strict';

  const FOLD_KEY = 'items-fold';
  const GROUP_META = {
    inbox: { title: 'Inbox', icon: 'inbox', empty: { pending: 'Sin tareas pendientes', done: 'Ninguna tarea hecha', all: 'Sin tareas' } },
    nota: { title: 'Notas', icon: 'notebook-pen', empty: { pending: 'Ninguna casilla pendiente en tus notas', done: 'Ninguna casilla marcada', all: 'Tus notas no tienen casillas' } },
    ideas: { title: 'Ideas', icon: 'lightbulb', empty: { pending: 'Sin ideas pendientes', done: 'Ninguna idea procesada', all: 'Sin ideas' } },
    rutinas: { title: 'Rutinas', icon: 'repeat', empty: { pending: 'Sin rutinas: crea una con «Rutina» en la captura', done: 'Ninguna rutina hecha hoy', all: 'Sin rutinas' } },
    calendario: { title: 'Próximos eventos', icon: 'calendar', empty: { pending: 'Nada en los próximos 7 días', done: '', all: 'Nada en los próximos 7 días' } },
  };
  const DROP_HINT = { inbox: 'Suelta aquí para dejarla en el Inbox', nota: 'Suelta aquí', ideas: 'Suelta aquí para pasarla a idea', rutinas: 'Suelta aquí para convertirla en rutina' };
  const TYPE_GROUPS = { tarea: ['inbox', 'nota'], idea: ['ideas'], rutina: ['rutinas'] };
  const WEEKDAYS = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];

  /* Próximos eventos (GET /api/calendar/agenda): se ven con la misma tarjeta, sin arrastre */
  let agenda = null, agendaAt = 0, agendaLoading = null;
  function loadAgenda(force = false) {
    if (!force && agenda && Date.now() - agendaAt < 60000) return Promise.resolve(agenda);
    agendaLoading ||= api('/api/calendar/agenda?days=7', { quiet: true })
      .then((d) => { agenda = d.entries.filter((e) => e.kind === 'event'); agendaAt = Date.now(); views.forEach((v) => v.render()); return agenda; })
      .catch(() => { agenda = []; return agenda; })
      .finally(() => { agendaLoading = null; });
    return agendaLoading;
  }
  onDataChange(/^\/api\/calendar/, () => loadAgenda(true));
  const norm = (s) => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const esc = (s) => escapeHtml(s);
  const today = () => new Date().toISOString().slice(0, 10);

  // Plegados en el servidor (Prefs, ui.js): sobreviven a reiniciar y a cambiar de navegador
  let folded = { ...Prefs.get(FOLD_KEY, {}) };
  function saveFold() { Prefs.set(FOLD_KEY, { ...folded }); }
  const views = new Set();
  document.addEventListener('prefs:changed', () => {
    folded = { ...Prefs.get(FOLD_KEY, {}) };
    views.forEach((v) => v.render());
  });

  // Igual que splitCategoryPath() de cerebro.js: «Área - Sub - Más» o «Área->Sub»
  function catPath(category) {
    const parts = String(category || '').replace(/->/g, ' - ').split(/\s+-\s+/).map((p) => p.trim()).filter(Boolean);
    return parts.length ? parts : ['Sin categoría'];
  }

  function linkify(html) {
    return html.replace(/(https?:\/\/[^\s<]+)/g, (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer" class="no-drag">${url.length > 48 ? url.slice(0, 45) + '…' : url}</a>`);
  }

  // Notas de un elemento en modo lectura: Markdown saneado (marked + DOMPurify si están cargados)
  function renderMd(text) {
    if (!window.marked || !window.DOMPurify) return `<p>${linkify(esc(text)).replace(/\n/g, '<br>')}</p>`;
    const html = DOMPurify.sanitize(marked.parse(text, { breaks: true, gfm: true }), { USE_PROFILES: { html: true }, FORBID_ATTR: ['style'] });
    return html.replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ');
  }

  /* ---------- Notas de las tareas: visibles salvo las ocultadas a mano (Prefs) ---------- */
  const NOTES_HIDDEN = 'item-notes-hidden';
  const notesHidden = () => Prefs.get(NOTES_HIDDEN, {}) || {};

  /* ---------- Rutinas: repetición y hábito ---------- */
  const routineMinutes = (it) => it.duration_min || Items.children(it.id).reduce((a, k) => a + (k.duration_min || 0), 0);
  const fmtMin = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ''}` : `${m} min`);

  // Mapa de las últimas 12 semanas (columnas = semanas, filas = días) y racha
  function habitHTML(it) {
    const cells = it.heatmap || [];
    const weeks = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
    const lbl = { done: 'hecha', missed: 'sin hacer', off: 'no tocaba', future: '', pending: 'pendiente hoy' };
    const done = cells.filter((c) => c.state === 'done').length, due = cells.filter((c) => c.state === 'done' || c.state === 'missed').length;
    return `<div class="il-habit no-drag" role="group" aria-label="Hábito de las últimas 12 semanas">
      <div class="habit-grid" role="img" aria-label="${done} de ${due} días hechos en 12 semanas">
        <span class="habit-days" aria-hidden="true">${WEEKDAYS.map((d) => `<span>${d}</span>`).join('')}</span>
        ${weeks.map((w) => `<span class="habit-week">${w.map((c) => `<span class="habit-cell" data-state="${c.state}" title="${c.day}${lbl[c.state] ? ': ' + lbl[c.state] : ''}"></span>`).join('')}</span>`).join('')}
      </div>
      <p class="tiny muted tabular">${icon('flame', 'icon-sm')} Racha ${it.streak?.actual || 0} · mejor ${it.streak?.mejor || 0} · ${due ? Math.round(done / due * 100) : 0} % en 12 semanas</p></div>`;
  }

  /* ---------- Asociar a una rutina o a un bloque suyo (página /rutinas) ---------- */
  async function attachToRoutine(it) {
    const rutinas = Items.state.items.filter((i) => i.type === 'rutina' && !i.parent_id);
    if (!rutinas.length) { toast('Aún no tienes rutinas: créalas en Rutinas', { type: 'info' }); return; }
    const picked = await uiPick({
      title: `Asociar «${it.text.split('\n')[0].slice(0, 40)}»`, placeholder: 'Busca una rutina o un bloque',
      load: () => rutinas.flatMap((r) => [{ id: r.id, label: r.text.split('\n')[0], sub: 'La rutina entera', icon: 'repeat' },
        ...Items.children(r.id).map((k) => ({ id: k.id, label: `${r.text.split('\n')[0]} › ${k.text.split('\n')[0]}`, sub: k.days_text || '', icon: 'corner-down-right' }))]),
    });
    if (picked) await Items.update(it.id, { routine_step: picked.id });
  }

  /* ---------- Enlaces con notas (app/links.py: marcador [[tarea:N]] en la nota) ---------- */
  let notesForLinks = null;
  async function linkToNote(it) {
    const picked = await uiPick({
      title: 'Enlazar con una nota', placeholder: 'Busca una nota por título o categoría',
      load: async () => {
        if (!notesForLinks) notesForLinks = (await api('/api/notes', { quiet: true })).notes.filter((n) => n.status !== 'indice' && !n.encrypted);
        const linked = new Set((it.links || []).map((l) => l.note_id));
        return notesForLinks.filter((n) => !linked.has(n.id)).map((n) => ({ id: n.id, label: n.title || n.id, sub: n.category, icon: 'notebook-pen' }));
      },
    });
    if (!picked) return;
    try {
      await api(`/api/items/${it.id}/links`, { method: 'POST', body: { note_id: picked.id } });
      await Items.load();
      toast(`Enlazada con «${picked.label}»`, { action: { label: 'Abrir', onClick: () => { location.href = `/?note=${encodeURIComponent(picked.id)}`; } } });
    } catch { /* api() ya avisa */ }
  }
  async function unlinkNote(it, link) {
    await api(`/api/items/${it.id}/links/${encodeURIComponent(link.note_id)}`, { method: 'DELETE' });
    await Items.load();
    toast('Enlace quitado', { type: 'info', duration: 1800 });
  }

  function formatDue(d) {
    const dt = new Date(d + 'T00:00:00');
    return dt.toLocaleDateString('es-ES', { day: 'numeric', month: 'short', ...(dt.getFullYear() !== new Date().getFullYear() ? { year: 'numeric' } : {}) });
  }

  // Agarres para redimensionar la tarjeta en la cuadrícula de Tareas (tareas-grid.js); con teclado, Mayús + flechas
  const RESIZE_HANDLES = ['e', 's', 'se'].map((a) => `<span class="il-resize no-drag" data-resize="${a}" aria-hidden="true" title="Arrastra para cambiar el tamaño"></span>`).join('');

  class View {
    constructor(root, opts = {}) {
      this.root = root;
      this.variant = opts.variant || 'page';
      this.filters = { status: 'pending', type: 'all', category: '', q: '', ...(opts.filters || {}) };
      this.selected = new Set();
      this.selectMode = false;
      this.editing = null;     // id en edición
      this.adding = null;      // 'item:<id>' (paso nuevo) o 'note:<id>' (casilla nueva en una nota)
      this.openDetails = new Set();  // elementos con sus notas desplegadas (lectura)
      this.hoverId = null;           // tarjeta bajo el ratón (tecla E)
      this.onRender = opts.onRender;
      this.menuItems = opts.menuItems;
      root.classList.add('il', `il-${this.variant}`);
      root.addEventListener('click', (e) => this.onClick(e));
      root.addEventListener('dblclick', (e) => this.onDblClick(e));
      root.addEventListener('keydown', (e) => this.onKey(e));
      root.addEventListener('submit', (e) => this.onSubmit(e));
      root.addEventListener('mouseover', (e) => { const li = e.target.closest('.il-item'); this.hoverId = li ? Number(li.dataset.id) : null; });
      root.addEventListener('mouseleave', () => { this.hoverId = null; });
      // E con el ratón sobre una tarjeta: añadir un paso. En captura, para que el tablero no la tome por la goma
      document.addEventListener('keydown', (e) => this.onGlobalKey(e), true);
      document.addEventListener('items:changed', () => this.render());
      views.add(this);
      this.bar = document.createElement('div');
      this.bar.className = 'il-bulkbar';
      this.bar.hidden = true;
      this.bar.setAttribute('role', 'toolbar');
      this.bar.setAttribute('aria-label', 'Acciones con la selección');
      root.after(this.bar);
      this.bar.addEventListener('click', (e) => this.onBulk(e));
      root.innerHTML = `<div class="il-skeleton">${'<span class="skeleton skeleton-card"></span>'.repeat(3)}</div>`;
      Items.ready().catch(() => {
        root.innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudo cargar la lista', text: 'Revisa la conexión y recarga.', compact: true });
      });
      if (Items.state.loaded) this.render();
    }

    setFilters(f) { Object.assign(this.filters, f); this.render(); }

    filtering() { return !!(this.filters.q || this.filters.category || this.filters.type !== 'all'); }

    /* ---------- Qué se ve ---------- */
    matches(it) {
      const f = this.filters;
      // Una rutina se repite: hecha hoy sigue en «Pendientes» (marcada)
      if (f.status === 'pending' && it.done && it.type !== 'rutina') return false;
      if (f.status === 'done' && !it.done) return false;
      if (f.type !== 'all' && it.type !== f.type) return false;
      if (f.category) {
        const cat = it.origin === 'nota' ? it.note_category : it.category;
        if (!cat || (norm(cat) !== norm(f.category) && !norm(cat).startsWith(norm(f.category) + ' - '))) return false;
      }
      if (f.q) {
        const q = norm(f.q);
        const hay = [it.text, it.details, it.note_title, it.category, ...Items.children(it.id).map((k) => k.text)].map(norm).join(' ');
        if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
      }
      return true;
    }

    topOf(group) {
      return Items.state.items.filter((it) => !it.parent_id && it.origin === group && this.matches(it));
    }

    /* ---------- Pintado ---------- */
    render() {
      if (!Items.state.loaded) return;
      if (this.editing !== null && !Items.get(this.editing)) this.editing = null;
      const drafts = this.saveDrafts();
      const focusId = document.activeElement?.closest?.('.il-item')?.dataset.id;
      const focusInRow = document.activeElement?.matches?.('[data-act]') ? document.activeElement.dataset.act : null;
      const scroller = this.scroller();
      const top = scroller.scrollTop;
      const inner = new Map([...this.innerScroll()].map(([key, el]) => [key, el.scrollTop]));
      const known = new Set(Items.state.items.map((i) => String(i.id)));
      [...this.selected].forEach((id) => { if (!known.has(String(id))) this.selected.delete(id); });

      // Con el filtro de tipo, solo los grupos que pueden tener ese tipo (en una nota solo hay tareas)
      const groups = ['inbox', 'nota', 'ideas', 'rutinas'].filter((g) => this.filters.type === 'all' || TYPE_GROUPS[this.filters.type]?.includes(g));
      if (this.filters.type === 'all' && this.filters.status !== 'done' && !this.filters.q && !this.filters.category) groups.push('calendario');
      this.root.innerHTML = groups.map((g) => (g === 'calendario' ? this.eventsHTML() : this.groupHTML(g))).join('')
        + `<datalist id="il-cats-${this.variant}">${this.categories().map((c) => `<option value="${esc(c)}">`).join('')}</datalist>`;
      this.root.classList.toggle('is-selecting', this.selectMode);
      this.wireSortables();
      scroller.scrollTop = top;
      if (!this.restoreDrafts(drafts) && focusId) {
        const li = this.root.querySelector(`.il-item[data-id="${focusId}"]`);
        (focusInRow && li?.querySelector(`:scope > .il-row [data-act="${focusInRow}"]`) || li)?.focus({ preventScroll: true });
      }
      this.renderBar();
      this.onRender?.(this);
      // Después de onRender: la cuadrícula da a las tarjetas su tamaño ahí, y sin él no hay a dónde desplazarse
      if (this.onRender) scroller.scrollTop = top;
      this.innerScroll().forEach((el, key) => { if (inner.has(key)) el.scrollTop = inner.get(key); });
      document.dispatchEvent(new CustomEvent('items:rendered'));
    }

    // Lo que se desplaza de verdad: en la app no es el documento (.page-body). Al repintar la cuadrícula, las tarjetas
    // pierden un momento su tamaño, la página encoge y volvería arriba si no se restaura aquí
    scroller() {
      for (let n = this.root.parentElement; n && n !== document.body; n = n.parentElement) {
        if (/(auto|scroll)/.test(getComputedStyle(n).overflowY)) return n;
      }
      return document.scrollingElement;
    }

    // Lo que se desplaza por dentro de una tarjeta en la cuadrícula (pasos y notas), para conservarlo al repintar
    innerScroll() {
      const boxes = this.root.querySelectorAll('.il-children, .il-details, .il-item.is-sized > .il-row');
      return new Map([...boxes].map((el) => [`${el.classList[0]}:${el.closest('.il-item').dataset.id}`, el]));
    }

    // Lo escrito en un editor o en «añadir» abiertos sobrevive a un repintado (cambios de otra pestaña)
    saveDrafts() {
      const forms = [...this.root.querySelectorAll('.il-editor, .il-addform')];
      if (!forms.length) return null;
      const a = document.activeElement;
      return {
        fields: forms.flatMap((f) => [...f.querySelectorAll('input, textarea, select')].map((el) => ({
          key: `${f.dataset.edit || f.dataset.add}|${el.name || el.id}`, value: el.type === 'checkbox' ? el.checked : el.value }))),
        types: forms.filter((f) => f.dataset.edit).map((f) => [f.dataset.edit, f.querySelector('[data-ed-type][aria-pressed="true"]')?.dataset.edType]),
        focus: a && this.root.contains(a) && a.closest('.il-editor, .il-addform') ? {
          key: `${a.closest('form').dataset.edit || a.closest('form').dataset.add}|${a.name || a.id}`,
          start: a.selectionStart, end: a.selectionEnd } : null,
      };
    }

    restoreDrafts(d) {
      if (!d) return false;
      const find = (key) => {
        const [form, name] = key.split('|');
        const f = this.root.querySelector(`[data-edit="${CSS.escape(form)}"], [data-add="${CSS.escape(form)}"]`);
        return f && [...f.querySelectorAll('input, textarea, select')].find((el) => (el.name || el.id) === name);
      };
      d.fields.forEach(({ key, value }) => {
        const el = find(key);
        if (el?.type === 'checkbox') el.checked = value;
        else if (el) el.value = value;
      });
      d.types.forEach(([id, t]) => this.root.querySelectorAll(`[data-edit="${id}"] [data-ed-type]`)
        .forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.edType === t))));
      const el = d.focus && find(d.focus.key);
      if (!el) return false;
      el.focus({ preventScroll: true });
      try { if (d.focus.start != null) el.setSelectionRange(d.focus.start, d.focus.end); } catch {}
      return true;
    }

    categories() {
      const set = new Set();
      Items.state.items.forEach((it) => { if (it.category) set.add(it.category); });
      return [...set].sort((a, b) => a.localeCompare(b, 'es'));
    }

    foldBtn(key, label, open) {
      return `<button type="button" class="btn btn-ghost btn-icon btn-sm il-fold" data-il-fold="${esc(key)}" aria-expanded="${open}" aria-label="${open ? 'Plegar' : 'Desplegar'} ${esc(label)}">${icon('chevron-down', 'icon-sm')}</button>`;
    }

    groupHTML(g) {
      const meta = GROUP_META[g];
      const items = this.topOf(g);
      const key = `${this.variant}:g:${g}`;
      const open = !folded[key];
      let body;
      const emptyText = this.filtering() ? 'Nada coincide con el filtro' : meta.empty[this.filters.status];
      if (g === 'nota') body = this.notesHTML(items);
      else if (g === 'rutinas') body = this.routinesTodayHTML() + this.listHTML(items.sort((a, b) => (b.today - a.today) || (a.due_time || '99').localeCompare(b.due_time || '99')), { target: g }, emptyText);
      else body = this.listHTML(items, { target: g }, emptyText);
      return `<section class="il-group" data-group="${g}" aria-labelledby="il-h-${this.variant}-${g}">
        <header class="il-group-head">
          ${this.foldBtn(key, meta.title, open)}
          <span class="col-icon" data-kind="${g}" aria-hidden="true">${icon(meta.icon, 'icon-sm')}</span>
          <h2 id="il-h-${this.variant}-${g}">${meta.title}</h2>
          <span class="badge tabular" data-count="${g}">${items.length}</span>
          <span class="grow"></span>
          ${g === 'rutinas' ? `<a class="btn btn-ghost btn-sm" href="/rutinas" title="Tus rutinas como la línea del día">${icon('calendar-clock', 'icon-sm')}<span class="hide-mobile">Ver el día</span></a>` : ''}
          ${g === 'rutinas' ? `<button type="button" class="btn btn-ghost btn-sm" data-act="routine-templates" title="Crear una rutina desde una plantilla">${icon('layout-template', 'icon-sm')}<span class="hide-mobile">Plantillas</span></button>` : ''}
          ${g !== 'nota' ? `<button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="add-to" data-type="${Items.typeFor(g)}" aria-label="Nueva ${Items.typeFor(g)}" title="Nueva ${Items.typeFor(g)}">${icon('plus', 'icon-sm')}</button>` : ''}
        </header>
        <div class="il-group-body" ${open ? '' : 'hidden'}>${body}</div>
      </section>`;
    }

    // Próximos eventos del calendario (7 días): misma tarjeta, sin arrastre; se editan en /calendario
    eventsHTML() {
      if (!agenda) loadAgenda();
      const key = `${this.variant}:g:calendario`;
      const open = !folded[key];
      const list = agenda || [];
      const fmt = (e) => {
        const d = new Date(e.start.slice(0, 10) + 'T00:00');
        const today = new Date().toISOString().slice(0, 10);
        const dia = e.start.slice(0, 10) === today ? 'Hoy' : d.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric' });
        return e.all_day ? dia : `${dia} · ${e.start.slice(11, 16)}`;
      };
      const body = !agenda ? '<p class="il-empty">Cargando…</p>' : !list.length ? `<p class="il-empty">${GROUP_META.calendario.empty.all}.</p>`
        : `<ul class="il-evlist" aria-label="Próximos eventos">${list.map((e) => `<li class="il-item il-event" data-kind="event" data-type="${esc(e.type)}">
            <div class="il-row"><span class="il-evdot" aria-hidden="true">${icon(e.type === 'examen' ? 'triangle-alert' : 'calendar', 'icon-sm')}</span>
              <div class="il-body"><a class="il-text il-evlink" href="/calendario?dia=${e.start.slice(0, 10)}">${esc(e.title)}</a>
                <div class="il-meta"><span class="il-chip">${icon('clock', 'icon-sm')}${esc(fmt(e))}</span>${e.type !== 'evento' ? `<span class="tag">${esc(e.type)}</span>` : ''}</div></div></div></li>`).join('')}</ul>`;
      return `<section class="il-group" data-group="calendario" aria-labelledby="il-h-${this.variant}-calendario">
        <header class="il-group-head">${this.foldBtn(key, 'Próximos eventos', open)}
          <span class="col-icon" data-kind="calendario" aria-hidden="true">${icon('calendar', 'icon-sm')}</span>
          <h2 id="il-h-${this.variant}-calendario">Próximos eventos</h2><span class="badge tabular">${list.length}</span><span class="grow"></span>
          <a class="btn btn-ghost btn-icon btn-sm" href="/calendario" aria-label="Abrir el calendario" title="Abrir el calendario">${icon('external-link', 'icon-sm')}</a></header>
        <div class="il-group-body" ${open ? '' : 'hidden'}>${body}</div></section>`;
    }

    // Notas: categoría → subcategoría → nota, cada nivel plegable y con su contador
    notesHTML(items) {
      if (!items.length) {
        if (this.filtering()) return '<p class="il-empty">Nada coincide con el filtro.</p>';
        const t = GROUP_META.nota.empty[this.filters.status];
        return `<p class="il-empty">${esc(t)}. Escribe <code>- [ ] algo</code> en una nota o arrastra aquí una tarea con la nota abierta en su grupo.</p>`;
      }
      const tree = new Map();
      items.forEach((it) => {
        const [area, ...rest] = catPath(it.note_category);
        const sub = rest.join(' · ');
        if (!tree.has(area)) tree.set(area, new Map());
        const subs = tree.get(area);
        if (!subs.has(sub)) subs.set(sub, new Map());
        const notes = subs.get(sub);
        if (!notes.has(it.note_id)) notes.set(it.note_id, { title: it.note_title || it.note_id, pos: it.note_position, items: [] });
        notes.get(it.note_id).items.push(it);
      });
      const byName = (a, b) => (a[0] === 'Sin categoría') - (b[0] === 'Sin categoría') || a[0].localeCompare(b[0], 'es');
      const count = (m) => [...m.values()].reduce((n, v) => n + (v instanceof Map ? count(v) : v.items.length), 0);
      return [...tree.entries()].sort(byName).map(([area, subs]) => {
        const aKey = `${this.variant}:c:${area}`;
        const aOpen = !folded[aKey];
        const subHTML = [...subs.entries()].sort(byName).map(([sub, notes]) => {
          const notesHTML = [...notes.entries()].sort((a, b) => ((a[1].pos ?? Infinity) - (b[1].pos ?? Infinity)) || a[1].title.localeCompare(b[1].title, 'es')).map(([nid, n]) => this.noteHTML(nid, n)).join('');
          if (!sub) return notesHTML;
          const sKey = `${this.variant}:c:${area}/${sub}`;
          const sOpen = !folded[sKey];
          return `<div class="il-cat il-subcat">
            <div class="il-cat-head">${this.foldBtn(sKey, sub, sOpen)}<h4>${esc(sub)}</h4><span class="badge tabular">${count(notes)}</span></div>
            <div class="il-cat-body" ${sOpen ? '' : 'hidden'}>${notesHTML}</div></div>`;
        }).join('');
        return `<div class="il-cat">
          <div class="il-cat-head">${this.foldBtn(aKey, area, aOpen)}<span aria-hidden="true">${icon('folder', 'icon-sm')}</span><h3>${esc(area)}</h3><span class="badge tabular">${count(subs)}</span></div>
          <div class="il-cat-body" ${aOpen ? '' : 'hidden'}>${subHTML}</div></div>`;
      }).join('');
    }

    noteHTML(noteId, n) {
      const key = `${this.variant}:n:${noteId}`;
      const open = !folded[key];
      return `<div class="il-note" data-note="${esc(noteId)}">
        <div class="il-note-head">${this.foldBtn(key, n.title, open)}
          <a class="il-note-title" href="/?note=${encodeURIComponent(noteId)}" title="Abrir la nota">${icon('notebook-pen', 'icon-sm')}<span>${esc(n.title)}</span></a>
          <span class="badge tabular">${n.items.length}</span><span class="grow"></span>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="add-note" data-note="${esc(noteId)}" aria-label="Nueva tarea en «${esc(n.title)}»" title="Nueva tarea en esta nota">${icon('plus', 'icon-sm')}</button>
        </div>
        <div class="il-note-body" ${open ? '' : 'hidden'}>
          ${this.listHTML(n.items, { target: 'nota', note: noteId }, '')}
          ${this.adding === `note:${noteId}` ? this.addFormHTML(`note:${noteId}`, 'Nueva tarea en esta nota…') : ''}
        </div></div>`;
    }

    // Resumen de las rutinas de hoy: cuántas van, la siguiente y empezarla (o crear la primera)
    routinesTodayHTML() {
      if (this.filters.status === 'done') return '';
      const all = Items.state.items.filter((i) => i.type === 'rutina' && !i.parent_id);
      if (!all.length) {
        return `<div class="rt-today is-empty"><span class="grow small muted">Organiza el día con rutinas por pasos: mañana, estudio, gimnasio…</span>
          <button type="button" class="btn btn-tinted btn-sm" data-act="routine-templates">${icon('layout-template', 'icon-sm')}Empezar con una plantilla</button></div>`;
      }
      const hoy = all.filter((i) => i.today);
      if (!hoy.length) return '';
      const done = hoy.filter((i) => i.done).length;
      const next = hoy.filter((i) => !i.done).sort((a, b) => (a.due_time || '99').localeCompare(b.due_time || '99'))[0];
      return `<div class="rt-today">
        <span class="rt-today-main"><span class="small"><b>${done === hoy.length ? 'Rutinas de hoy hechas' : 'Rutinas de hoy'}</b> <span class="muted tabular">· ${done} de ${hoy.length}</span></span>
          <span class="tiny muted">${next ? `Siguiente: ${esc(next.text.split('\n')[0].slice(0, 50))}${next.due_time ? ` · ${next.due_time}` : ''}` : 'Todo hecho. ¡Buena racha!'}</span></span>
        ${next && Items.children(next.id).length ? `<button type="button" class="btn btn-tinted btn-sm" data-act="run-routine" data-run="${next.id}">${icon('play', 'icon-sm')}Empezar</button>` : ''}
      </div>`;
    }

    listHTML(items, { target, note = '' }, emptyText) {
      return `<ul class="il-list" data-zone data-target="${target}" ${note ? `data-note="${esc(note)}"` : ''} data-empty="${esc(emptyText || DROP_HINT[target])}"
        aria-label="${esc(GROUP_META[target].title)}">${items.map((it) => this.itemHTML(it)).join('')}</ul>`;
    }

    itemHTML(it, child = false) {
      const kids = child ? [] : Items.children(it.id);
      const fkey = `i:${it.id}`;
      const open = !folded[fkey];
      const sel = this.selected.has(it.id);
      const editing = this.editing === it.id;
      const label = it.text.split('\n')[0].slice(0, 50);
      const doneKids = kids.filter((k) => k.done).length;
      const meta = [];
      if (kids.length) meta.push(`<span class="il-chip tabular" title="Pasos hechos">${icon('list-checks', 'icon-sm')}${doneKids}/${kids.length}</span>`);
      const isStep = it.type === 'rutina' && it.parent_id;
      if (isStep) {  // paso de una rutina: su hora y su duración
        if (it.due_time) meta.push(`<span class="il-chip tabular" title="Empieza a las ${it.due_time}">${icon('clock', 'icon-sm')}${it.due_time}</span>`);
        if (it.duration_min) meta.push(`<span class="il-chip tabular" title="Duración">${icon('timer', 'icon-sm')}${fmtMin(it.duration_min)}</span>`);
        if (it.days_text) meta.push(`<span class="il-chip${it.today === false ? ' subtle' : ''}" title="Días en que toca este bloque">${icon('calendar', 'icon-sm')}${esc(it.days_text)}</span>`);
      } else if (it.type === 'rutina') {
        const mins = kids.length ? routineMinutes(it) : 0;
        meta.push(`<span class="il-chip" title="Se repite">${icon('repeat', 'icon-sm')}${esc(it.repeat_text || 'Cada día')}${it.due_time ? ` · ${it.due_time}` : ''}${mins ? ` · ${fmtMin(mins)}` : ''}</span>`);
        if (it.streak?.actual) meta.push(`<span class="il-chip il-streak" title="Racha actual (mejor: ${it.streak.mejor})">${icon('flame', 'icon-sm')}${it.streak.actual}</span>`);
        if (!it.today) meta.push('<span class="il-chip subtle">Hoy no toca</span>');
      }
      if (it.due_date) {
        const late = !it.done && it.due_date < today();
        meta.push(`<a class="il-chip il-due no-drag${late ? ' is-late' : it.due_date === today() ? ' is-today' : ''}" href="/calendario?dia=${it.due_date}" title="Ver en el calendario">${icon(it.due_time ? 'calendar-clock' : 'calendar', 'icon-sm')}<time datetime="${it.due_date}">${it.due_date === today() ? 'Hoy' : formatDue(it.due_date)}${it.due_time ? ` ${it.due_time}` : ''}</time>${it.due_time && it.duration_min ? ` · ${it.duration_min} min` : ''}</a>`);
      }
      if (it.routine_label) meta.push(`<a class="il-chip il-routine no-drag" href="/rutinas" title="Va en este bloque de una rutina">${icon('repeat', 'icon-sm')}${esc(it.routine_label)}</a>`);
      if (it.priority) meta.push(`<span class="tag prio" data-prio="${esc(it.priority)}">${icon('flag', 'icon-sm')}${esc(Items.PRIO[it.priority] || it.priority)}</span>`);
      if (it.category && it.origin !== 'nota') meta.push(`<span class="tag">${icon('tag', 'icon-sm')}${esc(it.category)}</span>`);
      // notas: se ven siempre salvo que se hayan ocultado en esa tarea (Prefs, sobrevive a reiniciar);
      // el mapa del hábito de una rutina, al revés: plegado hasta que se pide
      const showDet = it.type === 'rutina' ? this.openDetails.has(it.id) : !!it.details && !notesHidden()[it.id];
      if (it.type === 'rutina' && !isStep) meta.push(`<button type="button" class="il-chip il-chip-btn no-drag" data-act="details" aria-expanded="${showDet}" title="Ver el hábito de las últimas semanas">${icon('activity', 'icon-sm')}Hábito</button>`);
      if (it.details && it.type !== 'rutina') meta.push(`<button type="button" class="il-chip il-chip-btn no-drag" data-act="details" aria-expanded="${showDet}" title="${showDet ? 'Ocultar las notas' : 'Leer las notas'}">${icon('file-text', 'icon-sm')}Notas</button>`);
      (it.links || []).forEach((l) => meta.push(`<a class="card-link no-drag" href="/?note=${encodeURIComponent(l.note_id)}" title="Abrir la nota enlazada">${icon('notebook-pen', 'icon-sm')}${esc(l.title)}</a>`));
      if (it.origin !== 'nota' && it.note_id) meta.push(`<a class="card-link no-drag" href="/?note=${encodeURIComponent(it.note_id)}">${icon('link', 'icon-sm')}En una nota</a>`);
      if (it.origin !== 'nota' && !child && this.variant === 'sidebar') meta.push(`<time class="il-when" datetime="${new Date(it.created_at * 1000).toISOString()}">${timeAgo(it.created_at)}</time>`);

      return `<li class="il-item${child ? ' il-child' : ''}${it.done ? ' is-done' : ''}${sel ? ' is-selected' : ''}${this.flashId === it.id ? ' is-flash' : ''}" data-id="${it.id}" data-type="${it.type}" data-origin="${it.origin}"
          aria-label="${esc(label)}${it.done ? ' (hecha)' : ''}">
        <div class="il-row">
          <button type="button" class="drag-handle" data-drag-handle aria-label="Mover «${esc(label)}» (Alt + flechas)">${icon('grip-vertical', 'icon-sm')}</button>
          <button type="button" class="il-select" data-act="select" role="checkbox" aria-checked="${sel}" aria-label="Seleccionar «${esc(label)}»" tabindex="${this.selectMode ? 0 : -1}">${icon('check', 'icon-sm')}</button>
          <button type="button" class="card-check${child ? ' small-check' : ''}${it.done ? ' done' : ''}${it.type === 'rutina' ? ' is-routine' : ''}" data-act="done" role="checkbox" aria-checked="${it.done}"
            ${it.type === 'rutina' && !it.today ? 'disabled title="Hoy no toca"' : ''}
            aria-label="${it.done ? 'Volver a pendiente' : ({ idea: 'Marcar como procesada', rutina: 'Hecha hoy' }[it.type] || 'Marcar como hecha')}: ${esc(label)}">${icon('check', 'icon-sm')}</button>
          <div class="il-body">
            ${editing ? this.editorHTML(it, kids.length) : `<p class="il-text" data-act="edit-text">${linkify(esc(it.text))}</p>
            ${meta.length ? `<div class="il-meta">${meta.join('')}</div>` : ''}
            ${showDet && it.type === 'rutina' && !isStep ? habitHTML(it) : ''}
            ${showDet && it.details ? `<div class="il-details no-drag"><div class="il-details-md md">${renderMd(it.details)}</div>
              <button type="button" class="btn btn-ghost btn-sm" data-act="edit-details">${icon('pencil', 'icon-sm')}Editar notas</button></div>` : ''}`}
          </div>
          ${!child && !editing && it.type === 'rutina' && kids.length && it.today && !it.done ? `<button type="button" class="btn btn-tinted btn-icon btn-sm il-run" data-act="run-routine" aria-label="Empezar «${esc(label)}» paso a paso" title="Empezar paso a paso">${icon('play', 'icon-sm')}</button>` : ''}
          ${!child && !editing ? `<button type="button" class="btn btn-ghost btn-icon btn-sm il-addstep" data-act="add-step" aria-label="Añadir un paso a «${esc(label)}»" title="Añadir un paso (E)">${icon('circle-plus', 'icon-sm')}</button>` : ''}
          ${kids.length ? this.foldBtn(fkey, label, open).replace('il-fold', 'il-fold il-kids-fold') : ''}
          <button type="button" class="btn btn-ghost btn-icon btn-sm il-more" data-act="menu" aria-label="Acciones de «${esc(label)}»" aria-haspopup="menu" aria-expanded="false">${icon('ellipsis', 'icon-sm')}</button>
        </div>
        ${child ? '' : `<ul class="il-children" data-parent="${it.id}" data-target="${it.origin}" ${it.note_id && it.origin === 'nota' ? `data-note="${esc(it.note_id)}"` : ''}
            aria-label="Pasos de «${esc(label)}»" ${open ? '' : 'data-folded'}>${open ? kids.map((k) => this.itemHTML(k, true)).join('') : ''}</ul>
          ${this.variant === 'page' ? RESIZE_HANDLES : ''}
          ${this.adding === `item:${it.id}` ? this.addFormHTML(`item:${it.id}`, it.type === 'rutina' ? 'Nuevo paso (p. ej. «Ducha 10 min»)…' : 'Nuevo paso…') : ''}`}
      </li>`;
    }

    addFormHTML(key, placeholder) {
      const id = `il-add-${this.variant}-${key.replace(/\W/g, '-')}`;
      return `<form class="il-addform" data-add="${esc(key)}"><label class="sr-only" for="${id}">${esc(placeholder)}</label>
        <input id="${id}" class="input input-sm" maxlength="2000" placeholder="${esc(placeholder)}" autocomplete="off">
        <button type="submit" class="btn btn-tinted btn-sm">Añadir</button>
        <button type="button" class="btn btn-ghost btn-sm" data-act="add-cancel">Cancelar</button></form>`;
    }

    editorHTML(it, nKids) {
      const isNote = it.origin === 'nota';
      const lockType = isNote ? 'Una casilla de una nota es una tarea (sácala de la nota para hacerla idea)' : it.parent_id ? 'Un paso tiene el tipo de su elemento' : nKids ? 'Tiene pasos' : '';
      const id = `il-ed-${this.variant}-${it.id}`;
      const isStep = it.type === 'rutina' && it.parent_id;
      return `<form class="il-editor no-drag" data-edit="${it.id}">
        <label class="sr-only" for="${id}">Texto</label>
        <textarea id="${id}" name="text" class="textarea" rows="${Math.min(6, Math.max(2, it.text.split('\n').length))}" maxlength="20000">${esc(it.text)}</textarea>
        <div class="il-editor-grid">
          <div class="segmented" role="group" aria-label="Tipo" ${lockType ? `title="${esc(lockType)}"` : ''}>
            <button type="button" data-ed-type="tarea" aria-pressed="${it.type === 'tarea'}" ${lockType ? 'disabled' : ''}>${icon('square-check', 'icon-sm')}Tarea</button>
            <button type="button" data-ed-type="idea" aria-pressed="${it.type === 'idea'}" ${lockType ? 'disabled' : ''}>${icon('lightbulb', 'icon-sm')}Idea</button>
            <button type="button" data-ed-type="rutina" aria-pressed="${it.type === 'rutina'}" ${lockType ? 'disabled' : ''}>${icon('repeat', 'icon-sm')}Rutina</button>
          </div>
          <label class="field"><span class="field-label">Categoría</span>
            <input class="input input-sm" name="category" list="il-cats-${this.variant}" maxlength="60" value="${esc(isNote ? it.note_category || '' : it.category || '')}" ${isNote ? 'disabled title="La de su nota"' : ''} placeholder="Sin categoría"></label>
          <label class="field"><span class="field-label">Prioridad</span>
            <select class="select input-sm" name="priority"><option value="">Sin prioridad</option>
              ${Object.entries(Items.PRIO).map(([k, v]) => `<option value="${k}" ${it.priority === k ? 'selected' : ''}>${v.replace('Prioridad ', '')}</option>`).join('')}</select></label>
          ${isStep ? '' : it.type === 'rutina' ? dayPicker({ rule: it.repeat || { freq: 'daily' }, legend: 'Se repite', note: everyNote(it.repeat, it.repeat_text || '') })
            : `<label class="field"><span class="field-label">Fecha</span>
            <input class="input input-sm" type="date" name="due_date" value="${esc(it.due_date || '')}"></label>`}
          <label class="field"><span class="field-label">Hora</span>
            <input class="input input-sm" type="time" name="due_time" value="${esc(it.due_time || '')}"></label>
          <label class="field"><span class="field-label">Duración (min)</span>
            <input class="input input-sm" type="number" name="duration_min" min="${it.type === 'rutina' ? 1 : 5}" max="1440" step="${it.type === 'rutina' ? 1 : 5}" value="${it.duration_min || ''}" placeholder="${isStep ? 10 : it.type === 'rutina' ? 30 : 60}"></label>
        </div>
        <label class="field"><span class="field-label">Notas</span>
          <textarea name="details" class="textarea" rows="2" maxlength="20000" placeholder="Detalles, enlaces…">${esc(it.details || '')}</textarea></label>
        <div class="row il-editor-actions">
          <button type="submit" class="btn btn-primary btn-sm">Guardar</button>
          <button type="button" class="btn btn-sm" data-act="cancel-edit">Cancelar</button>
          <span class="tiny subtle hide-mobile"><kbd>Ctrl</kbd>+<kbd>Enter</kbd> guarda · <kbd>Esc</kbd> cancela</span>
        </div>
      </form>`;
    }

    /* ---------- Arrastre ---------- */
    destOf(list) {
      const parent = list.dataset.parent ? Number(list.dataset.parent) : null;
      return { target: list.dataset.target, note_id: list.dataset.note || null, parent_id: parent };
    }

    wireSortables() {
      this.root.querySelectorAll('.il-list, .il-children').forEach((list) => {
        const isKids = list.classList.contains('il-children');
        const dest = this.destOf(list);
        const label = isKids ? `los pasos de «${(Items.get(dest.parent_id)?.text || '').slice(0, 30)}»`
          : dest.note_id ? `la nota «${list.closest('.il-note')?.querySelector('.il-note-title span')?.textContent || ''}»` : GROUP_META[dest.target].title;
        Sortable.create(list, {
          group: 'items', items: '.il-item', handle: '[data-drag-handle]', keyboard: !isKids, label,
          nest: isKids ? null : (li) => li.querySelector(':scope > .il-children'), nestRow: ':scope > .il-row',
          id: (el) => el.dataset.id, data: dest,
          accepts: (ctx) => Items.moveError(Number(ctx.id), ctx.to.data),
          onDrop: (ctx) => Items.move(Number(ctx.id), { ...ctx.to.data, before_id: ctx.beforeId ? Number(ctx.beforeId) : null }),
        });
      });
    }

    /* ---------- Acciones de una tarjeta ---------- */
    itemOf(el) {
      const li = el.closest('.il-item');
      return li ? Items.get(Number(li.dataset.id)) : null;
    }

    toggleFold(key) {
      folded[key] = !folded[key];
      if (!folded[key]) delete folded[key];
      saveFold();
      this.render();
    }

    startEdit(it) {
      this.editing = it.id;
      this.adding = null;
      this.render();
      const ta = this.root.querySelector(`[data-edit="${it.id}"] textarea[name=text]`);
      ta?.focus();
      ta?.setSelectionRange(ta.value.length, ta.value.length);
    }

    stopEdit(focusId) {
      this.editing = null;
      this.render();
      if (focusId) this.root.querySelector(`.il-item[data-id="${focusId}"]`)?.focus();
    }

    async saveEdit(form) {
      const it = Items.get(Number(form.dataset.edit));
      if (!it) return this.stopEdit();
      const f = form.elements;
      const patch = {};
      const text = f.text.value.trim();
      if (!text) { f.text.focus(); return; }
      if (text !== it.text) patch.text = text;
      const type = form.querySelector('[data-ed-type][aria-pressed="true"]')?.dataset.edType;
      if (type && type !== it.type) patch.type = type;
      if (it.origin !== 'nota' && f.category.value.trim() !== (it.category || '')) patch.category = f.category.value.trim();
      if (f.priority.value !== (it.priority || '')) patch.priority = f.priority.value;
      if (f.due_date && f.due_date.value !== (it.due_date || '')) patch.due_date = f.due_date.value;
      if (f.due_time && f.due_time.value !== (it.due_time || '')) patch.due_time = f.due_time.value;
      const dur = parseInt(f.duration_min.value, 10) || 0;
      if (dur !== (it.duration_min || 0)) patch.duration_min = dur;
      if (form.querySelector('[data-day]')) {
        const rep = repeatFromDays(form, it.repeat);
        if (!rep) { toast('Elige al menos un día', { type: 'info' }); return; }
        if (JSON.stringify(rep) !== JSON.stringify(it.repeat || { freq: 'daily' })) patch.repeat = rep;
      }
      if (f.details.value.trim() !== (it.details || '')) patch.details = f.details.value.trim();
      const btn = form.querySelector('[type=submit]');
      btn.classList.add('is-loading');
      try {
        if (Object.keys(patch).length) await Items.update(it.id, patch);
        this.stopEdit(it.id);
      } catch { btn.classList.remove('is-loading'); }
    }

    startAdd(key) {
      this.adding = key;
      this.editing = null;
      if (key.startsWith('item:')) { delete folded[`i:${key.slice(5)}`]; saveFold(); }
      this.render();
      this.root.querySelector(`[data-add="${CSS.escape(key)}"] input`)?.focus();
    }

    stopAdd() {
      this.adding = null;
      this.render();
    }

    async submitAdd(form) {
      const input = form.querySelector('input');
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      const key = form.dataset.add;
      // Vacío antes de guardar: el repintado que provoca el alta restauraría el borrador
      input.value = '';
      input.disabled = true;
      try {
        if (key.startsWith('item:')) await Items.create({ text, parent_id: Number(key.slice(5)) });
        else await Items.create({ text, type: 'tarea', note_id: key.slice(5) });
        this.render();  // el formulario sigue abierto (y vacío) para el siguiente
        const next = this.root.querySelector(`[data-add="${CSS.escape(key)}"] input`);
        if (next) { next.value = ''; next.focus(); }
      } catch {
        const again = this.root.querySelector(`[data-add="${CSS.escape(key)}"] input`) || input;
        again.disabled = false;
        again.value = text;
      }
    }

    // Hermanos visibles (en el orden en que se ven) para Subir/Bajar y anidar
    siblingsOf(it) {
      const li = this.root.querySelector(`.il-item[data-id="${it.id}"]`);
      if (!li) return { list: null, ids: [] };
      return { list: li.parentElement, ids: [...li.parentElement.children].filter((c) => c.matches('.il-item')).map((c) => Number(c.dataset.id)) };
    }

    async moveBy(it, delta) {
      const { list, ids } = this.siblingsOf(it);
      const i = ids.indexOf(it.id);
      if (!list || i < 0 || i + delta < 0 || i + delta >= ids.length) return;
      const rest = ids.filter((x) => x !== it.id);  // sin ella, su nuevo sitio es i + delta
      await this.tryMove(it, { ...this.destOf(list), before_id: rest[i + delta] ?? null });
    }

    async nest(it) {
      if (it.parent_id) return;
      const { ids } = this.siblingsOf(it);
      const prev = ids[ids.indexOf(it.id) - 1];
      if (!prev) { toast('No hay ninguna tarjeta encima en la que meterla', { type: 'info' }); return; }
      await this.tryMove(it, { parent_id: prev, before_id: null });
    }

    async unnest(it) {
      const p = it.parent_id && Items.get(it.parent_id);
      if (!p) return;
      const { ids } = this.siblingsOf(p);
      const after = ids[ids.indexOf(p.id) + 1] ?? null;
      await this.tryMove(it, { target: p.origin, note_id: p.origin === 'nota' ? p.note_id : null, parent_id: null, before_id: after });
    }

    async tryMove(it, dest) {
      const verdict = Items.moveError(it.id, dest);
      if (verdict !== true) { toast(verdict, { type: 'info' }); return; }
      try { await Items.move(it.id, dest); } catch (err) { toast(err.message || 'No se pudo mover', { type: 'error' }); return; }
      this.root.querySelector(`.il-item[data-id="${it.id}"]`)?.focus();
    }

    menu(it, anchor) {
      const kids = Items.children(it.id).length;
      const groups = ['inbox', 'ideas', 'rutinas'].filter((g) => g !== it.origin || it.parent_id);
      const goTo = (g) => this.tryMove(it, { target: g, parent_id: null, before_id: null });
      openMenu(anchor, [
        { label: it.done ? 'Volver a pendiente' : (it.type === 'idea' ? 'Marcar como procesada' : 'Marcar como hecha'), icon: it.done ? 'rotate-ccw' : 'check', onClick: () => Items.setDone(it.id, !it.done) },
        { label: 'Editar', icon: 'pencil', onClick: () => this.startEdit(it) },
        !it.parent_id && { label: 'Añadir un paso (E)', icon: 'circle-plus', onClick: () => this.startAdd(`item:${it.id}`) },
        it.type === 'rutina' && !it.parent_id && kids && { label: 'Hacer paso a paso', icon: 'play', onClick: () => Routines.run(it.id) },
        it.type === 'rutina' && !it.parent_id && { label: 'Guardar como plantilla…', icon: 'layout-template', onClick: () => Routines.saveTemplate(it.id) },
        it.type !== 'rutina' && { label: 'Ver en el calendario', icon: 'calendar', onClick: () => { location.href = `/calendario${it.due_date ? `?dia=${it.due_date}` : ''}`; } },
        !it.parent_id && it.type !== 'rutina' && { label: 'Tablero de la tarea…', icon: 'kanban', onClick: () => {
          if (window.__board?.openForItem) window.__board.openForItem(it.id);
          else location.href = `/inbox?tablero=${it.id}`;
        } },
        { label: 'Enlazar con una nota…', icon: 'link', onClick: () => linkToNote(it) },
        it.type !== 'rutina' && { label: it.routine_step ? 'Cambiar de bloque de rutina…' : 'Asociar a una rutina…', icon: 'repeat', onClick: () => attachToRoutine(it) },
        it.type !== 'rutina' && it.routine_step && { label: 'Quitar de la rutina', icon: 'unlink', onClick: () => Items.update(it.id, { routine_step: 0 }) },
        ...(it.links || []).map((l) => ({ label: `Quitar enlace con «${l.title.slice(0, 30)}»`, icon: 'unlink', onClick: () => unlinkNote(it, l) })),
        { label: 'Prioridad…', icon: 'flag', onClick: () => this.priorityMenu([it.id], anchor, it.priority) },
        ...(this.menuItems?.(it) || []),
        { separator: true },
        { label: 'Subir', icon: 'chevron-up', onClick: () => this.moveBy(it, -1) },
        { label: 'Bajar', icon: 'chevron-down', onClick: () => this.moveBy(it, 1) },
        !it.parent_id && !kids && { label: 'Meter como paso de la anterior', icon: 'corner-down-right', onClick: () => this.nest(it) },
        it.parent_id && { label: 'Sacar de su elemento', icon: 'arrow-left', onClick: () => this.unnest(it) },
        ...groups.map((g) => ({ label: `Mover a ${GROUP_META[g].title}`, icon: GROUP_META[g].icon, onClick: () => goTo(g) })),
        !it.parent_id && { label: 'Llevar a una nota…', icon: 'file-plus', onClick: () => openNoteDialog([it.id]) },
        it.origin === 'nota' && { label: 'Abrir la nota', icon: 'external-link', onClick: () => { location.href = `/?note=${encodeURIComponent(it.note_id)}`; } },
        { separator: true },
        { label: 'Seleccionar', icon: 'list-checks', onClick: () => { this.selectMode = true; this.toggleSelect(it.id, true); } },
        { label: 'Eliminar', icon: 'trash-2', danger: true, onClick: () => Items.remove(it.id) },
      ].filter(Boolean));
    }

    priorityMenu(ids, anchor, current) {
      const set = (p) => (ids.length === 1 ? Items.update(ids[0], { priority: p }) : Items.bulk(ids, 'priority', { value: p }));
      openMenu(anchor, [
        ...Object.entries(Items.PRIO).map(([k, v]) => ({ label: (current === k ? '✓ ' : '') + v, icon: 'flag', onClick: () => set(k) })),
        { separator: true }, { label: 'Sin prioridad', icon: 'x', onClick: () => set('') },
      ]);
    }

    /* ---------- Selección y lote ---------- */
    toggleSelect(id, on = !this.selected.has(id)) {
      if (on) this.selected.add(id); else this.selected.delete(id);
      if (!this.selected.size) this.selectMode = false;
      this.render();
    }

    selectRange(id) {
      const all = [...this.root.querySelectorAll('.il-item')].map((li) => Number(li.dataset.id));
      const last = this.lastSelected ?? id;
      const [a, b] = [all.indexOf(last), all.indexOf(id)].sort((x, y) => x - y);
      all.slice(a, b + 1).forEach((x) => this.selected.add(x));
      this.selectMode = true;
      this.render();
    }

    clearSelection() {
      this.selected.clear();
      this.selectMode = false;
      this.render();
    }

    renderBar() {
      const n = this.selected.size;
      this.bar.hidden = !this.selectMode && !n;
      if (this.bar.hidden) return;
      this.bar.innerHTML = `<span class="il-bulk-count tabular" aria-live="polite">${n ? `${n} seleccionad${n === 1 ? 'o' : 'os'}` : 'Toca para seleccionar'}</span>
        <span class="grow"></span>
        <button type="button" class="btn btn-sm" data-bulk="done" ${n ? '' : 'disabled'}>${icon('check', 'icon-sm')}<span class="hide-mobile">Completar</span><span class="sr-only show-mobile">Completar</span></button>
        <button type="button" class="btn btn-sm" data-bulk="move" ${n ? '' : 'disabled'} aria-haspopup="menu">${icon('arrow-left-right', 'icon-sm')}<span class="hide-mobile">Mover</span><span class="sr-only show-mobile">Mover</span></button>
        <button type="button" class="btn btn-sm" data-bulk="category" ${n ? '' : 'disabled'}>${icon('tag', 'icon-sm')}<span class="hide-mobile">Categoría</span><span class="sr-only show-mobile">Categoría</span></button>
        <button type="button" class="btn btn-sm" data-bulk="more" ${n ? '' : 'disabled'} aria-label="Más acciones" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
        <button type="button" class="btn btn-sm btn-danger" data-bulk="delete" ${n ? '' : 'disabled'}>${icon('trash-2', 'icon-sm')}<span class="hide-mobile">Borrar</span><span class="sr-only show-mobile">Borrar</span></button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-bulk="close" aria-label="Terminar la selección">${icon('x', 'icon-sm')}</button>`;
    }

    async onBulk(e) {
      const b = e.target.closest('[data-bulk]');
      if (!b) return;
      const ids = [...this.selected];
      const act = b.dataset.bulk;
      if (act === 'close') return this.clearSelection();
      if (!ids.length) return;
      if (act === 'done') { await Items.bulk(ids, ids.every((i) => Items.get(i)?.done) ? 'reopen' : 'done'); this.clearSelection(); }
      if (act === 'delete') { await Items.remove(ids); this.clearSelection(); }
      if (act === 'category') {
        const value = await uiPrompt('Categoría', { label: 'Para los elementos del Inbox y de Ideas (vacío la quita)', confirmLabel: 'Aplicar' });
        if (value === null) return;
        await Items.bulk(ids, 'category', { value: value.trim() });
      }
      if (act === 'more') this.priorityMenu(ids, b, null);
      if (act === 'move') {
        openMenu(b, [
          { label: 'Al Inbox', icon: 'inbox', onClick: async () => { await Items.bulk(ids, 'move', { target: 'inbox' }); this.clearSelection(); } },
          { label: 'A Ideas', icon: 'lightbulb', onClick: async () => { await Items.bulk(ids, 'move', { target: 'ideas' }); this.clearSelection(); } },
          { label: 'A una nota…', icon: 'notebook-pen', onClick: () => openNoteDialog(ids, () => this.clearSelection()) },
        ]);
      }
    }

    // Despliega lo que haga falta para que se vea un elemento (grupo, categoría, nota, padre)
    reveal(id) {
      const it = Items.get(id);
      if (!it) return null;
      const top = it.parent_id ? Items.get(it.parent_id) || it : it;
      const keys = [`${this.variant}:g:${top.origin}`, `i:${top.id}`];
      if (top.origin === 'nota') {
        const [area, ...rest] = catPath(top.note_category);
        keys.push(`${this.variant}:c:${area}`, `${this.variant}:n:${top.note_id}`);
        if (rest.length) keys.push(`${this.variant}:c:${area}/${rest.join(' · ')}`);
      }
      if (keys.some((k) => folded[k])) { keys.forEach((k) => delete folded[k]); saveFold(); }
      this.render();
      return this.root.querySelector(`.il-item[data-id="${id}"]`);
    }

    // Resalta un elemento unos segundos (sobrevive a los repintados)
    flash(id) {
      this.flashId = id;
      this.root.querySelector(`.il-item[data-id="${id}"]`)?.classList.add('is-flash');
      clearTimeout(this.flashTimer);
      this.flashTimer = setTimeout(() => { this.flashId = null; this.root.querySelector('.is-flash')?.classList.remove('is-flash'); }, 2400);
    }

    // Paso nuevo para un elemento (si es un paso, para su elemento: solo hay un nivel)
    stepFor(it) {
      const top = it.parent_id ? Items.get(it.parent_id) : it;
      if (top) this.startAdd(`item:${top.id}`);
    }

    // Tecla E con el ratón sobre una tarjeta (nunca mientras se escribe en un campo)
    onGlobalKey(e) {
      if (e.key !== 'e' && e.key !== 'E') return;
      if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented || this.hoverId == null) return;
      const t = e.target;
      if (t.isContentEditable || /^(input|textarea|select)$/i.test(t.tagName || '') || document.querySelector('dialog[open]')) return;
      if (this.root.contains(t) && t.closest?.('.il-item')) return;  // con el foco en una tarjeta ya lo hace onKey
      const it = Items.get(this.hoverId);
      if (!it || !this.root.isConnected || !this.root.offsetParent) return;
      e.preventDefault();
      e.stopPropagation();
      this.stepFor(it);
    }

    /* ---------- Eventos ---------- */
    onClick(e) {
      const fold = e.target.closest("[data-il-fold]");
      if (fold) { this.toggleFold(fold.dataset.ilFold); return; }
      const actEl = e.target.closest('[data-act]');
      const act = actEl?.dataset.act;
      if (act === 'add-to') { openQuickAdd(actEl.dataset.type); return; }
      if (act === 'add-note') { this.startAdd(`note:${actEl.dataset.note}`); return; }
      if (act === 'routine-templates') { Routines.openTemplates(); return; }
      if (act === 'run-routine' && actEl.dataset.run) { Routines.run(Number(actEl.dataset.run)); return; }
      if (act === 'add-cancel') { this.stopAdd(); return; }
      const it = this.itemOf(e.target);
      if (!it) return;
      const li = e.target.closest('.il-item');
      if (e.target.closest('.il-editor')) {
        const tb = e.target.closest('[data-ed-type]');
        if (tb && !tb.disabled) tb.parentElement.querySelectorAll('[data-ed-type]').forEach((x) => x.setAttribute('aria-pressed', String(x === tb)));
        if (act === 'cancel-edit') this.stopEdit(it.id);
        return;
      }
      // Selección: modo selección, Ctrl/Cmd + clic o Mayús + clic
      if (act === 'select' || (this.selectMode && !act && !e.target.closest('a')) || ((e.ctrlKey || e.metaKey) && !e.target.closest('a'))) {
        e.preventDefault();
        this.lastSelected = it.id;
        this.selectMode = true;
        this.toggleSelect(it.id);
        return;
      }
      if (e.shiftKey && this.selectMode) { this.selectRange(it.id); return; }
      if (act === 'done') { li.classList.toggle('is-done', !it.done); Items.setDone(it.id, !it.done); }
      if (act === 'add-step') { this.stepFor(it); return; }
      if (act === 'run-routine') { Routines.run(it.id); return; }
      if (act === 'details') {
        if (it.type === 'rutina') {
          if (this.openDetails.has(it.id)) this.openDetails.delete(it.id); else this.openDetails.add(it.id);
        } else {
          const hidden = { ...notesHidden() };
          if (hidden[it.id]) delete hidden[it.id]; else hidden[it.id] = true;
          Prefs.set(NOTES_HIDDEN, hidden);
        }
        this.render();
        return;
      }
      if (act === 'edit-details') {
        this.startEdit(it);
        this.root.querySelector(`[data-edit="${it.id}"] textarea[name=details]`)?.focus();
        return;
      }
      if (act === 'menu') this.menu(it, actEl);
    }

    onDblClick(e) {
      if (e.target.closest('.il-editor, a, button, .il-addform')) return;
      const it = this.itemOf(e.target);
      if (it) { e.preventDefault(); this.startEdit(it); }
    }

    onSubmit(e) {
      e.preventDefault();
      const form = e.target;
      if (form.matches('.il-editor')) this.saveEdit(form);
      if (form.matches('.il-addform')) this.submitAdd(form);
    }

    onKey(e) {
      const form = e.target.closest('.il-editor, .il-addform');
      if (form) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); form.matches('.il-editor') ? this.stopEdit(Number(form.dataset.edit)) : this.stopAdd(); }
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && form.matches('.il-editor')) { e.preventDefault(); this.saveEdit(form); }
        return;
      }
      const li = e.target.closest('.il-item');
      if (!li || e.target !== li) return;
      const it = Items.get(Number(li.dataset.id));
      if (!it) return;
      if (e.altKey && e.shiftKey && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
        e.preventDefault();
        if (e.key === 'ArrowRight') this.nest(it); else this.unnest(it);
        return;
      }
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === 'Enter') { e.preventDefault(); this.startEdit(it); }
      else if (e.key === ' ') { e.preventDefault(); Items.setDone(it.id, !it.done); }
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); Items.remove(it.id); }
      else if (e.key === 'e' || e.key === 'E') { e.preventDefault(); this.stepFor(it); }
      else if (e.key === 'x' || e.key === 'X') { e.preventDefault(); this.lastSelected = it.id; this.selectMode = true; this.toggleSelect(it.id); }
      else if (e.key === 'Escape' && this.selectMode) { e.preventDefault(); this.clearSelection(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const all = [...this.root.querySelectorAll('.il-item')];
        all[all.indexOf(li) + (e.key === 'ArrowDown' ? 1 : -1)]?.focus();
      } else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && this.root.closest('.is-matrix')) {
        // En la cuadrícula, a la tarjeta de al lado (sin pasar por sus pasos)
        e.preventDefault();
        const cards = [...this.root.querySelectorAll('.il-list > .il-item')];
        const at = cards.indexOf(li.closest('.il-list > .il-item'));
        cards[at + (e.key === 'ArrowRight' ? 1 : -1)]?.focus();
      }
    }
  }

  /* ---------- «Nueva tarea / idea» desde la cabecera de un grupo: la captura común ---------- */
  function openQuickAdd(type) {
    const local = document.querySelector('[data-capture]:not(#captureForm)');
    if (local && local.offsetParent) {
      local.setType?.(type);
      local.querySelector('[data-capture-text]').focus();
      return;
    }
    document.getElementById('captureForm')?.setType?.(type);
    openCapture();
  }

  /* ---------- Llevar a una nota (existente o nueva) ---------- */
  let notesCache = null;
  async function openNoteDialog(ids, done) {
    const dlg = document.getElementById('noteDialog');
    if (!dlg) return;
    const form = dlg.querySelector('form');
    const first = Items.get(ids[0]);
    dlg.querySelector('#noteDialogSub').textContent = ids.length === 1 ? (first?.text || '').split('\n')[0] : `${ids.length} elementos`;
    form.elements.title.value = (first?.text || '').split('\n')[0].slice(0, 120);
    const setDest = (d) => {
      form.dataset.dest = d;
      dlg.querySelectorAll('[data-dest]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.dest === d)));
      dlg.querySelectorAll('[data-for]').forEach((el) => { el.hidden = el.dataset.for !== d; });
    };
    dlg.querySelectorAll('[data-dest]').forEach((b) => { b.onclick = () => setDest(b.dataset.dest); });
    setDest('existing');
    if (!notesCache) {
      const { notes } = await api('/api/notes', { quiet: true });
      notesCache = notes.filter((n) => n.status !== 'indice' && !n.encrypted).sort((a, b) => a.title.localeCompare(b.title, 'es'));
    }
    form.elements.note_id.innerHTML = notesCache.map((n) => `<option value="${esc(n.id)}">${esc(n.title)}${n.category ? ` — ${esc(n.category)}` : ''}</option>`).join('');
    form.onsubmit = async (e) => {
      e.preventDefault();
      const btn = form.querySelector('[type=submit]');
      btn.classList.add('is-loading');
      try {
        let noteId;
        if (form.dataset.dest === 'new') {
          const title = form.elements.title.value.trim();
          if (!title) { form.elements.title.focus(); return; }
          noteId = (await Items.toNote(ids[0], { title, category: form.elements.category.value.trim() || 'Inbox' })).note_id;
          notesCache = null;
          if (ids.length > 1) await Items.bulk(ids.slice(1), 'move', { target: 'nota', note_id: noteId });
        } else {
          noteId = form.elements.note_id.value;
          if (ids.length === 1) await Items.move(ids[0], { target: 'nota', note_id: noteId, parent_id: null, before_id: null });
          else await Items.bulk(ids, 'move', { target: 'nota', note_id: noteId });
        }
        closeModal(dlg);
        done?.();
        toast('Llevado a la nota', { action: { label: 'Abrir', onClick: () => { location.href = `/?note=${encodeURIComponent(noteId)}`; } } });
      } catch (err) {
        toast(err.message || 'No se pudo llevar a la nota', { type: 'error' });
      } finally { btn.classList.remove('is-loading'); }
    };
    openModal(dlg, { focus: 'select' });
  }

  /* Botones Pendientes / Hechas (/ Todas) con el contador único del servidor */
  function wireStatus(view, box) {
    const btns = [...box.querySelectorAll('[data-status]')];
    const paint = () => {
      const c = Items.state.counts;
      if (!c) return;
      box.querySelectorAll('[data-status-count]').forEach((el) => { el.textContent = c[el.dataset.statusCount]; });
    };
    btns.forEach((b) => b.addEventListener('click', () => {
      btns.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      view.setFilters({ status: b.dataset.status });
    }));
    document.addEventListener('items:changed', paint);
    paint();
  }

  window.ItemList = { mount: (el, opts) => new View(el, opts), openNoteDialog, wireStatus };
})();
