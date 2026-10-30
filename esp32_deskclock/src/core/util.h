// Utilidades sin dependencias del hardware: fechas, nombres de archivo seguros, colores en texto.
#pragma once
#include <stddef.h>
#include <stdint.h>

// ── Fechas (calendario gregoriano, días desde 1970-01-01) ─────────────
int32_t daysFromCivil(int y, int m, int d);
void civilFromDays(int32_t days, int& y, int& m, int& d);
int daysInMonth(int y, int m);
int weekdayMon0(int y, int m, int d);           // 0 = lunes … 6 = domingo
bool parseIsoDate(const char* s, int& y, int& m, int& d);  // "AAAA-MM-DD"
int32_t isoToDays(const char* s);               // INT32_MIN si no es válida
void daysToIso(int32_t days, char* out);        // out ≥ 11 bytes

extern const char* const MONTHS_ES[12];         // "enero"…
extern const char* const WEEKDAYS_ES[7];        // "lunes"…
extern const char* const WEEKDAYS_SHORT_ES[7];  // "L","M","X"…

// «hoy», «mañana», «en 3 días», «hace 2 días»
void relativeDayEs(int deltaDays, char* out, size_t size);
// Primera letra en mayúscula (UTF-8 simple: solo ASCII y las vocales con tilde / ñ)
void capitalizeEs(char* s);

// ── Texto ─────────────────────────────────────────────────────────────
// Nombre de archivo seguro: minúsculas ASCII, dígitos y guiones; quita tildes («Física 2» → «fisica-2»)
void slugify(const char* in, char* out, size_t size);
// Copia segura (siempre termina en 0)
void copyStr(char* dst, const char* src, size_t size);

// ── Color ─────────────────────────────────────────────────────────────
uint16_t parseHexColor565(const char* hex, uint16_t fallback);  // "#RRGGBB"
void color565ToHex(uint16_t c, char* out);                      // out ≥ 8 bytes
