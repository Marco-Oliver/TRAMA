# Validacao real de upgrade v2.0.1 -> v2.1.0 em runner Windows limpo.
# Dados e chaves ficticias; nenhuma conta privada e acessada.
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

$legacyRoot = Join-Path $env:RUNNER_TEMP 'trama-legacy-source'
$vault = Join-Path $env:RUNNER_TEMP 'TRAMA-Vault-Upgrade'
$inbox = Join-Path $env:RUNNER_TEMP 'trama-legacy-inbox'
$installDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Upgrade-Install'
$oldSetupDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Old-Installer'
$oldSetup = Join-Path $oldSetupDir 'TRAMA_Setup.exe'
$newSetup = Join-Path (Get-Location) 'release\TRAMA_Setup.exe'
if (-not (Test-Path $newSetup)) { throw 'Instalador candidato nao encontrado.' }
New-Item -ItemType Directory -Force -Path $inbox, $oldSetupDir | Out-Null
git worktree add --detach $legacyRoot 'v2.0.1'
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel recuperar v2.0.1.' }

try {
    '[0:04] Console.WriteLine exibe texto no terminal.' |
        Set-Content -Path (Join-Path $inbox 'Aula-001-V01.txt') -Encoding UTF8
    python (Join-Path $legacyRoot 'main.py') init --vault $vault
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar cofre anterior.' }
    python (Join-Path $legacyRoot 'main.py') import --vault $vault --inbox $inbox
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao importar a transcricao anterior.' }

    $personal = Join-Path $vault '05-Anotacoes-Pessoais\minha-nota.md'
    New-Item -ItemType Directory -Force -Path (Split-Path $personal) | Out-Null
    '# Nao substituir minha anotacao particular' | Set-Content -Path $personal -Encoding UTF8
    $manualHash = (Get-FileHash $personal -Algorithm SHA256).Hash
    $catalog = Join-Path $vault '.base-conhecimento\estado.sqlite3'
    if (-not (Test-Path $catalog)) { throw 'Banco anterior nao foi criado.' }

    gh release download v2.0.1 --repo 'Marco-Oliver/TRAMA' --pattern 'TRAMA_Setup.exe' --dir $oldSetupDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $oldSetup)) {
        throw 'Falha ao baixar instalador oficial v2.0.1.'
    }
    $arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR=' + $installDir))
    Invoke-BoundedProcess $oldSetup $arguments 'Instalar v2.0.1' 180
    $exe = Join-Path $installDir 'TRAMA.exe'
    if (-not (Test-Path $exe)) { throw 'TRAMA.exe v2.0.1 ausente.' }
    $oldExeHash = (Get-FileHash $exe -Algorithm SHA256).Hash

    # Teste exclusivo com dados sinteticos; arquivo DPAPI ficticio.
    $localData = Join-Path $env:LOCALAPPDATA 'TRAMA'
    New-Item -ItemType Directory -Force -Path $localData | Out-Null
    $settingsFile = Join-Path $localData 'settings.json'
    $keyFile = Join-Path $localData 'api_keys.dpapi.json'
    @{ vault=$vault; favorites=@('02-Minhas-Aulas/Aula-001/00-Visao-geral.md'); confirmed_free=$false } |
        ConvertTo-Json -Compress | Set-Content -Path $settingsFile -Encoding UTF8
    '{"gemini":"ZmFrZS1kYXRhLW5vdC1hLXJlYWwta2V5"}' | Set-Content -Path $keyFile -Encoding UTF8
    $settingsHash = (Get-FileHash $settingsFile -Algorithm SHA256).Hash
    $keyHash = (Get-FileHash $keyFile -Algorithm SHA256).Hash

    Invoke-BoundedProcess $newSetup $arguments 'Upgrade candidato v2.1.0' 180
    if (-not (Test-Path $exe)) { throw 'TRAMA.exe atualizado ausente.' }
    if ((Get-FileHash $exe -Algorithm SHA256).Hash -eq $oldExeHash) {
        throw 'Upgrade nao trocou o executavel.'
    }
    if ((Get-FileHash $settingsFile -Algorithm SHA256).Hash -ne $settingsHash -or
        (Get-FileHash $keyFile -Algorithm SHA256).Hash -ne $keyHash) {
        throw 'Upgrade modificou preferencias ou credenciais sinteticas.'
    }
    Invoke-BoundedProcess $exe @('--self-test') 'Autoteste apos upgrade' 90

    python main.py rebuild --vault $vault
    if ($LASTEXITCODE -ne 0) { throw 'Versao candidata nao reabriu o cofre anterior.' }
    if ((Get-FileHash $personal -Algorithm SHA256).Hash -ne $manualHash) {
        throw 'Nota manual mudou apos upgrade.'
    }
    python tools/check_upgrade_catalog.py $catalog
    if ($LASTEXITCODE -ne 0) { throw 'SQLite perdeu fontes ou esquema.' }

    $uninstall = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path $uninstall)) { throw 'Desinstalador nao encontrado.' }
    Invoke-BoundedProcess $uninstall @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 'Desinstalar v2.1.0' 180
    if (-not (Test-Path $personal) -or (Get-FileHash $personal -Algorithm SHA256).Hash -ne $manualHash) {
        throw 'Desinstalacao modificou nota manual.'
    }
    if ((Get-FileHash $settingsFile -Algorithm SHA256).Hash -ne $settingsHash -or
        (Get-FileHash $keyFile -Algorithm SHA256).Hash -ne $keyHash) {
        throw 'Desinstalacao modificou preferencias ou credenciais sinteticas.'
    }
    Write-Output 'PASS: v2.0.1 -> v2.1.0 preserva SQLite, notas, ajustes e chaves sinteticas.'
} finally {
    git worktree remove --force $legacyRoot | Out-Null
}
