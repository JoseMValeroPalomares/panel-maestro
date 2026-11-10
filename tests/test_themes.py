"""Temas: un azulejo propio por sección, sin repetidos y con el glifo legible (≥ 3:1, contraste de gráfico)."""
import re
from pathlib import Path

import pytest

from core.templating import NAV_GROUPS
from core.themes import THEMES, TILES

ROOT = Path(__file__).resolve().parent.parent


def _lum(hex_: str) -> float:
    c = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_cada_seccion_del_menu_tiene_su_azulejo():
    secciones = {key for _, _, items in NAV_GROUPS for key, *_ in items}
    assert secciones == set(TILES)


@pytest.mark.parametrize("name", list(THEMES))
def test_azulejos_completos_unicos_y_legibles(name):
    t = THEMES[name]
    assert set(t["tiles"]) == set(TILES)
    assert len(set(t["tiles"].values())) == len(TILES), "dos secciones comparten color"
    for key, color in t["tiles"].items():
        assert _contrast(color, t["tile_fg"]) >= 3.0, f"{name}.{key}: glifo con poco contraste"


def test_ds_css_asigna_a_cada_seccion_su_propio_token():
    css = (ROOT / "static" / "css" / "ds.css").read_text(encoding="utf-8")
    pares = dict(re.findall(r'\[data-section="([a-z]+)"\] \{ --tile: var\(--tile-([a-z]+)\); \}', css))
    assert pares == {k: k for k in TILES}


def test_themes_css_generado_al_dia():
    from scripts.themes import build
    assert (ROOT / "static" / "css" / "themes.css").read_text(encoding="utf-8") == build()


def _lab(h: str):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    x = (c[0] * 0.4124 + c[1] * 0.3576 + c[2] * 0.1805) / 0.95047
    y = c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722
    z = (c[0] * 0.0193 + c[1] * 0.1192 + c[2] * 0.9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _delta_e(a: str, b: str) -> float:
    return sum((p - q) ** 2 for p, q in zip(_lab(a), _lab(b))) ** 0.5


@pytest.mark.parametrize("name", list(THEMES))
def test_azulejos_distinguibles(name):
    """Ningún par casi igual (ΔE ≥ 6) y, entre vecinos del menú, claramente distintos (ΔE ≥ 15)."""
    t = THEMES[name]["tiles"]
    keys = list(t)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            assert _delta_e(t[a], t[b]) >= 6, f"{name}: {a} y {b} casi iguales"
    for grupo, _, items in NAV_GROUPS:
        if grupo == "sistema":  # grises a propósito: utilidades, no destinos
            continue
        orden = [key for key, *_ in items]
        for a, b in zip(orden, orden[1:]):
            assert _delta_e(t[a], t[b]) >= 15, f"{name}: {a} y {b} (vecinos en el menú) se parecen"
