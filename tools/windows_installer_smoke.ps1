# Run on a clean GitHub-hosted Windows runner after Inno Setup compilation.
# Tests actual installation, packaged runtime, re-installation and uninstall.
$ErrorActionPreference = 'Stop'
function Invoke-BoundedProcess {
    param([string]$Path, [string[]]$Arguments, [string]$Label, [int]$Seconds = 180)
    $proc = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
    try {
        if (-not $proc.WaitForExit($Seconds * 1000)) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            throw "$Label excedeu o limite de $Seconds segundos."
        }
        $proc.Refresh()
        if ($proc.ExitCode -ne 0) {
            throw "$Label falhou com codigo $($proc.ExitCode)"
        }
    } finally {
        $proc.Dispose()
    }
}

$setup = Join-Path (Get-Location) 'release\TRAMA_Setup.exe'
if (-not (Test-Path $setup)) { throw 'Installer missing' }
$installDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Install-Smoke'
$dataDir = Join-Path $env:LOCALAPPDATA 'TRAMA'
$exe = Join-Path $installDir 'TRAMA.exe'
$sentinel = Join-Path $dataDir 'ci-retention-sentinel.txt'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
'Stays on disk across install and uninstall' | Set-Content $sentinel -Encoding UTF8
try {
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR=' + $installDir))
        Invoke-BoundedProcess $setup $arguments "Instalacao $attempt" 180
        if (-not (Test-Path $exe)) { throw 'Installed TRAMA.exe missing' }
        Invoke-BoundedProcess $exe @('--self-test') "Autoteste $attempt" 90
        if (-not (Test-Path $sentinel)) { throw 'User data lost during installation' }
    }
    $uninstall = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path $uninstall)) { throw 'Uninstaller missing' }
    Invoke-BoundedProcess $uninstall @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 'Desinstalacao' 180
    if (-not (Test-Path $sentinel)) { throw 'User data lost after uninstall' }
    Write-Output 'PASS: installed executable + reinstall + uninstall preserved local user data'
}
finally {
    Remove-Item -LiteralPath $sentinel -ErrorAction SilentlyContinue
}
