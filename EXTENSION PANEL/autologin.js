/* ==========================================================================
   autologin.js — en la pantalla de acceso del Panel (solo en la dirección
   configurada) escribe la contraseña guardada en las opciones y entra.
   Si la página ya muestra un error (contraseña incorrecta, demasiados
   intentos) no lo vuelve a intentar, para no entrar en bucle ni bloquearse.
   ========================================================================== */
'use strict';

(async () => {
  const form = document.querySelector('form[action="/login"]');
  const input = form?.querySelector('input[name="password"]');
  if (!form || !input) return;

  const { baseUrl = '', autoLogin = true, loginPassword = '' } =
    await browser.storage.local.get(['baseUrl', 'autoLogin', 'loginPassword']);
  if (!autoLogin || !loginPassword || !baseUrl) return;
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

  input.value = loginPassword;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  form.requestSubmit ? form.requestSubmit() : form.submit();
})();
