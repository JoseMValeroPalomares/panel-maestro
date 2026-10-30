/* hoy.js — pantalla de inicio «Hoy» (/api/today): agenda, rutinas, tareas de hoy y atrasadas,
   comida del día con sus macros y repaso de flashcards. Se marca desde aquí mismo. */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  let data = null;

  function check(e) {
    return `<button type="button" class="card-check small-check${e.done ? ' done' : ''}${e.kind === 'routine' ? ' is-routine' : ''}" data-check="${esc(e.key || 't' + e.id)}"
      role="checkbox" aria-checked="${!!e.done}" aria-label="${e.done ? 'Desmarcar' : 'Marcar'}: ${esc(e.title)}">${icon('check', 'icon-sm')}</button>`;
  }
  const empty = (t) => `<p class="small muted hoy-empty">${esc(t)}</p>`;

  function render() {
    const d = new Date(data.date + 'T00:00');
    const fecha = d.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
    $('hoyTitle').textContent = fecha.charAt(0).toUpperCase() + fecha.slice(1);
    const pend = data.rutinas.filter((r) => !r.done).length + data.tareas.filter((t) => !t.done).length;
    $('hoySub').textContent = pend ? `${pend} cosa${pend === 1 ? '' : 's'} por hacer hoy · ${data.hechas_hoy} hecha${data.hechas_hoy === 1 ? '' : 's'}` : (data.hechas_hoy ? `Todo hecho por hoy (${data.hechas_hoy})` : 'Día despejado');

    const agenda = [...data.eventos, ...data.tareas.filter((t) => !t.all_day)].sort((a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start));
    const now = data.now;
    $('hoyAgenda').innerHTML = agenda.length ? `<ul class="hoy-list">${agenda.map((e) => {
      const past = !e.all_day && (e.end || e.start) < now;
      const curr = !e.all_day && e.start <= now && now < (e.end || e.start);
      return `<li class="hoy-row${past ? ' is-past' : ''}${curr ? ' is-now' : ''}" data-type="${esc(e.type)}">
        <span class="hoy-time tabular">${e.all_day ? 'Todo el día' : `${e.start.slice(11, 16)}–${(e.end || '').slice(11, 16)}`}</span>
        ${e.kind === 'task' ? check(e) : `<span class="hoy-dot" aria-hidden="true"></span>`}
        <a class="hoy-title" href="${e.kind === 'event' ? `/calendario?dia=${data.date}` : `/tareas?item=${e.item_id}`}">${esc(e.title)}</a>
        ${curr ? '<span class="tag">Ahora</span>' : ''}</li>`;
    }).join('')}</ul>` : empty('Sin eventos ni bloques hoy.');

    $('hoyRutinasCount').textContent = data.rutinas.length ? `${data.rutinas.filter((r) => r.done).length}/${data.rutinas.length}` : '';
    $('hoyRutinas').innerHTML = data.rutinas.length ? `<ul class="hoy-list">${data.rutinas.map((r) => {
      const it = window.Items?.get(r.item_id);
      const steps = r.steps || [];
      return `<li class="hoy-row${r.done ? ' is-done' : ''}">${check(r)}<span class="hoy-title">${esc(r.title)}${steps.length ? ` <span class="tiny muted tabular">${steps.filter((x) => x.done).length}/${steps.length}</span>` : ''}</span>
        ${r.all_day ? '' : `<span class="tiny muted tabular">${r.start.slice(11, 16)}</span>`}
        ${it?.streak?.actual ? `<span class="hoy-streak tabular" title="Racha">${icon('flame', 'icon-sm')}${it.streak.actual}</span>` : ''}
        ${steps.length && !r.done ? `<button type="button" class="btn btn-ghost btn-icon btn-sm" data-run="${r.item_id}" aria-label="Empezar «${esc(r.title)}» paso a paso" title="Empezar paso a paso">${icon('play', 'icon-sm')}</button>` : ''}</li>`;
    }).join('')}</ul>` : `<p class="hoy-empty small muted">Ninguna rutina toca hoy. <button type="button" class="link-btn" data-rt-templates>Crear una desde una plantilla</button></p>`;

    const tareas = data.tareas.filter((t) => t.all_day);
    $('hoyTareas').innerHTML = (tareas.length || data.atrasadas.length) ? `
      ${tareas.length ? `<ul class="hoy-list">${tareas.map((t) => `<li class="hoy-row${t.done ? ' is-done' : ''}">${check(t)}<a class="hoy-title" href="/tareas?item=${t.item_id}">${esc(t.title)}</a></li>`).join('')}</ul>` : ''}
      ${data.atrasadas.length ? `<h3 class="hoy-h3">Atrasadas</h3><ul class="hoy-list">${data.atrasadas.map((t) => `<li class="hoy-row">${check({ key: 't' + t.id, id: t.id, title: t.title, done: false })}
        <a class="hoy-title" href="/tareas?item=${t.id}">${esc(t.title)}</a><span class="tiny hoy-late tabular">${new Date(t.due_date + 'T00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}</span></li>`).join('')}</ul>` : ''}`
      : empty('Nada con fecha de hoy.');

    const c = data.comida;
    if (!c) $('hoyComida').innerHTML = empty('No se pudo leer el plan de comidas.');
    else if (!c.comidas.length) $('hoyComida').innerHTML = `${empty('Aún no hay nada planificado para hoy.')}<a class="btn btn-sm" href="/comidas/">${icon('plus', 'icon-sm')}Planificar</a>`;
    else {
      const pct = (k) => Math.min(100, Math.round((c.total[k] || 0) / (c.objetivo[k] || 1) * 100));
      $('hoyComida').innerHTML = `<ul class="hoy-meals">${c.comidas.map((m) => `<li><span class="hoy-meal-name">${esc(m.nombre)}</span>
          <span class="hoy-meal-platos">${m.platos.map((p) => esc(p.nombre)).join(' · ')}</span><span class="tiny muted tabular">${Math.round(m.kcal)} kcal</span></li>`).join('')}</ul>
        <div class="hoy-macros">${[['kcal', 'Energía', 'kcal'], ['proteinas', 'Proteína', 'g'], ['carbohidratos', 'Hidratos', 'g'], ['grasas', 'Grasa', 'g']].map(([k, l, u]) =>
          `<div class="hoy-macro${k !== 'proteinas' && (c.total[k] || 0) > (c.objetivo[k] || Infinity) * 1.1 ? ' is-over' : ''}"><span class="tiny muted">${l}</span><span class="tabular"><b>${Math.round(c.total[k] || 0)}</b> / ${Math.round(c.objetivo[k] || 0)} ${u}</span>
            <span class="hoy-bar" role="progressbar" aria-label="${l}" aria-valuenow="${pct(k)}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct(k)}%"></span></span></div>`).join('')}</div>`;
    }

    // Lo siguiente del día: el próximo evento, bloque o paso de rutina que aún no ha empezado
    const next = [
      ...agenda.filter((e) => !e.all_day && !e.done).map((e) => ({ at: e.start.slice(11, 16), title: e.title, href: e.kind === 'event' ? `/calendario?dia=${data.date}` : `/tareas?item=${e.item_id}` })),
      ...data.rutinas.flatMap((r) => (r.steps?.length ? r.steps.filter((x) => !x.done && x.at).map((x) => ({ at: x.at, title: x.title, sub: r.title, href: `/rutinas?dia=${data.date}` }))
        : (!r.done && !r.all_day ? [{ at: r.start.slice(11, 16), title: r.title, href: `/rutinas?dia=${data.date}` }] : []))),
    ].filter((x) => x.at > now.slice(11, 16)).sort((a, b) => a.at.localeCompare(b.at))[0];
    const nx = $('hoyNext');
    nx.hidden = !next;
    if (next) {
      const mins = (Number(next.at.slice(0, 2)) * 60 + Number(next.at.slice(3))) - (Number(now.slice(11, 13)) * 60 + Number(now.slice(14, 16)));
      const falta = mins < 60 ? `en ${mins} min` : `en ${Math.floor(mins / 60)} h${mins % 60 ? ` ${mins % 60} min` : ''}`;
      nx.href = next.href;
      nx.innerHTML = `${icon('clock', 'icon-sm')}<span>A continuación: <b>${esc(next.title)}</b>${next.sub ? ` <span class="muted">· ${esc(next.sub)}</span>` : ''}</span>
        <span class="tabular muted">${next.at} · ${falta}</span>`;
    }

    // Dinero (si se usa Economía): lo gastado hoy y en el mes
    const m = data.dinero, eur = (n) => n.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' });
    $('hoyDineroCard').hidden = !m;
    if (m) {
      $('hoyDinero').innerHTML = `<div class="hoy-money"><div><span class="tiny muted">Hoy</span><b class="tabular">${eur(m.hoy)}</b></div>
          <div><span class="tiny muted">Este mes</span><b class="tabular">${eur(m.mes)}</b></div></div>
        ${m.ultimos.length ? `<ul class="hoy-list">${m.ultimos.map((u) => `<li class="hoy-row"><span class="hoy-title">${esc(u.concepto)}</span><span class="tabular">${eur(u.importe)}</span></li>`).join('')}</ul>` : ''}
        <p class="tiny muted hoy-money-hint">Apunta un gasto escribiendo arriba «g: 4,50 café».</p>`;
    }

    const f = data.flashcards;
    $('hoyRepaso').innerHTML = f.pendientes ? `<p><b class="tabular">${f.pendientes}</b> tarjeta${f.pendientes === 1 ? '' : 's'} de ${f.notas} nota${f.notas === 1 ? '' : 's'} para repasar hoy.</p>
      <a class="btn btn-tinted btn-sm" href="/?flashcards=1">${icon('book-open', 'icon-sm')}Repasar ahora</a>` : empty('Ninguna flashcard pendiente hoy.');
  }

  async function load() {
    try { data = await api('/api/today', { quiet: true }); } catch {
      $('hoyAgenda').innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudo cargar el día', compact: true });
      return;
    }
    render();
  }

  document.querySelector('.hoy').addEventListener('click', async (e) => {
    if (e.target.closest('[data-rt-templates]')) { Routines.openTemplates(); return; }
    const run = e.target.closest('[data-run]');
    if (run) { await Items.ready(); Routines.run(Number(run.dataset.run)); return; }
    const b = e.target.closest('[data-check]');
    if (!b) return;
    const key = b.dataset.check;
    const all = [...data.rutinas, ...data.tareas];
    const entry = all.find((x) => x.key === key);
    const done = b.getAttribute('aria-checked') !== 'true';
    b.classList.toggle('done', done);
    b.setAttribute('aria-checked', String(done));
    try {
      if (entry?.kind === 'routine') await api(`/api/routines/${entry.item_id}/check`, { method: 'POST', body: { day: data.date, done } });
      else await api(`/api/items/${entry ? entry.item_id : Number(key.slice(1))}`, { method: 'PATCH', body: { done } });
      if (done) toast(entry?.kind === 'routine' ? 'Hecha · suma a la racha' : 'Hecha', { type: 'info', duration: 1500 });
    } catch {}
    await Items.load().catch(() => {});
    load();
  });
  onDataChange(/^\/api\/(items|calendar|routines|notes)|^\/comidas\/api/, load);
  Items.ready().then(render).catch(() => {});
  load();
})();
