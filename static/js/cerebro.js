/* ==========================================================================
   Notas (Cerebro Digital) — lista, lectura, edición, cifrado, flashcards
   Depende de ui.js (icon, api, toast, openModal, uiConfirm, uiPrompt, openMenu…)
   ========================================================================== */

/* ---------- Estado ---------- */
let allNotes = [];
let activeNoteId = null;
let activeStatus = 'por-escribir';
let statusFilter = 'all';
let tagFilter = null;
let currentMode = 'read';
let autoSaveTimer = null;
let currentPreviewPct = 50;
let lastSavedSnapshot = '';
window.__simCodes = {};

// Cifrado: la contraseña vive solo en memoria durante la sesión
let noteIsEncrypted = false;
let currentPassphrase = null;
let passphraseResolver = null;
let passphraseMode = null;

// Flashcards
let fcQueue = [];
let fcIndex = 0;
let fcCurrentCard = null;

const STATUS_LABELS = { 'por-escribir': 'Por escribir', 'en-desarrollo': 'En desarrollo', 'consolidado': 'Consolidado', 'indice': 'Índice' };
const $ = (id) => document.getElementById(id);
const isMobile = () => window.matchMedia('(max-width: 767px)').matches;

marked.setOptions({ breaks: true, gfm: true });

/* ---------- Cifrado cliente (AES-GCM + PBKDF2): el servidor solo ve un blob ---------- */
async function deriveKey(passphrase, saltBytes) {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey('raw', enc.encode(passphrase), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt: saltBytes, iterations: 150000, hash: 'SHA-256' },
    keyMaterial, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']
  );
}
function bufToB64(buf) { return btoa(String.fromCharCode(...new Uint8Array(buf))); }
function b64ToBuf(b64) { return Uint8Array.from(atob(b64), c => c.charCodeAt(0)); }
async function encryptContent(plaintext, passphrase) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(passphrase, salt);
  const cipherBuf = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, new TextEncoder().encode(plaintext));
  return JSON.stringify({ salt: bufToB64(salt), iv: bufToB64(iv), data: bufToB64(cipherBuf) });
}
async function decryptContent(blobStr, passphrase) {
  const blob = JSON.parse(blobStr);
  const key = await deriveKey(passphrase, b64ToBuf(blob.salt));
  const plainBuf = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64ToBuf(blob.iv) }, key, b64ToBuf(blob.data));
  return new TextDecoder().decode(plainBuf);
}

function askPassphrase(mode, title, msg) {
  return new Promise((resolve) => {
    passphraseMode = mode;
    passphraseResolver = resolve;
    $('passphraseTitle').textContent = title;
    $('passphraseMsg').textContent = msg;
    $('passphraseInput').value = '';
    $('passphraseConfirmInput').value = '';
    $('passphraseConfirmField').hidden = mode !== 'setup';
    $('passphraseError').hidden = true;
    openModal('passphraseModal', { focus: '#passphraseInput' });
  });
}
function confirmPassphrase() {
  const pass = $('passphraseInput').value;
  if (!pass) { $('passphraseInput').focus(); return; }
  if (passphraseMode === 'setup' && pass !== $('passphraseConfirmInput').value) {
    $('passphraseError').textContent = 'Las contraseñas no coinciden.';
    $('passphraseError').hidden = false;
    return;
  }
  const resolver = passphraseResolver;
  passphraseResolver = null;
  closeModal('passphraseModal');
  if (resolver) resolver(pass);
}
function cancelPassphrase() {
  const resolver = passphraseResolver;
  passphraseResolver = null;
  closeModal('passphraseModal');
  if (resolver) resolver(null);
}
$('passphraseInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); confirmPassphrase(); } });
$('passphraseConfirmInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); confirmPassphrase(); } });

async function toggleEncryption() {
  if (!$('currentNoteId').value) return;
  if (!noteIsEncrypted) {
    const pass = await askPassphrase('setup', 'Proteger esta nota',
      'Elige una contraseña. Si la olvidas no podrás recuperar el contenido: no se guarda en ningún sitio.');
    if (!pass) return;
    currentPassphrase = pass;
    noteIsEncrypted = true;
  } else {
    const ok = await uiConfirm('Quitar la protección', 'La nota volverá a guardarse como texto legible.', { confirmLabel: 'Quitar protección' });
    if (!ok) return;
    noteIsEncrypted = false;
    currentPassphrase = null;
  }
  updateLockToggleUI();
  scheduleAutoSave();
}
function updateLockToggleUI() {
  const el = $('lockToggle');
  el.innerHTML = icon(noteIsEncrypted ? 'lock' : 'lock-open', 'icon-sm');
  el.setAttribute('aria-pressed', String(noteIsEncrypted));
  el.setAttribute('aria-label', noteIsEncrypted ? 'Nota cifrada: quitar protección' : 'Cifrar nota');
}

/* ---------- Árbol de categorías ---------- */
const CAT_COLORS = window.CATEGORY_COLORS;
function categoryColor(cat) {
  let hash = 0;
  for (let i = 0; i < cat.length; i++) hash = (hash * 31 + cat.charCodeAt(i)) | 0;
  return CAT_COLORS[Math.abs(hash) % CAT_COLORS.length];
}
function splitCategoryPath(catRaw) {
  if (!catRaw || !catRaw.trim()) return ['Sin categoría'];
  const parts = catRaw.replace(/->/g, ' - ').split(/\s+-\s+/).map(s => s.trim()).filter(Boolean);
  return parts.length ? parts : ['Sin categoría'];
}
function buildTree(notes) {
  const root = { notes: [], children: {} };
  notes.forEach(n => {
    let node = root;
    splitCategoryPath(n.category).forEach((part, idx, parts) => {
      const key = part.toLowerCase();
      if (!node.children[key]) node.children[key] = { notes: [], children: {}, label: part };
      node = node.children[key];
      if (idx === parts.length - 1) node.notes.push(n);
    });
  });
  return root;
}
function countNotesRecursive(node) {
  return node.notes.length + Object.values(node.children).reduce((acc, c) => acc + countNotesRecursive(c), 0);
}
// Plegado de categorías en el servidor (Prefs, ui.js); localStorage solo es la caché
function getCatState(path) { return !Prefs.get('notes-fold', {})[path]; }
function setCatState(path, open) {
  const folds = { ...Prefs.get('notes-fold', {}) };
  if (open) delete folds[path]; else folds[path] = true;
  Prefs.set('notes-fold', folds);
}
document.addEventListener('prefs:changed', () => { if (allNotes.length) applyFilters($('searchInput').value.trim()); });

function renderTreeNode(node, container, path, depth, highlight, color) {
  const isOpen = highlight ? true : getCatState(path);
  const wrapper = document.createElement('div');
  wrapper.className = 'tree-group';
  const header = document.createElement('button');
  header.type = 'button';
  header.className = `tree-row depth-${Math.min(depth, 1)}`;
  header.setAttribute('aria-expanded', String(isOpen));
  header.innerHTML = icon('chevron-down', 'chev') +
    (depth === 0 ? `<span class="cat-dot" style="background:${color}"></span>` : '') +
    `<span class="label">${highlight ? highlightText(node.label, highlight) : escapeHtml(node.label)}</span>` +
    `<span class="count">${countNotesRecursive(node)}</span>`;
  const children = document.createElement('div');
  children.className = 'tree-children';
  children.hidden = !isOpen;
  header.addEventListener('click', () => {
    const open = header.getAttribute('aria-expanded') !== 'true';
    header.setAttribute('aria-expanded', String(open));
    children.hidden = !open;
    setCatState(path, open);
  });
  // Orden manual (si lo hay) y si no, alfabético
  node.notes.sort((a, b) => ((a.position ?? Infinity) - (b.position ?? Infinity)) || (a.title || '').localeCompare(b.title || '', 'es'))
    .forEach(note => children.appendChild(makeNoteItem(note, highlight)));
  makeNotesSortable(children, path, highlight);
  Object.values(node.children).sort((a, b) => a.label.localeCompare(b.label, 'es'))
    .forEach(child => renderTreeNode(child, children, path + '/' + child.label, depth + 1, highlight, color));
  wrapper.append(header, children);
  container.appendChild(wrapper);
}

/* Arrastrar notas para ordenarlas dentro de su categoría (componente común sortable.js) */
function makeNotesSortable(container, path, highlight) {
  Sortable.create(container, {
    group: 'notas', items: '.note-row', label: path.split('/').pop(),
    id: (el) => el.dataset.id, data: { path: path.toLowerCase() },
    accepts: (ctx) => {
      if (highlight) return 'Quita la búsqueda para ordenar';
      return ctx.to.data.path === ctx.from.data.path ? true : 'Las notas solo se ordenan dentro de su categoría';
    },
    onDrop: async (ctx) => {
      await api(`/api/notes/${encodeURIComponent(ctx.id)}/move`, { method: 'POST', quiet: true, body: { before_id: ctx.beforeId } });
      await loadNotes();
    },
  });
}

function renderNotesList(notes, highlight) {
  const el = $('notesList');
  if (!notes.length) {
    el.innerHTML = allNotes.length
      ? emptyState({ iconName: 'search', title: 'Sin resultados', text: 'Prueba con otra palabra o quita los filtros.', compact: true })
      : emptyState({ iconName: 'notebook-pen', title: 'Aún no hay notas', text: 'Crea la primera y empieza a enlazar ideas.', compact: true });
    return;
  }
  el.innerHTML = '';
  Object.values(buildTree(notes).children).sort((a, b) => a.label.localeCompare(b.label, 'es'))
    .forEach(cat => renderTreeNode(cat, el, cat.label, 0, highlight, categoryColor(cat.label)));
}

function makeNoteItem(note, highlight) {
  const item = document.createElement('a');
  item.href = '?note=' + encodeURIComponent(note.id);
  item.className = 'note-row';
  item.dataset.id = note.id;
  if (note.id === activeNoteId) item.setAttribute('aria-current', 'true');
  const status = note.status || 'por-escribir';
  item.innerHTML = `<span class="status-dot" data-status="${status}" title="${STATUS_LABELS[status] || ''}"></span>` +
    `<span class="note-title">${highlight ? highlightText(note.title || note.id, highlight) : escapeHtml(note.title || note.id)}</span>` +
    (note.encrypted ? icon('lock') : '');
  item.addEventListener('click', (e) => { e.preventDefault(); openNote(note.id); });
  return item;
}

function highlightText(text, q) {
  const safe = escapeHtml(text || '');
  if (!q) return safe;
  const pattern = escapeHtml(q).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return safe.replace(new RegExp(pattern, 'gi'), m => `<mark>${m}</mark>`);
}

function setStatusFilter(status) {
  statusFilter = status;
  document.querySelectorAll('[data-status-filter]').forEach(c => c.setAttribute('aria-pressed', String(c.dataset.statusFilter === status)));
  applyFilters($('searchInput').value.trim());
}
document.querySelectorAll('[data-status-filter]').forEach(c => c.addEventListener('click', () => setStatusFilter(c.dataset.statusFilter)));

function renderTagChips() {
  const allTags = new Set();
  allNotes.forEach(n => (n.tags || '').split(',').map(t => t.trim()).filter(Boolean).forEach(t => allTags.add(t)));
  const container = $('tagChips');
  container.innerHTML = [...allTags].sort((a, b) => a.localeCompare(b, 'es')).map(tag =>
    `<button type="button" class="chip" data-tag="${escapeHtml(tag)}" aria-pressed="${tagFilter === tag}">#${escapeHtml(tag)}</button>`).join('');
  container.querySelectorAll('[data-tag]').forEach(b => b.addEventListener('click', () => {
    tagFilter = tagFilter === b.dataset.tag ? null : b.dataset.tag;
    renderTagChips();
    applyFilters($('searchInput').value.trim());
  }));
}

function applyFilters(query) {
  let filtered = allNotes;
  if (statusFilter !== 'all') filtered = filtered.filter(n => (n.status || 'por-escribir') === statusFilter);
  if (tagFilter) filtered = filtered.filter(n => (n.tags || '').split(',').map(t => t.trim()).includes(tagFilter));
  if (query) {
    const scored = filtered.map(n => ({ note: n, ...fuzzyMatch((n.title || '') + ' ' + (n.category || ''), query) }))
      .filter(x => x.match).sort((a, b) => b.score - a.score);
    renderNotesList(scored.map(x => x.note), query);
  } else {
    renderNotesList(filtered);
  }
}

function fuzzyMatch(str, pattern) {
  str = str.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  pattern = pattern.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  if (!pattern) return { match: true, score: 0 };
  let si = 0, pi = 0, score = 0, consecutive = 0;
  while (si < str.length && pi < pattern.length) {
    if (str[si] === pattern[pi]) { score += 1 + consecutive; consecutive++; pi++; } else consecutive = 0;
    si++;
  }
  return { match: pi === pattern.length, score };
}
let searchTimer;
$('searchInput').addEventListener('input', (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => applyFilters(e.target.value.trim()), 100);
});

/* ---------- Migas y autocompletado de categoría ---------- */
function updateBreadcrumbs() {
  const cat = $('noteCategory').value.trim();
  const bc = $('breadcrumbs');
  if (!cat) { bc.innerHTML = ''; return; }
  const parts = splitCategoryPath(cat);
  bc.innerHTML = `<span class="cat-dot" style="background:${categoryColor(parts[0])}"></span>` +
    parts.map(p => `<span class="crumb">${escapeHtml(p)}</span>`).join(`<span class="sep">${icon('chevron-right', 'icon-sm')}</span>`);
}

let categorySuggestionIndex = -1;
function getCategoryNode(prefixParts) {
  let node = buildTree(allNotes);
  for (const p of prefixParts) {
    node = node.children[p.toLowerCase()];
    if (!node) return null;
  }
  return node;
}
function updateCategorySuggestions(inputId = 'noteCategory', boxId = 'categorySuggestions') {
  const input = $(inputId), box = $(boxId);
  const rawParts = splitCategoryPath(input.value);
  const typing = input.value.trim() ? rawParts[rawParts.length - 1] : '';
  const node = getCategoryNode(input.value.trim() ? rawParts.slice(0, -1) : []);
  if (!node) return hideSuggestionBox(box, input);
  const q = typing.toLowerCase();
  const candidates = Object.values(node.children).map(c => c.label)
    .filter(label => label.toLowerCase().includes(q) && label.toLowerCase() !== q);
  if (!candidates.length) return hideSuggestionBox(box, input);
  categorySuggestionIndex = -1;
  box.innerHTML = candidates.slice(0, 8).map((label, i) =>
    `<button type="button" class="menu-item" role="option" id="${boxId}-o${i}" data-label="${escapeHtml(label)}">
       <span class="status-dot" style="background:${categoryColor(label)}"></span>${escapeHtml(label)}</button>`).join('');
  box.querySelectorAll('[data-label]').forEach(el => el.addEventListener('mousedown', (e) => {
    e.preventDefault();
    selectCategorySuggestion(el.dataset.label, inputId, boxId);
  }));
  box.hidden = false;
  placeSuggest(box, input);
  input.setAttribute('aria-expanded', 'true');
}
// Abre la lista hacia donde quepa entera (abajo por defecto, arriba si no hay sitio) y nunca más alta que el hueco
function placeSuggest(box, input) {
  box.classList.remove('suggest-up');
  box.style.maxHeight = box.style.top = box.style.bottom = '';
  const r = input.getBoundingClientRect();
  const vh = window.visualViewport?.height || innerHeight;
  const below = vh - r.bottom - 12, above = r.top - 12;
  const need = box.scrollHeight;
  const up = need > below && above > below;
  box.classList.toggle('suggest-up', up);
  // Pegada al campo aunque debajo haya una ayuda (posiciones relativas a su contenedor)
  if (box.offsetParent === input.offsetParent) {
    if (up) { box.style.top = 'auto'; box.style.bottom = (box.offsetParent.clientHeight - input.offsetTop + 4) + 'px'; }
    else { box.style.bottom = 'auto'; box.style.top = (input.offsetTop + input.offsetHeight + 4) + 'px'; }
  }
  box.style.maxHeight = Math.max(120, Math.min(need, up ? above : below)) + 'px';
}
function hideSuggestionBox(box, input) {
  box.hidden = true;
  input?.setAttribute('aria-expanded', 'false');
  input?.removeAttribute('aria-activedescendant');
}
function selectCategorySuggestion(label, inputId = 'noteCategory', boxId = 'categorySuggestions') {
  const input = $(inputId);
  const rawParts = input.value.trim() ? splitCategoryPath(input.value) : [''];
  rawParts[rawParts.length - 1] = label;
  input.value = rawParts.join(' - ');
  hideSuggestionBox($(boxId), input);
  if (inputId === 'noteCategory') { updateBreadcrumbs(); scheduleAutoSave(); }
  input.focus();
}
function handleCategoryKeydown(e, inputId = 'noteCategory', boxId = 'categorySuggestions') {
  const box = $(boxId), input = $(inputId);
  if (box.hidden) return;
  const items = [...box.querySelectorAll('[data-label]')];
  if (!items.length) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    categorySuggestionIndex = (categorySuggestionIndex + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items.forEach((it, i) => it.setAttribute('aria-selected', String(i === categorySuggestionIndex)));
    input.setAttribute('aria-activedescendant', items[categorySuggestionIndex].id);
  } else if ((e.key === 'Enter' || e.key === 'Tab') && categorySuggestionIndex >= 0) {
    e.preventDefault();
    selectCategorySuggestion(items[categorySuggestionIndex].dataset.label, inputId, boxId);
  } else if (e.key === 'Escape') {
    e.stopPropagation();
    hideSuggestionBox(box, input);
  }
}
for (const [inputId, boxId] of [['noteCategory', 'categorySuggestions'], ['newNoteCategoryInput', 'newNoteCategorySuggestions']]) {
  const input = $(inputId);
  input.addEventListener('input', () => updateCategorySuggestions(inputId, boxId));
  input.addEventListener('focus', () => updateCategorySuggestions(inputId, boxId));
  input.addEventListener('keydown', (e) => handleCategoryKeydown(e, inputId, boxId));
  input.addEventListener('blur', () => setTimeout(() => hideSuggestionBox($(boxId), input), 120));
}
$('noteCategory').addEventListener('input', () => { updateBreadcrumbs(); scheduleAutoSave(); });

/* ---------- Cargar / abrir / guardar ---------- */
async function loadNotes() {
  try {
    const data = await api('/api/notes');
    allNotes = data.notes;
  } catch {
    $('notesList').innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudieron cargar las notas', text: 'Revisa la conexión y recarga.', compact: true });
    return;
  }
  renderTagChips();
  applyFilters($('searchInput').value.trim());
  if (!$('emptyState').hidden) renderNotesHome();
}

function showNotePane(show) {
  $('editorArea').hidden = !show;
  $('emptyState').hidden = show;
  document.body.classList.toggle('note-open', show);
  if (!show) renderNotesHome();
}

/* ---------- Portada (sin nota abierta): cómo van las notas y por dónde seguir ---------- */
async function renderNotesHome() {
  const box = $('notesHome');
  if (!box || matchMedia('(max-width: 767px)').matches) return;
  let d;
  try { d = await api('/api/notes-home', { quiet: true }); } catch { return; }
  if (!d.total) return;  // sin notas: se queda el mensaje de bienvenida
  const orden = ['consolidado', 'en-desarrollo', 'por-escribir', 'indice'];
  const bar = orden.filter((k) => d.estados[k]).map((k) => `<span data-status="${k}" style="flex:${d.estados[k]}" title="${STATUS_LABELS[k]}: ${d.estados[k]}"></span>`).join('');
  const legend = orden.filter((k) => d.estados[k]).map((k) => `<span class="nh-legend-item" data-status="${k}"><span class="status-dot"></span>${STATUS_LABELS[k]} <b class="tabular">${d.estados[k]}</b></span>`).join('');
  const row = (n, extra) => `<li><button type="button" class="nh-row" data-open="${escapeHtml(n.id)}">
      <span class="status-dot" data-status="${n.status}" aria-hidden="true"></span>
      <span class="nh-title">${escapeHtml(n.title)}</span>
      <span class="nh-meta tiny muted">${extra(n)}</span></button></li>`;
  const card = (title, iconName, list, extra, emptyText, more = '') => `<section class="nh-card" aria-label="${title}">
      <h3 class="nh-h">${icon(iconName, 'icon-sm')}${title}${more}</h3>
      ${list.length ? `<ul class="nh-list">${list.map((n) => row(n, extra)).join('')}</ul>` : `<p class="small muted">${emptyText}</p>`}</section>`;
  const cat = (n) => escapeHtml((n.category || '').split(/->| - /)[0].trim());
  const pct = Math.round((d.estados.consolidado || 0) / d.total * 100);
  box.innerHTML = `<div class="nh">
      <header class="nh-head">
        <div><h2 class="nh-title-main">Tus notas</h2>
          <p class="small muted"><b class="tabular">${d.total}</b> notas · <b class="tabular">${pct} %</b> consolidadas</p></div>
        <div class="nh-actions">
          <button type="button" class="btn btn-primary" onclick="createNewNotePrompt()">${icon('square-pen', 'icon-sm')}Nueva nota</button>
          ${d.flashcards ? `<button type="button" class="btn btn-tinted" onclick="openFlashcardsModal()">${icon('layers', 'icon-sm')}Repasar ${d.flashcards} flashcard${d.flashcards === 1 ? '' : 's'}</button>` : ''}
          <button type="button" class="btn" onclick="quickRecall()">${icon('shuffle', 'icon-sm')}Una al azar</button>
        </div>
      </header>
      <div class="nh-bar" role="img" aria-label="${orden.filter((k) => d.estados[k]).map((k) => `${STATUS_LABELS[k]}: ${d.estados[k]}`).join(', ')}">${bar}</div>
      <div class="nh-legend">${legend}</div>
      <div class="nh-grid">
        ${card('Seguir escribiendo', 'history', d.recientes, (n) => (n.last_modified ? timeAgo(n.last_modified) : cat(n)), 'Aún no has editado ninguna.')}
        ${card('Por escribir', 'pencil', d.por_escribir, cat, '¡Nada pendiente de escribir!',
          d.estados['por-escribir'] > d.por_escribir.length ? ` <span class="tiny muted tabular">${d.estados['por-escribir']}</span>` : '')}
        ${card('Hace tiempo que no repasas', 'brain', d.olvidadas, (n) => (n.last_reviewed ? `repasada ${timeAgo(n.last_reviewed)}` : 'sin repasar'), 'Consolida alguna nota y aparecerá aquí.')}
      </div>
    </div>`;
}
document.addEventListener('click', (e) => {
  const b = e.target.closest('#notesHome [data-open]');
  if (b) openNote(b.dataset.open);
});
function closeNoteMobile() {
  flushAutoSave();
  document.body.classList.remove('note-open');
  if (isMobile()) {
    activeNoteId = null;
    $('editorArea').hidden = true;
    history.replaceState(null, '', location.pathname);
    applyFilters($('searchInput').value.trim());
  }
}

async function openNote(id) {
  if (activeNoteId && activeNoteId !== id) flushAutoSave();
  let note;
  try {
    note = await api(`/api/notes/${encodeURIComponent(id)}`, { quiet: true });
  } catch (err) {
    if (err.status === 404) {
      try { localStorage.removeItem('lastOpenNoteId'); } catch {}
      const title = id.replace(/-/g, ' ');
      const ok = await uiConfirm('Esa nota todavía no existe', `¿Crear «${title}»?`, { confirmLabel: 'Crear nota' });
      if (ok) createNoteDirect(title.charAt(0).toUpperCase() + title.slice(1), $('noteCategory').value.trim() || 'General', id);
    } else toast('No se pudo abrir la nota', { type: 'error' });
    return;
  }

  activeNoteId = id;
  try { localStorage.setItem('lastOpenNoteId', id); } catch {}
  if (new URLSearchParams(location.search).get('note') !== id) history.replaceState(null, '', '?note=' + encodeURIComponent(id));
  activeStatus = note.status || 'por-escribir';
  noteIsEncrypted = !!note.encrypted;
  currentPassphrase = null;
  updateLockToggleUI();

  $('currentNoteId').value = id;
  $('noteTitle').value = note.title || '';
  requestAnimationFrame(autosizeTitle);
  $('noteCategory').value = note.category || '';
  $('noteTags').value = note.tags || '';
  showNotePane(true);
  updateStatusBadge();
  updateBreadcrumbs();
  showSaveIndicator('');

  if (noteIsEncrypted) {
    $('noteContent').value = '';
    startedEmpty = false;
    setMode('read');
  } else {
    $('noteContent').value = note.content || '';
    lastSavedSnapshot = snapshot();
    armAutoStatus();
    updateCharCount();
    if (note.status === 'consolidado' || note.status === 'indice' || isMobile()) setMode('read');
    else setMode('edit');
    api(`/api/notes/${encodeURIComponent(id)}/reviewed`, { method: 'PATCH', quiet: true }).catch(() => {});
  }
  applyFilters($('searchInput').value.trim());
  $('readPane').scrollTop = 0;
  renderNoteLinks();
}

function showLockScreen() {
  $('readContent').innerHTML = `
    <div class="lock-screen">
      <div class="empty-icon">${icon('lock')}</div>
      <h3>Nota privada</h3>
      <p class="muted">El contenido está cifrado en tu navegador.</p>
      <label class="sr-only" for="unlockInline">Contraseña</label>
      <input type="password" id="unlockInline" class="input" placeholder="Contraseña" autocomplete="off">
      <button type="button" class="btn btn-primary btn-block" id="unlockBtn">Desbloquear</button>
      <p id="unlockError" class="field-error" role="alert" hidden>Contraseña incorrecta.</p>
    </div>`;
  $('unlockInline').addEventListener('keydown', (e) => { if (e.key === 'Enter') unlockCurrentNote(); });
  $('unlockBtn').addEventListener('click', unlockCurrentNote);
  setTimeout(() => $('unlockInline')?.focus(), 50);
}
async function unlockCurrentNote() {
  const pass = $('unlockInline').value;
  if (!pass) return;
  const id = $('currentNoteId').value;
  const note = await api(`/api/notes/${encodeURIComponent(id)}`);
  try {
    const plain = await decryptContent(note.content, pass);
    currentPassphrase = pass;
    $('noteContent').value = plain;
    lastSavedSnapshot = snapshot();
    updateCharCount();
    renderReadMode();
    api(`/api/notes/${encodeURIComponent(id)}/reviewed`, { method: 'PATCH', quiet: true }).catch(() => {});
  } catch {
    $('unlockError').hidden = false;
  }
}

async function checkWikilinkSuggestions(noteId) {
  try {
    const data = await api(`/api/notes/${encodeURIComponent(noteId)}/wikilink-suggestions`, { quiet: true });
    if (!data.suggestions?.length) return;
    const list = data.suggestions.map(s => `«${s.title}» (${s.occurrences}×)`).join(', ');
    const ok = await uiConfirm('Conceptos sin enlazar', `Esta nota menciona notas que ya existen: ${list}. ¿Convertir la primera aparición de cada una en enlace?`, { confirmLabel: 'Enlazar' });
    if (!ok) return;
    const ta = $('noteContent');
    let content = ta.value;
    data.suggestions.forEach(s => {
      const escapedTitle = s.title.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      content = content.replace(new RegExp(`\\b${escapedTitle}\\b`, 'i'), `[[${s.title}]]`);
    });
    ta.value = content;
    updateCharCount(); updatePreview(); scheduleAutoSave();
  } catch {}
}

function snapshot() {
  return JSON.stringify([$('noteTitle').value, $('noteCategory').value, $('noteTags').value, $('noteContent').value, noteIsEncrypted, activeStatus]);
}

async function saveNote(silent = false) {
  const id = $('currentNoteId').value;
  if (!id) return;
  clearTimeout(autoSaveTimer);
  autoSaveTimer = null;
  let contentToSend = $('noteContent').value;
  if (noteIsEncrypted) {
    if (!currentPassphrase) {
      const pass = await askPassphrase('setup', 'Contraseña de esta nota', 'Introduce la contraseña para cifrar y guardar.');
      if (!pass) return;
      currentPassphrase = pass;
    }
    contentToSend = await encryptContent(contentToSend, currentPassphrase);
  }
  const snap = snapshot();
  const payload = {
    title: $('noteTitle').value.trim() || 'Sin título',
    category: $('noteCategory').value,
    content: contentToSend,
    status: activeStatus,
    tags: $('noteTags').value.split(',').map(t => t.trim()).filter(Boolean),
    encrypted: noteIsEncrypted,
  };
  showSaveIndicator('saving');
  try {
    await api(`/api/notes/${encodeURIComponent(id)}`, { method: 'POST', body: payload, quiet: silent });
  } catch {
    showSaveIndicator('error');
    return;
  }
  lastSavedSnapshot = snap;
  showSaveIndicator('saved');
  if (!silent) toast('Nota guardada');
  if (currentMode === 'read' && !noteIsEncrypted) renderReadMode();
  await loadNotes();
  loadFlashcardStats();
  if (!silent && !noteIsEncrypted) checkWikilinkSuggestions(id);
}

function scheduleAutoSave() {
  if (!$('currentNoteId').value) return;
  clearTimeout(autoSaveTimer);
  showSaveIndicator('pending');
  autoSaveTimer = setTimeout(() => saveNote(true), 1000);
}
function flushAutoSave() {
  if (autoSaveTimer && snapshot() !== lastSavedSnapshot) saveNote(true);
}
window.addEventListener('beforeunload', (e) => {
  if (autoSaveTimer && snapshot() !== lastSavedSnapshot) { saveNote(true); e.preventDefault(); }
});

function showSaveIndicator(state) {
  const el = $('saveIndicator');
  el.className = 'save-indicator ' + state;
  el.textContent = { pending: 'Cambios sin guardar', saving: 'Guardando…', saved: 'Guardado', error: 'No se pudo guardar' }[state] || '';
}

async function deleteCurrentNote() {
  const id = $('currentNoteId').value;
  if (!id) return;
  const title = $('noteTitle').value || 'esta nota';
  const ok = await uiConfirm(`¿Eliminar «${title}»?`, 'Irá a la papelera: podrás restaurarla durante 30 días.', { confirmLabel: 'Eliminar', danger: true });
  if (!ok) return;
  const res = await api(`/api/notes/${encodeURIComponent(id)}`, { method: 'DELETE' });
  activeNoteId = null;
  try { localStorage.removeItem('lastOpenNoteId'); } catch {}
  $('currentNoteId').value = '';
  showNotePane(false);
  history.replaceState(null, '', location.pathname);
  toast('Nota en la papelera', { action: res.undo_token ? { label: 'Deshacer', onClick: async () => {
    await api(`/api/trash/brain/${res.undo_token}/restore`, { method: 'POST' });
    await loadNotes();
    openNote(id);
  } } : null });
  await loadNotes();
}

function updateStatusBadge() {
  const badge = $('statusBadge');
  badge.dataset.status = activeStatus;
  $('statusBadgeLabel').textContent = STATUS_LABELS[activeStatus] || activeStatus;
}
function toggleStatusMenu(anchor) {
  openMenu(anchor, Object.entries(STATUS_LABELS).map(([value, label]) => ({
    label: (value === activeStatus ? '✓ ' : '') + label,
    onClick: () => setNoteStatus(value),
  })), { align: 'start' });
}
async function setNoteStatus(status) {
  activeStatus = status;
  updateStatusBadge();
  const id = $('currentNoteId').value;
  if (!id) return;
  showSaveIndicator('saving');
  await api(`/api/notes/${encodeURIComponent(id)}/status`, { method: 'PATCH', body: { status } });
  lastSavedSnapshot = snapshot();
  showSaveIndicator('saved');
  await loadNotes();
}

function openNoteMenu(anchor) {
  openMenu(anchor, [
    { label: 'Guardar ahora', icon: 'save', onClick: () => saveNote(false) },
    { label: 'Mover selección a nota nueva', icon: 'scissors', onClick: splitSelectionToNewNote },
    { label: 'Copiar enlace a la nota', icon: 'link', onClick: copyNoteLink },
    { label: 'Enlazar tarea o idea…', icon: 'square-check', onClick: linkItemToNote },
    { label: 'Historial de versiones', icon: 'history', onClick: openVersions },
    { separator: true },
    { label: 'Eliminar nota', icon: 'trash-2', danger: true, onClick: deleteCurrentNote },
  ]);
}
function copyNoteLink() {
  const title = $('noteTitle').value;
  navigator.clipboard?.writeText(`[[${title}]]`).then(() => toast('Enlace copiado: [[' + title + ']]'), () => toast('No se pudo copiar', { type: 'error' }));
}

/* ---------- Nueva nota ---------- */
function slugify(text) {
  return text.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
}
function createNewNotePrompt() {
  $('newNoteTitleInput').value = '';
  $('newNoteCategoryInput').value = activeNoteId ? $('noteCategory').value.trim() : '';
  $('newNoteError').hidden = true;
  openModal('newNoteModal', { focus: '#newNoteTitleInput' });
}
$('newNoteTitleInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); confirmNewNote(); } });
function confirmNewNote() {
  const title = $('newNoteTitleInput').value.trim();
  const err = $('newNoteError');
  if (!title) { $('newNoteTitleInput').focus(); return; }
  const id = slugify(title);
  if (!id) { err.textContent = 'El título necesita al menos una letra o número.'; err.hidden = false; return; }
  if (allNotes.some(n => n.id === id)) { err.textContent = 'Ya existe una nota con ese título.'; err.hidden = false; return; }
  closeModal('newNoteModal');
  createNoteDirect(title, $('newNoteCategoryInput').value.trim() || 'General', id);
}
function createNoteDirect(title, category, id = slugify(title)) {
  activeNoteId = id;
  activeStatus = 'por-escribir';
  noteIsEncrypted = false;
  currentPassphrase = null;
  updateLockToggleUI();
  $('currentNoteId').value = id;
  $('noteTitle').value = title;
  $('noteCategory').value = category;
  $('noteTags').value = '';
  $('noteContent').value = '# ' + title + '\n\n';
  lastSavedSnapshot = '';
  armAutoStatus();
  showNotePane(true);
  updateStatusBadge();
  updateBreadcrumbs();
  updateCharCount();
  setMode('edit');
  history.replaceState(null, '', '?note=' + encodeURIComponent(id));
  $('noteLinks').hidden = true;
  saveNote(true);
}

/* ---------- Modo lectura / edición ---------- */
function setMode(mode) {
  currentMode = mode;
  const isEdit = mode === 'edit';
  if (isEdit && noteIsEncrypted && !currentPassphrase) { showLockScreen(); return; }
  $('editorArea').classList.toggle('is-reading', !isEdit);
  $('modeBtnRead').setAttribute('aria-pressed', String(!isEdit));
  $('modeBtnEdit').setAttribute('aria-pressed', String(isEdit));
  $('toolbar').hidden = !isEdit;
  $('readPane').hidden = isEdit;
  $('editPane').hidden = !isEdit;
  if (isEdit) {
    updatePreview();
    if (!isMobile()) setTimeout(() => $('noteContent').focus({ preventScroll: true }), 30);
  } else if (!noteIsEncrypted || currentPassphrase) renderReadMode();
  else showLockScreen();
}

function renderReadMode() {
  const raw = $('noteContent').value;
  const container = $('readContent');
  if (!raw.trim()) {
    container.innerHTML = emptyState({ iconName: 'pencil', title: 'Esta nota está vacía', text: 'Pulsa E o el botón Edición para empezar a escribir.', compact: true });
    return;
  }
  container.innerHTML = renderMarkdownWithWikiLinks(raw);
  paintItemLinks(container);
  window.Calendar?.mountEmbeds(container);  // bloques ```calendario
  enhanceRendered(container);
  wireTaskCheckboxes(container, raw);
  renderRelatedNotes();
}

/* Casillas «- [ ]» marcables en modo lectura: cada una es un elemento de la lista
   única de tareas (items.js), así que se marca con la misma acción que en el Inbox
   o en Tareas; el servidor cambia solo esa línea del .md. */
const TASK_LINE_RE = /^(\s*[-*+] \[)([ xX])(\] .+)$/;
function taskLines(raw) {
  const out = [];
  let fence = false;
  raw.split('\n').forEach((line, i) => {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence;
    else if (!fence && TASK_LINE_RE.test(line)) out.push(i);
  });
  return out;
}
function wireTaskCheckboxes(container, raw) {
  const boxes = [...container.querySelectorAll('li > input[type="checkbox"]')];
  const lines = taskLines(raw);
  if (!boxes.length || boxes.length !== lines.length || noteIsEncrypted) return; // si no cuadran, mejor no tocar nada
  boxes.forEach((box, k) => {
    box.disabled = false;
    box.setAttribute('aria-label', box.checked ? 'Desmarcar tarea' : 'Marcar tarea como hecha');
    box.addEventListener('change', async () => {
      const id = activeNoteId;
      const done = box.checked;
      box.disabled = true;
      try {
        if (autoSaveTimer || snapshot() !== lastSavedSnapshot) await saveNote(true); // lo pendiente de guardar, primero
        await Items.load();
        const it = Items.state.items.find((i) => i.origin === 'nota' && i.note_id === id && i.note_index === k);
        if (!it) throw new Error('La nota ha cambiado: recárgala');
        await Items.setDone(it.id, done);
        await reloadActiveNote(true);
      } catch (err) {
        box.checked = !done;
        box.disabled = false;
        toast(err.message || 'No se pudo marcar la tarea', { type: 'error' });
      }
    });
  });
}

function enhanceRendered(container) {
  if (window.renderMathInElement) {
    renderMathInElement(container, {
      delimiters: [{ left: '$$', right: '$$', display: true }, { left: '$', right: '$', display: false }],
      throwOnError: false,
    });
  }
  if (window.hljs) container.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
  const known = new Set(allNotes.map(n => n.id));
  container.querySelectorAll('.wiki-link[data-note-id]').forEach(a => {
    if (allNotes.length && !known.has(a.dataset.noteId)) { a.classList.add('missing'); a.title = 'Nota inexistente: pulsa para crearla'; }
  });
}

/* ---------- Cambios hechos en otra pestaña (Tareas, Inbox, Gestión…) ----------
   Se recarga la lista y, si la nota abierta no tiene cambios sin guardar, también
   su contenido (p. ej. una casilla marcada desde /tareas). */
async function refreshFromOtherTab() {
  await loadNotes();
  await reloadActiveNote();
  renderNoteLinks();
}
// Vuelve a leer la nota abierta si no tiene cambios sin guardar (force: tras marcar una casilla aquí)
async function reloadActiveNote(force = false) {
  const id = activeNoteId;
  if (!id || noteIsEncrypted || (!force && (autoSaveTimer || snapshot() !== lastSavedSnapshot))) return;
  let note;
  try { note = await api(`/api/notes/${encodeURIComponent(id)}`, { quiet: true }); } catch { return; }
  if (id !== activeNoteId || (note.content || '') === $('noteContent').value) return;
  $('noteContent').value = note.content || '';
  lastSavedSnapshot = snapshot();
  if (currentMode === 'read') renderReadMode(); else updatePreview();
}
onDataChange(/^\/api\/(notes|items|inbox|bulk\/notes)/, refreshFromOtherTab);

/* ---------- Tareas, ideas y rutinas enlazadas ([[tarea:N]]) ---------- */
const ITEM_ICONS = { tarea: 'square-check', idea: 'lightbulb', rutina: 'repeat' };
async function paintItemLinks(container) {
  const links = [...container.querySelectorAll('.item-link[data-item-id]')];
  if (!links.length) return;
  try { await Items.ready(); } catch { return; }
  links.forEach((a) => {
    const it = Items.get(Number(a.dataset.itemId));
    a.classList.toggle('missing', !it);
    a.classList.toggle('is-done', !!it?.done);
    a.innerHTML = it ? `${icon(it.done ? 'circle-check' : ITEM_ICONS[it.type] || 'square-check', 'icon-sm')}<span>${escapeHtml(it.text.split('\n')[0].slice(0, 80))}</span>`
      : `${icon('unlink', 'icon-sm')}<span>Elemento borrado</span>`;
    a.title = it ? `Abrir en Tareas (${it.type})` : 'Ya no existe';
  });
}
// Barra de la cabecera con las tareas e ideas enlazadas (en lectura y en edición): un clic lleva a ellas
async function renderNoteLinks() {
  const id = activeNoteId, bar = $('noteLinks');
  if (!id || noteIsEncrypted) { bar.hidden = true; return; }
  const { items } = await api(`/api/notes/${encodeURIComponent(id)}/links`, { quiet: true }).catch(() => ({ items: [] }));
  if (id !== activeNoteId) return;
  bar.hidden = !items.length;
  bar.innerHTML = items.length ? `<span class="note-links-label">${icon('link', 'icon-sm')}<span class="sr-only">Enlazadas:</span></span>`
    + items.map((it) => `<a href="/tareas?item=${it.id}" class="item-link${it.done ? ' is-done' : ''}" data-item-id="${it.id}" title="Abrir en Tareas">${icon(it.done ? 'circle-check' : ITEM_ICONS[it.type] || 'square-check', 'icon-sm')}<span>${escapeHtml(it.text.split('\n')[0].slice(0, 60))}</span></a>`).join('')
    + `<button type="button" class="btn btn-ghost btn-icon btn-sm" onclick="linkItemToNote()" aria-label="Enlazar otra tarea o idea" title="Enlazar otra tarea o idea">${icon('plus', 'icon-sm')}</button>` : '';
}
async function linkItemToNote() {
  const id = activeNoteId;
  if (!id) return;
  if (noteIsEncrypted) { toast('Una nota privada no admite enlaces', { type: 'info' }); return; }
  const picked = await uiPick({
    title: 'Enlazar una tarea o idea', placeholder: 'Busca una tarea, idea o rutina',
    load: async () => {
      await Items.ready();
      const linked = new Set((await api(`/api/notes/${encodeURIComponent(id)}/links`, { quiet: true })).items.map((x) => x.id));
      return Items.state.items.filter((it) => !it.parent_id && !linked.has(it.id) && !(it.origin === 'nota' && it.note_id === id))
        .sort((a, b) => a.done - b.done)
        .map((it) => ({ id: it.id, label: it.text.split('\n')[0].slice(0, 120), sub: `${it.type}${it.done ? ' · hecha' : ''}${it.category ? ' · ' + it.category : ''}`, icon: ITEM_ICONS[it.type] }));
    },
  });
  if (!picked) return;
  if (autoSaveTimer || snapshot() !== lastSavedSnapshot) await saveNote(true);
  await api(`/api/items/${picked.id}/links`, { method: 'POST', body: { note_id: id } });
  await reloadActiveNote(true);
  await Items.load();
  if (currentMode === 'read') renderReadMode();
  renderNoteLinks();
  toast('Enlazada', { action: { label: 'Ver', onClick: () => { location.href = `/tareas?item=${picked.id}`; } } });
}

/* ---------- Notas relacionadas y enlaces entrantes ---------- */
async function renderRelatedNotes() {
  const id = $('currentNoteId').value;
  if (!id) return;
  const enc = encodeURIComponent(id);
  const [related, back] = await Promise.all([
    api(`/api/notes/${enc}/related`, { quiet: true }).catch(() => ({})),
    api(`/api/notes/${enc}/backlinks`, { quiet: true }).catch(() => ({})),
  ]);
  if ($('currentNoteId').value !== id) return; // se cambió de nota mientras cargaba
  const container = $('readContent');
  container.querySelectorAll('.related-notes').forEach((el) => el.remove());
  if (back.backlinks?.length) {
    const box = document.createElement('section');
    box.className = 'related-notes backlinks';
    box.innerHTML = `<h2>Enlazan aquí <span class="badge">${back.backlinks.length}</span></h2><ul class="list">` +
      back.backlinks.map((b) => `<li><a class="list-row" href="?note=${encodeURIComponent(b.id)}" data-open-note="${escapeHtml(b.id)}">
        <span class="row-main"><span class="row-title">${escapeHtml(b.title)}</span>
        <span class="row-sub">${escapeHtml(b.context[0]).replace(/\[\[(.+?)\]\]/g, '<mark>$1</mark>')}</span></span>
        ${icon('chevron-right', 'icon-sm subtle')}</a></li>`).join('') + '</ul>';
    container.appendChild(box);
  }
  if (related.related?.length) {
    const box = document.createElement('section');
    box.className = 'related-notes';
    box.innerHTML = `<h2>Notas relacionadas</h2><div class="chips">` +
      related.related.map(n => `<a href="?note=${encodeURIComponent(n.id)}" class="wiki-link" data-note-id="${escapeHtml(n.id)}">${escapeHtml(n.title)}</a>`).join('') + '</div>';
    container.appendChild(box);
  }
}

/* ---------- Historial de versiones ---------- */
let versionsDialog = null;
async function openVersions() {
  const id = $('currentNoteId').value;
  if (!id) return;
  flushAutoSave();
  if (!versionsDialog) {
    versionsDialog = document.createElement('dialog');
    versionsDialog.className = 'modal modal-lg versions-modal';
    versionsDialog.innerHTML = `
      <div class="modal-header"><div><h2>Historial de versiones</h2><p class="modal-sub">Se guarda el estado anterior cada vez que vuelves a editar tras un rato.</p></div>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body versions-body"><ul class="list versions-list" role="listbox" aria-label="Versiones"></ul>
        <div class="versions-preview prose" aria-live="polite"></div></div>
      <div class="modal-footer"><span class="tiny subtle versions-info"></span><span class="spacer"></span>
        <button type="button" class="btn" data-close>Cerrar</button>
        <button type="button" class="btn btn-primary" data-restore-version disabled>Restaurar esta versión</button></div>`;
    document.body.appendChild(versionsDialog);
    wireAllDialogs();
  }
  const dlg = versionsDialog;
  const list = dlg.querySelector('.versions-list');
  const preview = dlg.querySelector('.versions-preview');
  const restoreBtn = dlg.querySelector('[data-restore-version]');
  const fmt = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' });
  list.innerHTML = skeletonRows(4);
  preview.innerHTML = '';
  restoreBtn.disabled = true;
  openModal(dlg);
  const { versions } = await api(`/api/notes/${encodeURIComponent(id)}/versions`);
  if (!versions.length) {
    list.innerHTML = '';
    preview.innerHTML = emptyState({ iconName: 'history', title: 'Aún no hay versiones anteriores', text: 'Aparecerán aquí cuando vuelvas a editar esta nota.', compact: true });
    return;
  }
  list.innerHTML = versions.map((v, i) => `<li><button type="button" class="list-row" role="option" aria-selected="false" data-version="${v.id}">
    <span class="row-main"><span class="row-title">${fmt.format(new Date(v.saved_at * 1000))}</span>
    <span class="row-sub">${timeAgo(v.saved_at)} · ${v.encrypted ? 'cifrada' : `${v.words} palabras`}${i === 0 ? ' · la más reciente' : ''}</span></span></button></li>`).join('');
  let selected = null;
  list.onclick = async (e) => {
    const b = e.target.closest('[data-version]');
    if (!b) return;
    list.querySelectorAll('[data-version]').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    selected = b.dataset.version;
    const v = await api(`/api/notes/${encodeURIComponent(id)}/versions/${selected}`);
    preview.innerHTML = v.encrypted ? emptyState({ iconName: 'lock', title: 'Versión cifrada', text: 'Se puede restaurar; para leerla necesitarás la contraseña.', compact: true })
      : renderMarkdownWithWikiLinks(v.content);
    restoreBtn.disabled = false;
  };
  restoreBtn.onclick = async () => {
    const ok = await uiConfirm('¿Restaurar esta versión?', 'El contenido actual se guarda antes en el historial, así que puedes volver a él.', { confirmLabel: 'Restaurar' });
    if (!ok) return;
    await api(`/api/notes/${encodeURIComponent(id)}/versions/${selected}/restore`, { method: 'POST' });
    closeModal(dlg);
    toast('Versión restaurada');
    await loadNotes();
    openNote(id);
  };
  list.querySelector('[data-version]')?.click();
}

async function splitSelectionToNewNote() {
  if (currentMode !== 'edit') setMode('edit');
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const selectedText = ta.value.substring(s, e).trim();
  if (!selectedText) { toast('Selecciona primero el texto que quieres mover', { type: 'info' }); return; }
  const title = (await uiPrompt('Nueva nota con la selección', { label: 'Título', confirmLabel: 'Crear y enlazar' }))?.trim();
  if (!title) return;
  const newId = slugify(title);
  if (!newId || allNotes.some(n => n.id === newId)) { toast('Ya existe una nota con ese título', { type: 'error' }); return; }
  await api(`/api/notes/${newId}`, { method: 'POST', body: {
    title, category: $('noteCategory').value || 'General', content: selectedText, status: 'por-escribir', tags: [], encrypted: false,
  } });
  ta.setRangeText(`[[${title}]]`, s, e, 'end');
  ta.focus();
  scheduleAutoSave();
  updatePreview();
  await loadNotes();
  toast(`Nota «${title}» creada y enlazada`);
}

/* ---------- Repaso ---------- */
async function quickRecall() {
  try {
    const data = await api('/api/notes/recall', { quiet: true });
    if (data.note_id) await openNote(data.note_id);
  } catch {
    toast('Todavía no hay notas para repasar', { type: 'info' });
  }
}

/* ---------- Anotaciones ---------- */
const ANNOT_LABELS = { resumir: 'Resumir', entender: 'Entender mejor', mal: 'Está mal' };
async function openAnnotationsModal() {
  $('healthModalTitle').textContent = 'Anotaciones pendientes';
  $('healthContent').innerHTML = skeletonRows(5);
  openModal('healthModal');
  const data = await api('/api/annotations');
  if (!data.annotations.length) {
    $('healthContent').innerHTML = emptyState({ iconName: 'pin', title: 'Nada pendiente', text: 'Marca bloques al editar con R (resumir), E (entender) o el aviso de error.', compact: true });
    return;
  }
  $('healthContent').innerHTML = `<ul class="list">${data.annotations.map(a => `
    <li><a class="list-row" href="?note=${encodeURIComponent(a.note_id)}" data-open-note="${escapeHtml(a.note_id)}">
      <span class="annotation-block" data-tag="${a.tag}"><span class="annot-label">${ANNOT_LABELS[a.tag] || a.tag}</span></span>
      <span class="row-main"><span class="row-title">${escapeHtml(a.text)}</span><span class="row-sub">${escapeHtml(a.note_title)}</span></span>
      ${icon('chevron-right', 'icon-sm subtle')}</a></li>`).join('')}</ul>`;
}

/* ---------- Render Markdown: wikilinks + fórmulas + simulaciones + anotaciones ---------- */
function renderMarkdownWithWikiLinks(raw) {
  const mathStore = [], simStore = [], annotStore = [];
  let processed = raw.replace(/```sim[ \t]*\r?\n([\s\S]*?)```/g, (_, code) => { simStore.push(code); return `@@SIM${simStore.length - 1}@@`; });
  processed = processed.replace(/\$\$([\s\S]+?)\$\$/g, (_, expr) => { mathStore.push({ expr, display: true }); return `@@MATH${mathStore.length - 1}@@`; });
  processed = processed.replace(/\$([^\$\n]+?)\$/g, (_, expr) => { mathStore.push({ expr, display: false }); return `@@MATH${mathStore.length - 1}@@`; });
  processed = processed.replace(/\{\{(resumir|entender|mal):([\s\S]+?)\}\}/g, (_, tag, text) => { annotStore.push({ tag, text: text.trim() }); return `@@ANNOT${annotStore.length - 1}@@`; });
  processed = processed.replace(/\[\[(?:tarea|idea|rutina|item):(\d+)\]\]/g, (_, id) => `@@ITEMLINK@@${id}@@`);
  const placeholder = processed.replace(/\[\[(.+?)\]\]/g, (_, name) => `@@WIKILINK@@${name}@@`);

  // El HTML de marked se sanea ANTES de reinsertar nuestros marcadores (todo escapado).
  let html = sanitizeHtml(marked.parse(placeholder));
  html = html.replace(/@@WIKILINK@@(.+?)@@/g, (_, name) => {
    const id = slugify(name);
    return `<a href="?note=${encodeURIComponent(id)}" class="wiki-link" data-note-id="${escapeHtml(id)}">${escapeHtml(name)}</a>`;
  });
  // Enlace a una tarea, idea o rutina ([[tarea:N]], app/links.py): ficha con su texto actual
  html = html.replace(/@@ITEMLINK@@(\d+)@@/g, (_, id) =>
    `<a href="/tareas?item=${id}" class="item-link" data-item-id="${id}">${icon('square-check', 'icon-sm')}<span>Elemento ${id}</span></a>`);
  html = html.replace(/@@MATH(\d+)@@/g, (_, idx) => {
    const m = mathStore[parseInt(idx, 10)];
    const delim = m.display ? '$$' : '$';
    return `<span class="katex-source">${delim}${escapeHtml(m.expr)}${delim}</span>`;
  });
  html = html.replace(/<p>@@SIM(\d+)@@<\/p>|@@SIM(\d+)@@/g, (_, i1, i2) => {
    const code = simStore[parseInt(i1 !== undefined ? i1 : i2, 10)];
    const widgetId = 'sim-' + Math.random().toString(36).slice(2, 9);
    window.__simCodes[widgetId] = code;
    return `<div class="sim-widget" id="${widgetId}">
      <div class="sim-header">${icon('circle-play', 'icon-sm')}<span class="grow">Simulación interactiva</span>
        <button type="button" class="btn btn-tinted btn-sm" data-sim-run="${widgetId}">${icon('play', 'icon-sm')}Ejecutar</button></div>
      <div class="sim-frame-wrap"></div></div>`;
  });
  html = html.replace(/@@ANNOT(\d+)@@/g, (_, idx) => {
    const a = annotStore[parseInt(idx, 10)];
    const inner = sanitizeHtml(marked.parseInline(a.text));
    return `<mark class="annotation-block" data-tag="${a.tag}"><span class="annot-label">${ANNOT_LABELS[a.tag]}</span>${inner}</mark>`;
  });
  return html;
}

function sanitizeHtml(html) {
  return window.DOMPurify ? DOMPurify.sanitize(html, { USE_PROFILES: { html: true }, FORBID_ATTR: ['style'] }) : escapeHtml(html);
}

// Delegación: wikilinks, notas en listas y simulaciones sin onclick inline.
document.addEventListener('click', (e) => {
  const link = e.target.closest('.wiki-link[data-note-id], [data-open-note]');
  if (link) {
    e.preventDefault();
    const id = link.dataset.noteId || link.dataset.openNote;
    if (link.closest('dialog')) closeModal(link.closest('dialog'));
    openNote(id);
    return;
  }
  const simBtn = e.target.closest('[data-sim-run]');
  if (simBtn) runSimulation(simBtn.dataset.simRun);
});

function markBlock(tag) {
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const sel = ta.value.substring(s, e);
  if (!sel.trim()) { toast('Selecciona primero el bloque que quieres marcar', { type: 'info' }); return; }
  ta.setRangeText(`{{${tag}:${sel}}}`, s, e, 'end');
  ta.focus();
  scheduleAutoSave();
  updatePreview();
}

function runSimulation(widgetId) {
  const wrapper = $(widgetId);
  if (!wrapper) return;
  const frameWrap = wrapper.querySelector('.sim-frame-wrap');
  const code = window.__simCodes[widgetId];
  const btn = wrapper.querySelector('[data-sim-run]');
  let iframe = frameWrap.querySelector('iframe');
  if (!iframe) {
    iframe = document.createElement('iframe');
    iframe.setAttribute('sandbox', 'allow-scripts');
    iframe.title = 'Simulación';
    frameWrap.appendChild(iframe);
    btn.innerHTML = icon('rotate-ccw', 'icon-sm') + 'Reiniciar';
  }
  iframe.srcdoc = '';
  requestAnimationFrame(() => { iframe.srcdoc = code; });
}
window.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'sim-resize') {
    document.querySelectorAll('.sim-frame-wrap iframe').forEach(f => {
      if (f.contentWindow === e.source) f.style.height = Math.min(Math.max(e.data.height, 120), 900) + 'px';
    });
  }
});

/* ---------- Atajos ---------- */
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = tag === 'input' || tag === 'textarea';
  if (document.querySelector('dialog[open]')) return;
  if (e.key.toLowerCase() === 'e' && !typing && !e.ctrlKey && !e.metaKey && activeNoteId && currentMode === 'read') { e.preventDefault(); setMode('edit'); }
  if (e.key === 'Escape' && currentMode === 'edit' && activeNoteId && !$('previewPane').classList.contains('mobile-open')) setMode('read');
  if (e.key === 'Escape' && $('previewPane').classList.contains('mobile-open')) closeMobilePreview();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && activeNoteId) { e.preventDefault(); saveNote(false); }
  if (e.key === '/' && !typing) { e.preventDefault(); $('searchInput').focus(); }
});

/* ---------- Barra de formato ---------- */
function afterEdit() { $('noteContent').focus(); updateCharCount(); scheduleAutoSave(); updatePreview(); }
function wrapSelection(before, after) {
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const sel = ta.value.substring(s, e);
  ta.setRangeText(sel ? before + sel + after : before + 'texto' + after, s, e, 'end');
  if (!sel) { ta.selectionStart = s + before.length; ta.selectionEnd = s + before.length + 5; }
  afterEdit();
}
function insertHeading(level) {
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const lineStart = ta.value.lastIndexOf('\n', s - 1) + 1;
  const sel = ta.value.substring(s, e).trim();
  if (!sel) {
    const lineEnd = ta.value.indexOf('\n', s) === -1 ? ta.value.length : ta.value.indexOf('\n', s);
    const line = ta.value.slice(lineStart, lineEnd).replace(/^#{1,6}\s+/, '');
    ta.setRangeText('#'.repeat(level) + ' ' + (line || 'Título'), lineStart, lineEnd, 'end');
  } else ta.setRangeText('#'.repeat(level) + ' ' + sel, s, e, 'end');
  afterEdit();
}
function insertWikiLink() {
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const sel = ta.value.substring(s, e).trim();
  ta.setRangeText('[[' + (sel || 'Concepto') + ']]', s, e, 'end');
  if (!sel) { ta.selectionStart = s + 2; ta.selectionEnd = s + 10; }
  afterEdit();
}
function insertLine(prefix) {
  const ta = $('noteContent');
  const pos = ta.value.lastIndexOf('\n', ta.selectionStart - 1) + 1;
  ta.setRangeText(prefix, pos, pos, 'end');
  afterEdit();
}
function insertTask() { insertLine('- [ ] '); }
function insertList(ordered) {
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const blockStart = ta.value.lastIndexOf('\n', s - 1) + 1;
  let blockEnd = ta.value.indexOf('\n', e);
  if (blockEnd === -1) blockEnd = ta.value.length;
  const lines = ta.value.slice(blockStart, blockEnd).split('\n');
  const already = lines.every(l => l.trim() === '' || (ordered ? /^\s*\d+\.\s/.test(l) : /^\s*[-*]\s/.test(l)));
  let counter = 1;
  const newLines = lines.map(line => {
    if (line.trim() === '') return line;
    const indent = (line.match(/^(\s*)/) || ['', ''])[1];
    const content = line.replace(/^(\s*)([-*]|\d+\.)\s+/, '').trimStart();
    if (already) return indent + content;
    return ordered ? `${indent}${counter++}. ${content}` : `${indent}- ${content}`;
  });
  ta.setRangeText(newLines.join('\n'), blockStart, blockEnd, 'end');
  afterEdit();
}
function handleListEnter(e) {
  const ta = e.target;
  const pos = ta.selectionStart;
  const lineStart = ta.value.lastIndexOf('\n', pos - 1) + 1;
  const currentLine = ta.value.slice(lineStart, pos);
  const taskM = currentLine.match(/^(\s*)([-*]) \[[ xX]\]\s(.*)$/);
  const bulletM = currentLine.match(/^(\s*)([-*])\s(.*)$/);
  const numberM = currentLine.match(/^(\s*)(\d+)\.\s(.*)$/);
  const match = taskM || bulletM || numberM;
  if (!match) return;
  const [, indent, marker, content] = match;
  e.preventDefault();
  if (content.trim() === '') { ta.setRangeText('', lineStart, pos, 'end'); afterEdit(); return; }
  const next = taskM ? `${indent}${marker} [ ] ` : bulletM ? `${indent}${marker} ` : `${indent}${parseInt(marker, 10) + 1}. `;
  ta.setRangeText(`\n${next}`, pos, pos, 'end');
  afterEdit();
}
function insertBlock(text) {
  const ta = $('noteContent');
  const s = ta.selectionStart;
  const before = ta.value.slice(0, s);
  const prefix = before.length && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : '';
  ta.setRangeText(prefix + text, s, s, 'end');
  afterEdit();
}
function insertTableTemplate() {
  insertBlock('| Columna 1 | Columna 2 | Columna 3 |\n| --- | --- | --- |\n| dato | dato | dato |\n| dato | dato | dato |\n\n');
}
function insertFormula() {
  const ta = $('noteContent');
  const s = ta.selectionStart, e = ta.selectionEnd;
  const sel = ta.value.substring(s, e);
  const text = sel ? `$${sel}$` : '$f = m \\cdot a$';
  ta.setRangeText(text, s, e, 'end');
  if (!sel) { ta.selectionStart = s + 1; ta.selectionEnd = s + text.length - 1; }
  afterEdit();
}
function insertSimulationTemplate() {
  insertBlock('```sim\n<!DOCTYPE html>\n<html>\n<head><style>\n' +
    '  body { margin:0; background:#0a0a0b; color:#ededee; font-family:sans-serif; display:flex; justify-content:center; }\n' +
    '  canvas { background:#131316; border-radius:8px; margin-top:10px; }\n' +
    '</style></head>\n<body>\n  <canvas id="c" width="400" height="300"></canvas>\n  <script>\n' +
    '    const ctx = document.getElementById("c").getContext("2d");\n    let x = 50, y = 50, vx = 2, vy = 1.5;\n' +
    '    function loop() {\n      ctx.clearRect(0,0,400,300);\n      x += vx; y += vy;\n' +
    '      if (x < 10 || x > 390) vx *= -1;\n      if (y < 10 || y > 290) vy *= -1;\n' +
    '      ctx.beginPath(); ctx.arc(x, y, 10, 0, Math.PI*2);\n      ctx.fillStyle = "#5e9dff"; ctx.fill();\n' +
    '      requestAnimationFrame(loop);\n    }\n    loop();\n  <\/script>\n</body>\n</html>\n```\n');
}
function insertFlashcardTemplate() { insertBlock('¿Pregunta de repaso? >> Respuesta breve\n'); }

$('noteContent').addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.metaKey) {
    const k = e.key.toLowerCase();
    if (k === 'b') { e.preventDefault(); wrapSelection('**', '**'); }
    if (k === 'i') { e.preventDefault(); wrapSelection('*', '*'); }
    if (k === 'k') { e.preventDefault(); insertWikiLink(); }
  } else if (e.key === 'Enter' && !e.shiftKey) handleListEnter(e);
});

/* Pegar imágenes directamente en el editor */
$('noteContent').addEventListener('paste', async (e) => {
  const items = Array.from(e.clipboardData?.items || []).filter(i => i.type.startsWith('image/'));
  if (!items.length) return;
  e.preventDefault();
  const formData = new FormData();
  formData.append('image', items[0].getAsFile());
  showSaveIndicator('saving');
  try {
    const data = await api('/api/upload-image', { method: 'POST', body: formData });
    const ta = $('noteContent');
    ta.setRangeText(`![](${data.url})`, ta.selectionStart, ta.selectionStart, 'end');
    afterEdit();
  } catch { showSaveIndicator('error'); }
});

/* ---------- Previsualización ---------- */
function setPreview(pct) {
  currentPreviewPct = pct;
  try { localStorage.setItem('previewPct', String(pct)); } catch {}
  document.querySelectorAll('[data-pv]').forEach(b => b.setAttribute('aria-pressed', String(parseInt(b.dataset.pv, 10) === pct)));
  $('previewPane').classList.toggle('is-hidden', pct === 0);
  updatePreview();
}
function openMobilePreview() {
  updatePreview(true);
  $('previewPane').classList.add('mobile-open');
  $('previewPane').querySelector('button')?.focus();
}
function closeMobilePreview() {
  $('previewPane').classList.remove('mobile-open');
  $('noteContent').focus({ preventScroll: true });
}
let previewTimer;
function updatePreview(force = false) {
  const pane = $('previewPane');
  const visible = force || pane.classList.contains('mobile-open') || (!pane.classList.contains('is-hidden') && pane.offsetParent !== null);
  if (!visible) return;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    const container = $('previewContent');
    container.innerHTML = renderMarkdownWithWikiLinks($('noteContent').value);
    paintItemLinks(container);
    window.Calendar?.mountEmbeds(container);
    enhanceRendered(container);
  }, force ? 0 : 120);
}

function updateCharCount() {
  const content = $('noteContent').value.trim();
  const words = content ? content.split(/\s+/).length : 0;
  $('charCount').textContent = `${words} palabra${words === 1 ? '' : 's'}`;
}
$('noteContent').addEventListener('input', () => { autoStartWriting(); updateCharCount(); updatePreview(); scheduleAutoSave(); });

/* Una nota vacía en «por escribir» pasa sola a «en desarrollo» al empezar a escribir.
   Solo esa transición: si luego se vuelve a poner «por escribir» a mano, se respeta. */
let startedEmpty = false;
function isBodyEmpty(raw) {
  return !String(raw || '').replace(/^\s*#\s+[^\n]*\n?/, '').trim();
}
function armAutoStatus() {
  startedEmpty = activeStatus === 'por-escribir' && !noteIsEncrypted && isBodyEmpty($('noteContent').value);
}
function autoStartWriting() {
  if (!startedEmpty || activeStatus !== 'por-escribir' || isBodyEmpty($('noteContent').value)) return;
  startedEmpty = false;
  activeStatus = 'en-desarrollo';
  updateStatusBadge();
  toast('La nota pasa a «En desarrollo»', { type: 'info', duration: 2200 });
}
function autosizeTitle() {
  const t = $('noteTitle');
  if (CSS.supports('field-sizing', 'content')) return;
  t.style.height = 'auto';
  t.style.height = t.scrollHeight + 'px';
}
$('noteTitle').addEventListener('input', () => { autosizeTitle(); scheduleAutoSave(); });
$('noteTitle').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); setMode('edit'); $('noteContent').focus(); } });
$('noteTags').addEventListener('input', scheduleAutoSave);

/* ---------- Flashcards (SM-2) ---------- */
async function loadFlashcardStats() {
  try {
    const data = await api('/api/flashcards/stats', { quiet: true });
    const badge = $('fcDueBadge');
    badge.textContent = data.due;
    badge.hidden = !data.due;
  } catch {}
}
async function openFlashcardsModal() {
  $('fcCardArea').innerHTML = '<span class="skeleton skeleton-title"></span><span class="skeleton skeleton-line" style="width:60%"></span>';
  $('fcGradeButtons').hidden = true;
  $('fcRevealBtn').hidden = true;
  openModal('flashcardsModal', { onClose: loadFlashcardStats, focus: '#fcRevealBtn' });
  const data = await api('/api/flashcards/due?limit=30');
  fcQueue = data.cards;
  fcIndex = 0;
  showNextFlashcard();
}
function showNextFlashcard() {
  const area = $('fcCardArea');
  $('fcProgress').textContent = fcQueue.length && fcIndex < fcQueue.length ? `${fcIndex + 1} de ${fcQueue.length}` : '';
  if (!fcQueue.length || fcIndex >= fcQueue.length) {
    area.innerHTML = emptyState({ iconName: 'circle-check', title: fcQueue.length ? '¡Repaso terminado!' : 'Nada que repasar', text: 'No quedan tarjetas pendientes por ahora. Crea más con «pregunta >> respuesta».', compact: true });
    $('fcGradeButtons').hidden = true;
    $('fcRevealBtn').hidden = true;
    return;
  }
  fcCurrentCard = fcQueue[fcIndex];
  area.innerHTML = `<div class="fc-question">${escapeHtml(fcCurrentCard.question)}</div>
    <a class="fc-source" href="?note=${encodeURIComponent(fcCurrentCard.note_id)}" data-open-note="${escapeHtml(fcCurrentCard.note_id)}">${escapeHtml(fcCurrentCard.note_title || '')}</a>`;
  $('fcGradeButtons').hidden = true;
  $('fcRevealBtn').hidden = false;
  $('fcRevealBtn').focus();
}
function revealFlashcardAnswer() {
  $('fcCardArea').insertAdjacentHTML('beforeend', `<div class="fc-answer">${escapeHtml(fcCurrentCard.answer)}</div>`);
  $('fcRevealBtn').hidden = true;
  $('fcGradeButtons').hidden = false;
  $('fcGradeButtons').querySelector('[data-q="4"]').focus();
}
async function gradeFlashcard(quality) {
  await api(`/api/flashcards/${fcCurrentCard.id}/review`, { method: 'POST', body: { quality } });
  fcIndex++;
  showNextFlashcard();
}
document.addEventListener('keydown', (e) => {
  if (!$('flashcardsModal').open) return;
  if (e.key === ' ' && !$('fcRevealBtn').hidden) { e.preventDefault(); revealFlashcardAnswer(); }
  const map = { '1': 0, '2': 2, '3': 4, '4': 5 };
  if (map[e.key] !== undefined && !$('fcGradeButtons').hidden) gradeFlashcard(map[e.key]);
});

/* ---------- Racha ---------- */
async function loadStreak() {
  try {
    const data = await api('/api/streak', { quiet: true });
    $('streakBadge').querySelector('span').textContent = data.streak;
    $('streakBadge').title = `${data.streak} día${data.streak === 1 ? '' : 's'} seguidos estudiando`;
  } catch {}
}

/* ---------- Salud del cerebro ---------- */
function noteLinkRow(n, trail = '') {
  return `<li><a class="list-row" href="?note=${encodeURIComponent(n.id)}" data-open-note="${escapeHtml(n.id)}">
    <span class="row-main row-title">${escapeHtml(n.title || n.id)}</span>${trail}${icon('chevron-right', 'icon-sm subtle')}</a></li>`;
}
async function openHealthModal() {
  $('healthModalTitle').textContent = 'Salud del cerebro';
  $('healthContent').innerHTML = skeletonRows(6);
  openModal('healthModal');
  const data = await api('/api/brain-health');
  const section = (title, count, body) => `<section class="health-section"><h3>${title}<span class="badge">${count}</span></h3>${body}</section>`;
  $('healthContent').innerHTML =
    section('Notas sin enlaces', data.orphans.length, data.orphans.length
      ? `<ul class="list">${data.orphans.map(n => noteLinkRow(n)).join('')}</ul>`
      : '<p class="muted small">Todas las notas están conectadas.</p>') +
    section('Sin tocar en más de 2 meses', data.stale.length, data.stale.length
      ? `<ul class="list">${data.stale.map(n => noteLinkRow(n, `<span class="row-trail">${timeAgo(n.last_modified)}</span>`)).join('')}</ul>`
      : '<p class="muted small">Nada desactualizado.</p>') +
    section('Por escribir, por categoría', data.pending_by_category.reduce((a, c) => a + c.n, 0), data.pending_by_category.length
      ? `<ul class="list">${data.pending_by_category.map(c => `<li class="list-row"><span class="row-main row-title">${escapeHtml(c.category)}</span><span class="badge">${c.n}</span></li>`).join('')}</ul>`
      : '<p class="muted small">Sin pendientes.</p>') +
    `<p class="tiny subtle" style="margin-top:var(--sp-4)">${data.total_notes} notas en total</p>`;
}

/* ---------- Gestor rápido de título / categoría ---------- */
function openManagerModal() {
  $('managerSearch').value = '';
  renderManagerTable();
  openModal('managerModal', { focus: '#managerSearch' });
}
$('managerSearch').addEventListener('input', renderManagerTable);
function managerFiltered() {
  const query = ($('managerSearch').value || '').toLowerCase();
  return allNotes.filter(n => (n.title || '').toLowerCase().includes(query) || (n.category || '').toLowerCase().includes(query))
    .sort((a, b) => (a.category || '').localeCompare(b.category || '', 'es') || (a.title || '').localeCompare(b.title || '', 'es'));
}
function renderManagerTable() {
  const sorted = managerFiltered();
  $('managerTableWrap').innerHTML = sorted.length ? `
    <div class="table-wrap" style="max-height:min(60vh,560px)"><table class="table manager-table">
      <thead><tr><th style="width:38%">Título</th><th>Categoría</th><th style="width:140px">Estado</th></tr></thead>
      <tbody>${sorted.map(n => `<tr>
        <td><input type="text" value="${escapeHtml(n.title || '')}" data-note="${escapeHtml(n.id)}" data-field="title" aria-label="Título de ${escapeHtml(n.title || n.id)}"></td>
        <td><input type="text" value="${escapeHtml(n.category || '')}" data-note="${escapeHtml(n.id)}" data-field="category" aria-label="Categoría de ${escapeHtml(n.title || n.id)}"></td>
        <td><span class="status" data-status="${n.status || 'por-escribir'}"><span class="status-dot"></span>${STATUS_LABELS[n.status || 'por-escribir']}</span></td>
      </tr>`).join('')}</tbody></table></div>
    <p class="tiny subtle" style="margin-top:var(--sp-2)">${sorted.length} nota${sorted.length !== 1 ? 's' : ''}. Los cambios se guardan al salir del campo.</p>`
    : emptyState({ iconName: 'search', title: 'Sin resultados', compact: true });
  $('managerTableWrap').querySelectorAll('input[data-note]').forEach(inp => inp.addEventListener('change', () =>
    updateNoteMetaField(inp.dataset.note, inp.dataset.field, inp.value)));
}
async function updateNoteMetaField(noteId, field, value) {
  await api(`/api/notes/${encodeURIComponent(noteId)}/meta`, { method: 'PATCH', body: { [field]: value } });
  toast('Guardado');
  await loadNotes();
  if (noteId === activeNoteId) {
    if (field === 'title') $('noteTitle').value = value;
    if (field === 'category') { $('noteCategory').value = value; updateBreadcrumbs(); }
    lastSavedSnapshot = snapshot();
  }
}
function copyManagerListForAI() {
  const grouped = {};
  managerFiltered().forEach(n => { (grouped[n.category || 'Sin categoría'] ||= []).push(n.title || '(sin título)'); });
  let text = 'Esta es la lista de mis notas por categoría en mi segundo cerebro digital. Ayúdame a evaluar si la organización tiene sentido, si hay categorías redundantes o mal nombradas, notas que deberían fusionarse o categorías que deberían dividirse:\n\n';
  Object.keys(grouped).sort().forEach(cat => { text += `## ${cat}\n${grouped[cat].map(t => `- ${t}`).join('\n')}\n\n`; });
  navigator.clipboard.writeText(text).then(() => toast('Lista copiada al portapapeles'), () => uiAlert('No se pudo copiar', text.slice(0, 400) + '…'));
}


/* ---------- Arranque ---------- */
// /?nueva=1 (paleta de comandos, «G N»): abre el diálogo de nota nueva
if (new URLSearchParams(location.search).get('nueva')) {
  history.replaceState(null, '', location.pathname);
  setTimeout(() => createNewNotePrompt(), 300);
}

(async function boot() {
  try { const pv = parseInt(localStorage.getItem('previewPct') || '50', 10); setPreview(pv === 0 ? 0 : 50); } catch { setPreview(50); }
  loadStreak();
  loadFlashcardStats();
  await loadNotes();
  const urlNote = new URLSearchParams(location.search).get('note');
  let lastNote = null;
  try { lastNote = localStorage.getItem('lastOpenNoteId'); } catch {}
  const noteToOpen = urlNote || (isMobile() ? null : lastNote);
  if (noteToOpen) openNote(noteToOpen);
  else showNotePane(false);
  if (new URLSearchParams(location.search).has('flashcards')) openFlashcardsModal(); // desde /repaso
})();

/* ---------- Resaltado de código claro u oscuro según el tema ---------- */
function syncCodeTheme() {
  const dark = getComputedStyle(document.documentElement).colorScheme.trim() !== 'light';
  $('hljsLight').disabled = dark;
  $('hljsDark').disabled = !dark;
}
document.addEventListener('themechange', syncCodeTheme);
syncCodeTheme();
