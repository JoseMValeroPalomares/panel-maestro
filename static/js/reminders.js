/* ==========================================================================
   reminders.js — avisos del Panel como notificaciones del navegador (window.Reminders)
   Cada minuto, mientras haya una pestaña del Panel abierta (y el permiso concedido),
   pide /api/reminders y muestra los que ya tocan. Una sola pestaña avisa (cerrojo en
   localStorage) y cada aviso sale una vez: antes de enseñarlo se reclama en el panel
   (POST /api/reminders/vistos), así que si ya lo enseñó el portátil (notify-send desde la
   Waybar) o el móvil, aquí no se repite. La configuración por tipo está en Prefs ('reminders').
   ========================================================================== */
(function () {
  'use strict';
  const SEEN = 'reminders-seen';
  const LOCK = 'reminders-lock';
  const supported = 'Notification' in window;

  function seen() { try { return JSON.parse(localStorage.getItem(SEEN) || '{}'); } catch { return {}; } }
  function markSeen(key) {
    const s = seen();
    s[key] = Date.now();
    const week = Date.now() - 7 * 86400000;
    Object.keys(s).forEach((k) => { if (s[k] < week) delete s[k]; });
    try { localStorage.setItem(SEEN, JSON.stringify(s)); } catch {}
  }
  // Solo una pestaña avisa: la que renueva el cerrojo cada minuto
  const me = Math.random().toString(36).slice(2);
  function leader() {
    try {
      const [who, at] = (localStorage.getItem(LOCK) || '').split('|');
      if (!who || who === me || Date.now() - Number(at) > 90000) { localStorage.setItem(LOCK, `${me}|${Date.now()}`); return true; }
    } catch { return true; }
    return false;
  }

  async function show(r) {
    window.Sonido?.play('aviso');
    const opts = { body: r.body, tag: r.key, icon: '/static/icons/icon-192.png', badge: '/static/icons/icon-192.png', data: { url: r.url } };
    try {
      const reg = await navigator.serviceWorker?.getRegistration();
      if (reg) { await reg.showNotification(r.title, opts); return; }
    } catch {}
    try {
      const n = new Notification(r.title, opts);
      n.onclick = () => { window.focus(); location.href = r.url; };
    } catch { toast(`${r.title} · ${r.body}`, { type: 'info', duration: 8000 }); }
  }

  async function tick() {
    if (!supported || Notification.permission !== 'granted' || !leader()) return;
    let data;
    try { data = await api('/api/reminders?horizon=2', { quiet: true }); } catch { return; }
    if (!data.settings?.navegador?.on) return;
    const now = data.now, s = seen(), shown = new Set(data.shown || []);
    const due = data.reminders.filter((r) => r.fire_at <= now && !s[r.key] && !shown.has(r.key));
    if (!due.length) return;
    let claimed;
    try { claimed = new Set((await api('/api/reminders/vistos', { method: 'POST', body: { keys: due.map((r) => r.key) }, quiet: true })).claimed); } catch { return; }
    for (const r of due) {
      markSeen(r.key);
      if (claimed.has(r.key)) show(r);
    }
  }

  /* ---------- Ajustes ---------- */
  const TYPES = [['evento', 'Eventos', 'calendar'], ['tarea', 'Tareas con hora', 'square-check'], ['rutina', 'Rutinas con hora', 'repeat'], ['flashcards', 'Repaso de flashcards', 'book-open'], ['resumen', 'Resumen de la mañana', 'sun']];
  const AT_HOUR = { flashcards: '20:00', resumen: '08:30' };  // los que avisan a una hora fija
  async function openSettings() {
    let conf;
    try { conf = (await api('/api/reminders/settings', { quiet: true })).settings; } catch { return; }
    const perm = supported ? Notification.permission : 'unsupported';
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm';
    const minOpts = [[0, 'A la hora'], [5, '5 min antes'], [10, '10 min antes'], [15, '15 min antes'], [30, '30 min antes'], [60, '1 hora antes']];
    dlg.innerHTML = `<div class="modal-header"><h2>Avisos</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body stack" id="remForm">
        ${TYPES.map(([k, l, ic]) => `<div class="rem-row"><label class="switch-row grow"><input type="checkbox" class="switch" name="${k}" ${conf[k].on ? 'checked' : ''}>${icon(ic, 'icon-sm')}<span>${l}</span></label>
          ${AT_HOUR[k] ? `<label><span class="sr-only">Hora de: ${l}</span><input type="time" class="input input-sm" name="${k}_hora" value="${conf[k].hora || AT_HOUR[k]}"></label>`
            : `<label><span class="sr-only">Antelación de ${l}</span><select class="select input-sm" name="${k}_min">${minOpts.map(([v, t]) => `<option value="${v}" ${Number(conf[k].min) === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`}</div>`).join('')}
        <hr class="sep">
        <fieldset class="rem-late stack-sm"><legend class="field-label">Tareas atrasadas</legend>
          <div class="rem-row"><label class="switch-row grow"><input type="checkbox" class="switch" name="atrasadas" ${conf.atrasadas.on ? 'checked' : ''} aria-describedby="remLateHint">${icon('clock-alert', 'icon-sm')}<span>Avisar en el escritorio</span></label>
            <label><span class="sr-only">Hora del aviso de atrasadas</span><input type="time" class="input input-sm" name="atrasadas_hora" value="${conf.atrasadas.hora || '09:00'}"></label></div>
          ${dayPicker({ days: conf.atrasadas.dias, legend: 'Días del aviso de atrasadas', hideLegend: true })}
          <p class="tiny muted" id="remLateHint">Una notificación con botones (Completar · Mañana · Hoy no · Borrar) por tarea y día como mucho, a esa hora y en esos días. En el panel, el aviso «N atrasadas» sale siempre.</p>
        </fieldset>
        <hr class="sep">
        <label class="switch-row"><input type="checkbox" class="switch" name="navegador" ${conf.navegador.on ? 'checked' : ''}><span>En este navegador ${perm === 'granted' ? '(permitido)' : perm === 'denied' ? '(bloqueado en el navegador)' : perm === 'unsupported' ? '(no disponible)' : ''}</span></label>
        ${perm === 'default' ? `<button type="button" class="btn btn-tinted btn-sm" data-perm>${icon('bell-ring', 'icon-sm')}Permitir notificaciones</button>` : ''}
        <label class="switch-row"><input type="checkbox" class="switch" name="escritorio" ${conf.escritorio.on ? 'checked' : ''}><span>En el escritorio del portátil (notify-send)</span></label>
        <p class="tiny muted">El navegador avisa mientras haya una pestaña del Panel abierta. Con el navegador cerrado avisa el portátil (módulo de la Waybar). Cada aviso sale en un solo sitio: el primero que lo enseña. El resumen de la mañana es una línea con lo de hoy («3 tareas, 2 clases · 1 atrasada»). Cada evento puede tener su propia antelación en su editor.</p>
      </form>
      <div class="modal-footer"><button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="remForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    dlg.querySelector('[data-perm]')?.addEventListener('click', async (e) => {
      const p = await Notification.requestPermission();
      e.target.closest('button').replaceWith(Object.assign(document.createElement('p'), { className: 'small', textContent: p === 'granted' ? 'Permitido.' : 'No se ha permitido.' }));
    });
    dlg.querySelector('form').addEventListener('submit', (e) => {
      e.preventDefault();
      const f = e.target;
      if (f.atrasadas.checked && !readDays(f.querySelector('.rem-late')).length) { toast('Elige al menos un día para el aviso de atrasadas', { type: 'info' }); return; }
      const value = {
        navegador: { on: f.navegador.checked }, escritorio: { on: f.escritorio.checked },
        flashcards: { on: f.flashcards.checked, hora: f.flashcards_hora.value || '20:00' },
        resumen: { on: f.resumen.checked, hora: f.resumen_hora.value || '08:30' },
        atrasadas: { on: f.atrasadas.checked, hora: f.atrasadas_hora.value || '09:00', dias: readDays(f.querySelector('.rem-late')) },
        ...Object.fromEntries(['evento', 'tarea', 'rutina'].map((k) => [k, { on: f[k].checked, min: Number(f[`${k}_min`].value) }])),
      };
      Prefs.set('reminders', value);
      closeModal(dlg);
      toast('Avisos guardados');
    });
    openModal(dlg, { onClose: () => dlg.remove() });
  }

  window.Reminders = { openSettings, tick };
  if (supported) { setTimeout(tick, 4000); setInterval(tick, 60000); }
})();
