# JARVIS — Assistant IA Personnel

> **Statut : en pause (juillet 2026)** — voir `STRATEGY.md` section **GEL DU PROJET — 02/07/2026** pour l'état fonctionnel, les bugs résiduels et le plan de reprise (migration Claude Haiku).

**Just A Rather Very Intelligent System** — Assistant vocal local propulsé par Groq (llama-3.3-70b), Whisper (faster-whisper) et Edge TTS (fr-FR-HenriNeural).

---

## Fonctionnalités

- Reconnaissance vocale hors-ligne (Whisper)
- Réponses en streaming via Claude claude-sonnet-4-6
- Synthèse vocale haute qualité (ElevenLabs / OpenAI TTS / pyttsx3 offline)
- Détection du wake word "Jarvis" (Porcupine / Vosk / clavier)
- Mémoire intégrée à Obsidian (lecture/écriture de notes)
- Commandes vocales locales instantanées
- Interface terminal Rich avec visualisation waveform

---

## Prérequis

| Outil | Version | Installation |
|---|---|---|
| Python | 3.9+ | python.org |
| ffmpeg | Toute | `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux) |
| pip | Inclus | — |

---

## Installation

### 1. Cloner / télécharger les fichiers

```bash
cd ~/projets/jarvis
```

### 2. Créer un environnement virtuel (recommandé)

```bash
python -m venv venv
source venv/bin/activate       # macOS/Linux
# OU
venv\Scripts\activate.bat      # Windows
```

### 3. Lancer le setup automatique

```bash
python setup.py
```

Le setup vérifie Python, ffmpeg, installe les dépendances, crée le `.env` et télécharge Whisper.

### 4. Configurer le .env

```bash
cp .env.template .env
nano .env    # ou vim, VS Code, etc.
```

Renseignez au minimum `ANTHROPIC_API_KEY`.

### 5. Lancer JARVIS

```bash
python main.py
```

---

## Configuration .env — Explications

### Clés API

#### ANTHROPIC_API_KEY (obligatoire)
- Créez un compte sur [console.anthropic.com](https://console.anthropic.com/)
- Allez dans **API Keys** → **Create Key**
- Format : `sk-ant-api03-...`

#### ELEVENLABS_API_KEY (recommandé)
- Compte gratuit sur [elevenlabs.io](https://elevenlabs.io/) — 10 000 caractères/mois offerts
- Settings → API Keys → Copy
- Choisissez une voix sur [elevenlabs.io/voice-library](https://elevenlabs.io/voice-library)
- Copiez l'ID de la voix dans `ELEVENLABS_VOICE_ID`

#### OPENAI_API_KEY (optionnel — TTS)
- Utilisé uniquement pour le TTS si ElevenLabs est absent
- [platform.openai.com/api-keys](https://platform.openai.com/api-keys)

#### PORCUPINE_ACCESS_KEY (optionnel — wake word)
- Compte gratuit sur [console.picovoice.ai](https://console.picovoice.ai/)
- 3 mois gratuits pour usage personnel
- Active la détection du mot "Jarvis" sans appui sur une touche

### Modèle Whisper

```
WHISPER_MODEL=medium
```

| Modèle | Taille | Vitesse | Précision FR |
|---|---|---|---|
| tiny | 75 MB | Très rapide | Basse |
| base | 150 MB | Rapide | Moyenne |
| small | 500 MB | Moyen | Bonne |
| medium | 1.5 GB | Moyen-lent | Très bonne |
| large | 3 GB | Lent | Excellente |

### Vault Obsidian

```
OBSIDIAN_VAULT_PATH=/Users/votre-nom/Documents/Mon Vault
```

JARVIS peut lire vos notes pour contextualiser ses réponses et y écrire des logs de conversation.

---

## Commandes vocales disponibles

| Commande | Exemples |
|---|---|
| Arrêter la lecture | "Arrête", "Stop", "Tais-toi" |
| Répéter la réponse | "Répète ça", "Répète s'il te plaît" |
| Heure et date | "Quelle heure est-il ?", "Quel jour sommes-nous ?" |
| Mode silencieux | "Mode silencieux", "Coupe le son" |
| Mode vocal | "Mode vocal", "Remets le son" |
| Arrêter JARVIS | "Au revoir", "Éteins-toi", "Bonne nuit" |
| Prendre une note | "Note que la réunion est à 14h" |
| Mémoriser | "Souviens-toi que mon mot de passe WiFi est XYZ" |
| Chercher dans les notes | "Qu'est-ce que tu sais sur le projet NexaTel ?" |
| Archiver une note | "Archive la note sur l'ancien projet" |
| Effacer l'historique | "Efface l'historique", "Nouvelle conversation" |

---

## Architecture technique

```
jarvis/
├── main.py          ← Boucle principale (orchestrateur)
├── config.py        ← Variables d'environnement
├── ui.py            ← Interface Rich (terminal)
├── stt.py           ← Speech-to-Text (Whisper)
├── tts.py           ← Text-to-Speech (ElevenLabs/OpenAI/pyttsx3)
├── llm.py           ← LLM (Claude claude-sonnet-4-6, streaming)
├── memory.py        ← Mémoire Obsidian
├── wake_word.py     ← Détection wake word (Porcupine/Vosk/Clavier)
├── commands.py      ← Commandes vocales locales
├── audio_utils.py   ← Enregistrement VAD, débruitage, lecture
├── setup.py         ← Installation et health check
├── requirements.txt ← Dépendances pip
├── .env.template    ← Template de configuration
└── .env             ← Votre configuration (ne pas committer)
```

### Flux de données

```
Microphone
    ↓ (audio_utils.py — VAD)
PCM Audio 16kHz
    ↓ (stt.py — Whisper)
Texte transcrit
    ↓ (commands.py — regex)
Commande locale ? ──→ Réponse instantanée
    ↓ non
(memory.py — recherche Obsidian)
Notes pertinentes
    ↓ (llm.py — Claude streaming)
Chunks de texte
    ↓ (tts.py — pipeline)
Phrases complètes → Synthèse → Lecture audio
```

---

## Intégration Obsidian

JARVIS crée automatiquement dans votre vault :

| Dossier | Contenu |
|---|---|
| `JARVIS-logs/` | Journaux de conversation quotidiens (YYYY-MM-DD.md) |
| `JARVIS-notes/` | Notes rapides dictées ("Note que...") |
| `JARVIS-archives/` | Notes archivées ("Archive la note sur...") |
| `memory/core.md` | Informations mémorisées ("Souviens-toi que...") |

Les notes de votre vault sont indexées au démarrage. JARVIS injecte automatiquement les 3 notes les plus pertinentes pour chaque question dans le contexte Claude.

---

## Dépannage

### "ANTHROPIC_API_KEY manquante"
→ Vérifiez que votre `.env` existe et contient la clé.  
→ Relancez depuis le dossier jarvis/ : `cd ~/projets/jarvis && python main.py`

### "Modèle Whisper introuvable"
→ Relancez `python setup.py` pour télécharger le modèle.  
→ Assurez-vous d'avoir une connexion internet lors du premier lancement.

### "Aucun microphone détecté"
→ macOS : Vérifiez les permissions micro dans Préférences Système → Sécurité → Microphone.  
→ Listez les micros : `python -c "from audio_utils import list_microphones; print(list_microphones())"`

### "TargetClosedError" ou crash audio
→ Vérifiez que PyAudio est bien installé : `pip install pyaudio`  
→ macOS : peut nécessiter `brew install portaudio` avant pip install pyaudio

### Wake word ne se déclenche pas
→ Sans Porcupine/Vosk, appuyez sur ESPACE pour parler  
→ Pour Porcupine : vérifiez que PORCUPINE_ACCESS_KEY est correcte  
→ Pour Vosk : vérifiez que VOSK_MODEL_PATH pointe vers un dossier valide

### ElevenLabs "quota exceeded"
→ Plan gratuit : 10 000 chars/mois  
→ JARVIS bascule automatiquement sur pyttsx3 si ElevenLabs échoue  
→ Commentez ELEVENLABS_API_KEY dans .env pour forcer pyttsx3

### Transcription en anglais alors que vous parlez français
→ Vérifiez `LANGUAGE=fr` dans votre `.env`  
→ Le modèle `tiny` peut être insuffisant pour le français — utilisez `medium`

### Réponses lentes
→ Passez à `WHISPER_MODEL=small` pour accélérer la transcription  
→ La première réponse après démarrage est plus lente (warm-up)

---

## Variables d'environnement — Référence complète

| Variable | Requis | Défaut | Description |
|---|---|---|---|
| ANTHROPIC_API_KEY | Oui | — | Clé API Claude |
| ELEVENLABS_API_KEY | Non | — | Clé TTS ElevenLabs |
| ELEVENLABS_VOICE_ID | Non | Rachel | ID voix ElevenLabs |
| OPENAI_API_KEY | Non | — | Clé TTS OpenAI |
| PORCUPINE_ACCESS_KEY | Non | — | Clé wake word Porcupine |
| VOSK_MODEL_PATH | Non | — | Chemin modèle Vosk |
| OBSIDIAN_VAULT_PATH | Non | — | Chemin vault Obsidian |
| WHISPER_MODEL | Non | medium | Taille modèle Whisper |
| JARVIS_NAME | Non | Jarvis | Nom du wake word |
| USER_NAME | Non | patron | Comment JARVIS vous appelle |
| LANGUAGE | Non | fr | Langue de transcription |
| SILENCE_THRESHOLD | Non | 1.5 | Secondes de silence avant arrêt |
| MAX_RECORDING_SECONDS | Non | 30 | Durée max d'enregistrement |
| MAX_HISTORY | Non | 10 | Échanges en mémoire de travail |
| DEBUG | Non | false | Logs détaillés |

---

*JARVIS v1.0 — Propulsé par Claude claude-sonnet-4-6, Whisper, ElevenLabs*
