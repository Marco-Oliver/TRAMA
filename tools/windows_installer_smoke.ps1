# Run on a clean GitHub-hosted Windows runner after Inno Setup compilation.
# Tests actual installation, packaged runtime, re-installation and uninstall.
$ErrorActionPreference = 'Stop'
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
        $process = Start-Process -FilePath $setup -ArgumentList $arguments -PassThru -Wait
        if ($process.ExitCode -ne 0) { throw "Installer exit code $($process.ExitCode), attempt $attempt" }
        if (-not (Test-Path $exe)) { throw 'Installed TRAMA.exe missing' }
        $smoke = Start-Process -FilePath $exe -ArgumentList '--self-test' -PassThru -Wait
        if ($smoke.ExitCode -ne 0) { throw "Installed executable failed smoke test, attempt $attempt" }
        if (-not (Test-Path $sentinel)) { throw 'User data lost during installation' }
    }
    $uninstall = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path $uninstall)) { throw 'Uninstaller missing' }
    $process = Start-Process -FilePath $uninstall -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru -Wait
    if ($process.ExitCode -ne 0) { throw "Uninstaller exit code $($process.ExitCode)" }
    if (-not (Test-Path $sentinel)) { throw 'User data lost after uninstall' }
    Write-Output 'PASS: installed executable + reinstall + uninstall preserved local user data'
}
finally {
    Remove-Item -LiteralPath $sentinel -ErrorAction SilentlyContinue
}
