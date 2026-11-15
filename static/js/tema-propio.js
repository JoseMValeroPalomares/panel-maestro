/* ==========================================================================
   tema-propio.js — la paleta propia (P-5), window.TemaPropio
   Ocho colores elegidos en Ajustes (fondo, superficie, texto, acento, rojo, naranja, verde y morado) bastan para
   todos los tokens del tema (los mismos que genera scripts/themes.py para los de serie): el resto se deriva aquí.
   Los colores viven en Prefs («tema-propio», viajan entre dispositivos); el CSS ya hecho se guarda también en
   localStorage («theme-propia-css») para que theme-init.js lo aplique antes del primer pintado, sin parpadeo.
   ========================================================================== */
(function () {
  'use strict';

  const CSS_KEY = 'theme-propia-css';
  const PREF = 'tema-propio';
  const DEFAULT = { bg: '#1b1e28', elev: '#232734', text: '#e2e6f2', accent: '#7aa2f7', danger: '#f7768e', warning: '#e0af68', success: '#9ece6a', index: '#bb9af7' };
  const FIELDS = [
    ['bg', 'Fondo'], ['elev', 'Superficie'], ['text', 'Texto'], ['accent', 'Acento'],
    ['danger', 'Rojo (borrar, avisos)'], ['warning', 'Naranja (pendiente)'], ['success', 'Verde (hecho)'], ['index', 'Morado (índices)'],
  ];
  const TILES = ['hoy', 'calendario', 'rutinas', 'tareas', 'universidad', 'proyectos', 'inbox', 'revision', 'notas', 'grafo', 'baul',
    'repaso', 'buscar', 'comidas', 'estudio', 'economia', 'rendimiento', 'gestion', 'backups', 'papelera'];
  // El papel de cada azulejo: un color propio (de los ocho) o un tono (grados) como en Mocha; null = gris
  const ROLE = { hoy: 45, calendario: 'accent', rutinas: 320, tareas: 170, universidad: 52, proyectos: 22, inbox: 'warning', revision: 12,
    notas: 235, grafo: 198, baul: 355, repaso: 'index', buscar: null, comidas: 'success', estudio: 'danger', economia: 186,
    rendimiento: 340, gestion: null, backups: null, papelera: null };

  /* ---------- Color ---------- */
  const valid = (h) => /^#[0-9a-f]{6}$/i.test(h || '');
  const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const hex = (c) => '#' + c.map((x) => Math.round(Math.max(0, Math.min(255, x))).toString(16).padStart(2, '0')).join('');
  const mix = (a, b, t) => { const [x, y] = [rgb(a), rgb(b)]; return hex(x.map((v, i) => v + (y[i] - v) * t)); };
  function lum(h) {
    return rgb(h).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; })
      .reduce((s, v, i) => s + v * [0.2126, 0.7152, 0.0722][i], 0);
  }
  function contrast(a, b) { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); }
  function toHsl(h) {
    const [r, g, b] = rgb(h).map((v) => v / 255), max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    if (max === min) return [0, 0, l];
    const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    const hh = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [hh * 60, s, l];
  }
  function fromHsl(hh, s, l) {
    const k = (n) => (n + hh / 30) % 12, a = s * Math.min(l, 1 - l);
    const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return hex([f(0), f(8), f(4)].map((v) => v * 255));
  }
  // El mismo tono con la luz justa para llegar a `min` de contraste con `fg` (hacia arriba o abajo según el tema)
  function reach(h, fg, min, up) {
    const [hh, s, l0] = toHsl(h);
    for (let i = 0, l = l0; i <= 60; i++, l += up ? 0.01 : -0.01) {
      const c = fromHsl(hh, s, Math.max(0, Math.min(1, l)));
      if (contrast(c, fg) >= min) return c;
    }
    return up ? '#ffffff' : '#000000';
  }
  const rgbTxt = (h) => rgb(h).join(', ');
  const rgba = (h, a) => `rgba(${rgbTxt(h)}, ${a})`;

  /* ---------- Del color al tema ---------- */
  function tokens(input) {
    const c = { ...DEFAULT, ...Object.fromEntries(Object.entries(input || {}).filter(([, v]) => valid(v))) };
    const dark = lum(c.bg) < 0.2;
    const elev2 = mix(c.elev, c.text, dark ? 0.04 : 0.025);
    const sunken = mix(c.bg, '#000000', dark ? 0.18 : 0.05);
    // texto secundario y apagado: lo más cerca del principal que siga en AA sobre la superficie más clara/oscura
    const text2 = reach(mix(c.text, c.elev, 0.14), elev2, 4.6, dark);
    const text3 = reach(mix(c.text, c.elev, 0.28), elev2, 4.6, dark);
    const onAccent = contrast('#ffffff', c.accent) >= contrast(sunken, c.accent) ? '#ffffff' : sunken;
    const onDanger = contrast('#ffffff', c.danger) >= contrast(sunken, c.danger) ? '#ffffff' : sunken;
    const hover = mix(c.accent, dark ? '#ffffff' : '#000000', 0.12);
    const tileFg = dark ? sunken : '#ffffff';
    const tiles = {};
    let gray = 0;
    TILES.forEach((k) => {
      const role = ROLE[k];
      let base;
      if (role === null) { base = mix(c.text, c.elev, 0.15 + 0.12 * gray++); return (tiles[k] = reach(base, tileFg, 3.2, dark)); }
      if (typeof role === 'string') base = c[role];
      else { const [, s, l] = toHsl(c.accent); base = fromHsl(role, Math.max(0.45, s * 0.9), l); }
      tiles[k] = reach(base, tileFg, 3.2, dark);
    });
    const cats = [c.accent, c.success, c.warning, c.danger, c.index, tiles.tareas, tiles.hoy, tiles.rutinas, tiles.grafo, tiles.proyectos]
      .map((x) => reach(x, c.elev, 3, dark));
    const neutral = mix(c.text, c.bg, 0.35), sep = mix(c.text, c.bg, 0.5);
    const h = dark ? '#cdd6f4' : '#000000';
    const v = {
      'color-scheme': dark ? 'dark' : 'light',
      '--bg': c.bg, '--bg-elev': c.elev, '--bg-elev-2': elev2, '--bg-sunken': sunken, '--sidebar': rgba(sunken, 0.88),
      '--fill': rgba(neutral, dark ? 0.14 : 0.12), '--fill-strong': rgba(neutral, dark ? 0.24 : 0.2),
      '--hover': rgba(h, dark ? 0.06 : 0.045), '--press': rgba(h, dark ? 0.1 : 0.08),
      '--separator': rgba(sep, dark ? 0.35 : 0.16), '--separator-strong': rgba(sep, dark ? 0.6 : 0.28),
      '--text': c.text, '--text-2': text2, '--text-3': text3, '--text-on-accent': onAccent, '--text-on-danger': onDanger,
      '--accent': reach(c.accent, c.elev, 4.6, dark), '--accent-fill': c.accent, '--accent-hover': hover,
      '--accent-soft': rgba(c.accent, dark ? 0.16 : 0.1), '--accent-ring': rgba(c.accent, dark ? 0.55 : 0.35),
      '--danger': c.danger, '--danger-soft': rgba(c.danger, dark ? 0.16 : 0.09),
      '--warning': c.warning, '--warning-soft': rgba(c.warning, dark ? 0.16 : 0.13),
      '--success': c.success, '--success-soft': rgba(c.success, dark ? 0.16 : 0.13), '--info': c.accent,
      '--st-draft': text3, '--st-wip': c.warning, '--st-done': c.success, '--st-index': c.index, '--tile-fg': tileFg,
      ...Object.fromEntries(TILES.map((k) => [`--tile-${k}`, tiles[k]])),
      '--c-event': tiles.calendario, '--c-idea': tiles.hoy, '--c-routine': tiles.repaso,
      ...Object.fromEntries(cats.map((x, i) => [`--cat-${i}`, x])),
      '--board-bg': dark ? c.elev : '#1e1e2e', '--board-grid': dark ? rgba(sep, 0.75) : '#45475a',
      '--shadow-1': dark ? '0 1px 2px rgba(0, 0, 0, 0.35)' : '0 1px 2px rgba(0, 0, 0, 0.06), 0 1px 1px rgba(0, 0, 0, 0.03)',
      '--shadow-2': dark ? '0 6px 20px rgba(0, 0, 0, 0.4), 0 1px 3px rgba(0, 0, 0, 0.3)' : '0 4px 16px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.05)',
      '--shadow-3': dark ? '0 24px 60px rgba(0, 0, 0, 0.55), 0 6px 16px rgba(0, 0, 0, 0.35)' : '0 18px 48px rgba(0, 0, 0, 0.16), 0 4px 12px rgba(0, 0, 0, 0.06)',
      '--backdrop': dark ? rgba(sunken, 0.66) : 'rgba(0, 0, 0, 0.32)',
    };
    return { colors: c, dark, vars: v };
  }
  const css = (colors) => `:root[data-theme="propia"] {\n${Object.entries(tokens(colors).vars).map(([k, x]) => `  ${k}: ${x};`).join('\n')}\n}\n`;

  // Los pares que se leen (texto sobre fondo): AA es 4,5 en texto y 3 en lo grande o en los botones con icono
  function checks(colors) {
    const { colors: c, vars: v } = tokens(colors);
    const pairs = [
      ['Texto sobre el fondo', c.text, c.bg, 4.5], ['Texto sobre la superficie', c.text, c.elev, 4.5],
      ['Texto apagado sobre la superficie', v['--text-3'], v['--bg-elev-2'], 4.5],
      ['Enlaces sobre la superficie', v['--accent'], c.elev, 4.5], ['Texto de los botones de acento', v['--text-on-accent'], c.accent, 4.5],
      ['Texto de los botones de borrar', v['--text-on-danger'], c.danger, 4.5],
      ['Rojo sobre la superficie', c.danger, c.elev, 3], ['Naranja sobre la superficie', c.warning, c.elev, 3],
      ['Verde sobre la superficie', c.success, c.elev, 3], ['Morado sobre la superficie', c.index, c.elev, 3],
    ];
    return pairs.map(([label, fg, bg, min]) => ({ label, ratio: contrast(fg, bg), min, ok: contrast(fg, bg) >= min }));
  }

  /* ---------- Aplicar ---------- */
  function styleEl() {
    let st = document.getElementById('themePropia');
    if (!st) { st = document.createElement('style'); st.id = 'themePropia'; document.head.appendChild(st); }
    return st;
  }
  // `persist`: guardar en Prefs y en la caché de theme-init.js; sin él, solo se ve (la vista previa del editor)
  function apply(colors, { persist = true } = {}) {
    const text = css(colors);
    styleEl().textContent = text;
    if (persist) {
      try { localStorage.setItem(CSS_KEY, text); } catch {}
      if (window.Prefs) Prefs.set(PREF, tokens(colors).colors);
    }
    return text;
  }
  function saved() { return { ...DEFAULT, ...((window.Prefs && Prefs.get(PREF, null)) || {}) }; }
  // Al cargar Prefs (otro dispositivo pudo cambiarla): rehacer el CSS si difiere del guardado
  function sync() {
    const p = window.Prefs && Prefs.get(PREF, null);
    if (!p) return;
    const text = css(p);
    let cached = '';
    try { cached = localStorage.getItem(CSS_KEY) || ''; } catch {}
    if (text === cached && document.getElementById('themePropia')) return;
    apply(p, { persist: false });
    try { localStorage.setItem(CSS_KEY, text); } catch {}
    paintSwatch();
  }
  if (window.Prefs) { Prefs.ready?.then?.(sync); document.addEventListener('prefs:changed', sync); }

  /* ---------- Editor (Ajustes → Tema → «Propia» → Editar) ----------
     Cada color con su selector y su código; lo que se cambia se ve al momento en toda la página y debajo salen los
     pares que no llegan a AA. Guardar la deja como tema; Cancelar (o Esc) vuelve a lo que había. */
  function paintSwatch() {
    const c = saved();
    document.querySelectorAll('[data-theme-choice="propia"] .theme-swatch').forEach((sw) => {
      sw.style.setProperty('--p-bg', c.bg); sw.style.setProperty('--p-elev', c.elev);
      sw.style.setProperty('--p-accent', c.accent); sw.style.setProperty('--p-text', c.text);
    });
  }
  function openEditor() {
    const before = document.documentElement.getAttribute('data-theme') || 'mocha';
    const prevCss = document.getElementById('themePropia')?.textContent || '';
    let draft = saved();
    const dlg = document.createElement('dialog');
    dlg.className = 'modal modal-sm tema-propio';
    dlg.setAttribute('aria-labelledby', 'tpTitle');
    dlg.innerHTML = `<div class="modal-header"><div><h2 id="tpTitle">Mi paleta</h2><p class="modal-sub">Se ve al momento en toda la página.</p></div>
        <button type="button" class="btn btn-ghost btn-icon modal-close" data-close aria-label="Cerrar sin guardar">${icon('x')}</button></div>
      <form class="modal-body stack" id="tpForm">
        <div class="tp-grid">${FIELDS.map(([k, label]) => `<div class="tp-field">
          <label class="tp-label" for="tp-${k}">${label}</label>
          <div class="tp-inputs"><input type="color" id="tp-${k}-pick" data-tp-pick="${k}" value="${draft[k]}" aria-label="${label}: elegir">
            <input class="input input-sm tabular" id="tp-${k}" data-tp="${k}" value="${draft[k]}" maxlength="7" spellcheck="false" autocomplete="off"></div></div>`).join('')}</div>
        <div class="tp-sample" aria-hidden="true">
          <div class="tp-card"><b>Así se ve</b><span>Texto secundario</span><small>Texto apagado</small>
            <div class="tp-row"><span class="btn btn-primary btn-sm">Acento</span><span class="tag">Etiqueta</span><a class="link-btn">Enlace</a></div>
            <div class="tp-row"><span class="tp-dot" style="background:var(--danger)"></span><span class="tp-dot" style="background:var(--warning)"></span>
              <span class="tp-dot" style="background:var(--success)"></span><span class="tp-dot" style="background:var(--st-index)"></span>
              ${['hoy', 'calendario', 'rutinas', 'tareas', 'notas', 'comidas'].map((t) => `<span class="tile" data-section="${t}"></span>`).join('')}</div></div>
        </div>
        <div class="tp-checks" id="tpChecks" aria-live="polite"></div>
      </form>
      <div class="modal-footer"><button type="button" class="btn btn-ghost" data-tp-reset>Restablecer</button><span class="spacer"></span>
        <button type="button" class="btn" data-close>Cancelar</button><button type="submit" form="tpForm" class="btn btn-primary">Guardar</button></div>`;
    document.body.appendChild(dlg);
    wireAllDialogs();
    let saved_ = false;
    const preview = () => {
      apply(draft, { persist: false });
      document.documentElement.setAttribute('data-theme', 'propia');
      const bad = checks(draft).filter((x) => !x.ok);
      dlg.querySelector('#tpChecks').innerHTML = bad.length
        ? `<p class="notice warn">${icon('triangle-alert', 'icon-sm')}<span>No llega a AA: ${bad.map((x) => `${escapeHtml(x.label)} (${x.ratio.toFixed(1).replace('.', ',')}:1, hace falta ${String(x.min).replace('.', ',')})`).join(' · ')}</span></p>`
        : `<p class="small tp-ok">${icon('circle-check', 'icon-sm')}Todo se lee bien (AA).</p>`;
    };
    const set = (k, v) => {
      if (!valid(v)) return;
      draft = { ...draft, [k]: v.toLowerCase() };
      dlg.querySelector(`[data-tp="${k}"]`).value = draft[k];
      dlg.querySelector(`[data-tp-pick="${k}"]`).value = draft[k];
      preview();
    };
    dlg.addEventListener('input', (e) => {
      const k = e.target.dataset.tpPick || e.target.dataset.tp;
      if (!k) return;
      let v = e.target.value.trim();
      if (e.target.dataset.tp && !v.startsWith('#')) v = '#' + v;
      if (valid(v)) set(k, v);
    });
    dlg.querySelector('[data-tp-reset]').addEventListener('click', () => { Object.entries(DEFAULT).forEach(([k, v]) => set(k, v)); });
    dlg.querySelector('form').addEventListener('submit', (e) => {
      e.preventDefault();
      saved_ = true;
      apply(draft);
      setThemeFromEditor();
      closeModal(dlg);
      toast('Paleta propia guardada');
    });
    preview();
    openModal(dlg, {
      focus: '[data-tp="bg"]',
      onClose: () => {
        if (!saved_) { styleEl().textContent = prevCss; document.documentElement.setAttribute('data-theme', before); }
        paintSwatch();
        dlg.remove();
      },
    });
  }
  // Guardar deja «propia» como tema, igual que elegirla en la cuadrícula
  function setThemeFromEditor() {
    document.querySelector('[data-theme-choice="propia"]')?.click();
    try { localStorage.setItem('theme', 'propia'); } catch {}
    document.documentElement.setAttribute('data-theme', 'propia');
  }
  document.addEventListener('click', (e) => { if (e.target.closest('[data-tp-open]')) openEditor(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', paintSwatch); else paintSwatch();

  window.TemaPropio = { DEFAULT, FIELDS, tokens, css, checks, apply, saved, contrast, valid, openEditor };
})();
