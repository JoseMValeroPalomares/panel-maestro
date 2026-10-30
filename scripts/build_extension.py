"""
Construye la extensión de Firefox (`EXTENSION PANEL/`).

    python -m scripts.build_extension            # regenera el sprite de iconos y crea dist/panel-firefox-<versión>.xpi
    python -m scripts.build_extension --solo-iconos

El .xpi es un zip con los archivos de la extensión (sin README ni archivos ocultos). Firefox normal solo
instala complementos firmados: para uso propio, súbelo como «no listado» en addons.mozilla.org (te lo firman
sin publicarlo) o cárgalo temporalmente desde about:debugging. Ver `EXTENSION PANEL/README.md`.
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "EXTENSION PANEL"
LUCIDE = ROOT / "node_modules" / "lucide-static" / "icons"
ICONS = ["inbox", "library", "square-check", "lightbulb", "settings", "external-link", "flag", "tag", "link",
         "check", "x", "wifi-off", "cloud-upload", "circle-alert", "key-round", "eye", "eye-off", "plug",
         "send", "globe", "clock", "calendar", "calendar-plus", "repeat", "circle", "circle-check", "arrow-right",
         "corner-down-right", "refresh-cw"]
SKIP = {"README.md"}


def build_sprite() -> None:
    symbols, missing = [], []
    for name in ICONS:
        f = LUCIDE / f"{name}.svg"
        if not f.exists():
            missing.append(name)
            continue
        inner = re.sub(r"<!--[\s\S]*?-->", "", f.read_text(encoding="utf-8"))
        inner = re.sub(r"^[\s\S]*?<svg[^>]*>", "", inner)
        inner = re.sub(r"</svg>\s*$", "", inner).strip()
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{" ".join(inner.split())}</symbol>')
    if missing:
        sys.exit("Iconos inexistentes en Lucide: " + ", ".join(missing))
    (EXT / "icons.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" fill="none" stroke="currentColor" '
        'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">\n' + "\n".join(symbols) + "\n</svg>\n",
        encoding="utf-8")
    print(f"Sprite: {len(symbols)} iconos en EXTENSION PANEL/icons.svg")


def build_xpi() -> Path:
    version = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))["version"]
    out = ROOT / "dist" / f"panel-firefox-{version}.xpi"
    out.parent.mkdir(exist_ok=True)
    files = sorted(p for p in EXT.rglob("*") if p.is_file() and p.name not in SKIP
                   and not any(part.startswith(".") for part in p.relative_to(EXT).parts))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(EXT).as_posix())
    print(f"{out.relative_to(ROOT)}: {len(files)} archivos")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--solo-iconos", action="store_true", help="solo regenera el sprite de iconos")
    args = parser.parse_args()
    if LUCIDE.exists():
        build_sprite()
    elif not (EXT / "icons.svg").exists():
        sys.exit("Falta node_modules/lucide-static: ejecuta npm install")
    if not args.solo_iconos:
        build_xpi()
    return 0


if __name__ == "__main__":
    sys.exit(main())
