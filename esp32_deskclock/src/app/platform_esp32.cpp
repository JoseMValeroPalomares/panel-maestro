// Implementación de platform.h en el ESP32: SD, NVS, hora del sistema y estado.
#ifdef ARDUINO
#include <Arduino.h>
#include <Preferences.h>
#include <SD.h>
#include <SPI.h>
#include <WiFi.h>
#include <stdarg.h>

#include "../../config.h"
#include "../platform/platform.h"
#include "device_internal.h"

// ─────────────────────────────────────────────
// Tiempo y registro
// ─────────────────────────────────────────────
uint32_t nowMs() { return millis(); }

bool localNow(struct tm& out) {
  const time_t t = time(nullptr);
  localtime_r(&t, &out);
  return out.tm_year + 1900 >= 2024;
}

int32_t todayDays() {
  struct tm t;
  if (!localNow(t)) return 0;
  // días desde 1970 de la fecha LOCAL
  int y = t.tm_year + 1900, m = t.tm_mon + 1;
  y -= m <= 2;
  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = (unsigned)(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + t.tm_mday - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + (int32_t)doe - 719468;
}

void logf(const char* fmt, ...) {
  char buf[200];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof buf, fmt, ap);
  va_end(ap);
  Serial.println(buf);
}

// ─────────────────────────────────────────────
// SD (comparte el bus SPI con la pantalla: todo desde loop(), con transacciones)
// ─────────────────────────────────────────────
static bool sdOk = false;
static uint32_t sdCheckedMs = 0;
static File readAtFile;
static char readAtPath[40] = "";

static void closeReadAt() {
  if (readAtFile) readAtFile.close();
  readAtPath[0] = 0;
}

bool device_sdMount() {
  closeReadAt();
  SD.end();
  // 16 MHz; si la tarjeta no responde, se prueba despacio (cables largos o tarjetas antiguas)
  sdOk = SD.begin(PIN_SD_CS, device_spi(), 16000000) || SD.begin(PIN_SD_CS, device_spi(), 4000000);
  sdCheckedMs = millis();
  if (sdOk) logf("SD montada (%llu MB)", SD.cardSize() / (1024ULL * 1024ULL));
  else logf("SD no disponible");
  return sdOk;
}

// Si falla, se reintenta cada 15 s; si estaba bien, se comprueba cada 30 s que siga ahí
void device_sdPoll() {
  const uint32_t now = millis();
  if (!sdOk && now - sdCheckedMs > 15000) {
    if (device_sdMount()) device_onSdMounted();
  } else if (sdOk && now - sdCheckedMs > 30000) {
    sdCheckedMs = now;
    File root = SD.open("/");
    if (!root) { logf("SD: la tarjeta ha dejado de responder"); sdOk = false; closeReadAt(); }
    else root.close();
  }
}

static void sdFailed() {
  // Un fallo de E/S: se comprobará el montaje en la siguiente vuelta
  sdCheckedMs = 0;
}

bool fsReady() { return sdOk; }
bool fsExists(const char* p) { return sdOk && SD.exists(p); }
bool fsRemove(const char* p) { return sdOk && SD.remove(p); }
bool fsMkdir(const char* p) { return sdOk && (SD.exists(p) || SD.mkdir(p)); }
bool fsRename(const char* a, const char* b) {
  if (!sdOk) return false;
  if (!strcmp(a, readAtPath) || !strcmp(b, readAtPath)) closeReadAt();
  return SD.rename(a, b);
}

static bool readWhole(const char* path, char** data, size_t* len) {
  File f = SD.open(path, FILE_READ);
  if (!f) return false;
  const size_t n = f.size();
  char* buf = (char*)malloc(n + 1);
  if (!buf) { f.close(); logf("SD: sin memoria para leer %s (%u B)", path, (unsigned)n); return false; }
  const size_t got = f.read((uint8_t*)buf, n);
  f.close();
  if (got != n) { free(buf); sdFailed(); return false; }
  buf[n] = 0;
  *data = buf;
  *len = n;
  return true;
}

bool fsReadFile(const char* path, char** data, size_t* len) {
  if (!sdOk) return false;
  if (SD.exists(path)) return readWhole(path, data, len);
  // El original falta: un corte de luz entre los dos renombrados. El .tmp está completo.
  char alt[72];
  snprintf(alt, sizeof alt, "%s.tmp", path);
  if (SD.exists(alt) && readWhole(alt, data, len)) { logf("SD: recuperado %s", alt); return true; }
  snprintf(alt, sizeof alt, "%s.bak", path);
  if (SD.exists(alt) && readWhole(alt, data, len)) { logf("SD: recuperado %s", alt); return true; }
  return false;
}

bool fsWriteAtomic(const char* path, const char* data, size_t len) {
  if (!sdOk) return false;
  if (!strcmp(path, readAtPath)) closeReadAt();
  char tmp[72], bak[72];
  snprintf(tmp, sizeof tmp, "%s.tmp", path);
  snprintf(bak, sizeof bak, "%s.bak", path);
  SD.remove(tmp);
  File f = SD.open(tmp, FILE_WRITE);
  if (!f) { sdFailed(); return false; }
  const size_t wrote = f.write((const uint8_t*)data, len);
  f.flush();
  f.close();
  if (wrote != len) { SD.remove(tmp); sdFailed(); return false; }
  SD.remove(bak);
  if (SD.exists(path) && !SD.rename(path, bak)) { sdFailed(); return false; }
  if (!SD.rename(tmp, path)) { SD.rename(bak, path); sdFailed(); return false; }
  SD.remove(bak);
  return true;
}

bool fsReadAt(const char* path, uint32_t offset, uint8_t* buf, size_t len) {
  if (!sdOk) return false;
  if (strcmp(path, readAtPath) != 0 || !readAtFile) {
    closeReadAt();
    readAtFile = SD.open(path, FILE_READ);
    if (!readAtFile) return false;
    strlcpy(readAtPath, path, sizeof readAtPath);
  }
  if (!readAtFile.seek(offset)) return false;
  return readAtFile.read(buf, len) == len;
}

// ─────────────────────────────────────────────
// Preferencias (mismo espacio de nombres que el firmware anterior: conserva el pomodoro)
// ─────────────────────────────────────────────
static Preferences prefs;
static bool prefsOpen = false;

static void openPrefs() {
  if (!prefsOpen) prefsOpen = prefs.begin("estudio", false);
}

int32_t prefGet(const char* key, int32_t def) {
  openPrefs();
  return prefsOpen ? prefs.getInt(key, def) : def;
}

void prefSet(const char* key, int32_t value) {
  openPrefs();
  if (prefsOpen && prefs.getInt(key, value - 1) != value) prefs.putInt(key, value);  // sin escribir si no cambia
}

// ─────────────────────────────────────────────
// Estado del sistema
// ─────────────────────────────────────────────
void sysInfo(SysInfo& o) {
  memset(&o, 0, sizeof o);
  o.wifi = WiFi.status() == WL_CONNECTED;
  o.rssi = o.wifi ? WiFi.RSSI() : 0;
  strlcpy(o.ip, o.wifi ? WiFi.localIP().toString().c_str() : "", sizeof o.ip);
  strlcpy(o.host, HOSTNAME, sizeof o.host);
  device_netInfo(o);
  o.sd = sdOk;
  static uint32_t sizeCheckedMs = 0, totalMB = 0, usedMB = 0;
  if (sdOk && (!sizeCheckedMs || millis() - sizeCheckedMs > 60000)) {
    sizeCheckedMs = millis();
    totalMB = (uint32_t)(SD.totalBytes() / (1024ULL * 1024ULL));
    usedMB = (uint32_t)(SD.usedBytes() / (1024ULL * 1024ULL));
  }
  o.sdTotalMB = sdOk ? totalMB : 0;
  o.sdUsedMB = sdOk ? usedMB : 0;
  struct tm t;
  o.timeValid = localNow(t);
  device_timeInfo(o);
  o.freeHeapKB = ESP.getFreeHeap() / 1024;
  o.minHeapKB = ESP.getMinFreeHeap() / 1024;
  o.uptimeSec = millis() / 1000;
  device_envInfo(o);
  o.chipTempC = temperatureRead();
}

static bool restartPending = false;
void requestRestart() { restartPending = true; }
bool device_restartPending() { return restartPending; }

#endif  // ARDUINO
