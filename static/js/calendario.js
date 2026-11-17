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
  // Rejilla del minicalendario (6 semanas desde el lunes de antes del día 1): contiene el día, los 3 días o la semana a
  // la vista, así que se pide antes de montar y el calendario saca su rango de ella sin otra petición (V-2). Sin
  // preferencias en caché aún no se sabe el contexto: entonces no se adelanta nada.
  const miniFirst = (d) => { const m = new Date(d.getFullYear(), d.getMonth(), 1); return Calendar.addDays(m, -((m.getDay() + 6) % 7)); };
  let pre = null;
  if (Prefs.cached && window.Ctx) {
    const first = miniFirst(params.get('dia') ? Calendar.parse(params.get('dia')) : new Date());
    pre = { key: Calendar.iso(first), ctx: Ctx.active(), p: Calendar.fetchEntries(first, Calendar.addDays(first, 41), Ctx.active()) };
    pre.p.catch(() => {});
  }
  const cal = Calendar.mount($('calendar'), {
    view: params.get('vista') || saved || undefined,
    date: params.get('dia') || undefined,
    onChange: (c) => {
      const t = c.title();
      $('calTitle').textContent = t.charAt(0).toUpperCase() + t.slice(1);
      document.querySelectorAll('[data-cal-view]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.calView === c.view)));
      history.replaceState(null, '', `?vista=${c.view}&dia=${Calendar.iso(c.date)}`);
      paintHours(c);
      // datos nuevos (algo se ha podido crear o mover): se refrescan los puntos; ni un repintado sin más ni la primera carga
      // (los puntos se piden al pintar el minicalendario por primera vez) los vuelven a pedir (V-2)
      if ((c.loads || 0) > 1 && c.loads !== dotsFor) { dotsFor = c.loads; miniDots.key = ''; }
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

  /* ---------- Crear escribiendo: «dentista mañana 17:00 30m en Clínica Sur» (P-3) ----------
     Lo entendido se ve debajo; Intro (o Ctrl+Intro) lo crea y deja la línea lista para otro, Alt+Intro o «Más opciones»
     abre el editor ya relleno (lugar, aviso, notas…) sin crear nada antes, y Esc vacía la línea. */
  const PREFIX = /^\s*[tire]\s*:/i;
  const quick = $('calQuickText'), hint = $('calQuickHint');
  const asEvent = (t) => (PREFIX.test(t) ? t : `e: ${t}`);
  let qLast = null;
  const clearHint = () => { hint.innerHTML = ''; hint.hidden = true; hint.classList.remove('is-ok', 'is-warn'); qLast = null; };
  const qPreview = Rapido.preview(async () => {
    const t = quick.value.trim();
    if (!t) return null;
    return api('/api/capture', { method: 'POST', body: { text: asEvent(t), dry_run: true }, quiet: true });
  }, (r) => {
    if (!r || r.error) { if (!quick.value.trim()) clearHint(); return; }
    qLast = r;
    const ok = r.kind !== 'inbox' || !r.revisar;
    const p = r.preview || {};
    hint.innerHTML = (r.kind === 'evento'
      ? Rapido.chips([{ icon: 'calendar', text: p.title }, { icon: 'clock', text: p.when }, p.location && { icon: 'map-pin', text: p.location, kind: 'plain' }, p.donde && { icon: 'layers', text: p.donde, kind: 'plain' }])
      : Rapido.chips([{ icon: ok ? 'check' : 'triangle-alert', text: ok ? r.message : 'Sin fecha clara: irá al Inbox para revisarlo', kind: ok ? 'plain' : 'warn' }]))
      + (r.kind === 'evento' ? '<button type="button" class="link-btn" data-quick-more>Más opciones</button><span class="tiny subtle hide-mobile"> · <kbd>Alt</kbd>+<kbd>Intro</kbd></span>' : '');
    hint.hidden = false;
    hint.classList.toggle('is-ok', ok);
    hint.classList.toggle('is-warn', !ok);
  }, 220);
  quick.addEventListener('input', () => { if (!quick.value.trim()) { qPreview.cancel(); clearHint(); return; } qPreview(); });
  async function quickMore() {
    if (!quick.value.trim()) return;
    qPreview.cancel();
    const r = qLast?.kind === 'evento' ? qLast : await api('/api/capture', { method: 'POST', body: { text: asEvent(quick.value.trim()), dry_run: true }, quiet: true }).catch(() => null);
    const p = r?.kind === 'evento' ? r.preview : null;
    const day = cal.date ? Calendar.iso(cal.date) : Calendar.iso(new Date());
    Calendar.openEditor(p ? { kind: 'event', type: 'evento', isNew: true, title: p.title, start: p.start, end: p.end, all_day: p.all_day, location: p.location || '' }
      : { kind: 'event', type: 'evento', isNew: true, title: quick.value.trim(), start: `${day}T09:00`, end: `${day}T10:00`, all_day: false }, cal);
    quick.value = '';
    clearHint();
  }
  hint.addEventListener('click', (e) => { if (e.target.closest('[data-quick-more]')) quickMore(); });
  quick.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && quick.value) { e.preventDefault(); e.stopPropagation(); quick.value = ''; qPreview.cancel(); clearHint(); }
    else if (e.key === 'Enter' && e.altKey) { e.preventDefault(); quickMore(); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $('calQuick').requestSubmit(); }
  });
  $('calQuick').addEventListener('submit', async (e) => {
    e.preventDefault();
    const t = quick.value.trim();
    if (!t) { quick.focus(); return; }
    qPreview.cancel();
    let r;
    try { r = await api('/api/capture', { method: 'POST', body: { text: asEvent(t) } }); } catch { return; }
    toast(r.message, { type: r.revisar ? 'warning' : 'info' });
    quick.value = '';
    clearHint();
    if (r.kind === 'evento' && r.preview?.start) cal.goTo(r.preview.start.slice(0, 10));
    else Calendar.refreshAll();
    quick.focus();
  });

  /* ---------- Minicalendario: ir a un día; los puntos marcan los días con algo ---------- */
  let mini = null, miniDots = { key: '', days: new Set() }, dotsFor;
  const MONTHS = (d) => d.toLocaleDateString('es-ES', { month: 'long', year: 'numeric' });
  function paintMini(c) {
    const ref = c ? new Date(c.date.getFullYear(), c.date.getMonth(), 1) : mini;
    if (c) mini = ref;
    const first = miniFirst(mini);
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
      const ctx = window.Ctx ? Ctx.active() : 'todo';
      const ahead = pre && pre.key === key && pre.ctx === ctx ? pre.p : null;  // la de arranque, una sola vez
      pre = null;
      const { entries } = await (ahead || Calendar.fetchEntries(first, Calendar.addDays(first, 41), ctx));
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

  /* ---------- Enlace .ics de solo lectura (P-11): suscribirse desde GNOME Calendar, Thunderbird, el móvil… ---------- */
  function openIcsLink() {
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm';
    dlg.innerHTML = `<div class="modal-header"><h2>Enlace para otro calendario</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body stack" id="icsBody" aria-live="polite"><p class="small muted">Cargando…</p></div>
      <div class="modal-footer" id="icsFoot"><span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    const body = dlg.querySelector('#icsBody');
    const foot = dlg.querySelector('#icsFoot');
    const fecha = (t) => t ? new Date(t * 1000).toLocaleString('es-ES', { dateStyle: 'medium', timeStyle: 'short' }) : '';
    const intro = '<p class="small muted">Una dirección de solo lectura con tus eventos (y, si quieres, las tareas con fecha) para suscribirte desde cualquier aplicación de calendario. Quien la tenga puede verlos: no la compartas. Las tareas de notas cifradas o sensibles nunca salen.</p>';
    const buttons = (activo) => {
      foot.innerHTML = `${activo ? `<button type="button" class="btn btn-ghost" data-ics="revocar">${icon('unlink')} Revocar</button>` : ''}<span class="spacer"></span>
        <button type="button" class="btn" data-close>Cerrar</button>
        <button type="button" class="btn ${activo ? '' : 'btn-primary'}" data-ics="crear">${icon(activo ? 'refresh-cw' : 'link')} ${activo ? 'Crear otro' : 'Crear el enlace'}</button>`;
    };
    function showState(st) {
      body.innerHTML = intro + (st.activo
        ? `<p>Hay un enlace activo, creado el ${escapeHtml(fecha(st.creado))}${st.ultimo_uso ? ` · último uso: ${escapeHtml(fecha(st.ultimo_uso))}` : ' · todavía sin usar'}.</p>
           <p class="small muted">Por seguridad no se guarda la dirección: si la has perdido, crea otra (la anterior deja de funcionar).</p>`
        : '<p>No hay ningún enlace activo.</p>');
      buttons(st.activo);
    }
    function showUrl(url) {
      body.innerHTML = `${intro}
        <label class="field"><span class="field-label">Dirección (cópiala ahora: no se vuelve a enseñar)</span>
          <span class="row"><input class="input grow" id="icsUrl" readonly value="${escapeHtml(url)}" spellcheck="false" translate="no" autocomplete="off">
          <button type="button" class="btn btn-primary" data-ics="copiar">${icon('clipboard-copy')} Copiar</button></span></label>
        <label class="row small"><input type="checkbox" class="checkbox" id="icsTareas"> Incluir las tareas con fecha sin hacer</label>`;
      const input = body.querySelector('#icsUrl');
      body.querySelector('#icsTareas').addEventListener('change', (e) => { input.value = url + (e.target.checked ? '?tareas=1' : ''); });
      input.addEventListener('focus', () => input.select());
      buttons(true);
      input.focus();
    }
    dlg.addEventListener('click', async (e) => {
      const b = e.target.closest('[data-ics]');
      if (!b) return;
      try {
        if (b.dataset.ics === 'copiar') {
          const ok = await copyText(body.querySelector('#icsUrl').value);
          toast(ok ? 'Dirección copiada' : 'No se pudo copiar: selecciónala y cópiala a mano', { type: ok ? 'success' : 'info' });
        } else if (b.dataset.ics === 'crear') {
          if (foot.querySelector('[data-ics=revocar]') && !await uiConfirm('¿Crear otro enlace?', 'El actual dejará de funcionar: tendrás que cambiarlo en las aplicaciones que ya lo usan.', { confirmLabel: 'Crear otro' })) return;
          showUrl((await api('/api/calendar/ics-enlace', { method: 'POST' })).url);
        } else if (b.dataset.ics === 'revocar') {
          if (!await uiConfirm('¿Revocar el enlace?', 'La dirección dejará de funcionar en todas las aplicaciones suscritas.', { confirmLabel: 'Revocar', danger: true })) return;
          await api('/api/calendar/ics-enlace', { method: 'DELETE' });
          toast('Enlace revocado', { type: 'success' });
          showState({ activo: false });
        }
      } catch (err) { toast(err.message || 'No se pudo', { type: 'error' }); }
    });
    openModal(dlg, { onClose: () => dlg.remove() });
    api('/api/calendar/ics-enlace').then(showState).catch((err) => { body.innerHTML = `<p>${escapeHtml(err.message || 'No se pudo cargar')}</p>`; });
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
    { label: 'Enlace para otro calendario…', icon: 'link', onClick: openIcsLink },
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
  // La galería común (plantillas.js): las de serie y las tuyas, con miniatura; aplica al día que se está viendo
  function applyDayTemplate() { Plantillas.open({ tab: 'dia', day: dayShown() }); }
  async function syncNow() {
    await api('/api/calendar/sync', { method: 'POST' });
    toast('Sincronizando con iCloud y el ESP32…', { type: 'info' });
    setTimeout(() => Calendar.refreshAll(), 6000);
  }

  /* ---------- Barra lateral ---------- */
  const today = Calendar.iso(new Date());
  function paintSide() {
    if (!Items.state.loaded) return;
    const all = Items.state.items.filter((i) => !window.Ctx || Ctx.match(i));  // el contexto activo, como la rejilla
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
    if (e.target.closest('[data-rt-templates]')) { Plantillas.open({ tab: 'rutina' }); return; }
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
  // Otro contexto: los puntos del mes y el lateral cambian con la rejilla
  document.addEventListener('contexto:changed', () => { miniDots.key = ''; paintMini(); paintSide(); });
})();
