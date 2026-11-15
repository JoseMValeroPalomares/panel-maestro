/* ============================================================
   Proponer flashcards con IA (F-4) — servicio: app/ia_flashcards.py.
   La IA propone hasta 15 «pregunta >> respuesta» sacadas SOLO de la nota; aquí se marcan, se editan o se descartan, y
   las elegidas se añaden bajo «## Flashcards» (sync_flashcards las recoge para Repaso). Nada se escribe sin pulsar
   «Añadir». Deshacer = la versión de antes (POST /api/notes/{id}/ia/deshacer, el mismo de Corregir con IA).
   Usa los globales de cerebro.js (noteIsEncrypted, saveNote, loadNotes, openNote, $) y de ui.js.
   ============================================================ */
let fcDialog = null;
let fcJob = null;
let fcPoll = null;

function fcEnsureDialog() {
  if (fcDialog) return fcDialog;
  fcDialog = document.createElement('dialog');
  fcDialog.className = 'modal modal-lg ai-modal fcia-modal';
  fcDialog.setAttribute('aria-labelledby', 'fcTitle');
  fcDialog.innerHTML = `
    <div class="modal-header"><div><h2 id="fcTitle">Proponer flashcards</h2><p class="modal-sub" id="fcSub"></p></div>
      <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
    <div class="modal-body ai-body" id="fcBody" aria-live="polite"></div>
    <div class="modal-footer" id="fcFooter"></div>`;
  document.body.appendChild(fcDialog);
  wireAllDialogs();
  fcDialog.addEventListener('close', () => {
    clearInterval(fcPoll);
    if (fcJob) { api(`/api/ia/jobs/${fcJob}`, { method: 'DELETE', quiet: true }).catch(() => {}); fcJob = null; }
  });
  return fcDialog;
}
const fcBody = () => document.getElementById('fcBody');
const fcFooter = () => document.getElementById('fcFooter');
const fcClose = '<span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button>';
const fcExisting = () => ($('noteContent').value.match(/^\s*.+?\s*>>\s*.+?\s*$/gm) || []).length;

async function openAiFlashcards() {
  const id = $('currentNoteId').value;
  if (!id) return;
  const dlg = fcEnsureDialog();
  document.getElementById('fcSub').textContent = '';
  fcBody().innerHTML = skeletonRows(3);
  fcFooter().innerHTML = '';
  openModal(dlg);
  let info = null, motivo = null;
  if (typeof noteIsEncrypted !== 'undefined' && noteIsEncrypted) {
    motivo = 'Las notas cifradas no se envían nunca a ninguna IA. Quita el cifrado si quieres proponer flashcards.';
  } else if (!$('noteContent').value.trim()) {
    motivo = 'La nota está vacía: escribe algo antes de pedir flashcards.';
  } else {
    try { await saveNote(true); } catch { /* si falla, se usa lo último guardado */ }
    try { info = await api(`/api/notes/${encodeURIComponent(id)}/ia`, { quiet: true }); }
    catch (e) { motivo = `No se pudo comprobar la IA: ${e.message}`; }
    if (info && !info.disponible) motivo = info.motivo;
  }
  const n = fcExisting();
  // El botón se ve siempre; si no se puede, desactivado y con el motivo al lado (aria-describedby)
  fcBody().innerHTML = `
    <p>La IA lee la nota y propone <strong>hasta 15 preguntas con su respuesta</strong>, sacadas solo de lo que hay escrito.
      Las que no se pueden localizar en la nota se descartan solas. Antes de añadir nada podrás marcarlas, editarlas o descartarlas.</p>
    <p class="small muted">${n ? `La nota ya tiene ${n} ${n === 1 ? 'flashcard' : 'flashcards'}: no se repetirán.` : 'Se añadirán bajo un encabezado «Flashcards» al final de la nota.'}</p>
    ${info ? `<label class="check ai-sensible"><input type="checkbox" class="checkbox" id="fcSensible" ${info.sensible ? 'checked' : ''}>
      <span><strong>Nota sensible</strong><br><span class="small muted">Solo se enviará a modelos locales o que no entrenan con tus datos.</span></span></label>` : ''}
    ${motivo ? `<p class="callout fcia-why" id="fcWhy">${icon(info?.sin_claves ? 'plug-zap' : 'lock', 'icon-sm')} ${escapeHtml(motivo)}</p>` : ''}`;
  fcFooter().innerHTML = `${info?.sin_claves ? '<button type="button" class="btn btn-tinted" data-fc-settings>Abrir Ajustes → IA</button>' : ''}
    <span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button>
    <button type="button" class="btn btn-primary" data-fc-start ${motivo ? 'disabled aria-describedby="fcWhy"' : ''}>${icon('layers', 'icon-sm')}Proponer flashcards</button>`;
  fcFooter().querySelector('[data-fc-start]').addEventListener('click', () => fcStart(id));
  fcFooter().querySelector('[data-fc-settings]')?.addEventListener('click', () => { closeModal(fcDialog); openAiSettings(); });
  document.getElementById('fcSensible')?.addEventListener('change', async (e) => {
    await api(`/api/notes/${encodeURIComponent(id)}/sensible`, { method: 'PUT', body: { sensible: e.target.checked }, quiet: true }).catch(() => {});
    openAiFlashcards();  // la política puede cambiar lo que se permite
  });
}

async function fcStart(id) {
  let r;
  try { r = await api(`/api/notes/${encodeURIComponent(id)}/ia/flashcards`, { method: 'POST', quiet: true }); }
  catch (e) {
    fcBody().innerHTML = emptyState({ iconName: 'triangle-alert', title: 'No se pudo empezar', text: e.message, compact: true });
    fcFooter().innerHTML = fcClose;
    return;
  }
  fcJob = r.job;
  fcBody().innerHTML = '<div class="ai-wait"><span class="spinner" aria-hidden="true"></span><p role="status">Leyendo la nota y preparando preguntas…</p></div>';
  fcFooter().innerHTML = '<span class="spacer"></span><button type="button" class="btn" data-fc-cancel>Cancelar</button>';
  fcFooter().querySelector('[data-fc-cancel]').addEventListener('click', () => { closeModal(fcDialog); toast('Propuesta cancelada', { type: 'info' }); });
  clearInterval(fcPoll);
  fcPoll = setInterval(async () => {
    if (!fcJob) return;
    let s;
    try { s = await api(`/api/ia/jobs/${fcJob}`, { quiet: true }); } catch { return; }
    if (s.estado === 'cola' || s.estado === 'trabajando') return;
    clearInterval(fcPoll);
    if (s.estado === 'listo') fcShow(id, s);
    else if (s.estado === 'error') {
      const intentos = (s.intentos || []).map((i) => `<li><code>${escapeHtml(i.modelo)}</code> — ${escapeHtml(i.error)}</li>`).join('');
      fcBody().innerHTML = emptyState({ iconName: 'triangle-alert', title: 'No salieron flashcards válidas', text: s.error || 'Prueba más tarde.', compact: true }) +
        (intentos ? `<details class="ai-details"><summary>Qué pasó con cada modelo</summary><ul class="small">${intentos}</ul></details>` : '');
      fcFooter().innerHTML = fcClose;
      fcJob = null;
    }
  }, 1000);
}

/* Cada tarjeta: marcar, editar (una línea, sin «>>») o descartar */
function fcProblem(q, a) {
  if (!q.trim() || !a.trim()) return 'Falta la pregunta o la respuesta';
  if (q.includes('>>') || a.includes('>>')) return 'No puede llevar «>>»';
  return '';
}

function fcShow(id, s) {
  document.getElementById('fcSub').textContent = `Propuestas por ${s.modelo.proveedor} · ${s.modelo.modelo}`;
  const cards = s.tarjetas || [], out = s.descartadas || [];
  if (!cards.length) {
    fcBody().innerHTML = emptyState({ iconName: 'circle-check', title: 'Nada nuevo que preguntar', text: 'La IA no encontró preguntas que no estén ya en la nota.', compact: true });
    fcFooter().innerHTML = fcClose;
    return;
  }
  fcBody().innerHTML = (s.aviso ? `<p class="callout">${escapeHtml(s.aviso)}</p>` : '') +
    `<p class="small muted">${cards.length} ${cards.length === 1 ? 'propuesta' : 'propuestas'}. Desmarca las que no quieras; puedes retocar el texto antes de añadirlas.</p>
    <ol class="fcia-list">${cards.map((c, i) => `<li class="fcia-card" data-fc="${i}">
      <label class="check fcia-pick"><input type="checkbox" class="checkbox" data-fc-on checked><span class="sr-only">Añadir la tarjeta ${i + 1}</span></label>
      <div class="fcia-fields">
        <label class="sr-only" for="fcQ${i}">Pregunta ${i + 1}</label>
        <textarea id="fcQ${i}" class="input fcia-q" data-fcia-q rows="1" aria-describedby="fcErr${i}" maxlength="300" autocomplete="off">${escapeHtml(c.pregunta)}</textarea>
        <label class="sr-only" for="fcA${i}">Respuesta ${i + 1}</label>
        <textarea id="fcA${i}" class="input input-sm fcia-a" data-fcia-a rows="1" aria-describedby="fcErr${i}" maxlength="400" autocomplete="off">${escapeHtml(c.respuesta)}</textarea>
        <p class="fcia-err small" id="fcErr${i}" data-fcia-err hidden></p>
      </div>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-fc-drop aria-label="Descartar la tarjeta ${i + 1}" title="Descartar">${icon('x', 'icon-sm')}</button>
    </li>`).join('')}</ol>` +
    (out.length ? `<details class="ai-details"><summary>${out.length} ${out.length === 1 ? 'descartada' : 'descartadas'} por la validación</summary>
      <ul class="small">${out.map((d) => `<li>${escapeHtml(d.pregunta || '(sin pregunta)')} — <span class="muted">${escapeHtml(d.motivo)}</span></li>`).join('')}</ul></details>` : '');
  fcFooter().innerHTML = `<span class="tiny subtle" id="fcCount"></span><span class="spacer"></span>
    <button type="button" class="btn" data-fc-reject>Descartar todas</button>
    <button type="button" class="btn btn-primary" data-fc-add>${icon('plus', 'icon-sm')}<span data-fc-add-label>Añadir</span></button>`;
  const rows = () => [...fcBody().querySelectorAll('.fcia-card')];
  const chosen = () => rows().filter((r) => r.querySelector('[data-fc-on]').checked);
  const update = () => {
    let bad = 0;
    rows().forEach((r) => {
      const on = r.querySelector('[data-fc-on]').checked;
      r.classList.toggle('is-off', !on);
      const msg = on ? fcProblem(r.querySelector('[data-fcia-q]').value, r.querySelector('[data-fcia-a]').value) : '';
      const err = r.querySelector('[data-fcia-err]');
      err.textContent = msg; err.hidden = !msg;
      r.querySelectorAll('textarea.input').forEach((x) => x.setAttribute('aria-invalid', String(Boolean(msg))));
      if (msg) bad++;
    });
    const n = chosen().length;
    document.getElementById('fcCount').textContent = `${n} de ${cards.length} marcadas`;
    const add = fcFooter().querySelector('[data-fc-add]');
    add.disabled = n === 0 || bad > 0;
    add.querySelector('[data-fc-add-label]').textContent = n ? `Añadir ${n} a la nota` : 'Añadir';
  };
  // Una tarjeta es una sola línea: Intro no parte el texto (Ctrl+Intro añade)
  fcBody().addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !e.target.matches('textarea')) return;
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) fcFooter().querySelector('[data-fc-add]:not(:disabled)')?.click();
  });
  fcBody().addEventListener('input', (e) => {
    if (e.target.matches('textarea') && /\n/.test(e.target.value)) e.target.value = e.target.value.replace(/\s*\n\s*/g, ' ');  // al pegar
    update();
  });
  fcBody().addEventListener('change', update);
  fcBody().addEventListener('click', (e) => {
    const drop = e.target.closest('[data-fc-drop]');
    if (!drop) return;
    const row = drop.closest('.fcia-card');
    const box = row.querySelector('[data-fc-on]');
    box.checked = !box.checked;
    update();
  });
  update();
  const send = async (tarjetas) => {
    try {
      const r = await api(`/api/ia/jobs/${fcJob}/flashcards`, { method: 'POST', body: { tarjetas }, quiet: true });
      fcJob = null;
      closeModal(fcDialog);
      if (!r.anadidas) { toast('Propuesta descartada', { type: 'info' }); return; }
      toast(`${r.anadidas} ${r.anadidas === 1 ? 'flashcard añadida' : 'flashcards añadidas'} a la nota`, {
        action: { label: 'Deshacer', onClick: async () => {
          await api(`/api/notes/${encodeURIComponent(id)}/ia/deshacer`, { method: 'POST' });
          toast('Flashcards quitadas'); await loadNotes(); openNote(id);
        } },
        duration: 9000,
      });
      await loadNotes(); openNote(id);
    } catch (e) { toast(e.message, { type: 'error' }); }
  };
  fcFooter().querySelector('[data-fc-add]').addEventListener('click', () =>
    send(chosen().map((r) => ({ pregunta: r.querySelector('[data-fcia-q]').value.trim(), respuesta: r.querySelector('[data-fcia-a]').value.trim() }))));
  fcFooter().querySelector('[data-fc-reject]').addEventListener('click', () => send([]));
  fcBody().querySelector('[data-fcia-q]')?.focus();
}
