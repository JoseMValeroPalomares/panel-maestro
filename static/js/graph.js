/* ============================================================
   Grafo de notas (vis-network)
   Los colores salen de los tokens del tema y se recalculan al cambiarlo.
   Depende de ui.js (icon, api, toast, uiConfirm…)
   ============================================================ */
let network = null;
let nodesDS = null;
let edgesDS = null;
let editMode = false;
let ctrlDown = false;
let linkSource = null;
let rawData = { nodes: [], edges: [] };
let panelNodeId = null;
let statusFilter = 'all';
let tagFilter = null;
let colorMode = 'status'; // 'status' | 'stale'
let orphanHighlight = false;
let collapsedCats = new Set();
const movedNodes = new Set();   // nodos arrastrados a mano desde la última vez que se guardó: pasan a «fijados»

const STATUS_LABELS = { 'por-escribir': 'Por escribir', 'en-desarrollo': 'En desarrollo', 'consolidado': 'Consolidado', 'indice': 'Índice' };
// Colores de categoría del tema activo (--cat-0…9): vis-network necesita el valor, no la variable
const catPalette = () => { const cs = getComputedStyle(document.documentElement); return Array.from({ length: 10 }, (_, i) => cs.getPropertyValue(`--cat-${i}`).trim()); };
// El lienzo necesita el color resuelto (no var(--…)): el mismo índice que en Notas y Baúl (ui.js:categoryIndex)
function categoryColor(cat) {
  return catPalette()[categoryIndex(cat)];
}

/* Paleta del lienzo a partir de los tokens CSS */
function themePalette() {
  const cs = getComputedStyle(document.documentElement);
  const v = (name) => cs.getPropertyValue(name).trim();
  return {
    text: v('--text'), text2: v('--text-2'), bg: v('--bg'), elev: v('--bg-elev'),
    separator: v('--separator-strong'), accent: v('--accent'), warning: v('--warning'), danger: v('--danger'),
    status: { 'por-escribir': v('--st-draft'), 'en-desarrollo': v('--st-wip'), 'consolidado': v('--st-done'), 'indice': v('--st-index') },
  };
}
const alpha = (hex, a) => {
  const h = hex.replace('#', '');
  if (h.length !== 6) return hex;
  return `rgba(${parseInt(h.slice(0, 2), 16)},${parseInt(h.slice(2, 4), 16)},${parseInt(h.slice(4, 6), 16)},${a})`;
};

/* ============================================================
   CARGA
   ============================================================ */
async function initGraph() {
  try {
    rawData = await api('/api/graph', { quiet: true });
    document.getElementById('btnAutoUndo').hidden = !rawData.hay_deshacer;
  } catch {
    showState(document.getElementById('loadingOverlay'), loadFailed('No se pudo cargar el grafo'), () => location.reload());
    return;
  }
  if (!rawData.nodes.some(n => n.type === 'note')) {
    document.getElementById('loadingOverlay').innerHTML = emptyState({ iconName: 'waypoints', title: 'Aún no hay notas', text: 'Crea notas y enlázalas con [[Nombre]] para ver tu mapa de conceptos.' });
    return;
  }
  renderGraph();
}

function pruneEmptyCategories(nodes, edges) {
  const noteIds = new Set(nodes.filter(n => n.type === 'note').map(n => n.id));
  const catIds = new Set(nodes.filter(n => n.type === 'category').map(n => n.id));
  let changed = true;
  while (changed) {
    changed = false;
    catIds.forEach(catId => {
      if (!edges.some(e => e.from === catId && (noteIds.has(e.to) || catIds.has(e.to)))) { catIds.delete(catId); changed = true; }
    });
  }
  const keep = new Set([...noteIds, ...catIds]);
  return { nodes: nodes.filter(n => keep.has(n.id)), edges: edges.filter(e => keep.has(e.from) && keep.has(e.to)) };
}

/* Notas sin ninguna conexión nota-nota (solo su enlace de categoría) */
function computeOrphanIds() {
  const connected = new Set();
  rawData.edges.forEach(e => { if (e.type === 'auto' || e.type === 'manual') { connected.add(e.from); connected.add(e.to); } });
  return rawData.nodes.filter(n => n.type === 'note' && !connected.has(n.id)).map(n => n.id);
}

function showLoading(show) { document.getElementById('loadingOverlay').hidden = !show; }

function renderGraph() {
  const P = themePalette();
  const hidden = new Set();
  collapsedCats.forEach(catId => getDescendantIds(catId).forEach(id => hidden.add(id)));
  const filtered = (statusFilter === 'all' ? rawData.nodes : rawData.nodes.filter(n => n.type === 'category' || n.status === statusFilter))
    .filter(n => !hidden.has(n.id));
  const ids = new Set(filtered.map(n => n.id));
  const { nodes, edges } = pruneEmptyCategories(filtered, rawData.edges.filter(e => ids.has(e.from) && ids.has(e.to)));
  const orphanIds = orphanHighlight ? new Set(computeOrphanIds()) : new Set();
  const now = Date.now() / 1000;
  const font = { color: P.text, face: getComputedStyle(document.body).fontFamily, strokeWidth: 3, strokeColor: P.bg };

  const visNodes = nodes.map(n => {
    const c = categoryColor(n.group || 'Sin categoría');
    if (n.type === 'category') {
      const isCollapsed = collapsedCats.has(n.id);
      const node = {
        id: n.id, label: isCollapsed ? `${n.label} ＋` : n.label, title: undefined, type: 'category',
        shape: 'box', margin: { top: 6, bottom: 6, left: 10, right: 10 },
        color: { background: c, border: c, highlight: { background: c, border: P.text }, hover: { background: c, border: P.text } },
        font: { color: '#11111b', size: n.depth === 0 ? 20 : 15, face: font.face, bold: { color: '#11111b' } },
        shapeProperties: { borderRadius: 7 }, borderWidth: isCollapsed ? 2 : 0,
        mass: n.depth === 0 ? 3 : 1.5, opacity: n.depth === 0 ? 1 : 0.88,
      };
      if (n.x != null && n.y != null) Object.assign(node, { x: n.x, y: n.y, physics: false }); else node.physics = true;
      return node;
    }
    const status = n.status || 'por-escribir';
    let border = P.status[status], borderWidth = status === 'consolidado' ? 3 : 2;
    if (colorMode === 'stale') {
      // Verde (repasada hoy) → rojo (más de 60 días o nunca)
      const t = Math.min((now - (n.last_reviewed || 0)) / 86400 / 60, 1);
      border = `hsl(${Math.round(130 - t * 125)}, 70%, 45%)`;
      borderWidth = 3;
    }
    const isOrphan = orphanIds.has(n.id);
    let label = wrapLabel(n.label);
    if (n.due_flashcards > 0) label += `  · ${n.due_flashcards}`;
    const node = {
      id: n.id, label, type: 'note', status,
      shape: status === 'indice' ? 'diamond' : 'dot', size: status === 'indice' ? 16 : 11,
      color: {
        background: isOrphan ? alpha(P.danger, 0.18) : P.elev,
        border: isOrphan ? P.danger : border,
        highlight: { background: alpha(c, 0.25), border: P.accent },
        hover: { background: alpha(c, 0.18), border },
      },
      font: { ...font, size: 14 },
      borderWidth: isOrphan ? 3 : borderWidth, borderWidthSelected: 4,
      shapeProperties: n.fijado ? { borderDashes: [3, 3] } : { borderDashes: false },
    };
    if (n.x != null && n.y != null) Object.assign(node, { x: n.x, y: n.y, physics: false }); else node.physics = true;
    return node;
  });

  const visEdges = edges.map(e => {
    if (e.type === 'category') {
      return { id: e.id, from: e.from, to: e.to, color: { color: P.separator, highlight: P.text2, hover: P.text2 }, width: 1,
        smooth: { type: 'cubicBezier', roundness: 0.4 }, arrows: { to: { enabled: false } }, selectionWidth: 1 };
    }
    const manual = e.type === 'manual';
    return {
      id: e.id, from: e.from, to: e.to,
      color: manual ? { color: P.warning, highlight: P.warning, hover: P.warning } : { color: alpha(P.accent.startsWith('#') ? P.accent : '#0066cc', 0.55), highlight: P.accent, hover: P.accent },
      width: manual ? 2 : 1.25, dashes: manual ? false : [5, 4],
      smooth: { type: 'curvedCW', roundness: 0.1 }, arrows: { to: { enabled: true, scaleFactor: 0.45 } }, selectionWidth: 2,
    };
  });

  nodesDS = new vis.DataSet(visNodes);
  edgesDS = new vis.DataSet(visEdges);
  const options = {
    layout: { randomSeed: 42 },
    physics: {
      enabled: true, solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -90, centralGravity: 0.008, springLength: 140, springConstant: 0.08, damping: 0.65, avoidOverlap: 0.7 },
      stabilization: { enabled: true, iterations: 400, updateInterval: 30 },
    },
    interaction: { hover: true, hoverConnectedEdges: true, selectConnectedEdges: false, tooltipDelay: 999999, keyboard: { enabled: true, bindToWindow: false }, zoomView: true, dragView: true, dragNodes: true },
    manipulation: { enabled: false },
  };

  if (network) network.destroy();
  network = new vis.Network(document.getElementById('graph-container'), { nodes: nodesDS, edges: edgesDS }, options);
  let finished = false;
  const finish = () => {
    if (finished) return;
    finished = true;
    network.setOptions({ physics: { enabled: false } });
    // encuadre con un mínimo de escala: así se leen los nombres sin acercarse (lo que sobra, se arrastra)
    network.fit({ animation: false, minZoomLevel: matchMedia('(max-width: 767px)').matches ? 0.4 : 0.6, maxZoomLevel: 1.2 });
    showLoading(false);
    buildLegend();
    updateStats();
    if (tagFilter) applyTagDim();
  };
  network.on('stabilizationIterationsDone', finish);
  if (!nodesDS.get().some(n => n.physics !== false)) finish();
  setTimeout(finish, 2500);
  network.on('hoverNode', showTooltip);
  network.on('blurNode', hideTooltip);
  network.on('dragStart', hideTooltip);
  network.on('dragEnd', (p) => (p.nodes || []).forEach((id) => movedNodes.add(id)));
  network.on('click', onNetworkClick);
  network.on('oncontext', onRightClick);
}

document.querySelectorAll('.chip[data-status]').forEach(c => c.addEventListener('click', () => setStatusFilter(c.dataset.status)));
function setStatusFilter(status) {
  statusFilter = status;
  document.querySelectorAll('.chip[data-status]').forEach(c => c.setAttribute('aria-pressed', String(c.dataset.status === status)));
  showLoading(true);
  renderGraph();
}
function setColorMode(mode) {
  colorMode = mode;
  document.getElementById('viewBtnStatus').setAttribute('aria-pressed', String(mode === 'status'));
  document.getElementById('viewBtnStale').setAttribute('aria-pressed', String(mode === 'stale'));
  renderGraph();
}
function toggleOrphanHighlight() {
  orphanHighlight = !orphanHighlight;
  document.getElementById('chipOrphans').setAttribute('aria-pressed', String(orphanHighlight));
  renderGraph();
}

function wrapLabel(label) {
  if (!label || label.length <= 18) return label;
  const lines = [];
  let cur = '';
  for (const w of label.split(' ')) {
    if ((cur + w).trim().length > 18) { lines.push(cur.trim()); cur = w + ' '; } else cur += w + ' ';
  }
  if (cur.trim()) lines.push(cur.trim());
  return lines.join('\n');
}

/* ============================================================
   ETIQUETAS: atenúa en vez de ocultar para no romper la estructura
   ============================================================ */
function buildTagChips() {
  const allTags = new Set();
  rawData.nodes.filter(n => n.type === 'note').forEach(n => (n.tags || '').split(',').map(t => t.trim()).filter(Boolean).forEach(t => allTags.add(t)));
  const box = document.getElementById('tagChips');
  box.innerHTML = [...allTags].sort((a, b) => a.localeCompare(b, 'es')).map(tag =>
    `<button type="button" class="chip" data-tag="${escapeHtml(tag)}" aria-pressed="${tagFilter === tag}">#${escapeHtml(tag)}</button>`).join('');
  box.querySelectorAll('[data-tag]').forEach(b => b.addEventListener('click', () => {
    tagFilter = tagFilter === b.dataset.tag ? null : b.dataset.tag;
    buildTagChips();
    applyTagDim();
  }));
}
function applyTagDim() {
  if (!nodesDS) return;
  nodesDS.update(rawData.nodes.filter(n => n.type === 'note' && nodesDS.get(n.id)).map(n => {
    const tags = (n.tags || '').split(',').map(t => t.trim());
    return { id: n.id, opacity: tagFilter && !tags.includes(tagFilter) ? 0.15 : 1 };
  }));
}

/* ============================================================
   TOOLTIP
   ============================================================ */
function showTooltip(params) {
  const node = rawData.nodes.find(n => n.id === params.node);
  if (!node) return;
  const linkedIds = rawData.edges.filter(e => (e.from === node.id || e.to === node.id) && e.type !== 'category').map(e => e.from === node.id ? e.to : e.from);
  const linked = linkedIds.map(id => rawData.nodes.find(n => n.id === id)?.label).filter(Boolean);
  const tt = document.getElementById('node-tooltip');
  const status = node.status || 'por-escribir';
  document.getElementById('tt-title').innerHTML = node.type === 'note'
    ? `<span class="status-dot" data-status="${status}"></span>${node.encrypted ? icon('lock', 'icon-sm') : ''}${escapeHtml(node.label)}`
    : escapeHtml(node.label);
  document.getElementById('tt-cat').textContent = node.type === 'note' ? (node.group || '') : 'Categoría · clic para plegar';
  const meta = [];
  if (node.type === 'note') {
    if (node.tags) meta.push(node.tags.split(',').map(t => '#' + t.trim()).join(' '));
    if (node.due_flashcards > 0) meta.push(`${node.due_flashcards} flashcard${node.due_flashcards > 1 ? 's' : ''} pendiente${node.due_flashcards > 1 ? 's' : ''}`);
    if (node.last_reviewed) meta.push('Repasada ' + timeAgo(node.last_reviewed));
  }
  document.getElementById('tt-meta').textContent = meta.join(' · ');
  document.getElementById('tt-links').textContent = linked.length ? '→ ' + linked.slice(0, 5).join(', ') + (linked.length > 5 ? '…' : '') : '';
  const pos = network.canvasToDOM(network.getPosition(params.node));
  const stage = document.querySelector('.graph-stage').getBoundingClientRect();
  tt.hidden = false;
  tt.style.left = Math.min(pos.x + 16, stage.width - tt.offsetWidth - 8) + 'px';
  tt.style.top = Math.max(8, pos.y - 16) + 'px';
  requestAnimationFrame(() => tt.classList.add('show'));
}
function hideTooltip() {
  const tt = document.getElementById('node-tooltip');
  tt.classList.remove('show');
  setTimeout(() => { if (!tt.classList.contains('show')) tt.hidden = true; }, 150);
}

/* ============================================================
   CLICS
   ============================================================ */
function onNetworkClick(params) {
  if (!params.nodes.length) { closePanel(); return; }
  const nodeId = params.nodes[0];
  const node = rawData.nodes.find(n => n.id === nodeId);
  if (node?.type === 'category' && !editMode) { toggleCategoryCollapse(nodeId); return; }
  if (editMode && (ctrlDown || linkSource) && node?.type === 'note') {
    if (!linkSource) {
      linkSource = nodeId;
      nodesDS.update({ id: nodeId, borderWidth: 5 });
      refreshEditBanner();
    } else if (linkSource !== nodeId) {
      createEdge(linkSource, nodeId);
      nodesDS.update({ id: linkSource, borderWidth: 2 });
      linkSource = null;
      refreshEditBanner();
    }
    return;
  }
  if (node?.type === 'note') openPanel(node);
}

function getDescendantIds(catId) {
  const children = rawData.edges.filter(e => e.from === catId && e.type === 'category').map(e => e.to);
  return children.reduce((acc, c) => [...acc, c, ...getDescendantIds(c)], []);
}
function toggleCategoryCollapse(catId) {
  if (collapsedCats.has(catId)) collapsedCats.delete(catId); else collapsedCats.add(catId);
  renderGraph();
}
async function onRightClick(params) {
  params.event.preventDefault();
  if (!editMode) return;
  const edgeId = network.getEdgeAt(params.pointer.DOM);
  const edge = edgeId != null && rawData.edges.find(e => e.id === edgeId);
  if (!edge || edge.type === 'category') return;
  if (await uiConfirm('¿Eliminar esta conexión?', '', { confirmLabel: 'Eliminar', danger: true })) deleteEdge(edgeId);
}

/* ============================================================
   PANEL DE NOTA
   ============================================================ */
function openPanel(node) {
  panelNodeId = node.id;
  const status = node.status || 'por-escribir';
  document.getElementById('panel-status').dataset.status = status;
  document.getElementById('panel-status-label').textContent = STATUS_LABELS[status] || '';
  document.getElementById('panel-title').textContent = node.label;
  document.getElementById('panel-cat').textContent = node.group || '';
  document.getElementById('panel-lock').hidden = !node.encrypted;
  const tags = (node.tags || '').split(',').map(t => t.trim()).filter(Boolean);
  document.getElementById('panel-tags').innerHTML = tags.map(t => `<span class="tag">#${escapeHtml(t)}</span>`).join('');
  const fc = document.getElementById('panel-fc');
  fc.hidden = !(node.due_flashcards > 0);
  fc.textContent = `${node.due_flashcards} flashcard(s) pendiente(s) de repaso`;
  document.getElementById('panel-link').href = `/?note=${encodeURIComponent(node.id)}`;
  document.getElementById('panel-connect-btn').hidden = !editMode;
  updatePinButton(node);
  document.getElementById('node-panel').hidden = false;
}
function closePanel() { document.getElementById('node-panel').hidden = true; panelNodeId = null; }
function startConnectFrom() {
  if (!panelNodeId) return;
  linkSource = panelNodeId;
  nodesDS.update({ id: panelNodeId, borderWidth: 5 });
  closePanel();
  refreshEditBanner();
}
function cancelConnect() {
  if (linkSource) nodesDS.update({ id: linkSource, borderWidth: 2 });
  linkSource = null;
  refreshEditBanner();
}
function refreshEditBanner() {
  const banner = document.getElementById('editBanner');
  banner.hidden = !editMode;
  if (!editMode) return;
  banner.innerHTML = linkSource
    ? `<strong>Nota de origen elegida.</strong><span>Toca la nota de destino para conectarlas.</span>
       <button type="button" class="btn btn-sm btn-ghost" data-call="cancelConnect">Cancelar</button>`
    : `<strong>Modo edición</strong><span>Arrastra notas para moverlas · <kbd>Ctrl</kbd> + clic en dos notas para conectarlas · clic derecho en una conexión para borrarla</span>`;
}

function toggleEditMode() {
  editMode = !editMode;
  const btn = document.getElementById('btnEdit');
  btn.setAttribute('aria-pressed', String(editMode));
  btn.classList.toggle('btn-tinted', editMode);
  btn.classList.toggle('btn-ghost', !editMode);
  if (!editMode) cancelConnect();
  document.getElementById('panel-connect-btn').hidden = !editMode;
  refreshEditBanner();
}
document.addEventListener('keydown', e => { if (e.key === 'Control' || e.key === 'Meta') ctrlDown = true; if (e.key === 'Escape' && linkSource) cancelConnect(); });
document.addEventListener('keyup', e => { if (e.key === 'Control' || e.key === 'Meta') ctrlDown = false; });

/* ============================================================
   API
   ============================================================ */
async function createEdge(source, target) {
  await api('/api/graph/edges', { method: 'POST', body: { source, target } });
  const P = themePalette();
  const tempId = `m-${source}-${target}-${Date.now()}`;
  edgesDS.add({ id: tempId, from: source, to: target, color: { color: P.warning, highlight: P.warning }, width: 2, smooth: { type: 'curvedCW', roundness: 0.1 }, arrows: { to: { enabled: true, scaleFactor: 0.45 } } });
  rawData.edges.push({ id: tempId, from: source, to: target, type: 'manual' });
  updateStats();
  toast('Notas conectadas');
}
async function deleteEdge(edgeId) {
  const edge = edgesDS.get(edgeId);
  if (!edge) return;
  await api('/api/graph/edges', { method: 'DELETE', body: { source: edge.from, target: edge.to } });
  edgesDS.remove(edgeId);
  rawData.edges = rawData.edges.filter(e => e.id !== edgeId);
  updateStats();
  toast('Conexión eliminada');
}
async function saveLayout() {
  const nodes = Object.entries(network.getPositions()).map(([id, pos]) => ({ id, x: Math.round(pos.x), y: Math.round(pos.y) }));
  const btn = document.getElementById('btnSave');
  btn.classList.add('is-loading');
  try {
    const fijados = [...movedNodes];
    await api('/api/graph/layout', { method: 'POST', body: { nodes, edges: [], fijados } });
    fijados.forEach((id) => { const n = rawData.nodes.find((x) => x.id === id); if (n) n.fijado = true; });
    movedNodes.clear();
    toast('Posiciones guardadas');
  } finally {
    btn.classList.remove('is-loading');
  }
}
async function resetLayout() {
  const ok = await uiConfirm('Recolocar el grafo', 'Las notas se moverán con la física. Las posiciones guardadas no cambian hasta que pulses Guardar.', { confirmLabel: 'Recolocar' });
  if (!ok) return;
  nodesDS.update(nodesDS.get().map(n => ({ id: n.id, physics: true })));
  network.setOptions({ physics: { enabled: true } });
  setTimeout(() => network.setOptions({ physics: { enabled: false } }), 4000);
}

/* ============================================================
   LEYENDA Y ESTADÍSTICAS
   ============================================================ */
function buildLegend() {
  buildTagChips();
  const legend = document.getElementById('legend');
  const cats = [...new Set(rawData.nodes.filter(n => n.type === 'category' && n.depth === 0).map(n => n.label))];
  legend.innerHTML =
    cats.map(c => `<span class="legend-item"><span class="legend-swatch" style="background:${categoryColor(c)};border-radius:3px"></span>${escapeHtml(c)}</span>`).join('') +
    '<span class="legend-sep"></span>' +
    Object.entries(STATUS_LABELS).map(([k, label]) => `<span class="legend-item"><span class="status-dot" data-status="${k}"></span>${label}${k === 'indice' ? ' (rombo)' : ''}</span>`).join('') +
    '<span class="legend-grow"></span>' +
    `<span class="legend-item"><svg width="24" height="6" aria-hidden="true"><line x1="0" y1="3" x2="24" y2="3" stroke="currentColor" stroke-width="1.5" stroke-dasharray="5,4" style="color:var(--accent)"/></svg>Enlace [[ ]]</span>
     <span class="legend-item"><svg width="24" height="6" aria-hidden="true"><line x1="0" y1="3" x2="24" y2="3" stroke="currentColor" stroke-width="2" style="color:var(--warning)"/></svg>Manual</span>`;
}
function updateStats() {
  const notes = nodesDS ? nodesDS.get().filter(n => n.type === 'note').length : 0;
  const links = rawData.edges.filter(e => e.type !== 'category').length;
  const total = rawData.nodes.filter(n => n.type === 'note').length;
  document.getElementById('stats').textContent = `${notes}${notes !== total ? ' de ' + total : ''} notas · ${links} conexiones`;
}


initGraph();
document.addEventListener('themechange', () => { if (network) renderGraph(); });


/* ============================================================
   GRAFO AUTOMÁTICO (servidor: app/graph_layout.py) · fijar nodos · deshacer
   ============================================================ */
function updatePinButton(node) {
  const b = document.getElementById('panel-pin-btn');
  b.setAttribute('aria-pressed', String(!!node.fijado));
  document.getElementById('panel-pin-label').textContent = node.fijado ? 'Soltar posición' : 'Fijar posición';
}
async function togglePin() {
  const node = rawData.nodes.find((n) => n.id === panelNodeId);
  if (!node) return;
  node.fijado = !node.fijado;
  if (node.fijado && network) { const p = network.getPositions([node.id])[node.id]; if (p) await api('/api/graph/layout', { method: 'POST', body: { nodes: [{ id: node.id, x: Math.round(p.x), y: Math.round(p.y) }], edges: [] }, quiet: true }); }
  await api('/api/graph/fijar', { method: 'POST', body: { id: node.id, fijado: node.fijado } });
  movedNodes.delete(node.id);
  nodesDS.update({ id: node.id, shapeProperties: node.fijado ? { borderDashes: [3, 3] } : { borderDashes: false } });
  updatePinButton(node);
  toast(node.fijado ? 'Posición fijada: «Generar automático» puede respetarla' : 'Posición suelta', { type: 'info' });
}

async function openAutoLayout() {
  if (!rawData.nodes.length) return;
  const fijados = rawData.nodes.filter((n) => n.fijado).length + movedNodes.size;
  let dlg = document.getElementById('autoDialog');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'autoDialog';
    dlg.className = 'modal modal-sm';
    dlg.setAttribute('aria-labelledby', 'autoTitle');
    dlg.innerHTML = `<div class="modal-header"><h2 id="autoTitle">Generar grafo automático</h2>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body stack">
        <p>Se recolocan todos los nodos: la categoría mayor en el centro, las demás a su alrededor (cuanto más grande, más cerca), subcategorías en anillos por profundidad y las notas sin categoría en el anillo exterior.</p>
        <label class="check"><input type="checkbox" class="checkbox" id="autoRespect"><span><strong>Respetar nodos fijados</strong><br><span class="small muted" id="autoRespectHint"></span></span></label>
        <p class="small muted">Podrás deshacerlo con «Deshacer recolocado».</p></div>
      <div class="modal-footer"><span class="spacer"></span><button type="button" class="btn" data-close>Cancelar</button>
        <button type="button" class="btn btn-primary" id="autoGo">${icon('sparkles', 'icon-sm')}Generar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    dlg.querySelector('#autoGo').addEventListener('click', () => { const r = dlg.querySelector('#autoRespect').checked; closeModal(dlg); runAutoLayout(r); });
  }
  dlg.querySelector('#autoRespect').checked = fijados > 0;
  dlg.querySelector('#autoRespect').disabled = fijados === 0;
  dlg.querySelector('#autoRespectHint').textContent = fijados ? `${fijados} ${fijados === 1 ? 'nodo fijado' : 'nodos fijados'} (arrastrados y guardados, o fijados desde su ficha) conservan su sitio.` : 'Aún no hay nodos fijados: arrastra uno y guarda las posiciones, o fíjalo desde su ficha.';
  openModal(dlg);
}

async function runAutoLayout(respetar) {
  const btn = document.getElementById('btnAuto');
  btn.classList.add('is-loading');
  try {
    if (respetar && movedNodes.size) await saveLayout();   // lo arrastrado pasa a fijado antes de recolocar
    const r = await api('/api/graph/auto', { method: 'POST', body: { respetar_fijados: respetar } });
    animateTo(r.posiciones);
    rawData.nodes.forEach((n) => { const p = r.posiciones[n.id]; if (p) { n.x = p.x; n.y = p.y; } if (!respetar) n.fijado = false; });
    if (!respetar) movedNodes.clear();
    document.getElementById('btnAutoUndo').hidden = false;
    toast(`Grafo recolocado (${r.total} nodos)`, { action: { label: 'Deshacer', onClick: undoAutoLayout }, duration: 8000 });
  } finally { btn.classList.remove('is-loading'); }
}

/* Movimiento suave de todos los nodos visibles a sus nuevas posiciones y encuadre final */
function animateTo(targets) {
  if (!network) return;
  network.setOptions({ physics: { enabled: false } });
  const desde = network.getPositions();
  const ids = Object.keys(desde).filter((id) => targets[id]);
  const dur = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 750;
  const t0 = performance.now();
  const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const fit = () => network.fit({ animation: { duration: dur ? 500 : 0, easingFunction: 'easeInOutQuad' }, minZoomLevel: matchMedia('(max-width: 767px)').matches ? 0.12 : 0.15, maxZoomLevel: 1.2 });
  const paso = (now) => {
    const k = dur ? Math.min(1, (now - t0) / dur) : 1, e = ease(k);
    nodesDS.update(ids.map((id) => ({ id, x: desde[id].x + (targets[id].x - desde[id].x) * e, y: desde[id].y + (targets[id].y - desde[id].y) * e, physics: false })));
    if (k < 1) requestAnimationFrame(paso); else { fit(); updateStats(); }
  };
  requestAnimationFrame(paso);
}

async function undoAutoLayout() {
  try { await api('/api/graph/auto/deshacer', { method: 'POST' }); } catch { return; }
  toast('Posiciones anteriores restauradas', { type: 'info' });
  await initGraph();
}
