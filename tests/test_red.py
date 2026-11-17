"""Red (core/red.py y core/mdns.py): validación, conflictos, orden de búsqueda de la placa, límite del barrido,
latidos y estado guardado. Nada sale a la red: `es_la_placa`, mDNS, vecinos y Tailscale van parcheados."""

import json
import re
import socket
import struct
from pathlib import Path

import pytest

from core import config, mdns, red

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture()
def r(monkeypatch):
    """`core.red` limpio, con placa «auto», este equipo en 192.168.1.36 y sin nadie que conteste."""
    archivo = Path(config.DATA_DIR) / "red.json"
    archivo.unlink(missing_ok=True)
    red.reiniciar_para_tests()
    monkeypatch.setattr(config, "ESP32_HOST", "auto")
    monkeypatch.setattr(mdns, "ips_locales", lambda: ["192.168.1.36"])
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: None)
    monkeypatch.setattr(red, "vecinos", dict)
    monkeypatch.setattr(red, "_tailscale", lambda: {"activo": False})
    monkeypatch.setattr(red, "_barrer", lambda mac: None)
    vivas: set[str] = set()
    monkeypatch.setattr(red, "es_la_placa", lambda host, timeout=1.5: host in vivas)
    red.vivas = vivas  # type: ignore[attr-defined]
    yield red
    del red.vivas  # type: ignore[attr-defined]
    archivo.unlink(missing_ok=True)
    red.reiniciar_para_tests()


# ── mDNS: paquetes de pega ──────────────────────────────────────────────
def _nombre(texto: str) -> bytes:
    return b"".join(bytes([len(p)]) + p.encode() for p in texto.split(".")) + b"\x00"


def _respuesta(nombre: str, ip: str, comprimida: bool = False) -> bytes:
    cabecera = struct.pack(">HHHHHH", 0, 0x8400, 1 if comprimida else 0, 1, 0, 0)
    registro = struct.pack(">HHIH", 1, 0x8001, 120, 4) + socket.inet_aton(ip)
    if comprimida:  # la respuesta repite la pregunta y su nombre es un puntero a ella (posición 12)
        return cabecera + _nombre(nombre) + struct.pack(">HH", 1, 1) + b"\xc0\x0c" + registro
    return cabecera + _nombre(nombre) + registro


def test_mdns_pregunta_bien_formada():
    p = mdns._pregunta("panel-estudio.local")
    assert p[:12] == struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    assert p[12:] == _nombre("panel-estudio.local") + struct.pack(">HH", 1, 0x8001)


def test_mdns_lee_respuestas_a():
    assert mdns.respuestas_a(_respuesta("Panel-Estudio.local", "192.168.1.35")) == [
        ("panel-estudio.local", "192.168.1.35")
    ]
    assert mdns.respuestas_a(_respuesta("panel-estudio.local", "192.168.1.35", comprimida=True)) == [
        ("panel-estudio.local", "192.168.1.35")
    ]


def test_mdns_ignora_preguntas_y_paquetes_rotos():
    assert mdns.respuestas_a(mdns._pregunta("panel-estudio.local")) == []  # la nuestra, de vuelta por el grupo
    bueno = _respuesta("panel-estudio.local", "192.168.1.35")
    for corte in (0, 5, 12, 20, len(bueno) - 2):
        assert mdns.respuestas_a(bueno[:corte]) == []
    bucle = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 0) + b"\xc0\x0c"  # puntero que se apunta a sí mismo
    assert mdns.respuestas_a(bucle) == []


def test_mdns_otros_tipos_no_cuentan():
    aaaa = struct.pack(">HHHHHH", 0, 0x8400, 0, 2, 0, 0)
    aaaa += _nombre("x.local") + struct.pack(">HHIH", 28, 1, 120, 16) + bytes(16)
    aaaa += _nombre("x.local") + struct.pack(">HHIH", 1, 1, 120, 4) + socket.inet_aton("10.0.0.7")
    assert mdns.respuestas_a(aaaa) == [("x.local", "10.0.0.7")]


def test_hostname_del_firmware_coincide():
    """El nombre que anuncia la placa por mDNS es el que busca el panel."""
    texto = (RAIZ / "esp32_deskclock" / "config.h").read_text(encoding="utf-8")
    m = re.search(r'#define\s+HOSTNAME\s+"([^"]+)"', texto)
    assert m and m.group(1) == red.ESP32_HOSTNAME


# ── Validación y conflictos ─────────────────────────────────────────────
def test_validar_ipv4(r):
    assert r.validar_ipv4(" 192.168.001.060 ") == "192.168.1.60"
    for mala in ("", "abc", "192.168.1", "192.168.1.60.4", "300.1.1.1", "192.168.1.-3", "::1"):
        with pytest.raises(ValueError):
            r.validar_ipv4(mala)
    for no_dispositivo in ("127.0.0.1", "0.0.0.0", "224.0.0.251", "169.254.3.4", "192.168.1.0", "192.168.1.255"):
        with pytest.raises(ValueError):
            r.validar_ipv4(no_dispositivo)
    assert r.validar_ipv4("192.168.1.255", "255.255.0.0") == "192.168.1.255"  # en una /16 sí es un equipo


def test_validar_mascara(r):
    assert r.validar_mascara("255.255.255.0") == "255.255.255.0"
    assert r.validar_mascara("24") == "255.255.255.0"
    for mala in ("255.0.255.0", "hola", "", "33"):
        with pytest.raises(ValueError):
            r.validar_mascara(mala)


def test_conflictos(r):
    assert "este equipo" in r.conflicto("192.168.1.36", "esp32")
    assert "este equipo" in r.conflicto("192.168.1.50", "esp32")  # la reserva del equipo
    assert "router" in r.conflicto("192.168.1.1", "esp32")
    assert "ESP32" in r.conflicto("192.168.1.60", "servidor")
    assert r.conflicto("192.168.1.35", "esp32") is None
    assert r.conflicto("192.168.1.60", "esp32") is None  # su propia reserva no choca consigo misma


def test_cambiar_ajustes_valida_y_guarda(r):
    r.cambiar_ajustes({"esp32": "192.168.1.31", "esp32_manual": "192.168.1.35"})
    assert r.ajuste("esp32") == "192.168.1.31" and r.ajuste("gateway") == "192.168.1.1"
    guardado = json.loads((Path(config.DATA_DIR) / "red.json").read_text(encoding="utf-8"))
    assert guardado["ajustes"] == {"esp32": "192.168.1.31", "esp32_manual": "192.168.1.35"}
    assert r.esp32_host() == "192.168.1.35"

    with pytest.raises(ValueError, match="este equipo"):
        r.cambiar_ajustes({"esp32_manual": "192.168.1.36"})
    with pytest.raises(ValueError, match="compartir"):
        r.cambiar_ajustes({"gateway": "192.168.1.31"})
    with pytest.raises(ValueError):
        r.cambiar_ajustes({"servidor": "no-es-ip"})
    assert r.ajuste("esp32") == "192.168.1.31"  # un cambio rechazado no deja nada a medias

    r.cambiar_ajustes({"esp32_manual": ""})  # vacío = vuelve a ser automática
    assert r.estado()["esp32"]["manual"] == ""
    assert r.esp32_host() == "192.168.1.31"


def test_estado_se_recuerda_y_un_archivo_roto_no_rompe(r):
    r.vivas.add("192.168.1.35")
    r.cambiar_ajustes({"esp32_manual": "192.168.1.35"})
    assert r.detectar_esp32()["ok"]
    r.reiniciar_para_tests()  # como tras reiniciar el panel
    assert r.cargar()["esp32"]["ip"] == "192.168.1.35"

    (Path(config.DATA_DIR) / "red.json").write_text("{esto no es json", encoding="utf-8")
    r.reiniciar_para_tests()
    assert r.cargar() == {"version": 1, "esp32": {}, "extension": {}, "ajustes": {}}
    (Path(config.DATA_DIR) / "red.json").write_text('{"esp32": "mal", "ajustes": []}', encoding="utf-8")
    r.reiniciar_para_tests()
    assert r.cargar()["esp32"] == {} and r.ajuste("esp32") == "192.168.1.60"


# ── Búsqueda de la placa ────────────────────────────────────────────────
def test_sin_placa_no_se_busca(r, monkeypatch):
    monkeypatch.setattr(config, "ESP32_HOST", "")
    assert r.esp32_host() == "" and r.esp32_ws_url() == ""
    res = r.detectar_esp32()
    assert res["ok"] is False and res["motivo"] == "sin-placa" and res["probadas"] == []
    assert r.redetectar_si_toca() is False


def test_orden_de_busqueda(r, monkeypatch):
    """manual → última → mDNS → .env → MAC conocida → respaldo → barrido; cada dirección se prueba una sola vez."""
    monkeypatch.setattr(config, "ESP32_HOST", "192.168.1.40")
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.41")
    monkeypatch.setattr(
        red, "vecinos", lambda: {"192.168.1.42": "24:0a:c4:12:34:56", "192.168.1.9": "aa:aa:aa:aa:aa:aa"}
    )
    r.cargar()["esp32"].update({"ip": "192.168.1.39", "mac": "24:0a:c4:12:34:56"})
    r.cargar()["ajustes"]["esp32_manual"] = "192.168.1.38"
    res = r.detectar_esp32()
    assert res["ok"] is False and res["motivo"] == "no-responde"
    assert res["probadas"] == [
        ["manual", "192.168.1.38"],
        ["última", "192.168.1.39"],
        ["mdns", "192.168.1.41"],
        ["env", "192.168.1.40"],
        ["mac", "192.168.1.42"],
        ["respaldo", "192.168.1.60"],
        ["barrido", "subred"],
    ]


@pytest.mark.parametrize(
    ("viva", "origen"),
    [("192.168.1.41", "mdns"), ("192.168.1.40", "env"), ("192.168.1.42", "mac"), ("192.168.1.60", "respaldo")],
)
def test_se_queda_con_la_primera_que_contesta(r, monkeypatch, viva, origen):
    monkeypatch.setattr(config, "ESP32_HOST", "192.168.1.40")
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.41")
    monkeypatch.setattr(red, "vecinos", lambda: {"192.168.1.42": "24:0a:c4:12:34:56"})
    r.cargar()["esp32"].update({"ip": "192.168.1.39", "mac": "24:0a:c4:12:34:56"})
    r.vivas.add(viva)
    res = r.detectar_esp32()
    assert res == {"ok": True, "ip": viva, "origen": origen, "cambio": True, "probadas": res["probadas"]}
    assert res["probadas"][-1] == [origen, viva]
    assert r.esp32_host() == viva and r.esp32_ws_url() == f"ws://{viva}/ws"
    assert r.cargar()["esp32"]["ip_anterior"] == "192.168.1.39"
    assert r.estado()["esp32"]["en_linea"] is True

    otra = r.detectar_esp32()  # sigue donde estaba: no es un cambio y conserva de dónde salió
    assert otra["ok"] and otra["cambio"] is False and otra["origen"] == origen


def test_la_ip_a_mano_manda(r, monkeypatch):
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.41")
    r.vivas.update({"192.168.1.41", "192.168.1.52"})
    r.cambiar_ajustes({"esp32_manual": "192.168.1.52"})
    res = r.detectar_esp32()
    assert res["ip"] == "192.168.1.52" and res["origen"] == "manual" and res["probadas"] == [["manual", "192.168.1.52"]]


def test_la_mac_se_aprende_de_los_vecinos(r, monkeypatch):
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.35")
    monkeypatch.setattr(red, "vecinos", lambda: {"192.168.1.35": "24:0A:C4:12:34:56"})
    r.vivas.add("192.168.1.35")
    assert r.detectar_esp32()["ok"]
    assert r.cargar()["esp32"]["mac"] == "24:0a:c4:12:34:56"


def test_barrido_como_mucho_cada_diez_minutos(r, monkeypatch):
    llamadas = []
    monkeypatch.setattr(red, "_barrer", lambda mac: llamadas.append(mac))
    reloj = [5000.0]
    monkeypatch.setattr(red.time, "monotonic", lambda: reloj[0])
    assert ["barrido", "subred"] in r.detectar_esp32()["probadas"]
    assert ["barrido", "subred"] not in r.detectar_esp32()["probadas"]  # recién hecho: no se repite
    reloj[0] += red.BARRIDO_CADA_S - 1
    r.detectar_esp32()
    assert len(llamadas) == 1
    reloj[0] += 1
    r.detectar_esp32()
    assert len(llamadas) == 2
    r.detectar_esp32(barrido=False)
    assert len(llamadas) == 2


def test_barrido_encuentra_la_placa(r, monkeypatch):
    monkeypatch.setattr(red, "_barrer", lambda mac: "192.168.1.77")
    res = r.detectar_esp32()
    assert res["ok"] and res["ip"] == "192.168.1.77" and res["origen"] == "barrido"


def test_barrer_prueba_solo_los_puertos_abiertos_y_antes_la_mac(r, monkeypatch):
    monkeypatch.undo()  # el `_barrer` de verdad…
    monkeypatch.setattr(mdns, "ips_locales", lambda: ["192.168.1.36"])
    monkeypatch.setattr(red, "_puerto_abierto", lambda ip, *a, **k: ip in ("192.168.1.1", "192.168.1.35"))
    monkeypatch.setattr(red, "vecinos", lambda: {"192.168.1.35": "24:0a:c4:12:34:56"})
    pedidas = []
    monkeypatch.setattr(red, "es_la_placa", lambda ip, timeout=1.5: pedidas.append(ip) or ip == "192.168.1.35")
    assert red._barrer("24:0a:c4:12:34:56") == "192.168.1.35"
    assert pedidas == ["192.168.1.35"]  # la de su MAC primero: al router ni se le pregunta
    red.cargar()["ajustes"]["mascara"] = "255.255.0.0"  # una /16 no se barre
    assert red._barrer("") is None


def test_recien_arrancado_el_equipo_tambien_se_busca(r, monkeypatch):
    """El reloj monótono empieza en el arranque: con 20 s de equipo encendido la primera búsqueda no espera."""
    monkeypatch.setattr(red.time, "monotonic", lambda: 20.0)
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.35")
    r.vivas.add("192.168.1.35")
    assert r.redetectar_si_toca() is True
    r.vivas.clear()
    r.cargar()["esp32"].clear()
    assert ["barrido", "subred"] in r.detectar_esp32()["probadas"]


def test_redetectar_una_vez_por_minuto(r, monkeypatch):
    reloj = [9000.0]
    monkeypatch.setattr(red.time, "monotonic", lambda: reloj[0])
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.35")
    assert r.redetectar_si_toca() is False  # se busca, pero nadie contesta
    r.vivas.add("192.168.1.35")
    assert r.redetectar_si_toca() is False  # hace menos de un minuto: ni se intenta
    reloj[0] += red.AUTO_CADA_S
    assert r.redetectar_si_toca() is True  # ha aparecido en otra dirección: los puentes reconectan ya
    reloj[0] += red.AUTO_CADA_S
    assert r.redetectar_si_toca() is False  # sigue en la misma


def test_es_la_placa_pide_la_firma(monkeypatch):
    class Resp:
        def __init__(self, cuerpo):
            self.cuerpo = cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return self.cuerpo[:n]

    pedidas = []

    def urlopen(url, timeout):
        pedidas.append(url)
        if "1.99" in url:
            raise OSError("sin ruta")
        return Resp(b"Panel de estudio ESP32 - usa /ws" if "1.35" in url else b"<html>router</html>")

    monkeypatch.setattr(red.urllib.request, "urlopen", urlopen)
    assert red.es_la_placa("192.168.1.35") is True
    assert red.es_la_placa("192.168.1.1") is False
    assert red.es_la_placa("192.168.1.99") is False
    assert pedidas[0] == "http://192.168.1.35/"


# ── Latidos ─────────────────────────────────────────────────────────────
def test_latido_del_esp32(r):
    r.cargar()["esp32"]["ip"] = "192.168.1.60"
    r.latido_esp32(
        {
            "type": "heartbeat",
            "ip": "192.168.1.35",
            "mac": "24:0A:C4:12:34:56",
            "host": "panel-estudio",
            "fw": "2.3.0",
            "uptime": 1234,
            "heap": 151000,
            "heap_min": 98000,
            "rssi": -57,
            "clients": 3,
        }
    )
    e = r.estado()["esp32"]
    assert e["ip"] == "192.168.1.35" and e["ip_anterior"] == "192.168.1.60" and e["origen"] == "latido"
    assert e["mac"] == "24:0a:c4:12:34:56" and e["fw"] == "2.3.0" and e["host"] == "panel-estudio"
    assert e["heap"] == 151000 and e["rssi"] == -57 and e["uptime"] == 1234 and e["en_linea"] is True
    assert e["direccion"] == "192.168.1.35" and e["coincide_reserva"] is False and e["respaldo"] == "192.168.1.60"
    guardado = json.loads((Path(config.DATA_DIR) / "red.json").read_text(encoding="utf-8"))
    assert guardado["esp32"]["ip"] == "192.168.1.35" and "heap" not in guardado["esp32"]  # lo del momento no se guarda


def test_latido_con_basura_no_estropea_nada(r):
    r.cargar()["esp32"].update({"ip": "192.168.1.35", "mac": "24:0a:c4:12:34:56"})
    r.latido_esp32({"ip": "999.1.1.1", "mac": "no-es-mac", "fw": "x" * 500, "heap": "mucho", "rssi": None})
    e = r.estado()["esp32"]
    assert e["ip"] == "192.168.1.35" and e["mac"] == "24:0a:c4:12:34:56"
    assert len(e["fw"]) == 40 and "heap" not in e and "rssi" not in e
    r.latido_esp32({}, origen_ip="127.0.0.1")  # sin datos y con origen que no vale
    assert r.estado()["esp32"]["ip"] == "192.168.1.35"


def test_en_linea_caduca(r, monkeypatch):
    r.visto_esp32()
    assert r.estado()["esp32"]["en_linea"] is True
    ahora = red.time.time()
    monkeypatch.setattr(red.time, "time", lambda: ahora + red.EN_LINEA_S + 1)
    assert r.estado()["esp32"]["en_linea"] is False


def test_latido_de_la_extension(r, monkeypatch):
    monkeypatch.setenv("PANEL_HOST", "127.0.0.1")
    monkeypatch.setenv("PANEL_PORT", "8000")
    monkeypatch.setattr(
        red,
        "_tailscale",
        lambda: {"activo": True, "ip": "100.64.0.9", "nombre": "equipo.t.ts.net", "url": "https://equipo.t.ts.net"},
    )
    assert r.estado()["extension"] == {"conocida": False, "activa": False, "url_vigente": True}
    r.latido_extension("2.11", "https://equipo.t.ts.net/", "100.64.0.3", "Firefox 150")
    x = r.estado()["extension"]
    assert x["conocida"] and x["activa"] and x["url_vigente"] and x["version"] == "2.11" and x["ip"] == "100.64.0.3"
    r.latido_extension("2.11", "http://localhost:8000", "127.0.0.1")
    assert r.estado()["extension"]["url_vigente"] is True
    r.latido_extension("2.9", "http://192.168.1.45:8000", "192.168.1.36")  # la IP antigua
    assert r.estado()["extension"]["url_vigente"] is False


# ── Este equipo ─────────────────────────────────────────────────────────
def test_servidor_solo_local_con_tailscale(r, monkeypatch):
    monkeypatch.setenv("PANEL_HOST", "127.0.0.1")
    monkeypatch.setenv("PANEL_PORT", "8000")
    monkeypatch.delenv("PANEL_SSL_CERT", raising=False)
    monkeypatch.setattr(
        red,
        "_tailscale",
        lambda: {"activo": True, "ip": "100.64.0.9", "nombre": "equipo.t.ts.net", "url": "https://equipo.t.ts.net"},
    )
    s = r.servidor()
    assert s["solo_local"] is True and s["ips"] == ["192.168.1.36"] and s["coincide_reserva"] is False
    assert [u["url"] for u in s["urls"]] == ["http://127.0.0.1:8000", "https://equipo.t.ts.net"]
    assert s["principal"] == "https://equipo.t.ts.net"


def test_servidor_en_la_red_local(r, monkeypatch):
    monkeypatch.setenv("PANEL_HOST", "0.0.0.0")
    monkeypatch.setenv("PANEL_PORT", "8123")
    monkeypatch.delenv("PANEL_SSL_CERT", raising=False)
    monkeypatch.setattr(mdns, "ips_locales", lambda: ["192.168.1.50", "192.168.1.37"])
    s = r.servidor()
    assert s["solo_local"] is False and s["coincide_reserva"] is True
    assert [u["url"] for u in s["urls"]] == [
        "http://127.0.0.1:8123",
        "http://192.168.1.50:8123",
        "http://192.168.1.37:8123",
    ]
    assert s["principal"] == "http://192.168.1.37:8123"


def test_tailscale_sin_instalar(monkeypatch):
    red.reiniciar_para_tests()

    def no_esta(*a, **k):
        raise FileNotFoundError("tailscale")

    monkeypatch.setattr(red.subprocess, "run", no_esta)
    assert red._tailscale() == {"activo": False}
    red.reiniciar_para_tests()


# ── python -m scripts.red ───────────────────────────────────────────────
def test_script_red(r, monkeypatch, capsys):
    from scripts import red as cli

    monkeypatch.setenv("PANEL_HOST", "127.0.0.1")
    assert cli.main([]) == 0
    assert "192.168.1.60" in capsys.readouterr().out
    monkeypatch.setattr(mdns, "resolver", lambda *a, **k: "192.168.1.35")
    assert cli.main(["--redetectar"]) == 1  # nadie contesta
    assert "no contesta" in capsys.readouterr().out
    r.vivas.add("192.168.1.35")
    assert cli.main(["--redetectar", "--json"]) == 0
    datos = json.loads(capsys.readouterr().out)
    assert datos["resultado"]["ip"] == "192.168.1.35" and datos["esp32"]["direccion"] == "192.168.1.35"


def test_latido_motivo_de_arranque_y_booleanos(r):
    r.latido_esp32({"ip": "192.168.1.35", "reset": "vigilante", "sd": True, "clients": True, "heap": 120000})
    e = r.estado()["esp32"]
    assert e["reset"] == "vigilante" and e["heap"] == 120000 and "clients" not in e  # True no es un número de clientes
