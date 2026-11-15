"""P-3 · Alta rápida de rutinas: una línea con lo mínimo y los pasos, uno por línea (POST /api/routines/rapida)."""

import pytest

from app.capture import parse_routine
from app.rutina_rapida import parse_paso


@pytest.mark.parametrize(
    "text,days,due,dur,title",
    [
        ("gimnasio L X V 18:00 1h", [0, 2, 4], "18:00", 60, "Gimnasio"),
        ("gimnasio lxv 18h", [0, 2, 4], "18:00", None, "Gimnasio"),
        ("leer L-V 22:00 30m", [0, 1, 2, 3, 4], "22:00", 30, "Leer"),
        ("yoga l a v a las 7", [0, 1, 2, 3, 4], "19:00", None, "Yoga"),
        ("correr S D 9h 1h30", [5, 6], "09:00", 90, "Correr"),
        ("llamar a casa D 20h", [6], "20:00", None, "Llamar a casa"),
    ],
)
def test_dias_con_letras_y_duracion(text, days, due, dur, title):
    r = parse_routine(text)
    assert r["repeat"] == {"freq": "weekly", "days": days}
    assert (r["due_time"], r["duration_min"], r["title"]) == (due, dur, title)


@pytest.mark.parametrize("text", ["leer las noticias", "comprar dvd", "pasear a Max"])
def test_palabras_normales_no_son_dias(text):
    r = parse_routine(text)
    assert r["repeat"] == {"freq": "daily"} and r["title"].lower() == text.lower()


def test_todos_los_dias_con_letras_es_diaria():
    assert parse_routine("leer LMXJVSD 22:00")["repeat"] == {"freq": "daily"}


@pytest.mark.parametrize(
    "line,out",
    [
        ("ducha 10m", ("Ducha", None, 10)),
        ("- [ ] pesas 40 min", ("Pesas", None, 40)),
        ("18:10 pesas 40m", ("Pesas", "18:10", 40)),
        ("pesas 18:10-18:50", ("Pesas", "18:10", 40)),
        ("2. estudiar 1h", ("Estudiar", None, 60)),
        ("   ", None),
    ],
)
def test_una_linea_de_paso(line, out):
    p = parse_paso(line)
    assert (p and (p["title"], p["due_time"], p["duration_min"])) == out


def _items(client):
    return {i["id"]: i for i in client.get("/api/items").json()["items"]}


def test_vista_previa_no_guarda_y_encadena_las_horas(client):
    antes = len(_items(client))
    r = client.post(
        "/api/routines/rapida",
        json={"text": "gimnasio lxv 18h", "pasos": "calentar 10m\npesas 40m\nestiramientos 10m", "dry_run": True},
    ).json()
    assert len(_items(client)) == antes
    p = r["preview"]
    assert p["title"] == "Gimnasio" and p["repeat"] == {"freq": "weekly", "days": [0, 2, 4]}
    assert [(s["title"], s["at"], s["end"]) for s in p["pasos"]] == [
        ("Calentar", "18:00", "18:10"),
        ("Pesas", "18:10", "18:50"),
        ("Estiramientos", "18:50", "19:00"),
    ]
    assert p["when"] == "Los lunes, miércoles, viernes · 18:00–19:00 · 3 pasos · 1 h"


def test_crea_la_rutina_con_sus_pasos(client):
    r = client.post(
        "/api/routines/rapida",
        json={"text": "mañanas L-V 7:00", "pasos": "ducha 10m\ndesayuno\n07:45 salir 5m", "dur_defecto": 15},
    ).json()
    items = _items(client)
    rid = r["id"]
    assert items[rid]["type"] == "rutina" and items[rid]["repeat"] == {"freq": "weekly", "days": [0, 1, 2, 3, 4]}
    kids = sorted((i for i in items.values() if i["parent_id"] == rid), key=lambda i: i["due_time"])
    assert [(k["text"], k["due_time"], k["duration_min"]) for k in kids] == [
        ("Ducha", "07:00", 10),
        ("Desayuno", "07:10", 15),  # sin duración: la de por defecto
        ("Salir", "07:45", 5),  # su hora escrita manda
    ]
    assert r["sin_hora"] == []


def test_mas_opciones_mandan_sobre_lo_escrito(client):
    r = client.post(
        "/api/routines/rapida",
        json={"text": "leer L 22h", "repeat": {"freq": "weekly", "days": [5]}, "due_time": "", "dry_run": True},
    ).json()["preview"]
    assert r["repeat"] == {"freq": "weekly", "days": [5]} and r["due_time"] is None


def test_un_paso_que_choca_se_queda_sin_hora(client):
    client.post("/api/routines/rapida", json={"text": "uno S 10:00", "pasos": "bloque 30m"})
    r = client.post("/api/routines/rapida", json={"text": "dos S 10:15", "pasos": "otro 10m"}).json()
    assert r["sin_hora"] == ["Otro"]


def test_pegar_pasos_en_una_rutina(client):
    rid = client.post("/api/routines/rapida", json={"text": "tarde J 16:00"}).json()["id"]
    r = client.post(f"/api/routines/{rid}/pasos", json={"pasos": "- merendar 15m\n- 17:00 piano 30m\n\n"}).json()
    items = _items(client)
    assert [(items[i]["text"], items[i]["due_time"], items[i]["duration_min"]) for i in r["ids"]] == [
        ("Merendar", None, 15),  # sin hora escrita: flexible, como al añadirlo uno a uno
        ("Piano", "17:00", 30),
    ]
    tarea = client.post("/api/items", json={"text": "no soy rutina"}).json()["id"]
    assert client.post(f"/api/routines/{tarea}/pasos", json={"pasos": "x"}).status_code == 422


def test_sin_nombre_ni_pasos_vacios(client):
    assert client.post("/api/routines/rapida", json={"text": ""}).status_code == 422
    rid = client.post("/api/routines/rapida", json={"text": "algo"}).json()["id"]
    assert client.post(f"/api/routines/{rid}/pasos", json={"pasos": "  \n "}).status_code == 422


def test_captura_r_guarda_la_duracion(client):
    r = client.post("/api/capture", json={"text": "r: meditar L X V 7:00 15m"}).json()
    it = _items(client)[r["id"]]
    assert (it["due_time"], it["duration_min"]) == ("07:00", 15)
    assert r["message"].endswith("a las 07:00 · 15 min")
