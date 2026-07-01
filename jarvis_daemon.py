#!/usr/bin/env python3
"""
jarvis_daemon.py — Lanceur JARVIS avec auto-restart sur modification de code.
Ce fichier est ce qui tourne en permanence en arrière-plan.
Il surveille tous les .py du dossier et relance JARVIS si l'un d'eux change.
"""

import os
import sys
import subprocess
import time
import signal
from pathlib import Path

JARVIS_DIR  = Path(__file__).parent
CHECK_EVERY = 3.0    # secondes entre chaque vérification de fichiers
RESTART_WAIT = 1.5   # délai avant de relancer après une modif


def get_mtimes() -> dict:
    """Retourne un dict {chemin: mtime} pour tous les .py du dossier."""
    result = {}
    for f in JARVIS_DIR.glob("*.py"):
        try:
            result[str(f)] = f.stat().st_mtime
        except OSError:
            pass
    return result


def launch_jarvis() -> subprocess.Popen:
    """Lance main.py dans un sous-processus et retourne le processus."""
    print(f"[JARVIS-Daemon] Démarrage...", flush=True)
    env = os.environ.copy()
    # S'assurer que les packages utilisateur sont dans le path (détection dynamique)
    try:
        import site as _site
        user_site = _site.getusersitepackages()
    except Exception:
        user_site = ""
    existing = env.get("PYTHONPATH", "")
    if user_site:
        env["PYTHONPATH"] = f"{user_site}:{existing}" if existing else user_site

    proc = subprocess.Popen(
        [sys.executable, str(JARVIS_DIR / "main.py")],
        cwd=str(JARVIS_DIR),
        env=env,
    )
    print(f"[JARVIS-Daemon] PID {proc.pid}", flush=True)
    return proc


def main():
    print("[JARVIS-Daemon] Démarré. Surveillance des fichiers .py activée.", flush=True)

    proc    = launch_jarvis()
    mtimes  = get_mtimes()
    last_check = time.time()

    def _stop(signum, frame):
        print("[JARVIS-Daemon] Arrêt reçu.", flush=True)
        if proc and proc.poll() is None:
            proc.terminate()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    while True:
        time.sleep(0.5)

        # Vérifier si JARVIS s'est crashé → relancer
        if proc.poll() is not None:
            print(f"[JARVIS-Daemon] Process terminé (code {proc.returncode}), relance dans 3s...", flush=True)
            time.sleep(3)
            proc = launch_jarvis()
            mtimes = get_mtimes()
            last_check = time.time()
            continue

        # Vérifier les modifications de fichiers toutes les CHECK_EVERY secondes
        if time.time() - last_check < CHECK_EVERY:
            continue

        last_check = time.time()
        new_mtimes = get_mtimes()
        changed = [
            Path(f).name
            for f, t in new_mtimes.items()
            if mtimes.get(f) != t
        ]

        if changed:
            print(f"[JARVIS-Daemon] Modification détectée : {', '.join(changed)}", flush=True)
            print(f"[JARVIS-Daemon] Redémarrage automatique...", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            time.sleep(RESTART_WAIT)
            proc = launch_jarvis()
            mtimes = new_mtimes


if __name__ == "__main__":
    main()
