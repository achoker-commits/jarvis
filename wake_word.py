"""
wake_word.py — Détection du mot de réveil pour JARVIS
3 stratégies : Porcupine → Vosk → Clavier (ESPACE/Entrée)
Utilise sounddevice pour la capture audio (pas de PyAudio requis).
"""

import logging
import struct
import sys
import time
import queue
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

# Imports optionnels
try:
    import pvporcupine
    _PORCUPINE_AVAILABLE = True
except ImportError:
    _PORCUPINE_AVAILABLE = False

try:
    from vosk import Model as VoskModel, KaldiRecognizer
    import json as _json
    _VOSK_AVAILABLE = True
except ImportError:
    _VOSK_AVAILABLE = False

try:
    import keyboard
    _KEYBOARD_AVAILABLE = True
except ImportError:
    _KEYBOARD_AVAILABLE = False

try:
    from openwakeword.model import Model as OWWModel
    import openwakeword
    _OWW_AVAILABLE = True
except ImportError:
    _OWW_AVAILABLE = False

try:
    from faster_whisper import WhisperModel as _FasterWhisper
    _WHISPER_KW_AVAILABLE = True
except ImportError:
    _WHISPER_KW_AVAILABLE = False


class WakeWordDetector:
    """
    Détecteur de mot de réveil avec détection automatique de stratégie.

    Priorité :
    1. Porcupine (si clé API fournie)
    2. Vosk (si modèle local disponible)
    3. Clavier ESPACE / Entrée (toujours disponible)
    """

    STRATEGY_PORCUPINE  = "porcupine"
    STRATEGY_WHISPER_KW = "whisper_kw"   # Whisper tiny — détecte "Jarvis" seul
    STRATEGY_OWW        = "openwakeword"  # OWW — nécessite "Hey Jarvis"
    STRATEGY_VOSK       = "vosk"
    STRATEGY_KEYBOARD   = "keyboard"

    def __init__(
        self,
        keyword: str = "jarvis",
        porcupine_key: Optional[str] = None,
        vosk_model_path: Optional[str] = None,
        sample_rate: int = 16000,
    ):
        self.keyword = keyword.lower()
        self.porcupine_key = porcupine_key
        self.vosk_model_path = vosk_model_path
        self.sample_rate = sample_rate

        self._porcupine = None
        self._vosk_model = None
        self._vosk_rec = None
        self._oww_model = None
        self._oww_threshold = 0.15
        self._kw_model = None         # Whisper tiny pour keyword spotting

        # Cooldown inter-appels + garde TTS
        self._last_trigger_time: float = 0.0  # persiste entre appels successifs
        self._muted: bool = False              # True pendant que TTS parle

        self.strategy = self._detect_strategy()
        logger.info(f"Stratégie wake word : {self.strategy}")
        self._init_strategy()

    def _detect_strategy(self) -> str:
        import os
        forced = os.getenv("WAKE_STRATEGY", "").lower()
        if forced == "keyboard":
            return self.STRATEGY_KEYBOARD
        if forced == "oww":
            return self.STRATEGY_OWW
        if forced == "whisper_kw":
            return self.STRATEGY_WHISPER_KW

        if self.porcupine_key and _PORCUPINE_AVAILABLE:
            return self.STRATEGY_PORCUPINE
        # Whisper KW en priorité : "Jarvis" seul sans "Hey"
        if _WHISPER_KW_AVAILABLE:
            return self.STRATEGY_WHISPER_KW
        if _OWW_AVAILABLE:
            return self.STRATEGY_OWW
        if _VOSK_AVAILABLE and self.vosk_model_path:
            if Path(self.vosk_model_path).is_dir():
                return self.STRATEGY_VOSK
        return self.STRATEGY_KEYBOARD

    def _init_strategy(self) -> None:
        if self.strategy == self.STRATEGY_PORCUPINE:
            self._init_porcupine()
        elif self.strategy == self.STRATEGY_WHISPER_KW:
            self._init_whisper_kw()
        elif self.strategy == self.STRATEGY_OWW:
            self._init_oww()
        elif self.strategy == self.STRATEGY_VOSK:
            self._init_vosk()

    def _init_porcupine(self) -> None:
        try:
            self._porcupine = pvporcupine.create(
                access_key=self.porcupine_key,
                keywords=["jarvis"],
            )
            logger.info("Porcupine initialisé avec succès")
        except Exception as e:
            logger.error(f"Échec init Porcupine : {e} — passage au clavier")
            self.strategy = self.STRATEGY_KEYBOARD

    def _init_oww(self) -> None:
        """Initialise OpenWakeWord avec le modèle hey_jarvis."""
        try:
            logger.info("Chargement OpenWakeWord hey_jarvis...")
            self._oww_model = OWWModel(
                wakeword_models=["hey jarvis"],
                inference_framework="onnx",
            )
            logger.info("OpenWakeWord hey_jarvis initialisé — dites 'Hey Jarvis' !")
        except Exception as e:
            logger.error(f"Échec init OpenWakeWord : {e} — passage au clavier")
            self.strategy = self.STRATEGY_KEYBOARD

    def _init_vosk(self) -> None:
        try:
            logger.info(f"Chargement modèle Vosk depuis {self.vosk_model_path}...")
            self._vosk_model = VoskModel(self.vosk_model_path)
            grammar = _json.dumps([self.keyword, "[unk]"])
            self._vosk_rec = KaldiRecognizer(self._vosk_model, self.sample_rate, grammar)
            logger.info("Vosk initialisé avec succès")
        except Exception as e:
            logger.error(f"Échec init Vosk : {e} — passage au clavier")
            self.strategy = self.STRATEGY_KEYBOARD

    # ------------------------------------------------------------------
    # Méthode principale
    # ------------------------------------------------------------------

    def listen_for_wake_word(self) -> bool:
        """Bloque jusqu'à la détection du mot de réveil. Retourne True."""
        if self.strategy == self.STRATEGY_PORCUPINE:
            return self._listen_porcupine()
        elif self.strategy == self.STRATEGY_WHISPER_KW:
            return self._listen_whisper_kw()
        elif self.strategy == self.STRATEGY_OWW:
            return self._listen_oww()
        elif self.strategy == self.STRATEGY_VOSK:
            return self._listen_vosk()
        else:
            return self._listen_keyboard()

    # ------------------------------------------------------------------
    # Stratégie : Whisper KW — dit juste "Jarvis", sans "Hey"
    # ------------------------------------------------------------------

    def _init_whisper_kw(self) -> None:
        """Charge faster-whisper tiny en mémoire pour le keyword spotting."""
        try:
            logger.info("Chargement Whisper tiny pour keyword spotting...")
            # Tenter d'abord depuis le cache local (évite la requête HuggingFace)
            try:
                self._kw_model = _FasterWhisper(
                    "tiny", device="cpu", compute_type="int8",
                    local_files_only=True
                )
            except Exception:
                self._kw_model = _FasterWhisper("tiny", device="cpu", compute_type="int8")
            logger.info("Whisper KW prêt — dites 'Jarvis' pour activer")
        except Exception as e:
            logger.warning(f"Whisper KW échoué : {e} — fallback OWW/clavier")
            self._kw_model = None
            if _OWW_AVAILABLE:
                self.strategy = self.STRATEGY_OWW
                self._init_oww()
            else:
                self.strategy = self.STRATEGY_KEYBOARD

    # ------------------------------------------------------------------
    # Helpers matching flou
    # ------------------------------------------------------------------

    @staticmethod
    def _lev_ratio(a: str, b: str) -> float:
        """Ratio de similarité Levenshtein normalisé [0, 1] — 1 = identique."""
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        la, lb = len(a), len(b)
        row = list(range(lb + 1))
        for i, ca in enumerate(a, 1):
            new_row = [i]
            for j, cb in enumerate(b, 1):
                new_row.append(
                    row[j - 1] if ca == cb
                    else 1 + min(row[j], new_row[-1], row[j - 1])
                )
            row = new_row
        return 1.0 - row[lb] / max(la, lb)

    def _is_keyword(self, text: str) -> bool:
        """
        True si 'text' contient une variante du mot-clé.
        Combine alias exacts + Levenshtein normalisé (seuil 0.75).
        """
        _ALIASES = {
            # Transcriptions correctes ou quasi-correctes
            "jarvis", "jarvi", "jarv", "jarves", "jarwis", "jarvais",
            "jarvice", "jarve", "jarvees",
            # Confusions phonétiques courantes (Whisper tiny FR)
            "gervais", "gervals", "harvey", "garvis", "garvey",
            "djarvis", "tchervis", "java",
            # Fragments / homophones
            "jarv",
        }
        words = text.lower().split()
        for word in words:
            clean = word.strip(".,!?;:'\"")
            if not clean:
                continue
            if clean in _ALIASES:
                return True
            if self._lev_ratio(clean, self.keyword) >= 0.75:
                return True
        return False

    # ------------------------------------------------------------------
    # Stratégie : Whisper KW — dit juste "Jarvis", sans "Hey"
    # ------------------------------------------------------------------

    def _listen_whisper_kw(self) -> bool:
        """
        Écoute permanente via fenêtre glissante + Whisper tiny.
        Buffer circulaire de 1.5 s analysé toutes les 0.5 s — garantit que
        "Jarvis" tombe toujours entièrement dans au moins une fenêtre.
        Matching flou : alias + Levenshtein normalisé ≥ 0.75.
        """
        if not self._kw_model:
            return self._listen_keyboard()

        import os, tempfile
        from collections import deque as _deque
        from audio_utils import build_wav_bytes, get_rms, GUI_MODE

        CHUNK        = 480    # 30 ms @ 16 kHz
        WIN_CHUNKS   = 50     # fenêtre 1.5 s (50 × 30 ms)
        STEP_CHUNKS  = 17     # analyse toutes les ~0.5 s
        RMS_THRESH   = 400    # seuil énergie (légèrement abaissé vs 500)
        ENERGY_RATIO = 0.15   # ≥ 15 % des frames doivent avoir de l'énergie
        COOLDOWN     = 3.0    # secondes entre deux détections

        audio_q: queue.Queue = queue.Queue()

        def _cb(indata, frames, time_info, status):
            audio_q.put(indata[:, 0].tobytes())

        import threading
        _triggered = threading.Event()

        def _kb_thread():
            try:
                input()
                _triggered.set()
            except Exception:
                pass

        threading.Thread(target=_kb_thread, daemon=True).start()

        if not GUI_MODE:
            print(f"\n  \033[36m●\033[0m  Dites  \033[1;36mJARVIS\033[0m  (ou appuyez sur Entrée)\n")

        try:
            with sd.InputStream(
                samplerate=16000, channels=1, dtype="int16",
                blocksize=CHUNK, callback=_cb, latency="low",
            ):
                ring         = _deque(maxlen=WIN_CHUNKS)  # buffer circulaire
                step_counter = 0
                # startup_grace : ignorer les WIN_CHUNKS premières frames (1.5 s)
                # pour laisser l'écho TTS résiduel se dissiper au démarrage
                startup_grace = WIN_CHUNKS

                while True:
                    if _triggered.is_set():
                        logger.info("Activation manuelle clavier")
                        self._play_activation_sound()
                        return True

                    try:
                        frame = audio_q.get(timeout=0.5)
                    except queue.Empty:
                        continue

                    ring.append(frame)
                    if startup_grace > 0:
                        startup_grace -= 1
                        continue  # période de grâce : accumule sans analyser

                    step_counter += 1
                    if step_counter < STEP_CHUNKS:
                        continue
                    step_counter = 0

                    # Garde TTS active ou cooldown inter-appels
                    if self._muted:
                        continue
                    now = time.time()
                    if now - self._last_trigger_time < COOLDOWN:
                        continue

                    # Vérifier qu'il y a de la parole dans la fenêtre
                    energy_ct = sum(1 for f in ring if get_rms(f) > RMS_THRESH)
                    if energy_ct < len(ring) * ENERGY_RATIO:
                        continue  # silence → pas d'analyse

                    # Transcrire la fenêtre glissante
                    raw = b"".join(ring)
                    if len(raw) < 3000:
                        continue

                    tmp_path = None
                    try:
                        wav = build_wav_bytes(raw)
                        with tempfile.NamedTemporaryFile(
                            suffix=".wav", delete=False, prefix="jarvis_kw_"
                        ) as f:
                            f.write(wav)
                            tmp_path = f.name

                        segs, _ = self._kw_model.transcribe(
                            tmp_path,
                            language="fr",
                            beam_size=1,
                            temperature=0.0,
                            no_speech_threshold=0.6,
                        )
                        text = " ".join(s.text for s in segs).lower().strip()

                        # Toujours logguer ce que tiny entend — clé pour la calibration
                        if text:
                            logger.info(f"[KW] tiny a entendu : '{text}'")

                        if self._is_keyword(text):
                            if not GUI_MODE:
                                print(f"\n  \033[32m✓ '{text}' → JARVIS activé\033[0m")
                            logger.info(f"Wake word détecté : '{text}'")
                            # Cooldown persistant + vider ring + drainer queue
                            self._last_trigger_time = time.time()
                            ring.clear()
                            try:
                                while True:
                                    audio_q.get_nowait()
                            except queue.Empty:
                                pass
                            self._play_activation_sound()
                            return True

                    except Exception as e:
                        logger.debug(f"KW transcription err : {e}")
                    finally:
                        if tmp_path:
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass

                    # Rattraper les frames accumulées pendant la transcription
                    try:
                        while True:
                            ring.append(audio_q.get_nowait())
                    except queue.Empty:
                        pass

        except Exception as e:
            logger.error(f"Erreur Whisper KW : {e}")
            return self._listen_keyboard()

    # ------------------------------------------------------------------
    # Stratégie 1 : Porcupine
    # ------------------------------------------------------------------

    def _listen_porcupine(self) -> bool:
        if not self._porcupine:
            return self._listen_keyboard()

        frame_length = self._porcupine.frame_length
        audio_queue: queue.Queue = queue.Queue()

        def _callback(indata, frames, time_info, status):
            audio_queue.put(indata[:, 0].tobytes())

        try:
            with sd.InputStream(
                samplerate=self._porcupine.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=frame_length,
                callback=_callback,
            ):
                logger.debug("Porcupine : écoute en cours...")
                while True:
                    try:
                        pcm_bytes = audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue
                    pcm_unpacked = struct.unpack_from(f"{frame_length}h", pcm_bytes)
                    result = self._porcupine.process(pcm_unpacked)
                    if result >= 0:
                        logger.info(f"Wake word détecté via Porcupine (index={result})")
                        self._play_activation_sound()
                        return True

        except Exception as e:
            logger.error(f"Erreur Porcupine : {e}")
            return self._listen_keyboard()

    # ------------------------------------------------------------------
    # Stratégie 2 : OpenWakeWord
    # ------------------------------------------------------------------

    def _listen_oww(self) -> bool:
        """Écoute permanente via OpenWakeWord — détecte 'Hey Jarvis' sans clé API."""
        if not self._oww_model:
            return self._listen_keyboard()

        CHUNK = 1280  # 80ms à 16kHz — taille optimale OWW
        audio_queue: queue.Queue = queue.Queue()

        def _callback(indata, frames, time_info, status):
            if not status:
                audio_queue.put(indata[:, 0].copy())

        import threading
        _triggered = threading.Event()

        def _keyboard_thread():
            try:
                input()
                _triggered.set()
            except Exception:
                pass

        kb_thread = threading.Thread(target=_keyboard_thread, daemon=True)
        kb_thread.start()

        # Réinitialiser l'état interne du modèle (évite re-trigger)
        try:
            self._oww_model.reset()
        except Exception:
            pass

        from audio_utils import GUI_MODE as _GUI
        if not _GUI:
            print("\n  \033[36m●\033[0m  Dites  \033[1;36mHey Jarvis\033[0m  (ou appuyez sur Entrée)\n")

        try:
            with sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="int16",
                blocksize=CHUNK,
                callback=_callback,
                latency="low",
            ):
                frame_count = 0
                last_trigger_time = 0.0
                COOLDOWN = 3.5  # secondes entre deux détections (évite les faux positifs)

                while True:
                    if _triggered.is_set():
                        logger.info("Activation manuelle clavier")
                        self._play_activation_sound()
                        return True

                    try:
                        frame = audio_queue.get(timeout=0.15)
                    except queue.Empty:
                        continue

                    frame_count += 1
                    # Laisser le modèle se "chauffer" sur les 15 premières frames (~1.2s)
                    if frame_count < 15:
                        pred = self._oww_model.predict(frame)
                        if frame_count == 14:
                            logger.info(f"OWW clés disponibles : {list(pred.keys())}")
                        continue

                    prediction = self._oww_model.predict(frame)
                    # OWW peut retourner "hey_jarvis" ou "hey jarvis" selon la version
                    score = float(
                        prediction.get("hey jarvis",
                        prediction.get("hey_jarvis",
                        next(iter(prediction.values()), 0.0)))
                    )

                    # Barre de niveau en temps réel (toutes les frames > 0.03)
                    if score > 0.03:
                        bar = "█" * int(score * 25)
                        pct = int(score * 100)
                        print(f"\r  \033[33m{pct:3d}%\033[0m  [{bar:<25}]  ", end="", flush=True)

                    now = time.time()
                    if score >= self._oww_threshold and (now - last_trigger_time) > COOLDOWN:
                        last_trigger_time = now
                        print(f"\n  \033[32m✓ Hey Jarvis détecté (score={score:.2f})\033[0m")
                        logger.info(f"Hey Jarvis détecté (score={score:.2f})")
                        self._play_activation_sound()
                        return True

        except Exception as e:
            logger.error(f"Erreur OpenWakeWord : {e}")
            return self._listen_keyboard()

    # ------------------------------------------------------------------
    # Stratégie 3 : Vosk
    # ------------------------------------------------------------------

    def _listen_vosk(self) -> bool:
        if not self._vosk_rec:
            return self._listen_keyboard()

        CHUNK = 1024
        audio_queue: queue.Queue = queue.Queue()

        def _callback(indata, frames, time_info, status):
            audio_queue.put(indata[:, 0].tobytes())

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=CHUNK,
                callback=_callback,
            ):
                logger.debug("Vosk : écoute en cours...")
                while True:
                    try:
                        data = audio_queue.get(timeout=1.0)
                    except queue.Empty:
                        continue

                    if self._vosk_rec.AcceptWaveform(data):
                        result = _json.loads(self._vosk_rec.Result())
                        text = result.get("text", "").lower()
                        if self.keyword in text:
                            logger.info(f"Wake word '{self.keyword}' détecté via Vosk")
                            self._play_activation_sound()
                            return True
                    else:
                        partial = _json.loads(self._vosk_rec.PartialResult())
                        partial_text = partial.get("partial", "").lower()
                        if self.keyword in partial_text:
                            logger.info("Wake word détecté (partiel) via Vosk")
                            self._vosk_rec.Reset()
                            self._play_activation_sound()
                            return True

        except Exception as e:
            logger.error(f"Erreur Vosk : {e}")
            return self._listen_keyboard()

    # ------------------------------------------------------------------
    # Stratégie 3 : Clavier (fallback toujours disponible)
    # ------------------------------------------------------------------

    def _listen_keyboard(self) -> bool:
        try:
            input()  # Attend simplement un appui sur Entrée
            self._play_activation_sound()
            return True
        except EOFError:
            time.sleep(0.5)
            return True
        except KeyboardInterrupt:
            raise

    # ------------------------------------------------------------------
    # Son d'activation
    # ------------------------------------------------------------------

    def _play_activation_sound(self) -> None:
        """Double bip pour signaler la détection."""
        try:
            from audio_utils import play_beep
            play_beep(frequency=880, duration=0.1)
            time.sleep(0.05)
            play_beep(frequency=1100, duration=0.1)
        except Exception:
            print("\a", end="", flush=True)

    # ------------------------------------------------------------------
    # Nettoyage
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        if self._porcupine:
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None
        logger.info("WakeWordDetector nettoyé")

    # ------------------------------------------------------------------
    # Garde TTS — à appeler avant/après chaque speak()
    # ------------------------------------------------------------------

    def mute(self) -> None:
        """Désactive la détection pendant que JARVIS parle (évite l'auto-trigger)."""
        self._muted = True

    def unmute(self) -> None:
        """Réactive la détection et démarre un cooldown de 3 s.
        Le cooldown couvre l'écho résiduel du TTS capté par le micro."""
        self._muted = False
        self._last_trigger_time = time.time()  # COOLDOWN partira de maintenant

    def get_strategy(self) -> str:
        return self.strategy

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass
