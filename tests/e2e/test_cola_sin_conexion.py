"""F-6: capturar sin conexión desde la PWA. Lo que no llega al panel por red se guarda en el dispositivo y se manda
solo al volver; lo que el panel rechaza no se encola."""

import time

# Simula «sin red» solo para las altas: fetch se rechaza como cuando no hay conexión (sin errores en la consola,
# que el fixture page trata como fallo). Se quita llamando a window.__conRed().
SIN_RED = """() => {
  const real = window.fetch;
  window.fetch = (url, opts = {}) => (opts.method === 'POST' && /\\/api\\/(capture|items)$/.test(String(url))
    ? Promise.reject(new TypeError('Failed to fetch')) : real(url, opts));
  window.__conRed = () => { window.fetch = real; };
}"""


def _textos(api, marca):
    return sorted(
        f"{i['type']}:{i['text']}" for i in api.get("/api/items").json()["items"] if i["text"].startswith(marca)
    )


def test_capturas_sin_red_se_guardan_y_se_mandan_al_volver(page, server, api):
    page.goto(f"{server}/tareas")
    page.wait_for_function("window.Items && Items.state.loaded")
    marca = f"COLA-{time.time_ns()}"
    page.evaluate(SIN_RED)

    page.fill("#tareasCapture-text", f"{marca} formulario")
    page.press("#tareasCapture-text", "Enter")
    page.wait_for_function("Items.pendingCaptures === 1")
    assert page.input_value("#tareasCapture-text") == ""  # se da por guardada (en la cola)
    page.evaluate(f"Items.capture('i: {marca} prefijo', 'idea')")
    page.evaluate(f"Items.create({{ text: '{marca} create', type: 'tarea' }})")
    page.wait_for_function("Items.pendingCaptures === 3")
    assert "3 capturas esperando" in page.text_content(".toast-region")
    assert _textos(api, marca) == []  # nada ha llegado todavía

    # La cola vive en el dispositivo: sobrevive a recargar y se manda sola al abrir
    page.reload()
    page.wait_for_function("window.Items && Items.pendingCaptures === 0", timeout=10000)
    page.wait_for_selector(".toast-msg:has-text('Guardadas 3 capturas')")
    assert _textos(api, marca) == [f"idea:{marca} prefijo", f"tarea:{marca} create", f"tarea:{marca} formulario"]


def test_lo_que_el_panel_rechaza_no_se_encola(page, server):
    page.goto(f"{server}/tareas")
    page.wait_for_function("window.Items && Items.state.loaded")
    # El panel contesta 422 (datos no válidos): eso no es «sin red» y no debe reintentarse para siempre. Se simula la
    # respuesta para no ensuciar la consola con el «Failed to load resource» del navegador.
    page.evaluate("""() => {
      const real = window.fetch;
      window.fetch = (url, opts = {}) => (opts.method === 'POST' && /\\/api\\/items$/.test(String(url))
        ? Promise.resolve(new Response(JSON.stringify({ error: 'Datos no válidos' }), { status: 422 })) : real(url, opts));
    }""")
    page.evaluate("Items.create({ text: 'algo', type: 'tarea' }).catch(() => {})")
    page.wait_for_selector(".toast.error:has-text('Datos no válidos')")
    assert page.evaluate("Items.pendingCaptures") == 0
