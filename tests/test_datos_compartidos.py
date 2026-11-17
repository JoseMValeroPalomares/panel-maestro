"""P-12: guardas de la carpeta de datos compartida con Windows (app/datos_compartidos.py, docs/windows.md §3)."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app import backup
from app import datos_compartidos as dc
from core import config


@pytest.fixture()
def datos(tmp_path, monkeypatch):
    """Una carpeta de datos propia (como la de la partición) con las dos BDs en WAL."""
    raiz = tmp_path / "particion" / "panel-maestro"
    data = raiz / "data"
    (data / "notes").mkdir(parents=True)
    (data / "notes" / "una.md").write_text("---\ntitle: Una\n---\nhola\n", encoding="utf-8")
    rutas = {
        "DATA_DIR": data,
        "NOTES_DIR": data / "notes",
        "BRAIN_DB": data / "brain.db",
        "TRASH_DIR": data / "trash",
        "COMIDAS_DB": raiz / "comidas" / "comidas.db",
        "UPLOADS_DIR": raiz / "uploads",
        "CALENDAR_STATE": raiz / "estudio" / "calendar_sync_v2.json",
        "BACKUPS_DIR": tmp_path / "copias-locales",
        "LOGS_DIR": tmp_path / "logs",
    }
    for k, v in rutas.items():
        monkeypatch.setattr(config, k, v)
    monkeypatch.setattr(backup, "BACKUPS_DIR", rutas["BACKUPS_DIR"])
    monkeypatch.setattr(backup, "STATUS_FILE", rutas["BACKUPS_DIR"] / "status.json")
    monkeypatch.setattr(backup, "ESTUDIO_STATE", rutas["CALENDAR_STATE"].with_name("calendar_sync_state.json"))
    rutas["COMIDAS_DB"].parent.mkdir(parents=True)
    for db in (rutas["BRAIN_DB"], rutas["COMIDAS_DB"]):
        conn = sqlite3.connect(db)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (v) VALUES ('inicial')")
        conn.commit()
        conn.close()
    monkeypatch.setattr(dc, "_estado", {})
    monkeypatch.setattr(dc, "_abiertos", 0)  # sin contar el lifespan del cliente de la sesión
    return rutas


def _cerrojo(rutas, **campos):
    base = {"sistema": "linux", "equipo": "otro", "pid": 999999, "arranque": "x", "abierto": 1.0, "cerrado": None}
    (rutas["DATA_DIR"] / dc.CERROJO).write_text(json.dumps({**base, **campos}), encoding="utf-8")


def _windows_abierto(rutas):
    _cerrojo(rutas, sistema="windows", equipo="DESKTOP-PRUEBA", arranque="inicio-1")


def _foto(carpeta: Path) -> dict:
    """Contenido byte a byte de toda la carpeta de datos (para comprobar que no se escribe nada)."""
    return {str(p.relative_to(carpeta)): p.read_bytes() for p in sorted(carpeta.rglob("*")) if p.is_file()}


def _con_wal_pendiente(db: Path, filas: int = 3) -> None:
    """Deja en `db` un -wal con transacciones confirmadas que no pasaron al .db, como tras matar el proceso."""
    trabajo = db.with_name("trabajo-" + db.name)
    shutil.copyfile(db, trabajo)
    conn = sqlite3.connect(trabajo)
    conn.execute("PRAGMA wal_autocheckpoint=0")
    for i in range(filas):
        conn.execute("INSERT INTO t (v) VALUES (?)", (f"en-wal-{i}",))
        conn.commit()
    shutil.copyfile(trabajo, db)  # «foto» con la conexión abierta: el -wal tiene lo último
    shutil.copyfile(f"{trabajo}-wal", f"{db}-wal")
    conn.close()
    for p in (trabajo, Path(f"{trabajo}-wal"), Path(f"{trabajo}-shm")):
        p.unlink(missing_ok=True)


def _filas(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        conn.close()


# ── Arranque normal y cierre ─────────────────────────────────


def test_sin_cerrojo_arranca_y_cierra_limpio(datos):
    dc.al_arrancar()
    c = json.loads((datos["DATA_DIR"] / dc.CERROJO).read_text(encoding="utf-8"))
    assert c["pid"] == os.getpid() and c["cerrado"] is None and c["sistema"] == config.PLATFORM
    _con_wal_pendiente(datos["BRAIN_DB"], 2)  # cambios del día
    _cerrojo(datos, **{**c})  # sigue siendo el nuestro
    dc.al_cerrar()
    c = json.loads((datos["DATA_DIR"] / dc.CERROJO).read_text(encoding="utf-8"))
    assert c["cerrado"]
    assert not dc.wal_pendiente()
    assert _filas(datos["BRAIN_DB"]) == 3
    dc.al_cerrar()  # dos veces no pasa nada


def test_el_lifespan_del_panel_deja_su_cerrojo(client):
    c = json.loads((Path(config.DATA_DIR) / dc.CERROJO).read_text(encoding="utf-8"))
    assert c["pid"] == os.getpid() and c["cerrado"] is None


def test_checkpoint_en_reposo_vacia_el_wal(datos):
    _con_wal_pendiente(datos["COMIDAS_DB"])
    assert dc.wal_pendiente() == ["comidas.db"]
    dc.checkpoint_en_reposo()
    assert dc.wal_pendiente() == []
    assert _filas(datos["COMIDAS_DB"]) == 4


# ── Carpeta que no se puede escribir ─────────────────────────


@pytest.mark.skipif(getattr(os, "geteuid", lambda: -1)() == 0, reason="root escribe en todo")
@pytest.mark.permisos_unix
def test_carpeta_en_solo_lectura_se_niega_y_no_escribe(datos):
    antes = _foto(datos["DATA_DIR"])
    os.chmod(datos["DATA_DIR"], 0o500)
    try:
        with pytest.raises(dc.ArranqueDenegado) as e:
            dc.al_arrancar()
    finally:
        os.chmod(datos["DATA_DIR"], 0o700)
    assert e.value.motivo == "solo-lectura"
    assert "inicio rápido" in str(e.value)
    assert _foto(datos["DATA_DIR"]) == antes
    anotado = json.loads((datos["LOGS_DIR"] / dc.DENEGADO).read_text(encoding="utf-8"))
    assert anotado["motivo"] == "solo-lectura" and anotado["accion"]


@pytest.mark.skipif(not hasattr(os, "statvfs"), reason="statvfs solo existe en Unix")
def test_montaje_en_solo_lectura_se_niega(datos, monkeypatch):
    real = os.statvfs

    class Ro:
        def __init__(self, r):
            self.r = r

        def __getattr__(self, k):
            return os.ST_RDONLY if k == "f_flag" else getattr(self.r, k)

    monkeypatch.setattr(dc.os, "statvfs", lambda p: Ro(real(p)))
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert e.value.motivo == "solo-lectura" and "solo lectura" in e.value.mensaje
    assert not (datos["DATA_DIR"] / dc.CERROJO).exists()


def test_particion_sin_montar_no_crea_una_carpeta_vacia(datos, monkeypatch, tmp_path):
    falta = tmp_path / "mnt-datos-sin-montar" / "panel-maestro" / "comidas"
    monkeypatch.setattr(config, "COMIDAS_DB", falta / "comidas.db")
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert "sin montar" in e.value.mensaje
    assert not falta.parent.exists()


@pytest.mark.permisos_unix
def test_tras_negarse_y_arrancar_bien_se_borra_el_aviso(datos):
    os.chmod(datos["DATA_DIR"], 0o500)
    try:
        with pytest.raises(dc.ArranqueDenegado):
            dc.al_arrancar()
    finally:
        os.chmod(datos["DATA_DIR"], 0o700)
    assert (datos["LOGS_DIR"] / dc.DENEGADO).exists()
    dc.al_arrancar()
    assert not (datos["LOGS_DIR"] / dc.DENEGADO).exists()


# ── Windows hibernado y datos movidos ────────────────────────


def test_windows_con_inicio_rapido_activo_se_niega(datos, monkeypatch):
    monkeypatch.setattr(config, "IS_WINDOWS", False)
    (datos["DATA_DIR"] / dc.ESTADO_WINDOWS).write_text(
        json.dumps({"inicio_rapido": True, "hibernacion": False, "comprobado": "2026-11-16 10:00"}), encoding="utf-8"
    )
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert e.value.motivo == "windows-hibernacion" and "inicio rápido" in e.value.mensaje
    (datos["DATA_DIR"] / dc.ESTADO_WINDOWS).write_text(
        json.dumps({"inicio_rapido": False, "hibernacion": False}), encoding="utf-8"
    )
    dc.al_arrancar()


def test_datos_viejos_tras_moverlos_se_niega(datos):
    (datos["DATA_DIR"] / dc.MARCA_MOVIDO).write_text("Ahora están en /mnt/datos/panel-maestro", encoding="utf-8")
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert e.value.motivo == "datos-movidos" and "/mnt/datos" in e.value.mensaje


# ── Cerrojo ──────────────────────────────────────────────────


def test_otro_panel_vivo_con_los_mismos_datos(datos):
    yo = dc.identidad()
    vivo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _cerrojo(datos, sistema=yo["sistema"], equipo=yo["equipo"], arranque=yo["arranque"], pid=vivo.pid)
        with pytest.raises(dc.ArranqueDenegado) as e:
            dc.al_arrancar()
        assert e.value.motivo == "en-uso" and str(vivo.pid) in e.value.mensaje
    finally:
        vivo.kill()
        vivo.wait()


def test_caida_de_este_sistema_en_reposo_sigue(datos):
    yo = dc.identidad()
    _cerrojo(datos, sistema=yo["sistema"], equipo=yo["equipo"], arranque="otro-encendido", pid=12345)
    informe = dc.al_arrancar()
    assert informe["aviso"] is None and "reposo" in informe["nota"] and informe["copia"] is None


def test_caida_de_este_sistema_con_wal_comprueba_y_sigue(datos):
    yo = dc.identidad()
    _cerrojo(datos, sistema=yo["sistema"], equipo=yo["equipo"], arranque="otro-encendido", pid=12345)
    _con_wal_pendiente(datos["BRAIN_DB"])
    informe = dc.al_arrancar()
    assert "no se cerró bien" in informe["aviso"]
    assert not dc.wal_pendiente() and _filas(datos["BRAIN_DB"]) == 4
    copias = list(datos["BACKUPS_DIR"].glob("cierre-sucio-*"))
    assert len(copias) == 1 and (copias[0] / "brain.db").is_file()
    item = dc.status_item()
    assert item["state"] == "aviso" and "no se cerró bien" in item["detail"]


def test_cierre_limpio_del_otro_sistema_hace_copia_y_sigue(datos):
    _cerrojo(datos, sistema="windows", equipo="DESKTOP-PRUEBA", cerrado=2.0)
    informe = dc.al_arrancar()
    assert informe["copia"].startswith("backup_cambio-sistema_")
    with zipfile.ZipFile(datos["BACKUPS_DIR"] / informe["copia"]) as zf:
        assert {"data/brain.db", "comidas/comidas.db", "notes/una.md"} <= set(zf.namelist())
    assert "Windows" in informe["nota"]


def test_otro_sistema_sin_cerrar_pero_en_reposo_sigue_con_copia(datos):
    _windows_abierto(datos)
    informe = dc.al_arrancar()
    assert informe["copia"].startswith("backup_cambio-sistema_") and "reposo" in informe["nota"]


def test_cierre_sucio_del_otro_sistema_avisa_y_no_escribe(datos):
    _windows_abierto(datos)
    _con_wal_pendiente(datos["BRAIN_DB"])
    antes = _foto(datos["DATA_DIR"])
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert e.value.motivo == "cierre-sucio"
    assert "Windows (DESKTOP-PRUEBA)" in e.value.mensaje and "seguir" in e.value.accion
    assert _foto(datos["DATA_DIR"]) == antes  # ni el cerrojo ni las BDs
    copias = list(datos["BACKUPS_DIR"].glob("cierre-sucio-*"))
    assert len(copias) == 1
    assert _filas(copias[0] / "brain.db") == 4  # la copia recuperó el WAL
    # Reintentar el arranque no hace otra copia
    with pytest.raises(dc.ArranqueDenegado):
        dc.al_arrancar()
    assert len(list(datos["BACKUPS_DIR"].glob("cierre-sucio-*"))) == 1
    assert _foto(datos["DATA_DIR"]) == antes
    # «seguir»: repite la comprobación, recupera el WAL y deja el cerrojo cerrado
    r = dc.seguir()
    assert r["ok"] and "están bien" in r["mensaje"]
    assert not dc.wal_pendiente() and _filas(datos["BRAIN_DB"]) == 4
    c = dc.leer_cerrojo()
    assert c["cerrado"] and c["aceptado"] and c["sistema"] == "windows"
    informe = dc.al_arrancar()  # ahora es un cierre limpio de Windows: copia y sigue
    assert informe["copia"].startswith("backup_cambio-sistema_")


def test_cierre_sucio_con_la_bd_danada_se_niega_y_seguir_tambien(datos):
    db = datos["BRAIN_DB"]
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE grande (id INTEGER PRIMARY KEY, v TEXT)")
    conn.execute("CREATE INDEX grande_v ON grande(v)")
    conn.executemany("INSERT INTO grande (v) VALUES (?)", [(f"fila-{i:05d}" * 4,) for i in range(3000)])
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    _con_wal_pendiente(db)
    with open(db, "r+b") as f:  # páginas del medio machacadas
        f.seek(4096 * 6)
        f.write(b"\x07" * 4096 * 4)
    _windows_abierto(datos)
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert e.value.motivo == "cierre-sucio-dañado" and "FALLA" in e.value.mensaje
    r = dc.seguir()
    assert not r["ok"] and not dc.leer_cerrojo()["cerrado"]


@pytest.mark.skipif(sys.platform == "win32", reason="notify-send y script /bin/sh (solo Linux)")
def test_el_aviso_del_escritorio_solo_como_servicio_y_por_panel_notify(datos, monkeypatch, tmp_path):
    """Como servicio (INVOCATION_ID) avisa con el programa de PANEL_NOTIFY; fuera de systemd, no. En los tests
    PANEL_NOTIFY es `true` (conftest): sus cierres sucios simulados no deben salir en el escritorio de verdad."""
    assert os.environ.get("PANEL_NOTIFY") == "true" and "INVOCATION_ID" not in os.environ
    registro = tmp_path / "avisos.txt"
    falso = tmp_path / "notify"
    falso.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" >> {registro}\n')
    falso.chmod(0o755)
    monkeypatch.setenv("PANEL_NOTIFY", str(falso))
    e = dc.ArranqueDenegado("prueba", "Mensaje de prueba", "Haz esto")

    dc._anotar_denegado(e)
    assert not registro.exists()  # sin systemd: la consola ya lo enseña

    monkeypatch.setenv("INVOCATION_ID", "abc")
    dc._anotar_denegado(e)
    lineas = registro.read_text().splitlines()
    assert lineas[:5] == ["-u", "critical", "-a", "Panel Maestro", "El panel no arranca"]
    assert "Mensaje de prueba" in lineas[5]


def test_seguir_sin_nada_pendiente(datos):
    assert dc.seguir()["ok"]


def test_cerrojo_ilegible_cuenta_como_cierre_sucio(datos):
    (datos["DATA_DIR"] / dc.CERROJO).write_text("{roto", encoding="utf-8")
    _con_wal_pendiente(datos["BRAIN_DB"])
    with pytest.raises(dc.ArranqueDenegado) as e:
        dc.al_arrancar()
    assert e.value.motivo == "cierre-sucio"


# ── Aviso en «Conexiones» ────────────────────────────────────


def test_copias_en_la_misma_unidad_que_unos_datos_compartidos(datos, monkeypatch):
    monkeypatch.setattr(dc, "compartida", lambda: True)
    dc.al_arrancar()
    item = dc.status_item()
    assert item["key"] == "datos" and item["state"] == "aviso" and "misma unidad" in item["detail"]


def test_datos_locales_sin_incidencias_no_dicen_nada(datos, monkeypatch):
    monkeypatch.setattr(dc, "compartida", lambda: False)
    dc.al_arrancar()
    assert dc.status_item() is None


@pytest.mark.skipif(sys.platform == "win32", reason="lee /proc/self/mounts (solo Linux)")
def test_tipo_de_sistema_de_archivos():
    assert dc.sistema_de_archivos(Path("/")) not in (None, "")


# ── scripts/datos_compartidos.py: mover y volver (fase 3) ─────


@pytest.fixture()
def cli(datos, monkeypatch, tmp_path):
    from scripts import datos_compartidos as sc

    monkeypatch.setattr(sc, "servicio_activo", lambda d: False)
    monkeypatch.setattr(sc, "_misma", lambda a, b: False)  # en tmp todo es la misma unidad
    (datos["DATA_DIR"] / "versions" / "una").mkdir(parents=True)
    (datos["DATA_DIR"] / "versions" / "una" / "1.md").write_text("vieja", encoding="utf-8")
    (datos["DATA_DIR"] / "notes" / ".a-medias.tmp").write_text("x", encoding="utf-8")
    datos["UPLOADS_DIR"].mkdir(parents=True)
    (datos["UPLOADS_DIR"] / "abc.png").write_bytes(b"\x89PNG" + bytes(range(256)))
    datos["CALENDAR_STATE"].parent.mkdir(parents=True)
    datos["CALENDAR_STATE"].write_text('{"ultima": 1}', encoding="utf-8")
    os.utime(datos["DATA_DIR"] / "notes" / "una.md", (1_700_000_000, 1_700_000_000))
    entorno = tmp_path / "panel.env"
    entorno.write_text(
        "# panel.env de prueba\nPANEL_ENV_FILE=/x/.env\n"
        + "".join(f"{k}={v}\n" for k, v in sc.desde_config().rutas().items())
        + "PANEL_BACKUPS_DIR=/y\n",
        encoding="utf-8",
    )
    return sc, entorno, tmp_path / "ntfs" / "panel-maestro"


def test_mover_simulacro_no_cambia_nada(datos, cli):
    sc, entorno, destino = cli
    destino.parent.mkdir()
    antes, env_antes, salida = _foto(datos["DATA_DIR"]), entorno.read_text(encoding="utf-8"), []
    assert sc.mover(destino, False, entorno, salida.append) == 0
    assert "Simulacro" in salida[-1]
    assert _foto(datos["DATA_DIR"]) == antes and entorno.read_text(encoding="utf-8") == env_antes
    assert not destino.exists() and not datos["BACKUPS_DIR"].exists()


def test_mover_copia_verificada_marca_y_entorno(datos, cli):
    sc, entorno, destino = cli
    destino.parent.mkdir()
    _con_wal_pendiente(datos["BRAIN_DB"])  # lo del WAL también tiene que llegar
    antes = _foto(datos["DATA_DIR"])
    assert sc.mover(destino, True, entorno, lambda *_: None) == 0
    nuevo = sc.en_carpeta(destino)
    # Archivos idénticos, con su fecha; ni temporales ni cerrojo
    assert (nuevo.notas / "una.md").read_bytes() == (datos["NOTES_DIR"] / "una.md").read_bytes()
    assert (nuevo.notas / "una.md").stat().st_mtime == 1_700_000_000
    assert (nuevo.data / "versions" / "una" / "1.md").read_text(encoding="utf-8") == "vieja"
    assert (nuevo.uploads / "abc.png").read_bytes() == (datos["UPLOADS_DIR"] / "abc.png").read_bytes()
    assert nuevo.calendario.read_text(encoding="utf-8") == '{"ultima": 1}'
    assert not (nuevo.notas / ".a-medias.tmp").exists()
    assert _filas(nuevo.brain_db) == 4 and _filas(nuevo.comidas_db) == 1
    # Copia previa completa fuera
    previa = sc.en_carpeta(next(datos["BACKUPS_DIR"].glob("pre-12-*")))
    assert _filas(previa.brain_db) == 4 and (previa.notas / "una.md").is_file()
    # panel.env con las rutas nuevas (lo demás igual) y el de antes guardado
    env = sc.leer_entorno(entorno)
    assert env["PANEL_DATA_DIR"] == str(nuevo.data) and env["PANEL_COMIDAS_DB"] == str(nuevo.comidas_db)
    assert env["PANEL_CALENDAR_STATE"] == str(nuevo.calendario) and env["PANEL_BACKUPS_DIR"] == "/y"
    assert entorno.read_text(encoding="utf-8").startswith("# panel.env de prueba")
    assert sc.leer_entorno(Path(f"{entorno}.antes-12"))["PANEL_DATA_DIR"] == str(datos["DATA_DIR"])
    # Lo viejo no se toca salvo la marca, y el panel ya no arranca con ello
    despues = _foto(datos["DATA_DIR"])
    assert set(despues) - set(antes) - {"brain.db-shm"} == {dc.MARCA_MOVIDO}  # el -shm lo crea SQLite al leer
    assert all(despues[k] == v for k, v in antes.items())
    with pytest.raises(dc.ArranqueDenegado):
        dc.al_arrancar()
    # Mover otra vez: no
    with pytest.raises(sc.Error):
        sc.mover(destino.parent / "otro", True, entorno, lambda *_: None)


def test_mover_se_niega_si_el_destino_tiene_algo_o_falta_la_particion(datos, cli):
    sc, entorno, destino = cli
    with pytest.raises(sc.Error, match="sin montar"):
        sc.mover(destino, False, entorno, lambda *_: None)
    destino.mkdir(parents=True)
    (destino / "algo").write_text("x", encoding="utf-8")
    with pytest.raises(sc.Error, match="no está vacía"):
        sc.mover(destino, False, entorno, lambda *_: None)


def test_mover_se_niega_con_el_panel_en_marcha(datos, cli):
    sc, entorno, destino = cli
    destino.parent.mkdir()
    dc.al_arrancar()  # este proceso tiene los datos abiertos
    yo = dc.identidad()
    vivo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        _cerrojo(datos, sistema=yo["sistema"], equipo=yo["equipo"], arranque=yo["arranque"], pid=vivo.pid)
        with pytest.raises(sc.Error, match="en marcha"):
            sc.mover(destino, True, entorno, lambda *_: None)
    finally:
        vivo.kill()
        vivo.wait()
    assert not destino.exists()


def test_mover_rechaza_nombres_que_windows_no_admite(datos, cli):
    sc, entorno, destino = cli
    destino.parent.mkdir()
    for malo in ("a:b.png", "con.txt", "nota.", 'co"mi.md'):
        assert not sc.nombre_valido_en_windows(Path("uploads") / malo)
    assert sc.nombre_valido_en_windows(Path("data/notes/ñandú-2.md"))
    try:
        (datos["UPLOADS_DIR"] / "a:b.png").write_bytes(b"x")
    except OSError:  # NTFS montado con windows_names (scripts/probar_ntfs.sh): el propio montaje ya no lo deja crear
        pytest.skip("el sistema de archivos ya rechaza el nombre (windows_names)")
    with pytest.raises(sc.Error, match="Windows no admite"):
        sc.mover(destino, True, entorno, lambda *_: None)


def test_volver_trae_lo_escrito_despues(datos, cli, monkeypatch):
    sc, entorno, destino = cli
    destino.parent.mkdir()
    viejos = sc.desde_config()
    sc.mover(destino, True, entorno, lambda *_: None)
    nuevo = sc.en_carpeta(destino)
    # El panel pasa a usar la partición y se escribe algo
    for k, v in {"DATA_DIR": nuevo.data, "NOTES_DIR": nuevo.notas, "BRAIN_DB": nuevo.brain_db,
                 "TRASH_DIR": nuevo.data / "trash", "COMIDAS_DB": nuevo.comidas_db, "UPLOADS_DIR": nuevo.uploads,
                 "CALENDAR_STATE": nuevo.calendario}.items():  # fmt: skip
        monkeypatch.setattr(config, k, v)
    (nuevo.notas / "escrita-en-windows.md").write_text("nueva", encoding="utf-8")
    salida = []
    assert sc.volver(False, False, entorno, salida.append) == 0 and "Simulacro" in salida[-1]
    assert sc.volver(True, False, entorno, lambda *_: None) == 0
    assert (viejos.notas / "escrita-en-windows.md").read_text(encoding="utf-8") == "nueva"
    assert not (viejos.data / dc.MARCA_MOVIDO).exists()
    assert _filas(viejos.brain_db) == 1
    assert sc.leer_entorno(entorno)["PANEL_DATA_DIR"] == str(viejos.data)
    assert not Path(f"{entorno}.antes-12").exists()
    aparte = sc.en_carpeta(next(datos["BACKUPS_DIR"].glob("pre-volver-*")))
    assert (aparte.data / dc.MARCA_MOVIDO).is_file() and (aparte.notas / "una.md").is_file()


def test_volver_sin_copiar(datos, cli):
    sc, entorno, destino = cli
    destino.parent.mkdir()
    sc.mover(destino, True, entorno, lambda *_: None)
    assert sc.volver(True, True, entorno, lambda *_: None) == 0
    assert not (datos["DATA_DIR"] / dc.MARCA_MOVIDO).exists()
    assert sc.leer_entorno(entorno)["PANEL_DATA_DIR"] == str(datos["DATA_DIR"])
    dc.al_arrancar()


def test_estado_y_seguir_por_la_linea_de_ordenes(datos, cli, capsys):
    sc, _entorno, _destino = cli
    assert sc.estado() == 0
    out = capsys.readouterr().out
    assert "integrity_check ok" in out and "notas .md=1" in out
    _windows_abierto(datos)
    _con_wal_pendiente(datos["BRAIN_DB"])
    assert sc.main(["--entorno", "ninguno", "seguir"]) == 0
    assert "están bien" in capsys.readouterr().out
