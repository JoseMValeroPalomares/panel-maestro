// Escena y compositor por franjas.
//
// Cada pantalla describe lo que se ve (rectángulos redondeados, texto, arcos,
// imágenes) en una Scene; el compositor la pinta franja a franja en memoria y
// solo entonces la envía a la pantalla: nada se borra antes de dibujarse, así
// que no hay parpadeo, y los bordes salen suavizados. Comparando la escena con
// la anterior (diffScenes) solo se repintan los rectángulos que han cambiado.
#pragma once
#include <stddef.h>
#include <stdint.h>

#include "color.h"
#include "font.h"

constexpr int SCREEN_WIDTH = 320;
constexpr int SCREEN_HEIGHT = 240;

struct Rect {
  int16_t x, y, w, h;
  bool empty() const { return w <= 0 || h <= 0; }
  int right() const { return x + w; }
  int bottom() const { return y + h; }
  bool intersects(const Rect& o) const { return x < o.right() && o.x < right() && y < o.bottom() && o.y < bottom(); }
  Rect intersect(const Rect& o) const;
  Rect unite(const Rect& o) const;
};

// Destino de los píxeles: la pantalla (TFT_eSPI) o un búfer en el PC
class Canvas {
 public:
  virtual ~Canvas() {}
  virtual void pushRows(int x, int y, int w, int h, const uint16_t* px) = 0;
};

// Fondo bajo toda la escena: color liso o imagen (fondo personalizado)
typedef void (*BaseRowFn)(int y, int x, int w, uint16_t* out, void* ctx);

enum Align : uint8_t { ALIGN_LEFT, ALIGN_CENTER, ALIGN_RIGHT };

struct Prim {
  enum Kind : uint8_t { RECT, TEXT, ARC, IMAGE, LINE } kind;
  uint8_t alpha;
  Rect box;               // caja que ocupa (para recortar y para el diff)
  uint16_t color, color2; // relleno; borde (RECT con borde) o color inferior (degradado)
  uint8_t radius, border, flags;
  // TEXT
  const Font* font;
  uint16_t glyphStart, glyphCount;
  // ARC (grados desde las 12 en el sentido de las agujas); LINE usa cx,cy → rOuter,rInner (1/16 px) y a0 = grosor (1/16 px)
  int16_t cx, cy, rOuter, rInner, a0, a1;
  // IMAGE (RGB565 big-endian, ampliada scale veces)
  const uint8_t* img;
  uint16_t imgW, imgH;
  uint8_t scale;
  uint32_t version;       // cambia cuando cambia el contenido de img
  uint32_t hash;
};

struct PlacedGlyph {
  const Glyph* g;
  int16_t x, y;  // esquina superior izquierda del mapa de bits
};

class Scene {
 public:
  static constexpr int MAX_PRIMS = 220;
  static constexpr int MAX_GLYPHS = 1100;
  enum Flags : uint8_t { GRADIENT = 1, ROUND_CAPS = 2 };

  void reset(uint16_t baseColor);
  void setBase(BaseRowFn fn, void* ctx) { baseFn_ = fn; baseCtx_ = ctx; }

  void rect(int x, int y, int w, int h, int r, uint16_t color, uint8_t alpha = 255);
  void stroke(int x, int y, int w, int h, int r, uint16_t color, int width = 1, uint8_t alpha = 255);
  void gradient(int x, int y, int w, int h, uint16_t top, uint16_t bottom, int r = 0);
  // Una línea de texto con su caja en (x, y) = esquina superior; devuelve el ancho
  int text(int x, int y, const Font& f, uint16_t color, const char* s, Align align = ALIGN_LEFT, size_t len = (size_t)-1);
  // Texto ajustado a maxW en hasta maxLines líneas («…» si sobra); devuelve la altura usada
  int paragraph(int x, int y, int maxW, const Font& f, uint16_t color, const char* s, int maxLines, int lineGap = 0,
                Align align = ALIGN_LEFT);
  // Texto de una línea recortado con «…» a maxW
  int textFit(int x, int y, int maxW, const Font& f, uint16_t color, const char* s, Align align = ALIGN_LEFT);
  void arc(int cx, int cy, int rOuter, int thickness, int startDeg, int endDeg, uint16_t color, bool roundCaps = true);
  void circle(int cx, int cy, int r, uint16_t color) { rect(cx - r, cy - r, 2 * r, 2 * r, r, color); }
  // Segmento con extremos redondeados (iconos: flechas, marca de hecho)
  void line(float x0, float y0, float x1, float y1, float width, uint16_t color);
  void image(int x, int y, const uint8_t* rgb565be, int w, int h, int scale, int radius, uint32_t version);

  int count() const { return count_; }
  const Prim& prim(int i) const { return prims_[i]; }
  uint16_t baseColor() const { return baseColor_; }
  bool full() const { return overflow_; }

  void render(Canvas& canvas, const Rect& clip) const;

 private:
  Prim& add(Prim::Kind k, const Rect& box);
  void finish(Prim& p);
  void renderStrip(uint16_t* buf, const Rect& strip) const;

  Prim prims_[MAX_PRIMS];
  PlacedGlyph glyphs_[MAX_GLYPHS];
  int count_ = 0, glyphCount_ = 0;
  bool overflow_ = false;
  uint16_t baseColor_ = 0;
  BaseRowFn baseFn_ = nullptr;
  void* baseCtx_ = nullptr;
};

// Recuerda la escena anterior (huella y caja de cada elemento) y devuelve las zonas que han cambiado
class SceneDiff {
 public:
  static constexpr int MAX_RECTS = 6;
  void invalidate() { valid_ = false; }
  // Devuelve el número de rectángulos a repintar (0 = nada); si es mucho, la pantalla entera
  int diff(const Scene& s, Rect* out);

 private:
  struct Entry { uint32_t hash; Rect box; };
  Entry prev_[Scene::MAX_PRIMS];
  int prevCount_ = 0;
  uint16_t prevBase_ = 0;
  bool valid_ = false;
};
