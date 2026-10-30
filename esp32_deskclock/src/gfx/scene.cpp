#include "scene.h"

#include <math.h>
#include <string.h>

// ─────────────────────────────────────────────
// Rect
// ─────────────────────────────────────────────
Rect Rect::intersect(const Rect& o) const {
  const int x0 = x > o.x ? x : o.x, y0 = y > o.y ? y : o.y;
  const int x1 = right() < o.right() ? right() : o.right();
  const int y1 = bottom() < o.bottom() ? bottom() : o.bottom();
  return Rect{(int16_t)x0, (int16_t)y0, (int16_t)(x1 - x0), (int16_t)(y1 - y0)};
}

Rect Rect::unite(const Rect& o) const {
  if (empty()) return o;
  if (o.empty()) return *this;
  const int x0 = x < o.x ? x : o.x, y0 = y < o.y ? y : o.y;
  const int x1 = right() > o.right() ? right() : o.right();
  const int y1 = bottom() > o.bottom() ? bottom() : o.bottom();
  return Rect{(int16_t)x0, (int16_t)y0, (int16_t)(x1 - x0), (int16_t)(y1 - y0)};
}

static const Rect SCREEN = {0, 0, SCREEN_WIDTH, SCREEN_HEIGHT};

// ─────────────────────────────────────────────
// Huella (FNV-1a) de cada elemento, para saber qué ha cambiado
// ─────────────────────────────────────────────
static uint32_t fnv(uint32_t h, const void* data, size_t n) {
  const uint8_t* p = (const uint8_t*)data;
  for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 16777619u; }
  return h;
}

// ─────────────────────────────────────────────
// Construcción
// ─────────────────────────────────────────────
void Scene::reset(uint16_t baseColor) {
  count_ = glyphCount_ = 0;
  overflow_ = false;
  baseColor_ = baseColor;
  baseFn_ = nullptr;
  baseCtx_ = nullptr;
}

Prim& Scene::add(Prim::Kind k, const Rect& box) {
  static Prim dummy;
  if (count_ >= MAX_PRIMS) { overflow_ = true; memset(&dummy, 0, sizeof dummy); return dummy; }
  Prim& p = prims_[count_++];
  memset(&p, 0, sizeof p);
  p.kind = k;
  p.alpha = 255;
  p.box = box;
  return p;
}

void Scene::finish(Prim& p) {
  uint32_t h = 2166136261u;
  h = fnv(h, &p.kind, 1); h = fnv(h, &p.alpha, 1); h = fnv(h, &p.box, sizeof p.box);
  h = fnv(h, &p.color, 2); h = fnv(h, &p.color2, 2); h = fnv(h, &p.radius, 1); h = fnv(h, &p.border, 1);
  h = fnv(h, &p.flags, 1); h = fnv(h, &p.cx, 2); h = fnv(h, &p.cy, 2); h = fnv(h, &p.rOuter, 2);
  h = fnv(h, &p.rInner, 2); h = fnv(h, &p.a0, 2); h = fnv(h, &p.a1, 2);
  h = fnv(h, &p.img, sizeof p.img); h = fnv(h, &p.version, 4); h = fnv(h, &p.scale, 1);
  for (int i = 0; i < p.glyphCount; i++) h = fnv(h, &glyphs_[p.glyphStart + i], sizeof(PlacedGlyph));
  p.hash = h;
}

void Scene::rect(int x, int y, int w, int h, int r, uint16_t color, uint8_t alpha) {
  if (w <= 0 || h <= 0 || !alpha) return;
  Prim& p = add(Prim::RECT, Rect{(int16_t)x, (int16_t)y, (int16_t)w, (int16_t)h});
  p.color = color;
  p.alpha = alpha;
  p.radius = (uint8_t)(r * 2 > w ? w / 2 : r * 2 > h ? h / 2 : r);
  finish(p);
}

void Scene::stroke(int x, int y, int w, int h, int r, uint16_t color, int width, uint8_t alpha) {
  if (w <= 0 || h <= 0) return;
  Prim& p = add(Prim::RECT, Rect{(int16_t)x, (int16_t)y, (int16_t)w, (int16_t)h});
  p.color = color;
  p.alpha = alpha;
  p.border = (uint8_t)width;
  p.radius = (uint8_t)(r * 2 > w ? w / 2 : r * 2 > h ? h / 2 : r);
  finish(p);
}

void Scene::gradient(int x, int y, int w, int h, uint16_t top, uint16_t bottom, int r) {
  if (w <= 0 || h <= 0) return;
  Prim& p = add(Prim::RECT, Rect{(int16_t)x, (int16_t)y, (int16_t)w, (int16_t)h});
  p.color = top;
  p.color2 = bottom;
  p.flags = GRADIENT;
  p.radius = (uint8_t)r;
  finish(p);
}

int Scene::text(int x, int y, const Font& f, uint16_t color, const char* s, Align align, size_t len) {
  if (!s) return 0;
  const int w = textWidth(f, s, len);
  if (align == ALIGN_CENTER) x -= w / 2;
  else if (align == ALIGN_RIGHT) x -= w;
  Prim& p = add(Prim::TEXT, Rect{(int16_t)x, (int16_t)y, (int16_t)w, (int16_t)f.lineHeight()});
  p.color = color;
  p.font = &f;
  p.glyphStart = (uint16_t)glyphCount_;
  const char* end = len == (size_t)-1 ? nullptr : s + len;
  int cx = x;
  Rect ink = p.box;
  while (*s && (!end || s < end)) {
    const uint32_t cp = utf8Next(s);
    if (cp == '\n') continue;
    const Glyph* g = fontGlyph(f, cp);
    if (!g) continue;
    if (g->w && g->h) {
      if (glyphCount_ >= MAX_GLYPHS) { overflow_ = true; break; }
      PlacedGlyph& pg = glyphs_[glyphCount_++];
      pg.g = g;
      pg.x = (int16_t)(cx + g->x);
      pg.y = (int16_t)(y + g->y);
      ink = ink.unite(Rect{pg.x, pg.y, (int16_t)g->w, (int16_t)g->h});
    }
    cx += g->adv;
  }
  p.glyphCount = (uint16_t)(glyphCount_ - p.glyphStart);
  p.box = ink;  // incluye lo que asoma fuera de la caja de la línea (acentos, «g»)
  finish(p);
  return w;
}

int Scene::textFit(int x, int y, int maxW, const Font& f, uint16_t color, const char* s, Align align) {
  char buf[200];
  ellipsize(f, s ? s : "", maxW, buf, sizeof buf);
  return text(x, y, f, color, buf, align);
}

int Scene::paragraph(int x, int y, int maxW, const Font& f, uint16_t color, const char* s, int maxLines, int lineGap,
                     Align align) {
  TextLine lines[12];
  char tail[200];
  if (maxLines > 12) maxLines = 12;
  const int n = wrapText(f, s ? s : "", maxW, lines, maxLines, tail, sizeof tail);
  const int lh = f.lineHeight() + lineGap;
  const int ax = align == ALIGN_CENTER ? x + maxW / 2 : align == ALIGN_RIGHT ? x + maxW : x;
  for (int i = 0; i < n; i++) text(ax, y + i * lh, f, color, lines[i].start, align, lines[i].len);
  return n * lh;
}

void Scene::arc(int cx, int cy, int rOuter, int thickness, int startDeg, int endDeg, uint16_t color, bool roundCaps) {
  if (endDeg <= startDeg) return;
  Prim& p = add(Prim::ARC, Rect{(int16_t)(cx - rOuter - 1), (int16_t)(cy - rOuter - 1), (int16_t)(2 * rOuter + 2),
                                (int16_t)(2 * rOuter + 2)});
  p.color = color;
  p.cx = (int16_t)cx; p.cy = (int16_t)cy;
  p.rOuter = (int16_t)rOuter; p.rInner = (int16_t)(rOuter - thickness);
  p.a0 = (int16_t)startDeg; p.a1 = (int16_t)endDeg;
  p.flags = roundCaps && endDeg - startDeg < 360 ? ROUND_CAPS : 0;
  finish(p);
}

void Scene::line(float x0, float y0, float x1, float y1, float width, uint16_t color) {
  const float h = width / 2 + 1;
  const int bx = (int)floorf(fminf(x0, x1) - h), by = (int)floorf(fminf(y0, y1) - h);
  const int bw = (int)ceilf(fmaxf(x0, x1) + h) - bx, bh = (int)ceilf(fmaxf(y0, y1) + h) - by;
  Prim& p = add(Prim::LINE, Rect{(int16_t)bx, (int16_t)by, (int16_t)bw, (int16_t)bh});
  p.color = color;
  p.cx = (int16_t)lroundf(x0 * 16); p.cy = (int16_t)lroundf(y0 * 16);
  p.rOuter = (int16_t)lroundf(x1 * 16); p.rInner = (int16_t)lroundf(y1 * 16);
  p.a0 = (int16_t)lroundf(width * 16);
  finish(p);
}

void Scene::image(int x, int y, const uint8_t* rgb, int w, int h, int scale, int radius, uint32_t version) {
  if (!rgb || w <= 0 || h <= 0) return;
  Prim& p = add(Prim::IMAGE, Rect{(int16_t)x, (int16_t)y, (int16_t)(w * scale), (int16_t)(h * scale)});
  p.img = rgb;
  p.imgW = (uint16_t)w; p.imgH = (uint16_t)h;
  p.scale = (uint8_t)scale;
  p.radius = (uint8_t)radius;
  p.version = version;
  finish(p);
}

// ─────────────────────────────────────────────
// Cobertura suavizada (0-255) de un rectángulo redondeado en el centro del píxel
// ─────────────────────────────────────────────
static inline uint8_t roundRectCoverage(const Rect& b, int r, int px, int py) {
  if (r <= 0) return 255;
  const float fx = px + 0.5f, fy = py + 0.5f;
  float dx = 0, dy = 0;
  if (fx < b.x + r) dx = b.x + r - fx; else if (fx > b.right() - r) dx = fx - (b.right() - r);
  if (fy < b.y + r) dy = b.y + r - fy; else if (fy > b.bottom() - r) dy = fy - (b.bottom() - r);
  if (dx == 0 || dy == 0) return 255;
  const float d = sqrtf(dx * dx + dy * dy);
  const float c = r - d + 0.5f;
  return c >= 1 ? 255 : c <= 0 ? 0 : (uint8_t)(c * 255);
}

static inline uint8_t mul8(uint8_t a, uint8_t b) { return (uint8_t)((a * b + 127) / 255); }

static void drawRect(const Prim& p, uint16_t* buf, const Rect& strip, const Rect& area) {
  const Rect inner = {(int16_t)(p.box.x + p.border), (int16_t)(p.box.y + p.border), (int16_t)(p.box.w - 2 * p.border),
                      (int16_t)(p.box.h - 2 * p.border)};
  const int ri = p.radius > p.border ? p.radius - p.border : 0;
  for (int y = area.y; y < area.bottom(); y++) {
    uint16_t color = p.color;
    if (p.flags & Scene::GRADIENT) {
      const int t = p.box.h > 1 ? (y - p.box.y) * 255 / (p.box.h - 1) : 0;
      color = blend565(p.color, p.color2, (uint8_t)t);
    }
    uint16_t* row = buf + (y - strip.y) * strip.w;
    const bool cornerRow = y < p.box.y + p.radius || y >= p.box.bottom() - p.radius;
    for (int x = area.x; x < area.right(); x++) {
      uint8_t a;
      const bool edgeCol = x < p.box.x + p.radius || x >= p.box.right() - p.radius;
      a = (cornerRow && edgeCol) ? roundRectCoverage(p.box, p.radius, x, y) : 255;
      if (p.border && a) {
        uint8_t in = 0;
        if (x >= inner.x && x < inner.right() && y >= inner.y && y < inner.bottom()) {
          in = roundRectCoverage(inner, ri, x, y);
        }
        a = a > in ? a - in : 0;
      }
      if (!a) continue;
      if (p.alpha != 255) a = mul8(a, p.alpha);
      uint16_t& d = row[x - strip.x];
      d = blend565(d, color, a);
    }
  }
}

static void drawArc(const Prim& p, uint16_t* buf, const Rect& strip, const Rect& area) {
  const float ro = p.rOuter, ri = p.rInner;
  const float rm = (ro + ri) / 2, half = (ro - ri) / 2;
  const bool fullCircle = p.a1 - p.a0 >= 360;
  const float a0 = p.a0 * (float)M_PI / 180, a1 = p.a1 * (float)M_PI / 180;
  // extremos (para las puntas redondeadas)
  const float e0x = p.cx + rm * sinf(a0), e0y = p.cy - rm * cosf(a0);
  const float e1x = p.cx + rm * sinf(a1), e1y = p.cy - rm * cosf(a1);
  for (int y = area.y; y < area.bottom(); y++) {
    uint16_t* row = buf + (y - strip.y) * strip.w;
    const float fy = y + 0.5f - p.cy;
    for (int x = area.x; x < area.right(); x++) {
      const float fx = x + 0.5f - p.cx;
      const float d = sqrtf(fx * fx + fy * fy);
      if (d > ro + 1 || d < ri - 1) continue;
      float cov = fminf(ro - d + 0.5f, d - ri + 0.5f);
      if (cov <= 0) continue;
      if (cov > 1) cov = 1;
      if (!fullCircle) {
        float ang = atan2f(fx, -fy);
        if (ang < 0) ang += 2 * (float)M_PI;
        // También vale el mismo ángulo una vuelta después (arcos que pasan por las 12)
        const bool inside = (ang >= a0 && ang <= a1) || (ang + 2 * (float)M_PI >= a0 && ang + 2 * (float)M_PI <= a1);
        if (!inside) {
          float capCov = 0;
          if (p.flags & Scene::ROUND_CAPS) {
            const float d0 = sqrtf((x + 0.5f - e0x) * (x + 0.5f - e0x) + (y + 0.5f - e0y) * (y + 0.5f - e0y));
            const float d1 = sqrtf((x + 0.5f - e1x) * (x + 0.5f - e1x) + (y + 0.5f - e1y) * (y + 0.5f - e1y));
            capCov = fmaxf(half - d0 + 0.5f, half - d1 + 0.5f);
            if (capCov > 1) capCov = 1;
          } else {
            // borde recto suavizado: distancia a los dos radios límite
            const float s0 = fabsf(fx * cosf(a0) + fy * sinf(a0));
            const float s1 = fabsf(fx * cosf(a1) + fy * sinf(a1));
            capCov = 0.5f - fminf(s0, s1);
          }
          if (capCov <= 0) continue;
          cov = fminf(cov, capCov);
        }
      }
      uint16_t& dst = row[x - strip.x];
      dst = blend565(dst, p.color, (uint8_t)(cov * 255));
    }
  }
}

static void drawLine(const Prim& p, uint16_t* buf, const Rect& strip, const Rect& area) {
  const float x0 = p.cx / 16.f, y0 = p.cy / 16.f, x1 = p.rOuter / 16.f, y1 = p.rInner / 16.f, hw = p.a0 / 32.f;
  const float dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy;
  for (int y = area.y; y < area.bottom(); y++) {
    uint16_t* row = buf + (y - strip.y) * strip.w;
    for (int x = area.x; x < area.right(); x++) {
      const float px = x + 0.5f - x0, py = y + 0.5f - y0;
      float t = len2 > 0 ? (px * dx + py * dy) / len2 : 0;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
      const float ex = px - t * dx, ey = py - t * dy;
      const float c = hw - sqrtf(ex * ex + ey * ey) + 0.5f;
      if (c <= 0) continue;
      uint16_t& d = row[x - strip.x];
      d = blend565(d, p.color, c >= 1 ? 255 : (uint8_t)(c * 255));
    }
  }
}

static void drawText(const Prim& p, const PlacedGlyph* glyphs, uint16_t* buf, const Rect& strip, const Rect& clip) {
  const uint8_t* bits = p.font->bits;
  for (int i = 0; i < p.glyphCount; i++) {
    const PlacedGlyph& pg = glyphs[p.glyphStart + i];
    const Glyph& g = *pg.g;
    const Rect gb = {pg.x, pg.y, (int16_t)g.w, (int16_t)g.h};
    if (!gb.intersects(clip)) continue;
    const Rect a = gb.intersect(clip);
    for (int y = a.y; y < a.bottom(); y++) {
      uint16_t* row = buf + (y - strip.y) * strip.w;
      const uint32_t base = (uint32_t)(y - pg.y) * g.w;
      for (int x = a.x; x < a.right(); x++) {
        const uint32_t idx = base + (uint32_t)(x - pg.x);
        const uint8_t byte = bits[g.offset + (idx >> 1)];
        const uint8_t nib = (idx & 1) ? (byte & 0x0F) : (byte >> 4);
        if (!nib) continue;
        uint16_t& d = row[x - strip.x];
        d = blend565(d, p.color, (uint8_t)(nib * 17));
      }
    }
  }
}

static void drawImage(const Prim& p, uint16_t* buf, const Rect& strip, const Rect& area) {
  for (int y = area.y; y < area.bottom(); y++) {
    uint16_t* row = buf + (y - strip.y) * strip.w;
    const int sy = (y - p.box.y) / p.scale;
    const uint8_t* src = p.img + (size_t)sy * p.imgW * 2;
    const bool cornerRow = p.radius && (y < p.box.y + p.radius || y >= p.box.bottom() - p.radius);
    for (int x = area.x; x < area.right(); x++) {
      const int sx = (x - p.box.x) / p.scale;
      const uint16_t c = (uint16_t)((src[sx * 2] << 8) | src[sx * 2 + 1]);
      uint8_t a = 255;
      if (cornerRow && (x < p.box.x + p.radius || x >= p.box.right() - p.radius)) a = roundRectCoverage(p.box, p.radius, x, y);
      uint16_t& d = row[x - strip.x];
      d = blend565(d, c, a);
    }
  }
}

// ─────────────────────────────────────────────
// Composición
// ─────────────────────────────────────────────
void Scene::renderStrip(uint16_t* buf, const Rect& strip) const {
  for (int y = 0; y < strip.h; y++) {
    uint16_t* row = buf + y * strip.w;
    if (baseFn_) baseFn_(strip.y + y, strip.x, strip.w, row, baseCtx_);
    else for (int x = 0; x < strip.w; x++) row[x] = baseColor_;
  }
  for (int i = 0; i < count_; i++) {
    const Prim& p = prims_[i];
    if (!p.box.intersects(strip)) continue;
    const Rect area = p.box.intersect(strip);
    switch (p.kind) {
      case Prim::RECT: drawRect(p, buf, strip, area); break;
      case Prim::ARC: drawArc(p, buf, strip, area); break;
      case Prim::TEXT: drawText(p, glyphs_, buf, strip, strip); break;
      case Prim::IMAGE: drawImage(p, buf, strip, area); break;
      case Prim::LINE: drawLine(p, buf, strip, area); break;
    }
  }
}

void Scene::render(Canvas& canvas, const Rect& clipIn) const {
  const Rect clip = clipIn.intersect(SCREEN);
  if (clip.empty()) return;
  constexpr int STRIP_H = 8;
  static uint16_t buf[SCREEN_WIDTH * STRIP_H];
  for (int y = clip.y; y < clip.bottom(); y += STRIP_H) {
    const int h = clip.bottom() - y < STRIP_H ? clip.bottom() - y : STRIP_H;
    const Rect strip = {clip.x, (int16_t)y, clip.w, (int16_t)h};
    renderStrip(buf, strip);
    canvas.pushRows(strip.x, strip.y, strip.w, strip.h, buf);
  }
}

// ─────────────────────────────────────────────
// Diferencias con la escena anterior
// ─────────────────────────────────────────────
static void addDirty(Rect* rects, int& n, Rect r) {
  r = r.intersect(SCREEN);
  if (r.empty()) return;
  // se funde con uno que toque; si no caben más, con el más cercano
  for (int i = 0; i < n; i++) {
    const Rect grown = {(int16_t)(rects[i].x - 4), (int16_t)(rects[i].y - 4), (int16_t)(rects[i].w + 8), (int16_t)(rects[i].h + 8)};
    if (grown.intersects(r)) { rects[i] = rects[i].unite(r); return; }
  }
  if (n < SceneDiff::MAX_RECTS) { rects[n++] = r; return; }
  rects[n - 1] = rects[n - 1].unite(r);
}

int SceneDiff::diff(const Scene& s, Rect* out) {
  int n = 0;
  if (!valid_ || s.baseColor() != prevBase_ || s.full()) {
    out[n++] = SCREEN;
  } else {
    const int common = s.count() < prevCount_ ? s.count() : prevCount_;
    for (int i = 0; i < common; i++) {
      if (s.prim(i).hash != prev_[i].hash) {
        addDirty(out, n, prev_[i].box);
        addDirty(out, n, s.prim(i).box);
      }
    }
    for (int i = common; i < prevCount_; i++) addDirty(out, n, prev_[i].box);
    for (int i = common; i < s.count(); i++) addDirty(out, n, s.prim(i).box);
    // Las uniones pueden solaparse tras fundirse: segunda pasada
    for (int pass = 0; pass < 2; pass++) {
      for (int i = 0; i < n; i++)
        for (int j = i + 1; j < n; j++)
          if (out[i].intersects(out[j])) { out[i] = out[i].unite(out[j]); out[j] = out[--n]; j = i; }
    }
    int area = 0;
    for (int i = 0; i < n; i++) area += out[i].w * out[i].h;
    if (area > SCREEN_WIDTH * SCREEN_HEIGHT * 6 / 10) { n = 1; out[0] = SCREEN; }
  }
  prevCount_ = s.count();
  prevBase_ = s.baseColor();
  for (int i = 0; i < s.count(); i++) prev_[i] = Entry{s.prim(i).hash, s.prim(i).box};
  valid_ = true;
  return n;
}
