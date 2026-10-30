/* ==========================================================================
   economia.js — página /economia: tu dinero (cuentas), el mes (gastos por categoría y 6 meses),
   deudas, lista de deseos y movimientos. Datos y reglas en app/finance.py (/api/finance).
   ========================================================================== */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (s) => escapeHtml(String(s ?? ''));
  const eur = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR' });
  const money = (n) => eur.format(n || 0);
  const pad = (n) => String(n).padStart(2, '0');
  const thisMonth = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}`; };
  const shift = (m, k) => { const [y, mm] = m.split('-').map(Number); const i = y * 12 + mm - 1 + k; return `${Math.floor(i / 12)}-${pad(i % 12 + 1)}`; };
  const monthName = (m, opts = { month: 'long', year: 'numeric' }) => { const [y, mm] = m.split('-').map(Number); return new Date(y, mm - 1, 1).toLocaleDateString('es-ES', opts); };
  const dayName = (d) => { const [y, m, dd] = d.split('-').map(Number); return new Date(y, m - 1, dd).toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long' }); };
  const cap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
  const CAT_ICON = { Comida: 'utensils', Supermercado: 'shopping-cart', Transporte: 'bus', Ocio: 'film', Universidad: 'graduation-cap', Casa: 'house',
    Ropa: 'shirt', Salud: 'heart-pulse', Deporte: 'dumbbell', Suscripciones: 'repeat', Regalos: 'gift', Compras: 'shopping-bag',
    Trabajo: 'banknote', Paga: 'banknote', Beca: 'graduation-cap', Regalo: 'gift', Venta: 'tag', 'Devolución': 'hand-coins', Otros: 'receipt' };
  const ACC_ICON = { efectivo: 'banknote', banco: 'landmark', ahorro: 'piggy-bank', tarjeta: 'credit-card', otra: 'wallet' };
  const catIcon = (c) => CAT_ICON[c] || 'receipt';

  let month = new URLSearchParams(location.search).get('mes') || thisMonth();
  let S = null, movs = [], catFilter = '';

  async function load() {
    $('ecMonthLabel').textContent = month === thisMonth() ? 'Este mes' : monthName(month, { month: 'short', year: 'numeric' }).replace('.', '').replace(/^./, (c) => c.toUpperCase());
    history.replaceState(null, '', month === thisMonth() ? location.pathname : `?mes=${month}`);
    try {
      S = await api(`/api/finance/summary?month=${month}`, { quiet: true });
      movs = (await api(`/api/finance/movements?month=${month}`, { quiet: true })).movements;
    } catch {
      $('ecMoney').innerHTML = emptyState({ iconName: 'wifi-off', title: 'No se pudo cargar', compact: true });
      return;
    }
    render();
  }

  /* ---------- Pintado ---------- */
  function render() {
    const m = S.mes;
    $('ecSub').textContent = `${monthName(month).replace(/^./, (c) => c.toUpperCase())} · ${money(m.gastos)} gastado · ${money(m.ingresos)} ingresado`;
    $('ecMonthTitle').textContent = month === thisMonth() ? 'Este mes' : monthName(month).replace(/^./, (c) => c.toUpperCase());

    // Tu dinero: total de las cuentas activas y cada cuenta
    const activas = S.cuentas.filter((c) => !c.archivada);
    $('ecMoney').innerHTML = activas.length ? `
      <p class="ec-total"><span class="ec-total-n tabular">${money(S.total)}</span><span class="small muted">en ${activas.length} cuenta${activas.length === 1 ? '' : 's'}</span></p>
      <ul class="hoy-list">${activas.map((c) => `<li class="hoy-row ec-row" data-account="${c.id}">
        <span class="ec-ico" aria-hidden="true">${icon(ACC_ICON[c.tipo] || 'wallet', 'icon-sm')}</span>
        <button type="button" class="hoy-title ec-link" data-edit-account="${c.id}">${esc(c.nombre)}</button>
        <span class="tabular ec-amt${c.saldo < 0 ? ' is-neg' : ''}">${money(c.saldo)}</span></li>`).join('')}</ul>
      ${S.me_deben || S.debo ? `<p class="tiny muted ec-note">Contando deudas: ${money(S.total + S.me_deben - S.debo)}</p>` : ''}`
      : `<p class="small muted">Añade dónde tienes el dinero (banco, efectivo, ahorro) con su saldo de hoy; después cada gasto e ingreso lo mueve.</p>
         <button type="button" class="btn btn-tinted btn-sm" data-add="account">${icon('plus', 'icon-sm')}Añadir una cuenta</button>`;

    // El mes: totales, gasto por categoría (barras de una serie) y los 6 meses
    const maxCat = Math.max(1, ...m.por_categoria.map((c) => c.total));
    const maxMes = Math.max(1, ...S.meses.map((x) => x.gastos));
    $('ecMonth').innerHTML = `
      <dl class="ec-kpis">
        <div><dt class="tiny muted">Gastado</dt><dd class="tabular">${money(m.gastos)}</dd></div>
        <div><dt class="tiny muted">Ingresado</dt><dd class="tabular">${money(m.ingresos)}</dd></div>
        <div><dt class="tiny muted">Balance</dt><dd class="tabular ec-amt${m.balance < 0 ? ' is-neg' : ' is-pos'}">${m.balance > 0 ? '+' : ''}${money(m.balance)}</dd></div>
      </dl>
      ${m.por_categoria.length ? `<h3 class="hoy-h3">En qué se ha ido</h3>
        <ul class="ec-bars">${m.por_categoria.map((c) => {
          // con presupuesto, la barra es lo gastado sobre el presupuesto (roja si se pasa)
          const b = c.presupuesto, over = b && c.total > b;
          const w = b ? Math.min(100, c.total / b * 100) : c.total / maxCat * 100;
          return `<li><button type="button" class="ec-bar-row${catFilter === c.categoria ? ' is-on' : ''}${b ? ' has-budget' : ''}${over ? ' is-over' : ''}" data-cat="${esc(c.categoria)}"
            title="${esc(c.categoria)}: ${money(c.total)}${b ? ` de ${money(b)} (${Math.round(c.total / b * 100)} %)` : m.gastos ? ` (${Math.round(c.total / m.gastos * 100)} %)` : ''}">
          <span class="ec-bar-label">${icon(catIcon(c.categoria), 'icon-sm')}${esc(c.categoria)}</span>
          <span class="ec-bar-track" aria-hidden="true"><span style="width:${c.total ? Math.max(2, w) : 0}%"></span></span>
          <span class="tabular ec-bar-n">${money(c.total)}${b ? `<span class="muted"> / ${money(b)}</span>` : ''}</span></button></li>`;
        }).join('')}</ul>
        ${S.presupuesto_total ? `<p class="tiny muted ec-note">Presupuesto del mes: ${money(S.presupuesto_total)} · ${m.gastos <= S.presupuesto_total ? `quedan ${money(S.presupuesto_total - m.gastos)}` : `te has pasado ${money(m.gastos - S.presupuesto_total)}`}</p>` : ''}`
        : '<p class="small muted">Sin gastos este mes.</p>'}
      <h3 class="hoy-h3">Gasto de los últimos 6 meses</h3>
      <div class="ec-months" role="img" aria-label="${S.meses.map((x) => `${monthName(x.mes, { month: 'long' })}: ${money(x.gastos)} gastado, ${money(x.ingresos)} ingresado`).join('; ')}">
        ${S.meses.map((x) => `<button type="button" class="ec-mcol${x.mes === month ? ' is-on' : ''}" data-goto-month="${x.mes}" title="${monthName(x.mes)}: ${money(x.gastos)} gastado · ${money(x.ingresos)} ingresado" aria-hidden="true" tabindex="-1">
          <span class="ec-mval tabular">${x.gastos ? Math.round(x.gastos) : ''}</span>
          <span class="ec-mbar"><span style="height:${x.gastos ? Math.max(3, x.gastos / maxMes * 100) : 0}%"></span></span>
          <span class="ec-mlab">${monthName(x.mes, { month: 'short' }).replace('.', '')}</span></button>`).join('')}
      </div>`;

    // Deudas: lo que te deben y lo que debes
    const meDeben = S.deudas.filter((d) => d.direccion === 'me-deben'), debo = S.deudas.filter((d) => d.direccion === 'debo');
    const debtList = (list, verbo) => `<ul class="hoy-list">${list.map((d) => `<li class="hoy-row ec-row" data-debt="${d.id}">
        <button type="button" class="hoy-title ec-link" data-edit-debt="${d.id}"><b>${esc(d.persona)}</b>${d.concepto ? ` <span class="muted">· ${esc(d.concepto)}</span>` : ''}${d.vence ? ` <span class="tiny muted">· vence ${esc(dayName(d.vence))}</span>` : ''}</button>
        <span class="tabular ec-amt">${money(d.importe)}</span>
        <button type="button" class="btn btn-ghost btn-sm" data-settle="${d.id}">${verbo}</button></li>`).join('')}</ul>`;
    $('ecDebts').innerHTML = S.deudas.length ? `
      ${meDeben.length ? `<h3 class="hoy-h3 ec-h3">Te deben <span class="tabular">${money(S.me_deben)}</span></h3>${debtList(meDeben, 'Cobrado')}` : ''}
      ${debo.length ? `<h3 class="hoy-h3 ec-h3">Debes <span class="tabular">${money(S.debo)}</span></h3>${debtList(debo, 'Pagado')}` : ''}`
      : '<p class="small muted">Nadie te debe nada y no debes nada. Apunta aquí lo que prestes o te presten.</p>';

    // Quiero comprar
    $('ecWishes').innerHTML = S.deseos.length ? `
      <ul class="hoy-list">${S.deseos.map((w) => `<li class="hoy-row ec-row" data-wish="${w.id}">
        ${w.prioridad ? `<span class="tag prio" data-prio="${esc(w.prioridad)}">${esc(w.prioridad)}</span>` : ''}
        <button type="button" class="hoy-title ec-link" data-edit-wish="${w.id}">${esc(w.nombre)}</button>
        ${w.url ? `<a class="btn btn-ghost btn-icon btn-sm" href="${esc(w.url)}" target="_blank" rel="noopener noreferrer" aria-label="Abrir el enlace de ${esc(w.nombre)}">${icon('external-link', 'icon-sm')}</a>` : ''}
        <span class="tabular ec-amt">${w.precio != null ? money(w.precio) : ''}</span>
        <button type="button" class="btn btn-ghost btn-sm" data-buy="${w.id}">Comprado</button></li>`).join('')}</ul>
      ${S.deseos_total ? `<p class="tiny muted ec-note">Todo junto: ${money(S.deseos_total)}${S.total ? ` · ${Math.round(S.deseos_total / Math.max(S.total, 0.01) * 100)} % de lo que tienes` : ''}</p>` : ''}`
      : '<p class="small muted">Apunta lo que quieres comprar con su precio; cuando lo compres, se anota como gasto.</p>';

    // Cada mes: recurrentes (se apuntan solos el día que toca)
    $('ecRecurring').innerHTML = S.recurrentes.length ? `
      <ul class="hoy-list">${S.recurrentes.map((r) => `<li class="hoy-row ec-row${r.activo ? '' : ' is-done'}">
        <span class="ec-ico" aria-hidden="true">${icon(catIcon(r.categoria), 'icon-sm')}</span>
        <button type="button" class="hoy-title ec-link ec-mov" data-edit-rec="${r.id}"><span>${esc(r.concepto)}</span>
          <span class="tiny muted">${r.activo ? `día ${r.dia} · próximo ${esc(dayName(r.proxima))}` : 'en pausa'}</span></button>
        <span class="tabular ec-amt${r.tipo === 'ingreso' ? ' is-pos' : ''}">${r.tipo === 'ingreso' ? '+' : '−'}${money(r.importe)}</span></li>`).join('')}</ul>
      <p class="tiny muted ec-note">Al mes: ${S.recurrentes_mes >= 0 ? `${money(S.recurrentes_mes)} en gastos fijos` : `${money(-S.recurrentes_mes)} de ingreso neto`}</p>`
      : '<p class="small muted">Alquiler, suscripciones, la paga…: lo que se repite cada mes se apunta solo el día que toca.</p>';

    $('ecExport').href = `/api/finance/export.csv?month=${month}`;
    $('ecExport').setAttribute('download', `economia-${month}.csv`);
    renderMovs();
  }

  function renderMovs() {
    const cats = [...new Set(movs.map((x) => x.categoria || 'Otros'))].sort((a, b) => a.localeCompare(b, 'es'));
    $('ecCats').innerHTML = [['', 'Todas'], ...cats.map((c) => [c, c])].map(([v, l]) =>
      `<button type="button" class="chip" data-filter-cat="${esc(v)}" aria-pressed="${catFilter === v}">${v ? icon(catIcon(v), 'icon-sm') : ''}${esc(l)}</button>`).join('');
    const q = $('ecQ').value.trim().toLowerCase();
    const list = movs.filter((x) => (!catFilter || (x.categoria || 'Otros') === catFilter)
      && (!q || `${x.concepto || ''} ${x.categoria || ''} ${x.notas || ''}`.toLowerCase().includes(q)));
    if (!list.length) {
      $('ecMovs').innerHTML = emptyState({ iconName: 'receipt', title: movs.length ? 'Nada con ese filtro' : 'Sin movimientos este mes',
        text: movs.length ? '' : 'Apunta un gasto o un ingreso con «Apuntar».', compact: true });
      return;
    }
    const cuenta = (id) => S.cuentas.find((c) => c.id === id)?.nombre;
    const byDay = {};
    list.forEach((x) => (byDay[x.fecha] ||= []).push(x));
    $('ecMovs').innerHTML = Object.entries(byDay).map(([d, xs]) => {
      const tot = xs.reduce((a, x) => a + (x.tipo === 'gasto' ? -x.importe : x.tipo === 'ingreso' ? x.importe : 0), 0);
      return `<section class="ec-day"><h3 class="ec-day-h"><span>${esc(cap(dayName(d)))}</span><span class="tabular muted">${tot ? `${tot > 0 ? '+' : ''}${money(tot)}` : ''}</span></h3>
        <ul class="hoy-list">${xs.map((x) => {
          const sign = x.tipo === 'gasto' ? '−' : x.tipo === 'ingreso' ? '+' : '';
          const sub = x.tipo === 'transferencia' ? `${esc(cuenta(x.cuenta_id) || '?')} → ${esc(cuenta(x.cuenta_destino) || '?')}` : [x.categoria || 'Otros', cuenta(x.cuenta_id)].filter(Boolean).map(esc).join(' · ');
          return `<li class="hoy-row ec-row"><span class="ec-ico" aria-hidden="true">${icon(x.tipo === 'transferencia' ? 'arrow-left-right' : catIcon(x.categoria), 'icon-sm')}</span>
            <button type="button" class="hoy-title ec-link ec-mov" data-edit-mov="${x.id}"><span>${esc(x.concepto || x.categoria || (x.tipo === 'ingreso' ? 'Ingreso' : 'Gasto'))}</span><span class="tiny muted">${sub}</span></button>
            <span class="tabular ec-amt${x.tipo === 'ingreso' ? ' is-pos' : ''}">${sign}${money(x.importe)}</span></li>`;
        }).join('')}</ul></section>`;
    }).join('');
  }

  /* ---------- Formularios ---------- */
  function dialog(title, body, { del = false } = {}) {
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm ec-dialog';
    dlg.innerHTML = `<div class="modal-header"><h2>${title}</h2><button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar">${icon('x')}</button></div>
      <form class="modal-body stack" id="ecForm">${body}</form>
      <div class="modal-footer">${del ? `<button type="button" class="btn btn-danger" data-del>${icon('trash-2', 'icon-sm')}Borrar</button>` : ''}<span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="ecForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    return dlg;
  }
  const field = (label, html) => `<label class="field"><span class="field-label">${label}</span>${html}</label>`;
  const accountOptions = (sel, empty = 'Ninguna') => `<option value="">${empty}</option>${S.cuentas.filter((c) => !c.archivada || c.id === sel)
    .map((c) => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.nombre)} · ${money(c.saldo)}</option>`).join('')}`;
  const today = () => new Date().toLocaleDateString('sv-SE');

  async function save(dlg, url, method, body) {
    const btn = dlg.querySelector('[type=submit]');
    btn.classList.add('is-loading');
    try { await api(url, { method, body }); } catch { btn.classList.remove('is-loading'); return false; }
    closeModal(dlg);
    load();
    return true;
  }
  function wireDelete(dlg, kind, id, what) {
    dlg.querySelector('[data-del]')?.addEventListener('click', async () => {
      let r;
      try { r = await api(`/api/finance/${kind}/${id}`, { method: 'DELETE' }); } catch { return; }
      closeModal(dlg);
      load();
      toast(`${what} en la papelera`, { action: { label: 'Deshacer', onClick: async () => { await api(`/api/trash/brain/${r.trash}/restore`, { method: 'POST' }); load(); } } });
    });
  }

  function movementForm(x = null, preset = {}) {
    const m = x || { tipo: 'gasto', fecha: today(), cuenta_id: S.cuentas.find((c) => !c.archivada)?.id || null, ...preset };
    const dlg = dialog(x ? 'Movimiento' : 'Apuntar', `
      <div class="segmented ec-tipo" role="group" aria-label="Tipo">${[['gasto', 'Gasto'], ['ingreso', 'Ingreso'], ['transferencia', 'Transferencia']]
        .map(([v, l]) => `<button type="button" data-tipo="${v}" aria-pressed="${m.tipo === v}">${l}</button>`).join('')}</div>
      ${field('Importe (€)', `<input name="importe" class="input ec-importe tabular" inputmode="decimal" required placeholder="0,00" value="${x ? String(x.importe).replace('.', ',') : ''}" autocomplete="off">`)}
      ${field('Concepto', `<input name="concepto" class="input" maxlength="200" placeholder="Menú del día, abono de transporte…" value="${esc(m.concepto || '')}">`)}
      <div class="field" data-for="cat"><span class="field-label">Categoría</span><div class="ec-catchips" id="ecCatChips"></div></div>
      <div class="rt-form-grid">
        ${field('<span data-acc-label>Cuenta</span>', `<select name="cuenta_id" class="select">${accountOptions(m.cuenta_id)}</select>`)}
        ${field('Fecha', `<input name="fecha" type="date" class="input" value="${esc(m.fecha || today())}" required>`)}
      </div>
      <div data-for="dest" hidden>${field('A la cuenta', `<select name="cuenta_destino" class="select">${accountOptions(m.cuenta_destino, 'Elige una')}</select>`)}</div>
      ${field('Notas', `<textarea name="notas" class="textarea" rows="2" maxlength="2000">${esc(m.notas || '')}</textarea>`)}`, { del: !!x });
    const f = dlg.querySelector('form');
    let tipo = m.tipo, cat = m.categoria || '';
    const paint = () => {
      dlg.querySelectorAll('[data-tipo]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tipo === tipo)));
      dlg.querySelector('[data-for="cat"]').hidden = tipo === 'transferencia';
      dlg.querySelector('[data-for="dest"]').hidden = tipo !== 'transferencia';
      dlg.querySelector('[data-acc-label]').textContent = tipo === 'transferencia' ? 'Desde la cuenta' : 'Cuenta';
      const cats = S.categorias[tipo === 'ingreso' ? 'ingreso' : 'gasto'];
      if (cat && !cats.includes(cat)) cats.push(cat);
      $('ecCatChips').innerHTML = cats.map((c) => `<button type="button" class="chip" data-cat="${esc(c)}" aria-pressed="${c === cat}">${icon(catIcon(c), 'icon-sm')}${esc(c)}</button>`).join('');
    };
    dlg.addEventListener('click', (e) => {
      const t = e.target.closest('[data-tipo]'), c = e.target.closest('#ecCatChips [data-cat]');
      if (t) { tipo = t.dataset.tipo; paint(); }
      if (c) { cat = cat === c.dataset.cat ? '' : c.dataset.cat; paint(); }
    });
    paint();
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { tipo, importe: f.importe.value, concepto: f.concepto.value, fecha: f.fecha.value, notas: f.notas.value,
        categoria: tipo === 'transferencia' ? null : cat || 'Otros',
        cuenta_id: f.cuenta_id.value ? Number(f.cuenta_id.value) : null,
        cuenta_destino: tipo === 'transferencia' && f.cuenta_destino.value ? Number(f.cuenta_destino.value) : null };
      save(dlg, x ? `/api/finance/movements/${x.id}` : '/api/finance/movements', x ? 'PATCH' : 'POST', body);
    });
    if (x) wireDelete(dlg, 'movements', x.id, 'Movimiento');
    openModal(dlg, { focus: 'input[name=importe]', onClose: () => dlg.remove() });
  }

  function accountForm(a = null) {
    const dlg = dialog(a ? 'Cuenta' : 'Nueva cuenta', `
      ${field('Nombre', `<input name="nombre" class="input" maxlength="60" required placeholder="Banco, Efectivo, Hucha…" value="${esc(a?.nombre || '')}">`)}
      <div class="rt-form-grid">
        ${field('Tipo', `<select name="tipo" class="select">${S.tipos_cuenta.map((t) => `<option value="${t}" ${(a?.tipo || 'banco') === t ? 'selected' : ''}>${t.charAt(0).toUpperCase() + t.slice(1)}</option>`).join('')}</select>`)}
        ${field(a ? 'Saldo inicial (€)' : 'Saldo de hoy (€)', `<input name="saldo" class="input tabular" inputmode="decimal" value="${a ? String(a.saldo_inicial).replace('.', ',') : ''}" placeholder="0,00">`)}
      </div>
      ${a ? `<p class="tiny muted">Saldo actual: ${money(a.saldo)}. El inicial es el de antes del primer movimiento apuntado.</p>
        <label class="switch-row"><input type="checkbox" class="switch" name="archivada" ${a.archivada ? 'checked' : ''}><span>Archivada (no cuenta en el total)</span></label>` : ''}`, { del: !!a });
    const f = dlg.querySelector('form');
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { nombre: f.nombre.value, tipo: f.tipo.value, saldo_inicial: f.saldo.value || 0, ...(a ? { archivada: f.archivada.checked } : {}) };
      save(dlg, a ? `/api/finance/accounts/${a.id}` : '/api/finance/accounts', a ? 'PATCH' : 'POST', body);
    });
    if (a) wireDelete(dlg, 'accounts', a.id, 'Cuenta');
    openModal(dlg, { focus: 'input[name=nombre]', onClose: () => dlg.remove() });
  }

  function debtForm(d = null) {
    const dlg = dialog(d ? 'Deuda' : 'Nueva deuda', `
      <div class="segmented" role="group" aria-label="Quién debe">${[['me-deben', 'Me deben'], ['debo', 'Debo']]
        .map(([v, l]) => `<button type="button" data-dir="${v}" aria-pressed="${(d?.direccion || 'me-deben') === v}">${l}</button>`).join('')}</div>
      <div class="rt-form-grid">
        ${field('Persona', `<input name="persona" class="input" maxlength="60" required value="${esc(d?.persona || '')}" autocomplete="off">`)}
        ${field('Importe (€)', `<input name="importe" class="input tabular" inputmode="decimal" required value="${d ? String(d.importe).replace('.', ',') : ''}" placeholder="0,00">`)}
      </div>
      ${field('Concepto', `<input name="concepto" class="input" maxlength="200" placeholder="La cena del viernes" value="${esc(d?.concepto || '')}">`)}
      ${field('Para cuándo (opcional)', `<input name="vence" type="date" class="input" value="${esc(d?.vence || '')}">`)}`, { del: !!d });
    const f = dlg.querySelector('form');
    let dir = d?.direccion || 'me-deben';
    dlg.addEventListener('click', (e) => {
      const b = e.target.closest('[data-dir]');
      if (b) { dir = b.dataset.dir; dlg.querySelectorAll('[data-dir]').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); }
    });
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { persona: f.persona.value, importe: f.importe.value, direccion: dir, concepto: f.concepto.value, vence: f.vence.value || null };
      save(dlg, d ? `/api/finance/debts/${d.id}` : '/api/finance/debts', d ? 'PATCH' : 'POST', body);
    });
    if (d) wireDelete(dlg, 'debts', d.id, 'Deuda');
    openModal(dlg, { focus: 'input[name=persona]', onClose: () => dlg.remove() });
  }

  function wishForm(w = null) {
    const dlg = dialog(w ? 'Quiero comprar' : 'Algo que quieres comprar', `
      ${field('Qué', `<input name="nombre" class="input" maxlength="120" required value="${esc(w?.nombre || '')}" placeholder="Auriculares, libro…">`)}
      <div class="rt-form-grid">
        ${field('Precio (€)', `<input name="precio" class="input tabular" inputmode="decimal" value="${w?.precio != null ? String(w.precio).replace('.', ',') : ''}" placeholder="0,00">`)}
        ${field('Prioridad', `<select name="prioridad" class="select"><option value="">Sin prioridad</option>${['alta', 'media', 'baja'].map((p) => `<option value="${p}" ${w?.prioridad === p ? 'selected' : ''}>${p.charAt(0).toUpperCase() + p.slice(1)}</option>`).join('')}</select>`)}
      </div>
      ${field('Enlace (opcional)', `<input name="url" type="url" class="input" maxlength="1000" value="${esc(w?.url || '')}" placeholder="https://…">`)}`, { del: !!w });
    const f = dlg.querySelector('form');
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      save(dlg, w ? `/api/finance/wishes/${w.id}` : '/api/finance/wishes', w ? 'PATCH' : 'POST',
        { nombre: f.nombre.value, precio: f.precio.value || null, prioridad: f.prioridad.value || null, url: f.url.value || null });
    });
    if (w) wireDelete(dlg, 'wishes', w.id, 'Deseo');
    openModal(dlg, { focus: 'input[name=nombre]', onClose: () => dlg.remove() });
  }

  function recurringForm(r = null) {
    const x = r || { tipo: 'gasto', dia: new Date().getDate() > 28 ? 1 : new Date().getDate(), activo: 1, categoria: 'Suscripciones', cuenta_id: S.cuentas.find((c) => !c.archivada)?.id || null };
    const dlg = dialog(r ? 'Cada mes' : 'Nuevo gasto o ingreso de cada mes', `
      <div class="segmented ec-tipo" role="group" aria-label="Tipo">${[['gasto', 'Gasto'], ['ingreso', 'Ingreso']]
        .map(([v, l]) => `<button type="button" data-tipo="${v}" aria-pressed="${x.tipo === v}">${l}</button>`).join('')}</div>
      <div class="rt-form-grid">
        ${field('Concepto', `<input name="concepto" class="input" maxlength="200" required placeholder="Gimnasio, Spotify, alquiler…" value="${esc(x.concepto || '')}">`)}
        ${field('Importe (€)', `<input name="importe" class="input tabular" inputmode="decimal" required placeholder="0,00" value="${r ? String(r.importe).replace('.', ',') : ''}">`)}
      </div>
      <div class="rt-form-grid">
        ${field('Día del mes', `<input name="dia" type="number" class="input tabular" min="1" max="28" required value="${x.dia}">`)}
        ${field('Cuenta', `<select name="cuenta_id" class="select">${accountOptions(x.cuenta_id)}</select>`)}
      </div>
      <div class="field" data-for="cat"><span class="field-label">Categoría</span><div class="ec-catchips" id="ecRecCats"></div></div>
      <p class="tiny muted">Se apunta solo cada mes ese día (hasta el 28, que existe en todos los meses).</p>
      ${r ? `<label class="switch-row"><input type="checkbox" class="switch" name="activo" ${r.activo ? 'checked' : ''}><span>Activo (en pausa no se apunta)</span></label>` : ''}`, { del: !!r });
    const f = dlg.querySelector('form');
    let tipo = x.tipo, cat = x.categoria || '';
    const paint = () => {
      dlg.querySelectorAll('[data-tipo]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tipo === tipo)));
      const cats = [...S.categorias[tipo]];
      if (cat && !cats.includes(cat)) cats.push(cat);
      $('ecRecCats').innerHTML = cats.map((c) => `<button type="button" class="chip" data-cat="${esc(c)}" aria-pressed="${c === cat}">${icon(catIcon(c), 'icon-sm')}${esc(c)}</button>`).join('');
    };
    dlg.addEventListener('click', (e) => {
      const t = e.target.closest('[data-tipo]'), c = e.target.closest('#ecRecCats [data-cat]');
      if (t) { tipo = t.dataset.tipo; if (!S.categorias[tipo].includes(cat)) cat = ''; paint(); }
      if (c) { cat = cat === c.dataset.cat ? '' : c.dataset.cat; paint(); }
    });
    paint();
    f.addEventListener('submit', (e) => {
      e.preventDefault();
      const body = { tipo, concepto: f.concepto.value, importe: f.importe.value, dia: Number(f.dia.value), categoria: cat || 'Otros',
        cuenta_id: f.cuenta_id.value ? Number(f.cuenta_id.value) : null, ...(r ? { activo: f.activo.checked } : {}) };
      save(dlg, r ? `/api/finance/recurring/${r.id}` : '/api/finance/recurring', r ? 'PATCH' : 'POST', body);
    });
    if (r) wireDelete(dlg, 'recurring', r.id, 'Recurrente');
    openModal(dlg, { focus: 'input[name=concepto]', onClose: () => dlg.remove() });
  }

  // Presupuestos: cuánto quieres gastar como mucho al mes en cada categoría (vacío = sin presupuesto)
  function budgetsForm() {
    const cats = [...new Set([...S.categorias.gasto, ...Object.keys(S.presupuestos)])];
    const dlg = dialog('Presupuesto de cada mes', `
      <p class="small muted">Lo máximo que quieres gastar al mes en cada categoría. Déjalo vacío para no fijarlo.</p>
      <div class="ec-budgets">${cats.map((c, i) => `<label class="ec-budget-row" for="ecB${i}"><span>${icon(catIcon(c), 'icon-sm')}${esc(c)}</span>
        <input id="ecB${i}" class="input input-sm tabular" inputmode="decimal" data-budget="${esc(c)}" placeholder="—" autocomplete="off"
          value="${S.presupuestos[c] != null ? String(S.presupuestos[c]).replace('.', ',') : ''}"><span class="tiny muted">€</span></label>`).join('')}</div>`);
    dlg.querySelector('form').addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = dlg.querySelector('[type=submit]');
      btn.classList.add('is-loading');
      try {
        for (const inp of dlg.querySelectorAll('[data-budget]')) {
          const before = S.presupuestos[inp.dataset.budget];
          const now = inp.value.trim();
          if (String(before ?? '').replace('.', ',') === now) continue;
          await api(`/api/finance/budgets/${encodeURIComponent(inp.dataset.budget)}`, { method: 'PUT', body: { importe: now || null } });
        }
      } catch { btn.classList.remove('is-loading'); return; }
      closeModal(dlg);
      load();
      toast('Presupuestos guardados');
    });
    openModal(dlg, { focus: '[data-budget]', onClose: () => dlg.remove() });
  }

  // Cobrar o pagar una deuda / marcar un deseo como comprado: en qué cuenta se apunta
  async function pickAccount(title, message) {
    const activas = S.cuentas.filter((c) => !c.archivada);
    if (!activas.length) return { cuenta_id: null };
    const picked = await uiPick({ title, placeholder: message,
      load: () => [{ id: 0, label: 'No apuntarlo en ninguna cuenta', icon: 'x' }, ...activas.map((c) => ({ id: c.id, label: c.nombre, sub: money(c.saldo), icon: ACC_ICON[c.tipo] || 'wallet' }))] });
    if (!picked) return null;
    return { cuenta_id: picked.id || null };
  }

  /* ---------- Eventos ---------- */
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-add], [data-edit-account], [data-edit-debt], [data-edit-wish], [data-edit-mov], [data-edit-rec], [data-budgets], [data-settle], [data-buy], [data-cat], [data-filter-cat], [data-goto-month]');
    if (!t || t.closest('dialog')) return;
    const id = (k) => Number(t.dataset[k]);
    if (t.dataset.add === 'account') accountForm();
    else if (t.dataset.add === 'debt') debtForm();
    else if (t.dataset.add === 'wish') wishForm();
    else if (t.dataset.add === 'recurring') recurringForm();
    else if (t.dataset.editRec) recurringForm(S.recurrentes.find((r) => r.id === id('editRec')));
    else if (t.dataset.budgets !== undefined) budgetsForm();
    else if (t.dataset.editAccount) accountForm(S.cuentas.find((c) => c.id === id('editAccount')));
    else if (t.dataset.editDebt) debtForm(S.deudas.find((d) => d.id === id('editDebt')));
    else if (t.dataset.editWish) wishForm(S.deseos.find((w) => w.id === id('editWish')));
    else if (t.dataset.editMov) movementForm(movs.find((x) => x.id === id('editMov')));
    else if (t.dataset.settle) {
      const d = S.deudas.find((x) => x.id === id('settle'));
      const r = await pickAccount(d.direccion === 'me-deben' ? `Cobrado de ${d.persona}` : `Pagado a ${d.persona}`, `¿En qué cuenta se apuntan los ${money(d.importe)}?`);
      if (!r) return;
      await api(`/api/finance/debts/${d.id}/settle`, { method: 'POST', body: r });
      toast(d.direccion === 'me-deben' ? 'Cobrado' : 'Pagado');
      load();
    } else if (t.dataset.buy) {
      const w = S.deseos.find((x) => x.id === id('buy'));
      const r = await pickAccount(`Comprado: ${w.nombre}`, w.precio ? `¿De qué cuenta salen los ${money(w.precio)}?` : 'Sin precio: no se apunta gasto');
      if (!r) return;
      await api(`/api/finance/wishes/${w.id}/buy`, { method: 'POST', body: r });
      toast(w.precio ? 'Comprado y apuntado como gasto' : 'Comprado');
      load();
    } else if (t.dataset.filterCat !== undefined) { catFilter = t.dataset.filterCat; render(); }
    else if (t.dataset.cat !== undefined && t.closest('.ec-bars')) { catFilter = catFilter === t.dataset.cat ? '' : t.dataset.cat; render(); $('ecMovs').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    else if (t.dataset.gotoMonth) { month = t.dataset.gotoMonth; catFilter = ''; load(); }
  });
  $('ecQ').addEventListener('input', () => renderMovs());
  $('ecNew').addEventListener('click', () => movementForm());
  document.querySelectorAll('[data-month]').forEach((b) => b.addEventListener('click', () => {
    const k = Number(b.dataset.month);
    month = k ? shift(month, k) : thisMonth();
    catFilter = '';
    load();
  }));
  onDataChange(/^\/api\/finance/, () => load());
  load();
})();
