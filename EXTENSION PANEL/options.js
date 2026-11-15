/* options.js — dirección del Panel, token y entrada automática con el token; «Probar conexión» antes de guardar.
   Permisos (2.9, S-4): la extensión no tiene acceso fijo a ninguna web. Al guardar o probar se pide permiso solo para
   el origen del Panel; YouTube, solo si se usa. permissions.request tiene que llamarse dentro del clic, antes de
   cualquier await (si no, Firefox lo rechaza). */
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

// Pide (dentro del gesto del usuario) el permiso para el origen del Panel; devuelve la promesa de la respuesta
function askHost(baseUrl) {
  const pattern = Panel.hostPattern(baseUrl);
  if (!pattern || !browser.permissions?.request) return Promise.resolve(Boolean(pattern));
  return browser.permissions.request({ origins: [pattern] }).catch(() => false);
}

// Prueba la configuración del formulario (sin guardarla). prefix: «Guardado. » al guardar
async function test(prefix = '', granted = Promise.resolve(true)) {
  const cfg = formCfg();
  if (!cfg.baseUrl || !cfg.token) { show('error', 'Escribe la dirección del Panel y el token'); return false; }
  if (!(await granted)) {
    show('error', `${prefix}Sin permiso para ${new URL(cfg.baseUrl).host}, la extensión no puede hablar con el Panel. Pulsa otra vez y acepta el aviso de Firefox.`);
    return false;
  }
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
  const { autoLogin = true } = await browser.storage.local.get('autoLogin');
  $('autoLogin').checked = autoLogin;
  const { ytAuto = true, ytPct = 50 } = await browser.storage.local.get(['ytAuto', 'ytPct']);
  $('ytAuto').checked = ytAuto;
  $('ytPct').value = ytPct;
  syncYoutubePermission();
  (cfg.baseUrl ? $('token') : $('baseUrl')).focus();
}

$('test').addEventListener('click', () => test('', askHost(formCfg().baseUrl)));
$('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const cfg = formCfg();
  const granted = cfg.baseUrl && cfg.token ? askHost(cfg.baseUrl) : Promise.resolve(false);  // antes de cualquier await
  if (!cfg.baseUrl || !cfg.token) { show('error', 'Escribe la dirección del Panel y el token'); return; }
  await browser.storage.local.set({ ...cfg, autoLogin: $('autoLogin').checked });
  await browser.storage.local.remove('loginPassword');  // de versiones anteriores a la 2.9
  $('baseUrl').value = cfg.baseUrl;
  await test('Guardado. ', granted);
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
$('autoLogin').addEventListener('change', () => browser.storage.local.set({ autoLogin: $('autoLogin').checked }));

// YouTube: permiso solo para youtube.com, pedido al activarlo (o con el botón si falta)
async function syncYoutubePermission() {
  $('ytPermRow').hidden = await Panel.hasHost(Panel.YOUTUBE);
}
function askYoutube() {
  return (browser.permissions?.request ? browser.permissions.request({ origins: [Panel.YOUTUBE] }) : Promise.resolve(true))
    .catch(() => false).then((ok) => { syncYoutubePermission(); return ok; });
}
$('ytPerm').addEventListener('click', () => askYoutube());

// YouTube: se guarda al cambiar (sin pasar por «Guardar»)
$('ytAuto').addEventListener('change', () => {
  const on = $('ytAuto').checked;
  const asked = on ? askYoutube() : Promise.resolve(true);  // dentro del clic
  browser.storage.local.set({ ytAuto: on });
  asked.then((ok) => { if (!ok) { $('ytAuto').checked = false; browser.storage.local.set({ ytAuto: false }); } });
});
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
