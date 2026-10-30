// Enlaces entre platform_esp32.cpp y device.cpp (solo en el ESP32).
#pragma once
#ifdef ARDUINO
#include <SPI.h>

#include "../platform/platform.h"

SPIClass& device_spi();
bool device_sdMount();
void device_sdPoll();
void device_onSdMounted();       // recarga los datos al volver la tarjeta
void device_netInfo(SysInfo& o);
void device_timeInfo(SysInfo& o);
void device_envInfo(SysInfo& o);
bool device_restartPending();
#endif
