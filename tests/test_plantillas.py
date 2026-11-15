"""P-4 · Plantillas: las de serie de día y rutina, aplicar por clave y las tuyas (renombrar, duplicar, editar, copiar,
borrar a la papelera)."""

import json


def test_dias_de_serie_y_aplicar(client):
    serie = client.get("/api/day-templates/serie").json()["plantillas"]
    assert {p["key"] for p in serie} >= {"b:clase", "b:estudio", "b:examen", "b:entrega", "b:finde"}
    assert all(p["descripcion"] and p["eventos"] for p in serie)
    r = client.post("/api/day-templates/aplicar", json={"key": "b:estudio", "day": "2026-12-02"}).json()
    assert r["eventos"] == 6
    evs = client.get("/api/calendar/entries", params={"start": "2026-12-02", "end": "2026-12-02"}).json()["entries"]
    assert any(e["title"] == "Bloque 1 · tema nuevo" and e["start"] == "2026-12-02T09:00" for e in evs)
    assert client.post("/api/day-templates/aplicar", json={"key": "b:nada", "day": "2026-12-02"}).status_code == 404


def test_rutinas_de_serie_con_descripcion(client):
    pl = client.get("/api/routine-templates").json()["plantillas"]
    keys = {p["key"] for p in pl}
    assert {"b:manana", "b:noche", "b:gimnasio", "b:dormir", "b:flashcards", "b:batch", "b:estirar"} <= keys
    assert all(p["descripcion"] for p in pl if p["builtin"])


def test_copiar_renombrar_editar_duplicar_y_borrar_rutina(client):
    c = client.post("/api/plantillas/rutina/copiar", json={"key": "b:gimnasio"}).json()
    tid = c["id"]
    r = client.patch(
        f"/api/plantillas/rutina/{tid}",
        json={
            "name": "Gimnasio corto",
            "descripcion": "Para días con prisa",
            "pasos": "calentar 5m\nfuerza 30m",
            "due_time": "18:30",
        },
    )
    assert r.status_code == 200
    t = next(p for p in client.get("/api/routine-templates").json()["plantillas"] if p["id"] == tid)
    assert t["title"] == "Gimnasio corto" and t["descripcion"] == "Para días con prisa" and t["due_time"] == "18:30"
    assert [(s["title"], s["duration_min"], s["at"]) for s in t["steps"]] == [
        ("Calentar", 5, "18:30"),
        ("Fuerza", 30, "18:35"),
    ]
    d = client.post(f"/api/plantillas/rutina/{tid}/duplicar").json()
    assert d["name"] == "Gimnasio corto (copia)"
    # borrar va a la papelera y se puede deshacer
    res = client.delete(f"/api/routine-templates/{d['id']}").json()
    assert res["undo_token"]


def test_dia_y_tablero_renombrar_y_duplicar(client):
    c = client.post("/api/plantillas/dia/copiar", json={"key": "b:clase", "name": "Martes de clase"}).json()
    client.patch(f"/api/plantillas/dia/{c['id']}", json={"descripcion": "Con laboratorio"})
    mine = next(p for p in client.get("/api/day-templates").json()["plantillas"] if p["id"] == c["id"])
    assert mine["key"] == f"u:{c['id']}" and mine["descripcion"] == "Con laboratorio" and mine["eventos"] == 5
    b = client.post(
        "/api/board-templates", json={"name": "Mi kanban", "data": json.dumps({"nodes": [], "descripcion": "x"})}
    ).json()
    client.patch(f"/api/plantillas/tablero/{b['id']}", json={"name": "Kanban de la casa"})
    dup = client.post(f"/api/plantillas/tablero/{b['id']}/duplicar").json()
    names = {t["name"] for t in client.get("/api/board-templates").json()["templates"]}
    assert {"Kanban de la casa", dup["name"]} <= names
    assert client.patch(f"/api/plantillas/tablero/{b['id']}", json={"pasos": "x"}).status_code == 422
    assert client.patch("/api/plantillas/otra/1", json={"name": "x"}).status_code == 404
