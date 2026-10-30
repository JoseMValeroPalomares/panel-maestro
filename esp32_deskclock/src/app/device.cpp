// Hardware del panel: pantalla ILI9341, RTC DS3231 + NTP, WiFi + WebSocket, mando IR y DHT22.
#ifdef ARDUINO
#include "device.h"

#include <Arduino.h>
#include <AsyncTCP.h>
#include <DHT.h>
#include <ESPAsyncWebServer.h>
#include <ESPmDNS.h>
#include <IRremote.hpp>
#include <RTClib.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_sntp.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <sys/time.h>

#include "../../config.h"
#include "../gfx/scene.h"
#include "../model/calendar.h"
#include "../model/lists.h"
#include "../model/media.h"
#include "../ui/ui.h"
#include "device_internal.h"
#include "protocol.h"

namespace {

// ═════════════════════════════════════════════════════════════════════
// Pantalla
// ═════════════════════════════════════════════════════════════════════
TFT_eSPI tft;

class TftCanvas : public Canvas {
 public:
  void pushRows(int x, int y, int w, int h, const uint16_t* px) override {
    tft.pushImage(x, y, w, h, const_cast<uint16_t*>(px));
  }
} canvas;

// ═════════════════════════════════════════════════════════════════════
// Hora: el sistema lleva UTC y la zona de Madrid (cambio de hora automático).
// El RTC guarda UTC; al arrancar sin WiFi la hora sale del RTC; el NTP corrige
// el sistema cada 6 h y, de paso, el RTC.
// ═════════════════════════════════════════════════════════════════════
constexpr const char* TZ_MADRID = "CET-1CEST,M3.5.0,M10.5.0/3";
RTC_DS3231 rtc;
bool rtcOk = false;
volatile bool ntpJustSynced = false;
bool ntpEver = false;

void onNtpSync(struct timeval*) { ntpJustSynced = true; }

void timePoll() {
  if (!ntpJustSynced) return;
  ntpJustSynced = false;
  ntpEver = true;
  const time_t now = time(nullptr);
  if (rtcOk) {
    rtc.adjust(DateTime((uint32_t)now));
    prefSet("rtc_utc", 1);
  }
  logf("hora: sincronizada por NTP");
  ui::invalidate();
}

// ═════════════════════════════════════════════════════════════════════
// Red: la tarea de AsyncTCP solo junta los trozos del mensaje y lo encola;
// loop() lo procesa (nada de pantalla ni SD desde la tarea de red).
// ═════════════════════════════════════════════════════════════════════
AsyncWebServer server(80);
AsyncWebSocket ws("/ws");

struct Msg {
  uint8_t* data;
  size_t len;
  bool binary;
};
QueueHandle_t inbox = nullptr;
volatile size_t queuedBytes = 0;
constexpr size_t MAX_TEXT = 32 * 1024, MAX_BINARY = 48 * 1024, MAX_QUEUED = 120 * 1024;

struct Assembly {
  uint32_t client = 0;
  uint8_t* buf = nullptr;
  size_t len = 0, cap = 0;
  bool binary = false, active = false;
};
Assembly slots[4];

Assembly* slotFor(uint32_t client, bool create) {
  for (auto& s : slots)
    if (s.active && s.client == client) return &s;
  if (!create) return nullptr;
  for (auto& s : slots)
    if (!s.active) { s = Assembly(); s.client = client; s.active = true; return &s; }
  return nullptr;
}

void dropSlot(Assembly* s) {
  if (!s) return;
  free(s->buf);
  *s = Assembly();
}

void onWsEvent(AsyncWebSocket*, AsyncWebSocketClient* client, AwsEventType type, void* arg, uint8_t* data, size_t len) {
  if (type == WS_EVT_DISCONNECT) { dropSlot(slotFor(client->id(), false)); return; }
  if (type != WS_EVT_DATA) return;
  const AwsFrameInfo* info = (const AwsFrameInfo*)arg;
  const bool binary = info->message_opcode == WS_BINARY;
  const size_t limit = binary ? MAX_BINARY : MAX_TEXT;
  Assembly* s = slotFor(client->id(), false);
  if (info->num == 0 && info->index == 0) {  // empieza un mensaje
    dropSlot(s);
    s = slotFor(client->id(), true);
    if (!s) return;
    s->binary = binary;
  }
  if (!s) return;
  if (s->len + len > limit) { dropSlot(s); return; }
  if (s->len + len > s->cap) {
    const size_t want = info->final && info->num == 0 ? info->len : (s->len + len) * 2;
    const size_t cap = want > limit ? limit : want < s->len + len ? s->len + len : want;
    uint8_t* nb = (uint8_t*)realloc(s->buf, cap + 1);
    if (!nb) { dropSlot(s); return; }
    s->buf = nb;
    s->cap = cap;
  }
  memcpy(s->buf + s->len, data, len);
  s->len += len;
  if (!(info->final && info->index + len == info->len)) return;  // faltan trozos
  if (queuedBytes + s->len > MAX_QUEUED) { dropSlot(s); return; }  // loop() no da abasto: se descarta
  s->buf[s->len] = 0;
  Msg m{s->buf, s->len, s->binary};
  if (xQueueSend(inbox, &m, 0) == pdTRUE) {
    queuedBytes += m.len;
    s->buf = nullptr;  // ahora es de la cola
  }
  dropSlot(s);
}

void netProcess() {
  Msg m;
  for (int i = 0; i < 6 && xQueueReceive(inbox, &m, 0) == pdTRUE; i++) {
    queuedBytes -= m.len;
    if (m.binary) protocol::handleBinary(m.data, m.len);  // se queda el búfer
    else { protocol::handleText((const char*)m.data, m.len); free(m.data); }
  }
}

uint32_t wifiLostMs = 0;
bool mdnsUp = false;

void wifiPoll() {
  static uint32_t lastCheck = 0;
  if (millis() - lastCheck < 2000) return;
  lastCheck = millis();
  if (WiFi.status() == WL_CONNECTED) {
    wifiLostMs = 0;
    if (!mdnsUp) {
      mdnsUp = MDNS.begin(HOSTNAME);
      if (mdnsUp) MDNS.addService("http", "tcp", 80);
      logf("WiFi: %s (%d dBm)", WiFi.localIP().toString().c_str(), WiFi.RSSI());
    }
    return;
  }
  if (!wifiLostMs) wifiLostMs = millis();
  // La reconexión automática del ESP32 suele bastar; si tras 30 s no hay red, se empieza de cero
  if (millis() - wifiLostMs > 30000) {
    logf("WiFi: sin conexión desde hace 30 s, reconectando");
    mdnsUp = false;
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    wifiLostMs = millis();
  }
}

// ═════════════════════════════════════════════════════════════════════
// Mando IR (HX1838, NEC): se usa el código de comando, así funcionan las repeticiones
// ═════════════════════════════════════════════════════════════════════
bool irKey(uint8_t command, ui::Key& k) {
  switch (command) {
    case 0x18: k = ui::K_UP; return true;
    case 0x52: k = ui::K_DOWN; return true;
    case 0x08: k = ui::K_LEFT; return true;
    case 0x5A: k = ui::K_RIGHT; return true;
    case 0x1C: k = ui::K_OK; return true;
    case 0x16: k = ui::K_BACK; return true;  // *
    case 0x0D: k = ui::K_HOME; return true;  // #
    case 0x19: k = ui::K_0; return true;
    case 0x45: k = ui::K_1; return true;
    case 0x46: k = ui::K_2; return true;
    case 0x47: k = ui::K_3; return true;
    case 0x44: k = ui::K_4; return true;
    case 0x40: k = ui::K_5; return true;
    case 0x43: k = ui::K_6; return true;
    case 0x07: k = ui::K_7; return true;
    case 0x15: k = ui::K_8; return true;
    case 0x09: k = ui::K_9; return true;
    default: return false;
  }
}

void irPoll() {
  static uint32_t holdStart = 0, lastRepeat = 0;
  static ui::Key held = ui::K_OK;
  if (!IrReceiver.decode()) return;
  const IRData& d = IrReceiver.decodedIRData;
  const bool repeat = d.flags & IRDATA_FLAGS_IS_REPEAT;
  ui::Key k;
  if (d.protocol == NEC && irKey((uint8_t)d.command, k)) {
    const uint32_t now = millis();
    if (!repeat) {
      held = k;
      holdStart = lastRepeat = now;
      ui::key(k, false);
    } else if (k == held && (k <= ui::K_RIGHT) && now - holdStart > 400 && now - lastRepeat > 140) {
      lastRepeat = now;
      ui::key(k, true);  // mantener pulsada una flecha: repetir
    }
  }
  IrReceiver.resume();
}

// ═════════════════════════════════════════════════════════════════════
// DHT22: se lee cada 30 s y solo con el mando en reposo (desactiva las
// interrupciones unos milisegundos y se perderían pulsaciones)
// ═════════════════════════════════════════════════════════════════════
DHT dht(PIN_DHT, DHT_SENSOR_TYPE);
float tempC = NAN, humidity = NAN;
uint32_t lastDht = 0, lastDhtOk = 0;

void dhtPoll() {
  const uint32_t now = millis();
  if (lastDht && now - lastDht < 30000) return;
  if (!IrReceiver.isIdle()) return;
  lastDht = now;
  if (dht.read()) {
    const float t = dht.readTemperature(), h = dht.readHumidity();  // usan la lectura de arriba
    if (!isnan(t) && t > -20 && t < 70) { tempC = t; lastDhtOk = now; }
    if (!isnan(h) && h >= 0 && h <= 100) humidity = h;
  }
  if (lastDhtOk && now - lastDhtOk > 5 * 60000) { tempC = humidity = NAN; }  // sensor desconectado
}

}  // namespace

// ═════════════════════════════════════════════════════════════════════
// Enlaces con platform_esp32.cpp
// ═════════════════════════════════════════════════════════════════════
SPIClass& device_spi() { return tft.getSPIinstance(); }

void device_onSdMounted() {
  calendar::load();
  lists::load();
  look::load();
  ui::invalidate();
}

void device_netInfo(SysInfo& o) {
  o.clients = (int)ws.count();
  const uint32_t last = protocol::lastPanelMessageMs();
  o.panelLinked = last && millis() - last < 60000;
}

void device_timeInfo(SysInfo& o) {
  o.ntpSynced = ntpEver;
  o.rtcOk = rtcOk;
}

void device_envInfo(SysInfo& o) {
  o.tempC = tempC;
  o.humidity = humidity;
}

void netBroadcast(const char* json, size_t len) {
  if (ws.count()) ws.textAll(json, len);
}

// ═════════════════════════════════════════════════════════════════════
// API
// ═════════════════════════════════════════════════════════════════════
namespace device {

void beginDisplay() {
  tft.init();
  tft.setRotation(3);
  tft.setSwapBytes(true);
  tft.fillScreen(0x18C3);  // pal::base, mientras arranca
  ui::begin(&canvas);
}

void beginStorage() {
  digitalWrite(TFT_CS, HIGH);  // la pantalla suelta el bus antes de hablar con la SD
  device_sdMount();
}

void beginTime() {
  setenv("TZ", TZ_MADRID, 1);
  tzset();
  Wire.begin(PIN_RTC_SDA, PIN_RTC_SCL);
  rtcOk = rtc.begin();
  if (rtcOk && !rtc.lostPower()) {
    uint32_t epoch = rtc.now().unixtime();
    if (prefGet("rtc_utc", 0) != 1) {
      // El firmware anterior guardaba la hora local: se interpreta como tal hasta el primer NTP
      struct tm t;
      const time_t local = (time_t)epoch;
      gmtime_r(&local, &t);
      t.tm_isdst = -1;
      epoch = (uint32_t)mktime(&t);
    }
    const struct timeval tv = {(time_t)epoch, 0};
    settimeofday(&tv, nullptr);
    logf("hora: tomada del RTC");
  } else {
    logf(rtcOk ? "hora: el RTC perdió la hora (¿pila?)" : "hora: RTC DS3231 no detectado");
  }
  sntp_set_time_sync_notification_cb(onNtpSync);
  sntp_set_sync_interval(6UL * 3600UL * 1000UL);
  configTzTime(TZ_MADRID, "pool.ntp.org", "time.google.com", "hora.roa.es");
}

void beginNetwork() {
  inbox = xQueueCreate(16, sizeof(Msg));
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);  // sin esperar: el reloj ya funciona con el RTC
  WiFi.setSleep(false);
  ws.onEvent(onWsEvent);
  server.addHandler(&ws);
  server.on("/", HTTP_GET, [](AsyncWebServerRequest* r) { r->send(200, "text/plain", "Panel de estudio ESP32"); });
  server.begin();
}

void beginInputs() {
  IrReceiver.begin(PIN_IR_RECV, DISABLE_LED_FEEDBACK);
  dht.begin();
}

void poll() {
  netProcess();
  irPoll();
  wifiPoll();
  dhtPoll();
  timePoll();
  device_sdPoll();
  static uint32_t lastClean = 0;
  // Con 4 se cerraban clientes en cadena: el panel tiene 2 conexiones fijas, más la web (PC y móvil)
  // y las conexiones cortas de la sincronización de iCloud
  if (millis() - lastClean > 1000) { lastClean = millis(); ws.cleanupClients(8); }
  if (device_restartPending()) {
    logf("reiniciando a petición del usuario");
    delay(200);
    ESP.restart();
  }
}

}  // namespace device
#endif  // ARDUINO
