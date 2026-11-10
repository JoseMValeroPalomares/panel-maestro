"""
Icono de la app: copia los SVG de assets/icons/app/ a static/icons/ y a la extensión, y genera los PNG de la PWA
(favicon 32, apple-touch 180, 192, 512 y enmascarable 512) con el Chromium de Playwright.

    python -m scripts.iconos_app

Necesita el Chromium que instala Playwright (~/.cache/ms-playwright) o la variable PLAYWRIGHT_CHROMIUM.
"""
import glob
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets" / "icons" / "app"
DST = ROOT / "static" / "icons"
EXT = ROOT / "EXTENSION PANEL" / "icons"

# (svg de origen, png de salida, tamaño). El apple-touch y el enmascarable van a sangre: el sistema pone su máscara.
PNGS = [
    ("favicon.svg", "favicon-32.png", 32),
    ("maskable.svg", "apple-touch-icon.png", 180),
    ("icon.svg", "icon-192.png", 192),
    ("icon.svg", "icon-512.png", 512),
    ("maskable.svg", "maskable-512.png", 512),
]


def _chromium() -> str:
    env = os.environ.get("PLAYWRIGHT_CHROMIUM")
    if env and os.path.exists(env):
        return env
    found = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")))
    if not found:
        raise SystemExit("No encuentro Chromium: instala el de Playwright o define PLAYWRIGHT_CHROMIUM")
    return found[-1]


def main() -> None:
    from playwright.sync_api import sync_playwright

    for name in ("icon.svg", "icon-claro.svg", "maskable.svg", "favicon.svg"):
        shutil.copyfile(SRC / name, DST / name)
    shutil.copyfile(SRC / "icon.svg", EXT / "icon.svg")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=_chromium())
        page = browser.new_page(device_scale_factor=1)
        for svg, png, size in PNGS:
            page.set_viewport_size({"width": size, "height": size})
            markup = (SRC / svg).read_text(encoding="utf-8").replace("<svg ", f'<svg width="{size}" height="{size}" ', 1)
            page.set_content(f'<html><body style="margin:0;background:transparent">{markup}</body></html>')
            page.screenshot(path=str(DST / png), omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
            print(f"static/icons/{png} ({size} px)")
        browser.close()
    print("SVG copiados a static/icons/ y a la extensión")


if __name__ == "__main__":
    main()
