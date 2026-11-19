/* ==========================================================================
   facturas.js — facturas de Economía (window.Facturas). Datos y reglas en app/facturas.py (/api/finance/facturas).
   Se suben arrastrando o eligiendo (PDF o foto, hasta 25 MB); cada una se ve en el lector de PDF del panel
   (pdf-visor.js) o en grande si es una imagen, y se descarga con su nombre original. Título, proveedor, fecha,
   importe, categoría, notas y el gasto al que corresponde se cambian en su ficha; borrar va a la papelera.
   Desde un movimiento (su ficha en economia.js) se ven y se adjuntan sus facturas: Facturas.mountForMovement.
   ========================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(String(s ?? ''));
  const eur = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });
  const money = (n) => eur.format(n || 0);
  const MAX = 25 * 1024 * 1024;
  const fmtDay = (d) => (d ? new Date(`${d}T00:00`).toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
  const size = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1).replace('.', ',')} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
  const fileIcon = (f) => (f.pdf ? 'file-text' : f.imagen ? 'image' : 'file');
  const listEl = $('ecFacList');
  let F = { facturas: [], anios: [], total: 0 }, q = '', anio = '';

  /* ---------- Lista ---------- */
  const changed = () => document.dispatchEvent(new CustomEvent('facturas:changed'));
  async function load() {
    if (!listEl) return;
    const qs = new URLSearchParams();
    if (q.trim()) qs.set('q', q.trim());
    if (anio) qs.set('anio', anio);
    try { F = await api(`/api/finance/facturas${qs.size ? `?${qs}` : ''}`, { quiet: true }); } catch {
      showState(listEl, loadFailed('No se pudieron cargar las facturas', true), load);
      return;
    }
    paint();
  }
  function paint() {
    const sel = $('ecFacYear');
    sel.innerHTML = `<option value="">Todos los años</option>${F.anios.map((a) => `<option value="${a}" ${a === anio ? 'selected' : ''}>${a}</option>`).join('')}`;
    $('ecFacN').textContent = F.facturas.length || '';
    if (!F.facturas.length) {
      listEl.innerHTML = q || anio ? `<p class="small muted">Ninguna factura coincide${q ? ` con «${esc(q)}»` : ''}${anio ? ` en ${anio}` : ''}.</p>`
        : '<p class="small muted">Aún no hay facturas. Súbelas aquí (la luz, el móvil, una compra con garantía…) y tenlas siempre a mano para verlas o descargarlas.</p>';
      return;
    }
    listEl.innerHTML = `<ul class="hoy-list ec-fac-list">${F.facturas.map(row).join('')}</ul>
      ${F.total ? `<p class="tiny muted ec-note">Suman ${money(F.total)}${anio ? ` en ${anio}` : ''} (las que tienen importe)</p>` : ''}`;
  }
  function row(f) {
    const sub = [f.proveedor, fmtDay(f.fecha), f.categoria, size(f.bytes || 0)].filter(Boolean).map(esc).join(' · ');
    return `<li class="hoy-row ec-row ec-fac" data-fac="${f.id}">
      <span class="ec-ico ec-fac-ico${f.pdf ? ' is-pdf' : ''}" aria-hidden="true">${icon(fileIcon(f), 'icon-sm')}</span>
      <button type="button" class="hoy-title ec-link ec-mov" data-fac-view="${f.id}" title="Ver «${esc(f.nombre)}»"><span>${esc(f.titulo)}</span><span class="tiny muted">${sub}${f.movimiento ? ` · ${icon('link-2', 'icon-sm')}${esc(f.movimiento.concepto || 'gasto')}` : ''}</span></button>
      <span class="tabular ec-amt">${f.importe != null ? money(f.importe) : ''}</span>
      <a class="btn btn-ghost btn-icon btn-sm" href="${f.url}?descargar=1" download="${esc(f.nombre)}" aria-label="Descargar «${esc(f.titulo)}»" title="Descargar">${icon('download', 'icon-sm')}</a>
      <button type="button" class="btn btn-ghost btn-icon btn-sm" data-fac-menu="${f.id}" aria-label="Más acciones de «${esc(f.titulo)}»" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button></li>`;
  }

  /* ---------- Ver: PDF en el lector, imagen en grande, lo demás se descarga ---------- */
  function view(f) {
    if (f.pdf && window.PdfVisor) {
      PdfVisor.open({ id: `fac${f.id}`, nombre: f.titulo }, { url: f.url, missingText: 'El archivo de esta factura ya no está en el disco.' });
      return;
    }
    if (!f.imagen) { location.href = `${f.url}?descargar=1`; return; }
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-lg ec-fac-img';
    dlg.setAttribute('aria-labelledby', 'ecFacImgT');
    dlg.innerHTML = `<div class="modal-header"><h2 id="ecFacImgT">${esc(f.titulo)}</h2>
        <a class="btn btn-ghost btn-icon" href="${f.url}?descargar=1" download="${esc(f.nombre)}" aria-label="Descargar">${icon('download')}</a>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body"><img src="${f.url}" alt="${esc(f.titulo)}" decoding="async"></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs?.();
    openModal(dlg, { onClose: () => dlg.remove() });
  }

  /* ---------- Subir ---------- */
  async function upload(files, extra = {}) {
    files = [...files];
    const big = files.filter((f) => f.size > MAX);
    if (big.length) toast(`${big.map((f) => f.name).join(', ')}: pasa de 25 MB`, { type: 'error' });
    files = files.filter((f) => f.size <= MAX && f.size > 0);
    if (!files.length) return [];
    const drop = [...($('ecFacDrop')?.querySelectorAll(':scope > span') || [])].find((x) => x.offsetParent), before = drop?.innerHTML;
    const out = [];
    for (const [i, file] of files.entries()) {
      if (drop) drop.textContent = files.length > 1 ? `Subiendo ${i + 1} de ${files.length}…` : `Subiendo ${file.name}…`;
      const fd = new FormData();
      fd.append('archivo', file, file.name);
      Object.entries(extra).forEach(([k, v]) => v != null && fd.append(k, String(v)));
      try { out.push(await api('/api/finance/facturas', { method: 'POST', body: fd })); } catch { /* api avisa */ }
    }
    if (drop) drop.innerHTML = before;
    if (out.length === 1 && !extra.movimiento_id) form(out[0], { nueva: true });
    else if (out.length) toast(`${out.length} facturas guardadas`, { type: 'success' });
    load();
    if (out.length) changed();
    return out;
  }

  /* ---------- Ficha: datos de la factura y el gasto al que corresponde ---------- */
  async function form(f, { nueva = false } = {}) {
    const month = (f.fecha || '').slice(0, 7);
    let movs = [];
    try { movs = month ? (await api(`/api/finance/movements?month=${month}`, { quiet: true })).movements.filter((m) => m.tipo === 'gasto') : []; } catch { /* sin lista */ }
    if (f.movimiento && !movs.some((m) => m.id === f.movimiento_id)) movs.unshift({ ...f.movimiento, tipo: 'gasto' });
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm ec-dialog';
    dlg.setAttribute('aria-labelledby', 'ecFacFormT');
    dlg.innerHTML = `<div class="modal-header"><div><h2 id="ecFacFormT">${nueva ? 'Factura guardada' : 'Factura'}</h2><p class="modal-sub ec-fac-sub">${icon(fileIcon(f), 'icon-sm')}<span>${esc(f.nombre)} · ${size(f.bytes || 0)}</span></p></div>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body stack" id="ecFacForm">
        <label class="field"><span class="field-label">Título</span><input name="titulo" class="input" maxlength="200" required value="${esc(f.titulo)}"></label>
        <div class="rt-form-grid">
          <label class="field"><span class="field-label">Proveedor</span><input name="proveedor" class="input" maxlength="120" placeholder="Endesa, Movistar…" value="${esc(f.proveedor || '')}"></label>
          <label class="field"><span class="field-label">Importe (€)</span><input name="importe" class="input tabular" inputmode="decimal" placeholder="0,00" value="${f.importe != null ? String(f.importe).replace('.', ',') : ''}" autocomplete="off"></label>
        </div>
        <div class="rt-form-grid">
          <label class="field"><span class="field-label">Fecha</span><input name="fecha" type="date" class="input" value="${esc(f.fecha || '')}"></label>
          <label class="field"><span class="field-label">Categoría</span><input name="categoria" class="input" maxlength="60" placeholder="Casa, Salud…" value="${esc(f.categoria || '')}"></label>
        </div>
        <label class="field"><span class="field-label">Gasto al que corresponde <span class="small muted">(del mes de la factura)</span></span>
          <select name="movimiento_id" class="select"><option value="0">Ninguno</option>${movs.map((m) => `<option value="${m.id}" ${m.id === f.movimiento_id ? 'selected' : ''}>${esc(m.concepto || 'Gasto')} · ${money(m.importe)} · ${esc(fmtDay(m.fecha))}</option>`).join('')}</select></label>
        <label class="field"><span class="field-label">Notas</span><textarea name="notas" class="textarea" rows="2" maxlength="5000" placeholder="Garantía hasta…, nº de cliente…">${esc(f.notas || '')}</textarea></label>
      </form>
      <div class="modal-footer"><button type="button" class="btn btn-danger" data-fac-del>${icon('trash-2', 'icon-sm')}Borrar</button><span class="spacer"></span>
        <button type="button" class="btn" data-fac-ver>${icon('eye', 'icon-sm')}Ver</button>
        <button type="submit" form="ecFacForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs?.();
    const fm = dlg.querySelector('form');
    fm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = Object.fromEntries(['titulo', 'proveedor', 'importe', 'fecha', 'categoria', 'notas'].map((k) => [k, fm[k].value]));
      body.movimiento_id = Number(fm.movimiento_id.value) || 0;
      const btn = dlg.querySelector('[type=submit]');
      btn.classList.add('is-loading');
      try { await api(`/api/finance/facturas/${f.id}`, { method: 'PATCH', body }); } catch { btn.classList.remove('is-loading'); return; }
      closeModal(dlg);
      load();
      changed();
    });
    dlg.querySelector('[data-fac-ver]').addEventListener('click', () => view(f));
    dlg.querySelector('[data-fac-del]').addEventListener('click', async () => { closeModal(dlg); remove(f); });
    openModal(dlg, { focus: nueva ? 'input[name=proveedor]' : 'input[name=titulo]', onClose: () => dlg.remove() });
  }

  async function remove(f) {
    let r;
    try { r = await api(`/api/finance/facturas/${f.id}`, { method: 'DELETE' }); } catch { return; }
    load();
    changed();
    undoToast(`«${f.titulo}» en la papelera`, r, () => { load(); changed(); });
  }

  /* ---------- Desde la ficha de un movimiento: sus facturas y «Adjuntar» ---------- */
  async function mountForMovement(el, mov) {
    const paintMov = async () => {
      let list = [];
      try { list = (await api(`/api/finance/facturas?movimiento_id=${mov.id}`, { quiet: true })).facturas; } catch { /* nada */ }
      el.innerHTML = `${list.length ? `<ul class="ec-fac-mini">${list.map((f) => `<li><button type="button" class="link-btn" data-mini-view="${f.id}">${icon(fileIcon(f), 'icon-sm')}${esc(f.titulo)}</button>
          <a class="btn btn-ghost btn-icon btn-sm" href="${f.url}?descargar=1" download="${esc(f.nombre)}" aria-label="Descargar «${esc(f.titulo)}»">${icon('download', 'icon-sm')}</a></li>`).join('')}</ul>` : ''}
        <label class="btn btn-ghost btn-sm ec-fac-up">${icon('paperclip', 'icon-sm')}<span>${list.length ? 'Adjuntar otra' : 'Adjuntar factura'}</span><input type="file" class="sr-only" accept="application/pdf,image/*,.pdf"></label>`;
      el.querySelectorAll('[data-mini-view]').forEach((b) => b.addEventListener('click', () => view(list.find((x) => x.id === Number(b.dataset.miniView)))));
      el.querySelector('input[type=file]').addEventListener('change', async (e) => {
        const files = [...e.target.files];
        if (!files.length) return;
        const done = await upload(files, { movimiento_id: mov.id, fecha: mov.fecha, importe: files.length === 1 ? mov.importe : null, proveedor: '', titulo: files.length === 1 && mov.concepto ? mov.concepto : '' });
        if (done.length) toast(done.length === 1 ? 'Factura adjuntada' : `${done.length} facturas adjuntadas`, { type: 'success', duration: 1600 });
        paintMov();
      });
    };
    paintMov();
  }

  /* ---------- Eventos ---------- */
  if (listEl) {
    listEl.addEventListener('click', (e) => {
      const v = e.target.closest('[data-fac-view]'), m = e.target.closest('[data-fac-menu]');
      const f = (id) => F.facturas.find((x) => x.id === Number(id));
      if (v) view(f(v.dataset.facView));
      if (m) {
        const it = f(m.dataset.facMenu);
        openMenu(m, [
          { label: 'Ver', icon: 'eye', onClick: () => view(it) },
          { label: 'Editar datos', icon: 'pencil', onClick: () => form(it) },
          { label: 'Descargar', icon: 'download', onClick: () => { location.href = `${it.url}?descargar=1`; } },
          { separator: true },
          { label: 'Borrar', icon: 'trash-2', danger: true, onClick: () => remove(it) },
        ]);
      }
    });
    $('ecFacFile').addEventListener('change', (e) => { upload(e.target.files); e.target.value = ''; });
    const drop = $('ecFacDrop');
    ['dragenter', 'dragover'].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add('is-over'); }));
    ['dragleave', 'drop'].forEach((t) => drop.addEventListener(t, () => drop.classList.remove('is-over')));
    drop.addEventListener('drop', (e) => { e.preventDefault(); upload(e.dataTransfer?.files || []); });
    let t = 0;
    $('ecFacQ').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { q = e.target.value; load(); }, 200); });
    $('ecFacYear').addEventListener('change', (e) => { anio = e.target.value; load(); });
    load();
  }

  window.Facturas = { load, upload, view, form, mountForMovement };
})();
