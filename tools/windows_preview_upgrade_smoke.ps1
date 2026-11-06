# Windows CI ONLY. Install a real public older Preview, then the already
# validated PR candidate. Never run against a user's installed TRAMA.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or -not $env:RUNNER_TEMP) {
    throw 'This destructive installer smoke requires an isolated Windows GitHub Actions runner.'
}

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
    } finally { $process.Dispose() }
}

$oldSetup = Join-Path $env:RUNNER_TEMP 'preview-old\TRAMA_Preview_Setup.exe'
$newSetup = Join-Path $env:RUNNER_TEMP 'preview-new\TRAMA_Preview_Setup.exe'
$oldSHA = 'a20ee31284214711b116a4c9a8e72c8561e9a5a8bb75204fb7f525a854ad4093'
$newSHA = 'a6966cf0d8baeac0c797ccb09490b7170593863d7c31a7630e74a0fe54748144'
if (-not (Test-Path -LiteralPath $oldSetup) -or -not (Test-Path -LiteralPath $newSetup)) {
    throw 'Both the released 189 and validated 207 installers are required.'
}
if ((Get-FileHash $oldSetup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $oldSHA) {
    throw 'Source Preview 189 SHA-256 mismatch.'
}
if ((Get-FileHash $newSetup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $newSHA) {
    throw 'Target Preview 207 SHA-256 mismatch.'
}

$installDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Preview-189-to-207'
$exe = Join-Path $installDir 'TRAMA.exe'
$metadata = Join-Path $installDir '_internal\release_channel.json'
$stableDir = Join-Path $env:LOCALAPPDATA 'TRAMA'
$previewDir = Join-Path $env:LOCALAPPDATA 'TRAMA-Preview'
$vault = Join-Path $env:RUNNER_TEMP 'TRAMA-Preview-Upgrade-Vault'
$note = Join-Path $vault '02-Minhas-Aulas\Aula-137\minha-nota-de-teste.md'
$stableConfig = Join-Path $stableDir 'settings.json'
$stableSentinel = Join-Path $stableDir 'ci-stable-189-207.txt'
$previewConfig = Join-Path $previewDir 'settings.json'
$previewSecret = Join-Path $previewDir 'api_keys.dpapi.json'
$previewSentinel = Join-Path $previewDir 'ci-preview-189-207.txt'
if ((Test-Path $installDir) -or (Test-Path $stableConfig) -or (Test-Path $previewConfig)) {
    throw 'Unexpected existing test install or user settings; refusing to overwrite.'
}

New-Item -ItemType Directory -Force $stableDir, $previewDir, (Split-Path $note -Parent) | Out-Null
'{"origin":"stable","vault":"STABLE-PRIVATE-DO-NOT-ACCESS"}' |
    Set-Content -LiteralPath $stableConfig -Encoding UTF8
'stable-sentinel-not-for-preview' | Set-Content -LiteralPath $stableSentinel -Encoding UTF8
'# Minha nota preservada no cofre de teste' | Set-Content -LiteralPath $note -Encoding UTF8
$stableHash = (Get-FileHash $stableConfig -Algorithm SHA256).Hash
$stableSentinelHash = (Get-FileHash $stableSentinel -Algorithm SHA256).Hash
$noteHash = (Get-FileHash $note -Algorithm SHA256).Hash

function Assert-Release([string]$Version) {
    if (-not (Test-Path -LiteralPath $exe) -or -not (Test-Path -LiteralPath $metadata)) {
        throw "Preview $Version EXE/embedded release channel missing."
    }
    $info = Get-Content -LiteralPath $metadata -Raw | ConvertFrom-Json
    if ($info.channel -ne 'preview' -or $info.github_repo -ne 'Marco-Oliver/TRAMA' -or
            $info.version -ne $Version) {
        throw "Wrong installed channel or version; expected $Version."
    }
    $marker = Join-Path $installDir '_internal\assets\trama-preview.marker'
    if (-not (Test-Path -LiteralPath $marker)) {
        throw "Preview isolation marker absent for $Version."
    }
    Invoke-BoundedProcess $exe @('--self-test') "TRAMA $Version self-test" 90
    if ((Get-FileHash $stableConfig -Algorithm SHA256).Hash -ne $stableHash -or
            (Get-FileHash $stableSentinel -Algorithm SHA256).Hash -ne $stableSentinelHash) {
        throw 'Stable TRAMA settings were changed by the experimental installer.'
    }
    if ((Get-FileHash $note -Algorithm SHA256).Hash -ne $noteHash) {
        throw 'Obsidian test vault note changed by the installer.'
    }
}

try {
    $args = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
              ('/DIR="' + $installDir + '"'))
    Invoke-BoundedProcess $oldSetup $args 'Install real Preview 189'
    Assert-Release '2.2.0-preview.189'

    # Synthetic test settings and placeholder secrets. Never real credentials.
    ('{"vault":"' + ($vault.Replace('\', '\\')) +
     '","preview_upgrade_marker":"persist-189-207"}') |
        Set-Content -LiteralPath $previewConfig -Encoding UTF8
    '{"fake_dpapi_test_only":"never_an_actual_key"}' |
        Set-Content -LiteralPath $previewSecret -Encoding UTF8
    'preview-persistent-setting' |
        Set-Content -LiteralPath $previewSentinel -Encoding UTF8
    $previewHashes = @{}
    foreach ($path in @($previewConfig, $previewSecret, $previewSentinel)) {
        $previewHashes[$path] = (Get-FileHash $path -Algorithm SHA256).Hash
    }

    Invoke-BoundedProcess $newSetup $args 'Upgrade Preview 189 to 207'
    Assert-Release '2.2.0-preview.207'
    foreach ($path in $previewHashes.Keys) {
        if (-not (Test-Path $path) -or
                (Get-FileHash $path -Algorithm SHA256).Hash -ne $previewHashes[$path]) {
            throw "Preview data changed or deleted during 189 to 207 upgrade: $path"
        }
    }
    $stableContent = Get-Content -LiteralPath $stableConfig -Raw
    $previewContent = Get-Content -LiteralPath $previewConfig -Raw
    if ($previewContent -match 'STABLE-PRIVATE' -or $stableContent -match 'persist-189-207') {
        throw 'Stable and Preview configuration namespaces crossed.'
    }

    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw 'Preview uninstaller missing.' }
    Invoke-BoundedProcess $uninstaller @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 'Preview 207 uninstall'
    if ((Get-FileHash $stableConfig -Algorithm SHA256).Hash -ne $stableHash -or
            (Get-FileHash $note -Algorithm SHA256).Hash -ne $noteHash) {
        throw 'Stable settings or test vault changed on uninstall.'
    }
    foreach ($path in $previewHashes.Keys) {
        if (-not (Test-Path $path) -or
                (Get-FileHash $path -Algorithm SHA256).Hash -ne $previewHashes[$path]) {
            throw 'Preview settings did not survive uninstall.'
        }
    }
    Write-Output 'PASS: real release 189 upgraded to validated 207; notes, Preview settings, fake keys and stable data preserved.'
} finally {
    foreach ($path in @($stableConfig, $stableSentinel, $previewConfig,
                         $previewSecret, $previewSentinel)) {
        Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    }
}
