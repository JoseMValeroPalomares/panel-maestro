/* ==========================================================================
   Conflictos entre dispositivos (notas y tableros): diálogo común y diferencias por líneas.
   El servidor responde 409 { conflict, current } cuando otro dispositivo guardó después de que esta
   página cargase; aquí se pregunta qué hacer. Nada se pierde: lo que no se elige queda en el historial
   (notas) o en la copia previa del tablero.
   Depende de ui.js (icon, openModal, closeModal, wireAllDialogs, escapeHtml).
   ========================================================================== */
window.Conflict = (() => {
  const MAX_CELLS = 2_000_000;  // tope del cálculo exacto (n × m líneas); por encima, todo lo distinto sin alinear
  const CONTEXT = 2;            // líneas iguales que se enseñan alrededor de cada cambio

  /* [{ t: 'same' | 'mine' | 'theirs', text }] — 'mine' = solo en este dispositivo, 'theirs' = solo en el otro */
  function lineDiff(mine, theirs) {
    const a = String(mine ?? '').split('\n'), b = String(theirs ?? '').split('\n');
    let start = 0;
    while (start < a.length && start < b.length && a[start] === b[start]) start++;
    let endA = a.length, endB = b.length;
    while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA--; endB--; }
    const out = a.slice(0, start).map((text) => ({ t: 'same', text }));
    const ma = a.slice(start, endA), mb = b.slice(start, endB);
    const n = ma.length, m = mb.length;
    if (n * m > MAX_CELLS) {
      ma.forEach((text) => out.push({ t: 'mine', text }));
      mb.forEach((text) => out.push({ t: 'theirs', text }));
    } else {
      // Subsecuencia común más larga, de atrás hacia delante, para recorrerla en orden
      const w = m + 1, L = new Uint32Array((n + 1) * w);
      for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
        L[i * w + j] = ma[i] === mb[j] ? L[(i + 1) * w + j + 1] + 1 : Math.max(L[(i + 1) * w + j], L[i * w + j + 1]);
      let i = 0, j = 0;
      while (i < n && j < m) {
        if (ma[i] === mb[j]) { out.push({ t: 'same', text: ma[i] }); i++; j++; }
        else if (L[(i + 1) * w + j] >= L[i * w + j + 1]) out.push({ t: 'mine', text: ma[i++] });
        else out.push({ t: 'theirs', text: mb[j++] });
      }
      while (i < n) out.push({ t: 'mine', text: ma[i++] });
      while (j < m) out.push({ t: 'theirs', text: mb[j++] });
    }
    a.slice(endA).forEach((text) => out.push({ t: 'same', text }));
    return out;
  }

  const SIGN = { mine: '+', theirs: '−' };
  const SR = { mine: 'Solo en este dispositivo: ', theirs: 'Solo en el otro: ' };
  function renderDiff(ops) {
    const changed = ops.map((o) => o.t !== 'same');
    if (!changed.some(Boolean)) return '<p class="muted">El texto es el mismo en los dos; solo cambian otros datos (título, categoría, etiquetas o estado).</p>';
    const keep = ops.map((_, k) => changed.slice(Math.max(0, k - CONTEXT), k + CONTEXT + 1).some(Boolean));
    keep.forEach((v, k) => { if (!v && keep[k - 1] && keep[k + 1]) keep[k] = true; });  // plegar una sola línea no ahorra nada
    let html = '', gap = 0;
    const flush = () => { if (gap) html += `<div class="diff-gap">${gap} ${gap === 1 ? 'línea igual' : 'líneas iguales'}</div>`; gap = 0; };
    ops.forEach((o, k) => {
      if (!keep[k]) { gap++; return; }
      flush();
      html += `<div class="diff-line diff-${o.t}"><span class="diff-sign" aria-hidden="true">${SIGN[o.t] || ' '}</span>`
        + `<span class="diff-text">${o.t !== 'same' ? `<span class="sr-only">${SR[o.t]}</span>` : ''}${escapeHtml(o.text) || '&nbsp;'}</span></div>`;
    });
    flush();
    return html;
  }

  /* Pregunta qué hacer. diff: función (puede ser async) que devuelve el HTML de las diferencias.
     Devuelve 'mine', 'theirs' o null (cerrado sin elegir: el conflicto sigue pendiente). */
  function ask({ title, message, mineLabel = 'Quedarme con lo mío', theirsLabel = 'Recargar la otra', diff, note }) {
    return new Promise((resolve) => {
      const dlg = document.createElement('dialog');
      dlg.className = 'modal modal-lg conflict-modal';
      dlg.innerHTML = `
        <div class="modal-header"><div><h2>${escapeHtml(title)}</h2><p class="modal-sub">${escapeHtml(message)}</p></div>
          <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Decidir más tarde">${icon('x')}</button></div>
        <div class="modal-body">
          <div class="conflict-diff" hidden>
            <p class="conflict-legend tiny"><span class="diff-key diff-mine"><span aria-hidden="true">+</span> Solo en este dispositivo</span>
              <span class="diff-key diff-theirs"><span aria-hidden="true">−</span> Solo en el otro</span></p>
            <div class="conflict-lines" role="region" aria-label="Diferencias" tabindex="0"></div>
          </div>
          ${note ? `<p class="tiny subtle conflict-note">${escapeHtml(note)}</p>` : ''}
        </div>
        <div class="modal-footer">
          ${diff ? `<button type="button" class="btn" data-diff aria-expanded="false">${icon('git-compare', 'icon-sm')}Ver diferencias</button>` : ''}
          <span class="spacer"></span>
          <button type="button" class="btn" data-pick="theirs">${escapeHtml(theirsLabel)}</button>
          <button type="button" class="btn btn-primary" data-pick="mine">${escapeHtml(mineLabel)}</button>
        </div>`;
      document.body.appendChild(dlg);
      wireAllDialogs();
      let result = null;
      dlg.querySelectorAll('[data-pick]').forEach((b) => b.addEventListener('click', () => { result = b.dataset.pick; closeModal(dlg); }));
      const btn = dlg.querySelector('[data-diff]');
      btn?.addEventListener('click', async () => {
        const box = dlg.querySelector('.conflict-diff');
        const open = box.hidden;
        box.hidden = !open;
        btn.setAttribute('aria-expanded', String(open));
        btn.lastChild.textContent = open ? 'Ocultar diferencias' : 'Ver diferencias';
        if (open && !box.dataset.done) {
          const lines = box.querySelector('.conflict-lines');
          lines.innerHTML = '<p class="muted">Comparando…</p>';
          try { lines.innerHTML = await diff(); box.dataset.done = '1'; } catch { lines.innerHTML = '<p class="muted">No se pudieron comparar.</p>'; }
        }
      });
      openModal(dlg, { focus: '[data-pick="mine"]', onClose: () => { dlg.remove(); resolve(result); } });
    });
  }

  return { lineDiff, renderDiff, ask };
})();
