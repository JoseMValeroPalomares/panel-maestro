/* ==========================================================================
   rapido.js — formularios rápidos de alta y edición (P-3), window.Rapido
   Una regla para todas las pantallas (rutinas, tareas y eventos, platos e ingredientes):
   - lo mínimo en una línea, con lo entendido debajo (Rapido.preview: vista previa con espera y orden);
   - «Más opciones» plegado y recordado por pantalla (Rapido.more);
   - teclado: Intro guarda, Ctrl+Intro guarda y deja el formulario listo para otro, Esc cancela (Rapido.keys);
     en un campo de varias líneas, Intro en una línea vacía guarda y Mayús+Intro siempre es salto de línea;
   - valores por defecto recordados en Prefs (Rapido.defaults: «rapido» → {pantalla: {…}});
   - editar un solo campo en el sitio, sin diálogo (Rapido.inline).
   ========================================================================== */
(function () {
  'use strict';

  const KEY = 'rapido';

  /* ---------- Valores recordados por pantalla ---------- */
  const all = () => ({ ...(Prefs.get(KEY, {}) || {}) });
  const defaults = {
    get(screen, name, fallback = null) { const v = (all()[screen] || {})[name]; return v ?? fallback; },
    set(screen, name, value) {
      const a = all();
      a[screen] = { ...(a[screen] || {}), [name]: value };
      Prefs.set(KEY, a);
    },
  };

  /* ---------- «Más opciones» plegado y recordado ---------- */
  function more(details, screen) {
    if (!details) return;
    details.open = !!defaults.get(screen, 'mas', false);
    details.addEventListener('toggle', () => defaults.set(screen, 'mas', details.open));
  }

  /* ---------- Teclado ----------
     save(): Intro · saveNew(): Ctrl+Intro (si no se da, Ctrl+Intro también guarda) · cancel(): Esc.
     En un textarea, Intro solo guarda en una línea vacía (o en una vacía al final): así se escribe un paso por línea. */
  function keys(root, { save, saveNew, cancel }) {
    root.addEventListener('keydown', (e) => {
      const t = e.target;
      if (e.isComposing || e.defaultPrevented) return;
      if (e.key === 'Escape' && cancel) {
        if (t.closest?.('[role=menu], .menu, dialog[open] dialog')) return;
        e.preventDefault();
        e.stopPropagation();
        cancel();
        return;
      }
      if (e.key !== 'Enter' || e.altKey) return;
      if (t.matches?.('button, summary, select, a') && !(e.ctrlKey || e.metaKey)) return;
      if (e.ctrlKey || e.metaKey) { e.preventDefault(); (saveNew || save)(); return; }
      if (e.shiftKey) return;
      if (t.tagName === 'TEXTAREA') {
        const before = t.value.slice(0, t.selectionStart);
        const line = before.slice(before.lastIndexOf('\n') + 1);
        const after = t.value.slice(t.selectionEnd);
        if (line.trim() || (after.trim() && !after.startsWith('\n'))) return;  // escribiendo: salto de línea
        e.preventDefault();
        save();
        return;
      }
      if (t.matches?.('input:not([type=checkbox]):not([type=radio]):not([type=button]):not([type=submit])')) {
        e.preventDefault();
        save();
      }
    });
  }

  /* ---------- Vista previa con espera: solo pinta la última respuesta ---------- */
  function preview(fn, paint, ms = 200) {
    let timer = null, seq = 0;
    const run = (now = false) => {
      clearTimeout(timer);
      const go = async () => {
        const my = ++seq;
        let res;
        try { res = await fn(); } catch (err) { res = { error: err?.message || 'No se entiende' }; }
        if (my === seq) paint(res);
      };
      if (now) return go();
      timer = setTimeout(go, ms);
      return null;
    };
    run.cancel = () => { clearTimeout(timer); seq++; };
    return run;
  }

  // Lo entendido, en pastillas: [{icon, text, kind?}] (kind: 'warn' para lo que falta o no cuadra)
  function chips(list) {
    return list.filter(Boolean).map((c) => `<span class="qf-chip${c.kind ? ` is-${c.kind}` : ''}">${c.icon ? icon(c.icon, 'icon-sm') : ''}${escapeHtml(c.text)}</span>`).join('');
  }

  /* ---------- Un campo en el sitio ----------
     Cambia el texto de `el` por un campo; Intro o salir del campo guarda (onSave(valor) → promesa; si falla, vuelve),
     Esc cancela. `type`: 'text' | 'time' | 'number'; `parse(v)` puede devolver null para rechazar. */
  function inline(el, { value = '', label = 'Editar', type = 'text', onSave, parse = (v) => v, width = null, placeholder = '' }) {
    if (!el || el.hidden || el.nextElementSibling?.classList.contains('qf-inline')) return;
    // El campo va al lado y el elemento se oculta mientras tanto (un campo no puede ir dentro de un botón)
    const input = document.createElement('input');
    input.className = 'input input-sm qf-inline no-drag';
    input.type = type === 'time' ? 'text' : type;
    if (type === 'time') { input.inputMode = 'numeric'; input.maxLength = 5; input.classList.add('tabular'); }
    input.value = value;
    input.placeholder = placeholder;
    input.setAttribute('aria-label', label);
    if (width) input.style.width = width;
    el.after(input);
    el.hidden = true;
    input.focus();
    input.select();
    let done = false;
    const restore = (focus) => { input.remove(); el.hidden = false; if (focus) el.focus?.(); };
    const finish = async (commit) => {
      if (done) return;
      done = true;
      const v = input.value.trim();
      if (!commit || v === String(value).trim()) { restore(true); return; }
      const parsed = parse(v);
      if (parsed === null) { done = false; input.focus(); return; }
      input.disabled = true;
      try { await onSave(parsed); } catch { input.disabled = false; done = false; input.focus(); return; }
      if (input.isConnected) restore(false);
    };
    input.addEventListener('keydown', (e) => {
      e.stopPropagation();  // las teclas de la lista (Espacio, Supr, E…) no actúan mientras se escribe
      if (e.key === 'Enter') { e.preventDefault(); finish(true); }
      else if (e.key === 'Escape') { e.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => { if (!input.disabled) finish(true); });
    ['click', 'dblclick', 'pointerdown'].forEach((t) => input.addEventListener(t, (e) => e.stopPropagation()));
  }

  // Pista de teclado común (oculta en el móvil, donde no hay teclado físico)
  const hint = (extra = '') => `<span class="tiny subtle hide-mobile qf-keys"><kbd>Intro</kbd> guarda · <kbd>Ctrl</kbd>+<kbd>Intro</kbd> guarda y crea otro · <kbd>Esc</kbd> cancela${extra}</span>`;

  window.Rapido = { defaults, more, keys, preview, chips, inline, hint };
})();
