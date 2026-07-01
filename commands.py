"""
commands.py — Commandes locales JARVIS (ultra-rapides, sans appel API)
Seules les opérations vraiment locales restent ici.
Tout le reste (météo, apps, web, musique, volume...) est géré par le tool calling LLM.
"""

import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Commandes locales (sans LLM)
CMD_STOP_SPEAKING  = "STOP_SPEAKING"
CMD_REPEAT         = "REPEAT"
CMD_DATETIME       = "DATETIME"
CMD_SILENT_MODE    = "SILENT_MODE"
CMD_VOCAL_MODE     = "VOCAL_MODE"
CMD_SHUTDOWN       = "SHUTDOWN"
CMD_QUICK_NOTE     = "QUICK_NOTE"
CMD_SAVE_MEMORY    = "SAVE_MEMORY"
CMD_FORGET_MEMORY  = "FORGET_MEMORY"
CMD_SEARCH_NOTES   = "SEARCH_NOTES"
CMD_CLEAR_HISTORY  = "CLEAR_HISTORY"
CMD_CALCULATE      = "CALCULATE"
CMD_SYSTEM_INFO    = "SYSTEM_INFO"
CMD_TRANSLATE      = "TRANSLATE"
CMD_REFRESH_VAULT  = "REFRESH_VAULT"
CMD_DAILY_BRIEF    = "DAILY_BRIEF"
CMD_WHO_AM_I       = "WHO_AM_I"
CMD_FOCUS_MODE     = "FOCUS_MODE"
CMD_NIGHT_MODE     = "NIGHT_MODE"
CMD_SESSION_SUMMARY = "SESSION_SUMMARY"
CMD_NEXATEL_PITCH   = "NEXATEL_PITCH"
CMD_POMODORO        = "POMODORO"
CMD_STATUS          = "STATUS"
CMD_REMINDER        = "REMINDER"
CMD_NEW_LEAD        = "NEW_LEAD"
CMD_HELP            = "HELP"
CMD_LEADS           = "LEADS"
CMD_MOTIVATION      = "MOTIVATION"

# Patterns regex — uniquement pour les commandes qui doivent bypasser le LLM
_PATTERNS = {
    CMD_STOP_SPEAKING: re.compile(
        r"\b(arrête|stop|stoppe|tais-toi|shut up|stop speaking)\b",
        re.IGNORECASE,
    ),
    CMD_REPEAT: re.compile(
        r"\b(répète|répète ça|répète s'il te plaît|repeat|redis(-moi)?)\b",
        re.IGNORECASE,
    ),
    CMD_DATETIME: re.compile(
        r"\b(quelle heure|quel jour|quelle date|il est quelle|on est quel|what time|what day|today)\b",
        re.IGNORECASE,
    ),
    CMD_SILENT_MODE: re.compile(
        r"\b(mode silencieux|sans audio)\b",
        re.IGNORECASE,
    ),
    CMD_VOCAL_MODE: re.compile(
        r"\b(mode vocal|reprends le son|avec audio)\b",
        re.IGNORECASE,
    ),
    CMD_SHUTDOWN: re.compile(
        r"\b(éteins-toi|au revoir|à bientôt|bonne nuit|shutdown|goodbye|ferme-toi)\b",
        re.IGNORECASE,
    ),
    CMD_QUICK_NOTE: re.compile(
        r"\b(?:note que|prends note(?: que)?|note:?)\s+(.+)",
        re.IGNORECASE,
    ),
    CMD_SAVE_MEMORY: re.compile(
        r"\b(?:souviens-toi que|mémorise que|retiens que|n'oublie pas que|remember that)\s+(.+)",
        re.IGNORECASE,
    ),
    CMD_FORGET_MEMORY: re.compile(
        r"\b(?:oublie|efface de ta mémoire|supprime de ta mémoire)\s+(.+)",
        re.IGNORECASE,
    ),
    CMD_SEARCH_NOTES: re.compile(
        r"\b(?:qu'est-ce que tu sais sur|que sais-tu sur|cherche dans tes notes)\s+(?!moi\b)(.+)",
        re.IGNORECASE,
    ),
    CMD_CLEAR_HISTORY: re.compile(
        r"\b(efface l'historique|réinitialise la mémoire|clear history|nouvelle conversation)\b",
        re.IGNORECASE,
    ),
    CMD_CALCULATE: re.compile(
        r"\b(?:calcule|combien (?:font|fait|vautent|ça fait)|quel est le résultat de|"
        r"c'est combien|calculate|résultat de|combien ça fait|donne-moi le résultat de|"
        r"fais le calcul de|racine (?:carrée )?de\s+\d|"
        r"\d+\s*(?:fois|plus|moins|divisé|pour cent|%)\s*\d)\s*(.+)?",
        re.IGNORECASE,
    ),
    CMD_TRANSLATE: re.compile(
        r"\b(?:traduis(?:-moi)?|traduire|comment (?:dit-on|se dit|on dit)|translate|"
        r"c'est quoi en (?:anglais|espagnol|arabe|allemand|italien|néerlandais|portugais|"
        r"turc|russe|chinois|japonais|coréen|hindi|polonais|roumain|français)|"
        r"ça se dit comment en|dis-moi comment dire|"
        r"que (?:veut dire|signifie)\s+.{1,60}\s+en\s+\w+|"
        r"comment (?:traduire|écrire)\s+.+\s+en\s+\w+|"
        r"c'est quoi la traduction de)\s*(.+)",
        re.IGNORECASE,
    ),
    CMD_REFRESH_VAULT: re.compile(
        r"\b(rafraîchis? tes notes|actualise? le vault|remets à jour tes notes|synchronise tes notes|re-?index(e|ez)? le vault)\b",
        re.IGNORECASE,
    ),
    CMD_DAILY_BRIEF: re.compile(
        r"\b(brief du matin|briefing du matin|résumé de (ma )?journée|point du jour|donne-moi le (brief|point|résumé)|qu'est-ce que j'ai (aujourd'hui|ce matin|prévu)|mon programme du jour|qu'est-ce qui est prévu aujourd'hui)\b",
        re.IGNORECASE,
    ),
    CMD_WHO_AM_I: re.compile(
        r"\b(qu'est-ce que tu sais sur moi|résume ce que tu sais sur moi|ce que tu sais de moi|tes souvenirs sur moi|ma fiche|ce que tu mémorises sur moi)\b",
        re.IGNORECASE,
    ),
    CMD_FOCUS_MODE: re.compile(
        r"\b(mode (focus|travail|concentration|boulot)|lance le mode focus|active le mode travail|mets-toi en mode (focus|travail)|je travaille|je me mets au travail)\b",
        re.IGNORECASE,
    ),
    CMD_NIGHT_MODE: re.compile(
        r"\b(mode nuit|mode veille|je vais dormir|je vais me coucher|mode repos|éteins tout)\b",
        re.IGNORECASE,
    ),
    CMD_SESSION_SUMMARY: re.compile(
        r"\b(résume (notre |la |cette )?session|qu'est-ce qu'on a (fait|dit|discuté)|résume notre conversation|bilan de session|ce qu'on a fait aujourd'hui)\b",
        re.IGNORECASE,
    ),
    CMD_NEXATEL_PITCH: re.compile(
        r"\b(aide-moi (à |avec |pour )?(convaincre|répondre|pitcher|composer|rédiger)|compose (un message|une réponse|un pitch)|argument (pour|contre|face|vs)|script (client|vente|NexaTel)|comment répondre (à |au client|à l'objection)|objection client|client qui hésite|client (VOO|Orange|Proximus|Telenet)|message pour (un client|mon client))\b",
        re.IGNORECASE,
    ),
    CMD_POMODORO: re.compile(
        r"\b(pomodoro|démarre (un )?pomodoro|lance (un )?pomodoro|timer (de |de travail |pomodoro )?(25|vingt.?cinq)|25 minutes de travail|session pomodoro)\b",
        re.IGNORECASE,
    ),
    CMD_STATUS: re.compile(
        r"\b(quel est ton (statut|état)|comment tu vas|état du système|état de jarvis|statut (de jarvis|du système)|tout va bien|tu fonctionnes bien|bilan système)\b",
        re.IGNORECASE,
    ),
    CMD_REMINDER: re.compile(
        r"\b(?:rappelle-?(?:moi|le|la|leur)?|reminde?(?:-?me)?)\b.{0,80}(?:dans\s+\d+\s*(?:heure|h\b|minute|min\b|mn\b|seconde|sec\b)|\d+\s*(?:heure|h\b|minute|min\b|mn\b|seconde|sec\b))",
        re.IGNORECASE,
    ),
    CMD_NEW_LEAD: re.compile(
        r"\b(nouveau (?:client|lead|prospect|contact)|j[‘’]ai (?:un |un nouveau |une |une nouvelle )?(?:client|lead|prospect)|nouveau (?:client|lead) nexatel|j[‘’]ai (?:converti|signé|obtenu) (?:un client|un lead|un prospect))\b",
        re.IGNORECASE,
    ),
    CMD_HELP: re.compile(
        r"\b(que peux-tu faire|qu’est-ce que tu (peux faire|sais faire)|tes (capacités|fonctions|fonctionnalités|commandes)|liste (tes|les) commandes|aide-moi à comprendre|quelles? sont tes|montre.moi tes capacités|help|comment t[‘’]utiliser)\b",
        re.IGNORECASE,
    ),
    CMD_LEADS: re.compile(
        r"(combien .{0,10}(leads?|prospects?|clients? potentiels?)|mes (leads?|prospects?)|pipeline nexatel|tableau de bord (clients?|leads?|nexatel)|état (de mes|du) (leads?|prospects?)|liste (de mes|des) (leads?|prospects?)|combien .{0,10}(converti|signé|gagné)|bilan nexatel)",
        re.IGNORECASE,
    ),
    CMD_MOTIVATION: re.compile(
        r"(je suis (nul|fatigué|découragé|démotivé|déprimé|au bout|épuisé|paumé)|j.en peux plus|c.est (trop )?(dur|difficile|compliqué)|je (galère|rame|bloque|lâche)|remonte.moi le moral|donne.moi (de la motivation|un coup de boost)|encourage.moi|motive.moi|je (doute|capitule|abandonne))",
        re.IGNORECASE,
    ),
}


class CommandProcessor:
    """Détecte et exécute les commandes locales ultra-rapides."""

    def __init__(self, tts, memory, llm, persistent_memory=None, user_name: str = "patron"):
        self.tts = tts
        self.memory = memory
        self.llm = llm
        self.persistent_memory = persistent_memory
        self.user_name = user_name

    def detect_command(self, text: str) -> Optional[str]:
        if not text or not text.strip():
            return None
        for cmd, pattern in _PATTERNS.items():
            if pattern.search(text):
                logger.debug(f"Commande locale : {cmd} dans '{text[:50]}'")
                return cmd
        return None

    def _extract_argument(self, command: str, text: str) -> Optional[str]:
        pattern = _PATTERNS.get(command)
        if not pattern:
            return None
        match = pattern.search(text)
        if match and match.lastindex and match.lastindex >= 1:
            return match.group(1).strip()
        return None

    def execute(self, command: str, text: str) -> Tuple[bool, Optional[str]]:
        """
        Retourne (handled, response_text).
        handled=True → ne pas appeler le LLM.
        """
        handlers = {
            CMD_STOP_SPEAKING:  self._handle_stop,
            CMD_REPEAT:         self._handle_repeat,
            CMD_DATETIME:       self._handle_datetime,
            CMD_SILENT_MODE:    self._handle_silent_mode,
            CMD_VOCAL_MODE:     self._handle_vocal_mode,
            CMD_SHUTDOWN:       self._handle_shutdown,
            CMD_QUICK_NOTE:     self._handle_quick_note,
            CMD_SAVE_MEMORY:    self._handle_save_memory,
            CMD_FORGET_MEMORY:  self._handle_forget_memory,
            CMD_SEARCH_NOTES:   self._handle_search_notes,
            CMD_CLEAR_HISTORY:  self._handle_clear_history,
            CMD_CALCULATE:      self._handle_calculate,
            CMD_SYSTEM_INFO:    self._handle_system_info,
            CMD_TRANSLATE:      self._handle_translate,
            CMD_REFRESH_VAULT:  self._handle_refresh_vault,
            CMD_DAILY_BRIEF:    self._handle_daily_brief,
            CMD_WHO_AM_I:       self._handle_who_am_i,
            CMD_FOCUS_MODE:     self._handle_focus_mode,
            CMD_NIGHT_MODE:     self._handle_night_mode,
            CMD_SESSION_SUMMARY: self._handle_session_summary,
            CMD_NEXATEL_PITCH:   self._handle_nexatel_pitch,
            CMD_POMODORO:        self._handle_pomodoro,
            CMD_STATUS:          self._handle_status,
            CMD_REMINDER:        self._handle_reminder,
            CMD_NEW_LEAD:        self._handle_new_lead,
            CMD_HELP:            self._handle_help,
            CMD_LEADS:           self._handle_leads,
            CMD_MOTIVATION:      self._handle_motivation,
        }
        handler = handlers.get(command)
        if not handler:
            return False, None
        try:
            return handler(text)
        except Exception as e:
            logger.error(f"Erreur commande {command} : {e}")
            return True, "Une erreur s'est produite."

    # ── Handlers ───────────────────────────────────────────────────────────

    def _handle_stop(self, text: str) -> Tuple[bool, Optional[str]]:
        self.tts.stop()
        return True, None

    def _handle_repeat(self, text: str) -> Tuple[bool, Optional[str]]:
        last = self.llm.get_last_response()
        return True, last or "Je n'ai rien à répéter."

    def _handle_datetime(self, text: str) -> Tuple[bool, Optional[str]]:
        now = datetime.now()
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois  = ["janvier", "février", "mars", "avril", "mai", "juin",
                 "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        return True, (
            f"Nous sommes {jours[now.weekday()]} {now.day} {mois[now.month - 1]} {now.year}, "
            f"il est {now.strftime('%H:%M')}."
        )

    def _handle_silent_mode(self, text: str) -> Tuple[bool, Optional[str]]:
        self.tts.set_silent_mode(True)
        return True, "Mode silencieux activé."

    def _handle_vocal_mode(self, text: str) -> Tuple[bool, Optional[str]]:
        self.tts.set_silent_mode(False)
        return True, "Mode vocal rétabli."

    def _handle_shutdown(self, text: str) -> Tuple[bool, Optional[str]]:
        from datetime import datetime
        h = datetime.now().hour
        if 5 <= h < 12:
            salut = "Bonne matinée"
        elif 12 <= h < 18:
            salut = "Bon après-midi"
        elif 18 <= h < 22:
            salut = "Bonne soirée"
        else:
            salut = "Bonne nuit"
        return True, f"Au revoir, {self.user_name}. {salut}. JARVIS hors ligne."

    def _handle_quick_note(self, text: str) -> Tuple[bool, Optional[str]]:
        content = self._extract_argument(CMD_QUICK_NOTE, text)
        if not content:
            return True, "Je n'ai pas compris la note."
        self.memory.save_quick_note(content)
        # Mémoriser aussi dans persistent_memory si la note contient des infos clés
        if self.persistent_memory and any(
            kw in content.lower() for kw in
            ["rdv", "réunion", "client", "lead", "appel", "demain", "contrat",
             "signé", "converti", "vendu", "lundi", "mardi", "mercredi",
             "jeudi", "vendredi", "important", "urgent", "nexatel"]
        ):
            self.persistent_memory.save_fact(content)
        return True, f"Note sauvegardée : {content[:60]}."

    def _handle_save_memory(self, text: str) -> Tuple[bool, Optional[str]]:
        content = self._extract_argument(CMD_SAVE_MEMORY, text)
        if not content:
            return True, "Qu'est-ce que je dois mémoriser ?"
        if self.persistent_memory:
            self.persistent_memory.save_fact(content)
        self.memory.save_core_memory(content)
        return True, f"Mémorisé : {content[:60]}."

    def _handle_forget_memory(self, text: str) -> Tuple[bool, Optional[str]]:
        keyword = self._extract_argument(CMD_FORGET_MEMORY, text)
        if not keyword:
            return True, "Que voulez-vous que j'oublie ?"
        removed = self.persistent_memory.forget_facts_about(keyword) if self.persistent_memory else 0
        if removed:
            return True, f"J'ai effacé {removed} souvenir(s) sur '{keyword}'."
        return True, f"Rien trouvé sur '{keyword}'."

    def _handle_search_notes(self, text: str) -> Tuple[bool, Optional[str]]:
        topic = self._extract_argument(CMD_SEARCH_NOTES, text)
        if not topic:
            return True, "Sur quel sujet ?"
        result = self.memory.search_and_read(topic)
        if not result:
            return True, f"Aucune note sur '{topic}'."
        # Synthèse LLM pour une réponse vocale naturelle
        if self.llm:
            try:
                synth = self.llm.chat_sync(
                    f"Note '{topic}' :\n{result[:600]}\n\n"
                    f"Résume en 2-3 phrases naturelles pour une réponse vocale. Pas de liste, pas de markdown.",
                    system="Tu es JARVIS. Résume le contenu d'une note de façon naturelle et concise, pour être lu à voix haute.",
                    max_tokens=100,
                )
                if synth and len(synth) > 20:
                    return True, synth
            except Exception:
                pass
        return True, result[:400]

    def _handle_clear_history(self, text: str) -> Tuple[bool, Optional[str]]:
        self.llm.clear_history()
        return True, "Historique effacé. Nouvelle conversation."

    def _handle_calculate(self, text: str) -> Tuple[bool, Optional[str]]:
        expr = self._extract_argument(CMD_CALCULATE, text) or text
        orig = expr.strip()

        # Traduction langage naturel → expression mathématique
        import re as _re
        e = expr.lower().strip()
        # Opérateurs textuels
        e = _re.sub(r'\bfois\b', '*', e)
        e = _re.sub(r'\bmultipli[eé][e]?\s*par\b', '*', e)
        e = _re.sub(r'\bdivisé\s*par\b', '/', e)
        e = _re.sub(r'\bplus\b', '+', e)
        e = _re.sub(r'\bmoins\b', '-', e)
        e = _re.sub(r'\bau\s*carré\b', '**2', e)
        e = _re.sub(r'\bau\s*cube\b', '**3', e)
        e = _re.sub(r'\bsquare\s*root\s*(?:de|of)?\b', 'sqrt', e)
        e = _re.sub(r'\bracine\s*(?:carrée\s*)?(?:de|d\'|du)?\s*(\d+(?:[.,]\d+)?)', r'sqrt(\1)', e)
        # Pourcentages : "15 pour cent de 350" → (15/100)*350
        pct_m = _re.search(r'(\d+(?:\.\d+)?)\s*(?:pour\s*cent|%)\s*de\s*(\d+(?:\.\d+)?)', e)
        if pct_m:
            pct_val = float(pct_m.group(1))
            base_val = float(pct_m.group(2))
            result = pct_val / 100 * base_val
            fmt = f"{result:.2f}".rstrip("0").rstrip(".")
            return True, f"{pct_val}% de {base_val} = {fmt}"
        # Virgule décimale française (3,14 → 3.14)
        e = e.replace(",", ".")
        # Symboles alternatifs
        e = e.replace("×", "*").replace("÷", "/").replace("^", "**")
        # Garder uniquement les chars valides + sqrt/pi
        e = _re.sub(r'[^0-9+\-*/().% sqrt pi e]', ' ', e).strip()
        e = _re.sub(r'\s+', '', e)
        if not e:
            return True, "Quelle expression voulez-vous calculer ?"
        try:
            import math as _math
            safe_env = {"__builtins__": {}, "sqrt": _math.sqrt, "pi": _math.pi, "e": _math.e}
            result = eval(e, safe_env)  # nosec
            if isinstance(result, float) and result == int(result):
                result = int(result)
            elif isinstance(result, float):
                result = round(result, 6)
            return True, f"{orig} = {result}"
        except ZeroDivisionError:
            return True, "Division par zéro impossible."
        except Exception:
            return True, f"Je n'arrive pas à évaluer '{orig}'."

    def _handle_system_info(self, text: str) -> Tuple[bool, Optional[str]]:
        try:
            import psutil
            text_lower = text.lower()
            parts = []
            if any(w in text_lower for w in ["batterie", "charge"]):
                batt = psutil.sensors_battery()
                if batt:
                    status = "en charge" if batt.power_plugged else "sur batterie"
                    parts.append(f"Batterie à {int(batt.percent)}%, {status}.")
                else:
                    parts.append("Aucune batterie — machine fixe.")
            if any(w in text_lower for w in ["ram", "mémoire"]):
                mem = psutil.virtual_memory()
                parts.append(f"RAM : {mem.used/(1024**3):.1f}/{mem.total/(1024**3):.1f} Go ({mem.percent}%).")
            if any(w in text_lower for w in ["cpu", "processeur"]):
                parts.append(f"CPU à {psutil.cpu_percent(interval=0.5)}%.")
            if any(w in text_lower for w in ["disque", "espace"]):
                disk = psutil.disk_usage("/")
                parts.append(f"Disque : {disk.free/(1024**3):.0f} Go libres sur {disk.total/(1024**3):.0f} Go.")
            if not parts:
                batt = psutil.sensors_battery()
                mem = psutil.virtual_memory()
                cpu = psutil.cpu_percent(interval=0.5)
                batt_str = f"batterie {int(batt.percent)}%" if batt else "branché"
                parts.append(f"CPU {cpu}%, RAM {mem.percent}%, {batt_str}.")
            return True, " ".join(parts)
        except ImportError:
            return True, "psutil non installé."
        except Exception as e:
            return True, f"Erreur système : {e}"

    def _handle_translate(self, text: str) -> Tuple[bool, Optional[str]]:
        content = self._extract_argument(CMD_TRANSLATE, text)
        if not content:
            return True, "Que traduire ?"
        text_lower = text.lower()
        # Détecter la langue cible et son code ISO
        LANG_MAP = {
            "anglais": ("en", "anglais"), "english": ("en", "anglais"),
            "espagnol": ("es", "espagnol"), "español": ("es", "espagnol"),
            "arabe": ("ar", "arabe"), "arabic": ("ar", "arabe"),
            "néerlandais": ("nl", "néerlandais"), "dutch": ("nl", "néerlandais"),
            "flamand": ("nl", "néerlandais"),
            "allemand": ("de", "allemand"), "german": ("de", "allemand"),
            "italien": ("it", "italien"), "italian": ("it", "italien"),
            "portugais": ("pt", "portugais"), "portuguese": ("pt", "portugais"),
            "turc": ("tr", "turc"), "turkish": ("tr", "turc"),
            "russe": ("ru", "russe"), "russian": ("ru", "russe"),
            "chinois": ("zh", "chinois"), "chinese": ("zh", "chinois"),
            "japonais": ("ja", "japonais"), "japanese": ("ja", "japonais"),
            "coréen": ("ko", "coréen"), "korean": ("ko", "coréen"),
            "hindi": ("hi", "hindi"),
            "polonais": ("pl", "polonais"), "polish": ("pl", "polonais"),
            "roumain": ("ro", "roumain"), "romanian": ("ro", "roumain"),
            "français": ("fr", "français"), "french": ("fr", "français"),
        }
        lang_code, lang_name = "en", "anglais"
        for kw, (code, name) in LANG_MAP.items():
            if kw in text_lower:
                lang_code, lang_name = code, name
                break

        # Nettoyer "en anglais", "en espagnol", etc. de la fin du contenu à traduire
        for kw in LANG_MAP:
            content = re.sub(r'\s+en\s+' + re.escape(kw) + r'\s*$', '', content, flags=re.IGNORECASE)
            content = re.sub(r'\s+' + re.escape(kw) + r'\s*$', '', content, flags=re.IGNORECASE)
        content = content.strip().strip('"\'')

        try:
            import requests, urllib.parse
            # Détecter la langue source (fr par défaut, ar/en si contenu non-latin)
            src_lang = "fr"
            if any('؀' <= c <= 'ۿ' for c in content):
                src_lang = "ar"  # Arabe détecté
            elif all(ord(c) < 128 for c in content if c.isalpha()):
                src_lang = "en"  # ASCII pur → probablement anglais
            # Éviter fr→fr (sens inverse inutile)
            if src_lang == lang_code:
                src_lang = "fr" if lang_code != "fr" else "en"
            # MyMemory API — 5000 chars/jour gratuit, sans clé
            url = (
                f"https://api.mymemory.translated.net/get"
                f"?q={urllib.parse.quote(content[:400])}"
                f"&langpair={src_lang}|{lang_code}"
                f"&de=achoker@francoisdesales.be"
            )
            resp = requests.get(url, timeout=5)
            data = resp.json()
            translation = data.get("responseData", {}).get("translatedText", "")
            if translation and translation.lower() != content.lower():
                return True, f"En {lang_name} : {translation}"
        except Exception:
            pass

        # Fallback : Groq si MyMemory indisponible
        result = self.llm.chat_sync(
            f"Traduis en {lang_name} (uniquement la traduction, rien d'autre) : {content}",
            system=f"Traducteur. Réponds UNIQUEMENT avec la traduction en {lang_name}.",
            max_tokens=80,
        )
        return True, f"En {lang_name} : {result}" if result else "Traduction indisponible."

    def _handle_refresh_vault(self, text: str) -> Tuple[bool, Optional[str]]:
        """Re-indexe le vault Obsidian — recharge le cache si accès direct refusé."""
        try:
            # Tenter un accès direct (marche en mode interactif)
            self.memory.index_vault(_retry=0)
            count = len(self.memory._index)
            if count > 0:
                return True, f"Notes Obsidian actualisées — {count} notes disponibles."
            # Fallback : recharger depuis le cache JSON
            if self.memory._load_from_cache():
                count = len(self.memory._index)
                return True, f"Cache rechargé — {count} notes disponibles."
            return True, "Impossible d'accéder aux notes. Lancez JARVIS depuis un terminal pour mettre le cache à jour."
        except Exception as e:
            return True, f"Erreur lors de l'actualisation : {e}"

    def _handle_daily_brief(self, text: str) -> Tuple[bool, Optional[str]]:
        """Brief multi-source : météo + agenda Obsidian + calendrier macOS, synthèse LLM."""
        from jarvis_tools import execute_tool
        from datetime import datetime as _dt

        now = _dt.now()
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois  = ["janvier", "février", "mars", "avril", "mai", "juin",
                 "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date_str = f"{jours[now.weekday()]} {now.day} {mois[now.month - 1]}"

        raw_parts = []

        # 1-4. Météo + Obsidian + Calendrier + Emails en parallèle
        _api_tasks = {
            "meteo":    (execute_tool, "meteo",      {"ville": "Charleroi"}),
            "obsidian": (execute_tool, "obsidian",   {"action": "agenda", "requete": ""}),
            "cal":      (execute_tool, "calendrier", {"action": "lire"}),
            "emails":   (execute_tool, "emails",     {"action": "lire_derniers"}),
        }
        _api_results: dict = {}
        with ThreadPoolExecutor(max_workers=4) as _pool:
            _futures = {
                _pool.submit(fn, tool, args): key
                for key, (fn, tool, args) in _api_tasks.items()
            }
            for _fut in as_completed(_futures, timeout=10):
                _key = _futures[_fut]
                try:
                    _api_results[_key] = _fut.result()
                except Exception:
                    _api_results[_key] = None

        weather = _api_results.get("meteo") or ""
        agenda  = _api_results.get("obsidian") or ""
        cal     = _api_results.get("cal") or ""
        emails  = _api_results.get("emails") or ""

        if weather and "indisponible" not in weather.lower():
            raw_parts.append(f"MÉTÉO: {weather}")
        if agenda and "Aucun" not in agenda:
            raw_parts.append(f"AGENDA OBSIDIAN: {agenda}")
        if cal and "aucun" not in cal.lower() and "indisponible" not in cal.lower():
            raw_parts.append(f"CALENDRIER: {cal}")
        if emails and "aucun" not in emails.lower() and "indisponible" not in emails.lower():
            raw_parts.append(f"EMAILS: {emails}")

        # 4. Mémoire persistante — derniers rappels
        if self.persistent_memory:
            facts = self.persistent_memory.get_facts(limit=5)
            rdv_facts = [f for f in facts if any(k in f.lower() for k in
                         ["rdv", "réunion", "entretien", "appel prévu"])]
            if rdv_facts:
                raw_parts.append("RAPPELS: " + " | ".join(rdv_facts[:2]))
            elif facts:
                raw_parts.append("RAPPELS: " + " | ".join(facts[:1]))

        # 5. Pipeline NexaTel — stats commerciales
        if self.persistent_memory:
            all_facts = self.persistent_memory.get_facts(limit=100)
            leads = [f for f in all_facts if any(k in f.lower() for k in
                     ["lead", "prospect", "nouveau client"])]
            conversions = [f for f in all_facts if any(k in f.lower() for k in
                           ["signé", "converti", "gagné", "closé"])]
            if leads or conversions:
                parts_nxt = []
                if leads:
                    parts_nxt.append(f"{len(leads)} lead{'s' if len(leads) > 1 else ''} actif{'s' if len(leads) > 1 else ''}")
                if conversions:
                    parts_nxt.append(f"{len(conversions)} conversion{'s' if len(conversions) > 1 else ''}")
                raw_parts.append(f"NEXATEL: {', '.join(parts_nxt)}.")
            else:
                raw_parts.append("NEXATEL: Aucun lead enregistré — bonne journée pour prospecter sur Facebook.")

        if not raw_parts:
            return True, f"Rien de particulier prévu pour ce {date_str}. Bonne journée, {self.user_name}."

        # Contexte saisonnier NexaTel
        from datetime import datetime as _dt2
        _m = _dt2.now().month
        _saison_tip = ""
        if _m in (5, 6):
            _saison_tip = "Saison forte déménagements — cibler les groupes FB immobilier/colocation."
        elif _m in (7, 8):
            _saison_tip = "Pic été — étudiants et familles déménagent. Facebook groups colocation et expats à prioriser."
        elif _m == 9:
            _saison_tip = "Rentrée — familles cherchent de nouvelles offres internet. Moment idéal pour prospecter."
        elif _m == 1:
            _saison_tip = "Début janvier — tous les opérateurs ont augmenté. Argument prix fixe NexaTel très fort maintenant."
        if _saison_tip:
            raw_parts.append(f"CONSEIL NEXATEL: {_saison_tip}")

        # Synthèse LLM si disponible — brief vocal naturel
        if self.llm:
            try:
                context = "\n".join(raw_parts)
                brief = self.llm.chat_sync(
                    f"Brief de {date_str} pour Ali :\n{context}\n\n"
                    f"Fais un brief vocal naturel en 2-3 phrases. Mentionne la météo en premier si disponible, "
                    f"puis les RDV importants, puis le point NexaTel avec le conseil du jour. "
                    f"Pas de liste, pas de markdown. Commence directement sans formule de politesse.",
                    system=(
                        f"Tu es JARVIS, assistant vocal de {self.user_name}. "
                        "Synthétise le brief de façon naturelle et directe, comme tu parlerais à voix haute. "
                        "Sois utile et concis — max 70 mots."
                    ),
                    max_tokens=150,
                )
                if brief and len(brief) > 20:
                    return True, brief
            except Exception:
                pass

        # Fallback sans LLM — texte brut
        return True, f"Brief du {date_str}. " + " ".join(p.split(": ", 1)[-1] for p in raw_parts)

    def _handle_who_am_i(self, text: str) -> Tuple[bool, Optional[str]]:
        """Résume ce que JARVIS sait sur Ali — faits catégorisés + synthèse LLM."""
        if not self.persistent_memory:
            return True, "Je n'ai pas encore de mémoire persistante pour cette session."

        facts = self.persistent_memory.get_facts(limit=50)
        sessions = self.persistent_memory.get_recent_sessions(3)

        if not facts and not sessions:
            return True, (
                "Je n'ai encore rien mémorisé sur vous. "
                "Parlez-moi de vous pendant nos échanges, je retiendrai les informations importantes."
            )

        # Catégoriser les faits par thème
        leads = [f for f in facts if any(k in f.lower() for k in
                 ["lead", "prospect", "client", "nouveau client"])]
        conversions = [f for f in facts if any(k in f.lower() for k in
                       ["signé", "converti", "gagné", "closé", "contrat"])]
        rdvs = [f for f in facts if any(k in f.lower() for k in
                ["rdv", "réunion", "rencontre", "entretien", "appel prévu"])]
        prefs = [f for f in facts if any(k in f.lower() for k in
                 ["préfère", "aime", "adore", "objectif", "vise", "cherche à"])]

        # Synthèse LLM — réponse naturelle et personnelle
        if self.llm and facts:
            try:
                stats_parts = []
                if leads:
                    stats_parts.append(f"{len(leads)} lead{'s' if len(leads) > 1 else ''} NexaTel")
                if conversions:
                    stats_parts.append(f"{len(conversions)} conversion{'s' if len(conversions) > 1 else ''}")
                if rdvs:
                    stats_parts.append(f"{len(rdvs)} rendez-vous")
                stats_str = (", ".join(stats_parts) + ". ") if stats_parts else ""

                recent_facts = facts[-8:]
                context = "\n".join(f"• {f}" for f in recent_facts)
                synth = self.llm.chat_sync(
                    f"Ce que je sais sur Ali ({len(facts)} faits mémorisés) :\n{context}\n\n"
                    f"Statistiques NexaTel : {stats_str}\n"
                    f"Fais un résumé naturel en 3-4 phrases. Commence par les chiffres NexaTel si pertinents.",
                    system=(
                        f"Tu es JARVIS, l'assistant personnel de {self.user_name}. "
                        "Résume ce que tu sais sur lui de façon directe et humaine. "
                        "Parle à la 2ème personne (vous avez, vous êtes, vous avez fait...)."
                    ),
                    max_tokens=150,
                )
                if synth and len(synth) > 20:
                    return True, synth
            except Exception:
                pass

        # Fallback sans LLM — résumé structuré
        parts = [f"J'ai {len(facts)} souvenir{'s' if len(facts) > 1 else ''} sur vous."]
        if leads:
            parts.append(f"{len(leads)} lead{'s' if len(leads) > 1 else ''} NexaTel dans le pipeline.")
        if conversions:
            parts.append(f"{len(conversions)} conversion{'s' if len(conversions) > 1 else ''}.")
        if rdvs:
            parts.append(f"{len(rdvs)} rendez-vous mémorisé{'s' if len(rdvs) > 1 else ''}.")
        recent = facts[-3:]
        if recent:
            parts.append("Derniers souvenirs : " + " — ".join(f[:60] for f in recent) + ".")
        if sessions:
            last = sessions[-1]
            summary = last.get("summary", "")
            if summary:
                parts.append(f"Dernière session ({last.get('date', '?')}) : {summary}.")
        return True, " ".join(parts)

    def _handle_focus_mode(self, text: str) -> Tuple[bool, Optional[str]]:
        """Mode travail : ouvre l'éditeur de code + Spotify focus + ferme les distractions."""
        from mac_control import app_open, app_quit, system_mute, spotify_search_play
        import threading

        steps = []

        # Fermer les apps de distraction
        for app in ["Messages", "WhatsApp", "Discord"]:
            try:
                app_quit(app)
            except Exception:
                pass

        # Ouvrir l'éditeur de code
        try:
            result = app_open("cursor")
            steps.append("Cursor ouvert")
        except Exception:
            try:
                app_open("vscode")
                steps.append("VS Code ouvert")
            except Exception:
                pass

        # Lancer de la musique de concentration sur Spotify en arrière-plan
        def _play_focus():
            try:
                spotify_search_play("lofi hip hop focus music")
            except Exception:
                pass
        threading.Thread(target=_play_focus, daemon=True).start()

        return True, f"Mode travail activé. Messages et Discord fermés, Cursor ouvert. Lofi en fond — bonne session, {self.user_name}."

    def _handle_night_mode(self, text: str) -> Tuple[bool, Optional[str]]:
        """Mode nuit : ferme tout, baisse la luminosité, dit bonne nuit."""
        from mac_control import spotify_play_pause, system_set_brightness, system_lock_screen
        import subprocess

        # Pause Spotify
        try:
            spotify_play_pause()
        except Exception:
            pass

        # Luminosité au minimum
        try:
            system_set_brightness(10)
        except Exception:
            pass

        from datetime import datetime as _dt
        h = _dt.now().hour
        # Mémoriser la fin de session
        if self.persistent_memory:
            try:
                self.persistent_memory.save_fact(f"Session terminée à {h}h — mode nuit activé")
            except Exception:
                pass

        return True, f"Bonne nuit, {self.user_name}. J'éteins la musique et je baisse la lumière. JARVIS veille."

    def _handle_session_summary(self, text: str) -> Tuple[bool, Optional[str]]:
        if not self.llm:
            return True, "Pas de LLM disponible pour le résumé."
        history = self.llm.get_history()
        if not history:
            return True, "On n'a encore rien échangé dans cette session."
        recent = history[-10:]
        text_to_summarize = " ".join(
            f"{m['role'].upper()}: {m['content'][:100]}" for m in recent
        )
        summary = self.llm.chat_sync(
            f"Résume en 2-3 phrases ce qu'on a fait dans cette session : {text_to_summarize[:600]}",
            system="Résume de façon concise et naturelle en français. Parle à la 1ère personne (on a, tu as, j'ai).",
            max_tokens=100,
        )
        if self.persistent_memory and summary:
            self.persistent_memory.save_session_summary(summary, len(history) // 2)
        return True, summary or "Session trop courte pour résumer."

    def _handle_nexatel_pitch(self, text: str) -> Tuple[bool, Optional[str]]:
        if not self.llm:
            return True, "LLM non disponible."
        text_lower = text.lower()
        context_parts = []
        if "orange" in text_lower:
            context_parts.append("client chez Orange (système deux vitesses avril 2026, anciens clients paient jusqu'à 600€/an de plus)")
        elif "voo" in text_lower:
            context_parts.append("client VOO (+3€/mois jan 2026, câble pas fibre)")
        elif "telenet" in text_lower:
            context_parts.append("client Telenet (+2% 2026, câble en Wallonie)")
        elif "proximus" in text_lower:
            context_parts.append("client Proximus boutique (réseau OK mais prix élevé, service 1.5/5)")
        if any(w in text_lower for w in ["hésite", "pas convaincu", "doute"]):
            context_parts.append("client qui hésite")
        if any(w in text_lower for w in ["prix", "cher", "coûte"]):
            context_parts.append("objection prix")
        if any(w in text_lower for w in ["arnaque", "confiance", "officiel", "légal"]):
            context_parts.append("objection légitimité")
        if any(w in text_lower for w in ["réseau", "qualité", "couverture"]):
            context_parts.append("objection réseau")
        situation = ", ".join(context_parts) if context_parts else "client générique cherchant à changer d'opérateur"
        prompt = (
            f"Situation : {situation}\n"
            f"Demande : {text}\n\n"
            f"Génère un message NexaTel court (3-4 phrases max) pour cette situation. "
            f"Ton : direct, humain, vendeur mais honnête. Inclure 1 chiffre concret (économie en €). "
            f"Terminer par une question ouverte."
        )
        system = (
            f"Tu es {self.user_name}, consultant indépendant certifié. "
            "Tu vends des abonnements 30-40% moins cher que la boutique officielle. "
            "Arguments clés : prix fixe à vie, même réseau officiel, installation gratuite. "
            "Format : message court et direct, style DM Facebook naturel."
        )
        result = self.llm.chat_sync(prompt, system=system, max_tokens=150)
        return True, result or "Je n'ai pas pu générer le pitch."

    def _handle_pomodoro(self, text: str) -> Tuple[bool, Optional[str]]:
        """Lance un timer Pomodoro 25 min travail + 5 min pause en arrière-plan."""
        import threading
        import time

        def _run_pomodoro():
            time.sleep(25 * 60)
            try:
                self.tts.speak(f"{self.user_name}, tes 25 minutes sont écoulées. Pause 5 minutes — tu l'as mérité.")
            except Exception:
                pass
            time.sleep(5 * 60)
            try:
                self.tts.speak("Pause terminée. Prêt pour le prochain Pomodoro ?")
            except Exception:
                pass

        t = threading.Thread(target=_run_pomodoro, daemon=True)
        t.start()
        return True, "Pomodoro lancé — 25 minutes de travail, je t'avertirai quand c'est fini. Concentre-toi."

    def _handle_status(self, text: str) -> Tuple[bool, Optional[str]]:
        """Rapporte l'état du système JARVIS : composants, notes, mémoire."""
        parts = []

        # Vault Obsidian
        try:
            note_count = len(self.memory._index) if self.memory and hasattr(self.memory, "_index") else 0
            if note_count:
                parts.append(f"{note_count} notes Obsidian indexées")
            else:
                parts.append("vault Obsidian vide ou non indexé")
        except Exception:
            parts.append("vault inconnu")

        # Mémoire persistante
        try:
            if self.persistent_memory:
                facts = self.persistent_memory.get_facts(limit=100)
                parts.append(f"{len(facts)} souvenir(s) en mémoire")
            else:
                parts.append("mémoire persistante inactive")
        except Exception:
            pass

        # LLM
        try:
            if self.llm:
                hist = self.llm.get_history()
                parts.append(f"{len(hist)} message(s) dans l'historique de cette session")
        except Exception:
            pass

        # Moteur LLM actif
        try:
            if self.llm:
                parts.append(f"moteur {self.llm.get_active_engine()}")
        except Exception:
            pass

        if parts:
            return True, "Tout fonctionne. " + ", ".join(parts) + "."
        return True, "JARVIS opérationnel."

    def _handle_reminder(self, text: str) -> Tuple[bool, Optional[str]]:
        """Parse un délai naturel et déclenche un rappel vocal."""
        import threading
        import time as _time
        import re as _re

        t = text.lower()

        # "rappelle-moi à 14h" → heure fixe, pas un délai relatif → rediriger vers alarme
        if _re.search(r'\bà\s+\d{1,2}h\d*\b', t) and not _re.search(r'\bdans\s+\d', t):
            return True, "Pour une heure précise, dites plutôt : 'alarme à 14h' ou 'réveille-moi à 14h30'."

        # Extraire le délai en secondes depuis la phrase (priorité aux patterns avec "dans")
        delay_s = 0
        patterns = [
            (r"dans\s+(\d+)\s*heures?\b", 3600),
            (r"dans\s+(\d+)\s*(?:minutes?|mins?|mn)\b", 60),
            (r"dans\s+(\d+)\s*(?:secondes?|secs?)\b", 1),
            (r"(\d+)\s*h\b(?!\s*\d{2})", 3600),   # "2h" mais pas "14h30" (heure fixe)
            (r"(\d+)\s*(?:minutes?|mins?|mn)\b", 60),
            (r"(\d+)\s*(?:secondes?|secs?)\b", 1),
        ]
        for pat, multiplier in patterns:
            m = _re.search(pat, t)
            if m:
                delay_s = int(m.group(1)) * multiplier
                break

        if not delay_s:
            return True, "Quel délai ? Dites par exemple : 'rappelle-moi dans 10 minutes de prendre mon café'."

        # Extraire le message du rappel — texte intentionnel, sans le délai lui-même
        msg = ""
        for delim in [" de ", " d'", " que ", " pour "]:
            if delim in t:
                candidate = t.split(delim, 1)[-1].strip().rstrip(".!?")
                # Supprimer le délai en fin de phrase s'il y est ("[msg] dans X minutes")
                candidate = _re.sub(r'\s+(?:dans\s+)?\d+\s*(?:heures?|h|minutes?|mins?|mn|secondes?|secs?)\s*$', '', candidate).strip()
                if candidate:
                    msg = candidate
                break
        if not msg:
            msg = "Rappel"

        # Formater le délai en texte lisible
        if delay_s >= 3600:
            delay_label = f"{delay_s // 3600} heure{'s' if delay_s >= 7200 else ''}"
        elif delay_s >= 60:
            delay_label = f"{delay_s // 60} minute{'s' if delay_s >= 120 else ''}"
        else:
            delay_label = f"{delay_s} seconde{'s' if delay_s > 1 else ''}"

        def _fire_reminder():
            _time.sleep(delay_s)
            reminder_text = f"{self.user_name}, rappel : {msg}."
            # Notification système macOS (visible même si le son est coupé)
            import subprocess as _sp
            try:
                msg_safe = msg.replace('"', "'").replace("\\", "/").replace("\n", " ")
                _sp.run(
                    ["osascript", "-e",
                     f'display notification "{msg_safe}" with title "JARVIS — Rappel" sound name "default"'],
                    check=False, capture_output=True, timeout=5,
                )
            except Exception:
                pass
            try:
                self.tts.speak(reminder_text)
            except Exception:
                pass

        threading.Thread(target=_fire_reminder, daemon=True).start()
        return True, f"Rappel programmé dans {delay_label} : {msg}."

    def _handle_new_lead(self, text: str) -> Tuple[bool, Optional[str]]:
        """Détecte un nouveau lead NexaTel, sauvegarde en mémoire + génère un pitch."""
        from datetime import datetime as _dt
        import re as _re

        # Extraire l'opérateur actuel du client s'il est mentionné
        t_lower = text.lower()
        operateur = ""
        if "orange" in t_lower:
            operateur = "Orange"
        elif "voo" in t_lower:
            operateur = "VOO"
        elif "telenet" in t_lower:
            operateur = "Telenet"
        elif "proximus" in t_lower or "boutique" in t_lower:
            operateur = "Proximus boutique"
        elif "scarlet" in t_lower:
            operateur = "Scarlet"

        # Extraire un prénom si mentionné
        prenom = ""
        m = _re.search(r"\b(?:appelé|nommé|qui s'appelle|prénom|cliente?)\s+([A-ZÀ-Ü][a-zà-ü]+)", text)
        if m:
            prenom = m.group(1)

        # Sauvegarder en mémoire persistante
        date_str = _dt.now().strftime("%Y-%m-%d")
        fact = f"Nouveau lead NexaTel le {date_str}"
        if prenom:
            fact += f" — {prenom}"
        if operateur:
            fact += f" (actuellement chez {operateur})"
        if self.persistent_memory:
            self.persistent_memory.save_fact(fact)

        # Générer un pitch ciblé via LLM
        if self.llm:
            context_parts = []
            if prenom:
                context_parts.append(f"Prénom du client : {prenom}")
            if operateur:
                context_parts.append(f"Opérateur actuel : {operateur}")
            context_parts.append("Contexte : nouveau lead, première approche")

            prompt = (
                f"Contexte : {'; '.join(context_parts)}\n\n"
                f"Génère un premier message NexaTel naturel et chaleureux (3 phrases max). "
                f"Objectif : briser la glace et proposer un devis. "
                f"Terminer par une question simple et directe."
            )
            system = (
                f"Tu es {self.user_name}, consultant indépendant. "
                "Style : direct, chaleureux, professionnel. "
                "Prix fixe à vie. Installation gratuite. "
                "30-40% moins cher que la boutique officielle."
            )
            pitch = self.llm.chat_sync(prompt, system=system, max_tokens=120)
            if pitch:
                confirmation = f"Nouveau lead enregistré{' (' + prenom + ')' if prenom else ''}. Voici un premier message : {pitch}"
                return True, confirmation

        msg = f"Nouveau lead enregistré{' — ' + prenom if prenom else ''}. Que voulez-vous noter d'autre sur ce client ?"
        return True, msg

    def _handle_leads(self, text: str) -> Tuple[bool, Optional[str]]:
        """Tableau de bord leads NexaTel depuis la mémoire persistante."""
        if not self.persistent_memory:
            return True, "Mémoire persistante non disponible."

        facts = self.persistent_memory.get_facts(limit=100)

        # Catégoriser les faits NexaTel
        leads = [f for f in facts if any(k in f.lower() for k in
                 ["lead", "prospect", "client", "nouveau client", "nexatel"])]
        conversions = [f for f in facts if any(k in f.lower() for k in
                       ["signé", "converti", "gagné", "closé", "contrat"])]
        rdvs = [f for f in facts if any(k in f.lower() for k in
                ["rdv", "réunion", "rencontre", "appel", "demain", "lundi",
                 "mardi", "mercredi", "jeudi", "vendredi"])]

        parts = []

        if not leads and not conversions:
            parts.append("Aucun lead NexaTel enregistré pour l'instant.")
        else:
            if leads:
                parts.append(f"{len(leads)} lead{'s' if len(leads) > 1 else ''} dans le pipeline.")
            if conversions:
                parts.append(f"{len(conversions)} conversion{'s' if len(conversions) > 1 else ''} enregistrée{'s' if len(conversions) > 1 else ''}.")
            if rdvs:
                parts.append(f"{len(rdvs)} rendez-vous mémorisé{'s' if len(rdvs) > 1 else ''}.")

        # Dernier lead en date
        if leads:
            last_lead = leads[-1][:80]
            parts.append(f"Dernier lead : {last_lead}.")

        # Synthèse LLM si disponible
        if self.llm and (leads or conversions):
            try:
                context = "\n".join(f"• {f}" for f in leads[-5:] + conversions[-3:])
                synth = self.llm.chat_sync(
                    f"Pipeline NexaTel :\n{context}\n\nFais un bilan rapide en 2 phrases. Ton : direct, factuel.",
                    system="Assistant commercial NexaTel. Résumé du pipeline prospects. Concis.",
                    max_tokens=80,
                )
                if synth and len(synth) > 15:
                    return True, synth
            except Exception:
                pass

        return True, " ".join(parts) if parts else "Pipeline vide pour l'instant."

    def _handle_motivation(self, text: str) -> Tuple[bool, Optional[str]]:
        """Donne un boost de motivation personnalisé à Ali selon son contexte."""
        from datetime import datetime as _dt
        import random

        h = _dt.now().hour
        t_lower = text.lower()

        # Détecter le type de problème
        is_tired = any(w in t_lower for w in ["fatigué", "épuisé", "au bout"])
        is_discouraged = any(w in t_lower for w in ["nul", "découragé", "démotivé", "doute", "abandonne", "capitule"])
        is_blocked = any(w in t_lower for w in ["galère", "rame", "bloque", "compliqué", "difficile", "dur"])

        # Si LLM disponible — réponse contextuelle personnalisée
        if self.llm:
            # Faits mémorisés pour personnaliser
            facts_str = ""
            if self.persistent_memory:
                facts = self.persistent_memory.get_facts(limit=10)
                leads_count = sum(1 for f in facts if any(k in f.lower() for k in ["lead", "client", "prospect"]))
                conversions = sum(1 for f in facts if any(k in f.lower() for k in ["signé", "converti", "gagné"]))
                if leads_count or conversions:
                    facts_str = f"Ali a {leads_count} leads et {conversions} conversions en mémoire. "

            context_hint = (
                "Ali est fatigué" if is_tired else
                "Ali doute de lui-même" if is_discouraged else
                "Ali est bloqué sur quelque chose" if is_blocked else
                "Ali a besoin d'un boost"
            )

            prompt = (
                f"Situation : {context_hint}. {facts_str}"
                f"Ali a 19 ans, gère NexaTel seul depuis chez lui à Charleroi, consultant Proximus indépendant. "
                f"Sa mère est infirmière, il soutient la famille. C'est {h}h.\n\n"
                f"Donne-lui 2-3 phrases de motivation VRAIE — pas des platitudes. "
                f"Rappelle-lui un fait concret sur ce qu'il accomplit. "
                f"Termine par une question ou un appel à l'action direct."
            )
            system = (
                "Tu es JARVIS, l'assistant d'Ali. Tu le connais bien. "
                "Ta motivation est honnête, directe, sans condescendance — comme un mentor qui y croit vraiment. "
                "Pas de 'tu es fort', 'continue'. Des faits et une direction."
            )
            try:
                response = self.llm.chat_sync(prompt, system=system, max_tokens=120)
                if response and len(response) > 20:
                    return True, response
            except Exception:
                pass

        # Fallback sans LLM — phrases préfabriquées contextuelles
        _FALLBACKS = {
            "tired": [
                "La fatigue, c'est le prix du sérieux. Tu as 19 ans et tu gères une entreprise. La plupart attendent 10 ans pour te rattraper.",
                "Pause courte, puis retour. Les gens qui réussissent ne sont pas infatigables — ils savent récupérer vite.",
            ],
            "discouraged": [
                "Tu as 19 ans. Tu as fondé NexaTel. Tu as des clients. La plupart des gens de ton âge n'ont encore rien commencé.",
                "Chaque non rapproche du oui. Les meilleurs commerciaux convertissent 1 prospect sur 10. Continue.",
            ],
            "blocked": [
                "Le blocage, c'est juste le signal que tu es à la limite de ta zone de confort. C'est là que ça pousse.",
                "Découpe le problème. Quelle est la plus petite action que tu peux faire maintenant ?",
            ],
            "default": [
                "T'as commencé avec rien. T'as construit NexaTel seul. C'est déjà plus que ce que beaucoup font en 5 ans.",
                "19 ans, consultant Proximus certifié, clients réels. Qu'est-ce qui te bloque concrètement ?",
            ],
        }
        key = "tired" if is_tired else "discouraged" if is_discouraged else "blocked" if is_blocked else "default"
        return True, random.choice(_FALLBACKS[key])

    def _handle_help(self, text: str) -> Tuple[bool, Optional[str]]:
        """Liste les capacités de JARVIS de façon conversationnelle."""
        response = (
            f"Voilà ce que je peux faire, {self.user_name}. "
            "Heure et date : demande directement. "
            "Météo : 'météo à Charleroi' ou 'prévisions de la semaine'. "
            "Calcul : 'combien font 15% de 200' ou 'racine carrée de 144'. "
            "Traduction : 'traduis bonjour en anglais' ou 'comment dit-on merci en arabe'. "
            "Notes Obsidian : 'note que j'ai une réunion demain' ou 'qu'est-ce que tu sais sur Thomas'. "
            "Mémoire : 'souviens-toi que mon client préféré s'appelle Karim'. "
            "Apps Mac : 'ouvre Spotify', 'ferme Chrome', 'lance un site web'. "
            "Système : batterie, WiFi, CPU, luminosité, volume, mode sombre. "
            "Emails : 'vérifie mes mails', 'lis mes derniers emails'. "
            "Calendrier : 'qu'est-ce que j'ai prévu aujourd'hui'. "
            "Rappels : 'rappelle-moi dans 30 minutes de rappeler Karim'. "
            "NexaTel : 'aide-moi à convaincre un client Orange', 'nouveau lead NexaTel', 'mes leads du mois'. "
            "Modes : 'mode focus' pour travailler, 'mode nuit' pour dormir, 'pomodoro' pour 25 min. "
            "Brief du matin : 'donne-moi le brief du matin'. "
            "Bilan : 'résume notre session' ou 'qu'est-ce que tu sais sur moi'. "
            "Recherche web : 'cherche le prix du bitcoin', 'qui est Elon Musk', 'actualités du jour'. "
            "Et pour tout le reste : pose-moi ta question directement."
        )
        return True, response

    def list_available_commands(self) -> list:
        return list(_PATTERNS.keys())
