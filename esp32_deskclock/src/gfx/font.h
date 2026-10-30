// Fuentes suavizadas (4 bits por píxel) generadas por tools/make_fonts.py y medición de texto UTF-8.
#pragma once
#include <stddef.h>
#include <stdint.h>

struct Glyph {
  uint32_t cp;       // punto de código Unicode
  uint32_t offset;   // primer byte del mapa de bits en Font::bits
  uint8_t w, h;      // tamaño del mapa de bits
  int16_t x, y;      // desplazamiento desde el cursor y desde la parte alta de la línea
  uint8_t adv;       // avance horizontal
};

struct Font {
  const Glyph* glyphs;   // ordenados por punto de código
  const uint8_t* bits;
  uint16_t count;
  uint8_t ascent, descent;
  int lineHeight() const { return ascent + descent; }
};

extern const Font FONT_SMALL, FONT_BODY, FONT_LABEL, FONT_TITLE, FONT_NUM, FONT_CLOCK;

// Decodifica el siguiente punto de código y avanza p (UTF-8 mal formado → U+FFFD)
uint32_t utf8Next(const char*& p);

// Glifo del punto de código; si la fuente no lo tiene, uno parecido (á→a, “→") o «?»
const Glyph* fontGlyph(const Font& f, uint32_t cp);

int textWidth(const Font& f, const char* s, size_t maxBytes = (size_t)-1);

// Parte el texto en líneas que caben en maxW px (por palabras; una palabra más larga
// que la línea se corta). Devuelve cuántas líneas ha llenado; si sobra texto, la
// última termina en «…». starts/lens señalan trozos del texto original, salvo la
// última recortada, que se copia en `tail` (tailSize bytes).
struct TextLine { const char* start; size_t len; };
int wrapText(const Font& f, const char* s, int maxW, TextLine* lines, int maxLines,
             char* tail, size_t tailSize);

// Recorta a una línea con «…» si no cabe (escribe en out)
void ellipsize(const Font& f, const char* s, int maxW, char* out, size_t outSize);
