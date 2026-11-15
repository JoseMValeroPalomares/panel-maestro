/* ==========================================================================
   contexto.js — el contexto activo (Puntual · Universidad · Proyectos · Todo) — window.Ctx
   Una sola lógica para todas las pantallas: Tareas, Inbox, Calendario, Hoy y la paleta.

     Ctx.active()            'puntual' | 'universidad' | 'proyectos' | 'todo' (preferencia `contexto`,
                             guardada en el servidor: la misma que leen la Waybar y la extensión)
     Ctx.set(c)              lo cambia y emite «contexto:changed»
     Ctx.match(it, c)        la regla de filtrado (la misma que app/contextos.py:matches)
     Ctx.mount(el)           pinta el control segmentado y lo mantiene al día
     Ctx.chip(it)            etiqueta con el color de la asignatura o del proyecto
     Ctx.forNew()            el contexto con el que se crea algo desde una lista filtrada
     Ctx.load()              asignaturas, proyectos y versiones (GET /api/contextos)
   ========================================================================== */
(function () {
  'use strict';

  const KEY = 'contexto';
  const LIST = [
    { id: 'puntual', label: 'Puntual', icon: 'zap' },
    { id: 'universidad', label: 'Universidad', icon: 'graduation-cap' },
    { id: 'proyectos', label: 'Proyectos', icon: 'rocket' },
    { id: 'todo', label: 'Todo', icon: 'layers' },
  ];
  const VALID = new Set(LIST.map((c) => c.id));
  const D = { asignaturas: [], proyectos: [], versiones: [], loaded: false };
  let loading = null;

  const active = () => {
    const v = window.Prefs ? Prefs.get(KEY, 'todo') : 'todo';
    return VALID.has(v) ? v : 'todo';
  };

  function set(c) {
    if (!VALID.has(c) || c === active()) return;
    Prefs.set(KEY, c);
    document.dispatchEvent(new CustomEvent('contexto:changed', { detail: { contexto: c } }));
  }

  // Otra pestaña (o la Waybar/extensión, vía servidor) lo cambió: Prefs avisa con prefs:changed
  let last = null;
  document.addEventListener('prefs:changed', () => {
    const now = active();
    if (last !== null && now !== last) document.dispatchEvent(new CustomEvent('contexto:changed', { detail: { contexto: now } }));
    last = now;
  });
  window.Prefs?.ready?.then(() => { last = active(); }).catch(() => {});

  const match = (it, c = active()) => c === 'todo' || (it.contexto || 'puntual') === c;
  const forNew = () => (active() === 'todo' ? 'puntual' : active());

  function load(force = false) {
    if (D.loaded && !force) return Promise.resolve(D);
    loading ||= api('/api/contextos', { quiet: true }).then((d) => {
      Object.assign(D, d, { loaded: true });
      document.dispatchEvent(new CustomEvent('contexto:data'));
      return D;
    }).finally(() => { loading = null; });
    return loading;
  }
  onDataChange?.(/^\/api\/(uni|proyectos|contextos)/, () => { if (D.loaded) load(true).catch(() => {}); });

  const asig = (id) => D.asignaturas.find((a) => a.id === id);
  const proy = (id) => D.proyectos.find((p) => p.id === id);
  const color = (c) => (c && /^cat-\d$/.test(c) ? `var(--${c})` : 'var(--text-3)');

  // Etiqueta de dónde va algo: «GABD» con su color o «#panel-maestro»
  function chip(it, { link = true } = {}) {
    if (it.asignatura_id) {
      const code = it.asignatura || asig(it.asignatura_id)?.codigo || 'Asignatura';
      const inner = `<span class="ctx-dot" style="background:${color(it.color || asig(it.asignatura_id)?.color)}"></span>${escapeHtml(code)}`;
      return link ? `<a class="ctx-chip no-drag" href="/universidad?asignatura=${it.asignatura_id}" title="${escapeHtml(it.asignatura_nombre || code)}">${inner}</a>`
        : `<span class="ctx-chip" title="${escapeHtml(it.asignatura_nombre || code)}">${inner}</span>`;
    }
    if (it.proyecto_id) {
      const slug = it.proyecto || proy(it.proyecto_id)?.slug || 'proyecto';
      const inner = `<span class="ctx-dot" style="background:${color(it.color || proy(it.proyecto_id)?.color)}"></span>#${escapeHtml(slug)}`;
      return link ? `<a class="ctx-chip no-drag" href="/proyectos/${encodeURIComponent(slug)}" title="${escapeHtml(it.proyecto_nombre || slug)}">${inner}</a>`
        : `<span class="ctx-chip">${inner}</span>`;
    }
    return '';
  }

  // Control segmentado: Puntual · Universidad · Proyectos · Todo
  function html({ compact = false, label = 'Contexto' } = {}) {
    const c = active();
    return `<div class="segmented ctx-switch${compact ? ' is-compact' : ''}" role="radiogroup" aria-label="${escapeHtml(label)}">
      ${LIST.map((x) => `<button type="button" role="radio" data-ctx="${x.id}" aria-checked="${x.id === c}" aria-pressed="${x.id === c}"
        title="${x.label}">${icon(x.icon, 'icon-sm')}<span class="${compact ? 'ctx-label' : ''}">${x.label}</span></button>`).join('')}
    </div>`;
  }

  function mount(el, opts = {}) {
    if (!el) return;
    const paint = () => {
      el.innerHTML = html(opts);
      el.querySelectorAll('[data-ctx]').forEach((b) => b.addEventListener('click', () => set(b.dataset.ctx)));
      el.querySelector('[role=radiogroup]').addEventListener('keydown', (e) => {  // flechas como en un radiogroup
        if (!['ArrowLeft', 'ArrowRight'].includes(e.key)) return;
        e.preventDefault();
        const i = LIST.findIndex((x) => x.id === active());
        const next = LIST[(i + (e.key === 'ArrowRight' ? 1 : LIST.length - 1)) % LIST.length].id;
        set(next);
        el.querySelector(`[data-ctx="${next}"]`)?.focus();
      });
    };
    paint();
    document.addEventListener('contexto:changed', paint);
    window.Prefs?.ready?.then(paint).catch(() => {});
  }

  // Opciones de «dónde va» (editor de tareas, captura): contexto, asignatura o proyecto
  function whereOptions(it = {}) {
    const cur = it.asignatura_id ? `a:${it.asignatura_id}` : it.proyecto_id ? `p:${it.proyecto_id}` : (it.contexto || forNew());
    const opt = (v, l) => `<option value="${v}" ${v === cur ? 'selected' : ''}>${escapeHtml(l)}</option>`;
    return opt('puntual', 'Puntual')
      + `<optgroup label="Universidad">${opt('universidad', 'Universidad (sin asignatura)')}${D.asignaturas.map((a) => opt(`a:${a.id}`, `${a.codigo} · ${a.nombre}`)).join('')}</optgroup>`
      + `<optgroup label="Proyectos">${opt('proyectos', 'Proyectos (sin proyecto)')}${D.proyectos.filter((p) => p.estado !== 'terminado' || p.id === it.proyecto_id).map((p) => opt(`p:${p.id}`, p.nombre)).join('')}</optgroup>`;
  }

  // «a:3» → {asignatura_id: 3}; «p:2» → {proyecto_id: 2}; «universidad» → {contexto: 'universidad'}
  function whereToPatch(v) {
    if (v.startsWith('a:')) return { asignatura_id: Number(v.slice(2)) };
    if (v.startsWith('p:')) return { proyecto_id: Number(v.slice(2)) };
    return { contexto: v };
  }
  const whereOf = (it) => (it.asignatura_id ? `a:${it.asignatura_id}` : it.proyecto_id ? `p:${it.proyecto_id}` : (it.contexto || 'puntual'));

  /* ---------- Abrir carpetas y archivos en el portátil (scripts/desktop/abrir) ----------
     El navegador no abre file:// desde http, y el servidor abriría la ventana en su propia pantalla.
     panelmaestro://abrir/<tipo>/<id> lo recibe el abridor instalado en el portátil, que pide al panel la
     ruta RELATIVA de ese id y la valida contra sus raíces permitidas (~/.config/panel-maestro/abrir.conf). */
  function openFolder(tipo, id) {
    const a = document.createElement('a');
    a.href = `panelmaestro://abrir/${encodeURIComponent(tipo)}/${Number(id)}`;
    a.rel = 'noopener';
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast('Abriendo en el portátil…', { type: 'info', duration: 2600,
      action: { label: '¿No se abre?', onClick: () => uiAlert?.('Abrir carpetas', 'Instala el abridor en el portátil: scripts/desktop/abrir/instalar.sh (README → «Abrir carpetas»). Mientras tanto, usa «Copiar ruta».') } });
  }
  // Se llama directamente en el clic (sin await antes): así el copiado por HTTP cuenta como gesto del usuario
  function copyPath(path) {
    if (!path) { toast('Esta carpeta no tiene ruta en este equipo', { type: 'info' }); return; }
    copyText(path).then((ok) => toast(ok ? 'Ruta copiada' : 'No se pudo copiar', { type: ok ? 'success' : 'error', duration: 1600 }));
  }

  // Los huecos [data-ctx-switch] de las plantillas se montan solos (data-ctx-compact: versión estrecha)
  document.querySelectorAll('[data-ctx-switch]').forEach((el) => mount(el, { compact: 'ctxCompact' in el.dataset }));

  window.Ctx = {
    openFolder, copyPath,
    LIST, active, set, match, forNew, load, mount, html, chip, color, asig, proy, whereOptions, whereToPatch, whereOf,
    get data() { return D; },
    label: (c) => LIST.find((x) => x.id === c)?.label || c,
  };
})();
