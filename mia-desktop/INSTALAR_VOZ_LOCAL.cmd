@echo off
setlocal
cd /d "%~dp0"
set "USERVOICE=%APPDATA%\mia-desktop-sbc"
set "PYENV=%USERVOICE%\voice-runtime\.venv"
set "MODELS=%USERVOICE%\voice-models"
echo mIA Desktop SBC V0.3 - Instalacion voluntaria de voz OFFLINE.
echo Descarga librerias y modelos, pero no transmite consultas ni audio.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    py -3.11 -m venv "%PYENV%"
  ) else (
    py -3.12 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
      py -3.12 -m venv "%PYENV%"
    ) else (
      py -3 -m venv "%PYENV%"
    )
  )
) else (
  python -m venv "%PYENV%"
)
if errorlevel 1 goto fail
"%PYENV%\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto fail
"%PYENV%\Scripts\python.exe" -m pip install -r "src\voice\requirements.txt"
if errorlevel 1 goto fail
"%PYENV%\Scripts\python.exe" "src\voice\install_models.py" "%MODELS%"
if errorlevel 1 goto fail
echo.
echo Completado. Reinicia mIA Desktop y activa reconocimiento en Configuracion.
pause
exit /b 0
:fail
echo.
echo Error al preparar el reconocimiento local. No se ha modificado el backend SBC.
pause
exit /b 1
