/* ==========================================================================
   tareas-grid.js — cuadrícula de Tareas: cada tarjeta se redimensiona como una ventana y las demás se recolocan.

   Cada lista es una rejilla fina: 10 pistas por cada columna de tarjetas normales y filas de 4 px. El ancho de una tarjeta
   se cuenta en pistas y su alto en filas, y `grid-auto-flow: dense` mete a las demás en los huecos. Todo va en variables
   CSS que solo se usan en la cuadrícula, así que la lista y el móvil no se enteran.
   Tamaños en Prefs 'tareas-sizes': { id: { w: pistas, h: px } } (sin dato: el tamaño normal).
   ========================================================================== */
window.TareasGrid = (function () {
  'use strict';
  const KEY = 'tareas-sizes';
  const TRACKS_PER_COLUMN = 10;
  const COLUMN_PX = 290;
  const ROW_PX = 4;
  const GAP_PX = 12;
  const MIN_TRACKS = 7;
  const MIN_HEIGHT = 64;
  const MAX_HEIGHT = 900;
  const KEY_TRACKS = 1;
  const KEY_PX = 24;
  const CARDS = '.il-list > .il-item';
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  const root = () => document.getElementById('itemList');
  const isActive = () => !!document.querySelector('.tareas.is-matrix') && matchMedia('(min-width: 768px)').matches;
  const sizes = () => Prefs.get(KEY) || {};
  const sizeOf = (id) => sizes()[id] || {};
  const tracksOf = (list) => Number(list.style.getPropertyValue('--tracks')) || TRACKS_PER_COLUMN;

  function save(id, size) {
    const all = {};
    Object.entries(sizes()).forEach(([k, v]) => { if (Items.get(Number(k))) all[k] = v; });  // fuera lo ya borrado
    if (size.w || size.h) all[id] = size; else delete all[id];
    Prefs.set(KEY, all);
  }

  function setTracks(list) {
    const columns = Math.max(1, Math.floor((list.clientWidth + GAP_PX) / (COLUMN_PX + GAP_PX)));
    list.style.setProperty('--tracks', columns * TRACKS_PER_COLUMN);
  }

  // La tarjeta mide lo que mide (alineada arriba) y reserva las filas que le tocan: sin bucles con el observador
  const fit = (li) => li.style.setProperty('--card-rows', Math.ceil((li.offsetHeight + GAP_PX) / ROW_PX));

  function apply(li, size) {
    const tracks = tracksOf(li.parentElement);
    const editing = !!li.querySelector('.il-editor');  // el formulario necesita su sitio, como poco el ancho normal
    const base = size.w || TRACKS_PER_COLUMN;
    li.style.setProperty('--card-w', clamp(editing ? Math.max(base, TRACKS_PER_COLUMN) : base, Math.min(MIN_TRACKS, tracks), tracks));
    const fixed = size.h && !editing;
    if (fixed) li.style.setProperty('--card-h', `${size.h}px`); else li.style.removeProperty('--card-h');
    li.classList.toggle('is-sized', !!fixed);
    fit(li);
  }

  const widths = new WeakMap();
  const observer = new ResizeObserver((entries) => {
    let relayout = false;
    entries.forEach(({ target }) => {
      if (!target.matches('.il-list')) { if (target.isConnected) fit(target); return; }
      if (widths.get(target) !== target.clientWidth) relayout = true;
    });
    if (relayout) requestAnimationFrame(layout);
  });

  function layout() {
    observer.disconnect();
    const host = root();
    if (!host || !isActive()) return;
    host.querySelectorAll('.il-list').forEach((list) => {
      setTracks(list);
      widths.set(list, list.clientWidth);
      observer.observe(list);
    });
    host.querySelectorAll(CARDS).forEach((li) => {
      apply(li, sizeOf(li.dataset.id));
      observer.observe(li);
    });
  }

  /* ---------- Arrastrar un borde ---------- */
  function begin(e, handle) {
    const start = handle.closest(CARDS);
    const id = Number(start.dataset.id);
    const axis = handle.dataset.resize;
    const rect = start.getBoundingClientRect();
    const original = sizeOf(id);
    const size = { ...original };
    const card = () => root().querySelector(`${CARDS}[data-id="${id}"]`);
    const step = () => { const list = card().parentElement; return (list.clientWidth + GAP_PX) / tracksOf(list); };
    document.body.classList.add('is-resizing');
    document.body.dataset.resize = axis;

    const onMove = (ev) => {
      const li = card();
      if (!li) return;
      if (axis !== 's') {
        const w = clamp(Math.round((ev.clientX - rect.left + GAP_PX) / step()), MIN_TRACKS, tracksOf(li.parentElement));
        if (w === TRACKS_PER_COLUMN) delete size.w; else size.w = w;
      }
      if (axis !== 'e') size.h = Math.round(clamp(ev.clientY - rect.top, MIN_HEIGHT, MAX_HEIGHT));
      apply(li, size);
    };
    const finish = (keep) => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onCancel);
      window.removeEventListener('keydown', onKey, true);
      document.body.classList.remove('is-resizing');
      delete document.body.dataset.resize;
      if (keep) save(id, size);
      const li = card();
      if (li) apply(li, keep ? size : original);
    };
    const onUp = () => finish(true);
    const onCancel = () => finish(false);
    const onKey = (ev) => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); finish(false); } };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onCancel);
    window.addEventListener('keydown', onKey, true);
  }

  function reset(id) {
    save(id, {});
    const li = root().querySelector(`${CARDS}[data-id="${id}"]`);
    if (li) apply(li, {});
  }

  /* ---------- Teclado: Mayús + flechas sobre la tarjeta con el foco ---------- */
  function onKeyDown(e) {
    const dx = { ArrowLeft: -KEY_TRACKS, ArrowRight: KEY_TRACKS }[e.key] || 0;
    const dy = { ArrowUp: -KEY_PX, ArrowDown: KEY_PX }[e.key] || 0;
    if (!(dx || dy) || !e.shiftKey || e.altKey || e.ctrlKey || e.metaKey || !isActive()) return;
    const li = e.target;
    if (!li.matches?.(CARDS)) return;
    e.preventDefault();
    e.stopPropagation();
    const id = Number(li.dataset.id);
    const size = { ...sizeOf(id) };
    if (dx) {
      const w = clamp((size.w || TRACKS_PER_COLUMN) + dx, MIN_TRACKS, tracksOf(li.parentElement));
      if (w === TRACKS_PER_COLUMN) delete size.w; else size.w = w;
    }
    if (dy) size.h = clamp((size.h || li.offsetHeight) + dy, MIN_HEIGHT, MAX_HEIGHT);
    save(id, size);
    apply(li, size);
  }

  function menuItems(it) {
    const size = sizeOf(it.id);
    if (it.parent_id || !isActive() || !(size.w || size.h)) return [];
    return [{ label: 'Tamaño normal', icon: 'rotate-ccw', onClick: () => reset(it.id) }];
  }

  function init() {
    const host = root();
    host.addEventListener('pointerdown', (e) => {
      const handle = e.target.closest?.('[data-resize]');
      if (!handle || e.button !== 0) return;
      e.preventDefault();
      begin(e, handle);
    });
    host.addEventListener('dblclick', (e) => {
      const handle = e.target.closest?.('[data-resize]');
      if (!handle) return;
      e.stopPropagation();
      reset(Number(handle.closest(CARDS).dataset.id));
    }, true);
    host.addEventListener('keydown', onKeyDown, true);
    matchMedia('(min-width: 768px)').addEventListener('change', layout);
  }

  return { init, layout, menuItems };
})();
