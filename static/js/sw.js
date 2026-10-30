/* Service worker del Panel. __VERSION__ y __PRECACHE__ los rellena el servidor
   (core/pwa.py) con un hash del contenido de los recursos: cada despliegue
   invalida la caché anterior sin tocar nada a mano. */
const VERSION = '__VERSION__';
const STATIC_CACHE = `panel-static-${VERSION}`;
const DATA_CACHE = 'panel-data-v1';
const DATA_MAX = 200; // sin tope crecería con cada URL distinta (semanas, días del calendario…)
let dataPuts = 0;
const PRECACHE = __PRECACHE__;
const OFFLINE_URL = '/static/offline.html';

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(STATIC_CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith('panel-static-') && key !== STATIC_CACHE) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

const isCacheable = (res) => res && res.ok && !res.redirected && res.type === 'basic';

async function trimDataCache(cache) {
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - DATA_MAX)).map((k) => cache.delete(k)));
}

async function networkFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(request);
    if (isCacheable(res)) {
      const stored = cache.put(request, res.clone());
      if (++dataPuts % 50 === 0) stored.then(() => trimDataCache(cache));
    }
    return res;
  } catch (err) {
    const cached = await cache.match(request);
    if (cached) return cached;
    throw err;
  }
}

async function staleWhileRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then((res) => { if (isCacheable(res)) cache.put(request, res.clone()); return res; }).catch(() => cached);
  return cached || network;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;
  // Cerrar sesión borra lo guardado para trabajar sin conexión: son notas, tareas y datos personales
  if (url.pathname.startsWith('/logout')) { event.waitUntil(caches.delete(DATA_CACHE)); return; }
  if (request.method !== 'GET') return;
  // Nunca cachear el login, las búsquedas ni descargas
  if (url.pathname.startsWith('/login') || url.pathname.startsWith('/api/search') || url.pathname.includes('/export') || url.pathname.includes('/download')) return;

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, DATA_CACHE).catch(async () =>
      (await caches.match(OFFLINE_URL)) || new Response('Sin conexión', { status: 503 })));
    return;
  }
  if (url.pathname.includes('/api/')) {
    event.respondWith(networkFirst(request, DATA_CACHE).catch(() =>
      new Response(JSON.stringify({ error: 'Sin conexión' }), { status: 503, headers: { 'Content-Type': 'application/json' } })));
    return;
  }
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/comidas/') || url.pathname.startsWith('/estudio/')) {
    event.respondWith(staleWhileRevalidate(request));
  }
});

// Recordatorios (static/js/reminders.js): al tocar la notificación se abre (o enfoca) el Panel en su sitio
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = event.notification.data?.url || '/';
  event.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const win = wins.find((w) => new URL(w.url).origin === self.location.origin);
    if (win) { await win.focus(); return win.navigate(url).catch(() => null); }
    return self.clients.openWindow(url);
  })());
});
