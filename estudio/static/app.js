// =====================================================================
// Panel de Estudio - pagina web unica
// NOTA: esta app vive montada bajo "/estudio" dentro del proceso
// fusionado con el Cerebro Digital, por eso "/config" se pide con el
// prefijo completo. El resto de comunicacion (WebSocket) va directo
// al ESP32, no pasa por este prefijo.
// =====================================================================

let ws = null;
let esp32WsUrl = null;


const state = {
  pomodoro: { workMin: 25, breakMin: 5, phase: "work", runState: "stopped", remainingSec: 25 * 60, lastSync: 0 },
  tasks: {
    categories: [],
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

function shadeColor(r, g, b, factor) {
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
  return rgbToHex(clamp(r * factor), clamp(g * factor), clamp(b * factor));
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
// Conexion WebSocket (directa al ESP32, no pasa por "/estudio")
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
  esp32WsUrl = status.esp32_ws_url;
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
function onPomodoroState(data) {
  state.pomodoro = {
    workMin: data.work_min, breakMin: data.break_min, phase: data.phase,
    runState: data.run_state, remainingSec: data.remaining_sec, lastSync: Date.now(),
  };
  document.getElementById("workMinLabel").textContent = data.work_min;
  document.getElementById("breakMinLabel").textContent = data.break_min;
  document.getElementById("btnPomoStartPause").innerHTML =
    data.run_state === "running" ? icon("pause") + "Pausar" : icon("play") + "Iniciar";
  renderPomodoro();
}

function renderPomodoro() {
  const p = state.pomodoro;
  let remaining = p.remainingSec;
  if (p.runState === "running") {
    remaining = Math.max(0, p.remainingSec - Math.floor((Date.now() - p.lastSync) / 1000));
  }
  const totalSec = (p.phase === "work" ? p.workMin : p.breakMin) * 60;
  const elapsed = totalSec - remaining;
  const pct = totalSec > 0 ? Math.min(100, (elapsed / totalSec) * 100) : 0;
  const ring = document.getElementById("pomoRing");
  ring.style.setProperty("--pct", pct + "%");
  ring.dataset.phase = p.phase;

  const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss = String(remaining % 60).padStart(2, "0");
  document.getElementById("pomoTimeDisplay").textContent = `${mm}:${ss}`;
  document.getElementById("pomoPhaseLabel").textContent = p.phase === "work" ? "Trabajo" : "Descanso";
}
setInterval(renderPomodoro, 1000);

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
