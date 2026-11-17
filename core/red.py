"""Red: una sola fuente de verdad de las direcciones de este equipo, del ESP32 y de la extensión.

Nadie más guarda ni adivina IPs: los puentes de `estudio/` piden aquí la de la placa, la web la enseña en
Ajustes → «Red y dispositivos» (`app/red_api.py`, `static/js/red.js`) y `python -m scripts.red` la imprime.

  · Estado en `DATA_DIR/red.json` (escritura atómica). Solo se reescribe cuando cambia algo de verdad (IP, MAC,
    firmware, origen) o cada 10 min como mucho para el «visto por última vez»: lo del momento vive en memoria.
  · La placa se busca, por orden: IP fijada a mano → última IP que funcionó → mDNS (`panel-estudio.local`, lo
    anuncia el firmware) → `ESP32_HOST` de `.env` → vecinos con su MAC → IP de respaldo (reserva DHCP) → barrido
    de la subred (último recurso, limitado a una vez cada 10 min). Cada candidata se comprueba pidiéndole `GET /`:
    solo vale si contesta «Panel de estudio ESP32».
  · Sin `ESP32_HOST` en `.env` no hay placa (como siempre). `ESP32_HOST=auto` = hay placa y no se sabe dónde.

Todo aquí es E/S bloqueante y corta: desde asyncio, con `asyncio.to_thread`.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from core import config, mdns
from core.files import atomic_write
from core.logging_config import get_logger

log = get_logger("red")

# ── Valores de partida (las reservas DHCP del router deben coincidir con ellos) ──
ESP32_HOSTNAME = "panel-estudio"  # el mismo que HOSTNAME en esp32_deskclock/config.h (lo comprueba un test)
ESP32_FIRMA = "Panel de estudio ESP32"  # lo que contesta la placa a GET /
RESPALDO: dict[str, str] = {
    "servidor": "192.168.1.50",
    "esp32": "192.168.1.60",
    "gateway": "192.168.1.1",
    "mascara": "255.255.255.0",
}

AUTO_CADA_S = 60.0  # entre dos búsquedas automáticas (los puentes fallan varios a la vez)
BARRIDO_CADA_S = 600.0  # el barrido de la subred, como mucho cada 10 min
GUARDAR_VISTO_CADA_S = 600.0
EN_LINEA_S = 90.0  # latido cada 30 s: tres perdidos = fuera de línea
EXTENSION_ACTIVA_S = 7 * 86400.0

_lock = threading.RLock()
_buscando = threading.Lock()
_estado: dict[str, Any] | None = None
_vivo: dict[str, Any] = {"esp32": {}, "extension": {}}  # lo del momento (no se guarda)
# «Nunca» es -inf y no 0: el reloj monótono cuenta desde el arranque del equipo, y con 0 no se buscaría la placa
# durante el primer minuto (ni se barrería en los diez primeros), justo cuando el panel acaba de arrancar.
_NUNCA = float("-inf")
_ultima_auto = _NUNCA
_ultimo_barrido = _NUNCA
_cache_tailscale: tuple[float, dict[str, Any]] = (0.0, {})


def _archivo() -> Path:
    return Path(config.DATA_DIR) / "red.json"


def _vacio() -> dict[str, Any]:
    return {"version": 1, "esp32": {}, "extension": {}, "ajustes": {}}


def cargar() -> dict[str, Any]:
    """El estado guardado (se lee una vez; después manda la memoria)."""
    global _estado
    with _lock:
        if _estado is None:
            try:
                datos = json.loads(_archivo().read_text(encoding="utf-8"))
                _estado = {**_vacio(), **datos} if isinstance(datos, dict) else _vacio()
            except (OSError, ValueError):
                _estado = _vacio()
            for clave in ("esp32", "extension", "ajustes"):
                if not isinstance(_estado.get(clave), dict):
                    _estado[clave] = {}
        return _estado


def _guardar() -> None:
    with _lock:
        if _estado is None:
            return
        try:
            _archivo().parent.mkdir(parents=True, exist_ok=True)
            atomic_write(_archivo(), json.dumps(_estado, indent=2, ensure_ascii=False, sort_keys=True))
        except OSError as e:  # disco de solo lectura, carpeta que no está: se sigue con lo de memoria
            log.warning("No se pudo guardar red.json: %s", e)


def reiniciar_para_tests() -> None:
    global _estado, _ultima_auto, _ultimo_barrido, _cache_tailscale
    with _lock:
        _estado = None
        _vivo["esp32"] = {}
        _vivo["extension"] = {}
        _ultima_auto = _ultimo_barrido = _NUNCA
        _cache_tailscale = (0.0, {})


# ── Validación ──────────────────────────────────────────────────────────
def validar_ipv4(texto: str, mascara: str | None = None) -> str:
    """Devuelve la IPv4 normalizada o lanza ValueError con el motivo (en español, para enseñarlo tal cual)."""
    texto = (texto or "").strip()
    if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", texto):
        raise ValueError("Escribe una IPv4 con cuatro números, por ejemplo 192.168.1.60")
    try:
        ip = ipaddress.IPv4Address(".".join(str(int(p)) for p in texto.split(".")))
    except ValueError:
        raise ValueError("Cada número de la IP va de 0 a 255") from None
    if ip.is_loopback or ip.is_multicast or ip.is_unspecified or ip.is_link_local or ip.is_reserved:
        raise ValueError("Esa dirección no es la de un dispositivo de tu red")
    red = ipaddress.IPv4Network(f"{ip}/{mascara or ajuste('mascara')}", strict=False)
    if red.prefixlen < 31 and ip in (red.network_address, red.broadcast_address):
        raise ValueError("Esa es la dirección de la red o la de difusión, no la de un dispositivo")
    return str(ip)


def validar_mascara(texto: str) -> str:
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{(texto or '').strip()}").netmask)
    except ValueError:
        raise ValueError("Máscara no válida; lo normal es 255.255.255.0") from None


def conflicto(ip: str, papel: str) -> str | None:
    """Motivo por el que `ip` no puede ser la de `papel` («esp32», «servidor», «gateway»), o None."""
    otras = {
        "este equipo": set(mdns.ips_locales()) | ({ajuste("servidor")} if papel != "servidor" else set()),
        "el router": {ajuste("gateway")} if papel != "gateway" else set(),
        "el ESP32": {ajuste("esp32"), str(cargar()["esp32"].get("ip") or "")} if papel != "esp32" else set(),
    }
    for quien, ips in otras.items():
        if ip in ips:
            return f"{ip} ya es la dirección de {quien}"
    return None


def ajuste(clave: str) -> str:
    """Respaldo configurable: «servidor», «esp32», «gateway», «mascara» (o el de partida)."""
    return str(cargar()["ajustes"].get(clave) or RESPALDO[clave])


def cambiar_ajustes(cambios: dict[str, str | None]) -> dict[str, Any]:
    """Valida y guarda los respaldos y la IP fijada a mano del ESP32 (`esp32_manual`; vacío = automática)."""
    estado = cargar()
    nuevos = dict(estado["ajustes"])
    if cambios.get("mascara") is not None:
        nuevos["mascara"] = validar_mascara(str(cambios["mascara"]))
    mascara = str(nuevos.get("mascara") or RESPALDO["mascara"])
    for clave in ("servidor", "esp32", "gateway"):
        if cambios.get(clave) is not None:
            nuevos[clave] = validar_ipv4(str(cambios[clave]), mascara)
    if "esp32_manual" in cambios and cambios["esp32_manual"] is not None:
        manual = str(cambios["esp32_manual"]).strip()
        if manual:
            manual = validar_ipv4(manual, mascara)
            motivo = conflicto(manual, "esp32")
            if motivo:
                raise ValueError(motivo)
        nuevos["esp32_manual"] = manual
    finales = {k: str(nuevos.get(k) or RESPALDO[k]) for k in ("servidor", "esp32", "gateway")}
    if len(set(finales.values())) < 3:
        raise ValueError("El equipo, el ESP32 y el router no pueden compartir dirección")
    with _lock:
        estado["ajustes"] = {k: v for k, v in nuevos.items() if v or k == "esp32_manual"}
        _guardar()
    return estado["ajustes"]


# ── Este equipo ─────────────────────────────────────────────────────────
def _tailscale() -> dict[str, Any]:
    """{activo, ip, nombre, url} de Tailscale (vacío si no está instalado o no hay sesión). Caché de 60 s."""
    global _cache_tailscale
    if time.monotonic() - _cache_tailscale[0] < 60 and _cache_tailscale[0]:
        return _cache_tailscale[1]
    out: dict[str, Any] = {"activo": False}
    try:
        r = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=3)
        datos = json.loads(r.stdout) if r.returncode == 0 else {}
        yo = datos.get("Self") or {}
        nombre = str(yo.get("DNSName") or "").rstrip(".")
        ips = [ip for ip in (yo.get("TailscaleIPs") or []) if ":" not in ip]
        out = {
            "activo": datos.get("BackendState") == "Running" and bool(ips),
            "ip": ips[0] if ips else "",
            "nombre": nombre,
            "url": "",
        }
        if out["activo"] and nombre:
            s = subprocess.run(["tailscale", "serve", "status", "--json"], capture_output=True, text=True, timeout=3)
            web = (json.loads(s.stdout or "{}") or {}).get("Web") or {} if s.returncode == 0 else {}
            for destino in web:  # «equipo.tailnet.ts.net:443»
                if destino.split(":")[0] == nombre:
                    puerto = destino.partition(":")[2]
                    out["url"] = f"https://{nombre}" + ("" if puerto in ("", "443") else f":{puerto}")
                    break
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    _cache_tailscale = (time.monotonic(), out)
    return out


def servidor() -> dict[str, Any]:
    """Cómo se llega a este panel: escucha, IPs de la red local, Tailscale y las direcciones que valen de verdad."""
    escucha = os.environ.get("PANEL_HOST", "").strip() or _leer_env("PANEL_HOST") or "0.0.0.0"
    puerto = int(os.environ.get("PANEL_PORT", "").strip() or _leer_env("PANEL_PORT") or 8000)
    con_tls = bool(os.environ.get("PANEL_SSL_CERT", "").strip() or _leer_env("PANEL_SSL_CERT"))
    ips = mdns.ips_locales()
    ts = _tailscale()
    urls = [{"donde": "este equipo", "url": f"{'https' if con_tls else 'http'}://127.0.0.1:{puerto}"}]
    if ts.get("url"):
        urls.append({"donde": "tailnet (móvil, fuera de casa)", "url": ts["url"]})
    if escucha not in ("127.0.0.1", "localhost", "::1"):
        urls += [{"donde": "red local", "url": f"{'https' if con_tls else 'http'}://{ip}:{puerto}"} for ip in ips]
    return {
        "nombre": socket.gethostname(),
        "escucha": escucha,
        "puerto": puerto,
        "solo_local": escucha in ("127.0.0.1", "localhost", "::1"),
        "ips": ips,
        "respaldo": ajuste("servidor"),
        "coincide_reserva": ajuste("servidor") in ips,
        "tailscale": ts,
        "urls": urls,
        "principal": ts.get("url") or urls[-1]["url"],
    }


def _leer_env(clave: str) -> str:
    """Valor de `clave` en el .env del panel (start.sh lee de ahí el host y el puerto sin exportarlos)."""
    try:
        for linea in reversed(Path(config.ENV_FILE).read_text(encoding="utf-8").splitlines()):
            m = re.match(rf"\s*{re.escape(clave)}\s*=\s*(.*)", linea)
            if m:
                return m.group(1).strip().strip("\"'")
    except OSError:
        pass
    return ""


# ── ESP32 ───────────────────────────────────────────────────────────────
def esp32_configurada() -> bool:
    return bool(config.ESP32_HOST)


def _env_esp32() -> str:
    """`ESP32_HOST` si es una dirección («auto» o vacío = ninguna)."""
    host = config.ESP32_HOST
    return "" if host.lower() in ("", "auto") else host


def esp32_host() -> str:
    """Dónde está la placa según lo último que se sabe («» si no hay placa)."""
    if not esp32_configurada():
        return ""
    estado = cargar()
    return str(estado["ajustes"].get("esp32_manual") or estado["esp32"].get("ip") or _env_esp32() or ajuste("esp32"))


def esp32_ws_url() -> str:
    host = esp32_host()
    return f"ws://{host}/ws" if host else ""


def es_la_placa(host: str, timeout: float = 1.5) -> bool:
    """¿Contesta `host` como el firmware del panel? (GET / → «Panel de estudio ESP32»)."""
    try:
        with urllib.request.urlopen(f"http://{host}/", timeout=timeout) as r:  # noqa: S310 — http a la red local
            return r.read(64).decode("utf-8", "replace").startswith(ESP32_FIRMA)
    except (OSError, urllib.error.URLError, ValueError):
        return False


def vecinos() -> dict[str, str]:
    """{ip: mac} de la tabla de vecinos del sistema (`ip neigh`; vacío donde no exista)."""
    try:
        r = subprocess.run(["ip", "-4", "neigh", "show"], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for linea in r.stdout.splitlines():
        m = re.match(r"(\d+\.\d+\.\d+\.\d+) .*lladdr ([0-9a-fA-F:]{17})", linea)
        if m:
            out[m.group(1)] = m.group(2).lower()
    return out


def _puerto_abierto(ip: str, puerto: int = 80, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((ip, puerto), timeout=timeout):
            return True
    except OSError:
        return False


def _barrer(mac: str) -> str | None:
    """Último recurso: llama al puerto 80 de toda la subred de cada interfaz y se queda con quien conteste como la
    placa (antes, con quien tenga su MAC). Unos 2 s por subred /24."""
    for propia in mdns.ips_locales():
        red = ipaddress.IPv4Network(f"{propia}/{ajuste('mascara')}", strict=False)
        if red.num_addresses > 1024:  # una /16 mal puesta no se barre
            continue
        candidatas = [str(h) for h in red.hosts() if str(h) != propia]
        with ThreadPoolExecutor(max_workers=64) as pool:
            abiertas = [ip for ip, ok in zip(candidatas, pool.map(_puerto_abierto, candidatas), strict=True) if ok]
        if mac:
            tabla = vecinos()
            abiertas.sort(key=lambda ip: tabla.get(ip) != mac)  # la de su MAC, la primera
        for ip in abiertas:
            if es_la_placa(ip):
                return ip
    return None


def detectar_esp32(barrido: bool = True) -> dict[str, Any]:
    """Busca la placa (ver el orden arriba), guarda lo que encuentre y devuelve
    {"ok", "ip", "origen", "cambio", "probadas": [[origen, dirección]…]}."""
    global _ultimo_barrido
    if not esp32_configurada():
        return {"ok": False, "ip": "", "origen": "", "cambio": False, "probadas": [], "motivo": "sin-placa"}
    estado = cargar()
    antes = str(estado["esp32"].get("ip") or "")
    mac = str(estado["esp32"].get("mac") or "")
    probadas: list[list[str]] = []
    vistas: set[str] = set()

    def probar(origen: str, host: str | None) -> bool:
        if not host or host in vistas:
            return False
        vistas.add(host)
        probadas.append([origen, host])
        return es_la_placa(host)

    def hallada(origen: str, ip: str) -> dict[str, Any]:
        cambio = _anotar_esp32(ip=ip, origen=origen, mac=vecinos().get(ip, ""))
        return {"ok": True, "ip": ip, "origen": origen, "cambio": cambio or ip != antes, "probadas": probadas}

    with _buscando:
        manual = str(estado["ajustes"].get("esp32_manual") or "")
        if probar("manual", manual):
            return hallada("manual", manual)
        if probar("última", antes):
            return hallada(str(estado["esp32"].get("origen") or "última"), antes)
        por_mdns = mdns.resolver(f"{ESP32_HOSTNAME}.local", timeout=1.5)
        if probar("mdns", por_mdns):
            return hallada("mdns", str(por_mdns))
        env = _env_esp32()
        if probar("env", env):
            return hallada("env", env)
        if mac:
            for ip, suya in vecinos().items():
                if suya == mac and probar("mac", ip):
                    return hallada("mac", ip)
        if probar("respaldo", ajuste("esp32")):
            return hallada("respaldo", ajuste("esp32"))
        if barrido and time.monotonic() - _ultimo_barrido >= BARRIDO_CADA_S:
            _ultimo_barrido = time.monotonic()
            probadas.append(["barrido", "subred"])
            encontrada = _barrer(mac)
            if encontrada:
                return hallada("barrido", encontrada)
    return {"ok": False, "ip": "", "origen": "", "cambio": False, "probadas": probadas, "motivo": "no-responde"}


def redetectar_si_toca() -> bool:
    """Para los puentes, tras un fallo de conexión: busca la placa como mucho una vez por minuto.
    True si ha aparecido en otra dirección (hay que reconectar ya)."""
    global _ultima_auto
    if not esp32_configurada() or time.monotonic() - _ultima_auto < AUTO_CADA_S or _buscando.locked():
        return False
    _ultima_auto = time.monotonic()
    antes = esp32_host()
    r = detectar_esp32()
    if r["ok"] and r["ip"] != antes:
        log.info("ESP32 encontrado en %s (por %s); antes %s", r["ip"], r["origen"], antes or "sin dirección")
        return True
    return False


def _anotar_esp32(**campos: Any) -> bool:
    """Guarda lo que cambie de la placa. True si cambió algo duradero (IP, MAC, firmware, origen)."""
    ahora = time.time()
    with _lock:
        esp = cargar()["esp32"]
        cambio = False
        for clave in ("ip", "mac", "origen", "fw", "host"):
            valor = str(campos.get(clave) or "").strip()
            if clave == "mac":
                valor = valor.lower()
            if valor and esp.get(clave) != valor:
                if clave == "ip" and esp.get("ip"):
                    esp["ip_anterior"] = esp["ip"]
                esp[clave] = valor
                cambio = True
        if cambio:
            esp["detectada"] = ahora
        _vivo["esp32"]["visto"] = ahora
        if cambio or ahora - float(esp.get("visto") or 0) > GUARDAR_VISTO_CADA_S:
            esp["visto"] = ahora
            _guardar()
        return cambio


def latido_esp32(datos: dict[str, Any], origen_ip: str = "") -> None:
    """Latido del firmware (`{"type": "heartbeat", ip, mac, host, fw, uptime, heap, heap_min, rssi, clients}`):
    llega por el WebSocket que el panel ya tiene abierto con la placa."""
    ip = str(datos.get("ip") or origen_ip or "")
    try:
        ip = validar_ipv4(ip) if ip else ""
    except ValueError:
        ip = ""
    mac = str(datos.get("mac") or "")
    if not re.fullmatch(r"[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}", mac):
        mac = ""
    campos: dict[str, Any] = {
        "mac": mac,
        "fw": str(datos.get("fw") or "")[:40],
        "host": str(datos.get("host") or "")[:40],
    }
    if ip and ip != cargar()["esp32"].get("ip"):
        campos |= {"ip": ip, "origen": "latido"}
    _anotar_esp32(**campos)
    with _lock:
        for clave in ("uptime", "heap", "heap_min", "rssi", "clients"):
            if isinstance(datos.get(clave), (int, float)) and not isinstance(datos.get(clave), bool):
                _vivo["esp32"][clave] = datos[clave]
        if isinstance(datos.get("reset"), str):  # por qué arrancó la última vez (vigilante, tension, error…)
            _vivo["esp32"]["reset"] = datos["reset"][:20]


def visto_esp32() -> None:
    """Contacto con la placa por cualquier vía (los puentes conectados): cuenta como «en línea»."""
    with _lock:
        _vivo["esp32"]["visto"] = time.time()


# ── Extensión ───────────────────────────────────────────────────────────
def latido_extension(version: str, url: str, ip: str, navegador: str = "") -> None:
    ahora = time.time()
    with _lock:
        ext = cargar()["extension"]
        nuevos = {"version": version[:20], "url": url[:200], "ip": ip[:45], "navegador": navegador[:60]}
        cambio = any(ext.get(k) != v for k, v in nuevos.items())
        ext.update(nuevos)
        _vivo["extension"]["visto"] = ahora
        if cambio or ahora - float(ext.get("visto") or 0) > GUARDAR_VISTO_CADA_S:
            ext["visto"] = ahora
            _guardar()


# ── Para la interfaz ────────────────────────────────────────────────────
def estado() -> dict[str, Any]:
    guardado = cargar()
    ahora = time.time()
    with _lock:
        esp = {**guardado["esp32"], **_vivo["esp32"]}
        ext = {**guardado["extension"], **_vivo["extension"]}
    srv = servidor()
    esp_visto = float(esp.get("visto") or 0)
    ext_visto = float(ext.get("visto") or 0)
    url_ext = str(ext.get("url") or "")
    validas = {u["url"].rstrip("/") for u in srv["urls"]} | {
        u["url"].replace("127.0.0.1", "localhost").rstrip("/") for u in srv["urls"]
    }
    return {
        "servidor": srv,
        "esp32": {
            **esp,
            "configurada": esp32_configurada(),
            "direccion": esp32_host(),  # la que usan los puentes ahora mismo («host» es el nombre que dice el latido)
            "manual": str(guardado["ajustes"].get("esp32_manual") or ""),
            "respaldo": ajuste("esp32"),
            "nombre_mdns": f"{ESP32_HOSTNAME}.local",
            "en_linea": bool(esp_visto and ahora - esp_visto < EN_LINEA_S),
            "coincide_reserva": esp32_host() == ajuste("esp32"),
        },
        "extension": {
            **ext,
            "conocida": bool(ext_visto),
            "activa": bool(ext_visto and ahora - ext_visto < EXTENSION_ACTIVA_S),
            "url_vigente": not url_ext or url_ext.rstrip("/") in validas,
        },
        "ajustes": {k: ajuste(k) for k in RESPALDO},
        "ahora": ahora,
    }
