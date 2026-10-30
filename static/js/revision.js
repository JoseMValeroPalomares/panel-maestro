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
    const w = await api(`/api/review/week?start=${iso(start)}`, { quiet: true });
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
    $('revRut').innerHTML = w.rutinas.length ? group(w.rutinas) : '<p class="small muted">Ninguna rutina cumplida esta semana.</p>';
  }

  let before = null;
  async function loadLog(more = false) {
    const r = await api(`/api/review/log?limit=40${more && before ? `&before=${before}` : ''}`, { quiet: true });
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
