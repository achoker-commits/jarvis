"""
audio_utils.py — Utilitaires audio pour JARVIS
Enregistrement via sounddevice (pas besoin de portaudio séparé),
réduction de bruit noisereduce, lecture via afplay/sounddevice.
"""

import collections
import io
import struct
import wave
import time
import math
import logging
import queue
import tempfile
import os
import sys
from typing import Optional

import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)

# Mettre à True quand l'UI Qt est active — supprime les prints terminal
GUI_MODE: bool = False

SAMPLE_RATE = 16000
CHANNELS = 1
FRAME_DURATION_MS = 30
# 30ms à 16kHz = 480 samples = 960 bytes
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)

try:
    import webrtcvad
    _VAD_AVAILABLE = True
except ImportError:
    _VAD_AVAILABLE = False
    logger.warning("webrtcvad non disponible — fallback RMS activé")

try:
    import noisereduce as nr
    _NR_AVAILABLE = True
except ImportError:
    _NR_AVAILABLE = False
    logger.warning("noisereduce non disponible — réduction de bruit désactivée")


# ---------------------------------------------------------------------------
# Construction header WAV
# ---------------------------------------------------------------------------

def build_wav_bytes(raw_pcm: bytes, sample_rate: int = SAMPLE_RATE, channels: int = CHANNELS) -> bytes:
    """Emballe des bytes PCM bruts dans un fichier WAV en mémoire."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16 bits = 2 octets
        wf.setframerate(sample_rate)
        wf.writeframes(raw_pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# RMS Energy
# ---------------------------------------------------------------------------

def get_rms(audio_chunk: bytes) -> float:
    """Calcule le RMS d'un chunk audio PCM 16 bits (NumPy ~10x plus rapide qu'une boucle Python)."""
    count = len(audio_chunk) // 2
    if count == 0:
        return 0.0
    arr = np.frombuffer(audio_chunk[:count * 2], dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(arr * arr)))


# ---------------------------------------------------------------------------
# Visualisation waveform
# ---------------------------------------------------------------------------

def _waveform_bar(rms: float, max_rms: float = 3000, width: int = 30) -> str:
    """Barre ASCII proportionnelle au niveau RMS."""
    level = min(int((rms / max(max_rms, 1)) * width), width)
    bar = "█" * level + "░" * (width - level)
    return f"[{bar}] {int(rms):5d}"


# ---------------------------------------------------------------------------
# Enregistrement audio avec VAD (sounddevice)
# ---------------------------------------------------------------------------

def record_audio_vad(
    max_seconds: int = 30,
    silence_duration: float = 0.8,
    sample_rate: int = SAMPLE_RATE,
    pre_speech_buffer_ms: int = 400,
) -> bytes:
    """
    Enregistre l'audio via sounddevice jusqu'à silence_duration secondes de silence.
    Utilise un pré-buffer pour capturer l'audio juste avant la détection vocale.
    Utilise webrtcvad si disponible, sinon fallback RMS.
    Retourne des bytes WAV complets (avec header).
    """
    audio_queue: queue.Queue = queue.Queue()

    def _callback(indata, frames, time_info, status):
        audio_queue.put(indata[:, 0].tobytes())

    vad = None
    if _VAD_AVAILABLE:
        try:
            vad = webrtcvad.Vad(2)  # Mode 2 = équilibré — ne coupe pas les pauses naturelles
        except Exception as e:
            logger.warning(f"Échec init webrtcvad : {e}")

    # Pré-buffer circulaire : capture les dernières ~400ms avant la parole
    pre_buffer_frames = int((pre_speech_buffer_ms / 1000) * (1000 / FRAME_DURATION_MS))
    pre_buffer: collections.deque = collections.deque(maxlen=pre_buffer_frames)

    recorded_frames = []
    silence_frames = 0
    max_silence_frames = int((silence_duration * 1000) / FRAME_DURATION_MS)
    max_frames = int((max_seconds * 1000) / FRAME_DURATION_MS)
    frame_count = 0
    started = False

    if not GUI_MODE:
        print("\n  Enregistrement...\n")

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=CHANNELS,
            dtype="int16",
            blocksize=FRAME_SIZE,
            callback=_callback,
            latency="low",
        ):
            while frame_count < max_frames:
                try:
                    frame = audio_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                rms = get_rms(frame)
                if not GUI_MODE:
                    print(f"\r  {_waveform_bar(rms)}", end="", flush=True)

                # Détection voix
                is_speech = False
                if vad:
                    try:
                        is_speech = vad.is_speech(frame, sample_rate)
                    except Exception:
                        is_speech = rms > 500
                else:
                    is_speech = rms > 500

                if is_speech:
                    if not started:
                        started = True
                        if not GUI_MODE:
                            print("\n  [Voix détectée]", flush=True)
                        recorded_frames.extend(pre_buffer)
                        pre_buffer.clear()
                    recorded_frames.append(frame)
                    silence_frames = 0
                else:
                    if started:
                        recorded_frames.append(frame)
                        silence_frames += 1
                        # Seuil adaptatif : phrase courte (<1.5s de parole) → silence plus court (0.5s)
                        speech_duration_s = len(recorded_frames) * FRAME_DURATION_MS / 1000
                        adaptive_silence = max_silence_frames
                        if speech_duration_s < 1.5:
                            adaptive_silence = max(int(max_silence_frames * 0.5), 8)
                        if silence_frames >= adaptive_silence:
                            if not GUI_MODE:
                                print("\n  [Silence — arrêt]", flush=True)
                            break
                    else:
                        pre_buffer.append(frame)

                frame_count += 1

    except Exception as e:
        logger.error(f"Erreur enregistrement : {e}")

    if not GUI_MODE:
        print()

    if not recorded_frames:
        logger.warning("Aucune trame audio enregistrée")
        silent = b"\x00" * (sample_rate * 1 * 2)
        return build_wav_bytes(silent, sample_rate)

    raw_pcm = b"".join(recorded_frames)
    return build_wav_bytes(raw_pcm, sample_rate)


# ---------------------------------------------------------------------------
# Réduction de bruit
# ---------------------------------------------------------------------------

def apply_noise_reduction(audio_bytes: bytes) -> bytes:
    """
    Applique une réduction de bruit sur les bytes WAV.
    Utilise les 0.5 premières secondes comme profil de bruit ambiant.
    Skip si : clip < 1s, ou SNR > 20dB (audio déjà propre — gagne 200-400ms).
    """
    if not _NR_AVAILABLE:
        return audio_bytes
    if len(audio_bytes) < 32000 * 2:   # < ~1s à 16kHz 16-bit mono
        return audio_bytes

    try:
        buf = io.BytesIO(audio_bytes)
        with wave.open(buf, "rb") as wf:
            sample_rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())

        audio_array = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

        noise_samples = int(sample_rate * 0.5)
        noise_profile = audio_array[:noise_samples]

        if len(noise_profile) < 100:
            return audio_bytes

        # Estimation SNR rapide : si audio propre, skip (~200-400ms économisés)
        noise_rms = float(np.sqrt(np.mean(noise_profile ** 2))) + 1e-9
        signal_rms = float(np.sqrt(np.mean(audio_array[noise_samples:] ** 2))) + 1e-9
        snr_db = 20 * math.log10(signal_rms / noise_rms)
        if snr_db > 20.0:
            logger.debug(f"SNR {snr_db:.1f}dB — réduction de bruit skippée (audio propre)")
            return audio_bytes

        reduced = nr.reduce_noise(
            y=audio_array,
            y_noise=noise_profile,
            sr=sample_rate,
            stationary=True,
        )

        reduced_int16 = (reduced * 32768.0).clip(-32768, 32767).astype(np.int16)
        return build_wav_bytes(reduced_int16.tobytes(), sample_rate)

    except Exception as e:
        logger.warning(f"Réduction de bruit échouée : {e}")
        return audio_bytes


# ---------------------------------------------------------------------------
# Lecture audio
# ---------------------------------------------------------------------------

_OUTPUT_SAMPLERATE = 44100  # taux de sortie standard macOS (évite err='-50' CoreAudio)


def play_audio_bytes(audio_bytes: bytes, fmt: str = "mp3") -> None:
    """
    Joue des bytes audio (MP3 ou WAV).
    MP3 → toujours afplay/subprocess (libsndfile 1.1+ décode le MP3 mais
    sd.play(data, 24000) déclenche PaMacCore err='-50' car CoreAudio refuse
    24kHz sur le device de sortie macOS par défaut).
    WAV/PCM → sounddevice en mémoire (pas de tempfile).
    """
    if not audio_bytes:
        return

    # WAV/PCM uniquement : sounddevice en mémoire avec samplerate explicite
    if fmt not in ("mp3", "mpeg"):
        try:
            buf = io.BytesIO(audio_bytes)
            data, samplerate = sf.read(buf, dtype="float32")
            # Rééchantillonner si nécessaire pour éviter err='-50' CoreAudio
            if samplerate != _OUTPUT_SAMPLERATE and len(data) > 0:
                import numpy as _np
                ratio = _OUTPUT_SAMPLERATE / samplerate
                new_len = int(len(data) * ratio)
                indices = _np.linspace(0, len(data) - 1, new_len)
                data = _np.interp(indices, _np.arange(len(data)), data if data.ndim == 1
                                  else data[:, 0]).astype(_np.float32)
            sd.play(data, _OUTPUT_SAMPLERATE)
            sd.wait()
            sd.stop()
            return
        except Exception:
            pass  # fallback subprocess

    # Fichier temporaire + outil système
    tmp_path = None
    try:
        suffix = f".{fmt}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        import subprocess
        if sys.platform == "darwin":
            subprocess.run(["afplay", tmp_path], check=True, capture_output=True)
        elif sys.platform.startswith("linux"):
            if fmt == "mp3":
                subprocess.run(["mpg123", "-q", tmp_path], check=True, capture_output=True)
            else:
                subprocess.run(["aplay", "-q", tmp_path], check=True, capture_output=True)
        else:
            os.startfile(tmp_path)
            time.sleep(3)

    except subprocess.CalledProcessError as e:
        import signal as _signal
        if e.returncode == -_signal.SIGINT or e.returncode == -2:
            pass  # Interruption normale (Ctrl+C ou stop_event) — pas une erreur
        else:
            logger.warning(f"Lecteur audio code {e.returncode} : {e.cmd}")
    except Exception as e:
        logger.error(f"Impossible de lire l'audio : {e}")
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def play_wav_file(filepath: str) -> None:
    """Joue un fichier WAV depuis le disque."""
    try:
        with open(filepath, "rb") as f:
            data = f.read()
        play_audio_bytes(data, fmt="wav")
    except Exception as e:
        logger.error(f"Impossible de lire {filepath} : {e}")


# ---------------------------------------------------------------------------
# Utilitaires microphone
# ---------------------------------------------------------------------------

def list_microphones() -> list:
    """Retourne la liste des microphones disponibles via sounddevice."""
    try:
        devices = sd.query_devices()
        micros = []
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                micros.append({
                    "index": i,
                    "name": dev.get("name", "Inconnu"),
                    "channels": dev.get("max_input_channels"),
                    "sample_rate": int(dev.get("default_samplerate", 44100)),
                })
        return micros
    except Exception as e:
        logger.error(f"Erreur liste micros : {e}")
        return []


def play_beep(frequency: int = 880, duration: float = 0.15) -> None:
    """Joue un bip de confirmation (tone sinusoïdal) via sounddevice.
    Utilise 44100 Hz (standard macOS) — 16000 Hz (taux STT) cause err='-50' CoreAudio."""
    try:
        t = np.linspace(0, duration, int(_OUTPUT_SAMPLERATE * duration), endpoint=False)
        wave_data = (0.3 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)
        sd.play(wave_data, _OUTPUT_SAMPLERATE)
        sd.wait()
    except Exception:
        print("\a", end="", flush=True)
