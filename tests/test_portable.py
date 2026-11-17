"""P-12: lo que hace falta para que el mismo código y los mismos datos valgan en Linux y en Windows."""

import os

import pytest
from fastapi import HTTPException

from core import config, files


def test_atomic_write_usa_saltos_de_linea_unix(tmp_path):
    p = tmp_path / "n.md"
    files.atomic_write(p, "a\nb\n")
    assert p.read_bytes() == b"a\nb\n"
    files.atomic_write(p, "a\r\nb\n", newline="")  # tal cual
    assert p.read_bytes() == b"a\r\nb\n"


def test_atomic_write_sigue_si_no_hay_permisos_unix(tmp_path, monkeypatch):
    def chmod(*_a, **_k):
        raise PermissionError("NTFS: operación no permitida")

    monkeypatch.setattr(files.os, "chmod", chmod)
    p = tmp_path / "n.md"
    files.atomic_write(p, "hola")
    assert p.read_text(encoding="utf-8") == "hola"
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]


def test_replace_reintenta_en_windows_si_el_archivo_esta_en_uso(tmp_path, monkeypatch):
    real, fallos = os.replace, []

    def replace(a, b):
        if len(fallos) < 3:
            fallos.append(1)
            raise PermissionError("en uso")
        real(a, b)

    monkeypatch.setattr(files.sys, "platform", "win32")
    monkeypatch.setattr(files.os, "replace", replace)
    monkeypatch.setattr(files.time, "sleep", lambda s: None)
    p = tmp_path / "n.md"
    files.atomic_write(p, "x")
    assert p.read_text(encoding="utf-8") == "x" and len(fallos) == 3


def test_replace_se_rinde_y_no_deja_temporales(tmp_path, monkeypatch):
    def replace(a, b):
        raise PermissionError("en uso siempre")

    monkeypatch.setattr(files.sys, "platform", "win32")
    monkeypatch.setattr(files.os, "replace", replace)
    monkeypatch.setattr(files.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        files.atomic_write(tmp_path / "n.md", "x")
    assert os.listdir(tmp_path) == []


def test_nombres_de_dispositivo_de_windows():
    from app.notes_core import note_path, note_slug

    for malo in ("con", "NUL", "com1", "lpt9", "aux"):
        with pytest.raises(HTTPException) as e:
            note_path(malo)
        assert e.value.status_code == 400
    assert note_slug("Con") == "con-nota"
    assert note_slug("Consola") == "consola"
    assert note_path("consola").endswith("consola.md")


def test_nota_que_solo_cambia_en_mayusculas(client):
    from app.notes_core import note_path

    assert (
        client.post(
            "/api/notes/Mayus-Prueba", json={"title": "Mayus", "content": "uno", "category": "Pruebas"}
        ).status_code
        == 200
    )
    with pytest.raises(HTTPException) as e:
        note_path("mayus-prueba")
    assert e.value.status_code == 409 and "Mayus-Prueba" in e.value.detail
    r = client.post("/api/notes/mayus-prueba", json={"title": "mayus", "content": "dos", "category": "Pruebas"})
    assert r.status_code == 409
    assert "uno" in (config.NOTES_DIR / "Mayus-Prueba.md").read_text(encoding="utf-8")
    assert "mayus-prueba.md" not in os.listdir(config.NOTES_DIR)  # exists() no distingue mayúsculas en Windows
    assert client.delete("/api/notes/Mayus-Prueba").status_code == 200


def test_en_windows_no_hay_dotfiles_ni_publicar(monkeypatch):
    from app import dotfiles, proyecto

    monkeypatch.setattr(config, "IS_WINDOWS", True)
    assert dotfiles.is_available() is False
    assert proyecto.is_available() is False


def test_plataforma_por_defecto():
    assert config.PLATFORM in ("linux", "windows")
    assert (config.PLATFORM == "windows") == config.IS_WINDOWS


def test_uvloop_no_se_instala_en_windows():
    lock = (config.PROJECT_ROOT / "requirements.lock").read_text(encoding="utf-8")
    linea = next(x for x in lock.splitlines() if x.startswith("uvloop=="))
    assert 'sys_platform != "win32"' in linea
