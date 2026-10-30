"""Rutinas con pasos (séptima ronda): pasos marcados por días, horario calculado y plantillas."""
from datetime import date, timedelta

HOY = date.today()


def _item(client, iid):
    return next(i for i in client.get("/api/items").json()["items"] if i["id"] == iid)


def _rutina(client, **extra):
    return client.post("/api/items", json={"text": "Mañana", "type": "rutina", "due_time": "07:00", **extra}).json()["id"]


def test_pasos_con_duracion_y_horario(client):
    rid = _rutina(client)
    a = client.post("/api/items", json={"text": "Ducha 10 min", "parent_id": rid}).json()["id"]
    b = client.post("/api/items", json={"text": "Desayuno (20 m)", "parent_id": rid}).json()["id"]
    c = client.post("/api/items", json={"text": "Agua", "parent_id": rid}).json()["id"]
    sa = _item(client, a)
    assert (sa["text"], sa["duration_min"], sa["type"], sa["parent_id"]) == ("Ducha", 10, "rutina", rid)
    assert _item(client, b)["duration_min"] == 20 and _item(client, c)["duration_min"] is None
    # en el calendario: con horario, cada bloque va en su hora (sin duración, un cuarto de hora)
    es = [x for x in client.get("/api/calendar/entries", params={"start": HOY.isoformat(), "end": HOY.isoformat()}).json()["entries"]
          if x["kind"] == "routine" and x.get("routine_id") == rid]
    assert [(x["title"], x["start"][11:], x["end"][11:]) for x in es] == [("Ducha", "07:00", "07:10"), ("Desayuno", "07:10", "07:30"), ("Agua", "07:30", "07:45")]
    # y en Hoy se juntan otra vez en su rutina
    hoy = next(x for x in client.get("/api/today").json()["rutinas"] if x["item_id"] == rid)
    assert [s["title"] for s in hoy["steps"]] == ["Ducha", "Desayuno", "Agua"] and not hoy["done"]
    # un paso no lleva regla propia
    assert client.patch(f"/api/items/{a}", json={"repeat": {"freq": "daily"}}).status_code == 422
    # una tarea no entra como paso de una rutina
    t = client.post("/api/items", json={"text": "tarea suelta"}).json()["id"]
    r = client.post(f"/api/items/{t}/move", json={"parent_id": rid})
    assert r.status_code == 422 and "rutina" in r.json()["detail"]


def test_marcar_pasos_marca_la_rutina(client):
    rid = _rutina(client)
    a = client.post("/api/items", json={"text": "Uno", "parent_id": rid}).json()["id"]
    b = client.post("/api/items", json={"text": "Dos", "parent_id": rid}).json()["id"]
    client.patch(f"/api/items/{a}", json={"done": True})
    assert _item(client, a)["done"] and not _item(client, rid)["done"]
    client.patch(f"/api/items/{b}", json={"done": True})
    assert _item(client, rid)["done"] and _item(client, rid)["streak"]["actual"] == 1  # todos hechos → rutina hecha
    client.patch(f"/api/items/{a}", json={"done": False})
    assert not _item(client, rid)["done"]  # falta uno → ya no
    # marcar la rutina marca sus pasos; desmarcarla los desmarca
    client.patch(f"/api/items/{rid}", json={"done": True})
    assert _item(client, a)["done"] and _item(client, b)["done"]
    client.patch(f"/api/items/{rid}", json={"done": False})
    assert not _item(client, a)["done"] and not _item(client, b)["done"]
    # el historial solo apunta la rutina, no cada paso
    rev = client.get("/api/review/week").json()
    assert not any(x["item_id"] in (a, b) for x in rev["rutinas"])


def test_plantillas_de_rutina(client):
    lista = client.get("/api/routine-templates").json()["plantillas"]
    manana = next(t for t in lista if t["key"] == "b:manana")
    assert manana["builtin"] and manana["steps"][0]["at"] == "07:30" and manana["total_min"] > 0
    # crear desde la de serie, con otra hora y los pasos editados
    rid = client.post("/api/routine-templates/apply", json={"key": "b:manana", "due_time": "08:00",
                                                           "steps": [{"title": "Agua", "duration_min": 2}, {"title": "Ducha", "duration_min": 10}]}).json()["id"]
    it = _item(client, rid)
    assert it["type"] == "rutina" and it["due_time"] == "08:00" and it["text"] == "Rutina de mañana"
    kids = [i for i in client.get("/api/items").json()["items"] if i["parent_id"] == rid]
    kids.sort(key=lambda i: -i["sort_order"])
    assert [(k["text"], k["duration_min"]) for k in kids] == [("Agua", 2), ("Ducha", 10)]
    # guardar una rutina propia como plantilla y volver a usarla
    saved = client.post("/api/routine-templates", json={"item_id": rid, "name": "Mi mañana"}).json()
    mia = next(t for t in client.get("/api/routine-templates").json()["plantillas"] if t["key"] == saved["key"])
    assert not mia["builtin"] and [s["title"] for s in mia["steps"]] == ["Agua", "Ducha"] and mia["due_time"] == "08:00"
    rid2 = client.post("/api/routine-templates/apply", json={"key": saved["key"], "title": "Mañana de finde",
                                                            "repeat": {"freq": "weekly", "days": [5, 6]}}).json()["id"]
    assert _item(client, rid2)["repeat_text"] == "Fines de semana"
    assert client.delete(f"/api/routine-templates/{saved['id']}").status_code == 200
    assert client.post("/api/routine-templates/apply", json={"key": saved["key"]}).status_code == 404
    # una tarea no se guarda como plantilla de rutina
    t = client.post("/api/items", json={"text": "tarea"}).json()["id"]
    assert client.post("/api/routine-templates", json={"item_id": t}).status_code == 422


def _dia_que_sea(weekday: int) -> str:
    d = HOY + timedelta(days=(weekday - HOY.weekday()) % 7)
    return d.isoformat()


def test_bloques_con_dias_y_hora_fija(client):
    rid = client.post("/api/items", json={"text": "Mi día prueba", "type": "rutina", "due_time": "07:30"}).json()["id"]
    a = client.post("/api/items", json={"text": "Desayunar 20 min", "parent_id": rid}).json()["id"]
    uni = client.post("/api/items", json={"text": "Universidad", "parent_id": rid, "duration_min": 330, "due_time": "08:30"}).json()["id"]
    sol = client.post("/api/items", json={"text": "Tomar el sol 20 min", "parent_id": rid}).json()["id"]
    assert client.patch(f"/api/items/{uni}", json={"step_days": [0, 1, 2, 3, 4]}).status_code == 200
    assert client.patch(f"/api/items/{rid}", json={"step_days": [0]}).status_code == 422  # la rutina no: sus pasos
    lunes, sabado = _dia_que_sea(0), _dia_que_sea(5)
    dl = client.get("/api/routines/day", params={"date": lunes}).json()
    r = next(x for x in dl["rutinas"] if x["id"] == rid)
    assert [(s["title"], s["at"], s["fixed"]) for s in r["steps"]] == [("Desayunar", "07:30", False), ("Universidad", "08:30", True), ("Tomar el sol", "14:00", False)]
    ds = client.get("/api/routines/day", params={"date": sabado}).json()
    r = next(x for x in ds["rutinas"] if x["id"] == rid)
    assert [s["title"] for s in r["steps"]] == ["Desayunar", "Tomar el sol"] and r["otros_dias"][0]["days_text"] == "De lunes a viernes"
    # el sábado, sin universidad: con los dos pasos de ese día hechos, la rutina queda hecha
    for sid in (a, sol):
        client.patch(f"/api/items/{sid}", json={"done": True, "day": sabado})
    assert next(x for x in client.get("/api/routines/day", params={"date": sabado}).json()["rutinas"] if x["id"] == rid)["done"]
    assert client.patch(f"/api/items/{uni}", json={"done": True, "day": sabado}).status_code == 422  # no toca
    # quitar los días propios: vuelve a todos los de la rutina
    client.patch(f"/api/items/{uni}", json={"step_days": []})
    assert "Universidad" in [s["title"] for s in next(x for x in client.get("/api/routines/day", params={"date": sabado}).json()["rutinas"] if x["id"] == rid)["steps"]]


def test_tarea_asociada_a_un_bloque(client):
    rid = client.post("/api/items", json={"text": "Tarde", "type": "rutina"}).json()["id"]
    paso = client.post("/api/items", json={"text": "Leer / estudiar", "parent_id": rid}).json()["id"]
    t = client.post("/api/items", json={"text": "Estudiar tema 3"}).json()["id"]
    assert client.patch(f"/api/items/{t}", json={"routine_step": paso}).status_code == 200
    it = _item(client, t)
    assert it["routine_step"] == paso and it["routine_label"] == "Tarde › Leer / estudiar"
    d = client.get("/api/routines/day").json()
    r = next(x for x in d["rutinas"] if x["id"] == rid)
    assert [x["text"] for x in r["steps"][0]["tasks"]] == ["Estudiar tema 3"]
    # hecha hoy: sigue viéndose hoy, tachada
    client.patch(f"/api/items/{t}", json={"done": True})
    r = next(x for x in client.get("/api/routines/day").json()["rutinas"] if x["id"] == rid)
    assert r["steps"][0]["tasks"][0]["done"]
    # reglas: una rutina no se asocia; solo a rutinas
    assert client.patch(f"/api/items/{rid}", json={"routine_step": paso}).status_code == 422
    otra = client.post("/api/items", json={"text": "no es rutina"}).json()["id"]
    assert client.patch(f"/api/items/{t}", json={"routine_step": otra}).status_code == 422
    # soltarla, y al borrar el paso las asociadas quedan sueltas
    client.patch(f"/api/items/{t}", json={"routine_step": 0})
    assert _item(client, t).get("routine_step") is None
    client.patch(f"/api/items/{t}", json={"routine_step": paso})
    client.delete(f"/api/items/{paso}")
    assert _item(client, t).get("routine_step") is None


def test_plantilla_mi_dia(client):
    t = next(x for x in client.get("/api/routine-templates").json()["plantillas"] if x["key"] == "b:dia")
    uni = next(s for s in t["steps"] if s["title"] == "Universidad")
    assert uni["fixed"] and uni["at"] == "08:30" and uni["days_text"] == "De lunes a viernes"
    rid = client.post("/api/routine-templates/apply", json={"key": "b:dia"}).json()["id"]
    sab = client.get("/api/routines/day", params={"date": _dia_que_sea(5)}).json()
    titles = [s["title"] for s in next(x for x in sab["rutinas"] if x["id"] == rid)["steps"]]
    assert "Universidad" not in titles and "Gimnasio" not in titles and titles[0] == "Levantarme"


def test_mover_un_bloque_no_le_pone_dias_y_saltar_hoy(client):
    rid = _rutina(client)
    a = client.post("/api/items", json={"text": "Ducha", "parent_id": rid}).json()["id"]
    b = client.post("/api/items", json={"text": "Desayuno", "parent_id": rid}).json()["id"]
    # reordenar dentro de la rutina: el paso sigue los días de la rutina (antes recibía «cada día» y rompía el día)
    assert client.post(f"/api/items/{b}/move", json={"target": "rutinas", "parent_id": rid, "before_id": a}).status_code == 200
    hoy = date.today().isoformat()
    dia = client.get(f"/api/routines/day?date={hoy}").json()
    r = next(x for x in dia["rutinas"] if x["id"] == rid)
    assert [s["title"] for s in r["steps"]][:2] == ["Desayuno", "Ducha"]
    # saltar hoy: cuenta como resuelto, pero se ve como saltado; deshacerlo lo deja pendiente
    assert client.post(f"/api/routines/{a}/skip", json={"day": hoy}).status_code == 200
    r = next(x for x in client.get(f"/api/routines/day?date={hoy}").json()["rutinas"] if x["id"] == rid)
    ducha = next(s for s in r["steps"] if s["id"] == a)
    assert ducha["done"] and ducha["skipped"]
    client.patch(f"/api/items/{b}", json={"done": True, "day": hoy})
    r = next(x for x in client.get(f"/api/routines/day?date={hoy}").json()["rutinas"] if x["id"] == rid)
    assert r["done"]  # hecho + saltado = rutina resuelta
    client.post(f"/api/routines/{a}/skip", json={"day": hoy, "skip": False})
    r = next(x for x in client.get(f"/api/routines/day?date={hoy}").json()["rutinas"] if x["id"] == rid)
    assert not r["done"] and not next(s for s in r["steps"] if s["id"] == a)["skipped"]
    assert client.post(f"/api/routines/{rid}/skip", json={}).status_code == 404  # solo bloques
