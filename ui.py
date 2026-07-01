"""
ui.py — Interface utilisateur Rich pour JARVIS
Affichage des états, transcriptions et réponses dans le terminal.
"""

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.style import Style


# Couleurs par état
STATE_STYLES = {
    "IDLE":      ("white",   "⬤ En veille"),
    "LISTENING": ("blue",    "⬤ Écoute en cours"),
    "THINKING":  ("yellow",  "⬤ Traitement"),
    "SPEAKING":  ("green",   "⬤ Parole"),
    "ERROR":     ("red",     "⬤ Erreur"),
}


class JarvisUI:
    """Interface Rich pour JARVIS — affichage clair et lisible en terminal."""

    def __init__(self):
        self.console = Console()
        self._current_state = "IDLE"
        self._last_user_text: str = ""
        self._response_buffer: str = ""

    # ------------------------------------------------------------------
    # Bannière de démarrage
    # ------------------------------------------------------------------

    def show_banner(self) -> None:
        """Affiche la bannière ASCII JARVIS avec les informations système."""
        self.console.print()
        self.console.print(
            Text(
                r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
""",
                style="bold cyan",
            )
        )
        self.console.print(
            Panel(
                Text.assemble(
                    ("  Just A Rather Very Intelligent System\n", "italic cyan"),
                    ("  Propulsé par Groq Llama 3.3 · Whisper · Edge TTS\n", "dim"),
                    (f"  Démarrage : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", "dim"),
                ),
                border_style="cyan",
                title="[bold cyan]JARVIS v3.0[/bold cyan]",
                title_align="center",
            )
        )
        self.console.print()

    def show_startup_status(self, components: dict) -> None:
        """
        Affiche le statut de chaque composant au démarrage.
        components = {"Whisper": True, "ElevenLabs": False, ...}
        """
        lines = []
        for name, ok in components.items():
            icon = "[green]✓[/green]" if ok else "[red]✗[/red]"
            lines.append(f"  {icon} {name}")

        self.console.print(
            Panel(
                "\n".join(lines),
                title="[bold]Statut des composants[/bold]",
                border_style="dim",
            )
        )
        self.console.print()

    # ------------------------------------------------------------------
    # Gestion des états
    # ------------------------------------------------------------------

    def set_status(self, state: str, message: str = "") -> None:
        """
        Change l'état affiché dans le terminal.
        state: IDLE | LISTENING | THINKING | SPEAKING | ERROR
        """
        self._current_state = state
        color, icon = STATE_STYLES.get(state, ("white", "⬤"))
        label = message or icon

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.print(
            f"[dim]{timestamp}[/dim]  [{color}]{icon}[/{color}]  [bold]{label}[/bold]"
        )

    # ------------------------------------------------------------------
    # Affichage des messages
    # ------------------------------------------------------------------

    def show_user_input(self, text: str) -> None:
        """Affiche ce que l'utilisateur a dit, dans un panel bleu."""
        self._last_user_text = text
        self.console.print()
        self.console.print(
            Panel(
                Text(text, style="bold white"),
                title="[bold blue]Vous[/bold blue]",
                border_style="blue",
            )
        )

    def stream_response(self, chunk: str) -> None:
        """
        Affiche un chunk de réponse JARVIS au fil du streaming.
        Accumule dans le buffer et affiche progressivement.
        """
        self._response_buffer += chunk
        # Affichage inline sans retour à la ligne
        self.console.print(chunk, end="", style="green", highlight=False)

    def finalize_response(self) -> None:
        """
        Finalise l'affichage de la réponse après le streaming.
        Entoure la réponse accumulée dans un panel vert.
        """
        if self._response_buffer:
            self.console.print()  # Retour à la ligne après le streaming inline
            self.console.print(
                Panel(
                    Text(self._response_buffer, style="green"),
                    title="[bold green]JARVIS[/bold green]",
                    border_style="green",
                )
            )
            self._response_buffer = ""
        self.console.print()

    def show_response(self, text: str) -> None:
        """Affiche une réponse JARVIS complète (non streamée)."""
        self.console.print()
        self.console.print(
            Panel(
                Text(text, style="green"),
                title="[bold green]JARVIS[/bold green]",
                border_style="green",
            )
        )
        self.console.print()

    def show_notes(self, notes: list) -> None:
        """
        Affiche les notes Obsidian actives utilisées pour le contexte.
        notes: list de dict avec 'title' et 'score'
        """
        if not notes:
            return

        lines = []
        for note in notes:
            title = note.get("title", "Sans titre")
            score = note.get("score", 0)
            lines.append(f"  [dim]•[/dim] {title}  [dim](pertinence: {score})[/dim]")

        self.console.print(
            Panel(
                "\n".join(lines),
                title="[bold magenta]Notes Obsidian actives[/bold magenta]",
                border_style="magenta",
            )
        )

    # ------------------------------------------------------------------
    # Logs
    # ------------------------------------------------------------------

    def log_info(self, message: str) -> None:
        """Log informatif (cyan)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.print(f"[dim]{timestamp}[/dim]  [cyan]ℹ[/cyan]  {message}")

    def log_warning(self, message: str) -> None:
        """Log avertissement (jaune)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.print(f"[dim]{timestamp}[/dim]  [yellow]⚠[/yellow]  {message}")

    def log_error(self, message: str) -> None:
        """Log erreur (rouge)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.print(f"[dim]{timestamp}[/dim]  [red]✗[/red]  [red]{message}[/red]")

    def log_success(self, message: str) -> None:
        """Log succès (vert)."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.print(f"[dim]{timestamp}[/dim]  [green]✓[/green]  {message}")

    def print_separator(self) -> None:
        """Ligne de séparation visuelle."""
        self.console.print(Rule(style="dim"))

    def print_wake_prompt(self, strategy: str = "keyboard") -> None:
        """Affiche l'invite d'attente selon la stratégie de wake word."""
        if strategy in ("keyboard", ""):
            self.console.print(
                "\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
                "  [bold white]Appuyez sur  [bold cyan]ENTRÉE[/bold cyan]  pour parler[/bold white]\n"
                "[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
            )
        elif strategy in ("whisper_kw",):
            self.console.print(
                "\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
                "  [bold white]Dites  [bold cyan]« JARVIS »[/bold cyan]  pour parler[/bold white]\n"
                "[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
            )
        elif strategy in ("oww", "openwakeword", "porcupine"):
            self.console.print(
                "\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
                "  [bold white]Dites  [bold cyan]« HEY JARVIS »[/bold cyan]  pour parler[/bold white]\n"
                "[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
            )
        else:
            self.console.print(
                "\n[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
                f"  [bold white]En attente  [dim]({strategy})[/dim][/bold white]\n"
                "[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]\n"
            )
