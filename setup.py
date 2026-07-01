"""
setup.py — Script d'installation et health check pour JARVIS
Vérifie les dépendances, crée le .env, teste les APIs.
"""

import os
import subprocess
import sys
import shutil
import time
from pathlib import Path

# Couleurs ANSI pour le terminal
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


def ok(msg: str) -> str:
    return f"{GREEN}✓{RESET} {msg}"


def fail(msg: str) -> str:
    return f"{RED}✗{RESET} {msg}"


def warn(msg: str) -> str:
    return f"{YELLOW}⚠{RESET} {msg}"


def info(msg: str) -> str:
    return f"{CYAN}ℹ{RESET} {msg}"


def header(msg: str) -> None:
    print(f"\n{BOLD}{CYAN}{'─' * 50}{RESET}")
    print(f"{BOLD}{msg}{RESET}")
    print(f"{CYAN}{'─' * 50}{RESET}")


def run_cmd(cmd: list, capture: bool = True) -> tuple:
    """Exécute une commande shell. Retourne (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=120,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout"
    except FileNotFoundError:
        return -1, "", f"Commande introuvable : {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


# ---------------------------------------------------------------------------
# Étape 1 : Vérification Python
# ---------------------------------------------------------------------------

def check_python() -> bool:
    header("Étape 1/7 — Vérification Python")
    version = sys.version_info
    print(f"  Python détecté : {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(fail(f"Python 3.9+ requis. Version actuelle : {version.major}.{version.minor}"))
        return False

    print(ok(f"Python {version.major}.{version.minor}.{version.micro} — OK"))
    return True


# ---------------------------------------------------------------------------
# Étape 2 : Vérification ffmpeg
# ---------------------------------------------------------------------------

def check_ffmpeg() -> bool:
    header("Étape 2/7 — Vérification ffmpeg")
    path = shutil.which("ffmpeg")
    if path:
        code, out, _ = run_cmd(["ffmpeg", "-version"])
        version_line = out.split("\n")[0] if out else "version inconnue"
        print(ok(f"ffmpeg trouvé : {path}"))
        print(f"  {version_line}")
        return True
    else:
        print(fail("ffmpeg non trouvé !"))
        print(info("Installation :"))
        if sys.platform == "darwin":
            print("  brew install ffmpeg")
        elif sys.platform.startswith("linux"):
            print("  sudo apt install ffmpeg")
        else:
            print("  https://ffmpeg.org/download.html")
        print(warn("Whisper nécessite ffmpeg pour décoder l'audio."))
        return False


# ---------------------------------------------------------------------------
# Étape 3 : Installation des requirements
# ---------------------------------------------------------------------------

def install_requirements() -> bool:
    header("Étape 3/7 — Installation des dépendances Python")
    req_file = Path(__file__).parent / "requirements.txt"

    if not req_file.exists():
        print(fail("requirements.txt introuvable !"))
        return False

    print(info(f"Installation depuis {req_file}..."))
    code, out, err = run_cmd(
        [sys.executable, "-m", "pip", "install", "-r", str(req_file), "--quiet"],
        capture=False,  # Afficher la progression
    )

    if code == 0:
        print(ok("Toutes les dépendances installées"))
        return True
    else:
        print(fail(f"Erreur pip (code {code})"))
        print(f"  {err[:300]}")
        return False


# ---------------------------------------------------------------------------
# Étape 4 : Test microphone
# ---------------------------------------------------------------------------

def check_microphone() -> bool:
    header("Étape 4/7 — Test microphone")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        micros = []
        for i, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) > 0:
                micros.append(f"  [{i}] {dev.get('name', 'Inconnu')}")

        if micros:
            print(ok(f"{len(micros)} microphone(s) détecté(s) :"))
            for m in micros[:5]:
                print(m)
            return True
        else:
            print(warn("Aucun microphone détecté"))
            return False

    except ImportError:
        print(warn("sounddevice non installé — test microphone ignoré"))
        return False
    except Exception as e:
        print(warn(f"Test microphone échoué : {e}"))
        return False


# ---------------------------------------------------------------------------
# Étape 5 : Création du .env
# ---------------------------------------------------------------------------

def create_env() -> bool:
    header("Étape 5/7 — Configuration .env")
    jarvis_dir = Path(__file__).parent
    env_file = jarvis_dir / ".env"
    template_file = jarvis_dir / ".env.template"

    if env_file.exists():
        print(ok(".env déjà présent — non écrasé"))
        return True

    if template_file.exists():
        shutil.copy(template_file, env_file)
        print(ok(f".env créé depuis le template : {env_file}"))
        print(warn("Éditez le .env et renseignez votre GROQ_API_KEY (gratuit sur console.groq.com)"))
        return True
    else:
        print(fail(".env.template introuvable"))
        return False


# ---------------------------------------------------------------------------
# Étape 6 : Test des clés API
# ---------------------------------------------------------------------------

def test_apis() -> bool:
    header("Étape 6/7 — Test des clés API")

    # Charger le .env
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent / ".env"
        load_dotenv(env_path)
    except ImportError:
        print(warn("python-dotenv non disponible — lecture des variables d'environnement système"))

    all_ok = True

    # Test Groq (LLM principal de JARVIS — gratuit)
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            import requests
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [{"role": "user", "content": "OK"}],
                    "max_tokens": 5,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                print(ok("Groq API — connexion réussie (llama-3.3-70b-versatile)"))
            else:
                print(fail(f"Groq API — status {resp.status_code} : {resp.text[:80]}"))
                all_ok = False
        except Exception as e:
            print(fail(f"Groq API — erreur : {str(e)[:80]}"))
            all_ok = False
    else:
        print(fail("GROQ_API_KEY non définie — JARVIS ne peut pas fonctionner sans Groq !"))
        print(info("Obtenez une clé gratuite sur : console.groq.com"))
        all_ok = False

    # Test Edge TTS (TTS principal — aucune clé requise)
    try:
        import edge_tts
        print(ok("edge-tts installé — voix Rémy disponible (aucune clé requise)"))
    except ImportError:
        print(warn("edge-tts non installé — pip install edge-tts"))

    return all_ok


# ---------------------------------------------------------------------------
# Étape 7 : Téléchargement des modèles
# ---------------------------------------------------------------------------

def download_models() -> bool:
    header("Étape 7/7 — Téléchargement des modèles")
    all_ok = True

    # Modèle Whisper
    whisper_model = os.getenv("WHISPER_MODEL", "medium")
    print(info(f"Téléchargement du modèle Whisper '{whisper_model}'..."))
    print(info("(Ceci peut prendre plusieurs minutes selon votre connexion)"))

    try:
        import whisper
        model = whisper.load_model(whisper_model)
        print(ok(f"Modèle Whisper '{whisper_model}' chargé avec succès"))
        del model  # Libérer la mémoire
    except ImportError:
        print(fail("openai-whisper non installé"))
        all_ok = False
    except Exception as e:
        print(fail(f"Erreur téléchargement Whisper : {e}"))
        all_ok = False

    # Modèle Vosk (optionnel)
    vosk_model_path = os.getenv("VOSK_MODEL_PATH", "")
    if vosk_model_path:
        if Path(vosk_model_path).is_dir():
            print(ok(f"Modèle Vosk trouvé : {vosk_model_path}"))
        else:
            print(warn(f"Modèle Vosk introuvable : {vosk_model_path}"))
            print(info("Téléchargez le modèle Vosk français depuis :"))
            print("  https://alphacephei.com/vosk/models")
            print("  Modèle recommandé : vosk-model-small-fr-0.22")
    else:
        print(info("VOSK_MODEL_PATH non définie — wake word via clavier (OK)"))

    return all_ok


# ---------------------------------------------------------------------------
# Rapport final
# ---------------------------------------------------------------------------

def print_final_report(results: dict) -> None:
    print(f"\n{BOLD}{'═' * 50}{RESET}")
    print(f"{BOLD}  RAPPORT D'INSTALLATION JARVIS{RESET}")
    print(f"{BOLD}{'═' * 50}{RESET}\n")

    for step, success in results.items():
        status = ok(step) if success else fail(step)
        print(f"  {status}")

    critical_ok = results.get("Python") and results.get("APIs")
    print()

    if critical_ok:
        print(f"{GREEN}{BOLD}  JARVIS est prêt !{RESET}")
        print(f"  Lancez JARVIS avec : {CYAN}python main.py{RESET}\n")
    else:
        print(f"{YELLOW}{BOLD}  Installation partielle — vérifiez les erreurs ci-dessus{RESET}")
        print(f"  JARVIS peut fonctionner en mode dégradé.\n")

    print(info("Commandes utiles :"))
    print(f"  python main.py          — Lancer JARVIS")
    print(f"  python setup.py         — Re-vérifier l'installation")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"\n{BOLD}{CYAN}")
    print("  ╔══════════════════════════════════════╗")
    print("  ║     JARVIS — Installation Setup      ║")
    print("  ╚══════════════════════════════════════╝")
    print(f"{RESET}")

    results = {}
    results["Python"]        = check_python()

    if not results["Python"]:
        print(fail("Python 3.9+ requis. Installation abandonnée."))
        sys.exit(1)

    results["ffmpeg"]        = check_ffmpeg()
    results["Dépendances"]   = install_requirements()
    results["Microphone"]    = check_microphone()
    results["Configuration"] = create_env()
    results["APIs"]          = test_apis()
    results["Modèles"]       = download_models()

    print_final_report(results)


if __name__ == "__main__":
    main()
