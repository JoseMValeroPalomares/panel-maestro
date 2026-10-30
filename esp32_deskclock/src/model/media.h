// Lo que llega del panel para mostrar: música que suena (con carátula), nota de repaso
// y el fondo/acento personalizado.
#pragma once
#include <ArduinoJson.h>
#include <stdint.h>

namespace music {
void update(JsonObjectConst msg);            // {"type":"nowplaying", ...}
void setCover(uint8_t* frame, size_t len);   // toma el búfer (malloc): 4 bytes ancho/alto BE + RGB565 BE
bool active();                               // sonando o en pausa, con datos recientes
bool playing();
const char* title();
const char* artist();
uint32_t positionSec();
uint32_t durationSec();
uint16_t accent();                           // color dominante de la carátula
const uint8_t* coverPixels(uint16_t& w, uint16_t& h, uint32_t& version);  // nullptr si no hay
void sendCommand(const char* action);        // play_pause, next, previous, volume_up, volume_down
}  // namespace music

namespace review {
constexpr uint32_t SHOW_MS = 45000;          // tiempo en pantalla
void receive(JsonObjectConst msg);           // {"type":"review_note", note_id, title, category, snippet}
bool pending();
bool showing();
void show();
void dismiss();
void openOnPc();                             // pide al panel que abra la nota en el PC
float remaining();                           // 1 → 0 mientras se muestra
bool expired();
const char* title();
const char* category();
const char* snippet();
bool openRequested();                        // se acaba de pedir abrirla (para el mensaje de confirmación)
}  // namespace review

namespace look {
void load();
// Fondo personalizado (imagen 160×120 que se guarda en la SD) o color liso
bool hasImage();
uint16_t color();
void setColor(uint16_t c);
bool setImage(const uint8_t* frame, size_t len);
void baseRow(int y, int x, int w, uint16_t* out, void* ctx);  // fondo de cada fila para el compositor
// Acento: el de la carátula cuando suena música, o el elegido a mano desde la web
void setManualAccent(uint16_t accent, uint16_t complementary);
void setAuto();
uint16_t accent();       // color de acento que usa la interfaz ahora mismo
uint32_t version();      // cambia cuando cambia el fondo (para repintar)
void broadcastState();
}  // namespace look
