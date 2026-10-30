/* =====================================================================
   Comidas: plan semanal (varios platos por comida), platos, compra,
   ingredientes y objetivos. Depende de ui.js.
   ===================================================================== */
const API = '/comidas/api';
const $ = (id) => document.getElementById(id);

const DIAS = [
  { key: 'lunes', label: 'Lun', full: 'Lunes' }, { key: 'martes', label: 'Mar', full: 'Martes' },
  { key: 'miercoles', label: 'Mié', full: 'Miércoles' }, { key: 'jueves', label: 'Jue', full: 'Jueves' },
  { key: 'viernes', label: 'Vie', full: 'Viernes' }, { key: 'sabado', label: 'Sáb', full: 'Sábado' },
  { key: 'domingo', label: 'Dom', full: 'Domingo' },
];
// Franjas de los platos del catálogo (fijas) y comidas del día en el plan (las de la tabla
// `franjas`: desayuno, comida, merienda, cena, extras y las tuyas)
const PLATO_FRANJAS = [
  { key: 'desayuno', label: 'Desayuno', icon: 'coffee' }, { key: 'comida', label: 'Comida', icon: 'utensils-crossed' },
  { key: 'merienda', label: 'Merienda', icon: 'apple' }, { key: 'cena', label: 'Cena', icon: 'moon' },
];
const FRANJA_ICONS = { desayuno: 'coffee', comida: 'utensils-crossed', merienda: 'apple', cena: 'moon', extras: 'cookie' };
let FRANJAS = PLATO_FRANJAS.map(f => ({ ...f, catalogo: f.key }));
let FRANJA_LABEL = Object.fromEntries(PLATO_FRANJAS.map(f => [f.key, f.label]));
let allFranjas = [];
function setFranjas(list) {
  if (!list?.length) return;
  allFranjas = list;
  FRANJAS = list.filter(f => f.activa).map(f => ({ key: f.clave, label: f.nombre, icon: FRANJA_ICONS[f.clave] || 'clock', catalogo: f.catalogo || f.clave, fraccion: f.fraccion, hora: f.hora, dias: f.dias || null }));
  FRANJA_LABEL = { ...Object.fromEntries(PLATO_FRANJAS.map(f => [f.key, f.label])), ...Object.fromEntries(list.map(f => [f.clave, f.nombre])) };
}
const ROLES = [['primero', 'Primero', '1.º'], ['segundo', 'Segundo', '2.º'], ['guarnicion', 'Guarnición', 'Guarn.'], ['postre', 'Postre', 'Postre'], ['bebida', 'Bebida', 'Bebida'], ['unico', 'Plato único', 'Único']];
const ROL_CORTO = Object.fromEntries(ROLES.map(([k, , c]) => [k, c]));
const CAT_LABELS = { proteina: 'Proteína', verdura: 'Verdura', fruta: 'Fruta', cereal: 'Cereal', lacteo: 'Lácteo', grasa: 'Grasa', legumbre: 'Legumbre', General: 'General' };
const MACROS = [
  { key: 'kcal', label: 'Energía', unit: 'kcal' }, { key: 'proteinas', label: 'Proteína', unit: 'g' },
  { key: 'carbohidratos', label: 'Hidratos', unit: 'g' }, { key: 'grasas', label: 'Grasa', unit: 'g' },
  { key: 'azucares', label: 'Azúcares', unit: 'g', max: true }, { key: 'sal', label: 'Sal', unit: 'g', max: true },
];

let currentWeekMonday = getMonday(new Date());
let plannerMode = 4;
let selectedDia = todayKey();
let planState = null;
let allMeals = [];
let allIngredients = [];
let mealFranjaFilter = '';
let ingCatFilter = '';
let ingOnlyIssues = false;
let assignTarget = null;
let profile = null;

/* ---------- Utilidades ---------- */
function getMonday(d) {
  d = new Date(d);
  const day = d.getDay();
  d.setDate(d.getDate() + (day === 0 ? -6 : 1 - day));
  d.setHours(0, 0, 0, 0);
  return d;
}
function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function todayKey() { return DIAS[(new Date().getDay() + 6) % 7].key; }
function isThisWeek() { return getMonday(new Date()).getTime() === currentWeekMonday.getTime(); }
const semana = () => fmtDate(currentWeekMonday);
const num = (v, d = 0) => Number(v || 0).toLocaleString('es-ES', { maximumFractionDigits: d, minimumFractionDigits: 0 });
// ¿Está quitada esta franja ese día? (franjas.dias: null = todos los días)
const franjaOff = (franja, dia) => { const f = allFranjas.find(x => x.clave === franja); return !!(f?.dias && !f.dias.includes(dia)); };
async function setFranjaDia(franja, dia, on) {
  const f = allFranjas.find(x => x.clave === franja);
  if (!f) return;
  const now = f.dias || DIAS.map(d => d.key);
  const dias = on ? DIAS.map(d => d.key).filter(k => now.includes(k) || k === dia) : now.filter(k => k !== dia);
  await api(`${API}/franjas/${franja}`, { method: 'PATCH', body: { dias } });
  const nombre = FRANJA_LABEL[franja] || franja, diaTxt = DIAS.find(d => d.key === dia)?.full.toLowerCase();
  toast(on ? `${nombre} vuelve el ${diaTxt}` : `Sin ${nombre.toLowerCase()} el ${diaTxt}`, {
    type: 'info', action: { label: 'Deshacer', onClick: () => setFranjaDia(franja, dia, !on) } });
  await loadFranjas();
  loadPlan();
}
const franjasActivas = () => plannerMode === 4 ? FRANJAS : FRANJAS.filter(f => f.key === 'comida' || f.key === 'cena');
const conArticulo = (key) => ({ desayuno: 'al desayuno', comida: 'a la comida', merienda: 'a la merienda', cena: 'a la cena', extras: 'a los extras' }[key] || `a «${FRANJA_LABEL[key] || key}»`);

function thumbHtml(meal, cls = '') {
  const img = meal.image_url && meal.image_url.startsWith('/static/') ? meal.image_url : '';
  return img ? `<img class="thumb ${cls}" src="${escapeHtml(img)}" alt="" loading="lazy" decoding="async">`
             : `<span class="thumb thumb-icon ${cls}" data-franja="${meal.franja}">${icon(FRANJA_ICONS[meal.franja] || 'utensils-crossed')}</span>`;
}

function meterClass(pct, isMax) {
  if (isMax) return pct > 115 ? 'over' : pct > 100 ? 'warn' : 'ok';
  return pct > 115 ? 'over' : pct >= 85 ? 'ok' : pct >= 50 ? 'warn' : '';
}
function meterRow(m, value, target) {
  const pct = target ? Math.round(value / target * 100) : 0;
  return `<div class="meter-row">
    <span class="meter-label">${m.label}</span>
    <div class="meter ${meterClass(pct, m.max)}" role="progressbar" aria-label="${m.label}" aria-valuenow="${Math.round(value)}" aria-valuemin="0" aria-valuemax="${Math.round(target || 0)}"><span style="width:${Math.min(pct, 100)}%"></span></div>
    <span class="meter-value tabular"><b>${num(value, m.unit === 'g' && value < 10 ? 1 : 0)}</b> / ${num(target)} ${m.unit}</span>
  </div>`;
}

/* ---------- Pestañas ---------- */
function switchTab(tab) {
  document.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === tab)));
  document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.id !== 'tab-' + tab; });
  try { localStorage.setItem('comidas_tab', tab); } catch {}
  if (tab === 'compra') loadShoppingList();
  if (tab === 'objetivos') { renderGoals(); loadBody(); loadFranjas(); }
}
document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => switchTab(b.dataset.tab)));

/* =====================================================================
   PLAN
   ===================================================================== */
document.querySelectorAll('[data-mode]').forEach(b => b.addEventListener('click', () => {
  plannerMode = parseInt(b.dataset.mode, 10);
  document.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  try { localStorage.setItem('comidas_mode', String(plannerMode)); } catch {}
  renderPlan();
}));

function changeWeek(delta) {
  currentWeekMonday = new Date(currentWeekMonday.getTime() + delta * 86400000);
  currentWeekMonday = getMonday(currentWeekMonday);
  selectedDia = isThisWeek() ? todayKey() : 'lunes';
  loadPlan();
}
function goThisWeek() { currentWeekMonday = getMonday(new Date()); selectedDia = todayKey(); loadPlan(); }

function weekLabel() {
  const sunday = new Date(currentWeekMonday.getTime() + 6 * 86400000);
  const o = { day: 'numeric', month: 'short' };
  return `${currentWeekMonday.toLocaleDateString('es-ES', o)} – ${sunday.toLocaleDateString('es-ES', o)}`;
}

async function loadPlan() {
  $('weekLabel').textContent = weekLabel();
  $('btnThisWeek').hidden = isThisWeek();
  try {
    planState = await api(`${API}/weekly-plan/${semana()}/full`, { quiet: true });
    setFranjas(planState.franjas);
  } catch {
    $('dayPanel').innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudo cargar el plan', text: 'Revisa la conexión y recarga.', compact: true });
    return;
  }
  renderPlan();
  loadSuggestions();
}

function renderPlan() {
  if (!planState) return;
  renderDayStrip();
  renderGrid();
  renderDayPanel();
  renderWeekSummary();
}

function renderDayStrip() {
  const obj = planState.objetivo_dia.kcal;
  $('dayStrip').innerHTML = DIAS.map((d, i) => {
    const fecha = new Date(currentWeekMonday.getTime() + i * 86400000);
    const kcal = planState.dias[d.key].total.kcal;
    const pct = obj ? Math.min(Math.round(kcal / obj * 100), 100) : 0;
    const today = isThisWeek() && d.key === todayKey();
    return `<button type="button" class="day-chip${today ? ' is-today' : ''}" role="tab" data-dia="${d.key}" aria-selected="${d.key === selectedDia}">
      <span class="day-chip-label">${d.label}</span><span class="day-chip-num tabular">${fecha.getDate()}</span>
      <span class="day-chip-bar" aria-hidden="true"><span style="width:${pct}%"></span></span>
      <span class="sr-only">${num(kcal)} kcal</span></button>`;
  }).join('');
  $('dayStrip').querySelectorAll('[data-dia]').forEach(b => b.addEventListener('click', () => selectDay(b.dataset.dia)));
}

function selectDay(dia) {
  selectedDia = dia;
  renderDayStrip();
  document.querySelectorAll('.planner-head').forEach(h => h.setAttribute('aria-pressed', String(h.dataset.dia === dia)));
  renderDayPanel();
  loadSuggestions();
}

function renderGrid() {
  const grid = $('plannerGrid');
  const franjas = franjasActivas();
  const obj = planState.objetivo_dia.kcal;
  let html = '<div class="planner-corner"></div>';
  DIAS.forEach((d, i) => {
    const fecha = new Date(currentWeekMonday.getTime() + i * 86400000);
    const kcal = planState.dias[d.key].total.kcal;
    const pct = obj ? Math.round(kcal / obj * 100) : 0;
    const today = isThisWeek() && d.key === todayKey();
    html += `<button type="button" class="planner-head${today ? ' is-today' : ''}" data-dia="${d.key}" aria-pressed="${d.key === selectedDia}">
      <span class="ph-day">${d.label} <span class="tabular">${fecha.getDate()}</span></span>
      <span class="ph-kcal tabular">${kcal ? num(kcal) + ' kcal' : '—'}</span>
      <span class="meter ${meterClass(pct)}" aria-hidden="true"><span style="width:${Math.min(pct, 100)}%"></span></span></button>`;
  });
  franjas.forEach(f => {
    html += `<div class="planner-franja">${icon(f.icon, 'icon-sm')}<span>${f.label}</span></div>`;
    DIAS.forEach(d => {
      const slot = planState.dias[d.key].comidas[f.key];
      html += franjaOff(f.key, d.key) && !slot?.platos?.length
        ? `<div class="meal-cell is-off"><button type="button" class="cell-off" data-act="franja-on" data-dia="${d.key}" data-franja="${f.key}"
            aria-label="${escapeHtml(f.label)} quitada el ${d.full.toLowerCase()}: volver a ponerla"><span>Sin ${escapeHtml(f.label.toLowerCase())}</span><span class="cell-off-act">Poner</span></button></div>`
        : cellHtml(d.key, f.key, slot);
    });
  });
  grid.style.gridTemplateRows = `auto repeat(${franjas.length}, minmax(112px, auto))`;
  grid.innerHTML = html;
  grid.querySelectorAll('.planner-head').forEach(h => h.addEventListener('click', () => selectDay(h.dataset.dia)));
}

function cellHtml(dia, franja, slot) {
  const platos = slot?.platos || [];
  if (!platos.length) {
    return `<div class="meal-cell is-empty"><button type="button" class="cell-add" data-act="add" data-dia="${dia}" data-franja="${franja}" aria-label="Añadir plato: ${FRANJA_LABEL[franja]} del ${dia}">${icon('plus', 'icon-sm')}<span>Añadir</span></button>
      <button type="button" class="btn btn-ghost btn-icon btn-sm cell-off-btn" data-act="franja-off" data-dia="${dia}" data-franja="${franja}" aria-label="Quitar ${escapeHtml(FRANJA_LABEL[franja] || franja)} el ${dia}" title="Quitar esta comida este día">${icon('eye-off', 'icon-sm')}</button></div>`;
  }
  return `<div class="meal-cell${slot.is_fixed ? ' is-fixed' : ''}" data-plan="${slot.plan_id}">
    <ul class="cell-platos">${platos.map(p => `<li><button type="button" class="cell-plato" data-act="recipe" data-meal="${p.meal_id}">
      <span class="cp-name">${p.rol ? `<span class="rol-tag">${ROL_CORTO[p.rol]}</span>` : ''}${escapeHtml(p.nombre)}</span><span class="cp-meta tabular">${p.gramos} g · ${num(p.macros.kcal)} kcal</span></button></li>`).join('')}</ul>
    <div class="cell-foot">
      <span class="tiny subtle tabular">${platos.length > 1 ? num(slot.total.kcal) + ' kcal' : ''}${slot.is_fixed ? ` ${icon('pin', 'icon-sm')}` : ''}</span>
      <span class="grow"></span>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="add" data-dia="${dia}" data-franja="${franja}" aria-label="Añadir otro plato">${icon('plus', 'icon-sm')}</button>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="cell-menu" data-dia="${dia}" data-franja="${franja}" aria-label="Opciones de la comida" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>
    </div></div>`;
}

document.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el || !el.closest('#tab-plan, #dayPanel')) return;
  const { act, dia, franja } = el.dataset;
  if (act === 'add') openAssign(dia, franja);
  if (act === 'recipe') openRecipe(parseInt(el.dataset.meal, 10));
  if (act === 'cell-menu') openCellMenu(el, dia, franja);
  if (act === 'remove-plato') removePlato(el.dataset.kind, parseInt(el.dataset.plan, 10), el.dataset.item ? parseInt(el.dataset.item, 10) : null);
  if (act === 'suggest-add') addSuggestion(parseInt(el.dataset.meal, 10), parseFloat(el.dataset.gramos), el.dataset.franja);
  if (act === 'doble') platoDoble(dia, franja);
  if (act === 'templates') openTemplatePicker(el, dia, franja);
  if (act === 'franja-off') setFranjaDia(franja, dia, false);
  if (act === 'franja-on') setFranjaDia(franja, dia, true);
});

/* ---------- Plato doble, plantillas y favoritos ---------- */
async function platoDoble(dia, franja) {
  try {
    const r = await api(`${API}/weekly-plan/doble`, { method: 'POST', body: { semana: semana(), dia, franja } });
    toast(`Primero: ${r.primero.nombre} · Segundo: ${r.segundo.nombre}`);
  } catch { /* api() ya avisa (p. ej. si no hay primeros o segundos) */ }
  closeModal('assignModal');
  loadPlan();
}
let templates = [];
async function loadTemplates() {
  try { templates = (await api(`${API}/meal-templates`, { quiet: true })).plantillas; } catch { templates = []; }
  return templates;
}
async function applyTemplate(t, dia, franja) {
  const slot = planState.dias[dia].comidas[franja];
  let reemplazar = false;
  if (slot?.platos?.length) {
    reemplazar = await uiConfirm(`¿Sustituir lo que hay en ${FRANJA_LABEL[franja]}?`, `«${t.nombre}» tiene ${t.items.length} plato${t.items.length === 1 ? '' : 's'}. Si no, se añaden a los que ya hay.`,
      { confirmLabel: 'Sustituir', cancelLabel: 'Añadir' });
  }
  await api(`${API}/meal-templates/${t.id}/apply`, { method: 'POST', body: { semana: semana(), dia, franja, reemplazar } });
  closeModal('assignModal');
  toast(`Plantilla «${t.nombre}» aplicada`);
  loadPlan();
}
async function openTemplatePicker(anchor, dia, franja) {
  await loadTemplates();
  if (!templates.length) { toast('Aún no hay plantillas: guarda una comida como plantilla desde su menú «…»', { type: 'info' }); return; }
  openMenu(anchor, templates.map(t => ({ label: `${t.favorito ? '★ ' : ''}${t.nombre} · ${t.items.length} plato${t.items.length === 1 ? '' : 's'}`, icon: 'layout-template', onClick: () => applyTemplate(t, dia, franja) })));
}
async function saveTemplate(slot) {
  const nombre = await uiPrompt('Guardar como plantilla', { label: 'Nombre', value: `${FRANJA_LABEL[slot.franja] || 'Comida'}: ${slot.platos.map(p => p.nombre).join(' + ')}`.slice(0, 80), confirmLabel: 'Guardar' });
  if (!nombre?.trim()) return;
  await api(`${API}/meal-templates`, { method: 'POST', body: { nombre: nombre.trim(), plan_id: slot.plan_id, favorito: true } });
  toast('Plantilla guardada en favoritos');
}
async function toggleMealFavorite(mealId) {
  const m = allMeals.find(x => x.id === mealId);
  if (!m) return;
  m.favorito = m.favorito ? 0 : 1;
  await api(`${API}/meals/${mealId}/favorito`, { method: 'PATCH', body: { favorito: !!m.favorito } });
  renderAssignList();
}
async function setRol(planId, itemId, rol) {
  await api(`${API}/weekly-plan/rol`, { method: 'PATCH', body: { plan_id: planId, item_id: itemId, rol: rol || null } });
  loadPlan();
}

function openCellMenu(anchor, dia, franja) {
  const slot = planState.dias[dia].comidas[franja];
  if (!slot) return;
  const principal = slot.platos.find(p => p.kind === 'principal');
  openMenu(anchor, [
    { label: 'Añadir otro plato', icon: 'plus', onClick: () => openAssign(dia, franja) },
    { label: 'Añadir primero y segundo', icon: 'copy-plus', onClick: () => platoDoble(dia, franja) },
    { label: 'Aplicar una plantilla…', icon: 'layout-template', onClick: () => openTemplatePicker(anchor, dia, franja) },
    { label: 'Guardar como plantilla…', icon: 'star', onClick: () => saveTemplate(slot) },
    principal && { label: 'Sustituir por la mejor opción', icon: 'wand-sparkles', onClick: () => regenerateCell(slot.plan_id) },
    { label: slot.is_fixed ? 'Dejar de fijar' : 'Fijar (el generador no lo toca)', icon: slot.is_fixed ? 'pin-off' : 'pin', onClick: () => togglePin(slot.plan_id) },
    { label: 'Añadir a la compra', icon: 'shopping-cart', onClick: () => addPlatosToShopping(slot.platos) },
    { label: franjaOff(franja, dia) ? `Volver a poner ${(FRANJA_LABEL[franja] || '').toLowerCase()} este día` : `Quitar ${(FRANJA_LABEL[franja] || '').toLowerCase()} este día`, icon: 'eye-off',
      onClick: () => setFranjaDia(franja, dia, franjaOff(franja, dia)) },
    { separator: true },
    { label: 'Vaciar esta comida', icon: 'trash-2', danger: true, onClick: () => clearCell(slot.plan_id) },
  ].filter(Boolean));
}

async function togglePin(planId) { await api(`${API}/weekly-plan/${planId}/toggle-fixed`, { method: 'PATCH' }); loadPlan(); }
async function regenerateCell(planId) {
  try {
    const r = await api(`${API}/weekly-plan/${planId}/regenerate`, { method: 'POST', quiet: true });
    toast(`Cambiado por ${r.nombre}`);
  } catch { toast('No hay alternativas para esta comida esta semana', { type: 'info' }); }
  loadPlan();
}
async function clearCell(planId) {
  await api(`${API}/weekly-plan/${planId}`, { method: 'DELETE' });
  toast('Comida vaciada');
  loadPlan();
}
async function removePlato(kind, planId, itemId) {
  if (kind === 'extra') await api(`${API}/weekly-plan/items/${itemId}`, { method: 'DELETE' });
  else {
    // Quitar el principal: si hay extras, el primero pasa a ser principal
    const slot = Object.values(planState.dias[selectedDia].comidas).find(s => s.plan_id === planId);
    const extras = slot.platos.filter(p => p.kind === 'extra');
    await api(`${API}/weekly-plan/${planId}`, { method: 'DELETE' });
    if (slot.is_fixed) await api(`${API}/weekly-plan/${planId}/toggle-fixed`, { method: 'PATCH', quiet: true }).catch(() => {});
    for (const ex of extras) {
      await api(`${API}/weekly-plan/slots`, { method: 'POST', body: { semana: semana(), dia: selectedDia, franja: slot.franja, meal_id: ex.meal_id, gramos: ex.personalizado ? ex.gramos : null } });
    }
  }
  loadPlan();
}
async function setGramos(kind, planId, itemId, value) {
  const gramos = value === '' ? null : Math.max(1, Math.min(3000, parseFloat(value)));
  const url = kind === 'extra' ? `${API}/weekly-plan/items/${itemId}` : `${API}/weekly-plan/${planId}/gramos`;
  await api(url, { method: 'PATCH', body: { gramos } });
  loadPlan();
}

async function generateWeek() {
  const btn = $('btnGenerate');
  btn.classList.add('is-loading');
  try {
    // Solo las comidas con parte de las kcal del día (extras y las propias, a mano o con plantillas)
    await api(`${API}/weekly-plan/generate`, { method: 'POST', body: { semana: semana(), franjas: franjasActivas().filter(f => f.fraccion === undefined || f.fraccion > 0).map(f => f.key) } });
    toast('Semana generada con tus objetivos');
  } finally { btn.classList.remove('is-loading'); }
  loadPlan();
}

function openPlanMenu(anchor) {
  openMenu(anchor, [
    { label: 'Añadir la semana a la compra', icon: 'shopping-cart', onClick: generateWeekShoppingList },
    { label: 'Exportar lista de la semana', icon: 'download', onClick: () => { location.href = `${API}/shopping-list/export/${semana()}?formato=txt`; } },
    { separator: true },
    { label: 'Vaciar la semana', icon: 'trash-2', danger: true, onClick: clearWeek },
  ]);
}
async function clearWeek() {
  const ok = await uiConfirm('¿Vaciar la semana?', 'Se quitarán todos los platos excepto las comidas fijadas.', { confirmLabel: 'Vaciar', danger: true });
  if (!ok) return;
  await api(`${API}/weekly-plan/${semana()}/clear`, { method: 'DELETE' });
  toast('Semana vaciada');
  loadPlan();
}

/* ---------- Panel del día ---------- */
function renderDayPanel() {
  const d = DIAS.find(x => x.key === selectedDia);
  const idx = DIAS.indexOf(d);
  const fecha = new Date(currentWeekMonday.getTime() + idx * 86400000);
  const dia = planState.dias[selectedDia];
  const obj = planState.objetivo_dia;
  const falta = dia.restante;
  let resumen;
  if (!dia.total.kcal) resumen = 'Aún no hay nada planificado.';
  else if (falta.kcal > 60) resumen = `Faltan <b>${num(falta.kcal)} kcal</b>${falta.proteinas > 5 ? ` y <b>${num(falta.proteinas)} g de proteína</b>` : ''}.`;
  else if (falta.kcal < -150) resumen = `Te pasas <b>${num(-falta.kcal)} kcal</b> del objetivo.`;
  else resumen = 'Día cuadrado con tu objetivo.';

  const quitadas = franjasActivas().filter(f => franjaOff(f.key, selectedDia) && !dia.comidas[f.key]?.platos?.length);
  const comidas = franjasActivas().filter(f => !quitadas.includes(f)).map(f => {
    const slot = dia.comidas[f.key];
    const platos = slot?.platos || [];
    return `<section class="dp-comida">
      <header class="dp-comida-head">${icon(f.icon, 'icon-sm')}<h3>${f.label}</h3>
        <span class="tabular small muted">${platos.length ? num(slot.total.kcal) + ' kcal' : ''}</span>
        <span class="grow"></span>
        <button type="button" class="btn btn-ghost btn-sm dp-doble" data-act="doble" data-dia="${selectedDia}" data-franja="${f.key}" title="Añadir primero y segundo para lo que falta" aria-label="Primero y segundo en ${f.label}">${icon('copy-plus', 'icon-sm')}<span class="hide-mobile">1.º y 2.º</span></button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="templates" data-dia="${selectedDia}" data-franja="${f.key}" aria-label="Aplicar una plantilla a ${f.label}" title="Plantillas" aria-haspopup="menu">${icon('layout-template', 'icon-sm')}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="add" data-dia="${selectedDia}" data-franja="${f.key}" aria-label="Añadir plato a ${f.label}">${icon('plus', 'icon-sm')}</button>
        ${platos.length ? '' : `<button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="franja-off" data-dia="${selectedDia}" data-franja="${f.key}" aria-label="Quitar ${f.label} este día" title="Quitar esta comida este día">${icon('eye-off', 'icon-sm')}</button>`}
      </header>
      ${platos.length ? `<ul class="dp-platos">${platos.map(p => `<li class="dp-plato">
        ${thumbHtml({ image_url: p.image_url, franja: f.key }, 'thumb-sm')}
        <div class="grow"><button type="button" class="dp-plato-name" data-act="recipe" data-meal="${p.meal_id}">${escapeHtml(p.nombre)}</button>
          <span class="tiny muted tabular">${num(p.macros.kcal)} kcal · P ${num(p.macros.proteinas)} · H ${num(p.macros.carbohidratos)} · G ${num(p.macros.grasas)}</span>
          <label class="rol-field"><span class="sr-only">Papel de ${escapeHtml(p.nombre)}</span><select class="select input-sm rol-select" data-plan="${p.plan_id}" data-item="${p.item_id ?? ''}">
            <option value="">Sin papel</option>${ROLES.map(([k, l]) => `<option value="${k}" ${p.rol === k ? 'selected' : ''}>${l}</option>`).join('')}</select></label></div>
        <label class="grams-input"><span class="sr-only">Gramos de ${escapeHtml(p.nombre)}</span>
          <input type="number" class="input input-sm tabular" min="1" max="3000" step="5" value="${p.gramos}" data-kind="${p.kind}" data-plan="${p.plan_id}" data-item="${p.item_id ?? ''}" title="Ración estándar: ${p.gramos_estandar} g"><span>g</span></label>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="remove-plato" data-kind="${p.kind}" data-plan="${p.plan_id}" data-item="${p.item_id ?? ''}" aria-label="Quitar ${escapeHtml(p.nombre)}">${icon('x', 'icon-sm')}</button>
      </li>`).join('')}</ul>`
        : `<button type="button" class="dp-empty" data-act="add" data-dia="${selectedDia}" data-franja="${f.key}">${icon('plus', 'icon-sm')}Añadir plato</button>`}
    </section>`;
  }).join('');

  $('dayPanel').innerHTML = `
    <div class="panel-header"><h2>${d.full} <span class="muted tabular" style="font-weight:500">${fecha.getDate()}</span></h2></div>
    <div class="panel-body stack">
      <p class="dp-summary">${resumen}</p>
      <div class="meters">${MACROS.map(m => meterRow(m, dia.total[m.key], obj[m.key])).join('')}</div>
      <div class="dp-comidas">${comidas}</div>
      ${quitadas.length ? `<p class="dp-off small muted">${icon('eye-off', 'icon-sm')}<span>Sin ${quitadas.map(f => f.label.toLowerCase()).join(' ni ')} este día.</span>
        ${quitadas.map(f => `<button type="button" class="btn btn-ghost btn-sm" data-act="franja-on" data-dia="${selectedDia}" data-franja="${f.key}">Poner ${escapeHtml(f.label.toLowerCase())}</button>`).join('')}</p>` : ''}
      <section class="dp-suggest" id="suggestBox" aria-label="Sugerencias"></section>
    </div>`;
  $('dayPanel').querySelectorAll('.grams-input input').forEach(inp => inp.addEventListener('change', () =>
    setGramos(inp.dataset.kind, parseInt(inp.dataset.plan, 10), inp.dataset.item ? parseInt(inp.dataset.item, 10) : null, inp.value)));
  $('dayPanel').querySelectorAll('.rol-select').forEach(sel => sel.addEventListener('change', () =>
    setRol(parseInt(sel.dataset.plan, 10), sel.dataset.item ? parseInt(sel.dataset.item, 10) : null, sel.value)));
}

async function loadSuggestions() {
  const box = $('suggestBox');
  if (!box || !planState) return;
  const dia = planState.dias[selectedDia];
  const vacia = franjasActivas().find(f => !(dia.comidas[f.key]?.platos?.length));
  if (dia.restante.kcal < 80) { box.innerHTML = ''; return; }
  box.innerHTML = `<h3 class="dp-suggest-title">${icon('sparkles', 'icon-sm')}Encaja con lo que falta</h3>${skeletonRows(3)}`;
  let s;
  try {
    s = await api(`${API}/weekly-plan/${semana()}/sugerencias?dia=${selectedDia}${vacia ? '&franja=' + vacia.key : ''}&n=4`, { quiet: true });
  } catch { box.innerHTML = ''; return; }
  if (!document.body.contains(box)) return;
  const franja = s.franja || 'comida';
  box.innerHTML = `<h3 class="dp-suggest-title">${icon('sparkles', 'icon-sm')}${vacia ? `Para ${({ desayuno: 'el desayuno', comida: 'la comida', merienda: 'la merienda', cena: 'la cena' })[franja] || `«${FRANJA_LABEL[franja] || franja}»`}` : 'Para completar el día'}
      <span class="tiny muted tabular">· hueco ${num(s.hueco.kcal)} kcal</span></h3>
    ${s.platos.length ? `<ul class="list suggest-list">${s.platos.map(p => `<li class="list-row">
      <span class="row-main"><span class="row-title">${escapeHtml(p.nombre)}</span>
        <span class="row-sub tabular">${p.gramos} g · ${num(p.aporte.kcal)} kcal · P ${num(p.aporte.proteinas)} g</span></span>
      <button type="button" class="btn btn-tinted btn-sm" data-act="suggest-add" data-meal="${p.id}" data-gramos="${p.gramos}" data-franja="${vacia ? vacia.key : (p.franja || franja)}" aria-label="Añadir ${escapeHtml(p.nombre)}">${icon('plus', 'icon-sm')}</button></li>`).join('')}</ul>` : ''}
    ${s.ingredientes.length ? `<p class="tiny muted" style="margin-top:var(--sp-3)">O un extra rico en ${{ proteinas: 'proteína', carbohidratos: 'hidratos', grasas: 'grasa' }[s.ingredientes[0].macro]}:</p>
      <div class="chips">${s.ingredientes.map(i => `<span class="tag">${escapeHtml(i.nombre)} · ${i.gramos} g</span>`).join('')}</div>` : ''}`;
}

async function addSuggestion(mealId, gramos, franja) {
  await api(`${API}/weekly-plan/slots`, { method: 'POST', body: { semana: semana(), dia: selectedDia, franja, meal_id: mealId, gramos } });
  toast('Plato añadido');
  loadPlan();
}

function renderWeekSummary() {
  const s = planState;
  const sub = s.dias_planificados ? `${s.dias_planificados} de 7 días planificados · media ${num(s.media_diaria.kcal)} kcal/día` : 'Sin días planificados';
  $('weekSummarySub').textContent = sub;
  $('weekSummary').innerHTML = `<div class="meters">${MACROS.slice(0, 4).map(m => meterRow(m, s.semana_total[m.key], s.objetivo_semana[m.key])).join('')}</div>`
    + (s.consejo ? `<p class="week-tip tiny">${icon('lightbulb', 'icon-sm')}<span>${escapeHtml(s.consejo)}</span></p>` : '');
}

/* ---------- Elegir plato ---------- */
async function openAssign(dia, franja) {
  const fuente = FRANJAS.find(f => f.key === franja)?.catalogo || franja;
  assignTarget = { dia, franja, filtro: fuente };
  const d = DIAS.find(x => x.key === dia);
  $('assignTitle').textContent = `Añadir ${conArticulo(franja)}`;
  $('assignSub').textContent = `${d.full} · faltan ${num(planState?.dias[dia].restante.kcal || 0)} kcal en el día`;
  $('assignSearch').value = '';
  $('assignFranja').innerHTML = [{ key: '', label: 'Todas' }, { key: 'fav', label: '★ Favoritos' }, ...PLATO_FRANJAS].map(f =>
    `<button type="button" class="chip" data-af="${f.key}" aria-pressed="${f.key === fuente}">${f.label}</button>`).join('');
  // Atajos: plato doble y plantillas (favoritas primero)
  await loadTemplates();
  $('assignQuick').innerHTML = `<button type="button" class="btn btn-tinted btn-sm" data-act="doble" data-dia="${dia}" data-franja="${franja}">${icon('copy-plus', 'icon-sm')}Primero y segundo</button>`
    + templates.slice(0, 6).map(t => `<button type="button" class="btn btn-sm" data-template="${t.id}" title="${escapeHtml(t.items.map(i => i.nombre).join(' + '))}">${icon(t.favorito ? 'star' : 'layout-template', 'icon-sm')}${escapeHtml(t.nombre)}</button>`).join('');
  $('assignQuick').querySelector('[data-act=doble]').addEventListener('click', () => platoDoble(dia, franja));
  $('assignQuick').querySelectorAll('[data-template]').forEach(b => b.addEventListener('click', () =>
    applyTemplate(templates.find(t => t.id === Number(b.dataset.template)), dia, franja)));
  $('assignFranja').querySelectorAll('[data-af]').forEach(b => b.addEventListener('click', () => {
    assignTarget.filtro = b.dataset.af;
    $('assignFranja').querySelectorAll('[data-af]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    renderAssignList();
  }));
  if (!allMeals.length) await loadMeals();
  renderAssignList();
  openModal('assignModal', { focus: '#assignSearch' });
}
$('assignSearch').addEventListener('input', renderAssignList);
function renderAssignList() {
  const q = normalize($('assignSearch').value);
  const f = assignTarget.filtro;
  const items = allMeals.filter(m => (!f || (f === 'fav' ? m.favorito : m.franja === f)) && (!q || normalize(m.nombre).includes(q)))
    .sort((a, b) => (b.favorito || 0) - (a.favorito || 0));
  $('assignList').innerHTML = items.length ? items.map(m => `<li class="assign-row"><button type="button" class="list-row" data-assign="${m.id}">
      ${thumbHtml(m, 'thumb-sm')}<span class="row-main"><span class="row-title">${escapeHtml(m.nombre)}</span>
      <span class="row-sub tabular">${Math.round(m.gramos_recomendados)} g · ${num(m.kcal_total)} kcal · P ${num(m.macros_racion?.proteinas)} g</span></span>${icon('plus', 'icon-sm subtle')}</button>
      <button type="button" class="btn btn-ghost btn-icon fav-btn${m.favorito ? ' is-fav' : ''}" data-fav="${m.id}" aria-pressed="${!!m.favorito}" aria-label="${m.favorito ? 'Quitar de favoritos' : 'Marcar como favorito'}: ${escapeHtml(m.nombre)}">${icon(m.favorito ? 'star' : 'star-off', 'icon-sm')}</button></li>`).join('')
    : `<li>${emptyState({ iconName: 'search', title: 'Sin platos', text: 'Prueba con otra franja o crea un plato nuevo.', compact: true })}</li>`;
  $('assignList').querySelectorAll('[data-fav]').forEach(b => b.addEventListener('click', () => toggleMealFavorite(Number(b.dataset.fav))));
  $('assignList').querySelectorAll('[data-assign]').forEach(b => b.addEventListener('click', async () => {
    await api(`${API}/weekly-plan/slots`, { method: 'POST', body: { semana: semana(), dia: assignTarget.dia, franja: assignTarget.franja, meal_id: parseInt(b.dataset.assign, 10) } });
    closeModal('assignModal');
    toast('Plato añadido');
    loadPlan();
  }));
}
const normalize = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

/* =====================================================================
   PLATOS
   ===================================================================== */
async function loadMeals() {
  try {
    allMeals = (await api(`${API}/meals`, { quiet: true })).meals;
  } catch {
    $('mealsGrid').innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudieron cargar los platos' });
    return;
  }
  renderMeals();
}
document.querySelectorAll('#franjaChips [data-franja]').forEach(c => c.addEventListener('click', () => {
  mealFranjaFilter = c.dataset.franja;
  document.querySelectorAll('#franjaChips [data-franja]').forEach(x => x.setAttribute('aria-pressed', String(x === c)));
  renderMeals();
}));
$('mealSearch').addEventListener('input', renderMeals);

function renderMeals() {
  const q = normalize($('mealSearch').value);
  const items = allMeals.filter(m => (!mealFranjaFilter || m.franja === mealFranjaFilter) &&
    (!q || normalize(m.nombre + ' ' + (m.tags || '')).includes(q)));
  if (!items.length) {
    $('mealsGrid').innerHTML = allMeals.length
      ? emptyState({ iconName: 'search', title: 'Sin resultados', text: 'Prueba con otra búsqueda o franja.' })
      : emptyState({ iconName: 'utensils-crossed', title: 'Aún no hay platos', text: 'Crea tu primer plato con sus ingredientes y los macros se calcularán solos.', actionLabel: 'Nuevo plato', action: 'meal' });
    $('mealsGrid').querySelector('[data-empty-action]')?.addEventListener('click', () => openMealForm());
    return;
  }
  $('mealsGrid').innerHTML = items.map(m => {
    const r = m.macros_racion || {};
    return `<button type="button" class="meal-card" data-meal="${m.id}">
      ${thumbHtml(m, 'meal-card-thumb')}
      <span class="meal-card-body">
        <span class="meal-card-franja tiny">${FRANJA_LABEL[m.franja] || m.franja}${m.tiempo_preparacion_min ? ` · ${m.tiempo_preparacion_min} min` : ''}</span>
        <span class="meal-card-name">${escapeHtml(m.nombre)}</span>
        <span class="meal-card-macros tabular"><b>${num(m.kcal_total)}</b> kcal · ${Math.round(m.gramos_recomendados)} g</span>
        <span class="macro-pills tabular"><span>P ${num(r.proteinas)}</span><span>H ${num(r.carbohidratos)}</span><span>G ${num(r.grasas)}</span></span>
      </span></button>`;
  }).join('');
  $('mealsGrid').querySelectorAll('[data-meal]').forEach(b => b.addEventListener('click', () => openRecipe(parseInt(b.dataset.meal, 10))));
}

async function openRecipe(mealId) {
  $('recipeBody').innerHTML = `<span class="skeleton skeleton-title"></span>${skeletonRows(5)}`;
  openModal('recipeModal');
  const m = await api(`${API}/meals/${mealId}`);
  $('recipeTitle').textContent = m.nombre;
  const n = m.nutricion_total, d = m.nutricion_por_100g;
  $('recipeBody').innerHTML = `
    <p class="small muted">${FRANJA_LABEL[m.franja] || ''} · ${Math.round(m.gramos_recomendados)} g por ración${m.es_racion_unica ? ' (receta entera)' : ` de ${Math.round(m.gramos_totales_receta)} g de receta`}${m.tiempo_preparacion_min ? ` · ${m.tiempo_preparacion_min} min` : ''}</p>
    ${!m.kcal_check.ok ? `<p class="atwater warn">${icon('triangle-alert', 'icon-sm')}Las kcal de la receta (${num(m.kcal_check.kcal)}) no cuadran con sus macros (${num(m.kcal_check.esperadas)}). Revisa los ingredientes marcados.</p>` : ''}
    <div class="macro-tiles tabular">
      ${['kcal', 'proteinas', 'carbohidratos', 'grasas'].map(k => `<div class="macro-tile"><b>${num(n[k])}${k === 'kcal' ? '' : ' g'}</b>
        <span>${{ kcal: 'kcal', proteinas: 'Proteína', carbohidratos: 'Hidratos', grasas: 'Grasa' }[k]}</span>
        <small>${num(d[k])}${k === 'kcal' ? '' : ' g'} / 100 g</small></div>`).join('')}
    </div>
    <h3 class="recipe-h">Ingredientes de la receta</h3>
    <ul class="list ing-list">${m.ingredientes.map(i => `<li class="list-row">
      <span class="row-main"><span class="row-title">${escapeHtml(i.nombre)}${!i.kcal_check.ok ? ` <span class="warn-dot" title="Sus kcal no cuadran con los macros">${icon('triangle-alert', 'icon-sm')}</span>` : ''}</span>
        <span class="row-sub tabular">${num(i.aporte.kcal)} kcal · P ${num(i.aporte.proteinas, 1)} · H ${num(i.aporte.carbohidratos, 1)} · G ${num(i.aporte.grasas, 1)}</span></span>
      <span class="row-trail tabular">${i.unidades ? `${num(i.unidades, 1)} ${escapeHtml(i.unidad_nombre || 'ud.')} · ` : ''}${num(i.gramos)} g</span></li>`).join('')}</ul>
    ${m.instrucciones.length ? `<h3 class="recipe-h">Pasos</h3><ol class="steps">${m.instrucciones.map(p => `<li><label class="row"><input type="checkbox" class="checkbox"><span>${escapeHtml(p)}</span></label></li>`).join('')}</ol>` : ''}`;
  $('recipeEditBtn').onclick = () => { closeModal('recipeModal'); openMealForm(mealId); };
  $('recipeShopBtn').onclick = async () => {
    await api(`${API}/shopping-list/from-meal/${mealId}`, { method: 'POST' });
    toast('Ingredientes añadidos a la compra');
  };
}

/* ---------- Formulario de plato ---------- */
function ingredientByName(name) {
  const n = normalize(name.trim());
  return allIngredients.find(i => normalize(i.nombre) === n);
}
function addIngredientRow(data = {}) {
  const li = document.createElement('div');
  li.className = 'ing-row';
  const ing = data.id ? allIngredients.find(i => i.id === data.id) : null;
  const useUnits = data.unidades != null && ing?.gramos_por_unidad;
  li.innerHTML = `
    <label class="grow"><span class="sr-only">Ingrediente</span><input type="text" class="input ing-name" list="ingredientOptions" placeholder="Buscar ingrediente" value="${escapeHtml(data.nombre || '')}"></label>
    <label><span class="sr-only">Cantidad</span><input type="number" class="input ing-qty tabular" min="0" step="any" inputmode="decimal" placeholder="Cantidad" value="${useUnits ? data.unidades : (data.gramos ?? '')}"></label>
    <label><span class="sr-only">Unidad</span><select class="select ing-unit"></select></label>
    <span class="ing-kcal tiny muted tabular"></span>
    <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Quitar ingrediente">${icon('x', 'icon-sm')}</button>`;
  $('ingredientRows').appendChild(li);
  const nameInput = li.querySelector('.ing-name');
  const unit = li.querySelector('.ing-unit');
  const refreshUnits = () => {
    const ing2 = ingredientByName(nameInput.value);
    const prev = unit.value || (useUnits ? 'ud' : 'g');
    unit.innerHTML = '<option value="g">g</option>' + (ing2?.gramos_por_unidad ? `<option value="ud">${escapeHtml(ing2.unidad_nombre || 'unidad')} (${num(ing2.gramos_por_unidad)} g)</option>` : '');
    unit.value = ing2?.gramos_por_unidad && prev === 'ud' ? 'ud' : 'g';
  };
  refreshUnits();
  nameInput.addEventListener('change', () => { refreshUnits(); recalcMacros(); });
  li.querySelector('.ing-qty').addEventListener('input', recalcMacros);
  unit.addEventListener('change', recalcMacros);
  li.querySelector('button').addEventListener('click', () => { li.remove(); recalcMacros(); });
}
function addStepRow(text = '') {
  const li = document.createElement('li');
  li.className = 'step-row';
  li.innerHTML = `<label class="grow"><span class="sr-only">Paso</span><input type="text" class="input" maxlength="2000" placeholder="Describe el paso" value="${escapeHtml(text)}"></label>
    <button type="button" class="btn btn-ghost btn-icon btn-sm" aria-label="Quitar paso">${icon('x', 'icon-sm')}</button>`;
  li.querySelector('button').addEventListener('click', () => li.remove());
  $('stepRows').appendChild(li);
}
function collectIngredients() {
  const out = [], unknown = [];
  $('ingredientRows').querySelectorAll('.ing-row').forEach(row => {
    const name = row.querySelector('.ing-name').value.trim();
    const qty = parseFloat(row.querySelector('.ing-qty').value);
    if (!name) return;
    const ing = ingredientByName(name);
    if (!ing) { unknown.push(name); return; }
    if (!qty || qty <= 0) return;
    const units = row.querySelector('.ing-unit').value === 'ud';
    out.push({ ing, item: units ? { ingredient_id: ing.id, unidades: qty } : { ingredient_id: ing.id, gramos: qty }, gramos: units ? qty * ing.gramos_por_unidad : qty, row });
  });
  return { out, unknown };
}
function recalcMacros() {
  const { out } = collectIngredients();
  const tot = { kcal: 0, proteinas: 0, carbohidratos: 0, grasas: 0 };
  let gramos = 0;
  $('ingredientRows').querySelectorAll('.ing-kcal').forEach(el => { el.textContent = ''; });
  out.forEach(({ ing, gramos: g, row }) => {
    const f = g / 100;
    tot.kcal += ing.kcal_100g * f; tot.proteinas += ing.proteinas_100g * f;
    tot.carbohidratos += ing.carbohidratos_100g * f; tot.grasas += ing.grasas_100g * f;
    gramos += g;
    row.querySelector('.ing-kcal').textContent = `${num(ing.kcal_100g * f)} kcal`;
  });
  const unica = $('mealUnica').checked;
  const racion = unica ? gramos : (parseFloat($('mealGramos').value) || 0);
  const factor = gramos ? racion / gramos : 0;
  $('mealGramosHint').textContent = gramos ? `Receta completa: ${num(gramos)} g` : '0 = se sugiere al guardar';
  $('macroPreview').innerHTML = gramos ? `
    <div class="macro-tiles tabular">
      ${['kcal', 'proteinas', 'carbohidratos', 'grasas'].map(k => `<div class="macro-tile"><b>${num(tot[k] * factor)}${k === 'kcal' ? '' : ' g'}</b>
        <span>${{ kcal: 'kcal / ración', proteinas: 'Proteína', carbohidratos: 'Hidratos', grasas: 'Grasa' }[k]}</span>
        <small>receta: ${num(tot[k])}${k === 'kcal' ? '' : ' g'}</small></div>`).join('')}
    </div>` : '<p class="small muted">Añade ingredientes para ver los macros.</p>';
}
$('mealGramos').addEventListener('input', recalcMacros);
$('mealUnica').addEventListener('change', () => { $('mealGramos').disabled = $('mealUnica').checked; recalcMacros(); });

async function openMealForm(mealId = null) {
  if (!allIngredients.length) await loadIngredients();
  $('mealForm').reset();
  $('ingredientRows').innerHTML = '';
  $('stepRows').innerHTML = '';
  $('mealEditingId').value = mealId || '';
  $('mealDeleteBtn').hidden = !mealId;
  $('mealGramos').disabled = false;
  if (mealId) {
    const m = await api(`${API}/meals/${mealId}`);
    $('mealFormTitle').textContent = 'Editar plato';
    $('mealNombre').value = m.nombre;
    $('mealFranja').value = m.franja;
    $('mealTiempo').value = m.tiempo_preparacion_min || 0;
    $('mealGramos').value = Math.round(m.gramos_recomendados);
    $('mealUnica').checked = m.es_racion_unica;
    $('mealGramos').disabled = m.es_racion_unica;
    $('mealTags').value = m.tags || '';
    $('mealImage').value = m.image_url && !m.image_url.startsWith('/static/') ? m.image_url : '';
    $('mealImage').dataset.current = m.image_url || '';
    m.ingredientes.forEach(i => addIngredientRow(i));
    m.instrucciones.forEach(p => addStepRow(p));
  } else {
    $('mealFormTitle').textContent = 'Nuevo plato';
    $('mealImage').dataset.current = '';
    addIngredientRow(); addIngredientRow(); addStepRow();
  }
  recalcMacros();
  openModal('mealFormModal', { focus: '#mealNombre' });
}
async function suggestGramos() {
  const { out } = collectIngredients();
  if (!out.length) { toast('Añade ingredientes con cantidad primero', { type: 'info' }); return; }
  const r = await api(`${API}/meals/suggest-gramos`, { method: 'POST', body: { franja: $('mealFranja').value, ingredientes: out.map(o => o.item) } });
  $('mealGramos').value = Math.round(r.gramos_recomendados);
  recalcMacros();
}
$('mealForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const { out, unknown } = collectIngredients();
  if (unknown.length) { toast(`No existe en tus ingredientes: ${unknown.join(', ')}`, { type: 'error' }); return; }
  const id = $('mealEditingId').value;
  const imageInput = $('mealImage').value.trim();
  const payload = {
    nombre: $('mealNombre').value.trim(), franja: $('mealFranja').value, tags: $('mealTags').value.trim(),
    tiempo_preparacion_min: parseInt($('mealTiempo').value, 10) || 0,
    gramos_recomendados: parseFloat($('mealGramos').value) || 0, es_racion_unica: $('mealUnica').checked,
    instrucciones: [...$('stepRows').querySelectorAll('input')].map(i => i.value.trim()).filter(Boolean),
    image_url: imageInput || $('mealImage').dataset.current || '', image_source: 'manual',
    ingredientes: out.map(o => o.item),
  };
  await api(id ? `${API}/meals/${id}` : `${API}/meals`, { method: id ? 'PATCH' : 'POST', body: payload });
  closeModal('mealFormModal');
  toast(id ? 'Plato actualizado' : 'Plato creado');
  await loadMeals();
  loadPlan();
});
$('mealDeleteBtn').addEventListener('click', async () => {
  const id = $('mealEditingId').value;
  const ok = await uiConfirm('¿Eliminar este plato?', 'Se quitará también de los planes donde aparezca.', { confirmLabel: 'Eliminar', danger: true });
  if (!ok) return;
  await api(`${API}/meals/${id}`, { method: 'DELETE' });
  closeModal('mealFormModal');
  toast('Plato eliminado');
  await loadMeals();
  loadPlan();
});

/* =====================================================================
   INGREDIENTES
   ===================================================================== */
async function loadIngredients() {
  try {
    allIngredients = (await api(`${API}/ingredients`, { quiet: true })).ingredients;
  } catch { return; }
  $('ingredientOptions').innerHTML = allIngredients.map(i => `<option value="${escapeHtml(i.nombre)}">`).join('');
  const cats = [...new Set(allIngredients.map(i => i.categoria))].sort();
  $('ingCatChips').innerHTML = `<button type="button" class="chip" data-cat="" aria-pressed="${!ingCatFilter}">Todas</button>` +
    cats.map(c => `<button type="button" class="chip" data-cat="${escapeHtml(c)}" aria-pressed="${c === ingCatFilter}">${escapeHtml(CAT_LABELS[c] || c)}</button>`).join('');
  $('ingCatChips').querySelectorAll('[data-cat]').forEach(b => b.addEventListener('click', () => {
    ingCatFilter = b.dataset.cat;
    $('ingCatChips').querySelectorAll('[data-cat]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    renderIngredients();
  }));
  $('ingCategoria').innerHTML = Object.entries(CAT_LABELS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('');
  renderIngredients();
}
$('ingSearch').addEventListener('input', renderIngredients);

function renderIngredients() {
  const issues = allIngredients.filter(i => !i.kcal_check.ok);
  $('ingValidation').innerHTML = issues.length ? `<div class="notice warn">
      ${icon('triangle-alert')}<span class="grow"><b>${issues.length} ingrediente${issues.length > 1 ? 's' : ''}</b> con kcal que no cuadran con 4·P + 4·H + 9·G.</span>
      <button type="button" class="btn btn-sm" id="toggleIssues">${ingOnlyIssues ? 'Ver todos' : 'Ver solo esos'}</button></div>` : '';
  $('toggleIssues')?.addEventListener('click', () => { ingOnlyIssues = !ingOnlyIssues; renderIngredients(); });
  const q = normalize($('ingSearch').value);
  const items = allIngredients.filter(i => (!ingCatFilter || i.categoria === ingCatFilter) && (!q || normalize(i.nombre).includes(q)) && (!ingOnlyIssues || !i.kcal_check.ok));
  if (!items.length) {
    $('ingredientsTable').innerHTML = emptyState({ iconName: 'search', title: allIngredients.length ? 'Sin resultados' : 'Aún no hay ingredientes', compact: true });
    return;
  }
  $('ingredientsTable').innerHTML = `<div class="table-wrap"><table class="table ing-table">
    <thead><tr><th>Ingrediente</th><th class="hide-mobile">Categoría</th><th class="num">kcal</th><th class="num">Prot.</th><th class="num">Hidr.</th><th class="num">Grasa</th><th class="num hide-mobile">g/ud.</th><th><span class="sr-only">Acciones</span></th></tr></thead>
    <tbody>${items.map(i => `<tr>
      <td><button type="button" class="link-btn" data-edit-ing="${i.id}">${escapeHtml(i.nombre)}</button>
        ${!i.kcal_check.ok ? `<span class="warn-dot" title="Declaradas ${num(i.kcal_check.kcal)} kcal; por macros serían ${num(i.kcal_check.esperadas)}">${icon('triangle-alert', 'icon-sm')}</span>` : ''}</td>
      <td class="hide-mobile"><span class="tag">${escapeHtml(CAT_LABELS[i.categoria] || i.categoria)}</span></td>
      <td class="num">${num(i.kcal_100g)}</td><td class="num">${num(i.proteinas_100g, 1)}</td><td class="num">${num(i.carbohidratos_100g, 1)}</td><td class="num">${num(i.grasas_100g, 1)}</td>
      <td class="num hide-mobile">${i.gramos_por_unidad ? num(i.gramos_por_unidad) : '—'}</td>
      <td class="num"><button type="button" class="btn btn-ghost btn-icon btn-sm" data-ing-menu="${i.id}" aria-label="Acciones de ${escapeHtml(i.nombre)}" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button></td>
    </tr>`).join('')}</tbody></table></div>
    <p class="tiny subtle" style="margin-top:var(--sp-2)">${items.length} de ${allIngredients.length} · valores por 100 g</p>`;
  $('ingredientsTable').querySelectorAll('[data-edit-ing]').forEach(b => b.addEventListener('click', () => openIngredientForm(parseInt(b.dataset.editIng, 10))));
  $('ingredientsTable').querySelectorAll('[data-ing-menu]').forEach(b => b.addEventListener('click', () => {
    const ing = allIngredients.find(x => x.id === parseInt(b.dataset.ingMenu, 10));
    openMenu(b, [
      { label: 'Editar', icon: 'pencil', onClick: () => openIngredientForm(ing.id) },
      { label: 'Añadir a la compra', icon: 'shopping-cart', onClick: () => openAddShopping(ing.nombre) },
      { separator: true },
      { label: 'Eliminar', icon: 'trash-2', danger: true, onClick: () => deleteIngredient(ing) },
    ]);
  }));
}

const ING_FIELDS = [['ingKcal', 'kcal_100g'], ['ingProt', 'proteinas_100g'], ['ingCarb', 'carbohidratos_100g'], ['ingFat', 'grasas_100g'],
  ['ingSat', 'grasas_saturadas_100g'], ['ingSugar', 'azucares_100g'], ['ingSalt', 'sal_100g'], ['ingTrans', 'grasas_trans_100g']];
function openIngredientForm(id = null) {
  $('ingForm').reset();
  $('ingEditingId').value = id || '';
  $('ingFormTitle').textContent = id ? 'Editar ingrediente' : 'Nuevo ingrediente';
  if (id) {
    const ing = allIngredients.find(i => i.id === id);
    $('ingNombre').value = ing.nombre;
    $('ingCategoria').value = ing.categoria;
    ING_FIELDS.forEach(([el, k]) => { $(el).value = ing[k] ?? ''; });
    $('ingGpu').value = ing.gramos_por_unidad ?? '';
    $('ingUnidad').value = ing.unidad_nombre ?? '';
  }
  updateAtwater();
  openModal('ingredientModal', { focus: '#ingNombre' });
}
function updateAtwater() {
  const v = (id) => parseFloat($(id).value) || 0;
  const kcal = v('ingKcal'), exp = 4 * v('ingProt') + 4 * v('ingCarb') + 9 * v('ingFat');
  const diff = kcal - exp, pct = Math.abs(diff) / Math.max(kcal, exp, 1) * 100;
  const el = $('ingAtwater');
  if (!kcal && !exp) { el.textContent = ''; el.className = 'atwater'; return; }
  const ok = Math.abs(diff) <= 20 || pct <= 12;
  el.className = 'atwater ' + (ok ? 'ok' : 'warn');
  el.innerHTML = ok ? `${icon('circle-check', 'icon-sm')}Cuadra: por macros serían ${num(exp)} kcal.`
    : `${icon('triangle-alert', 'icon-sm')}No cuadra: por macros serían ${num(exp)} kcal (diferencia ${num(diff)}). Revisa los valores; la fibra o el alcohol explican diferencias pequeñas.`;
}
['ingKcal', 'ingProt', 'ingCarb', 'ingFat'].forEach(id => $(id).addEventListener('input', updateAtwater));
$('ingForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const id = $('ingEditingId').value;
  const payload = { nombre: $('ingNombre').value.trim(), categoria: $('ingCategoria').value,
    gramos_por_unidad: parseFloat($('ingGpu').value) || null, unidad_nombre: $('ingUnidad').value.trim() || null };
  ING_FIELDS.forEach(([el, k]) => { payload[k] = parseFloat($(el).value) || 0; });
  try {
    await api(id ? `${API}/ingredients/${id}` : `${API}/ingredients`, { method: id ? 'PATCH' : 'POST', body: payload });
  } catch { return; }
  closeModal('ingredientModal');
  toast(id ? 'Ingrediente actualizado' : 'Ingrediente creado');
  await loadIngredients();
  loadMeals();
  loadPlan();
});
async function deleteIngredient(ing) {
  const ok = await uiConfirm(`¿Eliminar «${ing.nombre}»?`, 'Desaparecerá de las recetas que lo usan.', { confirmLabel: 'Eliminar', danger: true });
  if (!ok) return;
  await api(`${API}/ingredients/${ing.id}`, { method: 'DELETE' });
  toast('Ingrediente eliminado');
  await loadIngredients();
  loadMeals();
}

/* =====================================================================
   LISTA DE LA COMPRA
   ===================================================================== */
const SOURCE_LABEL = { manual: 'Manual', planificador: 'Plan', mixto: 'Plan y manual', catalogo: 'Catálogo' };
async function loadShoppingList() {
  let data;
  try { data = await api(`${API}/shopping-list`, { quiet: true }); } catch { return; }
  const pend = data.items.filter(i => !i.comprado), done = data.items.filter(i => i.comprado);
  $('shopCountLabel').textContent = data.items.length ? `${pend.length} por comprar · ${done.length} en el carro` : '';
  if (!data.items.length) {
    $('shopLists').innerHTML = emptyState({ iconName: 'shopping-cart', title: 'La lista está vacía', text: 'Genera la lista desde el plan de la semana o añade productos sueltos.', actionLabel: 'Desde el plan', action: 'plan' });
    $('shopLists').querySelector('[data-empty-action]')?.addEventListener('click', generateWeekShoppingList);
    return;
  }
  const row = (i) => `<li class="list-row shop-row${i.comprado ? ' is-done' : ''}">
    <label class="check-hit"><input type="checkbox" class="checkbox" data-shop-check="${i.id}" ${i.comprado ? 'checked' : ''} aria-label="${escapeHtml(i.ingredient_nombre || i.nombre_libre)}"></label>
    <span class="row-main"><span class="row-title">${escapeHtml(i.ingredient_nombre || i.nombre_libre)}</span>
      <span class="row-sub">${SOURCE_LABEL[i.source] || i.source}${i.gramos_por_unidad ? ` · ≈ ${num(i.cantidad_gramos / i.gramos_por_unidad, 1)} ${escapeHtml(i.unidad_nombre || 'ud.')}` : ''}${i.plan_semana ? ` · semana del ${new Date(i.plan_semana + 'T00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}` : ''}</span></span>
    <label class="grams-input"><span class="sr-only">Cantidad</span><input type="number" class="input input-sm tabular" min="0" step="10" value="${Math.round(i.cantidad_gramos)}" data-shop-qty="${i.id}"><span>g</span></label>
    <button type="button" class="btn btn-ghost btn-icon btn-sm" data-shop-del="${i.id}" aria-label="Quitar">${icon('x', 'icon-sm')}</button></li>`;
  $('shopLists').innerHTML = `
    <section><h3 class="shop-h">Por comprar <span class="badge">${pend.length}</span></h3>
      ${pend.length ? `<ul class="list">${pend.map(row).join('')}</ul>` : '<p class="small muted">Todo en el carro.</p>'}</section>
    ${done.length ? `<section><h3 class="shop-h">En el carro <span class="badge">${done.length}</span></h3><ul class="list">${done.map(row).join('')}</ul></section>` : ''}`;
  $('shopLists').querySelectorAll('[data-shop-check]').forEach(c => c.addEventListener('change', async () => {
    await api(`${API}/shopping-list/${c.dataset.shopCheck}`, { method: 'PATCH', body: { comprado: c.checked } });
    loadShoppingList();
  }));
  $('shopLists').querySelectorAll('[data-shop-qty]').forEach(inp => inp.addEventListener('change', () =>
    api(`${API}/shopping-list/${inp.dataset.shopQty}`, { method: 'PATCH', body: { cantidad_gramos: parseFloat(inp.value) || 0 } })));
  $('shopLists').querySelectorAll('[data-shop-del]').forEach(b => b.addEventListener('click', async () => {
    await api(`${API}/shopping-list/${b.dataset.shopDel}`, { method: 'DELETE' });
    loadShoppingList();
  }));
}
async function generateWeekShoppingList() {
  const r = await api(`${API}/shopping-list/from-week/${semana()}`, { method: 'POST' });
  // Volver a pulsarlo no duplica: se rehace la parte de esa semana y se conserva lo añadido a mano
  toast(r.added ? `Lista al día con el plan: ${r.nuevos} nuevos, ${r.actualizados} actualizados` : 'El plan de esta semana está vacío', { type: r.added ? 'success' : 'info' });
  loadShoppingList();
}
function openShopMenu(anchor) {
  openMenu(anchor, [
    { label: 'Exportar lista de la semana (.txt)', icon: 'download', onClick: () => { location.href = `${API}/shopping-list/export/${semana()}?formato=txt`; } },
    { label: 'Exportar lista de la semana (.csv)', icon: 'download', onClick: () => { location.href = `${API}/shopping-list/export/${semana()}?formato=csv`; } },
    { separator: true },
    { label: 'Quitar lo que ya está en el carro', icon: 'check-check', onClick: async () => { await api(`${API}/shopping-list/done`, { method: 'DELETE' }); loadShoppingList(); } },
  ]);
}
function openAddShopping(name = '') {
  $('shopForm').reset();
  $('shopName').value = name;
  openModal('shopModal', { focus: '#shopName' });
}
$('shopForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const nombre = $('shopName').value.trim();
  const gramos = parseFloat($('shopQty').value) || 0;
  const ing = ingredientByName(nombre);
  await api(`${API}/shopping-list`, { method: 'POST', body: ing ? { ingredient_id: ing.id, cantidad_gramos: gramos } : { nombre_libre: nombre, cantidad_gramos: gramos } });
  closeModal('shopModal');
  toast('Añadido a la lista');
  loadShoppingList();
});
async function addPlatosToShopping(platos) {
  for (const p of platos) await api(`${API}/shopping-list/from-meal/${p.meal_id}`, { method: 'POST' });
  toast('Ingredientes añadidos a la compra');
}

/* =====================================================================
   OBJETIVOS
   ===================================================================== */
let profSexo = 'hombre', profObjetivo = 'mantenimiento';
const AJUSTE_OBJ = { definicion: -20, mantenimiento: 0, volumen: 10 };
document.querySelectorAll('[data-sexo]').forEach(b => b.addEventListener('click', () => {
  profSexo = b.dataset.sexo;
  document.querySelectorAll('[data-sexo]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  renderGoals();
}));
document.querySelectorAll('[data-objetivo]').forEach(b => b.addEventListener('click', () => {
  profObjetivo = b.dataset.objetivo;
  document.querySelectorAll('[data-objetivo]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  renderGoals();
}));
['pEdad', 'pPeso', 'pAltura', 'pActividad', 'pAjuste', 'pProteina', 'pGrasa'].forEach(id => $(id).addEventListener('input', renderGoals));

async function loadProfile() {
  profile = await api(`${API}/profile`);
  $('pEdad').value = profile.edad;
  $('pPeso').value = profile.peso_kg;
  $('pAltura').value = profile.altura_cm;
  $('pActividad').value = String(profile.nivel_actividad);
  $('pAjuste').value = profile.ajuste_pct ?? '';
  $('pProteina').value = profile.proteina_g_kg;
  $('pGrasa').value = profile.grasa_pct ?? 25;
  profSexo = profile.sexo;
  profObjetivo = profile.objetivo;
  document.querySelectorAll('[data-sexo]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.sexo === profSexo)));
  document.querySelectorAll('[data-objetivo]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.objetivo === profObjetivo)));
  renderGoals();
}

/* Misma fórmula que comidas/nutrition.py, para ver el efecto antes de guardar */
function computeGoals() {
  const v = (id) => parseFloat($(id).value);
  const peso = v('pPeso') || 0, altura = v('pAltura') || 0, edad = v('pEdad') || 0;
  const act = v('pActividad') || 1.2, prot = v('pProteina') || 0, grasaPct = v('pGrasa') || 25;
  const ajuste = $('pAjuste').value === '' ? AJUSTE_OBJ[profObjetivo] : v('pAjuste');
  const tmb = 10 * peso + 6.25 * altura - 5 * edad + (profSexo === 'hombre' ? 5 : -161);
  const tdee = tmb * act, kcal = tdee * (1 + ajuste / 100);
  const p = peso * prot, g = kcal * grasaPct / 100 / 9, cKcal = kcal - p * 4 - g * 9;
  return { tmb, tdee, kcal, ajuste, p, g, c: Math.max(cKcal, 0) / 4, cNeg: cKcal < 0, grasaPct };
}
function renderGoals() {
  if (!$('goalsResult')) return;
  $('ajusteHint').textContent = `Vacío = ${AJUSTE_OBJ[profObjetivo] > 0 ? '+' : ''}${AJUSTE_OBJ[profObjetivo]} % (${{ definicion: 'definición', mantenimiento: 'mantenimiento', volumen: 'volumen' }[profObjetivo]})`;
  const r = computeGoals();
  const pk = r.p * 4, gk = r.g * 9, ck = r.c * 4, tot = pk + gk + ck || 1;
  $('goalsResult').innerHTML = `
    <div class="goal-hero"><span class="goal-kcal tabular">${num(r.kcal)}</span><span class="muted">kcal al día</span></div>
    <p class="small muted goal-formula tabular">TMB ${num(r.tmb)} (Mifflin-St Jeor) × ${$('pActividad').value} = ${num(r.tdee)} kcal de gasto · ${r.ajuste >= 0 ? '+' : ''}${num(r.ajuste)} %</p>
    <div class="split-bar" role="img" aria-label="Reparto de calorías: proteína ${Math.round(pk / tot * 100)} %, hidratos ${Math.round(ck / tot * 100)} %, grasa ${Math.round(gk / tot * 100)} %">
      <span class="sb-p" style="width:${pk / tot * 100}%"></span><span class="sb-c" style="width:${ck / tot * 100}%"></span><span class="sb-g" style="width:${gk / tot * 100}%"></span></div>
    <ul class="list goal-list">
      <li class="list-row"><span class="legend-dot sb-p"></span><span class="row-main row-title">Proteína</span><span class="tabular"><b>${num(r.p)} g</b> <span class="muted">· ${Math.round(pk / tot * 100)} %</span></span></li>
      <li class="list-row"><span class="legend-dot sb-c"></span><span class="row-main row-title">Hidratos</span><span class="tabular"><b>${num(r.c)} g</b> <span class="muted">· ${Math.round(ck / tot * 100)} %</span></span></li>
      <li class="list-row"><span class="legend-dot sb-g"></span><span class="row-main row-title">Grasa</span><span class="tabular"><b>${num(r.g)} g</b> <span class="muted">· ${Math.round(r.grasaPct)} %</span></span></li>
    </ul>
    ${r.cNeg ? `<p class="atwater warn">${icon('triangle-alert', 'icon-sm')}La proteína y la grasa ya superan las calorías: baja los g/kg o el % de grasa.</p>` : ''}
    <p class="tiny subtle" style="margin-top:var(--sp-3)">Límites OMS: azúcares libres &lt; ${num(r.kcal * 0.1 / 4)} g · sal &lt; 5 g · fruta y verdura ≥ 400 g.</p>`;
}
$('profileForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const payload = {
    edad: parseInt($('pEdad').value, 10), peso_kg: parseFloat($('pPeso').value), altura_cm: parseFloat($('pAltura').value),
    sexo: profSexo, nivel_actividad: parseFloat($('pActividad').value), objetivo: profObjetivo,
    proteina_g_kg: parseFloat($('pProteina').value), grasa_pct: parseFloat($('pGrasa').value),
    ajuste_pct: $('pAjuste').value === '' ? null : parseFloat($('pAjuste').value),
  };
  await api(`${API}/profile`, { method: 'PATCH', body: payload });
  toast('Objetivos guardados');
  await loadProfile();
  loadPlan();
});

/* =====================================================================
   PESO Y MEDIDAS (comidas/planner.py: body_log, tendencia y ajuste sugerido)
   ===================================================================== */
let bodyDays = 90;
let bodyData = null;
const BODY_FIELDS = [['bPeso', 'peso_kg'], ['bCintura', 'cintura_cm'], ['bCadera', 'cadera_cm'], ['bPecho', 'pecho_cm'],
  ['bBrazo', 'brazo_cm'], ['bMuslo', 'muslo_cm'], ['bGrasa', 'grasa_pct']];

async function loadBody() {
  try { bodyData = await api(`${API}/body?dias=${bodyDays}`, { quiet: true }); } catch { return; }
  if (!$('bFecha').value) $('bFecha').value = fmtDate(new Date());
  renderBodyTrend();
  renderBodyChart();
  renderBodyTable();
}
document.querySelectorAll('[data-body-days]').forEach(b => b.addEventListener('click', () => {
  bodyDays = Number(b.dataset.bodyDays);
  document.querySelectorAll('[data-body-days]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
  loadBody();
}));
$('bFecha').addEventListener('change', () => {
  const r = bodyData?.registros.find(x => x.fecha === $('bFecha').value);
  BODY_FIELDS.forEach(([id, k]) => { $(id).value = r?.[k] ?? ''; });
});
$('bodyForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(BODY_FIELDS.map(([id, k]) => [k, $(id).value === '' ? null : parseFloat($(id).value)]));
  if (Object.values(body).every(v => v === null)) { $('bPeso').focus(); toast('Escribe al menos el peso o una medida', { type: 'info' }); return; }
  await api(`${API}/body/${$('bFecha').value}`, { method: 'PUT', body });
  toast('Registro guardado');
  BODY_FIELDS.forEach(([id]) => { $(id).value = ''; });
  loadBody();
});

function renderBodyTrend() {
  const t = bodyData.tendencia, s = bodyData.sugerencia;
  if (!t) {
    $('bodyTrend').innerHTML = `<p class="small muted">${icon('info', 'icon-sm')} Con 3 pesajes en al menos una semana verás la tendencia y, si hace falta, un ajuste de las kcal.</p>`;
    return;
  }
  const dir = t.kg_semana > 0.05 ? 'sube' : t.kg_semana < -0.05 ? 'baja' : 'se mantiene';
  $('bodyTrend').innerHTML = `<div class="trend-row">
      <span class="trend-num tabular">${t.kg_semana > 0 ? '+' : ''}${num(t.kg_semana, 2)}<small> kg/semana</small></span>
      <span class="small muted">Tu peso ${dir} (${t.pesajes} pesajes desde el ${new Date(t.desde + 'T00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short' })}).</span></div>
    ${s ? `<div class="trend-tip${s.delta_kcal ? '' : ' is-ok'}">${icon(s.delta_kcal ? 'target' : 'circle-check', 'icon-sm')}<span>${escapeHtml(s.texto)}</span>
      ${s.delta_kcal ? `<button type="button" class="btn btn-tinted btn-sm" id="btnApplyAdjust">Aplicar (${s.ajuste_pct > 0 ? '+' : ''}${num(s.ajuste_pct, 1)} %)</button>` : ''}</div>` : ''}`;
  $('btnApplyAdjust')?.addEventListener('click', async () => {
    const r = await api(`${API}/body/aplicar-ajuste`, { method: 'POST', body: { ajuste_pct: s.ajuste_pct } });
    toast(`Objetivo: ${num(r.targets.kcal_objetivo)} kcal al día`);
    await loadProfile();
    loadPlan();
    loadBody();
  });
}

// Una serie (peso) en línea de 2 px con marcadores, tendencia discontinua y tooltip al pasar
function renderBodyChart() {
  const fig = $('bodyChart');
  const pts = bodyData.registros.filter(r => r.peso_kg != null).map(r => ({ d: new Date(r.fecha + 'T00:00'), v: r.peso_kg, r }));
  if (pts.length < 2) {
    fig.innerHTML = `<p class="small muted body-empty">${pts.length ? 'Un pesaje más y aparece la gráfica.' : 'Aún no hay pesajes en este periodo.'}</p>`;
    return;
  }
  const W = 520, H = 200, L = 40, R = 10, T = 10, B = 24;
  const xs = pts.map(p => +p.d), vs = pts.map(p => p.v);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  let y0 = Math.min(...vs), y1 = Math.max(...vs);
  const pad = Math.max(0.5, (y1 - y0) * 0.15);
  y0 = Math.floor(y0 - pad); y1 = Math.ceil(y1 + pad);
  const X = (t) => L + (t - x0) / ((x1 - x0) || 1) * (W - L - R);
  const Y = (v) => T + (1 - (v - y0) / ((y1 - y0) || 1)) * (H - T - B);
  const step = (y1 - y0) > 8 ? 2 : (y1 - y0) > 4 ? 1 : 0.5;
  let grid = '';
  for (let v = Math.ceil(y0 / step) * step; v <= y1; v += step) {
    grid += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" class="bc-grid"/><text x="${L - 6}" y="${Y(v) + 4}" class="bc-axis" text-anchor="end">${num(v, 1)}</text>`;
  }
  const fmtD = (d) => d.toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
  const ticks = [pts[0], pts[Math.floor(pts.length / 2)], pts[pts.length - 1]].filter((p, i, a) => a.indexOf(p) === i);
  const xl = ticks.map((p, i) => `<text x="${X(+p.d)}" y="${H - 6}" class="bc-axis" text-anchor="${i === 0 ? 'start' : i === ticks.length - 1 ? 'end' : 'middle'}">${fmtD(p.d)}</text>`).join('');
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${X(+p.d).toFixed(1)},${Y(p.v).toFixed(1)}`).join(' ');
  let trend = '';
  const t = bodyData.tendencia;
  if (t) {  // recta de la tendencia (kg/semana) que pasa por el peso medio del periodo
    const pend = t.kg_semana / 7 / 86400000, desde = +new Date(t.desde + 'T00:00');
    const rec = pts.filter(p => +p.d >= desde);
    const mx = rec.reduce((a, p) => a + +p.d, 0) / rec.length;
    const yAt = (tt) => t.peso_medio + pend * (tt - mx);
    trend = `<path d="M${X(desde)},${Y(yAt(desde))} L${X(x1)},${Y(yAt(x1))}" class="bc-trend"/>`;
  }
  fig.innerHTML = `<figcaption class="small muted">Peso (kg)${t ? ' · discontinua: tendencia' : ''}</figcaption>
    <div class="bc-wrap"><svg viewBox="0 0 ${W} ${H}" class="bc-svg" role="img" aria-label="Peso de ${num(vs[0], 1)} a ${num(vs[vs.length - 1], 1)} kg entre el ${fmtD(pts[0].d)} y el ${fmtD(pts[pts.length - 1].d)}">
      ${grid}${xl}${trend}<path d="${line}" class="bc-line"/>
      ${pts.map(p => `<circle cx="${X(+p.d)}" cy="${Y(p.v)}" r="4" class="bc-dot"/>`).join('')}
      <line class="bc-cross" y1="${T}" y2="${H - B}" x1="0" x2="0" visibility="hidden"/>
      <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" class="bc-hit"/></svg>
      <div class="bc-tip" hidden></div></div>`;
  const svg = fig.querySelector('svg'), tip = fig.querySelector('.bc-tip'), cross = fig.querySelector('.bc-cross');
  const move = (ev) => {
    const r = svg.getBoundingClientRect();
    const vx = (ev.clientX - r.left) / r.width * W;
    const p = pts.reduce((a, b) => Math.abs(X(+b.d) - vx) < Math.abs(X(+a.d) - vx) ? b : a);
    cross.setAttribute('x1', X(+p.d)); cross.setAttribute('x2', X(+p.d)); cross.setAttribute('visibility', 'visible');
    tip.hidden = false;
    tip.innerHTML = `<b class="tabular">${num(p.v, 1)} kg</b><span>${fmtD(p.d)}</span>${p.r.cintura_cm ? `<span class="tabular">Cintura ${num(p.r.cintura_cm, 1)} cm</span>` : ''}`;
    const left = X(+p.d) / W * r.width;
    tip.style.left = Math.min(Math.max(left, 60), r.width - 60) + 'px';
    tip.style.top = (Y(p.v) / H * r.height - 12) + 'px';
  };
  svg.addEventListener('pointermove', move);
  svg.addEventListener('pointerdown', move);
  svg.addEventListener('pointerleave', () => { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); });
}

function renderBodyTable() {
  const rows = [...bodyData.registros].reverse();
  const cols = [['peso_kg', 'Peso', 'kg'], ['cintura_cm', 'Cintura', 'cm'], ['cadera_cm', 'Cadera', 'cm'], ['pecho_cm', 'Pecho', 'cm'],
    ['brazo_cm', 'Brazo', 'cm'], ['muslo_cm', 'Muslo', 'cm'], ['grasa_pct', 'Grasa', '%']].filter(([k]) => rows.some(r => r[k] != null));
  $('bodyTable').innerHTML = rows.length ? `<div class="table-wrap"><table class="table tabular"><thead><tr><th>Fecha</th>${cols.map(([, l, u]) => `<th>${l} (${u})</th>`).join('')}<th><span class="sr-only">Acciones</span></th></tr></thead>
    <tbody>${rows.map(r => `<tr><td>${new Date(r.fecha + 'T00:00').toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: '2-digit' })}</td>
      ${cols.map(([k]) => `<td>${r[k] != null ? num(r[k], 1) : '—'}</td>`).join('')}
      <td><button type="button" class="btn btn-ghost btn-icon btn-sm" data-body-del="${r.fecha}" aria-label="Borrar el registro del ${r.fecha}">${icon('trash-2', 'icon-sm')}</button></td></tr>`).join('')}</tbody></table></div>`
    : '<p class="small muted">Sin registros.</p>';
  $('bodyTable').querySelectorAll('[data-body-del]').forEach(b => b.addEventListener('click', async () => {
    await api(`${API}/body/${b.dataset.bodyDel}`, { method: 'DELETE' });
    loadBody();
  }));
}

/* ---------- Comidas del día (franjas) ---------- */
async function loadFranjas() {
  let list;
  try { list = (await api(`${API}/franjas`, { quiet: true })).franjas; } catch { return; }
  setFranjas(list);
  const total = list.filter(f => f.activa).reduce((a, f) => a + (f.fraccion || 0), 0);
  $('franjasSum').innerHTML = Math.abs(total - 1) > 0.011
    ? `${icon('triangle-alert', 'icon-sm')} Las partes suman ${Math.round(total * 100)} %: el generador las reparte en proporción.` : '';
  $('franjasList').innerHTML = list.map(f => `<li class="franja-row${f.activa ? '' : ' is-off'}" data-franja-row="${f.clave}">
      <span class="tile" data-section="comidas">${icon(FRANJA_ICONS[f.clave] || 'clock', 'icon-sm')}</span>
      <label class="grow"><span class="sr-only">Nombre</span><input class="input input-sm" data-f="nombre" value="${escapeHtml(f.nombre)}" maxlength="40"></label>
      <label><span class="sr-only">Hora de ${escapeHtml(f.nombre)}</span><input class="input input-sm" type="time" data-f="hora" value="${f.hora || ''}"></label>
      <label class="pct-field"><span class="sr-only">Parte de las kcal del día de ${escapeHtml(f.nombre)}</span><input class="input input-sm tabular" type="number" min="0" max="100" step="5" data-f="fraccion" value="${Math.round((f.fraccion || 0) * 100)}"><span>%</span></label>
      <label class="switch-field" title="${f.activa ? 'Visible en el plan' : 'Oculta'}"><input type="checkbox" class="switch" data-f="activa" ${f.activa ? 'checked' : ''}><span class="sr-only">Visible en el plan</span></label>
      ${f.base ? '' : `<button type="button" class="btn btn-ghost btn-icon btn-sm" data-f-del aria-label="Quitar ${escapeHtml(f.nombre)}">${icon('trash-2', 'icon-sm')}</button>`}
      ${f.activa ? `<div class="franja-dias" role="group" aria-label="Días con ${escapeHtml(f.nombre.toLowerCase())}">
        ${DIAS.map((d, i) => `<button type="button" class="franja-dia" data-f-dia="${d.key}" aria-pressed="${!f.dias || f.dias.includes(d.key)}" title="${d.full}"><span aria-hidden="true">${'LMXJVSD'[i]}</span><span class="sr-only">${d.full}</span></button>`).join('')}
        <button type="button" class="btn btn-ghost btn-sm" data-f-dias="todos">Todos</button>
        <button type="button" class="btn btn-ghost btn-sm" data-f-dias="laborables">Lun a vie</button></div>` : ''}
    </li>`).join('');
  $('franjasList').querySelectorAll('[data-franja-row]').forEach(li => {
    const clave = li.dataset.franjaRow;
    li.querySelectorAll('[data-f]').forEach(inp => inp.addEventListener('change', async () => {
      const k = inp.dataset.f;
      const v = k === 'activa' ? inp.checked : k === 'fraccion' ? Math.max(0, Math.min(100, parseFloat(inp.value) || 0)) / 100 : inp.value.trim();
      if (k === 'nombre' && !v) { inp.focus(); return; }
      await api(`${API}/franjas/${clave}`, { method: 'PATCH', body: { [k]: v } });
      loadFranjas();
      loadPlan();
    }));
    const putDias = async (dias) => { await api(`${API}/franjas/${clave}`, { method: 'PATCH', body: { dias } }); await loadFranjas(); loadPlan(); };
    li.querySelectorAll('[data-f-dia]').forEach(b => b.addEventListener('click', () => {
      const on = [...li.querySelectorAll('[data-f-dia]')].filter(x => (x === b ? x.getAttribute('aria-pressed') !== 'true' : x.getAttribute('aria-pressed') === 'true')).map(x => x.dataset.fDia);
      putDias(on);
    }));
    li.querySelectorAll('[data-f-dias]').forEach(b => b.addEventListener('click', () =>
      putDias(b.dataset.fDias === 'todos' ? DIAS.map(d => d.key) : DIAS.slice(0, 5).map(d => d.key))));
    li.querySelector('[data-f-del]')?.addEventListener('click', async () => {
      const r = await api(`${API}/franjas/${clave}`, { method: 'DELETE' });
      toast(r.oculta ? 'Tiene comidas planificadas: se oculta' : 'Comida quitada');
      loadFranjas();
      loadPlan();
    });
  });
}
$('btnAddFranja').addEventListener('click', async () => {
  const nombre = await uiPrompt('Nueva comida del día', { label: 'Nombre', placeholder: 'Antes de entrenar', confirmLabel: 'Añadir' });
  if (!nombre?.trim()) return;
  await api(`${API}/franjas`, { method: 'POST', body: { nombre: nombre.trim() } });
  loadFranjas();
  loadPlan();
});

/* ---------- Arranque ---------- */
(async function boot() {
  try {
    plannerMode = parseInt(localStorage.getItem('comidas_mode') || '4', 10) === 2 ? 2 : 4;
    document.querySelectorAll('[data-mode]').forEach(x => x.setAttribute('aria-pressed', String(parseInt(x.dataset.mode, 10) === plannerMode)));
  } catch {}
  let tab = 'plan';
  try { tab = localStorage.getItem('comidas_tab') || 'plan'; } catch {}
  switchTab(['plan', 'platos', 'compra', 'ingredientes', 'objetivos'].includes(tab) ? tab : 'plan');
  await Promise.all([loadPlan(), loadMeals(), loadIngredients(), loadProfile()]);
})();
