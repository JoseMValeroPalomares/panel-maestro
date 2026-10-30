/* ==========================================================================
   tareas.js — centro de gestión de tareas e ideas: el mismo componente del
   Inbox (item-list.js) a ancho completo, con filtros y selección.
   ========================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const view = ItemList.mount($('itemList'), { variant: 'page' });
  ItemList.wireStatus(view, document.querySelector('.status-seg'));

  // Tipo y categoría se recuerdan (Prefs 'tareas-filters'), salvo al llegar con ?item= (hay que ver esa tarea)
  const FKEY = 'tareas-filters';
  const remember = () => Prefs.set(FKEY, { type: view.filters.type, category: view.filters.category });
  const paintType = (t) => document.querySelectorAll('[data-type-filter]').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.typeFilter === t)));
  document.querySelectorAll('[data-type-filter]').forEach((b) => b.addEventListener('click', () => {
    paintType(b.dataset.typeFilter);
    view.setFilters({ type: b.dataset.typeFilter });
    remember();
  }));

  let timer;
  $('taskSearch').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => view.setFilters({ q: e.target.value.trim() }), 120);
  });

  // Categorías: las del Inbox/Ideas y las de las notas con casillas (área y área - sub)
  const sel = $('catFilter');
  function paintCategories() {
    const set = new Set();
    Items.state.items.forEach((it) => {
      if (it.category) set.add(it.category);
      if (it.origin === 'nota' && it.note_category) {
        const parts = it.note_category.replace(/->/g, ' - ').split(/\s+-\s+/).filter(Boolean);
        parts.forEach((_, i) => set.add(parts.slice(0, i + 1).join(' - ')));
      }
    });
    const current = sel.value;
    sel.innerHTML = '<option value="">Todas las categorías</option>' + [...set].sort((a, b) => a.localeCompare(b, 'es'))
      .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
    sel.value = set.has(current) ? current : '';
  }
  sel.addEventListener('change', () => { view.setFilters({ category: sel.value }); remember(); });
  document.addEventListener('items:changed', paintCategories);
  if (!new URLSearchParams(location.search).get('item')) {
    Promise.all([Prefs.ready, Items.ready()]).then(() => {
      const f = Prefs.get(FKEY, null);
      if (!f) return;
      const type = document.querySelector(`[data-type-filter="${f.type}"]`) ? f.type : 'all';
      paintCategories();
      const category = [...sel.options].some((o) => o.value === f.category) ? f.category : '';
      sel.value = category;
      paintType(type);
      view.setFilters({ type, category });
    }).catch(() => {});
  }

  $('btnSelect').addEventListener('click', () => {
    if (view.selectMode) view.clearSelection();
    else { view.selectMode = true; view.render(); }
  });
  document.addEventListener('items:rendered', () => $('btnSelect').setAttribute('aria-pressed', String(view.selectMode)));

  // /tareas?item=N (enlace desde una nota, la paleta o el calendario): se muestra y se resalta
  const wanted = Number(new URLSearchParams(location.search).get('item'));
  if (wanted) {
    const reveal = () => {
      const it = Items.get(wanted);
      if (!it) return false;
      if (it.done && view.filters.status === 'pending') {
        document.querySelector('.status-seg [data-status="all"]')?.click();
      }
      const li = view.reveal(wanted);
      if (!li) return true;
      li.scrollIntoView({ block: 'center', behavior: 'smooth' });
      li.focus({ preventScroll: true });
      view.flash(wanted);
      return true;
    };
    Items.ready().then(() => { if (!reveal()) toast('Ese elemento ya no existe', { type: 'info' }); });
  }
})();
