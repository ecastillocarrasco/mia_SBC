@echo off
rem SOLO PARA ESTA RONDA DE PRUEBAS DE PRE: lanza la app ya INSTALADA con la validacion de
rem certificado TLS desactivada para el backend, porque mia-pre.sunsetbeachclub.local todavia
rem sirve un certificado autofirmado. Ver src/insecure-tls.cjs para el porque.
rem Cuando PRE tenga un certificado de una CA de confianza, deja de hacer falta este script:
rem basta con el acceso directo normal del menu inicio.
rem
rem Lanzalo con doble clic DESDE EL EXPLORADOR DE WINDOWS. Una terminal integrada de VS Code
rem puede heredar ELECTRON_RUN_AS_NODE, que rompe cualquier app Electron lanzada desde ahi.
setlocal
set MIA_DESKTOP_INSECURE_TLS=1
rem El instalador copia este script junto al .exe (mismo $INSTDIR), asi que %~dp0 ya apunta al
rem sitio correcto sin tener que adivinar si se instalo "solo para mi" o "para todos los usuarios".
set "MIA_EXE=%~dp0mIA Desktop SBC.exe"
if not exist "%MIA_EXE%" set "MIA_EXE=%ProgramFiles%\mIA Desktop SBC\mIA Desktop SBC.exe"
if not exist "%MIA_EXE%" set "MIA_EXE=%LOCALAPPDATA%\Programs\mIA Desktop SBC\mIA Desktop SBC.exe"
if not exist "%MIA_EXE%" (
  echo No encuentro mIA Desktop SBC.exe junto a este script, ni en "%ProgramFiles%\mIA Desktop SBC"
  echo ni en "%LOCALAPPDATA%\Programs\mIA Desktop SBC".
  echo Si elegiste otra carpeta al instalar, edita MIA_EXE en este script o lanza el .exe
  echo manualmente despues de ejecutar en esta misma ventana: set MIA_DESKTOP_INSECURE_TLS=1
  pause
  exit /b 1
)
echo [mIA] Lanzando con MIA_DESKTOP_INSECURE_TLS=1 para la prueba de PRE...
start "" "%MIA_EXE%"
endlocal
