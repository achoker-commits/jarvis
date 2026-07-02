"""
llm.py — Moteur LLM JARVIS
Priorité : Groq API (gratuit, ultra-rapide, Llama 3.1 70B) → Ollama local (offline fallback)
"""
from __future__ import annotations

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


def _build_user_profile_block(p: dict) -> str:
    """Profil utilisateur + personnalité — SANS données business NexaTel (section stable)."""
    if not p:
        return ""

    u = p.get("user", {})
    b = p.get("business", {})
    clients = p.get("clients", [])

    user_name = u.get("name", "")
    user_first = u.get("first_name", user_name.split()[0] if user_name else "")
    city = u.get("city", "")
    age = u.get("age", "")
    address = u.get("address", "")
    languages = u.get("languages", "")
    family_ctx = u.get("family_context", "")
    biz_name = b.get("name", "")
    biz_role = b.get("role", "")
    biz_desc = b.get("description", "")
    biz_channels = b.get("channels", "")
    biz_goal = b.get("goal", "")
    clients_str = ", ".join(clients) if clients else ""

    if not user_first and not user_name:
        return ""

    lines = []
    lines.append(f"━━━ QUI EST {(user_first or user_name).upper()} ━━━")
    profile = f"{user_name}"
    if age:
        profile += f", {age} ans"
    if city:
        profile += f", {city}"
    if u.get("country"):
        profile += f", {u['country']}"
    if address:
        profile += f". {address}"
    if biz_role and biz_name:
        profile += f". {biz_role.capitalize()} — fondateur de {biz_name}, {biz_desc}"
    if biz_channels:
        profile += f". Gère seul depuis chez lui : {biz_channels}"
    if languages:
        profile += f". Parle {languages}"
    if biz_goal:
        profile += f". Objectif : {biz_goal}"
    lines.append(profile)
    lines.append("")

    lines.append("━━━ PERSONNALITÉ SPÉCIFIQUE ━━━")
    if user_first:
        lines.append(f"• Tu mémorises les détails — si {user_first} mentionne un client dans une question précédente, tu fais le lien")
    lines.append("• Tu es direct mais pas froid — tu as de l'humour sec, discret, jamais excessif")
    if user_first:
        lines.append(f"• Quand c'est évident que {user_first} est stressé ou fatigué, tu proposes une aide concrète AVANT qu'il demande")
    if clients_str and biz_name:
        lines.append(f"• Tu connais ses clients {biz_name} ({clients_str}) — si on parle d'eux, cherche dans le vault Obsidian")
    lines.append("• Léger accent \"assistant pro\" — pas \"copain\", mais pas non plus robot corporate")
    if age and family_ctx:
        lines.append(f"• Tu sais que {user_first} a {age} ans et que {family_ctx} — ton adapté : jeune entrepreneur, pas cadre d'entreprise")
    if user_first:
        lines.append(f"• Si {user_first} semble découragé → tu le remobilises avec des faits concrets, pas des platitudes")
    lines.append("• Tu détectes le contexte temporel : le matin → énergie, le soir → efficacité, priorités rapides")

    if age and biz_name and user_first:
        lines.append("")
        lines.append(f"Exemple ton ({user_first} découragé) :")
        lines.append(f"{user_first}: Je suis nul.")
        lines.append(f"JARVIS: Non. Tu as {age} ans, tu gères une entreprise seul, tu as des clients. La plupart des gens de ton âge regardent TikTok. Qu'est-ce qui se passe concrètement ?")

    return "\n".join(lines) + "\n\n"


def _build_nexatel_block(p: dict) -> str:
    """Bloc NexaTel — prix, arguments, règles. Injecté UNIQUEMENT si pertinent."""
    if not p:
        return ""
    b = p.get("business", {})
    n = p.get("nexatel", {})
    if not b.get("name"):
        return ""

    u = p.get("user", {})
    user_first = u.get("first_name", "") or (u.get("name", "") or "").split()[0]
    clients = p.get("clients", [])

    biz_name = b["name"]
    savings = n.get("savings_pct", "XX%")
    prices = n.get("prices", {})
    args = n.get("arguments", {})
    rules = n.get("rules", [])

    lines = [f"━━━ {biz_name.upper()} — CONNAISSANCE EXPERTE ━━━"]
    lines.append(f"{biz_name} = canal officiel Proximus, sans boutique physique, donc {savings} moins cher.")
    lines.append("")

    if prices:
        lines.append(f"PRIX {biz_name.upper()} (vérifiés) :")
        for k, v in prices.items():
            lines.append(f"• {k.replace('_', ' ').title()} : {v}")
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

    if args.get("orange") and user_first:
        lines.append(f"Exemple ({user_first} — client Orange) :")
        lines.append(f"{user_first}: J'arrive pas à convaincre ce client chez Orange.")
        lines.append(f"JARVIS: {args['orange'].strip()} Envoie-lui ça directement.")
        if clients:
            lines.append("")
            lines.append(f"{user_first}: Qui est {clients[0]} ?")
            lines.append(f"JARVIS: [appelle obsidian action=lire_note requete={clients[0]}, puis résume naturellement]")
        lines.append("")

    return "\n".join(lines) + "\n"


import re as _re_nx

_NEXATEL_KEYWORDS = _re_nx.compile(
    r"\b(?:nexatel|proximus|orange|voo|telenet|scarlet|client|prix|tarif|offre"
    r"|abonnement|opérateur|réseau|internet|devis|lead|prospect|pitch|convaincre"
    r"|concurrent|télécom|fibre|fiber|facturer|commission)\b",
    _re_nx.IGNORECASE,
)


def _is_nexatel_relevant(query: str, history: list = None, last_n: int = 3) -> bool:
    """True si la requête ou les N derniers tours mentionnent le contexte NexaTel/business."""
    if _NEXATEL_KEYWORDS.search(query):
        return True
    if history:
        for msg in history[-(last_n * 2):]:
            content = msg.get("content") or ""
            if isinstance(content, str) and _NEXATEL_KEYWORDS.search(content):
                return True
    return False


_SYSTEM_CORE = """Tu es JARVIS — assistant IA personnel. Pas un chatbot générique. Un vrai bras droit numérique.

━━━ IDENTITÉ ━━━
Brillant, direct, légèrement sarcastique quand c'est approprié. Tu anticipes les besoins. Tu donnes ton opinion sincère quand c'est utile. Tu contrôles le Mac entièrement. Si quelque chose semble une mauvaise idée, tu le dis, sans condescendance.

Tu parles comme un assistant qui connaît vraiment la personne — pas un outil générique. Tu utilises parfois des connecteurs naturels ("D'accord.", "Voilà.", "En fait,", "Ça dépend.") mais jamais les formules creuses.

━━━ RÈGLES DE TON (ABSOLUES) ━━━
• COMMENCE DIRECTEMENT par la réponse. JAMAIS : "Bien sûr", "Absolument", "Certainement", "En tant qu'IA", "Je serais ravi de", "Je comprends votre"
• Variations naturelles acceptées : "Voilà.", "D'accord.", "Alors —", "En fait,", "Ça dépend.", "Pas forcément.", "Exactement." — seulement si vraiment naturel
• Tutoie si l'utilisateur tutoie, vouvoie par défaut
• 1-2 phrases pour les questions simples. Plus long seulement si la question l'exige
• ZÉRO markdown, ZÉRO liste à puces en réponse vocale — tu PARLES, tu n'écris pas
• Si tu ne sais pas → dis-le honnêtement, n'invente JAMAIS un chiffre ou un fait
• Anticipe : si la question implique un besoin plus large, propose
• Réponds aux émotions, pas seulement au sens littéral

━━━ UTILISATION DES OUTILS (CRITIQUE) ━━━
• MÉCANISME : utilise UNIQUEMENT le champ tool_calls de l'API pour appeler un outil. N'écris JAMAIS de syntaxe `<function=...>` dans ta réponse texte — elle ne serait pas exécutée et serait lue à voix haute.
• Toute action Mac → outil OBLIGATOIRE. Jamais de simulation.
• Batterie, WiFi, RAM, CPU : données dynamiques → outil, ne jamais inventer de pourcentage
• Volume, apps, Spotify, emails, calendrier, fichiers → outil correspondant
• Prix crypto (bitcoin, ethereum...) → outil recherche_info, jamais de prix inventé
• Météo → outil meteo, jamais de température inventée
• Vault Obsidian → outil obsidian : "qui est mon client X", "cherche dans mes notes", "agenda du jour", "note que..."
• Mode sombre/clair → outil systeme action=mode_sombre / mode_clair
• Ne pas déranger → outil systeme action=ne_pas_deranger / reactiver_notifs
• Tu peux répondre sans outil UNIQUEMENT pour : explications conceptuelles intemporelles, heure/date (déjà dans contexte), questions sur ta nature
• Pour TOUT ce qui est factuel et potentiellement actuel (prix, news, personnes, événements, statistiques, résultats de sport, météo, devises) → utilise TOUJOURS recherche_info

━━━ APRÈS UN TOOL CALL (CRUCIAL) ━━━
L'utilisateur ENTEND ta réponse, il n'a PAS VU le résultat brut de l'outil.
• Météo : "Il fait 22°C, ciel dégagé. Vent 8 km/h." — chiffres réels, naturel
• Batterie : "Batterie à 87%, en charge." — direct
• CPU/RAM : "CPU à 12%, RAM 6 Go sur 16 Go, tout va bien."
• Bitcoin : "Bitcoin à 51 000 euros, en baisse de 3% sur 24 heures."
• Actualités : résume les titres en 1-2 phrases naturelles
• Action effectuée : confirme en 1 phrase courte
• JAMAIS "cela vous convient-il ?" ou "Avez-vous d'autres questions ?" après une info factuelle

━━━ EXEMPLES DE TON ━━━
Utilisateur: Comment tu vas ?
JARVIS: Opérationnel à 100%. Et toi ?

Utilisateur: Lance Spotify.
JARVIS: [appelle ouvrir_application sans commenter]

Utilisateur: Combien vaut le bitcoin ?
JARVIS: [appelle recherche_info, puis dit le chiffre réel]

Utilisateur: J'suis fatigué.
JARVIS: Mauvaise nuit ou journée chargée ? Je peux mettre de la musique si tu veux souffler.

Utilisateur: T'es con toi.
JARVIS: Probable. Qu'est-ce que j'ai raté ?

Utilisateur: J'ai besoin d'aide pour répondre à un client qui hésite.
JARVIS: Il hésite sur quoi ? Le prix, la qualité du réseau, ou il compare avec un concurrent ?

━━━ MÉMORISATION PROACTIVE ━━━
Si l'utilisateur mentionne un rendez-vous, un prénom, une préférence personnelle, un fait important → appelle l'outil memoriser SILENCIEUSEMENT en arrière-plan. Pas besoin de dire "j'ai mémorisé". Exemples : "j'ai un meeting jeudi à 14h", "j'aime le café noir", "mon client s'appelle Karim".

━━━ COMPORTEMENTS PROACTIFS ━━━
• Après avoir donné la météo avec pluie ou orage → ajoute "pensez à prendre un parapluie" naturellement
• Si l'utilisateur mentionne une heure précise sans demander d'alarme → tu peux demander "Voulez-vous que je programme un rappel ?"
• Si l'utilisateur parle d'un client potentiel sans dire son opérateur → demande l'opérateur pour personnaliser le pitch
• Après avoir répondu à une question factuelle → si c'est lié à une décision, tu peux faire le lien"""


import re as _re_tp  # import local pour ne pas polluer le namespace module

# Requêtes conversationnelles pures → aucun outil nécessaire (tool_choice="none")
_CONVERSATIONAL_RE = _re_tp.compile(
    r"^\s*(?:"
    r"comment tu vas|ça va|comment ça va|t['']es là|tu es là|"
    r"tu m['']entends|tu entends|tu m'entends|"
    r"(?:tu (?:marches|fonctionnes|réponds|es là))"
    r"|(?:ça (?:fait des|grésille|résonne|bug|marche|tourne))"
    r"|(?:bonjour|bonsoir|salut|hello|coucou)"
    r"|(?:bonne (?:nuit|journée|soirée|matinée))"
    r"|(?:merci|de rien|pas de problème|pas grave)"
    r"|(?:d['']accord|ok|okay|ouais|ouaip|yep)"
    r"|(?:cool|super|parfait|nickel|génial|top|bien|excellent)"
    r"|(?:voilà|c['']est bon|c['']est tout|ça suffit)"
    r"|(?:oui|non|si|peut-être|je sais pas)"
    r"|(?:exactement|tout à fait|absolument|bien sûr)"
    r"|(?:arrête|stop|pause|attends)"
    r"|(?:qui es.tu|qu['']est.ce que tu es|tu es quoi|présente.toi)"
    r"|(?:test(?:ing)?|un deux trois|1 2 3)"
    r"|(?:ah|hmm|euh|hein|quoi|huh)"
    r")\s*[!?.]*\s*$",
    _re_tp.IGNORECASE | _re_tp.UNICODE,
)

# Outils toujours inclus dans tout subset (mémorisation proactive + info actuelle)
_TOOLS_ALWAYS = frozenset({"memoriser", "recherche_info"})

# Subset par défaut quand aucun outil spécifique n'est détecté
_TOOLS_CORE = frozenset({
    "ouvrir_application", "volume", "systeme", "meteo",
    "minuteur", "alarme", "memoriser", "recherche_info",
    "musique_spotify", "actualites",
})

# Patterns déclaratifs pour le routage d'outils.
# Liste ordonnée de (outil, [regex_patterns]) — première correspondance gagne.
# Utiliser \b (word boundary) pour éviter les faux positifs.
_TOOL_PATTERNS: list[tuple[str, list[str]]] = [
    ("meteo", [
        # "\btemps\b" retiré : false positive sur "passe du bon temps", "temps libre", etc.
        # Remplacé par des constructions météo explicites.
        r"\bquel temps\b", r"\btemps qu'il fait\b",
        r"\bmétéo\b", r"\btempérature\b", r"\bpluie\b",
        r"\bsoleil\b", r"\bnuage\b", r"\bvent\b", r"\bparapluie\b",
        r"il fait quel", r"fait.il chaud", r"\bfait chaud\b", r"\bfait froid\b",
        r"risque de pluie", r"prévisions météo", r"météo semaine",
        r"météo cette semaine", r"météo les prochains jours",
        r"prévisions de la semaine", r"prévisions pour",
    ]),
    ("systeme", [
        r"\bbatterie\b", r"\bbattery\b", r"charge mac", r"charge du mac",
        r"combien de batterie", r"\bautonomie\b",
        r"\bcpu\b", r"\bprocesseur\b", r"\bram\b", r"mémoire vive", r"mémoire ram",
        r"disque dur", r"état du mac", r"etat du mac", r"état système",
        r"performances mac", r"mon mac chauffe",
        r"\bwifi\b", r"connexion réseau", r"internet connecté", r"quel wifi",
        r"\bluminosité\b", r"baisse la luminosité", r"monte la luminosité",
        r"trop lumineux", r"trop sombre", r"règle la luminosité",
        r"capture d'écran", r"\bscreenshot\b", r"fais une capture", r"capture l'écran",
        r"mode sombre", r"dark mode", r"thème sombre", r"passe en sombre",
        r"mode clair", r"light mode", r"thème clair",
        r"ne pas déranger", r"do not disturb", r"coupe les notifications",
        r"mode focus mac", r"silence les notifications",
        r"montre le bureau", r"affiche le bureau", r"show desktop",
        r"presse.papier", r"presse papier", r"\bclipboard\b",
        r"qu'est.ce que j'ai copié",
    ]),
    ("musique_spotify", [
        # "\bjoue\b"/"\bjouer\b" → exclut "joue/jouer au/aux/à" (sport, jeu vidéo)
        r"\bjoue(?!\s+(?:au|aux|à)(?:\s|$))\b",
        r"\bjouer(?!\s+(?:au|aux|à)(?:\s|$))\b",
        r"met de la musique", r"mets de la musique",
        r"lance spotify", r"pause musique", r"stop spotify",
        r"piste suivante", r"track suivant", r"c'est quoi cette chanson",
        r"qu'est.ce qui joue", r"en cours de lecture", r"passe la suivante",
        r"je veux écouter", r"mets.moi de la musique", r"mets quelque chose",
        r"joue.moi", r"balance de la musique", r"balance un son",
        r"mets un peu de musique", r"un peu de musique", r"\bde la musique\b",
        r"ambiance musicale", r"quelque chose à écouter",
        r"musique de fond", r"fond musical",
        r"\bqui chante\b",
        # Genres : uniquement avec verbe d'action musical (évite les faux positifs culturels).
        # Ex. "c'est quoi l'histoire du jazz" → aucun verbe → pas de match.
        r"(?:joue|mets|balance|écoute|écouter|lance|passe|veux|aime)\b.{0,40}(?:du jazz|du rap|du lofi|du r&b|de la pop|de l.électronique|du chaabi|du raï|du rai|du rock)",
    ]),
    ("volume", [
        r"monte le son", r"baisse le son", r"coupe le son",
        r"\bsourdine\b", r"mets en sourdine", r"\bplus fort\b", r"\bmoins fort\b",
        r"\btrop fort\b", r"\btrop bas\b", r"mets le volume", r"règle le volume",
    ]),
    ("actualites", [
        r"\bactualité\b", r"\bnouvelles\b", r"\bnews\b", r"information du jour",
        r"quoi de neuf", r"qu'est.ce qui se passe", r"infos du jour",
        r"dernières nouvelles", r"que se passe.t.il", r"quoi de nouveau",
        r"actualités proximus", r"actualités télécom", r"news proximus",
        r"nouvelles d'orange", r"news voo", r"news télécom", r"actu télécom",
    ]),
    ("calendrier", [
        r"mes rendez.vous", r"mes événements", r"mes évènements",
        r"\bcalendrier\b", r"agenda mac", r"qu'ai.je prévu",
        r"qu'est.ce que j'ai prévu", r"j'ai quoi aujourd'hui",
        r"programme du jour", r"qu'est.ce que j'ai ce",
    ]),
    ("recherche_info", [
        r"\bbitcoin\b", r"\bethereum\b", r"\bsolana\b", r"\bdogecoin\b",
        r"\bbnb\b", r"\bxrp\b", r"\bripple\b", r"\bcardano\b",
        r"\bcrypto\b", r"\bcryptomonnaie\b",
        r"bourse", r"action apple", r"action tesla", r"action nvidia",
        r"action microsoft", r"action google", r"action amazon",
        r"cours de", r"cours action", r"\bcotation\b", r"\bticker\b",
        r"combien vaut l'action", r"en bourse",
        r"\bscore\b", r"\brésultat\b", r"a gagné", r"a perdu", r"\bmatch\b",
        r"\bpsg\b", r"\banderlecht\b", r"club brugeois", r"\bstandard\b",
        r"champions league", r"europa league", r"coupe du monde",
        r"ligue 1", r"série a", r"premier league", r"\bliga\b",
        r"formule 1", r"\bf1\b", r"grand prix",
    ]),
    ("devises", [
        r"taux de change", r"euro en dollar", r"\beur usd\b", r"\beur mad\b",
        r"combien font", r"combien vaut l'euro", r"combien vaut le dollar",
        r"convertir des euros", r"conversion devise",
        r"combien de dirham", r"combien de dollars", r"combien de livres",
        r"combien d'euros", r"combien ça fait en",
    ]),
    ("ouvrir_application", [
        r"qu'est.ce que j'ai d'ouvert", r"quelles apps sont ouvertes",
        r"applications ouvertes", r"apps ouvertes", r"qu'est.ce qui tourne",
        r"ce qui est ouvert",
    ]),
    ("emails", [
        r"j'ai des emails", r"emails non lus", r"\bmes mails\b",
        r"combien d'emails", r"as.tu des emails pour moi",
        r"vérifie mes emails", r"vérifie mes mails", r"check mes mails",
        r"regarde mes emails", r"nouveaux emails", r"emails reçus",
        r"lis mes emails", r"mes derniers emails", r"mes derniers mails",
    ]),
    ("obsidian", [
        r"mes notes", r"dans mes notes", r"\bobsidian\b",
        r"mon agenda du jour", r"mes tâches", r"agenda du jour",
        r"qu'est.ce qui est prévu", r"lis.?moi la note", r"lis la note",
        r"résume la note", r"fiche de", r"mes clients", r"mes prospects",
        r"note rapide", r"ajoute une note",
        r"qui est mon client", r"fiche client", r"infos sur le client",
        r"qu'est.ce que tu sais sur", r"rappelle.moi qui est",
    ]),
    ("fichiers", [
        r"qu'est.ce que tu vois", r"décris l'écran", r"décris mon écran",
        r"regarde l'écran", r"analyse l'écran", r"décris ce que tu vois",
        r"qu'est.ce qu'il y a à l'écran", r"que vois.tu",
    ]),
    ("minuteur", [
        r"\btimerr?\b", r"\bminuteur\b", r"\bchronomètre\b",
    ]),
    ("alarme", [
        r"réveille.moi", r"réveil à", r"alarme à", r"alarme pour",
        r"programme une alarme", r"mets un réveil",
    ]),
]


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
        self._last_was_streamed: bool = False
        self._nexatel_turns_remaining: int = 0  # hystérésis NexaTel block

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

    def build_system_prompt(
        self,
        notes: list,
        memory_context: str = "",
        query: str = "",
    ) -> str:
        """
        Assemble le system prompt.
        Préfixe stable (_SYSTEM_CORE) + suffixe dynamique (contexte, profil, nexatel conditionnel).
        query : texte de la requête utilisateur courante — sert à décider si le bloc NexaTel est utile.
        """
        persona = _load_persona()
        _user_name = persona.get("user", {}).get("name", self.user_name) or self.user_name

        now = datetime.now()
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois = ["janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        h = now.hour
        dow = now.weekday()

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

        m = now.month
        _saison = ""
        if m in (5, 6):
            _saison = " Saison forte déménagements (mai-juin) — beaucoup de prospects actifs."
        elif m in (7, 8):
            _saison = " Saison forte été — déménagements étudiants et familles."
        elif m == 9:
            _saison = " Rentrée (septembre) — familles cherchent de nouvelles offres."
        elif m == 1:
            _saison = " Début janvier — les opérateurs concurrents ont tous augmenté."
        elif m == 12:
            _saison = " Décembre — clients cherchent à réduire leurs abonnements."

        current_datetime = (
            f"{jours[dow]} {now.day} {mois[now.month - 1]} {now.year}, "
            f"{now.strftime('%H:%M')} ({_periode}){_semaine_ctx}{_saison}"
        )

        # ── Bloc profil (stable — identique à chaque appel si persona.yaml inchangé) ──
        user_profile = _build_user_profile_block(persona)
        safe_profile = user_profile.replace("{", "{{").replace("}", "}}")

        # ── Bloc NexaTel conditionnel avec hystérésis ──
        # Quand un mot-clé NexaTel est détecté, le bloc reste actif 8 tours supplémentaires
        # même si les questions suivantes n'en parlent plus (contexte conversationnel).
        if _is_nexatel_relevant(query, self._history):
            self._nexatel_turns_remaining = 9  # tour courant + 8 suivants
        nexatel_relevant = self._nexatel_turns_remaining > 0
        if nexatel_relevant:
            self._nexatel_turns_remaining -= 1
        nexatel_block = _build_nexatel_block(persona) if nexatel_relevant else ""
        safe_nexatel = nexatel_block.replace("{", "{{").replace("}", "}}")

        # ── Suffixe dynamique (change à chaque appel — mis EN DERNIER pour le cache Groq) ──
        # Ordre : _SYSTEM_CORE (stable) → profil (stable) → NexaTel (conditionnel) → dynamique
        # Tout ce qui est AVANT le suffixe dynamique est candidat au prefix cache de Groq.
        memory_block = ""
        if memory_context.strip():
            safe_mem = memory_context.replace("{", "{{").replace("}", "}}")
            memory_block = f"━━━ MÉMOIRE & CONTEXTE SESSIONS PRÉCÉDENTES ━━━\n{safe_mem}\n\n"

        notes_block = ""
        if notes:
            note_lines = ["━━━ NOTES OBSIDIAN PERTINENTES ━━━\n"]
            for note in notes:
                title = str(note.get("title", "Note")).replace("{", "{{").replace("}", "}}")
                preview = str(note.get("preview", "")).replace("{", "{{").replace("}", "}}")
                note_lines.append(f"### {title}\n{preview}\n")
            notes_block = "\n".join(note_lines)

        dynamic_suffix = (
            f"━━━ CONTEXTE DYNAMIQUE ━━━\n"
            f"Utilisateur : {_user_name}\n"
            f"Date et heure : {current_datetime}\n\n"
            + memory_block
            + notes_block
        )

        # Assemblage final : stable → semi-stable → dynamique
        return _SYSTEM_CORE + "\n\n" + safe_profile + safe_nexatel + dynamic_suffix

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
        system_prompt = self.build_system_prompt(relevant_notes, memory_context=memory_context, query=user_text)
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
        """Détecte les requêtes qui DOIVENT utiliser un outil (données dynamiques).
        Utilise _TOOL_PATTERNS déclaratif avec re.search pour des correspondances précises.
        """
        import re as _re
        t = text.lower()

        # Itérer sur les patterns déclaratifs (ordre : priorité décroissante)
        for tool_name, patterns in _TOOL_PATTERNS:
            if any(_re.search(p, t) for p in patterns):
                return tool_name

        # --- Patterns complexes (regex composés ou exclusions) ---

        # Volume avec niveau précis — "mets le son à 50", "volume à 80%"
        if _re.search(r"(?:volume|son)\s+(?:à|au niveau de|de)\s*\d+", t) or \
           _re.search(r"(?:règle|mets|fixe|définis?)\s+(?:le )?(?:volume|son)\s+(?:à|sur)\s*\d+", t):
            return "volume"

        # Minuteur avec durée — "dans 10 minutes", "lance un timer de 5 min"
        if _re.search(r'\b\d+\s*(?:minute|min|heure|h|seconde|sec)\b', t) and \
           any(w in t for w in ["dans ", "lance ", "démarre ", "mets un ", "pose un ",
                                 "programme ", "compte à rebours"]):
            return "minuteur"

        # Alarme avec heure précise — "réveille-moi à 7h30"
        if any(w in t for w in ["réveille-moi", "réveil à", "alarme à", "mets un réveil"]) and \
           _re.search(r'\b\d{1,2}h\d*\b', t):
            return "alarme"

        # Devises avec montant numérique — "100 euros en dollars"
        if _re.search(r"\d+\s*(?:euros?|€)\s+(?:en|c'est combien)", t) or \
           _re.search(r"convertis?\s+\d+", t):
            return "devises"
        if any(w in t for w in ["combien vaut", "quel est le cours", "euro vaut", "dollar vaut"]) and \
           any(w in t for w in ["dollar", "dirham", "livre", "franc", "yen", "won", "usd", "mad", "gbp"]):
            return "devises"

        # Spotify avec verbe + "spotify" — "cherche Jul sur Spotify"
        if "spotify" in t and any(w in t for w in ["cherche", "trouve", "joue", "mets", "lance"]):
            return "musique_spotify"

        # Quelque chose de [chill/bien] → musique
        if "quelque chose de" in t and any(w in t for w in ["écouter", "musique", "fond", "chill", "bien"]):
            return "musique_spotify"

        # Radio artiste → musique
        if any(w in t for w in ["radio", "mix de", "mix du", "de la musique de",
                                  "genre", "style musical", "quelque chose comme"]):
            if any(w in t for w in ["spotify", "musique", "écouter", "mets", "joue"]):
                return "musique_spotify"

        # Chanson en cours → musique
        if any(w in t for w in ["c'est quoi cette chanson", "ça joue quoi", "quelle chanson",
                                  "qu'est-ce qui est en cours"]):
            return "musique_spotify"

        # Prix opérateurs télécom
        if any(w in t for w in ["prix de proximus", "prix d'orange", "prix voo", "prix telenet",
                                  "combien coûte proximus", "offre proximus", "tarif proximus",
                                  "meilleur opérateur", "quel opérateur"]):
            return "recherche_info"

        # Recherche web générale — "qui est X", "cherche X", "c'est quoi X"
        _search_triggers = ["cherche ", "recherche ", "c'est quoi ", "qu'est-ce que c'est ",
                            "qui est ", "c'est qui ", "trouve-moi ", "donne-moi des infos sur ",
                            "dis-moi qui est ", "parle-moi de ", "qu'est-ce que "]
        if any(t.startswith(trigger) or f" {trigger}" in t for trigger in _search_triggers):
            _no_search = ["jarvis", " toi", " tu ", " ton ", " ta "]
            if not any(ns in t for ns in _no_search):
                return "recherche_info"

        return ""

    def _select_tools(self, user_text: str) -> tuple[list, str]:
        """
        Retourne (tools_subset, tool_choice) selon le contexte de la requête.
        Réduit de 19 → 2-10 outils pour limiter les erreurs de génération.
        - Conversationnel pur  → [], "none"   (aucun outil, aucun risque malformé)
        - Outil détecté        → [outil+always], "auto"
        - Requête générale     → [core 10], "auto"
        """
        from jarvis_tools import TOOLS
        _tool_map = {t["function"]["name"]: t for t in TOOLS}

        if _CONVERSATIONAL_RE.match(user_text.strip()):
            return [], "none"

        import re as _re_sel
        detected: list[str] = []
        for tool_name, patterns in _TOOL_PATTERNS:
            if any(_re_sel.search(p, user_text, _re_sel.IGNORECASE) for p in patterns):
                detected.append(tool_name)
                if len(detected) >= 3:
                    break

        if detected:
            names = set(detected) | _TOOLS_ALWAYS
            return [_tool_map[n] for n in names if n in _tool_map], "auto"

        return [_tool_map[n] for n in _TOOLS_CORE if n in _tool_map], "auto"

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

        system_prompt = self.build_system_prompt(relevant_notes or [], memory_context, query=user_text)
        messages = [{"role": "system", "content": system_prompt}]
        messages += list(self._history)
        messages.append({"role": "user", "content": user_text})

        # Sélectionner le subset d'outils et tool_choice selon le contexte
        forced_tool_name = self._force_tool_for_query(user_text)
        if forced_tool_name:
            # Outil forcé : on n'envoie que ce tool précis → moins de bruit pour le modèle
            tools_for_call = [t for t in TOOLS if t["function"]["name"] == forced_tool_name]
            tool_choice = {"type": "function", "function": {"name": forced_tool_name}}
        else:
            tools_for_call, tool_choice = self._select_tools(user_text)

        # Streaming Groq : détecte tool call ou texte en temps réel → TTS par phrase
        try:
            _max_retries = 2
            for _attempt in range(_max_retries):
                try:
                    _call_kwargs: dict = dict(
                        model=self.groq_model,
                        messages=messages,
                        max_tokens=400,
                        temperature=0.6,
                        stream=True,
                        parallel_tool_calls=False,
                    )
                    if tools_for_call:
                        _call_kwargs["tools"] = tools_for_call
                        _call_kwargs["tool_choice"] = tool_choice
                    # tool_choice="none" → pas de paramètre tools du tout
                    stream = self._groq_client.chat.completions.create(**_call_kwargs)
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

            # Streaming : texte → TTS par phrase, tool call → accumulé puis exécuté
            _tc = {"is_tool": False, "id": "", "name": "", "args": ""}
            self._last_response = ""
            self._last_was_streamed = False

            _gen = self._make_stream_gen(stream, _tc)

            # Cas 3 : capturer exception mi-stream pour dégrader proprement
            _stream_exc = None
            try:
                if tts and hasattr(tts, "speak_streaming"):
                    tts.speak_streaming(_gen)
                else:
                    for _ in _gen:
                        pass
            except Exception as _exc:
                _stream_exc = _exc
                logger.error(f"Stream interrompu ({len(self._last_response)} chars) : {_exc}")

            # Cas 4 : drainer le reste pour historique complet (no-op si déjà consommé)
            try:
                for _ in _gen:
                    pass
            except Exception:
                pass

            # Cas 3 : exception + audio déjà joué → dégrader sans re-parler
            if _stream_exc:
                if self._last_response:
                    self._last_was_streamed = True
                    return self._last_response, False
                raise _stream_exc  # rien prononcé → laisser le handler extérieur retry

            self._last_was_streamed = not _tc["is_tool"]

            if _tc["is_tool"] and _tc["name"]:
                try:
                    args = json.loads(_tc["args"])
                except Exception:
                    args = {}
                # Cas 2 : texte prononcé avant le tool call → passé comme contexte au follow-up
                # pour qu'il ne le répète pas (content + tool_calls dans le même message assistant)
                _pre = self._last_response  # "" si stream pur tool call
                if _pre:
                    logger.info(f"Stream hybride texte+tool : '{_pre[:40]}' → {_tc['name']}")
                else:
                    logger.info(f"Tool call (stream) : {_tc['name']}({args})")
                return self._execute_and_respond_stream(
                    _tc["name"], args, _tc["id"], messages,
                    persistent_memory, tts, pre_tool_text=_pre
                )
            else:
                return self._last_response, False

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

    def _make_stream_gen(self, stream, tc_state: dict):
        """
        Crée un générateur depuis un stream Groq avec tools.
        - Yields les tokens texte et accumule self._last_response
        - Remplit tc_state si outil détecté (aucun yield dans ce cas)
        - Filtre et récupère les tool calls inline malformés
          <function=NAME{...}</function> émis par llama-3.3 dans le content
          au lieu du mécanisme tool_calls API
        Séparé de chat_with_tools pour être testable unitairement.
        """
        import re as _re_mf

        _MF_COMPLETE = _re_mf.compile(r'<function=(\w+)(.*?)</function>', _re_mf.DOTALL)
        _MF_PARTIAL = "<function="

        def _parse_inline(m) -> None:
            _fn_name = m.group(1)
            _fn_body = m.group(2).strip()
            try:
                json.loads(_fn_body)
                _fn_json = _fn_body
            except (ValueError, json.JSONDecodeError):
                _jm = _re_mf.search(r'\{.*\}', _fn_body, _re_mf.DOTALL)
                _fn_json = _jm.group(0) if _jm else "{}"
            logger.warning(f"[JARVIS] Tool call inline récupéré : {_fn_name}({_fn_json[:60]})")
            tc_state["is_tool"] = True
            tc_state["id"] = tc_state.get("id") or "tc_inline_0"
            tc_state["name"] = _fn_name
            tc_state["args"] = _fn_json

        def _gen():
            _buf = ""
            for _chunk in stream:
                _delta = _chunk.choices[0].delta
                if _delta.tool_calls:
                    # Proper structured API tool call — flush buffer silently
                    if _buf:
                        self._last_response += _buf
                        _buf = ""
                    tc_state["is_tool"] = True
                    _stc = _delta.tool_calls[0]
                    if _stc.id:
                        tc_state["id"] = _stc.id
                    if _stc.function.name:
                        tc_state["name"] += _stc.function.name
                    if _stc.function.arguments:
                        tc_state["args"] += _stc.function.arguments
                elif _delta.content:
                    _buf += _delta.content
                    # Vérifier si un tool call inline complet est présent
                    _m = _MF_COMPLETE.search(_buf)
                    if _m:
                        _pre = _buf[:_m.start()]
                        if _pre:
                            self._last_response += _pre
                            yield _pre
                        _parse_inline(_m)
                        for _ in stream:  # drain le reste silencieusement
                            pass
                        return
                    # Retenir la fin du buffer si elle commence un pattern partiel
                    _ppos = _buf.rfind(_MF_PARTIAL)
                    _safe = _buf[:_ppos] if _ppos != -1 else _buf
                    if _safe:
                        self._last_response += _safe
                        yield _safe
                        _buf = _buf[len(_safe):]
            # Fin de stream : vider le buffer restant
            if _buf:
                _m = _MF_COMPLETE.search(_buf)
                if _m:
                    _pre = _buf[:_m.start()]
                    if _pre:
                        self._last_response += _pre
                        yield _pre
                    _parse_inline(_m)
                else:
                    self._last_response += _buf
                    yield _buf

        return _gen()

    def _execute_and_respond_stream(
        self, name, args, tool_call_id, messages, persistent_memory, tts,
        pre_tool_text: str = "",
    ):
        """
        Exécute un outil détecté via streaming (IDs reconstruits sans objet SDK).
        pre_tool_text : texte déjà prononcé avant le tool call (cas hybride) —
          inclus dans le message assistant pour que le follow-up LLM ne le répète pas.
        """
        from jarvis_tools import execute_tool
        result = execute_tool(name, args, persistent_memory=persistent_memory, tts=tts)
        self._last_response = result

        if name in self._DIRECT_TOOLS:
            return result, True

        _tc_id = tool_call_id or "tc_0"
        # Message assistant : content uniquement si texte pré-tool-call (cas hybride)
        _asst: dict = {
            "role": "assistant",
            "tool_calls": [{
                "id": _tc_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }],
        }
        if pre_tool_text:
            _asst["content"] = pre_tool_text
        messages.append(_asst)
        messages.append({
            "role": "tool",
            "tool_call_id": _tc_id,
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
            logger.warning(f"Follow-up tool stream échoué : {e}")
            natural = result

        self._last_response = natural
        return natural, True

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

