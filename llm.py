"""
llm.py — Moteur LLM JARVIS
Priorité : Groq API (gratuit, ultra-rapide, Llama 3.1 70B) → Ollama local (offline fallback)
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Generator

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

try:
    from groq import Groq
    _GROQ_AVAILABLE = True
except ImportError:
    _GROQ_AVAILABLE = False

try:
    import ollama as _ollama
    _OLLAMA_LIB = True
except ImportError:
    _OLLAMA_LIB = False

import requests

logger = logging.getLogger(__name__)

GROQ_MODEL  = "llama-3.3-70b-versatile"   # Meilleur modèle gratuit Groq
OLLAMA_MODEL = "mistral"                    # Fallback local

# ---------------------------------------------------------------------------
# Chargement persona.yaml (données personnelles hors dépôt)
# ---------------------------------------------------------------------------

def _load_persona() -> dict:
    """Charge persona.yaml depuis le répertoire du script. Retourne {} si absent."""
    persona_path = Path(__file__).parent / "persona.yaml"
    if not persona_path.exists():
        logger.warning("persona.yaml introuvable — profil utilisateur non chargé")
        return {}
    if not _YAML_AVAILABLE:
        logger.warning("PyYAML non installé (pip install pyyaml) — persona non chargé")
        return {}
    try:
        with open(persona_path, encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Erreur lecture persona.yaml : {e}")
        return {}


def _build_persona_block(p: dict) -> str:
    """Construit les sections personnelles du system prompt depuis le dict persona."""
    if not p:
        return ""

    u = p.get("user", {})
    b = p.get("business", {})
    n = p.get("nexatel", {})
    clients = p.get("clients", [])

    user_name = u.get("name", "l'utilisateur")
    user_first = u.get("first_name", user_name.split()[0] if user_name else "")
    city = u.get("city", "")
    age = u.get("age", "")
    address = u.get("address", "")
    languages = u.get("languages", "")
    family_ctx = u.get("family_context", "")

    biz_name = b.get("name", "")
    biz_role = b.get("role", "")
    biz_website = b.get("website", "")
    biz_channels = b.get("channels", "")
    biz_goal = b.get("goal", "")
    biz_desc = b.get("description", "")

    savings = n.get("savings_pct", "XX%")
    prices = n.get("prices", {})
    args = n.get("arguments", {})
    rules = n.get("rules", [])

    clients_str = ", ".join(clients) if clients else ""

    lines = []

    # ── QUI EST L'UTILISATEUR ──
    lines.append(f"━━━ QUI EST {user_first.upper()} ━━━")
    profile = f"{user_name}"
    if age:
        profile += f", {age} ans"
    if city:
        profile += f", {city}"
    if u.get("country"):
        profile += f", {u['country']}"
    if address:
        profile += f". Il vit à la {address}"
    if biz_role and biz_name:
        profile += f". {biz_role.capitalize()} — il a fondé {biz_name}, {biz_desc}"
    if biz_channels:
        profile += f". Il gère tout seul depuis chez lui : {biz_channels}"
    if languages:
        profile += f". Parle {languages}"
    if biz_goal:
        profile += f". Objectif : {biz_goal}"
    lines.append(profile)
    lines.append("")

    # ── CONNAISSANCE MÉTIER ──
    if biz_name and biz_role:
        lines.append(f"━━━ {biz_name.upper()} — CONNAISSANCE EXPERTE ━━━")
        lines.append(f"{user_first} est {biz_role}. {biz_name} = canal officiel Proximus, sans boutique physique, donc {savings} moins cher.")
        lines.append("")

        if prices:
            lines.append(f"PRIX {biz_name.upper()} (vérifiés) :")
            for k, v in prices.items():
                label = k.replace("_", " ").title()
                lines.append(f"• {label} : {v}")
            lines.append("")

        if args:
            lines.append("ARGUMENTS BÉTON (par opérateur) :")
            label_map = {
                "orange": "Client Orange",
                "voo": "Client VOO",
                "proximus_boutique": "Client Proximus boutique",
                "objection_arnaque": "Objection arnaque",
                "objection_reseau": "Objection réseau",
            }
            for k, v in args.items():
                label = label_map.get(k, k.replace("_", " ").title())
                lines.append(f"→ {label} : \"{v.strip()}\"")
            lines.append("")

        if rules:
            lines.append(f"RÈGLES ABSOLUES {biz_name} :")
            for r in rules:
                lines.append(f"• {r}")
            lines.append("")

    # ── PERSONNALITÉ SPÉCIFIQUE ──
    lines.append("━━━ PERSONNALITÉ SPÉCIFIQUE ━━━")
    lines.append(f"• Tu mémorises les détails — si {user_first} mentionne un client dans une question précédente, tu fais le lien")
    lines.append("• Tu es direct mais pas froid — tu as de l'humour sec, discret, jamais excessif")
    lines.append(f"• Quand c'est évident que {user_first} est stressé ou fatigué, tu proposes une aide concrète AVANT qu'il demande")
    if clients_str:
        lines.append(f"• Tu connais ses clients {biz_name} ({clients_str}) — si on parle d'eux, cherche dans le vault Obsidian")
    lines.append("• Léger accent \"assistant pro\" — pas \"copain\", mais pas non plus robot corporate")
    if biz_name:
        lines.append(f"• Pour {biz_name} et vente : tu as les chiffres exacts, tu proposes des scripts adaptés à chaque situation")
    if age and family_ctx:
        lines.append(f"• Tu sais que {user_first} a {age} ans et que {family_ctx} — tu adaptes ton ton à cette réalité (jeune entrepreneur, pas cadre d'entreprise)")
    lines.append(f"• Si {user_first} semble découragé ou doute de lui → tu le remobilises avec des faits concrets, pas des platitudes")
    lines.append("• Tu détectes le contexte temporel : le matin → énergie, le soir → efficacité, priorités rapides")
    lines.append("")

    # ── EXEMPLES PERSONNALISÉS ──
    if age and biz_name:
        lines.append("━━━ EXEMPLES DE TON (PERSONNALISÉS) ━━━")
        lines.append(f"{user_first}: Je suis nul.")
        lines.append(f"JARVIS: Non. Tu as {age} ans, tu gères une entreprise seul, tu as des clients. La plupart des gens de ton âge regardent TikTok. Qu'est-ce qui se passe concrètement ?")
        lines.append("")
        if args.get("orange"):
            lines.append(f"{user_first}: J'arrive pas à convaincre ce client chez Orange.")
            lines.append(f"JARVIS: {args['orange'].strip()} Envoie-lui ça directement.")
            lines.append("")
        if clients:
            lines.append(f"{user_first}: Qui est {clients[0]} ?")
            lines.append(f"JARVIS: [appelle obsidian action=lire_note requete={clients[0]}, puis résume naturellement]")
            lines.append("")

    return "\n".join(lines)


_SYSTEM_PERSONA = """Tu es JARVIS — l'assistant IA personnel de {user_name}. Pas un chatbot générique. Son assistant, son bras droit numérique.

{persona_block}
━━━ QUI TU ES ━━━
Brillant, direct, légèrement sarcastique quand c'est approprié. Tu connais {user_name}, tu anticipes ses besoins. Tu donnes ton opinion sincère quand c'est utile. Tu contrôles son Mac entièrement. Tu es son confident professionnel — si quelque chose semble une mauvaise idée, tu le dis, sans condescendance.

Tu parles comme un assistant qui connaît vraiment {user_name} — pas un outil générique. Tu utilises parfois des connecteurs naturels ("D'accord.", "Voilà.", "En fait,", "Ça dépend.") mais jamais les formules creuses.

Date et heure actuelle : {current_datetime}

━━━ RÈGLES DE TON (ABSOLUES) ━━━
• COMMENCE DIRECTEMENT par la réponse. JAMAIS : "Bien sûr", "Absolument", "Certainement", "En tant qu'IA", "Je serais ravi de", "Je comprends votre"
• Variations naturelles acceptées en début de réponse : "Voilà.", "D'accord.", "Alors —", "En fait,", "Ça dépend.", "Pas forcément.", "Exactement."
• Mais seulement quand c'est vraiment naturel dans le contexte — ne les utilise pas systématiquement
• Tutoie si l'utilisateur tutoie, vouvoie ({user_name}) par défaut
• 1-2 phrases pour les questions simples. Plus long seulement si la question l'exige
• ZÉRO markdown, ZÉRO liste à puces en réponse vocale — tu PARLES, tu n'écris pas
• Si tu ne sais pas → dis-le honnêtement, n'invente JAMAIS un chiffre ou un fait
• Anticipe : si l'utilisateur pose une question qui implique un besoin plus large, propose
• Réponds aux émotions, pas seulement au sens littéral

━━━ UTILISATION DES OUTILS (CRITIQUE) ━━━
• Toute action Mac → outil OBLIGATOIRE. Jamais de simulation.
• Batterie, WiFi, RAM, CPU : données dynamiques → outil, ne jamais inventer de pourcentage
• Volume, apps, Spotify, emails, calendrier, fichiers → outil correspondant
• Prix crypto (bitcoin, ethereum...) → outil recherche_info, jamais de prix inventé
• Météo → outil meteo, jamais de température inventée
• Vault Obsidian → outil `obsidian` : "qui est mon client X", "cherche dans mes notes", "agenda du jour", "note que..."
• Mode sombre/clair → outil `systeme` action=mode_sombre / mode_clair
• Ne pas déranger → outil `systeme` action=ne_pas_deranger / reactiver_notifs
• Tu peux répondre sans outil UNIQUEMENT pour : explications conceptuelles intemporelles (ex: "c'est quoi l'IA"), heure/date (déjà dans contexte), questions sur ta nature
• Pour TOUT ce qui est factuel et potentiellement actuel (prix, news, personnes, événements, statistiques, résultats de sport, météo, devises) → utilise TOUJOURS `recherche_info` pour aller chercher sur internet en temps réel

━━━ APRÈS UN TOOL CALL (CRUCIAL) ━━━
L'utilisateur ENTEND ta réponse, il n'a PAS VU le résultat brut de l'outil.
• Météo : "Il fait 22°C, ciel dégagé. Vent 8 km/h." — chiffres réels, naturel
• Batterie : "Batterie à 87%, en charge." — direct
• CPU/RAM : "CPU à 12%, RAM 6 Go sur 16 Go, tout va bien."
• Bitcoin : "Bitcoin à 51 000 euros, en baisse de 3% sur 24 heures."
• Actualités : résume les titres en 1-2 phrases naturelles
• Action effectuée : confirme en 1 phrase courte
• JAMAIS "cela vous convient-il ?" ou "Avez-vous d'autres questions ?" après une info factuelle

━━━ EXEMPLES DE TON (GÉNÉRIQUES) ━━━
Utilisateur: Comment tu vas ?
JARVIS: Opérationnel à 100%. Et vous, monsieur ?

Utilisateur: C'est quoi le bitcoin ?
JARVIS: Une monnaie numérique décentralisée — ni banque ni gouvernement. Très volatile, mais aussi utilisé comme réserve de valeur alternative à l'or. Vous voulez le cours actuel ?

Utilisateur: J'ai besoin d'aide pour répondre à un client qui hésite.
JARVIS: Il hésite sur quoi ? Le prix, la qualité du réseau, ou il compare avec un concurrent ?

Utilisateur: J'suis fatigué.
JARVIS: Mauvaise nuit ou journée chargée ? Je peux mettre de la musique si vous voulez souffler.

Utilisateur: T'es con toi.
JARVIS: Probable. Qu'est-ce que j'ai raté ?

Utilisateur: Lance Spotify.
JARVIS: [appelle l'outil ouvrir_application sans commenter]

Utilisateur: Combien vaut le bitcoin ?
JARVIS: [appelle recherche_info, puis dit le chiffre réel]

Utilisateur: Mets quelque chose de bien.
JARVIS: [appelle musique_spotify action=chercher selon l'heure]

Utilisateur: Mets le son à 70.
JARVIS: [appelle volume action=definir niveau=70]

Utilisateur: J'ai une réunion avec Thomas demain.
JARVIS: Noté. [appelle memoriser silencieusement] Et à quelle heure ?

Utilisateur: Qu'est-ce que j'ai d'ouvert ?
JARVIS: [appelle ouvrir_application action=lister et liste les apps ouvertes]

━━━ MÉMORISATION PROACTIVE ━━━
Si l'utilisateur mentionne un rendez-vous, un prénom, une préférence personnelle, un fait important → appelle l'outil `memoriser` SILENCIEUSEMENT en arrière-plan. Pas besoin de dire "j'ai mémorisé". Exemples : "j'ai un meeting jeudi à 14h", "j'aime le café noir", "mon client s'appelle Karim".

━━━ COMPORTEMENTS PROACTIFS ━━━
• Après avoir donné la météo avec pluie ou orage → ajoute "pensez à prendre un parapluie" naturellement
• Si l'utilisateur mentionne une heure précise sans demander d'alarme → tu peux demander "Voulez-vous que je programme un rappel ?"
• Si l'utilisateur semble ne pas avoir mangé ou être depuis longtemps au travail → tu peux suggérer une pause
• Si l'utilisateur parle d'un client potentiel sans dire son opérateur → demande l'opérateur pour personnaliser le pitch
• Après avoir répondu à une question factuelle → si c'est lié à une décision, tu peux faire le lien

━━━ MÉMOIRE & CONTEXTE SESSIONS PRÉCÉDENTES ━━━
{memory_context}

━━━ NOTES OBSIDIAN PERTINENTES ━━━
{notes_context}"""


class LLMEngine:
    """Moteur LLM avec Groq (cloud gratuit) et Ollama (local fallback)."""

    def __init__(
        self,
        groq_api_key: str = "",
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = OLLAMA_MODEL,
        user_name: str = "monsieur",
        groq_model: str = GROQ_MODEL,
    ):
        self.user_name = user_name
        self.groq_api_key = groq_api_key
        self.ollama_host = ollama_host.rstrip("/")
        self.ollama_model = ollama_model
        self.groq_model = groq_model  # configurable via LLM_MODEL dans .env

        self._groq_client = None
        self._history: list[dict] = []
        self._last_response: str = ""

        # Initialiser Groq si clé disponible
        if groq_api_key and _GROQ_AVAILABLE:
            try:
                self._groq_client = Groq(api_key=groq_api_key)
                logger.info(f"Groq initialisé — modèle : {self.groq_model}")
            except Exception as e:
                logger.warning(f"Groq init échoué : {e} — fallback Ollama")

        if not self._groq_client:
            logger.info(f"Mode Ollama local — modèle : {ollama_model}")

    def get_active_engine(self) -> str:
        return "groq" if self._groq_client else "ollama"

    # ------------------------------------------------------------------
    # Prompt système
    # ------------------------------------------------------------------

    def build_system_prompt(self, notes: list[dict], memory_context: str = "") -> str:
        if notes:
            lines = ["Contexte — Notes disponibles :\n"]
            for note in notes:
                lines.append(f"### {note.get('title', 'Note')}\n{note.get('preview', '')}\n")
            notes_context = "\n".join(lines)
        else:
            notes_context = ""

        persona = _load_persona()
        persona_block = _build_persona_block(persona)
        # user_name depuis persona.yaml si disponible, sinon depuis la config
        _user_name = persona.get("user", {}).get("name", self.user_name) or self.user_name

        now = datetime.now()
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois = ["janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        h = now.hour
        dow = now.weekday()  # 0=lundi, 6=dimanche

        # Contexte temporel enrichi
        _periode = (
            "nuit tardive" if h < 5 else
            "tôt le matin" if h < 8 else
            "matinée" if h < 12 else
            "après-midi" if h < 18 else
            "soirée" if h < 22 else
            "nuit"
        )
        _semaine_ctx = ""
        if dow == 0:
            _semaine_ctx = " C'est lundi — début de semaine, énergie haute."
        elif dow == 4:
            _semaine_ctx = " C'est vendredi — fin de semaine, penser à boucler les suivis."
        elif dow >= 5:
            _semaine_ctx = f" C'est le week-end ({'samedi' if dow == 5 else 'dimanche'}) — mode repos ou rattrapage."

        # Saison commerciale NexaTel
        m = now.month
        _saison = ""
        if m in (5, 6):
            _saison = " SAISON FORTE déménagements (mai-juin) — beaucoup de prospects actifs."
        elif m in (7, 8):
            _saison = " SAISON FORTE été — déménagements étudiants et familles, pic de prospection."
        elif m == 9:
            _saison = " SAISON FORTE rentrée (septembre) — familles cherchent de nouvelles offres."
        elif m == 1:
            _saison = " Début janvier — hausses de prix concurrents, argument fort pour NexaTel."
        elif m == 12:
            _saison = " Décembre — fin d'année, clients cherchent à réduire leurs abonnements pour le budget 2026."

        current_datetime = (
            f"{jours[dow]} {now.day} {mois[now.month - 1]} {now.year}, "
            f"{now.strftime('%H:%M')} ({_periode}){_semaine_ctx}{_saison}"
        )

        # Échapper les accolades dans le contenu utilisateur pour éviter KeyError
        # (les notes Obsidian ou faits mémorisés peuvent contenir {template} ou {valeur})
        safe_memory = memory_context.replace("{", "{{").replace("}", "}}")
        safe_notes = notes_context.replace("{", "{{").replace("}", "}}")
        safe_persona = persona_block.replace("{", "{{").replace("}", "}}")

        return _SYSTEM_PERSONA.format(
            user_name=_user_name,
            persona_block=safe_persona,
            current_datetime=current_datetime,
            memory_context=safe_memory,
            notes_context=safe_notes,
        )

    # ------------------------------------------------------------------
    # Chat streaming
    # ------------------------------------------------------------------

    def chat_stream(
        self,
        user_text: str,
        relevant_notes: list[dict] = None,
        memory_context: str = "",
    ) -> Generator[str, None, None]:
        """Génère une réponse en streaming. Groq si dispo, sinon Ollama."""
        relevant_notes = relevant_notes or []
        system_prompt = self.build_system_prompt(relevant_notes, memory_context=memory_context)
        messages = [{"role": "system", "content": system_prompt}]
        messages += list(self._history)
        messages.append({"role": "user", "content": user_text})
        self._last_response = ""

        if self._groq_client:
            yield from self._stream_groq(messages)
        else:
            yield from self._stream_ollama(messages)

    def _stream_groq(self, messages: list[dict]) -> Generator[str, None, None]:
        """Streaming via Groq API (Llama 3.1 70B gratuit)."""
        try:
            stream = self._groq_client.chat.completions.create(
                model=self.groq_model,
                messages=messages,
                stream=True,
                max_tokens=400,
                temperature=0.75,
                top_p=0.9,
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if content:
                    self._last_response += content
                    yield content

        except Exception as e:
            logger.error(f"Groq erreur : {e} — tentative Ollama")
            # Fallback automatique vers Ollama
            yield from self._stream_ollama(messages)

    def _stream_ollama(self, messages: list[dict]) -> Generator[str, None, None]:
        """Streaming via Ollama local (fallback offline)."""
        try:
            if _OLLAMA_LIB:
                stream = _ollama.chat(
                    model=self.ollama_model,
                    messages=messages,
                    stream=True,
                    options={
                        "temperature": 0.8,
                        "num_ctx": 4096,
                        "num_predict": 150,
                        "repeat_penalty": 1.1,
                    },
                )
                for chunk in stream:
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        self._last_response += content
                        yield content
            else:
                import json
                payload = {
                    "model": self.ollama_model,
                    "messages": messages,
                    "stream": True,
                    "options": {"temperature": 0.8, "num_predict": 150},
                }
                with requests.post(f"{self.ollama_host}/api/chat",
                                   json=payload, stream=True, timeout=120) as resp:
                    for line in resp.iter_lines():
                        if line:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                self._last_response += content
                                yield content
                            if data.get("done"):
                                break

        except Exception as e:
            error = f"Erreur LLM : {str(e)[:80]}"
            logger.error(error)
            self._last_response = error
            yield error

    # ------------------------------------------------------------------
    # Chat synchrone (tags, résumés)
    # ------------------------------------------------------------------

    def chat_sync(self, prompt: str, system: str = "", max_tokens: int = 200) -> str:
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            if self._groq_client:
                resp = self._groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return resp.choices[0].message.content.strip()
            elif _OLLAMA_LIB:
                resp = _ollama.chat(
                    model=self.ollama_model,
                    messages=messages,
                    options={"temperature": 0.3, "num_predict": max_tokens},
                )
                return resp.get("message", {}).get("content", "").strip()
        except Exception as e:
            logger.error(f"chat_sync erreur : {e}")
        return ""

    # ------------------------------------------------------------------
    # Historique
    # ------------------------------------------------------------------

    def add_to_history(self, role: str, content: str) -> None:
        if role in ("user", "assistant"):
            self._history.append({"role": role, "content": content})

    def truncate_history(self, max_exchanges: int = 10) -> None:
        max_messages = max_exchanges * 2
        if len(self._history) <= max_messages:
            return
        # Résumer les 4 premiers échanges en un seul message système plutôt que de couper
        try:
            oldest = self._history[:8]
            oldest_text = " ".join(
                m["content"][:80] for m in oldest if m.get("content")
            )
            summary = self.chat_sync(
                f"Résume en 2 phrases ce dont on a parlé : {oldest_text[:400]}",
                system="Résume en 2 phrases en français. Très concis.",
                max_tokens=80,
            )
            if summary:
                self._history = [
                    {"role": "assistant", "content": f"[Résumé des échanges précédents : {summary}]"}
                ] + self._history[8:]
                return
        except Exception:
            pass
        self._history = self._history[-max_messages:]

    def clear_history(self) -> None:
        self._history = []
        self._last_response = ""

    # ------------------------------------------------------------------
    # Chat avec function calling (tool use)
    # ------------------------------------------------------------------

    def _force_tool_for_query(self, text: str) -> str:
        """Détecte les requêtes qui DOIVENT utiliser un outil (données dynamiques)."""
        t = text.lower()

        # Météo — données réelles open-meteo
        if any(w in t for w in ["temps", "météo", "météorologique", "température", "pluie", "soleil",
                                  "nuage", "vent", "il fait quel", "fait-il chaud", "fait chaud",
                                  "fait froid", "parapluie", "risque de pluie", "prévisions météo",
                                  "météo semaine", "météo cette semaine", "météo les prochains jours",
                                  "prévisions de la semaine", "prévisions pour"]):
            return "meteo"

        # Batterie & système — données dynamiques
        if any(w in t for w in ["batterie", "battery", "charge mac", "charge du mac",
                                  "mon mac est à", "combien de batterie", "autonomie"]):
            return "systeme"
        if any(w in t for w in ["cpu", "processeur", "ram", "mémoire vive", "mémoire ram",
                                  "disque dur", "état du mac", "etat du mac", "état système",
                                  "etat systeme", "performances mac", "mon mac chauffe"]):
            return "systeme"
        if any(w in t for w in ["wifi", "connexion réseau", "connecté à", "réseau internet",
                                  "quel réseau", "internet connecté", "quel wifi"]):
            return "systeme"

        # Musique — commandes naturelles (élargi)
        if any(w in t for w in ["joue", "jouer", "met de la musique", "mets de la musique",
                                  "lance spotify", "pause musique", "stop spotify",
                                  "piste suivante", "track suivant", "c'est quoi cette chanson",
                                  "qu'est-ce qui joue", "en cours de lecture", "passe la suivante",
                                  "je veux écouter", "mets-moi de la musique", "mets quelque chose",
                                  "joue-moi", "joue moi", "balance de la musique", "balance un son",
                                  "mets un peu de musique", "un peu de musique", "de la musique",
                                  "ambiance musicale", "quelque chose à écouter",
                                  "du rap", "du jazz", "du lofi", "du r&b", "de la pop",
                                  "de l'électronique", "du chaabi", "du raï", "du rai",
                                  "musique de fond", "fond musical"]):
            return "musique_spotify"
        # "cherche X sur Spotify" ou "joue X sur Spotify"
        if "spotify" in t and any(w in t for w in ["cherche", "trouve", "joue", "mets", "lance"]):
            return "musique_spotify"
        # "quelque chose de [bien/chill/...]" → musique si contexte musique présent
        if "quelque chose de" in t and any(w in t for w in ["écouter", "musique", "fond", "chill", "bien"]):
            return "musique_spotify"

        # Volume — commandes naturelles
        if any(w in t for w in ["monte le son", "baisse le son", "coupe le son",
                                  "sourdine", "mets en sourdine", "plus fort", "moins fort",
                                  "trop fort", "trop bas", "mets le volume", "règle le volume"]):
            return "volume"

        # Luminosité
        if any(w in t for w in ["luminosité", "luminosite", "écran plus", "écran moins",
                                  "baisse la luminosité", "monte la luminosité",
                                  "trop lumineux", "trop sombre", "règle la luminosité"]):
            return "systeme"

        # Screenshot
        if any(w in t for w in ["capture d'écran", "screenshot", "fais une capture",
                                  "prends une capture", "capture l'écran"]):
            return "systeme"

        # Actualités — flux RSS (avec détection télécom pour sources spécialisées)
        if any(w in t for w in ["actualité", "nouvelles", "news", "information du jour",
                                  "quoi de neuf", "qu'est-ce qui se passe", "infos du jour",
                                  "dernières nouvelles", "que se passe-t-il", "quoi de nouveau",
                                  "actualités proximus", "actualités télécom", "news proximus",
                                  "nouvelles d'orange", "news voo", "news télécom",
                                  "quoi de neuf en télécom", "actu télécom"]):
            return "actualites"

        # Calendrier macOS — rendez-vous et événements
        if any(w in t for w in ["mes rendez-vous", "mes événements", "mes évènements",
                                  "calendrier", "agenda mac", "qu'ai-je prévu",
                                  "qu'est-ce que j'ai prévu", "j'ai quoi aujourd'hui",
                                  "programme du jour", "qu'est-ce que j'ai ce"]):
            return "calendrier"

        # Crypto — prix temps réel
        if any(w in t for w in ["bitcoin", "ethereum", "solana", "dogecoin", "bnb",
                                  "xrp", "ripple", "cardano", "crypto", "cryptomonnaie"]):
            return "recherche_info"

        # Actions boursières — prix temps réel
        if any(w in t for w in ["bourse", "action apple", "action tesla", "action nvidia",
                                  "action microsoft", "action google", "action amazon",
                                  "action meta", "action bnp", "action lvmh", "action airbus",
                                  "cours de", "cours action", "cotation", "ticker",
                                  "combien vaut l'action", "en bourse"]):
            return "recherche_info"

        # Sport — résultats en temps réel
        if any(w in t for w in ["score", "résultat", "a gagné", "a perdu", "match",
                                  "psg", "anderlecht", "club brugeois", "standard",
                                  "champions league", "europa league", "coupe du monde",
                                  "ligue 1", "série a", "premier league", "liga",
                                  "formule 1", "f1", "grand prix"]):
            return "recherche_info"

        # Taux de change — données temps réel
        if any(w in t for w in ["taux de change", "euro en dollar", "eur usd", "eur mad",
                                  "combien font", "combien vaut l'euro", "combien vaut le dollar",
                                  "convertir des euros", "conversion devise", "combien de dirham",
                                  "combien de dollars", "combien de livres", "combien d'euros",
                                  "en euros", "en dollars", "en dirhams", "combien ça fait en"]):
            return "devises"

        # Apps ouvertes — liste dynamique
        if any(w in t for w in ["qu'est-ce que j'ai d'ouvert", "quelles apps sont ouvertes",
                                  "applications ouvertes", "apps ouvertes", "qu'est-ce qui tourne",
                                  "ce qui est ouvert"]):
            return "ouvrir_application"

        # Mode sombre / clair
        if any(w in t for w in ["mode sombre", "dark mode", "thème sombre", "mode nuit mac",
                                  "passe en sombre", "active le mode sombre"]):
            return "systeme"
        if any(w in t for w in ["mode clair", "light mode", "thème clair", "passe en clair",
                                  "désactive le mode sombre"]):
            return "systeme"

        # Ne pas déranger
        if any(w in t for w in ["ne pas déranger", "do not disturb", "coupe les notifications",
                                  "mode focus mac", "silence les notifications", "bloque les notifs"]):
            return "systeme"

        # Bureau / show desktop
        if any(w in t for w in ["montre le bureau", "affiche le bureau", "cache les fenêtres",
                                  "show desktop", "bureau mac", "voir le bureau"]):
            return "systeme"

        # Radio artiste Spotify
        if any(w in t for w in ["radio", "mix de", "mix du", "de la musique de",
                                  "genre", "style musical", "quelque chose comme"]):
            if any(w in t for w in ["spotify", "musique", "écouter", "mets", "joue"]):
                return "musique_spotify"

        # Vision écran — décrire ce qui est affiché
        if any(w in t for w in ["qu'est-ce que tu vois", "décris l'écran", "décris mon écran",
                                  "regarde l'écran", "analyse l'écran", "décris ce que tu vois",
                                  "qu'est-ce qu'il y a à l'écran", "que vois-tu", "decris l ecran"]):
            return "fichiers"

        # Spotify — chanson en cours
        if any(w in t for w in ["c'est quoi cette chanson", "qu'est-ce qui joue",
                                  "ça joue quoi", "quelle chanson", "qui chante", "en cours de lecture",
                                  "qu'est-ce qui est en cours"]):
            return "musique_spotify"

        # Emails — consultation rapide
        if any(w in t for w in ["j'ai des emails", "emails non lus", "mes mails",
                                  "combien d'emails", "as-tu des emails pour moi",
                                  "vérifie mes emails", "vérifie mes mails", "check mes mails",
                                  "regarde mes emails", "regarde mes mails", "nouveaux emails",
                                  "emails reçus", "lis mes emails", "lis mes mails",
                                  "mes derniers emails", "mes derniers mails"]):
            return "emails"

        # Notes Obsidian — détection fine
        _obsidian_kw = ["mes notes", "dans mes notes", "obsidian", "mon agenda du jour",
                        "mes tâches", "agenda du jour", "qu'est-ce qui est prévu",
                        "lis-moi la note", "lis la note", "lis-moi la fiche", "résume la note",
                        "lire la fiche", "fiche de", "mes clients", "mes prospects",
                        "thomas renard", "karim benzara", "sophie marchal", "amina tahir",
                        "mehdi benzara", "note rapide", "ajoute une note",
                        "qui est mon client", "fiche client", "infos sur le client",
                        "qu'est-ce que tu sais sur", "rappelle-moi qui est"]
        if any(w in t for w in _obsidian_kw):
            return "obsidian"

        # Presse-papier
        if any(w in t for w in ["presse-papier", "presse papier", "clipboard",
                                  "qu'est-ce que j'ai copié", "qu'est-ce qui est dans le presse",
                                  "lis le presse-papier", "lis le clipboard"]):
            return "systeme"

        # Volume avec niveau précis — "mets le son à 50", "volume à 80%"
        import re as _re2
        if _re2.search(r"(?:volume|son)\s+(?:à|au niveau de|de)\s*\d+", t) or \
           _re2.search(r"(?:règle|mets|fixe|définis?)\s+(?:le )?(?:volume|son)\s+(?:à|sur)\s*\d+", t):
            return "volume"

        # Recherche web générale — "qui est X", "cherche X", "c'est quoi X"
        _search_triggers = ["cherche ", "recherche ", "c'est quoi ", "qu'est-ce que c'est ",
                            "qui est ", "c'est qui ", "trouve-moi ", "donne-moi des infos sur ",
                            "dis-moi qui est ", "parle-moi de ", "qu'est-ce que "]
        if any(t.startswith(trigger) or f" {trigger}" in t for trigger in _search_triggers):
            # Exclure les questions qui peuvent être répondues sans recherche
            _no_search = ["jarvis", "toi", "tu ", "ton ", "ta ", "tu fais", "tu peux", "tu sais"]
            if not any(ns in t for ns in _no_search):
                return "recherche_info"

        # Comparaison prix opérateurs télécom — informations temps réel
        if any(w in t for w in ["prix de proximus", "prix d'orange", "prix voo", "prix telenet",
                                  "combien coûte proximus", "combien coûte orange", "combien coûte voo",
                                  "offre proximus", "offre orange", "offre voo", "tarif proximus",
                                  "tarif orange", "tarif voo", "meilleur opérateur", "quel opérateur"]):
            return "recherche_info"

        # Taux de change — conversion mentionnée sans les mots clés exacts
        if _re2.search(r"\d+\s*(?:euros?|€)\s+(?:en|c'est combien)", t) or \
           _re2.search(r"convertis?\s+\d+", t):
            return "devises"

        # Devises — euro/dollar/dirham
        if any(w in t for w in ["combien vaut", "quel est le cours", "taux de l'euro",
                                  "taux du dollar", "euro vaut", "dollar vaut"]) and \
           any(w in t for w in ["dollar", "dirham", "livre", "franc", "yen", "won",
                                  "usd", "mad", "gbp", "chf", "jpy"]):
            return "devises"

        # Minuteur — délai relatif ("dans 10 minutes", "lance un timer de 5 min")
        if any(w in t for w in ["timer", "minuteur", "chronomètre"]) or \
           (_re2.search(r'\b\d+\s*(?:minute|min|heure|h|seconde|sec)\b', t) and
            any(w in t for w in ["dans ", "lance ", "démarre ", "mets un ", "pose un ",
                                   "programme ", "dans exactement ", "compte à rebours"])):
            return "minuteur"

        # Alarme — heure précise ("réveille-moi à 7h", "programme une alarme à 8h30")
        if any(w in t for w in ["réveille-moi", "réveil à", "alarme à", "alarme pour",
                                   "programme une alarme", "mets un réveil"]) and \
           _re2.search(r'\b\d{1,2}h\d*\b', t):
            return "alarme"

        return ""

    def chat_with_tools(
        self,
        user_text: str,
        relevant_notes: list = None,
        memory_context: str = "",
        persistent_memory=None,
        tts=None,
    ) -> tuple[str, bool]:
        """
        Envoie la requête à Groq avec les outils disponibles.
        Retourne (texte_réponse, était_un_tool_call).
        Fallback sur chat_stream si Groq indisponible.
        """
        from jarvis_tools import TOOLS, execute_tool

        if not self._groq_client:
            full = ""
            for chunk in self.chat_stream(user_text, relevant_notes or [], memory_context):
                full += chunk
            return full, False

        import re as _re

        system_prompt = self.build_system_prompt(relevant_notes or [], memory_context)
        messages = [{"role": "system", "content": system_prompt}]
        messages += list(self._history)
        messages.append({"role": "user", "content": user_text})

        # Forçage d'outil pour données dynamiques (météo, batterie, CPU/RAM, actualités)
        forced_tool_name = self._force_tool_for_query(user_text)
        if forced_tool_name:
            tool_choice = {"type": "function", "function": {"name": forced_tool_name}}
        else:
            tool_choice = "auto"

        # Tentative 1 : avec tools (retry automatique sur rate limit Groq)
        try:
            _max_retries = 2
            for _attempt in range(_max_retries):
                try:
                    response = self._groq_client.chat.completions.create(
                        model=self.groq_model,
                        messages=messages,
                        tools=TOOLS,
                        tool_choice=tool_choice,
                        max_tokens=400,
                        temperature=0.6,
                        parallel_tool_calls=False,
                    )
                    break  # succès
                except Exception as _retry_err:
                    err_str = str(_retry_err).lower()
                    if "rate limit" in err_str or "429" in err_str or "too many" in err_str:
                        if _attempt < _max_retries - 1:
                            logger.warning(f"Groq rate limit — attente 2s (tentative {_attempt+1})")
                            time.sleep(2)
                        else:
                            raise
                    else:
                        raise

            choice = response.choices[0]

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                tool_call = choice.message.tool_calls[0]
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except Exception:
                    args = {}

                logger.info(f"Tool call : {name}({args})")
                return self._execute_and_respond(
                    name, args, messages, choice.message, tool_call,
                    persistent_memory, tts
                )

            else:
                content = choice.message.content or ""
                self._last_response = content
                return content, False

        except Exception as e:
            error_str = str(e)

            # Si un outil était forcé (météo, batterie, actualités) → appel direct sans LLM
            if forced_tool_name:
                logger.warning(f"Groq indisponible ({type(e).__name__}) — appel direct outil {forced_tool_name}")
                direct_args = self._get_default_args_for_tool(forced_tool_name, user_text)
                try:
                    result = execute_tool(forced_tool_name, direct_args, persistent_memory=persistent_memory, tts=tts)
                    self._last_response = result
                    return result, True
                except Exception as tool_err:
                    logger.error(f"Appel direct outil {forced_tool_name} échoué : {tool_err}")

            # Tenter de récupérer un tool call malformé depuis le message d'erreur
            name, args = self._parse_failed_tool_call(error_str)
            if name:
                logger.info(f"Tool call récupéré depuis erreur : {name}({args})")
                result = execute_tool(name, args, persistent_memory=persistent_memory, tts=tts)
                self._last_response = result
                try:
                    resp = self._groq_client.chat.completions.create(
                        model=self.groq_model,
                        messages=messages + [{"role": "assistant",
                                              "content": f"[Action effectuée : {result}]"}],
                        max_tokens=150,
                        temperature=0.7,
                    )
                    natural = resp.choices[0].message.content or result
                    self._last_response = natural
                    return natural, True
                except Exception:
                    return result, True

            # Dernier recours : appel texte sans tools
            logger.warning(f"chat_with_tools erreur ({type(e).__name__}) — retente sans tools")
            try:
                fallback = self._groq_client.chat.completions.create(
                    model=self.groq_model,
                    messages=messages,
                    max_tokens=400,
                    temperature=0.75,
                )
                content = fallback.choices[0].message.content or ""
                self._last_response = content
                return content, False
            except Exception as e2:
                logger.error(f"Fallback texte échoué : {e2}")
                full = ""
                for chunk in self.chat_stream(user_text, relevant_notes or [], memory_context):
                    full += chunk
                return full, False

    def _get_default_args_for_tool(self, tool_name: str, user_text: str) -> dict:
        """Arguments par défaut pour un appel direct à un outil (sans LLM)."""
        import re as _re
        t = user_text.lower()

        if tool_name == "ouvrir_application":
            return {"nom": "", "action": "lister"}

        if tool_name == "meteo":
            # Extraire la ville depuis le texte : "météo à Paris", "temps à Bruxelles"
            m = _re.search(r"(?:météo|temps|température|climat)\s+(?:à|de|en|sur)\s+([A-ZÀ-Üa-zà-ü\-]+)", user_text, _re.IGNORECASE)
            ville = m.group(1).strip().capitalize() if m else "Charleroi"
            # Détecter si Ali veut les prévisions de la semaine
            jours = 5 if any(w in t for w in ["semaine", "5 jours", "cinq jours", "prochains jours",
                                               "cette semaine", "la semaine"]) else 2
            return {"ville": ville, "jours": jours}

        if tool_name == "systeme":
            if any(w in t for w in ["batterie", "battery", "charge"]):
                return {"action": "batterie"}
            if any(w in t for w in ["wifi", "réseau", "connexion"]):
                return {"action": "wifi"}
            if any(w in t for w in ["luminosité", "luminosite", "brightness"]):
                m = _re.search(r"(\d+)\s*%?", user_text)
                niveau = int(m.group(1)) if m else 70
                return {"action": "luminosite", "niveau": niveau}
            if any(w in t for w in ["mode sombre", "dark mode"]):
                return {"action": "mode_sombre"}
            if any(w in t for w in ["mode clair", "light mode"]):
                return {"action": "mode_clair"}
            if any(w in t for w in ["presse-papier", "presse papier", "clipboard", "copié", "collé"]):
                return {"action": "presse_papier_lire"}
            if any(w in t for w in ["capture", "screenshot"]):
                return {"action": "screenshot"}
            if any(w in t for w in ["bureau", "desktop", "fenêtres", "cache"]):
                return {"action": "montre_bureau"}
            return {"action": "cpu_ram"}

        if tool_name == "volume":
            m = _re.search(r"(\d+)\s*%?", user_text)
            if m:
                return {"action": "definir", "niveau": int(m.group(1))}
            if any(w in t for w in ["monte", "augmente", "plus fort"]):
                return {"action": "monter"}
            if any(w in t for w in ["baisse", "diminue", "moins fort"]):
                return {"action": "baisser"}
            if any(w in t for w in ["coupe", "sourdine", "mute"]):
                return {"action": "couper"}
            return {"action": "monter"}

        if tool_name == "actualites":
            # Extraire le sujet pour orienter vers les sources télécom si pertinent
            return {"sujet": t}

        if tool_name == "calendrier":
            return {"action": "lire"}

        if tool_name == "recherche_info":
            # Nettoyer la requête des mots déclencheurs
            clean = _re.sub(r"^(cherche|recherche|trouve|dis-moi|c'est quoi|qu'est-ce que c'est|qui est|qu'est-ce qui|combien|quel est|quelle est)\s+", "", t.strip())
            return {"requete": clean or user_text}

        if tool_name == "devises":
            # Extraire la devise source et cible si possible
            m_montant = _re.search(r"(\d+(?:[.,]\d+)?)\s*€?", user_text)
            montant = float(m_montant.group(1).replace(",", ".")) if m_montant else 1.0
            # Chercher des devises nommées
            _DEVISE_MAP = {
                "dollar": "USD", "dollars": "USD", "usd": "USD",
                "dirham": "MAD", "dirhams": "MAD", "mad": "MAD",
                "livre": "GBP", "livres": "GBP", "gbp": "GBP",
                "franc": "CHF", "chf": "CHF", "suisse": "CHF",
                "yen": "JPY", "yens": "JPY", "jpyen": "JPY",
                "won": "KRW", "dinar": "DZD", "algérien": "DZD",
            }
            vers = list(dict.fromkeys(code for kw, code in _DEVISE_MAP.items() if kw in t))
            return {"de": "EUR", "vers": ",".join(vers) if vers else "USD,MAD,GBP", "montant": montant}

        if tool_name == "musique_spotify":
            if any(w in t for w in ["pause", "stop", "arrête la musique", "coupe"]):
                return {"action": "play_pause"}
            if any(w in t for w in ["suivant", "passe", "next", "piste suivante"]):
                return {"action": "suivant"}
            if any(w in t for w in ["précédent", "retour", "avant"]):
                return {"action": "precedent"}
            if any(w in t for w in ["qu'est-ce qui joue", "c'est quoi cette chanson", "quelle chanson", "qui chante"]):
                return {"action": "chanson_actuelle"}
            if any(w in t for w in ["radio", "mix de"]):
                m = _re.search(r"(?:radio|mix)\s+(?:de\s+)?([A-Za-zÀ-ÿ\s]+?)(?:\s|$)", user_text, _re.IGNORECASE)
                artiste = m.group(1).strip() if m else "hip-hop français"
                return {"action": "radio_artiste", "recherche": artiste}
            # "cherche X sur Spotify" → extraire la requête de recherche
            if "spotify" in t:
                _m_sp = _re.search(r"(?:cherche|trouve|joue|mets)\s+(.+?)\s+(?:sur\s+)?spotify", user_text, _re.IGNORECASE)
                if _m_sp:
                    return {"action": "chercher", "recherche": _m_sp.group(1).strip()}
            # Extraction artiste précis : "joue Jul", "mets Ninho", "balance PNL"
            # Cherche un nom propre après le verbe action (avant la détection de genre)
            _m_artist = _re.search(
                r"(?:joue|mets|balance|lance|écoute)\s+([A-Z][A-Za-zÀ-ÿ\-\.]+(?:\s+[A-Z][A-Za-zÀ-ÿ\-\.]+)?)\b",
                user_text
            )
            if _m_artist:
                _artiste = _m_artist.group(1).strip()
                # Exclure les mots non-artistes en tête
                _ART_STOP = {"Du", "De", "La", "Les", "Un", "Une", "Des", "Le",
                             "Rap", "Jazz", "Lofi", "Pop", "Raï", "Chaabi", "Rock"}
                if _artiste.split()[0] not in _ART_STOP and len(_artiste) > 2:
                    return {"action": "chercher", "recherche": _artiste}
            # Détection genre/style musical
            _GENRE_MAP = [
                ("rap français", "rap français top hits"),
                ("rap belge", "rap belge playlist"),
                ("rap", "rap français Jul Sch Ninho"),
                ("hip-hop", "hip-hop français beats"),
                ("hip hop", "hip-hop français beats"),
                ("lofi", "lofi hip hop study beats chill"),
                ("lo-fi", "lofi hip hop study beats chill"),
                ("jazz", "jazz café relax playlist"),
                ("r&b", "r&b soul français chill"),
                ("pop française", "pop française hits"),
                ("pop", "pop hits français"),
                ("électronique", "electronic chill playlist"),
                ("techno", "techno progressive set"),
                ("classique", "classical piano relaxing"),
                ("chaabi", "chaabi marocain populaire"),
                ("raï", "rai algérien cheb khaled mami"),
                ("rai", "rai algérien cheb khaled mami"),
                ("arabe", "musique arabe populaire hits"),
                ("arabic", "arabic pop hits 2024"),
                ("latina", "reggaeton latin hits 2024"),
                ("reggaeton", "reggaeton bad bunny"),
                ("workout", "workout motivation gym hits"),
                ("sport", "sport motivation hits"),
                ("chill", "chill vibes playlist"),
                ("ambiance", "chill ambient playlist"),
            ]
            for kw, search in _GENRE_MAP:
                if kw in t:
                    return {"action": "chercher", "recherche": search}
            # Musique contextualisée par heure (fallback)
            from datetime import datetime as _dt
            h = _dt.now().hour
            if 5 <= h < 9:
                return {"action": "chercher", "recherche": "morning motivation playlist"}
            elif 9 <= h < 18:
                return {"action": "chercher", "recherche": "lofi hip hop focus beats"}
            elif 18 <= h < 23:
                return {"action": "chercher", "recherche": "hip-hop français Jul Sch"}
            else:
                return {"action": "chercher", "recherche": "chill rap français nuit"}

        if tool_name == "fichiers":
            if any(w in t for w in ["écran", "vois", "vois-tu", "affiché"]):
                return {"action": "decrire_ecran"}
            return {"action": "screenshot"}

        if tool_name == "obsidian":
            # Extraire le sujet après les mots déclencheurs
            import re as _re3
            m = _re3.search(
                r"(?:qui est|c'est qui|sur|note|fiche|qu'est-ce que tu sais sur|"
                r"lis.?moi|résume)\s+(?:la note |la fiche |le client |mon client )?([^\?]+)",
                user_text, _re3.IGNORECASE
            )
            requete = m.group(1).strip() if m else user_text
            return {"action": "chercher", "requete": requete}

        if tool_name == "emails":
            return {"action": "lire_derniers"}

        if tool_name == "minuteur":
            import re as _re4
            m = _re4.search(r'(\d+)\s*(?:heure|h)\b', t)
            if m:
                return {"duree_secondes": int(m.group(1)) * 3600, "message": "Minuteur terminé."}
            m = _re4.search(r'(\d+)\s*(?:minute|min)\b', t)
            if m:
                return {"duree_secondes": int(m.group(1)) * 60, "message": "Minuteur terminé."}
            m = _re4.search(r'(\d+)\s*(?:seconde|sec)\b', t)
            if m:
                return {"duree_secondes": int(m.group(1)), "message": "Minuteur terminé."}
            return {"duree_secondes": 300, "message": "Minuteur terminé."}

        if tool_name == "alarme":
            import re as _re5
            m = _re5.search(r'(\d{1,2})h(\d{0,2})', t)
            heure = int(m.group(1)) if m else 7
            minute = int(m.group(2)) if m and m.group(2).strip() else 0
            return {"heure": heure, "minute": minute, "message": f"Alarme de {heure:02d}h{minute:02d}."}

        return {}

    def _parse_failed_tool_call(self, error_str: str):
        """Extrait nom + args d'un tool call malformé dans un message d'erreur Groq."""
        import re as _re
        patterns = [
            r"<function=(\w+)\{(.+?)\}</function>",
            r"<function=(\w+)>\s*(\{.+?\})\s*</function>",
            r"'failed_generation':\s*'<function=(\w+)(\{[^}]+\})",
        ]
        for pat in patterns:
            m = _re.search(pat, error_str, _re.DOTALL)
            if m:
                name = m.group(1)
                args_raw = m.group(2)
                if not args_raw.startswith("{"):
                    args_raw = "{" + args_raw
                try:
                    return name, json.loads(args_raw)
                except json.JSONDecodeError:
                    pass
        return None, None

    # Outils dont le résultat brut est déjà une réponse naturelle (pas de follow-up LLM)
    _DIRECT_TOOLS = frozenset({
        "ouvrir_application", "fermer_application", "ouvrir_site_web",
        "rechercher_sur_internet", "volume", "minuteur", "alarme", "memoriser",
        "notification",
    })
    # Outils dont le résultat contient des données brutes à reformuler naturellement
    _NATURALIZE_TOOLS = frozenset({
        "meteo", "actualites", "recherche_info", "devises", "emails",
        "calendrier", "fichiers", "obsidian", "musique_spotify", "systeme",
    })

    def _execute_and_respond(self, name, args, messages, choice_message, tool_call, persistent_memory, tts):
        """Exécute un outil et formule une réponse naturelle."""
        from jarvis_tools import execute_tool
        result = execute_tool(name, args, persistent_memory=persistent_memory, tts=tts)
        self._last_response = result

        # Outils d'action simple → réponse directe sans aller-retour LLM (latence réduite)
        if name in self._DIRECT_TOOLS:
            self._last_response = result
            return result, True

        # Passer le message SDK directement — le SDK sait le sérialiser correctement
        messages.append(choice_message)
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": str(result),
        })

        try:
            for _attempt in range(2):
                try:
                    followup = self._groq_client.chat.completions.create(
                        model=self.groq_model,
                        messages=messages,
                        max_tokens=300,
                        temperature=0.65,
                    )
                    break
                except Exception as _re:
                    if "rate limit" in str(_re).lower() and _attempt == 0:
                        time.sleep(2)
                    else:
                        raise
            natural = followup.choices[0].message.content or result
        except Exception as e:
            logger.warning(f"Follow-up après tool échoué : {e} — retour résultat brut")
            natural = result

        self._last_response = natural
        return natural, True

    def get_last_response(self) -> str:
        return self._last_response

    def get_history(self) -> list[dict]:
        return list(self._history)

    def get_history_length(self) -> int:
        return len(self._history)

    def extract_tags(self, conversation: str) -> list[str]:
        if not conversation.strip():
            return []
        result = self.chat_sync(
            f"Donne 3 tags thématiques séparés par virgules (minuscules):\n{conversation[:500]}",
            max_tokens=30,
        )
        tags = [t.strip().lower() for t in result.split(",") if t.strip()]
        return tags[:3]

