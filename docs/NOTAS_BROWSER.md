# Pruebas de navegador opcionales

`tests/browser_smoke_v52.py` ejecuta dos pruebas sobre el frontend completo:

1. Composición de `?fan=1` en cuatro tamaños de pantalla, fondo negro y
   un máximo de dos KPIs visibles, con micrófono oculto.
2. Loading al 100 % y activación de usuario auténtica en el evento `click`
   de «Continuar».

Instalación opcional del entorno de pruebas:

```powershell
python -m pip install playwright
python -m playwright install chromium
python tests/browser_smoke_v52.py
```

No comprueba el GLB ni ElevenLabs; esas integraciones deben ensayarse en
el navegador de destino con el frontend real y el backend conectado.
