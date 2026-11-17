# Red y dispositivos: quién está dónde, sin escribir IPs

El panel habla con tres cosas: **este equipo** (donde corre), la **placa ESP32** y la **extensión** del navegador.
Ninguna dirección se escribe a mano ni vive repartida por el código: hay una sola fuente de verdad
(`core/red.py`, estado en `data/red.json`) que el panel mantiene solo, y un sitio donde verla y comprobarla:
**Ajustes → Red y dispositivos** (o `python -m scripts.red`).

## Cómo se conecta cada cosa

| Quién | Cómo llega al panel o a la placa | Qué pasa si cambia una IP |
|---|---|---|
| Navegador (PC, móvil) | `https://<equipo>.<tailnet>.ts.net` (Tailscale) o `http://127.0.0.1:8000` en el propio equipo | Nada: el nombre de la tailnet no depende de la IP |
| Panel → ESP32 | El panel es **cliente** WebSocket de la placa (`ws://<placa>/ws`) | El panel la vuelve a encontrar solo (ver abajo) |
| Web de Estudio → ESP32 | Por el puente `wss://<panel>/estudio/ws`: el navegador nunca habla con la placa | Nada |
| ESP32 → panel | **Nunca llama al panel**: solo contesta por el WebSocket que el panel le abre | Nada: no guarda ninguna dirección del panel |
| Extensión → panel | La dirección guardada en la extensión (botón «Detectar») | Cambia sola a otra dirección segura del panel, o avisa |

Por eso el HTTPS del panel no afecta a la placa (no hay certificados ni `setInsecure` en el firmware) y el panel
puede seguir escuchando solo en `127.0.0.1`.

## Cómo encuentra el panel a la placa

Cada vez que no consigue conectar (como mucho una búsqueda por minuto), y cuando pulsas **Redetectar**, prueba por
orden y se queda con la primera dirección que conteste `Panel de estudio ESP32` a `GET /`:

1. La **IP fijada a mano** en Ajustes (vacía, lo normal).
2. La **última** que funcionó.
3. **mDNS**: `panel-estudio.local` (la placa se anuncia; el panel pregunta sin necesitar avahi).
4. `ESP32_HOST` de `.env`, si es una dirección.
5. Los vecinos de la red con su **MAC** (la aprende sola la primera vez).
6. La **reserva** `192.168.1.60`.
7. Un **barrido** de la subred (puerto 80), solo como último recurso y como mucho cada 10 minutos.

Además, la placa manda un **latido** cada 30 s por el mismo WebSocket (IP, MAC, versión del firmware, memoria,
señal, motivo del último arranque): si su IP cambia con la conexión abierta, el panel se entera al momento.

En `.env` basta `ESP32_HOST=auto` (hay placa, búscala). Una IP concreta sigue valiendo: es una pista más. Vacío = no
hay placa y no se busca nada.

## Direcciones de partida y reservas del router

| Dispositivo | Reserva DHCP | Dónde se cambia |
|---|---|---|
| Este equipo (portátil) | `192.168.1.50` | Ajustes → Red y dispositivos → «Direcciones a mano y reservas» |
| ESP32 (`panel-estudio`, MAC en esa misma pantalla) | `192.168.1.60` | ídem |
| Router | `192.168.1.1`, máscara `255.255.255.0` | ídem |

**En el router** (lo haces tú, una vez): en la sección de DHCP / «direcciones reservadas» / «IP estática por MAC»,
asigna `192.168.1.50` a la MAC del portátil y `192.168.1.60` a la de la placa. No es obligatorio (todo funciona sin
ello, porque se busca solo), pero así las direcciones no cambian y el respaldo acierta a la primera. La pantalla
avisa mientras no coincidan. El panel **nunca** toca la configuración del router ni la de la red del equipo.

Estado (2026-11-17): reservas puestas en el router. El portátil tiene la `.50` por **cable** (`enp4s0`); por wifi
sigue con la que le dé el DHCP, y da igual: el panel solo escucha en 127.0.0.1 y se entra por Tailscale.

Validación: las direcciones que escribas tienen que ser IPv4 de un dispositivo (ni la de la red, ni la de difusión,
ni la del propio equipo o el router para la placa) y las tres no pueden coincidir.

## La pantalla

- **Este equipo**: IPs locales, si coincide con la reserva, Tailscale, dónde escucha y las direcciones que valen de
  verdad para entrar. **Probar conexión** pide `/healthz` a cada una y dice cuánto tarda.
- **ESP32**: en línea o no, IP y de dónde salió (mDNS, latido, reserva…), MAC, firmware, última conexión, señal y
  memoria. **Redetectar** la busca ahora; **Probar conexión** comprueba que contesta.
- **Extensión**: versión, por dónde entra y desde qué IP, última vez. Si entra por una dirección que ya no es del
  panel, lo dice.

API: `GET /api/red`, `POST /api/red/redetectar`, `POST /api/red/probar`, `PATCH /api/red/ajustes`,
`POST /api/red/latido` (extensión). Terminal: `python -m scripts.red [--redetectar] [--json]`.

## Qué esperaba cada parte y qué hay ahora

| El ESP32 / la web / la extensión esperaba | El panel ofrecía | Qué se hizo |
|---|---|---|
| Que el panel se conecte a `ws://<IP fija>/ws` | `ESP32_HOST` fijo en `.env`; al cambiar la IP de la placa, nada conectaba | Dirección dinámica (`core/red.py`) y búsqueda automática |
| La web de Estudio abre `ws://<IP>/ws` desde el navegador | Bajo `https://` el navegador lo bloquea (contenido mixto) y fuera de casa esa IP no existe | Puente `/estudio/ws` con la sesión del panel |
| WebSocket sin autenticar | El middleware dejaba pasar cualquier WebSocket | Token, o cookie + `Origin` del propio panel |
| La carátula antes que el título de su canción | El firmware la tiraba al llegar un título nuevo | El puente la manda después y el firmware ya no depende del orden (`has_art`) |
| Nadie le preguntaba a la placa quién es | No se sabía su MAC ni su versión | Latido (`heartbeat`) y TXT en mDNS |
| La extensión, una dirección escrita a mano (`http://192.168.x.x:8000`) | El panel ya solo escucha en `127.0.0.1` y por HTTPS en la tailnet | «Detectar», latido y dirección recomendada (2.11) |
| JSON y tipos de mensaje (`nowplaying`, `calendar_*`, `checklist_*`, `review_note`…) | Los mismos | Sin cambios: compatibles |

## Si algo falla

- **«Fuera de línea» y Redetectar no la encuentra**: ¿está encendida y en la misma wifi que el portátil? Mira el
  puerto serie (`esp32_deskclock/README.md`): debe decir `WiFi: … panel-estudio.local anunciado`. Como último
  recurso, fija su IP a mano en la pantalla.
- **La encuentra pero se cae**: mira «Encendida hace» y el motivo del último arranque (vigilante, tensión).
- **La extensión marca «Dirección antigua»**: ábrela → opciones → **Detectar** → Guardar.
- **Volver a como estaba**: borra `data/red.json` (se rehace solo) y deja en `.env` la IP de la placa en `ESP32_HOST`.
