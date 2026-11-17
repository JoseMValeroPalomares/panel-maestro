// =====================================================================
// Panel de Estudio - pagina web unica
// NOTA: esta app vive montada bajo "/estudio" dentro del proceso
// fusionado con el Cerebro Digital, por eso "/config" se pide con el
// prefijo completo. El WebSocket tampoco va directo al ESP32: entra por
// el puente /estudio/ws del panel (estudio/main.py), que reenvia a la placa.
// Asi funciona bajo HTTPS (un ws:// directo seria contenido mixto) y desde
// fuera de casa, y la web no necesita saber la IP de la placa.
// =====================================================================

let ws = null;
let esp32WsUrl = null;


const state = {
  pomodoro: { workMin: 25, breakMin: 5, phase: "work", runState: "stopped", remainingSec: 25 * 60, lastSync: 0 },
  tasks: {
    categories: null,  // null = aún no ha llegado nada de la placa (no es lo mismo que «no hay»)
    itemsByCategory: {},
    openCategories: new Set(),
    editingItem: null,
  },
};


// =====================================================================
// PERSONALIZACION DE FONDO
// =====================================================================
const THEME_STORAGE_KEY = "panelEstudioTheme";
const DEFAULT_ACCENT = { r: 91, g: 124, b: 250 };

// Tamaño que espera el ESP32 para el fondo personalizado (ver
// background_module.h: BG_IMG_W/BG_IMG_H = 160x120, escalado x2 en
// pantalla = 320x240 exactos).
const ESP32_BG_W = 160;
const ESP32_BG_H = 120;

function rgbToHex(r, g, b) {
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

function applyAccentColor(r, g, b) {
  // Solo los elementos propios de Estudio (anillo del pomodoro, hoy en el calendario):
  // el acento del sistema de diseño no cambia para no romper el contraste.
  const root = document.documentElement.style;
  root.setProperty("--estudio-accent", rgbToHex(r, g, b));
  root.setProperty("--estudio-accent-soft", `rgba(${r}, ${g}, ${b}, 0.18)`);
}

// Mismo algoritmo que usa el ESP32 (spotify_screen.cpp) para calcular
// el color "complementario" a partir del acento: rota el tono 180
// grados y ajusta saturacion/brillo minimos para que siempre se vea
// bien sobre fondo oscuro. Lo replicamos aqui para que el color que
// ves en la web y el que se pinta en el ESP32 sean coherentes.
function rgbToHsv(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  const d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  const s = max === 0 ? 0 : d / max;
  return { h, s, v: max };
}

function hsvToRgb(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let rf, gf, bf;
  if (h < 60) { rf = c; gf = x; bf = 0; }
  else if (h < 120) { rf = x; gf = c; bf = 0; }
  else if (h < 180) { rf = 0; gf = c; bf = x; }
  else if (h < 240) { rf = 0; gf = x; bf = c; }
  else if (h < 300) { rf = x; gf = 0; bf = c; }
  else { rf = c; gf = 0; bf = x; }
  return {
    r: Math.round((rf + m) * 255),
    g: Math.round((gf + m) * 255),
    b: Math.round((bf + m) * 255),
  };
}

function computeComplementary(r, g, b) {
  let { h, s, v } = rgbToHsv(r, g, b);
  h = (h + 180) % 360;
  if (s < 0.45) s = 0.65;
  if (v < 0.55) v = 0.85;
  return hsvToRgb(h, s, v);
}

function extractDominantColor(imgDataUrl, callback) {
  const canvas = document.getElementById("colorCanvas");
  const ctx = canvas.getContext("2d");
  const img = new Image();
  img.onload = () => {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
    let r = 0, g = 0, b = 0, count = 0;
    for (let i = 0; i < data.length; i += 4) {
      r += data[i]; g += data[i + 1]; b += data[i + 2];
      count++;
    }
    callback({ r: Math.round(r / count), g: Math.round(g / count), b: Math.round(b / count) });
  };
  img.onerror = () => showToast("No se pudo leer la imagen", true);
  img.src = imgDataUrl;
}

function applyTheme(imageDataUrl, accent) {
  const bgLayer = document.getElementById("bgLayer");
  if (bgLayer) bgLayer.style.backgroundImage = imageDataUrl ? `url(${imageDataUrl})` : "";
  const preview = document.getElementById("themePreview");
  if (preview) preview.style.backgroundImage = imageDataUrl ? `url(${imageDataUrl})` : "";
  applyAccentColor(accent.r, accent.g, accent.b);
}

function saveTheme(imageDataUrl, accent) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify({ image: imageDataUrl, accent }));
  } catch (e) {
    console.warn("No se pudo guardar el tema:", e);
  }
}

function loadSavedTheme() {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (!raw) return;
    const saved = JSON.parse(raw);
    applyTheme(saved.image || null, saved.accent || DEFAULT_ACCENT);
  } catch (e) {
    console.warn("No se pudo cargar el tema guardado:", e);
  }
}

// ---------------------------------------------------------------------
// Envio del fondo al ESP32: convierte la imagen a 160x120 RGB565 y la
// manda como frame binario por el mismo WebSocket que ya usamos para
// todo lo demas (pomodoro, calendario, tareas). El firmware distingue
// este frame del de la caratula de Spotify por su tamaño (38404 bytes
// vs 9604 bytes de Spotify), asi que no hace falta ningun protocolo
// especial: basta con mandarlo con las dimensiones correctas.
// ---------------------------------------------------------------------
function sendBackgroundImageToEsp32(imgDataUrl) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  const canvas = document.createElement("canvas");
  canvas.width = ESP32_BG_W;
  canvas.height = ESP32_BG_H;
  const ctx = canvas.getContext("2d");
  const img = new Image();
  img.onload = () => {
    ctx.drawImage(img, 0, 0, ESP32_BG_W, ESP32_BG_H);
    const pixels = ctx.getImageData(0, 0, ESP32_BG_W, ESP32_BG_H).data;

    const bodyBytes = ESP32_BG_W * ESP32_BG_H * 2;
    const frame = new Uint8Array(4 + bodyBytes);
    // Cabecera: ancho y alto en big-endian (igual que espera el ESP32)
    frame[0] = (ESP32_BG_W >> 8) & 0xff;
    frame[1] = ESP32_BG_W & 0xff;
    frame[2] = (ESP32_BG_H >> 8) & 0xff;
    frame[3] = ESP32_BG_H & 0xff;

    let offset = 4;
    for (let i = 0; i < pixels.length; i += 4) {
      const r = pixels[i], g = pixels[i + 1], b = pixels[i + 2];
      const rgb565 = ((r & 0xf8) << 8) | ((g & 0xfc) << 3) | (b >> 3);
      frame[offset++] = (rgb565 >> 8) & 0xff;
      frame[offset++] = rgb565 & 0xff;
    }

    ws.send(frame.buffer);
  };
  img.src = imgDataUrl;
}

function sendAccentToEsp32(accent) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const comp = computeComplementary(accent.r, accent.g, accent.b);
  send({
    type: "background_set_manual_accent",
    accent: rgbToHex(accent.r, accent.g, accent.b),
    complementary: rgbToHex(comp.r, comp.g, comp.b),
  });
}

function resetBackgroundOnEsp32() {
  send({ type: "background_reset" });
}

function initThemeUi() {
  const btnOpen = document.getElementById("btnOpenTheme");
  const modal = document.getElementById("themeModal");
  const fileInput = document.getElementById("themeImageInput");
  const btnReset = document.getElementById("btnResetTheme");
  if (!btnOpen || !modal) return;

  btnOpen.addEventListener("click", () => openModal(modal));

  fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const dataUrl = ev.target.result;
      extractDominantColor(dataUrl, (accent) => {
        applyTheme(dataUrl, accent);
        saveTheme(dataUrl, accent);
        sendBackgroundImageToEsp32(dataUrl);
        sendAccentToEsp32(accent);
        showToast("Fondo actualizado (navegador + ESP32)");
      });
    };
    reader.readAsDataURL(file);
  });

  btnReset.addEventListener("click", () => {
    try { localStorage.removeItem(THEME_STORAGE_KEY); } catch {}
    applyTheme(null, DEFAULT_ACCENT);
    fileInput.value = "";
    resetBackgroundOnEsp32();
    showToast("Fondo restaurado por defecto (navegador + ESP32)");
  });
}


// ---------------------------------------------------------------------
// Confirmación / aviso: usan los diálogos y toasts comunes (ui.js)
// ---------------------------------------------------------------------
function showConfirm(message, onConfirm, okLabel = "Eliminar") {
  uiConfirm(message, "", { confirmLabel: okLabel, danger: /eliminar/i.test(okLabel) }).then((ok) => { if (ok) onConfirm(); });
}
function showToast(message, isError = false) {
  toast(message, { type: isError ? "error" : "success" });
}

// ---------------------------------------------------------------------
// Conexion WebSocket (por el puente /estudio/ws del panel)
// ---------------------------------------------------------------------
// Pocos intentos con espera creciente; después se para y queda «Sin conexión» con el
// botón «Reintentar» (el servidor hace lo mismo con sus puentes: estudio/esp32_link.py).
const RETRY_DELAYS = [3000, 6000, 12000];
let failures = 0;
let retryTimer = null;

async function initConnection({ manual = false } = {}) {
  clearTimeout(retryTimer);
  setConnStatus("checking");
  let status;
  try {
    status = manual
      ? await api("/estudio/api/esp32/retry", { method: "POST", quiet: true })
      : await api("/estudio/api/esp32-status", { quiet: true });
  } catch {
    status = { online: false };
  }
  if (status.host === "") { setConnStatus(false); return; }  // sin placa configurada no hay nada que reintentar
  if (!status.online) { scheduleRetry(); return; }
  esp32WsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${status.ws_path || "/estudio/ws"}`;
  connect();
}

function scheduleRetry() {
  clearTimeout(retryTimer);
  failures++;
  if (failures > RETRY_DELAYS.length) { setConnStatus(false); return; }  // se para aquí
  setConnStatus("checking");
  retryTimer = setTimeout(initConnection, RETRY_DELAYS[failures - 1]);
}

function connect() {
  ws = new WebSocket(esp32WsUrl);
  let opened = false;
  ws.onopen = () => { opened = true; failures = 0; setConnStatus(true); send({ type: "get_state" }); };
  // Si se cae una conexión que funcionaba, se vuelve a contar desde cero
  ws.onclose = () => { ws = null; if (opened) failures = 0; scheduleRetry(); };
  ws.onerror = () => ws && ws.close();
  ws.onmessage = (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    handleMessage(data);
  };
}
document.getElementById("btnRetry").addEventListener("click", () => { failures = 0; initConnection({ manual: true }); });

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function setConnStatus(online) {
  const el = document.getElementById("connStatus");
  el.dataset.online = String(online);
  el.querySelector(".conn-label").textContent = online === "checking"
    ? (failures ? `Reintentando (${failures} de ${RETRY_DELAYS.length})…` : "Conectando con el ESP32…")
    : online ? "ESP32 conectado" : "Sin conexión";
  document.getElementById("offlineNotice").hidden = online !== false;
  document.querySelector(".estudio-grid").classList.toggle("is-offline", online === false);
}

function handleMessage(data) {
  switch (data.type) {
    case "pomodoro_state": return onPomodoroState(data);
    case "calendar_list": return onCalendarList(data.events || []);
    case "checklist_categories": return onChecklistCategories(data.categories || []);
    case "checklist_items": return onChecklistItems(data);
    case "review_state": return onReviewState(data);
    case "error": return showToast(data.message || "Ha ocurrido un error", true);
    default: return;
  }
}

function bindDebounced(elOrId, handler, delayMs = 300) {
  const el = typeof elOrId === "string" ? document.getElementById(elOrId) : elOrId;
  if (!el) return;
  let locked = false;
  el.addEventListener("click", () => {
    if (locked) return;
    locked = true;
    try { handler(); } finally { setTimeout(() => { locked = false; }, delayMs); }
  });
}


// =====================================================================
// POMODORO
// =====================================================================
/* Esfera del pomodoro: el anillo es el tiempo que queda y se dibuja en cada cuadro mientras corre (sin saltos de
   segundo en segundo); al empezar se llena de luz, al pausar respira una vez, al parar se vacía; los dígitos ruedan.
   El estado manda la placa (pomodoro_state); aquí solo se anima. Con movimiento reducido, todo al instante. */
const Pomo = (() => {
  const $p = (id) => document.getElementById(id);
  const quieto = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const ring = $p("pomoRing"), arc = $p("pomoArc"), glow = $p("pomoGlow"), head = $p("pomoHead"), btn = $p("btnPomoStartPause");
  const timeEl = $p("pomoTimeDisplay");
  // 60 marcas por dentro del anillo; una de cada cinco, más larga
  const ticks = [];
  const NS = "http://www.w3.org/2000/svg";
  for (let i = 0; i < 60; i++) {
    const a = (i / 60) * Math.PI * 2 - Math.PI / 2, largo = i % 5 === 0;
    const l = document.createElementNS(NS, "line");
    const r1 = largo ? 74 : 78, r2 = 82;
    l.setAttribute("x1", (110 + Math.cos(a) * r1).toFixed(2)); l.setAttribute("y1", (110 + Math.sin(a) * r1).toFixed(2));
    l.setAttribute("x2", (110 + Math.cos(a) * r2).toFixed(2)); l.setAttribute("y2", (110 + Math.sin(a) * r2).toFixed(2));
    if (largo) l.classList.add("is-long");
    $p("pomoTicks").appendChild(l);
    ticks.push(l);
  }
  // Dígitos «mm:ss» como tiras que ruedan
  timeEl.innerHTML = '<span class="pomo-dig"><span>2</span></span><span class="pomo-dig"><span>5</span></span><span class="pomo-colon">:</span><span class="pomo-dig"><span>0</span></span><span class="pomo-dig"><span>0</span></span>';
  const digs = [...timeEl.querySelectorAll(".pomo-dig")];
  let mostrados = "2500";
  function digitos(txt) {
    if (txt === mostrados) return;
    digs.forEach((d, i) => {
      if (txt[i] === mostrados[i]) return;
      if (quieto()) { d.innerHTML = `<span>${txt[i]}</span>`; return; }
      d.classList.remove("is-rolling");
      d.innerHTML = `<span>${mostrados[i]}</span><span>${txt[i]}</span>`;
      void d.offsetWidth;  // reinicia la animación aunque ya estuviera rodando
      d.classList.add("is-rolling");
    });
    mostrados = txt;
    timeEl.setAttribute("aria-label", `${txt.slice(0, 2)}:${txt.slice(2)}`);
  }
  timeEl.addEventListener("animationend", (e) => {
    const d = e.target.closest(".pomo-dig");
    if (d?.classList.contains("is-rolling")) { d.classList.remove("is-rolling"); d.innerHTML = `<span>${d.lastElementChild.textContent}</span>`; }
  });
  // Lo animable: cuánto anillo se ve encendido (show) y cuánto brilla (glow)
  const vis = { show: 0, glow: 0 };
  const anims = new Map();
  function tween(key, to, ms, ease = (t) => 1 - Math.pow(1 - t, 3)) {
    if (quieto() || !ms) { vis[key] = to; anims.delete(key); pedir(); return; }
    anims.set(key, { from: vis[key], to, t0: performance.now(), ms, ease });
    pedir();
  }
  function restante(now = Date.now()) {
    const p = state.pomodoro;
    return p.runState === "running" ? Math.max(0, p.remainingSec - (now - p.lastSync) / 1000) : p.remainingSec;
  }
  function dibujar() {
    const p = state.pomodoro;
    const total = (p.phase === "work" ? p.workMin : p.breakMin) * 60;
    const rem = restante();
    const frac = total > 0 ? Math.max(0, Math.min(1, rem / total)) : 0;
    const v = frac * vis.show;
    arc.style.opacity = v < 0.003 ? "0" : "1";  // un trazo vacío con extremos redondos aún pintaría un punto
    arc.style.strokeDasharray = `${v.toFixed(4)} 1`;
    glow.style.strokeDasharray = `${v.toFixed(4)} 1`;
    glow.style.opacity = v < 0.003 ? "0" : (vis.glow * 0.5).toFixed(3);
    const largo = Math.min(0.05, v);
    head.style.strokeDasharray = `${largo.toFixed(4)} 1`;
    head.style.strokeDashoffset = (-(v - largo)).toFixed(4);
    head.style.opacity = (v > 0.002 ? Math.min(1, vis.glow) * 0.9 : 0).toFixed(3);
    const lit = vis.glow > 0.2 && v > 0.01 ? Math.round(v * 60) % 60 : -1;
    ticks.forEach((t, i) => t.classList.toggle("is-lit", i === lit));
    // La cuenta atrás enseña el segundo en el que está: 25:00 hasta que pasa uno entero
    const s = rem > 0 ? Math.ceil(rem - 1e-6) : 0;
    digitos(String(Math.floor(s / 60)).padStart(2, "0").slice(-2) + String(s % 60).padStart(2, "0"));
    ring.dataset.phase = p.phase;
    $p("pomoPhaseLabel").textContent = p.phase === "work" ? "Trabajo" : "Descanso";
  }
  let raf = 0;
  function cuadro(now) {
    raf = 0;
    for (const [k, a] of anims) {
      const t = Math.min(1, (now - a.t0) / a.ms);
      vis[k] = a.from + (a.to - a.from) * a.ease(t);
      if (t >= 1) anims.delete(k);
    }
    dibujar();
    if (anims.size || (state.pomodoro.runState === "running" && !document.hidden)) pedir();
  }
  function pedir() { if (!raf) raf = requestAnimationFrame(cuadro); }
  document.addEventListener("visibilitychange", pedir);
  setInterval(pedir, 1000);  // pestaña en segundo plano: al menos el número al día

  let antes = null;
  function estado(nuevo) {
    const de = antes;
    antes = nuevo;
    btn.classList.toggle("is-running", nuevo === "running");
    btn.querySelector(".pomo-label").textContent = nuevo === "running" ? "Pausar" : nuevo === "paused" ? "Seguir" : "Iniciar";
    ring.classList.toggle("is-paused", nuevo === "paused");
    if (de === null) {  // primera noticia de la placa: tal cual, sin animar
      vis.show = nuevo === "stopped" ? 0 : 1;
      vis.glow = nuevo === "running" ? 1 : nuevo === "paused" ? 0.35 : 0;
      return pedir();
    }
    if (de === nuevo) return pedir();
    if (nuevo === "running") {
      if (de === "stopped") { tween("show", 1, 900, (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)); }
      else vis.show = 1;
      tween("glow", 1, 500);
      if (de === "stopped" && !quieto()) ring.animate([{ transform: "scale(0.985)" }, { transform: "scale(1.012)" }, { transform: "none" }], { duration: 700, easing: "cubic-bezier(0.16, 1, 0.3, 1)" });
    } else if (nuevo === "paused") {
      // Respira una vez y se queda quieto: nunca en bucle
      if (!quieto()) ring.animate([{ transform: "none" }, { transform: "scale(1.025)" }, { transform: "none" }], { duration: 1400, easing: "ease-in-out" });
      tween("glow", 0.35, 900);
    } else {
      tween("show", 0, 700);
      tween("glow", 0, 500);
    }
  }
  return { estado, pedir };
})();

function onPomodoroState(data) {
  state.pomodoro = {
    workMin: data.work_min, breakMin: data.break_min, phase: data.phase,
    runState: data.run_state, remainingSec: data.remaining_sec, lastSync: Date.now(),
  };
  document.getElementById("workMinLabel").textContent = data.work_min;
  document.getElementById("breakMinLabel").textContent = data.break_min;
  Pomo.estado(data.run_state);
}

function renderPomodoro() { Pomo.pedir(); }

bindDebounced("btnPomoStartPause", () => send({ type: "pomodoro_cmd", action: "start_pause" }));
bindDebounced("btnPomoReset", () => send({ type: "pomodoro_cmd", action: "reset" }));

document.querySelectorAll(".btn-step").forEach((btn) => {
  bindDebounced(btn, () => {
    const target = btn.dataset.target;
    const delta = parseInt(btn.dataset.delta, 10);
    let w = state.pomodoro.workMin, b = state.pomodoro.breakMin;
    if (target === "work") w = Math.max(1, w + delta);
    else b = Math.max(1, b + delta);
    send({ type: "pomodoro_set", work_min: w, break_min: b });
  }, 250);
});

// =====================================================================
// CALENDARIO: es el del Panel (static/js/calendar.js), que sincroniza con el ESP32 en los dos
// sentidos (estudio/calendar_sync.py). La lista que manda el ESP32 ya no se pinta aquí.
// =====================================================================
function onCalendarList() {}
if (window.Calendar) {
  // en Estudio cuentan los exámenes, entregas y tareas con fecha; las rutinas tienen su sitio en Tareas y Hoy
  Calendar.mount(document.getElementById("estCalendar"), { view: "month", compact: true, hide: ["routine"] });
  Calendar.mount(document.getElementById("estAgenda"), { view: "agenda", compact: true, days: 14, hide: ["routine"] });
}

// ── Notas de repaso en el reloj (se guarda en el ESP32) ──
const reviewToggle = document.getElementById("reviewAutoToggle");
function onReviewState(data) {
  reviewToggle.checked = data.enabled !== false;
  reviewToggle.disabled = false;
}
reviewToggle.addEventListener("change", () => {
  send({ type: "review_set", enabled: reviewToggle.checked });
  showToast(reviewToggle.checked ? "Las notas volverán a salir en el reloj" : "Las notas ya no saldrán solas en el reloj");
});

// =====================================================================
// TAREAS
// =====================================================================
function onChecklistCategories(categories) {
  state.tasks.categories = categories;
  renderCategories();
}

function onChecklistItems(data) {
  state.tasks.itemsByCategory[data.category] = data.items || [];
  if (state.tasks.openCategories.has(data.category)) {
    renderCategoryItems(data.category);
  }
}

function renderCategories() {
  const container = document.getElementById("categoriesContainer");
  container.innerHTML = "";

  if (state.tasks.categories === null) {
    container.innerHTML = stateView({ kind: "offline", title: "Esperando al ESP32", text: "Las categorías y tareas viven en la placa: aparecerán en cuanto se conecte.", compact: true });
    return;
  }
  if (state.tasks.categories.length === 0) {
    container.innerHTML = emptyState({ iconName: "list-checks", title: "Sin categorías", text: "Crea una arriba para organizar las tareas que ves en el ESP32.", compact: true });
    return;
  }

  state.tasks.categories.forEach((cat) => {
    const block = document.createElement("div");
    block.className = "category-block";
    const open = state.tasks.openCategories.has(cat.name);
    block.innerHTML = `
      <div class="category-header">
        <button type="button" class="category-toggle" data-cat="${escapeHtml(cat.name)}" aria-expanded="${open}">
          ${icon("chevron-down", "icon-sm chev")}<span class="cat-name">${escapeHtml(cat.name)}</span>
          <span class="badge">${cat.done}/${cat.total}</span>
        </button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm btn-del-cat" data-cat="${escapeHtml(cat.name)}" aria-label="Eliminar categoría ${escapeHtml(cat.name)}">${icon("trash-2", "icon-sm")}</button>
      </div>
      <div class="category-items" id="cat-items-${cssEscape(cat.name)}"></div>
    `;
    container.appendChild(block);
  });

  container.querySelectorAll(".category-toggle").forEach((header) => {
    header.addEventListener("click", () => toggleCategory(header.dataset.cat));
  });
  container.querySelectorAll(".btn-del-cat").forEach((btn) => {
    bindDebounced(btn, () => {
      showConfirm(`¿Eliminar la categoria "${btn.dataset.cat}" y todas sus tareas?`, () => {
        send({ type: "checklist_delete_category", name: btn.dataset.cat });
        state.tasks.openCategories.delete(btn.dataset.cat);
        showToast("Categoria eliminada");
      });
    });
  });

  state.tasks.openCategories.forEach((name) => {
    const el = document.getElementById(`cat-items-${cssEscape(name)}`);
    if (el) { el.classList.add("open"); renderCategoryItems(name); }
  });
}

function cssEscape(str) {
  return str.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function toggleCategory(name) {
  const el = document.getElementById(`cat-items-${cssEscape(name)}`);
  if (!el) return;
  if (state.tasks.openCategories.has(name)) {
    state.tasks.openCategories.delete(name);
    el.classList.remove("open");
    el.previousElementSibling.querySelector(".category-toggle").setAttribute("aria-expanded", "false");
  } else {
    state.tasks.openCategories.add(name);
    el.classList.add("open");
    el.previousElementSibling.querySelector(".category-toggle").setAttribute("aria-expanded", "true");
    send({ type: "checklist_get_items", category: name });
    renderCategoryItems(name);
  }
}

function renderCategoryItems(categoryName) {
  const el = document.getElementById(`cat-items-${cssEscape(categoryName)}`);
  if (!el) return;
  const items = state.tasks.itemsByCategory[categoryName] || [];
  const editing = state.tasks.editingItem;
  const isEditingHere = editing && editing.category === categoryName;

  let rowsHtml = "";
  if (items.length === 0) {
    rowsHtml = "<p class='small muted task-empty'>Sin tareas todavía.</p>";
  } else {
    rowsHtml = items.map((item, idx) => `
      <div class="task-row">
        <label class="check-hit"><input type="checkbox" ${item.done ? "checked" : ""} class="checkbox chk-item" data-cat="${escapeHtml(categoryName)}" data-idx="${idx}" data-id="${item.id || 0}" aria-label="${escapeHtml(item.text)}"></label>
        <span class="task-text ${item.done ? "done" : ""}">${escapeHtml(item.text)}</span>
        ${item.daily ? '<span class="tag">Diaria</span>' : ""}
        <button type="button" class="btn btn-ghost btn-icon btn-sm btn-edit-item" data-cat="${escapeHtml(categoryName)}" data-idx="${idx}" aria-label="Editar">${icon("pencil", "icon-sm")}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm btn-del-item" data-cat="${escapeHtml(categoryName)}" data-idx="${idx}" data-id="${item.id || 0}" aria-label="Eliminar">${icon("trash-2", "icon-sm")}</button>
      </div>
    `).join("");
  }

  const editItem = isEditingHere ? items[editing.index] : null;
  const formHtml = `
    <form class="add-item-form" data-cat="${escapeHtml(categoryName)}">
      <input type="text" class="input input-sm new-item-text" maxlength="60" aria-label="${isEditingHere ? "Editar tarea" : "Nueva tarea"}" placeholder="${isEditingHere ? "Editar tarea…" : "Nueva tarea…"}"
             value="${isEditingHere && editItem ? escapeHtml(editItem.text) : ""}" required>
      <label class="row small"><input type="checkbox" class="checkbox new-item-daily" ${isEditingHere && editItem && editItem.daily ? "checked" : ""}>Diaria</label>
      <button type="submit" class="btn btn-tinted btn-sm">${isEditingHere ? "Guardar" : "Añadir"}</button>
      ${isEditingHere ? `<button type="button" class="btn btn-sm btn-cancel-edit">Cancelar</button>` : ""}
    </form>
  `;

  el.innerHTML = rowsHtml + formHtml;

  el.querySelectorAll(".chk-item").forEach((chk) => {
    let locked = false;
    chk.addEventListener("change", () => {
      if (locked) return;
      locked = true;
      send({ type: "checklist_toggle_item", category: chk.dataset.cat, id: parseInt(chk.dataset.id, 10) || 0, index: parseInt(chk.dataset.idx, 10) });
      setTimeout(() => { locked = false; }, 300);
    });
  });

  el.querySelectorAll(".btn-del-item").forEach((btn) => {
    bindDebounced(btn, () => {
      showConfirm("¿Eliminar esta tarea?", () => {
        send({ type: "checklist_delete_item", category: btn.dataset.cat, id: parseInt(btn.dataset.id, 10) || 0, index: parseInt(btn.dataset.idx, 10) });
        showToast("Tarea eliminada");
      });
    });
  });

  el.querySelectorAll(".btn-edit-item").forEach((btn) => {
    bindDebounced(btn, () => {
      state.tasks.editingItem = { category: btn.dataset.cat, index: parseInt(btn.dataset.idx, 10) };
      renderCategoryItems(btn.dataset.cat);
    });
  });

  const cancelBtn = el.querySelector(".btn-cancel-edit");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      state.tasks.editingItem = null;
      renderCategoryItems(categoryName);
    });
  }

  const form = el.querySelector(".add-item-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = form.querySelector(".new-item-text").value.trim();
      const daily = form.querySelector(".new-item-daily").checked;
      if (!text) return;

      if (isEditingHere) {
        send({ type: "checklist_edit_item", category: categoryName, id: (editItem && editItem.id) || 0, index: editing.index, text, daily });
        state.tasks.editingItem = null;
        showToast("Tarea actualizada");
      } else {
        send({ type: "checklist_add_item", category: categoryName, text, daily });
        showToast("Tarea añadida");
      }
    });
  }
}

document.getElementById("newCategoryForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = document.getElementById("newCategoryName");
  const name = input.value.trim();
  if (!name) return;
  send({ type: "checklist_add_category", name });
  input.value = "";
  showToast("Categoría creada");
});

window.addEventListener('dragover', (e) => {
    e.preventDefault();
});

window.addEventListener('drop', (e) => {
    e.preventDefault();
});

// ---------------------------------------------------------------------
renderCategories();
loadSavedTheme();
initThemeUi();
initConnection();
