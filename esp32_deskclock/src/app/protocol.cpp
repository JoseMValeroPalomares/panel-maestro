#include "protocol.h"

#include <ArduinoJson.h>
#include <stdlib.h>
#include <string.h>

#include "../core/util.h"
#include "../model/calendar.h"
#include "../model/lists.h"
#include "../model/media.h"
#include "../model/notes.h"
#include "../model/pomodoro.h"
#include "../platform/platform.h"
#include "../ui/ui.h"

namespace protocol {

static uint32_t lastPanelMs = 0;
uint32_t lastPanelMessageMs() { return lastPanelMs; }

void sendFullState() {
  ui::broadcastScreen();
  ui::broadcastReviewState();
  pomodoro::broadcastState();
  calendar::broadcastList();
  lists::broadcastCategories();
  look::broadcastState();
}

static bool is(const char* a, const char* b) { return strcmp(a, b) == 0; }

void handleText(const char* json, size_t len) {
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, json, len);
  if (err) { logf("ws: JSON no válido (%u bytes): %s", (unsigned)len, err.c_str()); return; }
  JsonObjectConst m = doc.as<JsonObjectConst>();
  const char* type = m["type"] | "";

  // Lo que manda el panel (puentes de estudio/): música, calendario de iCloud, repaso
  if (is(type, "nowplaying")) { lastPanelMs = nowMs(); music::update(m); return; }
  if (is(type, "review_note")) { lastPanelMs = nowMs(); review::receive(m); return; }
  if (is(type, "notes_list")) { lastPanelMs = nowMs(); notes::receiveList(m["notes"].as<JsonArrayConst>()); return; }
  if (is(type, "note_content")) { lastPanelMs = nowMs(); notes::receiveContent(m); return; }
  if (is(type, "calendar_sync_full")) { lastPanelMs = nowMs(); calendar::replaceAll(m["events"].as<JsonArrayConst>()); return; }

  // Web de Estudio
  if (is(type, "get_state")) { sendFullState(); return; }
  if (is(type, "review_set")) { ui::setReviewAuto(m["enabled"] | true); return; }
  if (is(type, "set_screen")) { ui::goTo((ui::Screen)(m["screen"] | 0)); return; }
  if (is(type, "pomodoro_set")) { pomodoro::setMinutes(m["work_min"] | 25, m["break_min"] | 5); return; }
  if (is(type, "pomodoro_cmd")) {
    const char* a = m["action"] | "";
    if (is(a, "start_pause")) pomodoro::toggle();
    else if (is(a, "reset")) pomodoro::reset();
    return;
  }
  if (is(type, "calendar_get")) { lastPanelMs = nowMs(); calendar::broadcastList(); return; }
  if (is(type, "calendar_add")) { calendar::add(m["date"] | "", m["title"] | "", m["etype"] | "evento"); return; }
  if (is(type, "calendar_edit")) {
    calendar::update(m["uid"] | "", m["index"] | -1, m["date"] | "", m["title"] | "", m["etype"] | "evento");
    return;
  }
  if (is(type, "calendar_delete")) { calendar::remove(m["uid"] | "", m["index"] | -1); return; }

  if (is(type, "checklist_get_categories")) { lists::broadcastCategories(); return; }
  if (is(type, "checklist_get_items")) { lists::broadcastItems(m["category"] | ""); return; }
  if (is(type, "checklist_add_category")) { lists::addCategory(m["name"] | ""); return; }
  if (is(type, "checklist_delete_category")) { lists::deleteCategory(m["name"] | ""); return; }
  if (is(type, "checklist_add_item")) { lists::addItem(m["category"] | "", m["text"] | "", m["daily"] | false); return; }
  if (is(type, "checklist_edit_item")) {
    lists::editItem(m["category"] | "", m["id"] | 0, m["index"] | -1, m["text"] | "", m["daily"] | false);
    return;
  }
  if (is(type, "checklist_delete_item")) { lists::deleteItem(m["category"] | "", m["id"] | 0, m["index"] | -1); return; }
  if (is(type, "checklist_toggle_item")) { lists::toggleItem(m["category"] | "", m["id"] | 0, m["index"] | -1); return; }

  if (is(type, "background_set_manual_accent")) {
    const char* a = m["accent"] | "";
    const char* c = m["complementary"] | "";
    if (*a && *c) look::setManualAccent(parseHexColor565(a, 0), parseHexColor565(c, 0));
    return;
  }
  if (is(type, "background_set_color")) { look::setColor(parseHexColor565(m["color"] | "", 0)); return; }
  if (is(type, "background_reset")) { look::setAuto(); return; }

  // Mensajes que solo van del ESP32 al panel (los reenvía a todos, como antes)
  if (is(type, "cmd") || is(type, "open_note_request") || is(type, "notes_list_request") || is(type, "note_request")) {
    netBroadcast(json, len);
    return;
  }
  logf("ws: tipo de mensaje desconocido «%s»", type);
}

void handleBinary(uint8_t* frame, size_t len) {
  if (len < 4) { free(frame); return; }
  const uint16_t w = (uint16_t)((frame[0] << 8) | frame[1]), h = (uint16_t)((frame[2] << 8) | frame[3]);
  if (w == 160 && h == 120) {  // fondo personalizado subido desde la web
    const bool ok = look::setImage(frame, len);
    free(frame);
    ui::toast(ok ? "Fondo guardado" : "No se pudo guardar el fondo (¿hay SD?)");
    return;
  }
  lastPanelMs = nowMs();
  music::setCover(frame, len);  // carátula: se queda con el búfer
}

}  // namespace protocol
