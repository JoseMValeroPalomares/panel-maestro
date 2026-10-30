"""
Sincronía del calendario del Panel (tabla `events`, app/calendar.py) con iCloud (CalDAV) y
con el ESP32. El Panel es el centro: cada ciclo se fusiona **en tres vías** Panel ↔ iCloud y
después Panel ↔ ESP32, y al final se manda al ESP32 la lista completa.

Tres vías, igual que el puente anterior (estudio/icloud_sync.py), por cada par:
  - en los dos lados e iguales → nada;
  - en los dos y distintos → gana el lado que cambió desde la última vez (si cambiaron los
    dos, o no hay «última vez», gana el Panel);
  - solo en un lado → si estaba en la última vez, se borró en el otro: se borra; si no, es
    nuevo: se copia al otro lado.
Duplicados: un evento nuevo de fuera con el mismo título, día y tipo que uno del Panel que ese
lado aún no conoce se toma por el mismo (se adopta su uid) en vez de crear otro.
Guardas: si un lado devuelve 0 eventos cuando antes había varios, o el Panel está vacío y
antes no, el par se salta ese ciclo sin borrar nada. Lo que se borra en el Panel por la
sincronía va a la papelera (se puede recuperar 30 días).

Formatos que se comparan:
  iCloud: {title, start, end, all_day, kind[, location]} (hora local de Madrid, igual que el Panel;
          el lugar solo aparece si lo hay, así los eventos sin lugar se comparan como antes)
  ESP32:  {date, title, type} (el reloj solo guarda el día; la hora vive en el Panel). Al ESP32
          se le manda además "time" (HH:MM) y "end", que el firmware actual ignora.

Estado de la última vez: estudio/calendar_sync_v2.json (fuera de git). La primera vez no hay
«última vez»: los tres lados se unen (los eventos de iCloud y del ESP32 entran en el Panel con
su mismo uid) y nada se borra.
"""
import asyncio
import datetime as dt
import json
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
from icalendar import Calendar as ICalendar
from icalendar import Event as IEvent

from core.logging_config import get_logger

from . import icloud_sync as legacy
from .esp32_link import LINK

log = get_logger("calendar")
TZ = ZoneInfo("Europe/Madrid")
STATE_FILE = Path(__file__).parent / "calendar_sync_v2.json"
SYNC_INTERVAL_SEC = 480
EMPTY_GUARD = 3
ESP32_TYPES = ("examen", "entrega", "evento")

STATUS: dict[str, dict] = {"icloud": {"state": "idle"}, "esp32": {"state": "idle"}}
WAKE: asyncio.Event | None = None


def request_sync() -> None:
    if WAKE is not None:
        WAKE.set()


# ─────────────────────────────────────────────
# Formatos
# ─────────────────────────────────────────────

def canon(row) -> dict:
    """Evento del Panel → forma comparable con iCloud."""
    start, end, all_day = row["start"], row["end"], bool(row["all_day"])
    if all_day and not end:
        end = (dt.date.fromisoformat(start[:10]) + dt.timedelta(days=1)).isoformat()
    out = {"title": (row["title"] or "").strip(), "start": start, "end": end, "all_day": all_day, "kind": row["kind"] or "evento"}
    loc = (row["location"] if "location" in row.keys() else None) or ""
    if loc.strip():
        out["location"] = loc.strip()
    return out


def esp_view(ev: dict) -> dict:
    kind = ev.get("kind") or ev.get("type") or "evento"
    return {"date": ev["start"][:10], "title": ev["title"].strip(), "type": kind if kind in ESP32_TYPES else "evento"}


def three_way(local: dict, remote: dict, last: dict, eq=lambda a, b: a == b, *, panel_wins=True) -> dict:
    """Plan de cambios para un par. local/remote/last: uid → evento (en la forma comparable)."""
    plan = {"to_local": {}, "del_local": [], "to_remote": {}, "del_remote": [], "same": {}}
    for uid in set(local) | set(remote) | set(last):
        a, r, l = local.get(uid), remote.get(uid), last.get(uid)
        if a is not None and r is not None:
            if eq(a, r):
                plan["same"][uid] = a
                continue
            ch_a = l is not None and not eq(a, l)
            ch_r = l is not None and not eq(r, l)
            if ch_r and not ch_a:
                plan["to_local"][uid] = r
            else:
                plan["to_remote"][uid] = a
        elif a is not None:
            (plan["del_local"].append(uid) if l is not None else plan["to_remote"].__setitem__(uid, a))
        elif r is not None:
            (plan["del_remote"].append(uid) if l is not None else plan["to_local"].__setitem__(uid, r))
    return plan


def find_twin(conn, ev: dict, known_uids: set[str]) -> str | None:
    """Evento del Panel igual (título, día, tipo) que ese lado aún no conoce: es el mismo."""
    for row in conn.execute("SELECT uid, title, start, kind FROM events WHERE substr(start, 1, 10)=?", (ev["start"][:10],)):
        if row["uid"] not in known_uids and row["title"].strip().lower() == ev["title"].strip().lower() \
                and esp_view(canon({**dict(row), "end": None, "all_day": "T" not in row["start"]}))["type"] == esp_view(ev)["type"]:
            return row["uid"]
    return None


# ─────────────────────────────────────────────
# Panel (tabla events)
# ─────────────────────────────────────────────

def panel_events() -> dict[str, dict]:
    from app.database import get_db
    with get_db() as conn:
        return {r["uid"]: canon(r) for r in conn.execute("SELECT * FROM events")}


def panel_apply(changes: dict[str, dict], deletes: list[str], source: str, known: set[str], esp_mode=False) -> dict[str, str]:
    """Escribe en el Panel lo que llega de fuera. Devuelve {uid_de_fuera: uid_del_panel} si se adoptó uno."""
    from app.calendar import _normalize
    from app.database import get_db
    from core import undo
    adopted = {}
    with get_db() as conn:
        for uid, ev in changes.items():
            row = conn.execute("SELECT * FROM events WHERE uid=?", (uid,)).fetchone()
            if row is None:
                twin = find_twin(conn, ev if not esp_mode else {"title": ev["title"], "start": ev["date"], "kind": ev["type"]}, known)
                if twin:
                    adopted[uid] = twin
                    continue
                if esp_mode:
                    start, end, all_day, kind = ev["date"], None, True, ev["type"]
                else:
                    start, end, all_day, kind = ev["start"], ev["end"], ev["all_day"], ev["kind"]
                start, end = _normalize(start, end, all_day)
                conn.execute("INSERT INTO events (uid, title, start, end, all_day, kind, location, source, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (uid, ev["title"], start, end, int("T" not in start), kind if kind in ("evento", "examen", "entrega", "bloque") else "evento",
                              ev.get("location"), source, time.time()))
                continue
            if esp_mode:  # el ESP32 solo sabe el día, el título y el tipo: la hora se conserva
                old = canon(row)
                delta = dt.date.fromisoformat(ev["date"]) - dt.date.fromisoformat(old["start"][:10])
                shift = lambda v: None if v is None else (  # noqa: E731
                    (dt.datetime.fromisoformat(v) + delta).strftime("%Y-%m-%dT%H:%M") if "T" in v
                    else (dt.date.fromisoformat(v) + delta).isoformat())
                kind = row["kind"] if esp_view(old)["type"] == ev["type"] else ev["type"]
                conn.execute("UPDATE events SET title=?, start=?, end=?, kind=?, updated_at=? WHERE uid=?",
                             (ev["title"], shift(old["start"]), shift(row["end"]), kind, time.time(), uid))
            else:
                start, end = _normalize(ev["start"], ev["end"], ev["all_day"])
                conn.execute("UPDATE events SET title=?, start=?, end=?, all_day=?, kind=?, location=?, updated_at=? WHERE uid=?",
                             (ev["title"], start, end, int("T" not in start), ev["kind"], ev.get("location"), time.time(), uid))
        for uid in deletes:
            row = conn.execute("SELECT * FROM events WHERE uid=?", (uid,)).fetchone()
            if row:
                undo.save(conn, "event.delete", {"row": dict(row)}, title=f"{row['title']} (borrado en {source})", count=1)
                conn.execute("DELETE FROM events WHERE uid=?", (uid,))
    return adopted


# ─────────────────────────────────────────────
# iCloud (CalDAV, bloqueante: en un hilo)
# ─────────────────────────────────────────────

def _to_local(v) -> tuple[str, bool]:
    if isinstance(v, dt.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(TZ)
        return v.strftime("%Y-%m-%dT%H:%M"), False
    return v.isoformat()[:10], True


def icloud_fetch(cal, objects: dict) -> dict[str, dict]:
    out = {}
    for obj in cal.events():
        try:
            obj.load()
            for comp in ICalendar.from_ical(obj.data).walk("VEVENT"):
                uid = str(comp.get("UID"))
                objects[uid] = obj
                start, all_day = _to_local(comp.get("DTSTART").dt)
                if comp.get("DTEND") is not None:
                    end, _ = _to_local(comp.get("DTEND").dt)
                elif comp.get("DURATION") is not None:
                    base = comp.get("DTSTART").dt
                    end, _ = _to_local(base + comp.get("DURATION").dt)
                else:
                    end = None
                cats = comp.get("CATEGORIES")
                cat = "EVENTO"
                if cats:
                    lst = cats.cats if hasattr(cats, "cats") else [cats]
                    cat = str(lst[0]) if lst else cat
                kind = {"EXAMEN": "examen", "ENTREGA": "entrega", "BLOQUE": "bloque"}.get(cat.upper().strip(), "evento")
                out[uid] = canon({"title": str(comp.get("SUMMARY", "")), "start": start, "end": end, "all_day": all_day, "kind": kind,
                                  "location": str(comp.get("LOCATION", "") or "")})
        except Exception as e:  # noqa: BLE001 — un evento raro no para el resto
            log.warning(f"No se pudo leer un evento de iCloud: {e!r}")
    return out


def build_ics(uid: str, ev: dict) -> str:
    cal = ICalendar()
    cal.add("prodid", "-//Panel//Calendario//ES")
    cal.add("version", "2.0")
    e = IEvent()
    e.add("uid", uid)
    e.add("summary", ev["title"])
    if ev["all_day"]:
        d0 = dt.date.fromisoformat(ev["start"][:10])
        e.add("dtstart", d0)
        e.add("dtend", dt.date.fromisoformat(ev["end"][:10]) if ev.get("end") else d0 + dt.timedelta(days=1))
    else:
        s = dt.datetime.fromisoformat(ev["start"]).replace(tzinfo=TZ)
        e.add("dtstart", s)
        e.add("dtend", dt.datetime.fromisoformat(ev["end"]).replace(tzinfo=TZ) if ev.get("end") else s + dt.timedelta(hours=1))
    e.add("categories", [(ev.get("kind") or "evento").upper()])
    if ev.get("location"):
        e.add("location", ev["location"])
    e.add("dtstamp", dt.datetime.now(dt.timezone.utc))
    cal.add_component(e)
    return cal.to_ical().decode("utf-8")


def icloud_upsert(cal, objects: dict, uid: str, ev: dict) -> None:
    ics = build_ics(uid, ev)
    obj = objects.get(uid)
    if obj is None:
        cal.save_event(ics)
    else:
        obj.data = ics
        obj.save()


# ─────────────────────────────────────────────
# Estado
# ─────────────────────────────────────────────

def load_state() -> dict:
    """La primera vez no hay «última vez»: todo se trata como nuevo y se une (nada se borra)."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except ValueError:
            pass
    return {"icloud": {}, "esp32": {}}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    tmp.replace(STATE_FILE)


def guard(name: str, local: dict, remote: dict, last: dict) -> str | None:
    if len(remote) == 0 and len(last) > EMPTY_GUARD:
        return f"{name} devuelve 0 eventos y antes había {len(last)}: parece una lectura fallida"
    if len(local) == 0 and len(last) > EMPTY_GUARD:
        return f"el Panel no tiene eventos y antes había {len(last)} sincronizados con {name}: no se borra nada"
    return None


# ─────────────────────────────────────────────
# Puente
# ─────────────────────────────────────────────

class CalendarSyncBridge:
    def __init__(self, session: aiohttp.ClientSession, esp32_ws_url: str):
        self.session = session
        self.esp32_ws_url = esp32_ws_url
        self._legacy = legacy.IcloudSyncBridge(session, esp32_ws_url)

    async def run_forever(self):
        global WAKE
        WAKE = asyncio.Event()
        await asyncio.sleep(5)  # que el Panel termine de arrancar
        while True:
            try:
                await self.sync_once()
            except Exception as e:  # noqa: BLE001
                log.warning(f"Error en la sincronización del calendario: {e!r}")
            WAKE.clear()
            try:
                await asyncio.wait_for(WAKE.wait(), timeout=SYNC_INTERVAL_SEC)
            except TimeoutError:
                pass

    async def sync_once(self):
        state = load_state()
        if legacy.ICLOUD_USERNAME and legacy.ICLOUD_APP_PASSWORD:
            await self._sync_icloud(state)
        else:
            STATUS["icloud"] = {"state": "disabled", "detail": "Sin credenciales de iCloud en .env"}
        if self.esp32_ws_url:
            await self._sync_esp32(state)
        else:
            STATUS["esp32"] = {"state": "disabled", "detail": "Sin ESP32_HOST en .env"}
        save_state(state)

    async def _sync_icloud(self, state: dict):
        STATUS["icloud"] = {**STATUS["icloud"], "state": "syncing"}
        try:
            cal = await asyncio.to_thread(legacy._connect_calendar)
            objects: dict = {}
            remote = await asyncio.to_thread(icloud_fetch, cal, objects)
        except Exception as e:  # noqa: BLE001
            STATUS["icloud"] = {**STATUS["icloud"], "state": "error", "error": str(e)[:200], "error_at": time.time()}
            log.warning(f"iCloud no disponible: {e!r}")
            return
        local, last = panel_events(), state["icloud"]
        why = guard("iCloud", local, remote, last)
        if why:
            log.warning(f"Sincronía con iCloud saltada: {why}")
            STATUS["icloud"] = {**STATUS["icloud"], "state": "error", "error": why, "error_at": time.time()}
            return
        plan = three_way(local, remote, last)
        adopted = panel_apply(plan["to_local"], plan["del_local"], "iCloud", known=set(remote))
        for uid_remote, uid_panel in adopted.items():  # mismo evento con dos uid: el Panel adopta el de iCloud
            from app.database import get_db
            with get_db() as conn:
                conn.execute("UPDATE events SET uid=? WHERE uid=?", (uid_remote, uid_panel))
            plan["to_remote"].pop(uid_panel, None)  # ya está en iCloud con el otro uid: no se sube otra vez
        failed = []
        for uid, ev in plan["to_remote"].items():
            try:
                await asyncio.to_thread(icloud_upsert, cal, objects, uid, ev)
            except Exception as e:  # noqa: BLE001
                failed.append(uid)
                log.warning(f"No se pudo subir «{ev['title']}» a iCloud: {e!r}")
        for uid in plan["del_remote"]:
            if not await asyncio.to_thread(legacy._icloud_delete, objects, uid):
                failed.append(uid)
        # Lo que quedó igual en los dos lados es la nueva «última vez»; lo fallido conserva la anterior
        now_panel = panel_events()
        fresh = await asyncio.to_thread(icloud_fetch, cal, {}) if plan["to_remote"] else remote
        new_last = {uid: ev for uid, ev in now_panel.items() if uid in fresh and fresh[uid] == ev}
        for uid in failed:
            if uid in last:
                new_last[uid] = last[uid]
        state["icloud"] = new_last
        n = sum(len(plan[k]) for k in ("to_local", "del_local", "to_remote", "del_remote"))
        STATUS["icloud"] = {"state": "ok", "at": time.time(), "count": len(new_last), "changes": n,
                            "error": f"{len(failed)} cambios pendientes" if failed else None}
        log.info(f"iCloud: {len(remote)} eventos, {n} cambios ({len(plan['to_local'])}+{len(plan['del_local'])} en el Panel, "
                 f"{len(plan['to_remote'])}+{len(plan['del_remote'])} en iCloud)")

    async def _sync_esp32(self, state: dict):
        if LINK.state in ("offline", "disabled") and not LINK.can_try():
            STATUS["esp32"] = {**STATUS["esp32"], "state": LINK.state}
            return
        STATUS["esp32"] = {**STATUS["esp32"], "state": "syncing"}
        remote = await self._legacy._get_esp32_events()
        if remote is None:
            STATUS["esp32"] = {**STATUS["esp32"], "state": "error" if LINK.state == "online" else "offline",
                               "error": "El ESP32 no mandó su calendario", "error_at": time.time()}
            return
        local = {uid: esp_view(ev) for uid, ev in panel_events().items()}
        last = state["esp32"]
        why = guard("el ESP32", local, remote, last)
        if why:
            log.warning(f"Sincronía con el ESP32 saltada: {why}")
            STATUS["esp32"] = {**STATUS["esp32"], "state": "error", "error": why, "error_at": time.time()}
            return
        plan = three_way(local, remote, last)
        adopted = panel_apply(plan["to_local"], plan["del_local"], "el ESP32", known=set(remote), esp_mode=True)
        # Lista final: todo el Panel (los adoptados con el uid del Panel; el ESP32 borra el suyo duplicado)
        full = panel_events()
        payload = {"type": "calendar_sync_full", "events": [
            {"uid": uid, **esp_view(ev), **({"time": ev["start"][11:16], "end": (ev["end"] or "")[11:16]} if not ev["all_day"] else {})}
            for uid, ev in sorted(full.items(), key=lambda kv: kv[1]["start"])]}
        try:
            async with self.session.ws_connect(self.esp32_ws_url, heartbeat=10, timeout=aiohttp.ClientWSTimeout(ws_close=10)) as ws:
                await ws.send_str(json.dumps(payload, ensure_ascii=False))
                await asyncio.sleep(0.3)
        except Exception as e:  # noqa: BLE001
            LINK.failed(e)
            STATUS["esp32"] = {**STATUS["esp32"], "state": "error", "error": "No se pudo mandar la lista al ESP32", "error_at": time.time()}
            return
        state["esp32"] = {uid: esp_view(ev) for uid, ev in full.items()}
        n = sum(len(plan[k]) for k in ("to_local", "del_local", "to_remote", "del_remote"))
        STATUS["esp32"] = {"state": "ok", "at": time.time(), "count": len(full), "changes": n + len(adopted), "error": None}
        log.info(f"ESP32: {len(remote)} eventos, {n} cambios; enviados {len(full)}")


def status() -> dict:
    return {k: dict(v) for k, v in STATUS.items()}
