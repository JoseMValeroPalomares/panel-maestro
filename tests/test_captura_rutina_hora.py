"""«r: gimnasio a las 5»: la hora sin minutos de una rutina (antes daba IndexError y un 500)."""

import pytest

from app.capture import parse_routine


@pytest.mark.parametrize(
    "text,due_time",
    [
        ("gimnasio a las 5", "17:00"),  # de 1 a 7 sin más, por la tarde, como en los eventos
        ("gimnasio a las 7", "19:00"),
        ("gimnasio a las 9", "09:00"),
        ("gimnasio a las 5:30", "05:30"),  # con minutos, tal cual
        ("gimnasio 5h", "05:00"),
        ("gimnasio lunes y jueves a las 19", "19:00"),
    ],
)
def test_hora_de_la_rutina(text, due_time):
    r = parse_routine(text)
    assert r["due_time"] == due_time and r["title"] == "Gimnasio"


def test_captura_de_rutina_a_las_5(client):
    r = client.post("/api/capture", json={"text": "r: gimnasio a las 5", "dry_run": True})
    assert r.status_code == 200, r.text
    assert r.json()["preview"]["when"].endswith("a las 17:00")
