"""Tercera ronda: tareas e ideas con un solo componente en el Inbox y en Tareas.

Criterios de aceptación (a 1280 y a 375 px):
  1. Crear desde cada punto de entrada → aparece al instante, igual, en Inbox y en Tareas.
  2. Reordenar arrastrando en Tareas → persiste y se ve igual en el Inbox.
  3. Anidar bajo un padre y sacarlo; las reglas de tipo se respetan.
  4. Una tarea de una nota se edita desde Tareas y cambia en la nota, y al revés.
  5. Contadores y listados nunca se desincronizan (recarga y otras pestañas).
"""
import os
from pathlib import Path

import pytest

from tests.e2e.helpers import touch_drag

SHOTS = os.environ.get("PANEL_SHOTS")
CARD = '.il-item[data-id="{}"]'


def card(i):
    return CARD.format(i)


def _nuevo(api, text, type="tarea", **extra):
    r = api.post("/api/items", json={"text": text, "type": type, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _items(api):
    return {i["id"]: i for i in api.get("/api/items").json()["items"]}


def _limpiar(api):
    top = [i for i in _items(api).values() if not i["parent_id"] and i["origin"] != "nota"]
    if top:
        api.post("/api/items/bulk", json={"ids": [i["id"] for i in top], "action": "delete"})


def _abrir(page, server, path):
    page.goto(server + path)
    page.wait_for_selector(".il .il-group")
    page.wait_for_load_state("networkidle")


def _orden(page, group="inbox"):
    return page.eval_on_selector_all(f'[data-group="{group}"] .il-list > .il-item', "els => els.map(e => Number(e.dataset.id))")


def _settle(page, ms=350):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def _volver(pg):
    pg.evaluate("document.dispatchEvent(new CustomEvent('panel:changed', { detail: { path: '*', reason: 'focus' } }))")


def _deshacer(pg):
    pg.locator(".toast .toast-action", has_text="Deshacer").last.click()


def _texto(page, i):
    return page.locator(f"{card(i)} > .il-row .il-text").inner_text()


# ─────────── 1. Crear desde cada punto de entrada ───────────

def test_1_crear_desde_cada_punto_de_entrada(context, server, api):
    _limpiar(api)
    inbox, tareas = context.new_page(), context.new_page()
    _abrir(inbox, server, "/inbox")
    _abrir(tareas, server, "/tareas")

    def visto_en_los_dos(text):
        for pg in (inbox, tareas):
            pg.locator(".il-item .il-text", has_text=text).first.wait_for(timeout=5000)
        it = next(i for i in _items(api).values() if i["text"] == text)
        return it

    # Formulario de la pestaña Tareas (Enter guarda)
    tareas.fill("#tareasCapture-text", "Desde Tareas")
    tareas.press("#tareasCapture-text", "Enter")
    assert visto_en_los_dos("Desde Tareas")["origin"] == "inbox"

    # Captura del Inbox, como idea
    inbox.click("#inboxCapture [data-capture-type=idea]")
    inbox.fill("#inboxCapture-text", "Idea desde el Inbox")
    inbox.press("#inboxCapture-text", "Control+Enter")
    assert visto_en_los_dos("Idea desde el Inbox")["origin"] == "ideas"

    # Captura rápida en Tareas (en escritorio no hay FAB: el botón «Capturar» del pie de la barra lateral)
    tareas.click(".sidebar-footer [data-open-capture]")
    tareas.click("#captureForm [data-capture-type=tarea]")
    tareas.fill("#captureForm-text", "Desde el FAB")
    tareas.click("#captureForm [type=submit]")
    assert visto_en_los_dos("Desde el FAB")["origin"] == "inbox"
    assert not tareas.locator("#captureModal").evaluate("d => d.open")

    # Tecla C → la misma captura
    tareas.locator("body").press("Escape")
    tareas.locator("h1").click()
    tareas.keyboard.press("c")
    tareas.fill("#captureForm-text", "Con la tecla C")
    tareas.press("#captureForm-text", "Control+Enter")
    visto_en_los_dos("Con la tecla C")

    # «+» de la cabecera de Ideas → la captura de la página, como idea
    tareas.click('[data-group="ideas"] [data-act="add-to"]')
    assert tareas.get_attribute("#tareasCapture [data-capture-type=idea]", "aria-pressed") == "true"
    tareas.fill("#tareasCapture-text", "Idea desde la cabecera")
    tareas.press("#tareasCapture-text", "Enter")
    assert visto_en_los_dos("Idea desde la cabecera")["type"] == "idea"

    # Paso nuevo desde el menú de una tarjeta (Inbox)
    padre = next(i for i in _items(api).values() if i["text"] == "Desde Tareas")
    inbox.click(f"{card(padre['id'])} > .il-row [data-act=menu]")
    inbox.get_by_role("menuitem", name="Añadir un paso").click()
    inbox.fill(f"{card(padre['id'])} .il-addform input", "Paso desde el Inbox")
    inbox.press(f"{card(padre['id'])} .il-addform input", "Enter")
    assert visto_en_los_dos("Paso desde el Inbox")["parent_id"] == padre["id"]

    # Casilla nueva en una nota, desde su grupo en Tareas
    tareas.click('.il-note[data-note="plan-e2e"] [data-act="add-note"]')
    tareas.fill('.il-note[data-note="plan-e2e"] .il-addform input', "Casilla desde Tareas")
    tareas.press('.il-note[data-note="plan-e2e"] .il-addform input', "Enter")
    assert visto_en_los_dos("Casilla desde Tareas")["origin"] == "nota"
    assert "- [ ] Casilla desde Tareas" in api.get("/api/notes/plan-e2e").json()["content"]

    # Extensión de Firefox (alias antiguo y API nueva)
    api.post("/api/inbox", json={"content": "Desde la extensión 2.1", "item_type": "tarea"})
    api.post("/api/items", json={"text": "Desde la extensión 2.2", "type": "tarea"})
    for pg in (inbox, tareas):  # lo crea otro programa: se ve al volver a la pestaña (como al recuperar el foco)
        _volver(pg)
    visto_en_los_dos("Desde la extensión 2.1")
    visto_en_los_dos("Desde la extensión 2.2")
    inbox.close()
    tareas.close()


# ─────────── 2. Reordenar en Tareas y verlo igual en el Inbox ───────────

def test_2_reordenar_en_tareas_persiste_y_se_ve_en_el_inbox(page, server, api):
    _limpiar(api)
    a, b, c = (_nuevo(api, f"Orden {n}") for n in "abc")
    _abrir(page, server, "/tareas")
    assert _orden(page) == [c, b, a]
    _arrastrar(page, f"{card(a)} .il-text", card(c), "top")
    assert _orden(page) == [a, c, b]
    page.reload()
    page.wait_for_selector(".il-item")
    _settle(page)
    assert _orden(page) == [a, c, b]
    _abrir(page, server, "/inbox")
    assert _orden(page) == [a, c, b]


# ─────────── 3. Anidar y sacar, con reglas ───────────

def _arrastrar(page, src, target, where="top", during=None):
    """Como mouse_drag, pero mide el destino ya empezado el arrastre (la lista se reacomoda al ocultar el origen)."""
    a = page.locator(src).first.bounding_box()
    page.mouse.move(a["x"] + min(40, a["width"] / 2), a["y"] + 8)
    page.mouse.down()
    page.mouse.move(a["x"] + min(40, a["width"] / 2) + 8, a["y"] + 20, steps=3)
    page.wait_for_timeout(350)  # la lista de origen se recoge (animación) y el destino sube
    page.locator(target).first.scroll_into_view_if_needed()
    pos = lambda b: {"top": b["y"] + 4, "bottom": b["y"] + b["height"] - 4, "center": b["y"] + b["height"] / 2}[where]  # noqa: E731
    b = page.locator(target).first.bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, pos(b), steps=14)
    page.wait_for_timeout(150)
    b = page.locator(target).first.bounding_box()  # por si el hueco del arrastre lo ha movido
    page.mouse.move(b["x"] + b["width"] / 2 + 3, pos(b), steps=2)
    page.wait_for_timeout(120)
    result = during() if during else None
    page.mouse.up()
    _settle(page)
    return result


def _drop_como_paso(page, src, parent, during=None, sobre="> .il-row"):
    """Arrastra src y lo suelta sobre el centro de la tarjeta parent (= meterlo como paso). `sobre` elige
    la zona de parent: su fila (por defecto) o su lista de pasos («> .il-children»), que no se mueve
    cuando el hueco del arrastre empuja la tarjeta."""
    a = page.locator(f"{card(src)} > .il-row .il-text").bounding_box()
    page.mouse.move(a["x"] + 10, a["y"] + 6)
    page.mouse.down()
    page.mouse.move(a["x"] + 20, a["y"] + 20, steps=3)
    page.wait_for_timeout(100)
    b = page.locator(f"{card(parent)} {sobre}").bounding_box()
    page.mouse.move(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, steps=12)
    page.wait_for_timeout(150)
    b = page.locator(f"{card(parent)} {sobre}").bounding_box()  # por si algo se ha movido
    page.mouse.move(b["x"] + b["width"] / 2 + 4, b["y"] + b["height"] / 2, steps=2)
    result = during() if during else None
    page.mouse.up()
    _settle(page)
    return result


def test_3_anidar_y_sacar_con_reglas(page, server, api):
    _limpiar(api)
    x = _nuevo(api, "Suelta")
    p = _nuevo(api, "Madre")
    idea = _nuevo(api, "Idea madre", "idea")
    _nuevo(api, "Subidea", "idea", parent_id=idea)
    _abrir(page, server, "/tareas")

    _drop_como_paso(page, x, p)
    assert _items(api)[x]["parent_id"] == p
    assert page.locator(f"{card(p)} > .il-children > {card(x)}").count() == 1

    # Una subtarea no entra en una idea: aviso, zona roja y no se mueve
    def mirar():
        # el aviso aparece cuando el arrastre evalúa el destino: se espera a que tenga texto (no un tiempo fijo)
        page.wait_for_function("() => (document.querySelector('.sortable-ghost .sortable-badge')?.textContent || '').trim()", timeout=3000)
        return page.locator(".sortable-ghost .sortable-badge").inner_text()
    aviso = _drop_como_paso(page, x, idea, during=mirar, sobre="> .il-children")
    assert "subidea" in aviso
    assert _items(api)[x]["parent_id"] == p

    # Un elemento con pasos no se convierte en idea arrastrándolo a Ideas
    aviso = _arrastrar(page, f"{card(p)} > .il-row .il-text", card(idea), "top", during=mirar)
    assert "pasos" in aviso and _items(api)[p]["type"] == "tarea"

    # Sacarlo de su padre arrastrando a la lista (encima de la madre)
    _arrastrar(page, f"{card(x)} .il-text", card(p), "top")
    assert _items(api)[x]["parent_id"] is None
    assert _orden(page).index(x) == _orden(page).index(p) - 1


# ─────────── 4. Tarea de una nota: Tareas ↔ nota ───────────

def test_4_tarea_de_nota_en_los_dos_sentidos(context, server, api):
    tareas = context.new_page()
    nota = context.new_page()
    _abrir(tareas, server, "/tareas")
    tareas.click("[data-status=all]")
    uno = next(i for i in _items(api).values() if i["note_id"] == "plan-e2e" and i["text"] == "Tarea de nota uno")

    # Editar desde Tareas (doble clic) → cambia la línea de la nota
    tareas.dblclick(f"{card(uno['id'])} > .il-row .il-text")
    tareas.fill(f"[data-edit='{uno['id']}'] textarea[name=text]", "Tarea de nota uno editada")
    tareas.select_option(f"[data-edit='{uno['id']}'] select[name=priority]", "alta")
    tareas.fill(f"[data-edit='{uno['id']}'] input[name=due_date]", "2026-12-01")
    tareas.click(f"[data-edit='{uno['id']}'] [type=submit]")
    _settle(tareas)
    contenido = api.get("/api/notes/plan-e2e").json()["content"]
    assert "- [ ] Tarea de nota uno editada" in contenido
    assert _items(api)[uno["id"]]["priority"] == "alta"

    # Marcarla en Tareas → [x] en la nota
    tareas.click(f"{card(uno['id'])} > .il-row [data-act=done]")
    _settle(tareas)
    assert "- [x] Tarea de nota uno editada" in api.get("/api/notes/plan-e2e").json()["content"]

    # Al revés: marcar la otra casilla en la nota (modo lectura) → cambia en Tareas sin recargar
    dos = next(i for i in _items(api).values() if i["note_id"] == "plan-e2e" and i["text"] == "Tarea de nota dos")
    nota.goto(server + "/?note=plan-e2e")
    nota.wait_for_load_state("networkidle")
    nota.click("#modeBtnRead")
    boxes = nota.locator("li > input[type=checkbox]:not([disabled])")
    boxes.nth(1).wait_for(timeout=5000)
    boxes.nth(1).check()
    tareas.wait_for_selector(f"{card(dos['id'])}.is-done", timeout=5000)
    assert "- [x] Tarea de nota dos" in api.get("/api/notes/plan-e2e").json()["content"]

    # Y editar el texto en la nota (guardado normal) → cambia en Tareas
    c = api.get("/api/notes/plan-e2e").json()
    api.post("/api/notes/plan-e2e", json={"title": c["title"], "category": c["category"], "status": c["status"],
                                          "content": c["content"].replace("Tarea de nota dos", "Tarea dos desde la nota")})
    _volver(tareas)
    tareas.wait_for_selector(f"{card(dos['id'])} .il-text:text('Tarea dos desde la nota')", timeout=5000)
    tareas.close()
    nota.close()


# ─────────── 5. Contadores y listados sincronizados ───────────

def _contadores(pg):
    return pg.evaluate("""() => ({
        pend: document.querySelector('[data-status-count=pendientes]').textContent,
        hechas: document.querySelector('[data-status-count=hechas]').textContent,
        menu: document.querySelector('.nav-count[data-inbox-count]').textContent,
        grupos: Object.fromEntries([...document.querySelectorAll('[data-count]')].map(e => [e.dataset.count, e.textContent])),
        ids: [...document.querySelectorAll('.il-item')].map(e => e.dataset.id).sort().join(','),
    })""")


def test_5_contadores_y_listados_iguales_entre_pestanas(context, server, api):
    _limpiar(api)
    for n in range(3):
        _nuevo(api, f"Contar {n}")
    inbox, tareas = context.new_page(), context.new_page()
    _abrir(inbox, server, "/inbox")
    _abrir(tareas, server, "/tareas")
    assert _contadores(inbox) == _contadores(tareas)
    srv = api.get("/api/items/counts").json()
    assert _contadores(tareas)["pend"] == str(srv["pendientes"])
    assert _contadores(tareas)["menu"] == str(srv["inbox"]["pendientes"])  # el menú cuenta solo lo del Inbox

    # Completar en Tareas → el Inbox (otra pestaña) cuadra sin recargar
    first = _orden(tareas)[0]
    tareas.click(f"{card(first)} > .il-row [data-act=done]")
    inbox.wait_for_selector(card(first), state="detached", timeout=5000)
    _settle(inbox)
    assert _contadores(inbox) == _contadores(tareas)

    # Borrar en el Inbox con deshacer → Tareas cuadra; deshacer → vuelve en las dos
    second = _orden(inbox)[0]
    inbox.locator(card(second)).focus()
    inbox.keyboard.press("Delete")
    tareas.wait_for_selector(card(second), state="detached", timeout=5000)
    _deshacer(inbox)
    tareas.wait_for_selector(card(second), timeout=5000)
    _settle(inbox)
    _settle(tareas)
    assert _contadores(inbox) == _contadores(tareas)

    # Tras recargar, igual
    inbox.reload()
    tareas.reload()
    _abrir(inbox, server, "/inbox")
    _abrir(tareas, server, "/tareas")
    assert _contadores(inbox) == _contadores(tareas)
    inbox.close()
    tareas.close()


# ─────────── Teclado, lote, táctil ───────────

def test_teclado_editar_marcar_mover_y_anidar(page, server, api):
    _limpiar(api)
    a, b = _nuevo(api, "Tecla a"), _nuevo(api, "Tecla b")
    _abrir(page, server, "/tareas")
    assert _orden(page) == [b, a]
    page.locator(card(a)).focus()
    page.keyboard.press("Alt+ArrowUp")
    _settle(page)
    assert _orden(page) == [a, b]
    page.locator(card(b)).focus()
    page.keyboard.press("Alt+Shift+ArrowRight")  # paso de la anterior
    _settle(page)
    assert _items(api)[b]["parent_id"] == a
    page.locator(card(b)).focus()
    page.keyboard.press("Alt+Shift+ArrowLeft")   # y fuera
    _settle(page)
    assert _items(api)[b]["parent_id"] is None
    page.locator(card(a)).focus()
    page.keyboard.press("Enter")
    page.keyboard.press("Control+a")
    page.keyboard.type("Tecla a editada")
    page.keyboard.press("Control+Enter")
    _settle(page)
    assert _items(api)[a]["text"] == "Tecla a editada"
    page.locator(card(a)).focus()
    page.keyboard.press(" ")
    _settle(page)
    assert _items(api)[a]["done"] is True
    page.locator(card(b)).focus()
    page.keyboard.press("Alt+ArrowRight")  # al grupo siguiente: la primera nota (casilla nueva)
    _settle(page)
    assert _items(api)[b]["origin"] == "nota"
    for _ in range(5):  # y nota a nota hasta Ideas: se convierte en idea
        if _items(api)[b]["origin"] == "ideas":
            break
        page.locator(card(b)).focus()
        page.keyboard.press("Alt+ArrowRight")
        _settle(page)
    assert _items(api)[b]["type"] == "idea"
    assert "Tecla b" not in api.get("/api/notes/plan-e2e").json()["content"]


def test_lote_completar_categoria_y_borrar_con_deshacer(page, server, api):
    _limpiar(api)
    ids = [_nuevo(api, f"Lote {n}") for n in range(3)]
    _abrir(page, server, "/tareas")
    page.click("#btnSelect")
    for i in ids[:2]:
        page.click(f"{card(i)} > .il-row [data-act=select]")
    assert "2 seleccionados" in page.locator(".il-bulkbar").inner_text()
    page.once("dialog", lambda d: d.accept())
    page.click("[data-bulk=category]")
    page.fill(".modal[open] input, .modal[open] textarea", "Recados")
    page.keyboard.press("Enter")
    _settle(page)
    assert [_items(api)[i]["category"] for i in ids] == ["Recados", "Recados", None]
    page.click("[data-bulk=delete]")
    _settle(page)
    assert not set(ids[:2]) & set(_items(api))
    _deshacer(page)
    _settle(page)
    assert set(ids) <= set(_items(api))


def test_arrastre_tactil_en_movil(browser, server, api):
    _limpiar(api)
    a, b, c = (_nuevo(api, f"Dedo {n}") for n in "abc")
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, has_touch=True, is_mobile=True, service_workers="block")
    page = ctx.new_page()
    try:
        _abrir(page, server, "/tareas")
        touch_drag(page, f"{card(a)} .il-text", card(c), "top")
        assert _orden(page) == [a, c, b]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        ctx.close()


# ─────────── Capturas «después» ───────────

@pytest.mark.parametrize("w,h", [(1280, 900), (375, 812)])
def test_capturas_despues(browser, server, api, w, h):
    if not SHOTS:
        pytest.skip("PANEL_SHOTS no definido")
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    mobile = w < 768
    ctx = browser.new_context(viewport={"width": w, "height": h}, has_touch=mobile, is_mobile=mobile, service_workers="block")
    page = ctx.new_page()
    try:
        _abrir(page, server, "/tareas")
        page.screenshot(path=f"{SHOTS}/tareas-{w}.png", full_page=True)
        _abrir(page, server, "/inbox")  # en el móvil empieza en la lista
        page.screenshot(path=f"{SHOTS}/inbox-{w}.png")
    finally:
        ctx.close()
