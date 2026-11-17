<#
.SYNOPSIS
    Arranca el panel en Windows (P-12, docs/windows.md §7). Lo lanza la tarea programada «Panel Maestro» al iniciar
    sesión; install.ps1 lo copia a %LOCALAPPDATA%\PanelMaestro\app.

.DESCRIPTION
    1. Comprueba el inicio rápido y la hibernación (una actualización de Windows puede volver a encenderlos): si están
       activos, avisa y NO arranca. Deja lo que vio en <datos>\data\windows-estado.json para el panel de Linux.
    2. Arranca el panel en modo UTF-8 con el .env de %LOCALAPPDATA%\PanelMaestro.
    3. Si el panel se niega a arrancar (cierre sucio de Linux, carpeta en solo lectura…), enseña el motivo; tras un
       cierre sucio ofrece comprobar y seguir.

.PARAMETER Estado   Solo enseña el estado de los datos (cerrojo, WAL, integrity_check y recuentos) y sale.
.PARAMETER Seguir   Confirma un cierre sucio de Linux (repite la comprobación) y arranca.
.PARAMETER Parar    Para el panel y deja los datos cerrados.
#>
param(
    [switch]$Estado,
    [switch]$Seguir,
    [switch]$Parar
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\windows\comun.ps1')

$app = $PSScriptRoot
$python = Join-Path $script:Base 'venv\Scripts\python.exe'
$envFile = Join-Path $script:Base '.env'
if (-not (Test-Path $python) -or -not (Test-Path $envFile)) {
    Show-Aviso "El panel no está instalado en $script:Base. Ejecuta install.ps1." | Out-Null
    exit 1
}
$conf = Read-Env $envFile
$dataDir = $conf['PANEL_DATA_DIR']
$puerto = if ($conf['PANEL_PORT']) { [int]$conf['PANEL_PORT'] } else { 8000 }
$hostPanel = if ($conf['PANEL_HOST']) { $conf['PANEL_HOST'] } else { '127.0.0.1' }
$logs = if ($conf['PANEL_LOGS_DIR']) { $conf['PANEL_LOGS_DIR'] } else { Join-Path $script:Base 'logs' }
$denegado = Join-Path $logs 'arranque-denegado.json'

$env:PANEL_ENV_FILE = $envFile
$env:PANEL_PLATFORM = 'windows'
$env:PYTHONUTF8 = '1'   # Python en Windows abre en cp1252 por defecto (docs/windows.md §2.4)
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $app

# La salida de Python va a la consola (Out-Host): si no, la función la devolvería junto con el código de salida
function Invoke-Datos([string[]]$Orden) {
    & $python -m scripts.datos_compartidos --entorno ninguno @Orden | Out-Host
    return $LASTEXITCODE
}

if ($Estado) { exit (Invoke-Datos @('estado')) }

if ($Parar) {
    $ids = Get-ProcesosPanel $dataDir $puerto
    if (-not $ids) { Write-Host 'El panel no está en marcha.'; exit 0 }
    $ids | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    # Parado a la fuerza: «seguir» comprueba las BDs, pasa el WAL al .db y deja el cerrojo cerrado
    exit (Invoke-Datos @('seguir'))
}

# Una sola instancia por sesión
$mutex = New-Object System.Threading.Mutex($false, 'Local\PanelMaestroStart')
if (-not $mutex.WaitOne(0)) { Write-Host 'Ya hay un start.ps1 en marcha.'; exit 0 }

try {
    $energia = Get-EstadoEnergia
    Write-EstadoWindows $dataDir $energia
    $texto = Get-TextoEnergia $energia
    if ($texto) {
        Show-Aviso "El panel NO arranca.`n`n$texto" | Out-Null
        exit 1
    }
    if (-not (Test-Path $dataDir)) {
        Show-Aviso "No encuentro la carpeta de datos $dataDir (¿unidad sin montar o con otra letra?). El panel no arranca." | Out-Null
        exit 1
    }

    if ($Seguir) {
        if ((Invoke-Datos @('seguir')) -ne 0) {
            Show-Aviso 'La comprobación de los datos falla: el panel no arranca. Mira docs\recuperacion.md.' | Out-Null
            exit 1
        }
    }

    $intentos = 0
    while ($true) {
        if (Test-Path $denegado) { Remove-Item $denegado -Force }
        & $python -m uvicorn main:app --host $hostPanel --port $puerto
        $codigo = $LASTEXITCODE
        if ($codigo -eq 0) { break }   # parada normal
        if ($codigo -eq 3 -and (Test-Path $denegado)) {
            $d = [System.IO.File]::ReadAllText($denegado) | ConvertFrom-Json
            $msg = "El panel no arranca.`n`n$($d.mensaje)"
            if ($d.motivo -eq 'cierre-sucio') {
                if (Show-Aviso "$msg`n`n¿Comprobar otra vez las bases de datos y seguir si están bien?" -SiNo) {
                    if ((Invoke-Datos @('seguir')) -eq 0) { continue }
                    Show-Aviso 'La comprobación falla: el panel no arranca. Mira docs\recuperacion.md.' | Out-Null
                }
                exit 3
            }
            if ($d.accion) { $msg += "`n`n→ $($d.accion)" }
            Show-Aviso $msg | Out-Null
            exit 3
        }
        $intentos++
        if ($intentos -ge 3) {
            Show-Aviso "El panel se ha parado $intentos veces (código $codigo). Mira $logs\panel.log." | Out-Null
            exit $codigo
        }
        Start-Sleep -Seconds 5
    }
} finally {
    $mutex.ReleaseMutex()
}
