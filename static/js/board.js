/* ==========================================================================
   board.js — tablero del Inbox en SVG propio (formato 2, ver app/board_convert.py)

   Modelo: nodes (formas con su texto dentro), edges (conectores anclados a
   formas o con extremos libres) y strokes (dibujo a mano). Los conectores no
   guardan geometría: se calculan desde sus formas (lado fijo o automático,
   enrutado recto / ortogonal / curvo), así siguen a la forma al moverla,
   redimensionarla, moverla junto a otras o hacer zoom.
   Vista (desplazamiento + zoom) = una sola transformación del grupo «mundo».
   Repintado incremental: cada elemento guarda su firma y solo se rehace si cambia.
   Historial: instantáneas por elemento con cadenas compartidas (lo que no cambia
   no ocupa memoria otra vez), así el deshacer no tiene un límite práctico.

   Depende de ui.js (api, toast, uiPrompt, uiConfirm, openMenu, icon) y de
   sortable.js (soltar elementos del Inbox y formas de la paleta en el tablero).
   Usa el almacén único (Items, items.js) para mostrar y editar las tarjetas enlazadas.
   ========================================================================== */
(function () {
  'use strict';

  const NS = 'http://www.w3.org/2000/svg';
  const XHTML = 'http://www.w3.org/1999/xhtml';
  const GRID = 20;
  const MIN_ZOOM = 0.03, MAX_ZOOM = 4; // 3 %: «Ajustar» encuadra también tableros muy extensos
  const HISTORY_MAX = 5000;
  const STUB = 22;          // tramo recto al salir de una forma (enrutado ortogonal)
  const HEADER = 34;        // franja del título de un contenedor
  const GUIDE_PX = 6;       // distancia en pantalla a la que engancha una guía

  // Catppuccin Mocha (acentos). Se guardan como hex en el tablero.
  const PALETTE = [
    ['Lavanda', '#b4befe'], ['Azul', '#89b4fa'], ['Zafiro', '#74c7ec'], ['Cielo', '#89dceb'], ['Verde azulado', '#94e2d5'],
    ['Verde', '#a6e3a1'], ['Amarillo', '#f9e2af'], ['Melocotón', '#fab387'], ['Granate', '#eba0ac'], ['Rojo', '#f38ba8'],
    ['Malva', '#cba6f7'], ['Rosa', '#f5c2e7'], ['Flamenco', '#f2cdcd'], ['Texto', '#cdd6f4'], ['Superficie', '#585b70'],
  ];
  const DEFAULTS = {
    box: { fill: '#89b4fa26', stroke: '#89b4fa', color: '#cdd6f4', fontSize: 16, strokeWidth: 2, w: 180, h: 90 },
    rect: { fill: '#89b4fa26', stroke: '#89b4fa', color: '#cdd6f4', fontSize: 16, strokeWidth: 2, w: 180, h: 90 },
    ellipse: { fill: '#cba6f726', stroke: '#cba6f7', color: '#cdd6f4', fontSize: 16, strokeWidth: 2, w: 160, h: 100 },
    diamond: { fill: '#f9e2af26', stroke: '#f9e2af', color: '#cdd6f4', fontSize: 15, strokeWidth: 2, w: 160, h: 110 },
    sticky: { fill: '#f9e2af', stroke: '#f9e2af', color: '#1e1e2e', fontSize: 16, strokeWidth: 0, w: 180, h: 160 },
    text: { fill: 'none', stroke: 'none', color: '#cdd6f4', fontSize: 20, strokeWidth: 0, w: 200, h: 44 },
    container: { fill: '#585b7026', stroke: '#7f849c', color: '#cdd6f4', fontSize: 15, strokeWidth: 1.5, w: 380, h: 260 },
    inbox: { fill: '#313244', stroke: '#94e2d5', color: '#cdd6f4', fontSize: 14, strokeWidth: 2, w: 220, h: 96 },
  };
  const RX = { box: 0, rect: 12, sticky: 4, text: 6, container: 10, inbox: 12 };
  const LINE_DEFAULTS = { color: '#89b4fa', width: 2, route: 'straight', startHead: 'none', endHead: 'arrow', dash: 'solid' };
  const TYPE_COLORS = { tarea: '#94e2d5', idea: '#fab387', nota: '#fab387', rutina: '#cba6f7' }; // 'nota' = idea en tableros antiguos
  const SHAPES = [
    ['box', 'Rectángulo'], ['rect', 'Redondeado'], ['ellipse', 'Elipse'], ['diamond', 'Rombo'], ['sticky', 'Nota adhesiva'],
    ['text', 'Texto'], ['container', 'Contenedor'], ['line', 'Línea'], ['arrow', 'Flecha'],
  ];
  // Marco opcional de un texto suelto: la misma caja del texto dibujada con esta forma
  const FRAMES = [['none', 'Sin marco'], ['box', 'Rectángulo'], ['rect', 'Redondeado'], ['ellipse', 'Elipse'], ['diamond', 'Rombo']];
  const shapeOf = (n) => (n.kind === 'text' && n.frame ? n.frame : n.kind);
  const HEADS = [['none', 'Ninguna'], ['arrow', 'Flecha'], ['open', 'Flecha abierta'], ['diamond', 'Rombo'], ['circle', 'Círculo']];
  const ROUTES = [['straight', 'Recto', 'slash'], ['orthogonal', 'Ortogonal', 'corner-down-right'], ['curved', 'Curvo', 'spline']];
  const DASHES = [['solid', 'Continua'], ['dashed', 'Discontinua'], ['dotted', 'Punteada']];
  const WIDTHS = [1, 2, 3, 4, 6];
  const SIDES = { n: [0, -1], e: [1, 0], s: [0, 1], w: [-1, 0] };

  const $ = (sel, root = document) => root.querySelector(sel);
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const isMobile = () => window.matchMedia('(max-width: 767px)').matches;
  const uid = (p) => `${p}_${Math.random().toString(36).slice(2, 10)}`;
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const snapTo = (v) => Math.round(v / GRID) * GRID;
  const r1 = (v) => Math.round(v * 10) / 10;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const base = (c) => (typeof c === 'string' && c.startsWith('#') ? c.slice(0, 7) : c);
  const cleanText = (s) => (s || '').replace(/^---\s*/, '');

  /* ---------- Estado ---------- */
  const S = {
    boards: [], boardId: null, doc: emptyDoc(), view: { x: 0, y: 0, zoom: 1 },
    sel: new Set(), tool: 'select', snap: true, minimap: true, propsOpen: true, propsMode: 'float', sheetOpen: false,
    past: [], future: [], clipboard: null, style: null, pasteCount: 0, lineDefaults: { ...LINE_DEFAULTS },
    editing: null, gesture: null, pointers: new Map(), space: false, dirty: false, saveTimer: null, hover: null, version: 0,
  };
  try { S.propsOpen = localStorage.getItem('board-props') !== 'closed'; } catch {}

  function emptyDoc() { return { format: 2, nodes: [], edges: [], strokes: [] }; }
  const node = (id) => S.doc.nodes.find((n) => n.id === id);
  const edge = (id) => S.doc.edges.find((e) => e.id === id);
  const stroke = (id) => S.doc.strokes.find((s) => s.id === id);
  const item = (id) => node(id) || edge(id) || stroke(id);
  const style = (n, key) => n[key] ?? DEFAULTS[n.kind]?.[key] ?? DEFAULTS.rect[key];
  const unit = (n) => style(n, 'fontSize') / (DEFAULTS[n.kind]?.fontSize || 16); // escala de los detalles de la forma
  const padOf = (n) => Math.max(2, r1(style(n, 'fontSize') * 0.625));
  const eRoute = (e) => e.route || 'straight';
  const eHead = (e, end) => (end === 'start' ? e.startHead || 'none' : e.endHead || (e.head === 'none' ? 'none' : 'arrow'));
  const eDash = (e) => e.dash || (e.dashed ? 'dashed' : 'solid');
  const inboxItem = (n) => (n.kind === 'inbox' && window.Items?.state.loaded ? Items.get(n.inboxId) : null);
  const CARD_STEP = 26, CARD_FOOT = 26, CARD_MIN = 64;  // alto de un paso y del pie en una tarjeta del Inbox

  /* ---------- DOM ---------- */
  let body, wrap, svg, defs, grid, world, layers, overlay, mini, miniWorld, miniView, statusEl, zoomLabel, props;

  function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null && v !== false) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }
  function attrs(e, a) { for (const [k, v] of Object.entries(a)) { if (v === undefined || v === null || v === false) e.removeAttribute(k); else e.setAttribute(k, v); } }

  function buildDom() {
    wrap = $('#boardWrap');
    body = $('#boardBody');
    svg = el('svg', { class: 'board-svg', role: 'application', 'aria-label': 'Lienzo del tablero', tabindex: '0' }, wrap);
    defs = el('defs', {}, svg);
    const pat = el('pattern', { id: 'boardGrid', width: GRID, height: GRID, patternUnits: 'userSpaceOnUse' }, defs);
    el('circle', { cx: 1, cy: 1, r: 1, class: 'grid-dot' }, pat);
    grid = el('rect', { class: 'board-grid', width: '100%', height: '100%', fill: 'url(#boardGrid)' }, svg);
    world = el('g', { class: 'board-world' }, svg);
    layers = { strokes: el('g', {}, world), edges: el('g', {}, world), nodes: el('g', {}, world) };
    overlay = el('g', { class: 'board-overlay' }, world);
    mini = $('#boardMinimap');
    const msvg = el('svg', { class: 'minimap-svg', 'aria-hidden': 'true' }, mini);
    miniWorld = el('g', {}, msvg);
    miniView = el('rect', { class: 'minimap-view' }, msvg);
    statusEl = $('#boardSaveStatus');
    zoomLabel = $('#zoomLabel');
    props = document.createElement('aside');
    props.className = 'board-props';
    props.id = 'boardProps';
    props.hidden = true;
    props.setAttribute('aria-label', 'Propiedades de la selección');
    body.appendChild(props);
  }

  /* ---------- Vista ---------- */
  function applyView() {
    const { x, y, zoom } = S.view;
    world.setAttribute('transform', `translate(${x} ${y}) scale(${zoom})`);
    const pat = $('#boardGrid', defs);
    const g = GRID * zoom;
    pat.setAttribute('width', g); pat.setAttribute('height', g);
    pat.setAttribute('x', x % g); pat.setAttribute('y', y % g);
    grid.style.opacity = zoom < 0.35 ? 0 : 1;
    zoomLabel.textContent = Math.round(zoom * 100) + '%';
    renderMinimapSoon();
    saveViewSoon();
  }
  let viewTimer;
  function saveViewSoon() {
    clearTimeout(viewTimer);
    viewTimer = setTimeout(() => { try { localStorage.setItem('board-view:' + S.boardId, JSON.stringify(S.view)); } catch {} }, 300);
  }
  function toWorld(cx, cy) {
    const r = svg.getBoundingClientRect();
    return { x: (cx - r.left - S.view.x) / S.view.zoom, y: (cy - r.top - S.view.y) / S.view.zoom };
  }
  function viewBounds(margin = 0) {
    const r = svg.getBoundingClientRect(), z = S.view.zoom, m = margin / z;
    return { x: -S.view.x / z + m, y: -S.view.y / z + m, w: r.width / z - 2 * m, h: r.height / z - 2 * m };
  }
  function zoomAt(cx, cy, factor) {
    const r = svg.getBoundingClientRect();
    const z = clamp(S.view.zoom * factor, MIN_ZOOM, MAX_ZOOM);
    const px = cx - r.left, py = cy - r.top;
    S.view.x = px - (px - S.view.x) * (z / S.view.zoom);
    S.view.y = py - (py - S.view.y) * (z / S.view.zoom);
    S.view.zoom = z;
    applyView();
    renderOverlay();
  }
  function zoomCenter(factor) { const c = svg.getBoundingClientRect(); zoomAt(c.left + c.width / 2, c.top + c.height / 2, factor); }
  function contentBounds(ids) {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    const add = (x, y) => { x1 = Math.min(x1, x); y1 = Math.min(y1, y); x2 = Math.max(x2, x); y2 = Math.max(y2, y); };
    S.doc.nodes.forEach((n) => { if (!ids || ids.has(n.id)) { add(n.x, n.y); add(n.x + n.w, n.y + n.h); } });
    S.doc.strokes.forEach((s) => { if (!ids || ids.has(s.id)) s.points.forEach(([x, y]) => add(x, y)); });
    S.doc.edges.forEach((e) => { if (!ids || ids.has(e.id)) [e.p1, e.p2].forEach((p) => p && add(p[0], p[1])); });
    return x1 === Infinity ? null : { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
  }
  function fit(animate = true) {
    const b = contentBounds();
    const r = svg.getBoundingClientRect();
    if (!b || !r.width) { S.view = { x: r.width / 2, y: r.height / 2, zoom: 1 }; applyView(); return; }
    const pad = 60;
    const zoom = Math.min(1.25, Math.max(MIN_ZOOM, Math.min((r.width - pad * 2) / Math.max(b.w, 1), (r.height - pad * 2) / Math.max(b.h, 1))));
    animateView({ zoom, x: r.width / 2 - (b.x + b.w / 2) * zoom, y: r.height / 2 - (b.y + b.h / 2) * zoom }, animate);
  }
  function animateView(target, animate) {
    if (!animate || reduceMotion()) { S.view = target; applyView(); renderOverlay(); return; }
    const from = { ...S.view }, t0 = performance.now(), dur = 260;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      S.view = { x: from.x + (target.x - from.x) * e, y: from.y + (target.y - from.y) * e, zoom: from.zoom + (target.zoom - from.zoom) * e };
      applyView(); renderOverlay();
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  /* ---------- Geometría de los conectores ---------- */
  function center(n) { return { x: n.x + n.w / 2, y: n.y + n.h / 2 }; }
  function sidePoint(n, side, gap = 0) {
    const c = center(n), [nx, ny] = SIDES[side];
    return { x: c.x + nx * (n.w / 2 + gap), y: c.y + ny * (n.h / 2 + gap) };
  }
  function sideToward(n, p) {
    const c = center(n), dx = (p.x - c.x) / Math.max(n.w, 1), dy = (p.y - c.y) / Math.max(n.h, 1);
    return Math.abs(dx) >= Math.abs(dy) ? (dx >= 0 ? 'e' : 'w') : (dy >= 0 ? 's' : 'n');
  }
  // Punto del borde de la forma en dirección a (tx, ty)
  function borderPoint(n, tx, ty, gap = 6) {
    const c = center(n);
    const dx = tx - c.x, dy = ty - c.y;
    if (!dx && !dy) return c;
    const a = n.w / 2 + gap, b = n.h / 2 + gap;
    let t;
    const sk = shapeOf(n);
    if (sk === 'ellipse') t = 1 / Math.sqrt((dx * dx) / (a * a) + (dy * dy) / (b * b));
    else if (sk === 'diamond') t = 1 / (Math.abs(dx) / a + Math.abs(dy) / b);
    else t = Math.min(a / Math.abs(dx || 1e-9), b / Math.abs(dy || 1e-9));
    return { x: c.x + dx * t, y: c.y + dy * t };
  }
  function endInfo(e, which) {
    const n = e[which] && node(e[which]);
    if (n) return { n, side: e[which + 'Side'] || null };
    const p = which === 'from' ? e.p1 : e.p2;
    return { p: { x: p?.[0] ?? 0, y: p?.[1] ?? 0 } };
  }
  function edgeGeom(e) {
    const A = endInfo(e, 'from'), B = endInfo(e, 'to'), route = eRoute(e);
    const gA = eHead(e, 'start') === 'none' ? 6 : 9, gB = eHead(e, 'end') === 'none' ? 6 : 9;
    const ref = (I) => (I.n ? (I.side ? sidePoint(I.n, I.side) : center(I.n)) : I.p);
    const ra = ref(A), rb = ref(B);
    let sa = A.side, sb = B.side;
    if (route !== 'straight') { if (A.n && !sa) sa = sideToward(A.n, rb); if (B.n && !sb) sb = sideToward(B.n, ra); }
    const s = A.n ? (sa ? sidePoint(A.n, sa, gA) : borderPoint(A.n, rb.x, rb.y, gA)) : A.p;
    const t = B.n ? (sb ? sidePoint(B.n, sb, gB) : borderPoint(B.n, ra.x, ra.y, gB)) : B.p;
    if (route === 'orthogonal') {
      const pts = orthoRoute(s, sa, t, sb);
      return { s, t, pts, d: roundedPath(pts, 8), mid: polyMid(pts) };
    }
    if (route === 'curved') {
      const dist = Math.hypot(t.x - s.x, t.y - s.y), k = clamp(dist * 0.4, 30, 220);
      const c1 = sa ? { x: s.x + SIDES[sa][0] * k, y: s.y + SIDES[sa][1] * k } : { x: s.x + (t.x - s.x) / 3, y: s.y + (t.y - s.y) / 3 };
      const c2 = sb ? { x: t.x + SIDES[sb][0] * k, y: t.y + SIDES[sb][1] * k } : { x: t.x + (s.x - t.x) / 3, y: t.y + (s.y - t.y) / 3 };
      const mid = { x: 0.125 * s.x + 0.375 * c1.x + 0.375 * c2.x + 0.125 * t.x, y: 0.125 * s.y + 0.375 * c1.y + 0.375 * c2.y + 0.125 * t.y };
      return { s, t, pts: [s, c1, c2, t], d: `M${s.x},${s.y} C${c1.x},${c1.y} ${c2.x},${c2.y} ${t.x},${t.y}`, mid };
    }
    return { s, t, pts: [s, t], d: `M${s.x},${s.y} L${t.x},${t.y}`, mid: { x: (s.x + t.x) / 2, y: (s.y + t.y) / 2 } };
  }
  function orthoRoute(s, ds, t, dt) {
    const H = (d) => d === 'e' || d === 'w';
    const a = ds ? { x: s.x + SIDES[ds][0] * STUB, y: s.y + SIDES[ds][1] * STUB } : s;
    const b = dt ? { x: t.x + SIDES[dt][0] * STUB, y: t.y + SIDES[dt][1] * STUB } : t;
    const ha = ds ? H(ds) : dt ? !H(dt) : Math.abs(b.x - a.x) >= Math.abs(b.y - a.y);
    const hb = dt ? H(dt) : ds ? !H(ds) : ha;
    let mid;
    if (ha && hb) {
      const away = (ds === 'e' && dt === 'w' && b.x < a.x) || (ds === 'w' && dt === 'e' && b.x > a.x);
      if (away) { const my = (a.y + b.y) / 2; mid = [{ x: a.x, y: my }, { x: b.x, y: my }]; }
      else {
        const mx = ds && ds === dt ? (ds === 'e' ? Math.max(a.x, b.x) : Math.min(a.x, b.x)) : (a.x + b.x) / 2;
        mid = [{ x: mx, y: a.y }, { x: mx, y: b.y }];
      }
    } else if (!ha && !hb) {
      const away = (ds === 's' && dt === 'n' && b.y < a.y) || (ds === 'n' && dt === 's' && b.y > a.y);
      if (away) { const mx = (a.x + b.x) / 2; mid = [{ x: mx, y: a.y }, { x: mx, y: b.y }]; }
      else {
        const my = ds && ds === dt ? (ds === 's' ? Math.max(a.y, b.y) : Math.min(a.y, b.y)) : (a.y + b.y) / 2;
        mid = [{ x: a.x, y: my }, { x: b.x, y: my }];
      }
    } else mid = ha ? [{ x: b.x, y: a.y }] : [{ x: a.x, y: b.y }];
    const raw = [s, ...(ds ? [a] : []), ...mid, ...(dt ? [b] : []), t];
    const out = [];
    raw.forEach((p) => {
      const last = out[out.length - 1];
      if (last && Math.abs(last.x - p.x) < 0.01 && Math.abs(last.y - p.y) < 0.01) return;
      const prev = out[out.length - 2];
      if (prev && last && ((Math.abs(prev.x - last.x) < 0.01 && Math.abs(last.x - p.x) < 0.01) || (Math.abs(prev.y - last.y) < 0.01 && Math.abs(last.y - p.y) < 0.01))) out.pop();
      out.push(p);
    });
    return out;
  }
  function roundedPath(pts, r) {
    let d = `M${pts[0].x},${pts[0].y}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const p = pts[i], a = pts[i - 1], b = pts[i + 1];
      const d1 = Math.hypot(p.x - a.x, p.y - a.y), d2 = Math.hypot(b.x - p.x, b.y - p.y);
      const rr = Math.min(r, d1 / 2, d2 / 2);
      if (rr < 0.5) { d += ` L${p.x},${p.y}`; continue; }
      const p1 = { x: p.x - ((p.x - a.x) / d1) * rr, y: p.y - ((p.y - a.y) / d1) * rr };
      const p2 = { x: p.x + ((b.x - p.x) / d2) * rr, y: p.y + ((b.y - p.y) / d2) * rr };
      d += ` L${p1.x},${p1.y} Q${p.x},${p.y} ${p2.x},${p2.y}`;
    }
    const l = pts[pts.length - 1];
    return d + ` L${l.x},${l.y}`;
  }
  function polyMid(pts) {
    const segs = [];
    let total = 0;
    for (let i = 1; i < pts.length; i++) { const l = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y); segs.push(l); total += l; }
    let half = total / 2;
    for (let i = 0; i < segs.length; i++) {
      if (half <= segs[i] || i === segs.length - 1) {
        const k = segs[i] ? half / segs[i] : 0, a = pts[i], b = pts[i + 1];
        return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k };
      }
      half -= segs[i];
    }
    return pts[0];
  }
  function markerFor(color, head) {
    const id = `mk-${head}-${color.replace(/[^a-z0-9]/gi, '')}`;
    if (!defs.querySelector('#' + id)) {
      const m = el('marker', { id, viewBox: '0 0 10 10', refX: head === 'arrow' || head === 'open' ? 8 : 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: 'auto-start-reverse', markerUnits: 'strokeWidth' }, defs);
      if (head === 'arrow') el('path', { d: 'M0,0 L10,5 L0,10 z', fill: color }, m);
      if (head === 'open') el('path', { d: 'M1,1 L9,5 L1,9', fill: 'none', stroke: color, 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, m);
      if (head === 'diamond') el('path', { d: 'M0,5 L5,1 L10,5 L5,9 z', fill: color }, m);
      if (head === 'circle') el('circle', { cx: 5.5, cy: 5, r: 3.5, fill: color }, m);
    }
    return `url(#${id})`;
  }
  function dashArray(dash, w) { return dash === 'dashed' ? `${r1(w * 4)} ${r1(w * 3)}` : dash === 'dotted' ? `0 ${r1(w * 2.2)}` : null; }

  /* ---------- Medir texto (etiquetas y exportar) ---------- */
  let measureCtx = null, fontFamily = null;
  function measure(text, fs, weight = 400) {
    if (!measureCtx) { measureCtx = document.createElement('canvas').getContext('2d'); fontFamily = getComputedStyle(document.body).fontFamily; }
    measureCtx.font = `${weight} ${fs}px ${fontFamily}`;
    return measureCtx.measureText(text).width;
  }
  function wrapLines(text, width, fs, weight) {
    const out = [];
    for (const para of String(text).split('\n')) {
      let line = '';
      for (const word of para.split(/(?<=\s)/)) { // cada palabra con su espacio final
        if (measure(line + word, fs, weight) <= width) { line += word; continue; }
        if (line.trim()) out.push(line.trimEnd());
        line = '';
        for (const ch of word) { // una palabra más larga que la línea se parte
          if (line && measure(line + ch, fs, weight) > width) { out.push(line); line = ''; }
          line += ch;
        }
      }
      out.push(line.trimEnd());
    }
    return out;
  }

  /* ---------- Pintado ---------- */
  const nodeEls = new Map(), edgeEls = new Map(), strokeEls = new Map();

  /* Tarjetas del Inbox: la tarea con sus pasos dentro. Quitar un paso solo lo oculta en esa tarjeta (n.hiddenSteps), no lo borra */
  function cardSteps(n, it) {
    const own = new Set(S.doc.nodes.filter((m) => m.kind === 'inbox').map((m) => m.inboxId));  // con tarjeta propia en el tablero no se repiten
    const loose = Items.children(it.id).filter((k) => !own.has(k.id));
    const hidden = new Set(n.hiddenSteps || []);
    return { shown: loose.filter((k) => !hidden.has(k.id)), hidden: loose.filter((k) => hidden.has(k.id)) };
  }
  function cardHeight(n, it) {
    const { shown, hidden } = cardSteps(n, it);
    if (!shown.length && !hidden.length) return null;
    const u = unit(n), pad = padOf(n), fs = style(n, 'fontSize');
    const lines = wrapLines(it.text, n.w - pad * 2 - 24 * u, fs, 600).length;
    return Math.ceil(pad * 2 + lines * fs * 1.3 + (shown.length * CARD_STEP + CARD_FOOT + 10) * u);
  }
  function fitCards() {  // una tarjeta nunca es más baja que lo que lleva dentro (también si la tarea gana pasos)
    S.doc.nodes.forEach((n) => {
      const it = inboxItem(n), h = it && cardHeight(n, it);
      if (h && n.h < h) n.h = h;
    });
  }
  function renderCardSteps(n, it, fo) {
    const { shown, hidden } = cardSteps(n, it);
    if (!shown.length && !hidden.length) return false;
    const box = document.createElementNS(XHTML, 'div');
    box.className = 'node-steps';
    box.style.fontSize = r1(style(n, 'fontSize') * 0.86) + 'px';
    box.style.color = style(n, 'color');
    shown.forEach((k) => {
      const row = document.createElementNS(XHTML, 'div');
      const title = escapeHtml(k.text.split('\n')[0]);
      row.className = 'node-step' + (k.done ? ' is-done' : '');
      row.innerHTML = `<button type="button" class="node-step-check" data-step-check="${k.id}" role="checkbox" aria-checked="${k.done}" aria-label="${k.done ? 'Reabrir' : 'Marcar como hecho'}: ${title}"
          ${k.today === false ? 'disabled title="Hoy no toca"' : ''}>${icon('check', 'icon-sm')}</button>
        <span class="node-step-text">${title}</span>
        ${n.locked ? '' : `<button type="button" class="node-step-x" data-step-hide="${k.id}" data-node="${n.id}" aria-label="Quitar «${title}» de esta tarjeta" title="Quitar de esta tarjeta (el paso sigue en la tarea)">${icon('x', 'icon-sm')}</button>`}`;
      box.appendChild(row);
    });
    const total = shown.length + hidden.length, done = [...shown, ...hidden].filter((k) => k.done).length;
    const foot = document.createElementNS(XHTML, 'div');
    foot.className = 'node-steps-foot';
    foot.innerHTML = `<span>${done} de ${total}</span>${n.locked ? '' : hidden.length
      ? `<button type="button" data-step-show="${n.id}">Mostrar ${hidden.length === 1 ? 'el oculto' : `${hidden.length} ocultos`}</button>`
      : `<button type="button" data-step-hide-all="${n.id}">Quitar pasos</button>`}`;
    box.appendChild(foot);
    fo.appendChild(box);
    return true;
  }
  async function stepAction(b) {
    const { stepCheck, stepHide, stepShow, stepHideAll, node: nid } = b.dataset;
    if (stepCheck) {
      const k = Items.get(Number(stepCheck));
      try { await Items.setDone(k.id, !k.done); } catch (err) { toast(err?.message || 'No se pudo cambiar el estado', { type: 'error' }); }
      return;
    }
    const n = node(nid || stepShow || stepHideAll), it = n && inboxItem(n);
    if (!it) return;
    record();
    if (stepShow) delete n.hiddenSteps;
    else if (stepHideAll) n.hiddenSteps = Items.children(it.id).map((k) => k.id);
    else n.hiddenSteps = [...(n.hiddenSteps || []), Number(stepHide)];
    n.h = Math.max(CARD_MIN * unit(n), cardHeight(n, it) || 0);  // se recoge o se abre con lo que queda
    changed();
  }

  function renderAll() {
    fitCards();
    syncLayer(S.doc.strokes, strokeEls, layers.strokes, renderStroke, sigStroke);
    syncLayer(S.doc.edges, edgeEls, layers.edges, renderEdge, sigEdge);
    syncLayer(S.doc.nodes, nodeEls, layers.nodes, renderNode, sigNode);
    renderOverlay();
    S.version++;
    renderMinimapSoon();
    updateToolbarState();
    renderProps();
    const empty = !S.doc.nodes.length && !S.doc.strokes.length && !S.doc.edges.length;
    const msg = $('#boardEmpty');
    msg.hidden = !empty;
    msg.querySelector('[data-when=board]').hidden = !S.boardId;  // tablero vacío
    msg.querySelector('[data-when=none]').hidden = !!S.boardId;  // aún no hay ningún tablero
  }
  function syncLayer(items, map, layer, render, sig) {
    const alive = new Set(items.map((i) => i.id));
    for (const [id, g] of map) if (!alive.has(id)) { g.remove(); map.delete(id); }
    let prev = null;
    items.forEach((it) => {
      let g = map.get(it.id);
      if (!g) { g = el('g', { 'data-id': it.id }); map.set(it.id, g); }
      if (g.parentNode !== layer || g.previousSibling !== prev) layer.insertBefore(g, prev ? prev.nextSibling : layer.firstChild); // orden (z) del documento
      prev = g;
      if (g._sig !== sig(it)) render(it, g);
    });
  }
  function sigNode(n) {
    const it = inboxItem(n);
    const steps = it ? cardSteps(n, it) : null;
    const extra = it ? `|${it.text}|${it.done}|${it.type}|${it.parent_id ? Items.get(it.parent_id)?.text : ''}|${steps.shown.map((k) => `${k.id}${k.text}${k.done}`).join()}|${steps.hidden.length}` : '';
    return JSON.stringify(n) + S.sel.has(n.id) + (S.editing === n.id) + extra;
  }
  function sigEdge(e) {
    const geo = (id) => { const n = id && node(id); return n ? `${n.x},${n.y},${n.w},${n.h},${n.kind}` : ''; };
    return JSON.stringify(e) + S.sel.has(e.id) + geo(e.from) + '|' + geo(e.to);
  }
  function sigStroke(s) { return JSON.stringify(s) + S.sel.has(s.id); }

  function shapeAttrs(n) {
    const sw = style(n, 'strokeWidth'), strokeC = style(n, 'stroke'), fill = style(n, 'fill');
    return { fill: fill === 'none' ? 'transparent' : fill, stroke: strokeC === 'none' || !sw ? 'none' : strokeC, 'stroke-width': sw || 0,
      'stroke-dasharray': dashArray(n.dash, sw), 'stroke-linecap': n.dash === 'dotted' ? 'round' : null };
  }
  // Geometría de las partes de la forma: se usa al pintar y mientras se escribe (sin rehacer el texto)
  function placeParts(n, g) {
    const k = n.kind, sk = shapeOf(n), u = unit(n), pad = padOf(n);
    g.setAttribute('transform', `translate(${n.x} ${n.y})`);
    const shape = g.querySelector('.shape');
    if (sk === 'ellipse') attrs(shape, { cx: n.w / 2, cy: n.h / 2, rx: n.w / 2, ry: n.h / 2 });
    else if (sk === 'diamond') attrs(shape, { points: `${n.w / 2},0 ${n.w},${n.h / 2} ${n.w / 2},${n.h} 0,${n.h / 2}` });
    else attrs(shape, { width: n.w, height: n.h, rx: Math.min(RX[sk] ?? 12, n.w / 2, n.h / 2) * (k === 'container' ? 1 : Math.min(u, 4)) });
    let fx = pad, fy = pad, fw = n.w - pad * 2, fh = n.h - pad * 2;
    if (sk === 'diamond') { fx = n.w / 4; fy = n.h / 4; fw = n.w / 2; fh = n.h / 2; }
    else if (sk === 'ellipse' && k === 'text') { fx = n.w * 0.15; fy = n.h * 0.15; fw = n.w * 0.7; fh = n.h * 0.7; } // rectángulo inscrito
    if (k === 'container') {
      const hh = Math.min(n.h, HEADER * u);
      attrs(g.querySelector('.container-sep'), { x1: 0, x2: n.w, y1: hh, y2: hh });
      fy = 0; fh = hh;
    }
    if (k === 'inbox') {
      attrs(g.querySelector('.inbox-strip'), { width: 5 * u, height: n.h, rx: 2 * u });
      fx = pad + 6 * u; fw = n.w - fx - pad - 18 * u;
      const check = g.querySelector('.node-check');
      if (check) check.setAttribute('transform', `translate(${n.w - 16 * u} ${16 * u}) scale(${u})`);
      const pl = g.querySelector('.node-parent');
      if (pl) { fh -= 18 * u; attrs(pl, { x: fx, y: n.h - 12 * u, 'font-size': 11 * u }); }
    }
    attrs(g.querySelector('.node-fo'), { x: fx, y: fy, width: Math.max(1, fw), height: Math.max(1, fh) });
    return { fw, fh };
  }
  function renderNode(n, g) {
    const kind = n.kind, it = inboxItem(n);
    g.setAttribute('class', `node node-${kind}${S.sel.has(n.id) ? ' is-selected' : ''}${n.locked ? ' is-locked' : ''}${it?.done ? ' is-done' : ''}`);
    g.innerHTML = '';
    const sa = { ...shapeAttrs(n), class: 'shape' };
    const sk = shapeOf(n);
    el(sk === 'ellipse' ? 'ellipse' : sk === 'diamond' ? 'polygon' : 'rect', sa, g);
    if (kind === 'container') el('line', { class: 'container-sep', stroke: sa.stroke, 'stroke-width': sa['stroke-width'] }, g);
    if (kind === 'inbox') {
      el('rect', { x: 0, y: 0, fill: TYPE_COLORS[it?.type || n.itemType] || TYPE_COLORS.tarea, class: 'inbox-strip' }, g);
      if (it) { // casilla para completar desde el tablero
        const done = it.done;
        const c = el('g', { class: 'node-check', 'data-check': n.id, role: 'checkbox', 'aria-checked': String(done), 'aria-label': done ? 'Reabrir' : 'Marcar como hecha' }, g);
        el('circle', { r: 14, class: 'node-check-hit' }, c);
        el('circle', { r: 8, class: 'node-check-ring', fill: done ? TYPE_COLORS.tarea : 'transparent', stroke: done ? TYPE_COLORS.tarea : '#9399b2', 'stroke-width': 1.5 }, c);
        if (done) el('path', { d: 'M-3.6,0.2 L-1,2.8 L3.8,-2.4', fill: 'none', stroke: '#1e1e2e', 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, c);
      }
      const parent = it?.parent_id ? Items.get(it.parent_id) : null;
      if (n.parentLabel || parent) el('text', { class: 'node-parent' }, g).textContent = '↳ ' + cleanText(parent?.text || n.parentLabel).slice(0, 40);
    }
    const fo = el('foreignObject', { class: 'node-fo' }, g);
    const div = document.createElementNS(XHTML, 'div');
    div.className = 'node-text' + ((kind === 'text' && !n.frame) || kind === 'inbox' ? ' align-start' : kind === 'container' ? ' align-title' : '');
    div.style.fontSize = style(n, 'fontSize') + 'px';
    div.style.color = style(n, 'color');
    div.textContent = it ? it.text : (n.text || '');
    if (S.editing === n.id) { div.contentEditable = 'true'; div.spellcheck = true; }
    fo.appendChild(div);
    if (it && renderCardSteps(n, it, fo)) div.classList.add('has-steps');
    const { fw, fh } = placeParts(n, g);
    if (n.fitText) fitFont(div, fw, fh);
    g.setAttribute('aria-label', (kind === 'inbox' ? 'Tarjeta del Inbox: ' : 'Forma: ') + (div.textContent || 'vacía') + (n.locked ? ' (bloqueada)' : ''));
    g._sig = sigNode(n);
  }
  // «Ajustar texto a la caja»: el mayor tamaño de letra con el que el texto cabe entero
  function fitFont(div, w, h) {
    if (!div.isConnected || !div.textContent) return;
    let lo = 4, hi = Math.max(8, Math.min(400, h));
    for (let i = 0; i < 9; i++) {
      const mid = (lo + hi) / 2;
      div.style.fontSize = mid + 'px';
      if (div.scrollHeight <= h + 0.5 && div.scrollWidth <= w + 0.5) lo = mid; else hi = mid;
    }
    div.style.fontSize = Math.floor(lo * 10) / 10 + 'px';
  }

  function renderEdge(e, g) {
    const geo = edgeGeom(e);
    const color = e.color || LINE_DEFAULTS.color, w = e.width || 2;
    g.setAttribute('class', `edge${S.sel.has(e.id) ? ' is-selected' : ''}${e.locked ? ' is-locked' : ''}`);
    let path = g.querySelector('.edge-line'), hit = g.querySelector('.edge-hit');
    if (!path) { hit = el('path', { class: 'edge-hit' }, g); path = el('path', { class: 'edge-line', fill: 'none' }, g); }
    hit.setAttribute('d', geo.d);
    const sh = eHead(e, 'start'), th = eHead(e, 'end'), dash = eDash(e);
    attrs(path, { d: geo.d, stroke: color, 'stroke-width': w, 'stroke-dasharray': dashArray(dash, w), 'stroke-linecap': 'round',
      'marker-start': sh === 'none' ? null : markerFor(color, sh), 'marker-end': th === 'none' ? null : markerFor(color, th) });
    g.querySelector('.edge-label')?.remove();
    if (e.label) {
      const fs = e.labelSize || 13, lh = fs * 1.25, lines = String(e.label).split('\n');
      const tw = Math.max(...lines.map((l) => measure(l, fs, 500)));
      const lg = el('g', { class: 'edge-label' }, g);
      el('rect', { class: 'edge-label-bg', x: geo.mid.x - tw / 2 - 6, y: geo.mid.y - (lines.length * lh) / 2 - 3, width: tw + 12, height: lines.length * lh + 6, rx: 5 }, lg);
      const t = el('text', { class: 'edge-label-text', 'text-anchor': 'middle', 'font-size': fs, 'font-weight': 500, fill: e.labelColor || '#cdd6f4' }, lg);
      lines.forEach((l, i) => { el('tspan', { x: geo.mid.x, y: geo.mid.y - (lines.length * lh) / 2 + i * lh + lh * 0.78 }, t).textContent = l; });
    }
    g.setAttribute('aria-label', 'Conector' + (e.label ? ': ' + e.label : ''));
    g._sig = sigEdge(e);
  }

  function strokePath(points) {
    if (points.length < 2) return '';
    let d = `M${points[0][0]},${points[0][1]}`;
    for (let i = 1; i < points.length - 1; i++) {
      const [x, y] = points[i], [nx, ny] = points[i + 1];
      d += ` Q${x},${y} ${(x + nx) / 2},${(y + ny) / 2}`;
    }
    const last = points[points.length - 1];
    return d + ` L${last[0]},${last[1]}`;
  }
  function renderStroke(s, g) {
    g.setAttribute('class', `stroke${S.sel.has(s.id) ? ' is-selected' : ''}${s.locked ? ' is-locked' : ''}`);
    let p = g.querySelector('.stroke-line'), hit = g.querySelector('.stroke-hit');
    if (!p) { hit = el('path', { class: 'stroke-hit' }, g); p = el('path', { class: 'stroke-line', fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, g); }
    const d = strokePath(s.points);
    p.setAttribute('d', d); hit.setAttribute('d', d);
    p.setAttribute('stroke', s.color || '#cdd6f4');
    p.setAttribute('stroke-width', s.width || 3);
    g._sig = sigStroke(s);
  }
  function renderEdgesOf(ids) {
    S.doc.edges.forEach((e) => { if (ids.has(e.from) || ids.has(e.to)) renderEdge(e, edgeEls.get(e.id)); });
  }

  /* Selección: cajas, asas, extremos y guías (coordenadas del mundo, tamaño constante en pantalla) */
  function selectedNodes() { return S.doc.nodes.filter((n) => S.sel.has(n.id)); }
  function selectedEdges() { return S.doc.edges.filter((e) => S.sel.has(e.id)); }
  function anchorsOf(n, overlayG, hot) {
    const z = S.view.zoom;
    const out = S.sel.has(n.id) && !n.locked ? 20 / z : 0; // seleccionada: por fuera, para no tapar las asas
    Object.keys(SIDES).forEach((side) => {
      const p = sidePoint(n, side, out);
      el('circle', { cx: p.x, cy: p.y, r: (side === hot ? 7 : 5.5) / z, class: `anchor${side === hot ? ' is-hot' : ''}`, 'data-anchor': n.id, 'data-side': side, 'stroke-width': 1.5 / z }, overlayG);
    });
  }
  function renderOverlay() {
    overlay.innerHTML = '';
    placeProps();
    const z = S.view.zoom, G = S.gesture;
    const nodes = selectedNodes();
    nodes.forEach((n) => el('rect', { x: n.x - 3 / z, y: n.y - 3 / z, width: n.w + 6 / z, height: n.h + 6 / z, class: 'sel-box', 'stroke-width': 1.5 / z }, overlay));
    const locked = nodes.some((n) => n.locked);
    if (nodes.length && !S.editing && !locked) {
      const b = nodes.length === 1 ? nodes[0] : contentBounds(new Set(nodes.map((n) => n.id)));
      if (nodes.length > 1) el('rect', { x: b.x - 8 / z, y: b.y - 8 / z, width: b.w + 16 / z, height: b.h + 16 / z, class: 'sel-group', 'stroke-width': 1 / z }, overlay);
      const hs = 10 / z;
      [['nw', b.x, b.y], ['n', b.x + b.w / 2, b.y], ['ne', b.x + b.w, b.y], ['e', b.x + b.w, b.y + b.h / 2],
        ['se', b.x + b.w, b.y + b.h], ['s', b.x + b.w / 2, b.y + b.h], ['sw', b.x, b.y + b.h], ['w', b.x, b.y + b.h / 2]]
        .forEach(([h, x, y]) => el('rect', { x: x - hs / 2, y: y - hs / 2, width: hs, height: hs, rx: 2 / z, class: `handle handle-${h}`, 'data-handle': h, 'stroke-width': 1.5 / z }, overlay));
    }
    nodes.filter((n) => n.locked).forEach((n) => { // candado en las formas bloqueadas
      const s = 16 / z;
      el('rect', { x: n.x + n.w - s * 0.6, y: n.y - s * 0.4, width: s, height: s, rx: 4 / z, class: 'lock-badge' }, overlay);
      el('use', { href: (document.documentElement.dataset.icons || '/static/icons.svg') + '#i-lock', x: n.x + n.w - s * 0.6 + s * 0.15, y: n.y - s * 0.4 + s * 0.15, width: s * 0.7, height: s * 0.7, class: 'lock-icon' }, overlay);
    });
    // Extremos de un conector seleccionado: se arrastran para reengancharlo o dejarlo libre
    const edges = selectedEdges();
    if (edges.length === 1 && !nodes.length && !edges[0].locked && !(G && G.type !== 'reattach')) {
      const geo = edgeGeom(edges[0]);
      [['s', geo.s], ['t', geo.t]].forEach(([end, p]) => el('circle', { cx: p.x, cy: p.y, r: 6 / z, class: 'endpoint', 'data-endpoint': end, 'stroke-width': 2 / z }, overlay));
    }
    // Puntos de conexión: en la forma bajo el ratón, o en el destino mientras se conecta
    const target = G && (G.type === 'connect' || G.type === 'reattach') ? (G.toNode && node(G.toNode)) : null;
    const hn = target || (!G && S.hover && node(S.hover));
    if (hn && !S.editing && (S.tool === 'select' || S.tool === 'arrow') && !(hn.locked && !target)) {
      if (target) el('rect', { x: hn.x - 4 / z, y: hn.y - 4 / z, width: hn.w + 8 / z, height: hn.h + 8 / z, class: 'connect-target', 'stroke-width': 2 / z }, overlay);
      anchorsOf(hn, overlay, target ? G.toSide : null);
    }
    if (G?.guides) G.guides.forEach((l) => el('line', { ...l, class: 'guide', 'stroke-width': 1 / z }, overlay));
    if (G?.type === 'marquee' && G.rect) el('rect', { ...G.rect, class: 'marquee', 'stroke-width': 1 / z }, overlay);
    if (G?.type === 'connect' && G.to) {
      const fake = { from: G.from, fromSide: G.fromSide, to: G.toNode, toSide: G.toSide, p1: [G.start.x, G.start.y], p2: [G.to.x, G.to.y], ...S.lineDefaults };
      const color = S.lineDefaults.color;
      el('path', { d: edgeGeom(fake).d, class: 'connect-preview', stroke: color, 'stroke-width': 2 / z, 'marker-end': S.lineDefaults.endHead === 'none' ? null : markerFor(color, S.lineDefaults.endHead) }, overlay);
    }
    if (G?.type === 'create' && G.rect) el('rect', { ...G.rect, class: 'create-preview', 'stroke-width': 1.5 / z }, overlay);
    if (G?.type === 'pen' && G.points.length > 1) el('path', { d: strokePath(G.points), class: 'pen-preview', stroke: S.penColor || '#cdd6f4', 'stroke-width': G.width }, overlay);
  }

  /* Minimapa: el contenido se rehace solo si cambia el documento; al desplazar solo se mueve el marco */
  let miniRaf = 0, miniVersion = -1;
  function renderMinimapSoon() { if (!miniRaf) miniRaf = requestAnimationFrame(() => { miniRaf = 0; renderMinimap(); }); }
  function renderMinimap() {
    if (!mini) return;
    mini.hidden = !S.minimap || !S.boardId;
    if (mini.hidden) return;
    if (miniVersion !== S.version) {
      miniVersion = S.version;
      miniWorld.innerHTML = '';
      S.doc.nodes.forEach((n) => el('rect', { x: n.x, y: n.y, width: n.w, height: n.h, rx: 6, fill: style(n, 'stroke') === 'none' ? '#7f849c' : base(style(n, 'stroke')) }, miniWorld));
      mini._bounds = contentBounds();
    }
    const b = mini._bounds, vw = viewBounds();
    const all = b ? { x: Math.min(b.x, vw.x), y: Math.min(b.y, vw.y) } : { x: vw.x, y: vw.y };
    all.w = (b ? Math.max(b.x + b.w, vw.x + vw.w) : vw.x + vw.w) - all.x;
    all.h = (b ? Math.max(b.y + b.h, vw.y + vw.h) : vw.y + vw.h) - all.y;
    const MW = mini.clientWidth || 180, MH = mini.clientHeight || 120;
    const k = Math.min(MW / Math.max(all.w, 1), MH / Math.max(all.h, 1));
    const ox = (MW - all.w * k) / 2 - all.x * k, oy = (MH - all.h * k) / 2 - all.y * k;
    miniWorld.setAttribute('transform', `translate(${ox} ${oy}) scale(${k})`);
    attrs(miniView, { x: vw.x * k + ox, y: vw.y * k + oy, width: vw.w * k, height: vw.h * k });
    mini._map = { k, ox, oy };
  }

  /* ---------- Historial ---------- */
  // Instantánea = cadenas JSON por elemento, compartidas entre instantáneas mientras no cambian
  let pool = new Map();
  const intern = (o) => { const k = JSON.stringify(o); const v = pool.get(k); if (v !== undefined) return v; pool.set(k, k); return k; };
  function snapshot() { return { n: S.doc.nodes.map(intern), e: S.doc.edges.map(intern), s: S.doc.strokes.map(intern) }; }
  function restore(sn) { return { format: 2, nodes: sn.n.map((x) => JSON.parse(x)), edges: sn.e.map((x) => JSON.parse(x)), strokes: sn.s.map((x) => JSON.parse(x)) }; }
  function sameSnap(a, b) { return ['n', 'e', 's'].every((k) => a[k].length === b[k].length && a[k].every((x, i) => x === b[k][i])); }
  function record() { // llamar ANTES de cambiar el documento
    S.past.push(snapshot());
    if (S.past.length > HISTORY_MAX) S.past.shift();
    S.future = [];
  }
  function recordFrom(before) { // el documento ya cambió durante un gesto: registra el estado de antes
    if (sameSnap(before, snapshot())) return false;
    S.past.push(before);
    if (S.past.length > HISTORY_MAX) S.past.shift();
    S.future = [];
    return true;
  }
  function changed() { renderAll(); scheduleSave(); }
  const alive = () => { S.sel = new Set([...S.sel].filter((id) => item(id))); };
  function undo() {
    if (!S.past.length) return;
    S.future.push(snapshot());
    S.doc = restore(S.past.pop());
    alive(); changed();
  }
  function redo() {
    if (!S.future.length) return;
    S.past.push(snapshot());
    S.doc = restore(S.future.pop());
    alive(); changed();
  }

  /* ---------- Guardado ---------- */
  function scheduleSave() {
    if (!S.boardId) return;
    S.dirty = true;
    statusEl.textContent = 'Guardando…';
    clearTimeout(S.saveTimer);
    S.saveTimer = setTimeout(save, 700);
  }
  async function save() {
    if (!S.boardId || !S.dirty) return;
    S.dirty = false;
    try {
      await api(`/api/boards/${S.boardId}/canvas`, { method: 'POST', quiet: true, body: { data: JSON.stringify(S.doc) } });
      statusEl.textContent = 'Guardado';
      setTimeout(() => { if (statusEl.textContent === 'Guardado') statusEl.textContent = ''; }, 1500);
    } catch (err) {
      S.dirty = true;
      statusEl.textContent = 'Sin guardar';
      toast(err?.message || 'No se pudo guardar el tablero', { type: 'error' });
    }
  }
  window.addEventListener('beforeunload', (e) => { if (S.dirty) { save(); e.preventDefault(); } });

  /* ---------- Crear (a tamaño normal en pantalla con cualquier zoom, y siempre a la vista) ---------- */
  function scaled(kind) {
    const d = DEFAULTS[kind], k = 1 / S.view.zoom;
    const out = { w: r1(d.w * k), h: r1(d.h * k) };
    if (Math.abs(k - 1) > 0.001) { out.fontSize = r1(d.fontSize * k); if (d.strokeWidth) out.strokeWidth = r1(d.strokeWidth * k); }
    return out;
  }
  function keepInView(b) { // devuelve el desplazamiento que mete el rectángulo b en la vista
    const v = viewBounds(16);
    if (v.w <= 0 || v.h <= 0) return { dx: 0, dy: 0 };
    const dx = b.w > v.w ? v.x - b.x : b.x < v.x ? v.x - b.x : b.x + b.w > v.x + v.w ? v.x + v.w - b.x - b.w : 0;
    const dy = b.h > v.h ? v.y - b.y : b.y < v.y ? v.y - b.y : b.y + b.h > v.y + v.h ? v.y + v.h - b.y - b.h : 0;
    return { dx, dy };
  }
  function addNode(kind, x, y, extra = {}, snap = S.snap) {
    const n = { id: uid('n'), kind, x, y, ...scaled(kind), text: '', ...extra };
    if (snap) { n.x = snapTo(n.x); n.y = snapTo(n.y); }
    const { dx, dy } = keepInView(n);
    n.x += dx; n.y += dy;
    if (kind === 'container') S.doc.nodes.unshift(n); else S.doc.nodes.push(n); // el contenedor va detrás de lo que contiene
    return n;
  }
  // Con clic va al centro de la vista; soltada (exact) queda centrada donde se suelta, sin saltos
  function insertShape(shape, at = viewCenter(), exact = false) {
    if (!S.boardId) { toast('Crea primero un tablero', { type: 'info' }); return; }
    record();
    if (shape === 'line' || shape === 'arrow') {
      const L = 160 / S.view.zoom;
      const ed = { id: uid('e'), ...S.lineDefaults, width: r1(S.lineDefaults.width / S.view.zoom), p1: [at.x - L / 2, at.y], p2: [at.x + L / 2, at.y], endHead: shape === 'line' ? 'none' : (S.lineDefaults.endHead === 'none' ? 'arrow' : S.lineDefaults.endHead) };
      if (ed.route === 'orthogonal') ed.route = 'straight';
      S.doc.edges.push(ed);
      S.sel = new Set([ed.id]);
      changed();
      document.dispatchEvent(new CustomEvent('board:inserted'));
      return ed;
    }
    const d = scaled(shape);
    const n = addNode(shape, at.x - d.w / 2, at.y - d.h / 2, shape === 'text' ? { text: 'Texto' } : shape === 'container' ? { text: 'Contenedor' } : {}, S.snap && !exact);
    S.sel = new Set([n.id]);
    changed();
    if (shape === 'text') startEdit(n.id);
    document.dispatchEvent(new CustomEvent('board:inserted'));
    return n;
  }

  /* ---------- Editar texto ---------- */
  function startEdit(id) {
    const n = node(id);
    if (!n || n.locked) return;
    S.editing = id;
    S.sel = new Set([id]);
    renderAll();
    const g = nodeEls.get(id), div = g?.querySelector('.node-text');
    if (!div) return;
    div.focus();
    const range = document.createRange();
    range.selectNodeContents(div);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
    const before = snapshot();
    const grow = () => { // ajuste automático: la caja crece con el texto (o la letra se ajusta a la caja)
      const fo = g.querySelector('.node-fo'), fh = +fo.getAttribute('height');
      if (n.fitText) { fitFont(div, +fo.getAttribute('width'), fh); return; }
      if (n.kind === 'container') return;
      const extra = div.scrollHeight - fh;
      if (extra > 0.5) { n.h = Math.ceil((n.h + extra * (shapeOf(n) === 'diamond' ? 2 : shapeOf(n) === 'ellipse' && n.kind === 'text' ? 1.5 : 1)) / 4) * 4; placeParts(n, g); renderEdgesOf(new Set([id])); renderOverlay(); }
    };
    div.addEventListener('input', grow);
    const finish = (commit) => {
      div.removeEventListener('input', grow);
      div.removeEventListener('blur', onBlur);
      div.removeEventListener('keydown', onKey);
      const text = div.innerText.replace(/\n$/, '');
      const h = n.h;
      S.editing = null;
      S.doc = restore(before);
      const m0 = node(id), it = inboxItem(n);
      const old = it ? it.text : n.text || '';
      if (m0?.kind === 'text' && !text.trim()) { // un texto vacío no se queda en el tablero
        S.doc.nodes = S.doc.nodes.filter((x) => x.id !== id);
        S.sel.delete(id);
        changed();
      } else if (commit && m0 && (text !== old || h !== m0.h)) {
        record();
        const m = node(id);
        if (!it) m.text = text;
        m.h = Math.max(m.h, h);
        if (it && text.trim() && text !== old) { m.text = text; saveInboxText(it, text); }
        changed();
      } else renderAll();
      svg.focus({ preventScroll: true });
    };
    const onBlur = () => finish(true);
    const onKey = (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); finish(true); }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); finish(true); }
    };
    div.addEventListener('blur', onBlur);
    div.addEventListener('keydown', onKey);
  }

  function editLabel(id) {
    const e = edge(id);
    if (!e || e.locked) return;
    S.sel = new Set([id]);
    renderAll();
    const geo = edgeGeom(e), r = svg.getBoundingClientRect(), wr = wrap.getBoundingClientRect();
    const ta = document.createElement('textarea');
    ta.className = 'edge-label-editor';
    ta.rows = 1;
    ta.value = e.label || '';
    ta.setAttribute('aria-label', 'Etiqueta del conector');
    ta.placeholder = 'Etiqueta';
    ta.style.left = r.left - wr.left + S.view.x + geo.mid.x * S.view.zoom + 'px';
    ta.style.top = r.top - wr.top + S.view.y + geo.mid.y * S.view.zoom + 'px';
    wrap.appendChild(ta);
    ta.focus(); ta.select();
    let finished = false;
    const done = (commit) => {
      if (finished) return; // quitar el campo provoca un blur: solo se termina una vez
      finished = true;
      const v = ta.value.trim();
      ta.remove();
      const ed = edge(id);
      if (commit && ed && v !== (ed.label || '')) { record(); const m = edge(id); if (v) m.label = v; else delete m.label; changed(); }
      svg.focus({ preventScroll: true });
    };
    ta.addEventListener('keydown', (ev) => {
      ev.stopPropagation();
      if (ev.key === 'Escape') { ev.preventDefault(); done(false); }
      if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); done(true); }
    });
    ta.addEventListener('blur', () => done(true));
  }

  /* ---------- Enlace con el Inbox (en los dos sentidos) ---------- */
  async function saveInboxText(it, text) {
    try { await Items.update(it.id, { text }); } catch (err) { toast(err?.message || 'No se pudo cambiar el elemento', { type: 'error' }); }
  }
  async function toggleInboxDone(nodeId) {
    const n = node(nodeId), it = n && inboxItem(n);
    if (!it) return;
    const done = it.done;
    try {
      await Items.setDone(it.id, !done);
      toast(done ? 'Reabierta' : 'Hecha', { type: 'info', duration: 1400 });
    } catch (err) { toast(err?.message || 'No se pudo cambiar el estado', { type: 'error' }); }
  }

  /* ---------- Selección ---------- */
  function expandGroups(ids) {
    const out = new Set(ids);
    S.doc.nodes.forEach((n) => { if (n.group && [...ids].some((id) => node(id)?.group === n.group)) out.add(n.id); });
    return out;
  }
  function setSelection(ids) {
    S.sel = expandGroups(ids);
    renderAll();
  }
  function hitTarget(target) {
    const g = target.closest?.('[data-id]');
    if (!g || !world.contains(g)) return null;
    const id = g.dataset.id;
    if (node(id)) return { kind: 'node', id };
    if (edge(id)) return { kind: 'edge', id };
    if (stroke(id)) return { kind: 'stroke', id };
    return null;
  }
  function nodeAt(p, exclude) {
    for (let i = S.doc.nodes.length - 1; i >= 0; i--) {
      const n = S.doc.nodes[i];
      if (n.id !== exclude && p.x >= n.x && p.x <= n.x + n.w && p.y >= n.y && p.y <= n.y + n.h) return n;
    }
    return null;
  }
  function nearSide(n, p) {
    let best = null, bd = 18 / S.view.zoom;
    Object.keys(SIDES).forEach((side) => { const q = sidePoint(n, side), d = Math.hypot(q.x - p.x, q.y - p.y); if (d < bd) { bd = d; best = side; } });
    return best;
  }

  /* ---------- Gestos (ratón, lápiz y táctil) ---------- */
  function onPointerDown(e) {
    if (S.editing && e.target.closest('.node-text[contenteditable="true"]')) return;
    e.preventDefault(); // sin selección de texto ni cambio de foco nativo (lo gestionamos aquí)
    if (S.editing) document.activeElement?.blur();
    svg.focus({ preventScroll: true });
    S.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    try { svg.setPointerCapture(e.pointerId); } catch {}
    if (S.pointers.size === 2) { startPinch(); return; }
    if (S.pointers.size > 2) return;
    const p = toWorld(e.clientX, e.clientY);
    const check = e.target.closest('[data-check]');
    if (check && S.tool === 'select') { S.pointers.delete(e.pointerId); toggleInboxDone(check.dataset.check); return; }
    const stepBtn = e.target.closest('[data-step-check], [data-step-hide], [data-step-show], [data-step-hide-all]');
    if (stepBtn && S.tool === 'select') { S.pointers.delete(e.pointerId); if (!stepBtn.disabled) stepAction(stepBtn); return; }
    const handle = e.target.closest('[data-handle]');
    const anchor = e.target.closest('[data-anchor]');
    const endpoint = e.target.closest('[data-endpoint]');
    const hit = hitTarget(e.target);
    const touch = e.pointerType === 'touch';
    // Doble clic/toque propio: el nativo se pierde porque la forma se repinta al seleccionarla
    const now = performance.now(), last = S.lastDown;
    S.lastDown = { t: now, id: hit?.id || null, x: e.clientX, y: e.clientY };
    if (last && now - last.t < 420 && last.id === (hit?.id || null) && Math.hypot(e.clientX - last.x, e.clientY - last.y) < 8 && S.tool === 'select' && !handle && !anchor && !endpoint) {
      S.lastDown = null;
      S.pointers.delete(e.pointerId);
      onDblClick(e, hit);
      return;
    }

    if (e.button === 1 || S.tool === 'hand' || S.space) return startPan(e);
    if (S.tool === 'pen') { S.gesture = { type: 'pen', points: [[p.x, p.y]], width: r1((S.penWidth || 3) / S.view.zoom) }; return; }
    if (S.tool === 'eraser') { S.gesture = { type: 'erase', before: snapshot() }; eraseAt(e); return; }
    if (DEFAULTS[S.tool] && !hit) { S.gesture = { type: 'create', kind: S.tool, start: p, rect: null }; return; }
    if (endpoint) {
      const ed = selectedEdges()[0];
      S.gesture = { type: 'reattach', id: ed.id, end: endpoint.dataset.endpoint, before: snapshot(), toNode: null, toSide: null };
      return;
    }
    if (S.tool === 'arrow' || anchor) {
      const from = anchor ? anchor.dataset.anchor : (hit?.kind === 'node' ? hit.id : null);
      S.gesture = { type: 'connect', from, fromSide: anchor?.dataset.side || null, start: anchor ? sidePoint(node(from), anchor.dataset.side) : p, to: p, toNode: null, toSide: null };
      return;
    }
    if (handle) return startResize(handle.dataset.handle, p);
    if (hit) {
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        const next = new Set(S.sel);
        const ids = expandGroups(new Set([hit.id]));
        const on = next.has(hit.id);
        ids.forEach((id) => (on ? next.delete(id) : next.add(id)));
        S.sel = next;
        renderAll();
        return;
      }
      if (!S.sel.has(hit.id)) setSelection(new Set([hit.id]));
      startMove(p);
      return;
    }
    // Vacío: en táctil desplaza, con ratón selecciona por área
    if (touch) return startPan(e);
    if (!e.shiftKey) setSelection(new Set());
    S.gesture = { type: 'marquee', start: p, rect: null, base: new Set(S.sel) };
  }

  function startMove(p) {
    const orig = { nodes: {}, strokes: {}, edges: {} };
    const free = (x) => S.sel.has(x.id) && !x.locked;
    S.doc.nodes.forEach((n) => { if (free(n)) orig.nodes[n.id] = { x: n.x, y: n.y }; });
    // Un contenedor arrastra lo que tiene dentro
    S.doc.nodes.filter((c) => c.kind === 'container' && orig.nodes[c.id]).forEach((c) => {
      S.doc.nodes.forEach((n) => { if (!orig.nodes[n.id] && !n.locked && n.x >= c.x && n.y >= c.y && n.x + n.w <= c.x + c.w && n.y + n.h <= c.y + c.h) orig.nodes[n.id] = { x: n.x, y: n.y }; });
      S.doc.strokes.forEach((s) => { if (!s.locked && s.points.every(([x, y]) => x >= c.x && y >= c.y && x <= c.x + c.w && y <= c.y + c.h)) S.sel.has(s.id) || (orig.strokes[s.id] = clone(s.points)); });
    });
    S.doc.strokes.forEach((s) => { if (free(s)) orig.strokes[s.id] = clone(s.points); });
    S.doc.edges.forEach((e) => { if (free(e)) orig.edges[e.id] = { p1: e.p1 && [...e.p1], p2: e.p2 && [...e.p2] }; });
    const ids = new Set(Object.keys(orig.nodes));
    if (!ids.size && !Object.keys(orig.strokes).length && !Object.keys(orig.edges).length) { S.gesture = null; return; }
    const edgeIds = S.doc.edges.filter((e) => ids.has(e.from) || ids.has(e.to) || orig.edges[e.id]).map((e) => e.id);
    // Guías inteligentes: bordes y centros de las demás formas
    const box = ids.size ? (() => { let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity; ids.forEach((id) => { const n = node(id); x1 = Math.min(x1, n.x); y1 = Math.min(y1, n.y); x2 = Math.max(x2, n.x + n.w); y2 = Math.max(y2, n.y + n.h); }); return { x: x1, y: y1, w: x2 - x1, h: y2 - y1 }; })() : null;
    const cands = { x: [], y: [] };
    if (box) S.doc.nodes.forEach((n) => {
      if (ids.has(n.id)) return;
      [n.x, n.x + n.w / 2, n.x + n.w].forEach((v) => cands.x.push({ v, a: n.y, b: n.y + n.h }));
      [n.y, n.y + n.h / 2, n.y + n.h].forEach((v) => cands.y.push({ v, a: n.x, b: n.x + n.w }));
    });
    S.gesture = { type: 'move', start: p, before: snapshot(), orig, ids, edgeIds, box, cands, moved: false, guides: null };
  }
  function guideSnap(G, dx, dy) {
    const T = GUIDE_PX / S.view.zoom, b = G.box;
    const best = (axis, d) => {
      const mv = axis === 'x' ? [b.x + d, b.x + b.w / 2 + d, b.x + b.w + d] : [b.y + d, b.y + b.h / 2 + d, b.y + b.h + d];
      let hit = null;
      G.cands[axis].forEach((c) => mv.forEach((m) => { const diff = c.v - m; if (Math.abs(diff) < T && (!hit || Math.abs(diff) < Math.abs(hit.diff))) hit = { diff, c }; }));
      return hit;
    };
    const hx = best('x', dx), hy = best('y', dy);
    if (hx) dx += hx.diff;
    if (hy) dy += hy.diff;
    const guides = [];
    if (hx) { const y1 = Math.min(hx.c.a, b.y + dy), y2 = Math.max(hx.c.b, b.y + b.h + dy); guides.push({ x1: hx.c.v, x2: hx.c.v, y1: y1 - 12, y2: y2 + 12 }); }
    if (hy) { const x1 = Math.min(hy.c.a, b.x + dx), x2 = Math.max(hy.c.b, b.x + b.w + dx); guides.push({ x1: x1 - 12, x2: x2 + 12, y1: hy.c.v, y2: hy.c.v }); }
    return { dx, dy, gx: !!hx, gy: !!hy, guides };
  }

  function startPan(e) {
    S.gesture = { type: 'pan', sx: e.clientX, sy: e.clientY, vx: S.view.x, vy: S.view.y };
    wrap.classList.add('is-panning');
  }
  function startPinch() {
    const [a, b] = [...S.pointers.values()];
    S.gesture = { type: 'pinch', d0: Math.hypot(a.x - b.x, a.y - b.y), c0: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, v0: { ...S.view } };
  }
  function startResize(h, p) {
    const nodes = selectedNodes();
    const box = nodes.length === 1 ? { x: nodes[0].x, y: nodes[0].y, w: nodes[0].w, h: nodes[0].h } : contentBounds(new Set(nodes.map((n) => n.id)));
    S.gesture = { type: 'resize', h, start: p, box, before: snapshot(), orig: nodes.map((n) => ({ id: n.id, x: n.x, y: n.y, w: n.w, h: n.h, fs: style(n, 'fontSize'), set: n.fontSize !== undefined })) };
  }

  function onPointerMove(e) {
    if (S.pointers.has(e.pointerId)) S.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const G = S.gesture;
    const p = toWorld(e.clientX, e.clientY);
    if (!G) { // hover: muestra los puntos de conexión
      const n = nodeAt(p);
      const id = n?.id || null;
      if (id !== S.hover && !e.target.closest('[data-anchor]')) { S.hover = id; renderOverlay(); }
      return;
    }
    if (G.type === 'pinch') {
      const [a, b] = [...S.pointers.values()];
      if (!b) return;
      const d = Math.hypot(a.x - b.x, a.y - b.y), c = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const r = svg.getBoundingClientRect();
      const z = clamp(G.v0.zoom * d / G.d0, MIN_ZOOM, MAX_ZOOM);
      const wx = (G.c0.x - r.left - G.v0.x) / G.v0.zoom, wy = (G.c0.y - r.top - G.v0.y) / G.v0.zoom;
      S.view = { zoom: z, x: c.x - r.left - wx * z, y: c.y - r.top - wy * z };
      applyView(); renderOverlay();
      return;
    }
    if (G.type === 'pan') {
      S.view.x = G.vx + (e.clientX - G.sx);
      S.view.y = G.vy + (e.clientY - G.sy);
      applyView(); renderOverlay();
      return;
    }
    if (G.type === 'move') {
      let dx = p.x - G.start.x, dy = p.y - G.start.y;
      if (!G.moved && Math.hypot(dx, dy) * S.view.zoom < 3) return;
      G.moved = true;
      G.guides = null;
      if (!e.altKey && G.box) { // Alt: sin guías ni cuadrícula
        const g = guideSnap(G, dx, dy);
        dx = g.dx; dy = g.dy; G.guides = g.guides;
        if (S.snap) { // la cuadrícula se aplica a la primera forma en el eje sin guía
          const o = G.orig.nodes[G.ids.values().next().value];
          if (!g.gx) dx = snapTo(o.x + dx) - o.x;
          if (!g.gy) dy = snapTo(o.y + dy) - o.y;
        }
      }
      for (const [id, o] of Object.entries(G.orig.nodes)) { const n = node(id), g = nodeEls.get(id); n.x = o.x + dx; n.y = o.y + dy; g.setAttribute('transform', `translate(${n.x} ${n.y})`); g._sig = null; }
      for (const [id, pts] of Object.entries(G.orig.strokes)) { const s = stroke(id); s.points = pts.map(([x, y]) => [x + dx, y + dy]); renderStroke(s, strokeEls.get(id)); }
      for (const [id, o] of Object.entries(G.orig.edges)) { const ed = edge(id); if (o.p1) ed.p1 = [o.p1[0] + dx, o.p1[1] + dy]; if (o.p2) ed.p2 = [o.p2[0] + dx, o.p2[1] + dy]; }
      G.edgeIds.forEach((id) => renderEdge(edge(id), edgeEls.get(id))); // conectores en tiempo real
      renderOverlay();
      return;
    }
    if (G.type === 'resize') {
      const { box, h } = G;
      let x1 = box.x, y1 = box.y, x2 = box.x + box.w, y2 = box.y + box.h;
      const px = S.snap && !e.altKey ? snapTo(p.x) : p.x, py = S.snap && !e.altKey ? snapTo(p.y) : p.y;
      const minW = 30 / S.view.zoom, minH = 24 / S.view.zoom;
      if (h.includes('w')) x1 = Math.min(px, x2 - minW);
      if (h.includes('e')) x2 = Math.max(px, x1 + minW);
      if (h.includes('n')) y1 = Math.min(py, y2 - minH);
      if (h.includes('s')) y2 = Math.max(py, y1 + minH);
      if (e.shiftKey && h.length === 2) { // proporcional
        const k = Math.max((x2 - x1) / box.w, (y2 - y1) / box.h);
        if (h.includes('w')) x1 = x2 - box.w * k; else x2 = x1 + box.w * k;
        if (h.includes('n')) y1 = y2 - box.h * k; else y2 = y1 + box.h * k;
      }
      const sx = (x2 - x1) / box.w, sy = (y2 - y1) / box.h;
      G.orig.forEach((o) => {
        const n = node(o.id);
        n.x = x1 + (o.x - box.x) * sx; n.y = y1 + (o.y - box.y) * sy;
        n.w = Math.max(minW, o.w * sx); n.h = Math.max(minH, o.h * sy);
        // Por una esquina, el texto escala con la forma (por un lado solo se recoloca)
        if (h.length === 2 && !n.fitText) { const fs = r1(clamp(o.fs * Math.min(sx, sy), 4, 400)); if (o.set || Math.abs(fs - o.fs) > 0.05) n.fontSize = fs; }
        renderNode(n, nodeEls.get(o.id));
      });
      renderEdgesOf(new Set(G.orig.map((o) => o.id)));
      renderOverlay();
      return;
    }
    if (G.type === 'marquee') {
      const x = Math.min(G.start.x, p.x), y = Math.min(G.start.y, p.y), w = Math.abs(p.x - G.start.x), hgt = Math.abs(p.y - G.start.y);
      G.rect = { x, y, width: w, height: hgt };
      const inside = new Set(G.base);
      S.doc.nodes.forEach((n) => { if (n.x < x + w && n.x + n.w > x && n.y < y + hgt && n.y + n.h > y) inside.add(n.id); });
      S.doc.strokes.forEach((s) => { if (s.points.some(([px2, py2]) => px2 >= x && px2 <= x + w && py2 >= y && py2 <= y + hgt)) inside.add(s.id); });
      S.doc.edges.forEach((ed) => { if (!ed.from && !ed.to && [ed.p1, ed.p2].every((q) => q && q[0] >= x && q[0] <= x + w && q[1] >= y && q[1] <= y + hgt)) inside.add(ed.id); });
      S.sel = expandGroups(inside);
      S.doc.nodes.forEach((n) => nodeEls.get(n.id)?.classList.toggle('is-selected', S.sel.has(n.id)));
      renderOverlay();
      return;
    }
    if (G.type === 'connect' || G.type === 'reattach') {
      const ed = G.type === 'reattach' ? edge(G.id) : null;
      const other = ed ? (G.end === 's' ? ed.to : ed.from) : G.from;
      const target = nodeAt(p, other);
      G.to = p;
      G.toNode = target ? target.id : null;
      G.toSide = target ? nearSide(target, p) : null;
      if (ed) {
        const [k, pk] = G.end === 's' ? ['from', 'p1'] : ['to', 'p2'];
        if (target) { ed[k] = target.id; if (G.toSide) ed[k + 'Side'] = G.toSide; else delete ed[k + 'Side']; delete ed[pk]; }
        else { delete ed[k]; delete ed[k + 'Side']; ed[pk] = [p.x, p.y]; }
        renderEdge(ed, edgeEls.get(ed.id));
      }
      renderOverlay();
      return;
    }
    if (G.type === 'create') {
      const x = Math.min(G.start.x, p.x), y = Math.min(G.start.y, p.y);
      G.rect = { x, y, width: Math.abs(p.x - G.start.x), height: Math.abs(p.y - G.start.y) };
      renderOverlay();
      return;
    }
    if (G.type === 'pen') {
      const last = G.points[G.points.length - 1];
      if (Math.hypot(p.x - last[0], p.y - last[1]) * S.view.zoom > 2) G.points.push([r1(p.x), r1(p.y)]);
      renderOverlay();
      return;
    }
    if (G.type === 'erase') eraseAt(e);
  }

  function eraseAt(e) {
    const t = document.elementFromPoint(e.clientX, e.clientY);
    const hit = t && hitTarget(t);
    if (!hit || item(hit.id)?.locked) return;
    removeIds(new Set([hit.id]), false);
    renderAll();
  }

  function onPointerUp(e) {
    S.pointers.delete(e.pointerId);
    const G = S.gesture;
    if (!G) return;
    if (G.type === 'pinch') { if (S.pointers.size < 2) S.gesture = null; return; }
    S.gesture = null;
    wrap.classList.remove('is-panning');
    const p = toWorld(e.clientX, e.clientY);
    if (G.type === 'move' || G.type === 'resize' || G.type === 'reattach' || G.type === 'erase') {
      if (recordFrom(G.before)) changed(); else renderAll();
      return;
    }
    if (G.type === 'marquee') { renderAll(); return; }
    if (G.type === 'connect') {
      const target = G.toNode && node(G.toNode);
      const far = Math.hypot(p.x - G.start.x, p.y - G.start.y) * S.view.zoom > 12;
      if ((!target && !far) || (target && G.from === target.id)) { renderOverlay(); return; }
      record();
      const ed = { id: uid('e'), ...S.lineDefaults, width: r1(S.lineDefaults.width / S.view.zoom) };
      if (G.from) { ed.from = G.from; if (G.fromSide) ed.fromSide = G.fromSide; } else ed.p1 = [G.start.x, G.start.y];
      if (target) { ed.to = target.id; if (G.toSide) ed.toSide = G.toSide; } else ed.p2 = [p.x, p.y];
      S.doc.edges.push(ed);
      S.sel = new Set([ed.id]);
      changed();
      if (S.tool === 'arrow' && !S.lockTool) setTool('select');
      return;
    }
    if (G.type === 'create') {
      record();
      const big = G.rect && G.rect.width * S.view.zoom > 12 && G.rect.height * S.view.zoom > 12;
      const d = scaled(G.kind);
      const n = big ? addNode(G.kind, G.rect.x, G.rect.y, { w: Math.max(40 / S.view.zoom, G.rect.width), h: Math.max(30 / S.view.zoom, G.rect.height) })
        : addNode(G.kind, G.start.x - d.w / 2, G.start.y - d.h / 2);
      if (S.snap && big) { n.w = Math.max(GRID * 2, snapTo(n.w)); n.h = Math.max(GRID, snapTo(n.h)); }
      changed();
      if (!S.lockTool) setTool('select');
      startEdit(n.id);
      return;
    }
    if (G.type === 'pen') {
      if (G.points.length > 1) {
        record();
        S.doc.strokes.push({ id: uid('s'), points: G.points, color: S.penColor || '#cdd6f4', width: G.width });
        changed();
      } else renderOverlay();
    }
  }

  function onDblClick(e, hit = hitTarget(e.target)) {
    if (hit?.kind === 'node') { startEdit(hit.id); return; }
    if (hit?.kind === 'edge') { editLabel(hit.id); return; }
    if (!hit && S.tool === 'select') { // doble clic en vacío: un cuadro de texto
      const p = toWorld(e.clientX, e.clientY);
      const d = scaled('text');
      record();
      const n = addNode('text', p.x - 12 / S.view.zoom, p.y - d.h / 2);
      changed();
      startEdit(n.id);
    }
  }

  function onWheel(e) {
    e.preventDefault();
    if (e.ctrlKey || e.metaKey) zoomAt(e.clientX, e.clientY, Math.pow(0.998, e.deltaY * (e.deltaMode === 1 ? 20 : 1)));
    else { S.view.x -= e.deltaX; S.view.y -= e.deltaY; applyView(); renderOverlay(); }
  }

  /* ---------- Operaciones sobre la selección ---------- */
  function removeIds(ids, withRecord = true) {
    ids = new Set([...ids].filter((id) => !item(id)?.locked));
    if (!ids.size) { if (withRecord && S.sel.size) toast('Lo seleccionado está bloqueado', { type: 'info' }); return; }
    if (withRecord) record();
    S.doc.nodes = S.doc.nodes.filter((n) => !ids.has(n.id));
    S.doc.strokes = S.doc.strokes.filter((s) => !ids.has(s.id));
    S.doc.edges = S.doc.edges.filter((e) => !ids.has(e.id) && !ids.has(e.from) && !ids.has(e.to));
    S.sel = new Set([...S.sel].filter((id) => !ids.has(id)));
    if (withRecord) changed();
  }
  function selectionPayload() {
    const ids = S.sel;
    return clone({
      nodes: S.doc.nodes.filter((n) => ids.has(n.id)),
      strokes: S.doc.strokes.filter((s) => ids.has(s.id)),
      edges: S.doc.edges.filter((e) => ids.has(e.id) || (ids.has(e.from) && ids.has(e.to))),
    });
  }
  // Inserta una copia con identificadores nuevos centrada en `at`. scale: para que una plantilla
  // se vea a tamaño normal con cualquier zoom; inView: la mete en lo visible.
  function insertPayload(payload, at, { scale = 1, inView = false } = {}) {
    const map = {};
    const b = contentBoundsOf(payload);
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2;
    let dx = at ? at.x - cx : 0, dy = at ? at.y - cy : 0;
    if (inView) { const k = keepInView({ x: cx + dx - (b.w * scale) / 2, y: cy + dy - (b.h * scale) / 2, w: b.w * scale, h: b.h * scale }); dx += k.dx; dy += k.dy; }
    const tx = (x) => cx + (x - cx) * scale + dx, ty = (y) => cy + (y - cy) * scale + dy;
    const groups = {};
    record();
    const fresh = new Set();
    payload.nodes.forEach((n) => {
      const id = uid('n'); map[n.id] = id; fresh.add(id);
      const copy = { ...n, id, x: tx(n.x), y: ty(n.y), w: n.w * scale, h: n.h * scale };
      if (scale !== 1) { copy.fontSize = r1(style(n, 'fontSize') * scale); copy.strokeWidth = r1(style(n, 'strokeWidth') * scale); }
      if (n.group) copy.group = groups[n.group] ||= uid('g');
      if (n.kind === 'container') S.doc.nodes.unshift(copy); else S.doc.nodes.push(copy);
    });
    payload.strokes.forEach((s) => { const id = uid('s'); fresh.add(id); S.doc.strokes.push({ ...s, id, width: r1((s.width || 3) * scale), points: s.points.map(([x, y]) => [tx(x), ty(y)]) }); });
    payload.edges.forEach((e) => {
      if ((e.from && !map[e.from]) || (e.to && !map[e.to])) return;
      const id = uid('e'); fresh.add(id);
      const copy = { ...e, id, width: r1((e.width || 2) * scale) };
      if (e.from) copy.from = map[e.from]; else delete copy.from;
      if (e.to) copy.to = map[e.to]; else delete copy.to;
      if (e.p1) copy.p1 = [tx(e.p1[0]), ty(e.p1[1])];
      if (e.p2) copy.p2 = [tx(e.p2[0]), ty(e.p2[1])];
      S.doc.edges.push(copy);
    });
    S.sel = fresh;
    changed();
    return fresh.size;
  }
  function contentBoundsOf(p) {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    const add = (x, y) => { x1 = Math.min(x1, x); y1 = Math.min(y1, y); x2 = Math.max(x2, x); y2 = Math.max(y2, y); };
    p.nodes.forEach((n) => { add(n.x, n.y); add(n.x + n.w, n.y + n.h); });
    p.strokes.forEach((s) => s.points.forEach(([x, y]) => add(x, y)));
    p.edges.forEach((e) => [e.p1, e.p2].forEach((pt) => pt && add(pt[0], pt[1])));
    return x1 === Infinity ? { x: 0, y: 0, w: 0, h: 0 } : { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
  }
  function viewCenter() {
    const r = svg.getBoundingClientRect();
    return toWorld(r.left + r.width / 2, r.top + r.height / 2);
  }
  function copy() {
    if (!S.sel.size) return;
    S.clipboard = selectionPayload();
    S.pasteCount = 0;
    try { localStorage.setItem('board-clipboard', JSON.stringify(S.clipboard)); } catch {}
    toast('Copiado', { type: 'info', duration: 1200 });
  }
  function paste() {
    let payload = S.clipboard;
    if (!payload) { try { payload = JSON.parse(localStorage.getItem('board-clipboard') || 'null'); } catch {} }
    if (!payload) return;
    S.pasteCount++;
    const b = contentBoundsOf(payload);
    insertPayload(payload, { x: b.x + b.w / 2 + 24 * S.pasteCount, y: b.y + b.h / 2 + 24 * S.pasteCount });
  }
  function duplicate() {
    if (!S.sel.size) return;
    const payload = selectionPayload();
    const b = contentBoundsOf(payload);
    insertPayload(payload, { x: b.x + b.w / 2 + GRID * 2, y: b.y + b.h / 2 + GRID * 2 });
  }
  function nudge(dx, dy) {
    const free = (x) => S.sel.has(x.id) && !x.locked;
    if (![...S.doc.nodes, ...S.doc.strokes, ...S.doc.edges].some(free)) return;
    record();
    S.doc.nodes.forEach((n) => { if (free(n)) { n.x += dx; n.y += dy; } });
    S.doc.strokes.forEach((s) => { if (free(s)) s.points = s.points.map(([x, y]) => [x + dx, y + dy]); });
    S.doc.edges.forEach((e) => { if (free(e)) { if (e.p1) e.p1 = [e.p1[0] + dx, e.p1[1] + dy]; if (e.p2) e.p2 = [e.p2[0] + dx, e.p2[1] + dy]; } });
    changed();
  }
  function group() {
    const nodes = selectedNodes();
    if (nodes.length < 2) { toast('Selecciona al menos dos formas para agrupar', { type: 'info' }); return; }
    record();
    const gid = uid('g');
    nodes.forEach((n) => { n.group = gid; });
    changed();
    toast('Agrupadas: se mueven juntas', { type: 'info', duration: 1600 });
  }
  function ungroup() {
    const nodes = selectedNodes().filter((n) => n.group);
    if (!nodes.length) return;
    record();
    nodes.forEach((n) => { delete n.group; });
    changed();
  }
  function align(how) {
    const nodes = selectedNodes().filter((n) => !n.locked);
    if (nodes.length < 2) { toast('Selecciona al menos dos formas sin bloquear', { type: 'info' }); return; }
    const b = contentBounds(new Set(nodes.map((n) => n.id)));
    record();
    nodes.forEach((n) => {
      if (how === 'left') n.x = b.x;
      if (how === 'center') n.x = b.x + b.w / 2 - n.w / 2;
      if (how === 'right') n.x = b.x + b.w - n.w;
      if (how === 'top') n.y = b.y;
      if (how === 'middle') n.y = b.y + b.h / 2 - n.h / 2;
      if (how === 'bottom') n.y = b.y + b.h - n.h;
    });
    changed();
  }
  function distribute(axis) {
    const nodes = selectedNodes().filter((n) => !n.locked);
    if (nodes.length < 3) { toast('Selecciona al menos tres formas para distribuir', { type: 'info' }); return; }
    record();
    const pos = axis === 'h' ? 'x' : 'y', size = axis === 'h' ? 'w' : 'h';
    nodes.sort((a, b) => a[pos] - b[pos]);
    const first = nodes[0], last = nodes[nodes.length - 1];
    const total = nodes.reduce((acc, n) => acc + n[size], 0);
    const gap = (last[pos] + last[size] - first[pos] - total) / (nodes.length - 1);
    let cur = first[pos];
    nodes.forEach((n) => { n[pos] = cur; cur += n[size] + gap; });
    changed();
  }

  // Cambia una propiedad en toda la selección (panel de propiedades). Lo de los conectores
  // y el lápiz se recuerda para los siguientes.
  function setProp(prop, value) {
    const nodes = selectedNodes(), edges = selectedEdges(), strokes = S.doc.strokes.filter((s) => S.sel.has(s.id));
    if (!nodes.length && !edges.length && !strokes.length) { // sin selección: valores para lo próximo que se dibuje
      if (prop === 'stroke') { S.lineDefaults.color = value; S.penColor = value; }
      if (prop === 'pen') S.penColor = value;
      if (['route', 'startHead', 'endHead', 'dash'].includes(prop)) S.lineDefaults[prop] = value;
      renderProps();
      return;
    }
    record();
    const all = [...nodes, ...edges, ...strokes];
    if (prop === 'locked') { const on = !all.every((x) => x.locked); all.forEach((x) => { if (on) x.locked = true; else delete x.locked; }); changed(); return; }
    nodes.forEach((n) => {
      if (prop === 'fill') n.fill = value === 'none' ? 'none' : n.kind === 'sticky' || n.kind === 'inbox' ? value : value + '33';
      if (prop === 'stroke') { n.stroke = value; if (value !== 'none' && !style(n, 'strokeWidth')) n.strokeWidth = r1(2 / S.view.zoom); }
      if (prop === 'color') n.color = value;
      if (prop === 'strokeWidth') n.strokeWidth = +value;
      if (prop === 'dash') { if (value === 'solid') delete n.dash; else n.dash = value; }
      if (prop === 'fontSize') n.fontSize = clamp(+value || style(n, 'fontSize'), 4, 400);
      if (prop === 'fitText') { if (value) n.fitText = true; else delete n.fitText; }
      if (prop === 'frame' && n.kind === 'text') {
        if (value === 'none') delete n.frame;
        else {
          // primera vez con marco: borde y relleno suaves para que se vea (luego se cambian con lo de siempre)
          if (!n.frame && style(n, 'stroke') === 'none' && style(n, 'fill') === 'none') {
            n.stroke = '#89b4fa'; n.fill = '#89b4fa26'; n.strokeWidth = r1(2 / S.view.zoom);
          }
          n.frame = value;
          // el texto queda dentro: la caja crece si se queda corta para la forma
          if (value === 'diamond' || value === 'ellipse') { n.h = Math.max(n.h, Math.round(n.w * (value === 'diamond' ? 0.6 : 0.5))); }
        }
      }
    });
    edges.forEach((e) => {
      if (prop === 'stroke' && value !== 'none') e.color = value;
      if (prop === 'color') e.labelColor = value;
      if (prop === 'strokeWidth') e.width = +value;
      if (prop === 'dash') { e.dash = value; delete e.dashed; }
      if (prop === 'route') e.route = value;
      if (prop === 'startHead') e.startHead = value;
      if (prop === 'endHead') { e.endHead = value; delete e.head; }
      if (prop === 'label') { if (String(value).trim()) e.label = String(value).trim(); else delete e.label; }
      if (prop === 'reverse') { [e.from, e.to] = [e.to, e.from]; [e.fromSide, e.toSide] = [e.toSide, e.fromSide]; [e.p1, e.p2] = [e.p2, e.p1]; Object.keys(e).forEach((k) => e[k] === undefined && delete e[k]); }
    });
    strokes.forEach((s) => {
      if (prop === 'stroke' && value !== 'none') s.color = value;
      if (prop === 'strokeWidth') s.width = +value;
    });
    if (prop === 'stroke' && value !== 'none') { S.lineDefaults.color = value; S.penColor = value; }
    if (edges.length && ['strokeWidth', 'dash', 'route', 'startHead', 'endHead'].includes(prop)) S.lineDefaults[prop === 'strokeWidth' ? 'width' : prop] = prop === 'strokeWidth' ? +value * S.view.zoom : value;
    changed();
  }
  // Compatibilidad: colores por destino (tests y atajos)
  function applyColor(target, color) { setProp({ fill: 'fill', stroke: 'stroke', text: 'color', pen: 'pen' }[target], color); }
  function copyStyle() {
    const n = selectedNodes()[0];
    const e = !n && selectedEdges()[0];
    if (!n && !e) { toast('Selecciona una forma o un conector', { type: 'info' }); return; }
    S.style = n ? { kind: 'node', fill: style(n, 'fill'), stroke: style(n, 'stroke'), color: style(n, 'color'), fontSize: style(n, 'fontSize'), strokeWidth: style(n, 'strokeWidth'), dash: n.dash }
      : { kind: 'edge', stroke: e.color, width: e.width, dash: eDash(e), route: eRoute(e), startHead: eHead(e, 'start'), endHead: eHead(e, 'end') };
    toast('Estilo copiado', { type: 'info', duration: 1200 });
  }
  function pasteStyle() {
    if (!S.style || !S.sel.size) return;
    const st = S.style;
    record();
    S.doc.nodes.forEach((n) => {
      if (!S.sel.has(n.id)) return;
      if (st.kind === 'node') { ['fill', 'stroke', 'color', 'fontSize', 'strokeWidth'].forEach((k) => { if (st[k] != null) n[k] = st[k]; }); if (st.dash) n.dash = st.dash; else delete n.dash; }
      else if (st.stroke) n.stroke = st.stroke;
    });
    S.doc.edges.forEach((e) => {
      if (!S.sel.has(e.id)) return;
      if (st.stroke && st.stroke !== 'none') e.color = base(st.stroke);
      if (st.kind === 'edge') { Object.assign(e, { width: st.width, dash: st.dash, route: st.route, startHead: st.startHead, endHead: st.endHead }); delete e.dashed; delete e.head; }
    });
    changed();
  }
  function bringTo(front) {
    if (!S.sel.size) return;
    record();
    const sel = S.doc.nodes.filter((n) => S.sel.has(n.id)), rest = S.doc.nodes.filter((n) => !S.sel.has(n.id));
    S.doc.nodes = front ? [...rest, ...sel] : [...sel, ...rest];
    changed();
  }

  /* ---------- Panel de propiedades (contextual) ---------- */
  function common(values) { const s = new Set(values); return s.size === 1 ? [...s][0] : undefined; }
  function renderProps() {
    if (!props) return;
    const nodes = selectedNodes(), edges = selectedEdges(), strokes = S.doc.strokes.filter((s) => S.sel.has(s.id));
    const mode = S.propsMode, open = mode === 'sheet' ? S.sheetOpen : S.propsOpen;
    const some = S.sel.size > 0 && !S.editing;
    const show = open && (mode === 'docked' || some); // acoplado se ve siempre; flotante y hoja, solo con selección
    $('#btnProps')?.setAttribute('aria-pressed', String(open));
    if (!show) { props.hidden = true; props._key = ''; return; }
    const key = some ? JSON.stringify([nodes, edges, strokes, !!S.style]) : 'vacío' + JSON.stringify(S.lineDefaults) + S.editing;
    props.hidden = false;
    if (key === props._key) return;
    props._key = key;
    const focusKey = props.contains(document.activeElement) ? document.activeElement.dataset.focusKey : null;
    props.innerHTML = some ? propsHtml(nodes, edges, strokes) : emptyPropsHtml();
    if (focusKey) props.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`)?.focus();
    placeProps();
  }
  // Flotante, el panel nunca tapa lo seleccionado: si la selección queda debajo, pasa al otro lado
  function placeProps() {
    if (!props || props.hidden || S.propsMode !== 'float') return;
    const b = contentBounds(S.sel);
    if (!b) return;
    const r = svg.getBoundingClientRect(), z = S.view.zoom;
    const sel = { l: r.left + S.view.x + b.x * z, r: r.left + S.view.x + (b.x + b.w) * z };
    const w = props.offsetWidth + 24;
    const hitsRight = sel.r > r.right - w, hitsLeft = sel.l < r.left + w;
    const left = props.classList.contains('at-left');
    if (!left && hitsRight && !hitsLeft) props.classList.add('at-left');
    else if (left && hitsLeft && !hitsRight) props.classList.remove('at-left');
  }
  function emptyPropsHtml() {
    const d = S.lineDefaults;
    return `<header class="props-head"><h2>Propiedades</h2>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="close" aria-label="Cerrar el panel de propiedades" title="Cerrar">${icon('x', 'icon-sm')}</button></header>
      <p class="props-empty">${S.editing ? 'Termina de escribir (Esc) para cambiar el estilo.' : 'Selecciona una forma, un conector o un trazo para cambiar su estilo.'}</p>
      <section class="props-sec"><h3>Conectores nuevos</h3>${swatchRow('stroke', d.color, false)}
        <div class="props-row"><span class="props-label">Enrutado</span>${segRow('route', ROUTES, d.route, 'Enrutado')}</div>
        <div class="props-row"><span class="props-label">Tipo</span>${segRow('dash', DASHES, d.dash, 'Tipo de línea')}</div>
        <div class="props-grid">${headSelect('startHead', d.startHead, 'Inicio')}${headSelect('endHead', d.endHead, 'Fin')}</div></section>`;
  }
  function swatchRow(prop, current, allowNone) {
    const b = (hex, name, extra = '') => `<button type="button" class="swatch${extra}" data-prop="${prop}" data-value="${hex}" data-focus-key="${prop}:${hex}" style="--c:${hex}" aria-label="${name}" title="${name}" aria-pressed="${current === hex}"></button>`;
    return `<div class="swatches">${allowNone ? b('none', 'Sin color', ' swatch-none') : ''}${PALETTE.map(([name, hex]) => b(hex, name)).join('')}</div>`;
  }
  const dashIcon = (v) => `<svg class="dash-icon" viewBox="0 0 30 10" aria-hidden="true"><path d="M2 5 H28" stroke="currentColor" stroke-width="2" stroke-linecap="round" ${v === 'dashed' ? 'stroke-dasharray="6 4"' : v === 'dotted' ? 'stroke-dasharray="0 4.5"' : ''}/></svg>`;
  function segRow(prop, options, current, label) {
    const inner = (v, text, ic) => (prop === 'dash' ? dashIcon(v) + `<span class="sr-only">${text}</span>` : ic ? icon(ic, 'icon-sm') + `<span class="sr-only">${text}</span>` : text);
    return `<div class="segmented props-seg" role="group" aria-label="${label}">${options.map(([v, text, ic]) =>
      `<button type="button" data-prop="${prop}" data-value="${v}" data-focus-key="${prop}:${v}" aria-pressed="${String(current) === String(v)}" title="${text}">${inner(v, text, ic)}</button>`).join('')}</div>`;
  }
  function headSelect(prop, current, label) {
    return `<label class="props-field"><span>${label}</span><select class="select input-sm" data-prop="${prop}" data-focus-key="${prop}">${current === undefined ? '<option value="" selected>Varias</option>' : ''}${HEADS.map(([v, t]) => `<option value="${v}"${current === v ? ' selected' : ''}>${t}</option>`).join('')}</select></label>`;
  }
  function propsHtml(nodes, edges, strokes) {
    const count = nodes.length + edges.length + strokes.length;
    const lines = [...edges, ...strokes];
    let h = `<header class="props-head"><h2>${count === 1 ? (nodes.length ? 'Forma' : edges.length ? 'Conector' : 'Trazo') : count + ' elementos'}</h2>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="close" aria-label="Cerrar el panel de propiedades" title="Cerrar">${icon('x', 'icon-sm')}</button></header>`;
    if (nodes.length) h += `<section class="props-sec"><h3>Relleno</h3>${swatchRow('fill', common(nodes.map((n) => base(style(n, 'fill')))), true)}</section>`;
    const strokeVals = [...nodes.map((n) => base(style(n, 'stroke'))), ...edges.map((e) => e.color || LINE_DEFAULTS.color), ...strokes.map((s) => s.color || '#cdd6f4')];
    const widthVals = [...nodes.map((n) => style(n, 'strokeWidth')), ...edges.map((e) => e.width || 2), ...strokes.map((s) => s.width || 3)];
    const dashVals = [...nodes.map((n) => n.dash || 'solid'), ...edges.map(eDash)];
    h += `<section class="props-sec"><h3>${nodes.length && !lines.length ? 'Borde' : lines.length && !nodes.length ? 'Línea' : 'Borde y línea'}</h3>${swatchRow('stroke', common(strokeVals), nodes.length > 0 && !lines.length)}
      <div class="props-row"><span class="props-label">Grosor</span>${segRow('strokeWidth', WIDTHS.map((w) => [w, String(w)]), common(widthVals), 'Grosor')}</div>
      ${dashVals.length ? `<div class="props-row"><span class="props-label">Tipo</span>${segRow('dash', DASHES.map(([v, t]) => [v, t]), common(dashVals), 'Tipo de línea')}</div>` : ''}</section>`;
    if (nodes.length && nodes.every((n) => n.kind === 'text')) {
      const cur = common(nodes.map((n) => n.frame || 'none'));
      h += `<section class="props-sec"><h3>Marco</h3><div class="segmented props-seg props-frames" role="group" aria-label="Marco del texto">${FRAMES.map(([v, t]) =>
        `<button type="button" data-prop="frame" data-value="${v}" data-focus-key="frame:${v}" aria-pressed="${cur === v}" title="${t}">${v === 'none' ? icon('type', 'icon-sm') : shapeIcon(v)}<span class="sr-only">${t}</span></button>`).join('')}</div></section>`;
    }
    if (nodes.length) {
      const fs = common(nodes.map((n) => style(n, 'fontSize')));
      const fit = nodes.every((n) => n.fitText);
      h += `<section class="props-sec"><h3>Texto</h3>${swatchRow('color', common(nodes.map((n) => style(n, 'color'))), false)}
        <div class="props-row"><span class="props-label">Tamaño</span><div class="stepper">
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="font-dec" aria-label="Letra más pequeña" ${fit ? 'disabled' : ''}>${icon('minus', 'icon-sm')}</button>
          <input type="number" class="input input-sm tabular" min="4" max="400" step="1" data-prop="fontSize" data-focus-key="fontSize" aria-label="Tamaño de letra" value="${fs !== undefined ? Math.round(fs * 10) / 10 : ''}" placeholder="—" ${fit ? 'disabled' : ''}>
          <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="font-inc" aria-label="Letra más grande" ${fit ? 'disabled' : ''}>${icon('plus', 'icon-sm')}</button></div></div>
        <label class="props-check"><input type="checkbox" data-prop="fitText" data-focus-key="fitText" ${fit ? 'checked' : ''}> Ajustar texto a la caja</label></section>`;
    }
    if (edges.length) {
      const one = edges.length === 1 ? edges[0] : null;
      h += `<section class="props-sec"><h3>Conector</h3>
        <div class="props-row"><span class="props-label">Enrutado</span>${segRow('route', ROUTES, common(edges.map(eRoute)), 'Enrutado')}</div>
        <div class="props-grid">${headSelect('startHead', common(edges.map((e) => eHead(e, 'start'))), 'Inicio')}${headSelect('endHead', common(edges.map((e) => eHead(e, 'end'))), 'Fin')}</div>
        ${one ? `<label class="props-field"><span>Etiqueta</span><input type="text" class="input input-sm" maxlength="200" data-prop="label" data-focus-key="label" value="${escapeHtml(one.label || '')}" placeholder="Doble clic en el conector"></label>` : ''}
        <button type="button" class="btn btn-sm" data-act="reverse">${icon('arrow-left-right', 'icon-sm')}Invertir sentido</button></section>`;
    }
    const locked = [...nodes, ...edges, ...strokes].every((x) => x.locked);
    h += `<section class="props-sec props-actions">
      <button type="button" class="btn btn-sm" data-act="lock" aria-pressed="${locked}" data-focus-key="lock">${icon(locked ? 'lock' : 'lock-open', 'icon-sm')}${locked ? 'Desbloquear' : 'Bloquear'}</button>
      <button type="button" class="btn btn-sm" data-act="copy-style">${icon('copy', 'icon-sm')}Copiar estilo</button>
      <button type="button" class="btn btn-sm" data-act="paste-style" ${S.style ? '' : 'disabled'}>${icon('replace', 'icon-sm')}Pegar estilo</button>
      ${nodes.length ? `<button type="button" class="btn btn-sm" data-act="front">${icon('bring-to-front', 'icon-sm')}Al frente</button>
      <button type="button" class="btn btn-sm" data-act="back">${icon('send-to-back', 'icon-sm')}Al fondo</button>` : ''}</section>`;
    return h;
  }
  function wireProps() {
    props.addEventListener('click', (ev) => {
      const b = ev.target.closest('button');
      if (!b || b.disabled) return;
      if (b.dataset.prop) { setProp(b.dataset.prop, b.dataset.value); return; }
      const act = b.dataset.act;
      if (act === 'close') { setPropsOpen(false); svg.focus({ preventScroll: true }); }
      if (act === 'lock') setProp('locked');
      if (act === 'reverse') setProp('reverse');
      if (act === 'copy-style') { copyStyle(); props._key = ''; renderProps(); }
      if (act === 'paste-style') pasteStyle();
      if (act === 'front' || act === 'back') bringTo(act === 'front');
      if (act === 'font-dec' || act === 'font-inc') {
        const f = selectedNodes().map((n) => style(n, 'fontSize'));
        if (!f.length) return;
        const steps = [8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64, 80, 96, 128];
        const cur = Math.max(...f), z = S.view.zoom, screen = cur * z;
        const next = act === 'font-inc' ? steps.find((s) => s > screen + 0.5) ?? screen * 1.25 : [...steps].reverse().find((s) => s < screen - 0.5) ?? screen / 1.25;
        setProp('fontSize', r1(next / z));
      }
    });
    props.addEventListener('change', (ev) => {
      const t = ev.target;
      if (!t.dataset.prop || (t.tagName === 'SELECT' && !t.value)) return;
      setProp(t.dataset.prop, t.type === 'checkbox' ? t.checked : t.value);
    });
    props.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') { ev.stopPropagation(); svg.focus({ preventScroll: true }); } });
  }
  // En hoja (tablero estrecho) el panel solo se abre a petición y no se recuerda
  function setPropsOpen(on) {
    if (S.propsMode === 'sheet') S.sheetOpen = on;
    else { S.propsOpen = on; try { localStorage.setItem('board-props', on ? 'open' : 'closed'); } catch {} }
    renderProps();
  }
  const propsOpenNow = () => (S.propsMode === 'sheet' ? S.sheetOpen : S.propsOpen);

  /* ---------- Paleta («Plantilla» en el panel lateral) y plantillas ---------- */
  const BUILTIN = [
    { name: 'Tarea con pasos', build: () => tpl([['rect', 0, 0, 220, 60, 'Objetivo', '#94e2d5'], ['rect', 0, 100, 220, 50, 'Paso 1'], ['rect', 0, 170, 220, 50, 'Paso 2'], ['rect', 0, 240, 220, 50, 'Paso 3']], [[0, 1], [1, 2], [2, 3]]) },
    { name: 'Pros y contras', build: () => tpl([['rect', 0, 0, 220, 50, 'Pros', '#a6e3a1'], ['rect', 260, 0, 220, 50, 'Contras', '#f38ba8'], ['sticky', 0, 70, 220, 160, ''], ['sticky', 260, 70, 220, 160, '']], []) },
    { name: 'Decisión', build: () => tpl([['diamond', 120, 0, 200, 110, '¿Decisión?', '#cba6f7'], ['rect', 0, 180, 180, 70, 'Sí', '#a6e3a1'], ['rect', 260, 180, 180, 70, 'No', '#f38ba8']], [[0, 1, 'Sí'], [0, 2, 'No']], 'orthogonal') },
    { name: 'Columnas Por hacer / Haciendo / Hecho', build: () => tpl([['container', 0, 0, 220, 320, 'Por hacer', '#89b4fa'], ['container', 240, 0, 220, 320, 'Haciendo', '#f9e2af'], ['container', 480, 0, 220, 320, 'Hecho', '#a6e3a1']], []) },
    { name: 'Diagrama de flujo', build: () => tpl([['ellipse', 40, 0, 160, 70, 'Inicio', '#a6e3a1'], ['box', 30, 120, 180, 70, 'Proceso'], ['diamond', 30, 240, 180, 110, '¿Condición?', '#f9e2af'], ['ellipse', 40, 410, 160, 70, 'Fin', '#f38ba8']], [[0, 1], [1, 2], [2, 3, 'Sí']], 'orthogonal') },
    { name: 'Nota adhesiva', build: () => tpl([['sticky', 0, 0, 180, 160, '']], []) },
    // Para desarrollar (también como tablero de una tarea, desde su menú)
    { name: 'Proyecto (versiones y estado)', build: () => buildItemDoc(null, 'proyecto') },
    { name: 'Plan de ejecución', build: () => buildItemDoc(null, 'plan') },
    { name: 'Estudio de un tema', build: () => buildItemDoc(null, 'estudio') },
    // Rutinas: un flujo con hora y duraciones, y un día repartido en mañana, tarde y noche
    { name: 'Rutina por pasos', build: () => tpl([['ellipse', 20, 0, 180, 64, 'Empieza · 07:30', '#cba6f7'], ['rect', 0, 110, 220, 56, 'Paso 1 · 10 min'],
      ['rect', 0, 196, 220, 56, 'Paso 2 · 15 min'], ['rect', 0, 282, 220, 56, 'Paso 3 · 5 min'], ['ellipse', 20, 384, 180, 64, 'Hecha', '#a6e3a1']],
    [[0, 1], [1, 2], [2, 3], [3, 4]]) },
    { name: 'Día por rutinas (mañana, tarde y noche)', build: () => tpl([['container', 0, 0, 230, 300, 'Mañana', '#f9e2af'], ['rect', 15, 50, 200, 50, '07:30 · Despertar'],
      ['rect', 15, 115, 200, 50, '08:00 · Desayuno'], ['container', 250, 0, 230, 300, 'Tarde', '#fab387'], ['rect', 265, 50, 200, 50, '17:00 · Estudio'],
      ['rect', 265, 115, 200, 50, '19:00 · Gimnasio'], ['container', 500, 0, 230, 300, 'Noche', '#cba6f7'], ['rect', 515, 50, 200, 50, '21:00 · Cena'],
      ['rect', 515, 115, 200, 50, '23:00 · Leer']], []) },
  ];
  function tpl(nodes, links, route) {
    const ns = nodes.map(([kind, x, y, w, h, text, color]) => {
      const n = { id: uid('n'), kind, x, y, w, h, text };
      if (color) { n.stroke = color; n.fill = kind === 'sticky' ? color : color + '33'; }
      return n;
    });
    return { nodes: ns, strokes: [], edges: links.map(([a, b, label]) => ({ id: uid('e'), from: ns[a].id, to: ns[b].id, color: '#89b4fa', width: 2, endHead: 'arrow', ...(route ? { route } : {}), ...(label ? { label } : {}) })) };
  }
  let myTemplates = [];
  async function loadTemplates() {
    try { myTemplates = (await api('/api/board-templates', { quiet: true })).templates; } catch { myTemplates = []; }
    renderTemplateList();
  }
  function templatePayload(key) {
    if (key.startsWith('b')) return BUILTIN[+key.slice(1)]?.build();
    const t = myTemplates.find((x) => String(x.id) === key.slice(1));
    try { return t && JSON.parse(t.data); } catch { return null; }
  }
  function insertTemplate(key, at = viewCenter()) {
    const payload = templatePayload(key);
    if (!payload || !S.boardId) { if (!S.boardId) toast('Crea primero un tablero', { type: 'info' }); return; }
    payload.edges ||= []; payload.strokes ||= [];
    insertPayload(payload, at, { scale: 1 / S.view.zoom, inView: true });
    document.dispatchEvent(new CustomEvent('board:inserted'));
  }
  /* ---------- Rutinas en el tablero ---------- */
  // Una rutina de verdad como flujo: cabecera con su hora y duración y sus pasos como tarjetas
  // enlazadas (se marcan desde el tablero: marcar el último marca la rutina)
  async function insertRoutine() {
    if (!S.boardId) { toast('Crea primero un tablero', { type: 'info' }); return; }
    await Items.ready();
    const rutinas = Items.state.items.filter((i) => i.type === 'rutina' && !i.parent_id);
    if (!rutinas.length) { toast('Aún no tienes rutinas: crea una desde «Plantillas» en el grupo Rutinas', { type: 'info' }); return; }
    const picked = await uiPick({ title: 'Poner una rutina en el tablero', placeholder: 'Busca una rutina',
      load: () => rutinas.map((r) => ({ id: r.id, label: r.text.split('\n')[0], sub: `${r.repeat_text || 'Cada día'}${r.due_time ? ` · ${r.due_time}` : ''} · ${Items.children(r.id).length} pasos`, icon: 'repeat' })) });
    if (!picked) return;
    const r = Items.get(picked.id), steps = Items.children(r.id);
    const mins = steps.reduce((a, k) => a + (k.duration_min || 0), 0);
    const head = { id: uid('n'), kind: 'rect', x: 0, y: 0, w: 240, h: 64, stroke: TYPE_COLORS.rutina, fill: TYPE_COLORS.rutina + '33',
      text: `${r.text.split('\n')[0]}${r.due_time ? ` · ${r.due_time}` : ''}${mins ? ` · ${mins} min` : ''}` };
    const d = DEFAULTS.inbox;
    const nodes = [head, ...steps.map((k, i) => ({ id: uid('n'), kind: 'inbox', x: 10, y: 100 + i * (d.h + 30), w: d.w, h: d.h, text: k.text,
      inboxId: k.id, itemType: 'rutina', parentLabel: r.text.split('\n')[0], stroke: TYPE_COLORS.rutina }))];
    const edges = nodes.slice(1).map((n, i) => ({ id: uid('e'), from: nodes[i].id, to: n.id, color: '#cba6f7', width: 2, endHead: 'arrow' }));
    insertPayload({ nodes, strokes: [], edges }, viewCenter(), { scale: 1 / S.view.zoom, inView: true });
    document.dispatchEvent(new CustomEvent('board:inserted'));
  }
  /* ---------- Tablero de una tarea ---------- */
  // Una tarea o idea puede tener su propio tablero (boards.item_id): se crea desde una plantilla con la
  // tarea y sus pasos como tarjetas vivas (se marcan desde el tablero) y se abre desde su menú.
  const ITEM_TEMPLATES = [
    { key: 'proyecto', label: 'Proyecto', sub: 'Ideas, por hacer, en curso y hecho; versiones v0.1, v0.2… con cambios y errores', icon: 'git-branch' },
    { key: 'plan', label: 'Plan de ejecución', sub: 'Objetivo, pasos en orden, comprobación y decisiones', icon: 'workflow' },
    { key: 'estudio', label: 'Estudio de un tema', sub: 'Temario, conceptos clave, dudas, recursos y resumen', icon: 'graduation-cap' },
    { key: 'vacio', label: 'Solo la tarea y sus pasos', sub: 'En una columna, para empezar en limpio', icon: 'list-checks' },
  ];
  // it = la tarea (o null: la plantilla suelta, con pasos de ejemplo)
  function buildItemDoc(it, key) {
    const d = DEFAULTS.inbox, color = it ? TYPE_COLORS[it.type] || TYPE_COLORS.tarea : '#94e2d5';
    const title = it ? it.text.split('\n')[0] : { proyecto: 'Proyecto', plan: 'Objetivo', estudio: 'Tema' }[key] || 'Tarea';
    const steps = it ? Items.children(it.id) : [];
    const nodes = [], edges = [];
    const N = (kind, x, y, w, h, text, c, extra = {}) => {
      const n = { id: uid('n'), kind, x, y, w, h, text, ...(c ? { stroke: c, fill: kind === 'sticky' ? c : c + '33' } : {}), ...extra };
      if (kind === 'container') nodes.unshift(n); else nodes.push(n);
      return n;
    };
    const E = (a, b, label, route) => edges.push({ id: uid('e'), from: a.id, to: b.id, color: '#89b4fa', width: 2, endHead: 'arrow', ...(label ? { label } : {}), ...(route ? { route } : {}) });
    const head = it ? N('inbox', 0, 0, 300, d.h, it.text, null, { inboxId: it.id, itemType: it.type, stroke: color }) : N('rect', 0, 0, 300, 70, title, color);
    // los pasos: tarjetas vivas de la tarea, o rectángulos de ejemplo en la plantilla suelta
    const stepNode = (k, i, x, y) => (k ? N('inbox', x, y, d.w, d.h, k.text, null, { inboxId: k.id, itemType: k.type, parentLabel: title, stroke: color })
      : N('rect', x, y, d.w, 56, `Paso ${i + 1}`));
    const list = steps.length ? steps : [null, null, null];
    const stepH = (k) => (k ? d.h : 56);
    const column = (x, y0, gap = 24) => { let y = y0; return list.map((k, i) => { const n = stepNode(k, i, x, y); y += stepH(k) + gap; return n; }); };
    const colH = list.reduce((a, k) => a + stepH(k) + 16, 0) + 70;

    if (key === 'proyecto') {
      const H = Math.max(320, colH), y = 140;
      const cols = [['Ideas', '#fab387'], ['Por hacer', '#89b4fa'], ['En curso', '#f9e2af'], ['Hecho', '#a6e3a1']];
      cols.forEach(([t, c], i) => N('container', i * 260, y, 240, H, t, c));
      let yTodo = y + 50, yDone = y + 50;
      list.forEach((k, i) => {
        if (k?.done) { stepNode(k, i, 3 * 260 + 10, yDone); yDone += stepH(k) + 16; }
        else { stepNode(k, i, 260 + 10, yTodo); yTodo += stepH(k) + 16; }
      });
      N('sticky', 10, y + 50, 220, 120, 'Ideas sueltas…', '#fab387');
      const yv = y + H + 70;
      N('text', 0, yv - 62, 300, 52, 'Versiones', null, { fontSize: 20 });
      const vs = [['v0.1 · lo mínimo que funciona', '#89b4fa'], ['v0.2 · mejoras', '#89b4fa'], ['v1.0 · estable', '#a6e3a1']]
        .map(([t, c], i) => N('rect', i * 260, yv, 220, 70, t, c));
      vs.slice(1).forEach((v, i) => E(vs[i], v));
      N('sticky', 0, yv + 110, 380, 170, 'Cambios\n· ', '#f9e2af');
      N('sticky', 410, yv + 110, 380, 170, 'Errores conocidos\n· ', '#f38ba8');
    } else if (key === 'plan') {
      const ns = column(40, 130);
      E(head, ns[0]); ns.slice(1).forEach((n, i) => E(ns[i], n));
      const last = ns[ns.length - 1], yq = last.y + last.h + 50;
      const q = N('diamond', 40, yq, 220, 110, '¿Funciona?', '#f9e2af');
      const ok = N('ellipse', 60, yq + 170, 180, 64, 'Hecho', '#a6e3a1');
      const fix = N('rect', 330, yq + 20, 200, 70, 'Ajustar y repetir', '#f38ba8');
      E(last, q); E(q, ok, 'Sí'); E(q, fix, 'No'); E(fix, ns[0], 'repetir', 'orthogonal');
      N('container', 600, 0, 300, 300, 'Decisiones', '#cba6f7');
      N('sticky', 620, 50, 260, 120, 'Qué decidí y por qué…', '#cba6f7');
      N('container', 600, 330, 300, 240, 'Riesgos y dudas', '#f38ba8');
    } else if (key === 'estudio') {
      const H = Math.max(300, colH), y = 140;
      N('container', 0, y, 240, H, 'Temario', '#89b4fa');
      column(10, y + 50, 16);
      [['Conceptos clave', '#94e2d5', 'Definiciones, fórmulas…'], ['Dudas', '#f38ba8', '¿…?'], ['Recursos', '#cba6f7', 'Apuntes, libros, vídeos, enlaces']]
        .forEach(([t, c, hint], i) => { const x = (i + 1) * 260; N('container', x, y, 240, H, t, c); N('sticky', x + 10, y + 50, 220, 130, hint, c); });
      N('sticky', 0, y + H + 40, 1000, 160, 'Resumen en mis palabras…', '#f9e2af');
    } else {
      const ns = column(20, 130);
      E(head, ns[0]); ns.slice(1).forEach((n, i) => E(ns[i], n));
    }
    return { nodes, strokes: [], edges };
  }
  async function openForItem(id) {
    await Items.ready();
    const it = Items.get(id);
    if (!it) { toast('Esa tarea ya no existe', { type: 'info' }); return; }
    const own = S.boards.find((b) => b.item_id === id);
    if (own) { await switchBoard(own.id); document.dispatchEvent(new CustomEvent('board:inserted')); return; }
    const title = it.text.split('\n')[0];
    const picked = await uiPick({ title: `Tablero de «${title.slice(0, 60)}»`, placeholder: 'Elige cómo empezar', confirmLabel: 'Crear el tablero',
      load: () => ITEM_TEMPLATES.map((t) => ({ id: t.key, label: t.label, sub: t.sub, icon: t.icon })) });
    if (!picked) return;
    let r;
    try {
      r = await api('/api/boards', { method: 'POST', body: { name: title.slice(0, 200), item_id: id, data: JSON.stringify({ format: 2, ...buildItemDoc(it, picked.id) }) } });
    } catch { return; }
    if (!S.boards.some((b) => b.id === r.id)) S.boards.unshift({ id: r.id, name: title, item_id: id });
    try { localStorage.removeItem('board-view:' + r.id); } catch {}
    await switchBoard(r.id);
    document.dispatchEvent(new CustomEvent('board:inserted'));  // en móvil, la hoja se aparta para verlo
    toast(`Tablero de «${title.slice(0, 40)}» creado`);
  }
  // Lo seleccionado (de arriba abajo) pasa a ser una rutina con esos pasos («Ducha · 10 min» → 10 min)
  async function routineFromSelection() {
    const sel = S.doc.nodes.filter((n) => S.sel.has(n.id) && n.kind !== 'container' && (inboxItem(n)?.text || n.text || '').trim())
      .sort((a, b) => (a.y - b.y) || (a.x - b.x));
    // las elipses son el inicio y el fin del flujo: no son pasos, pero la hora del inicio es la de la rutina
    const marks = sel.filter((n) => n.kind === 'ellipse'), ns = sel.filter((n) => n.kind !== 'ellipse');
    const time = marks.map((n) => (n.text || '').match(/\b([01]?\d|2[0-3]):([0-5]\d)\b/)).find(Boolean);
    if (!ns.length) { toast('Selecciona en el tablero las formas que serán los pasos (de arriba abajo)', { type: 'info' }); return; }
    const texts = ns.map((n) => (inboxItem(n)?.text || n.text).split('\n')[0].trim().replace(/\s*·\s*(\d+\s*(min|h))\s*$/i, ' $1'));
    const due = time ? `${time[1].padStart(2, '0')}:${time[2]}` : '';
    const name = (await uiPrompt('Crear una rutina con la selección', { label: 'Nombre de la rutina', value: 'Mi rutina', confirmLabel: 'Crear',
      message: `${texts.length} paso${texts.length === 1 ? '' : 's'}: ${texts.slice(0, 4).join(' · ')}${texts.length > 4 ? '…' : ''}${due ? `, empieza a las ${due}` : ''}. Se repite cada día; cámbialo luego en Tareas.` }))?.trim();
    if (!name) return;
    try {
      const { id } = await api('/api/items', { method: 'POST', body: { text: name, type: 'rutina', ...(due ? { due_time: due } : {}) } });
      for (const t of texts) await api('/api/items', { method: 'POST', body: { text: t, parent_id: id }, quiet: true });
    } catch { return; }
    await Items.load();
    toast(`Rutina «${name}» creada con ${texts.length} pasos`);
  }

  function shapeIcon(kind) {
    const a = 'fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"';
    const body = {
      box: `<rect x="5" y="6" width="30" height="18" ${a}/>`,
      rect: `<rect x="5" y="6" width="30" height="18" rx="5" ${a}/>`,
      ellipse: `<ellipse cx="20" cy="15" rx="15" ry="9.5" ${a}/>`,
      diamond: `<path d="M20 3 L35 15 L20 27 L5 15 Z" ${a}/>`,
      sticky: `<path d="M8 5 H32 V19 L26 25 H8 Z M26 25 V19 H32" ${a}/>`,
      text: `<text x="20" y="21" text-anchor="middle" font-size="15" font-weight="700" fill="currentColor">Aa</text>`,
      container: `<rect x="4" y="4" width="32" height="22" rx="3" ${a}/><path d="M4 10 H36" ${a}/>`,
      line: `<path d="M6 24 L34 6" ${a}/>`,
      arrow: `<path d="M6 24 L33 7 M25 6.5 L33 7 L30 14.5" ${a}/>`,
    }[kind];
    return `<svg class="shape-icon" viewBox="0 0 40 30" aria-hidden="true">${body}</svg>`;
  }
  const tileA11y = 'role="button" tabindex="0" aria-roledescription="forma" aria-description="Intro para añadirla en el centro del tablero; arrástrala para colocarla donde quieras"';
  function renderPalette() {
    const pal = $('#shapePalette');
    if (!pal) return;
    pal.innerHTML = SHAPES.map(([k, label]) => `<div class="shape-tile" data-shape="${k}" ${tileA11y} aria-label="${label}" title="${label}: clic para añadir, arrastra para colocar">${shapeIcon(k)}<span>${label}</span></div>`).join('');
    Sortable.create(pal, { group: 'board-palette', items: '.shape-tile', keyboard: false, label: 'Formas', accepts: () => 'Suelta la forma en el tablero', onDrop() {} });
    $('#templateSave')?.addEventListener('click', saveTemplate);
    $('#routineToBoard')?.addEventListener('click', insertRoutine);
    $('#routineFromSel')?.addEventListener('click', routineFromSelection);
    for (const list of [pal, $('#templateList')]) {
      if (!list) continue;
      list.addEventListener('click', (ev) => {
        const del = ev.target.closest('[data-del-template]');
        if (del) { ev.stopPropagation(); deleteTemplate(+del.dataset.delTemplate); return; }
        activateTile(ev.target.closest('.shape-tile, .tpl-tile'));
      });
      list.addEventListener('keydown', (ev) => {
        if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.matches('.shape-tile, .tpl-tile')) { ev.preventDefault(); activateTile(ev.target); }
      });
    }
  }
  function activateTile(t) {
    if (!t) return;
    if (t.dataset.shape) insertShape(t.dataset.shape);
    else if (t.dataset.template) insertTemplate(t.dataset.template);
  }
  function renderTemplateList() {
    const list = $('#templateList');
    if (!list) return;
    const row = (key, name, mine) => `<div class="tpl-tile" data-template="${key}" ${tileA11y.replace('forma', 'plantilla')} aria-label="Plantilla ${escapeHtml(name)}">
      ${icon(mine ? 'bookmark' : 'layout-grid', 'icon-sm')}<span class="grow">${escapeHtml(name)}</span>
      ${mine ? `<button type="button" class="btn btn-ghost btn-icon btn-sm tpl-del" data-del-template="${key.slice(1)}" aria-label="Borrar la plantilla ${escapeHtml(name)}" title="Borrar">${icon('trash-2', 'icon-sm')}</button>` : ''}</div>`;
    list.innerHTML = myTemplates.map((t) => row('u' + t.id, t.name, true)).join('') + BUILTIN.map((t, i) => row('b' + i, t.name, false)).join('');
    Sortable.create(list, { group: 'board-palette', items: '.tpl-tile', keyboard: false, label: 'Plantillas', accepts: () => 'Suelta la plantilla en el tablero', onDrop() {} });
  }
  function openTemplates(anchor) {
    const items = BUILTIN.map((t, i) => ({ label: t.name, icon: 'layout-grid', onClick: () => insertTemplate('b' + i) }));
    if (myTemplates.length) items.push({ separator: true }, ...myTemplates.map((t) => ({ label: t.name, icon: 'bookmark', onClick: () => insertTemplate('u' + t.id) })));
    items.push({ separator: true }, { label: 'Poner una rutina en el tablero…', icon: 'repeat', onClick: insertRoutine },
      { label: 'Crear una rutina con la selección…', icon: 'list-checks', onClick: routineFromSelection },
      { separator: true }, { label: 'Guardar la selección como plantilla', icon: 'save', onClick: saveTemplate });
    openMenu(anchor, items, { align: 'start' });
  }
  async function saveTemplate() {
    if (!S.sel.size) { toast('Selecciona primero lo que quieres guardar', { type: 'info' }); return; }
    const name = (await uiPrompt('Guardar como plantilla', { label: 'Nombre', confirmLabel: 'Guardar' }))?.trim();
    if (!name) return;
    await api('/api/board-templates', { method: 'POST', body: { name, data: JSON.stringify(selectionPayload()) } });
    toast('Plantilla guardada en «Mis plantillas»');
    loadTemplates();
  }
  async function deleteTemplate(id) {
    const t = myTemplates.find((x) => x.id === id);
    if (!t || !(await uiConfirm(`¿Borrar la plantilla «${t.name}»?`, 'Lo que ya insertaste en los tableros no cambia.', { confirmLabel: 'Borrar', danger: true }))) return;
    await api(`/api/board-templates/${id}`, { method: 'DELETE' });
    toast('Plantilla borrada');
    loadTemplates();
  }

  /* ---------- Exportar (PNG, SVG, JSON) e importar JSON ---------- */
  function exportSvg() {
    const b0 = contentBounds();
    if (!b0) return null;
    let x1 = b0.x, y1 = b0.y, x2 = b0.x + b0.w, y2 = b0.y + b0.h;
    S.doc.edges.forEach((e) => { edgeGeom(e).pts.forEach((p) => { x1 = Math.min(x1, p.x); y1 = Math.min(y1, p.y); x2 = Math.max(x2, p.x); y2 = Math.max(y2, p.y); }); });
    const pad = 32;
    x1 -= pad; y1 -= pad; x2 += pad; y2 += pad;
    const bg = getComputedStyle(wrap).backgroundColor;
    const out = document.createElementNS(NS, 'svg');
    attrs(out, { xmlns: NS, viewBox: `${x1} ${y1} ${x2 - x1} ${y2 - y1}`, width: Math.round(x2 - x1), height: Math.round(y2 - y1), 'font-family': getComputedStyle(document.body).fontFamily });
    el('rect', { x: x1, y: y1, width: x2 - x1, height: y2 - y1, fill: bg }, out);
    const d = el('defs', {}, out);
    defs.querySelectorAll('marker').forEach((m) => d.appendChild(m.cloneNode(true)));
    const prevSel = S.sel, prevEdit = S.editing;
    S.sel = new Set(); S.editing = null;
    renderAll(); // sin resaltado de selección
    for (const layer of [layers.strokes, layers.edges, layers.nodes]) {
      const c = layer.cloneNode(true);
      const origs = [...layer.querySelectorAll('*')], copies = [...c.querySelectorAll('*')];
      copies.forEach((n, i) => {
        const o = origs[i], cls = n.getAttribute('class') || '';
        if (/edge-hit|stroke-hit|node-check-hit/.test(cls)) { n.remove(); return; }
        if (/node-parent|edge-label-bg/.test(cls)) { const cs = getComputedStyle(o); n.setAttribute('fill', cs.fill); if (cls.includes('node-parent')) n.setAttribute('font-style', cs.fontStyle); }
        if (n.tagName === 'foreignObject') n.replaceWith(foToText(n, o.firstChild));
      });
      c.querySelectorAll('[data-id]').forEach((g) => { g.removeAttribute('data-id'); g.removeAttribute('class'); });
      out.appendChild(c);
    }
    S.sel = prevSel; S.editing = prevEdit;
    renderAll();
    return new XMLSerializer().serializeToString(out);
  }
  // El texto vive en foreignObject (HTML); al exportar pasa a <text> con sus líneas medidas,
  // así el SVG es autónomo y el PNG no queda «manchado» para el lienzo
  function foToText(fo, div) {
    const cs = getComputedStyle(div), fs = parseFloat(cs.fontSize), lh = fs * 1.3, weight = cs.fontWeight;
    const x = +fo.getAttribute('x'), y = +fo.getAttribute('y'), w = +fo.getAttribute('width'), h = +fo.getAttribute('height');
    const start = div.classList.contains('align-start') || div.classList.contains('align-title');
    const vcenter = !div.classList.contains('align-start');
    const lines = wrapLines(div.textContent || '', w, fs, weight).slice(0, Math.max(1, Math.floor((h + 1) / lh)));
    const top = vcenter ? y + (h - lines.length * lh) / 2 : y;
    const t = el('text', { 'font-size': fs, 'font-weight': weight, fill: cs.color, 'text-anchor': start ? 'start' : 'middle',
      'text-decoration': cs.textDecorationLine !== 'none' ? cs.textDecorationLine : null, opacity: cs.opacity !== '1' ? cs.opacity : null });
    lines.forEach((l, i) => { el('tspan', { x: start ? x : x + w / 2, y: top + i * lh + (lh - fs) / 2 + fs * 0.82 }, t).textContent = l; });
    return t;
  }
  function fileName(ext) {
    const b = S.boards.find((x) => x.id === S.boardId);
    return ((b?.name || 'tablero').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '').toLowerCase() || 'tablero') + '.' + ext;
  }
  function download(blob, name) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  async function exportAs(kind) {
    if (kind === 'json') { download(new Blob([JSON.stringify(S.doc, null, 2)], { type: 'application/json' }), fileName('json')); return; }
    const str = exportSvg();
    if (!str) { toast('El tablero está vacío', { type: 'info' }); return; }
    if (kind === 'svg') { download(new Blob([str], { type: 'image/svg+xml' }), fileName('svg')); return; }
    const url = URL.createObjectURL(new Blob([str], { type: 'image/svg+xml' }));
    try {
      const img = new Image();
      img.src = url;
      await img.decode();
      const k = Math.min(2, 8000 / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      const blob = await new Promise((res) => c.toBlob(res, 'image/png'));
      download(blob, fileName('png'));
    } catch { toast('No se pudo generar el PNG', { type: 'error' }); }
    finally { URL.revokeObjectURL(url); }
  }
  function importJson() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.hidden = true;
    document.body.appendChild(input);
    input.addEventListener('change', async () => {
      const f = input.files?.[0];
      input.remove();
      if (!f) return;
      try {
        const data = JSON.parse(await f.text());
        const num = (v) => Number.isFinite(v);
        const payload = {
          nodes: (data.nodes || []).filter((n) => n && n.id && DEFAULTS[n.kind] && [n.x, n.y, n.w, n.h].every(num)),
          edges: (data.edges || []).filter((e) => e && e.id && (e.from || Array.isArray(e.p1)) && (e.to || Array.isArray(e.p2))),
          strokes: (data.strokes || []).filter((s) => s && s.id && Array.isArray(s.points)),
        };
        const total = payload.nodes.length + payload.edges.length + payload.strokes.length;
        if (!total) throw new Error('vacío');
        insertPayload(payload, viewCenter());
        toast(`Importados ${total} elementos (Ctrl+Z para deshacer)`);
        fit();
      } catch { toast('El archivo no es un tablero válido (JSON exportado desde aquí)', { type: 'error' }); }
    });
    input.click();
  }

  /* ---------- Herramientas y barra ---------- */
  function setTool(t) {
    S.tool = t;
    document.querySelectorAll('[data-tool]').forEach((b) => {
      b.classList.toggle('active', b.dataset.tool === t);
      b.setAttribute('aria-pressed', String(b.dataset.tool === t));
    });
    wrap.dataset.tool = t;
    S.hover = null;
    renderOverlay();
  }
  function updateToolbarState() {
    const n = S.sel.size;
    document.querySelectorAll('[data-needs-selection]').forEach((b) => { b.disabled = !n; });
    $('#btnUndo').disabled = !S.past.length;
    $('#btnRedo').disabled = !S.future.length;
    $('#btnSnap').setAttribute('aria-pressed', String(S.snap));
    $('#btnMinimap').setAttribute('aria-pressed', String(S.minimap));
  }

  function openArrangeMenu(anchor) {
    const sel = [...S.sel].map(item).filter(Boolean);
    const locked = sel.length && sel.every((x) => x.locked);
    openMenu(anchor, [
      { label: 'Alinear a la izquierda', icon: 'arrow-left', onClick: () => align('left') },
      { label: 'Centrar en horizontal', icon: 'columns-2', onClick: () => align('center') },
      { label: 'Alinear a la derecha', icon: 'arrow-right', onClick: () => align('right') },
      { label: 'Alinear arriba', icon: 'chevron-up', onClick: () => align('top') },
      { label: 'Centrar en vertical', icon: 'minus', onClick: () => align('middle') },
      { label: 'Alinear abajo', icon: 'chevron-down', onClick: () => align('bottom') },
      { separator: true },
      { label: 'Distribuir en horizontal', icon: 'arrow-up-down', onClick: () => distribute('h') },
      { label: 'Distribuir en vertical', icon: 'arrow-up-down', onClick: () => distribute('v') },
      { separator: true },
      { label: 'Agrupar (Ctrl+G)', icon: 'group', onClick: group },
      { label: 'Desagrupar (Ctrl+Shift+G)', icon: 'ungroup', onClick: ungroup },
      { label: 'Traer al frente', icon: 'bring-to-front', onClick: () => bringTo(true) },
      { label: 'Enviar al fondo', icon: 'send-to-back', onClick: () => bringTo(false) },
      sel.length && { separator: true },
      sel.length && { label: locked ? 'Desbloquear (L)' : 'Bloquear (L)', icon: locked ? 'lock-open' : 'lock', onClick: () => setProp('locked') },
    ].filter(Boolean), { align: 'start' });
  }

  /* ---------- Teclado ---------- */
  function onKeyDown(e) {
    if (S.editing) return;
    const inField = /input|textarea|select/i.test(e.target.tagName) || e.target.isContentEditable;
    if (inField || document.querySelector('dialog[open]')) return;
    const boardFocused = wrap.contains(document.activeElement) || document.activeElement === document.body;
    if (!boardFocused || props.contains(document.activeElement)) return;
    const mod = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === ' ' && !S.space) { S.space = true; wrap.classList.add('is-space'); handled(); return; }
    if (mod && k === 'z') { handled(); e.shiftKey ? redo() : undo(); return; }
    if (mod && k === 'y') { handled(); redo(); return; }
    if (mod && k === 'c' && e.altKey) { handled(); copyStyle(); return; }
    if (mod && k === 'v' && e.altKey) { handled(); pasteStyle(); return; }
    if (mod && k === 'c') { handled(); copy(); return; }
    if (mod && k === 'x') { handled(); copy(); removeIds(new Set(S.sel)); return; }
    if (mod && k === 'v') { handled(); paste(); return; }
    if (mod && k === 'd') { handled(); duplicate(); return; }
    if (mod && k === 'a') { handled(); setSelection(new Set([...S.doc.nodes, ...S.doc.edges, ...S.doc.strokes].map((x) => x.id))); return; }
    if (mod && k === 'g') { handled(); e.shiftKey ? ungroup() : group(); return; }
    if (mod) return;
    if (e.key === 'Delete' || e.key === 'Backspace') { handled(); removeIds(new Set(S.sel)); return; }
    if (e.key === 'Escape') { handled(); setSelection(new Set()); setTool('select'); return; }
    if (e.key === 'Enter' && S.sel.size === 1) { const id = [...S.sel][0]; handled(); if (node(id)) startEdit(id); else if (edge(id)) editLabel(id); return; }
    const step = e.shiftKey ? GRID : 2;
    const arrows = { arrowleft: [-step, 0], arrowright: [step, 0], arrowup: [0, -step], arrowdown: [0, step] };
    if (arrows[k] && S.sel.size) { handled(); nudge(...arrows[k]); return; }
    const tools = { v: 'select', h: 'hand', r: 'rect', o: 'ellipse', s: 'sticky', t: 'text', a: 'arrow', p: 'pen', e: 'eraser' };
    if (tools[k]) { handled(); setTool(tools[k]); return; }
    if (k === 'l' && S.sel.size) { handled(); setProp('locked'); return; }
    if (k === 'f') { handled(); fit(); return; }
    if (k === '0') { handled(); zoomCenter(1 / S.view.zoom); return; }
    if (k === '+' || k === '=') { handled(); zoomCenter(1.2); return; }
    if (k === '-') { handled(); zoomCenter(1 / 1.2); return; }
    if (k === 'g') { handled(); S.snap = !S.snap; updateToolbarState(); toast(S.snap ? 'Ajuste a la cuadrícula activado' : 'Ajuste a la cuadrícula desactivado', { type: 'info', duration: 1400 }); return; }
    if (k === 'm') { handled(); S.minimap = !S.minimap; renderMinimap(); updateToolbarState(); }
  }
  function onKeyUp(e) { if (e.key === ' ') { S.space = false; wrap.classList.remove('is-space'); } }

  /* ---------- Tableros (lista, crear, renombrar, borrar) ---------- */
  async function loadBoards() {
    const data = await api('/api/boards', { quiet: true });
    S.boards = data.boards;
    renderTabs();
    let wanted = null;
    try { wanted = Number(localStorage.getItem('board-current')); } catch {}
    const target = S.boards.find((b) => b.id === wanted) || S.boards[0];
    if (target) await switchBoard(target.id);
    else { S.boardId = null; S.doc = emptyDoc(); renderAll(); }
  }
  function renderTabs() {
    const sel = $('#boardSelect');
    sel.innerHTML = S.boards.length ? S.boards.map((b) => `<option value="${b.id}"${b.id === S.boardId ? ' selected' : ''}>${escapeHtml(b.name)}</option>`).join('')
      : '<option value="">Sin tableros</option>';
    sel.disabled = !S.boards.length;
  }
  async function switchBoard(id) {
    if (S.dirty) await save();
    const data = await api(`/api/boards/${id}`);
    let doc;
    try { doc = JSON.parse(data.data || '{}'); } catch { doc = {}; }
    if (doc.format !== 2) doc = emptyDoc(); // el servidor ya convierte el formato antiguo al leer
    S.boardId = id;
    S.doc = { format: 2, nodes: doc.nodes || [], edges: doc.edges || [], strokes: doc.strokes || [] };
    paintItemLink(data.item_id);
    S.sel = new Set(); S.past = []; S.future = []; pool = new Map();
    try { localStorage.setItem('board-current', String(id)); } catch {}
    renderTabs();
    for (const map of [nodeEls, edgeEls, strokeEls]) { map.forEach((g) => g.remove()); map.clear(); }
    renderAll();
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem('board-view:' + id) || 'null'); } catch {}
    if (saved && Number.isFinite(saved.zoom)) { S.view = saved; applyView(); renderOverlay(); } else fit(false);
  }
  // Si el tablero es de una tarea, la barra lleva a ella
  function paintItemLink(itemId) {
    const a = $('#boardItemLink');
    if (!a) return;
    if (itemId && !Items.state.loaded) { Items.ready().then(() => paintItemLink(itemId)).catch(() => {}); return; }
    const it = itemId && Items.get(itemId);
    a.hidden = !it;
    if (!it) return;
    a.href = `/tareas?item=${it.id}`;
    a.querySelector('[data-item-title]').textContent = it.text.split('\n')[0];
  }
  async function newBoard() {
    const name = (await uiPrompt('Nuevo tablero', { label: 'Nombre', confirmLabel: 'Crear' }))?.trim();
    if (!name) return;
    const r = await api('/api/boards', { method: 'POST', body: { name } });
    S.boards.unshift({ id: r.id, name });
    await switchBoard(r.id);
  }
  function boardMenu(anchor) {
    if (!S.boardId) return;
    openMenu(anchor, [
      { label: 'Renombrar', icon: 'pencil', onClick: async () => {
        const b = S.boards.find((x) => x.id === S.boardId);
        const name = (await uiPrompt('Renombrar tablero', { value: b?.name || '', confirmLabel: 'Guardar' }))?.trim();
        if (!name) return;
        await api(`/api/boards/${S.boardId}`, { method: 'PATCH', body: { name } });
        b.name = name; renderTabs();
      } },
      { separator: true },
      { label: 'Exportar como PNG', icon: 'image-down', onClick: () => exportAs('png') },
      { label: 'Exportar como SVG', icon: 'download', onClick: () => exportAs('svg') },
      { label: 'Exportar como JSON', icon: 'file-json', onClick: () => exportAs('json') },
      { label: 'Importar JSON…', icon: 'file-up', onClick: importJson },
      { separator: true },
      { label: 'Vaciar el tablero', icon: 'eraser', onClick: async () => {
        if (!(await uiConfirm('¿Vaciar el tablero?', 'Puedes deshacerlo con Ctrl+Z mientras no cierres la página.', { confirmLabel: 'Vaciar', danger: true }))) return;
        record(); S.doc = emptyDoc(); S.sel = new Set(); changed();
      } },
      { label: 'Eliminar tablero', icon: 'trash-2', danger: true, onClick: async () => {
        const b = S.boards.find((x) => x.id === S.boardId);
        if (!(await uiConfirm(`¿Eliminar «${b?.name}»?`, 'Se borra el tablero y todo su contenido.', { confirmLabel: 'Eliminar', danger: true }))) return;
        await api(`/api/boards/${S.boardId}`, { method: 'DELETE' });
        S.dirty = false;
        S.boardId = null;
        await loadBoards();
      } },
    ]);
  }

  /* ---------- Soltar en el tablero: elementos del Inbox y formas o plantillas de la paleta ---------- */
  function setupDrop() {
    Sortable.addDropTarget(wrap, {
      accepts: () => (S.boardId ? true : 'Crea primero un tablero'),
      onDrop: (ctx) => {
        const p = toWorld(ctx.point.x, ctx.point.y);
        if (ctx.from?.group === 'board-palette') {
          if (ctx.item.dataset.shape) insertShape(ctx.item.dataset.shape, p, true);
          else if (ctx.item.dataset.template) insertTemplate(ctx.item.dataset.template, p);
          return;
        }
        const it = Items.get(Number(ctx.id));
        if (!it) return;
        record();
        const parent = it.parent_id ? Items.get(it.parent_id) : null;
        const d = scaled('inbox');
        if (Items.children(it.id).length) d.w = r1(d.w * 1.25);  // con pasos: el bloque entero, y que se lean
        // Queda centrada donde se suelta (sin saltos); el ajuste a la cuadrícula se aplica al moverla después
        const n = { id: uid('n'), kind: 'inbox', x: p.x - d.w / 2, y: p.y - d.h / 2, ...d, text: it.text,
          inboxId: it.id, itemType: it.type, parentLabel: parent ? parent.text : '' };
        const fit = cardHeight(n, it);
        if (fit && fit > n.h) { n.y += (n.h - fit) / 2; n.h = fit; }
        const k = keepInView(n);
        n.x += k.dx; n.y += k.dy;
        n.stroke = TYPE_COLORS[it.type] || TYPE_COLORS.tarea;
        S.doc.nodes.push(n);
        S.sel = new Set([n.id]);
        changed();
      },
    });
  }

  /* ---------- Arranque ---------- */
  function wire() {
    svg.addEventListener('pointerdown', onPointerDown);
    svg.addEventListener('pointermove', onPointerMove);
    svg.addEventListener('pointerup', onPointerUp);
    svg.addEventListener('pointercancel', onPointerUp);
    svg.addEventListener('pointerleave', () => { if (!S.gesture && S.hover) { S.hover = null; renderOverlay(); } });
    svg.addEventListener('wheel', onWheel, { passive: false });
    svg.addEventListener('contextmenu', (e) => {
      const h = hitTarget(e.target);
      if (!h && !S.sel.size) return;
      e.preventDefault();
      if (h && !S.sel.has(h.id)) setSelection(new Set([h.id]));
      openArrangeMenu({ getBoundingClientRect: () => ({ left: e.clientX, right: e.clientX, top: e.clientY, bottom: e.clientY }), setAttribute() {}, focus() {}, contains: () => false });
    });
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('keyup', onKeyUp);
    document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));
    $('#btnUndo').addEventListener('click', undo);
    $('#btnRedo').addEventListener('click', redo);
    $('#btnDuplicate').addEventListener('click', duplicate);
    $('#btnDelete').addEventListener('click', () => removeIds(new Set(S.sel)));
    $('#btnProps').addEventListener('click', () => {
      setPropsOpen(!propsOpenNow());
      if (propsOpenNow() && !S.sel.size && S.propsMode !== 'docked') toast('Selecciona algo para ver sus propiedades', { type: 'info', duration: 1600 });
    });
    $('#btnArrange').addEventListener('click', (e) => openArrangeMenu(e.currentTarget));
    $('#btnTemplates').addEventListener('click', (e) => openTemplates(e.currentTarget));
    $('#btnFit').addEventListener('click', () => fit());
    $('#btnZoomIn').addEventListener('click', () => zoomCenter(1.2));
    $('#btnZoomOut').addEventListener('click', () => zoomCenter(1 / 1.2));
    $('#btnZoomReset').addEventListener('click', () => zoomCenter(1 / S.view.zoom));
    $('#btnSnap').addEventListener('click', () => { S.snap = !S.snap; updateToolbarState(); });
    $('#btnMinimap').addEventListener('click', () => { S.minimap = !S.minimap; renderMinimap(); updateToolbarState(); });
    $('#btnNewBoard').addEventListener('click', newBoard);
    $('#btnBoardMenu').addEventListener('click', (e) => boardMenu(e.currentTarget));
    $('#boardSelect').addEventListener('change', (e) => switchBoard(Number(e.target.value)));
    $('#btnFullscreen').addEventListener('click', () => {
      const area = $('#boardArea');
      const on = !area.classList.contains('fullscreen');
      area.classList.toggle('fullscreen', on);
      $('#btnFullscreen').setAttribute('aria-pressed', String(on));
      setTimeout(() => { applyView(); renderOverlay(); }, 50);
    });
    // Minimapa: clic o arrastre para mover la vista
    mini.addEventListener('pointerdown', (e) => {
      const move = (ev) => {
        const m = mini._map, r = mini.getBoundingClientRect();
        if (!m) return;
        const wx = (ev.clientX - r.left - m.ox) / m.k, wy = (ev.clientY - r.top - m.oy) / m.k;
        const sr = svg.getBoundingClientRect();
        S.view.x = sr.width / 2 - wx * S.view.zoom; S.view.y = sr.height / 2 - wy * S.view.zoom;
        applyView(); renderOverlay();
      };
      move(e);
      mini.setPointerCapture(e.pointerId);
      mini.addEventListener('pointermove', move);
      mini.addEventListener('pointerup', () => mini.removeEventListener('pointermove', move), { once: true });
    });
    new ResizeObserver(() => { applyView(); renderOverlay(); }).observe(wrap);
    // Panel según el ancho del tablero: acoplado a la derecha si sobra sitio (nada queda tapado),
    // flotante si hay algo menos y hoja inferior si es estrecho
    new ResizeObserver(() => {
      const w = $('#boardArea').clientWidth;
      const mode = w >= 900 ? 'docked' : w >= 560 && !isMobile() ? 'float' : 'sheet';
      if (mode === S.propsMode) return;
      S.propsMode = mode;
      body.classList.toggle('props-docked', mode === 'docked');
      body.classList.toggle('props-sheet', mode === 'sheet');
      props.classList.remove('at-left');
      props._key = '';
      renderProps();
    }).observe($('#boardArea'));
    // Los cambios del Inbox (hecho, editado…) se reflejan en sus tarjetas (la firma de cada tarjeta incluye su elemento)
    document.addEventListener('items:changed', () => { if (!S.editing) renderAll(); });
    wireProps();
  }

  buildDom();
  wire();
  setupDrop();
  renderPalette();
  setTool('select');
  applyView();
  loadBoards().then(() => {
    // /inbox?tablero=<id de la tarea>: abre (o crea) el tablero de esa tarea
    const want = Number(new URLSearchParams(location.search).get('tablero'));
    if (want) { history.replaceState(null, '', '/inbox'); openForItem(want); }
  }).catch(() => { statusEl.textContent = 'No se pudo cargar'; });
  loadTemplates();

  // Para los tests de navegador
  window.__board = { state: S, toWorld, fit, applyView, undo, redo, align, distribute, group, applyColor, setProp, renderAll, edgeGeom, exportSvg, insertShape, insertTemplate, openForItem, buildItemDoc };
})();
