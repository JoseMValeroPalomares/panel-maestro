/* ==========================================================================
   compartir.js — destino de «Compartir» de la PWA (share_target del manifest, F-2)
   Llega /compartir?title=&text=&url= (GET: sin sesión, el login devuelve aquí con los datos).
   - Un enlace (url, o un texto que es poco más que un enlace, como comparten YouTube o el
     navegador) propone «Guardar en el Baúl» (POST /api/resources, la misma ruta del Baúl).
   - Un texto abre la captura rápida de siempre ya rellena: tarea o idea, y los prefijos
     (e: evento, r: rutina, t:, i:) funcionan igual (Items.capture → app/capture.py).
   Nada se guarda sin pulsar Guardar; al guardar se va a donde quedó.
   ========================================================================== */
(function () {
  'use strict';

  const URL_RE = /\bhttps?:\/\/[^\s<>"']+/i;
  const params = new URLSearchParams(location.search);
  const got = {
    title: (params.get('title') || '').trim(),
    text: (params.get('text') || '').trim(),
    url: (params.get('url') || '').trim(),
  };
  if (!got.title && !got.text && !got.url) return;  // sin nada: solo la explicación de la página

  // ¿Es un enlace? La URL explícita o la primera del texto, si el resto es solo un título corto
  const trimPunct = (u) => u.replace(/[).,;:!?»”]+$/, '');
  const found = got.text.match(URL_RE);
  const link = got.url || (found ? trimPunct(found[0]) : '');
  const rest = (found ? got.text.replace(found[0], '') : got.text).replace(/\s+/g, ' ').trim();
  const isLink = Boolean(link) && /^https?:\/\//i.test(link) && (!rest || rest === got.title || (rest.length <= 160 && !got.text.includes('\n')));
  const linkTitle = got.title || rest || link;
  const host = (() => { try { return new URL(link).hostname.replace(/^www\./, ''); } catch { return link; } })();

  // Lo que va a la captura: título (si no está ya en el texto), texto y enlace (si no está ya)
  function asText() {
    const parts = [];
    if (got.title && !got.text.includes(got.title)) parts.push(got.title);
    if (got.text) parts.push(got.text);
    if (got.url && !got.text.includes(got.url)) parts.push(got.url);
    return parts.join('\n');
  }

  /* ---------- Resumen en la página (por si se cierra el diálogo) ---------- */
  const body = document.querySelector('[data-share-body]');
  document.querySelector('[data-share-heading]').textContent = isLink ? 'Enlace recibido' : 'Texto recibido';
  body.innerHTML = `<div class="share-received">
      <span class="row-title">${escapeHtml(isLink ? linkTitle : (got.title || got.text.split('\n')[0] || got.url))}</span>
      <span class="row-sub">${escapeHtml(isLink ? link : got.text.length > 240 ? got.text.slice(0, 240) + '…' : (got.title ? got.text : ''))}</span>
    </div>
    <p class="small muted" data-share-state>Aún no se ha guardado nada.</p>
    <div class="share-actions">
      ${isLink ? `<button type="button" class="btn btn-primary" data-share-open="link">${icon('library', 'icon-sm')}Guardar en el Baúl</button>` : ''}
      <button type="button" class="btn${isLink ? '' : ' btn-primary'}" data-share-open="text">${icon('square-check', 'icon-sm')}${isLink ? 'Como tarea o idea' : 'Guardar como tarea o idea'}</button>
      <a class="btn btn-ghost" href="/hoy">Descartar</a>
    </div>`;
  body.addEventListener('click', (e) => {
    const b = e.target.closest('[data-share-open]');
    if (b) (b.dataset.shareOpen === 'link' ? openLink : openText)();
  });

  const done = (msg, href) => {
    const st = body.querySelector('[data-share-state]');
    if (st) st.textContent = msg;
    body.querySelectorAll('[data-share-open]').forEach((b) => { b.disabled = true; });
    // a la página que corresponde, sin dejar /compartir?… en el historial (Atrás no vuelve a guardarlo)
    setTimeout(() => location.replace(href), 900);
  };

  /* ---------- Texto: la captura rápida de siempre, rellena ---------- */
  function openText() {
    const form = document.getElementById('captureForm');
    const ta = form?.querySelector('[data-capture-text]');
    if (!ta) return;
    closeModal('shareLinkModal');
    ta.value = isLink ? [linkTitle !== link ? linkTitle : '', link].filter(Boolean).join('\n') : asText();
    ta.dispatchEvent(new Event('input'));
    openCapture();
    ta.setSelectionRange(0, 0);
    ta.scrollTop = 0;
  }
  // El formulario común (items.js) vacía el texto y cierra su diálogo al guardar: así se sabe que se guardó
  let sent = '';
  const capForm = document.getElementById('captureForm');
  const mark = () => { sent = capForm.querySelector('[data-capture-text]').value; };
  capForm?.addEventListener('submit', mark, true);  // botón Guardar
  capForm?.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) mark(); }, true);  // Ctrl+Intro
  document.getElementById('captureModal')?.addEventListener('close', () => {
    const ta = document.querySelector('#captureForm [data-capture-text]');
    if (!sent || !ta || ta.value.trim()) return;
    done('Guardado.', /^\s*e\s*:/i.test(sent) ? '/calendario' : '/tareas');
  });

  /* ---------- Enlace: al Baúl ---------- */
  const dlg = document.getElementById('shareLinkModal');
  const form = document.getElementById('shareLinkForm');
  let catsLoaded = false;
  function openLink() {
    dlg.querySelector('[data-share-title]').textContent = linkTitle;
    dlg.querySelector('[data-share-host]').textContent = host;
    dlg.querySelector('[data-share-icon]').innerHTML = icon(/(^|\.)youtu(\.be|be\.com)$/.test(host) ? 'youtube' : 'globe');
    if (!catsLoaded) {
      catsLoaded = true;
      api('/api/resources/categories', { quiet: true }).then(({ categories }) => {
        document.getElementById('shareCats').innerHTML = (categories || []).map((c) => `<option value="${escapeHtml(c)}">`).join('');
      }).catch(() => {});
    }
    openModal(dlg, { focus: '[type=submit]' });
  }
  dlg.querySelector('[data-share-as-item]').addEventListener('click', openText);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = form.querySelector('[type=submit]');
    btn.classList.add('is-loading');
    try {
      const watchLater = form.watch_later.checked;
      const res = await api('/api/resources', {
        method: 'POST',
        body: { url: link, category: form.category.value.trim() || 'General', watch_later: watchLater, contexto: window.Ctx?.forNew() },
        quiet: true,
      }).catch((err) => ({ error: err?.status === 409 ? 'dup' : (err?.message || 'error') }));
      if (res?.error === 'dup' || res?.error === 'URL ya existe') {
        closeModal(dlg);
        toast('Ese enlace ya estaba en el Baúl', { type: 'info' });
        done('Ya estaba en el Baúl.', '/vault');
        return;
      }
      if (res?.error) { toast('No se pudo guardar en el Baúl', { type: 'error' }); return; }
      closeModal(dlg);
      toast(watchLater ? 'Guardado en el Baúl, para más tarde' : 'Guardado en el Baúl');
      done('Guardado en el Baúl.', '/vault');
    } finally { btn.classList.remove('is-loading'); }
  });

  // Al llegar: el diálogo que toca, ya relleno
  (isLink ? openLink : openText)();
})();
