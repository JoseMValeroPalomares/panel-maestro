"""Captura rápida con prefijos (escritorio, app y extensión): POST /api/capture."""
import pytest

from app.capture import parse_routine, split_prefix


@pytest.mark.parametrize("text,kind,body", [
    ("comprar pilas", "inbox", "comprar pilas"), ("t: llamar al banco", "tarea", "llamar al banco"),
    ("I:una idea", "idea", "una idea"), ("r: leer", "rutina", "leer"), ("e: dentista mañana 17:00", "evento", "dentista mañana 17:00"),
])
def test_prefijos(text, kind, body):
    assert split_prefix(text) == (kind, body)


def test_rutinas_en_castellano():
    r = parse_routine("gimnasio lunes y jueves a las 19")
    assert r == {"title": "Gimnasio", "repeat": {"freq": "weekly", "days": [0, 3]}, "due_time": "19:00"}
    assert parse_routine("leer cada día")["repeat"] == {"freq": "daily"}
    assert parse_routine("estirar de lunes a viernes 7:30")["repeat"]["days"] == [0, 1, 2, 3, 4]
    assert parse_routine("regar las plantas cada 3 días")["repeat"] == {"freq": "interval", "every": 3}


def test_capturas_crean_cada_tipo(client):
    def cap(text, **kw):
        r = client.post("/api/capture", json={"text": text, **kw})
        assert r.status_code == 200, r.text
        return r.json()
    items = lambda: {i["id"]: i for i in client.get("/api/items").json()["items"]}  # noqa: E731
    a = cap("cosa sin prefijo captura")
    assert items()[a["id"]]["origin"] == "inbox"
    t, i = cap("t: tarea captura")["id"], cap("i: idea captura")["id"]
    assert items()[t]["type"] == "tarea" and items()[i]["type"] == "idea"
    r = cap("r: meditar cada día a las 7:00")
    assert items()[r["id"]]["type"] == "rutina" and items()[r["id"]]["due_time"] == "07:00"
    # evento: vista previa sin guardar y después guardado
    prev = cap("e: dentista mañana 17:00", dry_run=True)
    assert prev["kind"] == "evento" and "id" not in prev and prev["preview"]["title"] == "Dentista" and prev["preview"]["start"].endswith("T17:00")
    ev = cap("e: dentista mañana 17:00")
    assert client.get(f"/api/calendar/events/{ev['id']}").json()["title"] == "Dentista"
    # ambiguo: al Inbox marcado «Revisar fecha», nunca un evento inventado
    amb = cap("e: dentista 17:00")
    assert amb["kind"] == "inbox" and amb["revisar"] and "día" in amb["reason"]
    it = items()[amb["id"]]
    assert it["category"] == "Revisar fecha" and "Fecha sin interpretar" in it["details"]


def test_tarea_con_fecha_si_la_lleva_clara(client):
    from datetime import date, timedelta
    items = lambda: {i["id"]: i for i in client.get("/api/items").json()["items"]}  # noqa: E731
    r = client.post("/api/capture", json={"text": "t: pagar la luz mañana a las 10"}).json()
    it = items()[r["id"]]
    assert (it["text"], it["due_date"], it["due_time"]) == ("Pagar la luz", (date.today() + timedelta(days=1)).isoformat(), "10:00")
    assert "·" in r["message"]
    # sin fecha: el texto tal cual; con dos fechas: tampoco se inventa
    r = client.post("/api/capture", json={"text": "t: repasar tema 5"}).json()
    assert items()[r["id"]]["text"] == "repasar tema 5" and items()[r["id"]]["due_date"] is None
    r = client.post("/api/capture", json={"text": "i: algo el lunes o el martes", "dry_run": True}).json()
    assert r["preview"]["when"] is None and "id" not in r


def test_gasto_con_prefijo_g(client):
    from app.capture import parse_gasto
    assert parse_gasto("4,50 café") == {"importe": 4.5, "concepto": "Café", "categoria": "Comida"}
    assert parse_gasto("abono de autobús 20 €")["categoria"] == "Transporte"
    assert parse_gasto("algo raro sin precio") is None
    client.post("/api/finance/accounts", json={"nombre": "Cuenta captura", "saldo_inicial": 0})
    prev = client.post("/api/capture", json={"text": "g: 12,40 menú del día", "dry_run": True}).json()
    assert prev["kind"] == "gasto" and prev["preview"]["importe"] == 12.4 and "id" not in prev
    r = client.post("/api/capture", json={"text": "g: 12,40 menú del día"}).json()
    from datetime import date
    movs = client.get("/api/finance/movements", params={"month": date.today().strftime("%Y-%m")}).json()["movements"]
    assert any(m["id"] == r["id"] and m["importe"] == 12.4 and m["categoria"] == "Comida" for m in movs)
    sin = client.post("/api/capture", json={"text": "g: algo sin precio"}).json()
    assert sin["kind"] == "inbox" and sin["revisar"]
