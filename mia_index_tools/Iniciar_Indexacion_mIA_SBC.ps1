<#
  Ejecutar desde una segunda ventana PowerShell en el servidor donde corre mIA:
    .\Iniciar_Indexacion_mIA_SBC.ps1 -ProjectRoot 'C:\ruta\mIA' -MaxCycles 12

  NO cambia codigo ni base de datos por si mismo; llama al sincronizador oficial de mIA.
  Para incluir nominas y documentos firmados, requiere que la configuracion del backend
  YA tenga MIA_DATA__INDEX_SENSITIVE_CONTENT=true y aprobacion de retencion/privacidad.
  Notificacion opcional: variable de entorno MIA_SYNC_NOTIFY_WEBHOOK (solo cifras agregadas).
#>
param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [int]$CycleSeconds = 300,
  [int]$MaxCycles = 12,
  [int]$NotifyEvery = 3,
  [switch]$SensitiveApproved,
  [switch]$SkipPreflight
)
$ErrorActionPreference = 'Stop'
if ($CycleSeconds -lt 30) { throw 'CycleSeconds debe ser >= 30.' }
if ($MaxCycles -lt 0) { throw 'MaxCycles no puede ser negativo.' }
if ($NotifyEvery -lt 1) { throw 'NotifyEvery debe ser >= 1.' }
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$originalDir = Get-Location
$originalPyPath = $env:PYTHONPATH
$logs = Join-Path $ProjectRoot 'logs\indexacion_mia'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logPath = Join-Path $logs ("indexacion-$stamp.log")
$lockPath = Join-Path $logs 'indexacion.lock'
$lockStream = $null
try {
  # Lock held throughout the process. Prevents two copies of THIS wrapper running together.
  $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
} catch {
  throw 'Ya hay una instancia de este controlador de indexacion en ejecucion.'
}
try {
  Set-Location $ProjectRoot
  $env:PYTHONPATH = (Join-Path $ProjectRoot 'src')
  if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python no encontrado en PATH. Activa el entorno virtual de mIA.' }
  if (-not (Test-Path 'tools\mia_index_status.py')) { throw 'Copia tools\mia_index_status.py al proyecto antes de ejecutar.' }

  $enabled = (& python -c 'from mia.settings import get_settings; print(str(get_settings().data.index_sensitive_content).lower())' 2>&1)
  if ($LASTEXITCODE -ne 0) { throw "No se puede cargar la configuracion de mIA: $enabled" }
  if ($SensitiveApproved -and (($enabled | Select-Object -Last 1).ToString().Trim() -ne 'true')) {
    throw 'Indexacion sensible solicitada pero MIA_DATA__INDEX_SENSITIVE_CONTENT no es true.'
  }
  if (-not $SensitiveApproved -and (($enabled | Select-Object -Last 1).ToString().Trim() -eq 'true')) {
    throw 'La configuracion activa indexacion sensible. Ejecuta -SensitiveApproved solo tras aprobacion de privacidad.'
  }
  if (-not $SkipPreflight) {
    & python -m mia.ingestion.sync --list 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw 'Fallo en --list. Revisa las migraciones y conectividad.' }
    & python -m mia.ingestion.sync --check --source curriculums --source cv_docs --source nominas --source documentos_firmados --no-calendars 2>&1 | Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) { throw 'Fallo en --check. Comprueba acceso a SharePoint antes de indexar.' }
  }
  $cycle = 0
  while ($MaxCycles -eq 0 -or $cycle -lt $MaxCycles) {
    $cycle++
    "----- Ciclo $cycle | $(Get-Date -Format o) -----" | Tee-Object -FilePath $logPath -Append
    & python -m mia.ingestion.sync --source curriculums --source cv_docs --source nominas --source documentos_firmados --no-calendars 2>&1 | Tee-Object -FilePath $logPath -Append
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { "ERROR: sincronizador finalizo con codigo $exitCode" | Tee-Object -FilePath $logPath -Append }
    & python tools/mia_index_status.py 2>&1 | Tee-Object -FilePath $logPath -Append
    $auditExitCode = $LASTEXITCODE
    if (($cycle % $NotifyEvery) -eq 0 -or $exitCode -ne 0 -or $auditExitCode -ne 0) {
      Write-Host "RESUMEN ciclo $cycle terminado. Estado y errores en: $logPath"
      if ($env:MIA_SYNC_NOTIFY_WEBHOOK) {
        # Only aggregates, no filenames, document content, identifiers, or errors.
        $data = & python tools/mia_index_status.py --json 2>$null
        if ($LASTEXITCODE -eq 0) {
          try {
            $status = $data | ConvertFrom-Json
            $lines = @()
            foreach ($index in $status.indexes) {
              $lines += "$($index.source): $($index.with_vectors)/$($index.total_metadata) con vectores; $($index.pending_new_or_modified) nuevos/modificados; $($index.non_ok) no OK"
            }
            $message = "mIA: indexacion ciclo $cycle`n" + ($lines -join "`n")
            $body = @{ text = $message } | ConvertTo-Json -Compress
            Invoke-RestMethod -Uri $env:MIA_SYNC_NOTIFY_WEBHOOK -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 12 | Out-Null
          } catch {
            Write-Warning 'No se pudo enviar la notificacion del progreso. Verifica el webhook.'
          }
        }
      }
    }
    if ($MaxCycles -ne 0 -and $cycle -ge $MaxCycles) { break }
    Start-Sleep -Seconds $CycleSeconds
  }
  "Fin de la ventana programada. Log: $logPath" | Tee-Object -FilePath $logPath -Append
} finally {
  Set-Location $originalDir
  $env:PYTHONPATH = $originalPyPath
  if ($lockStream) { $lockStream.Dispose() }
}
