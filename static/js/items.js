/* ==========================================================================
   items.js — almacén único de tareas e ideas (window.Items)
   Una sola lista (GET /api/items) y una sola función por acción. La usan el
   Inbox y su tablero, la pestaña Tareas, la captura rápida (FAB, tecla C), las
   casillas de las notas y el arrastre. Cada cambio pasa por api(), que lo
   anuncia a las otras pestañas; aquí se recarga y se emite «items:changed».

   Reglas (las mismas que valida el servidor, app/items.py):
   - un solo nivel de pasos, y padre e hijos del mismo tipo;
   - un elemento con pasos no cambia de tipo ni pasa a ser paso de otro;
   - en una nota solo hay tareas (una idea sin pasos que entra se convierte).
   ========================================================================== */
(function () {
  'use strict';

  const GROUPS = { inbox: 'Inbox', nota: 'Notas', ideas: 'Ideas', rutinas: 'Rutinas' };
  const PRIO = { alta: 'Prioridad alta', media: 'Prioridad media', baja: 'Prioridad baja' };
  const TYPE_KEY = 'capture-type';

  const S = { items: [], byId: {}, kids: {}, counts: null, loaded: false };
  let loading = null;
  let pending = 0;   // escrituras propias en curso: no se recarga a medias

  function index(items) {
    S.items = items;
    S.byId = {};
    S.kids = {};
    items.forEach((it) => { S.byId[it.id] = it; });
    items.forEach((it) => { if (it.parent_id && S.byId[it.parent_id]) (S.kids[it.parent_id] ||= []).push(it); });
    // Pasos en el orden en que se ven (el del servidor: sort_order descendente)
  }

  function emit() {
    document.dispatchEvent(new CustomEvent('items:changed'));
    updateBadges();
  }

  async function load() {
    if (loading) return loading;
    loading = (async () => {
      const data = await api('/api/items', { quiet: true });
      index(data.items);
      S.counts = data.counts;
      S.loaded = true;
      emit();
    })();
    try { await loading; } finally { loading = null; }
  }
  const ready = () => (S.loaded ? Promise.resolve() : load());

  function updateBadges() {
    if (!S.counts) return;
    const n = S.counts.pendientes;
    document.querySelectorAll('[data-inbox-count]').forEach((el) => {
      el.textContent = n > 99 ? '99+' : String(n);
      el.hidden = n === 0;
    });
  }

  // Otra pestaña (o una nota guardada aquí) cambió algo: se recarga si ya se estaba usando
  onDataChange(/^\/api\/(items|inbox|notes|bulk\/notes)/, () => { if (S.loaded && !pending) load(); });

  /* ---------- Consultas ---------- */
  const get = (id) => S.byId[id];
  const children = (id) => S.kids[id] || [];
  const originOf = (it) => it.origin;
  const typeFor = (target) => ({ ideas: 'idea', rutinas: 'rutina' }[target] || 'tarea');

  /* ---------- Reglas ---------- */
  // dest = { target: 'inbox'|'nota'|'ideas', note_id, parent_id }. Devuelve true o el motivo.
  function moveError(id, dest) {
    const it = get(id);
    if (!it || !dest) return 'Destino no válido';
    const kids = children(it.id).length;
    if (dest.parent_id != null) {
      const p = get(dest.parent_id);
      if (!p) return 'Destino no válido';
      if (p.id === it.id) return 'No se puede meter dentro de sí mismo';
      if (p.parent_id) return 'Solo hay un nivel de pasos';
      if (kids) return 'Tiene pasos: no puede pasar a ser paso de otro';
      if (p.type !== it.type && (p.type === 'rutina' || it.type === 'rutina')) return 'Una rutina solo tiene rutinas como pasos';
      if (p.type !== it.type) return it.type === 'tarea' ? 'Una subtarea no puede pasar a ser subidea' : 'Una subidea no puede pasar a ser subtarea';
      return true;
    }
    if (!GROUPS[dest.target]) return 'Destino no válido';
    if (dest.target === 'nota' && !dest.note_id) return 'Falta la nota';
    if (typeFor(dest.target) !== it.type && kids) return `Tiene pasos: no se puede convertir en ${typeFor(dest.target)}`;
    return true;
  }

  /* ---------- Acciones (todas pasan por aquí) ---------- */
  async function write(fn) {
    pending++;
    try { return await fn(); } finally { pending--; }
  }
  async function after(result) { await load(); return result; }

  function create(body) {
    return write(async () => {
      const res = await api('/api/items', { method: 'POST', body });
      return after(res.id);
    });
  }

  function update(id, patch) {
    return write(async () => after(await api(`/api/items/${id}`, { method: 'PATCH', body: patch })));
  }

  function setDone(id, done) {
    const it = get(id);
    if (it) { it.done = done; emit(); }  // se ve al instante; la recarga confirma
    return write(async () => {
      try { await api(`/api/items/${id}`, { method: 'PATCH', body: { done } }); }
      finally { await load(); }
    });
  }

  function move(id, dest) {
    return write(async () => {
      const before = get(id);
      try {
        await api(`/api/items/${id}/move`, { method: 'POST', quiet: true, body: dest });
      } catch (err) { await load(); throw err; }
      await load();
      const now = get(id);
      if (before && now && before.type !== now.type) toast(now.type === 'tarea' ? 'Convertida en tarea' : 'Convertida en idea', { type: 'info', duration: 1800 });
    });
  }

  // Borra (con sus pasos) y ofrece deshacer
  function remove(ids, { label } = {}) {
    ids = [].concat(ids);
    return write(async () => {
      const res = ids.length === 1
        ? await api(`/api/items/${ids[0]}`, { method: 'DELETE' })
        : await api('/api/items/bulk', { method: 'POST', body: { ids, action: 'delete' } });
      await load();
      toast(label || (ids.length === 1 ? 'Eliminado' : `${ids.length} eliminados`), {
        action: { label: 'Deshacer', onClick: () => undo(res.undo) },
      });
    });
  }

  function undo(token) {
    return write(async () => {
      await api('/api/items/undo', { method: 'POST', body: { token } });
      await load();
      toast('Recuperado', { type: 'info', duration: 1600 });
    });
  }

  function bulk(ids, action, extra = {}) {
    return write(async () => {
      const res = await api('/api/items/bulk', { method: 'POST', body: { ids, action, ...extra } });
      await load();
      if (res.errors?.length) toast(`${res.errors.length} no se pudieron cambiar: ${res.errors[0].detail}`, { type: 'info' });
      return res;
    });
  }

  function toNote(id, body) {
    return write(async () => after(await api(`/api/items/${id}/to-note`, { method: 'POST', body })));
  }

  /* ---------- Captura (FAB, tecla C, Inbox, Tareas, extensión: POST /api/items) ---------- */
  function lastType() {
    try { const t = localStorage.getItem(TYPE_KEY); return ['idea', 'rutina'].includes(t) ? t : 'tarea'; } catch { return 'tarea'; }
  }
  function rememberType(t) { try { localStorage.setItem(TYPE_KEY, t); } catch {} }

  // Prefijos (los mismos que la captura del escritorio, app/capture.py): t: tarea · i: idea ·
  // r: rutina en castellano · e: evento en lenguaje natural (con vista previa antes de guardar)
  const PREFIX_RE = /^\s*([tireg])\s*:/i;  // g: gasto (Economía)
  async function captureWithPrefix(text) {
    if (/^\s*e\s*:/i.test(text)) {
      const prev = await api('/api/capture', { method: 'POST', body: { text, dry_run: true } });
      const ok = prev.kind === 'evento'
        ? await uiConfirm(prev.preview.title, prev.preview.when, { confirmLabel: 'Guardar el evento' })
        : await uiConfirm('No entiendo la fecha', `${prev.reason}. Se guardará en el Inbox marcado «Revisar fecha».`, { confirmLabel: 'Guardar en el Inbox' });
      if (!ok) return null;
    }
    const res = await api('/api/capture', { method: 'POST', body: { text } });
    await load();
    toast(res.message, {
      type: res.revisar ? 'info' : 'success',
      action: res.kind === 'evento' ? { label: 'Ver', onClick: () => { location.href = `/calendario?dia=${res.preview.start.slice(0, 10)}`; } } : null,
    });
    return res.id;
  }

  async function capture(text, type, extra = {}) {
    const clean = (text || '').trim();
    if (!clean) return null;
    if (PREFIX_RE.test(clean)) return write(() => captureWithPrefix(clean));
    rememberType(type);
    const id = await create({ text: clean, type, ...extra });
    toast({ idea: 'Idea guardada', rutina: 'Rutina creada' }[type] || 'Tarea guardada', {
      action: ['/inbox', '/tareas'].includes(location.pathname) ? null : { label: 'Ver', onClick: () => { location.href = '/tareas'; } },
    });
    return id;
  }

  /* Formulario de captura común (partial templates/_capture.html): texto + Tarea/Idea + Guardar */
  function wireCaptureForm(form, { onSaved } = {}) {
    if (!form || form.dataset.wired) return;
    form.dataset.wired = '1';
    const ta = form.querySelector('[data-capture-text]');
    const typeBtns = [...form.querySelectorAll('[data-capture-type]')];
    const count = form.querySelector('[data-capture-count]');
    const repeatBox = form.querySelector('[data-capture-repeat]');
    const setType = (t) => {
      typeBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.captureType === t)));
      if (repeatBox) repeatBox.hidden = t !== 'rutina';
    };
    const daysSlot = form.querySelector('[data-capture-days]');
    if (daysSlot) daysSlot.innerHTML = dayPicker({ legend: 'Se repite', hideLegend: true });
    setType(lastType());
    typeBtns.forEach((b) => b.addEventListener('click', () => { setType(b.dataset.captureType); rememberType(b.dataset.captureType); }));
    const sync = () => { if (count) count.textContent = ta.value.length > 400 ? `${ta.value.length}/${ta.maxLength}` : ''; };
    ta.addEventListener('input', sync);
    async function submit(e) {
      e?.preventDefault();
      const type = typeBtns.find((b) => b.getAttribute('aria-pressed') === 'true')?.dataset.captureType || 'tarea';
      if (!ta.value.trim()) { ta.focus(); return; }
      const btn = form.querySelector('[type=submit]');
      btn?.classList.add('is-loading');
      try {
        const repeat = type === 'rutina' && repeatBox ? repeatFromDays(repeatBox) : null;
        if (type === 'rutina' && repeatBox && !repeat) { toast('Elige al menos un día', { type: 'info' }); return; }
        const time = form.querySelector('[data-repeat-time]')?.value;
        const extra = repeat ? { repeat, ...(time ? { due_time: time } : {}) } : {};
        const id = await capture(ta.value, type, extra);
        ta.value = '';
        repeatBox?.querySelectorAll('[data-day]').forEach((c) => { c.checked = true; });
        sync();
        onSaved?.(id);
      } finally { btn?.classList.remove('is-loading'); }
    }
    form.addEventListener('submit', submit);
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || (!e.shiftKey && ta.rows <= 1))) submit(e);
    });
    form.setType = setType;
  }

  // Todos los formularios de captura de la página (el del FAB cierra su diálogo al guardar)
  document.querySelectorAll('[data-capture]').forEach((form) => {
    wireCaptureForm(form, form.id === 'captureForm' ? { onSaved: () => closeModal('captureModal') } : {});
  });

  window.Items = {
    GROUPS, PRIO,
    get state() { return S; },
    load, ready, get, children, originOf, moveError, typeFor,
    create, update, setDone, move, remove, undo, bulk, toNote, capture, wireCaptureForm, lastType,
  };
})();
