"""Ronda 2 · fase 6: tema Catppuccin Mocha en todas las pantallas (escritorio y móvil).

Recorre cada página: sin errores de consola, sin desbordamiento horizontal, fondo Mocha y el texto
principal con contraste AA. Con BOARD_SHOTS guarda capturas para revisarlas.
"""
import os
from pathlib import Path

import pytest

from core.themes import THEMES

SHOTS = os.environ.get("BOARD_SHOTS")
PAGES = ["/", "/hoy", "/inbox", "/tareas", "/calendario", "/vault", "/graph", "/buscar", "/repaso", "/revision", "/rendimiento", "/gestion", "/backups", "/papelera", "/comidas/", "/estudio/"]

CONTRAST = """() => {
  // rgb()/rgba() en 0–255; color(srgb …) (lo que da color-mix) en 0–1
  const parse = (c) => { const m = (c.match(/[\\d.]+/g) || [0, 0, 0, 0]).map(Number); const k = c.startsWith('color(') ? 255 : 1;
    return [m[0] * k, m[1] * k, m[2] * k, m.length > 3 ? m[3] : 1]; };
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const over = (top, under) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat(1);
  // Fondo real bajo un elemento: capas semitransparentes compuestas hasta una opaca
  const backOf = (el) => {
    const layers = [];
    for (let p = el; p; p = p.parentElement) {
      const c = parse(getComputedStyle(p).backgroundColor);
      if (c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let acc = parse(getComputedStyle(document.body).backgroundColor);
    for (let i = layers.length - 1; i >= 0; i--) acc = over(layers[i], acc);
    return acc;
  };
  const bad = [];
  for (const el of document.querySelectorAll('main h1, main h2, main p, main label, main button, main a, main span, nav a')) {
    if (!el.offsetParent || !el.textContent.trim() || el.closest('.board-wrap, .tile, [disabled], .skeleton, .sr-only')) continue;
    if ([...el.childNodes].every((n) => n.nodeType !== 3 || !n.textContent.trim())) continue;
    const cs = getComputedStyle(el);
    if (+cs.opacity < 1) continue;
    const back = backOf(el), fg = over(parse(cs.color), back);
    const [a, b] = [lum(fg), lum(back)].sort((x, y) => y - x);
    const r = (a + 0.05) / (b + 0.05);
    const big = parseFloat(cs.fontSize) >= 24 || (parseFloat(cs.fontSize) >= 18.6 && +cs.fontWeight >= 700);
    if (r < (big ? 3 : 4.5)) bad.push(`${el.tagName}.${el.className} «${el.textContent.trim().slice(0, 30)}» ${r.toFixed(2)}`);
  }
  return { bg: getComputedStyle(document.body).backgroundColor, bad: bad.slice(0, 8) };
}"""


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return f"rgb({int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)})"


CASES = [(t, 1280, 800) for t in ["system", *THEMES]] + [("mocha", 375, 812), ("light", 375, 812), ("latte", 375, 812)]


@pytest.mark.parametrize("theme,w,h", CASES, ids=[f"{t}-{w}" for t, w, _ in CASES])
def test_tema_en_todas_las_paginas(browser, server, theme, w, h):
    mobile = w < 768
    ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=mobile, has_touch=mobile, service_workers="block", color_scheme="light")
    page = ctx.new_page()
    page.add_init_script(f"localStorage.setItem('theme', '{theme}')")
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and "ESP32" not in m.text and "WebSocket" not in m.text and errors.append(m.text))
    expected_bg = _hex_to_rgb(THEMES["light" if theme == "system" else theme]["bg"])
    problems = []
    try:
        for path in PAGES:
            page.goto(server + path)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(200)
            r = page.evaluate(CONTRAST)
            if r["bg"] != expected_bg:
                problems.append(f"{path}: fondo {r['bg']} (se esperaba {expected_bg})")
            if r["bad"]:
                problems.append(f"{path}: contraste bajo {r['bad']}")
            if not page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"):
                problems.append(f"{path}: desborda en horizontal")
            if SHOTS and (theme in ("mocha", "light", "latte") or path in ("/", "/inbox", "/comidas/")):
                Path(SHOTS).mkdir(parents=True, exist_ok=True)
                name = path.strip("/").replace("/", "-") or "notas"
                page.screenshot(path=f"{SHOTS}/tema-{theme}-{name}-{w}.png")
        assert not problems, "\n".join(problems)
        assert not errors, errors
    finally:
        ctx.close()


def test_selector_de_tema(page, server):
    page.goto(server + "/")
    page.wait_for_load_state("networkidle")
    assert page.get_attribute("html", "data-theme") == "mocha"  # por defecto
    page.click(".sidebar [data-open-more]")
    radios = page.locator(".theme-grid [role=radio]")
    assert radios.count() == len(THEMES) + 1
    assert page.locator("[data-theme-choice=mocha]").get_attribute("aria-checked") == "true"
    page.click("[data-theme-choice=nord]")
    page.locator("html[data-theme=nord]").wait_for(state="attached")  # el cambio va dentro de un fundido
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == _hex_to_rgb(THEMES["nord"]["bg"])
    # teclado: flechas cambian de tema (grupo de radio con un solo tabulador)
    page.keyboard.press("ArrowRight")
    page.locator("html[data-theme=dracula]").wait_for(state="attached")
    page.goto(server + "/inbox")  # se recuerda y se aplica antes de pintar
    assert page.get_attribute("html", "data-theme") == "dracula"
    assert page.evaluate("document.getElementById('themeColor').content") == page.evaluate("getComputedStyle(document.body).backgroundColor")


@pytest.mark.parametrize("theme", ["mocha", "light"])
def test_foco_visible_con_teclado(browser, server, theme):
    """Recorre con Tab cada pantalla: todo lo que recibe el foco lo muestra (contorno o sombra)."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    page = ctx.new_page()
    page.add_init_script(f"localStorage.setItem('theme', '{theme}')")
    sin_foco = []
    try:
        for path in ["/", "/inbox", "/tareas", "/vault", "/comidas/", "/estudio/"]:
            page.goto(server + path)
            page.wait_for_load_state("networkidle")
            for _ in range(18):
                page.keyboard.press("Tab")
                r = page.evaluate("""() => { const e = document.activeElement; if (!e || e === document.body) return null;
                    const cs = getComputedStyle(e);
                    return { ok: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 || cs.boxShadow !== 'none',
                             what: e.tagName + '.' + (e.className?.baseVal ?? e.className) + ' ' + (e.getAttribute('aria-label') || e.textContent.trim()).slice(0, 30) }; }""")
                if r and not r["ok"]:
                    sin_foco.append(f"{path}: {r['what']}")
        assert not sin_foco, sorted(set(sin_foco))
    finally:
        ctx.close()
