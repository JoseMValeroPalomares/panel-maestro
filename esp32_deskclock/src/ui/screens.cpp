// Lo que se ve en cada pantalla. Paleta y tipografía del panel (Catppuccin Mocha + Inter).
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "../core/util.h"
#include "../model/calendar.h"
#include "../model/lists.h"
#include "../model/media.h"
#include "../model/notes.h"
#include "../model/pomodoro.h"
#include "../platform/platform.h"
#include "ui_internal.h"

namespace ui {

// ─────────────────────────────────────────────
// Piezas comunes
// ─────────────────────────────────────────────
static const Glyph* g0(const Font& f) { return fontGlyph(f, '0'); }
// y para que la parte alta de las cifras quede en `top`
static int digitsY(const Font& f, int top) { return top - g0(f)->y; }
static int digitsH(const Font& f) { return g0(f)->h; }
static int capY(const Font& f, int top) { return top - fontGlyph(f, 'H')->y; }

static void fmtClock(char* out, const struct tm* t) {
  if (t) snprintf(out, 6, "%02d:%02d", t->tm_hour, t->tm_min);
  else strcpy(out, "--:--");
}

static void fmtMinSec(char* out, uint32_t s) { snprintf(out, 12, "%lu:%02lu", (unsigned long)(s / 60), (unsigned long)(s % 60)); }

static void pageDots(Scene& s, int cx, int y) {
  const int n = SCREEN_COUNT, gap = 10;
  int x = cx - ((n - 1) * gap + 14) / 2;
  for (int i = 0; i < n; i++) {
    if (SCREEN_ORDER[i] == st.screen) { s.rect(x, y - 3, 16, 6, 3, look::accent()); x += 16 + gap - 6; }
    else { s.circle(x + 3, y, 3, pal::surface2); x += gap; }
  }
}

static void topBar(Scene& s, const char* title, const struct tm* t) {
  s.textFit(MARGIN, capY(FONT_LABEL, 11), 120, FONT_LABEL, pal::subtext1, title);
  pageDots(s, SCREEN_WIDTH / 2, 17);
  char clock[8];
  fmtClock(clock, t);
  s.text(SCREEN_WIDTH - MARGIN, capY(FONT_LABEL, 11), FONT_LABEL, pal::text, clock, ALIGN_RIGHT);
}

// Tecla del mando dibujada como una pequeña tecla, seguida de lo que hace.
// Las flechas se dibujan (la fuente no las trae): KEY_LR, KEY_UD y KEY_ARROWS.
static const char KEY_LR[] = "\x01", KEY_UD[] = "\x02", KEY_ARROWS[] = "\x03";

static void chevron(Scene& s, float cx, float cy, int dir, uint16_t c) {  // 0 izq, 1 der, 2 arriba, 3 abajo
  const float a = 3.2f, w = 1.7f;
  if (dir < 2) {
    const float k = dir == 0 ? 1 : -1;
    s.line(cx + k * a * 0.6f, cy - a, cx - k * a * 0.6f, cy, w, c);
    s.line(cx - k * a * 0.6f, cy, cx + k * a * 0.6f, cy + a, w, c);
  } else {
    const float k = dir == 2 ? 1 : -1;
    s.line(cx - a, cy + k * a * 0.6f, cx, cy - k * a * 0.6f, w, c);
    s.line(cx, cy - k * a * 0.6f, cx + a, cy + k * a * 0.6f, w, c);
  }
}

static void checkMark(Scene& s, float cx, float cy, float size, uint16_t c) {
  s.line(cx - size * 0.45f, cy + size * 0.02f, cx - size * 0.12f, cy + size * 0.32f, size * 0.22f, c);
  s.line(cx - size * 0.12f, cy + size * 0.32f, cx + size * 0.45f, cy - size * 0.3f, size * 0.22f, c);
}

static int keyCapWidth(const char* k) {
  if (k[0] == 1 || k[0] == 2) return 30;
  if (k[0] == 3) return 50;
  return textWidth(FONT_SMALL, k) + 12;
}
static int keyWidth(const char* k, const char* label) { return keyCapWidth(k) + 5 + textWidth(FONT_SMALL, label); }
static int drawKey(Scene& s, int x, int y, const char* k, const char* label) {
  const int kw = keyCapWidth(k);
  s.rect(x, y, kw, 18, 5, pal::surface1);
  const float cy = y + 9;
  if (k[0] == 1) { chevron(s, x + 10, cy, 0, pal::text); chevron(s, x + 20, cy, 1, pal::text); }
  else if (k[0] == 2) { chevron(s, x + 10, cy, 2, pal::text); chevron(s, x + 20, cy, 3, pal::text); }
  else if (k[0] == 3) {
    for (int i = 0; i < 4; i++) chevron(s, x + 10 + i * 10, cy, i, pal::text);
  } else {
    s.text(x + kw / 2, capY(FONT_SMALL, y + 5), FONT_SMALL, pal::text, k, ALIGN_CENTER);
  }
  s.text(x + kw + 5, capY(FONT_SMALL, y + 5), FONT_SMALL, pal::subtext0, label);
  return kw + 5 + textWidth(FONT_SMALL, label);
}
// Fila de teclas centrada: pares tecla/acción terminados en nullptr
static void hints(Scene& s, int y, const char* const* pairs) {
  int total = 0, n = 0;
  for (; pairs[n * 2]; n++) total += keyWidth(pairs[n * 2], pairs[n * 2 + 1]) + (n ? 14 : 0);
  int x = (SCREEN_WIDTH - total) / 2;
  for (int i = 0; i < n; i++) x += drawKey(s, x, y, pairs[i * 2], pairs[i * 2 + 1]) + 14;
}

static void card(Scene& s, int x, int y, int w, int h, uint16_t bg = pal::surface0) {
  s.rect(x, y, w, h, 14, bg);
}

// Fondo de pantalla: el personalizado (imagen de la SD) o el color base
static void background(Scene& s) {
  if (look::hasImage()) s.setBase(look::baseRow, nullptr);
  else s.reset(look::color());
}

static void envText(char* out, size_t size) {
  SysInfo si;
  sysInfo(si);
  if (isnan(si.tempC)) { out[0] = 0; return; }
  if (isnan(si.humidity)) snprintf(out, size, "%.1f°", si.tempC);
  else snprintf(out, size, "%.1f°  ·  %.0f %%", si.tempC, si.humidity);
  for (char* p = out; *p; p++) if (*p == '.') *p = ',';  // coma decimal
}

static void dateLong(char* out, size_t size, const struct tm* t) {
  if (!t) { snprintf(out, size, "Sincronizando la hora…"); return; }
  snprintf(out, size, "%s, %d de %s", WEEKDAYS_ES[(t->tm_wday + 6) % 7], t->tm_mday, MONTHS_ES[t->tm_mon]);
  capitalizeEs(out);
}

// ─────────────────────────────────────────────
// Reloj
// ─────────────────────────────────────────────
static void nextEventCard(Scene& s, int y, int h) {
  const int32_t today = todayDays();
  const int i = today ? calendar::firstFrom(today) : -1;
  card(s, MARGIN, y, SCREEN_WIDTH - 2 * MARGIN, h);
  if (i < 0) {
    s.text(MARGIN + 18, capY(FONT_BODY, y + h / 2 - 6), FONT_BODY, pal::subtext0,
           calendar::count() ? "Sin eventos próximos" : "Sin eventos en el calendario");
    return;
  }
  const calendar::Event& e = calendar::at(i);
  const int delta = e.day - today;
  const uint16_t c = calendar::colorFor(e.type);
  const bool soon = delta <= st.bannerDays;
  if (soon) s.rect(MARGIN, y, SCREEN_WIDTH - 2 * MARGIN, h, 14, blend565(pal::surface0, c, 40));
  // azulejo con el tipo
  s.rect(MARGIN + 14, y + (h - 34) / 2, 34, 34, 9, blend565(pal::surface0, c, soon ? 110 : 70));
  s.circle(MARGIN + 31, y + h / 2, 5, c);
  const int tx = MARGIN + 60, tw = SCREEN_WIDTH - 2 * MARGIN - 60 - 14;
  s.textFit(tx, capY(FONT_LABEL, y + 15), tw, FONT_LABEL, pal::text, e.title);
  char when[40], line[80], iso[11];
  relativeDayEs(delta, when, sizeof when);
  int yy, mm, dd;
  civilFromDays(e.day, yy, mm, dd);
  daysToIso(e.day, iso);
  snprintf(line, sizeof line, "%c%s · %s · %d %.3s", e.type[0] - 32, e.type + 1, when, dd, MONTHS_ES[mm - 1]);
  s.textFit(tx, capY(FONT_SMALL, y + 37), tw, FONT_SMALL, soon ? pal::text : pal::subtext0, line);
}

static void pomodoroChip(Scene& s, int cy) {
  if (pomodoro::run() == pomodoro::STOPPED) return;
  char t[16], line[48];
  fmtMinSec(t, pomodoro::remainingSec());
  const bool work = pomodoro::phase() == pomodoro::WORK;
  snprintf(line, sizeof line, "%s  %s%s", work ? "Trabajo" : "Descanso", t, pomodoro::run() == pomodoro::PAUSED ? "  (pausa)" : "");
  const int w = textWidth(FONT_SMALL, line) + 34;
  const uint16_t c = work ? pal::peach : pal::teal;
  s.rect(SCREEN_WIDTH / 2 - w / 2, cy - 11, w, 22, 11, blend565(pal::base, c, 50));
  s.circle(SCREEN_WIDTH / 2 - w / 2 + 13, cy, 4, c);
  s.text(SCREEN_WIDTH / 2 - w / 2 + 24, capY(FONT_SMALL, cy - 4), FONT_SMALL, pal::text, line);
}

void buildClock(Scene& s, const struct tm* t) {
  background(s);
  char buf[64];
  dateLong(buf, sizeof buf, t);
  s.textFit(MARGIN, capY(FONT_LABEL, 14), 190, FONT_LABEL, pal::subtext1, buf);
  envText(buf, sizeof buf);
  if (*buf) s.text(SCREEN_WIDTH - MARGIN, capY(FONT_LABEL, 14), FONT_LABEL, pal::subtext0, buf, ALIGN_RIGHT);
  char clock[8];
  fmtClock(clock, t);
  const int clockTop = 46;
  s.text(SCREEN_WIDTH / 2, digitsY(FONT_CLOCK, clockTop), FONT_CLOCK, t ? pal::text : pal::overlay0, clock, ALIGN_CENTER);
  pomodoroChip(s, clockTop + digitsH(FONT_CLOCK) + 20);
  nextEventCard(s, 160, 64);
}

// ─────────────────────────────────────────────
// Música (pantalla del reloj mientras suena algo)
// ─────────────────────────────────────────────
void buildMusic(Scene& s, const struct tm* t) {
  const uint16_t acc = look::accent();
  s.reset(blend565(pal::crust, acc, 28));
  char buf[64];
  fmtClock(buf, t);
  s.text(MARGIN, capY(FONT_LABEL, 14), FONT_LABEL, pal::text, buf);
  envText(buf, sizeof buf);
  if (*buf) s.text(SCREEN_WIDTH - MARGIN, capY(FONT_LABEL, 14), FONT_LABEL, pal::subtext0, buf, ALIGN_RIGHT);

  // Carátula (o un disco con el acento si aún no ha llegado)
  const int cx = MARGIN, cy = 40, size = 120;
  uint16_t w = 0, h = 0;
  uint32_t ver = 0;
  const uint8_t* px = music::coverPixels(w, h, ver);
  if (px) {
    const int scale = w <= 64 ? 2 : 1;
    s.image(cx + (size - w * scale) / 2, cy + (size - h * scale) / 2, px, w, h, scale, 12, ver);
  } else {
    s.rect(cx, cy, size, size, 12, blend565(pal::crust, acc, 60));
    s.arc(cx + size / 2, cy + size / 2, 44, 2, 0, 360, blend565(pal::crust, acc, 120));
    s.arc(cx + size / 2, cy + size / 2, 30, 2, 0, 360, blend565(pal::crust, acc, 120));
    s.circle(cx + size / 2, cy + size / 2, 8, acc);
  }
  // Título y artista
  const int tx = cx + size + 16, tw = SCREEN_WIDTH - MARGIN - tx;
  s.text(tx, capY(FONT_SMALL, cy + 4), FONT_SMALL, acc, music::playing() ? "Sonando ahora" : "En pausa");
  const int th = s.paragraph(tx, capY(FONT_TITLE, cy + 24), tw, FONT_TITLE, pal::text,
                             *music::title() ? music::title() : "Sin título", 2, -2);
  s.paragraph(tx, capY(FONT_BODY, cy + 24 + th + 6), tw, FONT_BODY, pal::subtext1, music::artist(), th > 30 ? 1 : 2);
  // Progreso
  const int py = 178, pw = SCREEN_WIDTH - 2 * MARGIN;
  const uint32_t dur = music::durationSec(), pos = music::positionSec();
  s.rect(MARGIN, py, pw, 4, 2, blend565(pal::crust, acc, 70));
  if (dur) s.rect(MARGIN, py, (int)((uint64_t)pw * pos / dur), 4, 2, acc);
  char a[12], b[12];
  fmtMinSec(a, pos);
  fmtMinSec(b, dur);
  s.text(MARGIN, capY(FONT_SMALL, py + 12), FONT_SMALL, pal::subtext0, a);
  if (dur) s.text(SCREEN_WIDTH - MARGIN, capY(FONT_SMALL, py + 12), FONT_SMALL, pal::subtext0, b, ALIGN_RIGHT);
  const char* const HP[] = {KEY_LR, "Canción", "OK", music::playing() ? "Pausa" : "Seguir", KEY_UD, "Volumen", nullptr};
  hints(s, HINT_Y, HP);
}

// ─────────────────────────────────────────────
// Repaso de una nota (ocupa toda la pantalla mientras dura)
// ─────────────────────────────────────────────
void buildReview(Scene& s) {
  s.reset(pal::base);
  const uint16_t c = pal::mauve;
  const int chipW = textWidth(FONT_SMALL, "Repaso") + 20;
  s.rect(MARGIN, 12, chipW, 20, 10, blend565(pal::base, c, 60));
  s.text(MARGIN + chipW / 2, capY(FONT_SMALL, 18), FONT_SMALL, c, "Repaso", ALIGN_CENTER);
  s.textFit(MARGIN + chipW + 10, capY(FONT_SMALL, 18), SCREEN_WIDTH - 2 * MARGIN - chipW - 10, FONT_SMALL, pal::subtext0,
            review::category(), ALIGN_LEFT);
  const int th = s.paragraph(MARGIN, capY(FONT_TITLE, 46), SCREEN_WIDTH - 2 * MARGIN, FONT_TITLE, pal::text, review::title(), 2, -2);
  const int top = 46 + th + 8;
  const int lines = (198 - top) / (FONT_BODY.lineHeight() + 2);
  s.paragraph(MARGIN, top - (FONT_BODY.ascent - fontGlyph(FONT_BODY, 'H')->h) + 2, SCREEN_WIDTH - 2 * MARGIN, FONT_BODY,
              pal::subtext1, review::snippet(), lines > 1 ? lines : 1, 2);
  // Tiempo que queda en pantalla
  const int bw = SCREEN_WIDTH - 2 * MARGIN;
  s.rect(MARGIN, 204, bw, 3, 1, pal::surface0);
  s.rect(MARGIN, 204, (int)(bw * review::remaining()), 3, 1, c);
  if (review::openRequested()) {
    const char* msg = "Abriendo la nota en el PC…";
    const int w = textWidth(FONT_SMALL, msg) + 28;
    s.rect(SCREEN_WIDTH / 2 - w / 2, HINT_Y - 1, w, 20, 10, blend565(pal::base, pal::green, 60));
    s.text(SCREEN_WIDTH / 2, capY(FONT_SMALL, HINT_Y + 5), FONT_SMALL, pal::green, msg, ALIGN_CENTER);
  } else {
    static const char* const H[] = {"OK", "Abrir en el PC", "*", "Cerrar", nullptr};
    hints(s, HINT_Y, H);
  }
}

// ─────────────────────────────────────────────
// Calendario
// ─────────────────────────────────────────────
void buildCalendar(Scene& s, const struct tm* t) {
  s.reset(pal::base);
  if (!st.calCursor) st.calCursor = todayDays();
  int y, m, d;
  civilFromDays(st.calCursor ? st.calCursor : daysFromCivil(2026, 1, 1), y, m, d);
  char title[32];
  snprintf(title, sizeof title, "%s %d", MONTHS_ES[m - 1], y);
  capitalizeEs(title);
  topBar(s, title, t);

  const int cellW = 44, cellH = 26, gx = (SCREEN_WIDTH - 7 * cellW) / 2, gy = 56;
  for (int c = 0; c < 7; c++)
    s.text(gx + c * cellW + cellW / 2, capY(FONT_SMALL, 40), FONT_SMALL, c >= 5 ? pal::overlay0 : pal::overlay1,
           WEEKDAYS_SHORT_ES[c], ALIGN_CENTER);
  const int first = weekdayMon0(y, m, 1), days = daysInMonth(y, m);
  const int32_t day1 = daysFromCivil(y, m, 1), today = todayDays();
  const uint16_t acc = look::accent();
  for (int dd = 1; dd <= days; dd++) {
    const int slot = first + dd - 1, col = slot % 7, row = slot / 7;
    const int cx = gx + col * cellW + cellW / 2, cy = gy + row * cellH + 9;
    const int32_t day = day1 + dd - 1;
    const bool isToday = day == today, isCursor = day == st.calCursor;
    if (isToday) s.rect(cx - 15, cy - 10, 30, 20, 10, acc);
    else if (isCursor) s.rect(cx - 15, cy - 10, 30, 20, 10, pal::surface1);
    if (isCursor && isToday) s.stroke(cx - 17, cy - 12, 34, 24, 12, pal::text, 2);
    char num[8];
    snprintf(num, sizeof num, "%d", dd);
    s.text(cx, capY(FONT_LABEL, cy - 5), FONT_LABEL, isToday ? pal::crust : col >= 5 ? pal::subtext0 : pal::text, num, ALIGN_CENTER);
    int idx[3];
    const int ne = calendar::eventsOn(day, idx, 3);
    for (int k = 0; k < ne; k++) s.circle(cx - (ne - 1) * 4 + k * 8, cy + 12, 2, calendar::colorFor(calendar::at(idx[k]).type));
  }
  // Abajo: lo que hay el día seleccionado, o cómo moverse
  int idx[4];
  const int ne = calendar::eventsOn(st.calCursor, idx, 4);
  if (ne) {
    const calendar::Event& e = calendar::at(idx[0]);
    char line[96];
    if (ne > 1) snprintf(line, sizeof line, "%s  +%d", e.title, ne - 1);
    else copyStr(line, e.title, sizeof line);
    static const char* const H[] = {"OK", "Ver día", nullptr};
    const int kx = SCREEN_WIDTH - MARGIN - keyWidth(H[0], H[1]);
    s.circle(MARGIN + 5, HINT_Y + 9, 4, calendar::colorFor(e.type));
    s.textFit(MARGIN + 16, capY(FONT_SMALL, HINT_Y + 5), kx - 14 - (MARGIN + 16), FONT_SMALL, pal::text, line);
    drawKey(s, kx, HINT_Y, H[0], H[1]);
  } else {
    static const char* const H[] = {KEY_ARROWS, "Moverse", "OK", "Ver día", "*", "Hoy", nullptr};
    hints(s, HINT_Y, H);
  }
}

void buildDayModal(Scene& s) {
  s.rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, pal::crust, 170);
  const int x = 22, y = 26, w = SCREEN_WIDTH - 44, h = 188;
  card(s, x, y, w, h);
  int yy, mm, dd;
  civilFromDays(st.calCursor, yy, mm, dd);
  char title[48];
  snprintf(title, sizeof title, "%s, %d de %s", WEEKDAYS_ES[weekdayMon0(yy, mm, dd)], dd, MONTHS_ES[mm - 1]);
  capitalizeEs(title);
  s.textFit(x + 16, capY(FONT_LABEL, y + 16), w - 32, FONT_LABEL, pal::text, title);
  const int32_t today = todayDays();
  char rel[24];
  relativeDayEs(st.calCursor - today, rel, sizeof rel);
  if (today) s.text(x + w - 16, capY(FONT_SMALL, y + 18), FONT_SMALL, pal::subtext0, rel, ALIGN_RIGHT);
  int idx[5];
  const int n = calendar::eventsOn(st.calCursor, idx, 5);
  if (!n) s.text(x + 16, capY(FONT_BODY, y + 56), FONT_BODY, pal::subtext0, "Sin eventos este día");
  for (int i = 0; i < n; i++) {
    const calendar::Event& e = calendar::at(idx[i]);
    const int ry = y + 42 + i * 28;
    s.circle(x + 22, ry + 9, 4, calendar::colorFor(e.type));
    s.textFit(x + 34, capY(FONT_BODY, ry + 3), w - 34 - 80, FONT_BODY, pal::text, e.title);
    s.text(x + w - 16, capY(FONT_SMALL, ry + 5), FONT_SMALL, calendar::colorFor(e.type), e.type, ALIGN_RIGHT);
  }
  static const char* const H[] = {KEY_LR, "Otro día", "*", "Cerrar", nullptr};
  hints(s, y + h - 28, H);
}

// ─────────────────────────────────────────────
// Listas
// ─────────────────────────────────────────────
static constexpr int ROW_H = 34, LIST_Y = 40, LIST_ROWS = 5;

static void progressBar(Scene& s, int x, int y, int w, int done, int total, uint16_t c) {
  s.rect(x, y, w, 4, 2, pal::surface2);
  if (total) s.rect(x, y, w * done / total, 4, 2, c);
}

void buildLists(Scene& s, const struct tm* t) {
  s.reset(pal::base);
  const uint16_t acc = look::accent();
  const int nCats = lists::categoryCount();
  const int lx = MARGIN, lw = SCREEN_WIDTH - 2 * MARGIN;
  if (!fsReady() && !nCats) {
    topBar(s, "Listas", t);
    s.paragraph(lx, 90, lw, FONT_BODY, pal::subtext0, "No hay tarjeta SD: inserta una para guardar las listas.", 2, 2, ALIGN_CENTER);
    return;
  }
  if (!st.listsOpen) {
    topBar(s, "Listas", t);
    if (!nCats) {
      s.paragraph(lx, 90, lw, FONT_BODY, pal::subtext0, "Aún no hay listas. Créalas desde la web de Estudio del panel.", 3, 2, ALIGN_CENTER);
      return;
    }
    const int shown = nCats - st.listsScroll < LIST_ROWS ? nCats - st.listsScroll : LIST_ROWS;
    card(s, lx, LIST_Y, lw, shown * ROW_H);
    for (int r = 0; r < shown; r++) {
      const int i = st.listsScroll + r, ry = LIST_Y + r * ROW_H;
      const lists::Category& c = lists::category(i);
      int done, total;
      lists::progress(c.id, done, total);
      if (i == st.listsSel) s.rect(lx, ry, lw, ROW_H, 14, pal::surface1);
      else if (r) s.rect(lx + 14, ry, lw - 14, 1, 0, pal::surface1);
      s.textFit(lx + 14, capY(FONT_BODY, ry + 12), lw - 130, FONT_BODY, pal::text, c.name);
      char cnt[16];
      snprintf(cnt, sizeof cnt, "%d/%d", done, total);
      s.text(lx + lw - 70, capY(FONT_SMALL, ry + 13), FONT_SMALL, done == total && total ? pal::green : pal::subtext0, cnt, ALIGN_RIGHT);
      progressBar(s, lx + lw - 60, ry + 15, 32, done, total, done == total && total ? pal::green : acc);
      s.text(lx + lw - 12, capY(FONT_BODY, ry + 12), FONT_BODY, pal::overlay1, "›", ALIGN_RIGHT);
    }
    static const char* const H[] = {KEY_UD, "Elegir", "OK", "Abrir", nullptr};
    hints(s, HINT_Y, H);
    return;
  }
  if (st.listsCat >= nCats) { st.listsOpen = false; return buildLists(s, t); }
  const lists::Category& c = lists::category(st.listsCat);
  int done, total;
  lists::progress(c.id, done, total);
  topBar(s, c.name, t);
  int idx[lists::MAX_ITEMS];
  const int n = lists::itemsOf(c.id, idx, lists::MAX_ITEMS);
  if (st.listsSel >= n) st.listsSel = n ? n - 1 : 0;
  if (!n) {
    s.paragraph(lx, 90, lw, FONT_BODY, pal::subtext0, "Lista vacía. Añade tareas desde la web de Estudio.", 2, 2, ALIGN_CENTER);
  } else {
    const int shown = n - st.listsScroll < LIST_ROWS ? n - st.listsScroll : LIST_ROWS;
    card(s, lx, LIST_Y, lw, shown * ROW_H);
    for (int r = 0; r < shown; r++) {
      const int i = st.listsScroll + r, ry = LIST_Y + r * ROW_H;
      const lists::Item& it = lists::item(idx[i]);
      if (i == st.listsSel) s.rect(lx, ry, lw, ROW_H, 14, pal::surface1);
      else if (r) s.rect(lx + 42, ry, lw - 42, 1, 0, pal::surface1);
      const int bx = lx + 22, by = ry + ROW_H / 2;
      if (it.done) {
        s.circle(bx, by, 9, pal::green);
        checkMark(s, bx, by, 10, pal::crust);
      } else {
        s.arc(bx, by, 9, 2, 0, 360, pal::overlay0);
      }
      const int badgeW = it.daily ? textWidth(FONT_SMALL, "Diaria") + 14 : 0;
      const int tw = lw - 42 - 12 - (badgeW ? badgeW + 8 : 0);
      s.textFit(lx + 42, capY(FONT_BODY, ry + 12), tw, FONT_BODY, it.done ? pal::overlay1 : pal::text, it.text);
      if (it.done) {
        char shown[80];
        ellipsize(FONT_BODY, it.text, tw, shown, sizeof shown);
        s.rect(lx + 42, ry + ROW_H / 2, textWidth(FONT_BODY, shown), 1, 0, pal::overlay1);
      }
      if (badgeW) {
        s.rect(lx + lw - 12 - badgeW, ry + 8, badgeW, 18, 9, blend565(pal::surface0, pal::teal, 50));
        s.text(lx + lw - 12 - badgeW / 2, capY(FONT_SMALL, ry + 13), FONT_SMALL, pal::teal, "Diaria", ALIGN_CENTER);
      }
    }
    if (n > LIST_ROWS) {  // barra de desplazamiento
      const int trackH = LIST_ROWS * ROW_H - 16, thumb = trackH * LIST_ROWS / n;
      const int ty = LIST_Y + 8 + (trackH - thumb) * st.listsScroll / (n - LIST_ROWS);
      s.rect(SCREEN_WIDTH - 9, ty, 3, thumb, 1, pal::overlay0);
    }
  }
  static const char* const H[] = {"OK", "Marcar", "*", "Volver", nullptr};
  hints(s, HINT_Y, H);
}

// ─────────────────────────────────────────────
// Pomodoro
// ─────────────────────────────────────────────
void buildPomodoro(Scene& s, const struct tm* t) {
  s.reset(pal::base);
  topBar(s, "Pomodoro", t);
  const bool work = pomodoro::phase() == pomodoro::WORK;
  const uint16_t c = work ? pal::peach : pal::teal;
  const int cx = 104, cy = 122, r = 80;
  const uint32_t total = pomodoro::totalSec(), left = pomodoro::remainingSec();
  s.arc(cx, cy, r, 10, 0, 360, pal::surface0, false);
  const int ang = total ? (int)((uint64_t)(total - left) * 360 / total) : 0;
  if (ang > 0) s.arc(cx, cy, r, 10, 0, ang, c);
  char time[12];
  snprintf(time, sizeof time, "%02lu:%02lu", (unsigned long)(left / 60 % 100), (unsigned long)(left % 60));
  s.text(cx, digitsY(FONT_NUM, cy - digitsH(FONT_NUM) / 2 - 6), FONT_NUM,
         pomodoro::run() == pomodoro::PAUSED ? pal::subtext0 : pal::text, time, ALIGN_CENTER);
  const char* label = pomodoro::run() == pomodoro::STOPPED ? "Listo" : pomodoro::run() == pomodoro::PAUSED ? "En pausa"
                      : work ? "Trabajo" : "Descanso";
  s.text(cx, capY(FONT_SMALL, cy + 26), FONT_SMALL, pomodoro::run() == pomodoro::RUNNING ? c : pal::subtext0, label, ALIGN_CENTER);

  // Columna derecha
  const int x = 206, w = SCREEN_WIDTH - MARGIN - x;
  char v[24];
  struct { const char* name; int value; const char* unit; uint16_t col; } rows[] = {
      {"Trabajo", pomodoro::workMin(), "min", pal::peach},
      {"Descanso", pomodoro::breakMin(), "min", pal::teal},
      {"Racha", pomodoro::streak(), pomodoro::streak() == 1 ? "día" : "días", pal::yellow}};
  for (int i = 0; i < 3; i++) {
    const int ry = 44 + i * 52;
    card(s, x, ry, w, 44);
    s.text(x + 12, capY(FONT_SMALL, ry + 8), FONT_SMALL, pal::subtext0, rows[i].name);
    snprintf(v, sizeof v, "%d %s", rows[i].value, rows[i].unit);
    s.text(x + 12, capY(FONT_LABEL, ry + 25), FONT_LABEL, pal::text, v);
    s.circle(x + w - 14, ry + 14, 3, rows[i].col);
  }
  if (pomodoro::run() == pomodoro::STOPPED) {
    static const char* const H[] = {"OK", "Empezar", KEY_UD, "Trabajo", KEY_LR, "Descanso", nullptr};
    hints(s, HINT_Y, H);
  } else {
    static const char* const H[] = {"OK", "Pausa/Seguir", "*", "Reiniciar", nullptr};
    hints(s, HINT_Y, H);
  }
}

void buildAlert(Scene& s) {
  s.rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, pal::crust, 180);
  const bool wasWork = st.alertPhase == pomodoro::WORK;
  const uint16_t c = wasWork ? pal::teal : pal::peach;
  const int x = 36, y = 52, w = SCREEN_WIDTH - 72, h = 136;
  card(s, x, y, w, h);
  s.circle(SCREEN_WIDTH / 2, y + 30, 14, blend565(pal::surface0, c, 90));
  s.circle(SCREEN_WIDTH / 2, y + 30, 6, c);
  s.text(SCREEN_WIDTH / 2, capY(FONT_TITLE, y + 56), FONT_TITLE, pal::text, wasWork ? "¡Hora de descansar!" : "A trabajar", ALIGN_CENTER);
  char line[48];
  snprintf(line, sizeof line, wasWork ? "%d minutos de descanso" : "%d minutos de concentración",
           wasWork ? pomodoro::breakMin() : pomodoro::workMin());
  s.text(SCREEN_WIDTH / 2, capY(FONT_BODY, y + 86), FONT_BODY, pal::subtext0, line, ALIGN_CENTER);
  static const char* const H[] = {"OK", "Entendido", nullptr};
  hints(s, y + h - 30, H);
}

// ─────────────────────────────────────────────
// Notas del Cerebro: lista y lector
// ─────────────────────────────────────────────
// Color por área (lo que va antes de « - » en la categoría): las subcategorías comparten color
static uint16_t areaColor(const char* category) {
  static const uint16_t C[] = {pal::mauve, pal::blue, pal::teal, pal::peach, pal::pink, pal::green, pal::yellow, pal::sky};
  uint32_t h = 2166136261u;
  for (const char* p = category; *p && strncmp(p, " - ", 3); p++) h = (h ^ (uint8_t)*p) * 16777619u;
  return C[h % (sizeof C / sizeof C[0])];
}

static void centerNote(Scene& s, const char* msg) {
  s.paragraph(MARGIN, 96, SCREEN_WIDTH - 2 * MARGIN, FONT_BODY, pal::subtext0, msg, 3, 2, ALIGN_CENTER);
}

static void buildNoteList(Scene& s, const struct tm* t) {
  topBar(s, "Notas", t);
  const int n = notes::count();
  if (!n) {
    centerNote(s, notes::listState() == notes::READY ? "No hay notas en el Cerebro todavía."
                                                     : "Pidiendo las notas al panel…");
    return;
  }
  if (st.notesSel >= n) st.notesSel = n - 1;
  if (st.notesScroll > st.notesSel) st.notesScroll = st.notesSel;
  const int rowH = 42, lx = MARGIN, lw = SCREEN_WIDTH - 2 * MARGIN, y0 = 40;
  const int shown = n - st.notesScroll < NOTE_ROWS ? n - st.notesScroll : NOTE_ROWS;
  card(s, lx, y0, lw, shown * rowH);
  for (int r = 0; r < shown; r++) {
    const int i = st.notesScroll + r, ry = y0 + r * rowH;
    const notes::Entry& e = notes::at(i);
    if (i == st.notesSel) s.rect(lx, ry, lw, rowH, 14, pal::surface1);
    else if (r) s.rect(lx + 30, ry, lw - 30, 1, 0, pal::surface1);
    s.circle(lx + 16, ry + rowH / 2, 4, areaColor(e.category));
    s.textFit(lx + 30, capY(FONT_BODY, ry + 8), lw - 30 - 24, FONT_BODY, pal::text, e.title);
    s.textFit(lx + 30, capY(FONT_SMALL, ry + 27), lw - 30 - 24, FONT_SMALL, pal::subtext0, e.category);
    s.text(lx + lw - 12, capY(FONT_BODY, ry + 14), FONT_BODY, pal::overlay1, "›", ALIGN_RIGHT);
  }
  if (n > NOTE_ROWS) {
    const int trackH = NOTE_ROWS * rowH - 16, thumb = trackH * NOTE_ROWS / n > 12 ? trackH * NOTE_ROWS / n : 12;
    const int ty = y0 + 8 + (trackH - thumb) * st.notesScroll / (n - NOTE_ROWS);
    s.rect(SCREEN_WIDTH - 9, ty, 3, thumb, 1, pal::overlay0);
  }
  char pos[16];
  snprintf(pos, sizeof pos, "%d/%d", st.notesSel + 1, n);
  static const char* const H[] = {KEY_UD, "Elegir", "OK", "Leer", nullptr};
  hints(s, HINT_Y, H);
  s.text(SCREEN_WIDTH - MARGIN, capY(FONT_SMALL, HINT_Y + 5), FONT_SMALL, pal::overlay1, pos, ALIGN_RIGHT);
}

static void buildNoteReader(Scene& s) {
  const int n = notes::count(), i = notes::openIndex();
  if (i < 0 || i >= n) { st.notesReading = false; return; }
  const notes::Entry& e = notes::at(i);
  const uint16_t c = areaColor(e.category);
  // Cabecera: área y posición, título
  char pos[16];
  snprintf(pos, sizeof pos, "%d/%d", i + 1, n);
  const int posW = textWidth(FONT_SMALL, pos);
  s.circle(MARGIN + 4, 18, 4, c);
  s.textFit(MARGIN + 14, capY(FONT_SMALL, 13), SCREEN_WIDTH - 2 * MARGIN - 14 - posW - 10, FONT_SMALL, pal::subtext0, e.category);
  s.text(SCREEN_WIDTH - MARGIN, capY(FONT_SMALL, 13), FONT_SMALL, pal::overlay1, pos, ALIGN_RIGHT);
  const int th = s.paragraph(MARGIN, capY(FONT_TITLE, 34), SCREEN_WIDTH - 2 * MARGIN, FONT_TITLE, pal::text, e.title, 2, -2);
  const int sep = 34 + th + 2;
  s.rect(MARGIN, sep, SCREEN_WIDTH - 2 * MARGIN, 1, 0, pal::surface0);

  // Texto con desplazamiento: se parte en líneas una vez por nota
  static TextLine lines[220];
  static char tail[160];
  static int total = 0;
  static uint32_t wrappedVer = 0xFFFFFFFF;
  const int textW = SCREEN_WIDTH - 2 * MARGIN - 10, lh = FONT_BODY.lineHeight() + 2, top = sep + 10;
  const int page = (206 - top) / lh;
  const notes::State cs = notes::contentState();
  if (cs == notes::READY && wrappedVer != notes::contentVersion()) {
    total = wrapText(FONT_BODY, notes::text(), textW, lines, 220, tail, sizeof tail);
    while (total && lines[total - 1].len == 0) total--;  // sin líneas vacías al final
    wrappedVer = notes::contentVersion();
  }
  if (cs != notes::READY) {
    s.text(MARGIN, capY(FONT_BODY, top + 4), FONT_BODY, pal::subtext0, "Cargando la nota…");
    st.readLines = 0;
  } else if (!total) {
    s.text(MARGIN, capY(FONT_BODY, top + 4), FONT_BODY, pal::subtext0, "Esta nota no tiene texto todavía.");
    st.readLines = 0;
  } else {
    st.readLines = total;
    st.readPage = page;
    if (st.readLine > total - page) st.readLine = total - page > 0 ? total - page : 0;
    const int y = top - (FONT_BODY.ascent - fontGlyph(FONT_BODY, 'H')->h);
    for (int k = 0; k < page && st.readLine + k < total; k++) {
      const TextLine& L = lines[st.readLine + k];
      if (L.len) s.text(MARGIN, y + k * lh, FONT_BODY, pal::subtext1, L.start, ALIGN_LEFT, L.len);
    }
    if (total > page) {  // barra de desplazamiento
      const int trackH = page * lh, thumb = trackH * page / total > 14 ? trackH * page / total : 14;
      const int ty = top + (trackH - thumb) * st.readLine / (total - page);
      s.rect(SCREEN_WIDTH - 9, top, 3, trackH, 1, pal::surface0);
      s.rect(SCREEN_WIDTH - 9, ty, 3, thumb, 1, c);
    }
  }
  if (notes::openRequested()) {
    const char* msg = "Abriendo la nota en el PC…";
    const int w = textWidth(FONT_SMALL, msg) + 28;
    s.rect(SCREEN_WIDTH / 2 - w / 2, HINT_Y - 1, w, 20, 10, blend565(pal::base, pal::green, 60));
    s.text(SCREEN_WIDTH / 2, capY(FONT_SMALL, HINT_Y + 5), FONT_SMALL, pal::green, msg, ALIGN_CENTER);
  } else if (st.readLines > st.readPage) {
    static const char* const H[] = {KEY_UD, "Leer", KEY_LR, "Otra", "OK", "PC", "*", "Lista", nullptr};
    hints(s, HINT_Y, H);
  } else {
    static const char* const H[] = {KEY_LR, "Otra nota", "OK", "Abrir en el PC", "*", "Lista", nullptr};
    hints(s, HINT_Y, H);
  }
}

void buildNotes(Scene& s, const struct tm* t) {
  s.reset(pal::base);
  if (st.notesReading) buildNoteReader(s);
  if (!st.notesReading) buildNoteList(s, t);
}

// ─────────────────────────────────────────────
// Ajustes y estado del sistema
// ─────────────────────────────────────────────
static void infoCard(Scene& s, int x, int y, int w, int h, const char* title, uint16_t dot, const char* big, const char* small1,
                     const char* small2) {
  card(s, x, y, w, h);
  s.circle(x + 16, y + 15, 4, dot);
  s.text(x + 26, capY(FONT_SMALL, y + 11), FONT_SMALL, pal::subtext0, title);
  s.textFit(x + 12, capY(FONT_LABEL, y + 29), w - 24, FONT_LABEL, pal::text, big);
  if (small1) s.textFit(x + 12, capY(FONT_SMALL, y + 48), w - 24, FONT_SMALL, pal::subtext0, small1);
  if (small2) s.textFit(x + 12, capY(FONT_SMALL, y + 62), w - 24, FONT_SMALL, pal::subtext0, small2);
}

void buildSystem(Scene& s, const struct tm* t) {
  s.reset(pal::base);
  topBar(s, "Ajustes", t);
  SysInfo si;
  sysInfo(si);
  // Dos filas de tarjetas entre la barra superior y la línea de teclas común
  const int gx = MARGIN, gw = (SCREEN_WIDTH - 2 * MARGIN - 8) / 2, ch = (HINT_Y - 10 - 38 - 8) / 2;
  char a[48], b[48], c[48];
  // Red
  if (si.wifi) { snprintf(a, sizeof a, "%s", si.ip); snprintf(b, sizeof b, "Señal %s", si.rssi > -60 ? "buena" : si.rssi > -72 ? "media" : "débil"); }
  else { snprintf(a, sizeof a, "Sin conexión"); snprintf(b, sizeof b, "Reintentando…"); }
  snprintf(c, sizeof c, si.panelLinked ? "Panel conectado" : "Panel sin conectar");
  infoCard(s, gx, 38, gw, ch, "Red", si.wifi ? pal::green : pal::red, a, b, c);
  // Ambiente
  if (isnan(si.tempC)) { snprintf(a, sizeof a, "Sin sensor"); b[0] = 0; }
  else {
    snprintf(a, sizeof a, "%.1f °C", si.tempC);
    if (isnan(si.humidity)) b[0] = 0; else snprintf(b, sizeof b, "Humedad %.0f %%", si.humidity);
    for (char* p = a; *p; p++) if (*p == '.') *p = ',';
  }
  snprintf(c, sizeof c, "Chip %.0f °C", si.chipTempC);
  infoCard(s, gx + gw + 8, 38, gw, ch, "Ambiente", isnan(si.tempC) ? pal::overlay0 : pal::teal, a, b[0] ? b : nullptr, c);
  // Tarjeta SD
  if (si.sd) {
    snprintf(a, sizeof a, "SD lista");
    if (si.sdTotalMB >= 2048) {
      snprintf(b, sizeof b, "%.1f de %.0f GB", si.sdUsedMB / 1024.0, si.sdTotalMB / 1024.0);
      for (char* p = b; *p; p++) if (*p == '.') *p = ',';
    }
    else if (si.sdTotalMB) snprintf(b, sizeof b, "%lu de %lu MB", (unsigned long)si.sdUsedMB, (unsigned long)si.sdTotalMB);
    else b[0] = 0;
  } else { snprintf(a, sizeof a, "Sin tarjeta SD"); snprintf(b, sizeof b, "Se reintenta sola"); }
  infoCard(s, gx, 38 + ch + 8, gw, ch, "Almacenamiento", si.sd ? pal::green : pal::red, a, b[0] ? b : nullptr, nullptr);
  // Sistema
  const uint32_t up = si.uptimeSec;
  if (up >= 86400) snprintf(a, sizeof a, "%lu d %lu h", (unsigned long)(up / 86400), (unsigned long)(up % 86400 / 3600));
  else snprintf(a, sizeof a, "%lu h %02lu min", (unsigned long)(up / 3600), (unsigned long)(up % 3600 / 60));
  snprintf(b, sizeof b, "Libres %lu KB", (unsigned long)si.freeHeapKB);
  snprintf(c, sizeof c, "Hora %s", si.ntpSynced ? "sincronizada" : si.timeValid ? "del reloj" : "sin ajustar");
  infoCard(s, gx + gw + 8, 38 + ch + 8, gw, ch, "Encendido", si.timeValid ? pal::green : pal::yellow, a, b, c);
  // Aviso de eventos: va como etiqueta de las flechas, en la misma línea que el resto de pantallas
  if (st.bannerDays) snprintf(a, sizeof a, "Aviso %d %s antes", st.bannerDays, st.bannerDays == 1 ? "día" : "días");
  else snprintf(a, sizeof a, "Aviso el mismo día");
  const char* const H[] = {KEY_UD, a, "OK", "Reiniciar", nullptr};
  hints(s, HINT_Y, H);
}

void buildConfirm(Scene& s) {
  s.rect(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, pal::crust, 180);
  const int x = 40, y = 64, w = SCREEN_WIDTH - 80, h = 112;
  card(s, x, y, w, h);
  s.text(SCREEN_WIDTH / 2, capY(FONT_TITLE, y + 22), FONT_TITLE, pal::text, "¿Reiniciar?", ALIGN_CENTER);
  s.text(SCREEN_WIDTH / 2, capY(FONT_SMALL, y + 52), FONT_SMALL, pal::subtext0, "Vuelve en unos segundos", ALIGN_CENTER);
  static const char* const H[] = {"OK", "Reiniciar", "*", "Cancelar", nullptr};
  hints(s, y + h - 30, H);
}

void buildToast(Scene& s) {
  const int w = textWidth(FONT_SMALL, st.toast) + 28;
  const int y = st.screen == CLOCK && st.modal == M_NONE ? 128 : 186;
  s.rect(SCREEN_WIDTH / 2 - w / 2, y, w, 24, 12, pal::surface2);
  s.text(SCREEN_WIDTH / 2, capY(FONT_SMALL, y + 7), FONT_SMALL, pal::text, st.toast, ALIGN_CENTER);
}

}  // namespace ui
