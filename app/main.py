"""
Piper TTS Microservice - CPU Optimized v3.1
Aggressive optimizations for low latency
"""
import os
import uuid
import re
import io
import wave
from pathlib import Path
from typing import Literal
from contextlib import asynccontextmanager

import numpy as np
from scipy import signal

from piper import PiperVoice

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, field_validator


# Configuration
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/app/models"))
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
AUDIO_DIR = Path("/audio")
STATIC_DIR = Path(__file__).parent / "static"

# Voice configuration - using MEDIUM models for speed
VOICE_CONFIG = {
    "en_US": {
        "model_path": MODELS_DIR / "en_US-ryan-medium.onnx",
        "name": "English (US)",
        "length_scale": 1.03,
        "noise_scale": 0.667,
        "noise_w": 0.75,
    },
    "es_MX": {
        "model_path": MODELS_DIR / "es_MX-claude-medium.onnx",
        "name": "Español (México)",
        "length_scale": 1.1,
        "noise_scale": 0.7,
        "noise_w": 0.9,
    },
}

DEFAULT_VOICE = "es_MX"

# Global state
voices: dict[str, PiperVoice] = {}

# Pre-computed filter coefficients (computed once at startup)
RADIO_FILTERS = {}


def precompute_filters():
    """Pre-compute filter coefficients for radio effect."""
    # For 22050 Hz (typical Piper output)
    sample_rate = 22050
    nyquist = sample_rate / 2

    # Bandpass 300-3400Hz
    low = 300 / nyquist
    high = 3400 / nyquist
    RADIO_FILTERS["bandpass_sos"] = signal.butter(3, [low, high], btype='band', output='sos')

    # Noise filter
    RADIO_FILTERS["noise_sos"] = signal.butter(2, [200 / nyquist, 4000 / nyquist], btype='band', output='sos')
    RADIO_FILTERS["sample_rate"] = sample_rate


def load_voices():
    """Load voice models at startup."""
    for voice_id, config in VOICE_CONFIG.items():
        model_path = config["model_path"]
        if model_path.exists():
            try:
                voices[voice_id] = PiperVoice.load(
                    str(model_path),
                    config_path=str(model_path) + ".json",
                    use_cuda=False,
                )
                print(f"[OK] Loaded: {voice_id}")
            except Exception as e:
                print(f"[ERR] {voice_id}: {e}")
        else:
            print(f"[MISS] {model_path}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    precompute_filters()
    load_voices()
    yield
    voices.clear()


app = FastAPI(
    title="Piper TTS Service",
    description="Race radio TTS - optimized",
    version="3.1.0",
    lifespan=lifespan,
)

app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")


class TTSRequest(BaseModel):
    text: str
    voice: Literal["en_US", "es_MX"] = DEFAULT_VOICE
    radio_effect: bool = True

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Text cannot be empty")
        if len(v) > 5000:
            raise ValueError("Text too long (max 5000)")
        return v


class TTSResponse(BaseModel):
    url: str
    voice: str
    radio_effect: bool


class VoiceInfo(BaseModel):
    id: str
    name: str
    available: bool


def sanitize_filename(filename: str) -> str:
    safe_name = re.sub(r'[^a-zA-Z0-9\-]', '', filename.replace('.wav', ''))
    return f"{safe_name}.wav"


def apply_radio_effect_fast(audio: np.ndarray) -> np.ndarray:
    """
    Fast radio effect - no resampling, pre-computed filters.
    """
    # 1. Bandpass filter (pre-computed SOS)
    audio = signal.sosfilt(RADIO_FILTERS["bandpass_sos"], audio)

    # 2. Simple compression (vectorized)
    threshold = 0.15
    ratio = 4.0
    sign = np.sign(audio)
    abs_audio = np.abs(audio)
    mask = abs_audio > threshold
    audio = np.where(mask, sign * (threshold + (abs_audio - threshold) / ratio), audio)

    # 3. Normalize
    max_val = np.max(np.abs(audio))
    if max_val > 0.01:
        audio = audio * (0.85 / max_val)

    # 4. Soft saturation
    audio = np.tanh(audio * 1.3)

    # 5. Add noise
    noise = np.random.normal(0, 0.012, len(audio)).astype(np.float32)
    noise = signal.sosfilt(RADIO_FILTERS["noise_sos"], noise)
    audio = audio + noise

    # Final normalize
    max_val = np.max(np.abs(audio))
    if max_val > 0.01:
        audio = audio * (0.92 / max_val)

    return audio.astype(np.float32)


def synthesize_to_file(
    text: str,
    voice_id: str,
    apply_radio: bool,
    output_path: Path
) -> None:
    """Synthesize audio directly to file."""
    voice = voices.get(voice_id)
    if not voice:
        raise RuntimeError(f"Voice not loaded: {voice_id}")

    config = VOICE_CONFIG[voice_id]

    # Synthesize to memory buffer
    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, 'wb') as wav_file:
        voice.synthesize(
            text,
            wav_file,
            length_scale=config["length_scale"],
            noise_scale=config["noise_scale"],
            noise_w=config["noise_w"],
        )

    # Read raw audio
    audio_buffer.seek(0)
    with wave.open(audio_buffer, 'rb') as wav_file:
        sample_rate = wav_file.getframerate()
        audio_bytes = wav_file.readframes(wav_file.getnframes())

    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # Apply radio effect
    if apply_radio:
        audio = apply_radio_effect_fast(audio)

    # Write output
    audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(output_path), 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_int16.tobytes())


@app.get("/voices", response_model=list[VoiceInfo])
async def list_voices():
    return [
        VoiceInfo(id=vid, name=cfg["name"], available=vid in voices)
        for vid, cfg in VOICE_CONFIG.items()
    ]


@app.post("/tts", response_model=TTSResponse)
async def text_to_speech(request: TTSRequest):
    if request.voice not in voices:
        raise HTTPException(503, f"Voice not available: {request.voice}")

    file_id = str(uuid.uuid4())
    filename = sanitize_filename(f"{file_id}.wav")
    output_path = AUDIO_DIR / filename

    try:
        output_path.resolve().relative_to(AUDIO_DIR.resolve())
    except ValueError:
        raise HTTPException(400, "Invalid filename")

    try:
        await run_in_threadpool(
            synthesize_to_file,
            request.text,
            request.voice,
            request.radio_effect,
            output_path
        )
    except Exception as e:
        raise HTTPException(500, f"TTS failed: {e}")

    return TTSResponse(
        url=f"{BASE_URL.rstrip('/')}/audio/{filename}",
        voice=request.voice,
        radio_effect=request.radio_effect
    )


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "voices": {v: v in voices for v in VOICE_CONFIG},
    }


@app.get("/")
async def serve_frontend():
    return FileResponse(STATIC_DIR / "index.html")
