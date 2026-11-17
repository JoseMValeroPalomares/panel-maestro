// Parte del firmware que solo existe en el ESP32: pantalla, SD, red, hora, mando y sensor.
#pragma once
#include <stdint.h>

namespace device {
void beginDisplay();
void beginStorage();
void beginTime();        // TZ de Madrid, hora del RTC y NTP en segundo plano
void beginNetwork();     // WiFi sin bloquear + servidor WebSocket
void beginInputs();      // mando IR y sensor DHT22
void beginWatchdog();    // lo último de setup(): si loop() se cuelga 20 s, la placa se reinicia sola
void poll();             // red (cola de mensajes), mando, sensor, SD, hora: llamar en cada vuelta de loop()
}  // namespace device
