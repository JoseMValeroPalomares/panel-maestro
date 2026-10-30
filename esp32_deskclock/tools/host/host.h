// Control de la plataforma simulada del PC (tests y capturas).
#pragma once
#include <time.h>

#include <map>
#include <string>
#include <vector>

#include "../../src/platform/platform.h"

namespace host {
extern std::string root;            // carpeta que hace de tarjeta SD
extern uint32_t ms;                 // millis() simulado
extern bool timeValid;
extern struct tm localTime;
extern bool sdOk;
extern std::vector<std::string> sent;  // mensajes enviados por WebSocket
extern std::map<std::string, int32_t> prefs;
extern SysInfo sys;
extern bool restartRequested;
}  // namespace host
