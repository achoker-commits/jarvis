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
        self._extract_turn_counter: int = 0  # limite appels LLM : 1 sur 3
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

    def forget_last_facts(self, n: int = 3) -> int:
        """Supprime les n derniers faits mémorisés (commande vocale 'oublie ça')."""
        removed = min(n, len(self._data["facts"]))
        if removed:
            self._data["facts"] = self._data["facts"][:-removed]
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
        """Worker d'extraction (thread secondaire). Critères stricts : faits durables uniquement."""
        import re as _re

        # ── Exclusions : états transitoires ou problèmes techniques ──────────
        _EXCLUSION_RE = _re.compile(
            r"(?:je pense qu['']il y a|il faut que|il y a un souci|"
            r"ça fait des|ça grésille|ça bug|ça marche pas|"
            r"je suis en train|je vais vérifier|j['']essaie|"
            r"tu m['']entends|tu entends|grésillement|feedback|"
            r"problème audio|problème micro|erreur|bug jarvis|"
            r"on règle|c['']est réglé|c['']est corrigé|ça devrait|"
            r"test|testing|un deux trois)",
            _re.IGNORECASE,
        )
        if _EXCLUSION_RE.search(user_text):
            return  # échange technique → rien à mémoriser

        extracted = []

        # ── Heuristiques — UNIQUEMENT faits durables et explicites ──────────
        _FACT_TRIGGERS = [
            # Préférences durables
            (r"\bj[e']? (?:préfère|aime|adore|déteste)\b.{10,60}", "préférence"),
            # Leads NexaTel (faits commerciaux concrets)
            (r"\bnouveau (?:client|prospect|lead|contact)\b.{0,60}", "lead nexatel"),
            (r"\bclient (?:chez|nommé|appelé|qui s'appelle)\b.{5,60}", "client nexatel"),
            (r"\b(?:j['']ai (?:trouvé|contacté|eu))\s+(?:un (?:nouveau )?client|un lead|un prospect)\b.{0,60}", "lead nexatel"),
            (r"\bclient (?:Orange|VOO|Telenet|Scarlet|Proximus boutique)\b.{0,60}", "lead qualifié"),
            # Conversions / succès commerciaux
            (r"\b(?:contrat signé|deal (?:signé|conclu)|client converti|j['']ai signé)\b.{0,60}", "conversion"),
            (r"\bj['']ai (?:vendu|closé|conclu)\b.{10,60}", "vente"),
            # Rendez-vous avec jour ET heure (les deux requis → plus strict)
            (r"\b(?:rdv|réunion|entretien)\b.{0,20}\b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|demain)\b.{0,20}\b(?:à|vers)\s*\d{1,2}h\b.{0,40}", "rdv"),
            # Revenus chiffrés
            (r"\bj['']ai (?:fait|gagné|touché)\s+\d+\s*(?:€|euro|eur)\b.{0,40}", "revenu"),
            # Objectifs chiffrés
            (r"\bje veux\s+\d+\s+(?:client|lead|prospect|vente)\b.{0,40}", "objectif chiffré"),
            (r"\b(?:mon objectif|objectif du mois)\s+(?:c'est|est)\s+\d+.{0,40}", "objectif chiffré"),
            # Prénom client mémorisé explicitement
            (r"\b(?:mon client|le client)\s+[A-Z][a-z]{2,15}\b.{0,40}", "client nommé"),
            # Décisions claires
            (r"\bj['']ai (?:décidé|choisi)\b.{10,60}", "décision"),
        ]

        for pattern, _ in _FACT_TRIGGERS:
            for m in _re.finditer(pattern, user_text, _re.IGNORECASE):
                fact_text = m.group(0)[:100].strip()
                if len(fact_text) > 15:
                    extracted.append(fact_text)
                    break  # 1 match par pattern max

        # ── Extraction LLM — seulement 1 tour sur 3 (réduit les 429) ────────
        self._extract_turn_counter += 1
        use_llm = llm and not extracted and (self._extract_turn_counter % 3 == 0)
        if use_llm:
            try:
                prompt = (
                    f"Ali dit : \"{user_text[:250]}\"\n\n"
                    "Y a-t-il UN fait DURABLE à mémoriser ? (client, préférence, décision, objectif chiffré, RDV confirmé). "
                    "PAS les états transitoires, problèmes techniques, ni les conversations banales. "
                    "Réponds JSON : {\"fact\": \"fait concis\"} ou {\"fact\": null} si rien."
                )
                raw = llm.chat_sync(
                    prompt,
                    system="Extraction mémoire. JSON uniquement. Très sélectif.",
                    max_tokens=60,
                )
                if raw:
                    import json as _json
                    import re as _re2
                    m = _re2.search(r'\{.*?\}', raw, _re2.DOTALL)
                    if m:
                        data = _json.loads(m.group(0))
                        f = data.get("fact")
                        if f and isinstance(f, str) and len(f) > 10:
                            extracted.append(f)
            except Exception as e:
                logger.debug(f"Extraction LLM échouée : {e}")

        # ── Sauvegarder — max 1 fait par échange ─────────────────────────────
        if extracted:
            self.save_fact(extracted[0])

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
