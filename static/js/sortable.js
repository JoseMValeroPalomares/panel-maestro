/* ==========================================================================
   sortable.js — arrastrar y soltar para ordenar (ratón, táctil y teclado)
   Un único componente para Inbox, Baúl y Notas. Script clásico: expone
   window.Sortable.

     Sortable.create(lista, {
       group: 'inbox',                 // listas del mismo grupo intercambian elementos
       items: '.inbox-card',           // hijos directos que se pueden mover
       handle: '[data-drag-handle]',   // opcional: asa que arrastra al instante en táctil
       data: { kind: 'tarea' },        // lo que quieras saber de la lista en accepts/onDrop
       label: 'Tareas',                // para los anuncios de lector de pantalla
       accepts(ctx) { return true | 'Motivo por el que no se puede' },
       nest(itemEl) { return listaDeHijos | null },  // opcional: soltar sobre la franja central
                                                     // de un elemento lo mete al final de esa lista
       ghost(clon, itemEl) { return true },          // opcional: retocar lo que se arrastra (true = alto libre)
       async onDrop(ctx) { ... }       // persistir; si lanza, se deshace el movimiento
     });
     Sortable.addDropTarget(el, { accepts(ctx), onDrop(ctx) })   // destinos externos (tablero)

   ctx = { item, id, from, to, index, fromIndex, point } (from/to = opciones de cada lista)
   ========================================================================== */
(function () {
  'use strict';

  const START_DISTANCE = 5;      // px de ratón antes de empezar a arrastrar
  const LONG_PRESS_MS = 320;     // pulsación larga en táctil
  const TOUCH_SLOP = 8;          // px que puede moverse el dedo durante la pulsación larga
  const EDGE = 56;               // px desde el borde para el desplazamiento automático
  const SETTLE_MS = 90;          // en una rejilla, el hueco espera a que el puntero pare: cruzarla no revuelve las tarjetas
  const STILL_PX = 4;            // lo que puede temblar el puntero sin dejar de estar parado
  const STICK = 10;              // px de margen antes de cambiar de celda: sin temblores en la frontera
  const NEST_HEIGHT = 44;        // zona de una tarjeta de rejilla donde soltar para meter dentro: abajo a la derecha, en px
  const NEST_WIDTH = 0.5;        // y en parte del ancho
  const reduceMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const lists = [];              // { el, opts }
  const targets = [];            // destinos externos { el, opts }
  let drag = null;               // estado del arrastre en curso
  let live = null;               // región aria-live para anuncios

  function announce(text) {
    if (!live) {
      live = document.createElement('div');
      live.className = 'sr-only';
      live.setAttribute('aria-live', 'assertive');
      document.body.appendChild(live);
    }
    live.textContent = '';
    setTimeout(() => { live.textContent = text; }, 30);
  }

  function hint(text) {
    if (window.toast) window.toast(text, { type: 'info', duration: 2400 });
  }

  const listOf = (el) => lists.find((l) => l.el === el);
  const itemsOf = (l, except) => [...l.el.children].filter((c) => c.matches(l.opts.items) && c !== except);
  const idOf = (l, item) => (l.opts.id ? l.opts.id(item) : item.dataset.id);

  /* ---------- Rejillas: se busca sobre una foto, no sobre lo que se ve ----------
     Mover el hueco recoloca las tarjetas, y con tamaños distintos lo hace mucho. Si el destino saliera de lo que se ve, cada
     cambio cambiaría el destino y entraría en bucle. La foto (relativa a la lista: el desplazamiento no la invalida) se hace
     al empezar o la primera vez que se entra en la lista, y el destino es solo función de dónde está el puntero. */
  function measure(l, home) {
    const box = l.el.getBoundingClientRect();
    const els = itemsOf(l, null);
    const rects = els.map((c) => {
      const r = c.getBoundingClientRect();
      return { left: r.left - box.left, right: r.right - box.left, top: r.top - box.top, bottom: r.bottom - box.top };
    });
    const style = getComputedStyle(l.el);
    const grid = (style.display === 'grid' && style.gridTemplateColumns.split(' ').length > 1) || rects.some((r) => Math.abs(r.left - rects[0].left) > 4);
    return { grid, rects, home: els.indexOf(home) };
  }

  function slotsOf(l) {
    if (!drag.slots.has(l)) drag.slots.set(l, measure(l, null));
    return drag.slots.get(l);
  }

  // La tarjeta de la rejilla en la que vive una lista de pasos (o null)
  function gridCardOf(l) {
    const card = l.el.parentElement?.closest('[data-sortable-item]');
    const host = card && listOf(card.parentElement);
    return host && slotsOf(host).grid ? card : null;
  }

  // Por una rejilla, cada tarjeta que admite lo arrastrado lo avisa: una tarjeta, con una pastilla donde soltarla (el resto
  // de la tarjeta sirve para recolocar); un paso, en toda ella
  function markNestable() {
    const cls = gridCardOf(drag.from) ? 'sortable-can-take' : 'sortable-can-nest';
    lists.filter((l) => l.opts.group === drag.from.opts.group && l.opts.nest && l.el.isConnected && slotsOf(l).grid).forEach((l) => {
      itemsOf(l, drag.item).forEach((it) => {
        const kl = listOf(l.opts.nest(it));
        if (kl && acceptsAtEnd(kl, 0, 0)) it.classList.add(cls);
      });
    });
  }

  function cancelSettle() {
    if (drag.settle) clearTimeout(drag.settle.timer);
    drag.settle = null;
  }

  /* ---------- Animación FLIP de los hermanos al abrir el hueco ---------- */
  function flip(elements, mutate) {
    if (reduceMotion()) { mutate(); return; }
    const before = new Map(elements.map((e) => [e, e.getBoundingClientRect()]));
    mutate();
    elements.forEach((e) => {
      const a = before.get(e);
      if (!a || !e.isConnected) return;
      const b = e.getBoundingClientRect();
      const dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) return;
      e.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
        { duration: 180, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
    });
  }

  /* ---------- Inicio ---------- */
  function onPointerDown(e) {
    if (drag || e.button > 0) return;
    const item = e.target.closest('[data-sortable-item]');
    if (!item) return;
    prune();
    const list = listOf(item.parentElement);
    if (!list || !item.matches(list.opts.items)) return;
    // Controles dentro del elemento: no arrastran (salvo el asa). Los enlaces sí, y el
    // clic que llega justo después de soltar se anula (ver swallowClick).
    const handle = list.opts.handle ? e.target.closest(list.opts.handle) : null;
    const control = e.target.closest('button, input, textarea, select, label, [contenteditable="true"], .no-drag');
    if (!handle && control && item.contains(control)) return;
    if (list.opts.handleOnly && !handle) return;

    const pending = { item, list, x: e.clientX, y: e.clientY, pointerId: e.pointerId, touch: e.pointerType !== 'mouse', handle: !!handle, timer: null };
    const cancel = () => {
      clearTimeout(pending.timer);
      window.removeEventListener('pointermove', move, true);
      window.removeEventListener('pointerup', cancel, true);
      window.removeEventListener('pointercancel', cancel, true);
    };
    const move = (ev) => {
      if (ev.pointerId !== pending.pointerId) return;
      const dist = Math.hypot(ev.clientX - pending.x, ev.clientY - pending.y);
      if (pending.touch && !pending.handle) {
        if (dist > TOUCH_SLOP) cancel(); // el usuario está desplazando la página
        return;
      }
      if (dist >= START_DISTANCE) { cancel(); start(pending, ev); }
    };
    window.addEventListener('pointermove', move, true);
    window.addEventListener('pointerup', cancel, true);
    window.addEventListener('pointercancel', cancel, true);
    if (pending.touch) {
      pending.timer = setTimeout(() => {
        cancel();
        navigator.vibrate?.(12);
        start(pending, { clientX: pending.x, clientY: pending.y, pointerId: pending.pointerId });
      }, pending.handle ? 0 : LONG_PRESS_MS);
    }
  }

  function start(p, e) {
    const { item, list } = p;
    const rect = item.getBoundingClientRect();
    const slots = new Map([[list, measure(list, item)]]);
    const ghost = item.cloneNode(true);
    ghost.removeAttribute('id');
    ghost.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));
    ghost.classList.add('sortable-ghost');
    ghost.setAttribute('aria-hidden', 'true');
    Object.assign(ghost.style, { width: rect.width + 'px', height: rect.height + 'px', left: rect.left + 'px', top: rect.top + 'px' });
    const badge = document.createElement('span');
    badge.className = 'sortable-badge';
    ghost.appendChild(badge);
    document.body.appendChild(ghost);
    if (list.opts.ghost?.(ghost, item)) ghost.style.height = 'auto';

    const placeholder = document.createElement(item.tagName === 'LI' ? 'li' : 'div');
    placeholder.className = 'sortable-placeholder';
    placeholder.style.height = rect.height + 'px';
    [...item.style].filter((p) => p.startsWith('--')).forEach((p) => placeholder.style.setProperty(p, item.style.getPropertyValue(p)));  // su tamaño en una rejilla
    placeholder.setAttribute('aria-hidden', 'true');
    item.after(placeholder);
    item.classList.add('sortable-source');

    drag = {
      item, from: list, fromIndex: itemsOf(list, null).indexOf(item), ghost, badge, placeholder,
      dx: e.clientX - rect.left, dy: e.clientY - rect.top, pointerId: p.pointerId,
      over: null, index: -1, valid: false, reason: '', point: { x: e.clientX, y: e.clientY }, raf: 0, scroller: null,
      slots, cell: null, settle: null,
    };
    markNestable();
    document.body.classList.add('sortable-dragging');
    lists.forEach((l) => { if (l.opts.group === list.opts.group) l.el.classList.add('sortable-zone'); });
    targets.forEach((t) => t.el.classList.add('sortable-zone'));
    window.addEventListener('pointermove', onMove, true);
    window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', onCancel, true);
    window.addEventListener('keydown', onKeyDuringDrag, true);
    document.addEventListener('touchmove', blockTouchScroll, { passive: false });
    announce(`Arrastrando «${(item.textContent || '').trim().slice(0, 60)}». Suelta para colocarlo, Escape para cancelar.`);
    update(e.clientX, e.clientY);
  }

  function blockTouchScroll(e) { if (drag) e.preventDefault(); }

  /* ---------- Movimiento ---------- */
  function onMove(e) {
    if (!drag || e.pointerId !== drag.pointerId) return;
    e.preventDefault();
    drag.point = { x: e.clientX, y: e.clientY };
    if (!drag.raf) drag.raf = requestAnimationFrame(() => { drag && (drag.raf = 0, update(drag.point.x, drag.point.y)); });
  }

  function markPointerItem(under) {
    const it = under?.closest?.('[data-sortable-item]') || null;
    if (it === drag.pointerItem) return;
    drag.pointerItem?.classList.remove('sortable-pointer');
    it?.classList.add('sortable-pointer');
    drag.pointerItem = it;
  }

  function setNest(it, invalid = false) {
    if (drag.nestItem !== it) drag.nestItem?.classList.remove('sortable-nest', 'sortable-nest-invalid');
    drag.nestItem = it;
    it?.classList.add('sortable-nest');
    it?.classList.toggle('sortable-nest-invalid', !!(it && invalid));
  }

  const acceptsAtEnd = (l, x, y) => !l.opts.accepts || l.opts.accepts(ctxFor(l, itemsOf(l, drag.item).length, { x, y })) === true;

  // Franja central (la mitad) de la fila de un elemento de una lista con `nest`: destino = su lista de hijos. En una rejilla,
  // la pastilla (o toda la tarjeta, para un paso) y sin mover el hueco (`still`): lo agrandaría y recolocaría todo
  function nestTarget(under, x, y) {
    let it = under.closest?.('[data-sortable-item]');
    if (!it || it === drag.item) return null;
    const card = it.parentElement.closest('[data-sortable-item]');  // sobre un paso, cuenta su tarjeta si es de una rejilla
    if (card && listOf(card.parentElement) && slotsOf(listOf(card.parentElement)).grid) it = card;
    const l = listOf(it.parentElement);
    if (!l || !l.opts.nest || l.opts.group !== drag.from.opts.group) return null;
    const kids = l.opts.nest(it);
    const kl = kids && listOf(kids);
    if (!kl) return null;
    if (slotsOf(l).grid) {
      const step = it.classList.contains('sortable-can-take');
      if ((!step && !it.classList.contains('sortable-can-nest')) || drag.placeholder.parentElement === kl.el) return null;
      const r = it.getBoundingClientRect();
      const inPill = y >= r.bottom - NEST_HEIGHT && x >= r.right - r.width * NEST_WIDTH;
      return step || inPill ? { kind: 'list', l: kl, nest: it, still: true } : null;
    }
    const row = (l.opts.nestRow ? it.querySelector(l.opts.nestRow) : it).getBoundingClientRect();
    if (y < row.top + row.height / 4 || y > row.bottom - row.height / 4) return null;
    return { kind: 'list', l: kl, nest: it };
  }

  function findTarget(x, y) {
    let under = document.elementFromPoint(x, y);
    if (!under) return null;
    markPointerItem(under);
    const nested = nestTarget(under, x, y);
    if (nested) return nested;
    // Una zona puede delegar en su lista (p. ej. la cabecera de una columna)
    const proxy = under.closest?.('[data-drop-proxy]');
    if (proxy && !under.closest('[data-sortable-list]')) under = document.getElementById(proxy.dataset.dropProxy) || under;
    for (let el = under; el && el !== document.body; el = el.parentElement) {
      const ext = targets.find((t) => t.el === el);
      if (ext) return { kind: 'external', t: ext };
      const l = listOf(el);
      if (!l || l.opts.group !== drag.from.opts.group) continue;
      const card = gridCardOf(l);
      if (!card || drag.placeholder.parentElement === l.el) return { kind: 'list', l };
      // Los pasos de otra tarjeta no son destino: el hueco la agrandaría. Se sigue hacia la rejilla
    }
    return null;
  }

  // En la lista de origen el elemento toma el sitio de la celda bajo el puntero; en otra, entra delante (o al final)
  function gridIndex(l, s, x, y) {
    if (!s.rects.length) return 0;
    const box = l.el.getBoundingClientRect();
    const px = x - box.left, py = y - box.top;
    const far = (r) => Math.hypot(Math.max(r.left - px, 0, px - r.right), Math.max(r.top - py, 0, py - r.bottom));
    const held = drag.cell?.l === l && far(s.rects[drag.cell.i]) <= STICK;
    const i = held ? drag.cell.i : s.rects.reduce((best, r, k) => (far(r) < far(s.rects[best]) ? k : best), 0);
    drag.cell = { l, i };
    if (s.home >= 0 || i < s.rects.length - 1) return i;
    const r = s.rects[i];
    return i + (py > r.bottom || px > r.left + r.width / 2 ? 1 : 0);
  }

  function indexIn(l, x, y) {
    const s = slotsOf(l);
    if (s.grid) return gridIndex(l, s, x, y);
    const items = itemsOf(l, drag.item);
    let i = 0;
    for (; i < items.length; i++) {
      const r = items[i].getBoundingClientRect();
      if (y < r.top + r.height / 2) break;
    }
    return i;
  }

  function ctxFor(l, index, point) {
    const before = l ? itemsOf(l, drag.item)[index] || null : null;
    return { item: drag.item, id: idOf(drag.from, drag.item), from: drag.from.opts, to: l ? l.opts : null, fromEl: drag.from.el,
      toEl: l ? l.el : null, index, fromIndex: drag.fromIndex, point,
      beforeEl: before, beforeId: before && l ? idOf(l, before) : null };
  }

  // Tras un arrastre que empezó en un enlace, el navegador manda un clic: se descarta
  function swallowClick() {
    const stop = (e) => { e.preventDefault(); e.stopPropagation(); };
    window.addEventListener('click', stop, { capture: true, once: true });
    setTimeout(() => window.removeEventListener('click', stop, { capture: true }), 350);
  }

  function setState(target, valid, reason) {
    lists.concat(targets).forEach((x) => x.el.classList.remove('sortable-over', 'sortable-invalid'));
    if (target) target.el.classList.add(valid ? 'sortable-over' : 'sortable-invalid');
    drag.ghost.classList.toggle('is-invalid', !valid && !!target);
    drag.ghost.classList.toggle('is-external', valid && target?.kind === 'external');
    drag.badge.textContent = !valid && target ? reason : '';
    document.body.classList.toggle('sortable-nodrop', !valid);
    drag.valid = valid;
    drag.reason = reason;
  }

  function update(x, y) {
    if (!drag) return;
    drag.ghost.style.transform = `translate(${x - drag.dx - parseFloat(drag.ghost.style.left)}px, ${y - drag.dy - parseFloat(drag.ghost.style.top)}px)`;
    autoScroll(x, y);
    const t = findTarget(x, y);
    if (!t?.nest) setNest(null);
    if (!t) {
      cancelSettle();
      setState(null, false, '');
      drag.over = null;
      return;
    }
    if (t.kind === 'external') {
      cancelSettle();
      const verdict = t.t.opts.accepts ? t.t.opts.accepts(ctxFor(null, 0, { x, y })) : true;
      if (drag.placeholder.isConnected) drag.placeholder.remove();
      drag.over = t;
      setState({ el: t.t.el, kind: 'external' }, verdict === true, verdict === true ? '' : verdict);
      return;
    }
    const l = t.l;
    const index = t.nest ? itemsOf(l, drag.item).length : indexIn(l, x, y);
    const verdict = l.opts.accepts ? l.opts.accepts(ctxFor(l, index, { x, y })) : true;
    drag.over = t;
    drag.index = index;
    if (t.nest) setNest(t.nest, verdict !== true);
    const grid = slotsOf(l).grid;
    if (verdict !== true) {
      cancelSettle();
      // En una rejilla el hueco se queda: quitarlo recolocaría todo y el puntero podría acabar en otro destino
      if (!grid && drag.placeholder.isConnected) flip(itemsOf(drag.from, drag.item), () => drag.placeholder.remove());
      setState({ el: l.el }, false, verdict || 'Aquí no se puede soltar');
      return;
    }
    setState({ el: l.el }, true, '');
    if (t.still) { cancelSettle(); return; }
    const ref = itemsOf(l, drag.item)[index] || null;
    if (drag.placeholder.parentElement === l.el && drag.placeholder.nextElementSibling === ref) { cancelSettle(); return; }
    if (!grid) { cancelSettle(); place(l, index); return; }
    // Solo con el puntero parado: mientras se mueve, la tarjeta a la que va no se aparta
    if (drag.settle?.l === l && drag.settle.index === index && Math.hypot(x - drag.settle.x, y - drag.settle.y) < STILL_PX) return;
    cancelSettle();
    drag.settle = { l, index, x, y, timer: setTimeout(() => {
      drag.settle = null;
      place(l, index);
    }, SETTLE_MS) };
  }

  function place(l, index) {
    const items = itemsOf(l, drag.item);
    const ref = items[index] || null;
    const affected = [...new Set([...items, ...itemsOf(drag.from, drag.item)])];
    flip(affected, () => {
      if (ref) l.el.insertBefore(drag.placeholder, ref);
      else {
        const after = items[items.length - 1];
        if (after) after.after(drag.placeholder); else l.el.prepend(drag.placeholder);
      }
    });
  }

  function scrollParent(el) {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (/(auto|scroll)/.test(s.overflowY) && n.scrollHeight > n.clientHeight) return n;
    }
    return document.scrollingElement;
  }

  function autoScroll(x, y) {
    const under = document.elementFromPoint(x, y);
    const sc = under ? scrollParent(under) : document.scrollingElement;
    const r = sc === document.scrollingElement ? { top: 0, bottom: innerHeight } : sc.getBoundingClientRect();
    let dy = 0;
    if (y < r.top + EDGE) dy = -Math.ceil((r.top + EDGE - y) / 4);
    else if (y > r.bottom - EDGE) dy = Math.ceil((y - (r.bottom - EDGE)) / 4);
    cancelAnimationFrame(drag.scrollRaf);
    if (!dy) return;
    const step = () => {
      if (!drag) return;
      sc.scrollTop += dy;
      drag.scrollRaf = requestAnimationFrame(step);
    };
    drag.scrollRaf = requestAnimationFrame(step);
  }

  /* ---------- Final ---------- */
  function cleanup() {
    swallowClick();
    window.removeEventListener('pointermove', onMove, true);
    window.removeEventListener('pointerup', onUp, true);
    window.removeEventListener('pointercancel', onCancel, true);
    window.removeEventListener('keydown', onKeyDuringDrag, true);
    document.removeEventListener('touchmove', blockTouchScroll);
    cancelAnimationFrame(drag.scrollRaf);
    cancelAnimationFrame(drag.raf);
    cancelSettle();
    document.body.classList.remove('sortable-dragging', 'sortable-nodrop');
    lists.concat(targets).forEach((x) => x.el.classList.remove('sortable-zone', 'sortable-over', 'sortable-invalid'));
    drag.item.classList.remove('sortable-source');
    drag.pointerItem?.classList.remove('sortable-pointer');
    drag.nestItem?.classList.remove('sortable-nest', 'sortable-nest-invalid');
    document.querySelectorAll('.sortable-can-nest, .sortable-can-take').forEach((el) => el.classList.remove('sortable-can-nest', 'sortable-can-take'));
    drag.ghost.remove();
    drag.placeholder.remove();
    drag = null;
  }

  function onCancel() {
    if (!drag) return;
    cleanup();
    announce('Movimiento cancelado');
  }

  function onKeyDuringDrag(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onCancel(); }
  }

  async function onUp(e) {
    if (!drag || e.pointerId !== drag.pointerId) return;
    const d = drag;
    const over = d.over;
    const point = { x: e.clientX, y: e.clientY };
    if (!over || !d.valid) {
      if (over && d.reason) hint(d.reason);
      cleanup();
      announce(d.reason || 'No se ha movido');
      return;
    }
    if (over.kind === 'external') {
      const ctx = ctxFor(null, 0, point);
      cleanup();
      try { await over.t.opts.onDrop(ctx); } catch (err) { if (err?.message) hint(err.message); }
      return;
    }
    const l = over.l;
    if (d.settle) {  // se suelta antes de que el hueco llegue: va directo
      const { l: to, index } = d.settle;
      cancelSettle();
      place(to, index);
    }
    const ctx = ctxFor(l, d.index, point);
    const ghostRect = d.ghost.getBoundingClientRect();
    // Colocación optimista en el hueco + animación desde el fantasma
    const prev = { parent: d.item.parentElement, next: d.item.nextElementSibling };
    d.placeholder.replaceWith(d.item);
    const item = d.item;
    cleanup();
    if (!reduceMotion()) {
      const r = item.getBoundingClientRect();
      item.animate([{ transform: `translate(${ghostRect.left - r.left}px, ${ghostRect.top - r.top}px)`, boxShadow: 'var(--shadow-3)' },
        { transform: 'none' }], { duration: 200, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
    }
    if (ctx.toEl === ctx.fromEl && ctx.index === ctx.fromIndex) return;
    try {
      await l.opts.onDrop(ctx);
      announce(`Colocado en la posición ${ctx.index + 1}${l.opts.label ? ' de ' + l.opts.label : ''}`);
    } catch (err) {
      prev.parent.insertBefore(item, prev.next && prev.next.isConnected ? prev.next : null);
      hint(err?.message || 'No se pudo mover');
    }
  }

  /* ---------- Teclado: Alt + flechas sobre un elemento enfocado ---------- */
  async function onKeyDown(e) {
    if (!drag) prune();
    if (drag || !e.altKey || e.shiftKey || !['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
    const item = e.target.closest('[data-sortable-item]');
    if (!item || (e.target !== item && !e.target.matches('[data-drag-handle]'))) return;
    const list = listOf(item.parentElement);
    if (!list) return;
    e.preventDefault();
    const siblings = itemsOf(list, null);
    const from = siblings.indexOf(item);
    let to = list, index = from;
    if (e.key === 'ArrowUp') index = Math.max(0, from - 1);
    if (e.key === 'ArrowDown') index = Math.min(siblings.length - 1, from + 1);
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      const group = lists.filter((l) => l.opts.group === list.opts.group && l.opts.keyboard !== false && l.el.isConnected);
      const next = group[group.indexOf(list) + (e.key === 'ArrowRight' ? 1 : -1)];
      if (!next) return;
      to = next; index = 0;
    }
    if (to === list && index === from) return;
    const others = itemsOf(to, item);
    const beforeEl = others[index] || null;
    const ctx = { item, id: idOf(list, item), from: list.opts, to: to.opts, fromEl: list.el, toEl: to.el, index, fromIndex: from, point: null, keyboard: true,
      beforeEl, beforeId: beforeEl ? idOf(to, beforeEl) : null };
    const verdict = to.opts.accepts ? to.opts.accepts(ctx) : true;
    if (verdict !== true) { announce(verdict); hint(verdict); return; }
    flip([...new Set([...siblings, ...others])], () => {
      const ref = others[index] || null;
      to.el.insertBefore(item, ref);
    });
    item.focus();
    try {
      await to.opts.onDrop(ctx);
      announce(`Movido a la posición ${index + 1}${to.opts.label ? ' de ' + to.opts.label : ''}`);
    } catch (err) {
      hint(err?.message || 'No se pudo mover');
    }
  }

  document.addEventListener('pointerdown', onPointerDown);
  // Sin arrastre nativo de enlaces e imágenes dentro de un elemento ordenable
  document.addEventListener('dragstart', (e) => { if (e.target.closest?.('[data-sortable-item]')) e.preventDefault(); });
  document.addEventListener('keydown', onKeyDown);
  // Las listas desaparecen al volver a pintar la página: se limpian al empezar un gesto
  // (no al crearlas: una lista puede registrarse antes de insertarse en el documento)
  function prune() {
    for (let i = lists.length - 1; i >= 0; i--) if (!lists[i].el.isConnected) lists.splice(i, 1);
    for (let i = targets.length - 1; i >= 0; i--) if (!targets[i].el.isConnected) targets.splice(i, 1);
  }

  function prepare(el, opts) {
    [...el.children].forEach((c) => {
      if (!c.matches(opts.items)) return;
      c.setAttribute('data-sortable-item', '');
      // Sin arrastre nativo (enlaces e imágenes): si no, el navegador cancela los eventos pointer
      c.setAttribute('draggable', 'false');
      c.querySelectorAll('a, img').forEach((x) => x.setAttribute('draggable', 'false'));
      if (!opts.handleOnly && !c.hasAttribute('tabindex')) c.tabIndex = 0;
      if (!c.hasAttribute('aria-roledescription')) c.setAttribute('aria-roledescription', 'elemento que se puede mover');
      if (!c.hasAttribute('aria-description')) c.setAttribute('aria-description', 'Alt más flechas para moverlo');
    });
  }

  window.Sortable = {
    create(el, opts) {
      const existing = listOf(el);
      if (existing) existing.opts = opts; else lists.push({ el, opts });
      el.setAttribute('data-sortable-list', '');
      prepare(el, opts);
      return { refresh: () => prepare(el, opts) };
    },
    addDropTarget(el, opts) {
      const i = targets.findIndex((t) => t.el === el);
      if (i >= 0) targets[i].opts = opts; else targets.push({ el, opts });
    },
    get dragging() { return !!drag; },
  };
})();
