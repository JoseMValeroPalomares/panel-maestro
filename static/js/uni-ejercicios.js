/* =====================================================================
   Universidad · ejercicios (window.UniEjercicios), con el contexto de universidad.js (window.Uni).
   - render(content): pestaña «Ejercicios», como la de temas: una sección por asignatura, en lista o por
     tema, con filtros de tema, estado (pendiente / hecho) y dificultad; la búsqueda y los chips de
     asignatura son los de la página.
   - rowHTML / handle: la fila de un ejercicio y sus acciones (también en la ficha de cada tema).
   - openEditor(ej | {asignatura_id, temas}, after): crear y editar (temas, dificultad, PDF y página).
   API: /api/uni/ejercicios (app/uni_ejercicios.py).
   ===================================================================== */
(function () {
  'use strict';

  const esc = (s) => escapeHtml(s);
  const DIF = { 1: 'Fácil', 2: 'Media', 3: 'Difícil' };
  const VISTA_KEY = 'uni-ej-vista';
  const F = { tema: 0, estado: '', dificultad: '' };
  let pintando = 0;

  const temaTitulo = (id) => Uni.V.temas.find((t) => t.id === id)?.titulo;

  /* ---------- Fila ---------- */
  function rowHTML(e, { tema = null } = {}) {
    const hecho = e.estado === 'hecho';
    const otros = e.temas.filter((id) => id !== tema).map(temaTitulo).filter(Boolean);
    const linea = (e.enunciado || '').split('\n').find((l) => l.trim()) || '';
    return `<li class="list-row uni-ej${hecho ? ' is-done' : ''}" data-ej="${e.id}">
      <button type="button" class="card-check small-check${hecho ? ' done' : ''}" data-ej-check role="checkbox" aria-checked="${hecho}" aria-label="${hecho ? 'Volver a pendiente' : 'Hecho'}: ${esc(e.titulo)}">${icon('check', 'icon-sm')}</button>
      <span class="row-main"><button type="button" class="link-btn row-title" data-ej-edit>${esc(e.titulo)}</button>
        ${linea || otros.length ? `<span class="row-sub">${esc(linea)}${linea && otros.length ? ' · ' : ''}${otros.map((x) => `<span class="uni-ej-tema">${esc(x)}</span>`).join(' ')}</span>` : ''}</span>
      ${e.dificultad ? `<span class="tag uni-dif" data-dif="${e.dificultad}">${DIF[e.dificultad]}</span>` : ''}
      ${e.archivo ? `<button type="button" class="btn btn-ghost btn-sm uni-ej-pdf" data-ej-pdf ${e.archivo.falta ? 'disabled' : ''} title="${esc(e.archivo.nombre)}${e.pagina ? `, página ${e.pagina}` : ''}${e.archivo.falta ? ' (no encontrado)' : ''}" aria-label="Abrir ${esc(e.archivo.nombre)}${e.pagina ? ` en la página ${e.pagina}` : ''}">${icon('file-text', 'icon-sm')}${e.pagina ? `<span class="tabular">p. ${e.pagina}</span>` : 'PDF'}</button>` : ''}
    </li>`;
  }

  // Acciones de una fila (data-* del botón pulsado); after() repinta quien la muestra
  async function handle(d, e, after) {
    if (!e) return;
    if (d.ejCheck !== undefined) {
      await api(`/api/uni/ejercicios/${e.id}`, { method: 'PATCH', quiet: true, body: { estado: e.estado === 'hecho' ? 'pendiente' : 'hecho' } });
      return after();
    }
    if (d.ejEdit !== undefined) return openEditor(e, after);
    if (d.ejPdf !== undefined && e.archivo) {
      const info = await api(`/api/uni/archivos/${e.archivo.id}/info`, { quiet: true }).catch(() => null);
      if (!info) return;
      if (!info.visor) { window.open(PdfVisor.url(info.id), '_blank', 'noopener'); return; }
      PdfVisor.open({ ...info, pagina: e.pagina || info.pagina }, { onClose: after });
    }
  }

  /* ---------- Pestaña ---------- */
  async function render(content) {
    const vista = Prefs.get(VISTA_KEY, 'lista');
    const asigs = Uni.activas().filter((a) => !Uni.asigFilter || a.id === Uni.asigFilter);
    if (F.tema && !Uni.V.temas.some((t) => t.id === F.tema && asigs.some((a) => a.id === t.asignatura_id))) F.tema = 0;
    const seg = (name, label, opts, val) => `<div class="segmented" role="group" aria-label="${label}">${opts.map(([v, l]) => `<button type="button" data-${name}="${v}" aria-pressed="${String(v) === String(val)}">${l}</button>`).join('')}</div>`;
    content.innerHTML = `<div class="row uni-toolbar uni-ej-toolbar">
        <button type="button" class="btn btn-tinted btn-sm" data-ej-new>${icon('plus', 'icon-sm')}Ejercicio</button>
        <label class="sr-only" for="uniEjTema">Tema</label>
        <select id="uniEjTema" class="select input-sm"><option value="0">Todos los temas</option>${asigs.map((a) => {
          const ts = Uni.V.temas.filter((t) => t.asignatura_id === a.id);
          return ts.length ? `<optgroup label="${esc(a.codigo)}">${ts.map((t) => `<option value="${t.id}" ${t.id === F.tema ? 'selected' : ''}>${esc(t.titulo)}</option>`).join('')}</optgroup>` : '';
        }).join('')}</select>
        ${seg('f-estado', 'Estado', [['', 'Todos'], ['pendiente', 'Pendientes'], ['hecho', 'Hechos']], F.estado)}
        ${seg('f-dif', 'Dificultad', [['', 'Cualquiera'], ['1', 'Fácil'], ['2', 'Media'], ['3', 'Difícil']], F.dificultad)}
        ${seg('f-vista', 'Agrupar', [['lista', 'Lista'], ['tema', 'Por tema']], vista)}
      </div><div data-ej-list aria-live="polite"><span class="skeleton skeleton-card"></span></div>`;
    const token = ++pintando;
    const qs = new URLSearchParams();
    if (Uni.asigFilter) qs.set('asignatura', Uni.asigFilter);
    if (F.tema) qs.set('tema', F.tema);
    if (F.estado) qs.set('estado', F.estado);
    if (F.dificultad) qs.set('dificultad', F.dificultad);
    if (Uni.q) qs.set('q', Uni.q);
    let r;
    try { r = await api(`/api/uni/ejercicios?${qs}`, { quiet: true }); } catch {
      showState(content.querySelector('[data-ej-list]'), loadFailed('No se pudieron cargar los ejercicios', true), () => render(content));
      return;
    }
    if (token !== pintando || !content.isConnected) return;
    const listEl = content.querySelector('[data-ej-list]');
    const filtrando = F.tema || F.estado || F.dificultad || Uni.q;
    const secciones = asigs.map((a) => {
      const mios = r.ejercicios.filter((e) => e.asignatura_id === a.id);
      if (!mios.length && filtrando) return '';
      const hechos = mios.filter((e) => e.estado === 'hecho').length;
      let cuerpo;
      if (!mios.length) cuerpo = `<p class="small muted uni-hint">Sin ejercicios. <button type="button" class="link-btn" data-ej-new="${a.id}">Añade el primero</button>.</p>`;
      else if (vista === 'tema') {
        const temas = Uni.V.temas.filter((t) => t.asignatura_id === a.id && (!F.tema || t.id === F.tema));
        const grupos = temas.map((t) => [t, mios.filter((e) => e.temas.includes(t.id))]).filter(([, l]) => l.length);
        const sin = F.tema ? [] : mios.filter((e) => !e.temas.length);
        cuerpo = grupos.map(([t, l]) => `<div class="uni-group"><h3 class="uni-group-title">${esc(t.titulo)} <span class="count">${l.filter((e) => e.estado === 'hecho').length}/${l.length}</span></h3>
            <ul class="list uni-ejs">${l.map((e) => rowHTML(e, { tema: t.id })).join('')}</ul></div>`).join('')
          + (sin.length ? `<div class="uni-group"><h3 class="uni-group-title">Sin tema <span class="count">${sin.length}</span></h3><ul class="list uni-ejs">${sin.map((e) => rowHTML(e)).join('')}</ul></div>` : '');
      } else cuerpo = `<ul class="list uni-ejs">${mios.map((e) => rowHTML(e)).join('')}</ul>`;
      return `<section class="uni-subject" style="--subj:${Uni.color(a)}" aria-labelledby="uej-h-${a.id}">
        <h2 class="cat-header" id="uej-h-${a.id}"><span class="dot" style="background:${Uni.color(a)}"></span><span class="uni-code">${esc(a.codigo)}</span><span class="uni-name">${esc(a.nombre)}</span>
          <span class="count tabular" title="Hechos de los que se ven">${hechos}/${mios.length}</span>
          ${mios.length ? `<span class="uni-bar uni-bar-head" aria-hidden="true"><span style="width:${Math.round((hechos / mios.length) * 100)}%"></span></span>` : ''}</h2>
        <div class="uni-subject-body">${cuerpo}</div></section>`;
    }).join('');
    listEl.innerHTML = secciones || emptyState({ iconName: 'pencil-ruler', title: filtrando ? 'Ningún ejercicio coincide' : 'Sin ejercicios',
      text: filtrando ? 'Prueba con otro filtro o quita la búsqueda.' : 'Apunta los ejercicios de cada tema (boletines, exámenes de otros años) y márcalos al hacerlos.',
      actionLabel: filtrando ? '' : 'Nuevo ejercicio', action: 'ej-new' });

    const repaint = () => Uni.load();  // recarga la página entera, que vuelve a pintar esta pestaña
    content.querySelector('#uniEjTema').addEventListener('change', (ev) => { F.tema = Number(ev.target.value); render(content); });
    content.querySelector('.uni-ej-toolbar').addEventListener('click', (ev) => {
      const b = ev.target.closest('button');
      if (!b) return;
      if (b.dataset.fEstado !== undefined) { F.estado = b.dataset.fEstado; return render(content); }
      if (b.dataset.fDif !== undefined) { F.dificultad = b.dataset.fDif; return render(content); }
      if (b.dataset.fVista !== undefined) { Prefs.set(VISTA_KEY, b.dataset.fVista); return render(content); }
    });
    content.querySelectorAll('[data-ej-new], [data-empty-action="ej-new"]').forEach((b) => b.addEventListener('click', () => {
      const aid = Number(b.dataset.ejNew) || Uni.asigFilter || (F.tema && Uni.V.temas.find((t) => t.id === F.tema)?.asignatura_id) || Uni.activas()[0]?.id;
      if (!aid) { toast('Crea antes una asignatura', { type: 'info' }); return; }
      openEditor({ asignatura_id: aid, temas: F.tema ? [F.tema] : [] }, repaint);
    }));
    listEl.addEventListener('click', (ev) => {
      const b = ev.target.closest('button');
      const li = b?.closest('[data-ej]');
      if (!li) return;
      handle(b.dataset, r.ejercicios.find((x) => x.id === Number(li.dataset.ej)), repaint);
    });
  }

  /* ---------- Editor ---------- */
  async function openEditor(e, after) {
    const nuevo = !e.id;
    let aid = e.asignatura_id;
    const archivos = {};
    const loadArchivos = async (id) => (archivos[id] ||= (await api(`/api/uni/asignaturas/${id}/archivos`, { quiet: true }).catch(() => ({ archivos: [] }))).archivos);
    const temasHTML = (id, sel) => {
      const ts = Uni.V.temas.filter((t) => t.asignatura_id === id);
      return ts.length ? `<div class="uni-temas-pick">${ts.map((t) => `<label class="row tiny"><input type="checkbox" class="checkbox" name="tema" value="${t.id}" ${sel.includes(t.id) ? 'checked' : ''}>${esc(t.titulo)}</label>`).join('')}</div>`
        : '<p class="tiny muted">Esta asignatura aún no tiene temas.</p>';
    };
    const pdfHTML = (lista, sel) => `<option value="">— Ninguno —</option>${[...new Set(lista.map((f) => f.tema_titulo))].map((tt) => `<optgroup label="${esc(tt)}">${lista.filter((f) => f.tema_titulo === tt).map((f) => `<option value="${f.id}" ${f.id === sel ? 'selected' : ''}>${esc(f.nombre)}${f.falta ? ' (no encontrado)' : ''}</option>`).join('')}</optgroup>`).join('')}`;
    const lista = await loadArchivos(aid);
    const res = await Uni.formDialog(nuevo ? 'Nuevo ejercicio' : 'Ejercicio', `
      ${nuevo ? `<label class="field"><span class="field-label">Asignatura</span><select name="asig" class="select" data-asig>${Uni.activas().map((a) => `<option value="${a.id}" ${a.id === aid ? 'selected' : ''}>${esc(a.codigo)} · ${esc(a.nombre)}</option>`).join('')}</select></label>` : ''}
      <label class="field"><span class="field-label">Título</span><input name="titulo" class="input" required maxlength="300" value="${esc(e.titulo || '')}" placeholder="Boletín 2, ejercicio 4…"></label>
      <label class="field"><span class="field-label">Enunciado <span class="muted">(opcional)</span></span><textarea name="enunciado" class="textarea" rows="3" maxlength="20000">${esc(e.enunciado || '')}</textarea></label>
      <fieldset class="field"><legend class="field-label">Temas</legend><div data-temas>${temasHTML(aid, e.temas || [])}</div></fieldset>
      <fieldset class="field"><legend class="field-label">Dificultad</legend><div class="choice-chips">${[['0', 'Sin indicar'], ['1', 'Fácil'], ['2', 'Media'], ['3', 'Difícil']].map(([v, l]) => `<label class="choice-chip"><input type="radio" name="dificultad" value="${v}" ${String(e.dificultad || 0) === v ? 'checked' : ''}><span>${l}</span></label>`).join('')}</div></fieldset>
      <div class="row uni-ej-donde"><label class="field grow"><span class="field-label">Está en el PDF</span><select name="archivo" class="select" data-pdf>${pdfHTML(lista, e.archivo?.id)}</select></label>
        <label class="field"><span class="field-label">Página</span><input name="pagina" type="number" min="1" max="100000" class="input uni-ej-pag" value="${e.pagina || ''}"></label></div>
      <label class="field"><span class="field-label">Notas o solución <span class="muted">(opcional)</span></span><textarea name="notas" class="textarea" rows="3" maxlength="20000">${esc(e.notas || '')}</textarea></label>
      <label class="row small"><input type="checkbox" class="checkbox" name="hecho" ${e.estado === 'hecho' ? 'checked' : ''}>Hecho</label>`,
    nuevo ? 'Crear' : 'Guardar', {
      size: '',
      danger: nuevo ? null : 'Borrar',
      onOpen: (dlg) => dlg.querySelector('[data-asig]')?.addEventListener('change', async (ev) => {
        aid = Number(ev.target.value);
        dlg.querySelector('[data-temas]').innerHTML = temasHTML(aid, []);
        dlg.querySelector('[data-pdf]').innerHTML = pdfHTML(await loadArchivos(aid), null);
      }),
    });
    if (!res) return;
    if (res === 'danger') {
      const r = await api(`/api/uni/ejercicios/${e.id}`, { method: 'DELETE' });
      undoToast('Ejercicio en la papelera', r, after);
      return after?.();
    }
    const body = {
      titulo: res.titulo.trim(), enunciado: res.enunciado, notas: res.notas, temas: res.tema,
      dificultad: Number(res.dificultad) || (nuevo ? null : 0), estado: res.hecho ? 'hecho' : 'pendiente',
      archivo_id: Number(res.archivo) || (nuevo ? null : 0), pagina: Number(res.pagina) || (nuevo ? null : 0),
    };
    try {
      if (nuevo) await api('/api/uni/ejercicios', { method: 'POST', body: { ...body, asignatura_id: aid } });
      else await api(`/api/uni/ejercicios/${e.id}`, { method: 'PATCH', body });
    } catch { return; }
    toast(nuevo ? 'Ejercicio creado' : 'Ejercicio guardado');
    after?.();
  }

  window.UniEjercicios = { render, rowHTML, handle, openEditor };
})();
