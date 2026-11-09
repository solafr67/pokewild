#!/usr/bin/env bash
# Exécuté sur le VPS (une seule fois) : ouvre le site sur le port 80 via nginx.
# Usage : bash deploy/ouvrir-site.sh 87.106.127.83
set -euo pipefail
IP="${1:?Usage: ouvrir-site.sh <ip-ou-domaine>}"
cd /root/pokewild
ENV=/root/pokewild/.env.web
[ -f "$ENV" ] || { echo "❌ $ENV introuvable"; exit 1; }

echo "→ Installation de nginx"
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nginx >/dev/null

echo "→ Configuration nginx"
install -m 644 deploy/nginx-pokewild-proxy.conf /etc/nginx/pokewild-proxy.conf
install -m 644 deploy/nginx-pokewild.conf /etc/nginx/conf.d/pokewild.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "→ Réglages du site"
set_var() { grep -q "^$1=" "$ENV" && sed -i "s|^$1=.*|$1=$2|" "$ENV" || echo "$1=$2" >> "$ENV"; }
set_var WEB_BASE_URL "http://$IP"
grep -q "^WEB_SECRET=." "$ENV" || set_var WEB_SECRET "$(openssl rand -hex 32)"
sed -i '/^WEB_DEV_LOGIN=/d' "$ENV"        # jamais en production
sed -i '/^WEB_COOKIE_SECURE=/d' "$ENV"    # HTTP pour l'instant (pas de HTTPS sans domaine)
chmod 600 "$ENV"

echo "→ Pare-feu"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then ufw allow 80/tcp >/dev/null && echo "port 80 ouvert (ufw)"; else echo "ufw inactif : rien à faire"; fi

systemctl restart pokewild-web
sleep 2
CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1/)
echo "Site local : HTTP $CODE (attendu : 200)"
echo
echo "✅ Site ouvert sur http://$IP"
echo "👉 Chez Discord (Developer Portal → OAuth2 → Redirects), ajoute exactement :"
echo "   http://$IP/auth/callback"
