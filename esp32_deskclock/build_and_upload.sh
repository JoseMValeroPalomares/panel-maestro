#!/bin/bash
# =====================================================================
# build_and_upload.sh
# Compila y sube el firmware del Panel ESP32 usando arduino-cli.
# =====================================================================

set -e

FQBN="esp32:esp32:esp32:PartitionScheme=huge_app"  # 3 MB para el programa (sin OTA ni SPIFFS, que no se usan)
SKETCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPILE_ONLY=false
PORT=""

for arg in "$@"; do
  case "$arg" in
    --compile-only) COMPILE_ONLY=true ;;
    /dev/*) PORT="$arg" ;;
  esac
done

echo "==> Directorio del sketch: $SKETCH_DIR"

if ! command -v arduino-cli &> /dev/null; then
  echo "ERROR: arduino-cli no esta instalado o no esta en el PATH."
  exit 1
fi

if ! arduino-cli core list | grep -q "esp32:esp32"; then
  echo "==> Instalando core esp32:esp32 (primera vez, puede tardar)..."
  arduino-cli config init --overwrite &> /dev/null || true
  arduino-cli config set board_manager.additional_urls \
    "https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json"
  arduino-cli core update-index
  arduino-cli core install esp32:esp32
fi

echo "==> Comprobando librerias..."
declare -a LIBS=(
  "TFT_eSPI"
  "RTClib"
  "IRremote"
  "ArduinoJson"
  "DHT sensor library"
  "Adafruit Unified Sensor"
)

INSTALLED=$(arduino-cli lib list)

for LIB in "${LIBS[@]}"; do
  if echo "$INSTALLED" | grep -qi "$LIB"; then
    echo "   - $LIB ya instalada"
  else
    echo "   - Instalando $LIB..."
    arduino-cli lib install "$LIB"
  fi
done

ARDUINO_LIBS_DIR="$HOME/Arduino/libraries"
mkdir -p "$ARDUINO_LIBS_DIR"

if [ ! -d "$ARDUINO_LIBS_DIR/AsyncTCP" ]; then
  echo "   - Instalando AsyncTCP desde GitHub..."
  git clone --depth 1 https://github.com/ESP32Async/AsyncTCP.git "$ARDUINO_LIBS_DIR/AsyncTCP"
fi

if [ ! -d "$ARDUINO_LIBS_DIR/ESPAsyncWebServer" ]; then
  echo "   - Instalando ESPAsyncWebServer desde GitHub..."
  git clone --depth 1 https://github.com/ESP32Async/ESPAsyncWebServer.git "$ARDUINO_LIBS_DIR/ESPAsyncWebServer"
fi

# Pantalla ILI9341 en el bus SPI compartido con la SD. Sin fuentes del TFT: la
# interfaz usa sus propias fuentes (src/gfx/fonts_data.h). SUPPORT_TRANSACTIONS es
# imprescindible para que la SD y la pantalla no se pisen en el bus.
TFT_FLAGS="-DUSER_SETUP_LOADED=1 \
-DILI9341_DRIVER=1 \
-DTFT_WIDTH=240 -DTFT_HEIGHT=320 \
-DTFT_MISO=19 -DTFT_MOSI=23 -DTFT_SCLK=18 \
-DTFT_CS=15 -DTFT_DC=2 -DTFT_RST=4 \
-DTOUCH_CS=21 \
-DSUPPORT_TRANSACTIONS=1 \
-DSPI_FREQUENCY=40000000 -DSPI_READ_FREQUENCY=20000000 -DSPI_TOUCH_FREQUENCY=2500000"

if [ ! -f "$SKETCH_DIR/secrets.h" ]; then
  echo "ERROR: falta secrets.h (copia secrets.example.h como secrets.h y pon tu WiFi)."
  exit 1
fi

BUILD_DIR="${BUILD_DIR:-$SKETCH_DIR/build}"

echo "==> Compilando..."
arduino-cli compile --fqbn "$FQBN" --build-path "$BUILD_DIR" \
  --build-property "compiler.cpp.extra_flags=$TFT_FLAGS" \
  "$SKETCH_DIR"

if [ "$COMPILE_ONLY" = true ]; then
  echo "==> Compilacion completada (--compile-only, no se sube)."
  exit 0
fi

if [ -z "$PORT" ]; then
  echo "==> Buscando placa ESP32 conectada..."
  PORT=$(arduino-cli board list | grep -i "esp32\|CP210\|CH340" | awk '{print $1}' | head -n1)

  if [ -z "$PORT" ]; then
    echo "AVISO: no se detecto automaticamente el puerto."
    ls /dev/ttyUSB* /dev/ttyACM* 2> /dev/null || echo "  (ninguno encontrado)"
    echo "Vuelve a ejecutar indicando el puerto: ./build_and_upload.sh /dev/ttyUSB0"
    exit 1
  fi
fi

echo "==> Puerto detectado: $PORT"

echo "==> Subiendo firmware..."
arduino-cli upload -p "$PORT" --fqbn "$FQBN" --input-dir "$BUILD_DIR" "$SKETCH_DIR"

echo "==> Listo. Firmware compilado y subido correctamente."
