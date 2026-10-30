// Canvas del PC: guarda los píxeles en memoria y los escribe como PPM/PNG (con ImageMagick).
#pragma once
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../src/gfx/scene.h"

class HostCanvas : public Canvas {
 public:
  uint16_t fb[SCREEN_WIDTH * SCREEN_HEIGHT];
  long pushes = 0, pixels = 0;
  HostCanvas() { memset(fb, 0, sizeof fb); }
  void pushRows(int x, int y, int w, int h, const uint16_t* px) override {
    pushes++;
    for (int r = 0; r < h; r++) {
      memcpy(&fb[(y + r) * SCREEN_WIDTH + x], px + r * w, w * 2);
      pixels += w;
    }
  }
  bool savePng(const char* path) const {
    char ppm[512];
    snprintf(ppm, sizeof ppm, "%s.ppm", path);
    FILE* f = fopen(ppm, "wb");
    if (!f) return false;
    fprintf(f, "P6\n%d %d\n255\n", SCREEN_WIDTH, SCREEN_HEIGHT);
    for (int i = 0; i < SCREEN_WIDTH * SCREEN_HEIGHT; i++) {
      int r, g, b;
      unpack565(fb[i], r, g, b);
      unsigned char px[3] = {(unsigned char)r, (unsigned char)g, (unsigned char)b};
      fwrite(px, 1, 3, f);
    }
    fclose(f);
    char cmd[1200];
    snprintf(cmd, sizeof cmd, "magick '%s' -scale 200%% '%s' && rm -f '%s'", ppm, path, ppm);
    return system(cmd) == 0;
  }
};
