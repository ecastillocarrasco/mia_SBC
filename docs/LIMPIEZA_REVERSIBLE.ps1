# mIA SBC V4: limpieza reversible de assets de desarrollo.
# Por defecto NO modifica nada. Solo informa de los candidatos.
# Uso: powershell -ExecutionPolicy Bypass -File .\LIMPIEZA_REVERSIBLE.ps1 -Frontend "C:\ruta\frontend"
# Para mover (despues de probar): agregar -Aplicar
param(
  [Parameter(Mandatory=$true)][string]$Frontend,
  [switch]$Aplicar
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $Frontend).Path
$public = Join-Path $root 'public'
$archive = Join-Path $root '_MIA_ASSETS_FUENTE_ARCHIVO'
$items = @('assets\blender', 'assets\rigs', 'assets\meshy')

Write-Host "Origen: $public"
Write-Host "Archivo privado: $archive"
Write-Host "Modo: $(if ($Aplicar) {'MOVER (REVERSIBLE)'} else {'SOLO AUDITORIA'})"

foreach ($rel in $items) {
  $source = Join-Path $public $rel
  $destination = Join-Path $archive $rel
  if (-not (Test-Path -LiteralPath $source)) {
    Write-Host "Omitido (no existe): $source"
    continue
  }
  $files = @(Get-ChildItem -LiteralPath $source -File -Recurse -Force)
  $total = ($files | Measure-Object -Property Length -Sum).Sum
  Write-Host ("{0}: {1} archivos, {2:N1} MiB" -f $rel, $files.Count, ($total / 1MB))
  if (-not $Aplicar) { continue }
  if (Test-Path -LiteralPath $destination) {
    throw "Destino existente, no se sobrescribe: $destination"
  }
  New-Item -ItemType Directory -Path (Split-Path $destination) -Force | Out-Null
  Move-Item -LiteralPath $source -Destination $destination
  Write-Host "Movido a: $destination"
}

Write-Host "AVISO: No se ha modificado dist, models, assets/avatar ni mia-assets."
Write-Host "No borres los maestros. Reconstuye dist con npm run build solo tras validar V4."
