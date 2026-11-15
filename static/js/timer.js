/* ==========================================================================
   timer.js — contador en marcha (window.Timer, P-2)
     Barra fija bajo la cabecera, en todas las páginas, con lo que está en marcha y su tiempo:
     Pausar/Seguir · Completar · Cambiar a otra · Quitar. Un solo contador, guardado en el servidor
     (app/contador.py): sobrevive a F5 y se ve igual en otra pestaña o en el móvil.
     Timer.start({ item_id | titulo, prevista_min })   empezar (si había otro, se cierra)
     Timer.pause() · Timer.resume() · Timer.complete({ marcar }) · Timer.stop()
     Timer.pick()            elegir qué empezar (tareas pendientes, rutinas y pasos, o una actividad libre)
     Timer.isRunning(id) · Timer.chip(item)   para las tarjetas de item-list.js
   No pregunta cada segundo: el tiempo se calcula aquí con la hora de inicio del tramo y el desfase con el reloj del
   servidor. Se recarga al cambiar algo en otra pestaña (BroadcastChannel de ui.js), al volver el foco y con el
   latido (cada minuto, solo con la pestaña visible y el contador en marcha), que además le dice al servidor que
   seguimos aquí (si no llega ninguno en 45 min, el servidor lo pausa solo: portátil dormido).
   ========================================================================== */
(function () {
  'use strict';
  const esc = (s) => escapeHtml(String(s ?? ''));
  let cur = null, reciente = null, offset = 0, tickTimer = null, beatTimer = null, busy = false, lastKey = '';
  const now = () => Date.now() / 1000 + offset;
  const KIND = { tarea: 'Tarea', idea: 'Idea', rutina: 'Rutina', paso: 'Paso', libre: 'Actividad libre' };

  function elapsed(s = cur) {
    if (!s) return 0;
    return Math.max(0, Math.floor(s.segundos + (s.tramo_inicio ? now() - s.tramo_inicio : 0)));
  }
  function clock(sec) {
    const h = Math.floor(sec / 3600), m = Math.floor(sec / 60) % 60, s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
  }
  function human(sec) {
    const m = Math.round(sec / 60);
    if (m < 1) return 'menos de un minuto';
    if (m < 60) return `${m} min`;
    return `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ''}`;
  }
  const hora = (ts) => new Date(ts * 1000).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });

  function adopt(res) {
    if (!res) return;
    if (typeof res.ahora === 'number') offset = res.ahora - Date.now() / 1000;
    if ('activa' in res) cur = res.activa;
    if ('reciente' in res) reciente = res.reciente;
  }

  /* ---------- Barra ---------- */
  function slot() { return window.topSlot?.('contador', 1); }
  // Región viva fija (fuera de la barra, que se repinta): solo habla cuando cambia qué está en marcha o su estado
  function say(text) {
    let el = document.getElementById('timerLive');
    if (!el) {
      el = Object.assign(document.createElement('span'), { id: 'timerLive', className: 'sr-only' });
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    el.textContent = text;
  }

  function paint() {
    const box = slot();
    if (!box) return;
    clearInterval(tickTimer);
    tickTimer = null;
    // Las tarjetas (item-list.js) solo se repintan cuando cambia qué está en marcha o su estado
    const key = cur ? `${cur.id}|${cur.estado}` : '';
    if (key !== lastKey) {
      const closed = lastKey && !cur;
      lastKey = key;
      if (closed && window.Items?.state?.loaded) Items.load().catch(() => {});  // su tiempo nuevo en la tarjeta
      else document.dispatchEvent(new CustomEvent('timer:changed', { detail: cur }));
      say(cur ? `${cur.estado === 'marcha' ? 'En marcha' : 'En pausa'}: ${cur.titulo}, ${human(elapsed())}` : (closed ? 'Contador cerrado' : ''));
    }
    if (!cur) {
      paintRecent(box);
      return;
    }
    box.hidden = false;
    const running = cur.estado === 'marcha';
    const sec = elapsed();
    const over = cur.prevista_min && sec > cur.prevista_min * 60;
    const sub = [
      cur.padre ? `${KIND.paso} de «${cur.padre}»` : KIND[cur.tipo],
      cur.prevista_min ? `${cur.prevista_min} min previstos` : '',
      cur.auto_pausa ? `sin señal desde las ${hora(cur.auto_pausa)}` : (!running ? 'en pausa' : ''),
    ].filter(Boolean).join(' · ');
    box.innerHTML = `<section class="run-bar${running ? ' is-running' : ' is-paused'}${over ? ' is-over' : ''}" aria-label="Contador en marcha">
      <span class="run-dot" aria-hidden="true"></span>
      <div class="run-what">
        ${cur.href ? `<a class="run-title" href="${esc(cur.href)}">${esc(cur.titulo)}</a>` : `<span class="run-title">${esc(cur.titulo)}</span>`}
        <span class="run-sub tiny">${esc(sub)}</span>
      </div>
      <span class="run-time tabular" data-run-time aria-hidden="true">${clock(sec)}</span>
      <div class="run-actions">
        ${cur.auto_pausa ? `<button type="button" class="btn btn-sm btn-tinted" data-run="recuperar" aria-label="Contar ese tiempo" data-tip="No hubo señales desde las ${hora(cur.auto_pausa)}: cuenta también ese hueco">${icon('history', 'icon-sm')}<span class="hide-mobile" aria-hidden="true">Contar ese tiempo</span></button>` : ''}
        <button type="button" class="btn btn-sm btn-icon btn-ghost" data-run="${running ? 'pausar' : 'seguir'}" aria-label="${running ? 'Pausar' : 'Seguir'}" data-tip="${running ? 'Pausar' : 'Seguir'}">${icon(running ? 'pause' : 'play', 'icon-sm')}</button>
        ${cur.tipo !== 'libre' ? `<button type="button" class="btn btn-sm btn-icon btn-ghost" data-run="completar" aria-label="Completar «${esc(cur.titulo)}»" data-tip="Completar">${icon('check', 'icon-sm')}</button>` : ''}
        <button type="button" class="btn btn-sm btn-icon btn-ghost" data-run="cambiar" aria-haspopup="dialog" aria-label="Cambiar a otra" data-tip="Cambiar a otra">${icon('arrow-left-right', 'icon-sm')}</button>
        <button type="button" class="btn btn-sm btn-icon btn-ghost" data-run="quitar" aria-label="Quitar el contador (el tiempo se guarda)" data-tip="Quitar (el tiempo se guarda)">${icon('x', 'icon-sm')}</button>
      </div></section>`;
    if (running) tickTimer = setInterval(tick, 1000);
  }

  function tick() {
    if (!cur || document.hidden) return;
    const el = document.querySelector('[data-run-time]');
    const sec = elapsed();
    if (el) el.textContent = clock(sec);
    const over = cur.prevista_min && sec > cur.prevista_min * 60;
    const bar = document.querySelector('.run-bar');
    if (over && bar && !bar.classList.contains('is-over')) {
      bar.classList.add('is-over');
      warnOver();
    }
  }

  // Pasarse de lo previsto: un aviso por sesión (también si se recarga la página)
  function warnOver() {
    const key = `contador-pasado-${cur.id}`;
    try { if (localStorage.getItem(key)) return; localStorage.setItem(key, '1'); } catch {}
    toast(`Has pasado los ${cur.prevista_min} min previstos de «${cur.titulo}»`, { type: 'info', duration: 5000 });
  }

  // Lo que se cerró solo a medianoche: se avisa una vez, con «Seguir hoy»
  function paintRecent(box) {
    let seen = false;
    try { seen = !reciente || localStorage.getItem('contador-visto') === String(reciente.id); } catch {}
    if (!reciente || seen) { box.innerHTML = ''; box.hidden = true; return; }
    box.hidden = false;
    box.innerHTML = `<div class="run-note" role="status">${icon('moon-star', 'icon-sm')}
      <span>«${esc(reciente.titulo)}» quedó en marcha y se cerró a medianoche (${human(reciente.transcurrido)}).</span>
      ${reciente.item_id ? `<button type="button" class="btn btn-sm btn-tinted" data-run="seguir-hoy">${icon('play', 'icon-sm')}Seguir hoy</button>` : ''}
      <button type="button" class="btn btn-sm btn-icon btn-ghost" data-run="visto" aria-label="Entendido, quitar el aviso">${icon('x', 'icon-sm')}</button></div>`;
  }

  /* ---------- Acciones ---------- */
  async function call(path, body) {
    if (busy) return null;
    busy = true;
    let res = null;
    try { res = await api(`/api/contador/${path}`, { method: 'POST', body }); } catch (e) {
      if (e.status === 409) await load();  // ya no hay nada en marcha (cerrado en otro sitio o a medianoche)
      return null;
    } finally { busy = false; }
    adopt(res);
    paint();
    beat();
    return res;
  }

  async function start({ item_id = null, titulo = null, prevista_min = null } = {}) {
    const res = await call('empezar', { item_id, titulo, prevista_min });
    if (res?.activa) {
      toast(`En marcha: ${res.activa.titulo}`, { type: 'info', duration: 1800 });
      document.querySelector('[data-run="pausar"]')?.focus({ preventScroll: true });
    }
    return res?.activa || null;
  }
  const pause = () => call('pausar');
  const resume = () => call('seguir');
  async function complete({ marcar = true, quiet = false } = {}) {
    const res = await call('completar', { marcar });
    if (res?.cerrada && !quiet) {
      toast(`Hecha: ${res.cerrada.titulo} · ${human(res.cerrada.transcurrido)}`, { type: 'success', duration: 2400 });
    }
    return res;
  }
  async function stop() {
    const res = await call('quitar');
    if (res?.cerrada) toast(`Contador quitado · ${human(res.cerrada.transcurrido)} guardados`, { type: 'info', duration: 2400 });
    return res;
  }

  // Qué empezar: lo pendiente (tareas, ideas, rutinas y sus pasos de hoy) o una actividad libre con lo escrito
  async function pick() {
    await window.Items?.ready?.().catch(() => {});
    const all = window.Items?.state?.items || [];
    const today = new Date().toISOString().slice(0, 10);
    let typed = '';
    const choice = await uiPick({
      title: cur ? 'Cambiar a otra' : 'Empezar contador',
      placeholder: 'Busca una tarea o escribe una actividad libre',
      confirmLabel: 'Empezar',
      load: () => {
        const items = all.filter((it) => !it.done && it.id !== cur?.item_id && (it.type !== 'rutina' || it.today !== false))
          .sort((a, b) => ((b.due_date && b.due_date <= today) - (a.due_date && a.due_date <= today)) || (a.type === 'rutina') - (b.type === 'rutina'))
          .map((it) => {
            const parent = it.parent_id ? Items.get(it.parent_id) : null;
            return { id: it.id, label: it.text.split('\n')[0], icon: it.type === 'rutina' ? 'repeat' : it.type === 'idea' ? 'lightbulb' : 'square-check',
              sub: [parent ? `Paso de «${parent.text.split('\n')[0]}»` : '', it.due_date ? (it.due_date < today ? 'Atrasada' : it.due_date === today ? 'Hoy' : it.due_date) : '', it.duration_min ? `${it.duration_min} min` : ''].filter(Boolean).join(' · ') };
          });
        return [{ id: 'libre', label: 'Actividad libre…', sub: 'Escribe lo que vas a hacer', icon: 'timer' }, ...items];
      },
    });
    // el cuadro de búsqueda ya se cerró: «Actividad libre» pregunta el nombre
    if (!choice) return null;
    if (choice.id === 'libre') {
      typed = await uiPrompt('Actividad libre', { label: '¿Qué vas a hacer?', placeholder: 'Ordenar el escritorio', confirmLabel: 'Empezar' });
      if (!typed?.trim()) return null;
      return start({ titulo: typed.trim().slice(0, 200) });
    }
    return start({ item_id: choice.id });
  }

  /* ---------- Carga, latido y sincronía ---------- */
  async function load() {
    try { adopt(await api('/api/contador', { quiet: true })); } catch { return; }
    paint();
    beat();
  }
  // Latido: cada minuto con la pestaña visible y el contador en marcha («seguimos aquí» para el servidor)
  function beat() {
    clearInterval(beatTimer);
    beatTimer = null;
    if (cur?.estado !== 'marcha') return;
    beatTimer = setInterval(async () => {
      if (document.hidden || cur?.estado !== 'marcha') return;
      try { adopt(await api('/api/contador/latido', { method: 'POST', quiet: true })); } catch { return; }
      paint();
    }, 60000);
  }

  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-run]');
    if (!b || !b.closest('.topstrip')) return;
    const act = b.dataset.run;
    if (act === 'pausar') pause();
    else if (act === 'seguir') resume();
    else if (act === 'recuperar') call('recuperar');
    else if (act === 'completar') complete();
    else if (act === 'quitar') stop();
    else if (act === 'cambiar') pick();
    else if (act === 'seguir-hoy') { try { localStorage.setItem('contador-visto', String(reciente.id)); } catch {} start({ item_id: reciente.item_id }); }
    else if (act === 'visto') { try { localStorage.setItem('contador-visto', String(reciente?.id)); } catch {} paint(); }
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) tick(); });
  onDataChange(/^\/api\/contador/, load);

  const isRunning = (id) => !!cur && cur.item_id === id;
  function chip(it) {
    const live = isRunning(it.id);
    const sec = (it.tiempo_s || 0);
    return `<span class="il-chip tabular${live ? ' il-timer-live' : ''}" title="${live ? 'En marcha ahora' : 'Tiempo registrado con el contador'}">${icon('timer', 'icon-sm')}${live ? (cur.estado === 'marcha' ? 'En marcha' : 'En pausa') : human(sec)}</span>`;
  }

  window.Timer = { start, pause, resume, complete, stop, pick, load, isRunning, chip, elapsed, get current() { return cur; } };
  load();
})();
