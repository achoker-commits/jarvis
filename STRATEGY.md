# JARVIS — Stratégie d'optimisation

Revue initiale : Claude Fable. Implémentation : sessions successives.

---

## Points réalisés

| # | Point | Fichier(s) | Statut |
|---|---|---|---|
| 1 | `persona.yaml` — données personnelles hors dépôt git | `llm.py`, `persona.yaml` (gitignored) | ✅ |
| 2 | `afplay` → `sounddevice` in-memory (−1 s/échange) | `audio_utils.py`, `main.py` | ✅ |
| 3 | Filler TTS instantané depuis pré-cache avant LLM | `tts.py`, `main.py` | ✅ |
| 4 | `_TOOL_PATTERNS` déclaratif + faux positifs corrigés | `llm.py`, `tests/test_routing.py` | ✅ |
| 5 | `ThreadPoolExecutor` `CMD_DAILY_BRIEF` — 4 API parallèles | `commands.py` | ✅ |
| 6 | Suppression `openai-whisper` (doublon `faster-whisper`) | `requirements.txt` | ✅ |
| 7 | Sections system prompt conditionnelles | `llm.py` | ✅ |
| 8 | Streaming Groq → TTS par phrase + 4 cas limites | `llm.py`, `tts.py` | ✅ |
| 9 | Cache TTS LRU 500 MB avec éviction par `st_atime` | `tts.py` | ✅ |

---

## Détail point 4 — Faux positifs TOOL_PATTERNS

### Problèmes corrigés

| Pattern avant | Faux positif | Correction |
|---|---|---|
| `r"\btemps\b"` | "il passe du bon temps", "temps libre" | Remplacé par `r"\bquel temps\b"` + `r"\btemps qu'il fait\b"` |
| `r"\bdu jazz\b"` (et autres genres) | "l'histoire du jazz", "inventeur du jazz" | Genres requis avec verbe d'action : `r"(?:joue|mets|balance|écoute|...).{0,40}(?:du jazz|...)"` |
| `r"\bjoue\b"` | "joue au foot", "joue à la PS5" | Lookahead négatif : `r"\bjoue(?!\s+(?:au|aux|à)(?:\s|$))\b"` |
| `r"\bjouer\b"` | "jouer aux cartes" | Même lookahead négatif |

### Tests (42 cas)
- `tests/test_routing.py` — 27 cas originaux + 15 cas faux positifs/vrais positifs

---

## Détail point 5 — ThreadPoolExecutor CMD_DAILY_BRIEF

4 appels API en parallèle (max_workers=4, timeout=10s) :

| Clé | Outil | Données |
|---|---|---|
| `meteo` | `execute_tool("meteo", ...)` | Open-Meteo (gratuit) |
| `obsidian` | `execute_tool("obsidian", ...)` | Vault local |
| `cal` | `execute_tool("calendrier", ...)` | AppleScript macOS |
| `emails` | `execute_tool("emails", ...)` | Mail macOS |

Séquentiels (accès local, non bloquants) :
- Mémoire persistante → rappels (`get_facts`)
- Stats NexaTel → leads/conversions

---

## Métriques latence cibles

| Étape | Avant | Cible après |
|---|---|---|
| Wake word → 1ère phrase | ~4 s | < 2 s |
| Réponse simple (streaming) | ~2.5 s | < 1.5 s |
| Réponse avec outil | ~3.5 s | < 2.5 s |
| Daily brief | ~2 s (séquentiel) | ~0.6 s (parallèle) |

---

## Points à venir

| # | Point | Priorité | Notes |
|---|---|---|---|
| 10 | Routeur d'intentions unifié | P2 | Fusionner `CMD_PATTERNS` (commands.py) et `_TOOL_PATTERNS` (llm.py) |
| 11 | Embeddings Obsidian (recherche sémantique) | P2 | Remplace recherche textuelle naïve |
| 12 | Briefing proactif sans commande vocale | P3 | Surveillance horloge côté JARVIS |
| 13 | Tests d'intégration bout en bout | P2 | Pipeline complet STT → LLM → TTS mockés |
