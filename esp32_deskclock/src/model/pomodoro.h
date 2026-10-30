// Temporizador Pomodoro (trabajo / descanso) con racha de días de estudio.
#pragma once
#include <stdint.h>

namespace pomodoro {

enum Phase : uint8_t { WORK, BREAK };
enum Run : uint8_t { STOPPED, RUNNING, PAUSED };

void load();
void tick();                 // cambia de fase al acabar (llamar siempre, en cualquier pantalla)
void toggle();               // iniciar / pausar / seguir
void reset();
void setMinutes(int workMin, int breakMin);

Phase phase();
Run run();
uint16_t workMin();
uint16_t breakMin();
uint32_t remainingSec();
uint32_t totalSec();
uint16_t streak();
const char* motivation();
// true una vez cuando termina una fase (para avisar aunque se esté en otra pantalla)
bool takeFinished(Phase& finished);

void broadcastState();

}  // namespace pomodoro
