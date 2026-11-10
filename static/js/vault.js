/* =====================================================================
   Baúl de recursos: biblioteca, «para más tarde» y vistos
   Depende de ui.js (icon, api, toast, openModal, uiConfirm, openMenu…)
   ===================================================================== */
let allResources = [];
let activeCat = '';
let activeType = 'all';
let searchQuery = '';
let mainTab = 'library';
let reloadTimer = null;

const isPending = (r) => !r.title || r.title === r.url;
const localImage = (r) => (r.image && r.image.startsWith('/static/')) ? r.image : '';

/* ---------- Carga ---------- */
async function loadResources() {
    try {
        const data = await api('/api/resources', { quiet: true });
        allResources = data.resources;
    } catch {
        showState(document.getElementById('vaultContent'), loadFailed('No se pudo cargar el Baúl'), loadResources);
        return;
    }
    renderCategories();
    applyFiltersAndRender();
    updateBadges();
    checkPendingResources();
    maybeBackfillChannels();
}

/* Vídeos antiguos sin canal: el servidor los rellena en segundo plano (poco a poco); mientras tanto, «Canal desconocido» */
const channelBackfill = { started: false, polls: 0 };
async function maybeBackfillChannels() {
    if (mainTab !== 'watched') return;
    if (!allResources.some((r) => r.watched && r.resource_type === 'youtube' && !isChannel(r.url) && !(r.channel || '').trim())) return;
    if (!channelBackfill.started) {
        channelBackfill.started = true;
        try { await api('/api/resources/backfill-channels', { method: 'POST', quiet: true }); } catch { /* se reintentará al recargar */ }
    }
    if (channelBackfill.polls++ < 12) setTimeout(loadResources, 5000);
}

function renderCategories() {
    const cats = [...new Set(allResources.map(r => r.category || 'General'))].sort((a, b) => a.localeCompare(b, 'es'));
    if (activeCat && !cats.includes(activeCat)) activeCat = '';
    const chips = document.getElementById('catChips');
    chips.innerHTML = `<button type="button" class="chip" data-cat="" aria-pressed="${!activeCat}">Todas</button>` +
        cats.map(c => `<button type="button" class="chip" data-cat="${escapeHtml(c)}" aria-pressed="${c === activeCat}"><span class="dot" style="color:${categoryColor(c)}"></span>${escapeHtml(c)}</button>`).join('');
    chips.querySelectorAll('[data-cat]').forEach(b => b.addEventListener('click', () => {
        activeCat = b.dataset.cat;
        chips.querySelectorAll('[data-cat]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
        applyFiltersAndRender();
    }));
    document.getElementById('catList').innerHTML = cats.map(c => `<option value="${escapeHtml(c)}">`).join('');
}

function updateBadges() {
    const wl = allResources.filter(r => r.watch_later && !r.watched).length;
    const watched = allResources.filter(r => r.watched).length;
    const wlb = document.getElementById('wlBadge'), wb = document.getElementById('watchedBadge');
    wlb.textContent = wl; wlb.hidden = !wl;
    wb.textContent = watched; wb.hidden = !watched;
}

document.querySelectorAll('.type-chip').forEach(b => b.addEventListener('click', () => {
    activeType = b.dataset.type;
    document.querySelectorAll('.type-chip').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    applyFiltersAndRender();
}));
for (const id of ['searchInput', 'searchInputMobile']) {
    document.getElementById(id).addEventListener('input', (e) => {
        searchQuery = e.target.value.trim().toLowerCase();
        applyFiltersAndRender();
    });
}

function switchMainTab(btn, tab) {
    mainTab = tab;
    document.querySelectorAll('.main-tab').forEach(b => b.setAttribute('aria-selected', String(b === btn)));
    applyFiltersAndRender();
    maybeBackfillChannels();
}

/* ---------- Filtros y render ---------- */
function applyFiltersAndRender() {
    let items = allResources;
    if (mainTab === 'watchlater') items = items.filter(r => r.watch_later && !r.watched);
    else if (mainTab === 'watched') items = items.filter(r => r.watched);
    else items = items.filter(r => !r.watch_later && !r.watched);
    if (activeCat) items = items.filter(r => (r.category || 'General') === activeCat);
    if (activeType !== 'all') items = items.filter(r => activeType === 'youtube' ? r.resource_type === 'youtube' : r.resource_type !== 'youtube');
    if (searchQuery) {
        items = items.filter(r => [r.title, r.description, r.category, r.url, r.channel].some(v => v?.toLowerCase().includes(searchQuery)));
    }
    render(items);
}

function groupByCategory(items) {
    const groups = {};
    items.forEach(r => (groups[r.category || 'General'] ||= []).push(r));
    return Object.keys(groups).sort((a, b) => a.localeCompare(b, 'es')).map(cat => ({ cat, items: groups[cat] }));
}

function render(items) {
    const el = document.getElementById('vaultContent');
    if (!items.length) {
        const filtered = searchQuery || activeCat || activeType !== 'all';
        el.innerHTML = !allResources.length
            ? emptyState({ iconName: 'library', title: 'El Baúl está vacío', text: 'Guarda vídeos de YouTube, artículos o cualquier enlace para tenerlos a mano.', actionLabel: 'Añadir el primero', action: 'add' })
            : filtered ? emptyState({ iconName: 'search', title: 'Sin resultados', text: 'Prueba con otra búsqueda o quita los filtros.' })
            : mainTab === 'watchlater' ? emptyState({ iconName: 'clock', title: 'Nada pendiente', text: 'Marca un recurso con la estrella para guardarlo aquí.' })
            : mainTab === 'watched' ? emptyState({ iconName: 'circle-check', title: 'Aún no hay nada visto', text: 'Marca un vídeo como visto desde «Para más tarde».' })
            : emptyState({ iconName: 'library', title: 'Todo está en otras pestañas', text: 'Los recursos para más tarde o vistos aparecen en sus pestañas.' });
        el.querySelector('[data-empty-action=add]')?.addEventListener('click', openAddModal);
        return;
    }
    const yt = items.filter(r => r.resource_type === 'youtube');
    const web = items.filter(r => r.resource_type !== 'youtube');
    let html = '';
    if (yt.length && mainTab === 'watched') {
        html += `<section class="vault-section"><h2 class="section-title">${icon('youtube')}Vídeos vistos <span class="section-sub">${yt.length}</span></h2>${watchedGroups(yt)}</section>`;
    } else if (yt.length) {
        html += `<section class="vault-section"><h2 class="section-title">${icon('youtube')}Vídeos <span class="section-sub">${yt.length}</span></h2>`;
        groupByCategory(yt).forEach(g => {
            html += catHeader(g.cat, g.items.length) + `<div class="yt-grid" data-cat="${escapeHtml(g.cat)}" data-kind="youtube">${g.items.map(ytCard).join('')}</div>`;
        });
        html += '</section>';
    }
    if (web.length) {
        html += `<section class="vault-section"><h2 class="section-title">${icon('globe')}Web y artículos <span class="section-sub">${web.length}</span></h2>`;
        groupByCategory(web).forEach(g => {
            html += catHeader(g.cat, g.items.length) + `<ul class="list web-list" data-cat="${escapeHtml(g.cat)}" data-kind="web">${g.items.map(webRow).join('')}</ul>`;
        });
        html += '</section>';
    }
    el.innerHTML = html;
    el.querySelectorAll('[data-kind]').forEach(makeSortable);
}

/* ---------- Vistos: por categoría y, dentro, por canal; grupos plegables con el estado guardado (Prefs) ---------- */
const UNKNOWN_CHANNEL = 'Canal desconocido';
const FOLD_KEY = 'baul-plegados';
const folded = () => new Set(Prefs.get(FOLD_KEY, []));
const slug = (k) => 'g-' + [...k].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

function watchedGroups(items) {
    const closed = folded();
    const toggle = (key, inner, level) => {
        const open = !closed.has(key);
        return `<button type="button" class="group-toggle" data-fold="${escapeHtml(key)}" aria-expanded="${open}" aria-controls="${slug(key)}">${icon('chevron-down', 'icon-sm chev')}${inner}</button>`;
    };
    return groupByCategory(items).map((g) => {
        const byChannel = {};
        g.items.forEach((r) => (byChannel[(r.channel || '').trim() || UNKNOWN_CHANNEL] ||= []).push(r));
        const channels = Object.keys(byChannel).sort((a, b) => (a === UNKNOWN_CHANNEL) - (b === UNKNOWN_CHANNEL) || a.localeCompare(b, 'es'));
        const ckey = 'c:' + g.cat;
        return `<div class="vgroup"><h3 class="cat-header">${toggle(ckey, `<span class="dot" style="background:${categoryColor(g.cat)}"></span>${escapeHtml(g.cat)}<span class="count">${g.items.length}</span>`)}</h3>
          <div class="vgroup-body" id="${slug(ckey)}" ${closed.has(ckey) ? 'hidden' : ''}>${channels.map((ch) => {
            const key = `k:${g.cat}|${ch}`;
            return `<div class="channel-group"><h4 class="channel-header">${toggle(key, `<span class="channel-name${ch === UNKNOWN_CHANNEL ? ' is-unknown' : ''}">${escapeHtml(ch)}</span><span class="count">${byChannel[ch].length}</span>`)}</h4>
              <div class="yt-grid" id="${slug(key)}" data-cat="${escapeHtml(g.cat)}" data-kind="youtube" data-channel="${escapeHtml(ch)}" ${closed.has(key) ? 'hidden' : ''}>${byChannel[ch].map(ytCard).join('')}</div></div>`;
          }).join('')}</div></div>`;
    }).join('');
}
document.getElementById('vaultContent').addEventListener('click', (e) => {
    const b = e.target.closest('[data-fold]');
    if (!b) return;
    const set = folded(), key = b.dataset.fold;
    const open = b.getAttribute('aria-expanded') !== 'true';
    if (open) set.delete(key); else set.add(key);
    Prefs.set(FOLD_KEY, [...set]);
    b.setAttribute('aria-expanded', String(open));
    document.getElementById(b.getAttribute('aria-controls')).hidden = !open;
});
document.addEventListener('prefs:changed', () => { if (mainTab === 'watched') applyFiltersAndRender(); });

/* Orden manual (componente común sortable.js): dentro de su sección (vídeos o web);
   soltar en otra categoría de la misma sección le cambia la categoría. */
function makeSortable(container) {
    const kind = container.dataset.kind;
    Sortable.create(container, {
        group: 'baul', items: kind === 'youtube' ? '.yt-card' : '.web-row', label: container.dataset.cat,
        id: (el) => Number(el.dataset.id), data: { cat: container.dataset.cat, kind },
        accepts: (ctx) => (ctx.to.data.kind === ctx.from.data.kind ? true : 'Los vídeos y las webs van en secciones distintas'),
        onDrop: async (ctx) => {
            await api(`/api/resources/${ctx.id}/move`, { method: 'POST', quiet: true, body: { category: ctx.to.data.cat, before_id: ctx.beforeId } });
            if (ctx.to.data.cat !== ctx.from.data.cat) toast(`Movido a «${ctx.to.data.cat}»`);
            loadResources();
        },
    });
}

function catHeader(cat, count) {
    return `<h3 class="cat-header"><span class="dot" style="background:${categoryColor(cat)}"></span>${escapeHtml(cat)}<span class="count">${count}</span></h3>`;
}

function actionsHtml(r) {
    return `<button type="button" class="btn btn-ghost btn-icon btn-sm later-btn${r.watch_later ? ' on' : ''}" data-act="later" aria-pressed="${!!r.watch_later}" aria-label="${r.watch_later ? 'Quitar de para más tarde' : 'Guardar para más tarde'}" title="Para más tarde">${icon(r.watch_later ? 'bookmark-check' : 'bookmark-plus', 'icon-sm')}</button>
        <button type="button" class="btn btn-ghost btn-icon btn-sm" data-act="menu" aria-label="Más acciones" aria-haspopup="menu">${icon('ellipsis', 'icon-sm')}</button>`;
}

// Un canal (no un vídeo): su imagen es el avatar, cuadrado; se pinta redondo sobre un fondo difuminado de sí mismo
const isChannel = (url) => /youtube\.com\/(@|channel\/|c\/|user\/)/.test(url || '');
function ytCard(r) {
    const img = localImage(r);
    const pending = isPending(r);
    const thumb = pending ? '<span class="skeleton yt-thumb-img"></span>'
        : img && isChannel(r.url) ? `<span class="yt-thumb-img yt-avatar-bg" style="--av: url('${escapeHtml(img)}')"><img class="yt-avatar" src="${escapeHtml(img)}" alt="" loading="lazy" decoding="async"></span>`
        : img ? `<img class="yt-thumb-img" src="${escapeHtml(img)}" alt="" loading="lazy" decoding="async">`
        : `<span class="yt-thumb-img yt-fallback">${icon('youtube', 'icon-xl')}</span>`;
    return `<article class="yt-card${pending ? ' pending' : ''}" data-id="${r.id}">
      <a class="yt-thumb" href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHtml(r.title || r.url)} (abre en una pestaña nueva)">
        ${thumb}${r.watched ? `<span class="watched-mark">${icon('check', 'icon-sm')}Visto</span>` : ''}
        <span class="play">${icon('play')}</span>
      </a>
      <div class="yt-info">
        <a class="yt-title" href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer" tabindex="-1">${pending ? '<span class="skeleton skeleton-line"></span>' : escapeHtml(r.title)}</a>
        <p class="yt-channel">${escapeHtml(isChannel(r.url) && (!r.channel || r.channel === r.title) ? 'Canal de YouTube' : (r.channel || r.description || ''))}</p>
      </div>
      <div class="yt-actions">${mainTab === 'watchlater' ? `<button type="button" class="btn btn-tinted btn-sm" data-act="watched">${icon('check', 'icon-sm')}Visto</button>` : ''}<span class="grow"></span>${actionsHtml(r)}</div>
    </article>`;
}

function webRow(r) {
    let host = '';
    try { host = new URL(r.url).hostname.replace(/^www\./, ''); } catch {}
    const img = localImage(r);
    return `<li class="list-row web-row" data-id="${r.id}">
      ${img ? `<img class="favicon" src="${escapeHtml(img)}" alt="" loading="lazy">` : `<span class="favicon favicon-fallback">${icon('globe', 'icon-sm')}</span>`}
      <a class="row-main" href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">
        <span class="row-title">${escapeHtml(isPending(r) ? host || r.url : r.title)}</span>
        <span class="row-sub">${escapeHtml(r.description || host)}</span>
      </a>
      <span class="row-trail">${actionsHtml(r)}</span>
    </li>`;
}

/* ---------- Acciones (delegación) ---------- */
document.getElementById('vaultContent').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const id = parseInt(btn.closest('[data-id]').dataset.id, 10);
    const r = allResources.find(x => x.id === id);
    if (btn.dataset.act === 'later') toggleWatchLater(id);
    if (btn.dataset.act === 'watched') markWatched(id);
    if (btn.dataset.act === 'menu') openMenu(btn, [
        { label: 'Abrir', icon: 'external-link', onClick: () => window.open(r.url, '_blank', 'noopener') },
        { label: 'Editar', icon: 'pencil', onClick: () => openEditModal(id) },
        r.resource_type === 'youtube' && { label: r.watched ? 'Marcar como no visto' : 'Marcar como visto', icon: 'check', onClick: () => markWatched(id) },
        { label: 'Copiar enlace', icon: 'copy', onClick: () => copyText(r.url).then((ok) => toast(ok ? 'Enlace copiado' : 'No se pudo copiar', { type: ok ? 'success' : 'error' })) },
        { separator: true },
        { label: 'Eliminar', icon: 'trash-2', danger: true, onClick: () => deleteResource(id) },
    ].filter(Boolean));
});

async function toggleWatchLater(id) {
    const data = await api(`/api/resources/${id}/watch-later`, { method: 'PATCH' });
    toast(data.watch_later ? 'Guardado para más tarde' : 'Quitado de para más tarde');
    loadResources();
}
async function markWatched(id) {
    const data = await api(`/api/resources/${id}/watched`, { method: 'PATCH' });
    toast(data.watched ? 'Marcado como visto' : 'Marcado como no visto');
    loadResources();
}

function checkPendingResources() {
    clearTimeout(reloadTimer);
    if (allResources.some(isPending)) reloadTimer = setTimeout(loadResources, 2500);
}

/* ---------- Añadir ---------- */
function openAddModal() {
    document.getElementById('addForm').reset();
    if (activeCat) document.getElementById('addCat').value = activeCat;
    document.getElementById('addWatchLater').checked = mainTab === 'watchlater';
    openModal('addModal', { focus: '#addUrl' });
}
document.getElementById('addForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = document.getElementById('addUrl').value.trim();
    if (!url) return;
    const btn = document.getElementById('btnSubmit');
    btn.classList.add('is-loading');
    try {
        await api('/api/resources', { method: 'POST', body: {
            url, category: document.getElementById('addCat').value.trim() || 'General',
            watch_later: document.getElementById('addWatchLater').checked,
        } });
        closeModal('addModal');
        toast('Recurso añadido; cargando título y miniatura…', { type: 'info' });
        loadResources();
    } catch (err) {
        if (err.status === 409) toast('Ese enlace ya está en el Baúl', { type: 'error' });
    } finally {
        btn.classList.remove('is-loading');
    }
});

/* ---------- Editar ---------- */
function openEditModal(id) {
    const r = allResources.find(x => x.id === id);
    if (!r) return;
    document.getElementById('editId').value = id;
    document.getElementById('editTitle').value = r.title || '';
    document.getElementById('editDesc').value = r.description || '';
    document.getElementById('editCat').value = r.category || '';
    document.getElementById('editWatchLater').checked = !!r.watch_later;
    openModal('editModal', { focus: '#editTitle' });
}
document.getElementById('editForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('editId').value;
    await api(`/api/resources/${id}`, { method: 'PATCH', body: {
        title: document.getElementById('editTitle').value.trim(),
        description: document.getElementById('editDesc').value.trim(),
        category: document.getElementById('editCat').value.trim() || 'General',
        watch_later: document.getElementById('editWatchLater').checked,
    } });
    closeModal('editModal');
    toast('Cambios guardados');
    loadResources();
});

/* ---------- Eliminar ---------- */
async function deleteResource(id) {
    const r = allResources.find(x => x.id === id);
    const ok = await uiConfirm('¿Eliminar este recurso?', r?.title || r?.url || '', { confirmLabel: 'Eliminar', danger: true });
    if (!ok) return;
    await api(`/api/resources/${id}`, { method: 'DELETE' });
    toast('Recurso eliminado', { action: r ? { label: 'Deshacer', onClick: async () => {
        await api('/api/resources', { method: 'POST', body: { url: r.url, category: r.category || 'General', watch_later: !!r.watch_later } });
        loadResources();
    } } : null });
    loadResources();
}

loadResources();
