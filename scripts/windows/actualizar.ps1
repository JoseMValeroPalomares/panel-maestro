# Actualiza el panel en Windows con un clic (acceso directo «Actualizar Panel Maestro», docs/windows.md §7): descarga
# la última versión publicada en GitHub y ejecuta su install.ps1, que para el panel cerrando los datos, copia el código,
# pone al día el venv y lo arranca. Respeta el .env, los datos y las copias. Este archivo va en UTF-8 CON BOM.
param([string]$Url = 'https://github.com/JoseMValeroPalomares/panel-maestro/archive/refs/heads/main.zip')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'comun.ps1')
$conf = Read-Env (Join-Path $script:Base '.env')
$tmp = Join-Path $env:TEMP 'panel-maestro-actualizar'
$codigo = 1
try {
    if (-not $conf['PANEL_DATA_DIR']) { throw "El panel no está instalado en $script:Base: usa instalar.cmd" }
    Write-Host "==> Descargando la última versión ($Url)" -ForegroundColor Cyan
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $tmp | Out-Null
    $zip = Join-Path $tmp 'panel.zip'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12   # PowerShell 5.1
    Invoke-WebRequest -UseBasicParsing $Url -OutFile $zip
    Expand-Archive $zip (Join-Path $tmp 'codigo')
    $install = Get-ChildItem (Join-Path $tmp 'codigo') -Directory | ForEach-Object { Join-Path $_.FullName 'install.ps1' } |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $install) { throw 'El zip descargado no trae install.ps1' }
    # -Datos y -SinDefender explícitos: así vale también el install.ps1 de versiones que aún no los deducen
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $install -Datos (Split-Path $conf['PANEL_DATA_DIR'] -Parent) -SinDefender
    $codigo = $LASTEXITCODE
} catch {
    Write-Host "ERROR: $_" -ForegroundColor Red
} finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
if ($codigo -eq 0) {
    $puerto = if ($conf['PANEL_PORT']) { $conf['PANEL_PORT'] } else { '8000' }
    Start-Process "http://127.0.0.1:$puerto/"
    Start-Sleep -Seconds 3
} else {
    Read-Host 'La actualización no ha terminado bien (el detalle está arriba). Pulsa Enter para cerrar'
}
exit $codigo
