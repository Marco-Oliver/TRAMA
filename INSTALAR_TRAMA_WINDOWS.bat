@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
if errorlevel 1 goto :failure
title TRAMA v1.9 - Instalar no Windows
color 07

echo.
echo    TRAMA  ^|  Instalacao no Windows
 echo   -----------------------------
echo.
echo    Esta instalacao usa Python APENAS para montar o executavel.
echo    Depois, o TRAMA funciona sem Python externo.
echo    Programas necessarios sao baixados por pip na primeira vez.
echo.
echo    Conferindo arquivos do TRAMA...
if not exist "%~dp0requirements.txt" goto :missing_files
if not exist "%~dp0TRAMA.spec" goto :missing_files
if not exist "%~dp0trama_launcher.py" goto :missing_files
if not exist "%~dp0tests\" goto :missing_files
if not exist "%~dp0knowledge_bridge\" goto :missing_files
where python >nul 2>nul
if errorlevel 1 (
 echo    Python nao foi encontrado. Instale Python 3.11+ e tente de novo.
 goto :failure
)
if not exist ".buildvenv\Scripts\python.exe" (
 echo    [1/5] Preparando instalacao...
 python -m venv .buildvenv
 if errorlevel 1 goto :failure
)
set "APP_PY=.buildvenv\Scripts\python.exe"
echo    [2/5] Instalando dependencias GRATUITAS do aplicativo...
"%APP_PY%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt" "pyinstaller>=6.10,<7"
if errorlevel 1 goto :failure

echo    [3/5] Conferindo os testes...
"%APP_PY%" -m unittest discover -s tests -q
if errorlevel 1 goto :failure

echo    [4/5] Criando o aplicativo Windows...
"%APP_PY%" -m PyInstaller --clean --noconfirm TRAMA.spec
if errorlevel 1 goto :failure
"dist\TRAMA\TRAMA.exe" --self-test
if errorlevel 1 goto :failure

echo    [5/5] Instalando no seu perfil Windows...
set "TRAMA_INSTALL_DIR=%LOCALAPPDATA%\Programs\TRAMA"
if not exist "%TRAMA_INSTALL_DIR%" mkdir "%TRAMA_INSTALL_DIR%"
robocopy "dist\TRAMA" "%TRAMA_INSTALL_DIR%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :failure
powershell -NoProfile -Command "$w=New-Object -ComObject WScript.Shell; $target=Join-Path $env:TRAMA_INSTALL_DIR 'TRAMA.exe'; $desktop=Join-Path ([Environment]::GetFolderPath('Desktop')) 'TRAMA.lnk'; $menu=Join-Path ([Environment]::GetFolderPath('Programs')) 'TRAMA.lnk'; foreach($link in @($desktop,$menu)){ $s=$w.CreateShortcut($link); $s.TargetPath=$target; $s.WorkingDirectory=$env:TRAMA_INSTALL_DIR; $s.IconLocation=$target; $s.Save() }"
if errorlevel 1 goto :failure

echo.
echo  SUCESSO: TRAMA instalado!
echo  Abrir pelo icone na area de trabalho ou pelo menu Iniciar.
echo  Seus dados continuam no cofre do Obsidian e em %%LOCALAPPDATA%%\TRAMA.
echo  Este instalador NAO ativa cobranca de IA, NAO conecta APIs e NAO importa arquivos.
echo.
pause
exit /b 0
:missing_files
echo.
echo  ERRO: A pasta do instalador esta incompleta.
echo  Local: %~dp0
echo  O arquivo requirements.txt e os demais arquivos devem estar na MESMA pasta
 echo  do INSTALAR_TRAMA_WINDOWS.bat, junto com tests e knowledge_bridge.
echo.
echo  SOLUCAO:
echo    1. Abra o ZIP novo no Explorador de Arquivos.
echo    2. Clique em EXTRAIR TUDO e escolha uma pasta NOVA.
echo    3. Execute INSTALAR_TRAMA_WINDOWS.bat na pasta extraida principal.
echo    4. Nao copie somente o arquivo .bat para a pasta antiga.
goto :failure
:failure
echo.
echo  Falha na instalacao. Suas notas do Obsidian NAO foram apagadas.
echo  Tire um print da mensagem acima para diagnostico.
echo.
pause
exit /b 1
