"""Sexta ronda · calendario: eventos, tareas con fecha como bloques, rutinas (hábitos),
plantillas de día, exportación .ics y papelera."""
from datetime import date, timedelta

import pytest

from app import routines

HOY = date.today()
D = lambda n: (HOY + timedelta(days=n)).isoformat()  # noqa: E731


def _entries(client, d0, d1):
    r = client.get("/api/calendar/entries", params={"start": d0, "end": d1})
    assert r.status_code == 200, r.text
    return r.json()["entries"]


def test_eventos_crud_y_rango(client):
    r = client.post("/api/calendar/events", json={"title": "Dentista", "start": f"{D(1)}T17:00"})
    eid = r.json()["id"]
    ev = client.get(f"/api/calendar/events/{eid}").json()
    assert ev["end"] == f"{D(1)}T18:00" and not ev["all_day"]  # 1 h por defecto
    client.post("/api/calendar/events", json={"title": "Congreso", "start": D(3), "end": D(5), "all_day": True, "kind": "evento"})
    keys = {e["title"]: e for e in _entries(client, D(0), D(6))}
    assert "Dentista" in keys and keys["Congreso"]["all_day"]
    # mover conserva la duración; redimensionar cambia el fin
    client.patch(f"/api/calendar/events/{eid}", json={"start": f"{D(2)}T09:30"})
    ev = client.get(f"/api/calendar/events/{eid}").json()
    assert (ev["start"], ev["end"]) == (f"{D(2)}T09:30", f"{D(2)}T10:30")
    client.patch(f"/api/calendar/events/{eid}", json={"end": f"{D(2)}T11:00"})
    assert client.get(f"/api/calendar/events/{eid}").json()["end"] == f"{D(2)}T11:00"
    # pasar a todo el día y volver
    client.patch(f"/api/calendar/events/{eid}", json={"all_day": True})
    assert client.get(f"/api/calendar/events/{eid}").json()["start"] == D(2)
    assert client.post("/api/calendar/events", json={"title": "Mal", "start": "ayer"}).status_code == 422


def test_tarea_con_fecha_es_un_bloque(client):
    tid = client.post("/api/items", json={"text": "Estudiar SO", "type": "tarea"}).json()["id"]
    # arrastrar al calendario = poner fecha, hora y duración a la tarea
    assert client.patch(f"/api/items/{tid}", json={"due_date": D(1), "due_time": "10:00", "duration_min": 90}).status_code == 200
    e = next(e for e in _entries(client, D(1), D(1)) if e["key"] == f"t{tid}")
    assert (e["start"], e["end"], e["all_day"]) == (f"{D(1)}T10:00", f"{D(1)}T11:30", False)
    # cambiar la tarea mueve el bloque (es el mismo dato) y quitar la hora lo deja «todo el día»
    client.patch(f"/api/items/{tid}", json={"due_time": ""})
    e = next(e for e in _entries(client, D(1), D(1)) if e["key"] == f"t{tid}")
    assert e["all_day"] and e["start"] == D(1)
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == tid)
    assert item["due_date"] == D(1) and item["due_time"] is None


def test_rutina_racha_y_mapa(client):
    rid = client.post("/api/items", json={"text": "Leer 20 min", "type": "rutina", "repeat": {"freq": "daily"}}).json()["id"]
    it = next(i for i in client.get("/api/items").json()["items"] if i["id"] == rid)
    assert it["type"] == "rutina" and it["origin"] == "rutinas" and not it["done"]
    # completar desde la lista (hoy) y desde el calendario (ayer)
    client.patch(f"/api/items/{rid}", json={"done": True})
    client.post(f"/api/routines/{rid}/check", json={"day": D(-1), "done": True})
    it = next(i for i in client.get("/api/items").json()["items"] if i["id"] == rid)
    assert it["done"] and it["streak"]["actual"] == 2
    occ = [e for e in _entries(client, D(-1), D(1)) if e["kind"] == "routine" and e["id"] == rid]
    assert [e["done"] for e in occ] == [True, True, False]
    stats = client.get(f"/api/routines/{rid}/stats").json()
    assert stats["total"] == 2 and stats["heatmap"][-1]["day"] >= HOY.isoformat()
    # desmarcar hoy no rompe la racha de ayer
    client.patch(f"/api/items/{rid}", json={"done": False})
    it = next(i for i in client.get("/api/items").json()["items"] if i["id"] == rid)
    assert not it["done"] and it["streak"]["actual"] == 1
    # no cuenta en el total de pendientes del Inbox
    counts = client.get("/api/items/counts").json()
    assert counts["rutinas"]["pendientes"] >= 1
    # historial de la revisión semanal: la semana de ayer (los lunes, ayer cae en la semana anterior)
    rev = client.get("/api/review/week", params={"start": D(-1)}).json()
    assert any(x["item_id"] == rid for x in rev["rutinas"])


def test_reglas_de_repeticion():
    lunes = date(2026, 10, 26)
    assert routines.occurs_on({"freq": "weekly", "days": [0, 2]}, lunes)
    assert not routines.occurs_on({"freq": "weekly", "days": [0, 2]}, lunes + timedelta(days=1))
    cada3 = {"freq": "interval", "every": 3, "from": "2026-10-24"}
    assert [routines.occurs_on(cada3, date(2026, 10, 24) + timedelta(days=i)) for i in range(7)] == [True, False, False, True, False, False, True]
    assert routines.describe({"freq": "weekly", "days": [0, 1, 2, 3, 4]}) == "De lunes a viernes"
    with pytest.raises(ValueError):
        routines.clean_repeat({"freq": "weekly", "days": []})
    rule = {"freq": "daily"}
    done = {(date(2026, 10, 20) + timedelta(days=i)).isoformat() for i in (0, 1, 2, 4, 5)}
    s = routines.streak(rule, done, date(2026, 10, 26), date(2026, 10, 20))
    assert s == {"actual": 2, "mejor": 3}  # hoy (26) aún sin hacer no rompe


def test_plantilla_de_dia(client):
    dia = D(10)
    client.post("/api/calendar/events", json={"title": "Gimnasio", "start": f"{dia}T07:00", "end": f"{dia}T08:00"})
    tid = client.post("/api/items", json={"text": "Bloque de estudio", "type": "tarea"}).json()["id"]
    client.patch(f"/api/items/{tid}", json={"due_date": dia, "due_time": "18:00", "duration_min": 120})
    r = client.post("/api/day-templates", json={"name": "Día de clase", "day": dia})
    assert r.status_code == 200 and r.json()["eventos"] == 2
    tpl = r.json()["id"]
    destino = D(17)
    r = client.post(f"/api/day-templates/{tpl}/apply", json={"day": destino})
    assert r.json()["eventos"] == 2
    titulos = {(e["title"], e["start"]) for e in _entries(client, destino, destino) if e["kind"] == "event"}
    assert ("Gimnasio", f"{destino}T07:00") in titulos and ("Bloque de estudio", f"{destino}T18:00") in titulos
    assert client.post("/api/day-templates", json={"name": "Vacío", "day": D(300)}).status_code == 422


def test_exportar_ics(client):
    client.post("/api/calendar/events", json={"title": "Examen ICS", "start": f"{D(4)}T09:00", "kind": "examen"})
    r = client.get("/api/calendar/export.ics")
    assert r.status_code == 200 and "BEGIN:VCALENDAR" in r.text and "Examen ICS" in r.text and "TZID=Europe/Madrid" in r.text


def test_papelera(client):
    eid = client.post("/api/calendar/events", json={"title": "Se borra", "start": D(2)}).json()["id"]
    tid = client.post("/api/items", json={"text": "Tarea a la papelera", "type": "tarea"}).json()["id"]
    client.delete(f"/api/calendar/events/{eid}")
    client.delete(f"/api/items/{tid}")
    lista = client.get("/api/trash").json()
    assert lista["ttl_days"] == 30
    por_titulo = {e["title"]: e for e in lista["entries"]}
    assert por_titulo["Se borra"]["label"] == "evento" and por_titulo["Tarea a la papelera"]["label"] == "tarea"
    # una idea o una rutina se nombran como lo que son
    for text, type_ in (("Idea a la papelera", "idea"), ("Rutina a la papelera", "rutina")):
        client.delete(f"/api/items/{client.post('/api/items', json={'text': text, 'type': type_}).json()['id']}")
    por_titulo = {e["title"]: e for e in client.get("/api/trash").json()["entries"]}
    assert por_titulo["Idea a la papelera"]["label"] == "idea" and por_titulo["Rutina a la papelera"]["label"] == "rutina"
    e = por_titulo["Se borra"]
    assert client.post(f"/api/trash/{e['db']}/{e['token']}/restore").json()["restored"] == 1
    assert any(x["title"] == "Se borra" for x in _entries(client, D(2), D(2)))
    t = por_titulo["Tarea a la papelera"]
    assert client.delete(f"/api/trash/{t['db']}/{t['token']}").status_code == 200
    assert client.post(f"/api/trash/{t['db']}/{t['token']}/restore").status_code == 404


def test_recordatorios(client):
    from datetime import datetime
    from app.reminders import due
    now = datetime.now().replace(second=0, microsecond=0)
    client.post("/api/calendar/events", json={"title": "Aviso pronto", "start": (now + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M")})
    rid = client.post("/api/items", json={"text": "Rutina con hora", "type": "rutina", "due_time": (now + timedelta(minutes=5)).strftime("%H:%M")}).json()["id"]
    titulos = {r["title"]: r for r in due(horizon=10)}
    assert "Aviso pronto" in titulos           # 15 min antes por defecto
    assert "Rutina con hora" in titulos
    client.put("/api/prefs/reminders", json={"value": {"evento": {"on": False}}})
    assert "Aviso pronto" not in {r["title"] for r in due(horizon=10)}
    client.patch(f"/api/items/{rid}", json={"done": True})
    assert "Rutina con hora" not in {r["title"] for r in due(horizon=10)}
    client.put("/api/prefs/reminders", json={"value": {}})
    assert client.get("/api/reminders").status_code == 200


def test_un_evento_de_todo_el_dia_no_aparece_al_dia_siguiente(client):
    client.post("/api/calendar/events", json={"title": "Solo el día 20", "start": D(20), "all_day": True})
    client.post("/api/calendar/events", json={"title": "Del 21 al 22", "start": D(21), "end": D(23), "all_day": True})
    titulos = lambda d: {e["title"] for e in _entries(client, d, d)}  # noqa: E731
    assert "Solo el día 20" in titulos(D(20)) and "Solo el día 20" not in titulos(D(21))
    assert "Del 21 al 22" in titulos(D(21)) and "Del 21 al 22" in titulos(D(22)) and "Del 21 al 22" not in titulos(D(23))


def test_editor_cambia_todo_el_dia_y_varios_dias(client):
    eid = client.post("/api/calendar/events", json={"title": "Viaje", "start": D(20), "all_day": True}).json()["id"]
    # el editor manda inicio y fin con la forma nueva: se respetan (antes se forzaba 09:00)
    client.patch(f"/api/calendar/events/{eid}", json={"all_day": False, "start": f"{D(20)}T16:30", "end": f"{D(20)}T18:00"})
    ev = client.get(f"/api/calendar/events/{eid}").json()
    assert (ev["start"], ev["end"], ev["all_day"]) == (f"{D(20)}T16:30", f"{D(20)}T18:00", False)
    # varios días (fin exclusivo) y vuelta a un solo día con fin vacío
    client.patch(f"/api/calendar/events/{eid}", json={"all_day": True, "start": D(20), "end": D(23), "location": "Granada"})
    ev = client.get(f"/api/calendar/events/{eid}").json()
    assert (ev["start"], ev["end"], ev["location"]) == (D(20), D(23), "Granada")
    client.patch(f"/api/calendar/events/{eid}", json={"start": D(20), "end": ""})
    assert client.get(f"/api/calendar/events/{eid}").json()["end"] == D(21)
