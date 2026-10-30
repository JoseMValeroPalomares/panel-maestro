// Lo que la lógica necesita del hardware. Dos implementaciones:
//   platform_esp32.cpp (SD, NVS, WebSocket, hora del sistema) y tools/host/platform_host.cpp (PC, para tests).
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <time.h>

uint32_t nowMs();
// Hora local (Europe/Madrid). Devuelve false si aún no hay hora válida (sin RTC ni NTP).
bool localNow(struct tm& out);
int32_t todayDays();  // días desde 1970 de la fecha local (0 si no hay hora)
void logf(const char* fmt, ...);

// ── Almacenamiento (SD) ───────────────────────────────────────────────
// Escritura atómica: se escribe <ruta>.tmp y se renombra, así un corte de luz deja
// el archivo viejo o el nuevo, nunca uno a medias. readFile recupera <ruta>.tmp/.bak
// si el original falta.
bool fsReady();
bool fsReadFile(const char* path, char** data, size_t* len);  // *data con malloc; liberar con free()
bool fsWriteAtomic(const char* path, const char* data, size_t len);
bool fsExists(const char* path);
bool fsRemove(const char* path);
bool fsMkdir(const char* path);
bool fsRename(const char* from, const char* to);
// Lee len bytes desde offset (para el fondo personalizado, fila a fila, sin cargarlo entero en RAM)
bool fsReadAt(const char* path, uint32_t offset, uint8_t* buf, size_t len);

// ── Preferencias (NVS) ────────────────────────────────────────────────
int32_t prefGet(const char* key, int32_t def);
void prefSet(const char* key, int32_t value);

// ── Red: mensaje a todos los clientes WebSocket ───────────────────────
void netBroadcast(const char* json, size_t len);

// ── Estado del sistema (pantalla de Ajustes) ──────────────────────────
struct SysInfo {
  bool wifi;          // conectado
  int rssi;           // dBm
  char ip[16];
  char host[32];
  int clients;        // clientes WebSocket (panel y navegadores)
  bool panelLinked;   // el panel ha hablado en el último minuto
  bool sd;
  uint32_t sdTotalMB, sdUsedMB;
  bool timeValid;
  bool ntpSynced;     // alguna vez desde el arranque
  bool rtcOk;
  uint32_t freeHeapKB, minHeapKB, uptimeSec;
  float tempC, humidity;  // NAN si el sensor no responde
  float chipTempC;
};
void sysInfo(SysInfo& out);
void requestRestart();
