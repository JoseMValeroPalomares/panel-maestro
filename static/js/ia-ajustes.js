/* ============================================================
   Ajustes → IA: estado de cada proveedor, política (entrenan / de pago / presupuesto), notas sensibles,
   botón de prueba y catálogo de modelos. Servicio: app/ia_notas.py (+ app/llm_router.py).
   ============================================================ */
let aiSetDialog = null;

async function openAiSettings() {
  if (!aiSetDialog) {
    aiSetDialog = document.createElement('dialog');
    aiSetDialog.className = 'modal modal-lg ai-modal';
    aiSetDialog.setAttribute('aria-labelledby', 'aiSetTitle');
    aiSetDialog.innerHTML = `
      <div class="modal-header"><div><h2 id="aiSetTitle">IA para corregir notas</h2>
        <p class="modal-sub">Cadena de respaldo: si un modelo falla o se agota, pasa al siguiente. Por defecto solo gratuitos que no entrenan con tus datos.</p></div>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <div class="modal-body stack" id="aiSetBody"></div>
      <div class="modal-footer"><span class="spacer"></span><button type="button" class="btn" data-close>Cerrar</button></div>`;
    document.body.appendChild(aiSetDialog);
    wireAllDialogs();
  }
  openModal(aiSetDialog);
  document.getElementById('aiSetBody').innerHTML = skeletonRows(4);
  await aiSetRender();
}

async function aiSetRender() {
  const body = document.getElementById('aiSetBody');
  let st, hist;
  try { [st, hist] = await Promise.all([api('/api/ia/estado', { quiet: true }), api('/api/ia/historial?limit=8', { quiet: true })]); }
  catch (e) { body.innerHTML = emptyState({ iconName: 'triangle-alert', title: 'No se pudo cargar', text: e.message, compact: true }); return; }
  const p = st.politica;
  const hora = (t) => new Date(t * 1000).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  const filas = st.modelos.map((m) => {
    const insignias = [m.local ? '<span class="badge">local</span>' : '', m.entrena ? '<span class="badge badge-warn" title="Puede usar lo que envías para entrenar">entrena</span>' : '', m.pago ? '<span class="badge badge-warn">de pago</span>' : ''].join(' ');
    const estado = m.clave ? '<span class="ai-ok">Configurado</span>' : `<span class="muted">Sin clave · <code>${escapeHtml(m.clave_env || '')}</code></span>`;
    const uso = m.clave ? `${m.uso_hoy}${m.limite_dia ? '/' + m.limite_dia : ''} hoy · ${m.tokens_mes} tok/mes${m.pago ? ` · ${m.coste_mes.toFixed(2)} $` : ''}` : '';
    const err = m.enfriado_hasta ? `<span class="warn">En pausa hasta ${hora(m.enfriado_hasta)} (${escapeHtml(m.motivo || '')})</span>` : (m.ultimo_error ? `Último error: ${escapeHtml(m.ultimo_error.error)} (${hora(m.ultimo_error.at)})` : '');
    return `<li class="list-row ai-prov"><span class="row-main"><span class="row-title">${escapeHtml(m.proveedor)} ${insignias}</span>
      <span class="row-sub">${escapeHtml(m.modelo_efectivo)} · ${estado}</span>
      ${uso ? `<span class="row-sub">${uso}</span>` : ''}${err ? `<span class="row-sub">${err}</span>` : ''}</span>
      <span class="ai-test"><button type="button" class="btn btn-sm" data-test="${escapeHtml(m.id)}" ${m.clave ? '' : 'disabled'}>Probar</button><span class="tiny" data-result="${escapeHtml(m.id)}" role="status"></span></span></li>`;
  }).join('');
  body.innerHTML = `
    ${st.configurados ? '' : `<p class="callout">Ningún proveedor configurado. Añade una clave a <code>.env</code> (<code>GROQ_API_KEY</code>, <code>OPENROUTER_API_KEY</code>, <code>GITHUB_MODELS_TOKEN</code>…) o <code>OLLAMA_URL=http://IP:11434</code> y reinicia el panel.</p>`}
    <ul class="list ai-provs">${filas}</ul>
    <div class="row row-wrap"><button type="button" class="btn btn-tinted" id="aiCatalog">${icon('refresh-cw', 'icon-sm')}Actualizar catálogo de modelos</button>
      <span class="tiny subtle">Orden y modelos: <code>${escapeHtml(st.archivo)}</code> (copia en <code>data/llm_modelos.json</code> para editarlos)</span></div>
    <fieldset class="field"><legend class="field-label">Política de privacidad</legend>
      <label class="check"><input type="checkbox" class="checkbox" id="aiTrain" ${p.permitir_entrenan ? 'checked' : ''}><span>Permitir proveedores que <strong>pueden entrenar</strong> con mis datos <span class="small muted">(nunca con notas sensibles)</span></span></label>
      <label class="field"><span class="field-label">Categorías sensibles <span class="small muted">(una por línea; sus notas solo van a modelos locales o que no entrenan)</span></span>
        <textarea class="input" id="aiSens" rows="3">${escapeHtml((p.categorias_sensibles || []).join('\n'))}</textarea></label>
      <div class="row"><button type="button" class="btn btn-primary" id="aiSave">Guardar política</button></div></fieldset>
    <div><h3 class="h4">Últimas correcciones</h3>${hist.correcciones.length ? `<ul class="list">${hist.correcciones.map((c) =>
      `<li class="list-row"><span class="row-main"><span class="row-title">${escapeHtml(c.title || c.note_id)}</span><span class="row-sub">${escapeHtml(c.proveedor || '')} · ${escapeHtml(c.modelo || '')} · ${escapeHtml(c.estado)} (${c.aceptadas}/${c.partes})</span></span></li>`).join('')}</ul>` : '<p class="small muted">Aún no has corregido ninguna nota.</p>'}</div>`;
  body.querySelectorAll('[data-test]').forEach((b) => b.addEventListener('click', async () => {
    const out = body.querySelector(`[data-result="${CSS.escape(b.dataset.test)}"]`);
    b.disabled = true; out.textContent = 'Probando…';
    try { const r = await api(`/api/ia/probar/${encodeURIComponent(b.dataset.test)}`, { method: 'POST', quiet: true }); out.textContent = r.ok ? `✓ ${r.latencia_ms} ms` : `✗ ${r.error}`; }
    catch (e) { out.textContent = '✗ ' + e.message; }
    b.disabled = false;
  }));
  document.getElementById('aiCatalog').onclick = async () => { await api('/api/ia/catalogo', { method: 'POST' }); toast('Catálogo actualizado'); aiSetRender(); };
  document.getElementById('aiSave').onclick = async () => {
    await api('/api/ia/politica', { method: 'POST', body: {
      permitir_entrenan: document.getElementById('aiTrain').checked,
      categorias_sensibles: document.getElementById('aiSens').value.split('\n').map((x) => x.trim()).filter(Boolean) } });
    toast('Política guardada'); aiSetRender();
  };
}
