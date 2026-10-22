"""mIA Desktop V0.3: persistent OFFLINE recognition worker.
No audio/transcripts written to disk or sent across the network.
Messages on stdout are JSONL. The audio callback never blocks on recognition.
"""
import json, sys, time, queue, threading, collections, unicodedata, re, os, wave
from pathlib import Path

RATE = 16000
FRAME_MS = 20
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2
MAX_DURATION = 24.0

def emit(kind, **fields):
    # Only stdout protocol contains content; Electron must never log these lines.
    sys.stdout.write(json.dumps({'type': kind, **fields}, ensure_ascii=False) + '\n')
    sys.stdout.flush()

def norm(s):
    s = ''.join(ch for ch in unicodedata.normalize('NFD', str(s or '').lower()) if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9 ]+', ' ', s).strip().replace('  ', ' ')

def variants(config):
    result = {}
    for cmd, key in [('SHOW', 'show'), ('HIDE', 'hide'), ('EXIT', 'exit')]:
        source = norm(config.get(key, ''))
        entries = {source}
        if 'mia' in source:
            entries.add(source.replace('mia', 'm i a'))
            entries.add(source.replace('mia', 'mía'))
        if cmd == 'SHOW' and source == 'hola mia':
            entries.add('oye mia')
        result[cmd] = {norm(x) for x in entries if norm(x)}
    return result

def classify(phrase, config):
    value = norm(phrase)
    for cmd, choices in variants(config).items():
        if value in choices:
            return cmd
    return None


def confirm_destructive_command(command, pcm_frames, configured, transcriber, np):
    """Reject false Vosk matches. Only a completed utterance independently
    transcribed by Whisper to the same exact hide/exit phrase is authorized.
    Never log or persist the PCM/transcribed words.
    """
    if command not in ('HIDE', 'EXIT') or len(pcm_frames) < 12:
        return False
    try:
        samples = np.frombuffer(b''.join(pcm_frames), dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) < RATE // 3 or float(np.sqrt(np.mean(samples ** 2))) < .003:
            return False
        segments, _ = transcriber.transcribe(samples, language='es', beam_size=1,
            vad_filter=False, condition_on_previous_text=False, temperature=0.0)
        text = ' '.join(part.text.strip() for part in segments).strip()
        return classify(text, configured) == command
    except Exception:
        # Fails closed; a speech model error never hides/closes the application.
        return False

def confirm_dictation_command(command, pcm_frames, configured, model, recognizer_type):
    """Whisper candidate must also be independently recognized by Vosk.
    A mistaken transcription is not permission to hide or exit the desktop.
    """
    if command not in ('HIDE', 'EXIT', 'SHOW') or not pcm_frames:
        return False
    try:
        phrases = sorted({entry for opts in variants(configured).values() for entry in opts})
        phrases.append('[unk]')
        recognition = recognizer_type(model, RATE, json.dumps(phrases, ensure_ascii=False))
        text = ''
        if recognition.AcceptWaveform(b''.join(pcm_frames)):
            text = json.loads(recognition.Result()).get('text', '')
        if not text:
            text = json.loads(recognition.FinalResult()).get('text', '')
        return classify(text, configured) == command
    except Exception:
        return False

def check_models(root):
    vosk_model = root / 'vosk-model-small-es-0.42'
    whisper_dir = root / 'whisper-base'
    return vosk_model, whisper_dir

def run():
    try:
        import sounddevice as sd
        import numpy as np
        from vosk import Model, KaldiRecognizer, SetLogLevel
        from faster_whisper import WhisperModel
        try:
            import webrtcvad
        except ImportError:
            webrtcvad = None
    except Exception:
        emit('ERROR', code='DEPENDENCY_MISSING')
        return 2
    root = Path(sys.argv[1]).resolve()
    vosk_dir, whisper_dir = check_models(root)
    if not vosk_dir.is_dir() or not (whisper_dir / 'model.bin').is_file():
        emit('ERROR', code='MODEL_MISSING')
        return 3
    try:
        SetLogLevel(-1)
        wake_model = Model(str(vosk_dir))
        transcriber = WhisperModel(str(whisper_dir), device='cpu', compute_type='int8', local_files_only=True, cpu_threads=max(1, min(4, os.cpu_count() or 2)))
    except Exception:
        emit('ERROR', code='MODEL_LOAD_FAILED')
        return 4
    messages = queue.Queue(maxsize=300)
    instructions = queue.Queue()
    configured = {'show': 'Hola mIA', 'hide': 'Oculta mIA', 'exit': 'Cierra mIA'}
    grammar = None
    recognizer = None
    stream = None
    active_mode = 'idle'
    dictation_begin = None
    dictation_frames = []
    preroll = collections.deque(maxlen=25)  # 500ms preroll at 20ms
    speech_started = False
    speech_end_counter = 0
    noise_floor = 0.007
    candidate = None
    wake_audio = collections.deque(maxlen=220)  # last 4.4 s; RAM only
    last_command_at = 0.0
    vad = webrtcvad.Vad(2) if webrtcvad else None

    def configure_wake():
        nonlocal grammar, recognizer
        grammar = sorted({entry for opts in variants(configured).values() for entry in opts})
        grammar.append('[unk]')
        recognizer = KaldiRecognizer(wake_model, RATE, json.dumps(grammar, ensure_ascii=False))

    def input_thread():
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if isinstance(command, dict): instructions.put(command)
            except (ValueError, TypeError):
                continue
        instructions.put({'cmd':'shutdown'})

    def audio_callback(indata, frames, time_info, status):
        try:
            # Each block is 320 mono PCM samples (20ms)
            messages.put_nowait(bytes(indata))
        except queue.Full:
            try: messages.get_nowait()
            except queue.Empty: pass
            try: messages.put_nowait(bytes(indata))
            except queue.Full: pass

    def open_microphone():
        nonlocal stream
        if stream is not None:
            return True
        try:
            stream = sd.RawInputStream(samplerate=RATE, blocksize=RATE*FRAME_MS//1000,
                                       dtype='int16', channels=1, callback=audio_callback)
            stream.start()
            return True
        except Exception:
            try:
                if stream is not None: stream.close()
            except Exception:
                pass
            stream = None
            return False

    def close_microphone():
        nonlocal stream
        if stream is not None:
            try: stream.stop()
            except Exception: pass
            try: stream.close()
            except Exception: pass
            stream = None
        # Captured buffers must not leak into a later turn.
        while not messages.empty():
            try: messages.get_nowait()
            except queue.Empty: break

    configure_wake()
    threading.Thread(target=input_thread, daemon=True).start()
    # Models are kept hot while the audio device remains CLOSED by default.
    emit('READY', engine='local-vosk-whisper')

    def process_dictation():
        nonlocal active_mode, dictation_frames, speech_started, speech_end_counter, dictation_begin
        close_microphone()
        active_mode='processing'
        if not speech_started or not dictation_frames:
            emit('DICTATION_ERROR', code='NO_SPEECH')
            active_mode='idle'
            return
        audio = np.frombuffer(b''.join(dictation_frames), dtype=np.int16).astype(np.float32) / 32768.0
        # Do not write audio to temporary files; zero-copy ndarray -> local Whisper
        try:
            segments, metadata = transcriber.transcribe(audio, language='es', beam_size=3,
                vad_filter=True, condition_on_previous_text=False, temperature=0.0)
            words = ' '.join(segment.text.strip() for segment in segments).strip()
            if not words or len(words)>4000:
                emit('DICTATION_ERROR', code='NO_SPEECH')
            else:
                cmd = classify(words, configured)
                if cmd:
                    if confirm_dictation_command(cmd,dictation_frames,configured,wake_model,KaldiRecognizer):
                        emit('DICTATION_COMMAND', command=cmd, verified=True)
                    else:
                        emit('DICTATION_ERROR', code='COMMAND_UNVERIFIED')
                else:
                    emit('TRANSCRIPT', text=words, confidence=None, alternatives=[])
        except Exception:
            emit('DICTATION_ERROR', code='TRANSCRIPTION_FAILED')
        finally:
            active_mode='idle'
            dictation_frames=[]
            speech_started=False
            speech_end_counter=0
            dictation_begin=None

    try:
        while True:
            try:
                while True:
                    ins = instructions.get_nowait()
                    cmd = ins.get('cmd')
                    if cmd=='shutdown':
                        close_microphone()
                        return 0
                    if cmd=='wake':
                        if isinstance(ins.get('phrases'), dict):
                            configured.update({k: str(ins['phrases'][k])[:48] for k in ('show','hide','exit') if k in ins['phrases']})
                        configure_wake()
                        candidate=None
                        wake_audio.clear()
                        if ins.get('enabled'):
                            if open_microphone():
                                active_mode='wake'
                                emit('WAKE_READY')
                            else:
                                active_mode='idle'
                                emit('ERROR',code='MICROPHONE_UNAVAILABLE')
                                emit('WAKE_PAUSED')
                        else:
                            active_mode='idle'
                            close_microphone()
                            emit('WAKE_PAUSED')
                    if cmd=='dictate':
                        if not open_microphone():
                            active_mode='idle'
                            emit('DICTATION_ERROR',code='MICROPHONE_UNAVAILABLE')
                            continue
                        active_mode='dictate'
                        dictation_begin=time.monotonic()
                        dictation_frames=[]
                        speech_started=False
                        speech_end_counter=0
                        preroll.clear()
                        wake_audio.clear()
                        while not messages.empty():
                            try: messages.get_nowait()
                            except queue.Empty: break
                        emit('DICTATION_READY')
                    if cmd=='cancel':
                        if active_mode=='dictate':
                            active_mode='idle'; dictation_frames=[];close_microphone();emit('DICTATION_ERROR',code='CANCELLED')
            except queue.Empty:
                pass
            try:
                pcm = messages.get(timeout=.08)
            except queue.Empty:
                if active_mode=='dictate' and dictation_begin and time.monotonic()-dictation_begin>MAX_DURATION:
                    process_dictation()
                continue
            if active_mode=='wake':
                wake_audio.append(pcm)
                if recognizer.AcceptWaveform(pcm):
                    text=json.loads(recognizer.Result()).get('text','')
                    cmd=classify(text,configured)
                    if cmd and time.monotonic()-last_command_at>1.8:
                        if cmd in ('HIDE','EXIT'):
                            # Never act on a Vosk-only guess. Whisper confirms the
                            # exact phrase from buffered local audio before any hide.
                            if confirm_destructive_command(cmd,list(wake_audio),configured,transcriber,np):
                                emit('COMMAND',command=cmd,verified=True)
                                last_command_at=time.monotonic()
                            else:
                                emit('COMMAND_REJECTED',command=cmd)
                        else:
                            emit('COMMAND',command=cmd)
                            last_command_at=time.monotonic()
                    candidate=None
                    wake_audio.clear()
                else:
                    text=json.loads(recognizer.PartialResult()).get('partial','')
                    cmd=classify(text,configured)
                    # Only SHOW is accepted from a stable partial result.
                    # HIDE and EXIT must wait for final Vosk + independent Whisper.
                    if cmd == 'SHOW':
                        if candidate and candidate[0]==cmd and time.monotonic()-candidate[1]>.22:
                            if time.monotonic()-last_command_at>1.8:
                                emit('COMMAND',command=cmd)
                                last_command_at=time.monotonic()
                                recognizer.Reset()
                                wake_audio.clear()
                            candidate=None
                        elif not candidate or candidate[0]!=cmd:
                            candidate=(cmd,time.monotonic())
                    else:
                        candidate=None
            elif active_mode=='dictate':
                # 500 ms preroll avoids cutting off the start of a phrase.
                preroll.append(pcm)
                volume=float(np.sqrt(np.mean(np.frombuffer(pcm,dtype=np.int16).astype(np.float32)**2)))/32768.0
                is_speech=vad.is_speech(pcm,RATE) if vad else (volume>max(.006,noise_floor*2.8))
                if not speech_started:
                    noise_floor=.985*noise_floor+.015*min(volume,.04)
                    if is_speech:
                        speech_started=True
                        dictation_frames=list(preroll)
                        speech_end_counter=0
                        emit('SPEECH_DETECTED')
                else:
                    dictation_frames.append(pcm)
                    speech_end_counter=0 if is_speech else speech_end_counter+1
                    if speech_end_counter>=34 or (dictation_begin and time.monotonic()-dictation_begin>MAX_DURATION):
                        process_dictation()
                if not speech_started and dictation_begin and time.monotonic()-dictation_begin>10:
                    emit('DICTATION_ERROR',code='NO_SPEECH');active_mode='idle';close_microphone()
    finally:
        close_microphone()

if __name__=='__main__':
    try:
        sys.exit(run())
    except Exception:
        emit('ERROR',code='WORKER_UNEXPECTED_ERROR')
        sys.exit(10)
