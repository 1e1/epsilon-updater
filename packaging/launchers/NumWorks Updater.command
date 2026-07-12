#!/bin/bash
# macOS — double-click to launch nwupdater (opens the UI in your browser).
# First time: right-click > Open to bypass Gatekeeper on an unsigned script.
# Works whether nwupdater is installed (pip) or run from a copy of the repo.

# 1. installed on PATH?
if command -v nwupdater >/dev/null 2>&1; then
  exec nwupdater ui
fi

# 2. otherwise run from the source tree: walk up until we find src/nwupdater
DIR="$(cd "$(dirname "$0")" && pwd)"
while [ "$DIR" != "/" ] && [ ! -d "$DIR/src/nwupdater" ]; do DIR="$(dirname "$DIR")"; done
if [ -d "$DIR/src/nwupdater" ] && command -v python3 >/dev/null 2>&1; then
  cd "$DIR" || exit 1
  export PYTHONPATH=src
  exec python3 -m nwupdater.cli ui
fi

# 3. neither worked — explain and keep the window open
echo "nwupdater est introuvable."
echo "  • installez-le :  pip install nwupdater      (puis relancez ce fichier), ou"
echo "  • placez ce fichier dans une copie du dépôt (dossier contenant src/nwupdater)."
echo
read -n 1 -s -r -p "Appuyez sur une touche pour fermer…"
