// Mensajes WebSocket del panel y de la web de Estudio → modelos e interfaz.
// Se llaman SIEMPRE desde loop() (la red solo encola), nunca desde la tarea de red.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace protocol {
void handleText(const char* json, size_t len);
void handleBinary(uint8_t* frame, size_t len);  // toma el búfer (malloc)
void sendFullState();
uint32_t lastPanelMessageMs();  // para saber si el panel está enlazado
}  // namespace protocol
