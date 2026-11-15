"""Abridor de panelmaestro:// (scripts/desktop/abrir/abrir.py): solo ids, la ruta relativa del panel se valida
contra las raíces de abrir.conf (600) y nada fuera de ellas se abre."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("abrir", ROOT / "scripts/desktop/abrir/abrir.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


@pytest.fixture()
def raiz(tmp_path, monkeypatch):
    uni = tmp_path / "Uja"
    (uni / "Tercero" / "Grafica").mkdir(parents=True)
    (uni / "Tercero" / "Grafica" / "tema1.pdf").write_bytes(b"%PDF")
    fuera = tmp_path / "secreto"
    fuera.mkdir()
    (uni / "Tercero" / "escape").symlink_to(fuera)
    conf = tmp_path / "abrir.conf"
    conf.write_text(f"[raices]\nuniversidad = {uni}\n")
    conf.chmod(0o600)
    monkeypatch.setattr(ab, "CONF", conf)
    return uni, conf


def _panel(monkeypatch, respuesta):
    calls = []
    monkeypatch.setattr(ab.pc, "request", lambda m, p, b=None: calls.append(p) or respuesta)
    return calls


def test_abre_la_ruta_valida(raiz, monkeypatch):
    uni, _ = raiz
    calls = _panel(monkeypatch, {"raiz": "universidad", "ruta": "Tercero/Grafica/tema1.pdf"})
    assert ab.destino("panelmaestro://abrir/tema/12") == uni / "Tercero" / "Grafica" / "tema1.pdf"
    assert calls == ["/api/abrir/tema/12"]


@pytest.mark.parametrize(
    "url",
    [
        "panelmaestro://abrir/tema/0",
        "panelmaestro://abrir/tema/1/../2",
        "panelmaestro://abrir/carpeta/1",
        "panelmaestro://abrir/tema/1?ruta=/etc",
        "panelmaestro://abrir/tema//etc/passwd",
        "file:///etc/passwd",
        "panelmaestro://abrir/tema/12a",
    ],
)
def test_url_no_valida_no_pregunta_ni_abre(raiz, monkeypatch, url):
    calls = _panel(monkeypatch, {"raiz": "universidad", "ruta": "Tercero"})
    with pytest.raises(ab.Rechazo):
        ab.destino(url)
    assert calls == []


@pytest.mark.parametrize(
    "resp",
    [
        {"raiz": "universidad", "ruta": "../secreto"},
        {"raiz": "universidad", "ruta": "/etc"},
        {"raiz": "universidad", "ruta": "Tercero/escape"},
        {"raiz": "universidad", "ruta": "Tercero/../../secreto"},
        {"raiz": "proyectos", "ruta": "x"},
        {"raiz": "universidad", "ruta": "~/.ssh"},
        {"raiz": "universidad", "ruta": "Tercero/no-existe"},
        {"raiz": "universidad", "ruta": None},
    ],
)
def test_ruta_fuera_de_la_raiz_no_se_abre(raiz, monkeypatch, resp):
    """Aunque el panel devolviera algo malicioso, el abridor no sale de sus raíces."""
    _panel(monkeypatch, resp)
    with pytest.raises(ab.Rechazo):
        ab.destino("panelmaestro://abrir/tema/5")


def test_config_con_permisos_abiertos_se_rechaza(raiz, monkeypatch):
    _, conf = raiz
    conf.chmod(0o644)
    _panel(monkeypatch, {"raiz": "universidad", "ruta": "Tercero"})
    with pytest.raises(ab.Rechazo, match="600"):
        ab.destino("panelmaestro://abrir/asignatura/1")


def test_main_dry_run_y_sin_abrir(raiz, monkeypatch, capsys, tmp_path):
    uni, _ = raiz
    _panel(monkeypatch, {"raiz": "universidad", "ruta": "Tercero/Grafica"})
    log = tmp_path / "abierto"
    opener = tmp_path / "opener"
    opener.write_text(f'#!/bin/sh\necho "$1" > {log}\n')
    opener.chmod(0o755)
    monkeypatch.setenv("PANEL_OPENER", str(opener))
    monkeypatch.setenv("PANEL_NOTIFY", "true")
    assert ab.main(["abrir.py", "--dry-run", "panelmaestro://abrir/asignatura/3"]) == 0
    assert capsys.readouterr().out.strip() == str(uni / "Tercero" / "Grafica")
    assert ab.main(["abrir.py", "panelmaestro://abrir/nada/3"]) == 1 and not log.exists()
    assert ab.main(["abrir.py", "panelmaestro://abrir/asignatura/3"]) == 0
    import time

    for _ in range(50):
        if log.exists():
            break
        time.sleep(0.05)
    assert log.read_text().strip() == str(uni / "Tercero" / "Grafica")
