/* ==========================================================================
   movimiento.js — motor de movimiento común (window.Mov). Ver DESIGN.md «Movimiento» y docs/plan-animaciones.md.
   Sin dependencias: WAAPI + los muelles de ds.css (--spring*) + un único bucle rAF que se apaga solo.

     Mov.reduce()                              → true con «reducir movimiento» (o sin Element.animate): estado final ya
     Mov.loop(fn)                              → fn(dt) en cada fotograma mientras devuelva true; devuelve «parar»
     Mov.spring({ value, k, c, onUpdate })     → muelle: .to(objetivo), .jump(valor), .stop(); persigue objetivos que cambian
     Mov.flip(elementos, mutar, opts)          → anima de la posición vieja a la nueva lo que `mutar()` recoloca
     Mov.flipList(root, sel, keyOf, pintar)    → repinta una lista: las filas que siguen viajan, las nuevas suben
     Mov.roll(el, texto)                       → las cifras que cambian ruedan (sube = desde abajo, baja = desde arriba)
     Mov.keepRoll(root, sel, attr, pintar)     → repinta y hace rodar los contadores `sel` (identificados por `attr`)
     Mov.tick(cls)                             → <svg> de ✓ cuyo trazo se dibuja (clase .tick-draw de ds.css)
     Mov.ringHTML(cls) / Mov.ring(el, 0…1)     → anillo de progreso con muelle; al completarse dibuja un ✓ y se pone verde
     Mov.heatmap(grid, opts)                   → mapa de actividad: ola al aparecer, racha encendida, contorno que salta
     Mov.stagger(els, keyframes, opts)         → la misma animación en cascada (tope de elementos animados)
     Mov.glide(contenedor, opts)               → resaltado que se desliza entre filas con dos muelles (borde delantero
                                                 y trasero): .to(el), .hide(), .refresh(), .track(ms), .destroy()
     Mov.shake(el)                             → temblor corto (error)

   Reglas: nada bloquea el clic siguiente; lo interrumpido parte de donde está; en reposo no hay rAF vivo.
   ========================================================================== */
(function () {
  'use strict';

  const mq = window.matchMedia ? matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };
  const reduce = () => mq.matches || !Element.prototype.animate;
  const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  const SPRING = () => css('--spring', 'cubic-bezier(0.34, 1.3, 0.64, 1)');
  const SPRING_SUAVE = () => css('--spring-suave', 'cubic-bezier(0.3, 1.1, 0.5, 1)');

  /* ---------- Un solo bucle rAF para todo lo que persigue un objetivo ---------- */
  const tareas = new Set();
  let raf = 0, last = 0;
  function frame(t) {
    const dt = Math.min(1 / 30, Math.max(0, (t - last) / 1000));
    last = t;
    for (const fn of [...tareas]) {
      let vivo = false;
      try { vivo = fn(dt); } catch (e) { console.error(e); }
      if (!vivo) tareas.delete(fn);
    }
    raf = tareas.size ? requestAnimationFrame(frame) : 0;
  }
  function loop(fn) {
    tareas.add(fn);
    if (!raf) { last = performance.now(); raf = requestAnimationFrame(frame); }
    return () => tareas.delete(fn);
  }

  /* ---------- Muelle amortiguado (Euler semi-implícito en pasos de 1/240 s) ---------- */
  function spring({ value = 0, k = 260, c = 26, eps = 0.05, onUpdate = () => {}, onRest = () => {} } = {}) {
    const s = { x: value, v: 0, target: value, running: false, cancel: null };
    const paso = (dt) => {
      let resto = dt;
      while (resto > 0) {
        const h = Math.min(resto, 1 / 240);
        const a = -k * (s.x - s.target) - c * s.v;
        s.v += a * h; s.x += s.v * h; resto -= h;
      }
      const quieto = Math.abs(s.x - s.target) < eps && Math.abs(s.v) < eps * 10;
      if (quieto) { s.x = s.target; s.v = 0; }
      onUpdate(s.x);
      if (quieto) { s.running = false; onRest(s.x); }
      return !quieto;
    };
    return {
      get value() { return s.x; },
      get target() { return s.target; },
      to(target) {
        s.target = target;
        if (reduce()) { s.x = target; s.v = 0; onUpdate(s.x); return this; }
        if (!s.running) { s.running = true; s.cancel = loop(paso); }
        return this;
      },
      jump(v) { s.x = v; s.v = 0; s.target = v; onUpdate(v); return this; },
      kick(v) { s.v += v; if (!s.running && !reduce()) { s.running = true; s.cancel = loop(paso); } return this; },
      stop() { s.cancel?.(); s.running = false; return this; },
    };
  }

  /* ---------- FLIP: lo que `mutar` mueve viaja desde donde estaba ---------- */
  function flip(elements, mutate, { duration = 420, easing = null, stagger = 0, max = 40 } = {}) {
    const els = [...elements].filter((e) => e && e.isConnected);
    if (reduce() || !els.length) { mutate(); return Promise.resolve(); }
    const antes = new Map(els.map((e) => [e, e.getBoundingClientRect()]));
    mutate();
    const ease = easing || SPRING_SUAVE();
    const anims = [];
    let i = 0;
    for (const [e, r] of antes) {
      if (!e.isConnected) continue;
      const n = e.getBoundingClientRect();
      const dx = r.left - n.left, dy = r.top - n.top;
      if (Math.abs(dx) < 0.5 && Math.abs(dy) < 0.5) continue;
      if (n.bottom < -50 || n.top > innerHeight + 50) continue;  // fuera de la vista: sin animar
      if (i >= max) break;
      anims.push(e.animate([{ translate: `${dx}px ${dy}px` }, { translate: '0 0' }],
        { duration, easing: ease, delay: Math.min(i++, 12) * stagger, composite: 'add' }).finished.catch(() => {}));
    }
    return Promise.all(anims);
  }

  /* ---------- Lista que se recoloca al repintarse (filtrar escribiendo) ----------
     `paint()` vuelve a pintar `root`; las filas (selector) que sigan, identificadas por keyOf(el), viajan desde su sitio
     anterior; las nuevas suben en cascada. La primera vez (sin filas antes) no anima nada. */
  function flipList(root, selector, keyOf, paint, { max = 80 } = {}) {
    if (!root || reduce()) { paint(); return; }
    const antes = new Map();
    root.querySelectorAll(selector).forEach((el) => {
      const k = keyOf(el);
      if (k != null && !antes.has(k) && el.getClientRects().length) antes.set(k, el.getBoundingClientRect());
    });
    paint();
    if (!antes.size) return;
    const filas = [...root.querySelectorAll(selector)];
    if (filas.length > max) return;
    const nuevos = [];
    const ease = SPRING_SUAVE();
    for (const el of filas) {
      if (!el.getClientRects().length) continue;
      const n = el.getBoundingClientRect();
      if (n.bottom < 0 || n.top > innerHeight) continue;
      const r = antes.get(keyOf(el));
      if (!r) { nuevos.push(el); continue; }
      const dx = r.left - n.left, dy = r.top - n.top;
      if (Math.abs(dx) > 0.5 || Math.abs(dy) > 0.5) {
        el.animate([{ translate: `${dx}px ${dy}px` }, { translate: '0 0' }], { duration: 420, easing: ease, composite: 'add' });
      }
    }
    stagger(nuevos, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }],
      { each: 18, duration: 260, easing: 'cubic-bezier(0.16, 1, 0.3, 1)' });
  }

  /* ---------- Cifras que ruedan ---------- */
  // Cada carácter que cambia va en una ventana (.roll-w, recortada con clip-path, que no mueve la línea base); el
  // nuevo es texto de verdad y el viejo un ::before, así que textContent siempre dice el valor actual.
  function roll(el, text) {
    if (!el) return;
    const nuevo = String(text ?? '');
    // A mitad de un rodar, el valor bueno es el guardado; si no, lo que se ve (alguien pudo cambiarlo sin Mov)
    const viejo = el.querySelector(':scope > .roll-w') ? (el.dataset.rollValue ?? el.textContent) : el.textContent;
    if (nuevo === viejo && !el.querySelector(':scope > .roll-w')) { el.dataset.rollValue = nuevo; return; }
    el.dataset.rollValue = nuevo;
    clearTimeout(el._rollT);
    if (reduce() || viejo === '' || nuevo === viejo || !el.isConnected) { el.textContent = nuevo; return; }
    const num = (s) => parseFloat(String(s).replace(/[^\d,.-]/g, '').replace(',', '.'));
    const a = num(nuevo), b = num(viejo);
    const sube = Number.isNaN(a) || Number.isNaN(b) ? true : a >= b;
    // Se alinean por la derecha (las unidades con las unidades)
    const n = Math.max(nuevo.length, viejo.length);
    const nv = nuevo.padStart(n, '\u0000'), vj = viejo.padStart(n, '\u0000');
    const frag = document.createDocumentFragment();
    let k = 0;
    for (let i = 0; i < n; i++) {
      const c = nv[i], o = vj[i];
      if (c === '\u0000') continue;
      if (c === o) { frag.append(c); continue; }
      const w = document.createElement('span');
      w.className = 'roll-w';
      const ch = document.createElement('span');
      ch.className = 'roll-ch';
      ch.dataset.dir = sube ? 'up' : 'down';
      ch.dataset.old = o === '\u0000' ? '' : o;
      ch.style.setProperty('--roll-i', String(Math.min(k++, 6)));
      ch.textContent = c;
      w.append(ch);
      frag.append(w);
    }
    el.replaceChildren(frag);
    el._rollT = setTimeout(() => { if (el.dataset.rollValue === nuevo) el.textContent = nuevo; }, 900);
  }

  // Para listas que se repintan con innerHTML: recuerda los contadores (selector + atributo que los identifica), pinta y
  // hace rodar los que cambiaron. Devuelve lo que devuelva `paint`.
  function keepRoll(root, selector, key, paint) {
    const antes = new Map();
    root?.querySelectorAll(selector).forEach((el) => antes.set(el.getAttribute(key), el.dataset.rollValue ?? el.textContent));
    const r = paint();
    root?.querySelectorAll(selector).forEach((el) => {
      const prev = antes.get(el.getAttribute(key)), now = el.textContent;
      if (prev == null || prev === now) return;
      el.textContent = prev; el.dataset.rollValue = prev;
      roll(el, now);
    });
    return r;
  }

  /* ---------- ✓ que se dibuja ---------- */
  const tick = (cls = '') => `<svg class="tick-draw ${cls}" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path pathLength="1" d="M20 6 9 17l-5-5"/></svg>`;

  /* ---------- Anillo de progreso (fracción de 0 a 1; al llegar a 1 se dibuja un ✓ y pasa a verde) ---------- */
  const ringHTML = (cls = '') => `<span class="mv-ring ${cls}" aria-hidden="true"><svg viewBox="0 0 24 24"><circle class="mv-ring-track" cx="12" cy="12" r="10"></circle>
    <circle class="mv-ring-arc" cx="12" cy="12" r="10" pathLength="1" transform="rotate(-90 12 12)"></circle>
    <path class="mv-ring-tick" pathLength="1" d="M7.4 12.4 10.5 15.3 16.6 8.9"></path></svg></span>`;
  // jump: ponerlo sin animar (primera vez, otro día). onUpdate(v) para lo que lo acompañe (un porcentaje)
  function ring(el, hasta, { jump = false, onUpdate = null } = {}) {
    if (!el) return;
    const arc = el.querySelector('.mv-ring-arc');
    hasta = Math.max(0, Math.min(1, hasta || 0));
    const pinta = (v) => { arc.style.strokeDashoffset = String(1 - v); arc.style.opacity = v > 0.004 ? '1' : '0'; onUpdate?.(v); };
    const completo = hasta >= 0.9999, desde = el._ringV;
    el.classList.toggle('is-done', completo);
    if (!el._ringS) el._ringS = spring({ value: desde ?? hasta, k: 120, c: 22, eps: 0.002, onUpdate: pinta });
    const sp = el._ringS;
    if (desde == null || jump || reduce()) { sp.stop().jump(hasta); el.classList.toggle('tick-on', completo); }
    else if (desde !== hasta) {
      sp.to(hasta);
      el.classList.toggle('tick-on', completo);
      if (completo && desde < 1) el.animate([{ scale: '1' }, { scale: '1.14' }, { scale: '1' }], { duration: 520, easing: 'cubic-bezier(0.16, 1, 0.3, 1)', delay: 420 });
    } else pinta(hasta);
    el._ringV = hasta;
  }

  /* ---------- Mapa de actividad (activity-heatmap) ----------
     grid: el contenedor de las celdas; cells: las celdas en orden de días; fila(i)/col(i): su sitio; on(el): si cuenta
     para la racha; label(el): el texto de la etiqueta. Al aparecer, las celdas surgen en ola diagonal; luego la racha
     más larga se enciende celda a celda; con ratón, un contorno salta de celda en celda con un muelle y una etiqueta
     lo acompaña (sustituye al title nativo, que salía tarde y doble). */
  function heatmap(grid, { cells, fila, col, on, label, entrada = true }) {
    if (!grid || !cells?.length) return;
    const vivo = !reduce() && entrada;
    if (vivo) cells.forEach((c, i) => c.animate([{ transform: 'scale(0.3)', opacity: 0 }, { transform: 'none', opacity: 1 }],
      { duration: 420, easing: SPRING(), delay: Math.min(fila(i) + col(i), 40) * 14, fill: 'backwards' }));
    // La racha más larga
    let best = [0, -1], start = -1;
    cells.forEach((c, i) => {
      if (on(c)) { if (start < 0) start = i; if (i - start > best[1] - best[0]) best = [start, i]; } else start = -1;
    });
    if (vivo && best[1] >= best[0] + 1) {
      const t0 = Math.min(40, fila(cells.length - 1) + col(cells.length - 1)) * 14 + 300;
      cells.slice(best[0], best[1] + 1).forEach((c, k) => {
        c.classList.add('is-streak');
        c.style.setProperty('--streak-delay', `${t0 + Math.min(k, 40) * 28}ms`);
      });
    }
    if (!window.matchMedia('(hover: hover)').matches) return;
    const host = grid.parentElement;
    if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
    // Si el mapa se vuelve a pintar en el mismo sitio, se reutilizan el contorno y la etiqueta y se quitan los oyentes viejos
    grid._heatOff?.();
    const box = host.querySelector(':scope > .heat-focus') || Object.assign(document.createElement('span'), { className: 'heat-focus' });
    const tag = host.querySelector(':scope > .heat-tag') || Object.assign(document.createElement('span'), { className: 'heat-tag' });
    box.setAttribute('aria-hidden', 'true'); tag.setAttribute('aria-hidden', 'true');
    box.classList.remove('is-on'); tag.classList.remove('is-on');
    if (!box.isConnected) host.append(box, tag);
    cells.forEach((c) => { if (c.title) { c.dataset.label = c.title; c.removeAttribute('title'); } });
    let w = 0, h = 0;
    const pinta = () => {
      box.style.translate = `${x.value}px ${y.value}px`;
      tag.style.translate = `calc(${x.value + w / 2}px - 50%) ${y.value - 6}px`;
    };
    const x = spring({ k: 520, c: 30, eps: 0.2, onUpdate: pinta }), y = spring({ k: 520, c: 30, eps: 0.2, onUpdate: pinta });
    let visto = false;
    const mover = (e) => {
      const c = e.target.closest?.('[data-label]');
      if (!c || !cells.includes(c)) return;
      const hr = host.getBoundingClientRect(), r = c.getBoundingClientRect();
      w = r.width; h = r.height;
      box.style.width = `${w + 4}px`; box.style.height = `${h + 4}px`;
      tag.textContent = label ? label(c) : c.dataset.label;
      const tx = r.left - hr.left - 2, ty = r.top - hr.top - 2;
      if (!visto) { x.jump(tx); y.jump(ty); } else { x.to(tx); y.to(ty); }
      visto = true;
      box.classList.add('is-on'); tag.classList.add('is-on');
    };
    const salir = () => { visto = false; box.classList.remove('is-on'); tag.classList.remove('is-on'); };
    grid.addEventListener('pointermove', mover);
    grid.addEventListener('pointerleave', salir);
    grid._heatOff = () => { grid.removeEventListener('pointermove', mover); grid.removeEventListener('pointerleave', salir); x.stop(); y.stop(); };
  }

  /* ---------- Cascada ---------- */
  function stagger(elements, keyframes, { each = 30, max = 12, duration = 360, easing = null, delay = 0, fill = 'backwards' } = {}) {
    const els = [...elements].filter(Boolean);
    if (reduce()) return Promise.resolve();
    const ease = easing || SPRING();
    return Promise.all(els.map((e, i) => e.animate(keyframes, {
      duration, easing: ease, fill, delay: delay + Math.min(i, max) * each,
    }).finished.catch(() => {})));
  }

  /* ---------- Temblor ---------- */
  function shake(el) {
    if (!el || reduce()) return;
    el.animate([{ translate: '0' }, { translate: '-6px' }, { translate: '5px' }, { translate: '-3px' }, { translate: '2px' }, { translate: '0' }],
      { duration: 380, easing: 'ease-out', composite: 'add' });
  }

  /* ---------- Resaltado que se desliza (dos muelles: borde delantero rígido, trasero blando) ---------- */
  // contenedor: el que tiene las filas (pasa a position: relative si es static). La píldora va debajo de las filas
  // (z-index -1 dentro de un contenedor con isolation). `axis`: 'y' (lista) o 'x' (pestañas).
  function glide(container, { className = 'glide-pill', axis = 'y', inset = 0 } = {}) {
    if (!container) return null;
    if (getComputedStyle(container).position === 'static') container.style.position = 'relative';
    container.style.isolation = 'isolate';
    const pill = document.createElement('span');
    pill.className = className;
    pill.setAttribute('aria-hidden', 'true');
    container.prepend(pill);
    let actual = null, shown = false, tBack = 0;
    // Una fila dentro de una zona que se está plegando (inert) ya no cuenta como visible
    const visible = (el) => !!el && el.isConnected && container.contains(el) && el.getClientRects().length > 0 && !el.closest('[inert]');
    const pinta = () => {
      const a = Math.min(lo.value, hi.value), b = Math.max(lo.value, hi.value);
      if (axis === 'y') { pill.style.translate = `0 ${a}px`; pill.style.height = `${b - a}px`; }
      else { pill.style.translate = `${a}px 0`; pill.style.width = `${b - a}px`; }
    };
    // El borde que va en cabeza es rígido; el que le sigue, blando: se estira al viajar y se recoge al llegar
    const lo = spring({ k: 420, c: 34, eps: 0.3, onUpdate: pinta });
    const hi = spring({ k: 420, c: 34, eps: 0.3, onUpdate: pinta });
    // Con offsetTop/offsetLeft (no con getBoundingClientRect): así no engaña la escala de un diálogo que se está abriendo
    const medir = (el) => {
      let x = 0, y = 0, n = el;
      while (n && n !== container) { x += n.offsetLeft; y += n.offsetTop; n = n.offsetParent; }
      if (n !== container) {  // otro contenedor posicionado en medio: por cajas
        const c = container.getBoundingClientRect(), r = el.getBoundingClientRect();
        x = r.left - c.left + container.scrollLeft; y = r.top - c.top + container.scrollTop;
      }
      const w = el.offsetWidth, h = el.offsetHeight;
      if (axis === 'y') {
        pill.style.left = `${x + inset}px`; pill.style.width = `${w - inset * 2}px`;
        return [y, y + h];
      }
      pill.style.top = `${y + inset}px`; pill.style.height = `${h - inset * 2}px`;
      return [x, x + w];
    };
    // want = la fila que se quiere marcar (aunque ahora esté oculta, p. ej. dentro de un grupo plegado); actual = la
    // que se marca de verdad
    let want = null;
    const ocultar = () => { shown = false; actual = null; pill.classList.remove('is-on'); };
    return {
      el: pill,
      get current() { return actual; },
      to(el) {
        want = el || null;
        if (!visible(el)) { ocultar(); return; }
        if (pill.parentNode !== container) container.prepend(pill);  // un innerHTML del contenedor se la llevó
        const [a, b] = medir(el);
        if (!shown || reduce()) {
          clearTimeout(tBack);
          lo.stop().jump(a); hi.stop().jump(b);
          shown = true; pill.classList.add('is-on');
        } else {
          const baja = a > lo.target;
          // El borde de delante (hacia donde va) es rígido; el de detrás arranca un poco después
          const [front, back] = baja ? [hi, lo] : [lo, hi];
          clearTimeout(tBack);
          front.to(baja ? b : a);
          tBack = setTimeout(() => back.to(baja ? a : b), 45);
        }
        actual = el;
      },
      refresh() {
        if (!visible(want)) { ocultar(); return; }
        if (!shown || actual !== want) { this.to(want); return; }
        const [a, b] = medir(actual); lo.stop().jump(a); hi.stop().jump(b);
      },
      // Seguir a la fila mientras lo de alrededor cambia de alto (un plegable que se abre encima), durante `ms`
      track(ms = 450) {
        const hasta = performance.now() + ms;
        loop(() => { if (want) this.refresh(); return performance.now() < hasta; });
      },
      hide() { want = null; ocultar(); },
      destroy() { clearTimeout(tBack); lo.stop(); hi.stop(); pill.remove(); },
    };
  }

  window.Mov = { reduce, loop, spring, flip, flipList, roll, keepRoll, tick, ring, ringHTML, heatmap, stagger, shake, glide };
})();
