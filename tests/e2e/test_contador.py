"""P-2: contador en marcha. Empezar en una pestaña y verlo en otra; pausar, cambiar y completar; 375 y 1280 px."""

import pytest


def _nueva(api, text, **extra):
    r = api.post("/api/items", json={"text": text, "type": "tarea", **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _item(api, i):
    return next((x for x in api.get("/api/items").json()["items"] if x["id"] == i), None)


@pytest.fixture(autouse=True)
def sin_contador(api):
    if api.get("/api/contador").json()["activa"]:
        api.post("/api/contador/quitar")
    yield
    if api.get("/api/contador").json()["activa"]:
        api.post("/api/contador/quitar")


@pytest.mark.parametrize("ancho", [375, 1280])
def test_empezar_en_una_pestana_y_verlo_en_otra(context, api, server, ancho):
    a = _nueva(api, f"E2E contador A {ancho}", duration_min=25)
    b = _nueva(api, f"E2E contador B {ancho}")
    uno, dos = context.new_page(), context.new_page()
    errores = []
    for pg in (uno, dos):
        pg.set_viewport_size({"width": ancho, "height": 820})
        pg.on("pageerror", lambda e: errores.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and errores.append(m.text))
    uno.goto(f"{server}/tareas")
    dos.goto(f"{server}/hoy")
    dos.locator("body").wait_for()

    # Empezar desde el menú de la tarjeta (pestaña 1)
    card = uno.locator(f'.il-item[data-id="{a}"]')
    card.wait_for()
    card.locator("[data-act='menu']").first.click()
    uno.locator(".menu .menu-item", has_text="Empezar contador").click()
    uno.locator(".run-bar.is-running").wait_for()
    assert f"E2E contador A {ancho}" in uno.locator(".run-title").inner_text()
    assert "25 min previstos" in uno.locator(".run-sub").inner_text()
    card.locator(".il-timer-live").wait_for()  # la tarjeta dice «En marcha»

    # La otra pestaña se entera sola (BroadcastChannel) y el tiempo corre en local
    dos.locator(".run-bar.is-running").wait_for()
    t0 = dos.locator("[data-run-time]").inner_text()
    dos.wait_for_timeout(1300)
    assert dos.locator("[data-run-time]").inner_text() != t0

    # Pausar en la 2 → la 1 lo ve en pausa; seguir con el mismo botón
    dos.get_by_role("button", name="Pausar").click()
    uno.locator(".run-bar.is-paused").wait_for()
    assert api.get("/api/contador").json()["activa"]["estado"] == "pausa"
    uno.get_by_role("button", name="Seguir").click()
    dos.locator(".run-bar.is-running").wait_for()

    # Cambiar a otra (la B) con el selector
    uno.get_by_role("button", name="Cambiar a otra").click()
    picker = uno.locator("dialog[open] .pick-search input")
    picker.fill(f"contador B {ancho}")
    uno.keyboard.press("Enter")
    uno.wait_for_function(f"document.querySelector('.run-title')?.textContent.includes('E2E contador B {ancho}')")
    dos.wait_for_function(f"document.querySelector('.run-title')?.textContent.includes('E2E contador B {ancho}')")

    # Completar: la tarea queda hecha, la barra desaparece en las dos y la A guarda su tiempo
    dos.get_by_role("button", name=f"Completar «E2E contador B {ancho}»").click()
    dos.wait_for_function("!document.querySelector('.run-bar')")
    uno.wait_for_function("!document.querySelector('.run-bar')")
    assert _item(api, b)["done"]
    assert "tiempo_s" in _item(api, a) or api.get("/api/contador/tiempos").json()["elementos"]
    assert uno.evaluate("document.documentElement.scrollWidth") <= ancho
    assert not errores, errores
    uno.close()
    dos.close()


def test_sobrevive_a_recargar_y_actividad_libre(page, api, server):
    page.goto(f"{server}/calendario")
    page.evaluate("void Timer.pick()")  # sin esperar a la promesa (se resuelve al elegir)
    page.locator("dialog[open] .pick-row", has_text="Actividad libre").click()
    page.locator("dialog[open] input").last.fill("E2E ordenar la mesa")
    page.keyboard.press("Enter")
    page.locator(".run-bar.is-running").wait_for()
    page.reload()
    page.locator(".run-bar.is-running").wait_for()  # el estado está en el servidor
    assert "E2E ordenar la mesa" in page.locator(".run-title").inner_text()
    assert page.locator('.run-bar [data-run="completar"]').count() == 0  # una actividad libre no se «completa»
    page.get_by_role("button", name="Quitar el contador (el tiempo se guarda)").click()
    page.wait_for_function("!document.querySelector('.run-bar')")
    assert api.get("/api/contador").json()["activa"] is None


def test_paso_a_paso_de_rutina_lleva_el_contador(page, api, server):
    r = api.post("/api/items", json={"text": "E2E rutina contador", "type": "rutina"}).json()["id"]
    p1 = api.post(
        "/api/items", json={"text": "E2E paso uno", "type": "rutina", "parent_id": r, "duration_min": 5}
    ).json()["id"]
    api.post("/api/items", json={"text": "E2E paso dos", "type": "rutina", "parent_id": r, "duration_min": 5})
    page.goto(f"{server}/tareas")
    page.wait_for_function("window.Items && Items.state.loaded")
    page.evaluate(f"Routines.run({r})")
    page.locator(".run-bar.is-running .run-title", has_text="E2E paso uno").wait_for()
    assert "Paso de «E2E rutina contador»" in page.locator(".run-sub").inner_text()
    page.locator('dialog[open] [data-run-act="done"]').click()
    page.locator(".run-bar .run-title", has_text="E2E paso dos").wait_for()  # el contador sigue al paso actual
    tiempos = api.get("/api/contador/tiempos").json()
    assert any(e["item_id"] == p1 for e in tiempos["elementos"]) or _item(api, p1)["done"]
