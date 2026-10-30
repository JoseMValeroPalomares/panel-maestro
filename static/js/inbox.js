/* =====================================================================
   INBOX: captura + lista de tareas e ideas (el componente común de
   item-list.js, el mismo de la pestaña Tareas) junto al tablero (board.js).
   ===================================================================== */
(function () {
  'use strict';
  const view = ItemList.mount(document.getElementById('itemList'), { variant: 'sidebar' });
  ItemList.wireStatus(view, document.querySelector('.sidebar-tabs'));
  // Tipo (Todo, Tareas, Ideas, Rutinas): se recuerda
  const typeBox = document.querySelector('.type-chips');
  const setType = (t) => {
    const r = typeBox.querySelector(`input[value="${t}"]`) || typeBox.querySelector('input[value="all"]');
    r.checked = true;
    view.setFilters({ type: r.value });
  };
  typeBox.addEventListener('change', (e) => { setType(e.target.value); Prefs.set('inbox-type', e.target.value); });
  Prefs.ready.then(() => setType(Prefs.get('inbox-type', 'all')));
})();

// Agenda de 7 días en la barra lateral (el mismo componente del calendario)
if (window.Calendar && document.getElementById('inboxAgenda')) Calendar.mount(document.getElementById('inboxAgenda'), { view: 'agenda', compact: true, days: 7, hide: ['routine'] });
