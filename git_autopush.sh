#!/bin/bash
# Auto-push JARVIS en fin de session Claude Code
cd /Users/chokerali/projets/jarvis || exit 0

# Aucune modif → rien à faire
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    exit 0
fi

GH_BIN="$HOME/.local/bin/gh"
if [ -f "$GH_BIN" ]; then
    "$GH_BIN" auth setup-git 2>/dev/null || true
fi

git add -A
git commit -m "auto-save: $(date '+%Y-%m-%d %H:%M')" --quiet
git push origin main --quiet 2>&1 | logger -t jarvis-autopush || true
