"""P-1: tareas atrasadas (/api/items/atrasadas) con sus acciones y el aviso de una vez al día."""

from datetime import date, datetime, timedelta

from app import atrasadas
from app.prefs import put as put_pref

HOY = date.today()
AYER = (HOY - timedelta(days=1)).isoformat()


def _nuevo(client, text, type="tarea", **extra):
    r = client.post("/api/items", json={"text": text, "type": type, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _lista(client, **q):
    r = client.get("/api/items/atrasadas", params={"contexto": "todo", **q})
    assert r.status_code == 200, r.text
    return r.json()


def _ids(client):
    return {e["id"] for e in _lista(client)["atrasadas"]}


def _accion(client, ids, action, value=None):
    r = client.post("/api/items/atrasadas/accion", json={"ids": ids, "action": action, "value": value})
    assert r.status_code == 200, r.text
    return r.json()


def test_cuenta_la_de_ayer_y_no_rutinas_ni_hechas_ni_de_hoy(client):
    ayer = _nuevo(client, "AT pagar la luz", due_date=AYER)
    hecha = _nuevo(client, "AT ya hecha", due_date=AYER)
    client.patch(f"/api/items/{hecha}", json={"done": True})
    rutina = _nuevo(client, "AT rutina de ayer", type="rutina", due_date=AYER)
    de_hoy = _nuevo(client, "AT de hoy", due_date=HOY.isoformat())
    ids = _ids(client)
    assert ayer in ids
    assert hecha not in ids and rutina not in ids and de_hoy not in ids
    e = next(e for e in _lista(client)["atrasadas"] if e["id"] == ayer)
    assert e["dias"] == 1 and e["href"] == f"/tareas?item={ayer}" and not e["callada"]


def test_respeta_el_contexto(client):
    uni = _nuevo(client, "AT práctica de la uni", due_date=AYER, contexto="universidad")
    suelta = _nuevo(client, "AT suelta", due_date=AYER)
    solo_uni = {e["id"] for e in _lista(client, contexto="universidad")["atrasadas"]}
    assert uni in solo_uni and suelta not in solo_uni
    puntual = {e["id"] for e in _lista(client, contexto="puntual")["atrasadas"]}
    assert suelta in puntual and uni not in puntual


def test_completar_posponer_y_borrar_con_deshacer(client):
    a = _nuevo(client, "AT completar", due_date=AYER)
    b = _nuevo(client, "AT posponer", due_date=AYER, due_time="18:30")
    c = _nuevo(client, "AT al sábado", due_date=AYER)
    d = _nuevo(client, "AT a una fecha", due_date=AYER)
    e = _nuevo(client, "AT borrar", due_date=AYER)

    _accion(client, [a], "completar")
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == a)
    assert item["done"]

    manana = (HOY + timedelta(days=1)).isoformat()
    assert _accion(client, [b], "posponer", "manana")["due_date"] == manana
    item = next(i for i in client.get("/api/items").json()["items"] if i["id"] == b)
    assert item["due_date"] == manana and item["due_time"] == "18:30"  # la hora se conserva

    sab = _accion(client, [c], "posponer", "sabado")["due_date"]
    assert date.fromisoformat(sab).weekday() == 5 and date.fromisoformat(sab) > HOY

    fecha = (HOY + timedelta(days=10)).isoformat()
    assert _accion(client, [d], "posponer", fecha)["due_date"] == fecha
    r = client.post("/api/items/atrasadas/accion", json={"ids": [d], "action": "posponer", "value": "31-12-2026"})
    assert r.status_code == 422

    res = _accion(client, [e], "borrar")
    assert res["undo_token"] and res["undo_db"] == "brain"
    assert e not in {i["id"] for i in client.get("/api/items").json()["items"]}
    r = client.post(f"/api/trash/brain/{res['undo_token']}/restore")
    assert r.status_code == 200, r.text
    assert e in _ids(client)  # vuelve de la papelera, y sigue atrasada

    assert not ({a, b, c, d} & _ids(client))


def test_una_rutina_no_admite_acciones(client):
    r_id = _nuevo(client, "AT rutina", type="rutina")
    r = client.post("/api/items/atrasadas/accion", json={"ids": [r_id], "action": "completar"})
    assert r.status_code == 422
    r = client.post("/api/items/atrasadas/accion", json={"ids": [1], "action": "olvidar"})
    assert r.status_code == 422


def test_hoy_no_calla_hasta_manana_y_posponer_lo_despierta(client):
    t = _nuevo(client, "AT hoy no", due_date=AYER)
    antes = _lista(client)["pendientes"]
    assert _accion(client, [t], "hoy_no")["hasta"] == (HOY + timedelta(days=1)).isoformat()
    data = _lista(client)
    assert next(e for e in data["atrasadas"] if e["id"] == t)["callada"]  # sigue en la lista, callada
    assert data["pendientes"] == antes - 1
    # un «hoy no» de ayer ya no calla nada
    st = atrasadas.estado()
    st["callar"][str(t)] = AYER
    put_pref(atrasadas.ESTADO, st)
    assert not next(e for e in _lista(client)["atrasadas"] if e["id"] == t)["callada"]


def test_avisar_una_vez_al_dia_a_la_hora(client):
    t = _nuevo(client, "AT aviso", due_date=AYER)
    callada = _nuevo(client, "AT aviso callado", due_date=AYER)
    _accion(client, [callada], "hoy_no")
    put_pref("reminders", {"atrasadas": {"on": True, "hora": "09:00", "dias": list(range(7))}})
    lista = atrasadas.listar("todo")
    hoy9 = datetime.combine(HOY, datetime.min.time())
    assert atrasadas.a_avisar(lista, hoy9.replace(hour=8, minute=59)) == []  # aún no es la hora
    ids = atrasadas.a_avisar(lista, hoy9.replace(hour=9))
    assert t in ids and callada not in ids
    r = client.post("/api/items/atrasadas/avisadas", json={"ids": [t]})
    assert r.status_code == 200
    assert t not in atrasadas.a_avisar(atrasadas.listar("todo"), hoy9.replace(hour=15))  # no se repite hoy
    assert t not in client.get("/api/items/atrasadas", params={"contexto": "todo", "avisar": 1}).json()["avisar"]
    # otro día sí vuelve a avisar (lo avisado ayer no cuenta)
    st = atrasadas.estado()
    st["avisadas"][str(t)] = AYER
    put_pref(atrasadas.ESTADO, st)
    assert t in atrasadas.a_avisar(atrasadas.listar("todo"), hoy9.replace(hour=15))
    # días y apagado
    otro = [d for d in range(7) if d != HOY.weekday()]
    put_pref("reminders", {"atrasadas": {"on": True, "hora": "09:00", "dias": otro}})
    assert atrasadas.a_avisar(lista, hoy9.replace(hour=10)) == []
    put_pref("reminders", {"atrasadas": {"on": False}})
    assert atrasadas.a_avisar(lista, hoy9.replace(hour=10)) == []
    put_pref("reminders", {})


def test_opciones_de_posponer():
    assert atrasadas.opciones(date(2026, 11, 13)) == {"manana": "2026-11-14", "sabado": "2026-11-14"}  # viernes
    assert atrasadas.opciones(date(2026, 11, 14))["sabado"] == "2026-11-21"  # sábado → el siguiente
    assert atrasadas.opciones(date(2026, 11, 15))["sabado"] == "2026-11-21"  # domingo


def test_lote_due_del_servicio_de_items(client):
    t = _nuevo(client, "AT lote due", due_date=AYER)
    r = client.post("/api/items/bulk", json={"ids": [t], "action": "due", "value": HOY.isoformat()})
    assert r.status_code == 200 and r.json()["count"] == 1
    r = client.post("/api/items/bulk", json={"ids": [t], "action": "due", "value": "mañana"})
    assert r.status_code == 422
