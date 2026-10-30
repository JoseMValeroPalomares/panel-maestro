#include "media.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "../core/util.h"
#include "../gfx/color.h"
#include "../platform/platform.h"

static void sendSmall(JsonDocument& doc) {
  char buf[256];
  const size_t len = serializeJson(doc, buf, sizeof buf);
  if (len < sizeof buf) netBroadcast(buf, len);
}

// ═════════════════════════════════════════════════════════════════════
namespace music {

static char titleBuf[96] = "", artistBuf[96] = "";
static bool isPlaying = false, isPaused = false, hasData = false;
static uint32_t basePos = 0, duration = 0, updatedMs = 0;
static uint16_t accentColor = pal::blue;
static uint8_t* cover = nullptr;
static uint16_t coverW = 0, coverH = 0;
static uint32_t coverVersion = 0;
static constexpr uint32_t STALE_MS = 10000;  // sin noticias del panel en 10 s = no hay música

void update(JsonObjectConst m) {
  const char* status = m["status"] | "stopped";
  isPlaying = !strcmp(status, "playing");
  isPaused = !strcmp(status, "paused");
  hasData = true;
  updatedMs = nowMs();
  if (!isPlaying && !isPaused) return;
  const char* t = m["title"] | "";
  if (strcmp(t, titleBuf) != 0 && cover) {  // canción nueva: la carátula vieja ya no vale
    free(cover);
    cover = nullptr;
    coverVersion++;
  }
  copyStr(titleBuf, t, sizeof titleBuf);
  copyStr(artistBuf, m["artist"] | "", sizeof artistBuf);
  basePos = m["position_sec"] | 0;
  duration = m["duration_sec"] | 0;
  if (m["accent_color"].is<int>()) accentColor = (uint16_t)(m["accent_color"].as<int>());
}

void setCover(uint8_t* frame, size_t len) {
  const uint16_t w = (uint16_t)((frame[0] << 8) | frame[1]), h = (uint16_t)((frame[2] << 8) | frame[3]);
  if (!w || !h || w > 160 || h > 160 || len != 4u + (size_t)w * h * 2) { free(frame); return; }
  free(cover);
  cover = frame;  // se guarda con la cabecera; coverPixels() se la salta
  coverW = w;
  coverH = h;
  coverVersion++;
}

bool active() { return hasData && (isPlaying || isPaused) && nowMs() - updatedMs < STALE_MS; }
bool playing() { return active() && isPlaying; }
const char* title() { return titleBuf; }
const char* artist() { return artistBuf; }
uint32_t durationSec() { return duration; }
uint32_t positionSec() {
  uint32_t p = basePos + (isPlaying ? (nowMs() - updatedMs) / 1000 : 0);
  return duration && p > duration ? duration : p;
}
uint16_t accent() { return accentColor; }

const uint8_t* coverPixels(uint16_t& w, uint16_t& h, uint32_t& version) {
  version = coverVersion;
  if (!cover) return nullptr;
  w = coverW;
  h = coverH;
  return cover + 4;
}

void sendCommand(const char* action) {
  JsonDocument doc;
  doc["type"] = "cmd";
  doc["action"] = action;
  sendSmall(doc);
}

}  // namespace music

// ═════════════════════════════════════════════════════════════════════
namespace review {

static char noteId[96] = "", titleBuf[120] = "", categoryBuf[64] = "", snippetBuf[480] = "";
static bool hasNote = false, isShowing = false, opened = false;
static uint32_t shownAt = 0, openedAt = 0;

void receive(JsonObjectConst m) {
  const char* id = m["note_id"] | "";
  if (!*id) return;
  copyStr(noteId, id, sizeof noteId);
  copyStr(titleBuf, m["title"] | "", sizeof titleBuf);
  copyStr(categoryBuf, m["category"] | "", sizeof categoryBuf);
  copyStr(snippetBuf, m["snippet"] | "", sizeof snippetBuf);
  hasNote = true;
  if (isShowing) shownAt = nowMs();  // ya se veía una: se sustituye y empieza de nuevo
  opened = false;
}

bool pending() { return hasNote && !isShowing; }
bool showing() { return isShowing; }

void show() {
  if (!hasNote) return;
  isShowing = true;
  opened = false;
  shownAt = nowMs();
}

void dismiss() {
  isShowing = false;
  hasNote = false;  // ya se ha visto: hasta la siguiente que mande el panel
  opened = false;
}

void openOnPc() {
  JsonDocument doc;
  doc["type"] = "open_note_request";
  doc["note_id"] = noteId;
  sendSmall(doc);
  opened = true;
  openedAt = nowMs();
}

bool openRequested() { return opened && nowMs() - openedAt < 4000; }

float remaining() {
  if (!isShowing) return 0;
  const uint32_t el = nowMs() - shownAt;
  return el >= SHOW_MS ? 0 : 1.0f - (float)el / SHOW_MS;
}

bool expired() { return isShowing && nowMs() - shownAt >= SHOW_MS && !openRequested(); }

const char* title() { return titleBuf; }
const char* category() { return categoryBuf; }
const char* snippet() { return snippetBuf; }

}  // namespace review

// ═════════════════════════════════════════════════════════════════════
namespace look {

static constexpr const char* BG_FILE = "/background.bin";
static constexpr int BG_W = 160, BG_H = 120;
static bool image = false, manual = false;
static uint16_t bgColor = pal::base, manualAccent = pal::blue, manualComp = pal::peach;
static uint32_t ver = 1;

void load() {
  bgColor = (uint16_t)prefGet("bg_color", pal::base);
  manual = prefGet("accent_manual", 0) != 0;
  manualAccent = (uint16_t)prefGet("accent", pal::blue);
  manualComp = (uint16_t)prefGet("accent2", pal::peach);
  image = prefGet("bg_image", 0) && fsExists(BG_FILE);
}

bool hasImage() { return image && fsReady(); }
uint16_t color() { return bgColor; }
uint32_t version() { return ver; }

void setColor(uint16_t c) {
  bgColor = c;
  image = false;
  prefSet("bg_color", c);
  prefSet("bg_image", 0);
  ver++;
  broadcastState();
}

bool setImage(const uint8_t* frame, size_t len) {
  if (len != 4u + BG_W * BG_H * 2) return false;
  if (!fsWriteAtomic(BG_FILE, (const char*)frame, len)) return false;
  image = true;
  prefSet("bg_image", 1);
  ver++;
  broadcastState();
  return true;
}

void baseRow(int y, int x, int w, uint16_t* out, void*) {
  static uint8_t row[BG_W * 2];
  static int cachedRow = -1;
  static uint32_t cachedVer = 0;
  const int sy = y * BG_H / 240;
  if (sy != cachedRow || cachedVer != ver) {
    if (!fsReadAt(BG_FILE, 4u + (uint32_t)sy * BG_W * 2, row, sizeof row)) {
      for (int i = 0; i < w; i++) out[i] = bgColor;
      return;
    }
    cachedRow = sy;
    cachedVer = ver;
  }
  for (int i = 0; i < w; i++) {
    const int sx = (x + i) * BG_W / 320;
    out[i] = (uint16_t)((row[sx * 2] << 8) | row[sx * 2 + 1]);
  }
}

void setManualAccent(uint16_t a, uint16_t c) {
  manual = true;
  manualAccent = a;
  manualComp = c;
  prefSet("accent_manual", 1);
  prefSet("accent", a);
  prefSet("accent2", c);
  broadcastState();
}

void setAuto() {
  manual = false;
  prefSet("accent_manual", 0);
  setColor(pal::base);
}

// Lleva un color a la gama pastel de Catppuccin: legible sobre fondo oscuro
static uint16_t pastel(uint16_t c) {
  int r, g, b;
  unpack565(c, r, g, b);
  const float rf = r / 255.f, gf = g / 255.f, bf = b / 255.f;
  const float mx = fmaxf(rf, fmaxf(gf, bf)), mn = fminf(rf, fminf(gf, bf)), d = mx - mn;
  if (d < 0.08f) return pal::lavender;  // carátula gris: acento neutro de la paleta
  float h = mx == rf ? fmodf((gf - bf) / d, 6) : mx == gf ? (bf - rf) / d + 2 : (rf - gf) / d + 4;
  h *= 60;
  if (h < 0) h += 360;
  const float s = 0.62f, v = 0.96f, cc = v * s, xx = cc * (1 - fabsf(fmodf(h / 60, 2) - 1)), m = v - cc;
  float r2, g2, b2;
  if (h < 60) { r2 = cc; g2 = xx; b2 = 0; } else if (h < 120) { r2 = xx; g2 = cc; b2 = 0; }
  else if (h < 180) { r2 = 0; g2 = cc; b2 = xx; } else if (h < 240) { r2 = 0; g2 = xx; b2 = cc; }
  else if (h < 300) { r2 = xx; g2 = 0; b2 = cc; } else { r2 = cc; g2 = 0; b2 = xx; }
  return rgb565((uint8_t)((r2 + m) * 255), (uint8_t)((g2 + m) * 255), (uint8_t)((b2 + m) * 255));
}

uint16_t accent() {
  if (manual) return pastel(manualAccent);
  if (music::active()) return pastel(music::accent());
  return pal::blue;
}

void broadcastState() {
  JsonDocument doc;
  char c1[8], c2[8], c3[8];
  color565ToHex(bgColor, c1);
  color565ToHex(manualAccent, c2);
  color565ToHex(manualComp, c3);
  doc["type"] = "background_state";
  doc["mode"] = image ? "image" : "color";
  doc["color"] = c1;
  doc["accent_manual"] = manual;
  doc["manual_accent"] = c2;
  doc["manual_complementary"] = c3;
  sendSmall(doc);
}

}  // namespace look
