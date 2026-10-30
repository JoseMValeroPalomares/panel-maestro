#include "pomodoro.h"

#include <ArduinoJson.h>

#include "../platform/platform.h"

namespace pomodoro {

static uint16_t work = 25, brk = 5, streakDays = 0;
static int32_t lastStudyDay = 0;
static Phase ph = WORK;
static Run state = STOPPED;
static uint32_t startMs = 0, elapsedBefore = 0;
static bool finishedFlag = false;
static Phase finishedPhase = WORK;
static uint8_t motivationIdx = 0;

static const char* const MOTIVATION[] = {"Tú puedes", "Un paso más", "Sigue así", "Vas genial", "A por ello",
                                         "Ya casi", "Concéntrate", "Buen ritmo", "Constancia", "Paso a paso"};

void load() {
  work = (uint16_t)prefGet("work_min", 25);
  brk = (uint16_t)prefGet("break_min", 5);
  streakDays = (uint16_t)prefGet("streak", 0);
  lastStudyDay = prefGet("last_day", 0);
  if (work < 1 || work > 180) work = 25;
  if (brk < 1 || brk > 60) brk = 5;
}

Phase phase() { return ph; }
Run run() { return state; }
uint16_t workMin() { return work; }
uint16_t breakMin() { return brk; }
uint16_t streak() { return streakDays; }
const char* motivation() { return ph == WORK ? MOTIVATION[motivationIdx] : "Descansa un poco"; }
uint32_t totalSec() { return (uint32_t)(ph == WORK ? work : brk) * 60; }

static uint32_t elapsedMs() { return elapsedBefore + (state == RUNNING ? nowMs() - startMs : 0); }

uint32_t remainingSec() {
  const uint32_t total = totalSec() * 1000, el = elapsedMs();
  return el >= total ? 0 : (total - el + 999) / 1000;
}

static void registerStudy() {
  const int32_t today = todayDays();
  if (!today || today == lastStudyDay) return;
  streakDays = lastStudyDay == today - 1 ? streakDays + 1 : 1;
  lastStudyDay = today;
  prefSet("streak", streakDays);
  prefSet("last_day", lastStudyDay);
}

void tick() {
  if (state != RUNNING || remainingSec() > 0) return;
  finishedPhase = ph;
  finishedFlag = true;
  if (ph == WORK) registerStudy();
  ph = ph == WORK ? BREAK : WORK;
  if (ph == WORK) motivationIdx = (uint8_t)((motivationIdx + 3) % (sizeof MOTIVATION / sizeof MOTIVATION[0]));
  elapsedBefore = 0;
  startMs = nowMs();
  broadcastState();
}

bool takeFinished(Phase& p) {
  if (!finishedFlag) return false;
  finishedFlag = false;
  p = finishedPhase;
  return true;
}

void toggle() {
  if (state == STOPPED) {
    ph = WORK;
    elapsedBefore = 0;
    startMs = nowMs();
    state = RUNNING;
    motivationIdx = (uint8_t)(nowMs() % (sizeof MOTIVATION / sizeof MOTIVATION[0]));
  } else if (state == RUNNING) {
    elapsedBefore += nowMs() - startMs;
    state = PAUSED;
  } else {
    startMs = nowMs();
    state = RUNNING;
  }
  broadcastState();
}

void reset() {
  state = STOPPED;
  ph = WORK;
  elapsedBefore = 0;
  broadcastState();
}

void setMinutes(int w, int b) {
  work = (uint16_t)(w < 1 ? 1 : w > 180 ? 180 : w);
  brk = (uint16_t)(b < 1 ? 1 : b > 60 ? 60 : b);
  prefSet("work_min", work);
  prefSet("break_min", brk);
  broadcastState();
}

void broadcastState() {
  JsonDocument doc;
  doc["type"] = "pomodoro_state";
  doc["work_min"] = work;
  doc["break_min"] = brk;
  doc["phase"] = ph == WORK ? "work" : "break";
  doc["run_state"] = state == RUNNING ? "running" : state == PAUSED ? "paused" : "stopped";
  doc["remaining_sec"] = remainingSec();
  doc["streak_days"] = streakDays;
  char buf[200];
  netBroadcast(buf, serializeJson(doc, buf, sizeof buf));
}

}  // namespace pomodoro
