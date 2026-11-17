/* =====================================================================
   Ficha de una tarea de proyecto (ventana centrada; se abre con el título o «Detalles»): título, estado, prioridad, fecha y versión;
   descripción en Markdown con checklist marcable (las casillas «- [ ]» de la descripción);
   subtareas (los pasos de siempre); adjuntos y comentarios (app/item_extras.py).
   Todo escribe por Items (items.js) o por /api/items/{id}/…; nada propio que sincronizar.
   Uso: PjFicha.open(id, { proyecto, onChange })
   ===================================================================== */
(function () {
  'use strict';

  const esc = (s) => escapeHtml(s);
  const NUM = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });
  const ESTADOS = [['todo', 'Por hacer', 'circle'], ['doing', 'En curso', 'circle-dot'], ['done', 'Hecha', 'circle-check']];
  const PRIOS = [['', 'Sin prioridad'], ['alta', 'Alta'], ['media', 'Media'], ['baja', 'Baja']];
  const CHECK_RE = /^(\s*(?:[-*+]|\d+[.)])\s+\[)([ xX])(\].*)$/;

  const bytes = (n) => (n < 1024 ? `${n} B` : n < 1048576 ? `${NUM.format(n / 1024)} KB` : `${NUM.format(n / 1048576)} MB`);
  const estadoDe = (it) => (it.done ? 'done' : it.en_curso ? 'doing' : 'todo');

  // Casillas de la descripción: [{hecha, texto}] en el orden en que marked las pinta
  function checklist(src) {
    return String(src || '').split('\n').map((l) => l.match(CHECK_RE)).filter(Boolean).map((m) => ({ hecha: m[2] !== ' ', texto: m[3].slice(1).trim() }));
  }
  function toggleCheck(src, i) {
    let n = -1;
    return String(src || '').split('\n').map((l) => {
      const m = l.match(CHECK_RE);
      if (!m) return l;
      n++;
      return n === i ? m[1] + (m[2] === ' ' ? 'x' : ' ') + m[3] : l;
    }).join('\n');
  }

  let current = null;  // { dlg, id, opts }
  const drafts = new Map();  // comentario a medio escribir por tarea: cerrar la ficha no lo pierde

  async function open(id, opts = {}) {
    await Items.ready();
    const it = Items.get(id);
    if (!it) { toast('Esa tarea ya no está', { type: 'info' }); return; }
    if (current?.dlg?.open) closeModal(current.dlg);
    const dlg = document.createElement('dialog');
    dlg.className = 'modal pj-ficha';
    dlg.setAttribute('aria-labelledby', 'pfTitleLabel');
    document.body.appendChild(dlg);
    current = { dlg, id, opts, editing: false };
    paint();
    wireAllDialogs?.();
    openModal(dlg, { focus: '[data-close]', onClose: () => { keepWork(dlg, id); dlg.remove(); document.removeEventListener('items:changed', onItems); if (current?.dlg === dlg) current = null; opts.onChange?.(); } });
    document.addEventListener('items:changed', onItems);
    if (drafts.has(id)) dlg.querySelector('#pfComIn').value = drafts.get(id);
    loadExtras();
  }
  // Al cerrar: la descripción que se estaba editando se guarda y el comentario sin enviar queda como borrador
  function keepWork(dlg, id) {
    const desc = dlg.querySelector('#pfDescIn'), com = dlg.querySelector('#pfComIn');
    if (desc && Items.get(id) && desc.value !== (Items.get(id).details || '')) {
      Items.update(id, { details: desc.value }).then(() => toast('Descripción guardada', { type: 'info', duration: 1400 })).catch(() => {});
    }
    if (com?.value.trim()) drafts.set(id, com.value); else drafts.delete(id);
  }
  // Otro sitio cambió la tarea (otra pestaña, el tablero…): se repinta salvo mientras se escribe
  function onItems() {
    if (!current || current.editing || document.activeElement?.id === 'pfTitle') return;
    if (!Items.get(current.id)) { closeModal(current.dlg); return; }
    paint();
    paintExtras();
  }

  function paint() {
    const { dlg, id, opts } = current;
    const it = Items.get(id);
    const P = opts.proyecto;
    const vers = (P?.versiones || []).filter((v) => v.estado === 'abierta' || v.id === it.version_id);
    const kids = Items.children(id);
    const checks = checklist(it.details);
    const done = checks.filter((c) => c.hecha).length;
    const est = estadoDe(it);
    // Repintar no pierde el foco ni el scroll (al marcar una casilla o cambiar el estado se repinta todo)
    const ae = dlg.contains(document.activeElement) ? document.activeElement : null;
    const dataAttr = ae && [...ae.attributes].find((a) => a.name.startsWith('data-') || a.name === 'id');
    const focusSel = dataAttr ? `[${dataAttr.name}="${CSS.escape(dataAttr.value)}"]` : null;
    const scroll = dlg.querySelector('.pf-body')?.scrollTop || 0;
    // Lo que se está escribiendo en los campos de añadir y en el comentario no se pierde al repintar
    const typed = Object.fromEntries(['pfCheckIn', 'pfStepIn', 'pfComIn'].map((k) => [k, dlg.querySelector('#' + k)?.value || '']));
    dlg.innerHTML = `<div class="modal-header pf-head">
        <label class="sr-only" for="pfTitle" id="pfTitleLabel">Título de la tarea</label>
        <textarea id="pfTitle" class="pf-title" rows="1" maxlength="2000">${esc(it.text.split('\n')[0])}</textarea>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar la ficha">${icon('x')}</button></div>
      <div class="modal-body pf-body">
        <div class="pf-meta">
          <div class="pf-field pf-field-wide"><span class="pf-label">Estado</span>
            <div class="segmented" role="group" aria-label="Estado">${ESTADOS.map(([k, l, ic]) => `<button type="button" data-estado="${k}" aria-pressed="${est === k}">${icon(ic, 'icon-sm')}${l}</button>`).join('')}</div></div>
          <label class="pf-field"><span class="pf-label">Prioridad</span><select class="select input-sm" data-f="priority">${PRIOS.map(([v, l]) => `<option value="${v}" ${String(it.priority || '') === v ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
          <label class="pf-field"><span class="pf-label">Fecha</span><input type="date" class="input input-sm" data-f="due_date" value="${esc(it.due_date || '')}"></label>
          ${P ? `<label class="pf-field"><span class="pf-label">Versión</span><select class="select input-sm" data-f="version_id"><option value="0">Sin versión</option>${vers.map((v) => `<option value="${v.id}" ${it.version_id === v.id ? 'selected' : ''}>${esc(v.nombre)}${v.titulo ? ` · ${esc(v.titulo)}` : ''}</option>`).join('')}</select></label>` : ''}
        </div>

        <section class="pf-sec" aria-labelledby="pfDescH">
          <div class="pf-sec-head"><h3 id="pfDescH">${icon('file-text', 'icon-sm')}Descripción</h3><span class="grow"></span>
            <button type="button" class="btn btn-ghost btn-sm" data-edit-desc>${icon('pencil', 'icon-sm')}${it.details ? 'Editar' : 'Escribir'}</button></div>
          <div class="pf-desc" id="pfDesc">${it.details ? `<div class="md">${renderMarkdown(it.details)}</div>` : '<p class="muted small">Sin descripción. Admite Markdown: títulos, listas, enlaces y casillas «- [ ]», que forman la checklist.</p>'}</div>
        </section>

        <section class="pf-sec" aria-labelledby="pfCheckH">
          <div class="pf-sec-head"><h3 id="pfCheckH">${icon('list-checks', 'icon-sm')}Checklist</h3>${checks.length ? `<span class="tiny tabular muted">${done}/${checks.length}</span>` : ''}</div>
          ${checks.length ? `<div class="pj-progress pf-progress" role="progressbar" aria-label="Checklist" aria-valuemin="0" aria-valuemax="${checks.length}" aria-valuenow="${done}"><span style="width:${Math.round((100 * done) / checks.length)}%"></span></div>` : ''}
          <form class="pf-add" data-add-check autocomplete="off"><label class="sr-only" for="pfCheckIn">Nuevo elemento de la checklist</label>
            <input id="pfCheckIn" class="input input-sm" maxlength="300" placeholder="Añadir a la checklist…"><button type="submit" class="btn btn-sm">${icon('plus', 'icon-sm')}<span class="sr-only">Añadir</span></button></form>
        </section>

        <section class="pf-sec" aria-labelledby="pfStepsH">
          <div class="pf-sec-head"><h3 id="pfStepsH">${icon('list-todo', 'icon-sm')}Subtareas</h3>${kids.length ? `<span class="tiny tabular muted">${kids.filter((k) => k.done).length}/${kids.length}</span>` : ''}</div>
          ${kids.length ? `<ul class="pf-steps">${kids.map((k) => `<li class="pf-step${k.done ? ' is-done' : ''}">
              <input type="checkbox" class="checkbox" data-step-done="${k.id}" ${k.done ? 'checked' : ''} aria-label="Hecha: ${esc(k.text.split('\n')[0])}">
              <span class="pf-step-text">${esc(k.text.split('\n')[0])}</span>
              <button type="button" class="btn btn-ghost btn-icon btn-sm" data-step-del="${k.id}" aria-label="Borrar la subtarea «${esc(k.text.slice(0, 40))}»">${icon('x', 'icon-sm')}</button></li>`).join('')}</ul>` : ''}
          <form class="pf-add" data-add-step autocomplete="off"><label class="sr-only" for="pfStepIn">Nueva subtarea</label>
            <input id="pfStepIn" class="input input-sm" maxlength="2000" placeholder="Añadir una subtarea…"><button type="submit" class="btn btn-sm">${icon('plus', 'icon-sm')}<span class="sr-only">Añadir</span></button></form>
        </section>

        <section class="pf-sec" aria-labelledby="pfAdjH">
          <div class="pf-sec-head"><h3 id="pfAdjH">${icon('paperclip', 'icon-sm')}Adjuntos</h3><span class="tiny tabular muted" data-adj-count></span></div>
          <div class="pf-adj" id="pfAdj"><span class="skeleton skeleton-line"></span></div>
          <label class="pf-drop" data-drop><input type="file" multiple class="sr-only" data-file>${icon('file-up', 'icon-sm')}<span>Arrastra archivos aquí o <u>elígelos</u> (hasta 25 MB cada uno)</span></label>
        </section>

        <section class="pf-sec" aria-labelledby="pfComH">
          <div class="pf-sec-head"><h3 id="pfComH">${icon('message-square', 'icon-sm')}Comentarios</h3><span class="tiny tabular muted" data-com-count></span></div>
          <ol class="pf-coms" id="pfComs"></ol>
          <form class="pf-com-form" data-com-form><label class="sr-only" for="pfComIn">Nuevo comentario</label>
            <textarea id="pfComIn" class="textarea" rows="2" maxlength="10000" placeholder="Escribe un comentario (Markdown; Ctrl+Enter para enviar)…"></textarea>
            <button type="submit" class="btn btn-primary btn-sm">${icon('send', 'icon-sm')}Comentar</button></form>
        </section>
      </div>
      <div class="modal-footer pf-foot">
        <button type="button" class="btn btn-ghost btn-sm" data-del>${icon('trash-2', 'icon-sm')}Borrar</button>
        <span class="grow"></span>
        <a class="btn btn-sm" href="/tareas?item=${id}">${icon('external-link', 'icon-sm')}Abrir en Tareas</a></div>`;
    wire();
    if (current.extras) paintExtras();
    Object.entries(typed).forEach(([k, v]) => { const f = dlg.querySelector('#' + k); if (f && v) f.value = v; });
    dlg.querySelector('.pf-body').scrollTop = scroll;
    if (focusSel) dlg.querySelector(focusSel)?.focus({ preventScroll: true });
  }

  const upd = (patch) => Items.update(current.id, patch).catch(() => {});

  function wire() {
    const { dlg, id } = current;
    const it = Items.get(id);
    const title = dlg.querySelector('#pfTitle');
    const grow = () => { title.style.height = 'auto'; title.style.height = title.scrollHeight + 'px'; };
    requestAnimationFrame(grow);
    title.addEventListener('input', grow);
    title.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); title.blur(); } });
    title.addEventListener('change', () => {
      const t = title.value.replace(/\s+/g, ' ').trim();
      if (!t) { title.value = it.text.split('\n')[0]; return; }
      const rest = it.text.split('\n').slice(1).join('\n');
      if (t !== it.text.split('\n')[0]) upd({ text: rest ? `${t}\n${rest}` : t });
    });
    dlg.querySelectorAll('[data-estado]').forEach((b) => b.addEventListener('click', () => {
      const k = b.dataset.estado;
      upd(k === 'done' ? { done: true } : { done: false, en_curso: k === 'doing' });
    }));
    dlg.querySelectorAll('[data-f]').forEach((f) => f.addEventListener('change', () => {
      const v = f.value;
      upd({ [f.dataset.f]: f.dataset.f === 'version_id' ? Number(v) || 0 : v });
    }));
    // Casillas de la descripción: marcar sin abrir el editor
    dlg.querySelectorAll('#pfDesc input[type=checkbox]').forEach((cb, i) => {
      cb.disabled = false;
      cb.dataset.chk = String(i);
      cb.classList.add('checkbox');
      cb.setAttribute('aria-label', `Marcar «${checklist(it.details)[i]?.texto || 'elemento'}»`);
      cb.addEventListener('change', () => upd({ details: toggleCheck(Items.get(id).details, i) }));
    });
    dlg.querySelector('[data-edit-desc]').addEventListener('click', editDesc);
    dlg.querySelector('[data-add-check]').addEventListener('submit', (e) => {
      e.preventDefault();
      const input = e.currentTarget.querySelector('input'), t = input.value.trim();
      if (!t) return;
      input.value = '';
      const src = (Items.get(id).details || '').replace(/\s+$/, '');
      upd({ details: `${src}${src ? '\n' : ''}- [ ] ${t}` }).then(() => dlg.querySelector('#pfCheckIn')?.focus());
    });
    dlg.querySelector('[data-add-step]').addEventListener('submit', async (e) => {
      e.preventDefault();
      const input = e.currentTarget.querySelector('input'), t = input.value.trim();
      if (!t) return;
      input.value = '';
      try { await Items.create({ text: t, type: Items.get(id).type, parent_id: id }); } catch { input.value = t; return; }
      dlg.querySelector('#pfStepIn')?.focus();
    });
    dlg.querySelectorAll('[data-step-done]').forEach((cb) => cb.addEventListener('change', () => Items.setDone(Number(cb.dataset.stepDone), cb.checked)));
    dlg.querySelectorAll('[data-step-del]').forEach((b) => b.addEventListener('click', () => Items.remove(Number(b.dataset.stepDel), { label: 'Subtarea borrada' })));
    dlg.querySelector('[data-del]').addEventListener('click', async () => {
      if (!(await uiConfirm('¿Borrar la tarea?', 'Con sus subtareas. Sus comentarios y adjuntos vuelven si la restauras desde la papelera (30 días).', { confirmLabel: 'Borrar', danger: true }))) return;
      closeModal(dlg);
      Items.remove(id, { label: 'Tarea borrada' });
    });
    // Adjuntos: elegir o soltar
    const drop = dlg.querySelector('[data-drop]'), file = dlg.querySelector('[data-file]');
    file.addEventListener('change', () => { upload([...file.files]); file.value = ''; });
    ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, () => drop.classList.remove('is-over')));
    drop.addEventListener('drop', (e) => { e.preventDefault(); upload([...(e.dataTransfer?.files || [])]); });
    // Comentarios
    const form = dlg.querySelector('[data-com-form]'), ta = form.querySelector('textarea');
    ta.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); } });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const texto = ta.value.trim();
      if (!texto) return;
      ta.value = '';
      try { await api(`/api/items/${id}/comentarios`, { method: 'POST', body: { texto } }); } catch { ta.value = texto; return; }
      await loadExtras();
      dlg.querySelector('#pfComs li:last-child')?.scrollIntoView({ block: 'nearest' });
    });
  }

  function editDesc() {
    const { dlg, id } = current;
    current.editing = true;
    const box = dlg.querySelector('#pfDesc');
    box.innerHTML = `<label class="sr-only" for="pfDescIn">Descripción (Markdown)</label>
      <textarea id="pfDescIn" class="textarea pf-desc-edit" rows="8" maxlength="20000">${esc(Items.get(id).details || '')}</textarea>
      <div class="row pf-desc-actions"><span class="tiny muted">Markdown · «- [ ] algo» crea una casilla · Ctrl+Enter guarda</span><span class="grow"></span>
        <button type="button" class="btn btn-ghost btn-sm" data-cancel>Cancelar</button><button type="button" class="btn btn-primary btn-sm" data-save>Guardar</button></div>`;
    const ta = box.querySelector('textarea');
    ta.focus();
    const done = async (save) => {
      current.editing = false;
      if (save && ta.value !== (Items.get(id).details || '')) await upd({ details: ta.value });
      paint();
    };
    box.querySelector('[data-save]').addEventListener('click', () => done(true));
    box.querySelector('[data-cancel]').addEventListener('click', () => done(false));
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); done(true); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
    });
  }

  async function loadExtras() {
    if (!current) return;
    const id = current.id;
    try { current.extras = await api(`/api/items/${id}/extras`, { quiet: true }); } catch { current.extras = { comentarios: [], adjuntos: [], error: true }; }
    if (current?.id === id) paintExtras();
    current?.opts.onExtras?.(id, { comentarios: current.extras.comentarios.length, adjuntos: current.extras.adjuntos.length });
  }

  function paintExtras() {
    const { dlg, extras, id } = current;
    if (!extras) return;
    const adj = dlg.querySelector('#pfAdj'), coms = dlg.querySelector('#pfComs');
    if (!adj || !coms) return;
    dlg.querySelector('[data-adj-count]').textContent = extras.adjuntos.length || '';
    dlg.querySelector('[data-com-count]').textContent = extras.comentarios.length || '';
    adj.innerHTML = extras.error ? '<p class="small muted">No se pudieron cargar.</p>' : extras.adjuntos.length ? `<ul class="pf-files">${extras.adjuntos.map((a) => `<li class="pf-file">
        ${a.imagen ? `<img class="pf-thumb" src="${esc(a.url)}" alt="" width="40" height="40" loading="lazy" decoding="async">` : `<span class="pf-file-icon" aria-hidden="true">${icon(a.mime === 'application/pdf' ? 'file-text' : 'file', 'icon-sm')}</span>`}
        <a class="pf-file-name" href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.nombre)}</a>
        <span class="tiny muted tabular">${bytes(a.bytes || 0)}</span>
        <a class="btn btn-ghost btn-icon btn-sm" href="${esc(a.url)}?descargar=1" download aria-label="Descargar ${esc(a.nombre)}">${icon('download', 'icon-sm')}</a>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-adj-del="${a.id}" aria-label="Quitar ${esc(a.nombre)}">${icon('trash-2', 'icon-sm')}</button></li>`).join('')}</ul>` : '';
    coms.innerHTML = extras.comentarios.map((c) => `<li class="pf-com" data-com="${c.id}">
        <div class="pf-com-head tiny muted"><time datetime="${new Date(c.created_at * 1000).toISOString()}" title="${new Date(c.created_at * 1000).toLocaleString('es-ES')}">${timeAgo(c.created_at)}</time>${c.updated_at ? ' · editado' : ''}
          <span class="grow"></span><button type="button" class="btn btn-ghost btn-icon btn-sm" data-com-menu="${c.id}" aria-label="Acciones del comentario" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button></div>
        <div class="md pf-com-body">${renderMarkdown(c.texto)}</div></li>`).join('');
    adj.querySelectorAll('[data-adj-del]').forEach((b) => b.addEventListener('click', async () => {
      const a = extras.adjuntos.find((x) => x.id === Number(b.dataset.adjDel));
      let res;
      try { res = await api(`/api/items/${id}/adjuntos/${a.id}`, { method: 'DELETE' }); } catch { return; }
      await loadExtras();
      undoToast(`«${a.nombre}» quitado`, res, loadExtras);
    }));
    coms.querySelectorAll('[data-com-menu]').forEach((b) => b.addEventListener('click', () => {
      const c = extras.comentarios.find((x) => x.id === Number(b.dataset.comMenu));
      openMenu(b, [
        { label: 'Editar', icon: 'pencil', onClick: () => editCom(c) },
        { label: 'Borrar', icon: 'trash-2', danger: true, onClick: async () => {
          let res;
          try { res = await api(`/api/items/${id}/comentarios/${c.id}`, { method: 'DELETE' }); } catch { return; }
          await loadExtras();
          undoToast('Comentario borrado', res, loadExtras);
        } },
      ]);
    }));
  }

  function editCom(c) {
    const li = current.dlg.querySelector(`[data-com="${c.id}"]`);
    if (!li) return;
    current.editing = true;
    const body = li.querySelector('.pf-com-body');
    body.innerHTML = `<label class="sr-only" for="pfComEd">Editar comentario</label><textarea id="pfComEd" class="textarea" rows="3" maxlength="10000">${esc(c.texto)}</textarea>
      <div class="row pf-desc-actions"><span class="grow"></span><button type="button" class="btn btn-ghost btn-sm" data-cancel>Cancelar</button><button type="button" class="btn btn-primary btn-sm" data-save>Guardar</button></div>`;
    const ta = body.querySelector('textarea');
    ta.focus();
    const done = async (save) => {
      current.editing = false;
      if (save && ta.value.trim() && ta.value.trim() !== c.texto) {
        try { await api(`/api/items/${current.id}/comentarios/${c.id}`, { method: 'PATCH', body: { texto: ta.value } }); } catch { return; }
      }
      loadExtras();
    };
    body.querySelector('[data-save]').addEventListener('click', () => done(true));
    body.querySelector('[data-cancel]').addEventListener('click', () => done(false));
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); done(true); }
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
    });
  }

  async function upload(files) {
    if (!files.length || !current) return;
    const id = current.id;
    const drop = current.dlg.querySelector('[data-drop] span');
    let ok = 0;
    for (const [i, f] of files.entries()) {
      if (f.size > 25 * 1024 * 1024) { toast(`«${f.name}» supera los 25 MB`, { type: 'error' }); continue; }
      if (drop) drop.textContent = `Subiendo ${i + 1} de ${files.length}…`;
      const fd = new FormData();
      fd.append('archivo', f, f.name);
      try { await api(`/api/items/${id}/adjuntos`, { method: 'POST', body: fd }); ok++; } catch { /* api avisa */ }
    }
    if (ok) toast(ok === 1 ? 'Archivo adjuntado' : `${ok} archivos adjuntados`, { type: 'success', duration: 1600 });
    await loadExtras();
    if (current?.dlg) { const s = current.dlg.querySelector('[data-drop] span'); if (s) s.innerHTML = 'Arrastra archivos aquí o <u>elígelos</u> (hasta 25 MB cada uno)'; }
  }

  window.PjFicha = { open, checklist, toggleCheck, estadoDe };
})();
