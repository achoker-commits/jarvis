# JARVIS — Stratégie d'optimisation

Revue initiale : Claude Fable. Implémentation : sessions successives.

---

## GEL DU PROJET — 02/07/2026

### État fonctionnel à la mise en pause

| Composant | État | Notes |
|---|---|---|
| Wake word (Whisper KW) | ✅ Fonctionnel | Détection "Jarvis" + aliases phonétiques + Levenshtein |
| STT (faster-whisper medium) | ✅ Fonctionnel | VAD webrtcvad, débruitage noisereduce |
| TTS (Edge TTS fr-FR-HenriNeural) | ✅ Fonctionnel | Streaming par phrase, cache LRU 500 MB |
| Météo (Open-Meteo) | ✅ Fonctionnel | Outil `meteo`, timeout 8s |
| Batterie / système (pmset) | ✅ Fonctionnel | Outil `systeme` |
| Bourse (yfinance) | ✅ Fonctionnel | ThreadPoolExecutor timeout 8s |
| Mémoire persistante JSON | ✅ Fonctionnel | `~/.jarvis_memory.json`, auto-extraction |
| Tools streaming (Groq) | ✅ Fonctionnel | 72 tests passent, 3 formats inline détectés |
| Filtre inline `<function=…>` | ✅ Fonctionnel | Regex + end-of-stream recovery |
| Pipeline audio post-freeze | ✅ Fonctionnel | sleep(0.2) entre wake word et micro, 1 seul thread clavier |
| Logs cycle de vie audio | ✅ Ajoutés | `[WAKE]`, `[REC]`, `[CYCLE]` à chaque transition |

### Bugs résiduels connus

| Bug | Symptôme | Cause racine identifiée |
|---|---|---|
| Pseudo-code `<function=…>` dans les réponses | llama-3.3 émet du texte brut imitant un tool call au lieu d'utiliser le mécanisme natif — le filtre fonctionne sur les formats connus mais llama peut en inventer de nouveaux | **llama-3.3-70b-versatile** génère ce format de façon non déterministe sur les questions philosophiques ou conversationnelles longues |
| Freeze 50-85 s sur questions conversationnelles | Le LLM prend un temps anormalement long à répondre aux questions ouvertes (philosophie, opinion) — aucun outil en cause | **llama-3.3** max_tokens atteint + retry Groq — architectural, pas corrigeable côté JARVIS |
| Filtre TTS inopérant sur certains chemins | Sur le chemin `_execute_and_respond_stream` après un tool call, du texte `<function=…>` résiduel peut atteindre le TTS si llama chaîne un 2e tool call de façon non standard | Chemin de code secondaire — nécessite refactoring LLM provider |

### Diagnostic établi

**Ces 3 bugs ont une cause commune : `llama-3.3-70b-versatile` (Groq).** Le modèle est excellent pour le small talk et les outils simples, mais génère des comportements non déterministes sur les requêtes complexes ou longues. L'architecture JARVIS est saine — les bugs disparaîtront en changeant de cerveau.

---

### PROCHAINE ÉTAPE À LA REPRISE : Migration vers Claude (Anthropic)

**Ne PAS continuer à débugger llama.** Le temps de debug dépasse le coût d'une migration.

#### Plan de migration

1. **Créer `llm_provider.py`** — abstraction `LLMProvider` (interface commune `chat_stream`, `chat_with_tools`, `chat_sync`)
2. **Implémenter `ClaudeProvider`** — `anthropic` SDK, `claude-haiku-4-5` pour la vitesse, `claude-sonnet-4-6` pour les tools complexes
3. **Garder `GroqProvider`** pour le small talk (latence < 500 ms, coût zéro)
4. **Routing hybride** dans `llm.py` :
   - Question courte / small talk → Groq llama (rapide, gratuit)
   - Tool call → Claude Haiku (fiable, format strict)
   - Requête NexaTel / longue → Claude Haiku (cohérence)
5. **Supprimer tout le code de détection `<function=…>`** — Claude utilise le tool use natif JSON, jamais de pseudo-code inline

#### Coût estimé
- Claude Haiku : ~$0.25/M tokens input, ~$1.25/M output
- Usage JARVIS estimé : 200-300 échanges/mois × ~500 tokens moyenne = **3-4$/mois**
- Groq (small talk) : gratuit

#### Fichiers à modifier
| Fichier | Changement |
|---|---|
| `llm_provider.py` | Créer (nouveau) |
| `llm.py` | Adapter `LLMEngine` pour déléguer à `GroqProvider` ou `ClaudeProvider` |
| `config.py` | Ajouter `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` |
| `llm.py` | Supprimer `_MF_COMPLETE`, `_MF_PARTIAL`, `_parse_inline`, filtres inline |
| `tts.py` | Simplifier `_clean_for_tts` (filtre inline inutile avec Claude) |
| `tests/test_streaming.py` | Adapter cas 5 et 6 (plus pertinents) |

#### Tests de validation post-migration
- `python3 -m pytest tests/ -q` → 72+ tests verts
- Question philosophique longue → pas de freeze
- Tool call météo → JSON propre, pas de `<function=…>`
- Small talk "comment tu vas" → Groq, < 600ms

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
| 7 | Sections system prompt conditionnelles — NexaTel bloc injecté seulement si pertinent | `llm.py` | ✅ |

---

## Détail point 7 — Restructuration system prompt

### Problème avant
- `_SYSTEM_PERSONA` injectait TOUT (profil user + prix NexaTel + arguments + règles) à chaque appel
- ~2000 chars (~500 tokens) de données NexaTel injectées même pour "quelle heure est-il ?"
- Le préfixe du prompt changeait à chaque appel (persona_block avant la partie stable) → cache Groq inutilisable

### Architecture après

| Section | Contenu | Stabilité |
|---|---|---|
| `_SYSTEM_CORE` | Identité, règles ton, outils, 6 exemples, mémorisation | **Identique à chaque appel** → cache Groq |
| `_build_user_profile_block()` | Profil user + personnalité (sans prix NexaTel) | Stable (ne change que si persona.yaml change) |
| `_build_nexatel_block()` | Prix, arguments, règles NexaTel | **Conditionnel** — injecté seulement si pertinent |
| Contexte dynamique | Date/heure, mémoire, notes Obsidian | Change par appel |

### Logique de détection NexaTel
`_is_nexatel_relevant(query, history, last_n=3)` :
- Cherche dans la requête courante ET les 3 derniers tours d'historique
- Mots-clés déclencheurs : nexatel, proximus, orange, voo, client, prix, tarif, offre, abonnement, opérateur, réseau, internet, lead, prospect, pitch, convaincre, concurrent, télécom, fibre

### Ordre d'assemblage (cache Groq)
```
_SYSTEM_CORE              ← stable — jamais modifié entre deux appels
safe_profile              ← stable — change seulement si persona.yaml change
safe_nexatel              ← conditionnel — deux entrées de cache (avec/sans NexaTel)
━━━ CONTEXTE DYNAMIQUE ━━━ ← change à chaque appel, mis EN DERNIER
  Utilisateur / Date/heure
  Mémoire
  Notes Obsidian
```
**Règle absolue : rien de dynamique ne doit précéder les blocs stables.**

### Hystérésis NexaTel
`self._nexatel_turns_remaining` (int, initialisé à 0) sur `LLMEngine` :
- Mot-clé détecté → compteur = 9 (tour courant + 8 suivants)
- Chaque appel à `build_system_prompt` décrémente de 1 si > 0
- Reset automatique si un nouveau mot-clé est détecté en cours de conversation
- Couverture : `tests/test_nexatel_hysteresis.py` (12 tests)

### Métriques
- Prompt requête banale (ex: météo) : ~6100 chars
- Prompt requête NexaTel : ~8100 chars
- **Gain : ~500 tokens épargnés par appel non-NexaTel**
- Cache Groq actif sur : `_SYSTEM_CORE` + `safe_profile` ≈ 1400+ tokens de préfixe stable

### Exemples few-shot réduits : 11 → 6 (comportements distincts)
| # | Exemple | Comportement |
|---|---|---|
| 1 | "Comment tu vas ?" | Small talk / ton naturel |
| 2 | "Lance Spotify." | Tool call action (sans commenter) |
| 3 | "Combien vaut le bitcoin ?" | Tool call données dynamiques |
| 4 | "J'suis fatigué." | Réponse émotionnelle |
| 5 | "T'es con toi." | Confrontation / humour sec |
| 6 | "Un client qui hésite..." | Contexte business |

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
