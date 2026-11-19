/* ==========================================================================
   nota-lectura.js — extras de la lectura de una nota (window.NotaLectura), plan de animaciones N-4 y N-5.

   N-5 · Copiar un bloque de código: cada `pre > code` lleva su botón «Copiar» (teclado y ratón; en el móvil siempre a
         la vista). Al pulsarlo, una franja de luz recorre las líneas de arriba abajo y el botón confirma él mismo
         (copied() de ui.js). Nada en notas cifradas bloqueadas: allí no hay HTML que leer.
   N-4 · Vista previa de un wikilink: al pasar el ratón (o con el foco del teclado) por un [[enlace]] sale un globo
         que nace de la palabra con el título, el área y el principio de la nota enlazada. Misma gracia que los
         tooltips (G-6): la primera espera 450 ms, las siguientes salen ya. Se pide la nota una vez (caché por id);
         las cifradas solo enseñan su título. Esc, el clic o salir del enlace lo cierran. Nunca con el dedo.
   Todo sale directo con «reducir movimiento» (Mov.reduce()).
   ========================================================================== */
(function () {
  'use strict';
  const reduce = () => window.Mov?.reduce?.() ?? matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- N-5 · Copiar código ---------- */
  function codeCopy(container) {
    container.querySelectorAll('pre > code').forEach((code) => {
      const pre = code.parentElement;
      if (pre.parentElement?.classList.contains('code-wrap')) return;
      // Envoltorio: el <pre> se desplaza a lo ancho y el botón (y la luz) no deben irse con él
      const wrap = document.createElement('div');
      wrap.className = 'code-wrap';
      pre.before(wrap);
      wrap.appendChild(pre);
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn-ghost btn-sm code-copy';
      const lang = [...code.classList].find((c) => c.startsWith('language-'))?.slice(9);
      b.setAttribute('aria-label', `Copiar el código${lang ? ` (${lang})` : ''}`);
      b.innerHTML = `${icon('copy', 'icon-sm')}<span>Copiar</span>`;
      wrap.appendChild(b);
    });
  }
  document.addEventListener('click', (e) => {
    const b = e.target.closest('.code-copy');
    if (!b) return;
    const wrap = b.closest('.code-wrap'), code = wrap?.querySelector('pre > code');
    if (!code) return;
    copyText(code.innerText.replace(/\n$/, '')).then((ok) => {
      if (!ok) { toast('No se pudo copiar', { type: 'error', duration: 1400 }); return; }
      copied(b);
      if (reduce()) return;
      // La luz «lee» el bloque: una franja que baja por las líneas (solo transform y opacity)
      const scan = document.createElement('span');
      scan.className = 'code-scan';
      scan.setAttribute('aria-hidden', 'true');
      wrap.appendChild(scan);
      const h = wrap.offsetHeight;
      const dur = Math.min(900, 280 + h * 0.9);
      scan.animate([{ transform: 'translateY(-48px)', opacity: 0 }, { opacity: 1, offset: 0.15 }, { opacity: 1, offset: 0.8 }, { transform: `translateY(${h}px)`, opacity: 0 }],
        { duration: dur, easing: 'cubic-bezier(0.4, 0, 0.2, 1)' }).onfinish = () => scan.remove();
    });
  });

  /* ---------- N-4 · Vista previa de los wikilinks ---------- */
  const cache = new Map();  // id → { at, p: Promise<{title, category, text, encrypted} | null> }
  let card = null, cardFor = null, timer = 0, offAt = 0;
  const GRACE = 700;
  const sel = '.wiki-link[data-note-id]:not(.missing)';  // lectura, previsualización y «Relacionadas»

  function fetchNote(id) {
    const hit = cache.get(id);
    if (!hit || performance.now() - hit.at > 60000) {  // un minuto: lo que se acaba de escribir se ve pronto
      cache.delete(id);
      cache.set(id, { at: performance.now(), p: api(`/api/notes/${encodeURIComponent(id)}`, { quiet: true }).then((n) => ({
        title: n.title || id, category: n.category || '', encrypted: !!n.encrypted,
        text: n.encrypted ? '' : plain(n.content || ''),
      })).catch(() => null) });
      if (cache.size > 80) cache.delete(cache.keys().next().value);
    }
    return cache.get(id).p;
  }
  // Markdown → texto corto y legible (sin frontmatter, marcas, fórmulas ni bloques de código)
  function plain(md) {
    return md.replace(/^---[\s\S]*?\n---\n?/, '').replace(/^\s*#\s+[^\n]*\n/, '')  // sin frontmatter ni el «# Título».replace(/```[\s\S]*?```/g, ' ').replace(/\$\$[\s\S]*?\$\$/g, ' ')
      .replace(/\{\{[a-z]+:([\s\S]*?)\}\}/g, '$1').replace(/\[\[(?:tarea|idea|rutina|item):\d+\]\]/g, '')
      .replace(/\[\[(.+?)\]\]/g, '$1').replace(/!\[[^\]]*\]\([^)]*\)/g, '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
      .replace(/^\s*#{1,6}\s+/gm, '').replace(/^\s*[-*+]\s+\[[ xX]\]\s+/gm, '· ').replace(/^\s*[-*+>]\s+/gm, '')
      .replace(/[*_`~]+/g, '').replace(/\s+/g, ' ').trim().slice(0, 320);
  }

  function hide() {
    clearTimeout(timer);
    if (!card || !cardFor) return;
    cardFor.removeAttribute('aria-describedby');
    cardFor = null;
    offAt = performance.now();
    card.classList.remove('is-on');
    const quita = () => { if (!cardFor) { try { if (card.matches(':popover-open')) card.hidePopover(); } catch { /* sin popover */ } } };
    if (reduce()) quita(); else setTimeout(quita, 180);
  }
  async function show(a) {
    const id = a.dataset.noteId;
    if (!id) return;
    if (!card) {
      card = document.createElement('div');
      card.className = 'wiki-peek';
      card.id = 'wikiPeek';
      card.setAttribute('role', 'tooltip');
      if ('popover' in card) card.popover = 'manual';
      document.body.appendChild(card);
    }
    cardFor = a;
    const n = await fetchNote(id);
    if (cardFor !== a || !a.isConnected) return;
    if (!n) { hide(); return; }
    const esc = escapeHtml;
    card.innerHTML = `<p class="wiki-peek-head">${icon(n.encrypted ? 'lock' : 'notebook-pen', 'icon-sm')}<b>${esc(n.title)}</b></p>
      ${n.category ? `<p class="wiki-peek-cat">${esc(n.category.replace(/ - /g, ' › '))}</p>` : ''}
      <p class="wiki-peek-text">${n.encrypted ? 'Nota cifrada: ábrela para leerla.' : n.text ? esc(n.text) + (n.text.length >= 320 ? '…' : '') : '<span class="muted">Sin texto todavía.</span>'}</p>`;
    a.setAttribute('aria-describedby', 'wikiPeek');
    try { if (card.popover && !card.matches(':popover-open')) card.showPopover(); } catch { /* sin popover */ }
    // Debajo de la palabra si cabe; si no, encima. El globo «nace» de la palabra (transform-origin en ella)
    const r = a.getBoundingClientRect(), w = card.offsetWidth, h = card.offsetHeight;
    const below = r.bottom + 8 + h < innerHeight - 8 || r.top - 8 - h < 8;
    const top = below ? r.bottom + 8 : r.top - 8 - h;
    const left = Math.max(8, Math.min(r.left + r.width / 2 - w / 2, innerWidth - w - 8));
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(top)}px`;
    card.style.transformOrigin = `${Math.round(r.left + r.width / 2 - left)}px ${below ? 0 : h}px`;
    card.classList.toggle('is-above', !below);
    requestAnimationFrame(() => card.classList.add('is-on'));
  }
  document.addEventListener('pointerover', (e) => {
    if (e.pointerType === 'touch') return;
    const a = e.target.closest?.(sel);
    if (!a || a === cardFor) return;
    clearTimeout(timer);
    const gracia = cardFor || performance.now() - offAt < GRACE;
    timer = setTimeout(() => show(a), gracia ? 0 : 450);
    fetchNote(a.dataset.noteId);  // se pide mientras espera: al salir, ya está
  });
  document.addEventListener('pointerout', (e) => {
    const a = e.target.closest?.(sel);
    if (a && !a.contains(e.relatedTarget)) { clearTimeout(timer); hide(); }
  });
  document.addEventListener('focusin', (e) => { const a = e.target.closest?.(sel); if (a && a.matches(':focus-visible')) show(a); });
  document.addEventListener('focusout', (e) => { if (e.target.closest?.(sel)) hide(); });
  document.addEventListener('pointerdown', hide, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && cardFor) hide(); }, true);
  window.addEventListener('scroll', hide, true);
  // Si la nota enlazada cambia (se guarda), su vista previa se vuelve a pedir
  document.addEventListener('panel:changed', () => cache.clear());

  window.NotaLectura = { codeCopy, hide };
})();
