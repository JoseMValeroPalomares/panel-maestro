"""Avisos sin repetidos entre navegador y escritorio, y resumen de la mañana (P-11)."""

from datetime import date, datetime, timedelta

from app import reminders


def test_reclamar_un_aviso_solo_lo_da_una_vez(client):
    r = client.post("/api/reminders/vistos", json={"keys": ["a@1", "b@2"]}).json()
    assert r["claimed"] == ["a@1", "b@2"]
    # el segundo cliente (navegador o portátil) ya no lo enseña
    assert client.post("/api/reminders/vistos", json={"keys": ["b@2", "c@3"]}).json()["claimed"] == ["c@3"]
    assert "reminders.vistos" not in client.get("/api/prefs").json()["prefs"]


def test_resumen_cuenta_lo_de_hoy_y_las_atrasadas(client):
    hoy = date.today().isoformat()
    ayer = (date.today() - timedelta(days=1)).isoformat()
    antes = client.get("/api/reminders/resumen").json()["counts"]  # la BD de los tests se comparte
    for t in ("Tarea uno", "Tarea dos"):
        client.post("/api/items", json={"text": t, "type": "tarea", "due_date": hoy})
    client.post("/api/items", json={"text": "Idea suelta", "type": "idea", "due_date": hoy})
    client.post("/api/items", json={"text": "Vieja", "type": "tarea", "due_date": ayer})
    client.post("/api/calendar/events", json={"title": "Entrega SO", "start": hoy, "all_day": True, "kind": "entrega"})
    res = client.get("/api/reminders/resumen").json()
    n = {k: res["counts"][k] - antes[k] for k in antes}
    assert n == {**dict.fromkeys(antes, 0), "tarea": 2, "entrega": 1, "atrasadas": 1}
    assert f"{res['counts']['tarea']} tareas" in res["body"] and "atrasada" in res["body"].split(" · ")[-1]
    assert res["title"].startswith("Hoy, ")


def test_resumen_sale_a_su_hora_y_hasta_tres_horas_tarde(client):
    client.post("/api/items", json={"text": "Algo", "type": "tarea", "due_date": date.today().isoformat()})
    client.put("/api/prefs/reminders", json={"value": {"resumen": {"on": True, "hora": "08:30"}}})
    d = date.today()

    def kinds(h, m):
        return [r["kind"] for r in reminders.due(datetime.combine(d, datetime.min.time()).replace(hour=h, minute=m), 1)]

    assert "resumen" not in kinds(7, 0)
    assert "resumen" in kinds(8, 30) and "resumen" in kinds(11, 0)
    assert "resumen" not in kinds(12, 0)
    client.put("/api/prefs/reminders", json={"value": {"resumen": {"on": False}}})
    assert "resumen" not in kinds(8, 30)


def test_los_avisos_de_tareas_traen_lo_de_los_botones(client):
    now = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=5)
    r = client.post(
        "/api/items",
        json={"text": "Llamar", "type": "tarea", "due_date": now.date().isoformat(), "due_time": now.strftime("%H:%M")},
    ).json()
    data = client.get("/api/reminders?horizon=30").json()
    rem = next(x for x in data["reminders"] if x["kind"] == "tarea")
    assert rem["item_id"] == r["id"] and rem["start"] == now.strftime("%Y-%m-%dT%H:%M") and rem["all_day"] is False
    assert data["shown"] == []
    client.post("/api/reminders/vistos", json={"keys": [rem["key"]]})
    assert client.get("/api/reminders?horizon=30").json()["shown"] == [rem["key"]]
