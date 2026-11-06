#!/bin/bash
# SINO BOT — UBUNTU VPS dastlabki o'rnatish (SmartCloud/Servercore/MyCloud)
# Bir marta bajariladi:  bash deploy/setup_vps.sh
set -e
echo "=== 1) Docker o'rnatish ==="
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y docker.io docker-compose-plugin git curl
  systemctl enable --now docker
fi
docker version | head -2

echo "=== 2) Kodni olish (GitHub) ==="
cd /opt 2>/dev/null || cd /
if [ ! -d /opt/sino_bot/.git ]; then
  mkdir -p /opt/sino_bot
  # ochiq repo bo'lsa: git clone https://github.com/mraxmatillayev4-code/trade.git sino_bot
  git clone git@github.com:mraxmatillayev4-code/trade.git /opt/sino_bot || \
  git clone https://github.com/mraxmatillayev4-code/trade.git /opt/sino_bot
fi
cd /opt/sino_bot && git pull

echo "=== 3) .env tekshiruv ==="
if [ ! -f .env ]; then
  echo "DIQQAT: /opt/sino_bot/.env yarating ( .env.example ni nusxalab to'ldiring ):"
  echo "  BOT_TOKEN, ADMIN_IDS, DATABASE_URL=postgresql+asyncpg://trader:trader_pass@postgres:5432/trading_bot"
  echo "  REDIS_URL=redis://redis:6379/0"
  cp .env.example .env || true
fi

echo "=== 4) Ishga tushirish ==="
docker compose up -d --build
sleep 20
curl -fsS http://127.0.0.1:8000/health && echo "  <- API SGLAM"

echo "=== 5) GIT AVIADEPLOY (har 2 daqiqada) ==="
mkdir -p /opt/sino_bot/deploy
cp deploy/git_autodeploy.sh /opt/sino_bot/deploy/ 2>/dev/null || true
chmod +x /opt/sino_bot/deploy/git_autodeploy.sh
( crontab -l 2>/dev/null | grep -v git_autodeploy ; echo "*/2 * * * * /opt/sino_bot/deploy/git_autodeploy.sh >> /var/log/sino_deploy.log 2>&1" ) | crontab -
echo "TAYYOR. Server IP: $(curl -fsS ifconfig.me 2>/dev/null || echo '?')"
