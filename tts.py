"""
tts.py — Moteur Text-to-Speech JARVIS
Chaîne de priorité : ElevenLabs → Edge TTS (gratuit, neural) → OpenAI TTS → pyttsx3
Edge TTS = voix Microsoft Edge, qualité neurale, 100% gratuit.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import queue
import re
import threading
import time
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

# Imports optionnels
try:
    from elevenlabs.client import ElevenLabs
    from elevenlabs import VoiceSettings
    _ELEVENLABS_AVAILABLE = True
except ImportError:
    _ELEVENLABS_AVAILABLE = False

try:
    import edge_tts
    _EDGE_TTS_AVAILABLE = True
except ImportError:
    _EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts non disponible — pip install edge-tts")

try:
    from openai import OpenAI as OpenAIClient
    _OPENAI_TTS_AVAILABLE = True
except ImportError:
    _OPENAI_TTS_AVAILABLE = False

try:
    import pyttsx3
    _PYTTSX3_AVAILABLE = True
except ImportError:
    _PYTTSX3_AVAILABLE = False

from audio_utils import play_audio_bytes, play_beep

# Voix Edge TTS disponibles (toutes gratuites)
EDGE_VOICES = {
    "homme_fr":    "fr-FR-HenriNeural",      # Voix masculine FR — proche ChatGPT
    "femme_fr":    "fr-FR-DeniseNeural",     # Voix féminine FR
    "homme_be":    "fr-BE-GerardNeural",     # Voix masculine belge
    "femme_be":    "fr-BE-IsabelleNeural",   # Voix féminine belge
}
DEFAULT_EDGE_VOICE = "fr-FR-HenriNeural"

_CACHE_MAX_BYTES = 500 * 1024 * 1024  # 500 MB


class TTSEngine:
    """
    Moteur TTS avec chaîne de dégradation et pipeline streaming.
    Priorité : ElevenLabs → Edge TTS → OpenAI TTS → pyttsx3
    """

    def __init__(
        self,
        elevenlabs_key: Optional[str] = None,
        elevenlabs_voice: Optional[str] = None,
        openai_key: Optional[str] = None,
        edge_voice: Optional[str] = None,
        language: str = "fr",
    ):
        self._el_key = elevenlabs_key
        self._el_voice = elevenlabs_voice or "21m00Tcm4TlvDq8ikWAM"
        self._openai_key = openai_key
        self._edge_voice = edge_voice or DEFAULT_EDGE_VOICE
        self.language = language

        self._el_client = None
        self._openai_client = None
        self._pyttsx3_engine = None
        self._silent_mode = False
        self._stop_event = threading.Event()
        self._cache: dict[str, bytes] = {}  # cache mémoire session
        self._push_text = None   # callback overlay : affiche chunk de texte
        self._clear_text = None  # callback overlay : efface le texte

        # Cache fichier persistant entre sessions (~/.jarvis_tts_cache/)
        self._cache_dir = Path.home() / ".jarvis_tts_cache"
        self._cache_dir.mkdir(exist_ok=True)

        # Boucle asyncio persistante pour Edge TTS (évite les conflits de threading)
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="EdgeTTS-Loop"
        )
        self._loop_thread.start()

        self._active_engine = self._init_engines()
        logger.info(f"TTS engine actif : {self._active_engine}")

    # ------------------------------------------------------------------
    # Initialisation des moteurs
    # ------------------------------------------------------------------

    def _init_engines(self) -> str:
        # 1. ElevenLabs (meilleure qualité, payant)
        if _ELEVENLABS_AVAILABLE and self._el_key:
            try:
                self._el_client = ElevenLabs(api_key=self._el_key)
                logger.info("ElevenLabs initialisé")
                return "elevenlabs"
            except Exception as e:
                logger.warning(f"ElevenLabs init échoué : {e}")

        # 2. Edge TTS (gratuit, neural, qualité ChatGPT)
        if _EDGE_TTS_AVAILABLE:
            try:
                # Test rapide pour vérifier la connectivité
                logger.info(f"Edge TTS initialisé — voix : {self._edge_voice}")
                return "edge_tts"
            except Exception as e:
                logger.warning(f"Edge TTS init échoué : {e}")

        # 3. OpenAI TTS (payant, bonne qualité)
        if _OPENAI_TTS_AVAILABLE and self._openai_key:
            try:
                self._openai_client = OpenAIClient(api_key=self._openai_key)
                logger.info("OpenAI TTS initialisé")
                return "openai_tts"
            except Exception as e:
                logger.warning(f"OpenAI TTS init échoué : {e}")

        # 4. pyttsx3 (offline, voix basique)
        if _PYTTSX3_AVAILABLE:
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 150)
                voices = engine.getProperty("voices")
                for v in voices:
                    if "fr" in v.id.lower() or "french" in v.name.lower():
                        engine.setProperty("voice", v.id)
                        logger.info(f"pyttsx3 voix française : {v.id}")
                        break
                self._pyttsx3_engine = engine
                logger.info("pyttsx3 initialisé (fallback offline)")
                return "pyttsx3"
            except Exception as e:
                logger.warning(f"pyttsx3 init échoué : {e}")

        logger.error("Aucun moteur TTS disponible — mode silencieux forcé")
        return "none"

    # ------------------------------------------------------------------
    # Edge TTS (async → sync wrapper)
    # ------------------------------------------------------------------

    async def _edge_tts_to_bytes(self, text: str) -> bytes:
        """Génère audio Edge TTS et retourne les bytes MP3."""
        communicate = edge_tts.Communicate(text, voice=self._edge_voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)

    def _edge_tts_bytes_sync(self, text: str) -> bytes:
        """Version synchrone de _edge_tts_to_bytes via la boucle persistante."""
        future = asyncio.run_coroutine_threadsafe(
            self._edge_tts_to_bytes(text), self._loop
        )
        return future.result(timeout=30)

    # ------------------------------------------------------------------
    # API publique
    # ------------------------------------------------------------------

    def _cache_key(self, text: str) -> str:
        return hashlib.md5(f"{self._edge_voice}:{text.strip().lower()}".encode()).hexdigest()

    def _load_from_file_cache(self, text: str) -> Optional[bytes]:
        key = self._cache_key(text)
        path = self._cache_dir / f"{key}.mp3"
        if path.exists():
            try:
                return path.read_bytes()
            except Exception:
                pass
        return None

    def _save_to_file_cache(self, text: str, audio: bytes) -> None:
        if len(audio) < 100:
            return
        key = self._cache_key(text)
        path = self._cache_dir / f"{key}.mp3"
        try:
            # Éviction LRU si cache > 500MB
            try:
                files = list(self._cache_dir.glob("*.mp3"))
                total = sum(f.stat().st_size for f in files)
                if total + len(audio) > _CACHE_MAX_BYTES:
                    for f in sorted(files, key=lambda x: x.stat().st_atime):
                        freed = f.stat().st_size
                        f.unlink()
                        total -= freed
                        if total + len(audio) <= _CACHE_MAX_BYTES:
                            break
            except Exception:
                pass
            path.write_bytes(audio)
        except Exception:
            pass

    def set_text_callbacks(self, push_fn, clear_fn) -> None:
        """Branche les callbacks d'affichage overlay (thread-safe via signaux Qt)."""
        self._push_text = push_fn
        self._clear_text = clear_fn

    def prewarm_cache(self, phrases: list) -> None:
        """Génère et met en cache les phrases en arrière-plan (sans bloquer)."""
        def _warm():
            for phrase in phrases:
                if self._stop_event.is_set():
                    break
                if self._load_from_file_cache(phrase):
                    continue  # déjà en cache
                try:
                    audio = self._edge_tts_bytes_sync(phrase)
                    if audio:
                        self._save_to_file_cache(phrase, audio)
                        logger.debug(f"TTS pré-cache: {phrase[:40]}")
                except Exception:
                    pass
        threading.Thread(target=_warm, daemon=True, name="TTS-Prewarm").start()

    def speak_filler(self, phrases: list | None = None) -> None:
        """Joue instantanément une phrase depuis le cache TTS (non-bloquant, < 5ms)."""
        if self._silent_mode or self._active_engine == "none":
            return
        candidates = phrases or ["Une seconde.", "Je cherche l'information.", "D'accord."]
        for phrase in candidates:
            cached = self._load_from_file_cache(phrase)
            if cached:
                threading.Thread(
                    target=lambda a=cached: play_audio_bytes(a, fmt="mp3"),
                    daemon=True,
                    name="TTS-Filler",
                ).start()
                return

    def speak(self, text: str) -> None:
        """Synthétise et joue du texte.
        Cherche d'abord dans le cache fichier (0ms), puis mémoire, puis génère.
        """
        if self._silent_mode or self._active_engine == "none":
            print(f"\n[JARVIS] {text}\n")
            return

        text = self._clean_for_tts(text)
        if not text.strip():
            return

        # Texte long → pipeline streaming phrase par phrase (première phrase joue plus vite)
        if len(text) > 80 and self._active_engine == "edge_tts":
            def _gen():
                yield text
            self.speak_streaming(_gen())
            return

        # Texte court : afficher dans l'overlay immédiatement
        if self._clear_text:
            self._clear_text()
        if self._push_text:
            self._push_text(text)

        self._stop_event.clear()

        # 1. Cache fichier (persistant entre sessions — lecture disque rapide)
        if self._active_engine == "edge_tts":
            cached = self._load_from_file_cache(text)
            if cached:
                logger.debug(f"TTS cache hit: {text[:40]}")
                play_audio_bytes(cached, fmt="mp3")
                return

        # 2. Cache mémoire session
        cache_key = text.lower().strip()
        if cache_key in self._cache:
            play_audio_bytes(self._cache[cache_key], fmt="mp3")
            return

        try:
            if self._active_engine == "edge_tts":
                audio = self._edge_tts_bytes_sync(text)
                if audio:
                    self._save_to_file_cache(text, audio)
                    play_audio_bytes(audio, fmt="mp3")
                else:
                    logger.warning("Edge TTS : bytes vides")
                    print(f"\n[JARVIS] {text}\n")

            elif self._active_engine == "elevenlabs" and self._el_client:
                audio_gen = self._el_client.generate(
                    text=text,
                    voice=self._el_voice,
                    model="eleven_multilingual_v2",
                    voice_settings=VoiceSettings(
                        stability=0.5,
                        similarity_boost=0.75,
                        style=0.0,
                        use_speaker_boost=True,
                    ),
                )
                play_audio_bytes(b"".join(audio_gen), fmt="mp3")

            elif self._active_engine == "openai_tts" and self._openai_client:
                response = self._openai_client.audio.speech.create(
                    model="tts-1",
                    voice="onyx",
                    input=text,
                    response_format="mp3",
                )
                play_audio_bytes(response.content, fmt="mp3")

            elif self._active_engine == "pyttsx3" and self._pyttsx3_engine:
                self._pyttsx3_engine.say(text)
                self._pyttsx3_engine.runAndWait()

            else:
                print(f"\n[JARVIS] {text}\n")

        except Exception as e:
            logger.error(f"speak() échoué ({self._active_engine}) : {e}")
            print(f"\n[JARVIS] {text}\n")

    def speak_streaming(self, text_generator: Generator[str, None, None]) -> None:
        """
        Pipeline streaming LLM → TTS.
        Edge TTS : génération et lecture en parallèle (N+1 généré pendant que N joue).
        Autres moteurs : pipeline séquentiel.
        """
        if self._silent_mode or self._active_engine == "none":
            full_text = ""
            for chunk in text_generator:
                full_text += chunk
                print(chunk, end="", flush=True)
            print()
            return

        self._stop_event.clear()
        sentence_queue: queue.Queue = queue.Queue()
        buffer = ""
        _first_chunk = True

        if self._active_engine == "edge_tts":
            # Pipeline concurrent : génération audio en avance sur la lecture
            audio_queue: queue.Queue = queue.Queue()

            # Effacer le texte overlay en début de réponse
            if self._clear_text:
                self._clear_text()

            def _gen_worker():
                while True:
                    try:
                        sentence = sentence_queue.get(timeout=20)
                    except queue.Empty:
                        audio_queue.put(None)
                        return
                    if sentence is None:
                        audio_queue.put(None)
                        return
                    if self._stop_event.is_set():
                        audio_queue.put(None)
                        return
                    try:
                        sentence = self._clean_for_tts(sentence)
                        if not sentence:
                            continue
                        _t_gen = time.time()
                        cached = self._load_from_file_cache(sentence)
                        if cached:
                            logger.debug(f"TTS cache hit ({len(sentence)}c)")
                            audio_queue.put(cached)
                        else:
                            audio = self._edge_tts_bytes_sync(sentence)
                            _gen_ms = int((time.time() - _t_gen) * 1000)
                            logger.debug(f"TTS gen {len(sentence)}c → {_gen_ms}ms")
                            if audio:
                                self._save_to_file_cache(sentence, audio)
                                audio_queue.put(audio)
                            else:
                                audio_queue.put(b"")
                    except Exception as e:
                        logger.error(f"TTS gen erreur : {e}")
                        audio_queue.put(b"")

            def _play_worker():
                while True:
                    try:
                        audio = audio_queue.get(timeout=30)
                    except queue.Empty:
                        return
                    if audio is None:
                        return
                    if self._stop_event.is_set():
                        return
                    if audio:
                        play_audio_bytes(audio, fmt="mp3")

            gen_thread = threading.Thread(target=_gen_worker, daemon=True, name="TTS-Gen")
            play_thread = threading.Thread(target=_play_worker, daemon=True, name="TTS-Play")
            gen_thread.start()
            play_thread.start()

            try:
                for chunk in text_generator:
                    if self._stop_event.is_set():
                        break
                    buffer += chunk
                    print(chunk, end="", flush=True)
                    # Pousser le chunk vers l'overlay en temps réel
                    if self._push_text and chunk:
                        self._push_text(chunk)
                    sentences = self._split_into_sentences(buffer)
                    if len(sentences) > 1:
                        for sentence in sentences[:-1]:
                            if sentence.strip():
                                sentence_queue.put(sentence.strip())
                        buffer = sentences[-1]
            finally:
                if buffer.strip() and not self._stop_event.is_set():
                    sentence_queue.put(buffer.strip())
                sentence_queue.put(None)
                print()

            gen_thread.join(timeout=30)
            play_thread.join(timeout=60)
            return

        # Autres moteurs : pipeline séquentiel
        if self._clear_text:
            self._clear_text()

        def tts_worker():
            while True:
                try:
                    sentence = sentence_queue.get(timeout=15)
                    if sentence is None:
                        break
                    if self._stop_event.is_set():
                        break
                    self.speak(sentence)
                    sentence_queue.task_done()
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"TTS worker erreur : {e}")

        tts_thread = threading.Thread(target=tts_worker, daemon=True)
        tts_thread.start()

        try:
            for chunk in text_generator:
                if self._stop_event.is_set():
                    break
                buffer += chunk
                print(chunk, end="", flush=True)
                if self._push_text and chunk:
                    self._push_text(chunk)
                sentences = self._split_into_sentences(buffer)
                if len(sentences) > 1:
                    for sentence in sentences[:-1]:
                        if sentence.strip():
                            sentence_queue.put(sentence.strip())
                    buffer = sentences[-1]
        finally:
            if buffer.strip() and not self._stop_event.is_set():
                sentence_queue.put(buffer.strip())
            sentence_queue.put(None)
            print()

        tts_thread.join(timeout=60)

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """Supprime le markdown et les artefacts visuels pour une lecture vocale naturelle."""
        import re as _re
        # Tool calls inline malformés — 2e ligne de défense (toutes variantes + orphelins)
        text = _re.sub(r'<function=\w+>?\s*.*?</function>', '', text, flags=_re.DOTALL)
        text = _re.sub(r'<function=\w+[^<]*>?', '', text)   # tags orphelins sans </function>
        # Blocs de code
        text = _re.sub(r'```[^`]*```', '', text, flags=_re.DOTALL)
        text = _re.sub(r'`([^`]+)`', r'\1', text)
        # Headers markdown
        text = _re.sub(r'^#{1,6}\s+', '', text, flags=_re.MULTILINE)
        # Gras / italique → texte seul
        text = _re.sub(r'\*{2,3}([^*]+)\*{2,3}', r'\1', text)
        text = _re.sub(r'\*([^*]+)\*', r'\1', text)
        text = _re.sub(r'__([^_]+)__', r'\1', text)
        text = _re.sub(r'_([^_\n]+)_', r'\1', text)
        # Liens Obsidian [[Note|Alias]] → préférer l'alias, sinon le nom de note
        text = _re.sub(r'\[\[[^\]|]+\|([^\]]+)\]\]', r'\1', text)
        text = _re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
        # Liens markdown → texte seul
        text = _re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        # URLs brutes (avec éventuelles parenthèses vides après)
        text = _re.sub(r'https?://\S+', '', text)
        text = _re.sub(r'\(\s*\)', '', text)
        # Tables markdown → retirer les séparateurs de colonnes
        text = _re.sub(r'^\s*\|[-| :]+\|\s*$', '', text, flags=_re.MULTILINE)
        text = _re.sub(r'\|', ' — ', text)
        # Listes numérotées : "1. " → ""
        text = _re.sub(r'^\s*\d+[.)]\s+', '', text, flags=_re.MULTILINE)
        # Listes markdown (tirets/étoiles en début de ligne, y compris →)
        text = _re.sub(r'^\s*[-*•→]\s+', '', text, flags=_re.MULTILINE)
        # Lignes de séparation visuelles
        text = _re.sub(r'[━─═▸▹▷◦◆◇■□●○]{2,}', '', text)
        # ── Symboles → prononciation naturelle ───────────────────────────
        text = _re.sub(r'N°\s*', 'numéro ', text)
        text = _re.sub(r'(\d+(?:[.,]\d+)?)\s*€', r'\1 euros', text)
        text = _re.sub(r'€\s*(\d+(?:[.,]\d+)?)', r'\1 euros', text)
        # Plages de pourcentages AVANT le % seul : "30-40%" → "30 à 40 pour cent"
        text = _re.sub(r'(\d+)\s*-\s*(\d+)\s*%', r'\1 à \2 pour cent', text)
        text = _re.sub(r'(\d+)\s*%', r'\1 pour cent', text)
        text = _re.sub(r'\+\s*(\d)', r'plus \1', text)          # +3 → plus 3
        text = _re.sub(r'(?<!\d)-\s*(\d)', r'moins \1', text)   # -3 → moins 3, pas 10-3
        text = _re.sub(r'\s*→\s*', ' — ', text)
        text = _re.sub(r'×', ' fois ', text)
        # Unités fréquentes — km/h AVANT /h pour éviter que /h consomme la fin de km/h
        text = _re.sub(r'(\d+)\s*km/h', r'\1 kilomètres par heure', text, flags=_re.IGNORECASE)
        text = _re.sub(r'/mois\b', ' par mois', text, flags=_re.IGNORECASE)
        text = _re.sub(r'/an\b', ' par an', text, flags=_re.IGNORECASE)
        text = _re.sub(r'/km\b', ' par kilomètre', text, flags=_re.IGNORECASE)
        text = _re.sub(r'/h\b', ' par heure', text, flags=_re.IGNORECASE)
        # Abréviations courantes
        text = _re.sub(r'\benv\.\s*', 'environ ', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\bapprox\.\s*', 'approximativement ', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\betc\.\s*', 'et cetera ', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\bp\.?\s?ex\.\s*', 'par exemple ', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\bc\.?-à-?d\.?\s*', "c'est-à-dire ", text, flags=_re.IGNORECASE)
        # Titres de civilité : "M. Renard" → "Monsieur Renard"
        text = _re.sub(r'\bMme?\s*\.\s*(?=[A-ZÀ-Ü])', 'Madame ', text)
        text = _re.sub(r'\bM\.\s*(?=[A-ZÀ-Ü])', 'Monsieur ', text)
        text = _re.sub(r'\bDr\.\s*(?=[A-ZÀ-Ü])', 'Docteur ', text)
        text = _re.sub(r'\bProf\.\s*(?=[A-ZÀ-Ü])', 'Professeur ', text)
        # Parenthèses isolées vides ou avec tirets : "(---)" → ""
        text = _re.sub(r'\(\s*[-–—]+\s*\)', '', text)
        # Guillemets typographiques → rien (le texte entre guillemets reste)
        text = _re.sub(r'[«»„"""]', '"', text)
        text = _re.sub(r'\bvs\.?\b', 'contre', text, flags=_re.IGNORECASE)
        # Unités réseau/télécom — NexaTel fréquent
        text = _re.sub(r'\bGbps\b', 'gigabits par seconde', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\bMbps\b', 'mégabits par seconde', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\bkbps\b', 'kilobits par seconde', text, flags=_re.IGNORECASE)
        text = _re.sub(r'\bGHz\b', 'gigahertz', text)
        text = _re.sub(r'\bMHz\b', 'mégahertz', text)
        text = _re.sub(r'\bkWh\b', 'kilowatt-heure', text)
        # Degrés Celsius : "22°C" → "22 degrés"
        text = _re.sub(r'(\d+)\s*°C', r'\1 degrés', text)
        # Emojis courants → retirer (peuvent causer des artefacts vocaux)
        text = _re.sub(r'[\U0001F300-\U0001F9FF]', '', text)
        # Sauts de ligne multiples → espace
        text = _re.sub(r'\n{2,}', '. ', text)
        text = _re.sub(r'\n', ' ', text)
        # Espaces multiples
        text = _re.sub(r' {2,}', ' ', text)
        return text.strip()

    def _split_into_sentences(self, text: str) -> list:
        """
        Découpe le texte en unités naturelles pour le TTS streaming.
        Priorité : ponctuation forte > virgule longue > longueur max.
        Évite les coupures sur abréviations (M., Dr., etc., p.ex., N°...) et nombres décimaux.
        """
        # Protéger les abréviations courantes avant de splitter
        _ABBREVS = ["M.", "Mme.", "Dr.", "Prof.", "etc.", "p.ex.", "ex.", "N°",
                    "St.", "Ste.", "vol.", "art.", "cf.", "vs.", "apr.", "av."]
        protected = text
        # Protéger les nombres décimaux (1.5, 3.14, €12.50, +2.3%)
        protected = re.sub(r'(\d)\.(\d)', r'\1__DOT__\2', protected)
        placeholders = {}
        for i, abbr in enumerate(_ABBREVS):
            ph = f"__ABBR{i}__"
            placeholders[ph] = abbr
            protected = protected.replace(abbr, ph)

        # Découpe sur . ! ? — les délimiteurs de phrases
        pattern = r'(?<=[.!?…])\s+'
        parts = re.split(pattern, protected)

        # Restaurer les abréviations et nombres décimaux dans les parties
        restored_parts = []
        for part in parts:
            part = re.sub(r'(\d)__DOT__(\d)', r'\1.\2', part)
            for ph, abbr in placeholders.items():
                part = part.replace(ph, abbr)
            restored_parts.append(part)
        parts = restored_parts

        result = []
        current = ""
        for part in parts:
            # Ajouter le fragment au buffer
            combined = (current + " " + part).strip() if current else part.strip()

            # Phrase complète (se termine par ponctuation forte)
            if combined and combined[-1] in ".!?…":
                result.append(combined)
                current = ""
            # Trop long → couper sur virgule ou tiret (60 chars pour réduire latence 1er audio)
            elif len(combined) > 60:
                # Chercher une virgule ou pause naturelle
                cut = max(
                    combined.rfind(", ", 0, 60),
                    combined.rfind(" — ", 0, 60),
                    combined.rfind(" ; ", 0, 60),
                )
                if cut > 20:
                    result.append(combined[:cut + 1].strip())
                    current = combined[cut + 1:].strip()
                else:
                    # Couper sur un espace
                    words = combined[:60].rsplit(" ", 1)
                    result.append(words[0].strip())
                    current = (words[1] if len(words) > 1 else "") + combined[60:]
            else:
                current = combined

        if current.strip():
            result.append(current.strip())

        return [s for s in result if s.strip()] or [text]

    def stop(self) -> None:
        """Arrête la lecture audio en cours."""
        self._stop_event.set()
        if self._pyttsx3_engine:
            try:
                self._pyttsx3_engine.stop()
            except Exception:
                pass

    def set_silent_mode(self, silent: bool) -> None:
        self._silent_mode = silent
        logger.info(f"Mode silencieux {'activé' if silent else 'désactivé'}")

    def is_silent(self) -> bool:
        return self._silent_mode

    def get_active_engine(self) -> str:
        return self._active_engine

    def set_edge_voice(self, voice: str) -> None:
        """Change la voix Edge TTS (voir EDGE_VOICES dict)."""
        self._edge_voice = voice
        self._cache.clear()
        logger.info(f"Voix Edge TTS changée : {voice}")
