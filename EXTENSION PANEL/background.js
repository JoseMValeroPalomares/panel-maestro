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
  if (msg?.type === 'refresh') return refreshBadge();
});

/* ---------- Reintentos y estado periódicos ---------- */
browser.alarms.create('refresh', { periodInMinutes: 1 });
browser.alarms.onAlarm.addListener((a) => { if (a.name === 'refresh') refreshBadge(); });
browser.runtime.onStartup?.addListener(refreshBadge);
browser.runtime.onInstalled.addListener(async (details) => {
  createMenus();
  refreshBadge();
  if (details.reason === 'install' || details.reason === 'update') {
    const { token } = await Panel.getConfig();
    if (!token) browser.runtime.openOptionsPage(); // la versión 2 necesita el token: se piden los datos
  }
});
self.addEventListener?.('online', refreshBadge);
createMenus();
refreshBadge();
