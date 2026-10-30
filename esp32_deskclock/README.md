# Reloj de escritorio ESP32 (`esp32_deskclock/`)

Firmware de la pantalla de estudio: reloj, música que suena en el PC, calendario sincronizado con
iCloud, listas, pomodoro, repaso y lectura de las notas del Cerebro. Se maneja con el mando IR. El panel
(`estudio/` en la raíz del repo) se conecta a él por WebSocket como cliente y le manda la música,
el calendario y las notas.

## Hardware

| Pieza | Pines |
|---|---|
| ESP32 DevKit (4 MB de flash) | — |
| Pantalla ILI9341 320×240 (SPI) | CS 15, DC 2, RST 4, MOSI 23, SCK 18, MISO 19 (táctil sin cablear, CS 21) |
| Tarjeta microSD (mismo bus SPI) | CS 5 |
| RTC DS3231 (I²C) | SDA 32, SCL 33 |
| Receptor IR HX1838 (mando NEC) | 34 |
| DHT22 / AM2302 (temperatura y humedad) | 25 |

Los pines de la pantalla van en `TFT_FLAGS` de `build_and_upload.sh`; el resto en `config.h`.

## Compilar y subir

```bash
cd esp32_deskclock
cp secrets.example.h secrets.h          # pon el WiFi; secrets.h está en .gitignore
./build_and_upload.sh /dev/ttyUSB0      # compila y sube (sin puerto, lo busca solo)
./build_and_upload.sh --compile-only    # solo compila (BUILD_DIR=<carpeta> para no ensuciar)
```

El script instala con `arduino-cli` el núcleo `esp32:esp32` y las librerías (TFT_eSPI, RTClib,
IRremote, ArduinoJson, DHT, AsyncTCP y ESPAsyncWebServer de ESP32Async) si faltan. Usa la partición
**«Huge APP»** (3 MB de programa, sin OTA): el primer volcado cambia la tabla de particiones, pero
la NVS (minutos del pomodoro, racha, ajustes) se conserva.

Al arrancar intenta el WiFi sin bloquear; la hora sale del RTC y se corrige por NTP cada 6 h
(hora de Madrid con cambio de horario). Si los colores salen invertidos en tu pantalla, añade
`-DTFT_INVERSION_ON=1` a `TFT_FLAGS`.

En el `.env` del panel, `ESP32_HOST` debe apuntar a la IP de la placa (o a `panel-estudio.local`).

## Mando

| Tecla | Qué hace |
|---|---|
| 1 · 2 · 3 · 4 · 5 · 0 | Reloj · Calendario · Listas · Pomodoro · Ajustes · Notas |
| ← → | Pantalla anterior / siguiente, en el orden Reloj, Calendario, Listas, Notas, Pomodoro, Ajustes (en el calendario, día; con música, canción; leyendo una nota, la nota anterior / siguiente) |
| ↑ ↓ | Mover selección; con música, volumen; en el pomodoro parado, minutos de trabajo; leyendo una nota, desplazar el texto |
| OK | Acción principal: play/pausa, abrir día, marcar tarea, arrancar pomodoro, abrir una nota (y, ya abierta, abrirla en el PC) |
| * | Atrás: cerrar, volver a hoy, reiniciar pomodoro |
| # | Ir al reloj |
| 6 · 7 · 8 | Pomodoro 25+5 · 50+10 · 90+15 |
| 9 | Ver ya la nota de repaso que esté esperando (aunque el repaso automático esté apagado) |

Mantener pulsada una flecha repite. Cada pantalla dibuja abajo las teclas que tiene.

## Archivos de la SD

| Archivo | Contenido |
|---|---|
| `/eventos.json` | Calendario (cada evento con su `uid`, igual que en iCloud) |
| `/listas.json` | Listas y tareas con ids; las listas del formato antiguo se migran solas sin borrarlas |
| `/background.bin` | Fondo personalizado subido desde la web de Estudio (160×120 RGB565) |

Se escriben de forma atómica (archivo temporal y renombrado); si la SD se saca, el firmware la
vuelve a montar y sigue funcionando en memoria mientras tanto.

## Protocolo con el panel

WebSocket en `ws://<placa>/ws`, mensajes JSON (`src/app/protocol.cpp`). El panel manda
`nowplaying`, `review_note`, `calendar_sync_full` y, como binario, la carátula: 4 bytes de cabecera
(ancho y alto, big-endian) + píxeles RGB565 big-endian, hasta 160×160 (`estudio/main.py` la manda a
120×120). Una imagen de 160×120 se guarda como fondo. La web de Estudio edita el calendario por
`uid` y las tareas por `id` (el índice se sigue aceptando). El ESP32 difunde a todos los clientes
`cmd` (mando de música) y `open_note_request`.

### Calendario (Panel ↔ ESP32)

El calendario del Panel (`/calendario`, tabla `events`) es el centro; `estudio/calendar_sync.py` lo
sincroniza cada 8 min (o con «Sincronizar ahora») con iCloud y con la placa, en tres vías y por `uid`:

1. El panel pide la lista: `{"type": "calendar_get"}` → el ESP32 contesta
   `{"type": "calendar_list", "events": [{"uid", "date": "AAAA-MM-DD", "title", "type": "evento|examen|entrega"}]}`.
2. Compara con el Panel y con la «última vez» (`estudio/calendar_sync_v2.json`): lo creado, cambiado o
   borrado en la placa pasa al Panel (el día, el título y el tipo; la hora se conserva), y al revés.
3. Manda la lista completa: `{"type": "calendar_sync_full", "events": [{"uid", "date", "title", "type",
   "time"?: "HH:MM", "end"?: "HH:MM"}]}`. `time` y `end` solo van en eventos con hora; el firmware actual
   los ignora (ArduinoJson descarta campos desconocidos), así que no hace falta volver a flashear.
   Un evento de tipo `bloque` del Panel llega como `evento`.

Guardas: si la placa devuelve 0 eventos cuando antes había más de 3, o el Panel está vacío, ese ciclo
no toca nada. Lo borrado en el Panel por la sincronía va a su papelera (30 días).

Pantalla Notas: el ESP32 difunde `notes_list_request` y el panel contesta `notes_list`
(`[{id, title, category}]`, sin notas cifradas ni índices); al abrir una, `note_request` con su
`note_id` y el panel contesta `note_content` (texto plano, sin Markdown). La web activa o desactiva
que la nota de repaso salga sola con `review_set` (`enabled`); el ESP32 lo guarda en NVS
(`review_auto`) y difunde `review_state`, también en la respuesta a `get_state`.

## Desarrollo en el PC (sin placa)

```bash
make -C tools/host test                    # tests de la lógica con ASan/UBSan
make -C tools/host preview OUT=/tmp/capt   # PNG de cada pantalla
python3 tools/make_fonts.py                # regenera src/gfx/fonts_data.h desde la Inter del panel
```

Necesitan `g++` y ArduinoJson en `~/Arduino/libraries/ArduinoJson` (lo deja el script de
compilación; otra ruta con `ARDUINOJSON=...`). La interfaz se compila igual para la placa y para el
PC (`src/platform/platform.h` separa lo que depende del hardware).

## Estructura

- `esp32_deskclock.ino`: `setup()` / `loop()`; solo `loop()` dibuja y toca la SD, la red solo encola.
- `src/gfx/`: compositor por franjas con suavizado; repinta solo lo que cambia. Fuentes Inter.
- `src/ui/`: pantallas, ventanas (repaso, día, avisos) y teclas.
- `src/model/`: calendario, listas, pomodoro, música, repaso y fondo.
- `src/app/`: dispositivo (WiFi, SD, RTC, IR, DHT, servidor) y protocolo.
- `tools/`: fuentes y compilación en el PC.
