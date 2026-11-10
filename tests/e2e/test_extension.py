"""Ronda 2 · fase 5: extensión de Firefox (popup, opciones y fondo) contra el servidor de pruebas.

Firefox no se puede manejar aquí con la extensión cargada, así que se sirven sus archivos tal cual en
http://ext.test con una API `browser.*` simulada (almacenamiento, pestaña activa, selección, insignia) y
Chromium sin la política de mismo origen (una extensión con permiso de host tampoco la tiene).
"""
import glob
import json
import os
import re
from pathlib import Path

import pytest

EXT = Path(__file__).resolve().parents[2] / "EXTENSION PANEL"
SHOTS = os.environ.get("BOARD_SHOTS")
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json"}

MOCK = """(() => {
  const KEY = '__ext_store';
  const init = %(init)s;
  if (!localStorage.getItem(KEY)) localStorage.setItem(KEY, JSON.stringify(init.store));
  const read = () => JSON.parse(localStorage.getItem(KEY));
  const write = (s) => localStorage.setItem(KEY, JSON.stringify(s));
  window.__calls = [];
  window.__listeners = {};
  const ev = (name) => ({ addListener(f) { if (name) __listeners[name] = f; } });
  window.browser = {
    storage: { local: {
      async get(keys) { const s = read(); const ks = keys == null ? Object.keys(s) : [].concat(keys);
        return Object.fromEntries(ks.filter((k) => k in s).map((k) => [k, s[k]])); },
      async set(o) { write({ ...read(), ...JSON.parse(JSON.stringify(o)) }); },
      async remove(k) { const s = read(); [].concat(k).forEach((x) => delete s[x]); write(s); },
    } },
    tabs: { query: async () => [init.tab], executeScript: async (o) => [String((o && o.code) || '').includes('panel-progress') ? init.progress : init.selection], create: async (o) => __calls.push(['tab', o.url]) },
    runtime: { getURL: (p) => 'http://ext.test/' + p, sendMessage: async (m) => __calls.push(['msg', m.type]), openOptionsPage: async () => __calls.push(['options']),
               onMessage: ev(), onStartup: ev(), onInstalled: ev() },
    contextMenus: { removeAll: async () => {}, create(o) { (window.__menus ||= []).push(o.id); }, onClicked: ev('menu') },
    notifications: { create: async (o) => { __calls.push(['notify', o.title, o.message]); } },
    commands: { onCommand: ev() },
    alarms: { create() {}, onAlarm: ev() },
    browserAction: { setBadgeText: async (o) => { window.__badge = o.text; }, setBadgeBackgroundColor: async () => {},
                     setTitle: async (o) => { window.__badgeTitle = o.title; }, openPopup: async () => {} },
  };
  window.close = () => __calls.push(['close']);
})();"""


@pytest.fixture(scope="module")
def nocors(browser):
    """Otro Chromium del mismo Playwright (solo puede haber uno abierto), sin la política de mismo origen."""
    b = browser.browser_type.launch(executable_path=_exe(), headless=True,
                                    args=["--disable-web-security"])
    yield b
    b.close()


def _exe():
    found = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))
    return os.environ.get("PLAYWRIGHT_CHROMIUM") or found[-1]


def open_ext(nocors, page_name, store, tab=None, selection="", width=380, height=600, progress=None, start="inbox"):
    ctx = nocors.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def serve(route):
        name = route.request.url.split("http://ext.test/", 1)[1].split("?")[0]
        if name == "__bg.html":
            return route.fulfill(body='<!doctype html><script src="lib/panel.js"></script><script src="background.js"></script>', content_type="text/html")
        f = EXT / name
        route.fulfill(body=f.read_bytes(), content_type=TYPES.get(f.suffix, "application/octet-stream")) if f.is_file() else route.fulfill(status=404)

    page.route("http://ext.test/**", serve)
    init = {"store": store, "tab": tab or {"url": "https://ejemplo.org/articulo", "title": "Un artículo"}, "selection": selection, "progress": progress}
    page.add_init_script(MOCK % {"init": json.dumps(init)})
    page.goto(f"http://ext.test/{page_name}")
    page.wait_for_load_state("networkidle")
    if page_name == "popup.html" and start and not selection and not store.get("pending"):
        page.click(f"#tab-{start}")   # el popup abre en el Baúl: estos tests parten de la pestaña que usan
    return ctx, page, errors


def store_of(page):
    return page.evaluate("JSON.parse(localStorage.getItem('__ext_store'))")


def inbox_items(api):
    return [i for i in api.get("/api/items").json()["items"] if not i["done"]]


def test_popup_envia_la_seleccion_al_inbox(nocors, server, api):
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t"}, selection="Frase interesante")
    try:
        page.wait_for_selector("#status[data-state=ok]")
        assert "Conectado" in page.text_content("#statusText")
        assert page.get_attribute("#tab-inbox", "aria-selected") == "true"  # con selección se abre en el Inbox
        assert page.input_value("#content") == "Frase interesante"
        assert page.text_content("#pageTitle") == "Un artículo"
        page.click("button[data-type=nota]")
        page.fill("#inboxCategory", "Lecturas")
        page.click("#priority [data-prio=alta]")
        assert page.get_attribute("#priority [data-prio=alta]", "aria-checked") == "true"
        page.keyboard.press("ArrowRight")  # flechas dentro del grupo: Alta → Media → Alta
        assert page.get_attribute("#priority [data-prio=media]", "aria-checked") == "true"
        page.keyboard.press("ArrowLeft")
        assert page.text_content("#pageHost") == "ejemplo.org" and page.is_checked("#includeLink")
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=f"{SHOTS}/ext-popup-inbox.png", full_page=True)
        page.keyboard.press("Control+Enter")
        page.wait_for_selector("#result[data-type=ok]")
        item = next(i for i in inbox_items(api) if i["text"].startswith("Frase interesante"))
        assert item["text"] == "Frase interesante\n\nUn artículo\nhttps://ejemplo.org/articulo"
        assert (item["type"], item["priority"], item["category"]) == ("idea", "alta", "Lecturas")
        page.wait_for_timeout(1000)
        calls = page.evaluate("__calls")
        assert ["close"] in calls and ["msg", "refresh"] in calls
        assert store_of(page)["lastType"] == "nota"  # recuerda el último tipo
        assert store_of(page)["recentInboxCats"][0] == "Lecturas"
        # al volver a abrirlo, la categoría usada es un chip de un clic
        page.reload()
        page.click("#tab-inbox")
        page.wait_for_selector("#inboxChips .chip")
        assert page.locator("#inboxChips .chip").first.text_content() == "Lecturas"
        page.locator("#inboxChips .chip").first.click()
        assert page.input_value("#inboxCategory") == "Lecturas"
        assert page.get_attribute("#inboxChips .chip >> nth=0", "aria-pressed") == "true"
        # en el Inbox del Panel la tarjeta muestra la prioridad y la categoría
        page.goto(server + "/inbox")
        card = page.locator(f".il-item[data-id='{item['id']}']")
        card.locator(".tag.prio[data-prio=alta]").wait_for()
        assert "Lecturas" in card.locator(".il-meta").text_content()
        assert not errors, errors
    finally:
        ctx.close()


def test_el_popup_abre_siempre_en_el_baul(nocors, server):
    # aunque la última pestaña usada fuera otra; con texto seleccionado, en cambio, es del Inbox
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t", "lastTab": "cal"}, start=None)
    try:
        assert page.get_attribute("#tab-vault", "aria-selected") == "true" and page.is_visible("#panel-vault")
        assert page.locator(".tabs [role=tab]").first.get_attribute("id") == "tab-vault"          # y es la primera pestaña
        assert not errors, errors
    finally:
        ctx.close()


def test_popup_baul_clasifica_solo_un_video_nuevo_como_ver_mas_tarde(nocors, server, api):
    url = "https://www.youtube.com/watch?v=extension12&list=PLabc&t=33s"
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t"}, start=None,
                                 tab={"url": url, "title": "Un vídeo"})
    try:
        page.wait_for_function("document.getElementById('detectedBadge').textContent !== 'Enlace web'")
        assert page.input_value("#vaultUrl") == url and "Vídeo de YouTube" in page.text_content("#kind")
        assert page.text_content("#detectedBadge") == "Ver más tarde" and "nuevo" in page.text_content("#detectedReason")
        assert not page.is_visible("#vaultState")                      # el selector está plegado: no hace falta tocarlo
        page.fill("#vaultCategory", "Ver")
        if SHOTS:
            page.screenshot(path=f"{SHOTS}/ext-popup-baul.png", full_page=True)
        page.click("#saveVault")
        page.wait_for_selector("#result[data-type=ok]")
        assert "para más tarde" in page.text_content("#result")
        res = next(r for r in api.get("/api/resources").json()["resources"] if "extension12" in r["url"])
        assert res["category"] == "Ver" and res["watch_later"] == 1 and res["url"] == "https://www.youtube.com/watch?v=extension12"
        # el mismo vídeo con otra URL (youtu.be, con tiempo): ya está en el Baúl → se detecta «visto» y se marca sin duplicar
        page.evaluate("localStorage.setItem('__ext_tab', 1)")
        page.reload()
        page.wait_for_load_state("networkidle")
        page.fill("#vaultUrl", "https://youtu.be/extension12?t=5")
        page.wait_for_function("document.getElementById('detectedBadge').textContent === 'Visto'", polling=100)
        assert "ya está en el Baúl" in page.text_content("#detectedReason")
        page.click("#saveVault")
        page.wait_for_selector("#result[data-type=ok]")
        assert "como visto" in page.text_content("#result")
        rows = [r for r in api.get("/api/resources").json()["resources"] if "extension12" in r["url"]]
        assert len(rows) == 1 and rows[0]["watched"] == 1 and rows[0]["watch_later"] == 0
        # teclado: las flechas cambian de pestaña (Baúl → Inbox)
        page.focus("#tab-vault")
        page.keyboard.press("ArrowRight")
        assert page.get_attribute("#tab-inbox", "aria-selected") == "true" and page.is_visible("#panel-inbox")
        assert not errors, errors
    finally:
        ctx.close()


def test_popup_baul_canal_y_umbral_de_visto(nocors, server, api):
    # página de un canal → se guarda como canal de YouTube, sin tocar el selector
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t"}, start=None,
                                 tab={"url": "https://www.youtube.com/@CanalDeExtension", "title": "Canal"})
    try:
        page.wait_for_function("document.getElementById('detectedBadge').textContent === 'Canal de YouTube'")
        page.click("#saveVault")
        page.wait_for_selector("#result[data-type=ok]")
        assert "como canal de YouTube" in page.text_content("#result")
        res = next(r for r in api.get("/api/resources").json()["resources"] if "CanalDeExtension" in r["url"])
        assert res["watch_later"] == 0 and res["watched"] == 0
    finally:
        ctx.close()
    # vídeo nuevo con el 80 % reproducido (umbral por defecto 50 %) → visto; con el 10 % → ver más tarde
    for vid, played, esperado in (("extprogres1", 800, "Visto"), ("extprogres2", 100, "Ver más tarde")):
        ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t"}, start=None,
                                     tab={"url": f"https://www.youtube.com/watch?v={vid}", "title": "V"}, progress={"played": played, "duration": 1000})
        try:
            page.wait_for_function(f"document.getElementById('detectedBadge').textContent === '{esperado}'")
            if esperado == "Visto":
                assert "80 %" in page.text_content("#detectedReason")
        finally:
            ctx.close()


def test_popup_baul_web_sin_clasificar_y_cambio_manual(nocors, server, api):
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t", "lastVaultCat": "Lecturas"}, start=None)
    try:
        page.wait_for_function("document.getElementById('detectedBadge').textContent !== ''")
        assert page.text_content("#detectedBadge") == "Enlace web"
        assert page.input_value("#vaultCategory") == "Lecturas"           # la última categoría usada sigue de partida
        page.click("#detectedChange")                                      # un clic para cambiarlo
        page.click("#vaultState [data-state=seen]")
        assert page.text_content("#detectedBadge") == "Visto" and page.get_attribute("#vaultState [data-state=seen]", "aria-pressed") == "true"
        page.click("#saveVault")
        page.wait_for_selector("#result[data-type=ok]")
        res = next(r for r in api.get("/api/resources").json()["resources"] if r["url"] == "https://ejemplo.org/articulo")
        assert res["watched"] == 1 and res["category"] == "Lecturas"
    finally:
        ctx.close()


def test_sin_conexion_cola_y_el_fondo_la_envia(nocors, server, api):
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": "http://127.0.0.1:9", "token": "t"})
    try:
        page.wait_for_selector("#status[data-state=error]")
        page.fill("#content", "Capturada sin conexión")
        page.click("#saveInbox")
        page.wait_for_selector("#result[data-type=warn]")
        assert "cola (1)" in page.text_content("#result")
        assert len(store_of(page)["queue"]) == 1
        # vuelve la conexión: el fondo vacía la cola y pone en la insignia los pendientes
        page.evaluate(f"localStorage.setItem('__ext_store', JSON.stringify({{...JSON.parse(localStorage.getItem('__ext_store')), baseUrl: '{server}'}}))")
        page.goto("http://ext.test/__bg.html")
        page.wait_for_function("window.__badge !== undefined")
        page.wait_for_timeout(300)
        assert store_of(page)["queue"] == []
        assert any(i["text"].startswith("Capturada sin conexión") for i in inbox_items(api))
        pending = api.get("/api/ext/status").json()["pending"]
        assert page.evaluate("__badge") == str(pending) and "conectado" in page.evaluate("__badgeTitle")
        assert not errors, errors
    finally:
        ctx.close()



def test_envio_rapido_desde_el_menu_contextual(nocors, server, api):
    ctx, page, errors = open_ext(nocors, "__bg.html", {"baseUrl": server, "token": "t", "includeLink": False})
    try:
        page.wait_for_function("window.__badge !== undefined")
        assert {"quick-selection", "quick-link"} <= set(page.evaluate("__menus"))
        tab = {"url": "https://ejemplo.org/a", "title": "Página A"}
        page.evaluate("([t]) => __listeners.menu({ menuItemId: 'quick-selection', selectionText: 'Llamar al dentista' }, t)", [tab])
        page.wait_for_function("__calls.some((c) => c[0] === 'notify')")
        assert ["notify", "Enviado al Inbox", "Llamar al dentista"] in page.evaluate("__calls")
        item = next(i for i in inbox_items(api) if i["text"].startswith("Llamar al dentista"))
        assert item["text"] == "Llamar al dentista" and item["type"] == "tarea"  # sin enlace: como en el popup
        # un enlace va siempre con su dirección
        page.evaluate("([t]) => __listeners.menu({ menuItemId: 'quick-link', linkText: 'Guía rápida', linkUrl: 'https://ejemplo.org/guia' }, t)", [tab])
        page.wait_for_function("__calls.filter((c) => c[0] === 'notify').length === 2")
        assert any(i["text"] == "Guía rápida\n\nhttps://ejemplo.org/guia" for i in inbox_items(api))
        assert not errors, errors
    finally:
        ctx.close()

def test_sin_configurar_y_opciones(nocors, server):
    ctx, page, errors = open_ext(nocors, "popup.html", {})
    try:
        page.wait_for_selector("#setup:not([hidden])")
        assert page.text_content("#statusText") == "Sin configurar"
        page.goto("http://ext.test/options.html")
        page.fill("#baseUrl", "127.0.0.1:9/")
        page.fill("#token", "t")
        page.click("#test")
        page.wait_for_selector("#result[data-type=error]")
        assert "No se puede conectar con http://127.0.0.1:9" in page.text_content("#result")
        page.fill("#baseUrl", server + "/")
        page.click("#toggleToken")
        assert page.get_attribute("#token", "type") == "text"
        page.click("#save")
        page.wait_for_selector("#result[data-type=ok]")
        assert page.text_content("#result").startswith("Guardado. Conectado")
        s = store_of(page)
        assert s["baseUrl"] == server and s["token"] == "t"  # sin la barra final
        if SHOTS:
            page.set_viewport_size({"width": 900, "height": 820})
            page.screenshot(path=f"{SHOTS}/ext-opciones.png", full_page=True)
        assert not errors, errors
    finally:
        ctx.close()



# ---------- Inicio de sesión automático (autologin.js) ----------
def open_login(nocors, server, store):
    """La pantalla de acceso real del servidor con el content script inyectado (sin CSP, como en Firefox)."""
    ctx = nocors.new_context()
    page = ctx.new_page()
    errors, posts = [], []
    # tras entrar, el login navega al panel: Chrome puede abortar la transición entre páginas (no es un fallo)
    page.on("pageerror", lambda e: not str(e).startswith("Transition was aborted because of invalid state") and errors.append(str(e)))
    scripts = '<script src="http://ext.test/lib/panel.js"></script><script src="http://ext.test/autologin.js"></script>'

    def ext(route):
        f = EXT / route.request.url.split("http://ext.test/", 1)[1]
        route.fulfill(body=f.read_bytes(), content_type="text/javascript")

    def login(route):
        if route.request.method == "POST":
            posts.append(route.request.post_data)
        res = route.fetch()
        # Sin el aviso de «aún no hay contraseña» (depende del .env de la máquina que pasa los tests)
        html = re.sub(r'<p class="login-msg warn".*?</p>', "", res.text(), flags=re.S).replace("</body>", scripts + "</body>")
        headers = {k: v for k, v in res.headers.items() if k.lower() not in ("content-security-policy", "content-length")}
        route.fulfill(status=res.status, headers=headers, body=html)

    page.route("http://ext.test/**", ext)
    page.route(f"{server}/login**", login)
    page.add_init_script(MOCK % {"init": json.dumps({"store": store, "tab": {}, "selection": ""})})
    return ctx, page, errors, posts


def test_autologin_escribe_la_contrasena_y_no_reintenta(nocors, server):
    ctx, page, errors, posts = open_login(nocors, server, {"baseUrl": server, "token": "t", "loginPassword": "secreta-e2e"})
    try:
        page.goto(f"{server}/login?next=/tareas")
        page.wait_for_selector(".login-msg.error")  # el servidor de pruebas no la acepta: vuelve con el error
        page.wait_for_timeout(500)
        assert len(posts) == 1, posts  # una sola vez: con el error a la vista no lo vuelve a intentar
        assert "password=secreta-e2e" in posts[0] and "next=%2Ftareas" in posts[0]
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("store", [
    {"autoLogin": False, "loginPassword": "secreta-e2e"},      # desactivado en las opciones
    {"loginPassword": ""},                                      # sin contraseña
    {"baseUrl": "http://127.0.0.1:9", "loginPassword": "x"},    # otro Panel: solo actúa en la dirección configurada
])
def test_autologin_no_actua(nocors, server, store):
    ctx, page, errors, posts = open_login(nocors, server, {"baseUrl": server, "token": "t", **store})
    try:
        page.goto(f"{server}/login")
        page.wait_for_timeout(600)
        assert posts == [] and page.input_value("#password") == ""
        assert not errors, errors
    finally:
        ctx.close()


def test_opciones_inicio_de_sesion_automatico(nocors, server):
    ctx, page, errors = open_ext(nocors, "options.html", {"baseUrl": server, "token": "t"}, width=900, height=1000)
    try:
        assert page.is_checked("#autoLogin")  # activado por defecto: basta con escribir la contraseña
        page.fill("#loginPassword", "secreta")
        page.click("#togglePassword")
        assert page.get_attribute("#loginPassword", "type") == "text"
        page.click("#save")
        page.wait_for_selector("#result[data-type=ok]")
        s = store_of(page)
        assert s["autoLogin"] is True and s["loginPassword"] == "secreta"
        page.uncheck("#autoLogin")
        page.click("#save")
        page.wait_for_selector("#result[data-type=ok]")
        s = store_of(page)
        assert s["autoLogin"] is False and s["loginPassword"] == "secreta"  # se conserva para volver a activarlo
        page.reload()
        page.wait_for_function("document.querySelector('#loginPassword').value === 'secreta'")
        assert not page.is_checked("#autoLogin")
        if SHOTS:
            page.screenshot(path=f"{SHOTS}/ext-opciones-autologin.png", full_page=True)
        assert not errors, errors
    finally:
        ctx.close()

# ---------- Temas (los mismos del Panel) ----------
from core.themes import THEMES  # noqa: E402
from tests.e2e.test_tema import CONTRAST  # noqa: E402

EXT_CONTRAST = CONTRAST.replace("main h1, main h2, main p, main label, main button, main a, main span, nav a",
                                "h1, h2, p, label, button, a, span, li, option").replace(".board-wrap, ", "")


def test_opciones_tema_y_el_popup_lo_usa(nocors, server):
    ctx, page, errors = open_ext(nocors, "options.html", {"baseUrl": server, "token": "t"}, width=900, height=900)
    try:
        assert page.get_attribute("html", "data-theme") == "mocha"
        assert page.locator("#themeGrid [role=radio]").count() == len(THEMES) + 1
        page.click("#themeGrid [data-theme=latte]")
        assert page.get_attribute("html", "data-theme") == "latte"
        page.keyboard.press("ArrowRight")  # Latte → Claro
        assert page.get_attribute("html", "data-theme") == "light"
        assert page.evaluate("document.activeElement.dataset.theme") == "light"
        page.goto("http://ext.test/popup.html")
        page.wait_for_selector("#status[data-state=ok]")
        assert page.get_attribute("html", "data-theme") == "light"
        assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(255, 255, 255)"
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("theme", ["system", *THEMES])
def test_contraste_de_la_extension_en_cada_tema(nocors, server, theme):
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t"}, selection="Texto de prueba")
    try:
        page.evaluate(f"localStorage.setItem('theme', '{theme}')")
        problems = []
        for name in ("popup.html", "options.html"):
            page.goto(f"http://ext.test/{name}")
            page.wait_for_load_state("networkidle")
            if name == "popup.html":
                page.wait_for_selector("#status[data-state=ok]")
                page.evaluate("document.getElementById('result').hidden = false; document.getElementById('result').dataset.type = 'warn'; document.getElementById('result').textContent = 'Aviso de prueba'")
            r = page.evaluate(EXT_CONTRAST)
            if r["bad"]:
                problems.append(f"{name}: {r['bad']}")
            if SHOTS and theme in ("latte", "nord", "light"):
                page.screenshot(path=f"{SHOTS}/ext-{theme}-{name.split('.')[0]}.png", full_page=True)
        assert not problems, problems
        assert not errors, errors
    finally:
        ctx.close()


# ─────────── 2.5: agenda, elegir el padre y prefijos ───────────

def _dia(n):
    from datetime import date, timedelta
    return (date.today() + timedelta(days=n)).isoformat()


def test_agenda_ver_crear_mover_y_completar(nocors, server, api):
    eid = api.post("/api/calendar/events", json={"title": "Evento de la extensión", "start": f"{_dia(1)}T10:00"}).json()["id"]
    rid = api.post("/api/items", json={"text": "Rutina de la extensión", "type": "rutina"}).json()["id"]
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t", "lastTab": "cal"}, start="cal")
    try:
        page.wait_for_selector(".agenda-row")
        assert page.get_attribute("#tab-cal", "aria-selected") == "true"
        assert page.locator(".agenda-row", has_text="Evento de la extensión").count() == 1
        # completar la rutina de hoy
        page.locator(f".agenda-row[data-key='r{rid}@{_dia(0)}'] [data-act=done]").click()
        page.wait_for_selector(f".agenda-row.is-done[data-key='r{rid}@{_dia(0)}']")
        assert next(i for i in api.get("/api/items").json()["items"] if i["id"] == rid)["done"]
        # pasar el evento a mañana (conserva la hora)
        page.locator(f".agenda-row[data-key='e{eid}'] [data-act=later]").click()
        page.wait_for_selector("#result[data-type=ok]")
        assert api.get(f"/api/calendar/events/{eid}").json()["start"] == f"{_dia(2)}T10:00"
        # crear en lenguaje natural, con vista previa
        page.fill("#calText", "revisión médica mañana 17:00")
        page.wait_for_selector("#calPreview[data-state=ok]")
        assert "17:00" in page.text_content("#calPreview")
        page.click("#calSave")
        page.wait_for_selector(".agenda-row:has-text('Revisión médica')")
        if SHOTS:
            page.screenshot(path=f"{SHOTS}/ext-popup-agenda.png", full_page=True)
        assert not errors, errors
    finally:
        ctx.close()


def test_elegir_padre_y_prefijos(nocors, server, api):
    padre = api.post("/api/items", json={"text": "Padre desde la extensión", "type": "tarea"}).json()["id"]
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": server, "token": "t"})
    try:
        page.wait_for_selector(f"#parent option[value='{padre}']", state="attached")
        page.click("#moreParent summary")
        page.select_option("#parent", str(padre))
        page.fill("#content", "Paso desde la extensión")
        page.uncheck("#includeLink")
        page.click("#saveInbox")
        page.wait_for_selector("#result[data-type=ok]")
        assert "paso" in page.text_content("#result").lower()
        hijo = next(i for i in api.get("/api/items").json()["items"] if i["text"] == "Paso desde la extensión")
        assert hijo["parent_id"] == padre
        page.reload()
        page.wait_for_selector("#status[data-state=ok]")
        page.click("#tab-inbox")
        page.fill("#content", "r: estirar cada día")
        page.uncheck("#includeLink")
        page.click("#saveInbox")
        page.wait_for_selector("#result[data-type=ok]")
        assert any(i["type"] == "rutina" and i["text"] == "Estirar" for i in api.get("/api/items").json()["items"])
        assert not errors, errors
    finally:
        ctx.close()


def test_evento_sin_conexion_va_a_la_cola(nocors, server, api):
    ctx, page, errors = open_ext(nocors, "popup.html", {"baseUrl": "http://127.0.0.1:9", "token": "t", "lastTab": "cal"}, start="cal")
    try:
        page.wait_for_selector(".agenda .hint")
        page.fill("#calText", "cena con amigos viernes 21:00")
        page.click("#calSave")
        page.wait_for_selector("#result[data-type=warn]")
        q = store_of(page)["queue"]
        assert q[-1]["kind"] == "capture" and q[-1]["body"]["text"] == "e: cena con amigos viernes 21:00"
        page.evaluate(f"localStorage.setItem('__ext_store', JSON.stringify({{...JSON.parse(localStorage.getItem('__ext_store')), baseUrl: '{server}'}}))")
        page.goto("http://ext.test/__bg.html")
        page.wait_for_function("window.__badge !== undefined")
        page.wait_for_timeout(300)
        assert store_of(page)["queue"] == []
        ents = api.get(f"/api/calendar/entries?start={_dia(0)}&end={_dia(7)}").json()["entries"]
        assert any(e["title"] == "Cena con amigos" for e in ents)
        assert not errors, errors
    finally:
        ctx.close()
