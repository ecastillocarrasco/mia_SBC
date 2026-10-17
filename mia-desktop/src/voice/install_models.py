"""Install offline models to a user-selected directory; no microphone access."""
import os, sys, io, zipfile, urllib.request
from pathlib import Path

VOSK_URL='https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip'

def main():
    root=Path(sys.argv[1]).resolve()
    root.mkdir(parents=True,exist_ok=True)
    dest=root/'vosk-model-small-es-0.42'
    if not dest.is_dir():
        print('Descargando modelo español Vosk (solo descarga del modelo, sin audio personal)...',flush=True)
        archive=root/'vosk-model-small-es-0.42.zip'
        try:
            urllib.request.urlretrieve(VOSK_URL,archive)
            with zipfile.ZipFile(archive) as z:
                for item in z.infolist():
                    p=(root/item.filename).resolve()
                    if not p.is_relative_to(root):
                        raise RuntimeError('Ruta insegura en ZIP del modelo')
                z.extractall(root)
        finally:
            archive.unlink(missing_ok=True)
    from huggingface_hub import snapshot_download
    model_dir=root/'whisper-base'
    if not (model_dir/'model.bin').exists():
        print('Descargando modelo Whisper base cuantizable (sin envío de audio)...',flush=True)
        snapshot_download(repo_id='Systran/faster-whisper-base',local_dir=str(model_dir),
                          allow_patterns=['model.bin','config.json','tokenizer.json','vocabulary.*','preprocessor_config.json'])
    if not (model_dir/'model.bin').is_file():
        raise RuntimeError('Whisper no se ha descargado correctamente')
    print('Motores locales preparados. Cierra y vuelve a abrir mIA Desktop.',flush=True)

if __name__=='__main__':main()
