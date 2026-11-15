/* ==========================================================================
   palette.js — paleta de comandos (Ctrl+K) y atajos «G + letra» (window.Palette)
   Busca de forma aproximada (fuzzyScore, ui.js) en notas, tareas, ideas, rutinas,
   eventos cercanos, platos y acciones; cada acción muestra su atajo. Con 2 letras o más,
   añade lo que sale «Dentro del texto» (índice único de /api/search: notas, tareas, Baúl, eventos). Flechas para
   moverse, Intro abre, Esc cierra. El índice (/api/palette/index) se pide al abrir
   y se guarda 2 minutos.
   ========================================================================== */
(function () {
  'use strict';

  const kbd = (s) => s.split(' ').map((k) => `<kbd>${escapeHtml(k)}</kbd>`).join(' ');
  const go = (url) => () => { location.href = url; };
  const newCapture = (type, prefix = '') => () => {
    const form = document.getElementById('captureForm');
    form?.setType?.(type);
    openCapture();
    const ta = form?.querySelector('[data-capture-text]');
    if (ta && prefix) { ta.value = prefix; ta.setSelectionRange(prefix.length, prefix.length); }
  };
  const ACTIONS = [
    { label: 'Nueva nota', icon: 'file-plus', keys: 'G N', run: go('/?nueva=1'), words: 'crear escribir' },
    { label: 'Nueva tarea', icon: 'square-check', keys: 'C', run: newCapture('tarea'), words: 'crear añadir todo' },
    { label: 'Nueva idea', icon: 'lightbulb', run: newCapture('idea'), words: 'crear añadir' },
    { label: 'Nueva rutina', icon: 'repeat', run: newCapture('rutina'), words: 'hábito crear repetir' },
    { label: 'Nuevo evento (lenguaje natural)', icon: 'calendar-plus', run: newCapture('tarea', 'e: '), words: 'cita calendario crear' },
    { label: 'Empezar contador…', icon: 'timer', run: () => window.Timer?.pick(), words: 'cronómetro tiempo empezar actividad libre estudiar' },
    { label: 'Captura rápida', icon: 'plus', keys: 'C', run: () => openCapture(), words: 'inbox apuntar' },
    { label: 'Ir a Hoy', icon: 'sun', keys: 'G H', run: go('/hoy'), words: 'inicio resumen' },
    { label: 'Ir a Calendario', icon: 'calendar', keys: 'G C', run: go('/calendario'), words: 'agenda semana mes' },
    { label: 'Ir a Notas', icon: 'notebook-pen', keys: 'G O', run: go('/'), words: 'cerebro' },
    { label: 'Ir a Inbox', icon: 'inbox', keys: 'G I', run: go('/inbox'), words: 'tablero' },
    { label: 'Ir a Tareas', icon: 'list-todo', keys: 'G T', run: go('/tareas'), words: 'ideas rutinas' },
    { label: 'Ir a Universidad', icon: 'school', keys: 'G A', run: go('/universidad'), words: 'asignaturas temas clases exámenes entregas' },
    { label: 'Ir a Proyectos', icon: 'rocket', keys: 'G P', run: go('/proyectos'), words: 'versiones bitácora' },
    ...['puntual', 'universidad', 'proyectos', 'todo'].map((c) => ({ label: `Contexto: ${{ puntual: 'Puntual', universidad: 'Universidad', proyectos: 'Proyectos', todo: 'Todo' }[c]}`,
      icon: { puntual: 'zap', universidad: 'school', proyectos: 'rocket', todo: 'layers' }[c], run: () => window.Ctx?.set(c), words: 'cambiar filtro ver' })),
    { label: 'Ir a Comidas', icon: 'utensils-crossed', keys: 'G M', run: go('/comidas/'), words: 'menú plan compra' },
    { label: 'Ir a Estudio', icon: 'graduation-cap', keys: 'G E', run: go('/estudio/'), words: 'esp32 pomodoro' },
    { label: 'Revisión semanal', icon: 'clipboard-check', keys: 'G R', run: go('/revision'), words: 'registro cambios completadas' },
    { label: 'Repasar flashcards', icon: 'layers', run: go('/repaso'), words: 'repaso' },
    { label: 'Buscar en todo', icon: 'search', keys: '/', run: go('/buscar'), words: 'texto completo notas tareas baúl eventos' },
    { label: 'Papelera', icon: 'trash-2', run: go('/papelera'), words: 'borrado restaurar' },
    { label: 'Copias de seguridad', icon: 'database-backup', run: go('/backups'), words: 'backup' },
    { label: 'Estado de las conexiones', icon: 'plug-zap', run: () => window.Status?.open(), words: 'esp32 icloud sincronizar' },
    { label: 'Avisos y recordatorios', icon: 'bell', run: () => window.Reminders?.openSettings(), words: 'notificaciones' },
    { label: 'Plegar o desplegar el menú', icon: 'panel-left', keys: 'Ctrl .', run: () => document.querySelector('[data-nav-toggle]')?.click(), words: 'barra lateral' },
  ];
  const ITEM_ICON = { tarea: 'square-check', idea: 'lightbulb', rutina: 'repeat' };

  let index = null, indexAt = 0;
  async function loadIndex() {
    if (index && Date.now() - indexAt < 120000) return index;
    index = await api('/api/palette/index', { quiet: true });
    indexAt = Date.now();
    return index;
  }

  function candidates(idx) {
    const out = ACTIONS.map((a) => ({ group: 'Acciones', label: a.label, sub: a.words, icon: a.icon, keys: a.keys, run: a.run, boost: 6 }));
    if (!idx) return out;
    idx.notes.forEach((n) => out.push({ group: 'Notas', label: n.title, sub: n.category, icon: 'notebook-pen', href: `/?note=${encodeURIComponent(n.id)}`, run: go(`/?note=${encodeURIComponent(n.id)}`) }));
    // Tareas: las del contexto activo (con «Todo», todas); lo demás no se filtra
    idx.items.filter((i) => !window.Ctx || Ctx.match(i)).forEach((i) => out.push({ group: { tarea: 'Tareas', idea: 'Ideas', rutina: 'Rutinas' }[i.type] || 'Tareas', label: i.text,
      sub: i.done ? 'hecha' : i.origin === 'nota' ? 'en una nota' : '', icon: ITEM_ICON[i.type] || 'square-check', href: `/tareas?item=${i.id}`, run: go(`/tareas?item=${i.id}`), penalty: i.done ? 4 : 0 }));
    idx.events.forEach((e) => out.push({ group: 'Eventos', label: e.title,
      sub: new Date(e.start.slice(0, 10) + 'T00:00').toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' }) + (e.start.length > 10 ? ` · ${e.start.slice(11, 16)}` : ''),
      icon: 'calendar', href: `/calendario?dia=${e.start.slice(0, 10)}`, run: go(`/calendario?dia=${e.start.slice(0, 10)}`) }));
    (idx.asignaturas || []).forEach((a) => {
      out.push({ group: 'Universidad', label: `${a.codigo} · ${a.nombre}`, sub: 'asignatura', icon: 'school', run: go(`/universidad?asignatura=${a.id}`) });
      if (a.carpeta) out.push({ group: 'Abrir carpeta', label: `Abrir la carpeta de ${a.codigo}`, sub: a.nombre, icon: 'folder-open', run: () => Ctx.openFolder('asignatura', a.id) });
    });
    (idx.temas || []).forEach((t) => {
      if (t.abrible) out.push({ group: 'Abrir tema', label: `${t.codigo} · ${t.titulo}`, sub: 'abrir el archivo o la carpeta', icon: 'folder-open', run: () => Ctx.openFolder('tema', t.id), penalty: 1 });
      else out.push({ group: 'Universidad', label: `${t.codigo} · ${t.titulo}`, sub: 'tema', icon: 'book-open', run: go(`/universidad?asignatura=${t.asignatura_id}`), penalty: 1 });
    });
    (idx.proyectos || []).forEach((p) => {
      out.push({ group: 'Proyectos', label: p.nombre, sub: `#${p.slug}`, icon: 'rocket', run: go(`/proyectos/${encodeURIComponent(p.slug)}`) });
      if (p.carpeta) out.push({ group: 'Abrir carpeta', label: `Abrir la carpeta de ${p.nombre}`, sub: `#${p.slug}`, icon: 'folder-open', run: () => Ctx.openFolder('proyecto', p.id) });
    });
    idx.meals.forEach((m) => out.push({ group: 'Platos', label: m.nombre, sub: m.franja, icon: 'utensils-crossed', run: go('/comidas/') }));
    return out;
  }

  /* Texto completo (F-3): lo que no sale por el título, sacado del índice único (/api/search) */
  const FTS_GROUPS = [['notes', 'notebook-pen'], ['items', null], ['resources', null], ['events', 'calendar']];
  const FTS_MAX = 6;
  let fts = { q: '', rows: [] }, ftsTimer = null, ftsSeq = 0;
  const marked = (t, [o, c]) => escapeHtml(String(t || '').replace(/[#*_`>|~]+/g, ' ').replace(/\s+/g, ' ').trim()).split(o).join('<mark>').split(c).join('</mark>');
  function ftsRows(data) {
    const m = data.marks || ['\u0002', '\u0003'];
    const rows = [];
    FTS_GROUPS.map(([k]) => k).forEach((k) => (data[k] || []).forEach((x) => {
      const ic = FTS_GROUPS.find(([g]) => g === k)[1] || (k === 'items' ? ITEM_ICON[x.type] || 'square-check' : x.resource_type === 'youtube' ? 'youtube' : 'globe');
      const label = k === 'items' ? x.text : x.title || x.url || '';
      const snip = x.snippet && x.snippet.includes(m[0]) ? x.snippet : '';
      rows.push({ group: 'Dentro del texto', label, icon: ic, href: x.href, run: go(x.href),
        subHtml: snip ? marked(snip, m) : escapeHtml({ notes: x.category, items: x.done ? 'hecha' : '', resources: x.channel || x.category, events: (x.start || '').slice(0, 10) }[k] || '') });
    }));
    return rows;
  }
  function fetchFts(q, repaint) {
    clearTimeout(ftsTimer);
    const t = q.trim();
    if (t.length < 2) { fts = { q: t, rows: [] }; return; }
    if (fts.q === t) return;
    const my = ++ftsSeq;
    ftsTimer = setTimeout(async () => {
      const ctx = window.Ctx?.active() || 'todo';
      const data = await api(`/api/search?${new URLSearchParams({ q: t, limit: 4, contexto: ctx })}`, { quiet: true }).catch(() => null);
      if (my !== ftsSeq || !data) return;
      fts = { q: t, rows: ftsRows(data) };
      repaint();
    }, 180);
  }

  function search(all, q) {
    if (!q.trim()) return all.filter((c) => c.group === 'Acciones');
    const found = all.map((c) => ({ c, s: Math.max(fuzzyScore(q, c.label) * 1.2, fuzzyScore(q, c.sub || '') * 0.5) + (c.boost || 0) - (c.penalty || 0) }))
      .filter((r) => r.s > (r.c.boost || 0) - (r.c.penalty || 0)).sort((a, b) => b.s - a.s).slice(0, 60).map((r) => r.c);
    const seen = new Set(found.slice(0, 12).map((c) => c.href).filter(Boolean));
    const inText = fts.q === q.trim() ? fts.rows.filter((r) => !seen.has(r.href)).slice(0, FTS_MAX) : [];
    // Siempre, al final: la búsqueda completa en /buscar (agrupada por tipo, con filtros)
    return [...found.slice(0, 12), ...inText, ...found.slice(12), { group: 'Texto completo', label: `Ver todos los resultados de «${q.trim()}»`, icon: 'file-search',
      run: go(`/buscar?q=${encodeURIComponent(q.trim())}`) }];
  }

  let dlg = null;
  function open() {
    if (dlg?.open) { dlg.querySelector('input').select(); return; }
    dlg = document.createElement('dialog');
    dlg.className = 'modal palette';
    dlg.setAttribute('aria-label', 'Paleta de comandos');
    dlg.innerHTML = `<div class="palette-search">${icon('search')}
        <label class="sr-only" for="paletteInput">Buscar notas, tareas, eventos, platos o acciones</label>
        <input id="paletteInput" class="palette-input" type="search" autocomplete="off" spellcheck="false" placeholder="Busca una nota, tarea, evento, plato o acción…"
          role="combobox" aria-expanded="true" aria-controls="paletteList" aria-autocomplete="list">
        <kbd class="hide-mobile">Esc</kbd></div>
      <ul class="palette-list" id="paletteList" role="listbox" aria-label="Resultados"></ul>
      <div class="palette-foot tiny subtle hide-mobile">${kbd('↑ ↓')} moverse · ${kbd('Intro')} abrir · ${kbd('Esc')} cerrar · ${kbd('G')} + letra para ir a una sección</div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    const input = dlg.querySelector('input'), list = dlg.querySelector('ul');
    let all = candidates(null), shown = [], active = 0;
    const paint = () => {
      shown = search(all, input.value);
      active = Math.min(active, Math.max(0, shown.length - 1));
      let last = '';
      list.innerHTML = shown.length ? shown.map((c, i) => {
        const head = c.group !== last ? `<li class="palette-group" role="presentation">${escapeHtml(c.group)}</li>` : '';
        last = c.group;
        return `${head}<li role="option" id="pal-${i}" class="palette-row" data-i="${i}" aria-selected="${i === active}">
          <span class="palette-icon" aria-hidden="true">${icon(c.icon, 'icon-sm')}</span>
          <span class="row-main"><span class="row-title">${escapeHtml(c.label)}</span>${c.subHtml ? `<span class="row-sub">${c.subHtml}</span>` : c.sub && c.group !== 'Acciones' ? `<span class="row-sub">${escapeHtml(c.sub)}</span>` : ''}</span>
          ${c.keys ? `<span class="palette-keys">${kbd(c.keys)}</span>` : ''}</li>`;
      }).join('') : `<li class="palette-empty small muted">Nada coincide con «${escapeHtml(input.value)}»</li>`;
      input.setAttribute('aria-activedescendant', shown.length ? `pal-${active}` : '');
      list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    };
    const run = (i) => { const c = shown[i]; if (!c) return; closeModal(dlg); setTimeout(() => c.run(), 0); };
    input.addEventListener('input', () => { active = 0; paint(); fetchFts(input.value, () => { if (dlg) paint(); }); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (shown.length) { active = (active + (e.key === 'ArrowDown' ? 1 : -1) + shown.length) % shown.length; paint(); }
      } else if (e.key === 'Enter') { e.preventDefault(); run(active); }
    });
    list.addEventListener('click', (e) => { const r = e.target.closest('[data-i]'); if (r) run(Number(r.dataset.i)); });
    list.addEventListener('mousemove', (e) => { const r = e.target.closest('[data-i]'); if (r && Number(r.dataset.i) !== active) { active = Number(r.dataset.i); paint(); } });
    openModal(dlg, { focus: 'input', onClose: () => { dlg.remove(); dlg = null; } });
    paint();
    loadIndex().then((idx) => { all = candidates(idx); if (dlg) paint(); }).catch(() => {});
  }

  /* ---------- Atajos: Ctrl+K (paleta) y «G + letra» ---------- */
  const GOTO = { h: '/hoy', c: '/calendario', u: '/rutinas', o: '/', i: '/inbox', t: '/tareas', a: '/universidad', p: '/proyectos', m: '/comidas/', d: '/economia', b: '/vault',
    e: '/estudio/', r: '/revision', n: '/?nueva=1' };

  /* ---------- «?»: ayuda de atajos (los de siempre y los de la página) ---------- */
  const k = (...keys) => keys.map((x) => `<kbd>${x}</kbd>`).join(' ');
  const LIST_KEYS = [[k('Intro'), 'Editar la tarjeta con el foco'], [k('E'), 'Añadir un paso (con el ratón encima)'],
    [k('X'), 'Seleccionar'], [`${k('Alt')} + flechas`, 'Mover, meter como paso o sacar']];
  const PAGE_KEYS = {
    'page-calendario': ['Calendario', [[`${k('←')} ${k('→')}`, 'Anterior / siguiente'], [k('T'), 'Volver a hoy'],
      [`${k('D')} ${k('3')} ${k('S')} ${k('M')} ${k('A')}`, 'Día, 3 días, semana, mes, agenda'], [k('N'), 'Nuevo evento escribiendo'],
      [`${k('Ctrl')} ${k('Intro')}`, 'Guardar en el editor']]],
    'page-tareas': ['Tareas', [[k('R'), 'Cambiar entre lista y cuadrícula'], [`${k('Mayús')} + flechas`, 'Cambiar el tamaño de la tarjeta (en cuadrícula)'], ...LIST_KEYS]],
    'page-inbox': ['Inbox y tablero', [...LIST_KEYS, [`${k('V')} ${k('H')}`, 'Seleccionar / desplazar el tablero'],
      [`${k('R')} ${k('O')} ${k('S')} ${k('T')} ${k('A')} ${k('P')}`, 'Caja, óvalo, nota, texto, conector, lápiz'],
      [`${k('Ctrl')} ${k('Z')}`, 'Deshacer en el tablero'], [`${k('F')} ${k('0')}`, 'Ajustar a pantalla / zoom 100 %']]],
    'page-rutinas': ['Rutinas', [[`${k('Ctrl')} ${k('Intro')}`, 'Guardar el formulario']]],
    'page-notas': ['Notas', [[k('/'), 'Buscar una nota'], [k('Esc'), 'Salir de la edición']]],
  };
  function help() {
    if (document.querySelector('dialog[open]')) return;
    const cap = (window.Prefs?.get('capture-key', 'c') || 'c').toUpperCase();
    const page = Object.keys(PAGE_KEYS).find((c) => document.body.classList.contains(c))
      || (document.body.dataset.section === 'notas' ? 'page-notas' : null);
    const rows = (list) => list.map(([keys, what]) => `<dt>${keys}</dt><dd>${what}</dd>`).join('');
    const go = [['H', 'Hoy'], ['C', 'Calendario'], ['U', 'Rutinas'], ['T', 'Tareas'], ['A', 'Universidad'], ['P', 'Proyectos'], ['I', 'Inbox'], ['O', 'Notas'], ['N', 'Nota nueva'],
      ['M', 'Comidas'], ['D', 'Economía'], ['B', 'Baúl'], ['E', 'Estudio'], ['R', 'Revisión']];
    const d = document.createElement('dialog');
    d.className = 'modal modal-sm keys-help';
    d.setAttribute('aria-labelledby', 'keysHelpTitle');
    d.innerHTML = `<div class="modal-header"><h2 id="keysHelpTitle">Atajos de teclado</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body stack">
        ${page ? `<section><h3>${PAGE_KEYS[page][0]}</h3><dl class="keys-list">${rows(PAGE_KEYS[page][1])}</dl></section>` : ''}
        <section><h3>En todo el panel</h3><dl class="keys-list">${rows([[`${k('Ctrl')} ${k('K')}`, 'Buscar e ir a cualquier sitio'],
          [k(cap), 'Captura rápida'], [`${k('Ctrl')} ${k('.')}`, 'Plegar o desplegar el menú'], [k('?'), 'Esta ayuda']])}</dl></section>
        <section><h3>${k('G')} y una letra para ir a…</h3><dl class="keys-list keys-go">${rows(go.map(([l, w]) => [k(l), w]))}</dl></section>
      </div>`;
    document.body.appendChild(d);
    wireAllDialogs?.();
    openModal(d, { onClose: () => d.remove() });
  }
  let gAt = 0;
  document.addEventListener('keydown', (e) => {
    if (e.defaultPrevented) return;
    const t = e.target;
    const typing = /^(input|textarea|select)$/i.test(t.tagName || '') || t.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') { e.preventDefault(); open(); return; }
    if (typing || e.ctrlKey || e.metaKey || e.altKey || document.querySelector('dialog[open]')) return;
    if (e.key === '?') { e.preventDefault(); help(); return; }
    const k = e.key.toLowerCase();
    if (gAt && Date.now() - gAt < 1200 && GOTO[k]) { e.preventDefault(); gAt = 0; location.href = GOTO[k]; return; }
    gAt = k === 'g' ? Date.now() : 0;
  });

  window.Palette = { open, ACTIONS, help };
})();
