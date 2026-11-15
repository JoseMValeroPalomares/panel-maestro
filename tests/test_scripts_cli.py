"""Scripts de línea de órdenes que tocan credenciales o el esquema (T-1): set_password, desktop_token y migrate.
Todo contra un .env y unas BDs temporales: nunca los reales."""

import sqlite3
import stat
import sys
from contextlib import closing

import pytest

from core import config, envfile
from core.security import verify_api_token, verify_password
from scripts import desktop_token, migrate, set_password


def _env(path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k] = v.strip().strip("'\"")
    return out


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# comentario que debe quedarse\nOTRA=1\n")
    monkeypatch.setattr(set_password, "ENV_PATH", path)
    monkeypatch.setattr(desktop_token, "ENV_PATH", path)
    monkeypatch.setattr(set_password, "update_env", lambda values: envfile.update_env(values, path))
    monkeypatch.setattr(desktop_token, "update_env", lambda values: envfile.update_env(values, path))
    return path


def _run(module, monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", [module.__name__, *args])
    return module.main()


# ── set_password ───────────────────────────────────────────────────────────


def test_generate_guarda_hash_y_secreto_sin_tocar_lo_demas(env_file, monkeypatch, capsys):
    assert _run(set_password, monkeypatch, "--generate", "--api-token") == 0
    out = capsys.readouterr().out
    password = out.split("no se vuelve a mostrar): ")[1].split()[0]
    token = out.split("Bearer ...'): ")[1].split()[0]
    env = _env(env_file)
    assert verify_password(password, env["PANEL_PASSWORD_HASH"])
    assert verify_api_token(token, env["PANEL_API_TOKEN_HASH"])
    assert len(env["PANEL_SESSION_SECRET"]) >= 32
    assert env["OTRA"] == "1" and "# comentario que debe quedarse" in env_file.read_text()
    assert password not in env_file.read_text() and token not in env_file.read_text()  # solo los hashes


def test_cambiar_la_contrasena_cambia_el_secreto_de_sesion(env_file, monkeypatch, capsys):
    _run(set_password, monkeypatch, "--generate")
    antes = _env(env_file)["PANEL_SESSION_SECRET"]
    _run(set_password, monkeypatch, "--generate")
    assert _env(env_file)["PANEL_SESSION_SECRET"] != antes  # todas las sesiones abiertas dejan de valer


def test_solo_token_no_toca_contrasena_ni_sesiones(env_file, monkeypatch, capsys):
    _run(set_password, monkeypatch, "--generate")
    antes = _env(env_file)
    assert _run(set_password, monkeypatch, "--solo-token") == 0
    despues = _env(env_file)
    assert despues["PANEL_PASSWORD_HASH"] == antes["PANEL_PASSWORD_HASH"]
    assert despues["PANEL_SESSION_SECRET"] == antes["PANEL_SESSION_SECRET"]
    token = capsys.readouterr().out.rsplit(": ", 1)[1].strip()
    assert verify_api_token(token, despues["PANEL_API_TOKEN_HASH"])


@pytest.mark.parametrize(
    ("respuestas", "codigo"),
    [(["corta", "corta"], 1), (["una-larga-1", "otra-larga-2"], 1), (["una-larga-1", "una-larga-1"], 0)],
)
def test_contrasena_por_teclado(env_file, monkeypatch, capsys, respuestas, codigo):
    it = iter(respuestas)
    monkeypatch.setattr(set_password.getpass, "getpass", lambda prompt="": next(it))
    assert _run(set_password, monkeypatch) == codigo
    env = _env(env_file)
    if codigo:
        assert "PANEL_PASSWORD_HASH" not in env  # un error no deja nada a medias
    else:
        assert verify_password("una-larga-1", env["PANEL_PASSWORD_HASH"])


# ── desktop_token ──────────────────────────────────────────────────────────


def test_desktop_token_archivo_600_y_copia_del_env(env_file, tmp_path, monkeypatch, capsys):
    conf = tmp_path / "conf" / "panel-maestro"
    monkeypatch.setattr(desktop_token, "CONF", conf)
    assert _run(desktop_token, monkeypatch, "--url", "http://127.0.0.1:8811/") == 0
    token = (conf / "token").read_text().strip()
    assert stat.S_IMODE((conf / "token").stat().st_mode) == 0o600
    assert stat.S_IMODE(conf.stat().st_mode) == 0o700
    assert (conf / "url").read_text() == "http://127.0.0.1:8811\n"
    assert verify_api_token(token, _env(env_file)["PANEL_DESKTOP_TOKEN_HASH"])
    copias = list(tmp_path.glob(".env.bak-*"))
    assert len(copias) == 1 and "PANEL_DESKTOP_TOKEN_HASH" not in copias[0].read_text()


def test_desktop_token_nuevo_invalida_el_anterior(env_file, tmp_path, monkeypatch, capsys):
    conf = tmp_path / "conf"
    monkeypatch.setattr(desktop_token, "CONF", conf)
    _run(desktop_token, monkeypatch)
    viejo = (conf / "token").read_text().strip()
    _run(desktop_token, monkeypatch)
    nuevo = (conf / "token").read_text().strip()
    assert viejo != nuevo and not (conf / "url").exists()
    h = _env(env_file)["PANEL_DESKTOP_TOKEN_HASH"]
    assert verify_api_token(nuevo, h) and not verify_api_token(viejo, h)


# ── migrate ────────────────────────────────────────────────────────────────


@pytest.fixture()
def dbs(client, tmp_path, monkeypatch):
    """Copias de las BDs de los tests (ya migradas al arrancar la app) para revertir y volver a aplicar."""
    paths = {}
    for name, src in (("cerebro", config.BRAIN_DB), ("comidas", config.COMIDAS_DB)):
        dst = tmp_path / f"{name}.db"
        with closing(sqlite3.connect(src)) as a, closing(sqlite3.connect(dst)) as b:
            a.backup(b)
        paths[name] = dst
    monkeypatch.setattr(config, "BRAIN_DB", paths["cerebro"])
    monkeypatch.setattr(config, "COMIDAS_DB", paths["comidas"])
    return paths


def _applied(path) -> set[int]:
    with closing(sqlite3.connect(path)) as c:
        return {r[0] for r in c.execute("SELECT version FROM schema_migrations")}


def test_migrate_status_up_down_up(dbs, monkeypatch, capsys):
    from app.migrations import MIGRATIONS

    todas = {m.version for m in MIGRATIONS}
    assert _applied(dbs["cerebro"]) == todas
    _run(migrate, monkeypatch, "status")
    out = capsys.readouterr().out
    assert f"cerebro {max(todas):>3} ✓" in out and "comidas" in out

    ultima = max(todas)
    _run(migrate, monkeypatch, "down", str(ultima - 1), "--db", "cerebro")
    assert "revertidas: [%d]" % ultima in capsys.readouterr().out
    assert _applied(dbs["cerebro"]) == todas - {ultima}
    assert _applied(dbs["comidas"])  # --db cerebro no toca la otra

    _run(migrate, monkeypatch, "up", "--db", "cerebro")
    assert "aplicadas: [%d]" % ultima in capsys.readouterr().out
    assert _applied(dbs["cerebro"]) == todas
    with closing(sqlite3.connect(dbs["cerebro"])) as c:
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_migrate_up_sin_pendientes(dbs, monkeypatch, capsys):
    _run(migrate, monkeypatch, "up")
    out = capsys.readouterr().out
    assert out.count("aplicadas: ninguna") == 2
