"""F-3: /buscar agrupa notas, tareas, Baúl y eventos; cada resultado lleva a su sitio; Ctrl+K enseña lo que sale
«Dentro del texto»; a 375 px no hay desborde."""

import re
import time


def _datos(api):
    r = api.post(
        "/api/notes/e2e-busqueda",
        json={"title": "Apuntes de óptica", "category": "E2E", "content": "La refracción del prisma separa colores."},
    )
    assert r.status_code == 200, r.text
    tarea = api.post("/api/items", json={"text": "Comprar un prisma de refracción", "contexto": "puntual"}).json()["id"]
    api.post("/api/calendar/events", json={"title": "Laboratorio", "start": "2026-12-04T10:00", "notes": "Refracción"})
    # Un recurso con una URL que no responde: se espera a que acabe su lectura de metadatos y se le pone título
    api.post("/api/resources", json={"url": "http://127.0.0.1:9/refraccion", "category": "Física"})
    rid = None
    for _ in range(50):
        rid = next(
            (x["id"] for x in api.get("/api/resources").json()["resources"] if x["url"].endswith("/refraccion")), None
        )
        if rid:
            break
        time.sleep(0.1)
    time.sleep(1.0)
    api.patch(f"/api/resources/{rid}", json={"title": "Vídeo de refracción", "description": "Experimento casero"})
    return tarea, rid


def test_buscar_agrupa_por_tipo_y_enlaza(page, api, server):
    tarea, rid = _datos(api)
    page.goto(f"{server}/buscar?q=refraccion")
    page.locator(".result-group").nth(3).wait_for()
    titulos = page.locator(".result-group-title").all_inner_texts()
    assert [re.sub(r"\s*\d+$", "", t.strip()) for t in titulos] == [
        "Notas",
        "Tareas, ideas y rutinas",
        "Baúl",
        "Eventos",
    ]
    assert page.locator(".result-group mark").count() >= 4  # la coincidencia, resaltada
    assert page.locator(f'a[href="/tareas?item={tarea}"]').count() == 1
    assert page.locator('a[href="/calendario?dia=2026-12-04"]').count() == 1

    # Solo el Baúl, y de ahí al recurso, resaltado
    page.locator('#kindChips [data-kind="recurso"]').click()
    page.wait_for_function("document.querySelectorAll('.result-group').length === 1")
    assert "tipo=recurso" in page.url
    page.locator(f'a[href="/vault?recurso={rid}"]').click()
    page.wait_for_url("**/vault*")
    page.locator(f'#vaultContent [data-id="{rid}"].is-flash').wait_for()

    # Ctrl+K: la nota sale «Dentro del texto» aunque su título no tenga la palabra
    page.goto(f"{server}/hoy")
    page.keyboard.press("Control+k")
    page.keyboard.type("prisma separa")
    fila = page.locator(".palette-row", has_text="Apuntes de óptica")
    fila.wait_for()
    assert fila.locator("mark").count() >= 1
    fila.click()
    page.wait_for_url("**/?note=e2e-busqueda")


def test_buscar_en_movil_sin_desborde(page, api, server):
    page.set_viewport_size({"width": 375, "height": 800})
    api.post("/api/items", json={"text": "Tarea de nefelometría con un texto bastante largo " * 4})
    page.goto(f"{server}/buscar?q=nefelometria")
    page.locator(".result-group").first.wait_for()
    assert page.evaluate("document.documentElement.scrollWidth") <= 375
