/* ==========================================================================
   rendimiento.js — página /rendimiento: registro del día (en un diálogo), Hoy (cuatro semáforos y alertas),
   Semana / mes (gráficos SVG de una serie), Exámenes (del calendario) y Correlaciones.
   Datos y reglas en app/rendimiento.py y app/rendimiento_rules.py (/api/rendimiento).
   ========================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(String(s ?? ''));
  const iso = (d) => d.toLocaleDateString('sv-SE');
  const today = () => iso(new Date());
  const addDays = (f, n) => { const [y, m, d] = f.split('-').map(Number); return iso(new Date(y, m - 1, d + n)); };
  const asDate = (f) => { const [y, m, d] = f.split('-').map(Number); return new Date(y, m - 1, d); };
  const longDay = (f) => asDate(f).toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const num = (v, d = 1) => (v == null ? '—' : Number(v).toLocaleString('es-ES', { maximumFractionDigits: d }));
  const NB = '\u00a0';
  const dur = (m) => { m = Math.round(m || 0); const h = Math.floor(m / 60), r = m % 60; return h ? (r ? `${h}${NB}h ${r}${NB}min` : `${h}${NB}h`) : `${r}${NB}min`; };
  const hhmm = (m) => { m = ((Math.round(m) % 1440) + 1440) % 1440; return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`; };

  const params = new URLSearchParams(location.search);
  let fecha = params.get('fecha') || today();
  let tab = ['hoy', 'semana', 'examenes', 'correlaciones', 'auditoria'].includes(params.get('vista')) ? params.get('vista') : 'hoy';
  let rango = params.get('rango') === '30' ? 30 : 7;
  let P = null; // panel del día

  const NIVEL = {
    verde: { label: 'Bien', icon: 'circle-check' },
    ambar: { label: 'Atención', icon: 'triangle-alert' },
    rojo: { label: 'Alerta', icon: 'octagon-alert' },
    gris: { label: 'Sin datos', icon: 'circle-dashed' },
  };
  // [clave, nombre, icono, qué mide en palabras llanas]
  const TARJETAS = [
    ['metabolico', 'Balance metabólico', 'zap', 'Energía, niebla mental, café, comida y siesta'],
    ['codificacion', 'Calidad de codificación', 'brain', 'Cuánto estudias recordando y cuánto solo releyendo'],
    ['sueno', 'Sueño y termorregulación', 'moon', 'Hora de dormir, pantallas, entreno tardío y descanso'],
    ['rotacion', 'Eficiencia de rotación', 'timer', 'Bloques de estudio demasiado largos sin pausas'],
  ];

  /* ---------- Navegación ---------- */
  function syncUrl() {
    const q = new URLSearchParams();
    if (fecha !== today()) q.set('fecha', fecha);
    if (tab !== 'hoy') q.set('vista', tab);
    if (tab === 'semana' && rango === 30) q.set('rango', '30');
    history.replaceState(null, '', q.toString() ? `?${q}` : location.pathname);
  }
  function setTab(t, focus = false) {
    tab = t;
    document.querySelectorAll('[role=tab][data-tab]').forEach((b) => {
      const on = b.dataset.tab === t;
      b.setAttribute('aria-selected', String(on));
      b.tabIndex = on ? 0 : -1;
      if (on && focus) b.focus();
      $(`rdPanel-${b.dataset.tab}`).hidden = !on;
    });
    syncUrl();
    loadTab();
  }
  function loadTab() {
    if (tab === 'hoy') loadToday();
    else if (tab === 'semana') loadWeek();
    else if (tab === 'examenes') loadExams();
    else if (tab === 'auditoria') loadAudit();
    else loadCorr();
  }
  function setDay(f) {
    fecha = f > today() ? today() : f;
    $('rdDayLabel').textContent = fecha === today() ? 'Hoy' : fecha === addDays(today(), -1) ? 'Ayer'
      : asDate(fecha).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' }).replace('.', '');
    $('rdNext').disabled = fecha >= today();
    syncUrl();
    loadTab();
  }

  /* ---------- Hoy ---------- */
  async function loadToday() {
    try { P = await api(`/api/rendimiento/panel?fecha=${fecha}`, { quiet: true }); } catch {
      showState($('rdToday'), loadFailed('No se pudo cargar', true), loadToday);
      return;
    }
    $('rdLogLabel').textContent = P.registrado ? 'Editar el día' : 'Registrar';
    $('rdLog').setAttribute('aria-label', P.registrado ? 'Editar el registro del día' : 'Registrar el día');
    const s = P.resumen;
    $('rdSub').textContent = `${cap(longDay(fecha))} · ` + (P.registrado
      ? [P.horas_sueno != null ? `${dur(P.horas_sueno * 60)} de sueño` : null, s.n ? `${dur(s.minutos)} de enfoque en ${s.n} bloque${s.n > 1 ? 's' : ''}` : 'sin bloques de estudio']
        .filter(Boolean).join(' · ')
      : 'sin registrar');
    const sinRegistro = !P.registrado ? `<div class="rd-callout">
        <span class="rd-callout-ico" aria-hidden="true">${icon('pencil', 'icon-sm')}</span>
        <div class="grow"><p class="rd-callout-title">${fecha === today() ? 'Aún no has registrado hoy' : 'Este día no tiene registro'}</p>
        <p class="small muted">Dos minutos: lo que se repite viene ya relleno de tu último registro y de las rutinas que marcaste.</p></div>
        <button type="button" class="btn btn-primary btn-sm" data-log>${icon('pencil', 'icon-sm')}Registrar</button></div>` : '';
    const ayer = P.registrado || P.ayer_registrado || fecha !== today() ? '' : `<p class="small muted rd-yesterday">¿Te faltó ayer? <button type="button" class="link-btn" data-log-day="${addDays(fecha, -1)}">Registrar ayer</button></p>`;
    $('rdToday').innerHTML = `${sinRegistro}${ayer}
      <div class="rd-lights">${TARJETAS.map(([k, t, ic, que]) => light(k, t, ic, P.semaforos[k], que)).join('')}</div>
      ${alertsHTML(P.alertas)}`;
  }
  function light(key, title, ic, s, que = '') {
    const n = NIVEL[s.nivel];
    const extra = s.motivos.slice(s.nivel === 'verde' ? 0 : 1);
    return `<article class="panel rd-light" data-nivel="${s.nivel}" aria-labelledby="rdL-${key}">
      <div class="rd-light-head"><span class="rd-light-ico" aria-hidden="true">${icon(ic, 'icon-sm')}</span>
        <h2 id="rdL-${key}">${title}</h2>
        <span class="rd-status" data-nivel="${s.nivel}">${icon(n.icon, 'icon-sm')}${n.label}</span></div>
      ${que ? `<p class="rd-light-what tiny muted">${esc(que)}</p>` : ''}
      <p class="rd-light-text">${esc(s.frase)}</p>
      ${extra.length ? `<ul class="rd-reasons">${extra.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}
    </article>`;
  }
  function alertsHTML(list) {
    if (!list.length) {
      return P.registrado ? `<p class="small muted rd-noalerts">${icon('shield-check', 'icon-sm')}Ninguna regla salta hoy.</p>` : '';
    }
    return `<section class="panel hoy-card rd-alerts" aria-labelledby="rdAlertsH">
      <div class="panel-header"><h2 id="rdAlertsH">${icon('triangle-alert', 'icon-sm')}Alertas</h2><span class="grow"></span><span class="tiny muted tabular">${list.length}</span></div>
      <ul class="panel-body rd-alert-list">${list.map((a) => `<li class="rd-alert" data-nivel="${a.nivel}">
        <span class="rd-status" data-nivel="${a.nivel}">${icon(NIVEL[a.nivel].icon, 'icon-sm')}<span class="sr-only">${NIVEL[a.nivel].label}</span></span>
        <div><p class="rd-alert-title">${esc(a.titulo)}</p><p class="small rd-alert-text">${esc(a.texto)}</p>
        ${a.item_id ? `<a class="tiny rd-alert-task" href="/tareas?item=${a.item_id}">${icon('square-check', 'icon-sm')}Ver la tarea</a>` : ''}</div></li>`).join('')}</ul></section>`;
  }

  /* ---------- Gráficos (SVG al ancho real; una serie por gráfico) ---------- */
  const charts = new Map();
  const ro = new ResizeObserver((entries) => entries.forEach((e) => { const c = charts.get(e.target); if (c) drawChart(e.target, c); }));
  function mountChart(el, cfg) { charts.set(el, cfg); ro.observe(el); drawChart(el, cfg); }

  function drawChart(el, cfg) {
    if (cfg.custom) return cfg.custom(); // los de dispersión guardan su propia función de pintado
    const W = Math.max(240, el.clientWidth), H = cfg.height || 150, L = cfg.left || 34, R = 8, T = 10, B = 22;
    const pts = cfg.data;
    const n = pts.length, step = (W - L - R) / n;
    const vals = pts.map(cfg.value);
    const refs = cfg.refs || [];
    let lo = cfg.min, hi = cfg.max;
    const known = vals.filter((v) => v != null).concat(refs.map((r) => r.v));
    if (lo == null) lo = Math.min(...known);
    if (hi == null) hi = Math.max(...known);
    if (cfg.pad) { lo = Math.floor((lo - cfg.pad) / cfg.pad) * cfg.pad; hi = Math.ceil((hi + cfg.pad) / cfg.pad) * cfg.pad; }
    if (hi === lo) hi = lo + 1;
    const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
    const cx = (i) => L + step * i + step / 2;
    const ticks = cfg.ticks ? cfg.ticks(lo, hi) : [lo, (lo + hi) / 2, hi];
    const fmt = cfg.fmt || ((v) => num(v));
    const every = n > 10 ? Math.ceil(n / 6) : 1;
    let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" aria-hidden="true" class="rd-svg">`;
    svg += ticks.map((t) => `<line class="rd-grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text class="rd-axis" x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${esc((cfg.tickFmt || fmt)(t))}</text>`).join('');
    svg += pts.map((p, i) => i % every === 0
      ? `<text class="rd-axis" x="${cx(i)}" y="${H - 6}" text-anchor="middle">${esc(xLabel(p.fecha, n))}</text>` : '').join('');
    if (cfg.kind === 'bar') {
      const bw = Math.min(28, step * 0.62), base = y(Math.max(lo, 0));
      vals.forEach((v, i) => {
        if (v == null) return;
        const top = y(v), h = Math.max(2, base - top), x = cx(i) - bw / 2, r = Math.min(4, bw / 2, h);
        svg += `<path class="rd-bar${cfg.flag && cfg.flag(pts[i]) ? ' is-flag' : ''}" d="M${x},${base} V${base - h + r} Q${x},${base - h} ${x + r},${base - h} H${x + bw - r} Q${x + bw},${base - h} ${x + bw},${base - h + r} V${base} Z"/>`;
      });
    } else {
      let d = '', pen = false;
      vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += `${pen ? 'L' : 'M'}${cx(i)},${y(v)} `; pen = true; });
      svg += `<path class="rd-line" d="${d}"/>`;
      vals.forEach((v, i) => { if (v != null) svg += `<circle class="rd-dot${cfg.flag && cfg.flag(pts[i]) ? ' is-flag' : ''}" cx="${cx(i)}" cy="${y(v)}" r="4"/>`; });
    }
    // Referencias encima de las marcas, para que su etiqueta nunca quede tapada
    refs.forEach((r) => {
      svg += `<line class="rd-ref${r.strong ? ' is-strong' : ''}" x1="${L}" x2="${W - R}" y1="${y(r.v)}" y2="${y(r.v)}"/>`;
      if (r.label) svg += `<text class="rd-ref-label" x="${W - R}" y="${y(r.v) - 4}" text-anchor="end">${esc(r.label)}</text>`;
    });
    svg += `<line class="rd-cross" id="${el.id}-x" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/>`;
    svg += '</svg>';
    // Zonas de interacción: una columna por día, más grandes que la marca, enfocables con el teclado
    const hits = pts.map((p, i) => {
      const v = vals[i];
      const tip = `${cap(longDay(p.fecha))}: ${v == null ? (p.registrado ? 'sin dato' : 'sin registro') : fmt(v)}${cfg.tipExtra ? cfg.tipExtra(p) : ''}`;
      return `<button type="button" class="rd-hit" style="left:${L + step * i}px;width:${step}px" data-x="${cx(i)}" data-tip="${esc(tip)}" aria-label="${esc(tip)}"></button>`;
    }).join('');
    el.innerHTML = svg + `<div class="rd-hits" style="height:${H - B}px">${hits}</div>`;
  }
  function xLabel(f, n) {
    const d = asDate(f);
    return n <= 10 ? d.toLocaleDateString('es-ES', { weekday: 'narrow' }) + ' ' + d.getDate() : String(d.getDate());
  }
  // Tooltip y cruz comunes a todos los gráficos
  function showTip(btn) {
    const tip = $('rdTip'), chart = btn.closest('.rd-chart');
    tip.textContent = btn.dataset.tip;
    tip.hidden = false;
    const r = btn.getBoundingClientRect(), tw = tip.offsetWidth;
    tip.style.left = `${Math.min(window.innerWidth - tw - 8, Math.max(8, r.left + r.width / 2 - tw / 2))}px`;
    tip.style.top = `${Math.max(8, r.top - tip.offsetHeight - 6)}px`;
    const x = chart && $(`${chart.id}-x`);
    if (x) { x.setAttribute('x1', btn.dataset.x); x.setAttribute('x2', btn.dataset.x); x.setAttribute('visibility', 'visible'); }
  }
  function hideTip() {
    $('rdTip').hidden = true;
    document.querySelectorAll('.rd-cross').forEach((x) => x.setAttribute('visibility', 'hidden'));
  }
  document.addEventListener('pointerover', (e) => { const b = e.target.closest('.rd-hit'); if (b) showTip(b); });
  document.addEventListener('pointerout', (e) => { if (e.target.closest('.rd-hit')) hideTip(); });
  document.addEventListener('focusin', (e) => { const b = e.target.closest('.rd-hit'); if (b) showTip(b); else hideTip(); });
  window.addEventListener('scroll', hideTip, true);

  function chartCard(id, title, subtitle, rows) {
    return `<section class="panel hoy-card rd-chart-card" aria-labelledby="${id}H">
      <div class="panel-header"><h2 id="${id}H">${title}</h2></div>
      <div class="panel-body"><p class="small muted rd-chart-sub">${subtitle}</p>
        <div class="rd-chart" id="${id}" role="group" aria-label="${esc(title)}"></div>
        ${rows ? `<details class="rd-table"><summary>${icon('table', 'icon-sm')}Ver como tabla</summary>${rows}</details>` : ''}</div></section>`;
  }
  const table = (head, rows) => `<div class="table-wrap"><table class="rd-tbl"><thead><tr>${head.map((h) => `<th scope="col">${h}</th>`).join('')}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i ? `<td class="tabular">${c}</td>` : `<th scope="row">${c}</th>`)).join('')}</tr>`).join('')}</tbody></table></div>`;

  /* ---------- Semana / mes ---------- */
  // Esqueleto solo en la primera carga de cada pestaña (al recargar se queda lo anterior hasta que llega lo nuevo)
  const skeleton = (el, n = 2) => { if (!el.childElementCount) el.innerHTML = '<span class="skeleton skeleton-card"></span>'.repeat(n); };

  async function loadWeek() {
    skeleton($('rdWeek'));
    let S;
    try { S = await api(`/api/rendimiento/serie?dias=${rango}&hasta=${fecha}`, { quiet: true }); } catch {
      showState($('rdWeek'), loadFailed('No se pudo cargar', true), loadWeek);
      return;
    }
    $('rdRangeLabel').textContent = `${asDate(S.desde).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })} – ${asDate(S.hasta).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}`;
    const t = S.totales, o = S.objetivos;
    if (!t.registrados) {
      $('rdWeek').innerHTML = emptyState({ iconName: 'chart-line', title: 'Sin registros en este periodo', text: 'Registra unos días y aquí verás tu sueño, tu enfoque y tu estado.', compact: true });
      return;
    }
    const D = S.dias;
    const dLabel = (p) => cap(asDate(p.fecha).toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' }));
    const kpi = (label, value, hint = '') => `<div class="rd-kpi"><dt>${label}</dt><dd class="tabular">${value}</dd>${hint ? `<span class="tiny muted">${hint}</span>` : ''}</div>`;
    $('rdWeek').innerHTML = `
      <dl class="rd-kpis">
        ${kpi('Días registrados', `${t.registrados}/${D.length}`)}
        ${kpi('Sueño medio', t.media_sueno != null ? `${num(t.media_sueno)}${NB}h` : '—', `objetivo ${num(o.sueno_h)}${NB}h`)}
        ${kpi('Enfoque medio', t.media_minutos != null ? dur(t.media_minutos) : '—', `${dur(t.minutos)} en total`)}
        ${kpi('Con Anki previo', t.pct_recall != null ? `${num(t.pct_recall, 0)}${NB}%` : '—', 'de los bloques')}
        ${kpi('Codificación activa', t.pct_activa != null ? `${num(t.pct_activa, 0)}${NB}%` : '—', 'de los minutos')}
        ${kpi('Blindaje de dopamina', t.blindaje != null ? `${t.blindaje}${NB}%` : '—', 'días sin ocio antes de las 19:00')}
      </dl>
      <div class="rd-charts">
        ${chartCard('rdcBed', 'Hora de acostarte', `Objetivo ${esc(o.acostarse)}; por encima de la línea fuerte salta la alerta circadiana.`,
          table(['Día', 'Acostarte'], D.filter((p) => p.registrado).map((p) => [dLabel(p), p.acostarse || '—'])))}
        ${chartCard('rdcSleep', 'Horas de sueño', `La noche anterior a cada día. Objetivo ${num(o.sueno_h)} h.`,
          table(['Día', 'Horas'], D.filter((p) => p.registrado).map((p) => [dLabel(p), p.horas_sueno != null ? num(p.horas_sueno) : '—'])))}
        ${chartCard('rdcFocus', 'Minutos de enfoque', `Efectivos por día. Más de ${dur(o.max_enfoque_min)} varios días seguidos es sobrecarga.`,
          table(['Día', 'Minutos', 'Bloques'], D.filter((p) => p.registrado).map((p) => [dLabel(p), p.minutos, p.bloques])))}
        ${chartCard('rdcRecall', 'Bloques con Anki previo', 'Porcentaje de bloques que empezaron con Active Recall.',
          table(['Día', '% con Anki', '% activa'], D.filter((p) => p.bloques).map((p) => [dLabel(p), `${p.pct_recall} %`, `${p.pct_activa} %`])))}
        ${chartCard('rdcActive', 'Codificación activa', 'Minutos en código, esquema o problemas (no lectura pasiva).', '')}
        <section class="panel hoy-card rd-chart-card" aria-labelledby="rdDopH">
          <div class="panel-header"><h2 id="rdDopH">Blindaje de dopamina</h2></div>
          <div class="panel-body"><p class="small muted rd-chart-sub">Ocio digital antes de las 19:00, día a día.</p>
            <ul class="rd-strip" style="--n:${Math.min(D.length, 15)}">${D.map((p) => {
              const st = !p.registrado ? 'none' : p.dopamina ? 'fail' : 'ok';
              const txt = `${dLabel(p)}: ${st === 'none' ? 'sin registro' : st === 'fail' ? 'ocio antes de las 19:00' : 'blindaje cumplido'}`;
              return `<li class="rd-cell" data-st="${st}" title="${esc(txt)}"><span class="sr-only">${esc(txt)}</span>${st === 'ok' ? icon('check', 'icon-sm') : st === 'fail' ? icon('x', 'icon-sm') : ''}</li>`;
            }).join('')}</ul>
            <ul class="tiny muted rd-legend"><li><span class="rd-cell" data-st="ok">${icon('check', 'icon-sm')}</span>Cumplido</li>
              <li><span class="rd-cell" data-st="fail">${icon('x', 'icon-sm')}</span>Ocio antes de las 19:00</li><li><span class="rd-cell" data-st="none"></span>Sin registro</li></ul>
          </div></section>
      </div>
      <section class="panel hoy-card" aria-labelledby="rdWAlertsH" id="rdWAlerts" hidden></section>
      <h2 class="rd-h2">Cómo te has sentido</h2>
      <div class="rd-charts rd-small">
        ${chartCard('rdcEnergy', 'Energía', `Media ${num(t.energia)} / 5`, '')}
        ${chartCard('rdcFog', 'Niebla mental', `Media ${num(t.niebla)} / 5 · más alto es peor`, '')}
        ${chartCard('rdcMood', 'Humor', `Media ${num(t.humor)} / 5`, table(['Día', 'Energía', 'Niebla', 'Humor'],
          D.filter((p) => p.registrado).map((p) => [dLabel(p), p.energia ?? '—', p.niebla ?? '—', p.humor ?? '—'])))}
      </div>`;
    loadWeekAlerts();
    const limite = o.limite_acostarse_min;
    mountChart($('rdcBed'), { data: D, kind: 'line', value: (p) => p.acostarse_min ?? null, fmt: hhmm, pad: 30, left: 44,
      refs: [{ v: o.acostarse_min, label: 'objetivo' }, { v: limite, label: 'límite', strong: true }],
      ticks: (lo, hi) => { const out = []; for (let v = lo; v <= hi; v += (hi - lo > 180 ? 60 : 30)) out.push(v); return out; },
      flag: (p) => p.acostarse_min > limite });
    mountChart($('rdcSleep'), { data: D, kind: 'bar', value: (p) => p.horas_sueno ?? null, min: 0, max: Math.max(10, ...D.map((p) => p.horas_sueno || 0)),
      fmt: (v) => `${num(v)} h`, refs: [{ v: o.sueno_h, label: 'objetivo' }], ticks: (lo, hi) => [0, 4, 8, hi > 10 ? 12 : 10].filter((v) => v <= hi),
      flag: (p) => p.horas_sueno != null && p.horas_sueno < o.sueno_h - 1 });
    mountChart($('rdcFocus'), { data: D, kind: 'bar', value: (p) => (p.registrado ? p.minutos : null), min: 0,
      max: Math.max(o.max_enfoque_min + 60, ...D.map((p) => p.minutos || 0)), fmt: (v) => dur(v), tickFmt: (v) => `${Math.round(v / 60)} h`,
      refs: [{ v: o.max_enfoque_min, label: 'sobrecarga' }], ticks: (lo, hi) => { const out = []; for (let v = 0; v <= hi; v += 120) out.push(v); return out; },
      tipExtra: (p) => (p.bloques ? ` · ${p.bloques} bloque${p.bloques > 1 ? 's' : ''}` : ''), flag: (p) => p.minutos > o.max_enfoque_min });
    const pct = { kind: 'bar', min: 0, max: 100, fmt: (v) => `${Math.round(v)} %`, ticks: () => [0, 50, 100] };
    mountChart($('rdcRecall'), { ...pct, data: D, value: (p) => (p.bloques ? p.pct_recall : null) });
    mountChart($('rdcActive'), { ...pct, data: D, value: (p) => (p.bloques ? p.pct_activa : null), refs: [{ v: 50 }] });
    const scale = { kind: 'line', min: 1, max: 5, ticks: () => [1, 3, 5], fmt: (v) => `${v} / 5`, height: 120, left: 26 };
    mountChart($('rdcEnergy'), { ...scale, data: D, value: (p) => p.energia ?? null });
    mountChart($('rdcFog'), { ...scale, data: D, value: (p) => p.niebla ?? null, flag: (p) => p.niebla >= 4 });
    mountChart($('rdcMood'), { ...scale, data: D, value: (p) => p.humor ?? null });
  }

  async function loadWeekAlerts() {
    let L;
    try { L = (await api(`/api/rendimiento/alertas?dias=${rango}&hasta=${fecha}`, { quiet: true })).alertas; } catch { return; }
    const box = $('rdWAlerts');
    if (!box) return;
    box.hidden = !L.length;
    if (!L.length) return;
    box.innerHTML = `<div class="panel-header"><h2 id="rdWAlertsH">${icon('history', 'icon-sm')}Alertas del periodo</h2><span class="grow"></span><span class="tiny muted tabular">${L.length}</span></div>
      <ul class="panel-body rd-alert-list">${L.map((a) => `<li class="rd-alert" data-nivel="${a.nivel}">
        <span class="rd-status" data-nivel="${a.nivel}">${icon(NIVEL[a.nivel].icon, 'icon-sm')}<span class="sr-only">${NIVEL[a.nivel].label}</span></span>
        <div><p class="rd-alert-title">${esc(a.titulo)} <span class="tiny muted tabular">· ${esc(cap(asDate(a.fecha).toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' })))}</span></p>
        ${a.item_id ? `<a class="tiny rd-alert-task" href="/tareas?item=${a.item_id}">${icon(a.tarea_hecha ? 'circle-check' : 'square-check', 'icon-sm')}${a.tarea_hecha ? 'Tarea hecha' : 'Ver la tarea'}</a>` : ''}</div></li>`).join('')}</ul>`;
  }

  /* ---------- Auditoría con IA ---------- */
  const CAPA = { metabolico: ['Balance metabólico', 'zap'], codificacion: ['Calidad de codificación', 'brain'], sueno: ['Sueño y termorregulación', 'moon'], rotacion: ['Eficiencia de rotación', 'timer'] };
  let IA = null, auditando = '';

  async function loadAudit() {
    skeleton($('rdAudit'));
    let H;
    try { [IA, H] = await Promise.all([api('/api/rendimiento/ia/estado', { quiet: true }), api('/api/rendimiento/ia/historial', { quiet: true })]); } catch {
      showState($('rdAudit'), loadFailed('No se pudo cargar', true), loadAudit);
      return;
    }
    const sinClaves = !IA.configurados;
    const dia = fecha === today() ? 'hoy' : 'este día';
    $('rdAudit').innerHTML = `
      <div class="rd-privacy">${icon('shield-check', 'icon-sm')}<p class="small">${esc(IA.aviso)}</p></div>
      ${sinClaves ? `<div class="rd-callout rd-callout-warn"><span class="rd-callout-ico" aria-hidden="true">${icon('plug-zap', 'icon-sm')}</span>
        <div class="grow"><p class="rd-callout-title">La IA no está configurada</p>
        <p class="small muted">Añade al menos una clave a <code>.env</code> (<code>OPENROUTER_API_KEY</code>, <code>GROQ_API_KEY</code>, <code>GEMINI_API_KEY</code> o <code>GITHUB_MODELS_TOKEN</code>) y reinicia el panel. Todo lo demás funciona sin ella.</p></div></div>` : ''}
      <div class="rd-audit-actions">
        <button type="button" class="btn btn-primary" data-audit="dia" ${sinClaves || auditando ? 'disabled' : ''}>${icon('sparkles', 'icon-sm')}${auditando === 'dia' ? 'Auditando…' : `Auditar ${dia}`}</button>
        <button type="button" class="btn btn-tinted" data-audit="semana" ${sinClaves || auditando ? 'disabled' : ''}>${icon('calendar-range', 'icon-sm')}${auditando === 'semana' ? 'Auditando…' : 'Auditar la semana'}</button>
        <label class="rd-switch"><input type="checkbox" class="switch" id="rdIncluirNota" ${IA.incluir_nota ? 'checked' : ''}><span class="small">Incluir mi nota libre</span></label>
      </div>
      <p class="tiny muted rd-audit-hint" aria-live="polite" id="rdAuditMsg">${auditando ? 'Puede tardar hasta un minuto si el primer modelo está saturado y hay que pasar al siguiente.' : `${IA.configurados} de ${IA.modelos.length} modelos con clave · se prueban en orden y, si uno falla, pasa al siguiente.`}</p>
      <details class="rd-prompt"><summary>${icon('pencil', 'icon-sm')}Instrucciones para la IA${IA.prompt_propio ? ' <span class="tag">Personalizadas</span>' : ''}</summary>
        <textarea class="textarea" id="rdPrompt" rows="7" maxlength="6000" autocomplete="off" aria-label="Instrucciones del sistema para la auditoría">${esc(IA.prompt)}</textarea>
        <div class="rd-prompt-actions"><button type="button" class="btn btn-ghost btn-sm" data-prompt-reset ${IA.prompt_propio ? '' : 'disabled'}>${icon('rotate-ccw', 'icon-sm')}Volver a las de serie</button>
          <button type="button" class="btn btn-sm" data-prompt-save>${icon('save', 'icon-sm')}Guardar instrucciones</button></div>
        <p class="tiny muted">El formato de la respuesta (JSON con las cuatro capas) se añade siempre al final: no hace falta escribirlo.</p></details>
      <h2 class="rd-h2">Historial</h2>
      ${H.auditorias.length ? `<ol class="rd-timeline">${H.auditorias.map(auditHTML).join('')}</ol>`
        : emptyState({ iconName: 'sparkles', title: 'Aún no hay auditorías', text: 'La primera aparecerá aquí, con el diagnóstico y la corrección de cada capa.', compact: true })}`;
  }

  function auditHTML(a) {
    const r = a.resultado;
    const cuando = new Date(a.creado * 1000).toLocaleString('es-ES', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
    const titulo = a.tipo === 'dia' ? cap(longDay(a.periodo))
      : `Semana ${a.periodo.split('-W')[1]} · hasta el ${asDate(a.fecha).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}`;
    return `<li class="panel rd-audit">
      <div class="rd-audit-head"><h3>${esc(titulo)}</h3><span class="grow"></span><span class="tiny muted">${esc(cuando)} · ${esc(a.proveedor || '')} <code>${esc(a.modelo || '')}</code></span></div>
      <dl class="rd-layers">${Object.entries(CAPA).map(([k, [nombre, ic]]) => {
        const c = r.capas[k];
        return `<div class="rd-layer"><dt><span class="rd-light-ico" aria-hidden="true">${icon(ic, 'icon-sm')}</span>${nombre}
          <span class="rd-status" data-nivel="${c.estado}">${icon(NIVEL[c.estado].icon, 'icon-sm')}${NIVEL[c.estado].label}</span></dt>
          <dd><p>${esc(c.diagnostico)}</p><p class="rd-fix"><b>Corrección.</b> ${esc(c.correccion)}</p></dd></div>`;
      }).join('')}</dl>
      <div class="rd-priority">${icon('target', 'icon-sm')}<div><p class="rd-alert-title">${a.tipo === 'dia' ? 'Prioridad para mañana' : 'Prioridad de la semana'}</p><p>${esc(r.prioridad_manana)}</p>
        ${a.tarea_id && a.tarea_pendiente ? `<a class="tiny rd-alert-task" href="/tareas?item=${a.tarea_id}">${icon('square-check', 'icon-sm')}Ver la tarea de mañana</a>` : ''}
        ${a.nota_id ? `<a class="tiny rd-alert-task" href="/?note=${encodeURIComponent(a.nota_id)}">${icon('notebook-pen', 'icon-sm')}Abrir la nota</a>` : ''}</div></div>
      ${r.alertas.length ? `<ul class="rd-audit-alerts">${r.alertas.map((x) => `<li>${icon('triangle-alert', 'icon-sm')}${esc(x)}</li>`).join('')}</ul>` : ''}
    </li>`;
  }

  async function runAudit(tipo, forzar = false) {
    auditando = tipo;
    loadAuditKeep();
    let r;
    try {
      r = await api('/api/rendimiento/ia/auditar', { method: 'POST', body: { tipo, fecha, forzar }, quiet: true });
    } catch (e) {
      auditando = '';
      const d = e.data?.detail;
      const msg = typeof d === 'object' && d ? d.mensaje : e.message;
      toast(msg || 'La auditoría falló', { type: 'error', duration: 8000 });
      await loadAudit();
      if (d?.intentos?.length) $('rdAuditMsg').textContent = `Probados: ${d.intentos.map((i) => `${i.modelo} (${i.error})`).join(' · ')}`;
      return;
    }
    auditando = '';
    await loadAudit();
    if (r.cache) toast('Nada cambió desde la última: se muestra la guardada', { action: { label: 'Repetir', onClick: () => runAudit(tipo, true) }, duration: 8000 });
    else toast(`Auditoría lista · ${r.proveedor}`);
  }
  // Repinta los botones con «Auditando…» sin volver a pedir nada
  function loadAuditKeep() {
    document.querySelectorAll('[data-audit]').forEach((b) => {
      b.disabled = true;
      if (b.dataset.audit === auditando) b.lastChild.textContent = 'Auditando…';
      b.classList.toggle('is-loading', b.dataset.audit === auditando);
    });
    const m = $('rdAuditMsg');
    if (m) m.textContent = 'Puede tardar hasta un minuto si el primer modelo está saturado y hay que pasar al siguiente.';
  }
  async function savePrompt(valor) {
    try { await api('/api/rendimiento/ajustes', { method: 'PUT', body: { ia_prompt: valor } }); } catch { return; }
    toast(valor ? 'Instrucciones guardadas' : 'Instrucciones de serie');
    loadAudit();
  }

  /* ---------- Exámenes y asignaturas ---------- */
  async function loadExams() {
    skeleton($('rdExams'));
    let A;
    try { A = (await api('/api/rendimiento/examenes', { quiet: true })).asignaturas; } catch {
      showState($('rdExams'), loadFailed('No se pudo cargar', true), loadExams);
      return;
    }
    if (!A.length) {
      $('rdExams').innerHTML = emptyState({ iconName: 'graduation-cap', title: 'Sin exámenes ni asignaturas',
        text: 'Crea los exámenes en el Calendario con el tipo «Examen» y un título como «IG · Parcial 2»: la sigla antes del punto es la asignatura.',
        compact: true }) + `<p class="rd-center"><a class="btn btn-tinted btn-sm" href="/calendario">${icon('calendar', 'icon-sm')}Abrir el calendario</a></p>`;
      return;
    }
    const cuenta = (d) => (d == null ? '' : d === 0 ? 'Hoy' : d === 1 ? 'Mañana' : `En ${d} días`);
    $('rdExams').innerHTML = `<p class="small muted rd-exams-hint">Los exámenes salen del Calendario. Pon un objetivo de horas a cada asignatura para ver la deuda de estudio y el ritmo que necesitas.</p>
      <ul class="rd-exams">${A.map((a) => {
        const pctObj = a.objetivo_h ? Math.min(100, Math.round(100 * a.horas / a.objetivo_h)) : null;
        const urg = a.dias != null && a.dias <= 7 ? ' is-soon' : '';
        return `<li class="panel rd-exam${urg}">
          <div class="rd-exam-head"><h2>${esc(a.sigla)}</h2>
            ${a.proximo ? `<span class="rd-count tabular${urg}">${cuenta(a.dias)}</span>` : '<span class="tiny muted">Sin examen próximo</span>'}</div>
          ${a.examenes.length ? `<ul class="rd-exam-list">${a.examenes.map((e) => `<li><span class="tabular">${asDate(e.fecha).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}</span> ${esc(e.titulo)}</li>`).join('')}</ul>` : ''}
          <dl class="rd-exam-stats">
            <div><dt>Acumuladas</dt><dd class="tabular">${num(a.horas)}${NB}h</dd></div>
            <div><dt>Últimos 7 días</dt><dd class="tabular">${num(a.horas_semana)}${NB}h</dd></div>
            <div><dt>Deuda</dt><dd class="tabular${a.deuda_h ? ' is-debt' : ''}">${a.deuda_h != null ? `${num(a.deuda_h)}${NB}h` : '—'}</dd></div>
          </dl>
          ${pctObj != null ? `<div class="meter${pctObj >= 100 ? ' ok' : ''}" role="img" aria-label="${pctObj} % del objetivo"><span style="width:${pctObj}%"></span></div>` : ''}
          <div class="rd-exam-foot">
            <label class="rd-goal"><span class="small muted">Objetivo</span>
              <input class="input input-sm tabular" type="text" inputmode="decimal" maxlength="6" autocomplete="off" data-goal="${esc(a.sigla)}" value="${a.objetivo_h != null ? num(a.objetivo_h) : ''}" placeholder="—" aria-label="Objetivo de horas de ${esc(a.sigla)}">
              <span class="small muted">h</span></label>
            ${a.ritmo_h_dia ? `<span class="small rd-pace">${num(a.ritmo_h_dia)}${NB}h/día hasta el examen</span>` : a.ultima ? `<span class="tiny muted">Último bloque: ${asDate(a.ultima).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}</span>` : ''}
          </div></li>`;
      }).join('')}</ul>`;
  }
  async function saveGoal(input) {
    const raw = input.value.trim().replace(',', '.');
    const v = raw === '' ? null : Number(raw);
    if (v != null && (!Number.isFinite(v) || v < 0)) { input.setAttribute('aria-invalid', 'true'); toast('El objetivo es un número de horas', { type: 'error' }); return; }
    input.removeAttribute('aria-invalid');
    try { await api(`/api/rendimiento/asignaturas/${encodeURIComponent(input.dataset.goal)}`, { method: 'PUT', body: { objetivo_h: v } }); } catch { return; }
    loadExams();
  }

  /* ---------- Correlaciones ---------- */
  async function loadCorr() {
    skeleton($('rdCorr'), 1);
    let C;
    try { C = await api('/api/rendimiento/correlaciones', { quiet: true }); } catch {
      showState($('rdCorr'), loadFailed('No se pudo cargar', true), loadCorr);
      return;
    }
    if (!C.suficiente) {
      const falta = C.minimo - C.n;
      $('rdCorr').innerHTML = `<div class="panel rd-insufficient">
        ${emptyState({ iconName: 'chart-scatter', title: 'Datos insuficientes', text: `Para que una correlación signifique algo hacen falta al menos ${C.minimo} días con horas de sueño. Llevas ${C.n}: faltan ${falta}.`, compact: true })}
        <div class="meter" role="img" aria-label="${C.n} de ${C.minimo} días"><span style="width:${Math.round(100 * C.n / C.minimo)}%"></span></div></div>`;
      return;
    }
    const lectura = (r) => {
      if (r == null) return 'Sin variación suficiente para calcularla.';
      const a = Math.abs(r), fuerza = a >= 0.5 ? 'fuerte' : a >= 0.3 ? 'moderada' : a >= 0.1 ? 'débil' : 'prácticamente nula';
      return `Relación ${fuerza}${a >= 0.1 ? (r > 0 ? ': cuanto más duermes, más sube' : ': cuanto más duermes, más baja') : ''}. Correlación no es causa.`;
    };
    $('rdCorr').innerHTML = `<div class="rd-charts">
      ${scatterCard('rdsMin', 'Sueño y minutos efectivos', C.sueno_minutos, C.n, lectura(C.sueno_minutos), 'Horizontal: horas dormidas la noche anterior · vertical: enfoque efectivo ese día')}
      ${scatterCard('rdsEst', 'Sueño y estado cognitivo', C.sueno_estado, C.n_estado, lectura(C.sueno_estado), 'Horizontal: horas dormidas la noche anterior · vertical: % de bloques en estado funcional')}</div>`;
    const maxH = Math.max(1, Math.ceil(Math.max(...C.puntos.map((p) => p.minutos)) / 60));
    const hTicks = Array.from({ length: maxH + 1 }, (_, i) => i * 60).filter((v, i, a) => maxH <= 6 || i % 2 === 0 || i === a.length - 1);
    drawScatter($('rdsMin'), C.puntos, (p) => p.minutos, (v) => dur(v), { max: maxH * 60, ticks: hTicks, tickFmt: (v) => `${v / 60} h` });
    drawScatter($('rdsEst'), C.puntos.filter((p) => p.pct_funcional != null), (p) => p.pct_funcional, (v) => `${Math.round(v)} % de bloques funcionales`,
      { max: 100, ticks: [0, 50, 100], tickFmt: (v) => `${v} %` });
  }
  const scatterCard = (id, title, r, n, text, axes) => `<section class="panel hoy-card rd-chart-card" aria-labelledby="${id}H">
    <div class="panel-header"><h2 id="${id}H">${title}</h2><span class="grow"></span><span class="rd-r tabular">r = ${r == null ? '—' : num(r, 2)}</span></div>
    <div class="panel-body"><p class="small muted rd-chart-sub">${text} (${n} días)</p><p class="tiny muted rd-axes">${axes}</p><div class="rd-chart" id="${id}" role="group" aria-label="${esc(title)}"></div></div></section>`;
  function drawScatter(el, pts, fy, fmt, axis) {
    const draw = () => {
      const W = Math.max(240, el.clientWidth), H = 200, L = 40, R = 10, T = 10, B = 28;
      const xs = pts.map((p) => p.horas_sueno), ys = pts.map(fy);
      const x0 = Math.floor(Math.min(...xs)), x1 = Math.max(x0 + 1, Math.ceil(Math.max(...xs))), y0 = 0, y1 = axis.max;
      const X = (v) => L + (W - L - R) * (v - x0) / (x1 - x0), Y = (v) => T + (H - T - B) * (1 - (v - y0) / (y1 - y0));
      let s = `<svg width="${W}" height="${H}" aria-hidden="true" class="rd-svg">`;
      axis.ticks.forEach((v) => { s += `<line class="rd-grid" x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}"/><text class="rd-axis" x="${L - 6}" y="${Y(v) + 4}" text-anchor="end">${esc(axis.tickFmt(v))}</text>`; });
      for (let h = x0; h <= x1; h++) s += `<text class="rd-axis" x="${X(h)}" y="${H - 8}" text-anchor="middle">${h} h</text>`;
      s += pts.map((p, i) => `<circle class="rd-dot is-scatter" cx="${X(xs[i])}" cy="${Y(ys[i])}" r="4.5"/>`).join('');
      s += '</svg>';
      const hits = pts.map((p, i) => {
        const tip = `${cap(longDay(p.fecha))}: ${num(xs[i])} h de sueño · ${fmt(ys[i])}`;
        return `<button type="button" class="rd-hit is-point" style="left:${X(xs[i]) - 11}px;top:${Y(ys[i]) - 11}px" data-tip="${esc(tip)}" aria-label="${esc(tip)}"></button>`;
      }).join('');
      el.innerHTML = s + `<div class="rd-hits" style="height:${H}px">${hits}</div>`;
    };
    charts.set(el, { custom: draw });
    ro.observe(el);
    draw();
  }

  /* ---------- Registro del día ---------- */
  const OPC = {
    activacion: [['si', 'Sí'], ['parcial', 'Parcial'], ['no', 'No']],
    siesta: [['ninguna', 'Ninguna'], ['corta', '15–20 min'], ['larga', '90 min']],
    comida_tarde: [['baja', 'Baja en azúcares'], ['alta', 'Alta en azúcares simples']],
    codificacion: [['codigo', 'Código'], ['esquema', 'Esquema'], ['problemas', 'Problemas'], ['lectura', 'Lectura pasiva']],
    pausas: [['sistematico', 'Sistemáticas'], ['ocasional', 'Ocasionales'], ['no', 'No']],
    estado: [['funcional', 'Funcional'], ['degradado', 'Degradado']],
  };
  let uid = 0;
  const chips = (name, opts, val, label) => `<div class="choice-chips choice-chips-sm" role="radiogroup" aria-label="${esc(label)}">${opts.map(([v, l]) =>
    `<label class="choice-chip"><input type="radio" name="${name}" value="${v}" ${String(val) === String(v) ? 'checked' : ''}><span>${l}</span></label>`).join('')}</div>`;
  const scale = (name, val, from, to, label) => chips(name, Array.from({ length: to - from + 1 }, (_, i) => [from + i, String(from + i)]), val, label);
  const yesno = (name, val, label) => chips(name, [[1, 'Sí'], [0, 'No']], val == null ? '' : Number(val), label);
  const time = (name, val, label) => `<input type="text" class="input input-sm tabular rd-time" name="${name}" inputmode="numeric" maxlength="5" autocomplete="off" value="${esc(val || '')}" placeholder="23:30" aria-label="${esc(label)}">`;
  const row = (label, html, src) => `<div class="rd-row"><span class="rd-row-label">${label}${src ? `<span class="rd-src" title="Precargado desde ${esc(src)}">${esc(src)}</span>` : ''}</span><div class="rd-row-body">${html}</div></div>`;

  function blockHTML(b, asignaturas) {
    const k = `b${++uid}`;
    const top = asignaturas.slice(0, 6);
    return `<fieldset class="rd-block" data-block="${k}">
      <legend class="sr-only">Bloque de estudio</legend>
      <div class="rd-block-head">
        <input class="input input-sm rd-subject" name="${k}-asig" list="rdSubjects" maxlength="60" autocomplete="off" value="${esc(b.asignatura || '')}" placeholder="Asignatura o proyecto…" aria-label="Asignatura o proyecto" required>
        <input class="input input-sm tabular rd-min" name="${k}-min" type="number" autocomplete="off" min="1" max="600" step="5" value="${b.minutos || ''}" placeholder="min" aria-label="Minutos efectivos" required>
        <span class="small muted">min</span>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-del-block aria-label="Quitar este bloque">${icon('trash-2', 'icon-sm')}</button>
      </div>
      ${top.length ? `<div class="chips rd-subject-chips">${top.map((s) => `<button type="button" class="chip chip-sm" data-subject="${esc(s)}" aria-pressed="${s === b.asignatura}">${esc(s)}</button>`).join('')}</div>` : ''}
      <div class="chips rd-min-chips">${[25, 45, 50, 90].map((m) => `<button type="button" class="chip chip-sm" data-min="${m}">${m} min</button>`).join('')}</div>
      ${row('Anki / Active Recall previo', yesno(`${k}-rec`, b.recall ? 1 : 0, 'Active Recall previo'))}
      ${row('Codificación', chips(`${k}-cod`, OPC.codificacion, b.codificacion || 'problemas', 'Tipo de codificación'))}
      ${row('Pausas con ojos cerrados', chips(`${k}-pau`, OPC.pausas, b.pausas || 'ocasional', 'Pausas cortas'))}
      ${row('Estado cognitivo', chips(`${k}-est`, OPC.estado, b.estado || 'funcional', 'Estado cognitivo'))}
      ${row('Noté la caída a las', time(`${k}-cai`, b.caida, 'Hora en que noté la pérdida de rendimiento') + '<span class="tiny muted">opcional</span>')}
    </fieldset>`;
  }

  async function openLog(f = fecha) {
    let D;
    try { D = await api(`/api/rendimiento/dia?fecha=${f}`); } catch { return; }
    const r = D.registro || {}, s = D.sugerencia || {}, src = D.registro ? {} : D.fuentes;
    const v = (k) => (k in r ? r[k] : s[k]);
    const bloques = r.bloques || [];
    const dlg = document.createElement('dialog');
    dlg.className = 'modal rd-dialog';
    dlg.setAttribute('aria-labelledby', 'rdDlgTitle');
    dlg.innerHTML = `<div class="modal-header"><h2 id="rdDlgTitle">${D.registro ? 'Editar' : 'Registrar'} · ${esc(cap(longDay(f)))}</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body rd-form" id="rdForm" novalidate>
        <datalist id="rdSubjects">${D.asignaturas.map((a) => `<option value="${esc(a)}">`).join('')}</datalist>
        ${!D.registro && Object.keys(src).length ? `<p class="small muted rd-prefill">${icon('sparkles', 'icon-sm')}Precargado de tu último registro y de las rutinas marcadas: revisa y cambia lo que no cuadre.</p>` : ''}
        <section class="rd-sec"><h3>${icon('moon', 'icon-sm')}Anoche</h3>
          ${row('Me acosté', time('acostarse', v('acostarse'), 'Hora de acostarte'), src.acostarse)}
          ${row('Apagué pantallas', time('pantallas_off', v('pantallas_off'), 'Hora de apagar pantallas'), src.pantallas_off)}
          ${row('Me desperté', time('despertar', v('despertar'), 'Hora de despertar'), src.despertar)}
          ${row('Calidad del sueño', scale('calidad_sueno', v('calidad_sueno'), 1, 5, 'Calidad del sueño de 1 a 5'))}
        </section>
        <section class="rd-sec"><h3>${icon('sunrise', 'icon-sm')}Mañana</h3>
          ${row('Primer café', time('primer_cafe', v('primer_cafe'), 'Hora del primer café') + '<span class="tiny muted">vacío si no tomaste</span>', src.primer_cafe)}
          ${row('Activación matutina', chips('activacion', OPC.activacion, v('activacion'), 'Activación matutina'), src.activacion)}
          ${row('Luz solar directa', yesno('luz_solar', v('luz_solar'), 'Luz solar directa'), src.luz_solar)}
        </section>
        <section class="rd-sec"><h3>${icon('graduation-cap', 'icon-sm')}Bloques de estudio</h3>
          <div id="rdBlocks">${bloques.map((b) => blockHTML(b, D.asignaturas)).join('')}</div>
          <button type="button" class="btn btn-tinted btn-sm" id="rdAddBlock">${icon('plus', 'icon-sm')}Añadir bloque</button>
        </section>
        <section class="rd-sec"><h3>${icon('sunset', 'icon-sm')}Tarde</h3>
          ${row('Dopamina barata antes de las 19:00', yesno('dopamina', v('dopamina') ?? 0, 'Ocio digital antes de las 19:00') + `<span data-show="dopamina">${time('dopamina_hora', v('dopamina_hora'), 'Hora del ocio digital')}</span>`)}
          ${row('Siesta', chips('siesta', OPC.siesta, v('siesta') || 'ninguna', 'Siesta'), src.siesta)}
          ${row('Comida en el valle', chips('comida_tarde', OPC.comida_tarde, v('comida_tarde'), 'Alimentación en el valle de la tarde'), src.comida_tarde)}
          ${row('Entreno', yesno('entreno', v('entreno') ?? 0, 'Entreno'), src.entreno)}
          <div class="rd-sub" data-show="entreno">
            ${row('Terminé a las', time('entreno_fin', v('entreno_fin'), 'Hora de fin del entreno'), src.entreno_fin)}
            ${row('Duración', `<input class="input input-sm tabular rd-min" name="entreno_min" type="number" autocomplete="off" min="0" max="600" step="5" value="${v('entreno_min') ?? ''}" aria-label="Duración del entreno en minutos"><span class="small muted">min</span>`, src.entreno_min)}
            ${row('Intensidad', scale('entreno_intensidad', v('entreno_intensidad'), 1, 5, 'Intensidad percibida de 1 a 5'))}
          </div>
        </section>
        <section class="rd-sec"><h3>${icon('smile', 'icon-sm')}Cómo estás</h3>
          ${row('Energía', scale('energia', v('energia'), 1, 5, 'Energía de 1 a 5'))}
          ${row('Niebla mental', scale('niebla', v('niebla'), 1, 5, 'Niebla mental de 1 a 5, más alto es peor'))}
          ${row('Dolor de cabeza', scale('dolor_cabeza', v('dolor_cabeza'), 0, 3, 'Dolor de cabeza de 0 a 3'))}
          ${row('Humor', scale('humor', v('humor'), 1, 5, 'Humor de 1 a 5'))}
          <label class="field"><span class="field-label">Nota</span><textarea class="textarea" name="nota" rows="2" maxlength="4000" autocomplete="off" placeholder="Opcional: lo que quieras recordar de hoy…">${esc(r.nota || '')}</textarea></label>
        </section>
      </form>
      <div class="modal-footer">${D.registro ? `<button type="button" class="btn btn-danger" data-del-day>${icon('trash-2', 'icon-sm')}Borrar</button>` : ''}<span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="rdForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    const form = dlg.querySelector('form');
    const toggles = () => dlg.querySelectorAll('[data-show]').forEach((el) => { el.hidden = form.elements[el.dataset.show].value !== '1'; });
    toggles();
    form.addEventListener('change', toggles);
    // La pastilla marcada sigue a lo escrito en la asignatura
    form.addEventListener('input', (e) => {
      const t = e.target.closest('.rd-subject');
      if (t) t.closest('.rd-block').querySelectorAll('[data-subject]').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.subject === t.value.trim())));
    });
    // Horas escritas a mano: «730» → «07:30»
    form.addEventListener('focusout', (e) => {
      const t = e.target.closest('.rd-time');
      if (!t) return;
      const p = parseTime(t.value);
      if (p === null) t.setAttribute('aria-invalid', 'true'); else { t.value = p; t.removeAttribute('aria-invalid'); }
    });
    dlg.addEventListener('click', (e) => {
      const blk = e.target.closest('.rd-block');
      if (e.target.closest('#rdAddBlock')) {
        // el bloque nuevo copia los ajustes del anterior: suele repetirse la forma de estudiar
        const last = [...dlg.querySelectorAll('.rd-block')].pop();
        const prev = last ? readBlock(form, last.dataset.block) : { asignatura: D.asignaturas[0] || '', minutos: 50, recall: true };
        const box = $('rdBlocks');
        box.insertAdjacentHTML('beforeend', blockHTML({ ...prev, caida: null }, D.asignaturas));
        box.lastElementChild.querySelector('.rd-subject').focus();
      } else if (e.target.closest('[data-del-block]')) {
        blk.remove();
      } else if (e.target.closest('[data-subject]')) {
        const b = e.target.closest('[data-subject]');
        blk.querySelector('.rd-subject').value = b.dataset.subject;
        blk.querySelectorAll('[data-subject]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      } else if (e.target.closest('[data-min]')) {
        blk.querySelector('.rd-min').value = e.target.closest('[data-min]').dataset.min;
      } else if (e.target.closest('[data-del-day]')) {
        deleteDay(dlg, f);
      }
    });
    form.addEventListener('submit', (e) => { e.preventDefault(); submit(dlg, form, f); });
    guardUnsaved(dlg, form);
    openModal(dlg, { focus: D.registro ? '[data-close]' : 'input[name=acostarse]', onClose: () => dlg.remove() });
  }

  // Cerrar con cambios sin guardar pregunta antes (botones de cerrar y Esc)
  function guardUnsaved(dlg, form) {
    let dirty = false, asked = false;
    const mark = () => { dirty = true; };
    form.addEventListener('input', mark);
    form.addEventListener('change', mark);
    dlg.addEventListener('click', (e) => { if (e.target.closest('#rdAddBlock, [data-del-block]')) dirty = true; });
    const ask = async (e) => {
      if (!dirty || asked) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      if (await uiConfirm('¿Descartar los cambios?', 'Lo que has rellenado de este día no se guardará.', { confirmLabel: 'Descartar', cancelLabel: 'Seguir editando', danger: true })) {
        asked = true;
        closeModal(dlg);
      }
    };
    dlg.addEventListener('cancel', ask);
    dlg.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', ask, { capture: true }));
  }

  function readBlock(form, k) {
    const val = (n) => form.elements[`${k}-${n}`]?.value ?? '';
    return { asignatura: val('asig').trim(), minutos: Number(val('min')) || 0, recall: val('rec') === '1', codificacion: val('cod'),
      pausas: val('pau'), estado: val('est'), caida: parseTime(val('cai')) || null };
  }

  async function submit(dlg, form, f) {
    const E = form.elements;
    const bad = [...form.querySelectorAll('.rd-time')].find((t) => parseTime(t.value) === null);
    if (bad) { bad.setAttribute('aria-invalid', 'true'); bad.focus(); toast('Escribe la hora como 23:30', { type: 'error' }); return; }
    const blocks = [...form.querySelectorAll('.rd-block')].map((b) => readBlock(form, b.dataset.block));
    const incompleto = blocks.findIndex((b) => !b.asignatura || !(b.minutos > 0));
    if (incompleto >= 0) {
      const b = form.querySelectorAll('.rd-block')[incompleto];
      (b.querySelector('.rd-subject').value.trim() ? b.querySelector('.rd-min') : b.querySelector('.rd-subject')).focus();
      toast('Cada bloque necesita asignatura y minutos', { type: 'error' });
      return;
    }
    const t = (n) => parseTime(E[n].value) || null, i = (n) => (E[n].value === '' ? null : Number(E[n].value)), b = (n) => (E[n].value === '' ? null : E[n].value === '1');
    const body = {
      acostarse: t('acostarse'), pantallas_off: t('pantallas_off'), despertar: t('despertar'), calidad_sueno: i('calidad_sueno'),
      primer_cafe: t('primer_cafe'), activacion: E.activacion.value || null, luz_solar: b('luz_solar'),
      dopamina: b('dopamina'), dopamina_hora: t('dopamina_hora'), siesta: E.siesta.value || null, comida_tarde: E.comida_tarde.value || null,
      entreno: b('entreno'), entreno_fin: t('entreno_fin'), entreno_min: i('entreno_min'), entreno_intensidad: i('entreno_intensidad'),
      energia: i('energia'), niebla: i('niebla'), dolor_cabeza: i('dolor_cabeza'), humor: i('humor'), nota: E.nota.value, bloques: blocks,
    };
    const btn = dlg.querySelector('[type=submit]');
    btn.classList.add('is-loading');
    let res;
    try { res = await api(`/api/rendimiento/dia/${f}`, { method: 'PUT', body }); } catch { btn.classList.remove('is-loading'); return; }
    closeModal(dlg);
    const n = res.alertas.length;
    toast(n ? `Día guardado · ${n} alerta${n > 1 ? 's' : ''}` : 'Día guardado');
    if (f !== fecha) setDay(f); else loadTab();
  }

  async function deleteDay(dlg, f) {
    if (!(await uiConfirm('¿Borrar el registro de este día?', 'Queda 30 días en la papelera.', { confirmLabel: 'Borrar', danger: true }))) return;
    let r;
    try { r = await api(`/api/rendimiento/dia/${f}`, { method: 'DELETE' }); } catch { return; }
    closeModal(dlg);
    loadTab();
    toast('Registro en la papelera', { action: { label: 'Deshacer', onClick: async () => { await api(`/api/trash/brain/${r.trash}/restore`, { method: 'POST' }); loadTab(); } } });
  }

  /* ---------- Ajustes ---------- */
  async function openSettings() {
    let A;
    try { A = await api('/api/rendimiento/ajustes'); } catch { return; }
    const dlg = document.createElement('dialog');
    dlg.className = 'modal rd-dialog';
    dlg.setAttribute('aria-labelledby', 'rdSetTitle');
    const inp = (c) => {
      const v = A.ajustes[c.clave];
      const attrs = c.tipo === 'hora' ? `type="text" inputmode="numeric" maxlength="5" class="input input-sm tabular rd-time"`
        : `type="number" class="input input-sm tabular rd-num" autocomplete="off" ${c.rango ? `min="${c.rango[0]}" max="${c.rango[1]}"` : ''} step="${c.tipo === 'float' ? '0.5' : '1'}"`;
      return `<label class="rd-set"><span>${esc(c.etiqueta)}</span><input name="${c.clave}" ${attrs} value="${esc(v)}" data-default="${esc(A.defaults[c.clave])}"></label>`;
    };
    const opts = (sel) => `<option value="0"${sel === 0 ? ' selected' : ''}>Ninguna</option>` + A.rutinas.map((r) => `<option value="${r.id}"${r.id === sel ? ' selected' : ''}>${esc(r.content)}</option>`).join('');
    dlg.innerHTML = `<div class="modal-header"><h2 id="rdSetTitle">Ajustes de Rendimiento</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body rd-form" id="rdSetForm" novalidate>
        <section class="rd-sec"><h3>${icon('triangle-alert', 'icon-sm')}Umbrales</h3>${A.campos.map(inp).join('')}</section>
        <section class="rd-sec" id="rdSetIA"><h3>${icon('sparkles', 'icon-sm')}Modelos de IA</h3><span class="skeleton skeleton-card"></span></section>
        <section class="rd-sec"><h3>${icon('download', 'icon-sm')}Tus datos</h3>
          <p class="small muted">Tus registros, en tu equipo. El JSON lleva todo; el CSV va en dos tablas.</p>
          <div class="rd-export"><a class="btn btn-sm" href="/api/rendimiento/exportar?formato=json" download>${icon('download', 'icon-sm')}JSON</a>
            <a class="btn btn-sm" href="/api/rendimiento/exportar?formato=csv&amp;tabla=dias" download>${icon('download', 'icon-sm')}CSV de días</a>
            <a class="btn btn-sm" href="/api/rendimiento/exportar?formato=csv&amp;tabla=bloques" download>${icon('download', 'icon-sm')}CSV de bloques</a></div>
        </section>
        <section class="rd-sec"><h3>${icon('repeat', 'icon-sm')}Precarga desde Rutinas</h3>
          <p class="small muted">Si marcas esta rutina, el registro del día viene con el campo ya relleno.</p>
          ${A.rutinas_campos.map((c) => `<label class="rd-set"><span>${esc(c.etiqueta)}</span><select class="select input-sm" name="rut-${c.clave}">${opts(A.rutinas_mapa[c.clave] ?? 0)}</select></label>`).join('')}
        </section>
      </form>
      <div class="modal-footer"><button type="button" class="btn btn-ghost" data-reset>${icon('rotate-ccw', 'icon-sm')}Valores por defecto</button><span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="rdSetForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    const form = dlg.querySelector('form');
    dlg.querySelector('[data-reset]').addEventListener('click', () => form.querySelectorAll('[data-default]').forEach((i) => { i.value = i.dataset.default; }));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = { rutinas: {} };
      for (const c of A.campos) {
        const el = form.elements[c.clave];
        if (c.tipo === 'hora') {
          const p = parseTime(el.value);
          if (!p) { el.setAttribute('aria-invalid', 'true'); el.focus(); toast('Escribe la hora como 00:30', { type: 'error' }); return; }
          body[c.clave] = p;
        } else body[c.clave] = el.value;
      }
      A.rutinas_campos.forEach((c) => { body.rutinas[c.clave] = Number(form.elements[`rut-${c.clave}`].value); });
      try { await api('/api/rendimiento/ajustes', { method: 'PUT', body }); } catch { return; }
      closeModal(dlg);
      toast('Ajustes guardados');
      loadTab();
    });
    openModal(dlg, { focus: 'input', onClose: () => dlg.remove() });
    paintModels();
  }

  async function paintModels() {
    let E;
    try { E = await api('/api/rendimiento/ia/estado', { quiet: true }); } catch { return; }
    const box = $('rdSetIA');
    if (!box) return;
    const hora = (t) => new Date(t * 1000).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    box.innerHTML = `<h3>${icon('sparkles', 'icon-sm')}Modelos de IA</h3>
      <p class="small muted">Se prueban en este orden. Para cambiarlo o añadir otro, edita <code>${esc(E.archivo)}</code> (si no existe, copia <code>app/llm_modelos.json</code> a <code>data/llm_modelos.json</code>).</p>
      <ol class="rd-models">${E.modelos.map((m) => {
        const st = !m.clave ? ['gris', `Sin clave (${m.clave_env})`] : m.enfriado_hasta ? ['ambar', `En pausa hasta las ${hora(m.enfriado_hasta)}`]
          : m.ultima && !m.ultima.ok ? ['ambar', `Último fallo: ${m.ultima.error}`] : m.ultima ? ['verde', `Respondió en ${(m.ultima.latencia_ms / 1000).toFixed(1).replace('.', ',')} s`] : ['verde', 'Listo'];
        return `<li class="rd-model"><div class="rd-model-name"><b>${esc(m.proveedor)}</b> <code>${esc(m.modelo)}</code></div>
          <span class="rd-status" data-nivel="${st[0]}">${icon(NIVEL[st[0]].icon, 'icon-sm')}${esc(st[1])}</span>
          <span class="tiny muted tabular">${m.limite_dia ? `${m.uso_hoy}/${m.limite_dia} hoy` : `${m.uso_hoy} hoy`}</span></li>`;
      }).join('')}</ol>`;
  }

  /* ---------- Eventos ---------- */
  document.addEventListener('click', (e) => {
    const t = e.target;
    if (t.closest('#rdLog') || t.closest('[data-log]')) openLog();
    else if (t.closest('[data-log-day]')) openLog(t.closest('[data-log-day]').dataset.logDay);
    else if (t.closest('#rdSettings')) openSettings();
    else if (t.closest('[data-audit]')) runAudit(t.closest('[data-audit]').dataset.audit);
    else if (t.closest('[data-prompt-save]')) savePrompt($('rdPrompt').value.trim() === IA?.prompt_defecto ? '' : $('rdPrompt').value);
    else if (t.closest('[data-prompt-reset]')) savePrompt('');
    else if (t.closest('[data-day]')) { const k = Number(t.closest('[data-day]').dataset.day); setDay(k ? addDays(fecha, k) : today()); }
    else if (t.closest('[role=tab][data-tab]')) setTab(t.closest('[data-tab]').dataset.tab);
    else if (t.closest('[data-range]')) {
      const b = t.closest('[data-range]');
      rango = Number(b.dataset.range);
      paintRange();
      syncUrl();
      loadWeek();
    }
  });
  // Pestañas con flechas (patrón ARIA de tablist)
  document.querySelector('.rd-tabs').addEventListener('keydown', (e) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
    const tabs = [...document.querySelectorAll('[role=tab][data-tab]')];
    const i = tabs.findIndex((b) => b.dataset.tab === tab);
    const j = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    e.preventDefault();
    setTab(tabs[j].dataset.tab, true);
  });
  document.addEventListener('change', async (e) => {
    if (e.target.matches('[data-goal]')) saveGoal(e.target);
    if (e.target.id === 'rdIncluirNota') {
      try { await api('/api/rendimiento/ajustes', { method: 'PUT', body: { ia_incluir_nota: e.target.checked } }); } catch { e.target.checked = !e.target.checked; return; }
      toast(e.target.checked ? 'La nota libre se enviará a la IA' : 'La nota libre ya no se envía');
    }
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.matches('[data-goal]')) { e.preventDefault(); e.target.blur(); } });

  function paintRange() { document.querySelectorAll('[data-range]').forEach((x) => x.setAttribute('aria-pressed', String(Number(x.dataset.range) === rango))); }
  paintRange();
  setTab(tab);
  setDay(fecha);
  if (params.get('registrar')) { openLog(); history.replaceState(null, '', location.pathname); }
})();
