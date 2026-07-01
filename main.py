"""
main.py — Point d'entrée principal de JARVIS
Boucle principale : wake word → écoute → transcription → LLM → TTS
"""

import logging
import logging.handlers
import sys
import os
import time
import threading
from pathlib import Path

# Ajouter le répertoire courant au path Python
sys.path.insert(0, str(Path(__file__).parent))

# Configuration du logging avec rotation (5 MB max, 3 backups)
_log_dir = Path(__file__).parent
_log_file = _log_dir / "jarvis.log"
_log_handlers: list = [logging.StreamHandler(sys.stdout)]
if sys.stdout.isatty():
    _log_handlers.append(
        logging.handlers.RotatingFileHandler(
            _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
    )
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=_log_handlers,
)
logger = logging.getLogger("jarvis.main")

# Imports JARVIS
from config import Config
from ui import JarvisUI
from stt import STTEngine
from tts import TTSEngine
from memory import MemorySystem
from persistent_memory import PersistentMemory
from llm import LLMEngine
from wake_word import WakeWordDetector
from commands import CommandProcessor, CMD_SHUTDOWN
from audio_utils import record_audio_vad, apply_noise_reduction

# Interface Qt (PyQt6) — overlay visuel moderne
try:
    from jarvis_qt_window import create_qt_app, check_microphone_permission
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False

# Fallback tkinter (désactivé sur macOS 14+)
if not _QT_AVAILABLE:
    try:
        from jarvis_overlay import JarvisOverlay as _TkOverlay
    except ImportError:
        _TkOverlay = None


def init_components(config: Config, ui: JarvisUI, pre_components: dict = None) -> dict:
    """
    Initialise tous les composants JARVIS dans l'ordre.

    Retourne un dict avec les instances et le statut de chacun.
    """
    components = dict(pre_components or {})
    status = {}

    # STT (faster-whisper — chargé en arrière-plan pour démarrage rapide)
    ui.log_info("Chargement du modèle STT en arrière-plan...")
    try:
        stt = STTEngine(config.WHISPER_MODEL, config.LANGUAGE, async_load=True)
        components["stt"] = stt
        status[f"STT (faster-whisper {config.WHISPER_MODEL})"] = True
    except Exception as e:
        logger.error(f"STT init échoué : {e}")
        ui.log_error(f"STT indisponible : {e}")
        components["stt"] = None
        status["Whisper STT"] = False

    # TTS
    ui.log_info("Initialisation du moteur TTS...")
    try:
        tts = TTSEngine(
            elevenlabs_key=config.ELEVENLABS_API_KEY if config.has_elevenlabs() else None,
            elevenlabs_voice=config.ELEVENLABS_VOICE_ID,
            openai_key=config.OPENAI_API_KEY if config.has_openai_tts() else None,
            edge_voice=config.EDGE_VOICE,
            language=config.LANGUAGE,
        )
        components["tts"] = tts
        status[f"TTS ({tts.get_active_engine()})"] = True
    except Exception as e:
        logger.error(f"TTS init échoué : {e}")
        # TTS minimal : affichage texte
        from tts import TTSEngine as MinimalTTS
        tts = MinimalTTS()
        components["tts"] = tts
        status["TTS"] = False

    # Mémoire Obsidian
    ui.log_info("Connexion au vault Obsidian...")
    try:
        memory = MemorySystem(config.OBSIDIAN_VAULT_PATH if config.has_obsidian() else None)
        components["memory"] = memory
        status["Mémoire Obsidian"] = memory.is_available()
    except Exception as e:
        logger.error(f"Memory init échoué : {e}")
        memory = MemorySystem(None)
        components["memory"] = memory
        status["Mémoire Obsidian"] = False

    # LLM (Groq cloud → Ollama local fallback)
    engine_label = "Groq" if config.has_groq() else f"Ollama ({config.OLLAMA_MODEL})"
    ui.log_info(f"Connexion LLM ({engine_label})...")
    try:
        llm = LLMEngine(
            groq_api_key=config.GROQ_API_KEY,
            ollama_host=config.OLLAMA_HOST,
            ollama_model=config.OLLAMA_MODEL,
            user_name=config.USER_NAME,
            groq_model=config.LLM_MODEL,
        )
        components["llm"] = llm
        status[f"LLM ({llm.get_active_engine()})"] = True
    except Exception as e:
        logger.error(f"LLM init échoué : {e}")
        ui.log_error(f"LLM indisponible : {e}")
        sys.exit(1)  # Sans LLM, JARVIS ne peut pas fonctionner

    # Wake word
    ui.log_info("Initialisation du détecteur de wake word...")
    try:
        wake = WakeWordDetector(
            keyword=config.JARVIS_NAME.lower(),
            porcupine_key=config.PORCUPINE_ACCESS_KEY if config.has_porcupine() else None,
            vosk_model_path=config.VOSK_MODEL_PATH if config.has_vosk() else None,
        )
        components["wake"] = wake
        status[f"Wake Word ({wake.get_strategy()})"] = True
    except Exception as e:
        logger.error(f"Wake word init échoué : {e}")
        # Fallback clavier
        from wake_word import WakeWordDetector as WW
        wake = WW(keyword=config.JARVIS_NAME.lower())
        components["wake"] = wake
        status["Wake Word (keyboard)"] = True

    # Mémoire persistante (entre les sessions)
    ui.log_info("Chargement de la mémoire persistante...")
    try:
        persistent_mem = PersistentMemory()
        components["persistent_memory"] = persistent_mem
        stats = persistent_mem.stats()
        status[f"Mémoire persistante ({stats['facts']} faits)"] = True
    except Exception as e:
        logger.warning(f"Mémoire persistante indisponible : {e}")
        components["persistent_memory"] = None

    # CommandProcessor
    try:
        commands = CommandProcessor(
            tts, memory, llm,
            persistent_memory=components.get("persistent_memory"),
            user_name=config.USER_NAME,
        )
        components["commands"] = commands
    except Exception as e:
        logger.error(f"Commands init échoué : {e}")
        components["commands"] = None

    # Overlay visuel (Qt ou tkinter selon disponibilité)
    # Note : si Qt est utilisé, l'overlay est créé AVANT dans main() et passé ici
    if "overlay" not in components:
        components["overlay"] = None
    status["Interface visuelle"] = components["overlay"] is not None and components["overlay"].is_enabled()

    ui.show_startup_status(status)
    return components


def run_main_loop(config: Config, ui: JarvisUI, components: dict) -> None:
    """Boucle principale de JARVIS."""
    stt: STTEngine           = components["stt"]
    tts: TTSEngine           = components["tts"]
    memory: MemorySystem     = components["memory"]
    persistent_mem: PersistentMemory = components.get("persistent_memory")
    llm: LLMEngine           = components["llm"]
    wake: WakeWordDetector   = components["wake"]
    cmds: CommandProcessor   = components["commands"]
    overlay: JarvisOverlay   = components.get("overlay")

    # Connecter overlay → TTS pour afficher le texte en temps réel (thread-safe via signaux Qt)
    if overlay and hasattr(overlay, "push_text") and hasattr(tts, "set_text_callbacks"):
        tts.set_text_callbacks(overlay.push_text, overlay.clear_text)

    # Briefing du matin
    try:
        briefing = memory.get_morning_briefing(user_name=config.USER_NAME)
        if briefing:
            ui.log_info("Briefing du matin disponible")
            tts.speak(briefing)
    except Exception as e:
        logger.warning(f"Briefing du matin échoué : {e}")

    # Message de bienvenue personnalisé selon l'heure
    from datetime import datetime as _dt
    _now = _dt.now()
    _h = _now.hour
    _jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    _jour = _jours_fr[_now.weekday()]

    if 5 <= _h < 12:
        salutation = "Bonjour"
    elif 12 <= _h < 18:
        salutation = "Bon après-midi"
    elif 18 <= _h < 22:
        salutation = "Bonsoir"
    else:
        salutation = "Bonne nuit"

    # Récupérer les faits mémorisés pour personnaliser
    _facts_count = len(persistent_mem.get_facts()) if persistent_mem else 0

    # Construction du message de bienvenue
    if _h in (5, 6, 7):
        _opening = f"JARVIS en ligne. {salutation}, {config.USER_NAME}. Bonne matinée ce {_jour}."
    elif _now.weekday() == 0 and _h < 12:
        _opening = f"JARVIS en ligne. {salutation}, {config.USER_NAME}. Bonne semaine."
    elif _now.weekday() >= 4 and _h >= 17:
        _opening = f"JARVIS en ligne. {salutation}, {config.USER_NAME}. Bon week-end en perspective."
    else:
        _opening = f"JARVIS en ligne. {salutation}, {config.USER_NAME}."

    if _facts_count > 0:
        _opening += f" {_facts_count} souvenir{'s' if _facts_count > 1 else ''} en mémoire."

    # Mentionner un RDV imminent depuis la mémoire persistante
    _rdv_hint = ""
    if persistent_mem:
        try:
            _facts = persistent_mem.get_facts(limit=50)
            _rdv_facts = [f for f in _facts if any(
                k in f.lower() for k in ["rdv", "réunion", "entretien", "appel", "meeting"]
            )]
            if _rdv_facts:
                _rdv_hint = f" Vous avez un rappel : {_rdv_facts[-1][:60]}."
        except Exception:
            pass

    welcome = _opening + _rdv_hint

    # Météo matinale intégrée dans le message d'accueil (5h-12h)
    if 5 <= _h < 12:
        try:
            from jarvis_tools import execute_tool as _exec_tool
            _weather = _exec_tool("meteo", {"ville": "Charleroi"})
            if _weather and "indisponible" not in _weather.lower() and "erreur" not in _weather.lower():
                # Raccourcir la météo pour le message d'accueil
                _weather_short = _weather.split(".")[0] + "."
                welcome += f" {_weather_short}"
        except Exception:
            pass

    # Avertissement batterie faible (< 20% et non branché)
    try:
        import subprocess as _sp, re as _re_batt
        _batt_out = _sp.run(["pmset", "-g", "batt"], capture_output=True, text=True, timeout=3).stdout
        _pct_m = _re_batt.search(r'(\d+)%', _batt_out)
        if _pct_m:
            _pct = int(_pct_m.group(1))
            _on_battery = "Battery Power" in _batt_out
            if _pct < 20 and _on_battery:
                welcome += f" Batterie à {_pct}% — pensez à brancher."
    except Exception:
        pass

    tts.speak(welcome)
    ui.log_success("JARVIS opérationnel")

    # Pré-cache les phrases fréquentes en arrière-plan (réponses instantanées)
    tts.prewarm_cache([
        # Confirmations rapides
        "D'accord.",
        "Compris.",
        "Entendu.",
        "Fait.",
        "C'est noté.",
        "Je lance ça.",
        "Mémorisé.",
        "Une seconde.",
        # Erreurs / incompréhensions
        "Je n'ai pas compris, pouvez-vous répéter ?",
        "Pouvez-vous répéter ? Je n'ai pas bien compris.",
        "Je n'ai rien à répéter.",
        # Recherche
        "Je cherche l'information.",
        "Voici ce que j'ai trouvé.",
        # Mémoire / notes
        "Aucune note trouvée.",
        "Note sauvegardée.",
        "Historique effacé. Nouvelle conversation.",
        "Notes Obsidian actualisées.",
        "Aucun événement particulier trouvé pour aujourd'hui.",
        # Système
        "Tâche effectuée.",
        # NexaTel — phrases de vente fréquentes (prêtes immédiatement)
        "Même réseau Proximus officiel numéro un en Belgique, trente à quarante pour cent moins cher.",
        "Prix fixe à vie, contractuellement garanti.",
        "Installation gratuite à domicile.",
        "Nouveau lead enregistré.",
        "Voulez-vous que je génère un pitch pour ce client ?",
        "Il hésite sur quoi ? Le prix, le réseau, ou il compare avec Orange ?",
        "Depuis avril 2026, Orange discrimine ses anciens clients.",
        # Salutations contextuelles
        f"JARVIS en ligne. {salutation}, {config.USER_NAME}.",
        f"Bonsoir, {config.USER_NAME}.",
        f"Bonjour, {config.USER_NAME}.",
        f"Bonne nuit, {config.USER_NAME}.",
    ])

    # Compteur de session pour les sauvegardes
    session_exchanges = []
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 5
    _auto_listen = False  # True quand JARVIS pose une question → pas besoin de redire "JARVIS"

    while True:
        try:
            # ----------------------------------------------------------
            # 1. Attente du mot de réveil (sauf si JARVIS vient de poser une question)
            # ----------------------------------------------------------
            if overlay:
                overlay.set_idle()

            if _auto_listen:
                ui.set_status("LISTENING", "→ Répondez directement...")
                ui.log_info("Auto-écoute (question posée)")
                _auto_listen = False
            else:
                ui.set_status("IDLE", "En attente...")
                ui.print_wake_prompt(strategy=wake.get_strategy())
                wake.listen_for_wake_word()

            if consecutive_errors > 0:
                consecutive_errors = 0

            # ----------------------------------------------------------
            # 2. Enregistrement audio
            # ----------------------------------------------------------
            if overlay:
                overlay.set_listening()
            ui.set_status("LISTENING", "J'écoute...")
            try:
                audio_bytes = record_audio_vad(
                    max_seconds=config.MAX_RECORDING_SECONDS,
                    silence_duration=config.SILENCE_THRESHOLD,
                )
                audio_bytes = apply_noise_reduction(audio_bytes)
            except Exception as e:
                logger.error(f"Erreur enregistrement : {e}")
                ui.log_error(f"Microphone indisponible : {e}")
                tts.speak("Problème avec le microphone. Veuillez vérifier votre matériel.")
                continue

            # ----------------------------------------------------------
            # 3. Transcription STT (attendre chargement si async)
            # ----------------------------------------------------------
            if overlay:
                overlay.set_thinking()
            ui.set_status("THINKING", "Transcription en cours...")

            if stt is None:
                ui.log_error("Whisper non disponible — transcription impossible")
                tts.speak("Le moteur de reconnaissance vocale n'est pas disponible.")
                continue

            # Si le modèle est encore en cours de chargement, attendre (max 30s)
            if not stt.is_model_loaded():
                ui.log_info("Modèle STT encore en chargement, patientez...")
                tts.speak("Une seconde, je me réveille.")
                if not stt.wait_until_ready(timeout=30):
                    ui.log_error("Whisper non disponible après délai")
                    tts.speak("Le moteur de reconnaissance vocale n'est pas disponible.")
                    continue

            text, detected_lang = stt.transcribe_with_lang(audio_bytes, language=None)

            if stt.is_empty_transcription(text):
                ui.log_warning(f"Transcription vide ou bruit : '{text}'")
                tts.speak("Pouvez-vous répéter ? Je n'ai pas bien compris.")
                continue

            ui.show_user_input(text)
            logger.info(f"Transcription : '{text}'")

            # Bip de confirmation "j'ai entendu" — réduit la sensation de silence
            try:
                from audio_utils import play_beep
                play_beep(frequency=660, duration=0.07)
            except Exception:
                pass

            # ----------------------------------------------------------
            # 4. Détection de commandes locales
            # ----------------------------------------------------------
            if cmds:
                command = cmds.detect_command(text)
                if command:
                    handled, response = cmds.execute(command, text)
                    if handled:
                        if command == CMD_SHUTDOWN:
                            if response:
                                tts.speak(response)
                            break  # Sortir de la boucle

                        if response:
                            ui.show_response(response)
                            tts.speak(response)
                            _auto_listen = response.strip().endswith("?")

                        # Sauvegarder la commande dans l'historique
                        session_exchanges.append({"role": "user", "content": text})
                        if response:
                            session_exchanges.append({"role": "assistant", "content": response})

                        continue

            # ----------------------------------------------------------
            # 5. Recherche de notes Obsidian pertinentes
            # ----------------------------------------------------------
            notes = []
            try:
                notes = memory.search_relevant_notes(text, top_k=3)
                if notes:
                    ui.show_notes(notes)
            except Exception as e:
                logger.warning(f"Recherche notes échouée : {e}")

            # ----------------------------------------------------------
            # 6. Génération de réponse LLM (tool calling ou streaming)
            # ----------------------------------------------------------
            ui.set_status("THINKING", "JARVIS réfléchit...")

            memory_context = persistent_mem.get_context_for_llm() if persistent_mem else ""

            # Indice de langue pour le LLM (arabe/anglais → JARVIS répond dans la même langue)
            if detected_lang == "ar":
                text_for_llm = f"[Ali parle en arabe. Réponds-lui en arabe.] {text}"
            elif detected_lang == "en":
                text_for_llm = f"[Ali parle en anglais. Réponds-lui en anglais.] {text}"
            else:
                text_for_llm = text

            # Filler instantané depuis le pré-cache (réduit la perception de latence)
            tts.speak_filler()

            # Essayer le tool calling en premier (compréhension naturelle)
            full_response, was_tool = llm.chat_with_tools(
                text_for_llm, notes,
                memory_context=memory_context,
                persistent_memory=persistent_mem,
                tts=tts,
            )

            # ----------------------------------------------------------
            # 7. TTS — réponse directe si tool call, sinon on re-stream
            # ----------------------------------------------------------
            if overlay:
                overlay.set_speaking()
            ui.set_status("SPEAKING", "JARVIS parle...")

            if was_tool or full_response:
                if full_response:
                    ui.show_response(full_response)
                    # Ne pas re-parler si speak_streaming a déjà joué la réponse
                    if not getattr(llm, "_last_was_streamed", False):
                        tts.speak(full_response)
            else:
                # Fallback : streaming pur (Ollama ou erreur groq)
                response_gen = llm.chat_stream(text, notes, memory_context=memory_context)
                tts.speak_streaming(response_gen)
                full_response = llm.get_last_response()

            llm.add_to_history("user", text)
            llm.add_to_history("assistant", full_response)
            llm.truncate_history(config.MAX_HISTORY)

            session_exchanges.append({"role": "user", "content": text})
            session_exchanges.append({"role": "assistant", "content": full_response})

            # Extraction automatique de faits en arrière-plan (n'ajoute pas de latence)
            if persistent_mem and full_response:
                persistent_mem.auto_extract_from_exchange(text, full_response, llm)

            # Si JARVIS pose une question → auto-écoute au prochain tour (sans redire "JARVIS")
            _auto_listen = bool(full_response and full_response.strip().endswith("?"))

            # Sauvegarder toutes les 5 réponses pour ne pas perdre la session
            if len(session_exchanges) >= 10:
                try:
                    tags = llm.extract_tags(
                        " ".join(e["content"] for e in session_exchanges[-4:])
                    )
                    memory.save_conversation(session_exchanges[-10:], tags=tags)
                    session_exchanges = []  # Reset après sauvegarde
                except Exception as e:
                    logger.warning(f"Sauvegarde conversation échouée : {e}")

            ui.print_separator()

        except KeyboardInterrupt:
            logger.info("Interruption clavier — arrêt de JARVIS")
            break

        except Exception as e:
            consecutive_errors += 1
            logger.error(f"Erreur boucle principale ({consecutive_errors}) : {e}", exc_info=True)
            ui.log_error(f"Erreur : {str(e)[:100]}")

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                ui.log_error(f"{MAX_CONSECUTIVE_ERRORS} erreurs consécutives — arrêt de sécurité")
                tts.speak("Trop d'erreurs consécutives. JARVIS s'arrête.")
                break

            try:
                tts.speak("Une erreur s'est produite. Je reste à l'écoute.")
            except Exception:
                print("[JARVIS] Une erreur s'est produite. Je reste à l'écoute.")

    # ------------------------------------------------------------------
    # Arrêt propre
    # ------------------------------------------------------------------
    shutdown(config, components, session_exchanges, ui)


def shutdown(config: Config, components: dict, session_exchanges: list, ui: JarvisUI) -> None:
    """Procédure d'arrêt propre de JARVIS."""
    logger.info("Arrêt de JARVIS en cours...")

    # Sauvegarder la conversation en cours
    if session_exchanges:
        try:
            memory: MemorySystem = components.get("memory")
            llm: LLMEngine = components.get("llm")
            persistent_mem: PersistentMemory = components.get("persistent_memory")
            if memory and llm:
                tags = llm.extract_tags(
                    " ".join(e["content"] for e in session_exchanges[-4:])
                )
                memory.save_conversation(session_exchanges, tags=tags)
                logger.info(f"Session sauvegardée ({len(session_exchanges)} échanges)")

            # Résumé persistant de la session
            if persistent_mem and llm and len(session_exchanges) >= 2:
                last_texts = " ".join(e["content"] for e in session_exchanges[-6:])
                summary = llm.chat_sync(
                    f"Résume en 1 phrase ce dont on a parlé : {last_texts[:400]}",
                    system="Résume en une seule phrase courte, en français.",
                    max_tokens=60,
                )
                if summary:
                    persistent_mem.save_session_summary(summary, len(session_exchanges))
        except Exception as e:
            logger.warning(f"Sauvegarde session finale échouée : {e}")

    # Libérer les ressources
    wake: WakeWordDetector = components.get("wake")
    if wake:
        wake.cleanup()

    overlay: JarvisOverlay = components.get("overlay")
    if overlay:
        overlay.close()

    ui.log_info(f"JARVIS hors ligne. À bientôt, {config.USER_NAME}.")
    print()


def _jarvis_worker(config: Config, ui: JarvisUI, components: dict) -> None:
    """JARVIS main loop — tourne dans un thread secondaire quand Qt est actif."""
    try:
        run_main_loop(config, ui, components)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.error(f"Erreur fatale worker : {e}", exc_info=True)
    finally:
        # Signaler à Qt de quitter proprement
        overlay = components.get("overlay")
        if overlay and _QT_AVAILABLE and hasattr(overlay, "_signals"):
            try:
                overlay._signals.quit_app.emit()
            except Exception:
                pass


def main() -> None:
    """Point d'entrée principal."""
    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    try:
        config = Config()
        config.validate()
    except EnvironmentError as e:
        print(str(e))
        sys.exit(1)
    except Exception as e:
        print(f"Erreur de configuration inattendue : {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Interface terminale
    # ------------------------------------------------------------------
    ui = JarvisUI()
    ui.show_banner()

    if config.DEBUG:
        logging.getLogger().setLevel(logging.DEBUG)
        ui.log_info("Mode DEBUG activé")

    # ------------------------------------------------------------------
    # Overlay Qt (créé ici car Qt doit être dans le thread principal)
    # ------------------------------------------------------------------
    qt_app = None
    overlay = None

    if _QT_AVAILABLE:
        try:
            qt_app, overlay, _signals = create_qt_app()
            ui.log_success("Interface visuelle Qt chargée")
        except Exception as e:
            logger.warning(f"Interface Qt indisponible : {e}")
            overlay = None
    elif "_TkOverlay" in dir() and _TkOverlay:
        try:
            overlay = _TkOverlay(width=380, height=380)
            ui.log_info("Interface visuelle tkinter (fallback)")
        except Exception:
            overlay = None

    # ------------------------------------------------------------------
    # Initialisation des composants (overlay déjà créé, passé directement)
    # ------------------------------------------------------------------
    ui.log_info("Initialisation des composants...")
    try:
        # Passer l'overlay AVANT l'appel pour que le status soit correct
        _pre_components = {"overlay": overlay}
        components = init_components(config, ui, pre_components=_pre_components)
        components["overlay"] = overlay
    except SystemExit:
        raise
    except Exception as e:
        ui.log_error(f"Échec d'initialisation critique : {e}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Boucle principale : Qt en main thread, JARVIS dans un thread
    # ------------------------------------------------------------------
    if qt_app is not None:
        # Supprimer les prints terminal inutiles (le feedback est dans l'overlay Qt)
        import audio_utils as _au
        _au.GUI_MODE = True

        worker = threading.Thread(
            target=_jarvis_worker,
            args=(config, ui, components),
            daemon=True,
            name="JarvisWorker",
        )
        worker.start()
        try:
            sys.exit(qt_app.exec())
        except SystemExit:
            pass
    else:
        # Pas de Qt — boucle directe dans le main thread
        try:
            run_main_loop(config, ui, components)
        except KeyboardInterrupt:
            pass
        finally:
            ui.log_info("Au revoir.")


if __name__ == "__main__":
    main()
