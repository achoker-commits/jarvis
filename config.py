"""
config.py — Configuration et variables d'environnement JARVIS
Charge le fichier .env et valide les clés requises.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv


class Config:
    """Classe de configuration centralisée pour JARVIS."""

    def __init__(self, env_file: str = ".env"):
        # Cherche le .env dans le répertoire courant ou celui du script
        env_path = Path(env_file)
        if not env_path.exists():
            env_path = Path(__file__).parent / env_file

        load_dotenv(dotenv_path=env_path, override=False)

        # --- Groq API (LLM cloud gratuit, meilleure qualité) ---
        self.GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")

        # --- Ollama (LLM local, fallback offline) ---
        self.OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral")

        # --- Edge TTS voix ---
        self.EDGE_VOICE: str = os.getenv("EDGE_VOICE", "fr-FR-RemyMultilingualNeural")

        # --- Clés optionnelles ElevenLabs ---
        self.ELEVENLABS_API_KEY: str | None = os.getenv("ELEVENLABS_API_KEY") or None
        self.ELEVENLABS_VOICE_ID: str = os.getenv(
            "ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"
        )  # Rachel par défaut

        # --- OpenAI TTS (optionnel) ---
        self.OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None

        # --- Porcupine wake word (optionnel) ---
        self.PORCUPINE_ACCESS_KEY: str | None = (
            os.getenv("PORCUPINE_ACCESS_KEY") or None
        )

        # --- Obsidian vault (optionnel) ---
        self.OBSIDIAN_VAULT_PATH: str | None = (
            os.getenv("OBSIDIAN_VAULT_PATH") or None
        )

        # --- Paramètres modèles ---
        self.WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "small")
        self.VOSK_MODEL_PATH: str | None = os.getenv("VOSK_MODEL_PATH") or None

        # --- Personnalité ---
        self.JARVIS_NAME: str = os.getenv("JARVIS_NAME", "Jarvis")
        self.USER_NAME: str = os.getenv("USER_NAME", "patron")
        self.LANGUAGE: str = os.getenv("LANGUAGE", "fr")

        # --- LLM (accès depuis commands.py pour affichage statut) ---
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

        # --- Audio ---
        self.SILENCE_THRESHOLD: float = float(
            os.getenv("SILENCE_THRESHOLD", "0.8")
        )
        self.MAX_RECORDING_SECONDS: int = int(
            os.getenv("MAX_RECORDING_SECONDS", "30")
        )

        # --- Mémoire ---
        self.MAX_HISTORY: int = int(os.getenv("MAX_HISTORY", "10"))

        # --- Mode debug ---
        self.DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")

    def validate(self) -> None:
        """Vérifie qu'au moins un LLM est disponible."""
        if self.GROQ_API_KEY:
            return  # Groq configuré, on est bons
        # Sinon, vérifier Ollama
        import requests
        try:
            resp = requests.get(f"{self.OLLAMA_HOST}/api/tags", timeout=3)
            if resp.status_code != 200:
                raise EnvironmentError(
                    "\n[ERREUR] Ni GROQ_API_KEY ni Ollama ne sont disponibles.\n"
                    "Ajoutez GROQ_API_KEY dans le .env (console.groq.com)\n"
                )
        except requests.exceptions.ConnectionError:
            raise EnvironmentError(
                "\n[ERREUR] Ni GROQ_API_KEY ni Ollama ne sont disponibles.\n"
                "Ajoutez GROQ_API_KEY dans le .env (console.groq.com)\n"
            )

    def has_groq(self) -> bool:
        return bool(self.GROQ_API_KEY)

    # --- Méthodes de vérification des optionnels ---

    def has_elevenlabs(self) -> bool:
        """Retourne True si ElevenLabs est configuré."""
        return bool(self.ELEVENLABS_API_KEY)

    def has_openai_tts(self) -> bool:
        """Retourne True si OpenAI TTS est configuré."""
        return bool(self.OPENAI_API_KEY)

    def has_porcupine(self) -> bool:
        """Retourne True si Porcupine wake word est configuré."""
        return bool(self.PORCUPINE_ACCESS_KEY)

    def has_obsidian(self) -> bool:
        """Retourne True si un vault Obsidian est configuré et accessible."""
        if not self.OBSIDIAN_VAULT_PATH:
            return False
        return Path(self.OBSIDIAN_VAULT_PATH).is_dir()

    def has_vosk(self) -> bool:
        """Retourne True si un modèle Vosk est disponible."""
        if not self.VOSK_MODEL_PATH:
            return False
        return Path(self.VOSK_MODEL_PATH).is_dir()

    def __repr__(self) -> str:
        return (
            f"Config("
            f"whisper={self.WHISPER_MODEL}, "
            f"lang={self.LANGUAGE}, "
            f"user={self.USER_NAME}, "
            f"elevenlabs={self.has_elevenlabs()}, "
            f"porcupine={self.has_porcupine()}, "
            f"obsidian={self.has_obsidian()}"
            f")"
        )
