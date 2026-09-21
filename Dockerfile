FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Render/UptimeRobot uchun healthcheck
HEALTHCHECK --interval=60s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:'+__import__('os').environ.get('PORT','8000')+'/health',timeout=5).status==200 else 1)" || exit 1

# Default: barcha xizmatlar (bot + scheduler + websocket + API) bitta jarayonda
CMD ["python", "-m", "app.main", "all"]
