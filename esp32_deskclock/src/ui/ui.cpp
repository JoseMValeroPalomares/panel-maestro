#include <ArduinoJson.h>
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

State st;

static Canvas* canvas = nullptr;
static Scene scene;
static SceneDiff differ;
static uint32_t lastFrame = 0;
static bool forceFrame = true;

void begin(Canvas* c) {
  canvas = c;
  st.bannerDays = prefGet("banner_days", 2);
  if (st.bannerDays < 0 || st.bannerDays > 14) st.bannerDays = 2;
  st.reviewAuto = prefGet("review_auto", 1) != 0;
  differ.invalidate();
}

Screen current() { return st.screen; }
int bannerDays() { return st.bannerDays; }

void setBannerDays(int d) {
  st.bannerDays = d < 0 ? 0 : d > 14 ? 14 : d;
  prefSet("banner_days", st.bannerDays);
}

bool reviewAuto() { return st.reviewAuto; }

void setReviewAuto(bool on) {
  st.reviewAuto = on;
  prefSet("review_auto", on ? 1 : 0);
  if (!on && st.modal == M_REVIEW) { review::dismiss(); st.modal = M_NONE; }
  forceFrame = true;
  broadcastReviewState();
}

void broadcastReviewState() {
  JsonDocument doc;
  doc["type"] = "review_state";
  doc["enabled"] = st.reviewAuto;
  char buf[64];
  netBroadcast(buf, serializeJson(doc, buf, sizeof buf));
}

void invalidate() {
  differ.invalidate();
  forceFrame = true;
}

void broadcastScreen() {
  JsonDocument doc;
  doc["type"] = "screen_changed";
  doc["screen"] = (int)st.screen;
  char buf[64];
  netBroadcast(buf, serializeJson(doc, buf, sizeof buf));
}

static void openModal(Modal m) {
  st.modal = m;
  st.modalSince = nowMs();
  forceFrame = true;
}

static void closeModal() {
  st.modal = M_NONE;
  forceFrame = true;
}

void goTo(Screen s) {
  if (s >= SCREEN_COUNT) return;
  if (st.modal == M_DAY || st.modal == M_CONFIRM) closeModal();
  if (s == CALENDAR && st.screen != CALENDAR) st.calCursor = todayDays();
  if (s == LISTS && st.screen != LISTS) { st.listsOpen = false; st.listsSel = st.listsScroll = 0; }
  if (s == NOTES && st.screen != NOTES) { st.notesReading = false; notes::requestList(); }  // la lista se refresca al entrar
  st.screen = s;
  forceFrame = true;
  broadcastScreen();
}

void toast(const char* text) {
  copyStr(st.toast, text, sizeof st.toast);
  st.toastUntil = nowMs() + 2600;
  forceFrame = true;
}

// ── Mando ─────────────────────────────────────────────────────────────
static constexpr int LIST_ROWS = 5;

// Pantalla vecina en el recorrido con las flechas (dir = -1 / +1)
static Screen neighbor(int dir) {
  int i = 0;
  while (i < SCREEN_COUNT && SCREEN_ORDER[i] != st.screen) i++;
  return SCREEN_ORDER[(i + dir + SCREEN_COUNT) % SCREEN_COUNT];
}

static void notesKey(Key k, bool repeat) {
  const int n = notes::count();
  if (!st.notesReading) {
    if (k == K_UP && st.notesSel > 0) st.notesSel--;
    else if (k == K_DOWN && st.notesSel < n - 1) st.notesSel++;
    else if (k == K_OK && !repeat && n) { notes::open(st.notesSel); st.notesReading = true; st.readLine = 0; }
    else if ((k == K_LEFT || k == K_RIGHT) && !repeat) { goTo(neighbor(k == K_LEFT ? -1 : 1)); return; }
  } else {
    if (k == K_UP && st.readLine > 0) st.readLine--;
    else if (k == K_DOWN && st.readLine < st.readLines - st.readPage) st.readLine++;
    else if ((k == K_LEFT || k == K_RIGHT) && !repeat && n) {  // nota anterior / siguiente
      st.notesSel = (st.notesSel + (k == K_LEFT ? n - 1 : 1)) % n;
      notes::open(st.notesSel);
      st.readLine = 0;
    } else if (k == K_OK && !repeat) notes::openOnPc();
    else if (k == K_BACK && !repeat) st.notesReading = false;
  }
  if (st.notesSel >= n) st.notesSel = n ? n - 1 : 0;
  if (st.notesSel < st.notesScroll) st.notesScroll = st.notesSel;
  if (st.notesSel >= st.notesScroll + NOTE_ROWS) st.notesScroll = st.notesSel - NOTE_ROWS + 1;
}

static void listsKey(Key k) {
  const int nCats = lists::categoryCount();
  if (!st.listsOpen) {
    if (k == K_UP && st.listsSel > 0) st.listsSel--;
    else if (k == K_DOWN && st.listsSel < nCats - 1) st.listsSel++;
    else if (k == K_OK && nCats) { st.listsOpen = true; st.listsCat = st.listsSel; st.listsSel = st.listsScroll = 0; return; }
  } else {
    if (st.listsCat >= nCats) { st.listsOpen = false; return; }
    int idx[lists::MAX_ITEMS];
    const int n = lists::itemsOf(lists::category(st.listsCat).id, idx, lists::MAX_ITEMS);
    if (k == K_UP && st.listsSel > 0) st.listsSel--;
    else if (k == K_DOWN && st.listsSel < n - 1) st.listsSel++;
    else if (k == K_OK && n) {
      const lists::Item& it = lists::item(idx[st.listsSel]);
      const bool willBeDone = !it.done;
      lists::toggleItemById(it.id);
      toast(willBeDone ? "Hecha" : "Pendiente otra vez");
    } else if (k == K_BACK) {
      st.listsOpen = false;
      st.listsSel = st.listsCat;
      st.listsScroll = 0;
      return;
    }
  }
  if (st.listsSel < st.listsScroll) st.listsScroll = st.listsSel;
  if (st.listsSel >= st.listsScroll + LIST_ROWS) st.listsScroll = st.listsSel - LIST_ROWS + 1;
}

static void modalKey(Key k) {
  switch (st.modal) {
    case M_REVIEW:
      if (k == K_OK) { review::openOnPc(); forceFrame = true; }
      else if (k == K_BACK || k == K_HOME) { review::dismiss(); closeModal(); }
      break;
    case M_DAY:
      if (k == K_BACK || k == K_OK || k == K_HOME) closeModal();
      else if (k == K_LEFT || k == K_RIGHT) st.calCursor += k == K_LEFT ? -1 : 1;
      break;
    case M_ALERT:
      closeModal();
      break;
    case M_CONFIRM:
      if (k == K_OK) requestRestart();
      closeModal();
      break;
    default: break;
  }
}

void key(Key k, bool repeat) {
  forceFrame = true;
  // Los números cambian de pantalla siempre (como antes): 1 reloj, 2 calendario, 3 listas, 4 pomodoro, 5 ajustes, 0 notas
  if (!repeat && ((k >= K_1 && k <= K_5) || k == K_0)) {
    if (st.modal == M_REVIEW) { review::dismiss(); closeModal(); }
    goTo((Screen)(k == K_0 ? NOTES : k == K_1 ? CLOCK : k == K_2 ? CALENDAR : k == K_3 ? LISTS : k == K_4 ? POMODORO : SYSTEM));
    return;
  }
  if (!repeat && k >= K_6 && k <= K_8) {
    static const int presets[3][2] = {{25, 5}, {50, 10}, {90, 15}};
    const int* p = presets[k - K_6];
    pomodoro::setMinutes(p[0], p[1]);
    char t[48];
    snprintf(t, sizeof t, "Pomodoro %d + %d min", p[0], p[1]);
    toast(t);
    return;
  }
  if (!repeat && k == K_9 && review::pending()) {  // ver ya la nota de repaso que espera
    goTo(CLOCK);
    review::show();
    openModal(M_REVIEW);
    return;
  }
  if (st.modal != M_NONE) { if (!repeat) modalKey(k); return; }
  if (k == K_HOME && !repeat) { goTo(CLOCK); return; }
  // Las flechas izquierda/derecha cambian de pantalla donde no tienen otro uso
  switch (st.screen) {
    case CLOCK:
      if (music::active()) {
        if (k == K_OK && !repeat) music::sendCommand("play_pause");
        else if (k == K_LEFT && !repeat) music::sendCommand("previous");
        else if (k == K_RIGHT && !repeat) music::sendCommand("next");
        else if (k == K_UP) music::sendCommand("volume_up");
        else if (k == K_DOWN) music::sendCommand("volume_down");
      } else if ((k == K_LEFT || k == K_RIGHT) && !repeat) goTo(neighbor(k == K_LEFT ? -1 : 1));
      break;
    case CALENDAR:
      if (k == K_LEFT) st.calCursor--;
      else if (k == K_RIGHT) st.calCursor++;
      else if (k == K_UP) st.calCursor -= 7;
      else if (k == K_DOWN) st.calCursor += 7;
      else if (k == K_OK && !repeat) openModal(M_DAY);
      else if (k == K_BACK && !repeat) st.calCursor = todayDays();
      break;
    case LISTS:
      if ((k == K_LEFT || k == K_RIGHT) && !repeat && !st.listsOpen) goTo(neighbor(k == K_LEFT ? -1 : 1));
      else if (!repeat || k == K_UP || k == K_DOWN) listsKey(k);
      break;
    case POMODORO: {
      const bool stopped = pomodoro::run() == pomodoro::STOPPED;
      if (k == K_OK && !repeat) pomodoro::toggle();
      else if (k == K_BACK && !repeat) { pomodoro::reset(); toast("Pomodoro reiniciado"); }
      else if (stopped && (k == K_UP || k == K_DOWN))
        pomodoro::setMinutes(pomodoro::workMin() + (k == K_UP ? 1 : -1), pomodoro::breakMin());
      else if (stopped && (k == K_LEFT || k == K_RIGHT))
        pomodoro::setMinutes(pomodoro::workMin(), pomodoro::breakMin() + (k == K_RIGHT ? 1 : -1));
      else if (!stopped && !repeat && (k == K_LEFT || k == K_RIGHT)) goTo(neighbor(k == K_LEFT ? -1 : 1));
      break;
    }
    case SYSTEM:
      if (k == K_UP || k == K_DOWN) setBannerDays(st.bannerDays + (k == K_UP ? 1 : -1));
      else if (k == K_OK && !repeat) openModal(M_CONFIRM);
      else if ((k == K_LEFT || k == K_RIGHT) && !repeat) goTo(neighbor(k == K_LEFT ? -1 : 1));
      break;
    case NOTES:
      notesKey(k, repeat);
      break;
    default: break;
  }
}

// ── Composición ───────────────────────────────────────────────────────
void build(Scene& s) {
  struct tm now;
  const struct tm* t = localNow(now) ? &now : nullptr;
  if (st.modal == M_REVIEW) {
    buildReview(s);
  } else {
    switch (st.screen) {
      case CLOCK: music::active() ? buildMusic(s, t) : buildClock(s, t); break;
      case CALENDAR: buildCalendar(s, t); break;
      case LISTS: buildLists(s, t); break;
      case POMODORO: buildPomodoro(s, t); break;
      case SYSTEM: buildSystem(s, t); break;
      case NOTES: buildNotes(s, t); break;
      default: buildClock(s, t); break;
    }
    if (st.modal == M_DAY) buildDayModal(s);
    else if (st.modal == M_ALERT) buildAlert(s);
    else if (st.modal == M_CONFIRM) buildConfirm(s);
  }
  if (st.toastUntil && nowMs() < st.toastUntil) buildToast(s);
}

static void autoModals() {
  // Nota de repaso: aparece sola en el reloj (también con música) y desaparece al rato, salvo que
  // se haya desactivado desde la web (sigue esperando: el 9 la muestra)
  if (st.modal == M_REVIEW && (!review::showing() || review::expired())) { review::dismiss(); closeModal(); }
  // Notas: si el panel no ha contestado, se vuelve a pedir la lista (cada pocos segundos)
  if (st.screen == NOTES && notes::listState() == notes::LOADING) notes::requestList();
  if (st.reviewAuto && st.modal == M_NONE && st.screen == CLOCK && review::pending()) { review::show(); openModal(M_REVIEW); }
  // Fin de una fase del pomodoro: aviso en cualquier pantalla (si no se está leyendo una nota)
  pomodoro::Phase finished;
  if (st.modal != M_REVIEW && pomodoro::takeFinished(finished)) {
    st.alertPhase = finished;
    openModal(M_ALERT);
  }
  if (st.modal == M_ALERT && nowMs() - st.modalSince > 12000) closeModal();
  if (st.toastUntil && nowMs() >= st.toastUntil) { st.toastUntil = 0; forceFrame = true; }
}

void tick() {
  autoModals();
  const uint32_t now = nowMs();
  if (!forceFrame && now - lastFrame < 80) return;  // ~12 fotogramas por segundo como mucho
  lastFrame = now;
  forceFrame = false;
  scene.reset(pal::base);
  build(scene);
  Rect dirty[SceneDiff::MAX_RECTS];
  const int n = differ.diff(scene, dirty);
  if (!canvas) return;
  for (int i = 0; i < n; i++) scene.render(*canvas, dirty[i]);
}

}  // namespace ui
