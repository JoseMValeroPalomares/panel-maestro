@echo off
rem Doble clic: instala o actualiza el panel en Windows desde esta carpeta y lo deja en marcha (docs/windows.md §7).
rem Sin Set-ExecutionPolicy: el zip de GitHub trae la marca «descargado de Internet» y RemoteSigned no dejaría ejecutarlo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
if errorlevel 1 (
    echo.
    echo La instalacion no ha terminado bien: el detalle esta arriba.
    pause
    exit /b 1
)
rem shortcut: puerto 8000 fijo; con -Puerto distinto, abre el acceso directo «Panel Maestro»
start "" http://127.0.0.1:8000/
