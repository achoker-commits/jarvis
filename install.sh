#!/bin/bash
# install.sh — Installe JARVIS comme programme permanent sur ce Mac.
# Lance JARVIS automatiquement à chaque connexion, sans terminal.
# Usage : bash ~/projets/jarvis/install.sh

set -e

PLIST_SRC="$HOME/projets/jarvis/build/com.ali.jarvis.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.ali.jarvis.plist"
LABEL="com.ali.jarvis"

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       JARVIS — Installation          ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Vérifier que le projet existe
if [ ! -f "$HOME/projets/jarvis/main.py" ]; then
    echo "  ❌ ~/projets/jarvis/main.py introuvable."
    echo "     Vérifiez que le dossier du projet est correct."
    exit 1
fi

# Copier le fichier plist
echo "  → Installation du service système..."
cp "$PLIST_SRC" "$PLIST_DST"

# Décharger si déjà chargé (évite les erreurs de double chargement)
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Charger et démarrer
launchctl load "$PLIST_DST"

echo ""
echo "  ✅ JARVIS installé avec succès !"
echo ""
echo "  ┌─────────────────────────────────────────────┐"
echo "  │  JARVIS démarre automatiquement à chaque    │"
echo "  │  connexion à votre Mac.                     │"
echo "  │                                             │"
echo "  │  Modifications de code → redémarrage auto  │"
echo "  │  (détection en temps réel)                  │"
echo "  └─────────────────────────────────────────────┘"
echo ""
echo "  Commandes utiles :"
echo "    Statut   : launchctl list | grep jarvis"
echo "    Redémarrer : bash ~/projets/jarvis/restart.sh"
echo "    Désinstaller : bash ~/projets/jarvis/uninstall.sh"
echo "    Logs     : tail -f ~/projets/jarvis/jarvis.log"
echo ""

# Vérifier que le service tourne
sleep 2
if launchctl list | grep -q "$LABEL"; then
    echo "  ● JARVIS est en cours d'exécution."
else
    echo "  ⚠️  Le service ne semble pas démarré. Vérifiez :"
    echo "     tail -f ~/projets/jarvis/jarvis_error.log"
fi
echo ""
