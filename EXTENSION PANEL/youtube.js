/* ==========================================================================
   youtube.js — content script de youtube.com.
   · Página de un vídeo: si su canal está en el Baúl, lo marca como visto al
     llevar reproducido el umbral elegido (por defecto, la mitad).
   · Página de un canal del Baúl: marca «Visto» en las miniaturas ya vistas.
   Las peticiones al Panel las hace background.js (aquí no hay token).
   ========================================================================== */
(function () {
  'use strict';

  const SEEN = 'panel-visto';
  const CARDS = 'ytd-rich-item-renderer, ytd-grid-video-renderer, ytd-video-renderer, ytd-playlist-video-renderer, ytd-compact-video-renderer';
  const THUMB = 'yt-thumbnail-view-model, ytd-thumbnail, #thumbnail'; // el diseño nuevo usa el primero
  const send = (msg) => browser.runtime.sendMessage(msg).catch(() => null);

  let opts = { ytAuto: true, ytPct: 50 };
  const loadOpts = () => browser.storage.local.get(['ytAuto', 'ytPct']).then((o) => {
    opts = { ytAuto: o.ytAuto !== false, ytPct: Math.min(100, Math.max(10, Number(o.ytPct) || 50)) };
  }).catch(() => {});
  browser.storage.onChanged.addListener(loadOpts);

  /* ---------- Página de vídeo ---------- */
  let watch = null; // { id, played, last, sent }

  function videoId() {
    return location.pathname === '/watch' ? new URLSearchParams(location.search).get('v') : null;
  }
  function ownerChannel() {
    const a = document.querySelector('ytd-watch-metadata ytd-video-owner-renderer a[href*="/@"], ytd-watch-metadata ytd-video-owner-renderer a[href*="/channel/"], #owner a[href*="/@"], #owner a[href*="/channel/"]');
    return a ? decodeURIComponent(a.getAttribute('href')).split('?')[0] : '';
  }
  function videoTitle() {
    return (document.querySelector('ytd-watch-metadata h1')?.textContent || document.title.replace(/ - YouTube$/, '')).trim();
  }

  function onTime(e) {
    const v = e.target;
    const id = videoId();
    if (!opts.ytAuto || !id || !watch || watch.id !== id || watch.sent) return;
    if (!isFinite(v.duration) || v.duration < 30) return; // directos y clips muy cortos no cuentan
    const dt = v.currentTime - watch.last;
    watch.last = v.currentTime;
    if (dt > 0 && dt < 2.5) watch.played += dt; // solo tiempo realmente reproducido (los saltos no suman)
    if (watch.played < Math.min(v.duration * opts.ytPct / 100, 600)) return;
    const channel = ownerChannel();
    if (!channel) return; // el DOM aún no tiene el canal: se reintenta en el siguiente evento
    watch.sent = true;
    send({ type: 'yt-visto', video_id: id, channel, title: videoTitle() }).then((r) => {
      if (r?.tracked) remember(id);
    });
  }

  function hookVideo() {
    const v = document.querySelector('video.html5-main-video, video');
    if (!v || v.dataset.panelHook) return;
    v.dataset.panelHook = '1';
    v.addEventListener('timeupdate', onTime);
    v.addEventListener('seeking', () => { if (watch) watch.last = v.currentTime; });
  }

  function onWatchPage() {
    const id = videoId();
    if (!id) { watch = null; return; }
    if (!watch || watch.id !== id) watch = { id, played: 0, last: 0, sent: false };
    hookVideo();
  }

  /* ---------- Página de canal ---------- */
  let seen = new Set();
  let seenFor = '';
  let observer = null;

  function remember(id) { seen.add(id); paint(); }

  function pageChannel() {
    const m = location.pathname.match(/^\/(@[^/]+|channel\/[\w-]+|(?:c|user)\/[^/]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function paint() {
    if (!seen.size) return;
    for (const card of document.querySelectorAll(CARDS)) {
      const a = card.querySelector('a[href*="/watch?v="]');
      const id = a && new URLSearchParams(a.search).get('v');
      const on = !!id && seen.has(id);
      if (on === card.classList.contains(SEEN)) continue;
      card.classList.toggle(SEEN, on);
      const host = card.querySelector(THUMB);
      host?.querySelector('.panel-visto-badge')?.remove();
      if (on && host) {
        const b = document.createElement('span');
        b.className = 'panel-visto-badge';
        b.textContent = '✓ Visto';
        host.appendChild(b);
      }
    }
  }

  let timer = 0;
  const schedulePaint = () => { clearTimeout(timer); timer = setTimeout(paint, 200); };

  async function onChannelPage() {
    const ch = pageChannel();
    if (!ch) { seenFor = ''; seen = new Set(); observer?.disconnect(); observer = null; return; }
    if (seenFor !== ch) {
      seenFor = ch;
      seen = new Set();
      const r = await send({ type: 'yt-canal', channel: ch });
      if (seenFor !== ch) return; // se navegó a otro mientras tanto
      seen = new Set(r?.watched || []);
    }
    if (!seen.size) return;
    if (!observer) {
      observer = new MutationObserver(schedulePaint); // scroll infinito y cambio de pestaña dentro del canal
      observer.observe(document.body, { childList: true, subtree: true });
    }
    paint();
  }

  /* ---------- Navegación sin recarga de YouTube ---------- */
  function route() {
    onWatchPage();
    onChannelPage();
  }
  document.addEventListener('yt-navigate-finish', route);
  loadOpts().then(route);
})();
