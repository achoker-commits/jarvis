"""
persistent_memory.py — Mémoire persistante JARVIS entre les sessions
Stocke les faits importants, préférences et résumés de sessions dans ~/.jarvis_memory.json
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_FILE = Path.home() / ".jarvis_memory.json"


class PersistentMemory:
    """Mémoire JSON persistante entre les sessions JARVIS."""

    def __init__(self, filepath: Optional[str] = None):
        self._path = Path(filepath) if filepath else MEMORY_FILE
        self._data = self._load()
        logger.info(f"Mémoire persistante chargée : {len(self._data.get('facts', []))} faits")

    def _load(self) -> dict:
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Erreur chargement mémoire persistante : {e}")
        return {"user": {}, "facts": [], "last_sessions": [], "preferences": {}}

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Erreur sauvegarde mémoire persistante : {e}")

    def _is_duplicate(self, fact: str) -> bool:
        """Retourne True si un fait très similaire existe déjà (évite les doublons)."""
        import re as _re
        def _normalize(s):
            s = s.lower().strip()
            s = _re.sub(r"[^\w\s]", " ", s)
            s = _re.sub(r"\s+", " ", s)
            return set(s.split())
        new_words = _normalize(fact)
        if len(new_words) < 3:
            return False
        for entry in self._data["facts"][-30:]:
            existing = _normalize(entry["fact"])
            if not existing:
                continue
            overlap = len(new_words & existing) / max(len(new_words | existing), 1)
            if overlap > 0.75:
                return True
        return False

    def save_fact(self, fact: str) -> None:
        if self._is_duplicate(fact):
            logger.debug(f"Fait dupliqué ignoré : {fact[:60]}")
            return
        entry = {"fact": fact, "date": datetime.now().strftime("%Y-%m-%d %H:%M")}
        self._data["facts"].append(entry)
        if len(self._data["facts"]) > 100:
            self._data["facts"] = self._data["facts"][-100:]
        self._save()
        logger.info(f"Fait mémorisé : {fact[:60]}")

    def get_facts(self, limit: int = 20) -> list:
        return [e["fact"] for e in self._data["facts"][-limit:]]

    def forget_facts_about(self, keyword: str) -> int:
        before = len(self._data["facts"])
        self._data["facts"] = [
            f for f in self._data["facts"]
            if keyword.lower() not in f["fact"].lower()
        ]
        removed = before - len(self._data["facts"])
        if removed:
            self._save()
        return removed

    def save_session_summary(self, summary: str, exchange_count: int = 0) -> None:
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "summary": summary[:200],
            "exchanges": exchange_count,
        }
        self._data["last_sessions"].append(entry)
        if len(self._data["last_sessions"]) > 15:
            self._data["last_sessions"] = self._data["last_sessions"][-15:]
        self._save()

    def get_recent_sessions(self, limit: int = 3) -> list:
        return self._data["last_sessions"][-limit:]

    def set_user_info(self, key: str, value: str) -> None:
        self._data["user"][key] = value
        self._save()

    def get_user_info(self) -> dict:
        return self._data.get("user", {})

    def get_context_for_llm(self) -> str:
        """Génère un bloc de contexte mémorisé à injecter dans le system prompt."""
        from datetime import datetime as _dt, timedelta as _td
        lines = []

        all_facts = self._data.get("facts", [])
        now = _dt.now()
        cutoff_7d = (now - _td(days=7)).strftime("%Y-%m-%d")
        cutoff_30d = (now - _td(days=30)).strftime("%Y-%m-%d")

        # Stats NexaTel en tête — donne au LLM le contexte commercial immédiat
        leads = [f for f in all_facts if any(k in f["fact"].lower() for k in
                 ["lead", "prospect", "nouveau client"])]
        conversions = [f for f in all_facts if any(k in f["fact"].lower() for k in
                       ["signé", "converti", "gagné", "closé", "contrat"])]
        if leads or conversions:
            parts = []
            if leads:
                parts.append(f"{len(leads)} lead{'s' if len(leads) > 1 else ''}")
            if conversions:
                parts.append(f"{len(conversions)} conversion{'s' if len(conversions) > 1 else ''}")
            lines.append(f"Pipeline NexaTel : {', '.join(parts)}.")

        # Faits récents (7 derniers jours) — priorité maximale
        recent_7d = [f for f in all_facts if f.get("date", "") >= cutoff_7d]
        # Faits importants plus anciens (rdv, contrats, clients)
        older_important = [f for f in all_facts
                           if f.get("date", "") < cutoff_7d and any(
                               kw in f["fact"].lower()
                               for kw in ["nexatel", "client", "réunion", "rdv", "contrat", "signé", "lead"]
                           )][-4:]

        shown = {e["fact"] for e in recent_7d}
        combined = recent_7d + [f for f in older_important if f["fact"] not in shown]

        if combined:
            lines.append("Mémorisé :")
            for entry in combined[-12:]:
                date_str = f"[{entry['date'][:10]}] " if "date" in entry else ""
                lines.append(f"• {date_str}{entry['fact']}")

        sessions = self.get_recent_sessions(3)
        if sessions:
            lines.append("Sessions récentes :")
            for s in sessions:
                lines.append(f"• {s['date'][:10]} — {s['summary']}")

        return "\n".join(lines) if lines else ""

    def auto_extract_from_exchange(self, user_text: str, jarvis_response: str, llm=None) -> None:
        """
        Extrait automatiquement les faits importants d'un échange Ali ↔ JARVIS.
        Utilise d'abord des heuristiques rapides, puis LLM si disponible.
        Tourne en arrière-plan — ne bloque jamais la boucle principale.
        """
        import threading
        threading.Thread(
            target=self._extract_worker,
            args=(user_text, jarvis_response, llm),
            daemon=True,
            name="MemExtract",
        ).start()

    def _extract_worker(self, user_text: str, jarvis_response: str, llm) -> None:
        """Worker d'extraction (thread secondaire)."""
        import re as _re

        combined = f"{user_text} {jarvis_response}"
        extracted = []

        # ── Heuristiques locales (0ms) ─────────────────────────────────────
        _FACT_TRIGGERS = [
            # Préférences personnelles
            (r"\bj[e']? (?:préfère|aime|adore|déteste|veux|souhaite)\b.{10,80}", "préférence"),
            # Intentions proches
            (r"\bje (?:vais|compte|prévois|prépare|pense)\b.{10,80}", "intention"),
            # Leads NexaTel — détection enrichie
            (r"\bnouveau (?:client|prospect|lead|contact)\b.{0,80}", "lead nexatel"),
            (r"\bclient (?:chez|avec|nommé|appelé|qui s'appelle)\b.{5,80}", "client nexatel"),
            (r"\b(?:j['']ai|j['']ai eu|j['']ai trouvé|j['']ai contacté)\s+(?:un (?:nouveau )?client|un lead|un prospect)\b.{0,80}", "lead nexatel"),
            (r"\bclient (?:Orange|VOO|Telenet|Scarlet|Proximus boutique)\b.{0,80}", "lead nexatel qualifié"),
            # Conversions / succès commerciaux
            (r"\b(?:j['']ai (?:gagné|vendu|signé|converti|closé|conclu))\b.{10,80}", "succès nexatel"),
            (r"\b(?:contrat signé|deal (?:signé|conclu)|client converti)\b.{0,60}", "conversion nexatel"),
            # Rendez-vous avec heure/jour
            (r"\b(?:rdv|réunion|rencontre|entretien|appel)\b.{0,20}\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain|après-demain|ce soir|ce matin)\b.{0,60}", "rdv"),
            (r"\bréunion\b.{0,10}\b(?:à|vers|de)\s+\d{1,2}h\b.{0,50}", "rdv"),
            # Objectifs et plans
            (r"\bmon objectif\b.{10,80}", "objectif"),
            (r"\bje (?:vise|cherche à|essaie de|veux atteindre)\b.{10,80}", "objectif"),
            # Revenus et finances
            (r"\b(?:j['']ai (?:fait|gagné|touché))\s+\d+\s*(?:€|euro|eur)\b.{0,60}", "revenu"),
            # Problèmes à retenir
            (r"\b(?:problème|bug|erreur|ça marche pas|ça ne marche pas)\b.{5,60}", "problème"),
            # Facebook / marketing
            (r"\b(?:groupe|post|commentaire|dm|message)\s+(?:facebook|fb)\b.{0,60}", "marketing fb"),
            # Budget / investissement
            (r"\b(?:j['']ai dépensé|j['']ai investi|budget|coût|ça m'a coûté)\b.{5,60}", "finance"),
            # Prospection active
            (r"\b(?:j['']ai envoyé|j['']ai posté|j['']ai écrit|j['']ai répondu)\b.{10,80}", "prospection"),
            # Devis / commande
            (r"\b(?:devis|commande|bon de commande|facture|paiement)\b.{0,60}", "commercial"),
            # Appel avec heure
            (r"\bappel\b.{0,15}\b(?:à|vers)\s+\d{1,2}h\b.{0,50}", "rdv téléphonique"),
            # Prénom client mémorisé
            (r"\b(?:mon client|le client|chez le client)\s+(?:[A-Z][a-z]{2,15})\b.{0,60}", "client nommé"),
            # Conversation client — "j'ai parlé à / avec [prénom]"
            (r"\bj['']ai (?:parlé|discuté|échangé)\s+(?:à|avec)\s+[A-Z][a-z]{2,15}\b.{0,60}", "échange client"),
            # Numéro de contact client
            (r"\b(?:son numéro|son tel|son téléphone|son contact)\b.{5,60}", "contact client"),
            # Compte rendu d'appel
            (r"\bj['']ai (?:appelé|rappelé|eu au téléphone)\s+.{5,60}", "appel client"),
            # Objectif chiffré — "je veux X clients", "j'ai besoin de X leads"
            (r"\bje veux\s+\d+\s+(?:client|lead|prospect|vente|conversion)\b.{0,60}", "objectif chiffré"),
            (r"\b(?:mon objectif|objectif du mois)\s+(?:c'est|est)\s+\d+.{0,60}", "objectif chiffré"),
            # Commission / revenu mensuel
            (r"\b(?:ma commission|mes revenus|mon revenu|mon chiffre d'affaires)\b.{5,60}", "revenu"),
            # Rendu de travail — "j'ai terminé", "j'ai fini"
            (r"\bj['']ai (?:terminé|fini|complété|réalisé)\b.{10,60}", "tâche terminée"),
            # Apprentissage ou décision prise
            (r"\bj['']ai (?:appris|décidé|choisi|compris)\b.{10,60}", "décision"),
        ]

        for pattern, category in _FACT_TRIGGERS:
            for m in _re.finditer(pattern, user_text, _re.IGNORECASE):
                fact_text = m.group(0)[:120].strip()
                if len(fact_text) > 15:
                    extracted.append(fact_text)

        # ── Extraction LLM (si disponible et peu de faits trouvés) ──────────
        if llm and len(extracted) < 2:
            try:
                prompt = (
                    f"Ali dit : \"{user_text[:300]}\"\n"
                    f"JARVIS répond : \"{jarvis_response[:200]}\"\n\n"
                    "Extrait en 1-2 faits courts et importants à mémoriser sur Ali. "
                    "Seulement s'il y a quelque chose de vraiment notable (client, objectif, préférence, décision). "
                    "Réponds en JSON : {\"facts\": [\"fait 1\", \"fait 2\"]} ou {\"facts\": []} si rien d'important."
                )
                raw = llm.chat_sync(
                    prompt,
                    system="Tu extrais des faits mémorables sur l'utilisateur. Sois concis. Format JSON uniquement.",
                    max_tokens=80,
                )
                if raw:
                    import json as _json
                    import re as _re2
                    # Chercher le JSON dans la réponse
                    m = _re2.search(r'\{[^}]+\}', raw, _re2.DOTALL)
                    if m:
                        data = _json.loads(m.group(0))
                        for f in data.get("facts", []):
                            if isinstance(f, str) and len(f) > 10:
                                extracted.append(f)
            except Exception as e:
                logger.debug(f"Extraction LLM échouée : {e}")

        # ── Sauvegarder les faits extraits ───────────────────────────────────
        for fact in extracted[:3]:   # max 3 faits par échange
            if fact and len(fact) > 10:
                self.save_fact(fact)

    def clear_all(self) -> None:
        self._data = {"user": {}, "facts": [], "last_sessions": [], "preferences": {}}
        self._save()
        logger.info("Mémoire persistante effacée")

    def stats(self) -> dict:
        return {
            "facts": len(self._data.get("facts", [])),
            "sessions": len(self._data.get("last_sessions", [])),
            "path": str(self._path),
        }
