/* ==========================================================================
   item-copy.js — copiar varias tareas e ideas al portapapeles (window.ItemCopy)
   La selección múltiple vive en item-list.js; aquí está el formato y el diálogo.

     ItemCopy.format(entries, { format: 'md' | 'text', notes: bool })   → texto (puro, sin DOM)
     ItemCopy.collect(ids, { steps: bool })                              → entries desde Items (padres con sus pasos)
     ItemCopy.open(ids)                                                  → diálogo con vista previa y botón «Copiar»

   Formatos: «md» = lista Markdown con casillas (`- [ ]`/`- [x]`) y sangría de 2 espacios por nivel (un paso va bajo su
   tarea); «text» = texto plano (una línea por tarea, los pasos sangrados con «- »). Las notas de cada tarea son opcionales.
   Copiado robusto: copyText() (ui.js) usa navigator.clipboard si existe (solo con https o localhost) y, si no, el
   textarea + execCommand('copy') DENTRO del manejador del clic (se llama sin await previo). Con la app por http en la red
   local es el camino normal; si ni así se puede, el texto queda seleccionado en la vista previa para Ctrl+C.
   ========================================================================== */
(function () {
  'use strict';
  const OPTS_KEY = 'copy-opts';
  const pad = (n) => '  '.repeat(n);

  /* entries = [{ text, done, details, children: [{ text, done, details }] }] */
  function format(entries, { format: fmt = 'md', notes = false } = {}) {
    const out = [];
    const emit = (e, level) => {
      const [first, ...rest] = String(e.text || '').split('\n');
      const body = rest.filter((l) => l.trim());
      if (fmt === 'md') {
        out.push(`${pad(level)}- [${e.done ? 'x' : ' '}] ${first}`);
        body.forEach((l) => out.push(`${pad(level + 1)}${l}`));
        if (notes && e.details) String(e.details).split('\n').forEach((l) => out.push(`${pad(level + 1)}> ${l}`.trimEnd()));
      } else {
        out.push(`${level ? pad(level) + '- ' : ''}${first}${e.done ? ' (hecha)' : ''}`);
        body.forEach((l) => out.push(`${pad(level + 1)}${l}`));
        if (notes && e.details) String(e.details).split('\n').forEach((l) => out.push(`${pad(level + 1)}${l}`.trimEnd()));
      }
      (e.children || []).forEach((c) => emit(c, level + 1));
    };
    entries.forEach((e) => emit(e, 0));
    return out.join('\n');
  }

  /* Los seleccionados en el orden en que se ven. Un paso cuyo padre también está seleccionado va bajo él; con «steps» los
     pasos de un padre seleccionado entran aunque no estén marcados; un paso suelto va como línea propia. */
  function collect(ids, { steps = true, order = null } = {}) {
    const set = new Set(ids.map(Number));
    const rank = new Map((order || [...set]).map((id, i) => [Number(id), i]));
    const sorted = (list) => [...list].sort((a, b) => (rank.get(a.id) ?? 1e9) - (rank.get(b.id) ?? 1e9));
    const items = sorted([...set].map((id) => Items.get(id)).filter(Boolean));
    const pick = (it) => ({ text: it.text, done: !!it.done, details: it.details || '', children: [] });
    const top = items.filter((it) => !it.parent_id || !set.has(it.parent_id));
    return top.map((it) => {
      const e = pick(it);
      if (!it.parent_id) {
        const kids = Items.children(it.id);
        e.children = (steps ? kids : sorted(kids.filter((k) => set.has(k.id)))).map(pick);
      }
      return e;
    });
  }

  let dlg = null;
  function open(ids, order) {
    if (!ids.length) return;
    const saved = Prefs.get(OPTS_KEY, {}) || {};
    const o = { format: saved.format === 'text' ? 'text' : 'md', notes: !!saved.notes, steps: saved.steps !== false };
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'modal modal-lg copy-modal';
      dlg.setAttribute('aria-labelledby', 'copyTitle');
      dlg.innerHTML = `
        <div class="modal-header"><div><h2 id="copyTitle">Copiar al portapapeles</h2><p class="modal-sub" id="copyCount"></p></div>
          <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
        <div class="modal-body stack">
          <div class="segmented" role="group" aria-label="Formato">
            <button type="button" data-copy-fmt="md" aria-pressed="true">${icon('list-checks', 'icon-sm')}Markdown con casillas</button>
            <button type="button" data-copy-fmt="text" aria-pressed="false">${icon('file-text', 'icon-sm')}Texto plano</button>
          </div>
          <label class="check"><input type="checkbox" class="checkbox" id="copySteps"><span>Incluir los pasos (subtareas) de las tareas seleccionadas</span></label>
          <label class="check"><input type="checkbox" class="checkbox" id="copyNotes"><span>Incluir las notas de cada tarea</span></label>
          <label class="field"><span class="field-label">Vista previa <span class="small muted">(si no se copia solo, queda seleccionada: Ctrl + C)</span></span>
            <textarea class="input copy-preview" id="copyPreview" rows="10" readonly spellcheck="false"></textarea></label>
        </div>
        <div class="modal-footer"><span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button>
          <button type="button" class="btn btn-primary" id="copyGo">${icon('copy', 'icon-sm')}Copiar</button></div>`;
      document.body.appendChild(dlg);
      wireAllDialogs();
    }
    const q = (s) => dlg.querySelector(s);
    const render = () => {
      const text = format(collect(dlg._ids, { steps: o.steps, order: dlg._order }), o);
      q('#copyPreview').value = text;
      q('#copyCount').textContent = `${dlg._ids.length} ${dlg._ids.length === 1 ? 'elemento seleccionado' : 'elementos seleccionados'}`;
      dlg.querySelectorAll('[data-copy-fmt]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.copyFmt === o.format)));
      q('#copySteps').checked = o.steps;
      q('#copyNotes').checked = o.notes;
      return text;
    };
    dlg._ids = ids;
    dlg._order = order;
    dlg.onclick = (e) => {
      const f = e.target.closest('[data-copy-fmt]');
      if (f) { o.format = f.dataset.copyFmt; Prefs.set(OPTS_KEY, { ...o }); render(); }
    };
    q('#copySteps').onchange = (e) => { o.steps = e.target.checked; Prefs.set(OPTS_KEY, { ...o }); render(); };
    q('#copyNotes').onchange = (e) => { o.notes = e.target.checked; Prefs.set(OPTS_KEY, { ...o }); render(); };
    // IMPORTANTE: copyText se llama directamente en el clic (sin await antes): así execCommand('copy') cuenta como gesto del usuario
    q('#copyGo').onclick = () => {
      const text = render();
      const ta = q('#copyPreview');
      copyText(text).then((ok) => {
        if (ok) { toast('Copiado al portapapeles'); closeModal(dlg); }
        else { ta.focus(); ta.select(); toast('No se pudo copiar solo: el texto está seleccionado, pulsa Ctrl + C', { type: 'error', duration: 6000 }); }
      });
    };
    render();
    openModal(dlg, { focus: '#copyGo' });
  }

  window.ItemCopy = { format, collect, open };
})();
