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

  // Permiso de host (opcional desde la 2.9, S-4): solo el origen del Panel y YouTube, pedidos en las opciones.
  // Los patrones de Firefox no llevan puerto: http://192.168.1.41/* vale para cualquier puerto de esa dirección.
  const YOUTUBE = 'https://www.youtube.com/*';
  function hostPattern(baseUrl) {
    try {
      const u = new URL(normalizeUrl(baseUrl));
      return `${u.protocol}//${u.hostname}/*`;
    } catch { return ''; }
  }
  async function hasHost(pattern) {
    if (!pattern) return false;
    if (!browser.permissions?.contains) return true;   // sin la API (pruebas antiguas): como antes
    try { return await browser.permissions.contains({ origins: [pattern] }); } catch { return false; }
  }

  /* ---------- Dónde está el Panel (2.11) ----------
     La dirección se guarda en el almacenamiento (baseUrl), nunca en el código. Para no depender de una IP que cambia:
       · «Detectar» (opciones) prueba, por orden, las direcciones que el propio Panel dijo en su último latido
         (panelUrls: la primera es la recomendada, normalmente el nombre https de la tailnet), este equipo y la reserva
         DHCP del servidor. Vale la que conteste a /healthz (público) con app = panel-maestro.
       · Si la dirección guardada deja de contestar, la extensión cambia sola a otra de las del latido, pero solo a
         una https o de este mismo equipo y con permiso ya dado: una IP http de la red local no se adopta sin que la
         confirmes (en otra wifi podría ser otro aparato y se llevaría el token). */
  const DEFAULT_URLS = ['http://127.0.0.1:8000', 'http://localhost:8000', 'http://192.168.1.50:8000'];
  const RECOVER_EVERY_MS = 60000;
  let lastRecover = 0;

  async function knownUrls() {
    const { panelUrls = [] } = await browser.storage.local.get('panelUrls');
    return (Array.isArray(panelUrls) ? panelUrls : []).map(normalizeUrl).filter(Boolean);
  }
  async function candidates(extra = []) {
    return [...new Set([...extra.map(normalizeUrl), ...(await knownUrls()), ...DEFAULT_URLS].filter(Boolean))];
  }
  const isLoopback = (url) => { try { return ['127.0.0.1', 'localhost', '[::1]'].includes(new URL(url).hostname); } catch { return false; } };
  const safeToAdopt = (url) => /^https:\/\//i.test(url) || isLoopback(url);

  // ¿Contesta el Panel en esa dirección? (sin token: /healthz es público)
  async function isPanel(baseUrl, timeout = 2500) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      const res = await fetch(normalizeUrl(baseUrl) + '/healthz', { signal: ctrl.signal, credentials: 'omit', cache: 'no-store' });
      return (await res.json())?.app === 'panel-maestro';
    } catch { return false; } finally { clearTimeout(timer); }
  }
  // La primera de `urls` (en su orden) donde está el Panel; solo se prueban las que tienen permiso
  async function detect(urls) {
    const allowed = [];
    for (const u of urls) if (await hasHost(hostPattern(u))) allowed.push(u);
    const found = await Promise.all(allowed.map((u) => isPanel(u)));
    return allowed.find((_, i) => found[i]) || '';
  }
  // La guardada no contesta: ¿está el Panel en otra de sus direcciones? (como mucho una búsqueda por minuto)
  async function recover(current) {
    if (Date.now() - lastRecover < RECOVER_EVERY_MS) return '';
    lastRecover = Date.now();
    const alt = await detect((await knownUrls()).filter((u) => u !== current && safeToAdopt(u)));
    if (alt) await browser.storage.local.set({ baseUrl: alt, movedFrom: current, movedAt: Date.now() });
    return alt;
  }

  // Latido: la extensión dice al Panel que sigue viva y por dónde entra (Ajustes → Red y dispositivos), y el Panel
  // contesta con sus direcciones de ahora, que se guardan para «Detectar» y para el cambio automático.
  async function heartbeat(cfg) {
    const used = cfg || (await getConfig());
    const ua = navigator.userAgent.match(/(Firefox|Chrome|Edg)\/(\d+)/);
    const data = await request('/api/red/latido', {
      method: 'POST', cfg,
      body: { version: browser.runtime.getManifest?.().version || '', url: used.baseUrl, navegador: ua ? `${ua[1]} ${ua[2]}` : '' },
    });
    const urls = [...new Set([data?.principal, ...(data?.urls || [])].map(normalizeUrl).filter(Boolean))];
    if (urls.length) await browser.storage.local.set({ panelUrls: urls });
    return { principal: normalizeUrl(data?.principal), urls };
  }

  async function getConfig() {
    const { baseUrl = '', token = '' } = await browser.storage.local.get(['baseUrl', 'token']);
    return { baseUrl: normalizeUrl(baseUrl), token: String(token || '').trim() };
  }

  // Petición al Panel. cfg permite probar una configuración sin guardarla (Opciones).
  async function request(path, { method = 'GET', body, cfg, noRecover = false } = {}) {
    const { baseUrl, token } = cfg || (await getConfig());
    if (!baseUrl || !token) throw new PanelError('config', 'Falta configurar la dirección del Panel y el token');
    if (!(await hasHost(hostPattern(baseUrl)))) {
      const e = new PanelError('config', 'Falta el permiso para la dirección del Panel: abre las opciones y pulsa Guardar');
      e.permission = true;   // es configuración (no se reintenta solo), pero el popup lo explica distinto
      throw e;
    }
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
      clearTimeout(timer);
      // Solo con la configuración guardada (no al probar una del formulario) y una vez: ¿ha cambiado de dirección?
      const alt = !cfg && !noRecover ? await recover(baseUrl) : '';
      if (alt) return request(path, { method, body, noRecover: true });
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

  self.Panel = { PanelError, normalizeUrl, hostPattern, hasHost, YOUTUBE, getConfig, request, status, send, flush, getQueue, detectType, isWebUrl, composeInbox,
    DEFAULT_URLS, candidates, isPanel, detect, heartbeat, safeToAdopt };
})();
