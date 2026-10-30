/* ==========================================================================
   rutinas.js — página /rutinas: cada rutina como la línea de su día (bloques en orden)
   Datos: GET /api/routines/day?date= (app/calendar.py). Un bloque es un paso de la rutina con su
   duración, su inicio y su fin (se cambian en la propia línea; ninguna hora depende de otra, así que puede
   haber huecos libres, y el servidor rechaza lo que se solapa) y, si hace falta, sus propios días
   («Universidad, de lunes a viernes»). Arrastrar un bloque a otro sitio le da la hora de ese sitio
   (POST /api/routines/{id}/place). Las tareas e ideas se asocian a un bloque (PATCH /api/items/{id} {routine_step}).
   Escrituras con /api/items (las mismas reglas que Tareas e Inbox).
   ========================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(String(s ?? ''));
  const DOW = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
  const DOW_LONG = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return new Date(y, m - 1, d); };
  const hhmm = (t) => `${pad(Math.floor(t / 60) % 24)}:${pad(t % 60)}`;
  const fmtMin = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ''}` : `${m} min`);
  const toMin = (t) => (t ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)) : null);
  const endMin = (s) => (s.end ? toMin(s.end) : toMin(s.at));
  const MIN_GAP = 15;  // un hueco más corto no se anuncia

  const params = new URLSearchParams(location.search);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  // la semana que se ve: de lunes a domingo de la semana del día elegido
  let day = params.get('dia') ? parse(params.get('dia')) : today;
  let data = null;

  /* ---------- Selector de día ---------- */
  function paintDays() {
    const monday = new Date(day); monday.setDate(day.getDate() - ((day.getDay() + 6) % 7));
    $('rtDays').innerHTML = DOW.map((l, i) => {
      const d = new Date(monday); d.setDate(monday.getDate() + i);
      const k = iso(d);
      return `<button type="button" data-day="${k}" aria-pressed="${k === iso(day)}" title="${DOW_LONG[i]} ${d.getDate()}"
        class="${k === iso(today) ? 'is-today' : ''}"><span aria-hidden="true">${l}</span><span class="sr-only">${DOW_LONG[i]} ${d.getDate()}</span></button>`;
    }).join('');
  }
  $('rtDays').addEventListener('click', (e) => {
    const b = e.target.closest('[data-day]');
    if (!b) return;
    day = parse(b.dataset.day);
    history.replaceState(null, '', iso(day) === iso(today) ? location.pathname : `?dia=${iso(day)}`);
    load();
  });

  /* ---------- Carga y pintado ---------- */
  async function load() {
    paintDays();
    try { data = await api(`/api/routines/day?date=${iso(day)}`, { quiet: true }); } catch {
      $('rtPage').innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudieron cargar las rutinas', compact: true });
      return;
    }
    render();
  }

  function render() {
    const isToday = data.date === data.today;
    const past = data.date < data.today;
    const nowMin = toMin(data.now);
    const steps = data.rutinas.flatMap((r) => r.steps);
    const done = steps.filter((s) => s.done).length;
    const d = parse(data.date);
    const label = isToday ? 'Hoy' : `${DOW_LONG[data.weekday].charAt(0).toUpperCase()}${DOW_LONG[data.weekday].slice(1)}`;
    $('rtSub').textContent = data.rutinas.length
      ? `${label}, ${d.getDate()} de ${d.toLocaleDateString('es-ES', { month: 'long' })} · ${done} de ${steps.length} bloques hechos`
      : `${label}, ${d.getDate()} de ${d.toLocaleDateString('es-ES', { month: 'long' })}`;

    if (!data.rutinas.length && !data.otras.length) {
      $('rtPage').innerHTML = `<section class="panel rp-empty">${emptyState({ iconName: 'repeat', title: 'Organiza tu día en bloques',
        text: 'Una rutina es lo que haces siempre: levantarte, desayunar, la universidad… Pon cada bloque a la hora que quieras, deja huecos libres entre ellos y haz que toque solo algunos días.', compact: true })}
        <div class="rp-empty-actions"><button type="button" class="btn btn-primary" data-act="templates">${icon('layout-template', 'icon-sm')}Empezar con «Mi día»</button>
        <button type="button" class="btn" data-act="new">${icon('plus', 'icon-sm')}Crear una vacía</button></div></section>`;
      return;
    }

    const card = (r) => {
      const first = r.steps.find((s) => s.at), last = [...r.steps].reverse().find((s) => s.at);
      const range = first ? `${first.at}${last && (last.end || last.at) !== first.at ? `–${last.end || last.at}` : ''}` : (r.due_time || '');
      const hecho = r.steps.filter((s) => s.done).length;
      const current = isToday ? r.steps.findIndex((s) => !s.done && s.at && toMin(s.at) <= nowMin && nowMin < (s.end ? toMin(s.end) : toMin(s.at) + 1)) : -1;
      const next = isToday ? r.steps.findIndex((s) => !s.done) : -1;
      const line = r.steps.flatMap((s, i) => [gapHTML(r, r.steps[i - 1], s), step(r, s, i === current, i === next && current < 0, past || isToday)]).join('');
      return `<section class="panel rp-card${r.done ? ' is-done' : ''}" data-rid="${r.id}" aria-labelledby="rp-h-${r.id}">
        <header class="rp-head">
          <div class="rp-head-main">
            <h2 id="rp-h-${r.id}" class="rp-title">${esc(r.title)}</h2>
            <p class="rp-meta tiny muted">${range ? `<span class="tabular">${range}</span> · ` : ''}${esc(r.repeat_text)}${r.steps.length ? ` · ${hecho} de ${r.steps.length}` : ''}${r.streak?.actual ? ` · <span class="rp-streak">${icon('flame', 'icon-sm')}${r.streak.actual}</span>` : ''}</p>
          </div>
          ${isToday && r.steps.length && !r.done ? `<button type="button" class="btn btn-tinted btn-sm" data-act="run">${icon('play', 'icon-sm')}Empezar</button>` : ''}
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="routine-menu" aria-label="Acciones de «${esc(r.title)}»" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
        </header>
        ${r.steps.length ? `<ol class="rp-line">${line}</ol>`
          : '<p class="small muted rp-none">Este día no tiene bloques. Añade el primero aquí abajo.</p>'}
        ${r.tasks.length ? `<div class="rp-loose"><span class="tiny muted">Asociadas a la rutina</span>${tasksHTML(r.tasks)}</div>` : ''}
        <form class="rp-add" data-add="${r.id}">
          <label class="sr-only" for="rp-add-${r.id}">Nuevo bloque de «${esc(r.title)}»</label>
          <input id="rp-add-${r.id}" class="input input-sm" maxlength="300" placeholder="Nuevo bloque (p. ej. «Gimnasio 1h»)" autocomplete="off">
          <label class="sr-only" for="rp-add-at-${r.id}">Hora del bloque nuevo</label>
          <input id="rp-add-at-${r.id}" class="input input-sm rp-add-at tabular" type="text" inputmode="numeric" maxlength="5" autocomplete="off" name="at" placeholder="Inicio">
          <label class="sr-only" for="rp-add-end-${r.id}">Hora de fin del bloque nuevo</label>
          <input id="rp-add-end-${r.id}" class="input input-sm rp-add-at tabular" type="text" inputmode="numeric" maxlength="5" autocomplete="off" name="end" placeholder="Fin">
          <button type="submit" class="btn btn-ghost btn-sm">${icon('plus', 'icon-sm')}Añadir</button>
        </form>
        ${r.otros_dias.length ? `<p class="rp-other tiny muted">Otros días: ${r.otros_dias.map((s) => `<button type="button" class="link-btn" data-step="${s.id}" data-act="edit-step">${esc(s.title)}</button> (${esc((s.days_text || '').toLowerCase())})`).join(' · ')}</p>` : ''}
      </section>`;
    };
    const active = document.activeElement?.closest?.('.rp-time-input');
    const focused = active && `[data-step="${active.closest('[data-step]').dataset.step}"] [data-time="${active.dataset.time}"]`;
    const otras = data.otras.length ? `<p class="small muted rp-others">No tocan este día: ${data.otras.map((o) => `<b>${esc(o.title)}</b> (${esc(o.repeat_text.toLowerCase())})`).join(' · ')}</p>` : '';
    $('rtPage').innerHTML = data.rutinas.map(card).join('') + otras;
    if (focused) $('rtPage').querySelector(focused)?.focus();  // poner varias horas seguidas con Tab
    // Arrastrar (o Alt + flechas): el bloque toma la hora del sitio donde cae
    $('rtPage').querySelectorAll('.rp-line').forEach((ol) => {
      const rid = Number(ol.closest('[data-rid]').dataset.rid);
      Sortable.create(ol, {
        group: `rp-${rid}`, items: '.rp-step', handle: '[data-drag-handle]', label: `los bloques de «${data.rutinas.find((x) => x.id === rid)?.title || ''}»`,
        id: (el) => el.dataset.step, data: { rid },
        onDrop: (ctx) => place(stepOf(Number(ctx.id)), ctx.beforeId ? Number(ctx.beforeId) : null),
      });
    });
  }

  // El hueco entre dos bloques seguidos; no se anuncia si lo ocupa un bloque de otra rutina
  function gapHTML(r, prev, s) {
    if (!prev?.at || !s.at) return '';
    const from = endMin(prev), to = toMin(s.at);
    if (to - from < MIN_GAP) return '';
    const taken = data.rutinas.some((o) => o.id !== r.id && o.steps.some((x) => x.at && toMin(x.at) < to && endMin(x) > from));
    return taken ? '' : `<li class="rp-gap"><span class="rp-rail" aria-hidden="true"></span><span class="tiny muted">Libre ${fmtMin(to - from)}</span></li>`;
  }

  function step(r, s, isNow, isNext, canCheck) {
    return `<li class="rp-step${s.done ? ' is-done' : ''}${s.skipped ? ' is-skipped' : ''}${isNow ? ' is-now' : ''}${isNext ? ' is-next' : ''}" data-step="${s.id}">
      <span class="rp-time">${timeInput(s, 'start')}${s.at ? timeInput(s, 'end') : ''}</span>
      <span class="rp-rail" aria-hidden="true"><span class="rp-dot">${s.skipped ? icon('skip-forward', 'icon-sm') : s.done ? icon('check', 'icon-sm') : ''}</span></span>
      <div class="rp-body">
        <div class="rp-row">
          <button type="button" class="rp-grip" data-drag-handle aria-label="Mover «${esc(s.title)}» (Alt + flechas)" title="Arrastra para colocarlo: toma la hora de ese sitio">${icon('grip-vertical', 'icon-sm')}</button>
          ${canCheck ? `<button type="button" class="card-check small-check is-routine${s.done ? ' done' : ''}" data-act="check" role="checkbox" aria-checked="${s.done}" aria-label="${s.done ? 'Desmarcar' : 'Hecho'}: ${esc(s.title)}">${icon('check', 'icon-sm')}</button>` : ''}
          <button type="button" class="rp-step-title" data-act="edit-step" title="Editar el bloque">${esc(s.title)}</button>
          ${s.clash ? `<span class="tag rp-clash" title="Se solapa con «${esc(s.clash)}»">Se solapa</span>` : ''}
          ${s.skipped ? '<span class="tag">Saltado</span>' : isNow ? '<span class="tag rp-now">Ahora</span>' : isNext ? '<span class="tag">Siguiente</span>' : ''}
          <span class="grow"></span>
          <span class="tiny muted tabular rp-dur">${s.duration_min ? fmtMin(s.duration_min) : ''}${s.days_text ? ` · ${esc(s.days_text.toLowerCase())}` : ''}</span>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="step-menu" aria-label="Acciones del bloque «${esc(s.title)}»" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
        </div>
        ${s.tasks.length ? tasksHTML(s.tasks) : ''}
      </div></li>`;
  }

  const timeInput = (s, field) => {
    const start = field === 'start';
    return `<input type="text" name="${start ? 'hora' : 'fin'}" inputmode="numeric" maxlength="5" autocomplete="off" class="rp-time-input tabular" data-time="${field}"
      value="${esc((start ? s.at : s.end) || '')}" placeholder="${start ? 'Hora' : 'Fin'}" aria-label="${start ? 'Hora' : 'Hora de fin'} de «${esc(s.title)}»"
      title="${start ? (s.at ? 'Cambiar la hora' : 'Sin hora: ponle una') : '¿A qué hora acaba?'}">`;
  };

  function tasksHTML(list) {
    return `<ul class="rp-tasks">${list.map((t) => `<li class="rp-task${t.done ? ' is-done' : ''}" data-task="${t.id}">
      <button type="button" class="card-check small-check${t.done ? ' done' : ''}" data-act="task-done" role="checkbox" aria-checked="${t.done}" aria-label="${t.done ? 'Volver a pendiente' : 'Marcar como hecha'}: ${esc(t.text)}">${icon('check', 'icon-sm')}</button>
      <a class="rp-task-text" href="/tareas?item=${t.id}">${t.type === 'idea' ? icon('lightbulb', 'icon-sm') : ''}${esc(t.text)}</a>
      ${t.due_date ? `<span class="tiny muted tabular">${parse(t.due_date).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}</span>` : ''}
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="unlink" aria-label="Quitar «${esc(t.text)}» de este bloque" title="Quitar del bloque">${icon('x', 'icon-sm')}</button></li>`).join('')}</ul>`;
  }

  /* ---------- Acciones ---------- */
  const routineOf = (el) => data.rutinas.find((r) => r.id === Number(el.closest('[data-rid]')?.dataset.rid));
  const stepOf = (id) => data.rutinas.flatMap((r) => [...r.steps, ...r.otros_dias].map((s) => ({ ...s, rid: r.id }))).find((s) => s.id === id);
  const patch = (id, body) => api(`/api/items/${id}`, { method: 'PATCH', body });

  $('rtPage').addEventListener('click', async (e) => {
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const act = el.dataset.act;
    const r = routineOf(el);
    const sid = Number(el.closest('[data-step]')?.dataset.step);
    const tid = Number(el.closest('[data-task]')?.dataset.task);
    if (act === 'templates') { Routines.openTemplates(); return; }
    if (act === 'new') { newRoutine(); return; }
    if (act === 'run') { await Items.ready(); Routines.run(r.id); return; }
    if (act === 'routine-menu') { routineMenu(r, el); return; }
    if (act === 'check') {
      const s = stepOf(sid);
      el.classList.toggle('done', !s.done);
      try {
        if (s.skipped) await api(`/api/routines/${sid}/skip`, { method: 'POST', body: { day: data.date, skip: false } });
        else await patch(sid, { done: !s.done, day: data.date });
      } catch {}
      load();
      return;
    }
    if (act === 'edit-step') { editStep(stepOf(sid)); return; }
    if (act === 'step-menu') { stepMenu(stepOf(sid), el); return; }
    if (act === 'task-done') {
      const t = [...(r?.tasks || []), ...(r?.steps || []).flatMap((s) => s.tasks)].find((x) => x.id === tid);
      try { await patch(tid, { done: !t.done }); } catch {}
      load();
      return;
    }
    if (act === 'unlink') { try { await patch(tid, { routine_step: 0 }); } catch {} load(); }
  });

  // Minutos de un inicio a un fin; un fin anterior al inicio es del día siguiente
  const minutesTo = (start, end) => (toMin(end) - toMin(start) + 1440) % 1440;

  // Se guarda al salir del campo o con Intro. Inicio vacío: sin hora; fin vacío: sin duración. Cambiar el inicio conserva
  // la duración (el fin se mueve con él); cambiar el fin cambia la duración
  async function setTime(input) {
    const s = stepOf(Number(input.closest('[data-step]')?.dataset.step));
    if (!s) return;
    const start = input.dataset.time === 'start';
    const had = (start ? s.due_time : s.end) || '', at = parseTime(input.value);
    if (at === null) toast('Escribe la hora como 17:30', { type: 'info' });
    input.value = at ?? had;
    if (at === null || at === had) return;
    if (!start && at === s.due_time) { toast('El fin tiene que ser después del inicio', { type: 'info' }); input.value = had; return; }
    try { await patch(s.id, start ? { due_time: at } : { duration_min: at ? minutesTo(s.due_time, at) : 0 }); } catch { input.value = had; return; }
    load();
  }
  $('rtPage').addEventListener('focusout', (e) => { if (e.target.matches('.rp-time-input')) setTime(e.target); });
  $('rtPage').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.matches('.rp-time-input')) { e.preventDefault(); e.target.blur(); }
  });

  $('rtPage').addEventListener('submit', async (e) => {
    const f = e.target.closest('[data-add]');
    if (!f) return;
    e.preventDefault();
    const input = f.querySelector('input');
    const text = input.value.trim();
    if (!text) return;
    const at = parseTime(f.at.value), end = parseTime(f.end.value);
    if (at === null || end === null) { toast('Escribe la hora como 17:30', { type: 'info' }); (at === null ? f.at : f.end).focus(); return; }
    if (end && !at) { toast('Pon también a qué hora empieza', { type: 'info' }); f.at.focus(); return; }
    if (end && end === at) { toast('El fin tiene que ser después del inicio', { type: 'info' }); f.end.focus(); return; }
    input.disabled = true;
    const times = { ...(at ? { due_time: at } : {}), ...(end ? { duration_min: minutesTo(at, end) } : {}) };
    try { await api('/api/items', { method: 'POST', body: { text, parent_id: Number(f.dataset.add), ...times } }); } catch { input.disabled = false; return; }
    await load();
    document.getElementById(`rp-add-${f.dataset.add}`)?.focus();
  });

  function routineMenu(r, anchor) {
    openMenu(anchor, [
      { label: 'Editar la rutina…', icon: 'pencil', onClick: () => editRoutine(r) },
      { label: 'Añadir un bloque', icon: 'plus', onClick: () => document.getElementById(`rp-add-${r.id}`)?.focus() },
      { label: 'Guardar como plantilla…', icon: 'layout-template', onClick: async () => { await Items.ready(); Routines.saveTemplate(r.id); } },
      { label: 'Ver en Tareas', icon: 'list-todo', onClick: () => { location.href = `/tareas?item=${r.id}`; } },
      { separator: true },
      { label: 'Eliminar la rutina', icon: 'trash-2', danger: true, onClick: () => removeItem(r.id, `«${r.title}» y sus bloques`) },
    ]);
  }

  function stepMenu(s, anchor) {
    const r = data.rutinas.find((x) => x.id === s.rid);
    openMenu(anchor, [
      { label: 'Asociar una tarea…', icon: 'link', onClick: () => attachTask(s) },
      { label: 'Nueva tarea en este bloque…', icon: 'square-check', onClick: () => newTaskIn(s) },
      { label: 'Editar el bloque…', icon: 'pencil', onClick: () => editStep(s) },
      { label: 'Duplicar el bloque', icon: 'copy', onClick: () => duplicateStep(r, s) },
      s.on !== false && { label: s.skipped ? 'No saltarlo' : `Saltar ${data.date === data.today ? 'hoy' : 'este día'}`, icon: 'skip-forward', onClick: () => skipStep(s) },
      s.due_time && { label: 'Quitar la hora', icon: 'clock', onClick: () => clearTime(s) },
      { separator: true },
      s.on !== false && { label: 'Subir', icon: 'chevron-up', onClick: () => moveStep(r, s, -1) },
      s.on !== false && { label: 'Bajar', icon: 'chevron-down', onClick: () => moveStep(r, s, 1) },
      s.on !== false && { separator: true },
      { label: 'Eliminar el bloque', icon: 'trash-2', danger: true, onClick: () => removeItem(s.id, `«${s.title}»`) },
    ].filter(Boolean));
  }

  // Saltar un bloque ese día: cuenta como resuelto para la rutina, pero no como hecho
  async function skipStep(s) {
    try { await api(`/api/routines/${s.id}/skip`, { method: 'POST', body: { day: data.date, skip: !s.skipped } }); } catch { return; }
    toast(s.skipped ? `«${s.title}» ya no está saltado` : `«${s.title}» saltado ${data.date === data.today ? 'hoy' : 'ese día'}`);
    load();
  }

  async function clearTime(s) {
    try { await patch(s.id, { due_time: '' }); } catch { return; }
    load();
  }

  // Duplicar: la copia va justo debajo, con la misma duración y días pero sin hora (a la misma, chocaría)
  async function duplicateStep(r, s) {
    try {
      const { id } = await api('/api/items', { method: 'POST', body: { text: s.title, parent_id: r.id } });
      await patch(id, { duration_min: s.duration_min || 0, step_days: s.days || [] });
      const order = await stepOrder(r.id);
      const after = order[order.indexOf(s.id) + 1];
      await api(`/api/items/${id}/move`, { method: 'POST', body: { target: 'rutinas', parent_id: r.id, before_id: after && after !== id ? after : null } });
    } catch { return; }
    toast(`«${s.title}» duplicado`);
    load();
  }

  async function removeItem(id, what) {
    if (!(await uiConfirm(`¿Eliminar ${what}?`, 'Irá a la papelera durante 30 días.', { confirmLabel: 'Eliminar', danger: true }))) return;
    try { await api(`/api/items/${id}`, { method: 'DELETE' }); } catch { return; }
    toast('En la papelera');
    load();
  }

  function moveStep(r, s, delta) {
    const i = r.steps.findIndex((x) => x.id === s.id), j = i + delta;
    if (i < 0 || j < 0 || j >= r.steps.length) return;
    return place(s, delta < 0 ? r.steps[j].id : r.steps[j + 1]?.id ?? null);
  }

  // Colocar un bloque en la línea: toma la hora de ese sitio. Si no cabe, se pregunta antes de mover los siguientes
  async function place(s, before) {
    const url = `/api/routines/${s.id}/place`, body = { before_id: before, day: data.date };
    try {
      let res = await api(url, { method: 'POST', body });
      if (res.status === 'no_cabe') {
        const [first, ...rest] = res.mover;
        const who = rest.length ? `«${first}» y ${rest.length === 1 ? 'el siguiente' : `los ${rest.length} siguientes`}` : `«${first}»`;
        if (await uiConfirm(`«${s.title}» no cabe ahí`, `Para hacerle sitio, ${who} empezaría${rest.length ? 'n' : ''} ${fmtMin(res.minutos)} más tarde.`, { confirmLabel: 'Mover' })) {
          res = await api(url, { method: 'POST', body: { ...body, push: true } });
        }
      }
      if (res.status === 'success' && res.at && res.at !== s.at) toast(`«${s.title}» a las ${res.at}`);
    } catch {}
    load();
  }
  async function stepOrder(rid) {
    await Items.load();
    return Items.children(rid).map((k) => k.id);
  }

  /* ---------- Diálogos ---------- */
  function dialog(title, body, footer) {
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm';
    dlg.innerHTML = `<div class="modal-header"><h2>${title}</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body stack form-pro" id="rtDlgForm">${body}</form><div class="modal-footer">${footer}</div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    // Ctrl+Intro guarda desde cualquier campo
    dlg.querySelector('form').addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.currentTarget.requestSubmit(); } });
    return dlg;
  }
  const row = (iconName, html) => `<div class="form-row"><span class="form-row-ico" aria-hidden="true">${icon(iconName, 'icon-sm')}</span><div class="form-row-body stack-sm">${html}</div></div>`;
  const DURS = [[5, '5 min'], [10, '10 min'], [15, '15 min'], [30, '30 min'], [60, '1 h'], [90, '1 h 30'], [120, '2 h']];

  function editStep(s) {
    const dlg = dialog('Bloque', `
      <label class="sr-only" for="rpStepTitle">Nombre</label>
      <input id="rpStepTitle" name="title" class="input form-title" maxlength="300" required placeholder="Nombre del bloque" value="${esc(s.title)}">
      ${row('clock', `<div class="form-line"><label class="tiny muted" for="rpStepAt">Empieza</label><input id="rpStepAt" name="at" type="time" class="input input-sm" value="${esc(s.due_time || '')}">
          <label class="tiny muted" for="rpStepEnd">Acaba</label><input id="rpStepEnd" name="end" type="time" class="input input-sm" value="${esc(s.end || '')}">
          <button type="button" class="link-btn tiny" data-clear-at>Sin hora</button></div>
        <p class="tiny muted">Sin hora, el bloque no ocupa sitio en el día y lo haces cuando te venga bien.</p>`)}
      ${row('timer', `<div class="form-line"><label class="sr-only" for="rpStepDur">Duración en minutos</label>
          <input id="rpStepDur" name="dur" type="number" class="input input-sm tabular" style="width:6em" min="0" max="1440" step="5" value="${s.duration_min || ''}" placeholder="—"><span class="tiny muted">min</span></div>
        <div class="chips" role="group" aria-label="Duración">${DURS.map(([m, l]) => `<button type="button" class="chip chip-sm" data-dur="${m}" aria-pressed="${s.duration_min === m}">${l}</button>`).join('')}</div>`)}
      ${row('calendar', `${dayPicker({ days: s.days, legend: 'Días en que toca' })}<p class="tiny muted">Con todos marcados, los mismos días que la rutina.</p>`)}`,
      `<span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="rtDlgForm" class="btn btn-primary">Guardar</button>`);
    const f = dlg.querySelector('form');
    dlg.querySelector('[data-clear-at]').addEventListener('click', () => { f.at.value = ''; f.end.value = ''; f.at.focus(); });
    // Inicio, fin y duración van juntos: el fin sale de los otros dos, y escribir el fin da la duración
    const syncChips = () => dlg.querySelectorAll('[data-dur]').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.dur === f.dur.value)));
    const syncEnd = () => { f.end.value = f.at.value && Number(f.dur.value) ? hhmm(toMin(f.at.value) + Number(f.dur.value)) : ''; };
    dlg.querySelectorAll('[data-dur]').forEach((b) => b.addEventListener('click', () => { f.dur.value = b.dataset.dur; syncChips(); syncEnd(); }));
    f.dur.addEventListener('input', () => { syncChips(); syncEnd(); });
    f.at.addEventListener('change', syncEnd);
    f.end.addEventListener('change', () => {
      if (!f.at.value || !f.end.value) return;
      f.dur.value = minutesTo(f.at.value, f.end.value) || '';
      syncChips();
    });
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const days = readDays(dlg);
      if (!days.length) { toast('Elige al menos un día', { type: 'info' }); return; }
      try {
        await patch(s.id, { text: f.title.value.trim(), duration_min: Number(f.dur.value) || 0, due_time: f.at.value, step_days: days.length === 7 ? [] : days });
      } catch { return; }
      closeModal(dlg);
      load();
    });
    openModal(dlg, { focus: 'input[name=title]', onClose: () => dlg.remove() });
  }

  function editRoutine(r) {
    const dlg = dialog('Rutina', `
      <label class="sr-only" for="rpRtTitle">Nombre</label>
      <input id="rpRtTitle" name="title" class="input form-title" maxlength="300" required placeholder="Nombre de la rutina" value="${esc(r.title)}">
      ${row('clock', `<div class="form-line"><label class="tiny muted" for="rpRtAt">Hora de la rutina</label><input id="rpRtAt" name="at" type="time" class="input input-sm" value="${esc(r.due_time || '')}"></div>
        <p class="tiny muted">Para el calendario y los avisos si sus bloques no tienen hora. No mueve los que sí la tienen.</p>`)}
      ${row('repeat', dayPicker({ rule: r.repeat, legend: 'Se repite', note: everyNote(r.repeat, r.repeat_text) }))}`,
      `<span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="rtDlgForm" class="btn btn-primary">Guardar</button>`);
    const f = dlg.querySelector('form');
    f.addEventListener('submit', async (e) => {
      e.preventDefault();
      const repeat = repeatFromDays(dlg, r.repeat);
      if (!repeat) { toast('Elige al menos un día', { type: 'info' }); return; }
      const body = { text: f.title.value.trim(), due_time: f.at.value, repeat };
      try { await patch(r.id, body); } catch { return; }
      closeModal(dlg);
      load();
    });
    openModal(dlg, { focus: 'input[name=title]', onClose: () => dlg.remove() });
  }

  async function newRoutine() {
    const name = await uiPrompt('Nueva rutina', { label: 'Nombre', placeholder: 'Mi día', confirmLabel: 'Crear',
      message: 'Después añade sus bloques en orden. Para empezar con un día completo de ejemplo, usa «Plantillas».' });
    if (!name?.trim()) return;
    try { await api('/api/items', { method: 'POST', body: { text: name.trim(), type: 'rutina', due_time: '07:30' } }); } catch { return; }
    load();
  }

  async function attachTask(s) {
    await Items.ready();
    const picked = await uiPick({
      title: `Asociar a «${s.title}»`, placeholder: 'Busca una tarea o idea',
      load: () => Items.state.items.filter((i) => i.type !== 'rutina' && !i.done && i.routine_step !== s.id)
        .map((i) => ({ id: i.id, label: i.text.split('\n')[0], sub: i.routine_label ? `Ahora en ${i.routine_label}` : (i.parent_id ? 'Paso' : ''), icon: i.type === 'idea' ? 'lightbulb' : 'square-check' })),
    });
    if (!picked) return;
    try { await patch(picked.id, { routine_step: s.id }); } catch { return; }
    load();
  }
  async function newTaskIn(s) {
    const text = await uiPrompt(`Nueva tarea en «${s.title}»`, { label: 'Tarea', placeholder: 'Estudiar el tema 3', confirmLabel: 'Crear' });
    if (!text?.trim()) return;
    try {
      const { id } = await api('/api/items', { method: 'POST', body: { text: text.trim() } });
      await patch(id, { routine_step: s.id });
    } catch { return; }
    load();
  }

  $('rtTemplates').addEventListener('click', () => Routines.openTemplates());
  $('rtNew').addEventListener('click', newRoutine);
  // lo que cambie en otra pestaña o en un diálogo (plantillas, paso a paso…) se ve aquí
  onDataChange(/^\/api\/(items|routines|routine-templates)/, () => load());
  load();
})();
