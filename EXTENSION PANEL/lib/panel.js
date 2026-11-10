/* ==========================================================================
   panel.js — lo común de la extensión: configuración, peticiones al Panel con
   el token (cabecera Authorization: Bearer) y cola de envíos sin conexión.
   Script clásico: lo cargan el fondo (background.js), el popup y las opciones.
   ========================================================================== */
(function () {
  'use strict';

  const TIMEOUT_MS = 8000;
  const QUEUE_MAX = 200;

  class PanelError extends Error {
    // kind: 'config' (falta URL/token) | 'auth' (token no válido) | 'network' (sin conexión) |
    //       'duplicate' (ya está en el Baúl) | 'invalid' (datos rechazados) | 'server'
    constructor(kind, message, status = 0) { super(message); this.kind = kind; this.status = status; }
    get retryable() { return this.kind === 'network' || (this.kind === 'server' && this.status >= 500); }
  }

  function normalizeUrl(value) {
    let v = String(value || '').trim();
    if (!v) return '';
    if (!/^https?:\/\//i.test(v)) v = 'http://' + v;
    return v.replace(/\/+$/, '');
  }

  async function getConfig() {
    const { baseUrl = '', token = '' } = await browser.storage.local.get(['baseUrl', 'token']);
    return { baseUrl: normalizeUrl(baseUrl), token: String(token || '').trim() };
  }

  // Petición al Panel. cfg permite probar una configuración sin guardarla (Opciones).
  async function request(path, { method = 'GET', body, cfg } = {}) {
    const { baseUrl, token } = cfg || (await getConfig());
    if (!baseUrl || !token) throw new PanelError('config', 'Falta configurar la dirección del Panel y el token');
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    let res;
    try {
      res = await fetch(baseUrl + path, {
        method,
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body: body ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
        credentials: 'omit',
      });
    } catch {
      throw new PanelError('network', 'No se puede conectar con el Panel');
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = await res.json(); } catch {}
    if (res.ok) return data;
    const detail = typeof data?.detail === 'string' ? data.detail : Array.isArray(data?.detail) ? data.detail[0]?.msg : data?.error;
    if (res.status === 401) throw new PanelError('auth', 'Token no válido: revísalo en las opciones', 401);
    if (res.status === 409) throw new PanelError('duplicate', 'Ya está en el Baúl', 409);
    if (res.status === 422 || res.status === 400) throw new PanelError('invalid', detail || 'El Panel no aceptó los datos', res.status);
    if (res.status === 503 && data?.error === 'Sin conexión') throw new PanelError('network', 'No se puede conectar con el Panel', 503);
    throw new PanelError('server', detail || `El Panel respondió con un error (${res.status})`, res.status);
  }

  const status = (cfg) => request('/api/ext/status', { cfg });

  /* ---------- Envíos (con cola si no hay conexión) ---------- */
  // /api/items: la misma API que usa el Panel para crear; /api/capture: prefijos y eventos en lenguaje natural
  const ENDPOINTS = { inbox: '/api/items', vault: '/api/resources', capture: '/api/capture', ytvisto: '/api/ext/youtube/visto' };

  // Lo que dejó en la cola una versión anterior (2.1 o menos) va con el formato de /api/inbox
  const upgrade = (kind, body) => (kind === 'inbox' && body && body.text === undefined && body.content !== undefined
    ? { text: body.content, type: body.item_type === 'nota' ? 'idea' : 'tarea', priority: body.priority ?? null, category: body.category ?? null }
    : body);

  async function getQueue() { return (await browser.storage.local.get('queue')).queue || []; }
  async function setQueue(q) { await browser.storage.local.set({ queue: q.slice(-QUEUE_MAX) }); }

  // Envía o, si no hay conexión, lo deja en la cola. Devuelve { sent: true, data } o { queued: n }.
  async function send(kind, body) {
    try {
      const data = await request(ENDPOINTS[kind], { method: 'POST', body });
      return { sent: true, data };
    } catch (err) {
      if (!err.retryable) throw err;
      const q = await getQueue();
      q.push({ kind, body, at: Date.now() });
      await setQueue(q);
      return { queued: q.length };
    }
  }

  // Reintenta la cola en orden. Lo que el Panel rechaza (duplicado, datos no válidos) se descarta;
  // si vuelve a fallar la conexión se para y se deja para la próxima vez.
  let flushing = null;
  function flush() {
    if (flushing) return flushing;
    flushing = (async () => {
      let q = await getQueue();
      let sent = 0, dropped = 0;
      while (q.length) {
        const it = q[0];
        try {
          await request(ENDPOINTS[it.kind], { method: 'POST', body: upgrade(it.kind, it.body) });
          sent++;
        } catch (err) {
          if (err.retryable || err.kind === 'auth' || err.kind === 'config') break;
          dropped++;
        }
        q = q.slice(1);
        await setQueue(q);
      }
      return { sent, dropped, left: q.length };
    })();
    return flushing.finally(() => { flushing = null; });
  }

  /* ---------- Utilidades ---------- */
  function detectType(url) {
    let host = '';
    try { host = new URL(url).hostname; } catch {}
    if (/(^|\.)youtube\.com$|^youtu\.be$/i.test(host)) {
      if (/\/watch\?|youtu\.be\/|\/shorts\//i.test(url)) return { key: 'video', label: 'Vídeo de YouTube' };
      if (/\/(channel|c|user)\/|\/@/i.test(url)) return { key: 'channel', label: 'Canal de YouTube' };
      return { key: 'youtube', label: 'YouTube' };
    }
    return { key: 'web', label: 'Página web' };
  }
  const isWebUrl = (url) => /^https?:\/\//i.test(url || '');

  // Texto que se guarda en el Inbox: lo escrito y, si se pide, el título y el enlace de la página
  function composeInbox(text, page, includeLink) {
    const t = String(text || '').trim();
    if (!includeLink || !page || !isWebUrl(page.url)) return t;
    const ref = [page.title && page.title !== page.url ? page.title.trim() : '', page.url].filter(Boolean).join('\n');
    return t ? `${t}\n\n${ref}` : ref;
  }

  self.Panel = { PanelError, normalizeUrl, getConfig, request, status, send, flush, getQueue, detectType, isWebUrl, composeInbox };
})();
