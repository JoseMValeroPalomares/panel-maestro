"""
Reglas deterministas de la auditoría de rendimiento (sin IA ni BD: funciones puras, fáciles de probar).

Convención del registro: el día D guarda la noche que lo precede (acostarse, pantallas, despertar, calidad)
y lo que pasó durante D. Las horas son «HH:MM»; para la noche, una hora antes de las 12:00 cuenta como de
madrugada (00:45 va después de 23:30).

    semaforos(dia, ajustes)              las cuatro tarjetas de «Hoy»: verde | ambar | rojo | gris (sin datos)
    alertas(dias, fecha, ajustes)        reglas que saltan en esa fecha, mirando hacia atrás lo que necesiten
    horas_sueno(dia)                     horas dormidas la noche anterior (None si falta un dato)
    correlacion(xs, ys)                  r de Pearson (None si no hay variación)
"""
from datetime import date, timedelta

# Umbrales configurables (rend_ajustes). Tipo, etiqueta y límites para validar y pintar los ajustes.
AJUSTES = {
    "objetivo_acostarse": ("hora", "Hora objetivo de acostarte", None),
    "limite_acostarse": ("hora", "Alerta circadiana si te acuestas después de", None),
    "noches_tarde": ("int", "… durante estas noches seguidas", (1, 7)),
    "objetivo_sueno_h": ("float", "Horas de sueño objetivo", (4, 12)),
    "pantallas_min_antes": ("int", "Minutos sin pantallas antes de dormir", (0, 240)),
    "cafe_min_tras_despertar": ("int", "Minutos mínimos entre despertar y el primer café", (0, 240)),
    "cafe_limite": ("hora", "Último café antes de", None),
    "limite_entreno": ("hora", "Aviso si el entreno termina después de", None),
    "bloques_sin_recall": ("int", "Bloques sin Active Recall previo tolerados al día", (0, 10)),
    "max_lectura_pasiva": ("int", "% máximo de minutos en lectura pasiva", (0, 100)),
    "max_enfoque_min": ("int", "Minutos de enfoque al día antes de avisar de sobrecarga", (30, 900)),
    "dias_sobrecarga": ("int", "… durante estos días seguidos", (1, 14)),
    "max_dopamina_semana": ("int", "Veces por semana de dopamina barata antes de las 19:00", (0, 7)),
    "niebla_alerta": ("int", "Niebla mental que cuenta para la fatiga (1-5)", (1, 5)),
    "dolor_alerta": ("int", "Dolor de cabeza que cuenta para la fatiga (0-3)", (1, 3)),
    "dias_fatiga": ("int", "… durante estos días seguidos (con sueño suficiente)", (1, 14)),
    "max_desviacion_min": ("int", "Desviación media máxima de la hora de dormir o despertar (min)", (15, 300)),
    "bloque_max_min": ("int", "Minutos de un bloque sin pausas antes de avisar", (15, 240)),
    "dias_correlacion": ("int", "Días de datos para ver correlaciones", (7, 120)),
}
DEFAULTS = {
    "objetivo_acostarse": "23:30", "limite_acostarse": "00:30", "noches_tarde": 2, "objetivo_sueno_h": 7.5,
    "pantallas_min_antes": 60, "cafe_min_tras_despertar": 90, "cafe_limite": "14:00", "limite_entreno": "21:30",
    "bloques_sin_recall": 2, "max_lectura_pasiva": 50, "max_enfoque_min": 240, "dias_sobrecarga": 3,
    "max_dopamina_semana": 2, "niebla_alerta": 4, "dolor_alerta": 2, "dias_fatiga": 3,
    "max_desviacion_min": 90, "bloque_max_min": 90, "dias_correlacion": 21,
}


# ── Horas ─────────────────────────────────────────────────────────────────────

def minutos(hhmm: str | None) -> int | None:
    if not hhmm or len(hhmm) < 5 or hhmm[2] != ":":
        return None
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except ValueError:
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def noche(hhmm: str | None) -> int | None:
    """Minutos de una hora nocturna en una escala que sigue tras medianoche (00:30 → 24:30)."""
    m = minutos(hhmm)
    return None if m is None else (m + 1440 if m < 720 else m)


def hhmm(m: int) -> str:
    m %= 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def horas_sueno(dia: dict) -> float | None:
    a, d = noche(dia.get("acostarse")), minutos(dia.get("despertar"))
    if a is None or d is None:
        return None
    dur = d + 1440 - a
    return round(dur / 60, 2) if 0 < dur <= 16 * 60 else None


def _h(horas: float) -> str:
    return _dur(round(horas * 60))


def _dur(m: int) -> str:
    h, mm = divmod(abs(int(m)), 60)
    return f"{h} h {mm:02d} min" if h and mm else (f"{h} h" if h else f"{mm} min")


# ── Bloques ───────────────────────────────────────────────────────────────────

def resumen_bloques(bloques: list[dict]) -> dict:
    total = sum(b.get("minutos") or 0 for b in bloques)
    n = len(bloques)
    pasiva = sum(b.get("minutos") or 0 for b in bloques if b.get("codificacion") == "lectura")
    return {
        "n": n, "minutos": total,
        "sin_recall": sum(1 for b in bloques if not b.get("recall")),
        "pct_recall": round(100 * sum(1 for b in bloques if b.get("recall")) / n) if n else None,
        "pct_activa": round(100 * (total - pasiva) / total) if total else None,
        "pct_pasiva": round(100 * pasiva / total) if total else None,
        "degradados": sum(1 for b in bloques if b.get("estado") == "degradado"),
        "sin_pausas": sum(1 for b in bloques if b.get("pausas") == "no"),
        "asignaturas": sorted({b.get("asignatura") for b in bloques if b.get("asignatura")}),
    }


# ── Semáforos ─────────────────────────────────────────────────────────────────

def _luz(puntos: int, motivos: list[str], ok: str) -> dict:
    nivel = "verde" if puntos == 0 else ("ambar" if puntos <= 2 else "rojo")
    return {"nivel": nivel, "frase": ok if nivel == "verde" else motivos[0], "motivos": motivos}


def _ordenar(pesados: list[tuple[int, str]]) -> tuple[int, list[str]]:
    pesados.sort(key=lambda x: -x[0])
    return sum(p for p, _ in pesados), [m for _, m in pesados]


def semaforo_metabolico(dia: dict, aj: dict) -> dict:
    if not dia:
        return {"nivel": "gris", "frase": "Sin registro de hoy.", "motivos": []}
    p = []
    if (dia.get("niebla") or 0) >= aj["niebla_alerta"]:
        p.append((3, f"Niebla mental alta ({dia['niebla']}/5)."))
    if dia.get("comida_tarde") == "alta":
        p.append((1, "Comida del valle alta en azúcares simples."))
    if dia.get("siesta") == "larga":
        p.append((1, "Siesta de 90 min: puede robar presión de sueño."))
    cafe, desp = minutos(dia.get("primer_cafe")), minutos(dia.get("despertar"))
    if cafe is not None and desp is not None and 0 <= cafe - desp < aj["cafe_min_tras_despertar"]:
        p.append((1, f"Café a los {cafe - desp} min de despertar (objetivo ≥ {aj['cafe_min_tras_despertar']})."))
    if cafe is not None and cafe > (minutos(aj["cafe_limite"]) or 1440):
        p.append((1, f"Café después de las {aj['cafe_limite']}."))
    if dia.get("energia") is not None and dia["energia"] <= 2:
        p.append((1, f"Energía baja ({dia['energia']}/5)."))
    if (dia.get("dolor_cabeza") or 0) >= 2:
        p.append((1, f"Dolor de cabeza {dia['dolor_cabeza']}/3."))
    pts, mot = _ordenar(p)
    return _luz(pts, mot, "Energía estable: café a su hora y valle sin picos de azúcar.")


def semaforo_codificacion(bloques: list[dict], aj: dict) -> dict:
    r = resumen_bloques(bloques)
    if not r["n"]:
        return {"nivel": "gris", "frase": "Sin bloques de estudio registrados.", "motivos": []}
    p = []
    if r["sin_recall"] > aj["bloques_sin_recall"]:
        p.append((3, f"{r['sin_recall']} bloques sin Active Recall previo: riesgo de ilusión de competencia."))
    elif r["sin_recall"]:
        p.append((1, f"{r['sin_recall']} de {r['n']} bloques sin Active Recall previo."))
    if r["pct_pasiva"] is not None and r["pct_pasiva"] > aj["max_lectura_pasiva"]:
        p.append((3, f"Predomina la lectura pasiva ({r['pct_pasiva']} % de los minutos)."))
    elif r["pct_pasiva"]:
        p.append((1, f"{r['pct_pasiva']} % de los minutos en lectura pasiva."))
    if r["degradados"]:
        p.append((1, f"{r['degradados']} bloque{'s' if r['degradados'] > 1 else ''} en estado degradado."))
    pts, mot = _ordenar(p)
    return _luz(pts, mot, f"Codificación activa: {r['pct_recall']} % con recall previo, {r['pct_activa']} % activa.")


def semaforo_sueno(dia: dict, aj: dict) -> dict:
    if not dia:
        return {"nivel": "gris", "frase": "Sin registro de hoy.", "motivos": []}
    p = []
    a = noche(dia.get("acostarse"))
    obj, lim = noche(aj["objetivo_acostarse"]), noche(aj["limite_acostarse"])
    if a is not None and lim is not None and a > lim:
        p.append((2, f"Te acostaste a las {dia['acostarse']}, más tarde de las {aj['limite_acostarse']}."))
    elif a is not None and obj is not None and a > obj:
        p.append((1, f"Acostarte a las {dia['acostarse']}: {_dur(a - obj)} tras el objetivo."))
    h = horas_sueno(dia)
    if h is not None and h < aj["objetivo_sueno_h"] - 1:
        p.append((2, f"Solo {_h(h)} de sueño."))
    elif h is not None and h < aj["objetivo_sueno_h"]:
        p.append((1, f"{_h(h)} de sueño, por debajo de {_h(aj['objetivo_sueno_h'])}."))
    pant = noche(dia.get("pantallas_off"))
    if pant is not None and a is not None and a - pant < aj["pantallas_min_antes"]:
        p.append((1, f"Pantallas hasta {max(0, a - pant)} min antes de dormir."))
    fin = minutos(dia.get("entreno_fin"))
    if dia.get("entreno") and fin is not None and fin > (minutos(aj["limite_entreno"]) or 1440):
        p.append((1, f"Entreno hasta las {dia['entreno_fin']}: la temperatura central tarda en bajar."))
    if dia.get("calidad_sueno") is not None and dia["calidad_sueno"] <= 2:
        p.append((1, f"Calidad de sueño baja ({dia['calidad_sueno']}/5)."))
    pts, mot = _ordenar(p)
    ok = f"Dormiste {_h(h)} y te acostaste a tu hora." if h is not None else "Horario de sueño dentro del objetivo."
    return _luz(pts, mot, ok)


def semaforo_rotacion(bloques: list[dict], aj: dict) -> dict:
    r = resumen_bloques(bloques)
    if not r["n"]:
        return {"nivel": "gris", "frase": "Sin bloques de estudio registrados.", "motivos": []}
    p = []
    if r["degradados"] * 2 >= r["n"]:
        p.append((2, f"{r['degradados']} de {r['n']} bloques en estado degradado."))
    largos = [b for b in bloques if (b.get("minutos") or 0) > aj["bloque_max_min"] and b.get("pausas") != "sistematico"]
    if largos:
        p.append((1, f"{len(largos)} bloque{'s' if len(largos) > 1 else ''} de más de {aj['bloque_max_min']} min sin pausas sistemáticas."))
    if r["minutos"] > aj["max_enfoque_min"]:
        p.append((1, f"{_dur(r['minutos'])} de enfoque, por encima de {_dur(aj['max_enfoque_min'])}."))
    if r["sin_pausas"] * 2 > r["n"]:
        p.append((1, "La mayoría de bloques sin pausas cortas con ojos cerrados."))
    pts, mot = _ordenar(p)
    return _luz(pts, mot, f"{_dur(r['minutos'])} en {r['n']} bloque{'s' if r['n'] > 1 else ''}, sin señales de fatiga.")


def semaforos(dia: dict | None, aj: dict) -> dict:
    bloques = (dia or {}).get("bloques") or []
    return {
        "metabolico": semaforo_metabolico(dia or {}, aj),
        "codificacion": semaforo_codificacion(bloques, aj),
        "sueno": semaforo_sueno(dia or {}, aj),
        "rotacion": semaforo_rotacion(bloques, aj),
    }


# ── Reglas automáticas ────────────────────────────────────────────────────────

def _atras(fecha: str, n: int) -> list[str]:
    d = date.fromisoformat(fecha)
    return [(d - timedelta(days=i)).isoformat() for i in range(n)]


def alertas(dias: dict[str, dict], fecha: str, aj: dict) -> list[dict]:
    """`dias`: fecha → registro (con «bloques»). Devuelve las alertas que saltan en `fecha`."""
    out = []
    hoy = dias.get(fecha) or {}

    # Circadiana: acostarse después del límite N noches seguidas
    lim, n = noche(aj["limite_acostarse"]), int(aj["noches_tarde"])
    noches = [dias.get(f) or {} for f in _atras(fecha, n)]
    if lim is not None and all((noche(d.get("acostarse")) or 0) > lim for d in noches):
        horas = ", ".join(d["acostarse"] for d in reversed(noches))
        out.append({"id": "circadiana", "nivel": "rojo", "titulo": "Alerta circadiana",
                    "texto": f"{n} noches seguidas acostándote después de las {aj['limite_acostarse']} ({horas}). "
                             "Adelanta la luz de la mañana y corta pantallas antes."})

    # Termorregulación: entreno que termina tarde
    fin = minutos(hoy.get("entreno_fin"))
    if hoy.get("entreno") and fin is not None and fin > (minutos(aj["limite_entreno"]) or 1440):
        out.append({"id": "termorregulacion", "nivel": "ambar", "titulo": "Termorregulación y sueño",
                    "texto": f"El entreno terminó a las {hoy['entreno_fin']}, después de las {aj['limite_entreno']}: "
                             "la temperatura corporal alta retrasa el sueño. Ducha templada y cena ligera."})

    # Ilusión de competencia: bloques sin recall o predominio de lectura pasiva
    r = resumen_bloques(hoy.get("bloques") or [])
    motivos = []
    if r["sin_recall"] > aj["bloques_sin_recall"]:
        motivos.append(f"{r['sin_recall']} bloques sin Active Recall previo")
    if r["pct_pasiva"] is not None and r["pct_pasiva"] > aj["max_lectura_pasiva"]:
        motivos.append(f"un {r['pct_pasiva']} % del tiempo en lectura pasiva")
    if motivos:
        out.append({"id": "ilusion", "nivel": "rojo", "titulo": "Riesgo de ilusión de competencia",
                    "texto": f"Hoy: {' y '.join(motivos)}. Empieza cada bloque recuperando de memoria y pasa la lectura a esquema, código o problemas."})

    # Sobrecarga: más de X min de enfoque durante N días seguidos
    n = int(aj["dias_sobrecarga"])
    tot = [resumen_bloques((dias.get(f) or {}).get("bloques") or [])["minutos"] for f in _atras(fecha, n)]
    if all(t > aj["max_enfoque_min"] for t in tot):
        out.append({"id": "sobrecarga", "nivel": "rojo", "titulo": "Riesgo de sobrecarga",
                    "texto": f"{n} días seguidos con más de {_dur(aj['max_enfoque_min'])} de enfoque efectivo "
                             f"({', '.join(_dur(t) for t in reversed(tot))}). Plantéate mañana un día de recuperación: "
                             "repaso ligero, luz y movimiento."})

    # Blindaje de dopamina: veces en los últimos 7 días
    veces = [f for f in _atras(fecha, 7) if (dias.get(f) or {}).get("dopamina")]
    if len(veces) > aj["max_dopamina_semana"]:
        out.append({"id": "dopamina", "nivel": "ambar", "titulo": "Fallo del blindaje de dopamina",
                    "texto": f"{len(veces)} días con ocio digital antes de las 19:00 en la última semana "
                             f"(máximo {aj['max_dopamina_semana']}). Déjalo como recompensa después del último bloque."})

    # Fatiga persistente: niebla o cefalea N días seguidos aun durmiendo lo suficiente. Sin diagnósticos.
    n = int(aj["dias_fatiga"])
    racha = [dias.get(f) or {} for f in _atras(fecha, n)]

    def fatiga(d):
        h = horas_sueno(d)
        sintoma = (d.get("niebla") or 0) >= aj["niebla_alerta"] or (d.get("dolor_cabeza") or 0) >= aj["dolor_alerta"]
        return sintoma and h is not None and h >= aj["objetivo_sueno_h"]

    if all(fatiga(d) for d in racha):
        out.append({"id": "fatiga", "nivel": "rojo", "titulo": "Fatiga persistente",
                    "texto": f"{n} días seguidos con niebla mental ≥ {aj['niebla_alerta']} o dolor de cabeza ≥ {aj['dolor_alerta']} "
                             "pese a dormir lo suficiente. Prioriza el descanso y baja la carga; si se mantiene o empeora, "
                             "pide valoración médica. Esto no es un diagnóstico."})

    # Desajuste circadiano: desviación media de la hora de acostarse o despertar en la última semana
    semana = [dias.get(f) or {} for f in _atras(fecha, 7)]
    for campo, nombre, conv in (("acostarse", "acostarte", noche), ("despertar", "despertarte", minutos)):
        xs = [conv(d.get(campo)) for d in semana if conv(d.get(campo)) is not None]
        if len(xs) < 4:
            continue
        media = sum(xs) / len(xs)
        desv = sum(abs(x - media) for x in xs) / len(xs)
        if desv > aj["max_desviacion_min"]:
            out.append({"id": "desajuste", "nivel": "ambar", "titulo": "Desajuste circadiano",
                        "texto": f"Tu hora de {nombre} varía de media {round(desv)} min esta semana (máximo {aj['max_desviacion_min']}). "
                                 "Fija una hora de despertar, también el fin de semana: es la que ancla el reloj."})
            break
    return out


# ── Correlaciones ─────────────────────────────────────────────────────────────

def correlacion(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(sxy / (sx * sy), 2) if sx and sy else None
