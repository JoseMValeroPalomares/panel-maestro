<#
.SYNOPSIS
    Instala el panel en Windows 11 con los datos en la partición compartida con Linux (P-12, docs/windows.md §7).
    Solo la web: sin captura rápida, avisos del sistema ni Waybar.

.EXAMPLE
    .\install.ps1 -Datos D:\panel-maestro                         # con los datos que movió Linux (scripts.datos_compartidos mover)
    .\install.ps1 -Datos D:\panel-maestro -Secretos E:\linux.env  # copia la contraseña y los tokens del .env de Linux
    .\install.ps1 -Desinstalar                                    # quita todo menos la carpeta de datos

.PARAMETER Datos      Carpeta compartida (la de /mnt/datos/panel-maestro en Linux).
.PARAMETER Secretos   Un .env de Linux del que copiar la contraseña, los tokens e iCloud. Sin él, pide una contraseña.
.PARAMETER Nueva      Admite una carpeta de datos sin panel (empezar de cero). Sin esto se niega, para no crear datos
                      vacíos por una letra de unidad equivocada.
.PARAMETER Universidad  Carpeta de la universidad en Windows (p. ej. D:\Uja): manda sobre la ruta de Linux de la BD.
.PARAMETER Puerto     Puerto local (8000).
.PARAMETER SinDefender  No añade la exclusión del antivirus (no pide administrador).
#>
param(
    [string]$Datos,
    [string]$Secretos,
    [switch]$Nueva,
    [string]$Universidad,
    [int]$Puerto = 8000,
    [switch]$SinDefender,
    [switch]$Desinstalar
)

$ErrorActionPreference = 'Stop'
$origen = $PSScriptRoot
. (Join-Path $origen 'scripts\windows\comun.ps1')

function Paso([string]$t) { Write-Host "==> $t" -ForegroundColor Cyan }
function Aviso([string]$t) { Write-Host "Aviso: $t" -ForegroundColor Yellow }
function Falla([string]$t) { Write-Host "ERROR: $t" -ForegroundColor Red; exit 1 }

$app = Join-Path $script:Base 'app'
$venv = Join-Path $script:Base 'venv'
$envFile = Join-Path $script:Base '.env'
$tarea = 'Panel Maestro'
$accesos = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Panel Maestro.url'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'Panel Maestro.url')
)

function Invoke-Admin([string]$Orden) {
    $p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $Orden)
    return $p.ExitCode
}

# ─────────────────────────── Desinstalar ───────────────────────────
if ($Desinstalar) {
    $conf = Read-Env $envFile
    $dataDir = $conf['PANEL_DATA_DIR']
    Paso 'Parando el panel y cerrando los datos'
    if (Test-Path (Join-Path $app 'start.ps1')) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'start.ps1') -Parar
    }
    Paso "Quitando la tarea «$tarea» y los accesos directos"
    Unregister-ScheduledTask -TaskName $tarea -Confirm:$false -ErrorAction SilentlyContinue
    $accesos | ForEach-Object { Remove-Item $_ -Force -ErrorAction SilentlyContinue }
    if ($dataDir -and -not $SinDefender) {
        $carpeta = Split-Path $dataDir -Parent
        Paso "Quitando la exclusión del antivirus de $carpeta (pide administrador)"
        try { Invoke-Admin "Remove-MpPreference -ExclusionPath '$carpeta'" | Out-Null } catch { Aviso "No se quitó: $_" }
    }
    $copias = $conf['PANEL_BACKUPS_DIR']
    $r = Read-Host "¿Borrar $script:Base (código, venv, .env, logs y las COPIAS de Windows en $copias)? [s/N]"
    if ($r -match '^[sS]') {
        Remove-Item $script:Base -Recurse -Force
        Write-Host "Borrado $script:Base."
    } else {
        Write-Host "Se queda $script:Base."
    }
    Write-Host "La carpeta de datos ($dataDir) no se ha tocado." -ForegroundColor Green
    exit 0
}

# ─────────────────────────── Comprobaciones ───────────────────────────
if (-not $Datos) { Falla 'Falta -Datos <carpeta compartida> (p. ej. D:\panel-maestro)' }
$Datos = [System.IO.Path]::GetFullPath($Datos.TrimEnd('\'))
Paso 'Comprobando Windows'
$energia = Get-EstadoEnergia
$texto = Get-TextoEnergia $energia
if ($texto) { Falla $texto }
Write-Host '   Inicio rápido e hibernación: desactivados.'

if (-not (Test-Path $Datos)) { Falla "No existe $Datos (¿otra letra de unidad?)" }
foreach ($od in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
    if ($od -and $Datos.ToLower().StartsWith($od.TrimEnd('\').ToLower())) {
        Falla "La carpeta de datos está dentro de OneDrive ($od): OneDrive bloquea archivos a mitad de escritura."
    }
}
$dataDir = Join-Path $Datos 'data'
$tienePanel = (Test-Path (Join-Path $dataDir 'panel-cerrojo.json')) -or (Test-Path (Join-Path $dataDir 'brain.db'))
if (-not $tienePanel -and -not $Nueva) {
    Falla "$Datos no tiene datos del panel (falta data\brain.db). Muévelos antes desde Linux (docs/windows.md §6) o usa -Nueva."
}
if ($Datos.Substring(0, 2) -ieq $env:SystemDrive) {
    Aviso "Los datos están en la unidad del sistema ($env:SystemDrive): Linux no los verá."
}
$rtc = Get-RegistroDword 'HKLM:\SYSTEM\CurrentControlSet\Control\TimeZoneInformation' 'RealTimeIsUniversal'
if ($rtc -ne 1) {
    Aviso ('Windows guarda la hora del reloj en hora local y Linux en UTC: irá una hora mal tras cambiar de sistema. ' +
        'Como administrador: reg add "HKLM\SYSTEM\CurrentControlSet\Control\TimeZoneInformation" /v RealTimeIsUniversal /t REG_DWORD /d 1 /f')
}
if ((Get-RegistroDword 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' 'LongPathsEnabled') -ne 1) {
    Aviso 'Rutas largas desactivadas (límite de 260 caracteres). Hoy no hace falta; si alguna nota falla al guardar, actívalas.'
}

# ─────────────────────────── Python ───────────────────────────
Paso 'Python'
function Find-Python {
    foreach ($v in @('3.14', '3.13', '3.12')) {
        try {
            $p = & py "-$v" -c 'import sys; print(sys.executable)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
        } catch { }
    }
    foreach ($d in @('Python314', 'Python313', 'Python312')) {
        $p = Join-Path $env:LOCALAPPDATA "Programs\Python\$d\python.exe"
        if (Test-Path $p) { return $p }
    }
    return $null
}
$py = Find-Python
if (-not $py) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Falla 'No hay Python ni winget: instala Python 3.14 de python.org' }
    Write-Host '   Instalando Python 3.14 con winget…'
    & winget install --exact --id Python.Python.3.14 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if (-not $py) { Falla 'winget terminó pero no encuentro Python: abre otra consola y vuelve a ejecutar install.ps1' }
}
Write-Host "   $py ($(& $py --version))"

# ─────────────────────────── Código y venv ───────────────────────────
Paso "Copiando el código a $app"
New-Item -ItemType Directory -Force -Path $script:Base | Out-Null
$fuera = @('.git', 'venv', 'node_modules', 'data', 'backups', 'logs', 'dist', '__pycache__', '.pytest_cache',
    'esp32_deskclock', 'uploads', 'export')
& robocopy $origen $app /MIR /NFL /NDL /NJH /NJS /NP /XD @fuera /XF '.env' '*.db' '*.db-wal' '*.db-shm' '*.pyc' | Out-Null
if ($LASTEXITCODE -ge 8) { Falla "robocopy falló ($LASTEXITCODE)" }

Paso "Entorno de Python en $venv"
if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { & $py -m venv $venv }
$vpy = Join-Path $venv 'Scripts\python.exe'
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r (Join-Path $app 'requirements.lock')
if ($LASTEXITCODE -ne 0) {
    Aviso 'No se pudo instalar requirements.lock; pruebo con requirements.txt'
    & $vpy -m pip install --quiet -r (Join-Path $app 'requirements.txt') tzdata
    if ($LASTEXITCODE -ne 0) { Falla 'No se pudieron instalar las dependencias' }
}

# ─────────────────────────── .env ───────────────────────────
Paso "Configuración en $envFile"
$d = $Datos.Replace('\', '/')
$base = $script:Base.Replace('\', '/')
$cambios = [ordered]@{
    PANEL_PLATFORM       = 'windows'
    PANEL_HOST           = '127.0.0.1'
    PANEL_PORT           = "$Puerto"
    PANEL_DATA_DIR       = "$d/data"
    PANEL_NOTES_DIR      = "$d/data/notes"
    PANEL_BRAIN_DB       = "$d/data/brain.db"
    PANEL_TRASH_DIR      = "$d/data/trash"
    PANEL_COMIDAS_DB     = "$d/comidas/comidas.db"
    PANEL_UPLOADS_DIR    = "$d/uploads"
    PANEL_CALENDAR_STATE = "$d/estudio/calendar_sync_v2.json"
    PANEL_BACKUPS_DIR    = "$base/backups"
    PANEL_LOGS_DIR       = "$base/logs"
    PANEL_PROJECT_DIR    = "$base/app"
}
if ($Universidad) { $cambios['PANEL_UNI_ROOT'] = $Universidad.Replace('\', '/') }
elseif (Test-Path (Join-Path (Split-Path $Datos -Qualifier) 'Uja')) {
    $cambios['PANEL_UNI_ROOT'] = (Join-Path (Split-Path $Datos -Qualifier) 'Uja').Replace('\', '/')
    Write-Host "   Universidad: $($cambios['PANEL_UNI_ROOT'])"
}
$nuevoEnv = -not (Test-Path $envFile)
if ($nuevoEnv) {
    [System.IO.File]::WriteAllText($envFile, "# Panel Maestro en Windows (install.ps1). NO lo compartas: lleva secretos.`n", $script:Utf8SinBom)
}
if ($Secretos) {
    if (-not (Test-Path $Secretos)) { Falla "No existe $Secretos" }
    $linux = Read-Env $Secretos
    foreach ($k in @('PANEL_PASSWORD_HASH', 'PANEL_SESSION_SECRET', 'PANEL_SESSION_GEN', 'PANEL_API_TOKEN_HASH',
            'ICLOUD_USERNAME', 'ICLOUD_APP_PASSWORD', 'ICLOUD_CALENDAR_NAME', 'OPENROUTER_API_KEY', 'GROQ_API_KEY',
            'GEMINI_API_KEY')) {
        if ($linux.Contains($k)) { $cambios[$k] = $linux[$k] }
    }
    Write-Host "   Secretos copiados de $Secretos (bórralo de donde lo dejaras si era una copia temporal)."
}
Write-Env $envFile $cambios
if (-not (Read-Env $envFile)['PANEL_PASSWORD_HASH']) {
    Write-Host '   Contraseña del panel:'
    $env:PANEL_ENV_FILE = $envFile
    Push-Location $app
    & $vpy -m scripts.set_password
    Pop-Location
}

# ─────────────────────────── Antivirus ───────────────────────────
if (-not $SinDefender) {
    Paso "Exclusión de Microsoft Defender para $Datos (pide administrador)"
    try {
        $c = Invoke-Admin "Add-MpPreference -ExclusionPath '$Datos'"
        if ($c -ne 0) { Aviso "No se añadió (código $c)" }
    } catch {
        Aviso "No se añadió la exclusión ($_). Puedes hacerlo en Seguridad de Windows → Exclusiones."
    }
}

# ─────────────────────────── Tarea y accesos directos ───────────────────────────
Paso "Tarea programada «$tarea» al iniciar sesión"
$accion = New-ScheduledTaskAction -Execute 'powershell.exe' -WorkingDirectory $app `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$(Join-Path $app 'start.ps1')`""
$disparo = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$ajustes = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $tarea -Action $accion -Trigger $disparo -Settings $ajustes `
    -Description 'Panel Maestro (solo web, http://127.0.0.1). Datos en la partición compartida con Linux.' -Force | Out-Null

Paso 'Accesos directos en el escritorio y en Inicio'
foreach ($a in $accesos) {
    New-Item -ItemType Directory -Force -Path (Split-Path $a) | Out-Null
    [System.IO.File]::WriteAllText($a, "[InternetShortcut]`r`nURL=http://127.0.0.1:$Puerto/`r`n", [System.Text.Encoding]::ASCII)
}

Paso 'Arrancando'
Start-ScheduledTask -TaskName $tarea
$listo = $false
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:$Puerto/healthz"
        if ($r.StatusCode -eq 200) { $listo = $true; break }
    } catch { }
}
if ($listo) {
    Write-Host "Hecho: http://127.0.0.1:$Puerto/ (y el acceso directo «Panel Maestro»)." -ForegroundColor Green
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $app 'start.ps1') -Estado
} else {
    Aviso "El panel no responde todavía. Mira $base/logs/panel.log o ejecuta: & '$app\start.ps1'"
}
