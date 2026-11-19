/* ==========================================================================
   red.js — Ajustes → «Red y dispositivos» (window.Red)
   Las direcciones de este equipo, del ESP32 y de la extensión, que el panel busca y recuerda solo
   (core/red.py, /api/red). Aquí se ven, se comprueban («Probar conexión»), se vuelven a buscar
   («Redetectar») y, si hace falta, se fija la del ESP32 a mano o se cambian las de respaldo.
   Nada de aquí toca la red del equipo ni el router: solo mira y avisa.
   ========================================================================== */
(function () {
  'use strict';
  const ORIGEN = { manual: 'fijada a mano', 'última': 'la última que funcionó', mdns: 'por su nombre (mDNS)', env: 'del archivo .env',
    mac: 'por su MAC', respaldo: 'la de reserva', barrido: 'buscando en la red', latido: 'la dijo la placa' };
  // Motivos del último arranque de la placa que conviene saber (los normales, «encendido» y «reinicio», no se dicen)
  const ARRANQUE = { vigilante: 'se reinició sola (se había colgado)', tension: 'se reinició por falta de tensión (cable o cargador)', error: 'se reinició por un error' };
  let dlg = null;
  let estado = null;
  let timer = null;

  const hora = (ts) => (ts ? `${timeAgo(ts)} (${new Date(ts * 1000).toLocaleString('es-ES', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })})` : 'nunca');
  const dato = (nombre, valor, mono = false) => (valor || valor === 0
    ? `<div class="red-dato"><dt>${escapeHtml(nombre)}</dt><dd${mono ? ' class="red-mono"' : ''}>${escapeHtml(String(valor))}</dd></div>` : '');
  const pill = (state, texto) => `<span class="status-pill" data-state="${state}">${escapeHtml(texto)}</span>`;
  const duracion = (s) => (s >= 86400 ? `${Math.floor(s / 86400)} d ${Math.floor((s % 86400) / 3600)} h` : s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min` : `${Math.max(1, Math.round(s / 60))} min`);

  function equipo(s) {
    const urls = s.urls.map((u) => `<li><span class="red-url"><span class="red-mono">${escapeHtml(u.url)}</span> <span class="subtle">${escapeHtml(u.donde)}</span></span>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-copiar="${escapeHtml(u.url)}" aria-label="Copiar ${escapeHtml(u.url)}">${icon('copy', 'icon-sm')}</button></li>`).join('');
    return `<section class="red-disp" aria-labelledby="redEquipo">
      <header class="red-cab"><span class="tile" data-section="gestion" aria-hidden="true">${icon('laptop')}</span>
        <h3 id="redEquipo">Este equipo <span class="subtle red-nombre">${escapeHtml(s.nombre)}</span></h3>${pill('ok', 'En marcha')}</header>
      <dl class="red-datos">
        ${dato('IP en la red local', s.ips.join(', ') || 'sin red local', true)}
        ${dato('Reserva en el router', s.respaldo + (s.coincide_reserva ? ' ✓' : ' (no coincide)'), true)}
        ${dato('Tailscale', s.tailscale.activo ? `${s.tailscale.ip} · ${s.tailscale.nombre}` : 'no está activo', s.tailscale.activo)}
        ${dato('Escucha en', s.solo_local ? `${s.escucha}:${s.puerto} (solo este equipo)` : `${s.escucha}:${s.puerto} (toda la red local)`, true)}
      </dl>
      <p class="field-label">Direcciones para entrar</p><ul class="red-urls">${urls}</ul>
      <div class="red-acciones"><button type="button" class="btn btn-sm" data-probar="servidor">${icon('activity', 'icon-sm')}Probar conexión</button>
        <span class="red-resultado" data-resultado="servidor" role="status"></span></div></section>`;
  }

  function placa(e) {
    const en = e.enlace || {};
    const cab = !e.configurada ? pill('warn', 'Sin placa')
      : e.en_linea || en.online ? pill('ok', 'En línea') : pill(en.state === 'connecting' ? 'warn' : 'error', en.state === 'connecting' ? 'Conectando…' : 'Fuera de línea');
    const cuerpo = !e.configurada
      ? '<p class="small muted">No hay placa configurada. Para activarla, pon <code>ESP32_HOST=auto</code> en el archivo <code>.env</code> y reinicia el panel: la dirección la encuentra sola.</p>'
      : `<dl class="red-datos">
        ${dato('IP actual', e.direccion + (e.manual ? ' · fijada a mano' : e.origen ? ` · ${ORIGEN[e.origen] || e.origen}` : ''), true)}
        ${dato('Nombre en la red', e.nombre_mdns, true)}
        ${dato('MAC', e.mac, true)}
        ${dato('Reserva en el router', e.respaldo + (e.coincide_reserva ? ' ✓' : ' (no coincide)'), true)}
        ${dato('Última conexión', hora(e.visto))}
        ${dato('Firmware', e.fw)}
        ${e.uptime ? dato('Encendida hace', duracion(e.uptime) + (ARRANQUE[e.reset] ? ` · ${ARRANQUE[e.reset]}` : '')) : ''}
        ${e.rssi ? dato('Señal wifi', `${e.rssi} dBm${e.rssi > -67 ? ' (buena)' : e.rssi > -78 ? ' (justa)' : ' (débil)'}`) : ''}
        ${e.heap ? dato('Memoria libre', `${Math.round(e.heap / 1024)} KB${e.heap_min ? ` (mínimo ${Math.round(e.heap_min / 1024)} KB)` : ''}`) : ''}
        ${e.ip_anterior && e.ip_anterior !== e.direccion ? dato('Antes estaba en', e.ip_anterior, true) : ''}
      </dl>
      <div class="red-acciones"><button type="button" class="btn btn-sm btn-tinted" data-redetectar>${icon('radar', 'icon-sm')}Redetectar</button>
        <button type="button" class="btn btn-sm" data-probar="esp32">${icon('activity', 'icon-sm')}Probar conexión</button>
        <span class="red-resultado" data-resultado="esp32" role="status"></span></div>`;
    return `<section class="red-disp" aria-labelledby="redPlaca">
      <header class="red-cab"><span class="tile" data-section="estudio" aria-hidden="true">${icon('cpu')}</span><h3 id="redPlaca">ESP32</h3>${cab}</header>${cuerpo}</section>`;
  }

  function extension(x, srv) {
    const cab = !x.conocida ? pill('warn', 'Sin noticias') : !x.url_vigente ? pill('error', 'Dirección antigua') : x.activa ? pill('ok', 'Activa') : pill('warn', 'Hace tiempo');
    const cuerpo = !x.conocida
      ? `<p class="small muted">La extensión aún no ha llamado a este panel. Ábrela y, en «Conexión», pulsa <strong>Detectar</strong>: probará sola <span class="red-mono">${escapeHtml(srv.principal)}</span> y las demás direcciones.</p>`
      : `<dl class="red-datos">
        ${dato('Entra por', x.url, true)}
        ${dato('Desde', x.ip, true)}
        ${dato('Versión', [x.version, x.navegador].filter(Boolean).join(' · '))}
        ${dato('Última conexión', hora(x.visto))}
      </dl>`;
    return `<section class="red-disp" aria-labelledby="redExt">
      <header class="red-cab"><span class="tile" data-section="baul" aria-hidden="true">${icon('puzzle')}</span><h3 id="redExt">Extensión del navegador</h3>${cab}</header>${cuerpo}</section>`;
  }

  function ajustes(e) {
    const a = e.ajustes;
    const campo = (id, etiqueta, valor, pista = '') => `<label class="field"><span class="field-label">${etiqueta}</span>
      <input class="input red-mono" name="${id}" value="${escapeHtml(valor)}" inputmode="decimal" autocomplete="off" spellcheck="false" maxlength="15" placeholder="192.168.1.…">${pista ? `<span class="field-hint">${pista}</span>` : ''}</label>`;
    return `<details class="form-details red-ajustes"><summary>${icon('chevron-right', 'icon-sm')}Direcciones a mano y reservas</summary>
      <form class="stack" id="redForm" novalidate>
        <div class="red-manual">${campo('esp32_manual', 'IP del ESP32 fijada a mano', e.esp32.manual, 'Vacío = automática (lo normal). Fíjala solo si la búsqueda no la encuentra.')}
          <button type="button" class="btn btn-sm" data-probar="ip">Probar esa IP</button></div>
        <fieldset class="field"><legend class="field-label">Direcciones de respaldo (las reservas DHCP del router)</legend>
          <div class="red-rejilla">${campo('servidor', 'Este equipo', a.servidor)}${campo('esp32', 'ESP32', a.esp32)}${campo('gateway', 'Router', a.gateway)}${campo('mascara', 'Máscara', a.mascara)}</div>
          <span class="field-hint">Se usan cuando la búsqueda automática falla. En el router, reserva <strong>${escapeHtml(a.servidor)}</strong> para este equipo y <strong>${escapeHtml(a.esp32)}</strong> para el ESP32${e.esp32.mac ? ` (MAC ${escapeHtml(e.esp32.mac)})` : ''}: así no cambian nunca.</span></fieldset>
        <p class="field-error" id="redError" role="alert" hidden></p>
        <div class="row"><button type="submit" class="btn btn-primary btn-sm">Guardar direcciones</button><span class="red-resultado" data-resultado="ip" role="status"></span></div>
      </form></details>`;
  }

  function paint() {
    const body = dlg.querySelector('#redBody');
    const abierto = body.querySelector('.red-ajustes')?.open;
    const editando = body.querySelector('#redForm')?.contains(document.activeElement);
    if (editando) return;  // no se repinta encima de lo que se está escribiendo
    const avisos = estado.avisos.map((a) => `<p class="red-aviso">${icon('info', 'icon-sm')}<span>${escapeHtml(a.texto)}</span></p>`).join('');
    body.innerHTML = `${avisos}${equipo(estado.servidor)}${placa(estado.esp32)}${extension(estado.extension, estado.servidor)}${ajustes(estado)}`;
    if (abierto) body.querySelector('.red-ajustes').open = true;
  }

  async function cargar() {
    try { estado = await api('/api/red', { quiet: true }); paint(); }
    catch (e) {
      if (!estado) showState(dlg.querySelector('#redBody'), { kind: navigator.onLine === false ? 'offline' : 'error', title: 'No se pudo leer la red', text: e.message, compact: true }, cargar);
    }
  }

  function resultado(clave, ok, texto) {
    const out = dlg.querySelector(`[data-resultado="${clave}"]`);
    if (!out) return;
    out.dataset.ok = ok === null ? '' : ok ? '1' : '0';
    out.textContent = texto;
  }

  async function probar(que, boton) {
    const ip = que === 'ip' ? dlg.querySelector('[name="esp32_manual"]').value.trim() : undefined;
    if (que === 'ip' && !ip) { resultado('ip', false, 'Escribe antes una IP'); return; }
    boton.classList.add('is-loading');
    resultado(que, null, 'Probando…');
    try {
      const r = await api('/api/red/probar', { method: 'POST', body: { que, ip }, quiet: true });
      if (que === 'servidor') resultado(que, r.ok, r.pruebas.map((p) => `${p.ok ? '✓' : '✗'} ${p.donde}${p.ok ? ` (${p.ms} ms)` : `: ${p.error}`}`).join(' · '));
      else resultado(que, r.ok, r.ok ? `✓ ${r.host} contesta (${r.ms} ms)` : `✗ ${r.error}`);
      if (que === 'esp32' && r.ok) cargar();
    } catch (e) { resultado(que, false, `✗ ${e.message}`); }
    boton.classList.remove('is-loading');
  }

  async function redetectar(boton) {
    boton.classList.add('is-loading');
    resultado('esp32', null, 'Buscando la placa… (hasta 10 s)');
    try {
      const r = await api('/api/red/redetectar', { method: 'POST', quiet: true });
      estado = r; paint();
      const res = r.resultado;
      resultado('esp32', res.ok, res.ok
        ? `✓ ${res.cambio ? 'Encontrada' : 'Sigue'} en ${res.ip} · ${ORIGEN[res.origen] || res.origen}`
        : `✗ No contesta en ${res.probadas.filter((p) => p[0] !== 'barrido').map((p) => p[1]).join(', ') || 'ninguna dirección'}. ¿Está encendida y en la misma wifi?`);
    } catch (e) { resultado('esp32', false, `✗ ${e.message}`); boton.classList.remove('is-loading'); }
  }

  async function guardar(form) {
    const err = form.querySelector('#redError');
    const body = Object.fromEntries([...new FormData(form)].map(([k, v]) => [k, String(v).trim()]));
    for (const k of ['servidor', 'esp32', 'gateway', 'mascara']) if (!body[k]) delete body[k];  // vacío = se queda como estaba
    const boton = form.querySelector('[type="submit"]');
    boton.classList.add('is-loading');
    form.querySelectorAll('[aria-invalid]').forEach((i) => i.removeAttribute('aria-invalid'));
    try {
      estado = await api('/api/red/ajustes', { method: 'PATCH', body, quiet: true });
      err.hidden = true;
      document.activeElement?.blur();
      paint();
      toast('Direcciones guardadas');
    } catch (e) {
      err.textContent = e.message; err.hidden = false;
      const culpable = Object.keys(body).find((k) => body[k] && e.message.includes(body[k]));
      if (culpable) { const i = form.querySelector(`[name="${culpable}"]`); i.setAttribute('aria-invalid', 'true'); i.focus(); }
    }
    boton.classList.remove('is-loading');
  }

  function open() {
    closeModal('moreSheet');
    if (!dlg) {
      dlg = document.createElement('dialog');
      dlg.className = 'modal red-modal';
      dlg.setAttribute('aria-labelledby', 'redTitle');
      dlg.innerHTML = `<div class="modal-header"><div><h2 id="redTitle">Red y dispositivos</h2>
          <p class="modal-sub">El panel busca y recuerda solo las direcciones. Aquí se ven y se comprueban.</p></div>
          <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
        <div class="modal-body stack" id="redBody"></div>`;
      document.body.appendChild(dlg);
      wireAllDialogs();
      dlg.addEventListener('click', (e) => {
        const p = e.target.closest('[data-probar]');
        if (p) return void probar(p.dataset.probar, p);
        const r = e.target.closest('[data-redetectar]');
        if (r) return void redetectar(r);
        const c = e.target.closest('[data-copiar]');
        if (c) copyText(c.dataset.copiar).then((ok) => (ok ? copied(c, true, 'Dirección copiada') : toast('No se pudo copiar', { type: 'error' })));
      });
      dlg.addEventListener('submit', (e) => { if (e.target.id === 'redForm') { e.preventDefault(); guardar(e.target); } });
      dlg.addEventListener('close', () => { clearInterval(timer); timer = null; });
    }
    openModal(dlg);
    if (estado) paint(); else dlg.querySelector('#redBody').innerHTML = skeletonRows(6);
    cargar();
    clearInterval(timer);
    timer = setInterval(() => { if (!document.hidden && dlg.open) cargar(); }, 15000);
  }

  window.Red = { open };
})();
