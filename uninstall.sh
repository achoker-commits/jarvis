#!/bin/bash
# uninstall.sh — Désinstalle JARVIS du démarrage automatique.
PLIST="$HOME/Library/LaunchAgents/com.ali.jarvis.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "✅ JARVIS désinstallé. Il ne démarrera plus automatiquement."
