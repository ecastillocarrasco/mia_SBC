param(
  [ValidateSet('probe','wake','dictate')][string]$Mode = 'dictate',
  [string]$Phrase = 'Hola mIA',
  [string]$HidePhrase = 'Oculta mIA',
  [string]$ExitPhrase = 'Cierra mIA',
  [ValidateRange(5,45)][int]$TimeoutSeconds = 22
)
$ErrorActionPreference='Stop'
# Windows PowerShell 5.1 supports [Type]::new(). The old New-Object
# System.Text.UTF8Encoding($false) form incorrectly treats arguments as a type.
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Emit([string]$kind, [string]$payload) {
  [Console]::WriteLine($kind + "`t" + $payload)
  [Console]::Out.Flush()
}
try {
  Add-Type -AssemblyName System.Speech -ErrorAction Stop
  $installed = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers())
  $selected = $installed | Where-Object { $_.Culture.Name -eq 'es-ES' } | Select-Object -First 1
  if ($Mode -eq 'probe') {
    $engines = @($installed | ForEach-Object { $_.Culture.Name })
    Emit 'PROBE' (@{available=($null -ne $selected); count=$installed.Count; locales=$engines} | ConvertTo-Json -Compress)
    exit 0
  }
  if ($null -eq $selected) {
    Emit 'ERROR' 'NO_ES_RECOGNIZER|No se ha detectado un reconocedor SAPI de español (es-ES). La voz de lectura instalada no sirve necesariamente para dictado.'
    exit 2
  }
  $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($selected)
  try {
    try { $engine.SetInputToDefaultAudioDevice() }
    catch { Emit 'ERROR' 'NO_MICROPHONE|Windows no permite abrir el dispositivo de entrada de audio predeterminado.'; exit 3 }
    if ($Mode -eq 'wake') {
      # Multiple pronunciation-safe versions of the same configurable command.
      # These are exact grammar alternatives, never fuzzy free dictation.
      $names = @(@{name='SHOW';phrase=$Phrase;limit=0.70},@{name='HIDE';phrase=$HidePhrase;limit=0.74},@{name='EXIT';phrase=$ExitPhrase;limit=0.90})
      $mapping = @{}
      $index = 0
      foreach ($item in $names) {
        $variants = @($item.phrase)
        # SAPI commonly transcribes the acronym as the proper name Mia/Mia-accented.
        if ($item.phrase -match '(?i)\bmia\b') {
          $variants += [regex]::Replace($item.phrase,'(?i)\bmia\b','Mía')
          $variants += [regex]::Replace($item.phrase,'(?i)\bmia\b','mia')
        }
        if ($item.name -eq 'SHOW' -and $item.phrase -match '(?i)^hola\s+m[ií]a$') { $variants += 'Oye Mía' }
        foreach ($variant in ($variants | Select-Object -Unique)) {
          $builder = [System.Speech.Recognition.GrammarBuilder]::new($variant)
          $builder.Culture = $selected.Culture
          $grammar = [System.Speech.Recognition.Grammar]::new($builder)
          $grammar.Name = $item.name + '_' + $index
          $mapping[$grammar.Name] = $item
          $engine.LoadGrammar($grammar)
          $index++
        }
      }
      # Shorter pauses improve command reaction without restarting the recognizer.
      $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(2)
      $engine.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.45)
      $engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromSeconds(0.7)
      Emit 'READY' 'wake'
      while ($true) {
        $heard = $engine.Recognize([TimeSpan]::FromSeconds(3))
        if ($heard) {
          $command = $mapping[$heard.Grammar.Name]
          if ($command -and $heard.Confidence -ge $command.limit) { Emit 'COMMAND' $command.name }
        }
      }
    } else {
      $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(6)
      $engine.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.8)
      $engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromSeconds(1.2)
      $engine.LoadGrammar([System.Speech.Recognition.DictationGrammar]::new())
      Emit 'READY' 'dictate'
      $heard = $engine.Recognize([TimeSpan]::FromSeconds($TimeoutSeconds))
      if ($heard -and $heard.Text -and $heard.Confidence -ge .28) {
        $options = @($heard.Alternates | Select-Object -First 4 | ForEach-Object { @{ text = ($_.Text -replace '[\r\n\t]+',' '); confidence = [Math]::Round($_.Confidence,2) } })
        Emit 'RESULT' (@{ text = ($heard.Text -replace '[\r\n\t]+',' '); confidence = [Math]::Round($heard.Confidence,2); alternatives = $options } | ConvertTo-Json -Compress -Depth 4)
      } else { Emit 'EMPTY' 'not-recognized' }
    }
  } finally { if($engine){$engine.Dispose()} }
} catch {
  # Do not transmit raw PowerShell exception text; it may contain paths or user data.
  $code = 'SAPI_INIT_FAILED'
  if ($_.Exception -is [System.IO.FileNotFoundException]) { $code = 'SAPI_ASSEMBLY_MISSING' }
  Emit 'ERROR' ($code + '|No se ha podido iniciar el motor de voz. Revisa el diagnóstico de Windows y los motores de reconocimiento instalados.')
  exit 1
}
