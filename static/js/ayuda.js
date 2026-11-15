/* Ayuda (/ayuda/<guía>): pinta una guía de docs/ con el Markdown saneado común (ui.js:renderMarkdown). */
(function () {
  'use strict';
  const src = document.getElementById('docSrc');
  const body = document.getElementById('docBody');
  if (!src || !body) return;
  body.innerHTML = renderMarkdown(src.value, { breaks: false });
  // El título de la guía ya es la cabecera de la página: un solo h1
  body.querySelector('h1')?.remove();
  let guias = {};
  try { guias = JSON.parse(body.dataset.guias || '{}'); } catch { /* sin enlaces entre guías */ }
  body.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href');
    if (/^https?:/.test(href)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; return; }
    if (href.startsWith('#') || href.startsWith('/')) return;
    // Otra guía de docs/: la suya si el panel la enseña; si no, texto (no un enlace roto)
    const destino = guias[href.split('#')[0]];
    if (destino) a.setAttribute('href', destino);
    else a.replaceWith(...a.childNodes);
  });
})();
