"""Hoy, estado de conexiones e índice de la paleta."""
from datetime import date


def test_hoy(client):
    hoy = date.today().isoformat()
    client.post("/api/calendar/events", json={"title": "Evento de hoy (Hoy)", "start": f"{hoy}T23:30"})
    tid = client.post("/api/items", json={"text": "Tarea de hoy (Hoy)", "type": "tarea"}).json()["id"]
    client.patch(f"/api/items/{tid}", json={"due_date": hoy})
    client.post("/api/items", json={"text": "Rutina de hoy (Hoy)", "type": "rutina"})
    t = client.get("/api/today").json()
    assert any(e["title"] == "Evento de hoy (Hoy)" for e in t["eventos"])
    assert any(e["title"] == "Tarea de hoy (Hoy)" for e in t["tareas"])
    assert any(e["title"] == "Rutina de hoy (Hoy)" for e in t["rutinas"])
    assert "pendientes" in t["flashcards"] and t["date"] == hoy


def test_estado_de_conexiones(client):
    s = client.get("/api/status").json()
    keys = {i["key"] for i in s["items"]}
    assert {"esp32", "cal-icloud", "cal-esp32", "backups"} <= keys
    assert all("label" in i and "state" in i for i in s["items"])


def test_indice_de_la_paleta(client):
    client.post("/api/items", json={"text": "Buscar con Ctrl+K", "type": "idea"})
    idx = client.get("/api/palette/index").json()
    assert any(n["id"] == "nota-inicial" for n in idx["notes"])
    assert any(i["text"] == "Buscar con Ctrl+K" and i["type"] == "idea" for i in idx["items"])
    assert set(idx) == {"notes", "items", "meals", "events"}


def test_portada_de_notas(client):
    r = client.get("/api/notes-home")
    assert r.status_code == 200, r.text
    d = r.json()
    assert {"estados", "total", "recientes", "por_escribir", "olvidadas", "flashcards"} <= set(d)
    assert d["total"] == sum(d["estados"].values())
    assert all(n["status"] == "por-escribir" for n in d["por_escribir"])
    assert all(n["status"] in ("en-desarrollo", "consolidado") for n in d["recientes"])


def test_hoy_con_el_gasto_del_dia(client):
    hoy = date.today().isoformat()
    client.post("/api/finance/movements", json={"fecha": hoy, "importe": 4.5, "tipo": "gasto", "concepto": "Café hoy"})
    client.post("/api/finance/movements", json={"fecha": hoy, "importe": 100, "tipo": "ingreso", "concepto": "Venta"})
    d = client.get("/api/today").json()["dinero"]
    assert d["hoy"] >= 4.5 and d["mes"] >= d["hoy"]
    assert any(u["concepto"] == "Café hoy" for u in d["ultimos"])
    assert all(u["concepto"] != "Venta" for u in d["ultimos"])  # solo gastos
