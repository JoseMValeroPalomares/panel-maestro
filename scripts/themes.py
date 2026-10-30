"""
Genera static/css/themes.css: los tokens de color de cada tema del Panel.

    python -m scripts.themes

Cada tema se define una sola vez aquí (paleta) y el resto de tokens se derivan (fondos suaves, separadores,
sombras…). Catppuccin Mocha es el tema por defecto (también sin `data-theme`). «Sistema» usa el claro y el
oscuro de Apple según la preferencia del equipo. Los valores que no son de la paleta oficial de un tema están
ajustados para cumplir AA (4.5:1 en texto); lo comprueba tests/e2e/test_tema.py en todas las páginas.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "static" / "css" / "themes.css"
sys.path.insert(0, str(ROOT))

from core.themes import DEFAULT, THEMES, TILES  # noqa: E402


def rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgba(color, a: float) -> str:
    r, g, b = rgb(color) if isinstance(color, str) else color
    return f"rgba({r}, {g}, {b}, {a})"


def tokens(t: dict) -> list[str]:
    dark = t["dark"]
    hover = (205, 214, 244) if dark else (0, 0, 0)
    out = [
        f"color-scheme: {'dark' if dark else 'light'};",
        f"--bg: {t['bg']}; --bg-elev: {t['elev']}; --bg-elev-2: {t['elev2']}; --bg-sunken: {t['sunken']};",
        f"--sidebar: {rgba(t['sunken'] if dark else t['sunken'], 0.88)};",
        f"--fill: {rgba(t['neutral'], 0.14 if dark else 0.12)}; --fill-strong: {rgba(t['neutral'], 0.24 if dark else 0.2)};",
        f"--hover: {rgba(hover, 0.06 if dark else 0.045)}; --press: {rgba(hover, 0.1 if dark else 0.08)};",
        f"--separator: {rgba(t['sep'], 0.35 if dark else 0.16)}; --separator-strong: {rgba(t['sep'], 0.6 if dark else 0.28)};",
        f"--text: {t['text']}; --text-2: {t['text2']}; --text-3: {t['text3']};",
        f"--text-on-accent: {t['on_accent']}; --text-on-danger: {t['on_danger']};",
        f"--accent: {t['accent']}; --accent-fill: {t['accent_fill']}; --accent-hover: {t['accent_hover']};",
        f"--accent-soft: {rgba(t['accent_fill'], 0.16 if dark else 0.1)}; --accent-ring: {rgba(t['accent_fill'], 0.55 if dark else 0.35)};",
        f"--danger: {t['danger']}; --danger-soft: {rgba(t['danger'], 0.16 if dark else 0.09)};",
        f"--warning: {t['warning']}; --warning-soft: {rgba(t['warning'], 0.16 if dark else 0.13)};",
        f"--success: {t['success']}; --success-soft: {rgba(t['success'], 0.16 if dark else 0.13)}; --info: {t['accent']};",
        f"--st-draft: {t['draft']}; --st-wip: {t['warning']}; --st-done: {t['success']}; --st-index: {t['index']};",
        f"--tile-fg: {t['tile_fg']}; " + " ".join(f"--tile-{k}: {v};" for k, v in zip(TILES, t["tiles"])),
        " ".join(f"--cat-{i}: {c};" for i, c in enumerate(t["cats"])),
        # Lienzo del tablero: la superficie del tema si es oscuro; en los claros, Mocha (las formas son para fondo oscuro)
        f"--board-bg: {t['elev'] if dark else '#1e1e2e'}; --board-grid: {rgba(t['sep'], 0.75) if dark else '#45475a'};",
    ]
    if dark:
        out.append("--shadow-1: 0 1px 2px rgba(0, 0, 0, 0.35); --shadow-2: 0 6px 20px rgba(0, 0, 0, 0.4), 0 1px 3px rgba(0, 0, 0, 0.3);")
        out.append(f"--shadow-3: 0 24px 60px rgba(0, 0, 0, 0.55), 0 6px 16px rgba(0, 0, 0, 0.35); --backdrop: {rgba(t['sunken'], 0.66)};")
    else:
        out.append("--shadow-1: 0 1px 2px rgba(0, 0, 0, 0.06), 0 1px 1px rgba(0, 0, 0, 0.03); --shadow-2: 0 4px 16px rgba(0, 0, 0, 0.08), 0 1px 3px rgba(0, 0, 0, 0.05);")
        out.append("--shadow-3: 0 18px 48px rgba(0, 0, 0, 0.16), 0 4px 12px rgba(0, 0, 0, 0.06); --backdrop: rgba(0, 0, 0, 0.32);")
    return out


def block(selector: str, t: dict, indent: str = "") -> str:
    body = "\n".join(f"{indent}  {line}" for line in tokens(t))
    return f"{indent}{selector} {{\n{body}\n{indent}}}\n"


def build() -> str:
    parts = ["/* Generado por `python -m scripts.themes` — no editar a mano. Temas del Panel (tokens de color). */\n"]
    for name, t in THEMES.items():
        sel = f':root[data-theme="{name}"]'
        if name == DEFAULT:
            sel = f':root, {sel}'
        parts.append(f"/* {t['label']} */\n" + block(sel, t))
    parts.append("/* Sistema: claro u oscuro de Apple según la preferencia del equipo */\n" + block(':root[data-theme="system"]', THEMES["light"]))
    parts.append("@media (prefers-color-scheme: dark) {\n" + block(':root[data-theme="system"]', THEMES["dark"], "  ") + "}\n")
    return "\n".join(parts)


# ---------- Extensión de Firefox: mismas paletas, con los nombres de su CSS (EXTENSION PANEL/ui.css) ----------
EXT = ROOT / "EXTENSION PANEL"


def mix(a: str, b: str, t: float) -> str:
    """Color entre a y b (t = proporción de b), en hex."""
    ra, rb = rgb(a), rgb(b)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ra, rb))


def ext_tokens(t: dict) -> list[str]:
    dark = t["dark"]
    return [
        f"color-scheme: {'dark' if dark else 'light'};",
        f"--bg: {t['elev']}; --field: {t['sunken'] if dark else t['bg']}; --control: {mix(t['elev'], t['text'], 0.1)};",
        f"--border: {mix(t['elev'], t['text'], 0.2)}; --border-strong: {mix(t['elev'], t['text'], 0.32)};",
        f"--text: {t['text']}; --text-2: {t['text2']}; --text-3: {t['text3']}; --placeholder: {t['text3']};",
        f"--accent: {t['accent_fill']}; --accent-hover: {t['accent_hover']}; --on-accent: {t['on_accent']}; --link: {t['accent']};",
        f"--success: {t['success']}; --warning: {t['warning']}; --danger: {t['danger']};",
        f"--tile-fg: {t['tile_fg']}; --tile-inbox: {tile(t, 'inbox')}; --tile-baul: {tile(t, 'baul')}; --tile-grafo: {tile(t, 'grafo')};",
    ]


def tile(t: dict, name: str) -> str:
    from core.themes import TILES
    return t["tiles"][TILES.index(name)]


def ext_build() -> str:
    def blk(sel, t, ind=""):
        return f"{ind}{sel} {{\n" + "\n".join(f"{ind}  {x}" for x in ext_tokens(t)) + f"\n{ind}}}\n"
    parts = ["/* Generado por `python -m scripts.themes` — no editar a mano. Temas de la extensión (los mismos del Panel). */\n"]
    for name, t in THEMES.items():
        sel = f':root[data-theme="{name}"]'
        parts.append(f"/* {t['label']} */\n" + blk(f":root, {sel}" if name == DEFAULT else sel, t))
    parts.append(blk(':root[data-theme="system"]', THEMES["light"]))
    parts.append("@media (prefers-color-scheme: dark) {\n" + blk(':root[data-theme="system"]', THEMES["dark"], "  ") + "}\n")
    return "\n".join(parts)


def ext_list() -> str:
    from core.themes import CHOICES, preview
    items = [{"key": k, "label": label, "preview": preview(k)} for k, label in CHOICES]
    return ("/* Generado por `python -m scripts.themes`: temas para la página de opciones. */\n"
            f"self.PANEL_THEMES = {json.dumps(items, ensure_ascii=False, indent=2)};\n")


def main() -> int:
    OUT.write_text(build(), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(THEMES)} temas + sistema")
    (EXT / "themes.css").write_text(ext_build(), encoding="utf-8")
    (EXT / "lib" / "themes.js").write_text(ext_list(), encoding="utf-8")
    print("EXTENSION PANEL/themes.css y lib/themes.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
