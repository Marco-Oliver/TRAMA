# Testa atualização real v1.9.0 -> candidata 2.0.0 preservando cofre e SQLite.
# Executar somente em runner Windows limpo, após compilar release/TRAMA_Setup.exe.
$ErrorActionPreference = 'Stop'
$legacyRoot = Join-Path $env:RUNNER_TEMP 'trama-legacy-source'
$vault = Join-Path $env:RUNNER_TEMP 'TRAMA-Vault-Upgrade'
$inbox = Join-Path $env:RUNNER_TEMP 'trama-legacy-inbox'
$installDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Upgrade-Install'
$oldSetupDir = Join-Path $env:RUNNER_TEMP 'TRAMA-Old-Installer'
$oldSetup = Join-Path $oldSetupDir 'TRAMA_Setup.exe'
$newSetup = Join-Path (Get-Location) 'release\TRAMA_Setup.exe'
if (-not (Test-Path $newSetup)) { throw 'Instalador candidato não encontrado' }
New-Item -ItemType Directory -Force $inbox, $oldSetupDir | Out-Null
git worktree add --detach $legacyRoot 'v1.9.0'
if ($LASTEXITCODE -ne 0) { throw 'Não foi possível recuperar as fontes v1.9.0' }
try {
    # Prepara dados com o código que está no release anterior, não com o novo.
    '[0:04] Console.WriteLine exibe texto no terminal.' |
        Set-Content -Path (Join-Path $inbox 'Aula-001-V01.txt') -Encoding UTF8
    python (Join-Path $legacyRoot 'main.py') init --vault $vault
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao iniciar cofre legado' }
    python (Join-Path $legacyRoot 'main.py') import --vault $vault --inbox $inbox
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao importar transcrição com versão antiga' }
    $personal = Join-Path $vault '05-Anotacoes-Pessoais\minha-nota.md'
    New-Item -ItemType Directory -Force (Split-Path $personal) | Out-Null
    '# Não substituir minha anotação particular' |
        Set-Content -Path $personal -Encoding UTF8
    $before = (Get-FileHash $personal -Algorithm SHA256).Hash
    $catalog = Join-Path $vault '.base-conhecimento\estado.sqlite3'
    if (-not (Test-Path $catalog)) { throw 'Banco anterior não foi criado' }

    # Instalação e upgrade verdadeiros; mesmo AppId, pasta e base de usuário.
    gh release download v1.9.0 --repo 'Marco-Oliver/TRAMA' --pattern 'TRAMA_Setup.exe' --dir $oldSetupDir
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $oldSetup)) {
        throw 'Não foi possível baixar o instalador oficial v1.9.0'
    }
    $args = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR=' + $installDir))
    $old = Start-Process -FilePath $oldSetup -ArgumentList $args -PassThru -Wait
    if ($old.ExitCode -ne 0) { throw "Instalação antiga falhou: $($old.ExitCode)" }
    $new = Start-Process -FilePath $newSetup -ArgumentList $args -PassThru -Wait
    if ($new.ExitCode -ne 0) { throw "Atualização candidata falhou: $($new.ExitCode)" }
    $exe = Join-Path $installDir 'TRAMA.exe'
    if (-not (Test-Path $exe)) { throw 'TRAMA.exe atualizado não encontrado' }
    $launch = Start-Process -FilePath $exe -ArgumentList '--self-test' -PassThru -Wait
    if ($launch.ExitCode -ne 0) { throw 'Auto-teste do aplicativo atualizado falhou' }

    # O código da versão nova abre o SQLite v1.9.0 e reconstrói o cofre.
    python main.py rebuild --vault $vault
    if ($LASTEXITCODE -ne 0) { throw 'Cofre legado não abriu com código v2.0.0' }
    $after = (Get-FileHash $personal -Algorithm SHA256).Hash
    if ($before -ne $after) { throw 'Anotação pessoal foi alterada' }
    if (-not (Test-Path (Join-Path $vault '01-Meu-Conhecimento\Indice-de-Duvidas.md'))) {
        throw 'Índice de dúvidas não criado após migração de catálogo'
    }
    python tools/check_upgrade_catalog.py $catalog
    if ($LASTEXITCODE -ne 0) { throw 'Banco SQLite perdeu fontes ou nova tabela' }

    $uninstall = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path $uninstall)) { throw 'Desinstalador não encontrado após upgrade' }
    $removed = Start-Process -FilePath $uninstall -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -PassThru -Wait
    if ($removed.ExitCode -ne 0) { throw 'Desinstalação falhou' }
    if (-not (Test-Path $personal) -or (Get-FileHash $personal -Algorithm SHA256).Hash -ne $before) {
        throw 'Desinstalação apagou a nota do estudante'
    }
    Write-Output 'PASS: v1.9.0 -> v2.0.0 preserva SQLite, fontes e nota manual após upgrade e desinstalação'
}
finally {
    git worktree remove --force $legacyRoot | Out-Null
}
