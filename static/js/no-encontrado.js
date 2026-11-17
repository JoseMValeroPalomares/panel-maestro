/* no-encontrado.js — «Volver» de la página 404 (la CSP no admite scripts en línea) */
(function () {
  'use strict';
  const back = document.querySelector('[data-back]');
  if (!back) return;
  // Sin historial (enlace abierto en una pestaña nueva) no hay adónde volver: se oculta
  if (history.length <= 1) { back.hidden = true; return; }
  back.addEventListener('click', () => history.back());
})();
