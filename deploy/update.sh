#!/usr/bin/env bash
# Exécuté sur le VPS : récupère la dernière version, met à jour les dépendances, relance bot + site.
set -euo pipefail
cd /root/pokewild
git fetch origin main
git reset --hard origin/main
/root/venv-web/bin/pip install -q -r requirements.txt
systemctl restart pokewild
systemctl is-enabled pokewild-web >/dev/null 2>&1 && systemctl restart pokewild-web || true
systemctl is-active pokewild
