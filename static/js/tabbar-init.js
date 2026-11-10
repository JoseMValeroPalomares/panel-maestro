/* ==========================================================================
   tabbar-init.js — destinos de la barra inferior del móvil (window.applyTabbar)
   La barra trae todas las secciones; solo se ven las elegidas en Ajustes (Prefs «tabbar», hasta 4) o, si no hay
   elección, las de por defecto (core/templating.TABBAR). Va justo detrás de la barra en el HTML para colocarla
   antes del primer pintado con la caché de Prefs; ui.js la vuelve a aplicar cuando cambia la preferencia.
   ========================================================================== */
(function () {
  'use strict';
  const MAX = 4;
  function applyTabbar(keys) {
    const bar = document.querySelector('.tabbar');
    if (!bar) return;
    const tabs = [...bar.querySelectorAll('a.tab[data-section]')];
    const valid = Array.isArray(keys) ? keys.filter((k) => tabs.some((t) => t.dataset.section === k)).slice(0, MAX) : [];
    const chosen = valid.length ? valid : tabs.filter((t) => t.dataset.default !== undefined).map((t) => t.dataset.section);
    tabs.forEach((t) => {
      const i = chosen.indexOf(t.dataset.section);
      t.hidden = i < 0;
      t.style.order = i < 0 ? '' : String(i);
    });
  }
  let cached = null;
  try { cached = (JSON.parse(localStorage.getItem('prefs-cache') || '{}') || {}).tabbar; } catch {}
  applyTabbar(cached);
  window.applyTabbar = applyTabbar;
  window.TABBAR_MAX = MAX;
})();
