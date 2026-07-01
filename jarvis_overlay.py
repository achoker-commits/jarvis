"""
jarvis_overlay.py — Interface visuelle JARVIS (customtkinter)
Fenêtre dark moderne avec cercle pulsant et égaliseur animé style Iron Man.
"""

import threading
import time
import math
import queue
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import tkinter as tk
    _TK_AVAILABLE = True
except ImportError:
    tk = None
    _TK_AVAILABLE = False

# Palette JARVIS
BG       = "#06080f"
CYAN     = "#00d4ff"
CYAN_DIM = "#003d55"
GREEN    = "#00ff88"
GOLD     = "#ffaa00"
WHITE    = "#c8e8f4"
DARK     = "#0a1520"


class JarvisOverlay:
    """Overlay JARVIS animé — moderne, minimaliste, style HUD Iron Man."""

    STATE_IDLE      = "idle"
    STATE_LISTENING = "listening"
    STATE_THINKING  = "thinking"
    STATE_SPEAKING  = "speaking"

    def __init__(self, width: int = 360, height: int = 360, always_on_top: bool = True):
        # Attributs de base toujours présents (même si désactivé)
        self._enabled = False
        self._state = self.STATE_IDLE
        self._frame = 0
        self._message = ""
        self._audio_levels = [0.0] * 24
        self._cmd_queue: queue.Queue = queue.Queue()
        self._width = width
        self._height = height
        self._always_on_top = always_on_top
        self._win = None
        self._canvas = None
        self._running = False

        if not _TK_AVAILABLE or not self._check_tk_safe():
            return

        self._drag_x = 0
        self._drag_y = 0
        self._thread = threading.Thread(target=self._ui_loop, daemon=True, name="JarvisOverlay")
        self._thread.start()
        time.sleep(0.4)
        if self._running:
            self._enabled = True

    @staticmethod
    def _check_tk_safe() -> bool:
        """
        Vérifie si tkinter est compatible avec le système actuel.
        Python 3.9 sur macOS 14+ (Darwin 23+) → _tkinter appelle abort().
        """
        import sys
        import platform

        # Python 3.10+ a un tkinter recompilé compatible avec macOS récent
        if sys.version_info >= (3, 10):
            return True

        # Python 3.9 crash sur macOS 14+ (Darwin 23+)
        try:
            mac_ver = platform.mac_ver()[0]  # ex: "26.3.1" ou "15.2"
            if mac_ver:
                major = int(mac_ver.split(".")[0])
                if major >= 14:
                    logger.warning(
                        f"tkinter désactivé : Python {sys.version_info[:2]} "
                        f"incompatible avec macOS {mac_ver}"
                    )
                    return False
        except Exception:
            pass

        return True

    def _ui_loop(self):
        try:
            self._win = tk.Tk()

            self._win.title("J.A.R.V.I.S")
            self._win.configure(bg=BG)
            self._win.resizable(False, False)
            self._win.overrideredirect(True)  # Pas de barre de titre

            # Position : coin inférieur droit
            sw = self._win.winfo_screenwidth()
            sh = self._win.winfo_screenheight()
            x = sw - self._width - 24
            y = sh - self._height - 72
            self._win.geometry(f"{self._width}x{self._height}+{x}+{y}")

            if self._always_on_top:
                self._win.wm_attributes("-topmost", True)

            try:
                self._win.wm_attributes("-alpha", 0.94)
            except Exception:
                pass

            # Canvas
            self._canvas = tk.Canvas(
                self._win, width=self._width, height=self._height,
                bg=BG, highlightthickness=0,
            )
            self._canvas.pack(fill=tk.BOTH, expand=True)

            # Glisser la fenêtre avec la souris
            self._canvas.bind("<Button-1>", self._start_drag)
            self._canvas.bind("<B1-Motion>", self._do_drag)

            self._running = True
            self._tick()
            self._win.mainloop()
        except Exception as e:
            logger.warning(f"Overlay désactivé : {e}")
            self._enabled = False
        finally:
            try:
                import signal as _sig
                _sig.signal(_sig.SIGABRT, _sig.SIG_DFL)
            except (OSError, ValueError):
                pass

    def _start_drag(self, e):
        self._drag_x = e.x
        self._drag_y = e.y

    def _do_drag(self, e):
        dx = e.x - self._drag_x
        dy = e.y - self._drag_y
        x = self._win.winfo_x() + dx
        y = self._win.winfo_y() + dy
        self._win.geometry(f"+{x}+{y}")

    def _tick(self):
        if not self._running:
            return
        # Lire commandes
        while not self._cmd_queue.empty():
            try:
                cmd, val = self._cmd_queue.get_nowait()
                if cmd == "state":
                    self._state = val
                elif cmd == "msg":
                    self._message = val
                elif cmd == "levels":
                    self._audio_levels = val
            except queue.Empty:
                break

        self._draw()
        self._frame += 1
        if self._win:
            self._win.after(16, self._tick)  # ~60fps

    # ------------------------------------------------------------------ drawing

    def _draw(self):
        c = self._canvas
        if not c:
            return
        c.delete("all")
        cx, cy = self._width // 2, self._height // 2
        t = self._frame / 60.0

        self._bg_glow(c, cx, cy)

        if self._state == self.STATE_IDLE:
            self._draw_idle(c, cx, cy, t)
        elif self._state == self.STATE_LISTENING:
            self._draw_listening(c, cx, cy, t)
        elif self._state == self.STATE_THINKING:
            self._draw_thinking(c, cx, cy, t)
        elif self._state == self.STATE_SPEAKING:
            self._draw_speaking(c, cx, cy, t)

        self._draw_hud(c, cx)

    def _bg_glow(self, c, cx, cy):
        """Halo de fond subtil centré."""
        colors = {
            self.STATE_IDLE:      CYAN_DIM,
            self.STATE_LISTENING: "#004466",
            self.STATE_THINKING:  "#332200",
            self.STATE_SPEAKING:  "#003322",
        }
        col = colors.get(self._state, CYAN_DIM)
        for r in range(150, 60, -15):
            alpha = 1 - r / 150
            c.create_oval(cx - r, cy - r, cx + r, cy + r,
                          fill="", outline=col, width=1)

    def _draw_idle(self, c, cx, cy, t):
        # Arc-reactor veille — cercles concentriques lents
        for i, r in enumerate([95, 72, 50]):
            pulse = math.sin(t * 0.7 + i * 0.8)
            w = 1 + pulse * 0.5
            col = self._alpha_color(CYAN, 0.15 + 0.1 * pulse)
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=col, width=w)

        # Hexagone central statique
        self._hexagon(c, cx, cy, 28, CYAN_DIM, width=2)
        self._hexagon(c, cx, cy, 14, CYAN, width=2)

        # Texte JARVIS
        c.create_text(cx, cy + 120, text="J · A · R · V · I · S",
                      fill=CYAN_DIM, font=("Courier", 11, "bold"), anchor="center")

    def _draw_listening(self, c, cx, cy, t):
        # Cercles pulsants rapides
        for i in range(5):
            r = 40 + i * 18 + 8 * math.sin(t * 4 + i * 0.6)
            alpha = max(0, 0.8 - i * 0.15)
            c.create_oval(cx-r, cy-r, cx+r, cy+r,
                          outline=self._alpha_color(CYAN, alpha), width=2 - i * 0.3)

        # Égaliseur audio (24 barres)
        n = 24
        bw = 5
        gap = 3
        total = n * (bw + gap)
        x0 = cx - total // 2
        for i in range(n):
            lvl = self._audio_levels[i % len(self._audio_levels)]
            wave = abs(math.sin(t * 5 + i * 0.35)) * 0.5 + lvl * 0.5
            h = max(3, int(48 * wave))
            x = x0 + i * (bw + gap)
            c.create_rectangle(x, cy + 8 - h, x + bw, cy + 8 + h,
                                fill=CYAN, outline="")

        c.create_text(cx, cy + 115, text="● J'ÉCOUTE",
                      fill=CYAN, font=("Courier", 11, "bold"), anchor="center")

    def _draw_thinking(self, c, cx, cy, t):
        # Roue dentée tournante
        n = 12
        r_out, r_in = 75, 55
        for i in range(n):
            a1 = t * 1.8 + (2 * math.pi * i / n)
            a2 = a1 + math.pi / n * 0.7
            x1o, y1o = cx + r_out * math.cos(a1), cy + r_out * math.sin(a1)
            x2o, y2o = cx + r_out * math.cos(a2), cy + r_out * math.sin(a2)
            x1i, y1i = cx + r_in * math.cos(a1), cy + r_in * math.sin(a1)
            x2i, y2i = cx + r_in * math.cos(a2), cy + r_in * math.sin(a2)
            bright = (math.sin(a1 * 2 - t * 3) + 1) / 2
            col = self._lerp(CYAN_DIM, CYAN, bright)
            c.create_polygon(x1o, y1o, x2o, y2o, x2i, y2i, x1i, y1i,
                             fill=col, outline="")

        # Cercle central
        c.create_oval(cx-32, cy-32, cx+32, cy+32, fill=DARK, outline=CYAN, width=2)
        # Points tournants à l'intérieur
        for i in range(3):
            a = t * 3 + i * 2.09
            px = cx + 16 * math.cos(a)
            py = cy + 16 * math.sin(a)
            c.create_oval(px-4, py-4, px+4, py+4, fill=CYAN, outline="")

        c.create_text(cx, cy + 115, text="● TRAITEMENT",
                      fill=GOLD, font=("Courier", 11, "bold"), anchor="center")

    def _draw_speaking(self, c, cx, cy, t):
        # Ondes concentriques sortantes
        for i in range(6):
            phase = (t * 1.8 - i * 0.28) % 1.0
            r = 28 + phase * 120
            alpha = max(0, 1 - phase) * (0.9 - i * 0.1)
            if alpha > 0:
                c.create_oval(cx-r, cy-r, cx+r, cy+r,
                              outline=self._alpha_color(GREEN, alpha),
                              width=max(1, int(3 * (1 - phase))))

        # Micro central
        c.create_oval(cx-28, cy-28, cx+28, cy+28, fill=DARK, outline=GREEN, width=2)
        c.create_text(cx, cy, text="♪", fill=GREEN,
                      font=("Courier", 20, "bold"), anchor="center")

        # Mini égaliseur parole
        n = 16
        for i in range(n):
            x = cx - n * 4 + i * 8
            h = abs(math.sin(t * 6 + i * 0.5)) * 22 + 4
            c.create_rectangle(x, cy + 60 - h, x + 5, cy + 60 + h,
                                fill=GREEN, outline="")

        c.create_text(cx, cy + 115, text="● JARVIS PARLE",
                      fill=GREEN, font=("Courier", 11, "bold"), anchor="center")

    def _draw_hud(self, c, cx):
        """Ligne de statut en haut + bordure."""
        # Bordure haut
        c.create_line(20, 30, self._width - 20, 30, fill=CYAN_DIM, width=1)

        state_labels = {
            self.STATE_IDLE:      ("EN VEILLE", CYAN_DIM),
            self.STATE_LISTENING: ("ÉCOUTE ACTIVE", CYAN),
            self.STATE_THINKING:  ("TRAITEMENT", GOLD),
            self.STATE_SPEAKING:  ("PAROLE", GREEN),
        }
        label, col = state_labels.get(self._state, ("JARVIS", WHITE))
        c.create_text(cx, 18, text=f"J.A.R.V.I.S  ·  {label}",
                      fill=col, font=("Courier", 9, "bold"), anchor="center")

        # Message optionnel en bas
        if self._message:
            c.create_line(20, self._height - 32, self._width - 20, self._height - 32,
                          fill=CYAN_DIM, width=1)
            c.create_text(cx, self._height - 16, text=self._message[:44],
                          fill=CYAN_DIM, font=("Courier", 8), anchor="center")

    # ------------------------------------------------------------------ helpers

    def _hexagon(self, c, cx, cy, r, color, width=1):
        pts = []
        for i in range(6):
            a = math.pi / 6 + i * math.pi / 3
            pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
        c.create_polygon(pts, outline=color, fill="", width=width)

    def _alpha_color(self, hex_color: str, alpha: float) -> str:
        try:
            alpha = max(0, min(1, alpha))
            r = int(int(hex_color[1:3], 16) * alpha + 0x06 * (1 - alpha))
            g = int(int(hex_color[3:5], 16) * alpha + 0x08 * (1 - alpha))
            b = int(int(hex_color[5:7], 16) * alpha + 0x0f * (1 - alpha))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _lerp(self, c1: str, c2: str, t: float) -> str:
        try:
            t = max(0, min(1, t))
            r = int(int(c1[1:3], 16) + (int(c2[1:3], 16) - int(c1[1:3], 16)) * t)
            g = int(int(c1[3:5], 16) + (int(c2[3:5], 16) - int(c1[3:5], 16)) * t)
            b = int(int(c1[5:7], 16) + (int(c2[5:7], 16) - int(c1[5:7], 16)) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return c1

    # ------------------------------------------------------------------ public API

    def set_state(self, state: str, message: str = "") -> None:
        if not self._enabled:
            return
        self._cmd_queue.put(("state", state))
        self._cmd_queue.put(("msg", message))

    def set_audio_levels(self, levels: list) -> None:
        if self._enabled:
            self._cmd_queue.put(("levels", levels[:24]))

    def set_idle(self):      self.set_state(self.STATE_IDLE)
    def set_listening(self): self.set_state(self.STATE_LISTENING)
    def set_thinking(self):  self.set_state(self.STATE_THINKING)
    def set_speaking(self):  self.set_state(self.STATE_SPEAKING)

    def is_enabled(self) -> bool:
        return self._enabled

    def close(self):
        self._running = False
        if self._win:
            try:
                self._win.after(0, self._win.destroy)
            except Exception:
                pass
