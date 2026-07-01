"""
test_wakeword.py — Calibration du wake word "Hey Jarvis"
Lance ce script, dis "Hey Jarvis" plusieurs fois et note les scores max affichés.
Le seuil optimal = score max / 1.5 (environ)
"""
import sys
import queue
import time
import numpy as np
import sounddevice as sd
from openwakeword.model import Model

CHUNK = 1280   # 80ms à 16kHz — taille optimale OWW
RATE  = 16000

print("\n" + "═"*50)
print("   TEST WAKE WORD — Hey Jarvis")
print("═"*50)
print("\nChargement du modèle...")

model = Model(wakeword_models=["hey jarvis"], inference_framework="onnx")
print("✓ Modèle chargé\n")
print("Dis 'Hey Jarvis' plusieurs fois.")
print("Appuie sur Ctrl+C pour arrêter.\n")
print(f"{'Score':<10} {'Barre':<30} {'Statut'}")
print("─"*55)

audio_queue = queue.Queue()
max_score_seen = 0.0

def callback(indata, frames, time_info, status):
    audio_queue.put(indata[:, 0].copy())

try:
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                        blocksize=CHUNK, callback=callback):
        while True:
            try:
                frame = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            pred = model.predict(frame)
            score = float(pred.get("hey jarvis", 0.0))

            if score > max_score_seen:
                max_score_seen = score

            # Afficher seulement si score > 0.05
            if score > 0.05:
                bar_len = int(score * 40)
                bar = "█" * bar_len + "░" * (40 - bar_len)
                detected = "  ← DÉTECTÉ ✓" if score >= 0.5 else ""
                print(f"\r{score:.3f}      [{bar}]{detected}   max={max_score_seen:.3f}", end="", flush=True)
            else:
                print(f"\r{'.'*3} (silence)   max vu = {max_score_seen:.3f}", end="", flush=True)

except KeyboardInterrupt:
    print(f"\n\n{'═'*50}")
    print(f"  Score maximum observé : {max_score_seen:.3f}")
    print(f"  Seuil recommandé      : {max_score_seen * 0.65:.3f}")
    print(f"{'═'*50}\n")
