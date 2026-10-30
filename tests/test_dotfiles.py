"""Dotfiles: traer ~ al repo sin deshacer su limpieza y subirlo a GitHub (aquí, un repo bare local)."""
import hashlib
import os
import stat
import subprocess
import time

import pytest

from app import dotfiles
from core import config

ORIGINAL = "# cabecera del autor\nuno\ndos\ntres\ncuatro\ncinco\n"
LIMPIO = "uno\ndos\ntres\ncuatro\ncinco\n"
B = "b1\nb2\nb3\nlínea cuatro de b\nlínea cinco de b\nlínea seis de b\nlínea siete de b\n"
CHECK = """#!/usr/bin/env bash
# Mismo formato que el check-secrets.sh real
out=$(grep -rIn 'ghp_' stow seeds 2>/dev/null || true)
if [[ -n $out ]]; then
    echo "$out" | sed 's/^/  ! /'
    echo "Posibles secretos encontrados."
    exit 1
fi
echo "Todo limpio."
"""


def git(cwd, *args):
    run = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return run.stdout


@pytest.fixture()
def dot(tmp_path, monkeypatch):
    """~ con archivos reales, repo con esos archivos limpios y renombrados, y un remoto."""
    home, repo, remote = tmp_path / "home", tmp_path / "dotfiles", tmp_path / "remoto.git"
    conf = home / ".config" / "app"
    conf.mkdir(parents=True)
    (conf / "a.conf").write_text(ORIGINAL)
    (conf / "Marca_b.conf").write_text("# cabecera del autor\n" + B)
    (conf / "viejo.conf").write_text("sigue aquí\n")
    (home / ".config" / "app" / "enlace").symlink_to(conf / "a.conf")  # absoluto en ~, relativo en el repo
    (home / ".config" / "app" / "copia.conf.bak-2026").write_text("copia\n")

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    pkg = repo / "stow" / "app" / ".config" / "app"
    pkg.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.name", "Pruebas")
    git(repo, "config", "user.email", "pruebas@example.com")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "check-secrets.sh").write_text(CHECK)
    (repo / ".gitignore").write_text("*.token\n")
    (pkg / "a.conf").write_text(ORIGINAL)
    (pkg / "Marca_b.conf").write_text("# cabecera del autor\n" + B)
    (pkg / "viejo.conf").write_text("sigue aquí\n")
    (pkg / "enlace").symlink_to("a.conf")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "copia tal cual de ~")
    base = git(repo, "rev-parse", "HEAD").strip()
    (pkg / "a.conf").write_text(LIMPIO)
    git(repo, "mv", str(pkg / "Marca_b.conf"), str(pkg / "b.conf"))
    (pkg / "b.conf").write_text(B)
    (repo / "stow" / "app" / "README.md").write_text("# Componente\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "sin autor original")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "-u", "origin", "main")

    monkeypatch.setattr(config, "DOTFILES_DIR", repo)
    monkeypatch.setattr(config, "DOTFILES_HOME", home)
    monkeypatch.setattr(config, "DOTFILES_BASE", base)
    monkeypatch.setattr(dotfiles, "BASE_DIR", tmp_path / "base")

    class Dot:
        pass
    d = Dot()
    d.home, d.repo, d.remote, d.conf, d.pkg = home, repo, remote, conf, pkg
    d.remote_file = lambda name: git(remote, "show", f"main:stow/app/.config/app/{name}")
    d.log = lambda: git(remote, "log", "--format=%s").splitlines()
    return d


def huella(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[p] = os.readlink(p) if os.path.islink(p) else hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


def nuevo(path, text):
    """Un archivo creado después del último commit (el commit es de este mismo segundo)."""
    path.write_text(text)
    later = time.time() + 5
    os.utime(path, (later, later))


def test_la_limpieza_no_es_un_cambio(dot, client):
    st = client.get("/api/dotfiles").json()
    assert st["available"] and st["changes"] == [] and st["ahead"] == 0
    assert st["web_url"] is None  # remoto local
    assert [c["name"] for c in st["components"]] == ["app"]


def test_sin_repo_lo_dice_sin_fallar(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOTFILES_DIR", tmp_path / "no-existe")
    assert client.get("/api/dotfiles").json()["available"] is False


def test_un_cambio_en_home_sube_sin_deshacer_la_limpieza(dot, client):
    (dot.conf / "a.conf").write_text(ORIGINAL.replace("cuatro", "cuatro nuevo"))
    st = client.get("/api/dotfiles").json()
    assert [(c["path"], c["kind"], c["component"]) for c in st["changes"]] == [("stow/app/.config/app/a.conf", "modificado", "app")]

    r = client.post("/api/dotfiles/push")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "subido" and r.json()["files"] == 1 and r.json()["commit"]
    assert dot.remote_file("a.conf") == LIMPIO.replace("cuatro", "cuatro nuevo")  # sin la cabecera
    st = client.get("/api/dotfiles").json()
    assert st["changes"] == [] and st["ahead"] == 0


def test_un_archivo_renombrado_en_el_repo_se_sigue_por_su_nombre_en_home(dot, client):
    (dot.conf / "Marca_b.conf").write_text("# cabecera del autor\n" + B.replace("b2", "b2 cambiado"))
    assert client.post("/api/dotfiles/push").status_code == 200
    assert dot.remote_file("b.conf") == B.replace("b2", "b2 cambiado")
    assert "Marca_b.conf" not in git(dot.remote, "ls-tree", "-r", "--name-only", "main")


def test_nunca_toca_home(dot, client):
    (dot.conf / "a.conf").write_text(ORIGINAL + "seis\n")
    nuevo(dot.conf / "otro.conf", "otro\n")
    antes = huella(dot.home)
    assert client.post("/api/dotfiles/push").status_code == 200
    assert huella(dot.home) == antes


def test_el_mismo_renglon_se_puede_cambiar_varias_veces(dot, client):
    """Tras subir, el antepasado es lo subido: si no, la segunda vez chocaría consigo mismo."""
    (dot.conf / "a.conf").write_text(ORIGINAL.replace("dos", "dos v1"))
    client.post("/api/dotfiles/push")
    (dot.conf / "a.conf").write_text(ORIGINAL.replace("dos", "dos v2"))
    r = client.post("/api/dotfiles/push").json()
    assert r["status"] == "subido" and r["conflicts"] == []
    assert dot.remote_file("a.conf") == LIMPIO.replace("dos", "dos v2")


def test_archivos_nuevos_solo_los_recientes_y_de_configuracion(dot, client):
    nuevo(dot.conf / "reciente.conf", "nuevo\n")
    nuevo(dot.conf / "copia2.conf.bak-2026", "copia\n")
    nuevo(dot.conf / "clave.token", "secreto\n")
    nuevo(dot.conf / "imagen.bin", "x\0y")
    (dot.conf / "antiguo.conf").write_text("anterior al último commit\n")
    os.utime(dot.conf / "antiguo.conf", (1000, 1000))
    (dot.conf / "enlazado.conf").symlink_to("a.conf")
    changes = client.get("/api/dotfiles").json()["changes"]
    assert [(c["path"], c["kind"]) for c in changes] == [("stow/app/.config/app/reciente.conf", "nuevo")]
    client.post("/api/dotfiles/push")
    assert dot.remote_file("reciente.conf") == "nuevo\n"


def test_cuenta_como_nuevo_desde_la_copia_base_y_luego_desde_la_ultima_subida(dot, client):
    """Un script creado tras la copia pero antes del último commit no se pierde; lo ya visto no vuelve a salir."""
    nuevo(dot.conf / "script.sh", "#!/bin/sh\n")
    later = str(int(time.time()) + 60)
    run = subprocess.run(["git", "-C", str(dot.repo), "commit", "-q", "--allow-empty", "-m", "commit a mano"],
                         env={**os.environ, "GIT_COMMITTER_DATE": f"{later} +0000"}, capture_output=True)
    assert run.returncode == 0
    assert [c["kind"] for c in client.get("/api/dotfiles").json()["changes"]] == ["nuevo"]
    client.post("/api/dotfiles/push")
    assert dot.remote_file("script.sh") == "#!/bin/sh\n"

    (dot.conf / "ya-existia.conf").write_text("de antes\n")
    os.utime(dot.conf / "ya-existia.conf", (1000, 1000))
    assert client.get("/api/dotfiles").json()["changes"] == []


def test_lo_que_falta_en_home_se_avisa_y_se_conserva(dot, client):
    (dot.conf / "viejo.conf").unlink()
    (dot.conf / "a.conf").write_text(ORIGINAL + "seis\n")
    st = client.get("/api/dotfiles").json()
    assert st["missing"] == ["stow/app/.config/app/viejo.conf"]
    assert [c["path"] for c in st["changes"]] == ["stow/app/.config/app/a.conf"]
    client.post("/api/dotfiles/push")
    assert dot.remote_file("viejo.conf") == "sigue aquí\n"


def test_enlace_cambiado(dot, client):
    enlace = dot.conf / "enlace"
    assert client.get("/api/dotfiles").json()["changes"] == []  # absoluto en ~ = relativo en el repo
    enlace.unlink()
    enlace.symlink_to(dot.conf / "viejo.conf")
    assert client.get("/api/dotfiles").json()["changes"][0]["kind"] == "enlace"
    client.post("/api/dotfiles/push")
    assert os.readlink(dot.pkg / "enlace") == "viejo.conf"
    assert client.get("/api/dotfiles").json()["changes"] == []


def test_enlace_absoluto_fuera_de_home_no_es_un_cambio(dot, client):
    (dot.conf / "tema").symlink_to("/usr/share/themes/tema/gtk.css")
    (dot.pkg / "tema").symlink_to("/usr/share/themes/tema/gtk.css")
    git(dot.repo, "add", "-A")
    git(dot.repo, "commit", "-qm", "tema")
    assert client.get("/api/dotfiles").json()["changes"] == []


def test_un_secreto_para_la_subida_y_el_repo_queda_como_estaba(dot, client):
    (dot.conf / "a.conf").write_text(ORIGINAL + "token = ghp_" + "a" * 36 + "\n")
    nuevo(dot.conf / "reciente.conf", "nuevo\n")
    r = client.post("/api/dotfiles/push")
    assert r.status_code == 422
    assert "a.conf:6" in r.json()["detail"] and "No se ha subido nada" in r.json()["detail"]
    assert "ghp_" not in r.json()["detail"]  # dice dónde, nunca el secreto
    assert git(dot.repo, "status", "--porcelain") == ""
    assert (dot.pkg / "a.conf").read_text() == LIMPIO
    assert len(dot.log()) == 2
    # al quitarlo, sube sin arrastrar nada de lo anterior
    (dot.conf / "a.conf").write_text(ORIGINAL + "seis\n")
    assert client.post("/api/dotfiles/push").status_code == 200
    assert dot.remote_file("a.conf") == LIMPIO + "seis\n"


def test_sin_comprobador_de_secretos_no_se_sube(dot, client):
    (dot.repo / "scripts" / "check-secrets.sh").unlink()
    git(dot.repo, "commit", "-qam", "sin comprobador")
    (dot.conf / "a.conf").write_text(ORIGINAL + "seis\n")
    r = client.post("/api/dotfiles/push")
    assert r.status_code == 422 and "check-secrets" in r.json()["detail"]
    assert len(dot.log()) == 2


def test_un_choque_se_queda_fuera_y_el_resto_sube(dot, client):
    (dot.pkg / "a.conf").write_text(LIMPIO.replace("tres", "tres repo"))
    git(dot.repo, "commit", "-qam", "retoque en el repo")
    (dot.conf / "a.conf").write_text(ORIGINAL.replace("tres", "tres home"))
    (dot.conf / "Marca_b.conf").write_text("# cabecera del autor\n" + B + "b8\n")
    kinds = {c["path"].rsplit("/", 1)[1]: c["kind"] for c in client.get("/api/dotfiles").json()["changes"]}
    assert kinds == {"a.conf": "conflicto", "b.conf": "modificado"}
    r = client.post("/api/dotfiles/push").json()
    assert r["conflicts"] == ["stow/app/.config/app/a.conf"] and r["files"] == 1
    assert dot.remote_file("a.conf") == LIMPIO.replace("tres", "tres repo")
    assert dot.remote_file("b.conf") == B + "b8\n"
    assert "<<<<<<<" not in (dot.pkg / "a.conf").read_text()


def test_si_github_va_por_delante_se_rebasa(dot, client, tmp_path):
    otro = tmp_path / "otro-equipo"
    git(tmp_path, "clone", "-q", str(dot.remote), str(otro))
    git(otro, "config", "user.name", "Otro")
    git(otro, "config", "user.email", "otro@example.com")
    (otro / "NOTAS.txt").write_text("desde otro equipo\n")
    git(otro, "add", "-A")
    git(otro, "commit", "-qm", "otro equipo")
    git(otro, "push", "-q")
    (dot.conf / "a.conf").write_text(ORIGINAL + "seis\n")
    assert client.post("/api/dotfiles/push").status_code == 200
    assert dot.log()[1] == "otro equipo"  # no se pisa: lo nuestro va encima
    assert git(dot.remote, "show", "main:NOTAS.txt") == "desde otro equipo\n"


def test_si_github_choca_no_fuerza_y_lo_deja_en_local(dot, client, tmp_path):
    otro = tmp_path / "otro-equipo"
    git(tmp_path, "clone", "-q", str(dot.remote), str(otro))
    git(otro, "config", "user.name", "Otro")
    git(otro, "config", "user.email", "otro@example.com")
    (otro / "stow/app/.config/app/a.conf").write_text(LIMPIO.replace("cuatro", "cuatro otro"))
    git(otro, "commit", "-qam", "otro equipo")
    git(otro, "push", "-q")
    remoto = git(dot.remote, "rev-parse", "main")
    (dot.conf / "a.conf").write_text(ORIGINAL.replace("cuatro", "cuatro aquí"))
    r = client.post("/api/dotfiles/push")
    assert r.status_code == 409 and "chocan" in r.json()["detail"]
    assert git(dot.remote, "rev-parse", "main") == remoto
    assert git(dot.repo, "status", "--porcelain") == ""
    assert not (dot.repo / ".git" / "rebase-merge").exists()
    assert git(dot.repo, "log", "-1", "--format=%s").startswith("Actualiza la configuración")


def test_sin_conexion_queda_guardado_y_se_reintenta(dot, client):
    (dot.conf / "a.conf").write_text(ORIGINAL + "seis\n")
    git(dot.repo, "remote", "set-url", "origin", "/no/existe.git")
    r = client.post("/api/dotfiles/push")
    assert r.status_code == 502 and "vuelve a pulsar" in r.json()["detail"] and "fatal" not in r.json()["detail"]
    st = client.get("/api/dotfiles").json()
    assert st["ahead"] == 1 and st["changes"] == []
    git(dot.repo, "remote", "set-url", "origin", str(dot.remote))
    assert client.post("/api/dotfiles/push").json()["status"] == "subido"
    assert dot.remote_file("a.conf") == LIMPIO + "seis\n"


def test_sube_commits_pendientes_aunque_no_haya_cambios(dot, client):
    (dot.repo / "NOTAS.txt").write_text("a mano\n")
    git(dot.repo, "add", "-A")
    git(dot.repo, "commit", "-qm", "commit a mano")
    assert client.get("/api/dotfiles").json()["ahead"] == 1
    r = client.post("/api/dotfiles/push").json()
    assert r["status"] == "subido" and r["commit"] is None
    assert dot.log()[0] == "commit a mano"


def test_al_dia_no_hace_nada(dot, client):
    assert client.post("/api/dotfiles/push").json()["status"] == "al-dia"
    assert len(dot.log()) == 2


def test_cambios_hechos_en_el_propio_repo_tambien_cuentan(dot, client):
    (dot.repo / "install.sh").write_text("#!/bin/sh\n")
    assert [(c["path"], c["kind"], c["component"]) for c in client.get("/api/dotfiles").json()["changes"]] == [("install.sh", "repo", "repositorio")]
    client.post("/api/dotfiles/push")
    assert git(dot.remote, "show", "main:install.sh") == "#!/bin/sh\n"


def test_conserva_el_permiso_de_ejecucion(dot, client):
    script = dot.conf / "a.conf"
    script.write_text(ORIGINAL + "seis\n")
    script.chmod(0o755)
    client.post("/api/dotfiles/push")
    assert (dot.pkg / "a.conf").stat().st_mode & stat.S_IXUSR


def test_sin_commit_base_no_deshace_la_limpieza(dot, client, monkeypatch):
    monkeypatch.setattr(config, "DOTFILES_BASE", "0" * 40)
    assert client.get("/api/dotfiles").status_code == 409
    assert client.post("/api/dotfiles/push").status_code == 409
    assert len(dot.log()) == 2


def test_diff_solo_de_lo_que_ha_cambiado(dot, client):
    (dot.conf / "a.conf").write_text(ORIGINAL.replace("dos", "dos cambiado"))
    r = client.get("/api/dotfiles/diff", params={"path": "stow/app/.config/app/a.conf"}).json()
    assert "-dos" in r["lines"] and "+dos cambiado" in r["lines"]
    assert not any("cabecera" in line for line in r["lines"])  # es lo que subirá, no ~ contra el repo
    assert client.get("/api/dotfiles/diff", params={"path": "stow/app/.config/app/viejo.conf"}).status_code == 404
    assert client.get("/api/dotfiles/diff", params={"path": "../../../etc/passwd"}).status_code == 404


def test_las_rutas_piden_sesion(dot):
    from fastapi.testclient import TestClient

    import main
    anon = TestClient(main.app)
    assert anon.get("/api/dotfiles").status_code == 401
    assert anon.post("/api/dotfiles/push").status_code == 401
