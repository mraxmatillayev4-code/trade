# SINO BOT — VPS MIGRATSIYA (Render → Ubuntu VPS)

Tavsiya: **SmartCloud VDS HDD 1-2-30 (82 000 so'm/oy)** yoki Servercore 1CPU/1GB (102 592 so'm/oy).
Talab: Ubuntu 22.04/24.04, 2 GB RAM, 30 GB disk, root SSH.

## 1. Tayyorlik (serverda bir marta)
```bash
apt-get update -y && apt-get install -y git curl
mkdir -p /opt && cd /opt
git clone git@github.com:mraxmatillayev4-code/trade.git sino_bot
# (private repo bo'lsa: serverda SSH deploy-key qiling yoki PAT bilan clone)
cd sino_bot
bash deploy/setup_vps.sh
```

## 2. .env (eng muhim qatorlari)
```
BOT_TOKEN=<telegram bot token>
ADMIN_IDS=<admin telegram id>
DATABASE_URL=postgresql+asyncpg://trader:trader_pass@postgres:5432/trading_bot
REDIS_URL=redis://redis:6379/0
PORT=8000
```
Qolgan kalitlar — hozirgi Render dashboard'dagi bilan bir xil ko'chiriladi.

## 3. Ishga tushirish
```bash
cd /opt/sino_bot && docker compose up -d --build
curl http://127.0.0.1:8000/health     # {"status":"ok","version":"SINO-LAI-128",...} chiqishi kerak
```

## 4. Git avto-deploy (push → server o'zi yangilanadi)
setup_vps.sh buni o'zi cron'ga yozadi (har 2 daqiqada `deploy/git_autodeploy.sh`).
Log: `/var/log/sino_deploy.log`. Qo'lda yangilash: `bash deploy/git_autodeploy.sh`.

## 5. Render'dan chiqish
1. Bot VPS'da barqaror ishlayotganini tekshiring (Telegram'da /kanal_holati → SINO-LAI-128).
2. Render'da workspace ni **suspend** qiling (to'lov to'xtaydi).
3. MetaApi / boshqa integratsiyalar .env orqali o'zgardi — qayta sozlash shart emas.

## 6. Foydali komandalar
```bash
docker compose logs -f bot      # jonli log
docker compose ps               # holat
docker compose restart bot      # qayta ishga tushirish
```
Muammo bo'lsa: `docker compose logs --tail=100 bot api` chiqishini yuboring.
