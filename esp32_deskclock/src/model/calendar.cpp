#include "calendar.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../core/util.h"
#include "../gfx/color.h"
#include "../platform/platform.h"

namespace calendar {

static Event events[MAX_EVENTS];
static int n = 0;

int count() { return n; }
const Event& at(int i) { return events[i]; }

static void normalizeType(const char* in, char* out) {
  if (in && (!strcmp(in, "examen") || !strcmp(in, "entrega") || !strcmp(in, "evento"))) copyStr(out, in, sizeof(Event::type));
  else copyStr(out, "evento", sizeof(Event::type));
}

static void newUid(char* out) {
  static uint32_t seq = 0;
  snprintf(out, sizeof(Event::uid), "%08lX-%04X@panel-estudio", (unsigned long)(time(nullptr) & 0xFFFFFFFF),
           (unsigned)((nowMs() + ++seq * 7919) & 0xFFFF));
}

static void sortEvents() {
  for (int i = 1; i < n; i++) {
    Event key = events[i];
    int j = i - 1;
    while (j >= 0 && events[j].day > key.day) { events[j + 1] = events[j]; j--; }
    events[j + 1] = key;
  }
}

static bool fill(Event& e, const char* uid, const char* isoDate, const char* title, const char* type) {
  const int32_t day = isoToDays(isoDate);
  if (day == INT32_MIN || !title || !*title) return false;
  if (uid && *uid) copyStr(e.uid, uid, sizeof e.uid); else newUid(e.uid);
  e.day = day;
  copyStr(e.title, title, sizeof e.title);
  normalizeType(type, e.type);
  return true;
}

static void save() {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  char iso[11];
  for (int i = 0; i < n; i++) {
    JsonObject o = arr.add<JsonObject>();
    daysToIso(events[i].day, iso);
    o["uid"] = events[i].uid;
    o["date"] = iso;
    o["title"] = events[i].title;
    o["type"] = events[i].type;
  }
  const size_t len = measureJson(doc);
  char* buf = (char*)malloc(len + 1);
  if (!buf) { logf("calendario: sin memoria para guardar"); return; }
  serializeJson(doc, buf, len + 1);
  if (!fsWriteAtomic(FILE_PATH, buf, len)) logf("calendario: no se pudo guardar en la SD");
  free(buf);
}

void load() {
  n = 0;
  char* data = nullptr;
  size_t len = 0;
  if (!fsReadFile(FILE_PATH, &data, &len)) return;
  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, data, len);
  free(data);
  if (err) {
    logf("calendario: %s ilegible (%s); se aparta", FILE_PATH, err.c_str());
    fsRename(FILE_PATH, "/eventos.ilegible.json");  // que un guardado no lo pise
    return;
  }
  for (JsonObjectConst o : doc.as<JsonArrayConst>()) {
    if (n >= MAX_EVENTS) break;
    if (fill(events[n], o["uid"] | "", o["date"] | "", o["title"] | "", o["type"] | "evento")) n++;
  }
  sortEvents();
  logf("calendario: %d eventos", n);
}

static int find(const char* uid, int index) {
  if (uid && *uid) {
    for (int i = 0; i < n; i++)
      if (!strcmp(events[i].uid, uid)) return i;
    return -1;
  }
  return index >= 0 && index < n ? index : -1;
}

static void changed() {
  sortEvents();
  save();
  broadcastList();
}

static void error(const char* message) {
  JsonDocument doc;
  doc["type"] = "error";
  doc["message"] = message;
  char buf[200];
  netBroadcast(buf, serializeJson(doc, buf, sizeof buf));
}

bool add(const char* isoDate, const char* title, const char* type) {
  if (n >= MAX_EVENTS) { error("El calendario está lleno: borra algún evento antiguo."); return false; }
  if (!fill(events[n], nullptr, isoDate, title, type)) { error("Fecha o título no válidos."); return false; }
  n++;
  changed();
  return true;
}

bool update(const char* uid, int index, const char* isoDate, const char* title, const char* type) {
  const int i = find(uid, index);
  if (i < 0) { error("Ese evento ya no existe: recarga la lista."); broadcastList(); return false; }
  Event e = events[i];
  if (!fill(e, events[i].uid, isoDate, title, type)) { error("Fecha o título no válidos."); return false; }
  events[i] = e;
  changed();
  return true;
}

bool remove(const char* uid, int index) {
  const int i = find(uid, index);
  if (i < 0) { broadcastList(); return false; }
  memmove(&events[i], &events[i + 1], sizeof(Event) * (n - i - 1));
  n--;
  changed();
  return true;
}

void replaceAll(JsonArrayConst list) {
  int m = 0;
  for (JsonObjectConst o : list) {
    if (m >= MAX_EVENTS) break;
    if (fill(events[m], o["uid"] | "", o["date"] | "", o["title"] | "", o["type"] | "evento")) m++;
  }
  n = m;
  changed();
  logf("calendario: sincronizado (%d eventos)", n);
}

int eventsOn(int32_t day, int* outIdx, int maxOut) {
  int k = 0;
  for (int i = 0; i < n && k < maxOut; i++)
    if (events[i].day == day) outIdx[k++] = i;
  return k;
}

int firstFrom(int32_t day) {
  for (int i = 0; i < n; i++)
    if (events[i].day >= day) return i;
  return -1;
}

uint16_t colorFor(const char* type) {
  if (!strcmp(type, "examen")) return pal::red;
  if (!strcmp(type, "entrega")) return pal::peach;
  return pal::blue;
}

void broadcastList() {
  JsonDocument doc;
  doc["type"] = "calendar_list";
  JsonArray arr = doc["events"].to<JsonArray>();
  const int32_t today = todayDays();
  char iso[11];
  for (int i = 0; i < n; i++) {
    JsonObject o = arr.add<JsonObject>();
    daysToIso(events[i].day, iso);
    o["uid"] = events[i].uid;
    o["date"] = iso;
    o["title"] = events[i].title;
    o["type"] = events[i].type;
    o["days_until"] = today ? events[i].day - today : 0;
  }
  const size_t len = measureJson(doc);
  char* buf = (char*)malloc(len + 1);
  if (!buf) return;
  serializeJson(doc, buf, len + 1);
  netBroadcast(buf, len);
  free(buf);
}

}  // namespace calendar
