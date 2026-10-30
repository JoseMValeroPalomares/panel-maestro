// Piezas compartidas por ui.cpp (gestor) y screens.cpp (lo que se dibuja).
#pragma once
#include <time.h>

#include "../gfx/scene.h"
#include "ui.h"

namespace ui {

enum Modal : uint8_t { M_NONE, M_REVIEW, M_DAY, M_ALERT, M_CONFIRM };

struct State {
  Screen screen = CLOCK;
  Modal modal = M_NONE;
  uint32_t modalSince = 0;
  // Calendario
  int32_t calCursor = 0;         // día seleccionado (días desde 1970)
  // Listas
  bool listsOpen = false;        // dentro de una categoría
  int listsCat = 0, listsSel = 0, listsScroll = 0;
  // Notas
  bool notesReading = false;     // leyendo una (si no, en la lista)
  int notesSel = 0, notesScroll = 0;
  int readLine = 0, readLines = 0, readPage = 1;  // desplazamiento del texto (lo calcula el dibujo)
  // Ajustes
  int bannerDays = 2;
  bool reviewAuto = true;
  // Aviso del pomodoro
  uint8_t alertPhase = 0;        // fase que acaba de terminar
  // Aviso breve
  char toast[72] = "";
  uint32_t toastUntil = 0;
};

extern State st;

// Constructores de cada pantalla (screens.cpp)
void buildClock(Scene& s, const struct tm* now);
void buildMusic(Scene& s, const struct tm* now);
void buildCalendar(Scene& s, const struct tm* now);
void buildLists(Scene& s, const struct tm* now);
void buildPomodoro(Scene& s, const struct tm* now);
void buildSystem(Scene& s, const struct tm* now);
void buildNotes(Scene& s, const struct tm* now);
void buildReview(Scene& s);
void buildDayModal(Scene& s);
void buildAlert(Scene& s);
void buildConfirm(Scene& s);
void buildToast(Scene& s);

// Medidas comunes
constexpr int MARGIN = 16;
constexpr int TOPBAR_H = 32;
constexpr int HINT_Y = 216;
constexpr Screen SCREEN_ORDER[SCREEN_COUNT] = {CLOCK, CALENDAR, LISTS, NOTES, POMODORO, SYSTEM};
constexpr int NOTE_ROWS = 4;

}  // namespace ui
