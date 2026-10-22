# mIA SBC | Continuacion segura de sincronizacion e indexacion

**No es una migracion nueva:** la solucion ya usa PostgreSQL con extension pgvector y dos tablas de fragmentos vectorizados (`hr_cv_chunks`, `hr_document_chunks`).

## 1. Instalacion

Copiar `tools/mia_index_status.py` en la carpeta `tools/` del proyecto mIA original. Copiar `Iniciar_Indexacion_mIA_SBC.ps1` en la raiz. Los scripts son auxiliares; no reemplazan el codigo del sincronizador ni cambian el esquema.

Ejecutar en el **servidor que ya usa las credenciales y la base de datos reales**, desde PowerShell con el entorno virtual del proyecto activado. Evitar arrancar a la vez un Container Apps Job / otro sincronizador existente; el lock del script solo protege frente a una segunda copia del mismo controlador, no frente a otros procesos.

## 2. Preflight sin escrituras

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m mia.ingestion.sync --list
python -m mia.ingestion.sync --check --source curriculums --source cv_docs --source nominas --source documentos_firmados --no-calendars
python tools/mia_index_status.py
```

Si falla, **no** activar el proceso. Comprobar revision Alembic 0011 y disponibilidad de la extension pgvector. No lanzar `alembic upgrade` sin respaldo y plan de cambios.

## 3. Ejecutar indexacion gradual

Solo CV cuando `MIA_DATA__INDEX_SENSITIVE_CONTENT=false`:

```powershell
.\Iniciar_Indexacion_mIA_SBC.ps1 -ProjectRoot "$PWD" -CycleSeconds 300 -MaxCycles 12
```

**Nominas y documentos firmados:** el codigo los indexa solo con `MIA_DATA__INDEX_SENSITIVE_CONTENT=true`. Activarlo *unicamente tras revisar y aprobar* retencion de texto completo, cifrado, controles de acceso y envio de OCR/embeddings a proveedores externos. Con este cambio se almacena el texto completo y sus fragmentos, no solo los vectores. Debe protegerse especificamente informacion sanitaria de documentos firmados. Tras activar la configuracion en el entorno autorizado:

```powershell
.\Iniciar_Indexacion_mIA_SBC.ps1 -ProjectRoot "$PWD" -SensitiveApproved -CycleSeconds 300 -MaxCycles 12
```

## 4. Avisos de progreso

- El controlador imprime un resumen agregado cada 3 ciclos (por defecto, alrededor de cada 15 minutos **mas la duracion del trabajo**); siempre conserva un log local en `logs/indexacion_mia`.
- Adicionalmente puede enviar un texto de estado a una URL de webhook de Teams/Power Automate que admita mensajes `{"text":"..."}`. Configurar `MIA_SYNC_NOTIFY_WEBHOOK` mediante variable de entorno segura. **El webhook recibe solo totales agregados**, sin nombres, DNI, nominas ni CV. Algunas versiones de Teams Workflows exigen un formato diferente; adaptar la integracion de notificacion si fuera necesario.
- `python tools/mia_index_status.py` devuelve los contadores de metadatos, indexaciones correctas y archivos pendientes/error. El total con vectores puede diferir de total de metadatos para formatos vacios/no soportados. No confundir «sincronizado» con «vectorizado».
- El script no puede enviar avisos dentro de ChatGPT por si mismo. Para avisos reales fuera de la maquina debe existir un canal de notificaciones configurado.

## 5. Consideraciones importantes observadas en el codigo

- Los indexadores procesan un maximo de `MIA_CURRICULUMS__INDEX_BATCH` (200 por defecto) **por dominio y ejecucion**. Ejecutar ciclos sucesivos completa pendientes nuevos/modificados.
- `--source` limita la sincronizacion de metadatos. La fase de indexacion procesa CV y, si esta activada, **ambos dominios sensibles**, aunque el listado de `--source` sea parcial.
- Algunos documentos con `too_large`, `error`, `unsupported` o `empty` pueden quedar sin vectorizar. Los errores almacenados no se reintentan siempre por defecto; hay que revisarlos y decidir una remediacion segura (no borrar masivamente para forzar indexacion).
- El OCR de imagenes puede estar bloqueado al habilitar `PrivacyGateway`, pues actualmente no protege pixeles. No desactivar el gateway para forzar OCR de documentos personales.
- Si el sincronizador se ejecuta automaticamente en Azure, es preferible ampliar el trabajo existente y su telemetria en vez de lanzar otro proceso concurrente en Windows.
- El usuario necesita otorgar permiso para ejecutar indexacion persistente de nominas y documentos firmados; la bandera predeterminada esta desactivada por razones de privacidad.

## 6. Alcance

Este paquete se ha revisado en seco contra el codigo, no se ha ejecutado en la infraestructura corporativa. No contiene credenciales ni datos empresariales. El informe de progreso requiere la base de datos real para mostrar porcentajes precisos.
