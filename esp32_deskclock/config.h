#ifndef CONFIG_H
#define CONFIG_H

// ================== RED ==================
// Credenciales en secrets.h (no se sube a git; plantilla en secrets.example.h)
#include "secrets.h"
#define HOSTNAME      "panel-estudio"

// El táctil no está cableado: el firmware se maneja con el mando IR.

// ================== PINES ==================
// TFT y tactil definidos en User_Setup.h / build_and_upload.sh:
// TFT_CS 15, TFT_DC 2, TFT_RST 4, MOSI 23, SCK 18, MISO 19, TOUCH_CS 21

#define PIN_SD_CS     5
#define PIN_RTC_SDA   32
#define PIN_RTC_SCL   33
#define PIN_IR_RECV   34

// El buzzer se ha quitado; en su lugar (mismo pin, GPIO25) va el DHT22/AM2302.
#define PIN_DHT       25
#define DHT_SENSOR_TYPE DHT22

#endif
