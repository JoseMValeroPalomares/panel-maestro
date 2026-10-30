#include <stdio.h>
#include "host_canvas.h"

int main(int argc, char** argv) {
  static Scene s;
  HostCanvas c;
  s.reset(pal::base);
  s.text(16, 10, FONT_SMALL, pal::subtext0, "Lunes, 19 de octubre · Año ñandú ¿qué? ¡sí! «…»");
  s.text(160, 26, FONT_CLOCK, pal::text, "18:45", ALIGN_CENTER);
  s.rect(16, 150, 288, 72, 14, pal::surface0);
  s.stroke(16, 150, 288, 72, 14, pal::surface1, 1);
  s.circle(40, 186, 8, pal::peach);
  s.text(60, 166, FONT_LABEL, pal::text, "Examen de Electrónica");
  s.paragraph(60, 186, 230, FONT_BODY, pal::subtext0, "Mañana a las 9:00 en el aula 2.14, llevar calculadora y apuntes", 2);
  s.arc(280, 40, 24, 6, 0, 250, pal::mauve);
  s.text(280, 26, FONT_SMALL, pal::text, "68%", ALIGN_CENTER);
  c.pushes = 0;
  s.render(c, Rect{0, 0, SCREEN_WIDTH, SCREEN_HEIGHT});
  printf("prims %d pushes %ld\n", s.count(), c.pushes);
  return c.savePng(argc > 1 ? argv[1] : "smoke.png") ? 0 : 1;
}
