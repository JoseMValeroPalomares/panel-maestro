/* ==========================================================================
   calendar.js — el calendario del Panel (window.Calendar)
     Calendar.mount(el, { view: 'week' | '3d' | 'day' | 'month' | 'agenda', date, compact, days, hide: ['routine'] })
     (hide: tipos de entrada que no se pintan: 'event', 'task' o 'routine')

   Datos: GET /api/calendar/entries (app/calendar.py): eventos, tareas con fecha (bloques
   de tiempo si tienen hora) y rutinas de cada día, con el mismo formato. Escrituras:
     - eventos: /api/calendar/events
     - tareas: Items.update (fecha, hora, duración: el bloque ES la tarea)
     - rutinas: marcar el día (/api/routines/{id}/check) o cambiar su hora (Items.update)
   Gestos (ratón y dedo; con el dedo, pulsación larga): arrastrar mueve, el borde inferior
   redimensiona, arrastrar en vacío crea, clic edita. Una tarea o idea de la lista de la
   izquierda (o de cualquier [data-cal-drag-item]) soltada en la rejilla crea un bloque.
   Con el dedo, deslizar en horizontal pasa al periodo anterior o siguiente.
   Teclado: ←/→ periodo, T hoy, D/3/S/M/A vista (fuera de campos de texto).
   ========================================================================== */
(function () {
  'use strict';

  const HOUR = 48;          // px por hora en los calendarios pequeños (notas); en la página, ver hourFor()
  const SIZE_KEY = 'calendar-hour-size';  // altura de cada hora: normal, tall (alta) o fit (que quepa todo el horario)
  // Horario visible en Día/3 días/Semana (Prefs, se recuerda): lo de fuera se avisa en la columna
  const HOURS_KEY = 'calendar-hours';
  const ROUTINES_KEY = 'calendar-show-routines';  // ver u ocultar los bloques de las rutinas (se recuerda)
  const hoursPref = () => { const h = window.Prefs?.get(HOURS_KEY, null) || {}; const a = Math.max(0, Math.min(23, h.start ?? 8)); return { start: a, end: Math.max(a + 1, Math.min(24, h.end ?? 22)) }; };
  const SNAP = 15;          // minutos
  const DAY_MS = 86400000;
  const DOW = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
  const VIEW_LABEL = { day: 'Día', '3d': '3 días', week: 'Semana', month: 'Mes', agenda: 'Agenda' };
  const KIND_LABEL = { evento: 'Evento', examen: 'Examen', entrega: 'Entrega', bloque: 'Bloque' };
  const esc = (s) => escapeHtml(s);

  /* ---------- Fechas (siempre locales, «AAAA-MM-DD» / «AAAA-MM-DDTHH:MM») ---------- */
  const pad = (n) => String(n).padStart(2, '0');
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const parse = (s) => new Date(s.length > 10 ? s : s + 'T00:00');
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const monday = (d) => addDays(d, -((d.getDay() + 6) % 7));
  const minutes = (s) => (s.length > 10 ? Number(s.slice(11, 13)) * 60 + Number(s.slice(14, 16)) : 0);
  const hhmm = (m) => `${pad(Math.floor(m / 60))}:${pad(m % 60)}`;
  const at = (day, m) => `${day}T${hhmm(Math.max(0, Math.min(1439, m)))}`;
  const todayIso = () => iso(new Date());
  const fmtDay = (d, opts) => d.toLocaleDateString('es-ES', opts);
  const snap = (m) => Math.round(m / SNAP) * SNAP;

  function entryRange(e) {
    const s = parse(e.start);
    let end = e.end ? parse(e.end) : (e.all_day ? addDays(s, 1) : new Date(+s + 3600000));
    if (e.all_day && e.end && e.end.length === 10 && +end <= +s) end = addDays(s, 1);
    return [s, end];
  }
  // Días (AAAA-MM-DD) que ocupa una entrada
  function daysOf(e) {
    const [s, end] = entryRange(e);
    const out = [];
    let d = new Date(s.getFullYear(), s.getMonth(), s.getDate());
    const last = e.all_day ? addDays(end, -1) : new Date(+end - 1);
    while (+d <= +last && out.length < 62) { out.push(iso(d)); d = addDays(d, 1); }
    return out.length ? out : [iso(s)];
  }

  /* ---------- Componente ---------- */
  const instances = new Set();
  let dragItem = null;  // tarea arrastrada desde una lista externa

  class Cal {
    constructor(el, opts = {}) {
      this.el = el;
      this.compact = !!opts.compact;
      this.view = opts.view || (window.matchMedia('(max-width: 767px)').matches ? '3d' : 'week');
      this.days = opts.days || (this.compact ? 7 : 14);
      this.date = opts.date ? parse(opts.date) : new Date();
      this.entries = [];
      this.onChange = opts.onChange;
      this.hide = new Set(opts.hide || []);
      el.classList.add('cal', `cal-${this.compact ? 'compact' : 'full'}`);
      el.innerHTML = `<div class="cal-body" aria-live="polite"><div class="skeleton skeleton-card"></div></div>`;
      el.addEventListener('click', (e) => this.onClick(e));
      el.addEventListener('pointerdown', (e) => this.onPointerDown(e));
      el.addEventListener('dragover', (e) => this.onDragOver(e));
      el.addEventListener('drop', (e) => this.onDrop(e));
      el.addEventListener('keydown', (e) => this.onKey(e));
      if (!this.compact) this.swipe();
      instances.add(this);
      this.load();
    }

    /* ---------- Rango visible ---------- */
    range() {
      const d = this.date;
      if (this.view === 'day') return [d, d];
      if (this.view === '3d') return [d, addDays(d, 2)];
      if (this.view === 'week') { const m = monday(d); return [m, addDays(m, 6)]; }
      if (this.view === 'agenda') return [d, addDays(d, this.days - 1)];
      const first = new Date(d.getFullYear(), d.getMonth(), 1);
      const start = monday(first);
      return [start, addDays(start, 41)];
    }

    title() {
      const [a, b] = this.range();
      if (this.view === 'day') return fmtDay(a, { weekday: 'long', day: 'numeric', month: 'long' });
      if (this.view === 'month') return fmtDay(this.date, { month: 'long', year: 'numeric' });
      const same = a.getMonth() === b.getMonth();
      return `${fmtDay(a, { day: 'numeric', ...(same ? {} : { month: 'short' }) })} – ${fmtDay(b, { day: 'numeric', month: 'short', year: 'numeric' })}`;
    }

    setView(v) { this.view = v; this.load(); }
    go(delta) {
      if (delta === 0) this.date = new Date();
      else if (this.view === 'day') this.date = addDays(this.date, delta);
      else if (this.view === '3d') this.date = addDays(this.date, 3 * delta);
      else if (this.view === 'agenda') this.date = addDays(this.date, this.days * delta);
      else if (this.view === 'month') this.date = new Date(this.date.getFullYear(), this.date.getMonth() + delta, 1);
      else this.date = addDays(this.date, 7 * delta);
      this.load();
    }
    goTo(day) { this.date = parse(day); this.load(); }

    // Con el dedo: deslizar en horizontal (sin pulsación larga) cambia de periodo
    swipe() {
      let s = null;
      this.el.addEventListener('pointerdown', (e) => { s = e.pointerType === 'touch' ? { x: e.clientX, y: e.clientY, t: Date.now() } : null; });
      this.el.addEventListener('pointerup', (e) => {
        if (!s || this.el.classList.contains('is-dragging') || this.el.querySelector('.cal-inline')) { s = null; return; }
        const dx = e.clientX - s.x, dy = e.clientY - s.y;
        if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy) && Date.now() - s.t < 700) this.go(dx < 0 ? 1 : -1);
        s = null;
      });
    }

    async load() {
      const [a, b] = this.range();
      try {
        const data = await api(`/api/calendar/entries?start=${iso(a)}&end=${iso(b)}`, { quiet: true });
        const noRoutines = !this.compact && window.Prefs?.get(ROUTINES_KEY, true) === false;
        this.entries = data.entries.filter((e) => !this.hide.has(e.kind) && !(noRoutines && e.kind === 'routine'));
        // un pintado anterior (al llegar las preferencias) no sabía aún qué hay: la primera vez se coloca con los datos
        if (!this.placed) { this.placed = true; this.keepScroll = null; }
      } catch {
        showState(this.el.querySelector('.cal-body'), loadFailed('No se pudo cargar el calendario', true), () => this.load());
        return;
      }
      this.render();
    }

    /* ---------- Pintado ---------- */
    render() {
      const body = this.el.querySelector('.cal-body') || this.el;
      const scroller = body.querySelector('.cal-scroll');
      const keep = this.keepScroll !== undefined ? this.keepScroll : scroller ? scroller.scrollTop : null;
      this.keepScroll = undefined;
      body.innerHTML = this.view === 'month' ? this.monthHTML() : this.view === 'agenda' ? this.agendaHTML() : this.gridHTML();
      const sc = body.querySelector('.cal-scroll');
      if (sc && !this.compact) {
        const tabbar = document.querySelector('.tabbar')?.offsetHeight || 0;
        const avail = window.innerHeight - sc.getBoundingClientRect().top - tabbar - 20;
        const next = this.hourFor(sc, avail);
        if (Math.abs(next - this.hour) > 1 && !this.refitting) {
          this.keepScroll = keep === null ? null : keep * next / this.hour;  // misma hora a la vista
          this.hour = next;
          this.refitting = true;
          this.render();
          this.refitting = false;
          return;
        }
        sc.style.maxHeight = `${Math.max(320, avail)}px`;
        // la barra de desplazamiento no debe descuadrar la cabecera respecto a las columnas
        sc.parentElement.style.setProperty('--scrollbar', `${sc.offsetWidth - sc.clientWidth}px`);
      }
      if (sc) sc.scrollTop = keep ?? this.firstScroll();
      this.onChange?.(this);
      this.el.dispatchEvent(new CustomEvent('cal:rendered', { bubbles: true }));
    }

    /* Altura de una hora: la franja no debe ser mucho más ancha que alta, así que crece con el ancho de la
       columna (entre un mínimo legible y un máximo). «fit» reparte la pantalla para ver todo el horario. */
    hourFor(sc, avail) {
      const size = window.Prefs?.get(SIZE_KEY, 'normal');
      if (size === 'fit') return Math.round(Math.max(34, Math.min(72, avail / (this.h1 - this.h0))));
      const col = sc.querySelector('.cal-col')?.offsetWidth || 0;
      const phone = window.innerWidth < 768;
      const [min, max] = size === 'tall' ? [96, phone ? 110 : 150] : [72, phone ? 84 : 110];
      return Math.round(Math.max(min, Math.min(max, col / (size === 'tall' ? 1.5 : 2))));
    }

    /* minutos desde medianoche → px dentro de la rejilla (y al revés), según el horario visible */
    y(min) { return (min - this.h0 * 60) / 60 * this.hour; }
    minAt(y) { return y / this.hour * 60 + this.h0 * 60; }

    firstScroll() {
      const [a, b] = this.range(), t = todayIso();
      let m = 7 * 60;
      if (t >= iso(a) && t <= iso(b)) { const n = new Date(); m = n.getHours() * 60 + n.getMinutes() - 90; }
      else {
        const timed = this.entries.filter((e) => !e.all_day).map((e) => minutes(e.start));
        if (timed.length) m = Math.min(...timed) - 30;
      }
      return Math.max(0, this.y(m));
    }

    chip(e, extra = '') {
      const done = e.done ? ' is-done' : '';
      const t = e.all_day ? '' : `<span class="cal-time tabular">${e.start.slice(11, 16)}${this.view === 'agenda' && e.end ? `–${e.end.slice(11, 16)}` : ''}</span>`;
      const loc = this.view === 'agenda' && e.location ? `<span class="cal-loc">${icon('map-pin', 'icon-sm')}${esc(e.location)}</span>` : '';
      const check = e.kind !== 'event' ? `<span class="cal-check" data-cal-check="${esc(e.key)}" role="checkbox" aria-checked="${e.done}" aria-label="${e.done ? 'Desmarcar' : 'Marcar'}: ${esc(e.title)}" tabindex="-1">${icon(e.done ? 'circle-check' : 'circle', 'icon-sm')}</span>` : '';
      return `<button type="button" class="cal-chip${done}" data-key="${esc(e.key)}" data-kind="${e.kind}" data-type="${esc(e.type)}" ${extra}
        aria-label="${esc(this.describe(e))}">${check}${t}<span class="cal-title">${esc(e.title)}</span>${loc}</button>`;
    }

    describe(e) {
      const what = e.kind === 'event' ? KIND_LABEL[e.type] || 'Evento' : e.step ? `${e.routine_title}` : e.kind === 'routine' ? 'Rutina' : e.type === 'idea' ? 'Idea' : 'Tarea';
      const when = e.all_day ? 'todo el día' : `de ${e.start.slice(11, 16)} a ${(e.end || '').slice(11, 16)}`;
      return `${what}: ${e.title}, ${fmtDay(parse(e.start), { weekday: 'long', day: 'numeric', month: 'long' })}, ${when}${e.location ? `, en ${e.location}` : ''}${e.done ? ' (hecho)' : ''}`;
    }

    gridHTML() {
      const { start: h0, end: h1 } = hoursPref();
      this.h0 = h0; this.h1 = h1;
      this.hour = this.hour || HOUR;
      const lo = h0 * 60, hi = h1 * 60;
      const [a, b] = this.range();
      const days = [];
      for (let d = new Date(a); +d <= +b; d = addDays(d, 1)) days.push(iso(d));
      const today = todayIso();
      const allDay = Object.fromEntries(days.map((d) => [d, []]));
      const timed = Object.fromEntries(days.map((d) => [d, []]));
      this.entries.forEach((e) => {
        if (e.all_day) daysOf(e).forEach((d) => allDay[d]?.push(e));
        else (timed[e.start.slice(0, 10)] || []).push(e);
      });
      const nowMin = new Date().getHours() * 60 + new Date().getMinutes();
      const cols = days.map((d) => {
        // lo que cae fuera del horario visible no se pinta: se avisa arriba o abajo de la columna
        const before = timed[d].filter((e) => (e.end && e.end.slice(0, 10) === d ? minutes(e.end) : 1440) <= lo);
        const after = timed[d].filter((e) => minutes(e.start) >= hi);
        const laid = layout(timed[d].filter((e) => !before.includes(e) && !after.includes(e)));
        const out = (list, where) => list.length ? `<button type="button" class="cal-out cal-out-${where}" data-key="${esc(list[0].key)}" title="${esc(list.map((e) => `${e.start.slice(11, 16)} ${e.title}`).join('\n'))}"
          aria-label="${list.length} fuera del horario visible (${where === 'top' ? 'antes' : 'después'}): ${esc(list.map((e) => e.title).join(', '))}">${icon(where === 'top' ? 'chevron-up' : 'chevron-down', 'icon-sm')}${list.length}</button>` : '';
        return `<div class="cal-col${d === today ? ' is-today' : ''}${isWeekend(d) ? ' is-weekend' : ''}" data-day="${d}" role="group" aria-label="${esc(fmtDay(parse(d), { weekday: 'long', day: 'numeric', month: 'long' }))}">
          ${laid.map(({ e, col, cols: n }) => {
            const s0 = Math.max(lo, minutes(e.start));
            const endM = Math.min(hi, e.end && e.end.slice(0, 10) === d ? minutes(e.end) : 1440);
            const top = this.y(s0);
            const h = Math.max(18, (endM - s0) / 60 * this.hour - 2);
            return `<div class="cal-ev${e.done ? ' is-done' : ''}${h < 40 ? ' is-short' : ''}${h < 26 ? ' is-tiny' : ''}${e.step ? ' is-step' : ''}" data-key="${esc(e.key)}" data-kind="${e.kind}" data-type="${esc(e.type)}"
              style="top:${top}px;height:${h}px;left:calc(${col / n * 100}% + 2px);width:calc(${100 / n}% - 4px)">
              <button type="button" class="cal-ev-main" data-key="${esc(e.key)}" aria-label="${esc(this.describe(e))}">
                ${e.kind !== 'event' ? `<span class="cal-check" data-cal-check="${esc(e.key)}" role="checkbox" aria-checked="${e.done}" aria-label="${e.done ? 'Desmarcar' : 'Marcar'}" tabindex="-1">${icon(e.done ? 'circle-check' : 'circle', 'icon-sm')}</span>` : ''}
                <span class="cal-title">${esc(e.title)}</span>
                <span class="cal-time tabular">${e.start.slice(11, 16)}–${(e.end || '').slice(11, 16)}</span>
                ${e.location ? `<span class="cal-loc">${esc(e.location)}</span>` : ''}</button>
              <span class="cal-resize" data-resize="${esc(e.key)}" aria-hidden="true"></span></div>`;
          }).join('')}
          ${d === today && nowMin >= lo && nowMin <= hi ? `<div class="cal-now" style="top:${this.y(nowMin)}px" aria-hidden="true"><span class="cal-now-label tabular">${hhmm(nowMin)}</span></div>` : ''}
          ${out(before, 'top')}${out(after, 'bottom')}
        </div>`;
      }).join('');
      const head = days.map((d) => {
        const dt = parse(d);
        return `<button type="button" class="cal-dayhead${d === today ? ' is-today' : ''}" data-goto="${d}" aria-label="Ver el ${esc(fmtDay(dt, { weekday: 'long', day: 'numeric' }))}">
          <span class="cal-dow">${this.view === 'week' ? DOW[(dt.getDay() + 6) % 7] : fmtDay(dt, { weekday: 'short' }).replace('.', '')}</span><span class="cal-dnum tabular">${dt.getDate()}</span></button>`;
      }).join('');
      const alls = days.map((d) => `<div class="cal-allday-cell${isWeekend(d) ? ' is-weekend' : ''}" data-day="${d}" data-allday>${allDay[d].map((e) => this.chip(e)).join('')}</div>`).join('');
      const hours = Array.from({ length: h1 - h0 + 1 }, (_, i) => `<span class="cal-hour tabular${i ? '' : ' is-first'}" style="top:${i * this.hour}px">${h0 + i < 24 && i < h1 - h0 ? hhmm((h0 + i) * 60) : ''}</span>`).join('');
      return `<div class="cal-grid" data-days="${days.length}" style="--days:${days.length};--hour:${this.hour}px;--span:${h1 - h0}">
        <div class="cal-head"><span class="cal-gutter"></span>${head}</div>
        <div class="cal-allday" role="group" aria-label="Todo el día"><span class="cal-gutter"></span>${alls}</div>
        <div class="cal-scroll" tabindex="-1"><div class="cal-hours">${hours}</div><div class="cal-cols">${cols}</div></div>
      </div>`;
    }

    monthHTML() {
      const [a] = this.range();
      const month = this.date.getMonth();
      const today = todayIso();
      const byDay = {};
      // las rutinas se repiten (a menudo cada día): en el mes taparían los eventos; se ven en día, semana y agenda
      this.entries.filter((e) => e.kind !== 'routine').forEach((e) => daysOf(e).forEach((d) => (byDay[d] ||= []).push(e)));
      const narrow = window.matchMedia('(max-width: 767px)').matches;
      let html = `<div class="cal-month"><div class="cal-mhead">${DOW.map((d) => `<span>${d}</span>`).join('')}</div><div class="cal-mgrid">`;
      for (let i = 0; i < 42; i++) {
        const dt = addDays(a, i), d = iso(dt);
        const list = (byDay[d] || []).sort((x, y) => (y.all_day - x.all_day) || x.start.localeCompare(y.start));
        const max = this.compact ? 2 : 3;
        if (narrow) {  // móvil: puntos de color (el texto no cabe); tocar el día lo abre
          html += `<button type="button" class="cal-mcell cal-mcell-dots${dt.getMonth() !== month ? ' is-out' : ''}${d === today ? ' is-today' : ''}${isWeekend(d) ? ' is-weekend' : ''}" data-goto="${d}"
            aria-label="${esc(fmtDay(dt, { weekday: 'long', day: 'numeric', month: 'long' }))}${list.length ? `: ${list.length} ${list.length === 1 ? 'cosa' : 'cosas'}` : ''}">
            <span class="cal-mnum tabular">${dt.getDate()}</span>
            <span class="cal-mdots" aria-hidden="true">${list.slice(0, 4).map((e) => `<i data-kind="${e.kind}" data-type="${esc(e.type)}"${e.done ? ' class="is-done"' : ''}></i>`).join('')}${list.length > 4 ? `<b class="tiny">+${list.length - 4}</b>` : ''}</span></button>`;
          continue;
        }
        html += `<div class="cal-mcell${dt.getMonth() !== month ? ' is-out' : ''}${d === today ? ' is-today' : ''}${isWeekend(d) ? ' is-weekend' : ''}" data-day="${d}" data-allday>
          <button type="button" class="cal-mnum tabular" data-goto="${d}" aria-label="Ver el ${esc(fmtDay(dt, { weekday: 'long', day: 'numeric', month: 'long' }))}">${dt.getDate()}</button>
          ${list.slice(0, max).map((e) => this.chip(e)).join('')}
          ${list.length > max ? `<button type="button" class="cal-more tiny" data-goto="${d}">+${list.length - max} más</button>` : ''}</div>`;
      }
      return html + '</div></div>';
    }

    /* Agenda: los bloques de cada rutina (a menudo una docena al día) van plegados en una línea con su horario y lo
       hecho, en el sitio del primero; se despliegan con un toque. Así los eventos del día no se pierden entre ellos. */
    agendaItems(list) {
      const groups = {};
      list.forEach((e) => { if (e.kind === 'routine' && e.routine_id) (groups[e.routine_id] ||= []).push(e); });
      const shown = new Set();
      return list.map((e) => {
        const g = e.kind === 'routine' && e.routine_id ? groups[e.routine_id] : null;
        if (!g || g.length < 3 || this.compact) return `<li>${this.chip(e)}</li>`;
        if (shown.has(e.routine_id)) return '';
        shown.add(e.routine_id);
        const timed = g.filter((x) => !x.all_day);
        const span = timed.length ? `${timed[0].start.slice(11, 16)}–${(timed[timed.length - 1].end || timed[timed.length - 1].start).slice(11, 16)}` : '';
        const done = g.filter((x) => x.done).length;
        return `<li><details class="cal-agroup" data-kind="routine"><summary>${icon('repeat', 'icon-sm')}
            <span class="cal-agroup-title">${esc(e.routine_title || e.title)}</span>
            <span class="tiny muted tabular">${g.length} bloques${span ? ` · ${span}` : ''} · ${done}/${g.length} hechos</span>
            ${icon('chevron-down', 'icon-sm cal-agroup-chev')}</summary>
          <ul class="cal-alist">${g.map((x) => `<li>${this.chip(x)}</li>`).join('')}</ul></details></li>`;
      }).join('');
    }

    agendaHTML() {
      const [a, b] = this.range();
      const byDay = {};
      this.entries.forEach((e) => (byDay[e.start.slice(0, 10)] ||= []).push(e));
      const out = [];
      let empty = 0;
      const gap = () => { if (empty && !this.compact) out.push(`<p class="cal-agap tiny subtle">${empty === 1 ? 'Un día libre' : `${empty} días libres`}</p>`); empty = 0; };
      for (let d = new Date(a); +d <= +b; d = addDays(d, 1)) {
        const k = iso(d), list = (byDay[k] || []).sort((x, y) => (y.all_day - x.all_day) || x.start.localeCompare(y.start));
        const isToday = k === todayIso();
        if (!list.length && !isToday) { empty++; continue; }
        gap();
        out.push(`<section class="cal-aday${isToday ? ' is-today' : ''}" data-day="${k}">
          <h3 class="cal-ahead"><button type="button" class="cal-adate" data-goto="${k}" aria-label="Ver el ${esc(fmtDay(d, { weekday: 'long', day: 'numeric', month: 'long' }))}">
            <span class="cal-adnum tabular">${d.getDate()}</span><span class="cal-adow">${esc(`${fmtDay(d, { weekday: 'short' })} · ${fmtDay(d, { month: 'short' })}`.replace(/\./g, ''))}</span></button></h3>
          ${list.length ? `<ul class="cal-alist">${this.agendaItems(list)}</ul>` : '<p class="cal-anone tiny subtle">Nada hoy</p>'}</section>`);
      }
      if (out.length) gap();
      return `<div class="cal-agenda">${out.join('') || `<p class="small muted">Nada en los próximos ${this.days} días.</p>`}</div>`;
    }

    entry(key) { return this.entries.find((e) => e.key === key); }

    /* ---------- Escrituras ---------- */
    async save(e, start, end, allDay) {
      try {
        if (e.kind === 'event') {
          await api(`/api/calendar/events/${e.id}`, { method: 'PATCH', body: { start, end, all_day: allDay } });
        } else if (e.kind === 'task') {
          const dur = !allDay && end ? Math.max(15, Math.round((parse(end) - parse(start)) / 60000)) : 0;
          await api(`/api/items/${e.item_id}`, { method: 'PATCH', body: { due_date: start.slice(0, 10), due_time: allDay ? '' : start.slice(11, 16), ...(allDay ? {} : { duration_min: dur }) } });
        } else if (e.kind === 'routine') {
          if (start.slice(0, 10) !== e.day) toast('Una rutina se repite: aquí solo cambia su hora', { type: 'info' });
          const dur = !allDay && end ? Math.max(5, Math.round((parse(end) - parse(start)) / 60000)) : 0;
          await api(`/api/items/${e.item_id}`, { method: 'PATCH', body: { due_time: allDay ? '' : start.slice(11, 16), ...(allDay ? {} : { duration_min: dur }) } });
        }
      } catch { /* api() avisa */ }
      refreshAll();
    }

    async toggle(e) {
      e.done = !e.done;
      this.render();
      try {
        if (e.kind === 'routine') await api(`/api/routines/${e.item_id}/check`, { method: 'POST', body: { day: e.day, done: e.done } });
        else await api(`/api/items/${e.item_id}`, { method: 'PATCH', body: { done: e.done } });
        if (e.done && e.kind === 'routine') toast('Hecha · suma a la racha', { type: 'info', duration: 1600 });
      } catch { e.done = !e.done; }
      refreshAll();
    }

    /* ---------- Gestos ---------- */
    pointToSlot(x, y) {
      const cols = [...this.el.querySelectorAll('.cal-col')];
      const col = cols.find((c) => { const r = c.getBoundingClientRect(); return x >= r.left && x < r.right; }) || null;
      if (!col) return null;
      const r = col.getBoundingClientRect();
      return { day: col.dataset.day, min: snap(Math.max(this.h0 * 60, Math.min(this.h1 * 60 - SNAP, this.minAt(y - r.top)))) };
    }
    pointToDay(x, y) {
      const cell = document.elementsFromPoint(x, y).find((n) => n.matches?.('[data-allday]'));
      return cell?.dataset.day || null;
    }

    onPointerDown(ev) {
      if (ev.button !== 0 || ev.target.closest('[data-cal-check], [data-goto], .cal-out')) return;
      const resize = ev.target.closest('[data-resize]');
      const evEl = ev.target.closest('.cal-ev, .cal-chip');
      const colEl = ev.target.closest('.cal-col');
      const alldayEl = ev.target.closest('[data-allday]');
      if (!resize && !evEl && !colEl && !alldayEl) return;
      const touch = ev.pointerType === 'touch';
      const start = { x: ev.clientX, y: ev.clientY, t: Date.now() };
      let mode = null, timer = null, moved = false, ghost = null;
      const e = evEl || resize ? this.entry((resize || evEl).dataset.key || resize.dataset.resize) : null;
      const begin = () => {
        if (resize) mode = 'resize';
        else if (e) mode = 'move';
        else if (colEl) mode = 'create';
        else mode = 'create-day';
        this.el.classList.add('is-dragging');
        if (touch) navigator.vibrate?.(10);
      };
      if (touch) timer = setTimeout(begin, 380); else begin();
      const slot0 = this.pointToSlot(ev.clientX, ev.clientY);
      const onMove = (m) => {
        const dx = m.clientX - start.x, dy = m.clientY - start.y;
        if (!mode) { if (Math.hypot(dx, dy) > 8) { clearTimeout(timer); cleanup(); } return; }  // con el dedo: desplazamiento normal
        if (Math.hypot(dx, dy) < 4 && !moved) return;
        moved = true;
        m.preventDefault();
        const slot = this.pointToSlot(m.clientX, m.clientY);
        if (mode === 'move' && e && !e.all_day && slot) {
          const dur = (parse(e.end || e.start) - parse(e.start)) / 60000 || 60;
          const grab = minutes(e.start) + 0;
          const off = slot0 ? slot0.min - grab : 0;
          const s = snap(slot.min - off);
          ghost = { start: at(slot.day, s), end: at(slot.day, s + dur), all_day: false };
          this.preview(e, ghost);
        } else if (mode === 'move' && e) {  // chip de todo el día (o de mes): a otro día
          const day = this.pointToDay(m.clientX, m.clientY);
          if (slot && !day) ghost = { start: at(slot.day, slot.min), end: at(slot.day, slot.min + 60), all_day: false };
          else if (day) {
            const shift = (parse(day) - parse(e.start.slice(0, 10))) / DAY_MS;
            ghost = e.all_day ? { start: day, end: e.end ? iso(addDays(parse(e.end), shift)) : null, all_day: true }
              : { start: day + e.start.slice(10), end: e.end ? iso(addDays(parse(e.end), shift)) + e.end.slice(10) : null, all_day: false };
          }
          this.el.querySelectorAll('.is-drop').forEach((n) => n.classList.remove('is-drop'));
          if (day) this.el.querySelector(`[data-allday][data-day="${day}"]`)?.classList.add('is-drop');
        } else if (mode === 'resize' && e && slot) {
          const s = minutes(e.start);
          ghost = { start: e.start, end: at(e.start.slice(0, 10), Math.max(s + SNAP, slot.min + SNAP)), all_day: false };
          this.preview(e, ghost);
        } else if (mode === 'create' && slot0 && slot) {
          const a = Math.min(slot0.min, slot.min), b = Math.max(slot0.min, slot.min) + SNAP;
          ghost = { start: at(slot0.day, a), end: at(slot0.day, b) };
          this.selection(slot0.day, a, b);
        }
      };
      const onUp = (u) => {
        clearTimeout(timer);
        cleanup();
        this.el.classList.remove('is-dragging');
        this.el.querySelectorAll('.is-drop').forEach((n) => n.classList.remove('is-drop'));
        if (!mode) return;
        if (moved && ghost && e && (mode === 'move' || mode === 'resize')) { this.save(e, ghost.start, ghost.end, ghost.all_day); return; }
        if (moved && mode === 'create' && ghost) { this.createAt(ghost.start, ghost.end, false); return; }
        if (!moved && e) { u.preventDefault(); openEditor(e, this); return; }
        if (!moved && mode === 'create' && slot0) { this.createAt(at(slot0.day, slot0.min), at(slot0.day, slot0.min + 60), false); return; }
        if (!moved && mode === 'create-day' && alldayEl) this.createAt(alldayEl.dataset.day, null, true);
      };
      // Con el dedo, tras la pulsación larga el gesto es un arrastre: no se desplaza la página
      const noScroll = (t) => { if (mode) t.preventDefault(); };
      if (touch) window.addEventListener('touchmove', noScroll, { passive: false });
      const cleanup = () => {
        window.removeEventListener('touchmove', noScroll);
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
        window.removeEventListener('pointercancel', onUp);
      };
      window.addEventListener('pointermove', onMove, { passive: false });
      window.addEventListener('pointerup', onUp);
      window.addEventListener('pointercancel', onUp);
      if (!touch) ev.preventDefault();
    }

    preview(e, g) {
      const node = this.el.querySelector(`.cal-ev[data-key="${CSS.escape(e.key)}"]`);
      const col = this.el.querySelector(`.cal-col[data-day="${g.start.slice(0, 10)}"]`);
      if (!node || !col) return;
      if (node.parentElement !== col) col.appendChild(node);
      node.style.top = `${this.y(minutes(g.start))}px`;
      node.style.height = `${Math.max(18, (minutes(g.end) - minutes(g.start)) / 60 * this.hour - 2)}px`;
      node.style.left = '2px';
      node.style.width = 'calc(100% - 4px)';
      node.querySelector('.cal-time').textContent = `${g.start.slice(11, 16)}–${g.end.slice(11, 16)}`;
      node.classList.add('is-moving');
    }

    selection(day, a, b) {
      this.el.querySelector('.cal-sel')?.remove();
      const col = this.el.querySelector(`.cal-col[data-day="${day}"]`);
      col?.insertAdjacentHTML('beforeend', `<div class="cal-sel" style="top:${this.y(a)}px;height:${(b - a) / 60 * this.hour}px"><span class="tabular">${hhmm(a)}–${hhmm(b)}</span></div>`);
    }

    // Crear en línea: un campo de título donde se ha hecho clic o se ha arrastrado
    createAt(start, end, allDay) {
      this.el.querySelector('.cal-inline')?.remove();
      const host = allDay ? this.el.querySelector(`[data-allday][data-day="${start.slice(0, 10)}"]`)
        : this.el.querySelector(`.cal-col[data-day="${start.slice(0, 10)}"]`);
      if (!host) return;
      const top = allDay ? '' : `style="top:${this.y(minutes(start))}px;min-height:${Math.max(30, (minutes(end) - minutes(start)) / 60 * this.hour)}px"`;
      host.insertAdjacentHTML('beforeend', `<form class="cal-inline${allDay ? ' is-allday' : ''}" ${top}>
        <label class="sr-only" for="calNew">Título del evento</label>
        <input id="calNew" class="input input-sm" maxlength="300" placeholder="${allDay ? 'Evento de todo el día' : `Nuevo ${start.slice(11, 16)}–${end.slice(11, 16)}`}" autocomplete="off">
        <span class="tiny subtle">Enter crea · Esc cancela · <button type="button" class="link-btn" data-more>Más…</button></span></form>`);
      const form = host.querySelector('.cal-inline'), input = form.querySelector('input');
      input.focus();
      const close = () => { form.remove(); this.el.querySelector('.cal-sel')?.remove(); };
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const title = input.value.trim();
        if (!title) { close(); return; }
        input.disabled = true;
        try { await api('/api/calendar/events', { method: 'POST', body: { title, start, end, all_day: allDay } }); } catch { input.disabled = false; return; }
        close();
        refreshAll();
      });
      form.querySelector('[data-more]').addEventListener('click', () => { close(); openEditor({ kind: 'event', title: input.value, start, end, all_day: allDay, type: 'evento', isNew: true }, this); });
      input.addEventListener('keydown', (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } });
      input.addEventListener('blur', () => setTimeout(() => { if (document.activeElement !== input && !input.value.trim() && form.isConnected) close(); }, 150));
    }

    /* Soltar una tarea o idea (arrastrada desde una lista) → bloque de tiempo enlazado */
    onDragOver(ev) {
      if (!dragItem) return;
      ev.preventDefault();
      ev.dataTransfer.dropEffect = 'move';
      const slot = this.pointToSlot(ev.clientX, ev.clientY);
      const day = slot ? null : this.pointToDay(ev.clientX, ev.clientY);
      this.el.querySelectorAll('.is-drop').forEach((n) => n.classList.remove('is-drop'));
      if (slot) this.selection(slot.day, slot.min, slot.min + 60);
      else if (day) this.el.querySelector(`[data-allday][data-day="${day}"]`)?.classList.add('is-drop');
    }
    async onDrop(ev) {
      if (!dragItem) return;
      ev.preventDefault();
      const id = dragItem;
      dragItem = null;
      this.el.querySelector('.cal-sel')?.remove();
      this.el.querySelectorAll('.is-drop').forEach((n) => n.classList.remove('is-drop'));
      const slot = this.pointToSlot(ev.clientX, ev.clientY);
      const day = slot ? slot.day : this.pointToDay(ev.clientX, ev.clientY);
      if (!day) return;
      await scheduleItem(id, day, slot ? hhmm(slot.min) : '', 60);
    }

    onClick(ev) {
      const check = ev.target.closest('[data-cal-check]');
      if (check) { ev.preventDefault(); ev.stopPropagation(); const e = this.entry(check.dataset.calCheck); if (e) this.toggle(e); return; }
      const go = ev.target.closest('[data-goto]');
      if (go && !this.compact) { this.date = parse(go.dataset.goto); this.view = 'day'; this.load(); return; }
      if (go && this.compact) { location.href = `/calendario?dia=${go.dataset.goto}`; return; }
      const outside = ev.target.closest('.cal-out');  // aviso «fuera del horario»: abre lo que tapa
      if (outside) { const e = this.entry(outside.dataset.key); if (e) openEditor(e, this); return; }
      const chip = ev.target.closest('.cal-chip, .cal-ev-main');
      if (chip && ev.detail === 0) { const e = this.entry(chip.dataset.key); if (e) openEditor(e, this); }  // teclado (Enter/Espacio)
    }

    onKey(ev) {
      const t = ev.target;
      if (/^(input|textarea|select)$/i.test(t.tagName) || t.isContentEditable || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (ev.key === ' ' && t.closest('.cal-chip, .cal-ev-main')) {
        const e = this.entry(t.closest('[data-key]').dataset.key);
        if (e && e.kind !== 'event') { ev.preventDefault(); this.toggle(e); }
      }
    }
  }

  function isWeekend(day) { const g = parse(day).getDay(); return g === 0 || g === 6; }

  // Columnas para entradas que se solapan en un día
  function layout(list) {
    const items = [...list].sort((a, b) => a.start.localeCompare(b.start) || (b.end || '').localeCompare(a.end || ''));
    const out = [];
    let group = [], groupEnd = '';
    const flush = () => {
      const cols = [];
      group.forEach((g) => {
        let c = cols.findIndex((endAt) => endAt <= g.e.start);
        if (c < 0) { c = cols.length; cols.push(''); }
        cols[c] = g.e.end || g.e.start;
        g.col = c;
      });
      group.forEach((g) => { g.cols = cols.length; out.push(g); });
      group = [];
    };
    items.forEach((e) => {
      if (group.length && e.start >= groupEnd) flush();
      group.push({ e });
      groupEnd = [groupEnd, e.end || e.start].sort().pop();
    });
    if (group.length) flush();
    return out;
  }

  function refreshAll() {
    instances.forEach((c) => { if (c.el.isConnected) c.load(); else instances.delete(c); });
    if (window.Items?.state?.loaded) Items.load();
  }
  // Cambios hechos en otra pestaña (o en la lista de tareas de esta página)
  onDataChange(/^\/api\/(calendar|items|routines|inbox)/, refreshAll);

  /* ---------- Programar una tarea (bloque de tiempo) ---------- */
  async function scheduleItem(id, day, time, dur = 60) {
    const it = window.Items?.get(id);
    try {
      await api(`/api/items/${id}`, { method: 'PATCH', body: { due_date: day, due_time: time, ...(time ? { duration_min: dur } : {}) } });
      toast(time ? `Bloque de ${dur} min el ${fmtDay(parse(day), { weekday: 'long', day: 'numeric' })} a las ${time}` : 'Con fecha', { type: 'info', duration: 2200 });
    } catch { return; }
    refreshAll();
    return it;
  }
  document.addEventListener('dragstart', (e) => {
    const src = e.target.closest?.('[data-cal-drag-item]');
    if (!src) return;
    dragItem = Number(src.dataset.calDragItem);
    e.dataTransfer.setData('text/plain', src.textContent.trim());
    e.dataTransfer.effectAllowed = 'move';
  });
  document.addEventListener('dragend', () => { dragItem = null; document.querySelectorAll('.cal-sel').forEach((n) => n.remove()); });

  /* ---------- Editor (diálogo) ---------- */
  function openEditor(e, cal) {
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm cal-editor';
    const isEvent = e.kind === 'event';
    const day = e.start.slice(0, 10), t0 = e.all_day ? '09:00' : e.start.slice(11, 16), t1 = e.all_day ? '10:00' : (e.end || '').slice(11, 16) || '10:00';
    // Todo el día: el fin guardado es exclusivo; en el formulario se muestra el último día
    const lastDay = e.all_day && e.end && e.end.length === 10 && e.end > day ? iso(addDays(parse(e.end), -1)) : day;
    const what = isEvent ? (e.isNew ? 'Nuevo evento' : 'Evento') : e.kind === 'routine' ? 'Rutina' : e.type === 'idea' ? 'Idea' : 'Tarea';
    dlg.innerHTML = `<div class="modal-header"><h2>${what}</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body stack form-pro" id="calEdForm">
        ${isEvent ? `<label class="sr-only" for="calEdTitle">Título</label><input id="calEdTitle" name="title" class="input form-title" maxlength="300" required placeholder="Título" value="${esc(e.title || '')}">
          <div class="choice-chips" role="radiogroup" aria-label="Tipo">${Object.entries(KIND_LABEL).map(([k, l]) => `<label class="choice-chip" data-kind="event" data-type="${k}">
            <input type="radio" name="kind" value="${k}" ${(e.type || 'evento') === k ? 'checked' : ''}><span><i class="choice-dot" aria-hidden="true"></i>${l}</span></label>`).join('')}</div>`
          : `<p class="cal-ed-title">${e.routine_title ? `<span class="tiny muted">${esc(e.routine_title)} ›</span> ` : ''}<b>${esc(e.title)}</b>${e.repeat_text ? `<span class="tiny muted"> · ${esc(e.repeat_text)}</span>` : ''}</p>`}
        <div class="form-row"><span class="form-row-ico" aria-hidden="true">${icon('clock', 'icon-sm')}</span>
          <div class="form-row-body stack-sm">
            <div class="form-line">
              <label class="sr-only" for="calEdDay">${e.kind === 'routine' ? 'Día (solo este)' : 'Día'}</label>
              <input id="calEdDay" name="day" type="date" class="input input-sm" value="${day}" ${e.kind === 'routine' ? 'disabled' : ''}>
              <span class="grow"></span>
              <label class="switch-row tiny"><input type="checkbox" class="switch" name="all_day" ${e.all_day ? 'checked' : ''}><span>Todo el día</span></label>
            </div>
            <div class="form-line" data-timed>
              <label class="sr-only" for="calEdT0">Empieza</label><input id="calEdT0" name="t0" type="time" class="input input-sm" step="300" value="${t0}">
              <span class="muted" aria-hidden="true">→</span>
              <label class="sr-only" for="calEdT1">Termina</label><input id="calEdT1" name="t1" type="time" class="input input-sm" step="300" value="${t1}">
              <span class="tiny muted tabular form-dur" data-dur-live aria-live="polite"></span>
            </div>
            <div class="chips" data-timed role="group" aria-label="Duración">
              ${[[15, '15 min'], [30, '30 min'], [60, '1 h'], [90, '1 h 30'], [120, '2 h'], [180, '3 h']].map(([m, l]) => `<button type="button" class="chip chip-sm" data-dur="${m}">${l}</button>`).join('')}
            </div>
            ${isEvent ? `<div class="form-line" data-allday-only><label class="tiny muted" for="calEdDayEnd">Hasta el</label><input id="calEdDayEnd" name="day_end" type="date" class="input input-sm" value="${lastDay}"></div>` : ''}
          </div></div>
        ${isEvent ? `<div class="form-row"><span class="form-row-ico" aria-hidden="true">${icon('map-pin', 'icon-sm')}</span>
          <div class="form-row-body"><label class="sr-only" for="calEdLoc">Lugar</label><input id="calEdLoc" name="location" class="input input-sm" maxlength="300" value="${esc(e.location || '')}" placeholder="Lugar (opcional)" autocomplete="off"></div></div>` : ''}
        <div class="form-row"><span class="form-row-ico" aria-hidden="true">${icon('bell', 'icon-sm')}</span>
          <div class="form-row-body"><div class="choice-chips choice-chips-sm" role="radiogroup" aria-label="Aviso">
            ${[[-1, 'Según su tipo'], [0, 'A la hora'], [15, '15 min antes'], [60, '1 h antes'], [1440, '1 día antes']]
              .map(([v, l]) => `<label class="choice-chip"><input type="radio" name="reminder" value="${v}" ${(e.reminder_min ?? -1) === v || (v === -1 && ![0, 15, 60, 1440].includes(e.reminder_min ?? -1)) ? 'checked' : ''}><span>${l}</span></label>`).join('')}
          </div></div></div>
        ${isEvent ? `<details class="form-details" ${e.notes ? 'open' : ''}><summary>${icon('file-text', 'icon-sm')}Notas</summary>
          <label class="sr-only" for="calEdNotes">Notas</label><textarea id="calEdNotes" name="notes" class="textarea" rows="3" maxlength="20000">${esc(e.notes || '')}</textarea></details>` : ''}
        ${e.source && e.source !== 'panel' ? `<p class="tiny muted">${icon('refresh-cw', 'icon-sm')} Llegó desde ${e.source === 'icloud' ? 'iCloud' : 'el ESP32'}; los cambios se sincronizan.</p>` : ''}
      </form>
      <div class="modal-footer">
        ${!e.isNew && isEvent ? `<button type="button" class="btn btn-danger" data-del>${icon('trash-2', 'icon-sm')}Borrar</button>
          <button type="button" class="btn btn-ghost btn-icon" data-dup aria-label="Duplicar" title="Duplicar (crea una copia; puedes cambiarle el día)">${icon('copy', 'icon-sm')}</button>` : ''}
        ${!isEvent ? `<a class="btn" href="${e.step ? `/rutinas?dia=${e.day}` : `/tareas?item=${e.item_id}`}">${icon('external-link', 'icon-sm')}Abrir</a>
          <button type="button" class="btn" data-check>${icon(e.done ? 'rotate-ccw' : 'check', 'icon-sm')}${e.done ? 'Desmarcar' : 'Hecha'}</button>` : ''}
        <span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button>
        <button type="submit" form="calEdForm" class="btn btn-primary">${e.isNew ? 'Crear' : 'Guardar'}</button>
      </div>`;
    document.body.appendChild(dlg);
    wireAllDialogs?.();
    const f = dlg.querySelector('form');
    const syncTimed = () => {
      dlg.querySelectorAll('[data-timed]').forEach((n) => { n.hidden = f.all_day.checked; });
      dlg.querySelectorAll('[data-allday-only]').forEach((n) => { n.hidden = !f.all_day.checked; });
    };
    f.all_day.addEventListener('change', syncTimed);
    syncTimed();
    // Cambiar el inicio mueve también el fin (se conserva la duración); los botones fijan la duración
    const toMin = (v) => (v ? Number(v.slice(0, 2)) * 60 + Number(v.slice(3, 5)) : 0);
    let dur = Math.max(15, toMin(t1) - toMin(t0)) || 60;
    const live = dlg.querySelector('[data-dur-live]');
    const fmtDur = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ''}` : `${m} min`);
    const paintDur = () => {
      const d = toMin(f.t1.value) - toMin(f.t0.value);
      live.textContent = d > 0 ? fmtDur(d) : '';
      dlg.querySelectorAll('[data-dur]').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.dur) === d)));
    };
    f.t0.addEventListener('change', () => { if (f.t0.value) f.t1.value = hhmm(Math.min(1439, toMin(f.t0.value) + dur)); paintDur(); });
    f.t1.addEventListener('change', () => { const d = toMin(f.t1.value) - toMin(f.t0.value); if (d > 0) dur = d; paintDur(); });
    dlg.querySelectorAll('[data-dur]').forEach((b) => b.addEventListener('click', () => {
      dur = Number(b.dataset.dur);
      f.t1.value = hhmm(Math.min(1439, toMin(f.t0.value || '09:00') + dur));
      paintDur();
    }));
    paintDur();
    // Ctrl+Intro guarda desde cualquier campo (también desde las notas)
    f.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); f.requestSubmit(); } });
    if (f.day_end) f.day.addEventListener('change', () => { if (f.day_end.value < f.day.value) f.day_end.value = f.day.value; });
    f.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const allDay = f.all_day.checked;
      const d = e.kind === 'routine' ? day : f.day.value;
      const start = allDay ? d : `${d}T${f.t0.value || '09:00'}`;
      let end = allDay ? (f.day_end && f.day_end.value > d ? iso(addDays(parse(f.day_end.value), 1)) : null) : `${d}T${f.t1.value || f.t0.value}`;
      if (!allDay && end <= start) end = at(d, minutes(start) + 60);
      const reminder = Number(f.reminder.value);
      try {
        if (isEvent) {
          const body = { title: f.title.value.trim(), start, end, all_day: allDay, kind: f.kind.value, notes: f.notes.value, location: f.location.value.trim(), reminder_min: reminder };
          if (e.isNew) await api('/api/calendar/events', { method: 'POST', body: { ...body, reminder_min: reminder < 0 ? null : reminder } });
          else await api(`/api/calendar/events/${e.id}`, { method: 'PATCH', body: { ...body, end: body.end ?? '' } });  // '' = fin por defecto
        } else {
          await cal.save(e, start, end, allDay);
          await api(`/api/items/${e.item_id}`, { method: 'PATCH', body: { reminder_min: reminder }, quiet: true });
        }
      } catch { return; }
      closeModal(dlg);
      refreshAll();
    });
    dlg.querySelector('[data-del]')?.addEventListener('click', async () => {
      const r = await api(`/api/calendar/events/${e.id}`, { method: 'DELETE' });
      closeModal(dlg);
      refreshAll();
      toast('Evento en la papelera', { action: { label: 'Deshacer', onClick: async () => { await api(`/api/trash/brain/${r.trash}/restore`, { method: 'POST' }); refreshAll(); } } });
    });
    dlg.querySelector('[data-dup]')?.addEventListener('click', () => {
      closeModal(dlg);
      openEditor({ ...e, id: null, key: null, uid: null, source: 'panel', isNew: true, title: f.title.value }, cal);
    });
    dlg.querySelector('[data-check]')?.addEventListener('click', () => { closeModal(dlg); cal.toggle(e); });
    openModal(dlg, { focus: isEvent ? 'input[name=title]' : 'input[name=t0]', onClose: () => dlg.remove() });
  }

  /* ---------- Bloques de código ```calendario en las notas ---------- */
  // ```calendario
  // vista: semana | mes | agenda | día
  // días: 7
  // ```
  function mountEmbeds(root) {
    root.querySelectorAll('pre > code.language-calendario, pre > code.lang-calendario').forEach((code) => {
      const pre = code.parentElement;
      const conf = Object.fromEntries(code.textContent.split('\n').map((l) => l.split(':').map((x) => x.trim().toLowerCase())).filter((p) => p.length === 2));
      const view = { semana: 'week', mes: 'month', agenda: 'agenda', dia: 'day', día: 'day' }[conf.vista] || 'agenda';
      const host = document.createElement('div');
      host.className = 'cal-embed';
      host.innerHTML = `<div class="cal-embed-head">${icon('calendar', 'icon-sm')}<span class="grow">Calendario</span><a class="tiny" href="/calendario">Abrir</a></div><div></div>`;
      pre.replaceWith(host);
      new Cal(host.lastElementChild, { view, compact: true, days: Math.max(1, Math.min(31, parseInt(conf['días'] || conf.dias || '7', 10) || 7)) });
    });
  }

  // Horario visible: se guarda y repinta todos los calendarios de la página
  function setHourSize(size) {
    window.Prefs?.set(SIZE_KEY, size);
    instances.forEach((c) => { if (c.el.isConnected && !c.compact) c.render(); });
  }
  function setShowRoutines(on) {
    window.Prefs?.set(ROUTINES_KEY, on);
    refreshAll();
  }
  function setHours(start, end) {
    window.Prefs?.set(HOURS_KEY, { start, end });
    instances.forEach((c) => { if (c.el.isConnected) { c.hour = HOUR; c.render(); } });
  }
  // Al cambiar el tamaño de la ventana, la altura de las horas se vuelve a calcular
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => instances.forEach((c) => { if (c.el.isConnected && !c.compact && c.view !== 'month' && c.view !== 'agenda') c.render(); }), 200);
  });
  document.addEventListener('prefs:changed', () => instances.forEach((c) => { if (c.el.isConnected && c.view !== 'month' && c.view !== 'agenda') c.render(); }));

  window.Calendar = {
    mount: (el, opts) => new Cal(el, opts), mountEmbeds, refreshAll, scheduleItem, openEditor,
    VIEW_LABEL, iso, parse, addDays, hours: hoursPref, setHours, setHourSize, setShowRoutines,
    get hourSize() { return window.Prefs?.get(SIZE_KEY, 'normal') || 'normal'; },
    get showRoutines() { return window.Prefs?.get(ROUTINES_KEY, true) !== false; },
  };
})();
