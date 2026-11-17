/* =====================================================================
   Lector de PDF (Universidad): window.PdfVisor.open({ id, nombre, pagina, paginas }, { onClose, onMissing })
   pdf.js vendorizado (static/vendor/pdfjs) que se carga solo al abrir el primero. Páginas en columna con
   desplazamiento continuo; solo se pintan las cercanas (IntersectionObserver) y se sueltan las lejanas.
   Recuerda la última página: PATCH /api/uni/archivos/{id} (con fetch directo para no avisar a todas las
   vistas en cada página) al pasar de página y al cerrar. Si algo falla, el mismo diálogo ofrece abrirlo en
   una pestaña nueva con el lector del navegador (#page=N).
   Teclado: ← → (o P / N) página, + − zoom, 0 ajustar al ancho, Esc cerrar.
   ===================================================================== */
(function () {
  'use strict';

  const BASE = '/static/vendor/pdfjs/';
  const CSS_UNITS = 96 / 72;          // 100 % = el tamaño real del papel en pantalla
  const ZOOMS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4];
  const KEEP = 6;                     // páginas pintadas a cada lado de la actual
  const MAX_PX = 16e6;                // tope de píxeles por lienzo (memoria en el móvil)
  let lib = null;

  function loadLib() {
    if (!lib) {
      lib = import(`${BASE}pdf.min.mjs`).then((m) => {
        m.GlobalWorkerOptions.workerSrc = `${BASE}pdf.worker.min.mjs`;
        return m;
      });
      lib.catch(() => { lib = null; });
    }
    return lib;
  }

  const contentUrl = (id) => `/api/uni/archivos/${id}/contenido`;

  function savePage(id, pagina, paginas, keepalive = false) {
    return fetch(`/api/uni/archivos/${id}`, {
      method: 'PATCH', keepalive, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pagina, paginas }),
    }).catch(() => {});
  }

  function open(archivo, { onClose, onMissing } = {}) {
    const esc = (s) => escapeHtml(s);
    const id = archivo.id;
    const hid = `pdf${id}-${Math.random().toString(36).slice(2, 6)}`;
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-full pdf-visor';
    dlg.setAttribute('aria-labelledby', hid);
    dlg.innerHTML = `
      <div class="pdf-bar">
        <h2 id="${hid}" class="pdf-title" title="${esc(archivo.nombre)}">${icon('file-text', 'icon-sm')}<span class="ellipsis">${esc(archivo.nombre)}</span></h2>
        <div class="pdf-nav" role="group" aria-label="Páginas">
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-prev aria-label="Página anterior" title="Página anterior (←)">${icon('chevron-left')}</button>
          <label class="pdf-page"><span class="sr-only">Página actual</span><input class="input input-sm tabular" data-page type="text" inputmode="numeric" autocomplete="off" value="${archivo.pagina || 1}" aria-describedby="${hid}t"></label>
          <span class="pdf-total tabular" id="${hid}t" data-total>de …</span>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-next aria-label="Página siguiente" title="Página siguiente (→)">${icon('chevron-right')}</button>
        </div>
        <div class="pdf-zoom" role="group" aria-label="Zoom">
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-zoom-out aria-label="Alejar" title="Alejar (−)">${icon('zoom-out')}</button>
          <button type="button" class="btn btn-ghost btn-sm tabular pdf-zoom-val" data-fit title="Ajustar al ancho (0)" aria-label="Ajustar al ancho">…</button>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-zoom-in aria-label="Acercar" title="Acercar (+)">${icon('zoom-in')}</button>
        </div>
        <a class="btn btn-ghost btn-icon btn-sm" data-tab href="${contentUrl(id)}#page=${archivo.pagina || 1}" target="_blank" rel="noopener" aria-label="Abrir en una pestaña nueva (buscar y copiar texto)" title="Abrir en una pestaña nueva">${icon('external-link')}</a>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar el lector">${icon('x')}</button>
      </div>
      <div class="pdf-scroll" data-scroll tabindex="0" aria-label="Páginas de ${esc(archivo.nombre)}">
        <div class="pdf-pages" data-pages><div class="pdf-msg"><span class="skeleton skeleton-card"></span></div></div>
      </div>
      <p class="sr-only" aria-live="polite" data-live></p>`;
    document.body.appendChild(dlg);

    const $ = (s) => dlg.querySelector(s);
    const scroll = $('[data-scroll]'), pagesEl = $('[data-pages]'), pageInput = $('[data-page]');
    let doc = null, loadingTask = null, pages = [], zoom = 1, fit = true, current = archivo.pagina || 1;
    let saved = archivo.pagina || 0, saveTimer = 0, closed = false, io = null, ro = null, queue = [], busy = false;

    const setTab = () => { $('[data-tab]').href = `${contentUrl(id)}#page=${current}`; };
    const announce = (t) => { const l = $('[data-live]'); l.textContent = ''; setTimeout(() => { l.textContent = t; }, 30); };

    function failed(title, text) {
      pagesEl.innerHTML = `<div class="pdf-msg">${stateView({ kind: 'error', title, text })}
        <a class="btn btn-tinted" href="${contentUrl(id)}#page=${current}" target="_blank" rel="noopener">${icon('external-link', 'icon-sm')}Abrir en una pestaña nueva</a></div>`;
      dlg.querySelectorAll('.pdf-nav button, .pdf-zoom button').forEach((b) => { b.disabled = true; });
    }

    /* ---------- Página actual y guardado ---------- */
    function pageAt() {
      const y = scroll.scrollTop + scroll.clientHeight * 0.3;
      let lo = 0, hi = pages.length - 1, best = 0;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (pages[mid].el.offsetTop <= y) { best = mid; lo = mid + 1; } else hi = mid - 1;
      }
      return best + 1;
    }
    function setCurrent(n) {
      if (n === current && pageInput.value === String(n)) return;
      current = n;
      if (document.activeElement !== pageInput) pageInput.value = String(n);
      setTab();
      $('[data-prev]').disabled = n <= 1;
      $('[data-next]').disabled = n >= pages.length;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => { if (current !== saved) { saved = current; savePage(id, current, pages.length); } }, 900);
      trim();
    }
    function goTo(n, say = true) {
      if (!pages.length) return;
      n = Math.max(1, Math.min(pages.length, n | 0 || 1));
      scroll.scrollTop = pages[n - 1].el.offsetTop - 8;
      setCurrent(n);
      if (say) announce(`Página ${n} de ${pages.length}`);
    }

    /* ---------- Tamaños y zoom ---------- */
    const scale = () => zoom * CSS_UNITS;
    function fitZoom() {
      const base = pages[0];
      if (!base) return 1;
      // al ancho, pero sin pasar de ~980 px: en una pantalla ancha una página vertical entera sería enorme
      const avail = Math.min(980, Math.max(200, scroll.clientWidth - (window.innerWidth < 768 ? 16 : 48)));
      return Math.max(0.25, Math.min(4, avail / (base.w * CSS_UNITS)));
    }
    function sizePages() {
      const s = scale();
      for (const p of pages) {
        p.el.style.width = `${Math.floor(p.w * s)}px`;
        p.el.style.height = `${Math.floor(p.h * s)}px`;
      }
      $('[data-fit]').textContent = `${Math.round(zoom * 100)} %`;
      $('[data-fit]').setAttribute('aria-pressed', String(fit));
    }
    function setZoom(z, keepFit = false) {
      const anchor = current, frac = pages.length ? (scroll.scrollTop - pages[anchor - 1].el.offsetTop) / Math.max(1, pages[anchor - 1].el.offsetHeight) : 0;
      fit = keepFit;
      zoom = Math.max(0.25, Math.min(4, z));
      sizePages();
      if (pages.length) scroll.scrollTop = pages[anchor - 1].el.offsetTop + frac * pages[anchor - 1].el.offsetHeight;
      for (const p of pages) if (p.scale && p.scale !== scale()) p.stale = true;
      pages.forEach((p) => { if (p.visible) enqueue(p); });
    }
    const zoomStep = (dir) => {
      const next = dir > 0 ? ZOOMS.find((z) => z > zoom + 0.01) : [...ZOOMS].reverse().find((z) => z < zoom - 0.01);
      setZoom(next ?? zoom);
    };

    /* ---------- Pintar ---------- */
    function enqueue(p) {
      if ((p.scale === scale() && !p.stale) || queue.includes(p)) return;
      queue.push(p);
      pump();
    }
    async function pump() {
      if (busy || closed) return;
      const p = queue.shift();
      if (!p) return;
      busy = true;
      try { await paint(p); } catch (err) {
        if (err?.name !== 'RenderingCancelledException') p.el.innerHTML = `<span class="pdf-page-err tiny">No se pudo pintar la página ${p.n}</span>`;
      }
      busy = false;
      pump();
    }
    async function paint(p) {
      if (!p.visible && Math.abs(p.n - current) > KEEP) return;
      const page = await doc.getPage(p.n);
      const vp1 = page.getViewport({ scale: 1 });
      if (Math.abs(vp1.width - p.w) > 0.5 || Math.abs(vp1.height - p.h) > 0.5) {  // páginas de otro tamaño
        p.w = vp1.width; p.h = vp1.height;
        const s0 = scale();
        p.el.style.width = `${Math.floor(p.w * s0)}px`;
        p.el.style.height = `${Math.floor(p.h * s0)}px`;
      }
      const s = scale();
      const vp = page.getViewport({ scale: s });
      let ratio = Math.min(window.devicePixelRatio || 1, 2);
      if (vp.width * vp.height * ratio * ratio > MAX_PX) ratio = Math.sqrt(MAX_PX / (vp.width * vp.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.floor(vp.width * ratio);
      canvas.height = Math.floor(vp.height * ratio);
      canvas.setAttribute('role', 'img');
      canvas.setAttribute('aria-label', `Página ${p.n}`);
      const task = page.render({ canvasContext: canvas.getContext('2d'), viewport: vp, transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : null });
      p.task = task;
      await task.promise;
      p.task = null;
      if (closed) return;
      p.el.querySelector('canvas')?.remove();
      p.el.appendChild(canvas);
      p.el.classList.add('is-painted');
      p.scale = s;
      p.stale = false;
      page.cleanup();
    }
    function trim() {
      for (const p of pages) {
        if (p.scale && !p.visible && Math.abs(p.n - current) > KEEP) {
          p.task?.cancel();
          const c = p.el.querySelector('canvas');
          if (c) { c.width = 0; c.height = 0; c.remove(); }
          p.el.classList.remove('is-painted');
          p.scale = 0;
        }
      }
    }

    /* ---------- Carga ---------- */
    async function start() {
      let pdfjs;
      try { pdfjs = await loadLib(); } catch {
        failed('No se pudo cargar el lector', 'Ábrelo en una pestaña nueva con el lector del navegador.');
        return;
      }
      if (closed) return;
      loadingTask = pdfjs.getDocument({
        url: contentUrl(id), withCredentials: true,
        cMapUrl: `${BASE}cmaps/`, cMapPacked: true, standardFontDataUrl: `${BASE}standard_fonts/`,
        iccUrl: `${BASE}iccs/`, wasmUrl: `${BASE}wasm/`, useWasm: false, enableXfa: false,
      });
      try { doc = await loadingTask.promise; } catch (err) {
        if (closed) return;
        const st = err?.status;
        if (st === 404) failed('Archivo no encontrado', 'Ya no está en la carpeta. Se ha marcado como «no encontrado»; si vuelve, se desmarca al sincronizar.');
        else if (st === 409) failed('El disco no está disponible', 'La carpeta de la universidad no está montada ahora mismo.');
        else if (err?.name === 'InvalidPDFException') failed('No es un PDF válido', 'El archivo está dañado o no es un PDF.');
        else if (err?.name === 'PasswordException') failed('PDF con contraseña', 'Ábrelo en una pestaña nueva para escribir la contraseña.');
        else failed('No se pudo abrir el PDF', 'Prueba a abrirlo en una pestaña nueva.');
        if (st === 404) onMissing?.();
        return;
      }
      if (closed) { doc.destroy(); return; }
      const first = (await doc.getPage(1)).getViewport({ scale: 1 });
      pagesEl.innerHTML = '';
      const frag = document.createDocumentFragment();
      for (let n = 1; n <= doc.numPages; n++) {
        const el = document.createElement('div');
        el.className = 'pdf-page-box';
        el.dataset.n = n;
        frag.appendChild(el);
        pages.push({ n, el, w: first.width, h: first.height, scale: 0, visible: false, task: null, stale: false });
      }
      pagesEl.appendChild(frag);
      $('[data-total]').textContent = `de ${doc.numPages}`;
      pageInput.setAttribute('aria-label', `Página actual, de ${doc.numPages}`);
      zoom = fitZoom();
      sizePages();
      io = new IntersectionObserver((entries) => {
        for (const e of entries) {
          const p = pages[Number(e.target.dataset.n) - 1];
          p.visible = e.isIntersecting;
          if (p.visible) enqueue(p);
        }
      }, { root: scroll, rootMargin: '120% 0px' });
      pages.forEach((p) => io.observe(p.el));
      ro = new ResizeObserver(() => { clearTimeout(ro.t); ro.t = setTimeout(() => { if (fit && pages.length) setZoom(fitZoom(), true); }, 150); });
      ro.observe(scroll);
      const start = Math.min(Math.max(1, archivo.pagina || 1), doc.numPages);
      requestAnimationFrame(() => {
        goTo(start, false);
        announce(start > 1 ? `Sigues en la página ${start} de ${doc.numPages}` : `${doc.numPages} páginas`);
      });
      if (archivo.paginas !== doc.numPages) savePage(id, start, doc.numPages);
    }

    /* ---------- Eventos ---------- */
    let raf = 0;
    scroll.addEventListener('scroll', () => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; if (pages.length) setCurrent(pageAt()); });
    }, { passive: true });
    $('[data-prev]').addEventListener('click', () => goTo(current - 1));
    $('[data-next]').addEventListener('click', () => goTo(current + 1));
    $('[data-zoom-in]').addEventListener('click', () => zoomStep(1));
    $('[data-zoom-out]').addEventListener('click', () => zoomStep(-1));
    $('[data-fit]').addEventListener('click', () => setZoom(fitZoom(), true));
    pageInput.addEventListener('focus', () => pageInput.select());
    pageInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); goTo(parseInt(pageInput.value, 10)); scroll.focus({ preventScroll: true }); }
    });
    pageInput.addEventListener('blur', () => { pageInput.value = String(current); });
    dlg.addEventListener('keydown', (e) => {
      if (e.target === pageInput || e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key;
      if (k === 'ArrowRight' || k === 'n' || k === 'N') { e.preventDefault(); goTo(current + 1); }
      else if (k === 'ArrowLeft' || k === 'p' || k === 'P') { e.preventDefault(); goTo(current - 1); }
      else if (k === '+' || k === '=') { e.preventDefault(); zoomStep(1); }
      else if (k === '-') { e.preventDefault(); zoomStep(-1); }
      else if (k === '0') { e.preventDefault(); setZoom(fitZoom(), true); }
    });

    wireAllDialogs(dlg.parentNode);
    openModal(dlg, {
      focus: '[data-scroll]',
      onClose: () => {
        closed = true;
        clearTimeout(saveTimer);
        if (pages.length && current !== saved) savePage(id, current, pages.length, true);
        io?.disconnect(); ro?.disconnect();
        pages.forEach((p) => p.task?.cancel());
        loadingTask?.destroy();
        dlg.remove();
        onClose?.({ pagina: pages.length ? current : archivo.pagina, paginas: pages.length || archivo.paginas });
      },
    });
    start();
    return dlg;
  }

  window.PdfVisor = { open, url: contentUrl };
})();
