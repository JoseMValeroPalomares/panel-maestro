/* =====================================================================
   Universidad · temas (window.UniTemas), con el contexto de universidad.js (window.Uni):
   - openPropuesta(asig): los temas que propone la carpeta (subcarpetas y documentos sueltos), para
     confirmarlos, renombrarlos, ordenarlos arrastrando, fusionarlos con otro, dejarlos para luego o
     descartarlos. API: GET/POST /api/uni/asignaturas/{id}/escaneo (app/uni_archivos.py).
   - openExplorar({ tema } | { carpeta: true, onPick }): explorador de la raíz en solo lectura para vincular a un
     tema documentos sueltos o carpetas enteras (también de fuera de la carpeta de la asignatura) o elegir una carpeta.
   - openOrganizar(asig): cada documento de la carpeta con su tema y la sugerencia por el número del nombre
     («Chuletario_Tema3», «Relación 4»…), que se aplica de golpe o se cambia una a una; crea «Tema N» si falta.
   - fusionarCon(tema). Los documentos y ejercicios de cada tema se ven en la propia página (universidad.js).
   Nada se escribe en el disco: el panel solo lee las carpetas.
   ===================================================================== */
(function () {
  'use strict';

  const esc = (s) => escapeHtml(s);
  const GRUPOS = { teoria: 'Teoría', practicas: 'Prácticas', otros: 'Otros' };
  const NUM = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 });
  const fmtSize = (b) => (b == null ? '' : b > 1e6 ? `${NUM.format(b / 1e6)} MB` : `${NUM.format(Math.max(1, Math.round(b / 1e3)))} KB`);
  const temasDe = (aid, { con = null } = {}) => Uni.V.temas.filter((t) => t.asignatura_id === aid && (con === null || t.id !== con));

  /* ---------- Propuesta de temas ---------- */
  async function openPropuesta(a) {
    let p;
    try { p = await api(`/api/uni/asignaturas/${a.id}/escaneo`); } catch { return; }
    if (!p.nuevos.length && !p.descartados.length) {
      toast(`${a.codigo}: no hay temas nuevos en la carpeta`, { type: 'info' });
      Uni.load();
      return;
    }
    const destinoOpts = (ruta) => `<option value="">Elige el tema…</option>
      ${p.existentes.length ? `<optgroup label="Temas que ya tienes">${p.existentes.map((t) => `<option value="tema:${t.id}">${esc(t.titulo)}</option>`).join('')}</optgroup>` : ''}
      <optgroup label="De esta lista">${p.nuevos.filter((x) => x.ruta !== ruta).map((x) => `<option value="${esc(x.ruta)}">${esc(x.titulo)}</option>`).join('')}</optgroup>`;
    const sel = (v, cur) => (v === cur ? 'selected' : '');
    const row = (t, i) => `<li class="uni-prop-row" data-ruta="${esc(t.ruta)}" data-accion="${t.accion || 'crear'}" data-destino="${esc(t.destino || '')}">
        <button type="button" class="drag-handle" data-drag-handle aria-label="Mover «${esc(t.titulo)}»">${icon('grip-vertical', 'icon-sm')}</button>
        <div class="uni-prop-main">
          <label class="sr-only" for="up-t${i}">Nombre del tema que sale de «${esc(t.nombre)}»</label>
          <input id="up-t${i}" class="input input-sm" data-f="titulo" maxlength="200" value="${esc(t.titulo)}" required>
          <span class="tiny muted uni-prop-src" title="${esc(t.ruta)}">${icon(t.tipo === 'carpeta' ? 'folder' : 'file-text', 'icon-sm')}<span class="ellipsis">${esc(t.ruta)}</span>
            <span class="tabular">${t.tipo === 'carpeta' ? `· ${t.archivos} doc.${t.pdfs ? ` (${t.pdfs} PDF)` : ''}` : ''}</span></span>
        </div>
        <div class="uni-prop-opts">
          <select class="select input-sm" data-f="accion" aria-label="Qué hacer con «${esc(t.titulo)}»">
            <option value="crear" ${sel('crear', t.accion)}>Crear tema</option><option value="fusionar" ${sel('fusionar', t.accion)}>Fusionar con…</option>
            <option value="luego">Para luego</option><option value="descartar">Descartar</option></select>
          <select class="select input-sm" data-f="grupo" aria-label="Grupo de «${esc(t.titulo)}»">${Object.entries(GRUPOS).map(([g, l]) => `<option value="${g}" ${g === t.grupo ? 'selected' : ''}>${l}</option>`).join('')}</select>
          <select class="select input-sm" data-f="destino" aria-label="Fusionar «${esc(t.titulo)}» con" hidden>${destinoOpts(t.ruta)}</select>
        </div></li>`;
    const res = await Uni.formDialog(`Temas de ${a.codigo} en la carpeta`, `
      <p class="small muted">Cada subcarpeta o documento suelto puede ser un tema. Lo que tiene el mismo número («tema3 – primera
        parte», «tema3 – segunda parte», «lesson3») ya sale fusionado en uno. Arrastra para ordenarlos, cambia el nombre o la
        acción; después, «Organizar documentos» reparte los PDF de carpetas como «Teoria» en su tema. Nada se toca en el disco.</p>
      ${p.nuevos.length ? `<div class="row uni-prop-all"><span class="tiny muted">Todos:</span>
          <button type="button" class="btn btn-ghost btn-sm" data-all="crear">Crear</button>
          <button type="button" class="btn btn-ghost btn-sm" data-all="luego">Para luego</button></div>
        <ol class="uni-prop" data-prop aria-label="Temas propuestos">${p.nuevos.map(row).join('')}</ol>` : '<p class="small">No hay temas nuevos.</p>'}
      ${p.descartados.length ? `<details class="uni-prop-desc"><summary class="small">Descartados antes (${p.descartados.length})</summary>
        <ul class="list">${p.descartados.map((t, i) => `<li class="list-row"><label class="row grow"><input type="checkbox" class="checkbox" data-recuperar="${esc(t.ruta)}" id="ud-r${i}">
          <span class="ellipsis">${esc(t.ruta)}</span></label><span class="tiny muted">Volver a proponer</span></li>`).join('')}</ul></details>` : ''}
      ${p.faltan.length ? `<p class="tiny muted">${icon('triangle-alert', 'icon-sm')} Ya no están en la carpeta (marcados, no borrados): ${p.faltan.map((t) => esc(t.titulo)).join(', ')}.</p>` : ''}`,
    p.nuevos.length ? 'Guardar' : 'Recuperar', {
      size: 'modal-lg',
      onOpen: (dlg) => {
        const list = dlg.querySelector('[data-prop]');
        if (!list) return;
        const sync = (li) => {
          const acc = li.querySelector('[data-f=accion]').value;
          li.dataset.accion = acc;
          li.querySelector('[data-f=destino]').hidden = acc !== 'fusionar';
          li.querySelector('[data-f=grupo]').hidden = acc !== 'crear';
          li.querySelector('[data-f=titulo]').required = acc === 'crear';
        };
        list.querySelectorAll('.uni-prop-row').forEach((li) => {  // lo propuesto por el servidor (fusiones por número)
          const dest = li.querySelector('[data-f=destino]');
          if (li.dataset.destino) dest.value = li.dataset.destino;
          sync(li);
        });
        list.addEventListener('change', (e) => { const li = e.target.closest('.uni-prop-row'); if (li && e.target.matches('[data-f=accion]')) { sync(li); if (li.dataset.accion === 'fusionar') li.querySelector('[data-f=destino]').focus(); } });
        dlg.querySelectorAll('[data-all]').forEach((b) => b.addEventListener('click', () => {
          list.querySelectorAll('.uni-prop-row').forEach((li) => { li.querySelector('[data-f=accion]').value = b.dataset.all; sync(li); });
        }));
        Sortable.create(list, { group: `uni-prop-${a.id}`, items: '.uni-prop-row', handle: '[data-drag-handle]', label: 'Temas propuestos', onDrop: () => {} });
      },
      collect: (form) => {
        const temas = [];
        for (const li of form.querySelectorAll('.uni-prop-row')) {
          const f = (k) => li.querySelector(`[data-f=${k}]`);
          const accion = f('accion').value, destino = f('destino');
          destino.setCustomValidity('');
          if (accion === 'fusionar') {
            const v = destino.value;
            const target = v && !v.startsWith('tema:') ? form.querySelector(`.uni-prop-row[data-ruta="${CSS.escape(v)}"]`) : null;
            if (!v || (target && target.dataset.accion !== 'crear')) {
              destino.setCustomValidity(!v ? 'Elige con qué tema fusionarlo' : 'Ese tema también tiene que crearse');
              destino.reportValidity();
              return false;
            }
          }
          temas.push({ ruta: li.dataset.ruta, titulo: f('titulo').value.trim(), grupo: f('grupo').value, accion, destino: destino.value || null });
        }
        return { temas, recuperar: [...form.querySelectorAll('[data-recuperar]:checked')].map((c) => c.dataset.recuperar) };
      },
    });
    if (!res) return;
    let r;
    try { r = await api(`/api/uni/asignaturas/${a.id}/escaneo`, { method: 'POST', body: res }); } catch { return; }
    const partes = [r.creados && `${r.creados} temas creados`, r.fusionados && `${r.fusionados} fusionados`, r.descartados && `${r.descartados} descartados`,
      r.recuperados && `${r.recuperados} vuelven a proponerse`, r.por_confirmar && `${r.por_confirmar} para luego`].filter(Boolean);
    toast(`${a.codigo}: ${partes.join(', ') || 'sin cambios'}`);
    Uni.load();
  }

  /* ---------- Explorador de la raíz (solo lectura): añadir documentos a un tema o elegir una carpeta ---------- */
  function openExplorar({ tema = null, carpeta = false, inicio = null, onPick = null } = {}) {
    const a = tema ? Uni.asig(tema.asignatura_id) : null;
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-lg uni-dialog uni-explorar';
    dlg.setAttribute('aria-labelledby', 'uexT');
    dlg.innerHTML = `<div class="modal-header"><div><h2 id="uexT">${carpeta ? 'Elegir carpeta' : `Añadir documentos a «${esc(tema.titulo)}»`}</h2>
        <p class="modal-sub">${carpeta ? 'Dentro de la carpeta raíz de la universidad. Solo se lee.' : 'Cualquier documento de la carpeta raíz, también de otras carpetas. El disco no se toca: solo se ve aquí.'}</p></div>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body stack"><nav class="uex-migas" aria-label="Carpeta actual" data-migas></nav><div data-lista aria-live="polite"><span class="skeleton skeleton-card"></span></div></div>
      <div class="modal-footer">${carpeta ? '' : '<span class="tiny muted" data-sel-info></span>'}<span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button>
        <button type="button" class="btn btn-primary" data-ok ${carpeta ? '' : 'disabled'}>${carpeta ? 'Elegir esta carpeta' : 'Añadir'}</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs?.();
    const sel = new Set(), carpetas = new Set();
    let data = null, ruta = inicio ?? null;

    async function ir(r) {
      const qs = new URLSearchParams();
      if (r) qs.set('ruta', r);
      if (a) qs.set('asignatura', a.id);
      try { data = await api(`/api/uni/explorar?${qs}`, { quiet: true }); } catch (e) {
        if (r) return ir('');  // la carpeta ya no existe: a la raíz
        showState(dlg.querySelector('[data-lista]'), loadFailed(e?.message || 'No se puede leer la carpeta raíz', false));
        return;
      }
      if (ruta === null && !r && data.inicio) return ir(data.inicio);  // empieza en la carpeta de la asignatura
      ruta = data.ruta;
      pintar();
      dlg.querySelector('[data-lista] button, [data-lista] input')?.focus();
    }
    function pintar() {
      const migas = [{ nombre: 'Raíz', ruta: '' }, ...data.migas];
      dlg.querySelector('[data-migas]').innerHTML = migas.map((m, i) => (i === migas.length - 1
        ? `<span aria-current="location">${i ? esc(m.nombre) : `${icon('house', 'icon-sm')}Raíz`}</span>`
        : `<button type="button" class="link-btn" data-ir="${esc(m.ruta)}">${i ? esc(m.nombre) : `${icon('house', 'icon-sm')}Raíz`}</button>`)).join(`<span aria-hidden="true">${icon('chevron-right', 'icon-sm')}</span>`);
      const todo = !carpeta && data.ruta && data.archivos.length;
      dlg.querySelector('[data-lista]').innerHTML = `<ul class="list uex-list" aria-label="Contenido de ${esc(data.ruta || 'la raíz')}">
        ${data.ruta ? `<li class="list-row"><button type="button" class="uex-dir" data-ir="${esc(data.ruta.split('/').slice(0, -1).join('/'))}">${icon('corner-left-up', 'icon-sm')}<span>Subir</span></button></li>` : ''}
        ${data.carpetas.map((c) => `<li class="list-row"><button type="button" class="uex-dir" data-ir="${esc(c.ruta)}">${icon('folder', 'icon-sm')}<span class="ellipsis">${esc(c.nombre)}</span>${icon('chevron-right', 'icon-sm uex-chev')}</button></li>`).join('')}
        ${data.archivos.map((f, i) => {
          const aqui = f.vinculado?.tema_id === tema?.id;
          return `<li class="list-row uex-file${carpeta ? ' is-dim' : ''}">${carpeta ? `${icon('file-text', 'icon-sm')}<span class="grow ellipsis">${esc(f.nombre)}</span>`
            : `<input type="checkbox" class="checkbox" id="uex${i}" data-ruta="${esc(f.ruta)}" ${aqui || sel.has(f.ruta) ? 'checked' : ''} ${aqui ? 'disabled' : ''}>
              <label for="uex${i}" class="grow uex-name">${icon('file-text', 'icon-sm')}<span class="ellipsis">${esc(f.nombre)}</span></label>
              ${f.vinculado ? `<span class="tag uex-tag${aqui ? ' is-here' : ''}" title="${aqui ? 'Ya está en este tema' : `Ahora en «${esc(f.vinculado.titulo)}»: se moverá aquí`}">${aqui ? 'Ya está' : esc(f.vinculado.titulo || '')}</span>` : ''}`}
            <span class="tiny muted tabular">${fmtSize(f.bytes)}</span></li>`;
        }).join('')}</ul>
        ${!data.carpetas.length && !data.archivos.length ? '<p class="small muted">Carpeta vacía (o sin documentos: PDF, Word, presentaciones, apuntes…).</p>' : ''}
        ${data.truncado ? '<p class="tiny muted">Hay muchas entradas: se enseñan las primeras.</p>' : ''}
        ${todo ? `<label class="row uex-all"><input type="checkbox" class="checkbox" data-toda ${carpetas.has(data.ruta) ? 'checked' : ''}><span class="small">Toda esta carpeta (también sus subcarpetas)</span></label>` : ''}`;
      info();
    }
    function info() {
      if (carpeta) return;
      const n = sel.size, c = carpetas.size;
      dlg.querySelector('[data-sel-info]').textContent = n || c ? [n && `${n} ${n === 1 ? 'documento' : 'documentos'}`, c && `${c} ${c === 1 ? 'carpeta' : 'carpetas'}`].filter(Boolean).join(' y ') : 'Marca los documentos que van en este tema';
      const ok = dlg.querySelector('[data-ok]');
      ok.disabled = !n && !c;
      ok.textContent = n || c ? 'Añadir al tema' : 'Añadir';
    }
    dlg.addEventListener('click', (e) => {
      const b = e.target.closest('[data-ir]');
      if (b) ir(b.dataset.ir);
    });
    dlg.addEventListener('change', (e) => {
      const cb = e.target;
      if (cb.dataset.ruta) { if (cb.checked) sel.add(cb.dataset.ruta); else sel.delete(cb.dataset.ruta); }
      if (cb.dataset.toda !== undefined) { if (cb.checked) carpetas.add(data.ruta); else carpetas.delete(data.ruta); }
      info();
    });
    dlg.querySelector('[data-ok]').addEventListener('click', async (e) => {
      if (carpeta) { onPick?.(data.ruta); closeModal(dlg); return; }
      const btn = e.currentTarget;
      btn.classList.add('is-loading');
      try {
        const body = { rutas: [...sel], carpetas: [...carpetas] };
        const r = await api(`/api/uni/temas/${tema.id}/vincular`, { method: 'POST', body });
        const n = r.nuevos + r.movidos;
        toast(n ? `${n} ${n === 1 ? 'documento añadido' : 'documentos añadidos'} a «${tema.titulo}»` : 'Ya estaban en el tema', { type: n ? 'success' : 'info' });
        closeModal(dlg);
        Uni.load();
      } catch { /* api avisa */ } finally { btn.classList.remove('is-loading'); }
    });
    openModal(dlg, { focus: '[data-close]', onClose: () => dlg.remove() });
    ir(ruta || '');
  }

  /* ---------- Organizar: cada documento con su tema y la sugerencia por su número ---------- */
  async function openOrganizar(a) {
    if (!a) return;
    let p;
    try { p = await api(`/api/uni/asignaturas/${a.id}/organizar`); } catch { return; }
    if (!p.archivos.length) { toast(a.carpeta ? `${a.codigo}: no hay documentos en su carpeta` : `${a.codigo} no tiene carpeta: añade documentos desde cada tema`, { type: 'info' }); return; }
    const original = (x) => (x.tema_id ? `tema:${x.tema_id}` : '');
    const inicial = (x) => x.sugerido || original(x);
    const temasOpts = ['teoria', 'otros', 'practicas'].map((g) => {
      const ts = p.temas.filter((t) => t.grupo === g);
      return ts.length ? `<optgroup label="${GRUPOS[g]}">${ts.map((t) => `<option value="tema:${t.id}">${esc(t.titulo)}</option>`).join('')}</optgroup>` : '';
    }).join('') + (Object.keys(p.nuevos).length ? `<optgroup label="Temas nuevos">${Object.entries(p.nuevos).map(([k, n]) => `<option value="nuevo:${k}" data-nuevo="${k}">${esc(n.titulo)} (nuevo)</option>`).join('')}</optgroup>` : '');
    const porCarpeta = {};
    p.archivos.forEach((x, i) => { (porCarpeta[x.carpeta || '(en la carpeta de la asignatura)'] ||= []).push([x, i]); });
    const filtro0 = p.sugerencias ? 'sugeridos' : p.sin_tema ? 'sin' : 'todos';
    const res = await Uni.formDialog(`Organizar los documentos de ${a.codigo}`, `
      <p class="small muted">Cada documento con su tema. ${p.sugerencias ? `Las <b>${p.sugerencias} sugerencias</b> (por el número del nombre: «Tema 4», «Relación 4», «pr2»…) ya están puestas: revísalas y guarda.` : 'Cambia el tema de los que quieras.'} En el disco no se mueve nada.</p>
      ${Object.keys(p.nuevos).length ? `<fieldset class="field uni-org-nuevos"><legend class="field-label">Temas que se crearán (cámbiales el nombre si quieres)</legend>
        <div class="uni-org-nuevos-list">${Object.entries(p.nuevos).map(([k, n]) => `<label class="uni-org-nuevo" data-nuevo-row="${k}"><span class="sr-only">Nombre del tema nuevo ${esc(n.titulo)}</span><input class="input input-sm" name="titulo_${k}" maxlength="200" value="${esc(n.titulo)}"></label>`).join('')}</div></fieldset>` : ''}
      <div class="row uni-org-bar">
        <div class="segmented" role="group" aria-label="Qué documentos ver">
          <button type="button" data-filtro="sugeridos" aria-pressed="${filtro0 === 'sugeridos'}">Con sugerencia <span class="count tabular">${p.sugerencias}</span></button>
          <button type="button" data-filtro="sin" aria-pressed="${filtro0 === 'sin'}">Sin tema <span class="count tabular">${p.sin_tema}</span></button>
          <button type="button" data-filtro="todos" aria-pressed="${filtro0 === 'todos'}">Todos <span class="count tabular">${p.archivos.length}</span></button></div>
        <span class="grow"></span>
        ${p.sugerencias ? `<button type="button" class="btn btn-ghost btn-sm" data-sug="0">${icon('undo-2', 'icon-sm')}Sin sugerencias</button>
          <button type="button" class="btn btn-ghost btn-sm" data-sug="1" hidden>${icon('wand-sparkles', 'icon-sm')}Poner sugerencias</button>` : ''}
      </div>
      <div class="uni-org" data-org>${Object.entries(porCarpeta).map(([c, rows]) => `<section class="uni-org-dir"><h3 class="uni-group-title">${icon('folder', 'icon-sm')}${esc(c)}</h3>
        <ul class="list">${rows.map(([x, i]) => `<li class="list-row uni-org-row" data-i="${i}" data-sug="${x.sugerido ? 1 : 0}" data-sin="${x.tema_id ? 0 : 1}">
          <span class="grow uni-org-name"><span class="ellipsis" title="${esc(x.ruta)}">${esc(x.nombre)}</span>
            ${x.sugerido ? `<span class="tag uni-org-sug">${icon('wand-sparkles', 'icon-sm')}Sugerido</span>` : ''}${x.quitado ? '<span class="tag">Quitado</span>' : ''}</span>
          <label class="sr-only" for="uorg${i}">Tema de ${esc(x.nombre)}</label>
          <select id="uorg${i}" class="select input-sm" data-i="${i}"><option value="">${x.tema_id ? '— Quitar del tema —' : '— Sin tema —'}</option>${temasOpts}</select></li>`).join('')}</ul></section>`).join('')}</div>`, 'Guardar', {
      size: 'modal-lg',
      onOpen: (dlg) => {
        const sels = [...dlg.querySelectorAll('select[data-i]')];
        const marcar = () => {
          const usados = new Set(sels.map((s2) => s2.value).filter((v) => v.startsWith('nuevo:')).map((v) => v.slice(6)));
          dlg.querySelectorAll('[data-nuevo-row]').forEach((l) => { l.hidden = !usados.has(l.dataset.nuevoRow); });
          sels.forEach((s2) => s2.closest('li').classList.toggle('is-changed', s2.value !== original(p.archivos[Number(s2.dataset.i)])));
        };
        sels.forEach((s2) => { s2.value = inicial(p.archivos[Number(s2.dataset.i)]); });
        const filtrar = (f) => {
          dlg.querySelectorAll('[data-filtro]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.filtro === f)));
          dlg.querySelectorAll('.uni-org-row').forEach((li) => { li.hidden = (f === 'sugeridos' && li.dataset.sug !== '1') || (f === 'sin' && li.dataset.sin !== '1'); });
          dlg.querySelectorAll('.uni-org-dir').forEach((sec) => { sec.hidden = ![...sec.querySelectorAll('.uni-org-row')].some((li) => !li.hidden); });
        };
        filtrar(filtro0);
        marcar();
        dlg.addEventListener('change', (e) => { if (e.target.matches('select[data-i]')) marcar(); });
        dlg.querySelectorAll('[data-filtro]').forEach((b) => b.addEventListener('click', () => filtrar(b.dataset.filtro)));
        dlg.querySelectorAll('[data-sug]').forEach((b) => b.addEventListener('click', () => {
          const poner = b.dataset.sug === '1';
          sels.forEach((s2) => { const x = p.archivos[Number(s2.dataset.i)]; s2.value = poner ? inicial(x) : original(x); });
          dlg.querySelectorAll('[data-sug]').forEach((x) => { x.hidden = x.dataset.sug === b.dataset.sug; });
          marcar();
        }));
      },
      collect: (form) => {
        const cambios = [];
        form.querySelectorAll('select[data-i]').forEach((s2) => {
          const x = p.archivos[Number(s2.dataset.i)];
          if (s2.value === original(x)) return;
          cambios.push({ ruta: x.ruta, destino: s2.value || 'quitar' });
        });
        const titulos = Object.fromEntries(Object.keys(p.nuevos).map((k) => [k, form.querySelector(`[name="titulo_${k}"]`)?.value.trim() || p.nuevos[k].titulo]));
        return { cambios, titulos };
      },
    });
    if (!res) return;
    if (!res.cambios.length) { toast('Sin cambios', { type: 'info' }); return; }
    let r;
    try { r = await api(`/api/uni/asignaturas/${a.id}/organizar`, { method: 'POST', body: res }); } catch { return; }
    toast([r.temas_creados && `${r.temas_creados} ${r.temas_creados === 1 ? 'tema nuevo' : 'temas nuevos'}`, r.movidos && `${r.movidos} ${r.movidos === 1 ? 'documento en su tema' : 'documentos en su tema'}`,
      r.quitados && `${r.quitados} quitados`].filter(Boolean).join(' · ') || 'Sin cambios');
    Uni.load();
  }

  /* ---------- Fusionar ---------- */
  async function fusionarCon(t) {
    const otros = temasDe(t.asignatura_id, { con: t.id });
    if (!otros.length) { toast('No hay otro tema en esta asignatura', { type: 'info' }); return false; }
    const r = await Uni.formDialog(`Fusionar «${t.titulo}»`, `
      <label class="field"><span class="field-label">Con el tema</span><select name="destino" class="select">${otros.map((x) => `<option value="${x.id}">${esc(x.titulo)}</option>`).join('')}</select></label>
      <p class="small muted">«${esc(t.titulo)}» deja de verse como tema aparte: sus archivos, ejercicios y tareas pasan al elegido. Se puede separar después; en el disco no cambia nada.</p>`, 'Fusionar');
    if (!r) return false;
    const destino = Number(r.destino);
    try { await api(`/api/uni/temas/${t.id}/fusionar`, { method: 'POST', body: { destino_id: destino } }); } catch { return false; }
    toast(`Fusionado con «${otros.find((x) => x.id === destino)?.titulo}»`, { action: { label: 'Separar', onClick: () => api(`/api/uni/temas/${t.id}/separar`, { method: 'POST' }).then(Uni.load) } });
    Uni.load();
    return true;
  }

  window.UniTemas = { openPropuesta, openExplorar, openOrganizar, fusionarCon };
})();
