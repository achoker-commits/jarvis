"""
test_qt_visual.py — Démo visuelle de toutes les animations JARVIS
Lance toutes les transitions d'état en séquence pour valider les animations.
Usage : python3 test_qt_visual.py
"""

import sys
import threading
import time

from PyQt6.QtWidgets import QApplication
from jarvis_qt_window import create_qt_app


def _demo_thread(overlay):
    """Tourne dans un thread secondaire, anime l'overlay en séquence."""
    time.sleep(0.8)

    steps = [
        ("idle",      "JARVIS en veille — respiration douce",              3.0),
        ("listening", "À l'écoute — orbes Siri dansants",                  3.0),
        ("thinking",  "Réflexion — anneau tournant + particules",           3.0),
        ("speaking",  "Parole — waveform 32 barres + texte streamé",       1.0),
    ]

    # Texte de démo streamé pendant l'état speaking
    demo_text = (
        "Bonjour Ali, je suis JARVIS, votre assistant personnel. "
        "Mes animations glassmorphism sont maintenant opérationnelles. "
        "Je peux afficher du texte en temps réel pendant que je parle."
    )

    for state, label, duration in steps:
        print(f"\n▶  État : {state.upper()} — {label}")
        getattr(overlay, f"set_{state}")()

        if state == "speaking":
            # Simuler le streaming chunk par chunk
            words = demo_text.split()
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                overlay.push_text(chunk)
                time.sleep(0.07)
            time.sleep(2.0)
        else:
            time.sleep(duration)

    # Retour idle
    overlay.set_idle()
    print("\n✅  Démo terminée — fermeture dans 2s")
    time.sleep(2.0)
    overlay._signals.quit_app.emit()


def main():
    qt_app, overlay, _signals = create_qt_app()

    worker = threading.Thread(
        target=_demo_thread,
        args=(overlay,),
        daemon=True,
        name="DemoThread",
    )
    worker.start()

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
