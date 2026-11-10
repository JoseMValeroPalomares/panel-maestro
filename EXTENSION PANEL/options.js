/* options.js — dirección del Panel, token e inicio de sesión automático; «Probar conexión» antes de guardar. */
'use strict';

const $ = (id) => document.getElementById(id);

function show(type, text) {
  const el = $('result');
  el.dataset.type = type;
  el.innerHTML = `<svg class="icon"><use href="icons.svg#i-${type === 'ok' ? 'check' : 'circle-alert'}"/></svg><span></span>`;
  el.querySelector('span').textContent = text;
  el.hidden = false;
}
const formCfg = () => ({ baseUrl: Panel.normalizeUrl($('baseUrl').value), token: $('token').value.trim() });

// Prueba la configuración del formulario (sin guardarla). prefix: «Guardado. » al guardar
async function test(prefix = '') {
  const cfg = formCfg();
  if (!cfg.baseUrl || !cfg.token) { show('error', 'Escribe la dirección del Panel y el token'); return false; }
  $('test').disabled = true;
  try {
    const st = await Panel.status(cfg);
    show('ok', `${prefix}Conectado: tienes ${st.pending} pendiente${st.pending === 1 ? '' : 's'} en el Inbox.`);
    return true;
  } catch (err) {
    show('error', prefix + (err.kind === 'network' ? `No se puede conectar con ${cfg.baseUrl}: ¿está el Panel en marcha y la dirección bien escrita?` : err.message));
    return false;
  } finally { $('test').disabled = false; }
}

async function load() {
  const cfg = await Panel.getConfig();
  $('baseUrl').value = cfg.baseUrl;
  $('token').value = cfg.token;
  const { autoLogin = true, loginPassword = '' } = await browser.storage.local.get(['autoLogin', 'loginPassword']);
  $('autoLogin').checked = autoLogin;
  $('loginPassword').value = loginPassword;
  syncAutoLogin();
  const { ytAuto = true, ytPct = 50 } = await browser.storage.local.get(['ytAuto', 'ytPct']);
  $('ytAuto').checked = ytAuto;
  $('ytPct').value = ytPct;
  (cfg.baseUrl ? $('token') : $('baseUrl')).focus();
}

$('test').addEventListener('click', () => test());
$('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const cfg = formCfg();
  if (!cfg.baseUrl || !cfg.token) { show('error', 'Escribe la dirección del Panel y el token'); return; }
  const login = { autoLogin: $('autoLogin').checked, loginPassword: $('loginPassword').value };
  await browser.storage.local.set({ ...cfg, ...login });
  $('baseUrl').value = cfg.baseUrl;
  await test('Guardado. ');
  browser.runtime.sendMessage({ type: 'refresh' }).catch(() => {});
});
// Botón del ojo: muestra u oculta el campo (what: «el token», «la contraseña»)
function toggleVisible(btn, input, what) {
  const show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.setAttribute('aria-pressed', String(show));
  btn.setAttribute('aria-label', `${show ? 'Ocultar' : 'Mostrar'} ${what}`);
  btn.querySelector('use').setAttribute('href', `icons.svg#i-${show ? 'eye-off' : 'eye'}`);
}
$('toggleToken').addEventListener('click', (e) => toggleVisible(e.currentTarget, $('token'), 'el token'));
$('togglePassword').addEventListener('click', (e) => toggleVisible(e.currentTarget, $('loginPassword'), 'la contraseña'));

// La contraseña se conserva aunque se desactive: solo se atenúa el campo
function syncAutoLogin() {
  const set = $('autoLogin').closest('fieldset');
  if ($('autoLogin').checked) delete set.dataset.off; else set.dataset.off = '';
}
$('autoLogin').addEventListener('change', syncAutoLogin);

// YouTube: se guarda al cambiar (sin pasar por «Guardar»)
$('ytAuto').addEventListener('change', () => browser.storage.local.set({ ytAuto: $('ytAuto').checked }));
$('ytPct').addEventListener('change', () => {
  const v = Math.min(100, Math.max(10, Number($('ytPct').value) || 50));
  $('ytPct').value = v;
  browser.storage.local.set({ ytPct: v });
});

/* ---------- Tema (los mismos del Panel; lib/themes.js) ---------- */
function renderThemes() {
  const grid = $('themeGrid');
  const current = document.documentElement.getAttribute('data-theme');
  grid.replaceChildren(...self.PANEL_THEMES.map((t) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'theme-option';
    b.setAttribute('role', 'radio');
    b.dataset.theme = t.key;
    b.setAttribute('aria-checked', String(t.key === current));
    b.tabIndex = t.key === current ? 0 : -1;
    const sw = document.createElement('span');
    sw.className = 'theme-swatch';
    sw.setAttribute('aria-hidden', 'true');
    for (const [k, v] of Object.entries(t.preview)) sw.style.setProperty('--p-' + k, v);
    sw.append(document.createElement('span'), document.createElement('span'));
    const name = Object.assign(document.createElement('span'), { className: 'theme-name', textContent: t.label });
    b.append(sw, name);
    return b;
  }));
}
function setTheme(key, focus = false) {
  document.documentElement.setAttribute('data-theme', key);
  try { localStorage.setItem('theme', key); } catch {}
  renderThemes();
  if (focus) $('themeGrid').querySelector(`[data-theme="${key}"]`)?.focus();
}
$('themeGrid').addEventListener('click', (e) => { const b = e.target.closest('[data-theme]'); if (b) setTheme(b.dataset.theme, true); });
$('themeGrid').addEventListener('keydown', (e) => {
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!step) return;
  e.preventDefault();
  const keys = self.PANEL_THEMES.map((t) => t.key);
  const i = keys.indexOf(document.documentElement.getAttribute('data-theme'));
  setTheme(keys[(i + step + keys.length) % keys.length], true);
});

document.addEventListener('DOMContentLoaded', () => { load(); renderThemes(); });
