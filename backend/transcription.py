import os
import wave
import threading
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

_model: WhisperModel | None = None
_model_lock = threading.Lock()


def transcribe_audio(audio_path: Path) -> str:
    """Transcribe a WAV file locally; the model is downloaded once and then cached."""
    with wave.open(str(audio_path), "rb") as audio_file:
        if audio_file.getnchannels() != 1 or audio_file.getsampwidth() != 2:
            raise ValueError("Voice recording must be mono, 16-bit PCM WAV audio.")
        if audio_file.getframerate() != 16000:
            raise ValueError("Voice recording must use a 16 kHz sample rate.")
        audio = np.frombuffer(audio_file.readframes(audio_file.getnframes()), dtype="<i2")
    audio = audio.astype(np.float32) / 32768.0

    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                model_name = os.getenv("LOCAL_WHISPER_MODEL", "base")
                model_cache = Path.home() / "AppData" / "Local" / "MyAgent" / "whisper-models"
                model_cache.mkdir(parents=True, exist_ok=True)
                _model = WhisperModel(
                    model_name,
                    device="cpu",
                    compute_type="int8",
                    download_root=str(model_cache),
                )

    segments, _ = _model.transcribe(audio, beam_size=5, vad_filter=True)
    return " ".join(segment.text.strip() for segment in segments).strip()
