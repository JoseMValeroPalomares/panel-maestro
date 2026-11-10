/* ============================================================
   Corregir con IA — botón de la nota, comparación por partes y deshacer.
   Servicio: app/ia_notas.py. Las notas cifradas no se envían nunca (el botón se desactiva y explica por qué).
   Usa los globales de cerebro.js (noteIsEncrypted, saveNote, loadNotes, openNote) y de ui.js.
   ============================================================ */
let aiDialog = null;
let aiJob = null;
let aiPoll = null;

function refreshAiButton() {
  const b = document.getElementById('aiBtn');
  if (!b) return;
  const locked = typeof noteIsEncrypted !== 'undefined' && noteIsEncrypted;
  b.setAttribute('aria-disabled', String(locked));
  b.title = locked ? 'Las notas cifradas no se envían a ninguna IA' : 'Corregir con IA';
}
window.refreshAiButton = refreshAiButton;

function aiEnsureDialog() {
  if (aiDialog) return aiDialog;
  aiDialog = document.createElement('dialog');
  aiDialog.className = 'modal modal-lg ai-modal';
  aiDialog.setAttribute('aria-labelledby', 'aiTitle');
  aiDialog.innerHTML = `
    <div class="modal-header"><div><h2 id="aiTitle">Corregir con IA</h2><p class="modal-sub" id="aiSub"></p></div>
      <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
    <div class="modal-body ai-body" id="aiBody" aria-live="polite"></div>
    <div class="modal-footer" id="aiFooter"></div>`;
  document.body.appendChild(aiDialog);
  wireAllDialogs();
  aiDialog.addEventListener('close', () => { clearInterval(aiPoll); if (aiJob) { api(`/api/ia/jobs/${aiJob}`, { method: 'DELETE', quiet: true }).catch(() => {}); aiJob = null; } });
  return aiDialog;
}
const aiBody = () => document.getElementById('aiBody');
const aiFooter = () => document.getElementById('aiFooter');
function aiSetFooter(html) { aiFooter().innerHTML = html; }

async function openAiCorrect() {
  const id = $('currentNoteId').value;
  if (!id) return;
  const dlg = aiEnsureDialog();
  document.getElementById('aiSub').textContent = '';
  if (typeof noteIsEncrypted !== 'undefined' && noteIsEncrypted) {
    aiBody().innerHTML = emptyState({ iconName: 'lock', title: 'Nota cifrada', text: 'Las notas cifradas no se envían nunca a ninguna IA. Quita el cifrado si quieres corregirla.', compact: true });
    aiSetFooter('<span class="spacer"></span><button type="button" class="btn" data-close>Entendido</button>');
    openModal(dlg);
    return;
  }
  aiBody().innerHTML = skeletonRows(3);
  aiSetFooter('');
  openModal(dlg);
  try { await saveNote(true); } catch { /* si falla, se corrige lo último guardado */ }
  let info;
  try { info = await api(`/api/notes/${encodeURIComponent(id)}/ia`, { quiet: true }); }
  catch (e) { aiBody().innerHTML = emptyState({ iconName: 'triangle-alert', title: 'No se pudo comprobar', text: e.message, compact: true }); return; }
  if (!info.disponible) {
    aiBody().innerHTML = emptyState({ iconName: info.sin_claves ? 'plug-zap' : 'lock', title: info.sin_claves ? 'Falta configurar la IA' : 'No disponible', text: info.motivo, compact: true });
    aiSetFooter(`<span class="spacer"></span>${info.sin_claves ? '<button type="button" class="btn btn-tinted" data-ai-settings>Abrir Ajustes → IA</button>' : ''}<button type="button" class="btn" data-close>Cerrar</button>`);
    aiFooterWire(id);
    return;
  }
  aiShowStart(id, info);
}

function aiShowStart(id, info) {
  const ult = (info.ultimas || [])[0];
  const fmt = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' });
  aiBody().innerHTML = `
    <p>La IA corrige <strong>forma, redacción, estructura, fórmulas, tablas y enlaces</strong> siguiendo tu <code>docs/GUIA_NOTAS.md</code>. No inventa datos ni añade etiquetas; antes de aplicar verás los cambios y podrás elegir qué aceptar.</p>
    <label class="check ai-sensible"><input type="checkbox" class="checkbox" id="aiSensible" ${info.sensible ? 'checked' : ''}>
      <span><strong>Nota sensible</strong><br><span class="small muted">Solo se enviará a modelos locales o que no entrenan con tus datos.</span></span></label>
    ${ult ? `<p class="small muted ai-last">Última corrección: ${escapeHtml(ult.proveedor || '')} · ${escapeHtml(ult.modelo || '')} · ${escapeHtml(ult.estado)} · ${fmt.format(new Date(ult.creado * 1000))}</p>` : ''}`;
  const undo = (info.ultimas || []).find((u) => ['aplicada', 'parcial'].includes(u.estado)) && info.ultimas[0] && ['aplicada', 'parcial'].includes(info.ultimas[0].estado);
  aiSetFooter(`${undo ? `<button type="button" class="btn btn-ghost" data-ai-undo>${icon('undo-2', 'icon-sm')}Deshacer la última</button>` : ''}
    <span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button>
    <button type="button" class="btn btn-primary" data-ai-start>${icon('sparkles', 'icon-sm')}Corregir</button>`);
  aiFooterWire(id);
  document.getElementById('aiSensible').addEventListener('change', (e) =>
    api(`/api/notes/${encodeURIComponent(id)}/sensible`, { method: 'PUT', body: { sensible: e.target.checked }, quiet: true }).catch(() => {}));
}

function aiFooterWire(id) {
  const f = aiFooter();
  f.querySelector('[data-ai-start]')?.addEventListener('click', () => aiStart(id));
  f.querySelector('[data-ai-settings]')?.addEventListener('click', () => { closeModal(aiDialog); openAiSettings(); });
  f.querySelector('[data-ai-undo]')?.addEventListener('click', async () => {
    if (!(await uiConfirm('¿Deshacer la última corrección?', 'La nota vuelve a como estaba antes de aplicarla.', { confirmLabel: 'Deshacer' }))) return;
    await api(`/api/notes/${encodeURIComponent(id)}/ia/deshacer`, { method: 'POST' });
    closeModal(aiDialog); toast('Corrección deshecha'); await loadNotes(); openNote(id);
  });
}

async function aiStart(id) {
  let r;
  try { r = await api(`/api/notes/${encodeURIComponent(id)}/ia/corregir`, { method: 'POST', quiet: true }); }
  catch (e) {
    aiBody().innerHTML = emptyState({ iconName: 'triangle-alert', title: 'No se pudo empezar', text: e.message, compact: true });
    aiSetFooter('<span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button>');
    return;
  }
  aiJob = r.job;
  aiBody().innerHTML = `<div class="ai-wait"><span class="spinner" aria-hidden="true"></span><p id="aiWaitMsg" role="status">Corrigiendo… puede tardar hasta un minuto.</p></div>`;
  aiSetFooter(`<span class="spacer"></span><button type="button" class="btn" data-ai-cancel>Cancelar</button>`);
  aiFooter().querySelector('[data-ai-cancel]').addEventListener('click', async () => {
    clearInterval(aiPoll);
    await api(`/api/ia/jobs/${aiJob}`, { method: 'DELETE', quiet: true }).catch(() => {});
    aiJob = null; closeModal(aiDialog); toast('Corrección cancelada', { type: 'info' });
  });
  clearInterval(aiPoll);
  aiPoll = setInterval(async () => {
    if (!aiJob) return;
    let s;
    try { s = await api(`/api/ia/jobs/${aiJob}`, { quiet: true }); } catch { return; }
    if (s.estado === 'cola' || s.estado === 'trabajando') return;
    clearInterval(aiPoll);
    if (s.estado === 'listo') aiShowDiff(id, s);
    else if (s.estado === 'error') aiShowError(id, s);
  }, 1000);
}

function aiShowError(id, s) {
  const intentos = (s.intentos || []).map((i) => `<li><code>${escapeHtml(i.modelo)}</code> — ${escapeHtml(i.error)}</li>`).join('');
  aiBody().innerHTML = emptyState({ iconName: 'triangle-alert', title: 'No se obtuvo una corrección válida', text: s.error || 'Prueba más tarde.', compact: true }) +
    (intentos ? `<details class="ai-details"><summary>Qué pasó con cada modelo</summary><ul class="small">${intentos}</ul></details>` : '');
  aiSetFooter('<span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button>');
  aiJob = null;
}

/* Diferencias por palabras dentro de un par antes/después de una sola línea */
function aiWordDiff(a, b) {
  const x = a.split(/(\s+)/), y = b.split(/(\s+)/);
  const n = x.length, m = y.length;
  if (n * m > 40000) return [escapeHtml(a), escapeHtml(b)];
  const t = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = x[i] === y[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
  let i = 0, j = 0, ha = '', hb = '';
  while (i < n && j < m) {
    if (x[i] === y[j]) { ha += escapeHtml(x[i]); hb += escapeHtml(y[j]); i++; j++; }
    else if (t[i + 1][j] >= t[i][j + 1]) { ha += `<del>${escapeHtml(x[i])}</del>`; i++; }
    else { hb += `<ins>${escapeHtml(y[j])}</ins>`; j++; }
  }
  while (i < n) ha += `<del>${escapeHtml(x[i++])}</del>`;
  while (j < m) hb += `<ins>${escapeHtml(y[j++])}</ins>`;
  return [ha, hb];
}

function aiShowDiff(id, s) {
  const total = s.partes.length;
  document.getElementById('aiSub').textContent = `Corregida por ${s.modelo.proveedor} · ${s.modelo.modelo}`;
  if (!total) {
    aiBody().innerHTML = emptyState({ iconName: 'circle-check', title: 'Sin cambios', text: 'La IA no encontró nada que corregir.', compact: true });
    aiSetFooter('<span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button>');
    return;
  }
  const lines = (arr, html) => (arr.length ? arr.map((l) => `<div class="ai-line">${html || escapeHtml(l) || '&nbsp;'}</div>`).join('') : '<div class="ai-line ai-empty">(nada)</div>');
  aiBody().innerHTML = (s.aviso ? `<p class="callout">${escapeHtml(s.aviso)}</p>` : '') +
    `<p class="small muted">${total} ${total === 1 ? 'cambio' : 'cambios'}. Desmarca los que no quieras. Los comentarios <code>&lt;!-- REVISAR --&gt;</code> son dudas de la IA sobre un dato.</p>` +
    s.partes.map((p) => {
      let a, b;
      if (p.antes.length === 1 && p.despues.length === 1) [a, b] = aiWordDiff(p.antes[0], p.despues[0]);
      return `<fieldset class="ai-part"><legend class="sr-only">Cambio en la línea ${p.linea}</legend>
        <label class="check ai-part-head"><input type="checkbox" class="checkbox" data-part="${p.id}" checked><span>Línea ${p.linea}</span></label>
        <div class="ai-cols">
          <div class="ai-col ai-before" aria-label="Antes"><span class="ai-tag">Antes</span>${a !== undefined ? lines([''], a) : lines(p.antes)}</div>
          <div class="ai-col ai-after" aria-label="Después"><span class="ai-tag">Después</span>${b !== undefined ? lines([''], b) : lines(p.despues)}</div>
        </div></fieldset>`;
    }).join('');
  aiSetFooter(`<span class="tiny subtle" id="aiCount"></span><span class="spacer"></span>
    <button type="button" class="btn" data-ai-reject>Rechazar todo</button>
    <button type="button" class="btn btn-tinted" data-ai-some>Aceptar las marcadas</button>
    <button type="button" class="btn btn-primary" data-ai-all>${icon('check', 'icon-sm')}Aceptar todo</button>`);
  const boxes = () => [...aiBody().querySelectorAll('[data-part]')];
  const upd = () => { const n = boxes().filter((b) => b.checked).length; document.getElementById('aiCount').textContent = `${n} de ${total} marcados`; aiFooter().querySelector('[data-ai-some]').disabled = n === 0; };
  aiBody().addEventListener('change', upd); upd();
  const apply = async (aceptadas) => {
    try {
      const r = await api(`/api/ia/jobs/${aiJob}/aplicar`, { method: 'POST', body: { aceptadas }, quiet: true });
      aiJob = null; closeModal(aiDialog);
      toast(r.aplicadas ? `Aplicados ${r.aplicadas} ${r.aplicadas === 1 ? 'cambio' : 'cambios'}` : 'Nada aplicado', { action: r.aplicadas ? { label: 'Deshacer', onClick: async () => {
        await api(`/api/notes/${encodeURIComponent(id)}/ia/deshacer`, { method: 'POST' }); toast('Corrección deshecha'); await loadNotes(); openNote(id); } } : null, duration: 9000 });
      await loadNotes(); openNote(id);
    } catch (e) { toast(e.message, { type: 'error' }); }
  };
  aiFooter().querySelector('[data-ai-all]').onclick = () => apply(null);
  aiFooter().querySelector('[data-ai-some]').onclick = () => apply(boxes().filter((b) => b.checked).map((b) => +b.dataset.part));
  aiFooter().querySelector('[data-ai-reject]').onclick = async () => {
    await api(`/api/ia/jobs/${aiJob}`, { method: 'DELETE', quiet: true }).catch(() => {});
    aiJob = null; closeModal(aiDialog); toast('Corrección rechazada', { type: 'info' });
  };
}

/* El botón desactivado (nota cifrada) no ejecuta data-call: igualmente explica por qué */
document.getElementById('aiBtn')?.addEventListener('click', () => { if (document.getElementById('aiBtn').getAttribute('aria-disabled') === 'true') openAiCorrect(); });


/* ---------- Copiar «prompt + nota» para pegarlo en un chat de IA (ChatGPT, Claude, Gemini…) ----------
   El contexto sale de GET /api/ia/prompt (app/ia_notas.py: formato, simulaciones, reglas y títulos; lleva dentro tu
   docs/GUIA_NOTAS.md). Se pide por adelantado: así el clic copia sin esperar red y funciona también por http, donde
   copiar exige hacerlo directamente en el manejador del clic. */
let aiPromptCache = null;
async function aiPrefetchPrompt() {
  try { aiPromptCache = (await api('/api/ia/prompt', { quiet: true })).prompt; } catch { /* se reintenta al pulsar */ }
}
aiPrefetchPrompt();

function aiPromptText() {
  const title = $('noteTitle').value.trim() || 'Sin título';
  const cat = $('noteCategory').value.trim();
  const body = $('noteContent').value;
  return `${aiPromptCache}\n\n=== NOTA ===\nTítulo: ${title}${cat ? `\nCategoría: ${cat}` : ''}\n\n${body}\n`;
}

function aiShowManualCopy(text) {
  let dlg = document.getElementById('aiManualCopy');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'aiManualCopy';
    dlg.className = 'modal modal-lg';
    dlg.setAttribute('aria-labelledby', 'aiManualTitle');
    dlg.innerHTML = `<div class="modal-header"><h2 id="aiManualTitle">Copia el texto a mano</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body stack"><p class="small muted">El navegador no ha dejado copiar solo. El texto está seleccionado: pulsa Ctrl + C y pégalo en tu chat.</p>
        <textarea class="input copy-preview" id="aiManualText" rows="14" readonly spellcheck="false"></textarea></div>
      <div class="modal-footer"><span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
  }
  dlg.querySelector('#aiManualText').value = text;
  openModal(dlg, { focus: '#aiManualText' });
  dlg.querySelector('#aiManualText').select();
}

async function copyAiPrompt() {
  if (!$('currentNoteId').value) return;
  const body = $('noteContent').value;
  if (!body.trim()) { toast(noteIsEncrypted ? 'Descifra la nota para poder copiarla' : 'La nota está vacía', { type: 'error' }); return; }
  // IMPORTANTE: sin ningún await antes de copyText, o el navegador (por http) no lo cuenta como gesto del usuario
  if (!aiPromptCache) { await aiPrefetchPrompt(); if (!aiPromptCache) { toast('No se pudo preparar el prompt', { type: 'error' }); return; } }
  if (typeof noteIsEncrypted !== 'undefined' && noteIsEncrypted && !(await uiConfirm('Nota cifrada', 'El texto se copiará SIN cifrar al portapapeles para que lo pegues en una IA. ¿Continuar?', { confirmLabel: 'Copiar' }))) return;
  const text = aiPromptText();
  copyText(text).then((ok) => {
    if (ok) toast('Prompt y nota copiados: pégalos en tu chat de IA');
    else aiShowManualCopy(text);
  });
}
