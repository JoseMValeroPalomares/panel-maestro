"""Calendario .ics por URL con token (P-11): solo lectura, revocable, sin sesión y sin enseñar el hash."""

from datetime import date, timedelta


def D(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


def test_enlace_crear_usar_rehacer_y_revocar(client, anon):
    client.post("/api/calendar/events", json={"title": "Examen feed", "start": f"{D(3)}T09:00", "kind": "examen"})
    assert client.get("/api/calendar/ics-enlace").json()["activo"] is False
    assert anon.get("/cal/loquesea.ics").status_code == 404

    r = client.post("/api/calendar/ics-enlace").json()
    path = r["path"]
    assert path.startswith("/cal/") and path.endswith(".ics") and r["url"].endswith(path)
    feed = anon.get(path)  # sin sesión
    assert feed.status_code == 200 and feed.headers["content-type"].startswith("text/calendar")
    assert "Examen feed" in feed.text and "attachment" not in feed.headers.get("content-disposition", "")
    st = client.get("/api/calendar/ics-enlace").json()
    assert st["activo"] and st["ultimo_uso"]

    # el hash no sale por /api/prefs ni se puede pisar desde ahí
    assert "calendario.ics" not in client.get("/api/prefs").json()["prefs"]
    assert client.put("/api/prefs/calendario.ics", json={"value": {"hash": "x"}}).status_code == 422

    nuevo = client.post("/api/calendar/ics-enlace").json()["path"]
    assert anon.get(path).status_code == 404 and anon.get(nuevo).status_code == 200
    client.delete("/api/calendar/ics-enlace")
    assert anon.get(nuevo).status_code == 404
    # solo lectura: nada de escribir por esa ruta
    assert anon.post(nuevo).status_code in (401, 403, 404, 405)


def test_tareas_opcionales(client, anon):
    client.post("/api/items", json={"text": "Entregar práctica feed", "type": "tarea", "due_date": D(2)})
    path = client.post("/api/calendar/ics-enlace").json()["path"]
    assert "Entregar práctica feed" not in anon.get(path).text
    txt = anon.get(path + "?tareas=1").text
    assert "Entregar práctica feed" in txt and "TRANSPARENT" in txt


def test_descarga_con_sesion_sigue(client):
    client.post("/api/calendar/events", json={"title": "Examen ICS", "start": f"{D(4)}T09:00", "kind": "examen"})
    r = client.get("/api/calendar/export.ics")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"] and "Examen ICS" in r.text
