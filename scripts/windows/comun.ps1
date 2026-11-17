# Funciones comunes de install.ps1 y start.ps1 (P-12, docs/windows.md). PowerShell 5.1 (el de Windows 11).
# Este archivo va en UTF-8 CON BOM: sin él, PowerShell 5.1 lo lee como ANSI y estropea los acentos.

$script:Base = Join-Path $env:LOCALAPPDATA 'PanelMaestro'
$script:Utf8SinBom = New-Object System.Text.UTF8Encoding $false

function Get-RegistroDword([string]$Ruta, [string]$Nombre) {
    try {
        $v = Get-ItemProperty -Path $Ruta -Name $Nombre -ErrorAction Stop
        return [int]$v.$Nombre
    } catch {
        return $null
    }
}

# Inicio rápido (HiberbootEnabled) e hibernación. Se leen del registro: no hace falta ser administrador.
function Get-EstadoEnergia {
    $hiberboot = Get-RegistroDword 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager\Power' 'HiberbootEnabled'
    $hibernate = Get-RegistroDword 'HKLM:\SYSTEM\CurrentControlSet\Control\Power' 'HibernateEnabled'
    if ($null -eq $hibernate) {
        $hibernate = Get-RegistroDword 'HKLM:\SYSTEM\CurrentControlSet\Control\Power' 'HibernateEnabledDefault'
    }
    $hiberfil = Test-Path (Join-Path $env:SystemDrive 'hiberfil.sys')
    [pscustomobject]@{
        InicioRapido = ($hiberboot -eq 1)
        Hibernacion  = (($hibernate -eq 1) -or $hiberfil)
        Hiberboot    = $hiberboot
        Hibernate    = $hibernate
        Hiberfil     = $hiberfil
    }
}

function Get-TextoEnergia($e) {
    $activos = @()
    if ($e.InicioRapido) { $activos += 'el inicio rápido' }
    if ($e.Hibernacion) { $activos += 'la hibernación' }
    if ($activos.Count -eq 0) { return $null }
    return ("Windows tiene {0} activos: al volver podría pisar lo que escriba Linux en la partición de datos. " -f ($activos -join ' y ')) +
        "En una consola de administrador:`n  powercfg /h off`n  reg add ""HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power"" /v HiberbootEnabled /t REG_DWORD /d 0 /f`n" +
        "y vuelve a intentarlo (docs\windows.md §5)."
}

# Lo que ve el panel de Linux al arrancar (app/datos_compartidos.py: comprobar_windows)
function Write-EstadoWindows([string]$DataDir, $e) {
    if (-not (Test-Path $DataDir)) { return }
    $json = [ordered]@{
        inicio_rapido = [bool]$e.InicioRapido
        hibernacion   = [bool]$e.Hibernacion
        comprobado    = (Get-Date -Format 'yyyy-MM-dd HH:mm')
        equipo        = $env:COMPUTERNAME
    } | ConvertTo-Json
    try {
        [System.IO.File]::WriteAllText((Join-Path $DataDir 'windows-estado.json'), $json, $script:Utf8SinBom)
    } catch {
        Write-Warning "No se pudo escribir windows-estado.json: $_"
    }
}

# .env sencillo: CLAVE=valor por línea; los comentarios y el orden se conservan al escribir
function Read-Env([string]$Ruta) {
    $h = [ordered]@{}
    if (Test-Path $Ruta) {
        foreach ($l in [System.IO.File]::ReadAllLines($Ruta)) {
            $t = $l.Trim()
            if ($t -and -not $t.StartsWith('#') -and $t.Contains('=')) {
                $i = $t.IndexOf('=')
                $h[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
            }
        }
    }
    return $h
}

function Write-Env([string]$Ruta, $Cambios) {
    $lineas = New-Object System.Collections.Generic.List[string]
    $vistas = @{}
    if (Test-Path $Ruta) {
        foreach ($l in [System.IO.File]::ReadAllLines($Ruta)) {
            $t = $l.Trim()
            if ($t -and -not $t.StartsWith('#') -and $t.Contains('=')) {
                $k = $t.Substring(0, $t.IndexOf('=')).Trim()
                if ($Cambios.Contains($k)) {
                    $lineas.Add("$k=$($Cambios[$k])"); $vistas[$k] = $true; continue
                }
            }
            $lineas.Add($l)
        }
    }
    foreach ($k in $Cambios.Keys) { if (-not $vistas.ContainsKey($k)) { $lineas.Add("$k=$($Cambios[$k])") } }
    [System.IO.File]::WriteAllText($Ruta, (($lineas -join "`n") + "`n"), $script:Utf8SinBom)
}

function Show-Aviso([string]$Texto, [string]$Titulo = 'Panel Maestro', [switch]$SiNo) {
    try {
        Add-Type -AssemblyName PresentationFramework -ErrorAction Stop
        if ($SiNo) {
            return ([System.Windows.MessageBox]::Show($Texto, $Titulo, 'YesNo', 'Warning') -eq 'Yes')
        }
        [void][System.Windows.MessageBox]::Show($Texto, $Titulo, 'OK', 'Warning')
    } catch {
        Write-Host $Texto
    }
    return $false
}

# Procesos del panel: el que dice el cerrojo (el pid del Python que tiene los datos abiertos) y cualquier uvicorn del panel
# en ese puerto (en un venv de Windows, python.exe es un lanzador que abre el Python de verdad como proceso hijo)
function Get-ProcesosPanel([string]$DataDir, [int]$Puerto) {
    $ids = @()
    $cerrojo = Join-Path $DataDir 'panel-cerrojo.json'
    if (Test-Path $cerrojo) {
        try {
            $c = [System.IO.File]::ReadAllText($cerrojo) | ConvertFrom-Json
            if ($c.sistema -eq 'windows' -and -not $c.cerrado -and (Get-Process -Id $c.pid -ErrorAction SilentlyContinue)) {
                $ids += [int]$c.pid
            }
        } catch { }
    }
    $patron = "uvicorn main:app .*--port $Puerto"
    $ids += Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -match $patron } | ForEach-Object { [int]$_.ProcessId }
    return $ids | Sort-Object -Unique
}
