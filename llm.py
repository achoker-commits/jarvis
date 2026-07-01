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


import re as _re_tp  # import local pour ne pas polluer le namespace module

# Patterns déclaratifs pour le routage d'outils.
# Liste ordonnée de (outil, [regex_patterns]) — première correspondance gagne.
# Utiliser \b (word boundary) pour éviter les faux positifs.
_TOOL_PATTERNS: list[tuple[str, list[str]]] = [
    ("meteo", [
        r"\btemps\b", r"\bmétéo\b", r"\btempérature\b", r"\bpluie\b",
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
        r"\bjoue\b", r"\bjouer\b", r"met de la musique", r"mets de la musique",
        r"lance spotify", r"pause musique", r"stop spotify",
        r"piste suivante", r"track suivant", r"c'est quoi cette chanson",
        r"qu'est.ce qui joue", r"en cours de lecture", r"passe la suivante",
        r"je veux écouter", r"mets.moi de la musique", r"mets quelque chose",
        r"joue.moi", r"balance de la musique", r"balance un son",
        r"mets un peu de musique", r"un peu de musique", r"\bde la musique\b",
        r"ambiance musicale", r"quelque chose à écouter",
        r"\bdu rap\b", r"\bdu jazz\b", r"\bdu lofi\b", r"\bdu r&b\b",
        r"\bde la pop\b", r"de l'électronique", r"\bdu chaabi\b",
        r"\bdu raï\b", r"\bdu rai\b", r"musique de fond", r"fond musical",
        r"\bqui chante\b",
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

    def _build_conditional_sections(
        self,
        persona: dict,
        has_notes: bool = False,
        has_memory: bool = False,
    ) -> str:
        """Sections optionnelles ajoutées au prompt selon le contexte actuel."""
        sections = []

        # Section météo/saison NexaTel — seulement si business configuré
        biz = persona.get("business", {})
        if biz.get("name"):
            from datetime import datetime as _dtc
            _m = _dtc.now().month
            _saison = {
                5: f"SAISON FORTE déménagements — beaucoup de prospects pour {biz['name']}.",
                6: f"SAISON FORTE déménagements — cibler les groupes Facebook immobilier.",
                7: "SAISON ÉTÉ — étudiants et familles déménagent.",
                8: "SAISON ÉTÉ — pic de prospection, expats et colocation.",
                9: "RENTRÉE — familles cherchent de nouvelles offres internet.",
                1: "JANVIER — tous les opérateurs ont augmenté. Argument prix fixe très fort.",
            }.get(_m)
            if _saison:
                sections.append(f"━━━ CONTEXTE COMMERCIAL ━━━\n{_saison}")

        # Section Obsidian — seulement si notes trouvées
        if has_notes:
            sections.append(
                "━━━ NOTES OBSIDIAN ━━━\n"
                "Des notes pertinentes ont été trouvées et injectées dans {notes_context}. "
                "Utilise-les pour personnaliser ta réponse."
            )

        # Section mémoire — seulement si faits mémorisés
        if has_memory:
            sections.append(
                "━━━ MÉMOIRE ACTIVE ━━━\n"
                "Des informations des sessions précédentes sont disponibles dans {memory_context}. "
                "Utilise-les naturellement sans les citer textuellement."
            )

        return "\n\n" + "\n\n".join(sections) if sections else ""

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

        # Sections conditionnelles (ajoutées seulement si pertinentes)
        conditional = self._build_conditional_sections(
            persona=persona,
            has_notes=bool(notes),
            has_memory=bool(memory_context.strip()),
        )

        return _SYSTEM_PERSONA.format(
            user_name=_user_name,
            persona_block=safe_persona,
            current_datetime=current_datetime,
            memory_context=safe_memory,
            notes_context=safe_notes,
        ) + conditional

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

        # Streaming Groq : détecte tool call ou texte en temps réel → TTS par phrase
        try:
            _max_retries = 2
            for _attempt in range(_max_retries):
                try:
                    stream = self._groq_client.chat.completions.create(
                        model=self.groq_model,
                        messages=messages,
                        tools=TOOLS,
                        tool_choice=tool_choice,
                        max_tokens=400,
                        temperature=0.6,
                        stream=True,
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
        Séparé de chat_with_tools pour être testable unitairement.
        """
        def _gen():
            for _chunk in stream:
                _delta = _chunk.choices[0].delta
                if _delta.tool_calls:
                    tc_state["is_tool"] = True
                    _stc = _delta.tool_calls[0]
                    if _stc.id:
                        tc_state["id"] = _stc.id
                    if _stc.function.name:
                        tc_state["name"] += _stc.function.name
                    if _stc.function.arguments:
                        tc_state["args"] += _stc.function.arguments
                elif _delta.content:
                    self._last_response += _delta.content
                    yield _delta.content
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

