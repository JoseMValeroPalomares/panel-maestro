"""
Red y dispositivos (Ajustes → «Red y dispositivos»; lógica en `core/red.py`).

    GET   /api/red              estado de este equipo, del ESP32 y de la extensión (direcciones, última vez, en línea)
    POST  /api/red/redetectar   busca la placa ahora (mDNS, última IP, vecinos, respaldo, barrido) y despierta a los
                                puentes si aparece
    POST  /api/red/probar       {que: "esp32" | "servidor" | "ip", ip?}: comprueba de verdad que contesta (y cuánto tarda)
    PATCH /api/red/ajustes      {esp32_manual?, servidor?, esp32?, gateway?, mascara?}: IP fijada a mano («» = automática)
                                y direcciones de respaldo (las reservas DHCP del router); valida formato y conflictos
    POST  /api/red/latido       {version, url, navegador}: la extensión dice que sigue viva y con qué dirección entra

Nada de aquí cambia la red del equipo ni la del router: solo mira, recuerda y avisa.
"""

import time
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import red
from core.logging_config import get_logger

log = get_logger("red")
router = APIRouter(prefix="/api/red")


class ProbarIn(BaseModel):
    que: str = Field(max_length=10)
    ip: str | None = Field(default=None, max_length=15)


class AjustesIn(BaseModel):
    esp32_manual: str | None = Field(default=None, max_length=15)
    servidor: str | None = Field(default=None, max_length=15)
    esp32: str | None = Field(default=None, max_length=15)
    gateway: str | None = Field(default=None, max_length=15)
    mascara: str | None = Field(default=None, max_length=15)


class LatidoIn(BaseModel):
    version: str = Field(default="", max_length=20)
    url: str = Field(default="", max_length=200)
    navegador: str = Field(default="", max_length=60)


def _enlace() -> dict:
    """Estado de los puentes con la placa (el mismo de «Conexiones»)."""
    from estudio.esp32_link import LINK

    return LINK.status()


def _despertar_puentes() -> None:
    from estudio.esp32_link import LINK

    if LINK.state not in ("online", "disabled"):
        LINK.retry()


def _estado() -> dict:
    out = red.estado()
    out["esp32"]["enlace"] = _enlace()
    out["avisos"] = avisos(out)
    return out


def avisos(e: dict) -> list[dict]:
    """Lo que el usuario tiene que saber o hacer a mano (reservas del router, extensión con dirección vieja…)."""
    out = []
    srv, esp, ext = e["servidor"], e["esp32"], e["extension"]
    if esp["configurada"] and esp.get("ip") and not esp["coincide_reserva"] and not esp["manual"]:
        out.append(
            {
                "clave": "reserva-esp32",
                "texto": f"El ESP32 está en {esp['direccion']} y su reserva es {esp['respaldo']}. Funciona igual (se "
                f"encuentra solo), pero conviene reservarle {esp['respaldo']} en el router para que no cambie.",
            }
        )
    if srv["ips"] and not srv["coincide_reserva"]:
        out.append(
            {
                "clave": "reserva-servidor",
                "texto": f"Este equipo está en {', '.join(srv['ips'])} y su reserva es {srv['respaldo']}. "
                f"Resérvale {srv['respaldo']} en el router (DHCP) o cambia aquí la dirección de respaldo.",
            }
        )
    if ext["conocida"] and not ext["url_vigente"]:
        out.append(
            {
                "clave": "extension-url",
                "texto": f"La extensión entra por {ext.get('url')}, que ya no es una dirección de este panel. "
                f"Ábrela y pulsa «Detectar» (la buena es {srv['principal']}).",
            }
        )
    if srv["solo_local"] and not srv["tailscale"].get("url"):
        out.append(
            {
                "clave": "solo-local",
                "texto": "El panel solo escucha en este equipo (127.0.0.1) y Tailscale no lo publica: "
                "desde el móvil no se llega.",
            }
        )
    return out


@router.get("")
def ver():
    return _estado()


@router.post("/redetectar")
def redetectar():
    res = red.detectar_esp32()
    if res["ok"]:
        _despertar_puentes()
    if res.get("cambio"):
        log.info("Redetección a mano: ESP32 en %s (por %s)", res["ip"], res["origen"])
    return {"resultado": res, **_estado()}


def _probar_url(url: str, timeout: float = 3.0) -> dict:
    """¿Contesta este panel en `url`? (GET /healthz; vale cualquier respuesta JSON con status ok)."""
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{url.rstrip('/')}/healthz", timeout=timeout) as r:  # noqa: S310 — URLs propias
            ok = r.status == 200 and b'"ok"' in r.read(200)
        return {
            "url": url,
            "ok": ok,
            "ms": round((time.monotonic() - t0) * 1000),
            "error": "" if ok else "no es el panel",
        }
    except (OSError, urllib.error.URLError, ValueError) as e:
        motivo = getattr(e, "reason", e)
        return {"url": url, "ok": False, "ms": round((time.monotonic() - t0) * 1000), "error": str(motivo)[:120]}


@router.post("/probar")
def probar(body: ProbarIn):
    if body.que == "servidor":
        srv = red.servidor()
        pruebas = [{**_probar_url(u["url"]), "donde": u["donde"]} for u in srv["urls"]]
        return {"que": "servidor", "ok": all(p["ok"] for p in pruebas), "pruebas": pruebas}
    if body.que in ("esp32", "ip"):
        if body.que == "ip":
            try:
                host = red.validar_ipv4(body.ip or "")
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
        else:
            host = red.esp32_host()
            if not host:
                return {
                    "que": "esp32",
                    "ok": False,
                    "host": "",
                    "ms": 0,
                    "error": "No hay placa configurada (ESP32_HOST)",
                }
        t0 = time.monotonic()
        ok = red.es_la_placa(host, timeout=2.5)
        ms = round((time.monotonic() - t0) * 1000)
        if ok and body.que == "esp32":
            red.visto_esp32()
            _despertar_puentes()
        return {
            "que": body.que,
            "ok": ok,
            "host": host,
            "ms": ms,
            "error": "" if ok else f"{host} no contesta como el ESP32 del panel",
        }
    raise HTTPException(422, "Se prueba «servidor», «esp32» o una «ip»")


@router.patch("/ajustes")
def cambiar(body: AjustesIn):
    cambios = body.model_dump(exclude_unset=True)
    antes = red.esp32_host()
    try:
        red.cambiar_ajustes(cambios)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if red.esp32_host() != antes:
        log.info("Dirección del ESP32 cambiada a mano: %s → %s", antes or "ninguna", red.esp32_host() or "ninguna")
        _despertar_puentes()
    return _estado()


@router.post("/latido")
def latido(body: LatidoIn, request: Request):
    """De la extensión (con su token Bearer). La IP es la de quien llama, no la que diga el cuerpo."""
    ip = request.client.host if request.client else ""
    red.latido_extension(body.version, body.url, ip, body.navegador)
    srv = red.servidor()
    return {"status": "success", "principal": srv["principal"], "urls": [u["url"] for u in srv["urls"]]}
