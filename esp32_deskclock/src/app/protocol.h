// Mensajes WebSocket del panel y de la web de Estudio → modelos e interfaz.
// Se llaman SIEMPRE desde loop() (la red solo encola), nunca desde la tarea de red.
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace protocol {
void handleText(const char* json, size_t len);
void handleBinary(uint8_t* frame, size_t len);  // toma el búfer (malloc)
void sendFullState();
// Latido: quién soy y cómo estoy (IP, MAC, versión, memoria, señal). El panel lo usa para saber dónde está la placa
// sin que nadie escriba su IP (core/red.py); se manda cada 30 s y al conectarse un cliente.
void sendHeartbeat();
uint32_t lastPanelMessageMs();  // para saber si el panel está enlazado
}  // namespace protocol
