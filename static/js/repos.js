/* ==========================================================================
   repos.js — en Copias: qué ha cambiado en cada repositorio (dotfiles y el propio panel) y subirlo a GitHub
   ========================================================================== */
(function () {
  'use strict';

  const KIND_LABELS = { modificado: 'Cambiado', nuevo: 'Nuevo', borrado: 'Borrado', enlace: 'Enlace', repo: 'En el repo', conflicto: 'Choca' };
  const REPOS = {
    dotfiles: {
      url: '/api/dotfiles',
      title: 'Dotfiles',
      upToDate: 'Lo que hay en tu sistema ya está en el repositorio.',
      contents: (s) => `Lo que restaura el instalador: ${plural(s.components.length, 'componente', 'componentes')} en ${s.repo}.`,
    },
    proyecto: {
      url: '/api/proyecto',
      title: 'Panel Maestro',
      upToDate: 'Todo lo publicable ya está en GitHub.',
      contents: () => 'Lo que se publica, siempre sin tus datos ni tu historial de commits.',
    },
  };
  const dateFmt = new Intl.DateTimeFormat('es-ES', { dateStyle: 'medium', timeStyle: 'short' });
  const numFmt = new Intl.NumberFormat('es-ES');
  const $ = (id) => document.getElementById(id);
  const cards = [...document.querySelectorAll('[data-repo]')];
  const modalPush = $('repoModalPush');
  const status = {};
  let current = null;  // el repo abierto en el diálogo

  const card = (key) => $(`${key}Panel`);
  const pushButtons = (key) => [card(key).querySelector('[data-push]'), ...(key === current ? [modalPush] : [])];
  const plural = (n, one, many) => `${numFmt.format(n)} ${n === 1 ? one : many}`;
  const toUpload = (s) => s.changes.filter((c) => c.kind !== 'conflicto');
  const conflicts = (s) => s.changes.filter((c) => c.kind === 'conflicto');
  // stow/<componente>/.config/x -> ~/.config/x: es el nombre que se reconoce; el resto ya está en el repo
  const shownPath = (path) => (/^(stow|seeds)\//.test(path) ? `~/${path.split('/').slice(2).join('/')}` : path);

  function alertBox(key, message) {
    const box = $(`${key}Alert`);
    box.hidden = !message;
    box.querySelector('span').textContent = message || '';
  }

  /* ---------- Resumen ---------- */
  function summaryText(s) {
    if (s.first) return 'Todavía no está en GitHub.';
    const files = toUpload(s).length;
    const pending = [];
    if (files) pending.push(plural(files, 'archivo cambiado', 'archivos cambiados'));
    if (s.ahead) pending.push(plural(s.ahead, 'commit', 'commits'));
    const parts = [pending.length ? `${pending.join(' y ')} sin subir.` : 'Al día con GitHub.'];
    if (conflicts(s).length) parts.push(`${plural(conflicts(s).length, 'archivo no se fusiona solo', 'archivos no se fusionan solos')}.`);
    if (s.last_push) parts.push(`Última subida ${timeAgo(s.last_push)}.`);
    return parts.join(' ');
  }

  function renderSummary(key) {
    const s = status[key];
    const panel = card(key);
    panel.setAttribute('aria-busy', 'false');
    $(`${key}Text`).textContent = summaryText(s);
    const pending = s.first || s.ahead || toUpload(s).length;
    panel.dataset.health = conflicts(s).length ? 'error' : pending ? 'antigua' : 'ok';
    panel.querySelector('[data-actions]').hidden = false;
  }

  /* ---------- Cambios ---------- */
  function renderChanges(s, repo) {
    const box = $('repoChanges');
    $('repoChangesCount').textContent = s.changes.length || '';
    if (s.first) {
      box.innerHTML = emptyState({ iconName: 'upload', title: 'Primera subida', text: 'Se publicará todo lo que ves en Contenido.', compact: true });
    } else if (!s.changes.length) {
      box.innerHTML = emptyState({ iconName: 'shield-check', title: 'Nada pendiente', text: repo.upToDate, compact: true });
    } else {
      const groups = new Map();
      s.changes.forEach((c) => groups.set(c.component, [...(groups.get(c.component) || []), c]));
      box.innerHTML = [...groups].map(([name, rows]) => `
        <section class="repo-group">
          <h3 class="repo-group-title">${escapeHtml(name)} <span class="chip-count">${rows.length}</span></h3>
          ${rows.map((c) => `
            <details class="repo-file" data-path="${escapeHtml(c.path)}">
              <summary>
                <span class="repo-path">${escapeHtml(shownPath(c.path)).replace(/\//g, '/<wbr>')}</span>
                <span class="kind" data-kind="${c.kind}">${KIND_LABELS[c.kind] || c.kind}</span>
                ${icon('chevron-right', 'icon-sm repo-chevron')}
              </summary>
              <div class="repo-diff-box"></div>
            </details>`).join('')}
        </section>`).join('');
    }
    if (conflicts(s).length) {
      box.insertAdjacentHTML('afterbegin', `<p class="restore-warning">${icon('triangle-alert', 'icon-sm')}<span>Lo marcado «Choca» cambió a la vez en tu sistema y en el repositorio, justo en las mismas líneas. Se queda fuera de la subida hasta que lo igualas a mano en ${escapeHtml(s.repo)}; el resto sube igual.</span></p>`);
    }
    if (s.missing.length) {
      box.insertAdjacentHTML('beforeend', `<p class="tiny subtle">${plural(s.missing.length, 'archivo ya no está', 'archivos ya no están')} en tu sistema y se conserva${s.missing.length === 1 ? '' : 'n'} en el repositorio: ${s.missing.map((p) => escapeHtml(shownPath(p))).join(', ')}.</p>`);
    }
  }

  async function loadDiff(details) {
    const target = details.querySelector('.repo-diff-box');
    if (target.dataset.loaded) return;
    target.dataset.loaded = '1';
    target.innerHTML = `<p class="tiny subtle">Cargando…</p>`;
    try {
      const d = await api(`${REPOS[current].url}/diff?path=${encodeURIComponent(details.dataset.path)}`, { quiet: true });
      if (d.binary) { target.innerHTML = '<p class="tiny subtle">Archivo binario.</p>'; return; }
      const line = (l) => {
        const cls = l.startsWith('@@') ? 'hunk' : l[0] === '+' ? 'add' : l[0] === '-' ? 'del' : '';
        return `<span class="${cls}">${escapeHtml(l) || ' '}</span>`;
      };
      target.innerHTML = `<pre class="repo-diff" tabindex="0" aria-label="Cambios de ${escapeHtml(shownPath(d.path))}">${d.lines.map(line).join('')}</pre>
        ${d.truncated ? '<p class="tiny subtle">Es muy largo: solo se muestra el principio.</p>' : ''}`;
    } catch (err) {
      delete target.dataset.loaded;
      target.innerHTML = `<p class="tiny subtle">${escapeHtml(err.message)}</p>`;
    }
  }

  /* ---------- Contenido e historial ---------- */
  const external = (url, label) => `<a class="btn btn-sm" href="${escapeHtml(url)}" target="_blank" rel="noopener">${icon('external-link', 'icon-sm')}${label}</a>`;

  function renderContents(s, repo) {
    const rows = s.components.map((c) => `<li><span class="repo-comp-name">${escapeHtml(c.name)}</span><span class="tiny subtle">${numFmt.format(c.files)}</span></li>`).join('');
    $('repoContents').innerHTML = `
      <div class="row row-wrap">
        <p class="small muted grow">${escapeHtml(repo.contents(s))}</p>
        ${s.web_url ? external(s.web_url, 'Abrir en GitHub') : ''}
      </div>
      <ul class="repo-components">${rows}</ul>`;
  }

  function renderHistory(s) {
    const links = s.web_url && s.commit_links !== false;
    $('repoHistory').innerHTML = `<ul class="list">${s.commits.map((c) => `
      <li class="list-row">
        <span class="row-main">
          <span class="row-title repo-commit-title">${escapeHtml(c.subject)}</span>
          <span class="row-sub">${dateFmt.format(new Date(c.date * 1000))}${c.pushed ? '' : ' · <span class="kind" data-kind="repo">Sin subir</span>'}</span>
        </span>
        ${links && c.pushed ? `<a class="btn btn-ghost btn-sm" href="${escapeHtml(s.web_url)}/commit/${c.hash}" target="_blank" rel="noopener" aria-label="Ver ${c.hash} en GitHub">${c.hash}</a>` : `<span class="tiny subtle">${c.hash}</span>`}
      </li>`).join('')}</ul>`;
  }

  function renderDetail(key) {
    const s = status[key];
    const repo = REPOS[key];
    const files = toUpload(s).length;
    $('repoTitle').textContent = repo.title;
    $('repoSub').textContent = [s.branch, plural(s.total_files, 'archivo', 'archivos')].join(' · ');
    modalPush.querySelector('span').textContent = files ? `Subir ${plural(files, 'archivo', 'archivos')}` : 'Subir a GitHub';
    renderChanges(s, repo);
    renderContents(s, repo);
    renderHistory(s);
  }

  function showPane(name) {
    document.querySelectorAll('#repoTabs [data-pane]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.pane === name)));
    document.querySelectorAll('.repo-pane').forEach((p) => { p.hidden = p.dataset.pane !== name; });
    document.querySelector('#repoModal .modal-body').scrollTop = 0;
  }

  /* ---------- Acciones ---------- */
  async function load(key) {
    status[key] = await api(REPOS[key].url, { quiet: true });
    renderSummary(key);
    if (key === current) renderDetail(key);
  }

  function setBusy(key, busy) {
    pushButtons(key).forEach((b) => { b.disabled = busy; b.classList.toggle('is-loading', busy); });
  }

  async function push(key) {
    setBusy(key, true);
    alertBox(key, '');
    try {
      const res = await api(`${REPOS[key].url}/push`, { method: 'POST', quiet: true });
      if (res.status === 'al-dia') toast('Ya estaba todo al día');
      else toast(res.files ? `${plural(res.files, 'archivo subido', 'archivos subidos')} a GitHub` : 'Subido a GitHub');
      if (res.conflicts.length) alertBox(key, `${plural(res.conflicts.length, 'archivo se ha quedado fuera', 'archivos se han quedado fuera')} por chocar con el repositorio: ${res.conflicts.map(shownPath).join(', ')}.`);
    } catch (err) {
      alertBox(key, err.message);
      toast('No se ha subido', { type: 'error' });
      if ($('repoModal').open) closeModal('repoModal');
    } finally {
      setBusy(key, false);
      await load(key).catch(() => {});
    }
  }

  async function view(key, btn) {
    btn.classList.add('is-loading');
    try {
      current = key;
      await load(key);
      showPane('cambios');
      openModal('repoModal');
    } finally {
      btn.classList.remove('is-loading');
    }
  }

  /* ---------- Eventos ---------- */
  cards.forEach((panel) => {
    const key = panel.dataset.repo;
    panel.querySelector('[data-view]').addEventListener('click', (e) => view(key, e.currentTarget).catch((err) => alertBox(key, err.message)));
    panel.querySelector('[data-push]').addEventListener('click', () => push(key));
    load(key).catch((err) => {
      panel.setAttribute('aria-busy', 'false');
      panel.dataset.health = 'error';
      $(`${key}Text`).textContent = err.message;
    });
  });
  modalPush.addEventListener('click', () => push(current));
  $('repoTabs').addEventListener('click', (e) => {
    const tab = e.target.closest('[data-pane]');
    if (tab) showPane(tab.dataset.pane);
  });
  $('repoChanges').addEventListener('toggle', (e) => { if (e.target.open) loadDiff(e.target); }, true);
})();
