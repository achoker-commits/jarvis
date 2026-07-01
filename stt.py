"""
stt.py — Speech-to-Text JARVIS
Priorité : faster-whisper (CTranslate2, 4x plus rapide) → Whisper standard
"""

import io
import logging
import os
import tempfile
import time
import wave

logger = logging.getLogger(__name__)

_NOISE_PHRASES = {
    "...", "…", ".", " ", "",
    "merci", "merci.", "sous-titrage",
    "you", "thank you", "thanks",
    "sous-titres réalisés para la communauté d'amara.org",
    # Hallucinations fréquentes de Whisper (YouTube / silence)
    "sous-titres", "sous-titres.", "sous-titres...",
    "merci d'avoir regardé", "merci d'avoir regardé !",
    "merci de votre attention", "merci de votre attention.",
    "abonnez-vous", "abonnez-vous !", "likez et abonnez-vous",
    "la suite au prochain épisode", "fin", "fin.",
    "musique douce", "[musique]", "(musique)",
    # Hallucinations supplémentaires (silence / fond sonore)
    "[silence]", "(silence)", "silence.",
    "cliquez sur la cloche", "cliquez sur la cloche !",
    "[applaudissements]", "(applaudissements)", "applaudissements.",
    "[rires]", "(rires)", "[bruit de fond]", "(bruit de fond)",
    "♪", "♫", "🎵", "🎶",
    "merci à tous", "merci à tous !",
    "à bientôt tout le monde", "à très bientôt",
    "n'hésitez pas à vous abonner", "n'hésitez pas",
    "restez connectés", "restez connecté",
    # Hallucinations communes Whisper tiny/small (fond sonore, respiration)
    "la musique continue", "la musique se poursuit",
    "tous droits réservés", "tout droit réservé",
    "sous-titre", "sous-titre.",
    "[toux]", "(toux)", "[respiration]", "(respiration)",
    "[bruit]", "(bruit)", "[claquement]",
    "transcription automatique", "transcription par",
    "sous-titrage automatique", "sous-titrage :",
    ".", ",", "!", "?",
    "hmm", "hm", "euh", "um", "uh",
    "ok", "okay", "ouais",
    # Hallucinations Whisper supplémentaires identifiées en production
    "bonjour", "bonjour.", "bonsoir", "bonsoir.",
    "au revoir", "au revoir.", "bonne journée", "bonne journée.",
    "je vous souhaite une bonne journée",
    "je suis désolé", "je suis désolé.",
    "merci beaucoup", "merci beaucoup.",
    "d'accord", "d'accord.", "très bien", "très bien.",
    "oui", "oui.", "non", "non.",
    "voilà", "voilà.", "voila", "voila.",
    "c'est ça", "c'est ça.", "exactement", "exactement.",
    "bien sûr", "bien sûr.", "biensur", "biensur.",
    "effectivement", "effectivement.",
    "[inaudible]", "(inaudible)", "inaudible.",
    "[incompréhensible]", "(incompréhensible)",
    "transcription en cours", "génération des sous-titres",
    "sous-titres automatiques", "sous-titres automatiques.",
    "cliquez pour activer", "activez les sous-titres",
    "abonnez-vous à la chaîne", "likez la vidéo",
    "partager en commentaire", "mettez un like",
    "la vidéo se poursuit", "voix off",
    "♩", "♬", "🎙️", "🎤",
    "merci pour votre écoute", "bonne écoute",
    "fin de l'enregistrement", "fin du podcast",
}

_FASTER_WHISPER_AVAILABLE = False
try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    pass


class STTEngine:
    """Moteur STT : faster-whisper en priorité, Whisper standard en fallback."""

    def __init__(self, model_name: str = "small", language: str = "fr", async_load: bool = False):
        self.model_name = model_name
        self.language = language
        self._model = None
        self._using_faster = False
        self._loading = False

        if async_load:
            import threading
            self._loading = True
            t = threading.Thread(target=self._load_model, daemon=True)
            t.start()
        else:
            self._load_model()

    def _load_model(self) -> None:
        self._loading = True
        # Essayer faster-whisper en premier
        if _FASTER_WHISPER_AVAILABLE:
            try:
                logger.info(f"Chargement faster-whisper '{self.model_name}'...")
                t0 = time.time()
                # Essayer d'abord depuis le cache local pour éviter la requête HuggingFace
                try:
                    self._model = FasterWhisperModel(
                        self.model_name, device="cpu", compute_type="int8",
                        local_files_only=True,
                    )
                except Exception:
                    self._model = FasterWhisperModel(
                        self.model_name, device="cpu", compute_type="int8",
                    )
                elapsed = time.time() - t0
                self._using_faster = True
                self._loading = False
                logger.info(f"faster-whisper chargé en {elapsed:.1f}s (int8 CPU)")
                return
            except Exception as e:
                logger.warning(f"faster-whisper échoué : {e} — fallback Whisper")

        # Fallback : Whisper standard
        try:
            import whisper
            logger.info(f"Chargement Whisper standard '{self.model_name}'...")
            t0 = time.time()
            self._model = whisper.load_model(self.model_name)
            elapsed = time.time() - t0
            self._using_faster = False
            logger.info(f"Whisper standard chargé en {elapsed:.1f}s")
        except Exception as e:
            logger.error(f"Échec chargement STT : {e}")
        finally:
            self._loading = False

    def transcribe(self, audio_bytes: bytes, language: str = None) -> str:
        """Transcrit l'audio. Retourne le texte. language=None = auto-détection."""
        text, _ = self.transcribe_with_lang(audio_bytes, language=language)
        return text

    def transcribe_with_lang(self, audio_bytes: bytes, language: str = None) -> tuple:
        """
        Transcrit l'audio et retourne (texte, langue_détectée).
        language=None → auto-détection Whisper.
        """
        if self._model is None:
            return "", self.language
        if not audio_bytes or len(audio_bytes) < 100:
            return "", self.language

        lang = language if language is not None else self.language
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="jarvis_stt_") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            t0 = time.time()

            if self._using_faster:
                text, detected_lang = self._transcribe_faster(tmp_path, lang)
            else:
                text = self._transcribe_standard(tmp_path)
                detected_lang = self.language

            elapsed = time.time() - t0
            logger.debug(f"Transcription en {elapsed:.2f}s [{detected_lang}] : '{text[:60]}'")
            return text, detected_lang

        except Exception as e:
            logger.error(f"Erreur transcription : {e}")
            return "", self.language
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _transcribe_faster(self, path: str, language: str = None) -> tuple:
        """Transcription via faster-whisper. Retourne (texte, langue_détectée)."""
        # Initial prompt : noms propres seulement pour auto-détection, contexte FR complet sinon
        if language is None:
            # Contexte neutre (noms propres universels) pour ne pas biaiser la détection
            prompt = "JARVIS, NexaTel, Proximus, Ali, Charleroi, Bruxelles, Spotify, YouTube."
        else:
            prompt = (
                "JARVIS, NexaTel, Proximus, Charleroi, Bruxelles, Belgique, bitcoin, ethereum, "
                "YouTube, Spotify, Chrome, Terminal, Safari, Messages, Mail, Finder. "
                "Ali, Karim, Amina, Thomas, Mehdi, Sophie. "
                "météo, batterie, volume, luminosité, agenda, note, traduction. "
                "Conversation naturelle en français belge."
            )
        segments, info = self._model.transcribe(
            path,
            language=language,            # None = auto-détection Whisper
            beam_size=1,                  # greedy = 3x plus rapide, minimal loss en fr
            best_of=1,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=400,
                threshold=0.45,
            ),
            initial_prompt=prompt,
            condition_on_previous_text=False,
            temperature=0.0,
            no_speech_threshold=0.65,
            compression_ratio_threshold=2.4,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        detected = getattr(info, "language", None) or language or self.language
        return text, detected

    def _transcribe_standard(self, path: str) -> str:
        """Transcription via Whisper standard."""
        result = self._model.transcribe(
            path,
            language=self.language,
            fp16=False,
            condition_on_previous_text=False,
            verbose=False,
            temperature=0,
            beam_size=1,
            best_of=1,
            no_speech_threshold=0.65,
            compression_ratio_threshold=2.4,
            initial_prompt=(
                "JARVIS, NexaTel, Proximus, Charleroi, Bruxelles, Belgique, bitcoin, "
                "YouTube, Spotify, Chrome, Terminal. Conversation en français belge."
            ),
        )
        return result.get("text", "").strip()

    def is_empty_transcription(self, text: str) -> bool:
        if not text:
            return True
        cleaned = text.strip().lower()
        if cleaned in _NOISE_PHRASES:
            return True
        words = cleaned.split()
        if len(words) < 2 and len(cleaned) < 4:
            return True
        if all(c in ".…,!? \t\n♪♫♩♬" for c in cleaned):
            return True
        # Phrase entièrement entre crochets ou parenthèses = hallucination
        if cleaned.startswith(("[", "(")) and cleaned.endswith(("]", ")")):
            return True
        # Répétition de caractère unique (ex: "hhhh", "aaaa") = bruit micro
        if len(set(cleaned.replace(" ", ""))) <= 2 and len(cleaned) > 3:
            return True
        return False

    def get_audio_duration(self, audio_bytes: bytes) -> float:
        try:
            buf = io.BytesIO(audio_bytes)
            with wave.open(buf, "rb") as wf:
                return wf.getnframes() / float(wf.getframerate())
        except Exception:
            return 0.0

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        """Attend que le modèle soit chargé (utile avec async_load=True)."""
        import time as _time
        deadline = _time.time() + timeout
        while self._loading and _time.time() < deadline:
            _time.sleep(0.1)
        return self._model is not None

    def is_model_loaded(self) -> bool:
        return self._model is not None and not self._loading

    def get_engine_name(self) -> str:
        return "faster-whisper" if self._using_faster else "whisper"

    def change_language(self, language: str) -> None:
        self.language = language
        logger.info(f"Langue STT changée : {language}")
