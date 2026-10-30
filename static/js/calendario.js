/* ==========================================================================
   calendario.js — página /calendario: el componente (calendar.js) a tamaño completo,
   con la creación rápida en lenguaje natural (/api/capture con «e:»), el minicalendario, las
   rutinas de hoy, las tareas e ideas sin fecha para arrastrar a la rejilla y la leyenda.
   La vista y el día se guardan en la URL (?vista=&dia=), así recargar no te mueve.
   ========================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const saved = Prefs.get('calendar-view', null);
  const cal = Calendar.mount($('calendar'), {
    view: params.get('vista') || saved || undefined,
    date: params.get('dia') || undefined,
    onChange: (c) => {
      const t = c.title();
      $('calTitle').textContent = t.charAt(0).toUpperCase() + t.slice(1);
      document.querySelectorAll('[data-cal-view]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.calView === c.view)));
      history.replaceState(null, '', `?vista=${c.view}&dia=${Calendar.iso(c.date)}`);
      paintHours(c);
      miniDots.key = '';  // cada pintado refresca los puntos (algo se ha podido crear o mover)
      paintMini(c);
    },
  });

  document.querySelectorAll('[data-cal-view]').forEach((b) => b.addEventListener('click', () => {
    cal.setView(b.dataset.calView);
    Prefs.set('calendar-view', b.dataset.calView);
  }));
  document.querySelectorAll('[data-cal-go]').forEach((b) => b.addEventListener('click', () => cal.go(Number(b.dataset.calGo))));
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (/^(input|textarea|select)$/i.test(t.tagName) || t.isContentEditable || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('dialog[open]')) return;
    const views = { d: 'day', 3: '3d', s: 'week', w: 'week', m: 'month', a: 'agenda' };
    if (e.key === 'ArrowLeft') { e.preventDefault(); cal.go(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); cal.go(1); }
    else if (e.key.toLowerCase() === 't') { e.preventDefault(); cal.go(0); }
    else if (e.key.toLowerCase() === 'n' && Prefs.get('capture-key', 'c') !== 'n') { e.preventDefault(); $('calQuickText').focus(); }
    else if (views[e.key.toLowerCase()]) { e.preventDefault(); cal.setView(views[e.key.toLowerCase()]); Prefs.set('calendar-view', cal.view); }
  });

  /* ---------- Crear escribiendo: «dentista mañana 17:00» ---------- */
  const PREFIX = /^\s*[tire]\s*:/i;
  const quick = $('calQuickText'), hint = $('calQuickHint'), HINT = '';  // la línea solo se ve al escribir (vista previa)
  const asEvent = (t) => (PREFIX.test(t) ? t : `e: ${t}`);
  let qTimer = null, qSeq = 0;
  quick.addEventListener('input', () => {
    clearTimeout(qTimer);
    const t = quick.value.trim();
    hint.hidden = !t;
    if (!t) { hint.textContent = HINT; hint.classList.remove('is-ok', 'is-warn'); return; }
    qTimer = setTimeout(async () => {
      const seq = ++qSeq;
      let r;
      try { r = await api('/api/capture', { method: 'POST', body: { text: asEvent(t), dry_run: true }, quiet: true }); } catch { return; }
      if (seq !== qSeq) return;
      const ok = r.kind !== 'inbox' || !r.revisar;
      hint.textContent = r.kind === 'evento' ? `${r.preview.title} · ${r.preview.when}` : ok ? r.message : 'Sin fecha clara: irá al Inbox para revisarlo';
      hint.classList.toggle('is-ok', ok);
      hint.classList.toggle('is-warn', !ok);
    }, 220);
  });
  $('calQuick').addEventListener('submit', async (e) => {
    e.preventDefault();
    const t = quick.value.trim();
    if (!t) { quick.focus(); return; }
    clearTimeout(qTimer);
    qSeq++;
    let r;
    try { r = await api('/api/capture', { method: 'POST', body: { text: asEvent(t) } }); } catch { return; }
    toast(r.message, { type: r.revisar ? 'warning' : 'info' });
    quick.value = '';
    hint.textContent = HINT;
    hint.hidden = true;
    hint.classList.remove('is-ok', 'is-warn');
    if (r.kind === 'evento' && r.preview?.start) cal.goTo(r.preview.start.slice(0, 10));
    else Calendar.refreshAll();
  });

  /* ---------- Minicalendario: ir a un día; los puntos marcan los días con algo ---------- */
  let mini = null, miniDots = { key: '', days: new Set() };
  const MONTHS = (d) => d.toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
  function paintMini(c) {
    const ref = c ? new Date(c.date.getFullYear(), c.date.getMonth(), 1) : mini;
    if (c) mini = ref;
    const first = Calendar.addDays(mini, -((mini.getDay() + 6) % 7));
    const [r0, r1] = cal.view === 'month' || cal.view === 'agenda' ? ['', ''] : cal.range().map(Calendar.iso);  // en Mes y Agenda no se marca el rango
    const key = Calendar.iso(first);
    if (miniDots.key !== key) loadDots(first, key);
    let cells = '';
    for (let i = 0; i < 42; i++) {
      const d = Calendar.addDays(first, i), k = Calendar.iso(d);
      const cls = [d.getMonth() !== mini.getMonth() && 'is-out', k === today && 'is-today', k >= r0 && k <= r1 && 'is-shown', miniDots.days.has(k) && 'has-dot'].filter(Boolean).join(' ');
      cells += `<button type="button" class="cal-mini-day tabular ${cls}" data-mini="${k}" aria-label="${escapeHtml(d.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' }))}${miniDots.days.has(k) ? ', con cosas' : ''}"${k === today ? ' aria-current="date"' : ''}>${d.getDate()}</button>`;
    }
    const m = MONTHS(mini);
    $('calMini').innerHTML = `<div class="cal-mini-head"><span class="cal-mini-title">${m.charAt(0).toUpperCase() + m.slice(1)}</span>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-mini-go="-1" aria-label="Mes anterior">${icon('chevron-left', 'icon-sm')}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-mini-go="1" aria-label="Mes siguiente">${icon('chevron-right', 'icon-sm')}</button></div>
      <div class="cal-mini-grid">${['L', 'M', 'X', 'J', 'V', 'S', 'D'].map((d) => `<span class="cal-mini-dow" aria-hidden="true">${d}</span>`).join('')}${cells}</div>`;
  }
  async function loadDots(first, key) {
    miniDots = { key, days: new Set() };
    try {
      const { entries } = await api(`/api/calendar/entries?start=${key}&end=${Calendar.iso(Calendar.addDays(first, 41))}`, { quiet: true });
      entries.filter((e) => e.kind !== 'routine').forEach((e) => miniDots.days.add(e.start.slice(0, 10)));
    } catch { return; }
    if (miniDots.key === key) paintMini();
  }
  $('calMini').addEventListener('click', (e) => {
    const go = e.target.closest('[data-mini-go]');
    if (go) { mini = new Date(mini.getFullYear(), mini.getMonth() + Number(go.dataset.miniGo), 1); paintMini(); return; }
    const d = e.target.closest('[data-mini]');
    if (d) cal.goTo(d.dataset.mini);
  });

  /* ---------- Horario visible (Día, 3 días y Semana): se guarda en el servidor ---------- */
  function paintHours(c = cal) {
    const h = Calendar.hours();
    $('calHoursLabel').textContent = `${h.start}–${h.end} h`;
    $('calHoursBtn').hidden = !['day', '3d', 'week'].includes(c.view);
  }
  function openHours() {
    const h = Calendar.hours();
    const opts = (from, to, sel) => Array.from({ length: to - from + 1 }, (_, i) => from + i)
      .map((v) => `<option value="${v}" ${v === sel ? 'selected' : ''}>${String(v).padStart(2, '0')}:00</option>`).join('');
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm';
    dlg.innerHTML = `<div class="modal-header"><h2>Horario visible</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body stack" id="calHoursForm">
        <p class="small muted">Las horas que se ven en Día, 3 días y Semana. Lo que quede fuera se avisa arriba o abajo de cada día.</p>
        <div class="rt-form-grid">
          <label class="field"><span class="field-label">Desde</span><select name="start" class="select">${opts(0, 23, h.start)}</select></label>
          <label class="field"><span class="field-label">Hasta</span><select name="end" class="select">${opts(1, 24, h.end)}</select></label>
        </div>
        <div class="chips" role="group" aria-label="Horarios rápidos">${[[8, 22, 'Día normal'], [7, 23, 'Más amplio'], [0, 24, 'Todo el día']]
          .map(([a, b, l]) => `<button type="button" class="chip" data-hours="${a},${b}">${l} · ${a}–${b} h</button>`).join('')}</div>
        <div class="field"><span class="field-label">Altura de cada hora</span>
          <div class="choice-chips" role="radiogroup" aria-label="Altura de cada hora">${[['normal', 'Normal'], ['tall', 'Alta'], ['fit', 'Que quepa todo']]
            .map(([v, l]) => `<label class="choice-chip"><input type="radio" name="size" value="${v}" ${Calendar.hourSize === v ? 'checked' : ''}><span>${l}</span></label>`).join('')}</div></div>
      </form>
      <div class="modal-footer"><span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="calHoursForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    const f = dlg.querySelector('form');
    dlg.addEventListener('click', (e) => {
      const q = e.target.closest('[data-hours]');
      if (q) { const [a, b] = q.dataset.hours.split(',').map(Number); f.start.value = a; f.end.value = b; }
    });
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const start = Number(f.start.value), end = Number(f.end.value);
      if (end <= start) { toast('El final tiene que ir después del principio', { type: 'info' }); return; }
      Calendar.setHourSize(f.size.value);
      Calendar.setHours(start, end);
      closeModal(dlg);
      paintHours();
    });
    openModal(dlg, { focus: 'select[name=start]', onClose: () => dlg.remove() });
  }
  $('calHoursBtn').addEventListener('click', openHours);
  const paintRoutinesBtn = () => $('calRoutinesBtn').setAttribute('aria-pressed', String(Calendar.showRoutines));
  $('calRoutinesBtn').addEventListener('click', () => { Calendar.setShowRoutines(!Calendar.showRoutines); paintRoutinesBtn(); });
  document.addEventListener('prefs:changed', paintRoutinesBtn);
  Prefs.ready.then(paintRoutinesBtn);

  /* ---------- Menú: plantillas de día, exportar, sincronizar ---------- */
  $('calMenuBtn').addEventListener('click', (e) => openMenu(e.currentTarget, [
    { label: 'Guardar este día como plantilla…', icon: 'layout-template', onClick: saveDayTemplate },
    { label: 'Aplicar una plantilla de día…', icon: 'copy-plus', onClick: applyDayTemplate },
    { separator: true },
    { label: 'Sincronizar ahora (iCloud y ESP32)', icon: 'refresh-cw', onClick: syncNow },
    { label: 'Exportar (.ics)', icon: 'download', onClick: () => { location.href = '/api/calendar/export.ics'; } },
    { label: 'Horario visible…', icon: 'clock', onClick: openHours },
    { label: 'Avisos y recordatorios…', icon: 'bell', onClick: () => window.Reminders?.openSettings() },
  ]));

  const dayShown = () => Calendar.iso(cal.date);
  async function saveDayTemplate() {
    const day = dayShown();
    const name = await uiPrompt('Guardar el día como plantilla', {
      label: 'Nombre', placeholder: 'Día de clase', confirmLabel: 'Guardar',
      message: `Se guardan los eventos, los bloques y las comidas del ${new Date(day + 'T00:00').toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' })}. Las rutinas ya se repiten solas.`,
    });
    if (!name?.trim()) return;
    const r = await api('/api/day-templates', { method: 'POST', body: { name: name.trim(), day } });
    toast(`Plantilla guardada: ${r.eventos} eventos y bloques, ${r.comidas} platos`);
  }
  async function applyDayTemplate() {
    const { plantillas } = await api('/api/day-templates', { quiet: true });
    if (!plantillas.length) { toast('Aún no hay plantillas: guarda primero un día', { type: 'info' }); return; }
    const picked = await uiPick({
      title: `Aplicar al ${new Date(dayShown() + 'T00:00').toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' })}`,
      placeholder: 'Busca una plantilla',
      load: () => plantillas.map((p) => ({ id: p.id, label: p.name, sub: `${p.eventos} eventos y bloques · ${p.comidas} platos`, icon: 'layout-template' })),
    });
    if (!picked) return;
    const r = await api(`/api/day-templates/${picked.id}/apply`, { method: 'POST', body: { day: dayShown() } });
    toast(`Aplicada: ${r.eventos} eventos y bloques, ${r.platos} platos`);
    Calendar.refreshAll();
  }
  async function syncNow() {
    await api('/api/calendar/sync', { method: 'POST' });
    toast('Sincronizando con iCloud y el ESP32…', { type: 'info' });
    setTimeout(() => Calendar.refreshAll(), 6000);
  }

  /* ---------- Barra lateral ---------- */
  const today = Calendar.iso(new Date());
  function paintSide() {
    if (!Items.state.loaded) return;
    const all = Items.state.items;
    // solo las rutinas (sus pasos van dentro de cada una)
    const rut = all.filter((i) => i.type === 'rutina' && !i.parent_id && i.today)
      .sort((a, b) => (a.due_time || '99').localeCompare(b.due_time || '99'));
    $('calRutCount').textContent = rut.length ? `${rut.filter((r) => r.done).length}/${rut.length}` : '';
    $('calRoutines').innerHTML = rut.length ? rut.map((r) => {
      const steps = Items.children(r.id);
      return `<li class="hoy-row cal-side-row${r.done ? ' is-done' : ''}">
        <button type="button" class="card-check small-check${r.done ? ' done' : ''}" data-rut="${r.id}" role="checkbox" aria-checked="${r.done}" aria-label="${r.done ? 'Desmarcar' : 'Marcar hecha hoy'}: ${escapeHtml(r.text)}">${icon('check', 'icon-sm')}</button>
        <span class="hoy-title">${escapeHtml(r.text.split('\n')[0])}${steps.length ? ` <span class="tiny muted tabular">${steps.filter((x) => x.done).length}/${steps.length}</span>` : ''}</span>
        ${r.due_time ? `<span class="tiny muted tabular">${r.due_time}</span>` : ''}
        ${r.streak?.actual ? `<span class="streak tabular" title="Racha">${icon('flame', 'icon-sm')}${r.streak.actual}</span>` : ''}
        ${steps.length && !r.done ? `<button type="button" class="btn btn-ghost btn-icon btn-sm" data-run="${r.id}" aria-label="Empezar «${escapeHtml(r.text.slice(0, 40))}» paso a paso" title="Empezar paso a paso">${icon('play', 'icon-sm')}</button>` : ''}</li>`;
    }).join('')
      : `<li class="hoy-empty tiny muted">Ninguna rutina hoy. <button type="button" class="link-btn" data-rt-templates>Crear una desde una plantilla</button></li>`;
    const pend = all.filter((i) => !i.parent_id && !i.done && i.type !== 'rutina' && !i.due_date);
    const sin = pend.slice(0, showAll ? 60 : 8);
    $('calUnscheduled').innerHTML = (sin.length ? sin.map((i) => `<li class="hoy-row cal-side-row cal-drag" draggable="true" data-cal-drag-item="${i.id}" data-type="${i.type}">
        <span class="drag-dot" aria-hidden="true">${icon('grip-vertical', 'icon-sm')}</span>
        <span class="hoy-title">${escapeHtml(i.text.split('\n')[0].slice(0, 90))}</span>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-plan="${i.id}" aria-label="Programar «${escapeHtml(i.text.slice(0, 40))}»" title="Programar">${icon('calendar-clock', 'icon-sm')}</button></li>`).join('')
      : '<li class="hoy-empty tiny muted">Todo tiene fecha</li>')
      + (pend.length > sin.length ? `<li><button type="button" class="btn btn-ghost btn-sm btn-block" data-show-all>Ver ${pend.length - sin.length} más</button></li>` : '');
  }
  let showAll = false;
  document.addEventListener('items:changed', paintSide);
  Items.ready().then(paintSide).catch(() => {});

  $('calRoutines').addEventListener('click', async (e) => {
    if (e.target.closest('[data-rt-templates]')) { Routines.openTemplates(); return; }
    const run = e.target.closest('[data-run]');
    if (run) { Routines.run(Number(run.dataset.run)); return; }
    const b = e.target.closest('[data-rut]');
    if (!b) return;
    const it = Items.get(Number(b.dataset.rut));
    await Items.setDone(it.id, !it.done);
    Calendar.refreshAll();
  });
  // Programar sin arrastrar (táctil o teclado): día y hora del bloque
  $('calUnscheduled').addEventListener('click', async (e) => {
    if (e.target.closest('[data-show-all]')) { showAll = true; paintSide(); return; }
    const b = e.target.closest('[data-plan]');
    if (!b) return;
    const it = Items.get(Number(b.dataset.plan));
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm';
    dlg.innerHTML = `<div class="modal-header"><h2>Programar</h2></div>
      <form class="modal-body stack" id="planForm"><p class="small">${escapeHtml(it.text.split('\n')[0])}</p>
        <div class="cal-ed-grid"><label class="field"><span class="field-label">Día</span><input type="date" name="day" class="input" value="${Calendar.iso(cal.date) < today ? today : Calendar.iso(cal.date)}" required></label>
        <label class="field"><span class="field-label">Hora</span><input type="time" name="time" class="input" step="900" value="10:00"></label>
        <label class="field"><span class="field-label">Duración (min)</span><input type="number" name="dur" class="input" min="15" max="720" step="15" value="60"></label></div>
        <p class="tiny muted">Sin hora queda como tarea de todo el día.</p></form>
      <div class="modal-footer"><button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="planForm" class="btn btn-primary">Programar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    dlg.querySelector('form').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const f = ev.target;
      await Calendar.scheduleItem(it.id, f.day.value, f.time.value, Number(f.dur.value) || 60);
      closeModal(dlg);
    });
    openModal(dlg, { focus: 'input[name=time]', onClose: () => dlg.remove() });
  });
})();
