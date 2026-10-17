@echo off
setlocal
cd /d "%~dp0"
where node >nul 2>nul
if errorlevel 1 (
  echo [mIA] Necesitas instalar Node.js LTS: https://nodejs.org/
  pause
  exit /b 1
)
if not exist "node_modules\electron\dist\electron.exe" (
  echo [mIA] Instalando dependencias de la aplicacion por primera vez...
  call npm install
  if errorlevel 1 (
    echo [mIA] La instalacion ha fallado. Comprueba tu red o proxy.
    pause
    exit /b 1
  )
)
echo [mIA] Iniciando aplicacion de escritorio...
call npm start
if errorlevel 1 pause
endlocal
