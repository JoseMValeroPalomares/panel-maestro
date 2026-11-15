"""V-5: sin contexto seguro (panel por http://IP desde el móvil) no hay crypto.subtle. «Cifrar» y abrir una nota cifrada
lo explican y enlazan a la guía de HTTPS (/ayuda/https) en vez de fallar con un error interno."""

import json

# Lo que ve un navegador que abre el panel por HTTP desde la red: ni contexto seguro ni crypto.subtle
SIN_HTTPS = """
Object.defineProperty(window, 'isSecureContext', { get: () => false });
Object.defineProperty(Crypto.prototype, 'subtle', { get: () => undefined });
"""


def test_cifrar_sin_https_explica_y_enlaza_a_la_guia(page, api, server):
    page.context.add_init_script(SIN_HTTPS)
    page.goto(f"{server}/?note=plan-e2e")
    lock = page.locator("#lockToggle")
    lock.wait_for()
    assert "is-unavailable" in lock.get_attribute("class")
    assert "no disponible" in lock.get_attribute("aria-label")
    lock.click()
    dlg = page.locator("dialog[open]", has_text="Cifrado no disponible en esta conexión")
    dlg.wait_for()
    dlg.get_by_role("button", name="Cómo activar HTTPS").click()
    page.wait_for_url(f"{server}/ayuda/https")
    page.locator("h1", has_text="Servir el panel por HTTPS").wait_for()  # la cabecera es el título de la guía
    assert page.locator("h1").count() == 1
    assert page.locator("#docBody pre code").count() > 0  # los bloques de órdenes de la guía
    # el enlace a la otra guía va a /ayuda, no a un .md que el panel no sirve
    page.locator("#docBody a[href='/ayuda/fuera-de-casa']").first.wait_for()
    assert page.locator("#docBody a[href$='.md']").count() == 0

    # una nota ya cifrada: en vez de pedir una contraseña que no podría usar, lo explica
    blob = json.dumps({"salt": "AAAA", "iv": "AAAA", "data": "AAAA"})
    r = api.post(
        "/api/notes/cifrada-e2e", json={"title": "Cifrada E2E", "category": "E2E", "content": blob, "encrypted": True}
    )
    assert r.status_code == 200, r.text
    page.goto(f"{server}/?note=cifrada-e2e")
    pantalla = page.locator(".lock-screen")
    pantalla.locator("a[href='/ayuda/https']").wait_for()
    assert pantalla.locator("#unlockInline").count() == 0


def test_ayuda_solo_sirve_las_guias_de_la_lista(api):
    assert api.get("/ayuda/https").status_code == 200
    assert api.get("/ayuda/..%2F.env").status_code == 404
    assert api.get("/ayuda/CLAUDE").status_code == 404
