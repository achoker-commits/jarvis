"""
jarvis_qt_window.py — Interface visuelle JARVIS (PyQt6)
Overlay glassmorphism premium : orbe Siri, particules, waveform, texte streamé.
Qt DOIT tourner dans le thread principal — utiliser les signaux pour communiquer.
"""

import math
import random
import sys
import subprocess

from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QSystemTrayIcon, QMenu
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QObject, pyqtSignal, QPointF, QRectF
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush,
    QRadialGradient, QLinearGradient, QConicalGradient,
    QIcon, QPixmap, QFont, QPainterPath, QFontMetrics,
    QGradient
)


# ─────────────────────────────────────────────────────────────────────────────
# Signaux thread-safe
# ─────────────────────────────────────────────────────────────────────────────

class JarvisSignals(QObject):
    state_changed  = pyqtSignal(str)
    audio_levels   = pyqtSignal(list)
    text_chunk     = pyqtSignal(str)   # chunk streamé de la réponse
    text_clear     = pyqtSignal()      # effacer le texte affiché
    quit_app       = pyqtSignal()


# ─────────────────────────────────────────────────────────────────────────────
# Utilitaires couleurs
# ─────────────────────────────────────────────────────────────────────────────

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t

def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(_lerp(a, b, t)) for a, b in zip(c1, c2))

def _hsv_to_rgb(h: float, s: float, v: float) -> tuple:
    """h in [0,360], s,v in [0,1]."""
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(h / 360, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


# ─────────────────────────────────────────────────────────────────────────────
# Particule simple
# ─────────────────────────────────────────────────────────────────────────────

class Particle:
    def __init__(self, cx: float, cy: float):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(0.3, 1.4)
        self.x   = cx + random.uniform(-20, 20)
        self.y   = cy + random.uniform(-20, 20)
        self.vx  = math.cos(angle) * speed
        self.vy  = math.sin(angle) * speed
        self.r   = random.uniform(1.5, 4.0)
        self.life = random.uniform(0.6, 1.0)
        self.decay = random.uniform(0.008, 0.018)
        self.hue = random.uniform(170, 220)  # cyan-bleu

    def update(self):
        self.x    += self.vx
        self.y    += self.vy
        self.vx   *= 0.97
        self.vy   *= 0.97
        self.life -= self.decay
        self.r    *= 0.995

    @property
    def alive(self) -> bool:
        return self.life > 0 and self.r > 0.3


# ─────────────────────────────────────────────────────────────────────────────
# Canvas d'animation principal
# ─────────────────────────────────────────────────────────────────────────────

class OrbCanvas(QWidget):

    PALETTES = {
        "idle":      [(0, 160, 255),  (30, 80, 220),  (80, 0, 200)],
        "listening": [(0, 220, 255),  (80, 100, 255), (180, 0, 255)],
        "thinking":  [(255, 160, 0),  (255, 80, 20),  (220, 0, 130)],
        "speaking":  [(0, 255, 150),  (0, 210, 255),  (0, 120, 255)],
        "error":     [(255, 60, 60),  (200, 0, 80),   (150, 0, 0)],
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state      = "idle"
        self._prev_state = "idle"
        self.frame      = 0
        self.audio_lvls = [0.0] * 32
        self._particles: list[Particle] = []
        self._transition = 1.0   # 0→1 lors d'un changement d'état
        self._spawn_counter = 0

        self.setFixedSize(480, 120)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)   # 60 fps

    def set_state(self, s: str):
        if s != self.state:
            self._prev_state = self.state
            self.state = s
            self._transition = 0.0   # démarre la transition

    def set_audio_levels(self, lvls: list):
        self.audio_lvls = (lvls + [0.0] * 32)[:32]

    def _tick(self):
        self.frame += 1
        # Avancer la transition
        if self._transition < 1.0:
            self._transition = min(1.0, self._transition + 0.04)
        # Particules
        self._spawn_counter += 1
        rate = {"idle": 8, "listening": 3, "thinking": 5, "speaking": 2}.get(self.state, 8)
        if self._spawn_counter >= rate:
            self._spawn_counter = 0
            cx, cy = self.width() // 2, self.height() // 2
            for _ in range(2 if self.state != "idle" else 1):
                p = Particle(cx, cy)
                if self.state == "thinking":
                    p.hue = random.uniform(20, 50)   # orange
                elif self.state == "speaking":
                    p.hue = random.uniform(140, 170)  # vert
                elif self.state == "error":
                    p.hue = random.uniform(0, 20)     # rouge
                self._particles.append(p)
        for pt in self._particles:
            pt.update()
        self._particles = [pt for pt in self._particles if pt.alive]
        if len(self._particles) > 150:
            self._particles = self._particles[-150:]
        self.update()

    def _interpolated_palette(self) -> list:
        pal_a = self.PALETTES.get(self._prev_state, self.PALETTES["idle"])
        pal_b = self.PALETTES.get(self.state, self.PALETTES["idle"])
        t = self._transition
        return [_lerp_color(a, b, t) for a, b in zip(pal_a, pal_b)]

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        t = self.frame / 60.0
        pal = self._interpolated_palette()

        # Particules en arrière-plan
        self._draw_particles(p)

        if self.state == "idle":
            self._draw_idle(p, cx, cy, t, pal)
        elif self.state == "listening":
            self._draw_listening(p, cx, cy, t, pal)
        elif self.state == "thinking":
            self._draw_thinking(p, cx, cy, t, pal)
        elif self.state == "speaking":
            self._draw_speaking(p, cx, cy, t, pal)
        else:
            self._draw_idle(p, cx, cy, t, pal)

    # ── animations ──────────────────────────────────────────────────────────

    def _draw_idle(self, p, cx, cy, t, pal):
        """Orbe centrale respirant doucement."""
        pulse = (math.sin(t * 0.9) + 1) / 2          # 0→1 lent
        outer_r = 28 + 6 * pulse
        inner_r = 14 + 3 * pulse
        # Halo externe
        self._radial(p, cx, cy, outer_r * 2.5, pal[0], int(35 + 20 * pulse))
        # Orbe principale
        self._radial(p, cx, cy, outer_r, pal[0], int(160 + 60 * pulse))
        # Cœur lumineux
        self._radial(p, cx, cy, inner_r, (220, 240, 255), int(200 + 55 * pulse))

        # Anneau fin
        pen = QPen(QColor(*pal[0], int(60 + 40 * pulse)), 1)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(int(cx - outer_r * 1.6), int(cy - outer_r * 1.6),
                      int(outer_r * 3.2), int(outer_r * 3.2))

    def _draw_listening(self, p, cx, cy, t, pal):
        """3 orbes Siri qui dansent + anneaux d'expansion."""
        # Anneaux d'expansion centrés
        for ring in range(3):
            phase_r = (t * 0.8 + ring * 0.5) % 1.0
            ring_r = 15 + phase_r * 65
            alpha_r = int(120 * (1 - phase_r))
            pen = QPen(QColor(*pal[0], alpha_r), 1.5)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(int(cx - ring_r), int(cy - ring_r),
                          int(ring_r * 2), int(ring_r * 2))

        # 3 orbes dansantes
        for i in range(3):
            phase = t * 2.5 + i * 2.094
            ox = cx + math.sin(phase) * 85 * (0.7 + 0.3 * math.cos(t * 1.5 + i))
            oy = cy + math.cos(phase * 0.7) * 30 * (0.6 + 0.4 * math.sin(t * 1.2 + i))
            r  = 36 + 12 * math.sin(t * 3.0 + i * 1.3)
            a  = int(180 + 60 * math.sin(t * 2.0 + i))
            self._radial(p, ox, oy, r, pal[i], a)
            # Halo
            self._radial(p, ox, oy, r * 1.8, pal[i], a // 4)

    def _draw_thinking(self, p, cx, cy, t, pal):
        """Anneau de points rotatif + orbe pulsante centrale."""
        n = 10
        for i in range(n):
            angle = t * 2.2 + i * (2 * math.pi / n)
            rx = 52 + 6 * math.sin(t * 3.5 + i * 0.8)
            ry = 26 + 4 * math.cos(t * 2.8 + i * 0.6)
            ox = cx + math.cos(angle) * rx
            oy = cy + math.sin(angle) * ry
            # Taille variable selon la position dans l'anneau
            dot_r = 5 + 4 * abs(math.sin(t * 4 + i * 0.7))
            phase_i = i / n
            alpha = int(100 + 155 * abs(math.sin(math.pi * phase_i + t * 2)))
            col_idx = i % len(pal)
            self._radial(p, ox, oy, dot_r, pal[col_idx], alpha)

        # Orbe centrale pulsante
        pulse = (math.sin(t * 4.5) + 1) / 2
        self._radial(p, cx, cy, 16 + 6 * pulse, pal[1], int(200 + 55 * pulse))
        self._radial(p, cx, cy, 8 + 3 * pulse, (255, 220, 100), int(230 + 25 * pulse))

        # Trait de connexion rotatif (arc partiel)
        pen = QPen(QColor(*pal[0], 60), 2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        start_angle = int((t * 120) % 360) * 16
        p.drawArc(int(cx - 52), int(cy - 26), 104, 52, start_angle, 200 * 16)

    def _draw_speaking(self, p, cx, cy, t, pal):
        """Waveform sinusoïdale premium — barres arrondies avec gradient."""
        n   = 32
        bw  = 8
        gap = 4
        total_w = n * (bw + gap) - gap
        x0  = cx - total_w // 2

        for i in range(n):
            # Combinaison audio réel + sinus pour un rendu naturel
            audio = self.audio_lvls[i] if i < len(self.audio_lvls) else 0.0
            sine1 = abs(math.sin(t * 5.5 + i * 0.38))
            sine2 = abs(math.sin(t * 3.2 + i * 0.55 + 1.2))
            wave  = 0.5 * sine1 + 0.3 * sine2 + 0.2 * audio

            # Enveloppe en cloche (plus haute au centre)
            env   = math.exp(-((i - n / 2) ** 2) / (2 * (n / 3.5) ** 2))
            bh    = max(4, int(46 * wave * env))

            x = x0 + i * (bw + gap)

            # Couleur dégradée selon position
            t_color = i / (n - 1)
            col = _lerp_color(pal[0], pal[2], t_color)

            # Gradient vertical sur chaque barre
            grad = QLinearGradient(x, cy - bh, x, cy + bh)
            grad.setColorAt(0.0, QColor(*col, 255))
            grad.setColorAt(0.4, QColor(*col, 220))
            grad.setColorAt(0.5, QColor(*_lerp_color(col, (255, 255, 255), 0.3), 255))
            grad.setColorAt(0.6, QColor(*col, 220))
            grad.setColorAt(1.0, QColor(*col, 255))

            path = QPainterPath()
            path.addRoundedRect(x, cy - bh, bw, bh * 2, bw // 2, bw // 2)
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPath(path)

            # Reflet lumineux sur le dessus de chaque barre
            glow = QLinearGradient(x, cy - bh, x, cy - bh + 6)
            glow.setColorAt(0, QColor(255, 255, 255, 80))
            glow.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(x, cy - bh, bw, 6, 3, 3)

    # ── particules ──────────────────────────────────────────────────────────

    def _draw_particles(self, p):
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._particles:
            alpha = int(200 * pt.life)
            r, g, b = _hsv_to_rgb(pt.hue, 0.7, 1.0)
            p.setBrush(QBrush(QColor(r, g, b, alpha)))
            p.drawEllipse(QRectF(pt.x - pt.r, pt.y - pt.r, pt.r * 2, pt.r * 2))

    # ── utilitaire ──────────────────────────────────────────────────────────

    def _radial(self, p, x, y, r, rgb, alpha):
        grad = QRadialGradient(x, y, r)
        grad.setColorAt(0,   QColor(*rgb, min(255, alpha)))
        grad.setColorAt(0.45, QColor(*rgb, min(255, alpha * 2 // 3)))
        grad.setColorAt(1,   QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(x - r, y - r, r * 2, r * 2))


# ─────────────────────────────────────────────────────────────────────────────
# Barre de texte streamé
# ─────────────────────────────────────────────────────────────────────────────

class TextStreamer(QWidget):
    """Affiche le texte de réponse JARVIS au fil du streaming avec effet curseur."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text   = ""
        self._cursor_visible = True
        self._frame  = 0
        self.setFixedHeight(38)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._cur_timer = QTimer(self)
        self._cur_timer.timeout.connect(self._blink)
        self._cur_timer.start(500)

    def append(self, chunk: str):
        self._text += chunk
        # Garder seulement les 160 derniers caractères (scroll invisible)
        if len(self._text) > 160:
            self._text = "…" + self._text[-158:]
        self.update()

    def clear(self):
        self._text = ""
        self.update()

    def _blink(self):
        self._cursor_visible = not self._cursor_visible
        self.update()

    def paintEvent(self, _):
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        # Fond légèrement teinté
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 8, 8)
        p.fillPath(path, QColor(0, 180, 255, 12))

        # Texte
        font = QFont("SF Pro Display", 11)
        if not font.exactMatch():
            font = QFont("Helvetica Neue", 11)
        font.setWeight(QFont.Weight.Light)
        p.setFont(font)

        display = self._text + ("▌" if self._cursor_visible else " ")
        p.setPen(QColor(200, 230, 255, 230))
        p.drawText(QRectF(12, 0, self.width() - 24, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   display)
        p.end()


# ─────────────────────────────────────────────────────────────────────────────
# Fenêtre principale
# ─────────────────────────────────────────────────────────────────────────────

class JarvisOverlayQt(QWidget):

    _LABEL_TEXT = {
        "idle":      "J · A · R · V · I · S",
        "listening": "●  J'ÉCOUTE",
        "thinking":  "◌  TRAITEMENT",
        "speaking":  "◉  JARVIS PARLE",
        "error":     "⚠  ERREUR",
    }
    _LABEL_COLOR = {
        "idle":      "rgba(100, 180, 255, 160)",
        "listening": "rgba(0, 220, 255, 255)",
        "thinking":  "rgba(255, 160, 0, 255)",
        "speaking":  "rgba(0, 255, 150, 255)",
        "error":     "rgba(255, 80, 80, 255)",
    }
    _BORDER_COLOR = {
        "idle":      (0, 120, 220, 40),
        "listening": (0, 200, 255, 80),
        "thinking":  (255, 140, 0, 70),
        "speaking":  (0, 255, 140, 70),
        "error":     (255, 60, 60, 80),
    }

    def __init__(self, signals: JarvisSignals):
        super().__init__()
        self._signals  = signals
        self._state    = "idle"
        self._enabled  = True
        self._anim_ref = None
        self._border_anim_t = 0.0

        self._build_window()
        self._build_ui()
        self._build_tray()
        self._connect_signals()

        # Timer pour l'animation de la bordure
        self._border_timer = QTimer(self)
        self._border_timer.timeout.connect(self._tick_border)
        self._border_timer.start(32)   # ~30 fps pour la bordure

        self.setWindowOpacity(0.0)
        self.hide()

    # ── construction ─────────────────────────────────────────────────────────

    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        screen = QApplication.primaryScreen().geometry()
        w, h = 520, 200
        x = (screen.width() - w) // 2
        y = screen.height() - h - 100
        self.setGeometry(x, y, w, h)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(6)

        self.canvas = OrbCanvas(self)
        layout.addWidget(self.canvas, alignment=Qt.AlignmentFlag.AlignCenter)

        self.label = QLabel("J · A · R · V · I · S")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_label_style("idle")
        layout.addWidget(self.label)

        self.text_strip = TextStreamer(self)
        layout.addWidget(self.text_strip)

    def _build_tray(self):
        px = QPixmap(24, 24)
        px.fill(QColor(0, 0, 0, 0))
        pt = QPainter(px)
        pt.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QRadialGradient(12, 12, 11)
        g.setColorAt(0, QColor(0, 230, 255, 255))
        g.setColorAt(0.6, QColor(0, 140, 255, 220))
        g.setColorAt(1, QColor(0, 60, 160, 180))
        pt.setBrush(QBrush(g))
        pt.setPen(Qt.PenStyle.NoPen)
        pt.drawEllipse(1, 1, 22, 22)
        pt.end()

        self._tray = QSystemTrayIcon(QIcon(px), self)
        self._tray_menu = QMenu()

        # Titre et état (non-clickable)
        self._tray_state_action = self._tray_menu.addAction("JARVIS — En veille")
        self._tray_state_action.setEnabled(False)
        self._tray_menu.addSeparator()

        # Toggle affichage overlay
        self._tray_toggle_action = self._tray_menu.addAction("Afficher l'overlay")
        self._tray_toggle_action.triggered.connect(self._tray_toggle_overlay)

        self._tray_menu.addSeparator()

        # Ouvrir le log
        log_action = self._tray_menu.addAction("Ouvrir le log JARVIS")
        log_action.triggered.connect(self._tray_open_log)

        self._tray_menu.addSeparator()
        self._tray_menu.addAction("Quitter JARVIS", QApplication.quit)

        self._tray.setContextMenu(self._tray_menu)
        self._tray.setToolTip("JARVIS — Assistant IA vocal")
        self._tray.activated.connect(self._tray_clicked)
        self._tray.show()

    def _tray_toggle_overlay(self):
        if self.isVisible():
            self.hide()
            self._tray_toggle_action.setText("Afficher l'overlay")
        else:
            self.show()
            self._tray_toggle_action.setText("Masquer l'overlay")

    def _tray_open_log(self):
        import subprocess, pathlib
        log = pathlib.Path(__file__).parent / "jarvis.log"
        if log.exists():
            subprocess.Popen(["open", str(log)])

    def _tray_clicked(self, reason):
        """Clic sur l'icône tray → basculer l'overlay."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_toggle_overlay()

    def _update_tray_state(self, state: str):
        labels = {
            "idle":      "JARVIS — En veille",
            "listening": "JARVIS — À l'écoute...",
            "thinking":  "JARVIS — Réflexion...",
            "speaking":  "JARVIS — Parle...",
            "error":     "JARVIS — Erreur",
        }
        self._tray_state_action.setText(labels.get(state, "JARVIS — Actif"))

    def _connect_signals(self):
        self._signals.state_changed.connect(self._on_state)
        self._signals.audio_levels.connect(self._on_levels)
        self._signals.text_chunk.connect(self._on_text_chunk)
        self._signals.text_clear.connect(self._on_text_clear)
        self._signals.quit_app.connect(QApplication.quit)

    # ── slots ────────────────────────────────────────────────────────────────

    def _on_state(self, state: str):
        self._state = state.lower()
        self.canvas.set_state(self._state)
        self.label.setText(self._LABEL_TEXT.get(self._state, "J · A · R · V · I · S"))
        self._apply_label_style(self._state)
        self.update()
        self._update_tray_state(self._state)

        if self._state in ("listening", "thinking", "speaking", "error"):
            self._fade_in()
            self._tray_toggle_action.setText("Masquer l'overlay")
        else:
            QTimer.singleShot(2200, self._fade_out)

    def _on_levels(self, lvls: list):
        self.canvas.set_audio_levels(lvls)

    def _on_text_chunk(self, chunk: str):
        self.text_strip.append(chunk)

    def _on_text_clear(self):
        self.text_strip.clear()

    # ── timer bordure ────────────────────────────────────────────────────────

    def _tick_border(self):
        self._border_anim_t += 0.03
        self.update()

    # ── animations ───────────────────────────────────────────────────────────

    def _fade_in(self):
        self.show()
        self.raise_()
        if self.windowOpacity() > 0.88:
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(280)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.97)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._anim_ref = anim

    def _fade_out(self):
        if self._state != "idle":
            return
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(600)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(self.hide)
        anim.start()
        self._anim_ref = anim

    # ── dessin fenêtre ───────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 28, 28)

        # Fond glassmorphism profond
        p.setClipPath(path)

        # Gradient de fond diagonal subtil
        bg_grad = QLinearGradient(0, 0, w, h)
        bg_grad.setColorAt(0.0, QColor(4,  10, 28, 240))
        bg_grad.setColorAt(0.5, QColor(6,  12, 32, 240))
        bg_grad.setColorAt(1.0, QColor(4,   8, 24, 240))
        p.fillPath(path, QBrush(bg_grad))

        # Lueur colorée de fond (selon l'état)
        bc = self._BORDER_COLOR.get(self._state, (0, 120, 220, 40))
        glow_pulse = (math.sin(self._border_anim_t * 1.5) + 1) / 2
        glow_alpha = int(bc[3] * (0.6 + 0.4 * glow_pulse))
        glow = QRadialGradient(w // 2, h // 2, max(w, h) // 2)
        glow.setColorAt(0,   QColor(bc[0], bc[1], bc[2], glow_alpha // 2))
        glow.setColorAt(0.5, QColor(bc[0], bc[1], bc[2], glow_alpha // 4))
        glow.setColorAt(1,   QColor(0, 0, 0, 0))
        p.fillPath(path, QBrush(glow))

        p.setClipping(False)

        # Bordure lumineuse animée (arc qui tourne en thinking)
        if self._state == "thinking":
            arc_pen = QPen(QColor(bc[0], bc[1], bc[2], 120), 1.5)
            p.setPen(arc_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            angle_start = int((self._border_anim_t * 60) % 360) * 16
            p.drawArc(1, 1, w - 2, h - 2, angle_start, 120 * 16)
            # Arc opposé
            p.drawArc(1, 1, w - 2, h - 2, angle_start + 180 * 16, 80 * 16)
        else:
            # Bordure fixe subtile
            pulse = int(40 + 30 * (math.sin(self._border_anim_t * 0.8) + 1) / 2)
            p.setPen(QPen(QColor(bc[0], bc[1], bc[2], pulse), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # Ligne de séparation après l'orbe
        sep_y = 140
        sep_grad = QLinearGradient(20, sep_y, w - 20, sep_y)
        sep_col = QColor(bc[0], bc[1], bc[2], 30)
        sep_grad.setColorAt(0,   QColor(0, 0, 0, 0))
        sep_grad.setColorAt(0.5, sep_col)
        sep_grad.setColorAt(1,   QColor(0, 0, 0, 0))
        p.setPen(QPen(QBrush(sep_grad), 1))
        p.drawLine(20, sep_y, w - 20, sep_y)

    # ── drag ────────────────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        self._drag_origin = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if hasattr(self, "_drag_origin"):
            delta = e.globalPosition().toPoint() - self._drag_origin
            self.move(self.pos() + delta)
            self._drag_origin = e.globalPosition().toPoint()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _apply_label_style(self, state: str):
        col = self._LABEL_COLOR.get(state, "rgba(100, 180, 255, 160)")
        self.label.setStyleSheet(
            f"color: {col}; "
            f"font-family: 'SF Pro Display', 'Helvetica Neue', 'Courier New', monospace; "
            f"font-size: 10px; font-weight: 500; letter-spacing: 4px; "
            f"text-transform: uppercase;"
        )

    # ── API publique ──────────────────────────────────────────────────────────

    def set_state(self, state: str, message: str = ""):
        self._signals.state_changed.emit(state.lower())

    def set_audio_levels(self, levels: list):
        self._signals.audio_levels.emit(levels)

    def push_text(self, chunk: str):
        self._signals.text_chunk.emit(chunk)

    def clear_text(self):
        self._signals.text_clear.emit()

    def set_idle(self):
        self.clear_text()
        self.set_state("idle")

    def set_listening(self):
        self.clear_text()
        self.set_state("listening")

    def set_thinking(self):
        self.set_state("thinking")

    def set_speaking(self):
        self.set_state("speaking")

    def is_enabled(self) -> bool:
        return self._enabled

    def close_window(self):
        self._signals.quit_app.emit()


# ─────────────────────────────────────────────────────────────────────────────
# Permission microphone macOS
# ─────────────────────────────────────────────────────────────────────────────

def check_microphone_permission() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import sounddevice as sd; sd.query_devices(); print('ok')"],
            capture_output=True, text=True, timeout=5
        )
        return "ok" in result.stdout
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

def create_qt_app() -> tuple:
    """Crée QApplication + JarvisOverlayQt + JarvisSignals. Retourne (app, overlay, signals)."""
    app     = QApplication.instance() or QApplication(sys.argv)
    signals = JarvisSignals()
    overlay = JarvisOverlayQt(signals)
    return app, overlay, signals
