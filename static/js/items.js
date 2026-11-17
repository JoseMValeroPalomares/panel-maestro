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
    // Pasos en el orden en que se ven (el del servidor: sort_order descendente); los de una rutina,
    // por su hora, y al final los que no tienen
    Object.values(S.kids).forEach((kids) => {
      if (kids[0].type === 'rutina') kids.sort((a, b) => (a.due_time || '99').localeCompare(b.due_time || '99'));
    });
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
    // Mismo criterio que ui.js (refreshInboxBadge): solo lo que está por procesar en el Inbox
    const n = S.counts.inbox?.pendientes ?? S.counts.pendientes;
    document.querySelectorAll('[data-inbox-count]').forEach((el) => {
      el.textContent = n > 99 ? '99+' : String(n);
      el.hidden = n === 0;
    });
  }

  // Otra pestaña (o una nota guardada aquí) cambió algo: se recarga si ya se estaba usando
  onDataChange(/^\/api\/(items|inbox|notes|bulk\/notes|capture)/, () => { if (S.loaded && !pending) load(); });

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

  // Lo nuevo va al contexto que se está viendo (si no dice otro): si no, desaparecería de la lista
  function withContext(body) {
    if (!window.Ctx || body.parent_id || body.note_id || 'contexto' in body || body.asignatura_id || body.proyecto_id) return body;
    return { ...body, contexto: Ctx.forNew() };
  }

  /* ---------- Cola sin conexión (F-6) ----------
     Una captura que no llega al panel POR RED (sin cobertura, fuera de casa sin Tailscale, el portátil apagado) no se
     pierde: se guarda en este dispositivo y se manda en orden al volver la conexión, al recuperar el foco y cada minuto
     mientras quede algo. Lo que el panel rechaza (datos no válidos) no entra en la cola: se avisa como siempre.
     Solo altas (/api/capture y /api/items); los textos con «e:» van sin la confirmación del evento, que necesita al
     servidor: si la fecha no se entiende, el servidor la deja en el Inbox marcada «Revisar fecha». */
  const QUEUE_KEY = 'panel.capturas-pendientes';
  const QUEUE_MAX = 200;
  const readQueue = () => { try { return JSON.parse(localStorage.getItem(QUEUE_KEY) || '[]'); } catch { return []; } };
  const writeQueue = (q) => { try { localStorage.setItem(QUEUE_KEY, JSON.stringify(q.slice(-QUEUE_MAX))); return true; } catch { return false; } };
  const isNetworkError = (err) => err && err.status === undefined;  // fetch rechazado: no hubo respuesta del panel

  // Envía un alta; si no hay red, la encola y devuelve { queued: n }
  async function postOrQueue(url, body) {
    try {
      return await api(url, { method: 'POST', body, quiet: true });
    } catch (err) {
      if (!isNetworkError(err)) { if (err.status !== 401) toast(err.message, { type: 'error' }); throw err; }
      const q = readQueue();
      q.push({ url, body: { ...body, dry_run: false }, at: Date.now() });
      if (!writeQueue(q)) { toast('Sin conexión con el panel y no se pudo guardar aquí: copia el texto', { type: 'error', duration: 8000 }); throw err; }
      toast(q.length === 1 ? 'Sin conexión: se guardará al volver' : `Sin conexión: ${q.length} capturas esperando`, { type: 'info', duration: 5000 });
      return { queued: q.length };
    }
  }

  let flushing = false;
  async function flushQueue() {
    if (flushing || !readQueue().length) return;
    flushing = true;
    let sent = 0;
    try {
      for (;;) {
        const q = readQueue();
        if (!q.length) break;
        try {
          await api(q[0].url, { method: 'POST', body: q[0].body, quiet: true });
          sent++;
        } catch (err) {
          if (isNetworkError(err) || err.status === 401 || err.status >= 500) break;  // se reintenta más tarde
          toast(`Una captura sin conexión no se pudo guardar: ${err.message}`, { type: 'error', duration: 8000 });
        }
        writeQueue(readQueue().slice(1));  // la primera ya está (o era inválida): fuera
      }
    } finally { flushing = false; }
    if (sent) {
      toast(sent === 1 ? 'Guardada la captura que hiciste sin conexión' : `Guardadas ${sent} capturas que hiciste sin conexión`);
      if (S.loaded) load();
    }
  }
  window.addEventListener('online', flushQueue);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) flushQueue(); });
  setInterval(() => { if (!document.hidden) flushQueue(); }, 60000);
  setTimeout(flushQueue, 1500);  // al abrir cualquier página, lo que quedó de otra vez

  /* Micro-interacciones (Fase 5): lo recién completado o creado, para que la lista lo anime. La lista se repinta dos veces
     (al instante y al confirmar el servidor): recent() da los ms ya pasados y la animación sigue por donde iba. */
  const RECENT = new Map();  // id → { kind: 'done' | 'new', at }
  const RECENT_MS = 900;
  function mark(id, kind) {
    if (id == null) return;
    RECENT.set(Number(id), { kind, at: performance.now() });
    // Lo completado sigue un momento en «Pendientes» (se ve marcarse); al acabar, otro repintado lo quita
    if (kind === 'done' && !S.byId[id]?.parent_id) setTimeout(emit, RECENT_MS + 30);  // un paso no sale de la lista
  }
  function recent(id) {
    const r = RECENT.get(Number(id));
    if (!r) return null;
    const ms = performance.now() - r.at;
    if (ms > RECENT_MS) { RECENT.delete(Number(id)); return null; }
    return { kind: r.kind, ms: Math.round(ms) };
  }

  function create(body) {
    body = withContext(body);
    return write(async () => {
      const res = await postOrQueue('/api/items', body);
      if (res.queued) return null;
      mark(res.id, 'new');
      return after(res.id);
    });
  }

  function update(id, patch) {
    return write(async () => after(await api(`/api/items/${id}`, { method: 'PATCH', body: patch })));
  }

  function setDone(id, done) {
    const it = get(id);
    if (done) mark(id, 'done');
    if (it) { it.done = done; emit(); }  // se ve al instante; la recarga confirma
    if (done) window.Sonido?.play('hecho');
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
  async function captureWithPrefix(text, extra = {}) {
    const where = { contexto: extra.contexto, asignatura_id: extra.asignatura_id, proyecto_id: extra.proyecto_id };
    if (/^\s*e\s*:/i.test(text) && navigator.onLine !== false) {
      let prev;
      try { prev = await api('/api/capture', { method: 'POST', body: { text, dry_run: true }, quiet: true }); } catch (err) {
        if (!isNetworkError(err)) { toast(err.message, { type: 'error' }); return null; }
        prev = null;  // sin red: se encola tal cual, sin confirmar
      }
      if (prev) {
        if (prev.status === 'error') { toast(prev.message, { type: 'error' }); return null; }
        const ok = prev.kind === 'evento'
          ? await uiConfirm(prev.preview.title, prev.preview.when, { confirmLabel: 'Guardar el evento' })
          : await uiConfirm('No entiendo la fecha', `${prev.reason}. Se guardará en el Inbox marcado «Revisar fecha».`, { confirmLabel: 'Guardar en el Inbox' });
        if (!ok) return null;
      }
    }
    const res = await postOrQueue('/api/capture', { text, ...withContext(Object.fromEntries(Object.entries(where).filter(([, v]) => v != null))) });
    if (res.queued) return null;
    if (res.status === 'error') { toast(res.message, { type: 'error' }); return null; }  // p. ej. una @mención que no existe
    mark(res.id, 'new');
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
    if (PREFIX_RE.test(clean)) return write(() => captureWithPrefix(clean, extra));
    rememberType(type);
    const id = await create({ text: clean, type, ...extra });
    if (id === null) return null;  // sin conexión: ya avisó la cola
    toast({ idea: 'Idea guardada', rutina: 'Rutina creada' }[type] || 'Tarea guardada', {
      action: ['/inbox', '/tareas'].includes(location.pathname) ? null : { label: 'Ver', onClick: () => { location.href = '/tareas'; } },
    });
    return id;
  }

  /* Formulario de captura común (templates/_items.html): texto + Tarea/Idea/Rutina + Guardar (P-3)
     Lo que se entiende del texto (fecha, hora, duración, «!alta», «+Categoría», @asignatura, #proyecto) se ve debajo;
     «Más opciones» (plegado y recordado) fija día, hora, duración, prioridad y categoría, y manda sobre lo escrito.
     Intro guarda, Mayús+Intro es salto de línea, Ctrl+Intro guarda y deja la captura abierta para otra, Esc la vacía. */
  const SCREEN = 'tareas';
  const pad2 = (n) => String(n).padStart(2, '0');
  const isoDay = (d) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  // Día: Hoy, Mañana y el próximo L…D (el de hoy es hoy; si no, el siguiente)
  function dayChoices() {
    const t = new Date(); t.setHours(12, 0, 0, 0);
    const add = (n) => { const d = new Date(t); d.setDate(t.getDate() + n); return isoDay(d); };
    const dow = (t.getDay() + 6) % 7;
    const names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];
    return [['Hoy', add(0), 'Hoy'], ['Mañana', add(1), 'Mañana'],
      ...['L', 'M', 'X', 'J', 'V', 'S', 'D'].map((l, i) => [l, add(((i - dow + 7) % 7) || 7), names[i]]).filter(([, d]) => d !== add(0) && d !== add(1))];
  }
  function wireCaptureForm(form, { onSaved } = {}) {
    if (!form || form.dataset.wired) return;
    form.dataset.wired = '1';
    const ta = form.querySelector('[data-capture-text]');
    const typeBtns = [...form.querySelectorAll('[data-capture-type]')];
    const count = form.querySelector('[data-capture-count]');
    const repeatBox = form.querySelector('[data-capture-repeat]');
    const prev = form.querySelector('[data-capture-preview]');
    const more = form.querySelector('[data-capture-more]');
    const inModal = !!form.closest('dialog');
    const opt = {};          // lo elegido en «Más opciones» (undefined = lo que diga el texto)
    let literal = false;     // «Sin fecha»: el texto tal cual
    const curType = () => typeBtns.find((b) => b.getAttribute('aria-pressed') === 'true')?.dataset.captureType || 'tarea';
    const setType = (t) => {
      typeBtns.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.captureType === t)));
      if (repeatBox) repeatBox.hidden = t !== 'rutina';
      form.querySelectorAll('[data-opt-when]').forEach((n) => { n.hidden = t === 'rutina'; });
      runPreview();
    };
    const daysSlot = form.querySelector('[data-capture-days]');
    if (daysSlot) daysSlot.innerHTML = dayPicker({ legend: 'Se repite', hideLegend: true });
    const daysBox = form.querySelector('[data-opt-days]');
    if (daysBox) {
      daysBox.innerHTML = dayChoices().map(([l, d, n]) => `<button type="button" class="chip chip-sm" data-opt-day="${d}" aria-pressed="false" title="${n} ${Number(d.slice(8))}"${l.length === 1 ? ` aria-label="${n} ${Number(d.slice(8))}"` : ''}>${l}</button>`).join('')
        + '<button type="button" class="chip chip-sm" data-opt-day="" aria-pressed="false">Sin fecha</button>';
    }
    if (more && window.Rapido) Rapido.more(more, SCREEN);
    const catList = form.querySelector('datalist');
    more?.addEventListener('toggle', () => {
      if (more.open && catList) catList.innerHTML = [...new Set(S.items.map((i) => i.category).filter(Boolean))].sort().map((c) => `<option value="${escapeHtml(c)}">`).join('');
    });
    const paintOpts = () => {
      form.querySelectorAll('[data-opt-day]').forEach((b) => b.setAttribute('aria-pressed', String(opt.due_date !== undefined && b.dataset.optDay === opt.due_date)));
      form.querySelectorAll('[data-opt-dur]').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.optDur) === opt.duration_min)));
      form.querySelectorAll('[data-opt-prio]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.optPrio === opt.priority)));
    };
    const toggleOpt = (key, value) => { opt[key] = opt[key] === value ? undefined : value; paintOpts(); runPreview(); };
    form.addEventListener('click', (e) => {
      const b = e.target.closest('[data-opt-day], [data-opt-dur], [data-opt-prio], [data-capture-literal]');
      if (!b) return;
      if (b.dataset.captureLiteral !== undefined) { literal = !literal; runPreview(); ta.focus(); return; }
      if (b.dataset.optDay !== undefined) toggleOpt('due_date', b.dataset.optDay);
      else if (b.dataset.optDur) toggleOpt('duration_min', Number(b.dataset.optDur));
      else toggleOpt('priority', b.dataset.optPrio);
    });
    const timeIn = form.querySelector('[data-opt-time]');
    const catIn = form.querySelector('[data-opt-cat]');
    timeIn?.addEventListener('input', () => { const t = parseTime(timeIn.value); opt.due_time = timeIn.value.trim() ? (t || undefined) : undefined; runPreview(); });
    catIn?.addEventListener('input', () => { opt.category = catIn.value.trim() || undefined; runPreview(); });

    // Lo que va al servidor: las opciones elegidas (más la duración recordada si se pone hora sin duración)
    function opciones() {
      const o = Object.fromEntries(Object.entries(opt).filter(([, v]) => v !== undefined));
      if (o.due_time && o.duration_min === undefined && window.Rapido) { const d = Rapido.defaults.get(SCREEN, 'dur'); if (d) o.duration_min = d; }
      if (literal || curType() === 'idea') o.literal = true;  // las ideas, tal cual
      return o;
    }
    const PREFIX = /^\s*[tiregTIREG]\s*:/;
    const where = () => (form.dataset.where && window.Ctx ? Ctx.whereToPatch(form.dataset.where) : {});
    const bodyFor = (dry) => {
      const type = curType();
      return withContext({ text: `${type === 'idea' ? 'i' : 't'}: ${ta.value.trim()}`, opciones: opciones(), dry_run: dry, ...where() });
    };
    const runPreview = window.Rapido ? Rapido.preview(async () => {
      const t = ta.value.trim();
      if (!t || curType() === 'rutina' || PREFIX.test(t)) return null;
      return api('/api/capture', { method: 'POST', body: bodyFor(true), quiet: true });
    }, (res) => {
      if (!prev) return;
      if (!res || res.status !== 'success') {
        prev.hidden = !(res && res.message);
        prev.innerHTML = res?.message ? Rapido.chips([{ icon: 'triangle-alert', text: res.message, kind: 'warn' }]) : '';
        return;
      }
      const p = res.preview;
      const chips = Rapido.chips([
        p.when && { icon: p.due_time ? 'calendar-clock' : 'calendar', text: p.when },
        p.priority && { icon: 'flag', text: PRIO[p.priority] || p.priority },
        p.category && { icon: 'tag', text: p.category, kind: 'plain' },
        p.donde && { icon: 'map-pin', text: p.donde, kind: 'plain' },
        literal && { icon: 'calendar-off', text: 'Sin leer la fecha', kind: 'plain' },
      ]);
      prev.hidden = !chips;
      prev.innerHTML = chips + (p.fecha_leida || literal ? `<button type="button" class="link-btn" data-capture-literal>${literal ? 'Leer la fecha' : 'No es una fecha'}</button>` : '');
    }, 250) : () => {};
    if (!runPreview.cancel) runPreview.cancel = () => {};

    setType(lastType());
    typeBtns.forEach((b) => b.addEventListener('click', () => { setType(b.dataset.captureType); rememberType(b.dataset.captureType); }));
    const sync = () => { if (count) count.textContent = ta.value.length > 400 ? `${ta.value.length}/${ta.maxLength}` : ''; };
    ta.addEventListener('input', () => { sync(); if (!ta.value.trim()) literal = false; runPreview(); });
    function reset() {
      ta.value = '';
      Object.keys(opt).forEach((k) => { opt[k] = undefined; });
      literal = false;
      if (timeIn) timeIn.value = '';
      if (catIn) catIn.value = '';
      repeatBox?.querySelectorAll('[data-day]').forEach((c) => { c.checked = true; });
      paintOpts();
      runPreview.cancel();
      if (prev) { prev.hidden = true; prev.innerHTML = ''; }
      sync();
    }
    async function submit(e, again = false) {
      e?.preventDefault();
      const type = curType();
      if (!ta.value.trim()) { ta.focus(); return; }
      if (timeIn?.value.trim() && parseTime(timeIn.value) === null) { toast('Escribe la hora como 17:30', { type: 'info' }); timeIn.focus(); return; }
      const btn = form.querySelector('[type=submit]');
      btn?.classList.add('is-loading');
      try {
        let id;
        if (type === 'rutina' || PREFIX.test(ta.value)) {
          const repeat = type === 'rutina' && repeatBox ? repeatFromDays(repeatBox) : null;
          if (type === 'rutina' && repeatBox && !repeat) { toast('Elige al menos un día', { type: 'info' }); return; }
          const time = form.querySelector('[data-repeat-time]')?.value;
          const extra = repeat ? { repeat, ...(time ? { due_time: time } : {}) } : {};
          if (form.dataset.where && window.Ctx) Object.assign(extra, Ctx.whereToPatch(form.dataset.where));
          id = await capture(ta.value, type, extra);
        } else {
          rememberType(type);
          const body = bodyFor(false);
          const res = await write(async () => {
            const r = await postOrQueue('/api/capture', body);
            if (!r.queued) mark(r.id, 'new');
            return r.queued ? r : after(r);
          });
          if (res.queued) { reset(); if (again) ta.focus(); else onSaved?.(null); return; }  // guardada en la cola
          if (res.status === 'error') { toast(res.message, { type: 'error' }); return; }
          id = res.id;
          if (body.opciones.duration_min && opt.duration_min !== undefined && window.Rapido) Rapido.defaults.set(SCREEN, 'dur', body.opciones.duration_min);
          toast(res.message, {
            action: ['/inbox', '/tareas'].includes(location.pathname) ? null : { label: 'Ver', onClick: () => { location.href = '/tareas'; } },
          });
        }
        reset();
        if (id) form.setWhere?.('');
        if (again) ta.focus(); else onSaved?.(id);
      } finally { btn?.classList.remove('is-loading'); }
    }
    form.addEventListener('submit', (e) => submit(e));
    form.addEventListener('keydown', (e) => {
      if (e.key !== 'Enter' || e.isComposing || e.shiftKey || e.altKey) return;
      if (e.target.matches('button, summary, select') && !(e.ctrlKey || e.metaKey)) return;
      if (!e.target.matches('textarea, input')) return;
      if (e.target.matches('[data-repeat-time]') && !(e.ctrlKey || e.metaKey)) { submit(e); return; }
      submit(e, (e.ctrlKey || e.metaKey) && inModal);
    });
    // Esc vacía la captura de la página (en el diálogo la cierra el propio diálogo)
    if (!inModal) {
      form.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape' || !ta.value.trim() || e.defaultPrevented) return;
        e.preventDefault();
        reset();
        ta.focus();
      });
    }
    form.setType = setType;
    // «+» de un subgrupo (una asignatura o un proyecto): lo siguiente que se guarde va ahí
    form.setWhere = (where) => {
      form.dataset.where = where || '';
      const name = !where ? '' : where.startsWith('a:') ? Ctx.asig(Number(where.slice(2)))?.codigo : where.startsWith('p:') ? '#' + (Ctx.proy(Number(where.slice(2)))?.slug || '') : Ctx.label(where);
      ta.placeholder = name ? `Nueva en ${name}…` : ta.dataset.ph;
    };
    ta.dataset.ph = ta.placeholder;
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
    get pendingCaptures() { return readQueue().length; }, flushQueue, recent,
  };
})();
