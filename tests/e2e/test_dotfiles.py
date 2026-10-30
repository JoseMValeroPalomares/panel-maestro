"""Copias: ver qué ha cambiado en los dotfiles y subirlo a GitHub con un botón."""
import subprocess


def _remote_file(env):
    return subprocess.run(["git", "-C", str(env["remote"]), "show", "main:stow/app/.config/app/a.conf"],
                          capture_output=True, text=True).stdout


def test_ver_y_subir(page, server, dotfiles_env):
    env = dotfiles_env
    env["live"].write_text("uno\ndos cambiado\ntres\n")
    page.goto(f"{server}/backups")
    page.locator("#dotfilesText", has_text="1 archivo cambiado sin subir").wait_for()
    assert page.get_attribute("#dotfilesPanel", "data-health") == "antigua"

    page.click("#dotfilesPanel [data-view]")
    page.locator("#repoModal[open]").wait_for()
    row = page.locator(".repo-file", has_text="~/.config/app/a.conf")
    row.locator("summary").click()
    row.locator(".repo-diff .add", has_text="+dos cambiado").wait_for()
    assert row.locator(".repo-diff .del").inner_text() == "-dos"

    page.click("#repoTabs [data-pane=contenido]")
    page.locator("#repoContents .repo-comp-name", has_text="app").wait_for()
    assert page.locator("#repoChanges").is_hidden()
    page.click("#repoTabs [data-pane=historial]")
    page.locator("#repoHistory .row-title", has_text="copia inicial").wait_for()
    page.click("#repoTabs [data-pane=cambios]")

    assert page.inner_text("#repoModalPush") == "Subir 1 archivo"
    page.click("#repoModalPush")
    page.locator(".toast", has_text="1 archivo subido a GitHub").wait_for()
    page.locator("#dotfilesText", has_text="Al día con GitHub").wait_for()
    assert _remote_file(env) == "uno\ndos cambiado\ntres\n"
    assert page.get_attribute("#dotfilesPanel", "data-health") == "ok"
    page.locator("#repoChanges .empty-state, #repoChanges [class*=empty]").first.wait_for()


def test_un_secreto_se_explica_y_no_sube(context, server, dotfiles_env):
    page = context.new_page()  # el 422 esperado sale en la consola: aquí no se vigila
    env = dotfiles_env
    subido = _remote_file(env)
    env["live"].write_text(subido + "token = ghp_" + "a" * 36 + "\n")
    page.goto(f"{server}/backups")
    page.locator("#dotfilesText", has_text="1 archivo cambiado").wait_for()
    page.click("#dotfilesPanel [data-push]")
    alert = page.locator("#dotfilesAlert")
    alert.wait_for()
    assert "No se ha subido nada" in alert.inner_text() and "ghp_" not in alert.inner_text()
    assert _remote_file(env) == subido
    env["live"].write_text(subido)
