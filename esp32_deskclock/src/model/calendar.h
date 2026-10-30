// Eventos del calendario (exámenes, entregas, eventos), sincronizados con iCloud por el panel.
#pragma once
#include <ArduinoJson.h>
#include <stdint.h>

namespace calendar {

constexpr int MAX_EVENTS = 100;
constexpr const char* FILE_PATH = "/eventos.json";  // mismo archivo y formato que el firmware anterior

struct Event {
  char uid[48];
  int32_t day;     // días desde 1970
  char title[64];
  char type[12];   // "evento" | "examen" | "entrega"
};

void load();
int count();
const Event& at(int i);  // ordenados por fecha

// Las operaciones aceptan uid (preferido) o el índice de la lista que se envió (web antigua)
bool add(const char* isoDate, const char* title, const char* type);
bool update(const char* uid, int index, const char* isoDate, const char* title, const char* type);
bool remove(const char* uid, int index);
// Sustituye la lista entera por la que envía el puente de iCloud
void replaceAll(JsonArrayConst events);

int eventsOn(int32_t day, int* outIdx, int maxOut);
int firstFrom(int32_t day);  // índice del primer evento desde ese día, o -1
uint16_t colorFor(const char* type);

void broadcastList();

}  // namespace calendar
