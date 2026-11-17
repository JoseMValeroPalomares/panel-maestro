/* revision.js — revisión semanal (/api/review/week) y registro de cambios (/api/review/log) */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(s);
  const ACTION = { done: 'Completada', reopen: 'Reabierta', created: 'Creada', check: 'Rutina hecha', uncheck: 'Rutina desmarcada', deleted: 'Borrada' };
  const DOW = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
  let start = new Date();

  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const fmt = (s, o) => new Date(s + 'T00:00').toLocaleDateString('es-ES', o);

  async function load() {
    let w;
    try { w = await api(`/api/review/week?start=${iso(start)}`, { quiet: true }); } catch {
      $('revRange').textContent = '';
      showState($('revStats'), loadFailed('No se pudo cargar la semana', true), load);
      $('revTime').innerHTML = '';
      for (const id of ['revList', 'revRut']) $(id).closest('section').hidden = true;  // vacías junto al error confunden
      return;
    }
    for (const id of ['revList', 'revRut']) $(id).closest('section').hidden = false;
    $('revRange').textContent = `Semana del ${fmt(w.from, { day: 'numeric', month: 'long' })} al ${fmt(w.to, { day: 'numeric', month: 'long' })}`;
    const days = Object.entries(w.por_dia);
    const max = Math.max(1, ...days.map(([, v]) => v.hechas));
    // Una serie (tareas e ideas completadas por día); las rutinas, en número debajo de cada barra
    const n = (k, one, many) => `<b class="tabular">${k}</b> ${k === 1 ? one : many}`;
    $('revStats').innerHTML = `<p>${n(w.hechas.length, 'completada', 'completadas')} · ${n(w.rutinas.length, 'rutina cumplida', 'rutinas cumplidas')} · ${n(w.creadas, 'creada', 'creadas')}</p>
      <div class="rev-bars" role="img" aria-label="Completadas por día: ${days.map(([d, v], i) => `${DOW[i]} ${v.hechas}`).join(', ')}">
        ${days.map(([d, v], i) => `<div class="rev-day" title="${fmt(d, { weekday: 'long', day: 'numeric' })}: ${v.hechas} completadas, ${v.rutinas} rutinas">
          <span class="rev-val tabular">${v.hechas || ''}</span><span class="rev-bar" style="height:${Math.round(v.hechas / max * 100)}%"></span>
          <span class="rev-dow">${DOW[i]}</span><span class="rev-rut tiny tabular">${v.rutinas ? `${v.rutinas} rut.` : ''}</span></div>`).join('')}</div>`;
    const group = (list) => {
      const by = {};
      list.forEach((r) => (by[r.day] ||= []).push(r));
      return Object.keys(by).sort().reverse().map((d) => `<h3 class="hoy-h3">${fmt(d, { weekday: 'long', day: 'numeric' })}</h3><ul class="hoy-list">${by[d].map((r) => `<li class="hoy-row">
        ${icon(r.type === 'idea' ? 'lightbulb' : r.type === 'rutina' ? 'repeat' : 'square-check', 'icon-sm')}
        ${r.exists ? `<a class="hoy-title" href="/tareas?item=${r.item_id}">${esc(r.text)}</a>` : `<span class="hoy-title">${esc(r.text)} <span class="tiny muted">(ya no existe)</span></span>`}
        <span class="tiny muted tabular">${new Date(r.at * 1000).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}</span></li>`).join('')}</ul>`).join('');
    };
    $('revList').innerHTML = w.hechas.length ? group(w.hechas) : '<p class="small muted">Nada completado esta semana.</p>';
    loadTime(w.from, w.to);
    $('revRut').innerHTML = w.rutinas.length ? group(w.rutinas) : '<p class="small muted">Ninguna rutina cumplida esta semana.</p>';
  }

  // Lo cronometrado con el contador (P-2): una barra por día y lo que más tiempo se llevó
  const hm = (sec, largo = false) => { const m = Math.round(sec / 60); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}${largo ? ' min' : ''}` : ''}`; };
  async function loadTime(from, to) {
    let t;
    try { t = await api(`/api/contador/tiempos?desde=${from}&hasta=${to}`, { quiet: true }); } catch { $('revTime').innerHTML = '<p class="small muted">No se pudo cargar el tiempo.</p>'; return; }
    if (!t.total) { $('revTime').innerHTML = '<p class="small muted">Nada cronometrado esta semana. Empieza el contador desde el menú de una tarea o con Ctrl K → «Empezar contador».</p>'; return; }
    const days = Object.entries(t.por_dia);
    const max = Math.max(1, ...days.map(([, v]) => v));
    $('revTime').innerHTML = `<p><b class="tabular">${hm(t.total, true)}</b> en total</p>
      <div class="rev-bars rev-bars-time" role="img" aria-label="Tiempo por día: ${days.map(([, v], i) => `${DOW[i]} ${hm(v)}`).join(', ')}">
        ${days.map(([d, v], i) => `<div class="rev-day" title="${fmt(d, { weekday: 'long', day: 'numeric' })}: ${hm(v)}">
          <span class="rev-val tabular">${v >= 60 ? hm(v) : ''}</span><span class="rev-bar" style="height:${Math.round(v / max * 100)}%"></span>
          <span class="rev-dow">${DOW[i]}</span><span></span></div>`).join('')}</div>
      <h4 class="hoy-h3">Lo que más tiempo se llevó</h4><ul class="hoy-list">${t.elementos.slice(0, 8).map((e) => `<li class="hoy-row">
        ${icon(e.tipo === 'libre' ? 'timer' : e.tipo === 'idea' ? 'lightbulb' : e.tipo === 'tarea' ? 'square-check' : 'repeat', 'icon-sm')}
        ${e.existe ? `<a class="hoy-title" href="/tareas?item=${e.item_id}">${esc(e.titulo)}</a>` : `<span class="hoy-title">${esc(e.titulo)}${e.existe === false ? ' <span class="tiny muted">(ya no existe)</span>' : ''}</span>`}
        <span class="tiny muted tabular">${hm(e.segundos, true)}</span></li>`).join('')}</ul>`;
  }

  let before = null;
  async function loadLog(more = false) {
    let r;
    try { r = await api(`/api/review/log?limit=40${more && before ? `&before=${before}` : ''}`, { quiet: true }); } catch {
      if (more) { toast('No se pudo cargar más', { type: 'error' }); return; }
      $('revMore').hidden = true;
      $('revLog').innerHTML = '<li></li>';
      showState($('revLog').firstElementChild, loadFailed('No se pudo cargar el registro', true), () => loadLog());
      return;
    }
    if (!more) $('revLog').innerHTML = '';
    $('revLog').insertAdjacentHTML('beforeend', r.entries.map((e) => `<li class="hoy-row"><span class="hoy-time tiny tabular">${new Date(e.at * 1000).toLocaleString('es-ES', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
      <span class="tag">${ACTION[e.action] || esc(e.action)}</span><span class="hoy-title">${esc(e.text || '')}</span></li>`).join('') || (more ? '' : '<li class="small muted">Sin cambios todavía.</li>'));
    before = r.entries.length ? r.entries[r.entries.length - 1].at : before;
    $('revMore').hidden = r.entries.length < 40;
  }

  document.querySelectorAll('[data-week]').forEach((b) => b.addEventListener('click', () => {
    const n = Number(b.dataset.week);
    start = n === 0 ? new Date() : new Date(start.getTime() + n * 7 * 86400000);
    load();
  }));
  $('revMore').addEventListener('click', () => loadLog(true));
  load();
  loadLog();
})();
