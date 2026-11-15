/* ==========================================================================
   autologin.js — en la pantalla de acceso del Panel (solo en la dirección
   configurada) entra con el token de la extensión: POST /api/ext/sesion
   devuelve la cookie de sesión y se sigue a la página que se pedía.
   La contraseña del Panel ya no se guarda en ningún sitio (desde la 2.9).
   Lo registra background.js solo para el origen del Panel, y solo si se
   dio permiso para él. Si la página muestra un error (o el token no vale)
   no lo reintenta, para no entrar en bucle.
   ========================================================================== */
'use strict';

(async () => {
  const form = document.querySelector('form[action="/login"]');
  if (!form) return;

  const { baseUrl = '', token = '', autoLogin = true } = await browser.storage.local.get(['baseUrl', 'token', 'autoLogin']);
  if (!autoLogin || !token || !baseUrl) return;
  let origin = '';
  try { origin = new URL(Panel.normalizeUrl(baseUrl)).origin; } catch { return; }
  if (location.origin !== origin) return;
  if (document.querySelector('.login-msg.error, [role="alert"]')) return;

  // Un intento cada 15 s como mucho, por si la página cambia y deja de mostrar el error
  const KEY = 'panelAutoLogin';
  try {
    if (Date.now() - Number(sessionStorage.getItem(KEY) || 0) < 15000) return;
    sessionStorage.setItem(KEY, String(Date.now()));
  } catch {}

  // content.fetch (Firefox): la petición sale de la propia página del Panel, así que la cookie que devuelve es suya.
  // El token no pasa a la página: queda en este script (mundo aislado).
  const init = { method: 'POST', credentials: 'same-origin', headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' } };
  const pageFetch = typeof content !== 'undefined' && content.fetch ? content.fetch.bind(content) : fetch;
  try {
    const res = await pageFetch('/api/ext/sesion', typeof cloneInto === 'function' ? cloneInto(init, window) : init);
    if (!res.ok) return;
  } catch { return; }

  const next = new URLSearchParams(location.search).get('next') || form.querySelector('input[name="next"]')?.value || '/';
  location.replace(next.startsWith('/') && !next.startsWith('//') ? next : '/');
})();
