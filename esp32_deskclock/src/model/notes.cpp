#include "notes.h"

#include <stdlib.h>
#include <string.h>

#include "../core/util.h"
#include "../platform/platform.h"

namespace notes {

static Entry* entries = nullptr;  // en el montón: solo ocupa memoria si se usa la pantalla
static int n = 0;
static State listSt = EMPTY;
static uint32_t listAskedMs = 0;

static int current = -1;
static State contentSt = EMPTY;
static char* body = nullptr;
static uint32_t bodyVersion = 0, contentAskedMs = 0, openedAtMs = 0;
static bool opened = false;

static constexpr uint32_t RETRY_MS = 5000;

static void sendJson(JsonDocument& doc) {
  char buf[200];
  const size_t len = serializeJson(doc, buf, sizeof buf);
  if (len < sizeof buf) netBroadcast(buf, len);
}

void requestList() {
  if (listSt == LOADING && nowMs() - listAskedMs < RETRY_MS) return;
  JsonDocument doc;
  doc["type"] = "notes_list_request";
  sendJson(doc);
  listSt = LOADING;
  listAskedMs = nowMs();
}

// La lista llega por partes (part 0..parts-1, de ~2 KB): entera eran 15 KB de JSON y la placa no tenía memoria para
// analizarla (la descartaba en silencio y, con poca memoria libre, acababa en pánico). La parte 0 empieza la lista,
// las demás añaden, y solo la última la da por buena. Sin «part» (panel antiguo) es una lista entera, como antes.
static char keepId[sizeof(Entry::id)] = "";
static int nextPart = 0;

void receiveList(JsonArrayConst arr, int part, int parts) {
  if (!entries) entries = (Entry*)malloc(sizeof(Entry) * MAX_NOTES);
  if (!entries) { logf("notas: sin memoria para la lista"); listSt = EMPTY; return; }
  if (parts < 1) parts = 1;
  if (part == 0) {
    // Si la nota abierta sigue en la lista nueva, se conserva su posición
    keepId[0] = 0;
    if (current >= 0 && current < n) copyStr(keepId, entries[current].id, sizeof keepId);
    n = 0;
    if (parts > 1) listSt = LOADING;  // las partes llegan seguidas: «cargando» solo un instante
  } else if (part != nextPart) {
    if (listSt != LOADING) return;  // una parte suelta con la lista ya completa: nada que hacer
    logf("notas: parte %d fuera de orden (esperaba %d): se vuelve a pedir", part, nextPart);
    nextPart = 0;
    listAskedMs = 0;  // la pantalla la vuelve a pedir enseguida
    return;
  }
  nextPart = part + 1;
  for (JsonObjectConst o : arr) {
    if (n >= MAX_NOTES) break;
    const char* id = o["id"] | "";
    if (!*id) continue;
    copyStr(entries[n].id, id, sizeof entries[n].id);
    copyStr(entries[n].title, o["title"] | "(sin título)", sizeof entries[n].title);
    copyStr(entries[n].category, o["category"] | "", sizeof entries[n].category);
    n++;
  }
  if (part < parts - 1) return;  // faltan partes: sigue «cargando»
  nextPart = 0;
  listSt = READY;
  if (current >= 0) {
    current = -1;
    for (int i = 0; i < n; i++)
      if (!strcmp(entries[i].id, keepId)) { current = i; break; }
  }
}

State listState() { return listSt; }
int count() { return n; }
const Entry& at(int i) { return entries[i]; }

void open(int i) {
  if (i < 0 || i >= n) return;
  if (i == current && contentSt != EMPTY && !(contentSt == LOADING && nowMs() - contentAskedMs > RETRY_MS)) return;
  current = i;
  free(body);
  body = nullptr;
  bodyVersion++;
  opened = false;
  JsonDocument doc;
  doc["type"] = "note_request";
  doc["note_id"] = entries[i].id;
  sendJson(doc);
  contentSt = LOADING;
  contentAskedMs = nowMs();
}

void receiveContent(JsonObjectConst m) {
  const char* id = m["note_id"] | "";
  if (current < 0 || strcmp(id, entries[current].id)) return;  // respuesta de otra nota: ya no interesa
  const char* t = m["text"] | "";
  size_t len = strlen(t);
  if (len > MAX_TEXT) len = MAX_TEXT;
  while (len && ((uint8_t)t[len] & 0xC0) == 0x80) len--;  // no partir un carácter UTF-8
  char* b = (char*)malloc(len + 1);
  if (!b) { logf("notas: sin memoria para el texto (%u B)", (unsigned)len); return; }
  memcpy(b, t, len);
  b[len] = 0;
  free(body);
  body = b;
  bodyVersion++;
  contentSt = READY;
}

int openIndex() { return current; }
State contentState() {
  // Si el panel no contesta, se vuelve a pedir al rato
  if (contentSt == LOADING && current >= 0 && nowMs() - contentAskedMs > RETRY_MS) open(current);
  return contentSt;
}
const char* text() { return body ? body : ""; }
uint32_t contentVersion() { return bodyVersion; }

void openOnPc() {
  if (current < 0) return;
  JsonDocument doc;
  doc["type"] = "open_note_request";
  doc["note_id"] = entries[current].id;
  sendJson(doc);
  opened = true;
  openedAtMs = nowMs();
}

bool openRequested() { return opened && nowMs() - openedAtMs < 4000; }

}  // namespace notes
