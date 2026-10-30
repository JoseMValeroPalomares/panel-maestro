#include "font.h"

#include <string.h>

#include "fonts_data.h"

uint32_t utf8Next(const char*& p) {
  const uint8_t c = (uint8_t)*p;
  if (!c) return 0;
  int extra = c < 0x80 ? 0 : (c >> 5) == 6 ? 1 : (c >> 4) == 14 ? 2 : (c >> 3) == 30 ? 3 : -1;
  if (extra < 0) { p++; return 0xFFFD; }
  uint32_t cp = extra == 0 ? c : extra == 1 ? (c & 0x1F) : extra == 2 ? (c & 0x0F) : (c & 0x07);
  p++;
  for (int i = 0; i < extra; i++) {
    const uint8_t n = (uint8_t)*p;
    if ((n & 0xC0) != 0x80) return 0xFFFD;
    cp = (cp << 6) | (n & 0x3F);
    p++;
  }
  return cp;
}

static const Glyph* findExact(const Font& f, uint32_t cp) {
  int lo = 0, hi = f.count - 1;
  while (lo <= hi) {
    const int mid = (lo + hi) / 2;
    if (f.glyphs[mid].cp == cp) return &f.glyphs[mid];
    if (f.glyphs[mid].cp < cp) lo = mid + 1; else hi = mid - 1;
  }
  return nullptr;
}

// Sustitutos para lo que no está en la fuente (o en las fuentes de solo números)
static uint32_t fallback(uint32_t cp) {
  static const char* const FROM = "ÀÁÂÃÄÅàáâãäåÈÉÊËèéêëÌÍÎÏìíîïÒÓÔÕÖòóôõöÙÚÛÜùúûüÇçÑñÝýÿ";
  static const char TO[] = "AAAAAAaaaaaaEEEEeeeeIIIIiiiiOOOOOoooooUUUUuuuuCcNnYyy";
  const char* p = FROM;
  for (int i = 0; *p; i++) {
    if (utf8Next(p) == cp) return (uint8_t)TO[i];
  }
  switch (cp) {
    case 0x2018: case 0x2019: return '\'';
    case 0x201C: case 0x201D: case 0xAB: case 0xBB: return '"';
    case 0x2013: case 0x2014: return '-';
    case 0x2026: return '.';
    case 0x2248: case 0x223C: return '~';
    case 0x207A: return '+';
    case 0x207B: case 0x2212: return '-';
    case 0x00D7: case 0x2715: return 'x';
    case 0x2192: return '>';
    case 0x2190: return '<';
    case 0x00A0: case 0x2009: case 0x202F: return ' ';
    default: return '?';
  }
}

const Glyph* fontGlyph(const Font& f, uint32_t cp) {
  const Glyph* g = findExact(f, cp);
  if (g) return g;
  if (cp == '\t') cp = ' ';
  g = findExact(f, fallback(cp));
  return g ? g : findExact(f, '?');
}

int textWidth(const Font& f, const char* s, size_t maxBytes) {
  int w = 0;
  const char* end = maxBytes == (size_t)-1 ? nullptr : s + maxBytes;
  while (*s && (!end || s < end)) {
    const uint32_t cp = utf8Next(s);
    if (cp == '\n') continue;
    const Glyph* g = fontGlyph(f, cp);
    if (g) w += g->adv;
  }
  return w;
}

static const char ELLIPSIS[] = "\xE2\x80\xA6";  // «…»

// Prefijo de s (len bytes) que cabe junto con «…» en maxW, seguido de «…»
static void cutWithDots(const Font& f, const char* s, size_t len, int maxW, char* out, size_t outSize) {
  const int ellW = textWidth(f, ELLIPSIS);
  const char* p = s;
  const char* fit = s;
  int w = 0;
  while (*p && p < s + len) {
    const Glyph* g = fontGlyph(f, utf8Next(p));
    const int adv = g ? g->adv : 0;
    if (w + adv + ellW > maxW) break;
    w += adv;
    fit = p;
  }
  size_t n = (size_t)(fit - s);
  while (n && s[n - 1] == ' ') n--;  // sin espacio antes de los puntos
  if (n + sizeof(ELLIPSIS) > outSize) n = outSize - sizeof(ELLIPSIS);
  memcpy(out, s, n);
  memcpy(out + n, ELLIPSIS, sizeof(ELLIPSIS));
}

void ellipsize(const Font& f, const char* s, int maxW, char* out, size_t outSize) {
  if (!outSize) return;
  if (textWidth(f, s) <= maxW) {
    strncpy(out, s, outSize - 1);
    out[outSize - 1] = 0;
    return;
  }
  cutWithDots(f, s, strlen(s), maxW, out, outSize);
}

int wrapText(const Font& f, const char* s, int maxW, TextLine* lines, int maxLines, char* tail, size_t tailSize) {
  int n = 0;
  const char* p = s;
  while (*p && n < maxLines) {
    while (*p == ' ') p++;
    if (!*p) break;
    const char* lineStart = p;
    const char* lastBreak = nullptr;  // fin de la última palabra que cabe
    const char* q = p;
    int w = 0;
    bool overflow = false;
    while (*q) {
      if (*q == '\n') { lastBreak = q; break; }
      const char* before = q;
      const Glyph* g = fontGlyph(f, utf8Next(q));
      const int adv = g ? g->adv : 0;
      if (w + adv > maxW) {
        overflow = true;
        if (!lastBreak) lastBreak = before > lineStart ? before : q;  // palabra más larga que la línea
        break;
      }
      w += adv;
      if (*q == ' ' || *q == '\n') lastBreak = q;
    }
    if (!overflow && !*q) lastBreak = q;
    lines[n].start = lineStart;
    lines[n].len = (size_t)(lastBreak - lineStart);
    while (lines[n].len && lineStart[lines[n].len - 1] == ' ') lines[n].len--;
    n++;
    p = lastBreak;
    if (*p == '\n') p++;
  }
  while (*p == ' ' || *p == '\n') p++;
  if (*p && n > 0 && tail && tailSize > sizeof(ELLIPSIS)) {
    // Queda texto sin mostrar: la última línea termina en «…»
    TextLine& last = lines[n - 1];
    cutWithDots(f, last.start, last.len, maxW, tail, tailSize);
    last.start = tail;
    last.len = strlen(tail);
  }
  return n;
}
