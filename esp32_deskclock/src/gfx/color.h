// Color RGB565 y mezcla, y la paleta Catppuccin Mocha del panel (core/themes.py).
#pragma once
#include <stdint.h>

constexpr uint16_t rgb565(uint8_t r, uint8_t g, uint8_t b) {
  return (uint16_t)(((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3));
}
constexpr uint16_t hex565(uint32_t rgb) { return rgb565((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF); }

inline void unpack565(uint16_t c, int& r, int& g, int& b) {
  r = (c >> 11) & 0x1F; g = (c >> 5) & 0x3F; b = c & 0x1F;
  r = (r << 3) | (r >> 2); g = (g << 2) | (g >> 4); b = (b << 3) | (b >> 2);
}

// a = 0 → bg, 255 → fg
inline uint16_t blend565(uint16_t bg, uint16_t fg, uint8_t a) {
  if (a == 255) return fg;
  if (a == 0) return bg;
  int r1, g1, b1, r2, g2, b2;
  unpack565(bg, r1, g1, b1);
  unpack565(fg, r2, g2, b2);
  return rgb565((uint8_t)(r1 + ((r2 - r1) * a + 127) / 255), (uint8_t)(g1 + ((g2 - g1) * a + 127) / 255),
                (uint8_t)(b1 + ((b2 - b1) * a + 127) / 255));
}

// Luminancia relativa aproximada (0-255) para elegir texto claro u oscuro
inline int luma565(uint16_t c) {
  int r, g, b;
  unpack565(c, r, g, b);
  return (r * 54 + g * 183 + b * 19) >> 8;
}

namespace pal {
// Catppuccin Mocha
constexpr uint16_t crust = hex565(0x11111b), mantle = hex565(0x181825), base = hex565(0x1e1e2e);
constexpr uint16_t surface0 = hex565(0x313244), surface1 = hex565(0x45475a), surface2 = hex565(0x585b70);
constexpr uint16_t overlay0 = hex565(0x6c7086), overlay1 = hex565(0x7f849c);
constexpr uint16_t subtext0 = hex565(0xa6adc8), subtext1 = hex565(0xbac2de), text = hex565(0xcdd6f4);
constexpr uint16_t blue = hex565(0x89b4fa), lavender = hex565(0xb4befe), mauve = hex565(0xcba6f7);
constexpr uint16_t peach = hex565(0xfab387), green = hex565(0xa6e3a1), red = hex565(0xf38ba8);
constexpr uint16_t yellow = hex565(0xf9e2af), teal = hex565(0x94e2d5), sky = hex565(0x89dceb);
constexpr uint16_t pink = hex565(0xf5c2e7);
}  // namespace pal
