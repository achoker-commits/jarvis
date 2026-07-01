"""
memory.py — Système de mémoire JARVIS intégré à Obsidian
Indexation du vault, recherche de notes, sauvegarde des conversations.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

_VAULT_CACHE = Path.home() / ".jarvis_vault_cache.json"

logger = logging.getLogger(__name__)

# Mots vides français — réduit le bruit dans la recherche sémantique
_FR_STOP_WORDS = frozenset({
    "le", "la", "les", "un", "une", "des", "du", "de", "en", "et", "ou",
    "est", "sont", "a", "au", "aux", "pas", "ne", "se", "sa", "son", "ses",
    "ma", "mon", "mes", "ta", "ton", "tes", "je", "tu", "il", "elle", "nous",
    "vous", "ils", "elles", "me", "te", "lui", "y", "ce", "qui", "que", "qu",
    "sur", "dans", "pour", "par", "avec", "sans", "si", "mais", "car",
    "plus", "bien", "tout", "aussi", "cette", "cet", "ces", "quel", "quelle",
    "quoi", "comment", "quand", "on", "ca", "c", "j", "d", "l", "n", "s",
    "moi", "toi", "eux", "ici", "alors", "donc", "puis", "apres", "avant",
    "tres", "peu", "trop", "assez", "encore", "toujours", "jamais", "rien",
    "avoir", "etre", "faire", "dire", "voir", "vouloir", "pouvoir", "savoir",
})

# Essaie de charger PyYAML pour le frontmatter
try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False
    logger.warning("PyYAML non disponible — frontmatter YAML non parsé")


class MemorySystem:
    """
    Système de mémoire JARVIS lié à un vault Obsidian.

    Fonctionne en mode dégradé si le vault est absent.
    """

    def __init__(self, vault_path: Optional[str] = None):
        self.vault_path: Optional[Path] = None
        self._index: list[dict] = []  # Liste de notes indexées
        self._degraded = False

        if vault_path:
            p = Path(vault_path).expanduser()
            if p.is_dir():
                self.vault_path = p
                logger.info(f"Vault Obsidian : {self.vault_path}")
                self.index_vault()
            else:
                logger.warning(
                    f"Vault Obsidian introuvable : {vault_path} — mode dégradé"
                )
                self._degraded = True
        else:
            logger.info("Pas de vault Obsidian configuré — mémoire en mode dégradé")
            self._degraded = True

    # ------------------------------------------------------------------
    # Indexation du vault
    # ------------------------------------------------------------------

    def index_vault(self, _retry: int = 0) -> None:
        """
        Indexe tous les fichiers .md du vault.

        Extrait : titre (nom de fichier), 200 premiers caractères, tags frontmatter.
        Réessaie jusqu'à 3 fois si 0 notes trouvées (race condition daemon au démarrage).
        """
        if self._degraded or not self.vault_path:
            return

        self._index = []
        try:
            md_files = list(self.vault_path.rglob("*.md"))
        except PermissionError as e:
            logger.warning(f"Permission refusée pour lire le vault Obsidian : {e}")
            logger.warning("→ Accordez 'Accès complet au disque' à python3 dans Réglages Système > Confidentialité > Accès complet au disque")
            return
        except Exception as e:
            logger.warning(f"Erreur accès vault Obsidian : {e}")
            return

        if logger.isEnabledFor(logging.DEBUG) and len(md_files) == 0:
            # Debug: vérifier si le dossier est accessible
            try:
                contents = list(self.vault_path.iterdir())
                logger.debug(f"Contenu vault (liste directe) : {[c.name for c in contents[:5]]}")
            except Exception as de:
                logger.debug(f"iterdir échoué : {de}")

        logger.info(f"Indexation de {len(md_files)} notes Obsidian...")

        # Si 0 résultats : essayer mdfind (Spotlight) — marche sans Full Disk Access
        if len(md_files) == 0:
            md_files = self._find_via_spotlight()
            if md_files:
                logger.info(f"mdfind (Spotlight) : {len(md_files)} notes trouvées")

        # Fallback 2 : cache JSON (écrit quand JARVIS tourne en mode interactif)
        if len(md_files) == 0:
            if self._load_from_cache():
                return

        # Retry si toujours 0 (race condition daemon macOS)
        if len(md_files) == 0 and _retry < 3:
            import threading
            delay = 5 * (2 ** _retry)  # 5s, 10s, 20s
            logger.info(f"0 notes trouvées — réessai dans {delay}s (tentative {_retry+1}/3)...")
            threading.Timer(delay, lambda: self.index_vault(_retry + 1)).start()
            return

        for filepath in md_files:
            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
                title = filepath.stem  # Nom sans extension
                tags = []
                preview = ""
                date_str = ""

                # Parser le frontmatter YAML
                fm, body = self._parse_frontmatter(content)
                if fm:
                    tags = fm.get("tags", [])
                    if isinstance(tags, str):
                        tags = [tags]
                    # YAML parse les années (2024) comme int → forcer str
                    tags = [str(t) for t in tags if t is not None]
                    date_str = str(fm.get("date", ""))
                    preview = body[:200].strip()
                else:
                    preview = content[:200].strip()

                self._index.append({
                    "title": title,
                    "path": str(filepath),
                    "tags": tags,
                    "preview": preview,
                    "date": date_str,
                    "full_content": content,  # Conservé pour la recherche
                })

            except Exception as e:
                logger.debug(f"Échec indexation {filepath.name} : {e}")
                continue

        logger.info(f"Vault indexé : {len(self._index)} notes")
        if self._index:
            self._save_to_cache()

    def _save_to_cache(self) -> None:
        """Sauvegarde l'index en cache JSON — utilisé par le daemon sans accès complet."""
        try:
            data = [
                {k: v for k, v in note.items()}
                for note in self._index
            ]
            with open(_VAULT_CACHE, "w", encoding="utf-8") as f:
                json.dump({"notes": data, "vault": str(self.vault_path)}, f,
                          ensure_ascii=False, separators=(",", ":"))
            logger.info(f"Cache vault sauvegardé : {len(data)} notes → {_VAULT_CACHE}")
        except Exception as e:
            logger.debug(f"Cache vault : erreur sauvegarde : {e}")

    def _load_from_cache(self) -> bool:
        """Charge l'index depuis le cache JSON (mode daemon sans Full Disk Access)."""
        if not _VAULT_CACHE.exists():
            logger.info("Cache vault absent — lancez JARVIS depuis un terminal une première fois")
            return False
        try:
            with open(_VAULT_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._index = data.get("notes", [])
            if self._index:
                logger.info(f"Cache vault chargé : {len(self._index)} notes")
                return True
        except Exception as e:
            logger.debug(f"Cache vault : erreur chargement : {e}")
        return False

    def _find_via_spotlight(self) -> list:
        """
        Utilise mdfind (Spotlight) pour trouver les .md dans le vault.
        Marche sans Full Disk Access depuis un LaunchAgent.
        """
        try:
            import subprocess
            result = subprocess.run(
                ["mdfind", "-onlyin", str(self.vault_path),
                 "kMDItemFSName == '*.md'cd"],
                capture_output=True, text=True, timeout=8,
            )
            if result.returncode == 0 and result.stdout.strip():
                paths = [Path(p) for p in result.stdout.strip().splitlines() if p.endswith(".md")]
                return paths
        except Exception as e:
            logger.debug(f"mdfind échoué : {e}")
        return []

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """
        Extrait le frontmatter YAML d'une note Obsidian.

        Retourne (frontmatter_dict, body_sans_frontmatter).
        """
        if not content.startswith("---"):
            return {}, content

        try:
            end = content.find("---", 3)
            if end == -1:
                return {}, content

            fm_str = content[3:end].strip()
            body = content[end + 3:].strip()

            if _YAML_AVAILABLE:
                fm = yaml.safe_load(fm_str) or {}
            else:
                # Parsing minimal sans PyYAML
                fm = {}
                for line in fm_str.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        fm[k.strip()] = v.strip()

            return fm if isinstance(fm, dict) else {}, body

        except Exception:
            return {}, content

    # ------------------------------------------------------------------
    # Recherche de notes pertinentes
    # ------------------------------------------------------------------

    def search_relevant_notes(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Recherche les notes les plus pertinentes pour une requête.

        Score = mots-clés signifiants (stop words filtrés) dans titre + preview + tags + body.
        Retourne top_k notes avec score > 0.
        """
        if self._degraded or not self._index:
            return []

        all_words = set(self._clean_text(query).split())
        if not all_words:
            return []

        # Filtrer les mots vides pour un meilleur signal sémantique
        effective_query = all_words - _FR_STOP_WORDS
        if not effective_query:
            effective_query = all_words  # fallback si requête = que des stop words

        scored = []
        for note in self._index:
            # Titre + preview + tags (poids fort)
            main_text = self._clean_text(
                note["title"] + " "
                + note["preview"] + " "
                + " ".join(str(t) for t in note.get("tags", []))
            )
            main_words = set(main_text.split())
            score = len(effective_query & main_words)

            # Bonus titre (×3 — le titre est très discriminant)
            title_words = set(self._clean_text(note["title"]).split())
            score += len(effective_query & title_words) * 3

            # Contenu complet — toujours cherché jusqu'à 3000 chars
            full = note.get("full_content", "")
            if full:
                full_words = set(self._clean_text(full[:3000]).split()) - _FR_STOP_WORDS
                content_hits = len(effective_query & full_words)
                # Poids plus fort si aucun match titre/preview (note avec titre peu descriptif)
                score += content_hits * (1.0 if score == 0 else 0.3)

            if score > 0:
                scored.append({
                    "title": note.get("title", ""),
                    "path": note.get("path", ""),
                    "tags": note.get("tags", []),
                    "preview": note.get("preview", ""),
                    "full_content": note.get("full_content", ""),
                    "score": score,
                })

        # Trier par score décroissant, prendre top_k
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _clean_text(self, text: str) -> str:
        """Normalise le texte pour la recherche (minuscules, sans ponctuation, sans accents)."""
        text = text.lower()
        import unicodedata as _ud
        text = _ud.normalize("NFD", text)
        text = "".join(c for c in text if _ud.category(c) != "Mn")
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def get_note_content(self, path: str) -> str:
        """Lit le contenu complet d'une note par son chemin."""
        try:
            return Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Impossible de lire {path} : {e}")
            return ""

    # ------------------------------------------------------------------
    # Briefing du matin
    # ------------------------------------------------------------------

    def get_morning_briefing(self, user_name: str = "monsieur") -> Optional[str]:
        """
        Cherche les notes mentionnant aujourd'hui ou les 7 prochains jours.

        Retourne un texte de briefing ou None si rien trouvé.
        """
        if self._degraded or not self._index:
            return None

        today = datetime.now()
        jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois_fr  = ["janvier", "février", "mars", "avril", "mai", "juin",
                    "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date_fr_str = (f"{jours_fr[today.weekday()]} {today.day} "
                       f"{mois_fr[today.month - 1]} {today.year}")

        relevant_notes = []

        # Chercher uniquement les notes qui mentionnent une date précise dans les 3 prochains jours
        for offset in range(3):
            target_date = today + timedelta(days=offset)
            date_str    = target_date.strftime("%Y-%m-%d")
            date_str_fr = target_date.strftime("%d/%m/%Y")
            day_slash   = target_date.strftime("%d/%m")

            for note in self._index:
                content_lower = note["full_content"].lower()
                # Exclure les logs de conversation
                if "jarvis-log" in note.get("tags", []):
                    continue
                if date_str in content_lower or date_str_fr in content_lower or day_slash in content_lower:
                    if note not in relevant_notes:
                        relevant_notes.append(note)

        if not relevant_notes:
            return None

        # Extraire tâches (- [ ]) ET lignes avec heure précise (ex: "à 14h", "14:00")
        task_lines = []
        time_pattern = re.compile(r'\b(\d{1,2}[h:]\d{0,2})\b')

        for note in relevant_notes[:3]:
            for line in note["full_content"].splitlines():
                stripped = line.strip()
                if len(stripped) < 6:
                    continue
                # Checkbox non cochée
                if "- [ ]" in stripped:
                    task_lines.append(("task", stripped.replace("- [ ]", "").strip()))
                # Ligne avec une heure mentionnée (ex: "RDV client à 14h30")
                elif time_pattern.search(stripped) and not stripped.startswith("#"):
                    # Éviter les lignes de date/frontmatter
                    if not re.match(r'^(date|created|updated)\s*:', stripped, re.IGNORECASE):
                        task_lines.append(("event", stripped.lstrip("- •>").strip()))

        if not task_lines:
            return None

        lines = [f"Rappel du jour, {user_name} :"]
        seen = set()
        for kind, task in task_lines[:4]:
            if task not in seen:
                seen.add(task)
                lines.append(task + ("." if not task.endswith(".") else ""))

        return " ".join(lines)

    # ------------------------------------------------------------------
    # Sauvegarde des conversations
    # ------------------------------------------------------------------

    def save_conversation(
        self,
        exchanges: list[dict],
        summary: str = "",
        tags: list[str] = None,
    ) -> Optional[str]:
        """
        Sauvegarde les échanges dans JARVIS-logs/YYYY-MM-DD.md.

        Chaque appel append au fichier du jour (ne pas écraser).
        Retourne le chemin du fichier créé/modifié.
        """
        if self._degraded or not self.vault_path:
            logger.debug("Sauvegarde conversation impossible (mode dégradé)")
            return None

        try:
            log_dir = self.vault_path / "JARVIS-logs"
            log_dir.mkdir(parents=True, exist_ok=True)

            date_str = datetime.now().strftime("%Y-%m-%d")
            filepath = log_dir / f"{date_str}.md"

            now_str = datetime.now().strftime("%H:%M:%S")
            tags_str = ", ".join(str(t) for t in (tags or []))

            # Frontmatter si fichier nouveau
            if not filepath.exists():
                header = (
                    f"---\n"
                    f"date: {date_str}\n"
                    f"type: jarvis-log\n"
                    f"tags: [{tags_str}]\n"
                    f"---\n\n"
                    f"# Journal JARVIS — {date_str}\n\n"
                )
                filepath.write_text(header, encoding="utf-8")

            # Append les échanges
            with filepath.open("a", encoding="utf-8") as f:
                f.write(f"\n## Session {now_str}\n\n")
                if summary:
                    f.write(f"**Résumé :** {summary}\n\n")
                for exchange in exchanges:
                    role = exchange.get("role", "unknown")
                    content = exchange.get("content", "")
                    icon = "🧑" if role == "user" else "🤖"
                    f.write(f"{icon} **{role.capitalize()}** : {content}\n\n")
                f.write("---\n")

            return str(filepath)

        except Exception as e:
            logger.error(f"Erreur sauvegarde conversation : {e}")
            return None

    # ------------------------------------------------------------------
    # Note rapide
    # ------------------------------------------------------------------

    def save_quick_note(
        self,
        content: str,
        title: Optional[str] = None,
    ) -> Optional[str]:
        """
        Crée une note rapide dans JARVIS-notes/.

        title optionnel — sinon timestamp utilisé.
        Retourne le chemin du fichier créé.
        """
        if self._degraded or not self.vault_path:
            logger.info(f"Note (mode dégradé) : {content}")
            return None

        try:
            notes_dir = self.vault_path / "JARVIS-notes"
            notes_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = title or f"Note_{timestamp}"
            # Nettoyer le titre pour en faire un nom de fichier valide
            safe_title = re.sub(r'[<>:"/\\|?*]', "_", safe_title)
            filepath = notes_dir / f"{safe_title}.md"

            now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            file_content = (
                f"---\n"
                f"date: {datetime.now().strftime('%Y-%m-%d')}\n"
                f"created: {now_str}\n"
                f"type: jarvis-note\n"
                f"tags: [jarvis, note-rapide]\n"
                f"---\n\n"
                f"# {safe_title}\n\n"
                f"{content}\n"
            )

            filepath.write_text(file_content, encoding="utf-8")
            logger.info(f"Note sauvegardée : {filepath}")

            # Re-indexer cette note
            self._index.append({
                "title": safe_title,
                "path": str(filepath),
                "tags": ["jarvis", "note-rapide"],
                "preview": content[:200],
                "date": datetime.now().strftime("%Y-%m-%d"),
                "full_content": file_content,
            })

            return str(filepath)

        except Exception as e:
            logger.error(f"Erreur sauvegarde note : {e}")
            return None

    # ------------------------------------------------------------------
    # Mémoire core
    # ------------------------------------------------------------------

    def save_core_memory(self, content: str) -> Optional[str]:
        """
        Ajoute une information importante à memory/core.md.

        Crée le fichier si inexistant.
        """
        if self._degraded or not self.vault_path:
            logger.info(f"Mémoire core (mode dégradé) : {content}")
            return None

        try:
            memory_dir = self.vault_path / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            core_path = memory_dir / "core.md"

            if not core_path.exists():
                core_path.write_text(
                    "---\ntype: jarvis-core-memory\ntags: [jarvis, memoire]\n---\n\n"
                    "# Mémoire Core JARVIS\n\n",
                    encoding="utf-8",
                )

            timestamp = datetime.now().strftime("%d/%m/%Y %H:%M")
            with core_path.open("a", encoding="utf-8") as f:
                f.write(f"- [{timestamp}] {content}\n")

            logger.info(f"Mémoire core mise à jour : {content[:50]}...")
            return str(core_path)

        except Exception as e:
            logger.error(f"Erreur mémoire core : {e}")
            return None

    # ------------------------------------------------------------------
    # Archivage de note
    # ------------------------------------------------------------------

    def archive_note(self, topic: str) -> bool:
        """
        Déplace une note correspondant au topic vers JARVIS-archives/.

        Retourne True si une note a été archivée.
        """
        if self._degraded or not self.vault_path:
            return False

        try:
            matches = self.search_relevant_notes(topic, top_k=1)
            if not matches:
                logger.info(f"Aucune note trouvée pour archiver : {topic}")
                return False

            note = matches[0]
            src = Path(note["path"])
            archive_dir = self.vault_path / "JARVIS-archives"
            archive_dir.mkdir(parents=True, exist_ok=True)

            dst = archive_dir / src.name
            src.rename(dst)

            # Mettre à jour l'index
            self._index = [n for n in self._index if n["path"] != note["path"]]
            logger.info(f"Note archivée : {src.name}")
            return True

        except Exception as e:
            logger.error(f"Erreur archivage : {e}")
            return False

    # ------------------------------------------------------------------
    # Recherche et lecture
    # ------------------------------------------------------------------

    def search_and_read(self, topic: str) -> str:
        """
        Cherche une note sur le topic et retourne son contenu complet.

        Retourne un message vide si rien trouvé.
        """
        matches = self.search_relevant_notes(topic, top_k=1)
        if not matches:
            return ""

        note = matches[0]
        content = self.get_note_content(note["path"])
        return f"Note '{note['title']}' :\n\n{content}"

    # ------------------------------------------------------------------
    # Infos
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Retourne des statistiques sur le vault indexé."""
        return {
            "notes_count": len(self._index),
            "vault_path": str(self.vault_path) if self.vault_path else None,
            "degraded": self._degraded,
        }

    def is_available(self) -> bool:
        """Retourne True si le système de mémoire est opérationnel."""
        return not self._degraded and self.vault_path is not None
