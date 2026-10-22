[CmdletBinding()]
param(
    [string]$Root = 'C:\Users\enriq\Desktop\Proyectos\Sunset\mia',
    [switch]$Aplicar
)

$ErrorActionPreference = 'Stop'
$paquete = $PSScriptRoot
$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'No se encontro el Python del entorno virtual.' }

$archivos = @(
    'src\mia\modules\rrhh\document_indexing.py',
    'src\mia\modules\rrhh\curriculums\indexer.py'
)
$original = @{
    'src\mia\modules\rrhh\document_indexing.py' = '2c7fb9540ce02be65f5a07c10ecd47e07896da53c4219c0f4841204430fcfd3d'
    'src\mia\modules\rrhh\curriculums\indexer.py' = '1d695cb5077c272e3f1ad517455026754f3703016571c546eb619f0e1f265fa9'
}

foreach ($rel in $archivos) {
    $actual = Join-Path $Root $rel
    $nuevo = Join-Path $paquete $rel
    if (-not (Test-Path -LiteralPath $actual)) { throw "No existe archivo original: $rel" }
    if (-not (Test-Path -LiteralPath $nuevo)) { throw "No existe archivo del parche: $rel" }
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $actual).Hash.ToLowerInvariant()
    if ($hash -ne $original[$rel]) {
        throw "BLOQUEADO: $rel fue modificado respecto a la version auditada. No sobreescribir. SHA256 actual: $hash"
    }
    Write-Host "Validado para parche: $rel"
}

$testRel = 'tests\test_mia_ocr_local.py'
$testDst = Join-Path $Root $testRel
$testSrc = Join-Path $paquete $testRel
if (Test-Path -LiteralPath $testDst) {
    throw 'Ya existe tests\test_mia_ocr_local.py. Revisar manualmente para evitar sobrescribir pruebas existentes.'
}

if (-not $Aplicar) {
    Write-Host 'SIMULACION OK: no se ha cambiado ningun archivo. Para aplicar: .\Aplicar_OCR_Local_mIA.ps1 -Aplicar'
    exit 0
}

$backup = Join-Path $Root ('backup_ocr_local_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach ($rel in $archivos) {
    $backupTarget = Join-Path $backup $rel
    New-Item -ItemType Directory -Path (Split-Path $backupTarget) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root $rel) -Destination $backupTarget
}
Write-Host "Backup: $backup"

try {
    foreach ($rel in $archivos) {
        Copy-Item -LiteralPath (Join-Path $paquete $rel) -Destination (Join-Path $Root $rel) -Force
    }
    Copy-Item -LiteralPath $testSrc -Destination $testDst
    Set-Location $Root
    $env:PYTHONPATH = Join-Path $Root 'src'
    & $python -m pytest 'tests\test_mia_ocr_local.py' -q
    if ($LASTEXITCODE -ne 0) { throw 'Fallaron las pruebas del OCR local.' }
    Write-Host 'PARCHE APLICADO: 2 fuentes, 1 test. No se ha ejecutado indexacion ni sincronizacion.'
    Write-Host "Para revertir, restaure los dos fuentes desde: $backup"
} catch {
    Write-Warning "Error durante la instalacion. Restaurando respaldo: $($_.Exception.Message)"
    foreach ($rel in $archivos) {
        Copy-Item -LiteralPath (Join-Path $backup $rel) -Destination (Join-Path $Root $rel) -Force
    }
    if (Test-Path -LiteralPath $testDst) { Remove-Item -LiteralPath $testDst -Force }
    throw
}
