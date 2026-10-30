"""Las esperas de los tests no dependen de eval: la CSP del panel lo prohíbe."""


def test_esperar_algo_que_tarda_con_la_csp_activa(page, server):
    page.goto(f"{server}/hoy")
    page.evaluate("() => { window.__tarde = false; setTimeout(() => { window.__tarde = true; }, 300); }")
    page.wait_for_function("window.__tarde === true")
    page.evaluate("() => { setTimeout(() => { window.__valor = 7; }, 200); }")
    page.wait_for_function("(n) => window.__valor === n", arg=7, timeout=3000)
