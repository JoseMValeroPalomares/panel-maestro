"""Iconos: todo nombre que se pinta existe en el sprite y cada estado de stateView tiene su ilustración."""
import re
from pathlib import Path

from core.templating import NAV_GROUPS

ROOT = Path(__file__).resolve().parent.parent
FUENTES = ["templates/*.html", "static/js/*.js", "comidas/static/js/*.js", "estudio/static/*.js"]
# icon('x'…), icon("x"…), icon: 'x', iconName: 'x'
USO = re.compile(r"""\bicon\(\s*['"]([a-z0-9-]+)['"]|\bicon(?:Name)?:\s*['"]([a-z0-9-]+)['"]""")


def _sprite(path: str, prefix: str) -> set[str]:
    return set(re.findall(rf'<symbol id="{prefix}-([a-z0-9-]+)"', (ROOT / path).read_text(encoding="utf-8")))


def test_todo_icono_usado_existe_en_el_sprite():
    sprite = _sprite("static/icons.svg", "i")
    usados = {}
    for pat in FUENTES:
        for f in ROOT.glob(pat):
            for a, b in USO.findall(f.read_text(encoding="utf-8")):
                usados.setdefault(a or b, f.relative_to(ROOT).as_posix())
    for _, _, items in NAV_GROUPS:
        for key, _label, _href, ic in items:
            usados.setdefault(ic, f"navegación ({key})")
    faltan = {n: donde for n, donde in usados.items() if n not in sprite}
    assert not faltan, f"iconos sin símbolo en static/icons.svg (añádelos a scripts/icons.txt): {faltan}"


def test_iconos_propios_en_el_sprite():
    propios = {p.stem for p in (ROOT / "assets" / "icons" / "propios").glob("*.svg")}
    assert propios and propios <= _sprite("static/icons.svg", "i")


def test_cada_estado_tiene_su_ilustracion():
    ui = (ROOT / "static" / "js" / "ui.js").read_text(encoding="utf-8")
    bloque = re.search(r"const STATES = \{([\s\S]*?)\};", ui).group(1)
    pedidas = set(re.findall(r"\['([a-z-]+)',", bloque))
    assert pedidas == {"vacio", "hecho", "sin-resultados", "error", "sin-conexion"}
    assert pedidas <= _sprite("static/ilustraciones.svg", "ill")


def test_sin_glifos_de_texto_como_icono():
    """✓ y ★ eran caracteres sueltos en menús y chips: ahora son iconos de la familia."""
    for pat in FUENTES:
        for f in ROOT.glob(pat):
            texto = f.read_text(encoding="utf-8")
            assert "'✓ '" not in texto and "'★ '" not in texto and "★ Favoritos" not in texto, f
