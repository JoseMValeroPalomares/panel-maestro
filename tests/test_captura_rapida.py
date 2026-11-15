"""P-3 · Captura rápida de tareas y eventos: marcas en el texto, «Más opciones» que mandan y lugar del evento."""

from datetime import date

from core.natural_date import parse_event


def _cap(client, text, **kw):
    r = client.post("/api/capture", json={"text": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def _item(client, iid):
    return next(i for i in client.get("/api/items").json()["items"] if i["id"] == iid)


def test_marcas_de_prioridad_y_categoria(client):
    r = _cap(client, "t: Llamar al dentista viernes 10:00 30m !alta +Salud")
    it = _item(client, r["id"])
    assert (it["text"], it["priority"], it["category"], it["due_time"], it["duration_min"]) == (
        "Llamar al dentista",
        "alta",
        "Salud",
        "10:00",
        30,
    )
    assert _item(client, _cap(client, "t: pilas !! +Casa")["id"])["priority"] == "alta"
    assert _item(client, _cap(client, "t: algo !baja")["id"])["priority"] == "baja"


def test_solo_se_lee_la_primera_linea(client):
    r = _cap(client, "t: Leer\nlo del 3 de mayo", dry_run=True)
    assert r["preview"]["when"] is None and r["preview"]["title"] == "Leer\nlo del 3 de mayo"


def test_mas_opciones_mandan_y_una_hora_sin_dia_es_hoy(client):
    p = _cap(client, "t: tarea viernes 10:00", dry_run=True, opciones={"due_time": "11:00", "priority": "media"})[
        "preview"
    ]
    assert p["due_time"] == "11:00" and p["priority"] == "media"
    p = _cap(client, "t: otra", dry_run=True, opciones={"due_time": "09:30", "duration_min": 45})["preview"]
    assert (p["due_date"], p["due_time"], p["duration_min"]) == (date.today().isoformat(), "09:30", 45)
    p = _cap(client, "t: leer el capítulo del 3 de mayo", dry_run=True, opciones={"literal": True})["preview"]
    assert p["title"] == "leer el capítulo del 3 de mayo" and "due_date" not in p
    p = _cap(client, "t: quitar viernes", dry_run=True, opciones={"due_date": ""})["preview"]
    assert "due_date" not in p and p["when"] is None


def test_evento_con_lugar_y_aviso(client):
    r = _cap(client, "e: Dentista 20/11 10:00 30m en Clínica Sur", opciones={"reminder_min": 60})
    assert r["preview"]["location"] == "Clínica Sur" and r["preview"]["title"] == "Dentista"
    assert r["preview"]["end"].endswith("10:30")
    # «en casa» (minúscula) es parte del título, no un lugar
    assert _cap(client, "e: cena en casa 20/11 21:00", dry_run=True)["preview"]["location"] is None


def test_duracion_en_m_y_dias_abreviados():
    assert parse_event("dentista mañana 10:00 30m")["duration_min"] == 30
    p = parse_event("x vie 11:00")
    assert p["ok"] and p["start"].weekday() == 4
    assert not parse_event("vienen 3 amigos")["ok"]
