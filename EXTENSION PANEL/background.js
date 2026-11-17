/* ==========================================================================
   background.js — menús contextuales, atajos, insignia del icono y cola.
   Insignia: número de pendientes del Inbox (azul), «↑N» envíos en cola
   (naranja), «!» sin configurar o token no válido, «×» sin conexión.
   ========================================================================== */
'use strict';

const COLORS = { ok: '#89b4fa', queue: '#fab387', error: '#f38ba8', idle: '#6c7086' };

/* ---------- Insignia ---------- */
async function refreshBadge() {
  const queue = await Panel.getQueue();
  let text = '', color = COLORS.ok, title = 'Panel: enviar al Inbox o al Baúl';
  try {
    if (queue.length) await Panel.flush();
    const left = (await Panel.getQueue()).length;
    const st = await Panel.status();
    if (left) { text = `↑${left}`; color = COLORS.queue; title = `${left} envío(s) en cola`; }
    else { text = st.pending ? String(st.pending > 99 ? '99+' : st.pending) : ''; title = `Panel conectado · ${st.pending} pendiente(s) en el Inbox`; }
  } catch (err) {
    const left = (await Panel.getQueue()).length;
    if (err.kind === 'config' || err.kind === 'auth') { text = '!'; color = COLORS.idle; title = err.message; }
    else { text = left ? `↑${left}` : '×'; color = left ? COLORS.queue : COLORS.error; title = 'Sin conexión con el Panel' + (left ? ` · ${left} envío(s) en cola` : ''); }
  }
  await browser.browserAction.setBadgeText({ text });
  await browser.browserAction.setBadgeBackgroundColor({ color });
  await browser.browserAction.setTitle({ title });
}

/* ---------- Abrir el popup en una pestaña concreta y con datos ---------- */
async function openWith(pending) {
  await browser.storage.local.set({ pending: { ...pending, at: Date.now() } });
  try { await browser.browserAction.openPopup(); } catch { /* sin gesto del usuario: se verá al abrirlo */ }
}

/* ---------- Menús contextuales ---------- */
function createMenus() {
  browser.contextMenus.removeAll().then(() => {
    browser.contextMenus.create({ id: 'quick-selection', title: 'Enviar «%s» al Inbox ya', contexts: ['selection'] });
    browser.contextMenus.create({ id: 'quick-link', title: 'Enviar el enlace al Inbox ya', contexts: ['link'] });
    browser.contextMenus.create({ id: 'sep', type: 'separator', contexts: ['selection', 'link'] });
    browser.contextMenus.create({ id: 'inbox-selection', title: 'Enviar «%s» al Inbox…', contexts: ['selection'] });
    browser.contextMenus.create({ id: 'inbox-page', title: 'Enviar esta página al Inbox', contexts: ['page'] });
    browser.contextMenus.create({ id: 'vault-link', title: 'Guardar el enlace en el Baúl', contexts: ['link'] });
    browser.contextMenus.create({ id: 'vault-page', title: 'Guardar esta página en el Baúl', contexts: ['page'] });
  });
}

/* ---------- Envío rápido: sin popup, como tarea, con aviso del sistema ---------- */
function notify(title, message) {
  browser.notifications.create({ type: 'basic', iconUrl: browser.runtime.getURL('icons/icon.svg'), title, message }).catch(() => {});
}
// withLink: true siempre (un enlace), o lo elegido en el popup («Añadir el enlace de la página»)
async function quickSend(text, page, withLink) {
  const { includeLink } = await browser.storage.local.get('includeLink');
  const body = { text: Panel.composeInbox(text, page, withLink ?? includeLink !== false), type: 'tarea', priority: null, category: null };
  if (!body.text) return;
  const shown = text.trim() || page.url;
  const preview = shown.length > 80 ? shown.slice(0, 79) + '…' : shown;
  try {
    const r = await Panel.send('inbox', body);
    notify(r.sent ? 'Enviado al Inbox' : 'Sin conexión: en la cola', r.sent ? preview : `${preview}\nSe enviará solo cuando vuelva la conexión.`);
  } catch (err) {
    notify('No se pudo enviar al Inbox', err.message);
    if (err.kind === 'config' || err.kind === 'auth') browser.runtime.openOptionsPage();
  }
  refreshBadge();
}

browser.contextMenus.onClicked.addListener((info, tab) => {
  const page = { url: tab?.url || '', title: tab?.title || '' };
  if (info.menuItemId === 'quick-selection') return quickSend(info.selectionText || '', page);
  // Un enlace: su texto (si lo hay) y la dirección; la página de origen no se añade
  if (info.menuItemId === 'quick-link') return quickSend(info.linkText || '', { url: info.linkUrl, title: '' }, true);
  if (info.menuItemId === 'inbox-selection') return openWith({ tab: 'inbox', text: info.selectionText || '', page });
  if (info.menuItemId === 'inbox-page') return openWith({ tab: 'inbox', text: '', page });
  if (info.menuItemId === 'vault-link') return openWith({ tab: 'vault', url: info.linkUrl, page });
  if (info.menuItemId === 'vault-page') return openWith({ tab: 'vault', url: page.url, page });
});

browser.commands.onCommand.addListener(async (cmd) => {
  if (cmd === 'open-agenda') return openWith({ tab: 'cal' });
  if (cmd !== 'open-vault') return;
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  openWith({ tab: 'vault', url: tab?.url || '', page: { url: tab?.url || '', title: tab?.title || '' } });
});

/* ---------- Mensajes del popup y las opciones ---------- */
browser.runtime.onMessage.addListener((msg) => {
  if (msg?.type === 'refresh') { latido(); return refreshBadge(); }  // se acaba de guardar la configuración
  // youtube.js: vídeo visto de un canal del Baúl (sin conexión va a la cola) y vistos de un canal
  if (msg?.type === 'yt-visto') {
    const { video_id, channel, title } = msg;
    return Panel.send('ytvisto', { video_id, channel, title })
      .then((r) => (r.sent ? r.data : { tracked: false, queued: true }))
      .catch(() => null);
  }
  if (msg?.type === 'yt-canal') {
    return Panel.request('/api/ext/youtube/canal?channel=' + encodeURIComponent(msg.channel)).catch(() => null);
  }
});

/* ---------- Content scripts solo donde hay permiso (S-4, 2.9) ----------
   Sin permisos de host fijos: el acceso al Panel (pantalla de acceso) y a YouTube se registra aquí, para el origen
   que se autorizó en las opciones. El fondo es persistente: los registros duran lo que dura Firefox abierto. */
let registered = [];
let syncing = Promise.resolve();
function syncContentScripts() {
  syncing = syncing.then(async () => {
    for (const r of registered) { try { await r.unregister(); } catch {} }
    registered = [];
    if (!browser.contentScripts?.register) return;
    const { baseUrl, token } = await Panel.getConfig();
    const { autoLogin = true } = await browser.storage.local.get('autoLogin');
    const panel = Panel.hostPattern(baseUrl);
    if (panel && token && autoLogin && await Panel.hasHost(panel)) {
      registered.push(await browser.contentScripts.register({
        matches: [panel.replace(/\/\*$/, '/login*')], js: [{ file: 'lib/panel.js' }, { file: 'autologin.js' }], runAt: 'document_idle',
      }));
    }
    if (await Panel.hasHost(Panel.YOUTUBE)) {
      registered.push(await browser.contentScripts.register({
        matches: [Panel.YOUTUBE], js: [{ file: 'youtube.js' }], css: [{ file: 'youtube.css' }], runAt: 'document_idle',
      }));
    }
  }).catch(() => {});
  return syncing;
}
browser.permissions?.onAdded?.addListener(() => { syncContentScripts(); refreshBadge(); });
browser.permissions?.onRemoved?.addListener(() => { syncContentScripts(); refreshBadge(); });
browser.storage.onChanged?.addListener((changes, area) => {
  if (area === 'local' && ['baseUrl', 'token', 'autoLogin'].some((k) => k in changes)) syncContentScripts();
});

/* ---------- Latido (2.11): el Panel sabe que la extensión sigue viva y por dónde entra ---------- */
function latido() { return Panel.heartbeat().catch(() => null); }  // sin configurar o sin conexión: ya lo dice la insignia

/* ---------- Reintentos y estado periódicos ---------- */
browser.alarms.create('refresh', { periodInMinutes: 1 });
browser.alarms.create('latido', { periodInMinutes: 30 });
browser.alarms.onAlarm.addListener((a) => { if (a.name === 'refresh') refreshBadge(); else if (a.name === 'latido') latido(); });
browser.runtime.onStartup?.addListener(refreshBadge);
browser.runtime.onInstalled.addListener(async (details) => {
  createMenus();
  // 2.9: la contraseña del Panel ya no se guarda (se entra con el token); la de versiones anteriores se borra
  await browser.storage.local.remove('loginPassword');
  refreshBadge();
  if (details.reason === 'install' || details.reason === 'update') {
    const { baseUrl, token } = await Panel.getConfig();
    // Sin token, o sin el permiso para la dirección del Panel (al pasar a la 2.9 hay que darlo una vez): opciones
    if (!token || !(await Panel.hasHost(Panel.hostPattern(baseUrl)))) browser.runtime.openOptionsPage();
  }
});
self.addEventListener?.('online', refreshBadge);
createMenus();
refreshBadge();
syncContentScripts();
latido();
