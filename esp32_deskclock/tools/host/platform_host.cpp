// Plataforma del PC: archivos en un directorio temporal, hora y sensores simulados.
#include <errno.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include <map>
#include <string>
#include <vector>

#include "../../src/platform/platform.h"
#include "../../src/core/util.h"
#include "host.h"

namespace host {
std::string root = "/tmp/esp32-host";
uint32_t ms = 1000;
bool timeValid = true;
struct tm localTime = {};
bool sdOk = true;
std::vector<std::string> sent;
std::map<std::string, int32_t> prefs;
SysInfo sys = {};
bool restartRequested = false;
}  // namespace host

static std::string full(const char* p) { return host::root + p; }

uint32_t nowMs() { return host::ms; }
bool localNow(struct tm& out) {
  if (!host::timeValid) return false;
  out = host::localTime;
  return true;
}
int32_t todayDays() {
  if (!host::timeValid) return 0;
  return daysFromCivil(host::localTime.tm_year + 1900, host::localTime.tm_mon + 1, host::localTime.tm_mday);
}
void logf(const char* fmt, ...) {
  if (getenv("HOST_QUIET")) return;
  va_list ap;
  va_start(ap, fmt);
  fprintf(stderr, "[log] ");
  vfprintf(stderr, fmt, ap);
  fprintf(stderr, "\n");
  va_end(ap);
}

bool fsReady() { return host::sdOk; }
bool fsExists(const char* p) { struct stat s; return host::sdOk && stat(full(p).c_str(), &s) == 0; }
bool fsRemove(const char* p) { return host::sdOk && unlink(full(p).c_str()) == 0; }
bool fsMkdir(const char* p) { return host::sdOk && (mkdir(full(p).c_str(), 0755) == 0 || errno == EEXIST); }
bool fsRename(const char* a, const char* b) { return host::sdOk && rename(full(a).c_str(), full(b).c_str()) == 0; }

static bool readAll(const std::string& path, char** data, size_t* len) {
  FILE* f = fopen(path.c_str(), "rb");
  if (!f) return false;
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  *data = (char*)malloc(n + 1);
  *len = fread(*data, 1, n, f);
  (*data)[*len] = 0;
  fclose(f);
  return true;
}

bool fsReadFile(const char* p, char** data, size_t* len) {
  if (!host::sdOk) return false;
  if (readAll(full(p), data, len)) return true;
  // recuperación como en el ESP32: .tmp completo o .bak
  if (readAll(full(p) + ".tmp", data, len) || readAll(full(p) + ".bak", data, len)) return true;
  return false;
}

bool fsWriteAtomic(const char* p, const char* data, size_t len) {
  if (!host::sdOk) return false;
  const std::string tmp = full(p) + ".tmp", bak = full(p) + ".bak";
  FILE* f = fopen(tmp.c_str(), "wb");
  if (!f) return false;
  const bool ok = fwrite(data, 1, len, f) == len;
  fclose(f);
  if (!ok) return false;
  unlink(bak.c_str());
  rename(full(p).c_str(), bak.c_str());
  if (rename(tmp.c_str(), full(p).c_str()) != 0) return false;
  unlink(bak.c_str());
  return true;
}

bool fsReadAt(const char* p, uint32_t off, uint8_t* buf, size_t len) {
  FILE* f = fopen(full(p).c_str(), "rb");
  if (!f) return false;
  fseek(f, off, SEEK_SET);
  const bool ok = fread(buf, 1, len, f) == len;
  fclose(f);
  return ok;
}

int32_t prefGet(const char* k, int32_t def) {
  auto it = host::prefs.find(k);
  return it == host::prefs.end() ? def : it->second;
}
void prefSet(const char* k, int32_t v) { host::prefs[k] = v; }

void netBroadcast(const char* json, size_t len) { host::sent.emplace_back(json, len); }

void sysInfo(SysInfo& out) { out = host::sys; }
void requestRestart() { host::restartRequested = true; }
