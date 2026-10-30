#!/usr/bin/env python3
"""
Genera src/gfx/fonts_data.h: la fuente Inter del panel (static/fonts) convertida
a mapas de bits suavizados de 4 bits por píxel para la pantalla del ESP32.

    python3 esp32_deskclock/tools/make_fonts.py

Cada fuente lleva ASCII, Latin-1 (tildes, ñ, ¿, ¡, º…) y unos pocos signos
tipográficos (… — « » “ ” • €). Las de números solo llevan dígitos y «:», con
avance fijo (cifras tabulares) para que la hora no baile al cambiar.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
WOFF = ROOT / "static" / "fonts" / "inter-latin-wght-normal.woff2"
OUT = Path(__file__).resolve().parents[1] / "src" / "gfx" / "fonts_data.h"

TEXT_CHARS = ([chr(c) for c in range(0x20, 0x7F)] + [chr(c) for c in range(0xA0, 0x100)]
              + list("–—‘’“”•…€←→↑↓›✓"))
DIGITS = list("0123456789:. -")

# nombre, tamaño (px de em), grosor, juego de caracteres, cifras tabulares
FONTS = [
    ("small", 13, 500, TEXT_CHARS, False),
    ("body", 16, 450, TEXT_CHARS, False),
    ("label", 15, 620, TEXT_CHARS, False),
    ("title", 22, 650, TEXT_CHARS, False),
    ("num", 40, 560, DIGITS, True),
    ("clock", 96, 560, DIGITS, True),
]


def missing_mask(font):
    """Máscara del glifo .notdef, para detectar caracteres que la fuente no tiene."""
    return render(font, chr(0xE000))[4]


def render(font, ch):
    l, t, r, b = font.getbbox(ch)
    w, h = max(0, r - l), max(0, b - t)
    if not w or not h:
        return l, t, 0, 0, b""
    img = Image.new("L", (w, h), 0)
    ImageDraw.Draw(img).text((-l, -t), ch, font=font, fill=255)
    return l, t, w, h, img.tobytes()


def pack4(alpha: bytes) -> bytes:
    out = bytearray((len(alpha) + 1) // 2)
    for i, a in enumerate(alpha):
        v = (a * 15 + 127) // 255
        out[i >> 1] |= (v << 4) if i % 2 == 0 else v
    return bytes(out)


def build(name, size, weight, chars, tabular):
    font = ImageFont.truetype(str(WOFF), size)
    font.set_variation_by_axes([weight])
    ascent, descent = font.getmetrics()
    notdef = missing_mask(font)
    glyphs, bits = [], bytearray()
    digit_adv = max(font.getlength(d) for d in "0123456789") if tabular else 0
    for ch in sorted(set(chars), key=ord):
        if ch != " " and render(font, ch)[4] == notdef:
            continue  # la fuente no lo tiene: el ESP32 pintará el sustituto
        x, y, w, h, alpha = render(font, ch)
        adv = font.getlength(ch)
        if tabular and ch.isdigit():
            x += round((digit_adv - adv) / 2)
            adv = digit_adv
        assert w < 256 and h < 256
        glyphs.append((ord(ch), len(bits), w, h, x, y, round(adv)))
        bits += pack4(alpha)
    return {"name": name, "ascent": ascent, "descent": descent, "glyphs": glyphs, "bits": bytes(bits)}


def emit(fonts) -> str:
    lines = ["// Generado por tools/make_fonts.py a partir de Inter (static/fonts del panel). No editar a mano.",
             "#pragma once", '#include "font.h"', ""]
    for f in fonts:
        n = f["name"]
        data = f["bits"]
        lines.append(f"static const uint8_t font_{n}_bits[] = {{")
        for i in range(0, len(data), 24):
            lines.append("  " + ",".join(str(b) for b in data[i:i + 24]) + ",")
        lines.append("};")
        lines.append(f"static const Glyph font_{n}_glyphs[] = {{")
        for g in f["glyphs"]:
            lines.append("  {%d,%d,%d,%d,%d,%d,%d}," % g)
        lines.append("};")
        lines.append(f"const Font FONT_{n.upper()} = {{ font_{n}_glyphs, font_{n}_bits, {len(f['glyphs'])}, "
                     f"{f['ascent']}, {f['descent']} }};")
        lines.append("")
    return "\n".join(lines)


def main():
    fonts = [build(*spec) for spec in FONTS]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(emit(fonts), encoding="utf-8")
    total = sum(len(f["bits"]) + 12 * len(f["glyphs"]) for f in fonts)
    for f in fonts:
        print(f"{f['name']:6} {len(f['glyphs']):3} glifos  {len(f['bits']) / 1024:6.1f} KB  "
              f"ascent {f['ascent']} descent {f['descent']}")
    print(f"Total ≈ {total / 1024:.1f} KB de flash → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
