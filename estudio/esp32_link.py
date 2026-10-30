"""
Estado común de la conexión con el ESP32 para todos los puentes (Spotify, repaso de
notas, calendario) y para la web.

Antes cada puente reintentaba cada 3 s para siempre y escribía dos líneas en el log
por intento (más de mil por hora con la placa apagada). Ahora:
  - unos pocos intentos con espera creciente (3 s, 6 s, 12 s);
  - después, «sin conexión» y pausa larga (10 min) sin intentar nada;
  - «Reintentar» (web o POST /estudio/api/esp32/retry) despierta a todos al instante;
  - el log solo cuenta los cambios de estado (conectado, perdido, sin conexión).

Varios puentes que fallan a la vez cuentan como un solo intento: un fallo solo suma
si llega cuando ya tocaba intentar (no dentro de la espera que puso otro).
"""
import asyncio
import time

from core.logging_config import get_logger

log = get_logger("esp32")

FAST_DELAYS = (3.0, 6.0, 12.0)   # esperas tras el 1.º, 2.º y 3.º fallo seguidos
PAUSE_SEC = 600.0                # después, «sin conexión» durante 10 min


class Esp32Link:
    def __init__(self, fast_delays=FAST_DELAYS, pause=PAUSE_SEC, clock=time.monotonic, wall=time.time):
        self.fast_delays = tuple(fast_delays)
        self.pause = pause
        self._clock = clock
        self._wall = wall
        self.state = "connecting"    # connecting | online | offline | disabled
        self.failures = 0
        self.next_attempt = 0.0      # reloj monótono
        self.last_ok = None          # hora de pared del último contacto
        self.last_error = None
        self.connected = 0           # puentes conectados ahora mismo
        self._wake = None

    # Event perezoso: se crea en el bucle de asyncio que lo usa
    @property
    def wake(self) -> asyncio.Event:
        if self._wake is None:
            self._wake = asyncio.Event()
        return self._wake

    def can_try(self) -> bool:
        return self._clock() >= self.next_attempt

    async def wait_turn(self) -> None:
        """Espera hasta que toque intentar (o hasta que alguien pida reintentar)."""
        while not self.can_try():
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=max(0.05, self.next_attempt - self._clock()))
            except TimeoutError:
                pass

    def ok(self) -> None:
        self.connected += 1
        if self.state != "online":
            log.info("ESP32 conectado")
        self.state = "online"
        self.failures = 0
        self.next_attempt = 0.0
        self.last_ok = self._wall()
        self.last_error = None
        self.wake.set()

    def seen(self) -> None:
        """Contacto puntual (lecturas sueltas del calendario)."""
        self.last_ok = self._wall()

    def closed(self) -> None:
        """Un puente conectado pierde la conexión: vuelve a intentar enseguida, sin contar fallo."""
        self.connected = max(0, self.connected - 1)
        if self.connected == 0 and self.state == "online":
            log.warning("Conexión con el ESP32 perdida; reintentando")
            self.state = "connecting"

    def failed(self, error: Exception | str | None = None) -> None:
        if not self.can_try():
            return  # otro puente ya contó este intento
        self.failures += 1
        self.last_error = str(error) if error else None
        if self.failures <= len(self.fast_delays):
            self.state = "connecting"
            self.next_attempt = self._clock() + self.fast_delays[self.failures - 1]
            if self.failures == 1:
                log.info(f"El ESP32 no responde ({self.last_error}); se reintentará con espera creciente")
        else:
            if self.state != "offline":
                log.warning(f"ESP32 sin conexión tras {self.failures} intentos; "
                            f"siguiente intento en {int(self.pause // 60)} min o al pulsar «Reintentar»")
            self.state = "offline"
            self.next_attempt = self._clock() + self.pause

    def retry(self) -> None:
        log.info("Reintento manual de la conexión con el ESP32")
        self.failures = 0
        self.next_attempt = 0.0
        if self.state not in ("online", "disabled"):
            self.state = "connecting"
        self.wake.set()

    def status(self) -> dict:
        wait = max(0.0, self.next_attempt - self._clock())
        return {"state": self.state, "online": self.state == "online", "failures": self.failures,
                "last_ok": self.last_ok, "last_error": self.last_error,
                "retry_in": round(wait) if self.state in ("connecting", "offline") and wait else 0}


LINK = Esp32Link()


async def keep_connected(session, url: str, serve, **ws_kwargs) -> None:
    """Bucle de un puente con conexión permanente: espera su turno, conecta, atiende con
    `serve(ws)` hasta que se cierre y vuelve a empezar. Sin conexión no escribe nada en el
    log (lo cuenta LINK una vez)."""
    while True:
        await LINK.wait_turn()
        connected = False
        try:
            async with session.ws_connect(url, **ws_kwargs) as ws:
                connected = True
                LINK.ok()
                await serve(ws)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — cualquier fallo de red cuenta igual
            if not connected:
                LINK.failed(e)
            else:
                log.debug(f"Conexión cerrada: {e!r}")
        finally:
            if connected:
                LINK.closed()
        if connected:
            await asyncio.sleep(1.0)
