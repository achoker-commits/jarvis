#!/bin/bash
# restart.sh — Redémarre JARVIS manuellement.
LABEL="com.ali.jarvis"
UID_VAL=$(id -u)
launchctl kickstart -k "gui/${UID_VAL}/${LABEL}" 2>/dev/null \
    || launchctl stop "$LABEL" 2>/dev/null && launchctl start "$LABEL"
echo "✅ JARVIS redémarré."
