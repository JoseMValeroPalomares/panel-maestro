// Interfaz: pantalla activa, capas modales (repaso, día, avisos) y mando IR.
// tick() construye la escena de lo que debe verse, la compara con la anterior y
// solo repinta lo que ha cambiado. Es lo único que dibuja en la pantalla.
#pragma once
#include <stdint.h>

#include "../gfx/scene.h"

namespace ui {

// El orden del enum es el número que usa la web (set_screen / screen_changed): NOTES va al final
// para no cambiar los de antes. El orden en que se recorren con las flechas está en SCREEN_ORDER.
enum Screen : uint8_t { CLOCK, CALENDAR, LISTS, POMODORO, SYSTEM, NOTES, SCREEN_COUNT };
enum Key : uint8_t { K_UP, K_DOWN, K_LEFT, K_RIGHT, K_OK, K_BACK, K_HOME, K_0, K_1, K_2, K_3, K_4, K_5, K_6, K_7, K_8, K_9 };

void begin(Canvas* canvas);
void goTo(Screen s);
Screen current();
void key(Key k, bool repeat = false);
void toast(const char* text);
void invalidate();             // repintado completo la próxima vez
void tick();                   // llamar desde loop() (se limita a ~12 fotogramas por segundo)
void build(Scene& s);          // escena de lo que se ve ahora (también para las capturas del PC)
void broadcastScreen();        // {"type":"screen_changed"} para la web
int bannerDays();
void setBannerDays(int days);
bool reviewAuto();             // si la nota de repaso aparece sola en el reloj
void setReviewAuto(bool on);   // se guarda en la NVS y se avisa a la web
void broadcastReviewState();   // {"type":"review_state","enabled":...}

}  // namespace ui
