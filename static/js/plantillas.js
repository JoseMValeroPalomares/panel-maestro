/* ==========================================================================
   plantillas.js — galería única de plantillas (P-4), window.Plantillas
   Las tres clases en un solo sitio, con pestañas: Tablero · Día · Rutina. Cada tarjeta lleva miniatura, nombre y
   descripción; se busca por nombre, descripción o etiquetas. Un clic la aplica (y pide nombre o fecha si hace falta);
   en el Inbox, las de tablero también se arrastran al lienzo. Las tuyas se renombran, describen, editan (los pasos de
   una rutina), duplican y borran (a la papelera, con deshacer); de las de serie se puede hacer una copia tuya.

     Plantillas.open({ tab, day })      en un diálogo (Rutinas, Calendario, menú del tablero)
     Plantillas.mount(el, { tab, embedded, onTablero })   dentro de una página (pestaña «Plantilla» del Inbox)
   ========================================================================== */
(function () {
  'use strict';
  const esc = (s) => escapeHtml(String(s ?? ''));
  const TABS = [['tablero', 'Tablero', 'layout-grid'], ['dia', 'Día', 'calendar-days'], ['rutina', 'Rutina', 'repeat']];
  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const fmtMin = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60}` : ''}` : `${m} min`);
  const toMin = (t) => (t ? Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5)) : null);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

  /* ---------- Datos de cada clase, en un formato común ---------- */
  async function load(tab) {
    if (tab === 'tablero') {
      let mine = [];
      try { mine = (await api('/api/board-templates', { quiet: true })).templates; } catch {}
      const parse = (t) => { try { return JSON.parse(t.data); } catch { return { nodes: [] }; } };
      return [
        ...mine.map((t) => { const p = parse(t); return { clase: 'tablero', key: 'u' + t.id, id: t.id, mine: true, name: t.name, desc: p.descripcion || `${p.nodes?.length || 0} formas`, thumb: { nodes: p.nodes || [] } }; }),
        ...(window.PlantillasCatalogo?.tablero || []).map((t) => ({ clase: 'tablero', key: 'c:' + t.key, mine: false, name: t.name, desc: t.desc, tags: t.tags, thumb: { cat: t } })),
      ];
    }
    if (tab === 'dia') {
      const [serie, mine] = await Promise.all([
        api('/api/day-templates/serie', { quiet: true }).then((r) => r.plantillas).catch(() => []),
        api('/api/day-templates', { quiet: true }).then((r) => r.plantillas).catch(() => []),
      ]);
      return [...mine, ...serie].map((p) => ({ clase: 'dia', key: p.key, id: p.id, mine: !p.builtin, name: p.name,
        desc: p.descripcion || `${p.eventos} eventos y bloques${p.comidas ? ` · ${p.comidas} platos` : ''}`, comidas: p.comidas, thumb: { events: p.data?.events || [] } }));
    }
    let list = [];
    try { list = (await api('/api/routine-templates', { quiet: true })).plantillas; } catch {}
    return list.map((t) => ({ clase: 'rutina', key: t.key, id: t.id, mine: !t.builtin, name: t.title, icon: t.icon,
      desc: t.descripcion || `${t.repeat_text}${t.due_time ? ` · ${t.due_time}` : ''}`,
      meta: `${t.repeat_text}${t.due_time ? ` · ${t.due_time}` : ''} · ${t.steps.length} pasos${t.total_min ? ` · ${fmtMin(t.total_min)}` : ''}`,
      tags: t.steps.map((s) => s.title).join(' '), steps: t.steps, raw: t, thumb: { steps: t.steps } }));
  }

  /* ---------- Miniaturas (SVG): formas del tablero, horario del día, pasos de la rutina ---------- */
  function thumbTablero(nodes) {
    if (!nodes.length) return '';
    const xs = nodes.map((n) => n.x), ys = nodes.map((n) => n.y);
    const x0 = Math.min(...xs), y0 = Math.min(...ys);
    const x1 = Math.max(...nodes.map((n) => n.x + n.w)), y1 = Math.max(...nodes.map((n) => n.y + n.h));
    const w = Math.max(1, x1 - x0), h = Math.max(1, y1 - y0);
    const shape = (n) => {
      const c = n.stroke || '#89b4fa', fill = n.kind === 'sticky' ? c : n.kind === 'text' ? 'none' : (n.fill || c + '33');
      const a = `fill="${esc(fill)}" stroke="${n.kind === 'text' ? 'none' : esc(c)}" stroke-width="${Math.max(w, h) / 120}"`;
      if (n.kind === 'ellipse') return `<ellipse cx="${n.x + n.w / 2}" cy="${n.y + n.h / 2}" rx="${n.w / 2}" ry="${n.h / 2}" ${a}/>`;
      if (n.kind === 'diamond') return `<polygon points="${n.x + n.w / 2},${n.y} ${n.x + n.w},${n.y + n.h / 2} ${n.x + n.w / 2},${n.y + n.h} ${n.x},${n.y + n.h / 2}" ${a}/>`;
      if (n.kind === 'text') return `<rect x="${n.x}" y="${n.y + n.h * 0.35}" width="${Math.min(n.w, 260)}" height="${n.h * 0.3}" rx="4" fill="#cdd6f4" opacity=".45"/>`;
      return `<rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="${n.kind === 'box' ? 2 : 10}" ${a}/>`;
    };
    const pad = Math.max(w, h) * 0.06;
    return `<svg viewBox="${x0 - pad} ${y0 - pad} ${w + pad * 2} ${h + pad * 2}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${nodes.map(shape).join('')}</svg>`;
  }
  function thumbCat(t) {
    const nodes = t.nodes.map(([kind, x, y, w, h, , color]) => ({ kind, x, y, w, h, stroke: color || '#89b4fa', fill: color ? (kind === 'sticky' ? color : color + '33') : '#89b4fa26' }));
    return thumbTablero(nodes);
  }
  // Día: una línea de 7 a 23 h con cada evento como una barra
  function thumbDia(events) {
    const t0 = 7 * 60, t1 = 23 * 60, W = 200;
    const bars = events.filter((e) => e.start).map((e, i) => {
      const a = Math.max(t0, toMin(e.start)), b = Math.min(t1, toMin(e.end) || a + 30);
      const color = { clase: 'var(--tile-universidad)', examen: 'var(--danger)', entrega: 'var(--warning)' }[e.kind] || 'var(--c-event)';
      return `<rect x="${((a - t0) / (t1 - t0)) * W}" y="${8 + (i % 4) * 14}" width="${Math.max(3, ((b - a) / (t1 - t0)) * W)}" height="10" rx="3" fill="${color}"/>`;
    });
    return `<svg viewBox="0 0 ${W} 72" aria-hidden="true"><line x1="0" y1="66" x2="${W}" y2="66" stroke="var(--separator-strong)"/>${[9, 13, 17, 21].map((hh) => `<line x1="${((hh * 60 - t0) / (t1 - t0)) * W}" y1="62" x2="${((hh * 60 - t0) / (t1 - t0)) * W}" y2="70" stroke="var(--separator-strong)"/>`).join('')}${bars.join('')}</svg>`;
  }
  // Rutina: los pasos uno detrás de otro, cada uno tan largo como dura
  function thumbRutina(steps) {
    const total = steps.reduce((a, s) => a + (s.duration_min || 10), 0) || 1;
    let x = 0;
    const bars = steps.map((s, i) => { const w = ((s.duration_min || 10) / total) * 196; const r = `<rect x="${x + 2}" y="${20 + (i % 2) * 18}" width="${Math.max(3, w - 2)}" height="14" rx="4" fill="var(--c-routine)" opacity="${0.55 + (i % 3) * 0.2}"/>`; x += w; return r; });
    return `<svg viewBox="0 0 200 72" aria-hidden="true">${bars.join('')}</svg>`;
  }
  const thumb = (p) => (p.clase === 'tablero' ? (p.thumb.cat ? thumbCat(p.thumb.cat) : thumbTablero(p.thumb.nodes)) : p.clase === 'dia' ? thumbDia(p.thumb.events) : thumbRutina(p.thumb.steps));

  /* ---------- La galería ---------- */
  const instances = new WeakMap();
  function mount(root, opts = {}) {
    const st = { tab: opts.tab || 'tablero', q: '', items: [], opts };
    instances.set(root, st);
    const uid = 'tg' + Math.random().toString(36).slice(2, 7);
    root.classList.add('tg', opts.embedded ? 'is-embedded' : 'is-modal');
    root.innerHTML = `<div class="tg-head">
        <div class="segmented tg-tabs" role="tablist" aria-label="Clase de plantilla">${TABS.map(([k, l, ic]) => `<button type="button" role="tab" id="${uid}-${k}" data-tg-tab="${k}" aria-selected="${k === st.tab}" aria-controls="${uid}-panel">${icon(ic, 'icon-sm')}${l}</button>`).join('')}</div>
        <label class="search tg-search">${icon('search')}<span class="sr-only">Buscar plantillas</span><input type="search" class="input input-sm" data-tg-q placeholder="Buscar plantillas" autocomplete="off"></label>
      </div>
      <p class="tiny subtle tg-hint" data-tg-hint></p>
      <div class="tg-grid" id="${uid}-panel" role="tabpanel" aria-labelledby="${uid}-${st.tab}" data-tg-grid></div>`;
    root.addEventListener('click', (e) => onClick(root, e));
    root.addEventListener('keydown', (e) => {
      const tab = e.target.closest('[data-tg-tab]');
      if (tab && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
        e.preventDefault();
        const i = TABS.findIndex(([k]) => k === tab.dataset.tgTab), k = TABS[(i + (e.key === 'ArrowRight' ? 1 : TABS.length - 1)) % TABS.length][0];
        setTab(root, k);
        root.querySelector(`[data-tg-tab="${k}"]`).focus();
        return;
      }
      if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.tg-card')) { e.preventDefault(); apply(root, e.target.closest('[data-key]').dataset.key); }
    });
    root.querySelector('[data-tg-q]').addEventListener('input', (e) => { st.q = e.target.value; paint(root); });
    setTab(root, st.tab);
    return root;
  }
  async function setTab(root, tab) {
    const st = instances.get(root);
    st.tab = tab;
    root.querySelectorAll('[data-tg-tab]').forEach((b) => { b.setAttribute('aria-selected', String(b.dataset.tgTab === tab)); b.tabIndex = b.dataset.tgTab === tab ? 0 : -1; });
    root.querySelector('[data-tg-grid]').setAttribute('aria-labelledby', root.querySelector(`[data-tg-tab="${tab}"]`).id);
    root.querySelector('[data-tg-hint]').textContent = {
      tablero: st.opts.embedded ? 'Clic para ponerla en el centro o arrástrala al sitio.' : 'Clic para usarla en un tablero (nuevo o el que tengas abierto).',
      dia: 'Pone sus eventos y bloques en el día que elijas.', rutina: 'Crea la rutina con sus pasos; antes puedes cambiar la hora, los días y los pasos.',
    }[tab];
    root.querySelector('[data-tg-grid]').innerHTML = '<span class="skeleton tg-skel"></span>'.repeat(4);
    st.items = await load(tab);
    if (st.tab === tab) paint(root);
  }
  function paint(root) {
    const st = instances.get(root);
    const q = norm(st.q).trim();
    const list = st.items.filter((p) => !q || q.split(/\s+/).every((w) => norm(`${p.name} ${p.desc} ${p.tags || ''}`).includes(w)));
    const grid = root.querySelector('[data-tg-grid]');
    if (!list.length) { grid.innerHTML = emptyState({ iconName: 'search', title: q ? `Ninguna plantilla con «${st.q}»` : 'No hay plantillas', compact: true }); return; }
    const drag = st.opts.embedded && st.tab === 'tablero';
    // La tarjeta (role=button) y su ⋯ van como hermanos dentro de .tg-item: nada interactivo dentro de otro
    grid.innerHTML = list.map((p) => `<div class="tg-item${drag ? ' tpl-tile' : ''}" data-key="${esc(p.key)}" ${drag ? `data-template="${esc(p.key)}" tabindex="-1"` : ''}>
        <article class="tg-card" tabindex="0" role="button" aria-label="${esc(p.name)}${p.mine ? ' (tuya)' : ''}: ${esc(p.desc)}. Usar la plantilla">
          <div class="tg-thumb">${thumb(p)}</div>
          <div class="tg-body"><h3 class="tg-name">${esc(p.name)}${p.mine ? ' <span class="tag">Tuya</span>' : ''}</h3>
            <p class="tg-desc">${esc(p.desc)}</p>${p.meta ? `<p class="tiny subtle tabular">${esc(p.meta)}</p>` : ''}</div>
        </article>
        <button type="button" class="btn btn-ghost btn-icon btn-sm tg-more no-drag" data-tg-menu="${esc(p.key)}" aria-label="Más acciones de «${esc(p.name)}»" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
      </div>`).join('');
    // En el Inbox, las de tablero se arrastran al lienzo como las formas (board.js recibe el «drop»); Sortable marca
    // las tarjetas al crearse, así que va después de pintarlas
    if (drag && window.Sortable) Sortable.create(grid, { group: 'board-palette', items: '.tpl-tile', keyboard: false, label: 'Plantillas', accepts: () => 'Suelta la plantilla en el tablero', onDrop() {} });
  }
  async function refresh(root) { const st = instances.get(root); if (st) { st.items = await load(st.tab); paint(root); } }

  function onClick(root, e) {
    const tab = e.target.closest('[data-tg-tab]');
    if (tab) { setTab(root, tab.dataset.tgTab); return; }
    const more = e.target.closest('[data-tg-menu]');
    if (more) { e.stopPropagation(); menu(root, more.dataset.tgMenu, more); return; }
    const card = e.target.closest('.tg-card');
    if (card) apply(root, card.closest('[data-key]').dataset.key);
  }
  const itemOf = (root, key) => instances.get(root).items.find((p) => p.key === key);

  /* ---------- Aplicar ---------- */
  async function apply(root, key) {
    const st = instances.get(root), p = itemOf(root, key);
    if (!p) return;
    if (p.clase === 'tablero') {
      if (st.opts.onTablero) { st.opts.onTablero(key); return; }
      if (window.__board?.insertTemplate && window.__board.state?.boardId) { closeOwnDialog(root); window.__board.insertTemplate(key); return; }
      location.href = `/inbox?plantilla=${encodeURIComponent(key)}`;  // un tablero nuevo con ella (board.js pregunta el nombre)
      return;
    }
    if (p.clase === 'rutina') { closeOwnDialog(root); await Items.ready?.(); Routines.openTemplates({ key }); return; }
    // Día: ¿cuál? Se escribe como en la captura («mañana», «vie», «20/11») o en AAAA-MM-DD
    const pre = st.opts.day || iso(new Date(Date.now() + 86400000));
    const v = (await uiPrompt(`«${p.name}» en un día`, { label: 'Día', value: pre, confirmLabel: 'Aplicar', message: 'Escribe la fecha: «mañana», «vie», «20/11»… Las rutinas no se tocan; se añaden sus eventos y bloques.' }))?.trim();
    if (!v) return;
    let day = /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
    if (!day) { try { day = (await api('/api/capture', { method: 'POST', body: { text: `t: x ${v}`, dry_run: true }, quiet: true })).preview?.due_date || null; } catch {} }
    if (!day) { toast(`No entiendo «${v}» como fecha`, { type: 'info' }); return; }
    const r = await api('/api/day-templates/aplicar', { method: 'POST', body: { key, day } });
    closeOwnDialog(root);
    toast(`«${p.name}»: ${r.eventos} eventos y bloques${r.platos ? `, ${r.platos} platos` : ''} el ${new Date(day + 'T00:00').toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' })}`,
      { action: location.pathname === '/calendario' ? null : { label: 'Ver', onClick: () => { location.href = `/calendario?dia=${day}`; } } });
    window.Calendar?.refreshAll?.();
  }
  function closeOwnDialog(root) { const d = root.closest('dialog'); if (d?.open) closeModal(d); }

  /* ---------- Las tuyas (y copiar las de serie) ---------- */
  const DEL = { tablero: (id) => `/api/board-templates/${id}`, dia: (id) => `/api/day-templates/${id}`, rutina: (id) => `/api/routine-templates/${id}` };
  function menu(root, key, anchor) {
    const p = itemOf(root, key);
    if (!p) return;
    const after = () => refresh(root);
    const items = [{ label: 'Usar', icon: 'circle-play', onClick: () => apply(root, key) }];
    if (p.mine) {
      items.push(
        { label: 'Renombrar…', icon: 'pencil', onClick: async () => {
          const name = (await uiPrompt('Renombrar la plantilla', { label: 'Nombre', value: p.name, confirmLabel: 'Guardar' }))?.trim();
          if (name && name !== p.name) { await api(`/api/plantillas/${p.clase}/${p.id}`, { method: 'PATCH', body: { name } }); after(); }
        } },
        { label: 'Descripción…', icon: 'file-text', onClick: async () => {
          const d = await uiPrompt('Descripción', { label: 'En una frase, para qué sirve', value: p.mine && !/^\d+ (formas|eventos)/.test(p.desc) ? p.desc : '', confirmLabel: 'Guardar' });
          if (d != null) { await api(`/api/plantillas/${p.clase}/${p.id}`, { method: 'PATCH', body: { descripcion: d.trim() } }); after(); }
        } },
        p.clase === 'rutina' && { label: 'Editar los pasos…', icon: 'list-ordered', onClick: async () => {
          const value = p.steps.map((s) => `${s.fixed && s.at ? `${s.at} ` : ''}${s.title}${s.duration_min ? ` ${s.duration_min}m` : ''}`).join('\n');
          const pasos = await uiPrompt(`Pasos de «${p.name}»`, { label: 'Uno por línea («ducha 10m», «18:30 cenar 30m»)', value, multiline: true, confirmLabel: 'Guardar' });
          if (pasos != null) { await api(`/api/plantillas/rutina/${p.id}`, { method: 'PATCH', body: { pasos } }); after(); }
        } },
        { label: 'Duplicar', icon: 'copy', onClick: async () => { await api(`/api/plantillas/${p.clase}/${p.id}/duplicar`, { method: 'POST' }); toast('Plantilla duplicada'); after(); } },
        { separator: true },
        { label: 'Borrar', icon: 'trash-2', danger: true, onClick: async () => {
          const res = await api(DEL[p.clase](p.id), { method: 'DELETE' });
          undoToast('Plantilla en la papelera', res, after);
          after();
        } },
      );
    } else {
      items.push({ label: 'Hacer una copia mía', icon: 'copy-plus', onClick: async () => {
        if (p.clase === 'tablero') {
          const t = window.PlantillasCatalogo.tablero.find((x) => 'c:' + x.key === key);
          const nodes = t.nodes.map(([kind, x, y, w, h, text, color, extra], i) => ({ id: `n${i}`, kind, x, y, w, h, text, ...(extra || {}), ...(color ? { stroke: color, fill: kind === 'sticky' ? color : color + '33' } : {}) }));
          const edges = t.links.map(([a, b, label], i) => ({ id: `e${i}`, from: `n${a}`, to: `n${b}`, color: '#89b4fa', width: 2, endHead: 'arrow', ...(t.route ? { route: t.route } : {}), ...(label ? { label } : {}) }));
          await api('/api/board-templates', { method: 'POST', body: { name: `${t.name} (mía)`, data: JSON.stringify({ nodes, edges, strokes: [], descripcion: t.desc }) } });
        } else await api(`/api/plantillas/${p.clase}/copiar`, { method: 'POST', body: { key } });
        toast('Copia guardada entre las tuyas: ya puedes renombrarla o editarla');
        after();
      } });
    }
    openMenu(anchor, items.filter(Boolean));
  }

  function open({ tab = 'tablero', day = null } = {}) {
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-lg tg-dialog';
    dlg.setAttribute('aria-labelledby', 'tgTitle');
    dlg.innerHTML = `<div class="modal-header"><div><h2 id="tgTitle">Plantillas</h2><p class="modal-sub">Tablero, día y rutina en un solo sitio. Guarda las tuyas desde un tablero, una tarea con pasos, el calendario o una rutina.</p></div>
      <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div><div class="modal-body" data-tg-root></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    mount(dlg.querySelector('[data-tg-root]'), { tab, day });
    openModal(dlg, { focus: '[data-tg-tab][aria-selected="true"]', onClose: () => dlg.remove() });
    return dlg;
  }

  // Una tarea con pasos como plantilla de tablero: el objetivo arriba y los pasos en columna, sobre la rejilla
  async function guardarTarea(it, kids) {
    const title = it.text.split('\n')[0];
    const name = (await uiPrompt('Guardar como plantilla de tablero', { label: 'Nombre', value: title.slice(0, 120), confirmLabel: 'Guardar',
      message: 'La tarea y sus pasos, dibujados como un flujo. La tendrás en Plantillas → Tablero.' }))?.trim();
    if (!name) return;
    const nodes = [{ id: 'n0', kind: 'rect', x: 0, y: 0, w: 280, h: 60, text: title, stroke: '#94e2d5', fill: '#94e2d533' },
      ...kids.map((k, i) => ({ id: `n${i + 1}`, kind: 'rect', x: 0, y: 100 + i * 80, w: 280, h: 60, text: k.text.split('\n')[0], stroke: '#89b4fa', fill: '#89b4fa33' }))];
    const edges = kids.map((k, i) => ({ id: `e${i}`, from: `n${i}`, to: `n${i + 1}`, color: '#89b4fa', width: 2, endHead: 'arrow' }));
    await api('/api/board-templates', { method: 'POST', body: { name, data: JSON.stringify({ nodes, edges, strokes: [], descripcion: `Tarea con ${kids.length} paso${kids.length === 1 ? '' : 's'}` }) } });
    toast('Plantilla guardada: la tienes en Plantillas → Tablero');
  }

  window.Plantillas = { open, mount, refresh, thumb, guardarTarea };
})();
