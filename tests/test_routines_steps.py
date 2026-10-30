"""Rutinas con pasos (séptima ronda): pasos marcados por días, horario calculado y plantillas."""
from datetime import date, timedelta

import pytest

HOY = date.today()


@pytest.fixture(autouse=True)
def sin_rutinas(client):
    """La BD de los tests es compartida y dos bloques no pueden pisarse: cada test empieza sin rutinas."""
    from app.database import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM inbox WHERE item_type='rutina'")


def _item(client, iid):
    return next(i for i in client.get("/api/items").json()["items"] if i["id"] == iid)


def _rutina(client, **extra):
    return client.post("/api/items", json={"text": "Mañana", "type": "rutina", "due_time": "07:00", **extra}).json()["id"]


def test_pasos_con_duracion_y_horario(client):
    rid = _rutina(client)
    a = client.post("/api/items", json={"text": "Ducha 10 min", "parent_id": rid, "due_time": "07:00"}).json()["id"]
    b = client.post("/api/items", json={"text": "Desayuno (20 m)", "parent_id": rid, "due_time": "07:10"}).json()["id"]
    c = client.post("/api/items", json={"text": "Agua", "parent_id": rid, "due_time": "07:30"}).json()["id"]
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
    # cada paso se queda con su hora: la de la plantilla es solo el punto de partida
    assert [(k["text"], k["duration_min"], k["due_time"]) for k in kids] == [("Agua", 2, "08:00"), ("Ducha", 10, "08:02")]
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
    a = client.post("/api/items", json={"text": "Desayunar 20 min", "parent_id": rid, "due_time": "07:30"}).json()["id"]
    uni = client.post("/api/items", json={"text": "Universidad", "parent_id": rid, "duration_min": 330, "due_time": "08:30"}).json()["id"]
    sol = client.post("/api/items", json={"text": "Tomar el sol 20 min", "parent_id": rid, "due_time": "14:00"}).json()["id"]
    assert client.patch(f"/api/items/{uni}", json={"step_days": [0, 1, 2, 3, 4]}).status_code == 200
    assert client.patch(f"/api/items/{rid}", json={"step_days": [0]}).status_code == 422  # la rutina no: sus pasos
    lunes, sabado = _dia_que_sea(0), _dia_que_sea(5)
    dl = client.get("/api/routines/day", params={"date": lunes}).json()
    r = next(x for x in dl["rutinas"] if x["id"] == rid)
    assert [(s["title"], s["at"]) for s in r["steps"]] == [("Desayunar", "07:30"), ("Universidad", "08:30"), ("Tomar el sol", "14:00")]
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


def _dia(client, fecha, rid):
    return next(x for x in client.get("/api/routines/day", params={"date": fecha}).json()["rutinas"] if x["id"] == rid)


def _paso(client, rid, texto, **extra):
    return client.post("/api/items", json={"text": texto, "parent_id": rid, **extra})


def test_cada_paso_a_su_hora_sin_encadenar(client):
    rid = _rutina(client)
    a = _paso(client, rid, "Desayunar 20 min", due_time="08:00").json()["id"]
    b = _paso(client, rid, "Gimnasio 1h", due_time="17:30").json()["id"]
    sin = _paso(client, rid, "Leer 30 min").json()["id"]
    hoy = HOY.isoformat()
    # con huecos: nada empieza porque acabe el anterior, y sin hora no se le inventa una
    r = _dia(client, hoy, rid)
    assert [(s["id"], s["at"], s["end"]) for s in r["steps"]] == [(a, "08:00", "08:20"), (b, "17:30", "18:30"), (sin, None, None)]
    # cambiar una hora o una duración no mueve a los demás
    assert client.patch(f"/api/items/{a}", json={"due_time": "09:00", "duration_min": 45}).status_code == 200
    assert _dia(client, hoy, rid)["steps"][1]["at"] == "17:30"
    # el orden del día es el del reloj, no el de la lista
    assert client.patch(f"/api/items/{sin}", json={"due_time": "06:30"}).status_code == 200
    assert [s["id"] for s in _dia(client, hoy, rid)["steps"]] == [sin, a, b]
    # quitarle la hora lo devuelve al final; el calendario lo pone en todo el día
    assert client.patch(f"/api/items/{sin}", json={"due_time": ""}).status_code == 200
    es = [x for x in client.get("/api/calendar/entries", params={"start": hoy, "end": hoy}).json()["entries"] if x.get("routine_id") == rid]
    assert [(x["title"], x["all_day"]) for x in es] == [("Desayunar", False), ("Gimnasio", False), ("Leer", True)]


def test_sin_horas_en_los_pasos_la_rutina_sigue_entera_en_el_calendario(client):
    rid = _rutina(client)
    _paso(client, rid, "Ducha 10 min")
    es = [x for x in client.get("/api/calendar/entries", params={"start": HOY.isoformat(), "end": HOY.isoformat()}).json()["entries"] if x.get("item_id") == rid]
    assert len(es) == 1 and es[0]["start"].endswith("07:00") and es[0]["steps"][0]["at"] is None


def test_un_bloque_no_puede_pisar_a_otro(client):
    rid = _rutina(client)
    uni = _paso(client, rid, "Universidad", due_time="08:30", duration_min=330).json()["id"]
    b = _paso(client, rid, "Gimnasio 1h", due_time="15:00").json()["id"]
    # por dentro: rechazado sin tocar nada, y con el primer hueco en el que cabe
    r = client.patch(f"/api/items/{b}", json={"due_time": "13:30"})
    assert r.status_code == 409 and "Universidad" in r.json()["detail"] and "08:30–14:00" in r.json()["detail"] and "14:00." in r.json()["detail"]
    assert _item(client, b)["due_time"] == "15:00"
    # tocar justo al final no es chocar
    assert client.patch(f"/api/items/{b}", json={"due_time": "14:00"}).status_code == 200
    # alargar un bloque también cuenta, y un cambio rechazado no guarda nada del resto
    r = client.patch(f"/api/items/{uni}", json={"text": "Otra cosa", "duration_min": 400})
    assert r.status_code == 409 and _item(client, uni)["text"] == "Universidad" and _item(client, uni)["duration_min"] == 330
    # crear encima también se rechaza y no deja nada a medias
    r = _paso(client, rid, "Dentista", due_time="09:00")
    assert r.status_code == 409 and "Dentista" not in [i["text"] for i in client.get("/api/items").json()["items"]]
    # sin duración ocupa solo su hora: se puede justo después, no a la misma hora
    c = _paso(client, rid, "Vitaminas", due_time="07:00").json()["id"]
    assert _paso(client, rid, "Agua", due_time="07:01").status_code == 200
    assert _paso(client, rid, "Café", due_time="07:00").status_code == 409
    assert client.patch(f"/api/items/{c}", json={"due_time": "07:00"}).status_code == 200  # consigo mismo no choca
    # sin hora nunca choca
    assert _paso(client, rid, "Leer 8h").status_code == 200


def test_el_choque_mira_los_dias_y_las_demas_rutinas(client):
    lv = client.post("/api/items", json={"text": "Clases", "type": "rutina", "repeat": {"freq": "weekly", "days": [0, 1, 2, 3, 4]}}).json()["id"]
    finde = client.post("/api/items", json={"text": "Finde", "type": "rutina", "repeat": {"freq": "weekly", "days": [5, 6]}}).json()["id"]
    _paso(client, lv, "Universidad", due_time="09:00", duration_min=60)
    # distintos días: la misma hora vale
    assert _paso(client, finde, "Paseo", due_time="09:00", duration_min=60).status_code == 200
    # si pasa a tocar también entre semana, ya choca (y dice cuándo)
    r = client.patch(f"/api/items/{finde}", json={"repeat": {"freq": "weekly", "days": [0, 5, 6]}})
    assert r.status_code == 409 and "Paseo" in r.json()["detail"] and "los lunes" in r.json()["detail"]
    assert _item(client, finde)["repeat_text"] == "Fines de semana"
    # lo mismo con los días propios de un paso
    tarde = client.post("/api/items", json={"text": "Tarde", "type": "rutina"}).json()["id"]
    sab = _paso(client, tarde, "Sábados", duration_min=30).json()["id"]
    assert client.patch(f"/api/items/{sab}", json={"step_days": [5]}).status_code == 200
    # el sábado a las 9:30 pisa el paseo; a las 10:00, ya no
    assert client.patch(f"/api/items/{sab}", json={"due_time": "09:30"}).status_code == 409
    assert client.patch(f"/api/items/{sab}", json={"due_time": "10:00"}).status_code == 200
    # una rutina sin pasos con hora también ocupa su sitio
    client.post("/api/items", json={"text": "Meditar", "type": "rutina", "due_time": "22:00", "duration_min": 20})
    r = _paso(client, lv, "Repaso", due_time="22:10")
    assert r.status_code == 409 and "Meditar" in r.json()["detail"]


def test_plantilla_con_choques_crea_lo_demas_sin_hora(client):
    rid = _rutina(client)
    _paso(client, rid, "Trabajo", due_time="07:32", duration_min=10)
    res = client.post("/api/routine-templates/apply", json={"key": "b:manana", "due_time": "07:30", "steps": [
        {"title": "Agua", "duration_min": 2}, {"title": "Ducha", "duration_min": 10}, {"title": "Desayunar", "duration_min": 15, "due_time": "08:00"},
        {"title": "Flexible", "duration_min": 5, "due_time": ""}]}).json()
    assert res["sin_hora"] == ["Ducha"]
    kids = {i["text"]: i["due_time"] for i in client.get("/api/items").json()["items"] if i["parent_id"] == res["id"]}
    assert kids == {"Agua": "07:30", "Ducha": None, "Desayunar": "08:00", "Flexible": None}


def test_solapes_que_vienen_de_antes_se_avisan(client, app):
    from app.database import get_db
    rid = _rutina(client)
    a = _paso(client, rid, "Uno", due_time="10:00", duration_min=60).json()["id"]
    b = _paso(client, rid, "Dos", due_time="12:00", duration_min=30).json()["id"]
    with get_db() as conn:
        conn.execute("UPDATE inbox SET due_time='10:30' WHERE id=?", (b,))
    r = _dia(client, HOY.isoformat(), rid)
    assert [(s["id"], s["clash"]) for s in r["steps"]] == [(a, "Dos"), (b, "Uno")]


def _colocar(client, sid, before=None, **extra):
    return client.post(f"/api/routines/{sid}/place", json={"before_id": before, "day": HOY.isoformat(), **extra})


def _horas(client, rid):
    return [(s["title"], s["at"]) for s in _dia(client, HOY.isoformat(), rid)["steps"]]


def test_colocar_un_bloque_le_da_la_hora_de_ese_sitio(client):
    rid = _rutina(client)
    a = _paso(client, rid, "Desayuno 20 min", due_time="08:00").json()["id"]
    b = _paso(client, rid, "Clase 1h", due_time="10:00").json()["id"]
    olvidado = _paso(client, rid, "Ducha 15 min").json()["id"]
    # el olvidado, que estaba abajo: al soltarlo entre los dos, empieza cuando acaba el de arriba
    r = _colocar(client, olvidado, b)
    assert r.json()["at"] == "08:20" and _horas(client, rid) == [("Desayuno", "08:00"), ("Ducha", "08:20"), ("Clase", "10:00")]
    # arriba del todo, acaba justo cuando empieza el primero
    assert _colocar(client, b, a).json()["at"] == "07:00"
    # al final, detrás del último
    assert _colocar(client, b).json()["at"] == "08:35"
    assert _horas(client, rid) == [("Desayuno", "08:00"), ("Ducha", "08:20"), ("Clase", "08:35")]


def test_colocar_entre_los_que_no_tienen_hora(client):
    rid = _rutina(client)
    a = _paso(client, rid, "Con hora 30 min", due_time="08:00").json()["id"]
    x = _paso(client, rid, "Uno").json()["id"]
    y = _paso(client, rid, "Dos").json()["id"]
    # entre los que no tienen hora solo cambia el orden, también si lo sube al primero de ellos
    assert _colocar(client, y, x).json()["at"] is None
    assert _horas(client, rid) == [("Con hora", "08:00"), ("Dos", None), ("Uno", None)]
    # uno con hora que baja entre ellos se queda sin hora
    assert _colocar(client, a).json()["at"] is None
    assert _item(client, a)["due_time"] is None
    # sin ninguna hora en la línea, tampoco se inventa una
    assert _colocar(client, x, y).json()["at"] is None and all(at is None for _, at in _horas(client, rid))


def test_si_no_cabe_no_se_mueve_nada_sin_permiso(client):
    rid = _rutina(client)
    _paso(client, rid, "Desayuno 20 min", due_time="08:00")
    c = _paso(client, rid, "Clase 1h", due_time="08:20").json()["id"]
    d = _paso(client, rid, "Café 10 min", due_time="09:30").json()["id"]
    e = _paso(client, rid, "Gimnasio 1h", due_time="09:45").json()["id"]
    g = _paso(client, rid, "Ducha larga 20 min", due_time="12:00").json()["id"]
    n = _paso(client, rid, "Ducha 30 min").json()["id"]
    antes = _horas(client, rid)
    r = _colocar(client, n, c).json()
    # solo lo justo: el empujón se va absorbiendo en los huecos que encuentra por el camino
    assert r["status"] == "no_cabe" and r["minutos"] == 30 and r["mover"] == ["Clase", "Café", "Gimnasio"]
    assert _horas(client, rid) == antes
    assert _colocar(client, n, c, push=True).json() == {"status": "success", "at": "08:20", "movidos": 3}
    assert _horas(client, rid) == [("Desayuno", "08:00"), ("Ducha", "08:20"), ("Clase", "08:50"), ("Café", "09:50"), ("Gimnasio", "10:00"), ("Ducha larga", "12:00")]
    assert (_item(client, d)["due_time"], _item(client, e)["due_time"], _item(client, g)["due_time"]) == ("09:50", "10:00", "12:00")


def test_colocar_respeta_las_demas_rutinas_y_el_dia(client):
    otra = client.post("/api/items", json={"text": "Otra", "type": "rutina"}).json()["id"]
    _paso(client, otra, "Dentista 1h", due_time="09:00")
    rid = _rutina(client)
    _paso(client, rid, "Primero 1h", due_time="08:00")
    b = _paso(client, rid, "Tercero 30 min", due_time="12:00").json()["id"]
    n = _paso(client, rid, "Segundo 30 min").json()["id"]
    # justo tras «Primero» está el dentista de la otra rutina: choca, avisa y no cambia nada
    r = _colocar(client, n, b)
    assert r.status_code == 409 and "Dentista" in r.json()["detail"] and _item(client, n)["due_time"] is None
    # un bloque de otro día no cuenta para la línea de ese día
    lunes, sabado = _dia_que_sea(0), _dia_que_sea(5)
    client.patch(f"/api/items/{b}", json={"step_days": [5]})
    r = client.post(f"/api/routines/{n}/place", json={"before_id": b, "day": lunes})
    assert r.status_code == 422
    assert client.post(f"/api/routines/{n}/place", json={"before_id": b, "day": sabado}).status_code == 409
    assert client.post(f"/api/routines/{rid}/place", json={}).status_code == 404  # solo bloques


def test_no_se_coloca_pasada_la_medianoche(client):
    rid = _rutina(client)
    _paso(client, rid, "Tarde 1h", due_time="23:30")
    n = _paso(client, rid, "Otro 30 min").json()["id"]
    assert _colocar(client, n).status_code == 422 and _item(client, n)["due_time"] is None
    t = _paso(client, rid, "Con hora 30 min", due_time="06:00").json()["id"]
    assert _colocar(client, t, n).status_code == 422 and _item(client, t)["due_time"] == "06:00"
