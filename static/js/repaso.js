/* ==========================================================================
   repaso.js — calendario de flashcards, días de estudio y notas sin repasar
   ========================================================================== */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const dayFmt = new Intl.DateTimeFormat('es-ES', { weekday: 'long', day: 'numeric', month: 'long' });
  const parse = (iso) => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
  const level = (n, max) => (n === 0 ? 0 : n <= max / 3 ? 1 : n <= (2 * max) / 3 ? 2 : 3);

  const plural = (n, one, many) => `<b>${n}</b> ${n === 1 ? one : many}`;

  async function load() {
    // medio año en pantalla grande; en el móvil, lo que cabe a lo ancho
    const weeks = matchMedia('(max-width: 767px)').matches ? 15 : 26;
    const cal = await api(`/api/review/calendar?past_weeks=${weeks}&future_days=28`);
    const parts = [
      cal.due_today ? `${plural(cal.due_today, 'flashcard', 'flashcards')} para hoy` : 'Nada que repasar hoy',
      cal.overdue ? `<span class="warn">${plural(cal.overdue, 'atrasada', 'atrasadas')}</span>` : '',
      cal.streak ? `racha de ${plural(cal.streak, 'día', 'días')}` : 'sin racha todavía',
      `${plural(cal.studied_days, 'día', 'días')} de estudio en ${weeks} semanas`,
    ].filter(Boolean);
    $('summary').innerHTML = parts.join(' · ');
    $('btnReview').hidden = !cal.due_today;

    // Próximas semanas: rejilla que empieza en lunes
    const max = Math.max(1, ...cal.upcoming.map((d) => d.flashcards));
    const pad = (parse(cal.upcoming[0].date).getDay() + 6) % 7;
    $('upcoming').innerHTML = '<li class="cal-pad" aria-hidden="true"></li>'.repeat(pad) + cal.upcoming.map((d, i) => {
      const date = parse(d.date);
      const label = `${dayFmt.format(date)}: ${d.flashcards} ${d.flashcards === 1 ? 'flashcard' : 'flashcards'}`;
      return `<li><button type="button" class="cal-day${i === 0 ? ' today' : ''}" data-level="${level(d.flashcards, max)}" data-i="${i}" aria-pressed="false" aria-label="${label}">
        <span class="d">${i === 0 ? 'Hoy' : date.getDate()}</span><span class="n" aria-hidden="true">${d.flashcards || ''}</span></button></li>`;
    }).join('');
    const any = cal.upcoming.some((d) => d.flashcards);
    // sin nada programado no se pinta un mes vacío: basta con decir cómo empezar
    $('upcomingBody').hidden = !any;
    $('upcomingEmpty').hidden = any;
    $('dayDetail').textContent = any ? 'Toca un día para ver de qué notas son.' : '';
    $('upcoming').onclick = (e) => {
      const b = e.target.closest('[data-i]');
      if (!b) return;
      $('upcoming').querySelectorAll('[data-i]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      const d = cal.upcoming[Number(b.dataset.i)];
      $('dayDetail').textContent = d.flashcards
        ? `${dayFmt.format(parse(d.date))}: ${d.flashcards} ${d.flashcards === 1 ? 'flashcard' : 'flashcards'}${d.notes.length ? ` de ${d.notes.join(', ')}` : ''}.`
        : `${dayFmt.format(parse(d.date))}: nada que repasar.`;
    };

    // Mapa de calor: columnas = semanas (lunes arriba)
    const today = cal.today;
    const lead = (parse(cal.heat[0].date).getDay() + 6) % 7;  // la primera columna empieza en lunes
    const cells = cal.heat.map((h) => `<li data-on="${h.studied}" title="${dayFmt.format(parse(h.date))}${h.studied ? ': estudiaste' : ''}"></li>`);
    const tail = (7 - ((lead + cells.length) % 7)) % 7;
    $('heat').innerHTML = '<li class="future" aria-hidden="true"></li>'.repeat(lead) + cells.join('') + '<li class="future" aria-hidden="true"></li>'.repeat(tail);
    // meses encima de la columna en que empieza cada uno
    const cols = Math.ceil((lead + cells.length) / 7);
    const monthFmt = new Intl.DateTimeFormat('es-ES', { month: 'short' });
    let last = -1;
    $('heatMonths').style.setProperty('--cols', cols);
    $('heat').style.setProperty('--cols', cols);
    $('heatMonths').innerHTML = Array.from({ length: cols }, (_, c) => {
      const h = cal.heat[Math.max(0, c * 7 - lead)];
      const m = h ? parse(h.date).getMonth() : last;
      const show = m !== last && c < cols - 1;
      last = m;
      return `<span>${show && h ? monthFmt.format(parse(h.date)).replace('.', '') : ''}</span>`;
    }).join('');
    $('heat').setAttribute('aria-label', `Estudiaste ${cal.studied_days} de los últimos ${cal.heat.length} días`);
    $('heatInfo').textContent = `hasta hoy, ${dayFmt.format(parse(today))}`;

    $('staleCount').textContent = cal.stale_total;
    $('staleList').innerHTML = cal.stale_notes.length ? cal.stale_notes.map((n) => `<li><a class="list-row" href="/?note=${encodeURIComponent(n.id)}">
      <span class="status-dot" data-status="${escapeHtml(n.status)}" aria-hidden="true"></span>
      <span class="row-main"><span class="row-title">${escapeHtml(n.title)}</span><span class="row-sub">${escapeHtml(n.category)}</span></span>
      <span class="row-trail">${n.days == null ? 'nunca' : `hace ${n.days} días`}${icon('chevron-right', 'icon-sm')}</span></a></li>`).join('')
      : `<li>${emptyState({ iconName: 'circle-check', title: 'Todo repasado', text: 'Ninguna nota lleva más de 30 días sin repasar.', compact: true })}</li>`;
  }

  load().catch(() => {});
})();
