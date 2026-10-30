/* ==========================================================================
   palette.js — paleta de comandos (Ctrl+K) y atajos «G + letra» (window.Palette)
   Busca de forma aproximada (fuzzyScore, ui.js) en notas, tareas, ideas, rutinas,
   eventos cercanos, platos y acciones; cada acción muestra su atajo. Flechas para
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
    { label: 'Captura rápida', icon: 'plus', keys: 'C', run: () => openCapture(), words: 'inbox apuntar' },
    { label: 'Ir a Hoy', icon: 'sun', keys: 'G H', run: go('/hoy'), words: 'inicio resumen' },
    { label: 'Ir a Calendario', icon: 'calendar', keys: 'G C', run: go('/calendario'), words: 'agenda semana mes' },
    { label: 'Ir a Notas', icon: 'notebook-pen', keys: 'G O', run: go('/'), words: 'cerebro' },
    { label: 'Ir a Inbox', icon: 'inbox', keys: 'G I', run: go('/inbox'), words: 'tablero' },
    { label: 'Ir a Tareas', icon: 'list-todo', keys: 'G T', run: go('/tareas'), words: 'ideas rutinas' },
    { label: 'Ir a Comidas', icon: 'utensils-crossed', keys: 'G M', run: go('/comidas/'), words: 'menú plan compra' },
    { label: 'Ir a Estudio', icon: 'graduation-cap', keys: 'G E', run: go('/estudio/'), words: 'esp32 pomodoro' },
    { label: 'Revisión semanal', icon: 'history', keys: 'G R', run: go('/revision'), words: 'registro cambios completadas' },
    { label: 'Repasar flashcards', icon: 'book-open', run: go('/repaso'), words: 'repaso' },
    { label: 'Buscar en las notas', icon: 'search', keys: '/', run: go('/buscar'), words: 'texto completo' },
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
    idx.notes.forEach((n) => out.push({ group: 'Notas', label: n.title, sub: n.category, icon: 'notebook-pen', run: go(`/?note=${encodeURIComponent(n.id)}`) }));
    idx.items.forEach((i) => out.push({ group: { tarea: 'Tareas', idea: 'Ideas', rutina: 'Rutinas' }[i.type] || 'Tareas', label: i.text,
      sub: i.done ? 'hecha' : i.origin === 'nota' ? 'en una nota' : '', icon: ITEM_ICON[i.type] || 'square-check', run: go(`/tareas?item=${i.id}`), penalty: i.done ? 4 : 0 }));
    idx.events.forEach((e) => out.push({ group: 'Eventos', label: e.title,
      sub: new Date(e.start.slice(0, 10) + 'T00:00').toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' }) + (e.start.length > 10 ? ` · ${e.start.slice(11, 16)}` : ''),
      icon: 'calendar', run: go(`/calendario?dia=${e.start.slice(0, 10)}`) }));
    idx.meals.forEach((m) => out.push({ group: 'Platos', label: m.nombre, sub: m.franja, icon: 'utensils-crossed', run: go('/comidas/') }));
    return out;
  }

  function search(all, q) {
    if (!q.trim()) return all.filter((c) => c.group === 'Acciones');
    return all.map((c) => ({ c, s: Math.max(fuzzyScore(q, c.label) * 1.2, fuzzyScore(q, c.sub || '') * 0.5) + (c.boost || 0) - (c.penalty || 0) }))
      .filter((r) => r.s > (r.c.boost || 0) - (r.c.penalty || 0)).sort((a, b) => b.s - a.s).slice(0, 60).map((r) => r.c);
  }

  let dlg = null;
  function open() {
    if (dlg?.open) { dlg.querySelector('input').select(); return; }
    dlg = document.createElement('dialog');
    dlg.className = 'modal palette';
    dlg.setAttribute('aria-label', 'Paleta de comandos');
    dlg.innerHTML = `<div class="palette-search">${icon('command')}
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
          <span class="row-main"><span class="row-title">${escapeHtml(c.label)}</span>${c.sub && c.group !== 'Acciones' ? `<span class="row-sub">${escapeHtml(c.sub)}</span>` : ''}</span>
          ${c.keys ? `<span class="palette-keys">${kbd(c.keys)}</span>` : ''}</li>`;
      }).join('') : `<li class="palette-empty small muted">Nada coincide con «${escapeHtml(input.value)}»</li>`;
      input.setAttribute('aria-activedescendant', shown.length ? `pal-${active}` : '');
      list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
    };
    const run = (i) => { const c = shown[i]; if (!c) return; closeModal(dlg); setTimeout(() => c.run(), 0); };
    input.addEventListener('input', () => { active = 0; paint(); });
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
  const GOTO = { h: '/hoy', c: '/calendario', u: '/rutinas', o: '/', i: '/inbox', t: '/tareas', m: '/comidas/', d: '/economia', b: '/vault',
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
    const go = [['H', 'Hoy'], ['C', 'Calendario'], ['U', 'Rutinas'], ['T', 'Tareas'], ['I', 'Inbox'], ['O', 'Notas'], ['N', 'Nota nueva'],
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
