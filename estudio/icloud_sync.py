#!/usr/bin/env python3
"""
Puente de sincronizacion bidireccional Calendario ESP32 <-> iCloud.

Objetivo: los dos calendarios deben terminar siendo IGUALES en cada
ciclo. Para conseguirlo sin resucitar eventos borrados ni perder
eventos nuevos, cada evento se compara contra tres fuentes:

  - in_icloud: como esta AHORA en iCloud (o None si no existe)
  - in_esp32:  como esta AHORA en el ESP32 (o None si no existe)
  - in_last:   como estaba la ULTIMA VEZ que ambos lados coincidieron
               (guardado en calendar_sync_state.json)

in_last es la clave para distinguir "lo he borrado" de "es nuevo":
  - Si un uid estaba en in_last y ahora falta en un lado -> se borro
    ahi a proposito, hay que borrarlo tambien en el otro lado.
  - Si un uid NUNCA estuvo en in_last -> es nuevo, hay que copiarlo
    al lado que todavia no lo tiene.

Ver explicacion completa de la logica de fusion en _merge().
"""

import asyncio
import datetime
import json
import random
import string
from pathlib import Path

import aiohttp
import caldav
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent

# =====================================================================
# CONFIGURACION - se lee de .env (ver .env.example), nunca en el codigo
# =====================================================================
from core import config as _config
from core.logging_config import get_logger

from .esp32_link import LINK

log = get_logger("icloud")

ICLOUD_USERNAME = _config.ICLOUD_USERNAME
ICLOUD_APP_PASSWORD = _config.ICLOUD_APP_PASSWORD  # contraseña de aplicacion, no la normal
ICLOUD_CALENDAR_NAME = _config.ICLOUD_CALENDAR_NAME  # crea este calendario en tu iPhone antes de usarlo
ICLOUD_URL = "https://caldav.icloud.com/"

SYNC_INTERVAL_SEC = 480
CALENDAR_REPLY_TIMEOUT_SEC = 8

STATE_FILE = Path(__file__).parent / "calendar_sync_state.json"

# Si el ESP32 pasa de tener mas de este numero de eventos sincronizados
# a reportar 0 de golpe, se trata como lectura fallida/parcial en vez
# de como un borrado masivo real (ver _sync_once). Sube este numero si
# tienes pocos eventos habitualmente y quieres permitir borrarlos todos
# de una vez sin que salte la guarda de seguridad.
EMPTY_ESP32_SAFETY_THRESHOLD = 3

TYPE_TO_CATEGORY = {"examen": "EXAMEN", "entrega": "ENTREGA", "evento": "EVENTO"}
CATEGORY_TO_TYPE = {v: k for k, v in TYPE_TO_CATEGORY.items()}

# =====================================================================
# UTILIDADES CALDAV (bloqueantes: se ejecutan en un hilo aparte)
# =====================================================================
def _connect_calendar():
    client = caldav.DAVClient(url=ICLOUD_URL, username=ICLOUD_USERNAME, password=ICLOUD_APP_PASSWORD)
    principal = client.principal()
    for cal in principal.calendars():
        if cal.name == ICLOUD_CALENDAR_NAME:
            return cal
    log.info(f"No existe el calendario '{ICLOUD_CALENDAR_NAME}', creandolo...")
    return principal.make_calendar(name=ICLOUD_CALENDAR_NAME)


def _normalize_event(uid, summary, dtstart, cat_str):
    """Convierte lo que sea que devuelva iCloud a nuestro formato
    canonico {date, title, type}, siempre igual sin importar como lo
    haya guardado/formateado iCloud por dentro."""
    if hasattr(dtstart, "strftime"):
        date_str = dtstart.strftime("%Y-%m-%d")
    else:
        date_str = str(dtstart)[:10]
    title = str(summary).strip()
    etype = CATEGORY_TO_TYPE.get(str(cat_str).upper().strip(), "evento")
    return {"date": date_str, "title": title, "type": etype}


def _fetch_icloud_events(cal, objects=None):
    """Lee los eventos de iCloud. Si se pasa `objects`, lo rellena con uid -> objeto
    CalDAV para editar o borrar después sin buscar por UID (iCloud contesta 412 a
    esa consulta)."""
    events = {}
    for ev in cal.events():
        try:
            ev.load()
            ical = ICalendar.from_ical(ev.data)
            for comp in ical.walk("VEVENT"):
                uid = str(comp.get("UID"))
                if objects is not None:
                    objects[uid] = ev
                summary = comp.get("SUMMARY", "")
                dtstart = comp.get("DTSTART").dt
                categories = comp.get("CATEGORIES")
                cat_str = "EVENTO"
                if categories:
                    cats = categories.cats if hasattr(categories, "cats") else [categories]
                    if cats:
                        cat_str = str(cats[0])
                events[uid] = _normalize_event(uid, summary, dtstart, cat_str)
        except Exception as e:
            log.warning(f"Aviso: no se pudo leer un evento de iCloud: {e}")
    return events


def _build_ics(uid, date_str, title, etype):
    cal = ICalendar()
    cal.add("prodid", "-//PanelEstudio//ESP32//ES")
    cal.add("version", "2.0")
    ev = IEvent()
    ev.add("uid", uid)
    ev.add("summary", title)
    y, m, d = [int(x) for x in date_str.split("-")]
    day = datetime.date(y, m, d)
    ev.add("dtstart", day)
    ev.add("dtend", day + datetime.timedelta(days=1))
    ev.add("categories", [TYPE_TO_CATEGORY.get(etype, "EVENTO")])
    ev.add("dtstamp", datetime.datetime.utcnow())
    cal.add_component(ev)
    return cal.to_ical().decode("utf-8")


def _icloud_upsert(cal, objects, uid, date_str, title, etype):
    ics = _build_ics(uid, date_str, title, etype)
    existing = objects.get(uid)
    if existing is None:
        cal.save_event(ics)
        return
    existing.data = ics
    existing.save()


def _icloud_delete(objects, uid):
    """Devuelve True si el evento ya no está en iCloud."""
    ev = objects.get(uid)
    if ev is None:
        return True  # ya no estaba
    try:
        ev.delete()
        return True
    except Exception as e:
        log.warning(f"Aviso: no se pudo borrar {uid} en iCloud: {e!r}")
        return False


def _events_from_esp32(raw_events):
    events = {}
    for ev in raw_events:
        uid = ev.get("uid") or _generate_uid()
        events[uid] = {"date": ev["date"], "title": ev["title"].strip(), "type": ev["type"]}
    return events


def _generate_uid():
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
    return f"{int(datetime.datetime.now().timestamp())}-{rand}@panel-estudio"

# =====================================================================
# ESTADO LOCAL
# =====================================================================
def _load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

# =====================================================================
# FUSION DE TRES VIAS
# =====================================================================
def _merge(icloud_events, esp32_events, last_state):
    """
    Devuelve (merged, icloud_upserts, icloud_deletes).

    merged         -> lista final que se enviara al ESP32 (calendar_sync_full)
    icloud_upserts -> eventos que hay que crear/actualizar en iCloud
    icloud_deletes -> uids que hay que borrar en iCloud

    Reglas por cada uid, segun donde exista y si estaba sincronizado
    antes (in_last):

      - No existe en ningun lado -> nada que hacer.
      - Solo existe en ESP32:
          - Si estaba sincronizado antes (in_last) -> se borro en
            iCloud -> no se añade a merged (asi se borra tambien del
            ESP32 en el siguiente push).
          - Si es nuevo (nunca estuvo en in_last) -> se creo en el
            ESP32 -> subir a iCloud.
      - Solo existe en iCloud:
          - Si estaba sincronizado antes (in_last) -> se borro en el
            ESP32 -> hay que borrarlo tambien en iCloud.
          - Si es nuevo -> se creo directamente en iCloud -> añadir
            al ESP32.
      - Existe en ambos y son iguales -> se mantiene.
      - Existe en ambos pero son distintos -> gana el lado que
        cambio respecto a in_last (edicion); si ambos cambiaron a la
        vez, gana iCloud por convenio.
    """
    all_uids = set(icloud_events) | set(esp32_events) | set(last_state)
    merged = {}
    icloud_upserts = {}
    icloud_deletes = []

    for uid in all_uids:
        in_icloud = icloud_events.get(uid)
        in_esp32 = esp32_events.get(uid)
        in_last = last_state.get(uid)

        # Nunca ha existido en ningun lado -> nada que hacer
        if in_icloud is None and in_esp32 is None:
            continue

        # Solo existe en ESP32
        if in_icloud is None and in_esp32 is not None:
            if in_last is not None:
                # Borrado en iCloud -> se propaga borrandolo tambien
                # del ESP32 (no se añade a merged)
                continue
            else:
                # Nuevo, creado en el ESP32 -> subir a iCloud
                merged[uid] = in_esp32
                icloud_upserts[uid] = in_esp32
            continue

        # Solo existe en iCloud
        if in_esp32 is None and in_icloud is not None:
            if in_last is not None:
                # Borrado en el ESP32 -> se propaga borrandolo tambien
                # de iCloud
                icloud_deletes.append(uid)
                continue
            else:
                # Nuevo, creado directamente en iCloud -> añadir al ESP32
                merged[uid] = in_icloud
            continue

        # Existe en ambos lados
        if in_icloud == in_esp32:
            merged[uid] = in_icloud
        else:
            changed_in_icloud = in_last is not None and in_icloud != in_last
            changed_in_esp32 = in_last is not None and in_esp32 != in_last
            if changed_in_icloud and not changed_in_esp32:
                merged[uid] = in_icloud
            elif changed_in_esp32 and not changed_in_icloud:
                merged[uid] = in_esp32
                icloud_upserts[uid] = in_esp32
            else:
                merged[uid] = in_icloud

    return merged, icloud_upserts, icloud_deletes

# =====================================================================
# PUENTE PRINCIPAL
# =====================================================================
class IcloudSyncBridge:
    def __init__(self, session: aiohttp.ClientSession, esp32_ws_url: str):
        self.session = session
        self.esp32_ws_url = esp32_ws_url

    async def run_forever(self):
        if not ICLOUD_USERNAME or not ICLOUD_APP_PASSWORD:
            log.warning("Sin ICLOUD_USERNAME/ICLOUD_APP_PASSWORD en .env: sincronizacion desactivada")
            return
        while True:
            try:
                await self._sync_once()
            except Exception as e:
                log.warning(f"Error durante la sincronizacion: {e}")
            await asyncio.sleep(SYNC_INTERVAL_SEC)

    async def _get_esp32_events(self):
        if LINK.state == "offline" and not LINK.can_try():
            return None  # en pausa tras varios fallos: ni se intenta ni se ensucia el log
        try:
            async with self.session.ws_connect(self.esp32_ws_url, heartbeat=10, timeout=10) as ws:
                await ws.send_str(json.dumps({"type": "calendar_get"}))
                # El ESP32 difunde a todos los clientes (pomodoro, pantalla, carátula...):
                # se ignora lo que no sea la lista hasta que llegue o venza el plazo.
                async with asyncio.timeout(CALENDAR_REPLY_TIMEOUT_SEC):
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        data = json.loads(msg.data)
                        if data.get("type") == "calendar_list":
                            LINK.seen()
                            return _events_from_esp32(data.get("events", []))
                log.warning(f"El ESP32 cerró la conexión sin mandar el calendario (código {ws.close_code})")
        except TimeoutError:
            log.warning(f"El ESP32 no mandó el calendario en {CALENDAR_REPLY_TIMEOUT_SEC} s")
        except aiohttp.ClientConnectionError as e:
            LINK.failed(e)
        except Exception as e:
            log.warning(f"No se pudo leer el calendario del ESP32: {e!r}")
        return None

    async def _push_to_esp32(self, merged_events):
        payload = {
            "type": "calendar_sync_full",
            "events": [
                {"uid": uid, "date": ev["date"], "title": ev["title"], "type": ev["type"]}
                for uid, ev in merged_events.items()
            ],
        }
        try:
            async with self.session.ws_connect(self.esp32_ws_url, heartbeat=10, timeout=10) as ws:
                await ws.send_str(json.dumps(payload))
                await asyncio.sleep(0.3)
        except Exception as e:
            log.warning(f"No se pudo enviar la lista fusionada al ESP32: {e}")

    async def _sync_once(self):
        log.info("Iniciando ciclo de sincronizacion...")

        cal = await asyncio.to_thread(_connect_calendar)
        icloud_objects = {}
        icloud_events = await asyncio.to_thread(_fetch_icloud_events, cal, icloud_objects)
        log.info(f"iCloud: {len(icloud_events)} eventos")

        esp32_events = await self._get_esp32_events()
        if esp32_events is None and LINK.state != "offline":
            # Un corte suelto (reconexiones de otros clientes) no debe costar un ciclo entero de 8 min
            await asyncio.sleep(2)
            esp32_events = await self._get_esp32_events()
        if esp32_events is None:
            if LINK.state != "offline":
                log.info("ESP32 no disponible ahora mismo, se reintentara en el siguiente ciclo")
            return
        log.info(f"ESP32: {len(esp32_events)} eventos")

        last_state = _load_state()

        # GUARDA DE SEGURIDAD: si el ESP32 pasa de tener varios eventos
        # sincronizados a reportar 0 de golpe, es mucho mas probable que
        # sea una lectura fallida/parcial (WS cortado a mitad, race
        # condition justo al arrancar el ESP32) que un borrado masivo
        # real hecho a mano. Se aborta el ciclo entero sin tocar ni
        # iCloud ni el ESP32, y se reintenta en el siguiente ciclo.
        if len(esp32_events) == 0 and len(last_state) > EMPTY_ESP32_SAFETY_THRESHOLD:
            log.warning(
                f"AVISO: el ESP32 reporta 0 eventos pero antes "
                f"tenia {len(last_state)} sincronizados. Esto huele a lectura "
                f"fallida/parcial, no a un borrado real -> se aborta este "
                f"ciclo sin tocar nada."
            )
            return

        merged, icloud_upserts, icloud_deletes = _merge(icloud_events, esp32_events, last_state)

        for uid, ev in icloud_upserts.items():
            log.info(f"Subiendo a iCloud: {ev['title']} ({ev['date']})")
            await asyncio.to_thread(_icloud_upsert, cal, icloud_objects, uid, ev["date"], ev["title"], ev["type"])

        failed_deletes = {}
        for uid in icloud_deletes:
            log.info(f"Borrando de iCloud: {uid}")
            if not await asyncio.to_thread(_icloud_delete, icloud_objects, uid):
                failed_deletes[uid] = last_state[uid]

        # CLAVE: tras escribir en iCloud, releemos EXACTAMENTE lo que
        # iCloud guardo (puede formatear fechas/campos a su manera) y
        # usamos eso -no lo que nosotros creiamos haber enviado- como
        # referencia para la proxima comparacion. Esto es lo que evita
        # los "falsos cambios" y las subidas repetidas en bucle.
        if icloud_upserts:
            fresh_icloud = await asyncio.to_thread(_fetch_icloud_events, cal)
            for uid in icloud_upserts:
                if uid in fresh_icloud:
                    merged[uid] = fresh_icloud[uid]

        await self._push_to_esp32(merged)
        # Un borrado fallido se queda en el estado: así el próximo ciclo lo reintenta
        # en vez de tomar el evento de iCloud por nuevo y devolverlo al ESP32
        _save_state({**merged, **failed_deletes})
        log.info(f"Ciclo completado. {len(merged)} eventos sincronizados.")
