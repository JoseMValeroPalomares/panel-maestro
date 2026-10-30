"""Calendario: la altura de cada hora crece con el ancho de la columna (las franjas no quedan aplastadas)."""
from datetime import date, timedelta

import pytest


def medir(page):
    return page.evaluate("""() => { const s = document.querySelector('.cal-scroll'), g = document.querySelector('.cal-grid');
      const cols = [...document.querySelectorAll('.cal-col')], heads = [...document.querySelectorAll('.cal-dayhead')];
      return { col: cols[0].getBoundingClientRect().width, hour: parseFloat(g.style.getPropertyValue('--hour')),
               scrolls: s.scrollHeight > s.clientHeight, top: s.scrollTop,
               skew: Math.abs(cols.at(-1).getBoundingClientRect().right - heads.at(-1).getBoundingClientRect().right) } }""")


@pytest.mark.parametrize("vista,ratio", [("week", 2.2), ("3d", 4.2)])
def test_franjas_proporcionadas_y_cabecera_cuadrada(page, server, vista, ratio):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(f"{server}/calendario?vista={vista}")
    page.wait_for_selector(".cal-col")
    page.wait_for_load_state("networkidle")
    m = medir(page)
    assert m["hour"] >= 72 and m["col"] / m["hour"] <= ratio
    assert m["skew"] < 1  # la barra de desplazamiento no descuadra la cabecera


def test_vista_dia_de_borde_a_borde_y_sin_rotulo(page, server):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(f"{server}/calendario?vista=day")
    page.wait_for_selector(".cal-col")
    page.wait_for_load_state("networkidle")
    tarjeta = page.locator("#calendar .cal-grid").evaluate("g => g.parentElement.getBoundingClientRect().width")
    assert abs(page.locator("#calendar .cal-grid").bounding_box()["width"] - tarjeta) < 2
    assert medir(page)["skew"] < 1
    assert page.locator(".cal-allday .cal-gutter").inner_text() == ""
    assert page.get_by_role("group", name="Todo el día").count() == 1  # el lector de pantalla sí lo anuncia


def test_altura_elegida_se_recuerda(page, server):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server}/calendario?vista=week")
    page.wait_for_selector(".cal-col")
    page.wait_for_load_state("networkidle")
    normal = medir(page)
    assert normal["scrolls"]
    page.click("#calHoursBtn")
    page.click("dialog[open] .choice-chip:has(input[value=fit])")
    page.click("dialog[open] [type=submit]")
    page.wait_for_timeout(400)
    fit = medir(page)
    assert fit["hour"] < normal["hour"]  # «Que quepa todo»: cabe el horario entero
    page.reload()
    page.wait_for_selector(".cal-col")
    page.wait_for_load_state("networkidle")
    assert abs(medir(page)["hour"] - fit["hour"]) <= 1


def test_abre_en_la_hora_actual_o_en_lo_primero(page, server, api):
    # otra semana con un evento por la tarde: la rejilla empieza cerca de él, no arriba del todo
    dia = (date.today() + timedelta(days=14)).isoformat()
    api.post("/api/calendar/events", json={"title": "Tarde E2E", "start": f"{dia}T18:00", "end": f"{dia}T19:00"})
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{server}/calendario?vista=day&dia={dia}")
    page.locator(".cal-ev", has_text="Tarde E2E").wait_for()
    page.wait_for_load_state("networkidle")
    assert medir(page)["top"] > 0
