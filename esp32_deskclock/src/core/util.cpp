#include "util.h"

#include <limits.h>

#include <initializer_list>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../gfx/color.h"

// Algoritmos de Howard Hinnant (dominio público)
int32_t daysFromCivil(int y, int m, int d) {
  y -= m <= 2;
  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = (unsigned)(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + (int32_t)doe - 719468;
}

void civilFromDays(int32_t z, int& y, int& m, int& d) {
  z += 719468;
  const int era = (z >= 0 ? z : z - 146096) / 146097;
  const unsigned doe = (unsigned)(z - era * 146097);
  const unsigned yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
  y = (int)yoe + era * 400;
  const unsigned doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
  const unsigned mp = (5 * doy + 2) / 153;
  d = (int)(doy - (153 * mp + 2) / 5 + 1);
  m = (int)(mp < 10 ? mp + 3 : mp - 9);
  y += m <= 2;
}

int daysInMonth(int y, int m) {
  static const int base[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (m < 1 || m > 12) return 30;
  if (m == 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0)) return 29;
  return base[m - 1];
}

int weekdayMon0(int y, int m, int d) {
  const int32_t days = daysFromCivil(y, m, d);  // 1970-01-01 fue jueves (3)
  return (int)(((days % 7) + 7 + 3) % 7);
}

bool parseIsoDate(const char* s, int& y, int& m, int& d) {
  if (!s || strlen(s) < 10 || s[4] != '-' || s[7] != '-') return false;
  for (int i : {0, 1, 2, 3, 5, 6, 8, 9})
    if (s[i] < '0' || s[i] > '9') return false;
  y = atoi(s);
  m = atoi(s + 5);
  d = atoi(s + 8);
  return y >= 2000 && y <= 2100 && m >= 1 && m <= 12 && d >= 1 && d <= daysInMonth(y, m);
}

int32_t isoToDays(const char* s) {
  int y, m, d;
  return parseIsoDate(s, y, m, d) ? daysFromCivil(y, m, d) : INT32_MIN;
}

void daysToIso(int32_t days, char* out) {
  int y, m, d;
  civilFromDays(days, y, m, d);
  snprintf(out, 11, "%04d-%02d-%02d", y, m, d);
}

const char* const MONTHS_ES[12] = {"enero", "febrero", "marzo", "abril", "mayo", "junio",
                                   "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"};
const char* const WEEKDAYS_ES[7] = {"lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"};
const char* const WEEKDAYS_SHORT_ES[7] = {"L", "M", "X", "J", "V", "S", "D"};

void relativeDayEs(int delta, char* out, size_t size) {
  if (delta == 0) snprintf(out, size, "hoy");
  else if (delta == 1) snprintf(out, size, "mañana");
  else if (delta == -1) snprintf(out, size, "ayer");
  else if (delta > 1) snprintf(out, size, "en %d días", delta);
  else snprintf(out, size, "hace %d días", -delta);
}

void capitalizeEs(char* s) {
  if (!s || !*s) return;
  if (s[0] >= 'a' && s[0] <= 'z') { s[0] = (char)(s[0] - 32); return; }
  // á é í ó ú ñ (C3 A1…) → Á É Í Ó Ú Ñ (C3 81…): mismo segundo byte menos 0x20
  if ((uint8_t)s[0] == 0xC3 && (uint8_t)s[1] >= 0xA0 && (uint8_t)s[1] <= 0xBE) s[1] = (char)((uint8_t)s[1] - 0x20);
}

void slugify(const char* in, char* out, size_t size) {
  static const char* const FROM[] = {"á", "à", "ä", "â", "é", "è", "ë", "ê", "í", "ì", "ï", "î", "ó", "ò", "ö", "ô",
                                     "ú", "ù", "ü", "û", "ñ", "ç", "Á", "É", "Í", "Ó", "Ú", "Ü", "Ñ", "Ç"};
  static const char TO[] = "aaaaeeeeiiiioooouuuuncaeiouunc";
  size_t n = 0;
  bool dash = false;
  const char* p = in ? in : "";
  while (*p && n + 1 < size) {
    char c = 0;
    bool matched = false;
    for (size_t i = 0; i < sizeof(FROM) / sizeof(FROM[0]); i++) {
      const size_t l = strlen(FROM[i]);
      if (strncmp(p, FROM[i], l) == 0) { c = TO[i]; p += l; matched = true; break; }
    }
    if (!matched) {
      c = *p++;
      if ((uint8_t)c >= 0x80) {  // otro carácter no ASCII: se salta entero
        while ((*p & 0xC0) == 0x80) p++;
        c = '-';
      }
    }
    if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
    const bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
    if (ok) { out[n++] = c; dash = false; }
    else if (!dash && n) { out[n++] = '-'; dash = true; }
  }
  while (n && out[n - 1] == '-') n--;
  if (!n && size > 4) { strcpy(out, "sin-nombre"); return; }
  out[n] = 0;
}

void copyStr(char* dst, const char* src, size_t size) {
  if (!size) return;
  strncpy(dst, src ? src : "", size - 1);
  dst[size - 1] = 0;
  // no dejar un carácter UTF-8 a medias al final
  size_t n = strlen(dst);
  size_t i = n;
  while (i > 0 && ((uint8_t)dst[i - 1] & 0xC0) == 0x80) i--;
  if (i > 0 && (uint8_t)dst[i - 1] >= 0xC0) {
    const uint8_t lead = (uint8_t)dst[i - 1];
    const size_t need = lead >= 0xF0 ? 4 : lead >= 0xE0 ? 3 : 2;
    if (n - (i - 1) < need) dst[i - 1] = 0;
  }
}

uint16_t parseHexColor565(const char* hex, uint16_t fallback) {
  if (!hex) return fallback;
  if (*hex == '#') hex++;
  if (strlen(hex) != 6) return fallback;
  char* end;
  const long v = strtol(hex, &end, 16);
  if (*end) return fallback;
  return hex565((uint32_t)v);
}

void color565ToHex(uint16_t c, char* out) {
  int r, g, b;
  unpack565(c, r, g, b);
  snprintf(out, 8, "#%02X%02X%02X", r, g, b);
}
