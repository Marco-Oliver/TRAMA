# Run only in a disposable Windows CI runner after compiling the Preview installer.
# The stable TRAMA install and its user data must remain completely untouched.
$ErrorActionPreference = 'Stop'

function Invoke-BoundedProcess {
    param([string]$Path, [string[]]$Arguments, [string]$Label, [int]$Seconds = 180)
    $process = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
    try {
        if (-not $process.WaitForExit($Seconds * 1000)) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            throw "$Label exceeded $Seconds seconds"
        }
        $process.Refresh()
        if ($process.ExitCode -ne 0) {
            throw "$Label failed with exit code $($process.ExitCode)"
        }
    } finally {
        $process.Dispose()
    }
}

$setup = Join-Path (Get-Location) 'release\TRAMA_Preview_Setup.exe'
if (-not (Test-Path -LiteralPath $setup)) { throw 'Preview installer not found' }
$installDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Preview-Install-Test'
$stableDir = Join-Path $env:LOCALAPPDATA 'TRAMA'
$previewDir = Join-Path $env:LOCALAPPDATA 'TRAMA-Preview-PR4'
$exe = Join-Path $installDir 'TRAMA.exe'

New-Item -ItemType Directory -Force -Path $stableDir | Out-Null
$sentinel = Join-Path $stableDir 'ci-stable-do-not-touch.txt'
$stableSettings = Join-Path $stableDir 'settings.json'
'Stable installation and local data stay untouched' | Set-Content -LiteralPath $sentinel -Encoding UTF8
'{"stable_only":"preserve","vault":"do-not-read"}' | Set-Content -LiteralPath $stableSettings -Encoding UTF8
$before = (Get-FileHash -LiteralPath $stableSettings -Algorithm SHA256).Hash

try {
    for ($attempt=1; $attempt -le 2; $attempt++) {
        $arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR=' + $installDir))
        Invoke-BoundedProcess $setup $arguments "Preview install #$attempt"
        if (-not (Test-Path -LiteralPath $exe)) { throw 'Installed Preview TRAMA.exe missing' }
        Invoke-BoundedProcess $exe @('--self-test') "Preview executable self-test #$attempt" 90
        if (-not (Test-Path -LiteralPath $sentinel)) { throw 'Stable local data removed by Preview' }
        if ((Get-FileHash -LiteralPath $stableSettings -Algorithm SHA256).Hash -ne $before) {
            throw 'Stable settings changed by Preview installer'
        }
        if (Test-Path -LiteralPath (Join-Path $previewDir 'settings.json')) {
            $previewSettings = Get-Content -LiteralPath (Join-Path $previewDir 'settings.json') -Raw
            if ($previewSettings -match 'do-not-read|stable_only') {
                throw 'Preview copied stable user settings'
            }
        }
    }
    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw 'Preview uninstaller missing' }
    Invoke-BoundedProcess $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 'Preview uninstall'
    if (-not (Test-Path -LiteralPath $sentinel)) { throw 'Stable data removed by Preview uninstall' }
    if ((Get-FileHash -LiteralPath $stableSettings -Algorithm SHA256).Hash -ne $before) {
        throw 'Stable settings changed after Preview uninstall'
    }
    Write-Output 'PASS: isolated Preview installer, reinstall/uninstall, no stable user data changes'
} finally {
    Remove-Item -LiteralPath $sentinel -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $stableSettings -ErrorAction SilentlyContinue
}
