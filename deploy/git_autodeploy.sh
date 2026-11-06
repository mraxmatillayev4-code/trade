#!/bin/bash
# SINO git-aviadeploy (har 2 daqiqada cron orqali):
# GitHub main da yangi commit chiqsa — kod yangilanadi, konteyner qayta quriladi.
# Hech qanday xato chiqsa — eski versiya ishlab turishda davom etadi.
cd /opt/sino_bot || exit 0
git fetch origin main -q || exit 0
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0
echo "[$(date '+%F %T')] yangi commit: $LOCAL -> $REMOTE"
git reset --hard origin/main -q
git clean -fdq -e .env -e data || true
# deps o'zgargan bo'lsa rebuild; aks holda tez restart
if git diff --name-only "$LOCAL" "$REMOTE" | grep -qE "requirements.txt|Dockerfile"; then
  docker compose up -d --build
else
  docker compose up -d --build --no-deps bot api
fi
sleep 15
if curl -fsS -m 10 http://127.0.0.1:8000/health >/dev/null; then
  echo "[$(date '+%F %T')] deploy OK ($REMOTE)"
else
  echo "[$(date '+%F %T')] HEALTH XATO — qoldiq loglarni ko'ring: docker compose logs --tail=80 bot"
fi
