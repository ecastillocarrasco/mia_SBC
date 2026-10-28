; Personalizacion del instalador NSIS de mia-desktop.
;
; 1) Un unico acceso directo (escritorio + menu inicio), con el nombre normal de la app, que en
;    realidad apunta a PROBAR_PRE_instalado.cmd en vez de al .exe: mientras PRE sirva un
;    certificado autofirmado, abrir el .exe a secas siempre falla al conectar (ver
;    src/insecure-tls.cjs). Se desactiva la creacion automatica de accesos directos de
;    electron-builder (createDesktopShortcut/createStartMenuShortcut:false en package.json) para
;    que no quede un segundo enlace "normal" que no funciona junto al que si funciona.
;    Cuando PRE tenga un certificado de una CA de confianza y el script deje de hacer falta: borrar
;    este fichero, el "include" de package.json, y volver a activar esos dos flags (o simplemente
;    quitarlos, que es su valor por defecto).
;
; 2) Al terminar, ofrece instalar tambien el reconocimiento de voz local (Vosk + Whisper): es un
;    paso voluntario con descarga de internet (~400-600MB) y que necesita Python 3 ya instalado,
;    por eso se pregunta en vez de lanzarlo sin avisar. Se abre en su propia ventana
;    (INSTALAR_VOZ_LOCAL.cmd, copiado junto al .exe via "extraFiles"); la instalacion de mIA
;    Desktop no espera a que termine.

!macro customInstall
  CreateShortCut "$DESKTOP\mIA Desktop SBC.lnk" "$INSTDIR\PROBAR_PRE_instalado.cmd" "" "$INSTDIR\mIA Desktop SBC.exe" 0
  CreateDirectory "$SMPROGRAMS\mIA Desktop SBC"
  CreateShortCut "$SMPROGRAMS\mIA Desktop SBC\mIA Desktop SBC.lnk" "$INSTDIR\PROBAR_PRE_instalado.cmd" "" "$INSTDIR\mIA Desktop SBC.exe" 0
  CreateShortCut "$SMPROGRAMS\mIA Desktop SBC\Desinstalar mIA Desktop SBC.lnk" "$INSTDIR\Uninstall mIA Desktop SBC.exe"

  MessageBox MB_YESNO "¿Instalar también el reconocimiento de voz local (Vosk + Whisper)?$\r$\n$\r$\nDescarga unos 400-600 MB de internet y necesita tener Python 3 ya instalado. Se abre en su propia ventana; la instalación de mIA Desktop no esperará a que termine.$\r$\n$\r$\nSi dices que no, puedes hacerlo luego ejecutando INSTALAR_VOZ_LOCAL.cmd en la carpeta de instalación." IDNO skip_voice
  Exec '"$INSTDIR\INSTALAR_VOZ_LOCAL.cmd"'
  skip_voice:
!macroend

!macro customUnInstall
  Delete "$DESKTOP\mIA Desktop SBC.lnk"
  Delete "$SMPROGRAMS\mIA Desktop SBC\mIA Desktop SBC.lnk"
  Delete "$SMPROGRAMS\mIA Desktop SBC\Desinstalar mIA Desktop SBC.lnk"
  RMDir "$SMPROGRAMS\mIA Desktop SBC"
!macroend
