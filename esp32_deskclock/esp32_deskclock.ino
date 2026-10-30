// =====================================================================
// Panel de estudio ESP32: reloj, música, repaso de notas, calendario,
// listas y pomodoro, conectado al panel del PC por WebSocket.
//
//   src/gfx     fuentes (Inter) y compositor por franjas, sin parpadeo
//   src/ui      pantallas y mando (lo único que dibuja)
//   src/model   calendario, listas, pomodoro, música, repaso, apariencia
//   src/app     protocolo WebSocket y hardware (pantalla, SD, red, hora, IR, DHT22)
//   tools/      generador de fuentes y compilación en el PC (tests y capturas)
//
// Regla de oro: la red solo encola mensajes; pantalla y SD se tocan solo desde loop().
// =====================================================================
#include "config.h"
#include "src/app/device.h"
#include "src/model/calendar.h"
#include "src/model/lists.h"
#include "src/model/media.h"
#include "src/model/pomodoro.h"
#include "src/platform/platform.h"
#include "src/ui/ui.h"

void setup() {
  Serial.begin(115200);
  logf("\n--- Panel ESP32: arrancando ---");
  device::beginDisplay();   // primero la pantalla: nunca se queda en negro esperando
  device::beginStorage();
  device::beginTime();
  calendar::load();
  lists::load();
  pomodoro::load();
  look::load();
  device::beginInputs();
  device::beginNetwork();   // el WiFi se conecta en segundo plano
  ui::invalidate();
}

void loop() {
  device::poll();
  pomodoro::tick();
  static uint32_t lastDaily = 0;
  if (nowMs() - lastDaily > 10000) {
    lastDaily = nowMs();
    lists::dailyTick(todayDays());
  }
  ui::tick();
  delay(2);  // cede la CPU a la red y al vigilante
}
