/* ==========================================================================
   classify.js — clasificación automática de lo que se guarda en el Baúl.
   Funciones puras (sin red ni DOM) que usan el popup y los tests.

     Classify.youtubeId(url)  → ID de 11 caracteres si es un vídeo (watch?v=…&list=…, youtu.be/, shorts/, live/, embed/), si no null
     Classify.isChannel(url)  → true en /@usuario, /channel/…, /c/…, /user/…
     Classify.detect({ url, exists, played, duration, threshold })
        → { state: 'channel' | 'later' | 'seen' | 'normal', save: '' | 'later' | 'seen', label, reason, certain }

   Reglas: canal → se guarda como canal de YouTube; vídeo que ya está en el Baúl, o con el % visto por encima del umbral
   → «visto»; vídeo nuevo → «ver más tarde»; si no se puede saber (sin conexión, página de YouTube que no es vídeo ni canal)
   → «ver más tarde» marcado como NO seguro, para que se pueda cambiar con un clic. Las webs que no son de YouTube no se
   clasifican («normal»).
   ========================================================================== */
(function () {
  'use strict';
  const HOST = /^(?:www\.|m\.|music\.)?(?:youtube\.com|youtube-nocookie\.com)$|^youtu\.be$/i;
  const ID = /^[\w-]{11}$/;

  function parse(url) { try { return new URL(String(url || '').trim()); } catch { return null; } }

  function youtubeId(url) {
    const u = parse(url);
    if (!u || !HOST.test(u.hostname)) return null;
    let id = '';
    if (u.hostname.toLowerCase() === 'youtu.be') id = u.pathname.split('/')[1] || '';
    else {
      const m = u.pathname.match(/^\/(?:shorts|live|embed|v)\/([\w-]{11})(?:\/|$)/);
      id = m ? m[1] : (u.pathname.replace(/\/$/, '') === '/watch' ? u.searchParams.get('v') || '' : '');
    }
    return ID.test(id) ? id : null;
  }

  function isChannel(url) {
    const u = parse(url);
    return !!u && HOST.test(u.hostname) && /^\/(?:@[^/]+|channel\/[^/]+|c\/[^/]+|user\/[^/]+)/.test(u.pathname);
  }

  function isYoutube(url) { const u = parse(url); return !!u && HOST.test(u.hostname); }

  function detect({ url, exists = null, played = null, duration = null, threshold = 50 } = {}) {
    if (!isYoutube(url)) return { state: 'normal', save: '', label: 'Enlace web', reason: 'No es de YouTube: se guarda sin clasificar', certain: true };
    if (isChannel(url)) return { state: 'channel', save: '', label: 'Canal de YouTube', reason: 'Es la página de un canal', certain: true };
    const id = youtubeId(url);
    if (!id) return { state: 'later', save: 'later', label: 'Ver más tarde', reason: 'No reconozco qué es esta página de YouTube', certain: false };
    if (exists) return { state: 'seen', save: 'seen', label: 'Visto', reason: 'El vídeo ya está en el Baúl', certain: true };
    if (duration >= 30 && played != null) {
      const pct = Math.round((played / duration) * 100);
      if (played >= Math.min(duration * threshold / 100, 600)) return { state: 'seen', save: 'seen', label: 'Visto', reason: `Llevas el ${pct} % (umbral: ${threshold} %)`, certain: true };
    }
    if (exists === null) return { state: 'later', save: 'later', label: 'Ver más tarde', reason: 'Sin conexión: no sé si ya está en el Baúl', certain: false };
    return { state: 'later', save: 'later', label: 'Ver más tarde', reason: 'Vídeo nuevo en el Baúl', certain: true };
  }

  self.Classify = { youtubeId, isChannel, isYoutube, detect };
})();
