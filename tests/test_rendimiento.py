"""Auditoría de rendimiento: reglas deterministas, semáforos, registro diario, exámenes, correlaciones y ajustes."""
from datetime import date, timedelta

from app import rendimiento_rules as R

AJ = dict(R.DEFAULTS)


def dias_atras(n: int, desde: str = "2030-05-20") -> list[str]:
    d = date.fromisoformat(desde)
    return [(d - timedelta(days=i)).isoformat() for i in range(n)]


def bloque(**kw):
    return {"asignatura": "IG", "minutos": 60, "recall": 1, "codificacion": "problemas", "pausas": "sistematico",
            "estado": "funcional", **kw}


# ── Reglas puras ──────────────────────────────────────────────────────────────

def test_horas_nocturnas_y_sueno():
    assert R.noche("00:30") > R.noche("23:30") and R.noche("23:59") < R.noche("00:01")
    assert R.horas_sueno({"acostarse": "23:30", "despertar": "07:00"}) == 7.5
    assert R.horas_sueno({"acostarse": "01:00", "despertar": "08:30"}) == 7.5
    assert R.horas_sueno({"acostarse": "23:30"}) is None
    assert R.minutos("25:00") is None and R.minutos("ab:cd") is None


def test_alerta_circadiana_solo_con_dos_noches_seguidas():
    hoy, ayer = dias_atras(2)
    tarde = {hoy: {"acostarse": "00:45"}, ayer: {"acostarse": "01:10"}}
    assert "circadiana" in {a["id"] for a in R.alertas(tarde, hoy, AJ)}
    una = {hoy: {"acostarse": "00:45"}, ayer: {"acostarse": "23:40"}}
    assert "circadiana" not in {a["id"] for a in R.alertas(una, hoy, AJ)}
    # a la hora límite exacta no salta (es «después de»)
    justo = {hoy: {"acostarse": "00:30"}, ayer: {"acostarse": "00:30"}}
    assert "circadiana" not in {a["id"] for a in R.alertas(justo, hoy, AJ)}


def test_entreno_tarde_e_ilusion():
    hoy = "2030-05-20"
    d = {hoy: {"entreno": 1, "entreno_fin": "21:45", "niebla": 4, "comida_tarde": "alta",
               "bloques": [bloque(recall=0), bloque(recall=0), bloque(recall=0)]}}
    ids = {a["id"]: a for a in R.alertas(d, hoy, AJ)}
    assert {"termorregulacion", "ilusion"} <= set(ids) and "fatiga" not in ids  # un solo día de niebla no es fatiga
    # dos bloques sin recall se toleran; la lectura pasiva dominante también es ilusión
    d = {hoy: {"bloques": [bloque(recall=0), bloque(recall=0)]}}
    assert "ilusion" not in {a["id"] for a in R.alertas(d, hoy, AJ)}
    d = {hoy: {"bloques": [bloque(codificacion="lectura", minutos=90), bloque(minutos=30)]}}
    assert "ilusion" in {a["id"] for a in R.alertas(d, hoy, AJ)}


def test_fatiga_persistente_solo_con_sueno_suficiente():
    f = dias_atras(3)
    bien = {"acostarse": "23:00", "despertar": "07:00"}  # 8 h
    d = {f[0]: {**bien, "niebla": 4}, f[1]: {**bien, "dolor_cabeza": 2}, f[2]: {**bien, "niebla": 5, "dolor_cabeza": 3}}
    a = {x["id"]: x for x in R.alertas(d, f[0], AJ)}
    assert "fatiga" in a and "valoración médica" in a["fatiga"]["texto"] and "no es un diagnóstico" in a["fatiga"]["texto"]
    d[f[1]] = {"acostarse": "02:00", "despertar": "07:00", "dolor_cabeza": 2}  # durmió poco: se explica, no es persistente
    assert "fatiga" not in {x["id"] for x in R.alertas(d, f[0], AJ)}
    d[f[1]] = {**bien, "niebla": 2}  # un día sin síntomas corta la racha
    assert "fatiga" not in {x["id"] for x in R.alertas(d, f[0], AJ)}


def test_desajuste_circadiano():
    f = dias_atras(7)
    regular = {x: {"acostarse": "23:30", "despertar": "07:30"} for x in f}
    assert "desajuste" not in {a["id"] for a in R.alertas(regular, f[0], AJ)}
    caos = {x: {"acostarse": h, "despertar": "07:30"} for x, h in zip(f, ["22:00", "02:30", "22:30", "03:00", "23:00", "02:00", "22:15"])}
    a = {x["id"]: x for x in R.alertas(caos, f[0], AJ)}
    assert "desajuste" in a and "acostarte" in a["desajuste"]["texto"]
    pocos = {x: caos[x] for x in f[:3]}  # con menos de 4 días no se juzga
    assert "desajuste" not in {x["id"] for x in R.alertas(pocos, f[0], AJ)}


def test_sobrecarga_y_blindaje_de_dopamina():
    f = dias_atras(7)
    largo = {"bloques": [bloque(minutos=130), bloque(minutos=130)]}  # 260 min > 240
    d = {f[0]: largo, f[1]: largo, f[2]: largo}
    assert "sobrecarga" in {a["id"] for a in R.alertas(d, f[0], AJ)}
    d[f[1]] = {"bloques": [bloque(minutos=200)]}
    assert "sobrecarga" not in {a["id"] for a in R.alertas(d, f[0], AJ)}
    dop = {x: {"dopamina": 1} for x in f[:3]}
    assert "dopamina" in {a["id"] for a in R.alertas(dop, f[0], AJ)}
    dop = {x: {"dopamina": 1} for x in f[:2]}
    assert "dopamina" not in {a["id"] for a in R.alertas(dop, f[0], AJ)}


def test_semaforos():
    bueno = {"acostarse": "23:15", "despertar": "07:15", "pantallas_off": "22:00", "primer_cafe": "09:00",
             "energia": 4, "niebla": 1, "comida_tarde": "baja", "siesta": "corta",
             "bloques": [bloque(), bloque(asignatura="FP", codificacion="codigo")]}
    s = R.semaforos(bueno, AJ)
    assert {k: v["nivel"] for k, v in s.items()} == {"metabolico": "verde", "codificacion": "verde", "sueno": "verde", "rotacion": "verde"}
    malo = {"acostarse": "01:30", "despertar": "06:30", "pantallas_off": "01:20", "calidad_sueno": 2, "niebla": 5,
            "comida_tarde": "alta", "bloques": [bloque(recall=0, codificacion="lectura", estado="degradado", pausas="no", minutos=150)] * 3}
    s = R.semaforos(malo, AJ)
    assert all(v["nivel"] == "rojo" for v in s.values()), s
    assert R.semaforos(None, AJ)["sueno"]["nivel"] == "gris"


def test_correlacion():
    assert R.correlacion([1, 2, 3, 4], [2, 4, 6, 8]) == 1.0
    assert R.correlacion([1, 2, 3], [3, 2, 1]) == -1.0
    assert R.correlacion([1, 1, 1], [1, 2, 3]) is None


# ── API ───────────────────────────────────────────────────────────────────────

def registro(**kw):
    return {"acostarse": "23:20", "despertar": "07:20", "calidad_sueno": 4, "primer_cafe": "09:00", "pantallas_off": "22:15",
            "activacion": "si", "luz_solar": True, "dopamina": False, "siesta": "ninguna", "comida_tarde": "baja",
            "entreno": True, "entreno_fin": "20:00", "entreno_min": 60, "entreno_intensidad": 3,
            "energia": 4, "niebla": 2, "dolor_cabeza": 0, "humor": 4,
            "bloques": [{"asignatura": "IG", "minutos": 90, "recall": True, "codificacion": "problemas", "pausas": "sistematico"},
                        {"asignatura": "FP", "minutos": 60, "recall": True, "codificacion": "codigo", "pausas": "ocasional", "caida": "18:40"}],
            **kw}


def test_registro_y_panel(client):
    f = "2025-04-10"
    r = client.put(f"/api/rendimiento/dia/{f}", json=registro())
    assert r.status_code == 200, r.text
    assert r.json()["semaforos"]["codificacion"]["nivel"] == "verde"
    d = client.get("/api/rendimiento/dia", params={"fecha": f}).json()
    assert d["registro"]["acostarse"] == "23:20" and [b["asignatura"] for b in d["registro"]["bloques"]] == ["IG", "FP"]
    assert "IG" in d["asignaturas"]
    # guardar otra vez sustituye los bloques; sin entreno se limpian sus campos
    client.put(f"/api/rendimiento/dia/{f}", json=registro(entreno=False, bloques=[{"asignatura": "IG", "minutos": 30}]))
    d = client.get("/api/rendimiento/dia", params={"fecha": f}).json()["registro"]
    assert len(d["bloques"]) == 1 and d["entreno_fin"] is None and d["bloques"][0]["codificacion"] == "problemas"
    # el día siguiente sugiere los hábitos del último registro
    s = client.get("/api/rendimiento/dia", params={"fecha": "2025-04-11"}).json()
    assert s["registro"] is None and s["sugerencia"]["acostarse"] == "23:20" and s["fuentes"]["acostarse"] == "último registro"
    p = client.get("/api/rendimiento/panel", params={"fecha": f}).json()
    assert p["registrado"] and p["horas_sueno"] == 8.0


def test_validacion(client):
    f = "2025-04-12"
    assert client.put(f"/api/rendimiento/dia/{f}", json=registro(acostarse="25:00")).status_code == 422
    assert client.put(f"/api/rendimiento/dia/{f}", json=registro(siesta="eterna")).status_code == 422
    assert client.put(f"/api/rendimiento/dia/{f}", json=registro(energia=9)).status_code == 422
    assert client.put(f"/api/rendimiento/dia/{f}", json=registro(bloques=[{"asignatura": " ", "minutos": 10}])).status_code == 422
    assert client.put("/api/rendimiento/dia/2030-13-01", json=registro()).status_code == 422
    futuro = (date.today() + timedelta(days=5)).isoformat()
    assert client.put(f"/api/rendimiento/dia/{futuro}", json=registro()).status_code == 422
    # «7:05» se normaliza
    assert client.put(f"/api/rendimiento/dia/{f}", json=registro(despertar="7:05")).status_code == 200
    assert client.get("/api/rendimiento/dia", params={"fecha": f}).json()["registro"]["despertar"] == "07:05"


def test_borrar_y_restaurar_desde_la_papelera(client):
    f = "2025-04-15"
    client.put(f"/api/rendimiento/dia/{f}", json=registro())
    token = client.delete(f"/api/rendimiento/dia/{f}").json()["trash"]
    assert client.get("/api/rendimiento/dia", params={"fecha": f}).json()["registro"] is None
    assert any(e["token"] == token and e["label"] == "registro de rendimiento" for e in client.get("/api/trash").json()["entries"])
    assert client.post(f"/api/trash/brain/{token}/restore").json()["restored"] == 1
    d = client.get("/api/rendimiento/dia", params={"fecha": f}).json()["registro"]
    assert d and len(d["bloques"]) == 2


def test_serie(client):
    for i, f in enumerate(["2025-03-01", "2025-03-02", "2025-03-04"]):
        client.put(f"/api/rendimiento/dia/{f}", json=registro(dopamina=i == 0, dopamina_hora="17:00"))
    s = client.get("/api/rendimiento/serie", params={"dias": 7, "hasta": "2025-03-07"}).json()
    assert len(s["dias"]) == 7 and s["totales"]["registrados"] == 3
    assert s["totales"]["blindaje"] == 67 and s["totales"]["minutos"] == 450
    assert s["dias"][0]["acostarse"] == "23:20" and not s["dias"][2]["registrado"]
    assert client.get("/api/rendimiento/serie", params={"dias": 0}).status_code == 422


def test_examenes_desde_el_calendario(client):
    hoy = date.today()
    ex = (hoy + timedelta(days=10)).isoformat()
    r = client.post("/api/calendar/events", json={"title": "MH · Examen de teoría", "start": ex, "all_day": True, "kind": "examen"})
    assert r.status_code == 200, r.text
    client.put(f"/api/rendimiento/dia/{hoy.isoformat()}", json=registro(bloques=[{"asignatura": "MH", "minutos": 120, "recall": True}]))
    assert client.put("/api/rendimiento/asignaturas/MH", json={"objetivo_h": 20}).status_code == 200
    a = next(x for x in client.get("/api/rendimiento/examenes").json()["asignaturas"] if x["sigla"] == "MH")
    assert a["dias"] == 10 and a["proximo"]["titulo"] == "Examen de teoría"
    assert a["horas"] == 2.0 and a["deuda_h"] == 18.0 and a["ritmo_h_dia"] == 1.8
    client.put("/api/rendimiento/asignaturas/MH", json={"objetivo_h": None})
    a = next(x for x in client.get("/api/rendimiento/examenes").json()["asignaturas"] if x["sigla"] == "MH")
    assert a["objetivo_h"] is None and a["deuda_h"] is None


def test_correlaciones_necesitan_21_dias(client):
    c = client.get("/api/rendimiento/correlaciones").json()
    if not c["suficiente"]:
        assert "puntos" not in c and c["minimo"] == 21
    base = date(2024, 1, 1)
    for i in range(22):
        h = 6 + (i % 4) * 0.5  # más sueño → más minutos
        despertar = f"{7 + int(h - 6):02d}:{'30' if h % 1 else '00'}"
        client.put(f"/api/rendimiento/dia/{(base + timedelta(days=i)).isoformat()}",
                   json=registro(acostarse="01:00", despertar=despertar,
                                 bloques=[{"asignatura": "IG", "minutos": int(h * 20), "recall": True}]))
    c = client.get("/api/rendimiento/correlaciones").json()
    assert c["suficiente"] and c["n"] >= 22 and c["sueno_minutos"] is not None


def test_ajustes(client):
    a = client.get("/api/rendimiento/ajustes").json()
    assert a["ajustes"]["limite_acostarse"] == "00:30" and any(c["clave"] == "niebla_alerta" for c in a["campos"])
    r = client.put("/api/rendimiento/ajustes", json={"limite_acostarse": "01:00", "max_enfoque_min": "300"})
    assert r.status_code == 200 and r.json()["ajustes"]["max_enfoque_min"] == 300
    assert client.put("/api/rendimiento/ajustes", json={"niebla_alerta": 9}).status_code == 422
    assert client.put("/api/rendimiento/ajustes", json={"inventado": 1}).status_code == 422
    assert client.put("/api/rendimiento/ajustes", json={"rutinas": {"entreno": "x"}}).status_code == 422
    client.put("/api/rendimiento/ajustes", json={"limite_acostarse": "00:30", "max_enfoque_min": 240})  # vuelve al valor por defecto
    assert client.get("/api/rendimiento/ajustes").json()["ajustes"]["max_enfoque_min"] == 240


def test_precarga_desde_rutinas(client):
    rid = client.post("/api/items", json={"text": "Gimnasio prueba", "type": "rutina", "due_time": "19:00", "duration_min": 60,
                                          "repeat": {"freq": "daily"}}).json()["id"]
    client.put("/api/rendimiento/ajustes", json={"rutinas": {"entreno": rid}})
    f = date.today().isoformat()
    s = client.get("/api/rendimiento/dia", params={"fecha": f}).json()
    assert s["sugerencia"]["entreno"] == 0
    r = client.post(f"/api/routines/{rid}/check", json={"day": f})
    assert r.status_code == 200, r.text
    s = client.get("/api/rendimiento/dia", params={"fecha": f}).json()
    assert s["sugerencia"]["entreno"] == 1 and s["sugerencia"]["entreno_fin"] == "20:00"
    assert "Gimnasio prueba" in s["fuentes"]["entreno"]
    client.put("/api/rendimiento/ajustes", json={"rutinas": {}})


def test_pagina(client):
    r = client.get("/rendimiento")
    assert r.status_code == 200 and "Rendimiento" in r.text
