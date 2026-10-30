/* ==========================================================================
   inbox-layout.js — panel lateral del Inbox (plegable) y hoja inferior en móvil
   En escritorio el estado se recuerda; en móvil la hoja empieza cerrada para ver
   el tablero, se abre con el botón «Lista» y se aparta sola mientras se arrastra.
   ========================================================================== */
(function () {
  'use strict';
  const layout = document.getElementById('inboxLayout');
  const btn = document.getElementById('btnSidebar');
  const sidebar = document.getElementById('inboxSidebar');
  const mobile = window.matchMedia('(max-width: 767px)');
  const KEY = 'inbox-sidebar';

  function set(open, remember = true) {
    layout.classList.toggle('sidebar-collapsed', !open);
    btn.setAttribute('aria-expanded', String(open));
    sidebar.inert = !open;
    if (remember && !mobile.matches) { try { localStorage.setItem(KEY, open ? 'open' : 'closed'); } catch {} }
  }
  function initial() {
    if (mobile.matches) return set(false, false);
    let saved = null;
    try { saved = localStorage.getItem(KEY); } catch {}
    set(saved !== 'closed', false);
  }
  btn.addEventListener('click', () => set(layout.classList.contains('sidebar-collapsed')));
  mobile.addEventListener('change', initial);
  // En móvil: tocar fuera de la hoja la cierra; Escape también
  document.addEventListener('pointerdown', (e) => {
    if (!mobile.matches || layout.classList.contains('sidebar-collapsed') || window.Sortable?.dragging) return;
    if (!sidebar.contains(e.target) && !btn.contains(e.target) && !e.target.closest('.menu, dialog, .toast-region')) set(false, false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && mobile.matches && !layout.classList.contains('sidebar-collapsed') && !document.querySelector('dialog[open], .menu')) set(false, false);
  });
  // Arrastrar la «agarradera» hacia abajo cierra la hoja
  const grabber = sidebar.querySelector('.sheet-grabber');
  grabber?.addEventListener('pointerdown', (e) => {
    const y0 = e.clientY;
    const up = (ev) => { if (ev.clientY - y0 > 40) set(false, false); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointerup', up);
  });
  // Arrastrando en móvil: si el dedo sale por encima de la hoja (hacia el tablero), la hoja se aparta;
  // si vuelve al borde de abajo, reaparece para poder soltar en la lista
  document.addEventListener('pointermove', (e) => {
    if (!mobile.matches || !window.Sortable?.dragging || layout.classList.contains('sidebar-collapsed')) return;
    const top = sidebar.getBoundingClientRect().top;
    if (!sidebar.classList.contains('is-peeking') && e.clientY < top - 8) sidebar.classList.add('is-peeking');
    else if (sidebar.classList.contains('is-peeking') && e.clientY > window.innerHeight - 110) sidebar.classList.remove('is-peeking');
  }, true);
  document.addEventListener('pointerup', () => {
    if (!sidebar.classList.contains('is-peeking')) return;
    sidebar.classList.remove('is-peeking');
    set(false, false); // se soltó en el tablero: la hoja se cierra
  }, true);
  // Pestañas del panel (Lista, 7 días, Plantilla): cada una ocupa todo el alto; se recuerda la elegida
  const PANE_KEY = 'inbox-pane';
  const tabs = [...sidebar.querySelectorAll('.sidebar-panes [data-pane]')];
  function showPane(name) {
    if (!tabs.some((t) => t.dataset.pane === name)) name = 'lista';
    tabs.forEach((t) => { const on = t.dataset.pane === name; t.setAttribute('aria-selected', String(on)); t.tabIndex = on ? 0 : -1; });
    sidebar.querySelectorAll('.sidebar-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    sidebar.querySelectorAll('[data-pane-only]').forEach((n) => { n.hidden = n.dataset.paneOnly !== name; });
    sidebar.querySelector('.sidebar-scroll').scrollTop = 0;
  }
  tabs.forEach((t) => t.addEventListener('click', () => { showPane(t.dataset.pane); window.Prefs?.set(PANE_KEY, t.dataset.pane); }));
  sidebar.querySelector('.sidebar-panes').addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const i = tabs.indexOf(document.activeElement);
    const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    next.focus(); next.click();
  });
  showPane('lista');
  window.Prefs?.ready.then(() => showPane(window.Prefs.get(PANE_KEY, 'lista')));
  // En móvil, al añadir una forma o plantilla desde la hoja, esta se cierra para verla en el tablero
  document.addEventListener('board:inserted', () => { if (mobile.matches) set(false, false); });
  initial();
})();
