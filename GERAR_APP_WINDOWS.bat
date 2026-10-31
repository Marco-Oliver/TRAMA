@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title TRAMA - Criar aplicativo Windows
color 0A
echo.
echo ==============================
echo   TRAMA - Gerar aplicativo
 echo ==============================
echo.
where python >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Verifique python --version.
  goto :failure
)
if not exist ".buildvenv\Scripts\python.exe" (
 echo [1/4] Preparando ambiente de criacao...
 python -m venv .buildvenv
 if errorlevel 1 goto :failure
)
set "PY=.buildvenv\Scripts\python.exe"
echo [2/4] Instalando ferramentas de empacotamento GRATUITAS...
"%PY%" -m pip install --disable-pip-version-check -r requirements.txt "pyinstaller>=6.10,<7"
if errorlevel 1 goto :failure
echo [3/4] Conferindo o projeto...
"%PY%" -m unittest discover -s tests -q
if errorlevel 1 goto :failure
echo [4/4] Criando TRAMA.exe para Windows...
"%PY%" -m PyInstaller --clean --noconfirm TRAMA.spec
if errorlevel 1 goto :failure
"dist\TRAMA\TRAMA.exe" --self-test
if errorlevel 1 goto :failure
echo.
echo PRONTO! Aplicativo portatil criado em:
echo   %CD%\dist\TRAMA\TRAMA.exe
echo.
echo A pasta dist\TRAMA pode ser copiada para outro Windows sem Python.
echo.
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC (
 echo Instalador Inno Setup encontrado. Gerando TRAMA_Setup.exe...
 "%ISCC%" "TRAMA_Instalador.iss"
 if errorlevel 1 goto :failure
 echo Instalador em: %CD%\release\TRAMA_Setup_v1.2.exe
) else (
 echo Opcional: para criar TRAMA_Setup.exe, instale Inno Setup 6.
 echo A versao portatil ja funciona sem instalador.
)
echo.
pause
exit /b 0
:failure
echo.
echo Falha ao criar o executavel. O Obsidian nao foi alterado.
echo Confira a mensagem acima, tire um print e envie para revisao.
echo.
pause
exit /b 1
