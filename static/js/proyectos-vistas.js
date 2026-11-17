/* =====================================================================
   Vistas de Proyectos que no son tarjetas: tabla ordenable y cronología (Gantt sencillo, sin librerías).
   PjVistas.table(el, rows, { columns, sort, onSort, onOpen, onToggle })
   PjVistas.timeline(el, rows, { markers, pxPerDay, onOpen, empty })
     rows:    [{ id, label, sub, start, end, color, done, href }]   (fechas AAAA-MM-DD; sin end = un hito)
     markers: [{ date, label }]   líneas verticales (versiones)
   ===================================================================== */
(function () {
  'use strict';

  const esc = (s) => escapeHtml(s);
  const DAY = 86400000;
  const parse = (iso) => (iso ? new Date(iso + 'T00:00') : null);
  const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const fmt = (iso, opts = { day: 'numeric', month: 'short' }) => (iso ? parse(iso).toLocaleDateString('es-ES', opts) : '');
  const days = (a, b) => Math.round((b - a) / DAY);

  /* ---------- Tabla ordenable ----------
     columns: [{ key, label, sortable, cls, render(row) → html, value(row) → para ordenar }] */
  function table(el, rows, { columns, sort = { key: null, dir: 1 }, onSort, onOpen, caption }) {
    const col = columns.find((c) => c.key === sort.key);
    const sorted = col ? [...rows].sort((a, b) => {
      const va = col.value(a), vb = col.value(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;  // lo vacío siempre al final
      if (vb == null) return -1;
      return (typeof va === 'string' ? va.localeCompare(vb, 'es', { sensitivity: 'base' }) : va - vb) * sort.dir;
    }) : rows;
    el.innerHTML = `<div class="pjt-wrap"><table class="pjt">${caption ? `<caption class="sr-only">${esc(caption)}</caption>` : ''}
      <thead><tr>${columns.map((c) => {
        const on = c.key === sort.key;
        const aria = c.sortable ? ` aria-sort="${on ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}"` : '';
        return `<th scope="col" class="${c.cls || ''}"${aria}>${c.sortable ? `<button type="button" class="pjt-sort" data-sort="${c.key}">${esc(c.label)}${icon(on ? (sort.dir > 0 ? 'arrow-up' : 'arrow-down') : 'arrow-down-up', 'icon-sm')}</button>` : c.label}</th>`;
      }).join('')}</tr></thead>
      <tbody>${sorted.map((r) => `<tr data-row="${r.id}" class="${r.done ? 'is-done' : ''}">${columns.map((c) => `<td class="${c.cls || ''}">${c.render(r)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    el.querySelectorAll('[data-sort]').forEach((b) => b.addEventListener('click', () => {
      const k = b.dataset.sort;
      onSort?.({ key: k, dir: sort.key === k ? -sort.dir : 1 });
    }));
    el.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); onOpen?.(Number(b.dataset.open)); }));
  }

  /* ---------- Cronología ---------- */
  function timeline(el, rows, { markers = [], pxPerDay = 18, onOpen, empty = 'Nada con fechas todavía.', label = 'Cronología' } = {}) {
    const dated = rows.filter((r) => r.start || r.end);
    if (!dated.length) { el.innerHTML = emptyState({ iconName: 'chart-gantt', title: 'Sin fechas', text: empty, compact: true }); return; }
    const today = parse(isoOf(new Date()));
    const all = [...dated.flatMap((r) => [r.start, r.end]), ...markers.map((m) => m.date)].filter(Boolean).map(parse);
    let from = new Date(Math.min(...all, today)), to = new Date(Math.max(...all, today));
    from = new Date(from.getFullYear(), from.getMonth(), 1);                      // del día 1 del primer mes…
    to = new Date(to.getFullYear(), to.getMonth() + 1, 0);                        // …al último del último
    const total = days(from, to) + 1;
    const room = Math.max(320, (el.clientWidth || 800) - (window.matchMedia('(max-width: 767px)').matches ? 130 : 222));
    const ppd = Math.max(pxPerDay, Math.ceil(room / total));                       // que llene al menos el ancho visible
    const W = total * ppd, x = (d) => days(from, d) * ppd;
    const months = [];
    for (let d = new Date(from); d <= to; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
      const end = new Date(d.getFullYear(), d.getMonth() + 1, 0);
      months.push({ x: x(d), w: (days(d, end > to ? to : end) + 1) * ppd, label: d.toLocaleDateString('es-ES', { month: 'short', year: ppd < 6 ? '2-digit' : undefined }) });
    }
    const weeks = [];
    if (ppd >= 6) for (let d = new Date(from); d <= to; d = new Date(d.getTime() + DAY)) if (d.getDay() === 1) weeks.push(x(d));
    const bar = (r) => {
      const s = parse(r.start || r.end), e = parse(r.end || r.start);
      const left = x(s), w = Math.max(ppd, (days(s, e) + 1) * ppd);
      const milestone = !r.start || !r.end || r.start === r.end;
      const late = !r.done && r.end && parse(r.end) < today;
      const when = r.start && r.end && r.start !== r.end ? `del ${fmt(r.start)} al ${fmt(r.end, { day: 'numeric', month: 'short', year: 'numeric' })}` : fmt(r.end || r.start, { day: 'numeric', month: 'short', year: 'numeric' });
      const tag = r.href ? 'a' : 'button';
      return `<${tag} ${r.href ? `href="${esc(r.href)}"` : `type="button" data-open="${r.id}"`} class="pjg-bar${milestone ? ' is-milestone' : ''}${r.done ? ' is-done' : ''}${late ? ' is-late' : ''}"
        style="--x:${left}px;--w:${milestone ? ppd : w}px;--c:${r.color || 'var(--accent)'}" aria-label="${esc(r.label)}: ${esc(when)}${r.done ? ', hecho' : late ? ', vencido' : ''}" title="${esc(r.label)} · ${esc(when)}">
        ${milestone ? '' : `<span class="pjg-bar-label">${esc(r.label)}</span>`}</${tag}>`;
    };
    const undated = rows.length - dated.length;
    el.innerHTML = `<div class="pjg" role="region" aria-label="${esc(label)}" tabindex="0">
      <div class="pjg-grid" style="--W:${W}px">
        <div class="pjg-corner"></div>
        <div class="pjg-scale" aria-hidden="true">${months.map((m) => `<span class="pjg-month" style="left:${m.x}px;width:${m.w}px">${esc(m.label)}</span>`).join('')}</div>
        ${dated.map((r, i) => `<div class="pjg-label${r.done ? ' is-done' : ''}" style="grid-row:${i + 2}">${r.href ? `<a href="${esc(r.href)}">${esc(r.label)}</a>` : `<button type="button" class="pjg-name" data-open="${r.id}">${esc(r.label)}</button>`}${r.sub ? `<span class="tiny muted">${esc(r.sub)}</span>` : ''}</div>
          <div class="pjg-track" style="grid-row:${i + 2}">${bar(r)}</div>`).join('')}
        <div class="pjg-lines" aria-hidden="true" style="grid-row: 2 / span ${dated.length}">
          ${weeks.map((w) => `<span class="pjg-week" style="left:${w}px"></span>`).join('')}
          ${months.map((m) => `<span class="pjg-mline" style="left:${m.x}px"></span>`).join('')}
          ${markers.map((m) => `<span class="pjg-marker" style="left:${x(parse(m.date)) + ppd / 2}px"><span class="pjg-marker-label">${esc(m.label)}</span></span>`).join('')}
          <span class="pjg-today" style="left:${x(today) + ppd / 2}px"><span class="pjg-marker-label">Hoy</span></span>
        </div>
      </div></div>
      ${markers.length ? `<ul class="pjg-legend tiny muted">${markers.map((m) => `<li>${icon('milestone', 'icon-sm')}${esc(m.label)} · ${fmt(m.date, { day: 'numeric', month: 'short', year: 'numeric' })}</li>`).join('')}</ul>` : ''}
      ${undated ? `<p class="tiny muted pjg-undated">${undated === 1 ? '1 sin fecha' : `${undated} sin fecha`}: no salen aquí.</p>` : ''}`;
    el.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => onOpen?.(Number(b.dataset.open))));
    // Empieza mostrando hoy (o el principio si hoy queda fuera)
    const box = el.querySelector('.pjg');
    const tx = x(today) - 200;
    if (tx > 0) box.scrollLeft = tx;
  }

  window.PjVistas = { table, timeline, isoOf, fmt };
})();
