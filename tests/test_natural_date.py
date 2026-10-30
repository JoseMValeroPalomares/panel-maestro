"""Fechas en lenguaje natural (español, Europe/Madrid) para la captura «e:»."""
from datetime import datetime

import pytest

from core.natural_date import TZ, describe, parse_event

# sábado 24 de octubre de 2026, 12:00
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=TZ)


def p(text):
    return parse_event(text, NOW)


def at(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


@pytest.mark.parametrize("text,title,start,end,all_day", [
    ("dentista mañana 17:00", "Dentista", at(2026, 10, 25, 17), at(2026, 10, 25, 18), False),
    ("examen de SO 3 nov 9:00 2h", "Examen de SO", at(2026, 11, 3, 9), at(2026, 11, 3, 11), False),
    ("reunión viernes 10:30", "Reunión", at(2026, 10, 30, 10, 30), at(2026, 10, 30, 11, 30), False),
    ("reunión el viernes a las 10", "Reunión", at(2026, 10, 30, 10), at(2026, 10, 30, 11), False),
    ("llamar a mamá hoy a las 18", "Llamar a mamá", at(2026, 10, 24, 18), at(2026, 10, 24, 19), False),
    ("revisar horno dentro de 2 horas", "Revisar horno", at(2026, 10, 24, 14), at(2026, 10, 24, 15), False),
    ("cumpleaños de Ana 3 de noviembre", "Cumpleaños de Ana", at(2026, 11, 3), at(2026, 11, 4), True),
    ("entrega TFG 15 de enero de 2027 12:00", "Entrega TFG", at(2027, 1, 15, 12), at(2027, 1, 15, 13), False),
    ("congreso 5 ene", "Congreso", at(2027, 1, 5), at(2027, 1, 6), True),  # enero ya pasó: el que viene
    ("clase pasado mañana de 10 a 12", "Clase", at(2026, 10, 26, 10), at(2026, 10, 26, 12), False),
    ("tutoría el próximo lunes a las 5 de la tarde", "Tutoría", at(2026, 10, 26, 17), at(2026, 10, 26, 18), False),
    ("desayuno mañana a las 9 de la mañana", "Desayuno", at(2026, 10, 25, 9), at(2026, 10, 25, 10), False),
    ("comida familiar el domingo a mediodía", "Comida familiar", at(2026, 10, 25, 12), at(2026, 10, 25, 13), False),
    ("médico 12/11 9:30 30 min", "Médico", at(2026, 11, 12, 9, 30), at(2026, 11, 12, 10), False),
    ("viaje 2026-12-20", "Viaje", at(2026, 12, 20), at(2026, 12, 21), True),
    ("gimnasio en 3 días 17h", "Gimnasio", at(2026, 10, 27, 17), at(2026, 10, 27, 18), False),
    ("pagar alquiler el 1", "Pagar alquiler", at(2026, 11, 1), at(2026, 11, 2), True),
    ("examen 3/11/2026 a las 9 y media durante 2 horas", "Examen", at(2026, 11, 3, 9, 30), at(2026, 11, 3, 11, 30), False),
    ("este sábado cine a las 22:00", "Cine", at(2026, 10, 24, 22), at(2026, 10, 24, 23), False),
])
def test_frases_tipicas(text, title, start, end, all_day):
    r = p(text)
    assert r["ok"], r
    assert (r["title"], r["start"], r["end"], r["all_day"]) == (title, start, end, all_day)


@pytest.mark.parametrize("text", [
    "dentista 17:00",                 # no dice qué día
    "llamar al fontanero",            # ni día ni hora
    "examen 31 de febrero",           # la fecha no existe
    "reunión mañana a las 25:00",     # hora imposible
    "cita el lunes o el martes",      # dos fechas
    "mañana",                         # sin título
])
def test_ambiguo_no_inventa(text):
    r = p(text)
    assert not r["ok"] and r["reason"] and r["start"] is None


def test_describe():
    assert describe(p("dentista mañana 17:00")) == "domingo 25 oct · 17:00–18:00"
    assert describe(p("cumpleaños 3 nov")) == "martes 3 nov · todo el día"
