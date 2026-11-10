/* ==========================================================================
   popup.js — enviar al Inbox (texto o selección, enlace de la página, tipo,
   categoría y prioridad) o guardar en el Baúl. Si no hay conexión, lo deja
   en la cola (lib/panel.js) y el fondo lo envía en cuanto vuelve.
   ========================================================================== */
'use strict';

const $ = (id) => document.getElementById(id);
const iconSvg = (name) => `<svg class="icon"><use href="icons.svg#i-${name}"/></svg>`;
let page = { url: '', title: '' };
let itemType = 'tarea';
let items = [];          // tareas e ideas del Panel (para elegir el padre de un paso)
const TABS = ['vault', 'inbox', 'cal'];   // la primera es el Baúl
const PREFIX_RE = /^\s*[tireg]\s*:/i;

/* ---------- Mensajes ---------- */
function showResult(type, text, iconName) {
  const el = $('result');
  el.dataset.type = type;
  el.innerHTML = iconSvg(iconName || { ok: 'check', warn: 'cloud-upload', error: 'circle-alert' }[type]) + '<span></span>';
  el.querySelector('span').textContent = text;
  el.hidden = false;
}
function setStatus(state, text) {
  $('status').dataset.state = state;
  $('statusText').textContent = text;
}

/* ---------- Pestañas (patrón ARIA: flechas para cambiar) ---------- */
function selectTab(name, focus = false) {
  for (const t of TABS) {
    const on = t === name;
    const tab = $('tab-' + t);
    tab.setAttribute('aria-selected', String(on));
    tab.tabIndex = on ? 0 : -1;
    $('panel-' + t).hidden = !on;
    if (on && focus) tab.focus();
  }
  $('result').hidden = true;
  browser.storage.local.set({ lastTab: name });
  const first = name === 'inbox' ? $('content') : name === 'cal' ? $('calText') : ($('vaultUrl').value ? $('vaultCategory') : $('vaultUrl'));
  if (!focus) first.focus();
  if (name === 'cal') loadAgenda();
}
document.querySelector('.tabs').addEventListener('click', (e) => {
  const t = e.target.closest('[role=tab]');
  if (t) selectTab(t.id.replace('tab-', ''));
});
document.querySelector('.tabs').addEventListener('keydown', (e) => {
  if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
  e.preventDefault();
  const cur = TABS.findIndex((t) => $('tab-' + t).getAttribute('aria-selected') === 'true');
  selectTab(TABS[(cur + (e.key === 'ArrowRight' ? 1 : -1) + TABS.length) % TABS.length], true);
});

/* ---------- Tipo (tarea / idea) ---------- */
function setType(t) {
  itemType = t;
  document.querySelectorAll('button[data-type]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.type === t)));
  fillParents();
}

/* ---------- Paso de… (elegir el elemento padre: solo de primer nivel y del mismo tipo) ---------- */
function fillParents() {
  const want = itemType === 'nota' ? 'idea' : 'tarea';
  const sel = $('parent'), keep = sel.value;
  const list = items.filter((i) => !i.parent_id && !i.done && i.type === want);
  sel.replaceChildren(Object.assign(document.createElement('option'), { value: '', textContent: 'Ninguno: elemento nuevo' }),
    ...list.map((i) => Object.assign(document.createElement('option'), { value: String(i.id), textContent: (i.text.split('\n')[0] || '').slice(0, 70) + (i.origin === 'nota' && i.note_title ? ` · ${i.note_title}` : '') })));
  sel.value = list.some((i) => String(i.id) === keep) ? keep : '';
  syncParent();
}
function syncParent() {
  const sel = $('parent'), more = $('moreParent');
  const txt = sel.value ? sel.selectedOptions[0].textContent : '';
  $('parentSummary').textContent = txt ? `Paso de: ${txt}` : 'Añadir como paso de otra tarea o idea';
  more.toggleAttribute('data-set', !!sel.value);
}
$('parent').addEventListener('change', syncParent);
document.querySelectorAll('button[data-type]').forEach((b) => b.addEventListener('click', () => {
  setType(b.dataset.type);
  browser.storage.local.set({ lastType: b.dataset.type });
}));

/* ---------- Baúl: clasificación AUTOMÁTICA (lib/classify.js); el selector queda plegado y se cambia con un clic ---------- */
let vaultState = '';
let stateTouched = false;       // si la has cambiado tú, la detección no la pisa
let detectToken = 0;
function setVaultState(v) {
  vaultState = v;
  document.querySelectorAll('#vaultState button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.state === v)));
}
$('vaultState').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  stateTouched = true;
  setVaultState(b.dataset.state);
  $('detectedBadge').textContent = { '': 'Normal', later: 'Ver más tarde', seen: 'Visto' }[b.dataset.state];
  $('detectedReason').textContent = 'Elegido por ti';
  $('detected').dataset.kind = b.dataset.state === 'later' ? 'later' : b.dataset.state === 'seen' ? 'seen' : 'normal';
});
$('detectedChange').addEventListener('click', () => {
  const open = $('vaultState').hidden;
  $('vaultState').hidden = !open;
  $('detectedChange').setAttribute('aria-expanded', String(open));
  $('detectedChange').textContent = open ? 'Ocultar' : 'Cambiar';
});

// Progreso del vídeo que se está viendo en la pestaña (mismo criterio que youtube.js: tiempo reproducido frente al umbral)
async function videoProgress() {
  try {
    const [r] = await browser.tabs.executeScript({ code: `/*panel-progress*/(() => { const v = document.querySelector('video.html5-main-video, video'); return v && isFinite(v.duration) ? { played: v.currentTime, duration: v.duration } : null; })()` });
    return r && typeof r.played === 'number' ? r : null;
  } catch { return null; }
}
async function detectVault() {
  const token = ++detectToken;
  const url = $('vaultUrl').value.trim();
  let exists = null, prog = null;
  const id = Classify.youtubeId(url);
  if (id) {
    try { exists = (await Panel.request('/api/ext/youtube/video?id=' + id)).exists; } catch { exists = null; }
    if (url === page.url) prog = await videoProgress();
  }
  if (token !== detectToken || stateTouched) return;
  const { ytPct = 50 } = await browser.storage.local.get('ytPct');
  const d = Classify.detect({ url, exists, played: prog?.played ?? null, duration: prog?.duration ?? null, threshold: Math.min(100, Math.max(10, Number(ytPct) || 50)) });
  setVaultState(d.save);
  $('detected').dataset.kind = d.state;
  $('detected').dataset.certain = String(d.certain);
  $('detectedBadge').textContent = d.label;
  $('detectedReason').textContent = d.certain ? d.reason : `${d.reason}. Puedes cambiarlo.`;
}

/* ---------- YouTube: ¿el canal de este vídeo está en el Baúl? ---------- */
let ytChannel = '';
async function checkYoutube() {
  if (!/^https?:\/\/(www\.)?youtube\.com\/watch\?/i.test(page.url)) return;
  let handle = '';
  try {
    [handle] = await browser.tabs.executeScript({ code: `(() => { const a = document.querySelector('ytd-watch-metadata ytd-video-owner-renderer a[href*="/@"], ytd-watch-metadata ytd-video-owner-renderer a[href*="/channel/"], #owner a[href*="/@"], #owner a[href*="/channel/"]'); return a ? decodeURIComponent(a.getAttribute('href')).split('?')[0] : ''; })()` });
  } catch { return; }
  if (!handle) return;
  ytChannel = handle;
  try {
    const r = await Panel.request('/api/ext/youtube/canal?channel=' + encodeURIComponent(handle));
    $('ytCard').hidden = false;
    $('ytCard').dataset.state = r.tracked ? 'on' : 'off';
    $('ytText').textContent = r.tracked ? 'Canal en el Baúl: sus vídeos se marcan solos como vistos.' : `El canal ${handle.replace(/^\//, '')} no está en el Baúl.`;
    $('ytAdd').hidden = r.tracked;
  } catch { /* sin conexión: sin aviso */ }
}
$('ytAdd').addEventListener('click', async () => {
  $('ytAdd').disabled = true;
  try {
    await Panel.send('vault', { url: 'https://www.youtube.com' + ytChannel, category: $('vaultCategory').value.trim() || 'General', watch_later: false });
    $('ytCard').dataset.state = 'on';
    $('ytText').textContent = 'Canal añadido al Baúl: sus vídeos se marcarán solos como vistos.';
    $('ytAdd').hidden = true;
  } catch (err) {
    if (err.kind === 'duplicate') { $('ytAdd').hidden = true; $('ytText').textContent = 'Ese canal ya estaba en el Baúl.'; }
    else showResult('error', err.message);
  }
  $('ytAdd').disabled = false;
});

/* ---------- Prioridad (radio en un clic; flechas para moverse) ---------- */
const prioButtons = () => [...document.querySelectorAll('#priority [role=radio]')];
const getPriority = () => document.querySelector('#priority [aria-checked="true"]')?.dataset.prio || '';
function setPriority(p, focus = false) {
  for (const b of prioButtons()) {
    const on = b.dataset.prio === p;
    b.setAttribute('aria-checked', String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
  }
}
$('priority').addEventListener('click', (e) => { const b = e.target.closest('[role=radio]'); if (b) setPriority(b.dataset.prio); });
$('priority').addEventListener('keydown', (e) => {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  const keys = prioButtons().map((b) => b.dataset.prio);
  setPriority(keys[(keys.indexOf(getPriority()) + step + keys.length) % keys.length], true);
});

/* ---------- Categorías en un clic: las últimas usadas y luego las del Panel ---------- */
const CHIPS_MAX = 6;
const chipSets = { inbox: { input: 'inboxCategory', box: 'inboxChips', key: 'recentInboxCats', extra: [] },
                   vault: { input: 'vaultCategory', box: 'vaultChips', key: 'recentVaultCats', extra: [] } };
async function renderChips(kind) {
  const set = chipSets[kind];
  const recent = (await browser.storage.local.get(set.key))[set.key] || [];
  const seen = new Set();
  const values = [...recent, ...set.extra].filter((v) => v && !seen.has(v.toLowerCase()) && seen.add(v.toLowerCase())).slice(0, CHIPS_MAX);
  const box = $(set.box);
  box.replaceChildren(...values.map((v) => Object.assign(document.createElement('button'), { type: 'button', className: 'chip', textContent: v, title: v })));
  box.hidden = !values.length;
  syncChips(kind);
}
function syncChips(kind) {
  const v = $(chipSets[kind].input).value.trim().toLowerCase();
  $(chipSets[kind].box).querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(c.textContent.toLowerCase() === v)));
}
async function rememberCategory(kind, value) {
  if (!value) return;
  const key = chipSets[kind].key;
  const recent = (await browser.storage.local.get(key))[key] || [];
  await browser.storage.local.set({ [key]: [value, ...recent.filter((v) => v.toLowerCase() !== value.toLowerCase())].slice(0, CHIPS_MAX) });
}
for (const kind of Object.keys(chipSets)) {
  const { input, box } = chipSets[kind];
  $(input).addEventListener('input', () => syncChips(kind));
  $(box).addEventListener('click', (e) => {
    const c = e.target.closest('.chip');
    if (!c) return;
    $(input).value = c.getAttribute('aria-pressed') === 'true' ? '' : c.textContent;
    syncChips(kind);
  });
}

/* ---------- Datos iniciales ---------- */
async function currentPage() {
  try {
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    return { url: tab?.url || '', title: tab?.title || '', favIconUrl: tab?.favIconUrl || '' };
  } catch { return { url: '', title: '' }; }
}
function showPage() {
  let host = '';
  try { host = new URL(page.url).hostname.replace(/^www\./, ''); } catch {}
  $('pageTitle').textContent = page.title || page.url;
  $('pageTitle').title = page.url;
  $('pageHost').textContent = host;
  if (/^(https?:|data:image\/)/i.test(page.favIconUrl || '')) {
    const img = Object.assign(document.createElement('img'), { className: 'favicon', alt: '', width: 16, height: 16, src: page.favIconUrl });
    img.addEventListener('error', () => { img.remove(); $('pageIconFallback').hidden = false; });
    $('pageIconFallback').hidden = true;
    $('pageIconFallback').before(img);
  }
}
async function pageSelection() {
  try {
    const [sel] = await browser.tabs.executeScript({ code: 'window.getSelection ? String(window.getSelection()) : ""' });
    return (sel || '').trim();
  } catch { return ''; } // páginas internas del navegador
}
function fillDatalist(id, values) {
  const dl = $(id);
  dl.replaceChildren(...values.map((v) => Object.assign(document.createElement('option'), { value: v })));
}

async function loadStatus() {
  const queue = (await Panel.getQueue()).length;
  try {
    const st = await Panel.status();
    fillDatalist('inboxCats', st.inbox_categories || []);
    chipSets.inbox.extra = st.inbox_categories || [];
    renderChips('inbox');
    const pend = st.pending === 1 ? '1 pendiente' : `${st.pending} pendientes`;
    setStatus(queue ? 'queue' : 'ok', `Conectado · ${pend} en el Inbox` + (queue ? ` · ${queue} en cola` : ''));
    Panel.request('/api/resources/categories').then((d) => {
      fillDatalist('vaultCats', d.categories || []);
      chipSets.vault.extra = d.categories || [];
      renderChips('vault');
    }).catch(() => {});
    if (queue) browser.runtime.sendMessage({ type: 'refresh' }).catch(() => {}); // que el fondo vacíe la cola
    Panel.request('/api/items').then((d) => { items = d.items || []; fillParents(); }).catch(() => {});
  } catch (err) {
    if (err.kind === 'config') { setStatus('idle', 'Sin configurar'); $('setup').hidden = false; return; }
    if (err.kind === 'auth') { setStatus('error', 'Token no válido'); $('setup').hidden = false; return; }
    setStatus(queue ? 'queue' : 'error', 'Sin conexión' + (queue ? ` · ${queue} en cola` : ': se guardará en la cola'));
  }
}

async function init() {
  const store = await browser.storage.local.get(['pending', 'lastTab', 'lastType', 'includeLink', 'lastVaultCat']);
  let pending = store.pending && Date.now() - store.pending.at < 60_000 ? store.pending : null;
  if (store.pending) await browser.storage.local.remove('pending');
  page = pending?.page?.url ? pending.page : await currentPage();
  if (pending?.tab === 'cal') pending.page = page;
  const selection = pending ? '' : await pageSelection();

  // Inbox
  $('content').value = pending?.text ?? selection;
  const web = Panel.isWebUrl(page.url);
  $('includeLink').closest('label').hidden = !web;
  $('includeLink').checked = store.includeLink !== false;
  showPage();
  setType(store.lastType === 'nota' ? 'nota' : 'tarea');

  // Baúl
  const url = pending?.url || (web ? page.url : '');
  $('vaultUrl').value = url;
  updateKind();
  $('vaultCategory').value = store.lastVaultCat || '';
  renderChips('inbox');
  renderChips('vault');

  // Se abre siempre en el Baúl (salvo que lo pida el menú contextual o haya texto seleccionado: eso es del Inbox)
  selectTab(pending?.tab || (selection ? 'inbox' : 'vault'));
  detectVault();
  loadStatus();
  checkYoutube();
}

function updateKind() {
  const u = $('vaultUrl').value.trim();
  $('kind').textContent = Panel.isWebUrl(u) ? Panel.detectType(u).label : '';
  $('kind').hidden = !Panel.isWebUrl(u);
}
$('vaultUrl').addEventListener('input', () => { updateKind(); clearTimeout(detectTimer); detectTimer = setTimeout(detectVault, 400); });
let detectTimer = null;
$('includeLink').addEventListener('change', (e) => browser.storage.local.set({ includeLink: e.target.checked }));

/* ---------- Enviar ---------- */
async function submit(kind) {
  const tab = kind;
  const btn = kind === 'inbox' ? $('saveInbox') : $('saveVault');
  let body;
  if (kind === 'inbox') {
    const content = Panel.composeInbox($('content').value, page, $('includeLink').checked && !$('includeLink').closest('label').hidden);
    if (!content) { showResult('error', 'Escribe algo o selecciona texto en la página'); $('content').focus(); return; }
    const parent = Number($('parent').value) || null;
    if (!parent && PREFIX_RE.test(content)) { kind = 'capture'; body = { text: content }; }   // t: i: r: e: como en el Panel
    else body = { text: content, type: itemType === 'nota' ? 'idea' : 'tarea', priority: getPriority() || null, category: $('inboxCategory').value.trim() || null, parent_id: parent };
  } else {
    const url = $('vaultUrl').value.trim();
    if (!Panel.isWebUrl(url)) { showResult('error', 'El enlace debe empezar por http:// o https://'); $('vaultUrl').focus(); return; }
    const category = $('vaultCategory').value.trim() || 'General';
    body = { url, category, watch_later: vaultState === 'later', watched: vaultState === 'seen' };
    browser.storage.local.set({ lastVaultCat: $('vaultCategory').value.trim() });
  }
  btn.disabled = true;
  try {
    const r = await Panel.send(kind, body);
    if (kind !== 'capture') rememberCategory(kind, kind === 'inbox' ? body.category : $('vaultCategory').value.trim());
    if (r.sent) {
      showResult('ok', kind === 'capture' ? (r.data?.message || 'Guardado') : tab === 'inbox' ? (body.parent_id ? 'Añadido como paso' : `Enviado al Inbox como ${itemType === 'tarea' ? 'tarea' : 'idea'}`) : `Guardado en el Baúl${vaultState === 'seen' ? ' como visto' : vaultState === 'later' ? ' para más tarde' : Classify.isChannel(body.url) ? ' como canal de YouTube' : ''}`);
      setTimeout(() => window.close(), 900);
    } else {
      showResult('warn', `Sin conexión: guardado en la cola (${r.queued}). Se enviará solo cuando vuelva la conexión.`);
      setTimeout(() => window.close(), 2200);
    }
    browser.runtime.sendMessage({ type: 'refresh' }).catch(() => {});
  } catch (err) {
    if (err.kind === 'duplicate') showResult('warn', 'Ya estaba en el Baúl', 'check');
    else showResult('error', err.message);
    if (err.kind === 'auth' || err.kind === 'config') $('setup').hidden = false;
    btn.disabled = false;
  }
}
$('panel-inbox').addEventListener('submit', (e) => { e.preventDefault(); submit('inbox'); });
$('panel-vault').addEventListener('submit', (e) => { e.preventDefault(); submit('vault'); });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    if ($('tab-cal').getAttribute('aria-selected') === 'true') return $('calForm').requestSubmit();
    submit($('tab-inbox').getAttribute('aria-selected') === 'true' ? 'inbox' : 'vault');
  }
});

/* ---------- Atajos de la cabecera ---------- */
const openOptions = () => { browser.runtime.openOptionsPage(); window.close(); };
$('openOptions').addEventListener('click', openOptions);
$('setupBtn').addEventListener('click', openOptions);
$('openPanel').addEventListener('click', async () => {
  const { baseUrl } = await Panel.getConfig();
  if (!baseUrl) return openOptions();
  browser.tabs.create({ url: baseUrl + '/inbox' });
  window.close();
});

/* ---------- Agenda: ver, crear, pasar a mañana y completar (app/calendar.py) ---------- */
const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];
let agenda = [];
const dayLabel = (iso) => {
  const d = new Date(iso + 'T00:00'), today = new Date(); today.setHours(0, 0, 0, 0);
  const diff = Math.round((d - today) / 86400000);
  return diff === 0 ? 'Hoy' : diff === 1 ? 'Mañana' : `${DIAS[d.getDay()]} ${d.getDate()}`;
};
async function loadAgenda() {
  const box = $('agenda');
  let data, offline = false;
  try {
    data = await Panel.request('/api/calendar/agenda?days=7');
    browser.storage.local.set({ agendaCache: data });
  } catch (err) {
    offline = true;
    data = (await browser.storage.local.get('agendaCache')).agendaCache;
    if (!data) { box.innerHTML = `<p class="hint">${err.kind === 'config' ? 'Configura la extensión para ver la agenda.' : 'Sin conexión y sin agenda guardada.'}</p>`; return; }
  }
  agenda = data.entries;
  const by = {};
  agenda.forEach((e) => (by[e.start.slice(0, 10)] ||= []).push(e));
  box.replaceChildren();
  if (offline) box.insertAdjacentHTML('beforeend', '<p class="hint">Sin conexión: la última agenda guardada (solo lectura).</p>');
  if (!agenda.length) { box.insertAdjacentHTML('beforeend', '<p class="hint">Nada en los próximos 7 días.</p>'); return; }
  for (const day of Object.keys(by).sort()) {
    const h = Object.assign(document.createElement('h3'), { className: 'agenda-day', textContent: dayLabel(day) });
    const ul = document.createElement('ul');
    ul.className = 'agenda-list';
    for (const e of by[day].sort((a, b) => (b.all_day - a.all_day) || a.start.localeCompare(b.start))) {
      const li = document.createElement('li');
      li.className = 'agenda-row' + (e.done ? ' is-done' : '');
      li.dataset.kind = e.kind;
      li.dataset.type = e.type;
      const check = e.kind !== 'event' && !offline
        ? `<button type="button" class="check" data-act="done" aria-pressed="${e.done}" aria-label="${e.done ? 'Desmarcar' : 'Completar'}">${iconSvg(e.done ? 'circle-check' : 'circle')}</button>`
        : `<span class="dot" aria-hidden="true"></span>`;
      const move = (e.kind === 'event' || e.kind === 'task') && !offline
        ? `<button type="button" class="btn btn-ghost btn-icon" data-act="later" aria-label="Pasar a mañana" title="Pasar a mañana">${iconSvg('arrow-right')}</button>` : '';
      li.innerHTML = `${check}<span class="agenda-time"></span><span class="agenda-title"></span>${move}`;
      li.querySelector('.agenda-time').textContent = e.all_day ? 'Todo el día' : e.start.slice(11, 16);
      li.querySelector('.agenda-title').textContent = e.title;
      li.dataset.key = e.key;
      ul.append(li);
    }
    box.append(h, ul);
  }
}
$('agenda').addEventListener('click', async (ev) => {
  const b = ev.target.closest('[data-act]');
  if (!b) return;
  const e = agenda.find((x) => x.key === b.closest('[data-key]').dataset.key);
  if (!e) return;
  b.disabled = true;
  try {
    if (b.dataset.act === 'done') {
      if (e.kind === 'routine') await Panel.request(`/api/routines/${e.item_id}/check`, { method: 'POST', body: { day: e.day, done: !e.done } });
      else await Panel.request(`/api/items/${e.item_id}`, { method: 'PATCH', body: { done: !e.done } });
    } else {
      const next = (iso) => { const d = new Date(iso.slice(0, 10) + 'T00:00'); d.setDate(d.getDate() + 1);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
      if (e.kind === 'event') await Panel.request(`/api/calendar/events/${e.id}`, { method: 'PATCH', body: { start: next(e.start) + e.start.slice(10) } });
      else await Panel.request(`/api/items/${e.item_id}`, { method: 'PATCH', body: { due_date: next(e.start) } });
      showResult('ok', `«${e.title}» pasa a mañana`);
    }
  } catch (err) { showResult('error', err.message); }
  loadAgenda();
});

let previewTimer = null;
$('calText').addEventListener('input', () => {
  clearTimeout(previewTimer);
  const v = $('calText').value.trim();
  if (!v) { $('calPreview').textContent = ''; return; }
  previewTimer = setTimeout(async () => {
    try {
      const p = await Panel.request('/api/capture', { method: 'POST', body: { text: 'e: ' + v, dry_run: true } });
      $('calPreview').dataset.state = p.kind === 'evento' ? 'ok' : 'warn';
      $('calPreview').textContent = p.kind === 'evento' ? `${p.preview.title} · ${p.preview.when}` : `No entiendo la fecha (${p.reason}): irá al Inbox para revisarla`;
    } catch { $('calPreview').textContent = 'Sin conexión: se guardará en la cola sin vista previa'; $('calPreview').dataset.state = 'warn'; }
  }, 350);
});
$('calForm').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const v = $('calText').value.trim();
  if (!v) { $('calText').focus(); return; }
  $('calSave').disabled = true;
  try {
    const r = await Panel.send('capture', { text: 'e: ' + v });
    showResult(r.sent ? 'ok' : 'warn', r.sent ? (r.data?.message || 'Evento creado') : `Sin conexión: en la cola (${r.queued})`);
    $('calText').value = '';
    $('calPreview').textContent = '';
    loadAgenda();
  } catch (err) { showResult('error', err.message); }
  $('calSave').disabled = false;
});

document.addEventListener('DOMContentLoaded', init);
