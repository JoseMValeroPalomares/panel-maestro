/* ==========================================================================
   routines.js — rutinas por pasos (window.Routines)
     Routines.openTemplates()   crear una rutina desde una plantilla (de serie o tuya), con la
                                hora, la repetición y los pasos editables antes de crearla
     Routines.saveTemplate(id)  guardar una rutina (con sus pasos) como plantilla
     Routines.run(id)           hacerla paso a paso: el paso actual con su temporizador,
                                Intro = hecho, S = saltar, Espacio = pausa
   Datos: /api/routine-templates (app/routine_templates.py); los pasos se marcan con Items.setDone
   (marcar el último marca la rutina, app/routines.py).
   ========================================================================== */
(function () {
  'use strict';
  const esc = (s) => escapeHtml(String(s ?? ''));
  const hm = (t) => `${String(Math.floor(t / 60) % 24).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`;
  const toMin = (v) => (v ? Number(v.slice(0, 2)) * 60 + Number(v.slice(3, 5)) : null);
  const fmtMin = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}` : `${m} min`);

  function dialog(cls, html) {
    const dlg = document.createElement('dialog');
    dlg.className = `modal ${cls}`;
    dlg.innerHTML = html;
    document.body.appendChild(dlg);
    wireAllDialogs();
    return dlg;
  }

  /* ---------- Plantillas ---------- */
  async function openTemplates() {
    let list;
    try { list = (await api('/api/routine-templates', { quiet: true })).plantillas; } catch { toast('No se pudieron cargar las plantillas', { type: 'error' }); return; }
    const dlg = dialog('rt-dialog', `<div class="modal-header"><h2>Nueva rutina desde una plantilla</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body" data-rt-body></div>
      <div class="modal-footer" data-rt-foot hidden></div>`);
    const body = dlg.querySelector('[data-rt-body]'), foot = dlg.querySelector('[data-rt-foot]');

    const paintList = () => {
      foot.hidden = true;
      body.innerHTML = `<p class="small muted">Elige una y ajusta la hora, los días y los pasos antes de crearla. Guarda las tuyas desde el menú «…» de una rutina.</p>
        <ul class="rt-cards">${list.map((t) => `<li><button type="button" class="rt-card" data-key="${esc(t.key)}">
          <span class="tile tile-sm" data-section="tareas" aria-hidden="true">${icon(t.icon, 'icon-sm')}</span>
          <span class="rt-card-main"><span class="rt-card-title">${esc(t.title)}${t.builtin ? '' : ' <span class="tag">Tuya</span>'}</span>
            <span class="tiny muted">${esc(t.repeat_text)}${t.due_time ? ` · ${t.due_time}` : ''} · ${t.steps.length} pasos${t.total_min ? ` · ${fmtMin(t.total_min)}` : ''}</span>
            <span class="tiny subtle rt-card-steps">${t.steps.slice(0, 4).map((s) => esc(s.title)).join(' · ')}${t.steps.length > 4 ? ' …' : ''}</span></span>
          ${icon('chevron-right', 'icon-sm')}</button>
          ${t.builtin ? '' : `<button type="button" class="btn btn-ghost btn-icon btn-sm rt-card-del" data-del="${t.id}" aria-label="Borrar la plantilla «${esc(t.title)}»" title="Borrar la plantilla">${icon('trash-2', 'icon-sm')}</button>`}</li>`).join('')}</ul>`;
    };

    const paintForm = (t) => {
      let steps = t.steps.map((s) => ({ title: s.title, duration_min: s.duration_min || '' }));
      foot.hidden = false;
      foot.innerHTML = `<button type="button" class="btn" data-back>${icon('chevron-left', 'icon-sm')}Volver</button><span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="rtForm" class="btn btn-primary">Crear rutina</button>`;
      body.innerHTML = `<form id="rtForm" class="stack">
        <label class="field"><span class="field-label">Nombre</span><input name="title" class="input" maxlength="300" value="${esc(t.title)}" required></label>
        <label class="field"><span class="field-label">Empieza a las</span><input name="due_time" type="time" class="input" value="${esc(t.due_time || '')}"></label>
        ${dayPicker({ rule: t.repeat, legend: 'Se repite', note: everyNote(t.repeat, t.repeat_text) })}
        <fieldset class="rt-steps"><legend class="field-label">Pasos <span class="tiny muted" data-total></span></legend>
          <ol class="rt-step-list" data-steps></ol>
          <button type="button" class="btn btn-ghost btn-sm" data-add-step>${icon('plus', 'icon-sm')}Añadir un paso</button></fieldset>
      </form>`;
      const f = body.querySelector('form'), ol = body.querySelector('[data-steps]');
      const paintSteps = () => {
        let t0 = toMin(f.due_time.value);
        ol.innerHTML = steps.map((s, i) => {
          const at = t0 != null ? hm(t0) : '';
          if (t0 != null) t0 += Number(s.duration_min) || 0;
          return `<li class="rt-step-row"><span class="rt-step-at tabular tiny muted" aria-hidden="true">${at}</span>
            <label class="sr-only" for="rtS${i}">Paso ${i + 1}</label><input id="rtS${i}" class="input input-sm" data-i="${i}" data-k="title" maxlength="300" value="${esc(s.title)}" placeholder="Paso">
            <label class="sr-only" for="rtD${i}">Minutos del paso ${i + 1}</label><input id="rtD${i}" class="input input-sm tabular rt-step-min" data-i="${i}" data-k="duration_min" type="number" min="0" max="600" value="${esc(s.duration_min)}" placeholder="min">
            <button type="button" class="btn btn-ghost btn-icon btn-sm" data-rm="${i}" aria-label="Quitar el paso ${i + 1}">${icon('x', 'icon-sm')}</button></li>`;
        }).join('');
        const total = steps.reduce((a, s) => a + (Number(s.duration_min) || 0), 0);
        body.querySelector('[data-total]').textContent = total ? `· ${fmtMin(total)}${f.due_time.value ? `, de ${f.due_time.value} a ${hm(toMin(f.due_time.value) + total)}` : ''}` : '';
      };
      paintSteps();
      // al escribir solo cambia el dato (y las horas si es una duración): no se repinta el campo con el foco
      ol.addEventListener('input', (e) => {
        const inp = e.target.closest('[data-i]');
        if (!inp) return;
        steps[Number(inp.dataset.i)][inp.dataset.k] = inp.value;
        if (inp.dataset.k === 'duration_min') { const pos = inp.id; paintSteps(); body.querySelector(`#${pos}`)?.focus(); }
      });
      f.due_time.addEventListener('change', paintSteps);
      ol.addEventListener('click', (e) => {
        const rm = e.target.closest('[data-rm]');
        if (rm) { steps.splice(Number(rm.dataset.rm), 1); paintSteps(); }
      });
      body.querySelector('[data-add-step]').addEventListener('click', () => {
        steps.push({ title: '', duration_min: 10 });
        paintSteps();
        ol.querySelector(`#rtS${steps.length - 1}`)?.focus();
      });
      f.addEventListener('submit', async (e) => {
        e.preventDefault();
        const repeat = repeatFromDays(f, t.repeat);
        if (!repeat) { toast('Elige al menos un día', { type: 'info' }); return; }
        const btn = foot.querySelector('[type=submit]');
        btn.classList.add('is-loading');
        try {
          await api('/api/routine-templates/apply', { method: 'POST', body: {
            key: t.key, title: f.title.value.trim(), due_time: f.due_time.value, repeat,
            steps: steps.filter((s) => s.title.trim()).map((s) => ({ title: s.title.trim(), duration_min: Number(s.duration_min) || null })),
          } });
        } catch { btn.classList.remove('is-loading'); return; }
        closeModal(dlg);
        toast(`Rutina «${f.title.value.trim()}» creada`);
        await Items.load();
      });
      foot.querySelector('[data-back]').addEventListener('click', paintList);
      f.title.focus();
    };

    body.addEventListener('click', async (e) => {
      const del = e.target.closest('[data-del]');
      if (del) {
        if (!(await uiConfirm('¿Borrar esta plantilla?', 'Las rutinas que ya creaste con ella no cambian.', { confirmLabel: 'Borrar', danger: true }))) return;
        await api(`/api/routine-templates/${del.dataset.del}`, { method: 'DELETE' });
        list = list.filter((t) => String(t.id) !== del.dataset.del || t.builtin);
        paintList();
        return;
      }
      const card = e.target.closest('[data-key]');
      if (card) paintForm(list.find((t) => t.key === card.dataset.key));
    });
    paintList();
    openModal(dlg, { onClose: () => dlg.remove() });
  }

  async function saveTemplate(id) {
    const it = Items.get(id);
    if (!it) return;
    if (!Items.children(id).length && !(await uiConfirm('Esta rutina no tiene pasos', '¿Guardarla igualmente como plantilla?', { confirmLabel: 'Guardar' }))) return;
    const name = await uiPrompt('Guardar como plantilla', { label: 'Nombre', value: it.text.split('\n')[0].slice(0, 120), confirmLabel: 'Guardar' });
    if (!name?.trim()) return;
    await api('/api/routine-templates', { method: 'POST', body: { item_id: id, name: name.trim() } });
    toast('Plantilla guardada: la tienes en «Plantillas» del grupo Rutinas');
  }

  /* ---------- Paso a paso ---------- */
  function run(id) {
    const routine = Items.get(id);
    if (!routine) return;
    let steps = Items.children(id).filter((s) => s.today !== false);  // solo los bloques de hoy
    if (!steps.length) { toast('Añade pasos a la rutina para hacerla paso a paso', { type: 'info' }); return; }
    let cur = Math.max(0, steps.findIndex((s) => !s.done));
    let left = null, timer = null, paused = false, busy = false;
    const dlg = dialog('rt-run', `<div class="modal-header"><h2>${icon('play', 'icon-sm')}${esc(routine.text.split('\n')[0])}</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body" data-run-body aria-live="polite"></div>`);
    const body = dlg.querySelector('[data-run-body]');
    const stop = () => { clearInterval(timer); timer = null; };
    const tick = () => {
      if (paused || left == null) return;
      left = Math.max(0, left - 1);
      const el = body.querySelector('[data-left]');
      if (el) { el.textContent = clock(left); el.classList.toggle('is-over', left === 0); }
      if (left === 0) { stop(); navigator.vibrate?.([120, 80, 120]); toast('Tiempo del paso cumplido', { type: 'info', duration: 2000 }); }
    };
    const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    const startTimer = () => {
      stop();
      const s = steps[cur];
      left = s?.duration_min ? s.duration_min * 60 : null;
      paused = false;
      if (left) timer = setInterval(tick, 1000);
    };

    const paint = () => {
      const done = steps.filter((s) => s.done).length;
      const all = done === steps.length;
      const pct = Math.round(done / steps.length * 100);
      if (all) {
        stop();
        const r = Items.get(id);
        body.innerHTML = `<div class="rt-run-done"><span class="rt-run-done-icon" aria-hidden="true">${icon('circle-check')}</span>
          <h3>Rutina hecha</h3><p class="muted">${r?.streak?.actual ? `Racha de ${r.streak.actual} ${r.streak.actual === 1 ? 'día' : 'días'}.` : 'Primer día de la racha.'}</p>
          <button type="button" class="btn btn-primary" data-close>Cerrar</button></div>`;
        body.querySelector('[data-close]').focus();
        return;
      }
      const s = steps[cur];
      body.innerHTML = `<div class="rt-run-progress"><span class="meter" aria-hidden="true"><span style="width:${pct}%"></span></span>
          <span class="tiny muted tabular">${done} de ${steps.length} pasos</span></div>
        <section class="rt-run-now" aria-label="Paso actual">
          <span class="tiny muted">Paso ${cur + 1}${s.duration_min ? ` · ${fmtMin(s.duration_min)}` : ''}</span>
          <h3 class="rt-run-title">${esc(s.text.split('\n')[0])}</h3>
          ${left != null ? `<p class="rt-run-clock tabular" data-left>${clock(left)}</p>` : ''}
          <div class="rt-run-actions">
            <button type="button" class="btn btn-primary" data-run-act="done">${icon('check', 'icon-sm')}Hecho <kbd>Intro</kbd></button>
            <button type="button" class="btn" data-run-act="skip">${icon('skip-forward', 'icon-sm')}Saltar</button>
            ${left != null ? `<button type="button" class="btn btn-ghost" data-run-act="pause" aria-pressed="${paused}">${icon(paused ? 'play' : 'pause', 'icon-sm')}${paused ? 'Seguir' : 'Pausa'}</button>` : ''}
          </div></section>
        <ol class="rt-run-list">${steps.map((x, i) => `<li><button type="button" class="rt-run-step${x.done ? ' is-done' : ''}${i === cur ? ' is-current' : ''}" data-go="${i}" ${i === cur ? 'aria-current="step"' : ''}>
          <span class="rt-run-dot" aria-hidden="true">${x.done ? icon('check', 'icon-sm') : i + 1}</span><span class="grow">${esc(x.text.split('\n')[0])}</span>
          ${x.duration_min ? `<span class="tiny muted tabular">${fmtMin(x.duration_min)}</span>` : ''}<span class="sr-only">${x.done ? '(hecho)' : ''}</span></button></li>`).join('')}</ol>`;
      body.querySelector('[data-run-act="done"]').focus({ preventScroll: true });
    };

    const nextOpen = (from) => {
      for (let k = 1; k <= steps.length; k++) { const i = (from + k) % steps.length; if (!steps[i].done) return i; }
      return from;
    };
    async function markDone() {
      if (busy) return;
      busy = true;
      const s = steps[cur];
      try { await Items.setDone(s.id, true); } catch { busy = false; return; }
      steps = Items.children(id).filter((x) => x.today !== false);  // tras recargar: el estado real (y la rutina, si era el último)
      cur = nextOpen(cur);
      busy = false;
      startTimer();
      paint();
    }
    body.addEventListener('click', (e) => {
      const b = e.target.closest('[data-run-act], [data-go]');
      if (!b) return;
      if (b.dataset.go != null) { cur = Number(b.dataset.go); if (steps[cur].done) return; startTimer(); paint(); return; }
      const act = b.dataset.runAct;
      if (act === 'done') markDone();
      if (act === 'skip') { cur = nextOpen(cur); startTimer(); paint(); }
      if (act === 'pause') { paused = !paused; paint(); }
    });
    dlg.addEventListener('keydown', (e) => {
      if (e.target.closest('input, textarea, select') || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'Enter' && !e.target.closest('[data-go], [data-close], [data-run-act="skip"], [data-run-act="pause"]')) { e.preventDefault(); markDone(); }
      else if (e.key === 's' || e.key === 'S') { e.preventDefault(); cur = nextOpen(cur); startTimer(); paint(); }
      else if (e.key === ' ' && left != null && !e.target.closest('button')) { e.preventDefault(); paused = !paused; paint(); }
    });
    startTimer();
    paint();
    openModal(dlg, { focus: '[data-run-act="done"]', onClose: () => { stop(); dlg.remove(); } });
  }

  window.Routines = { openTemplates, saveTemplate, run };
})();
