FROM python:3.11.15-slim-bookworm

WORKDIR /app/backend

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV S2RS_DATA_DIR=/data
ENV S2RS_ENABLE_CLOUD_EXTENSIONS=0
ENV S2RS_LOCAL_AI_ENABLED=0

RUN useradd -m -u 10001 appuser

COPY backend/requirements.txt /app/backend/requirements.txt
RUN apt-get update \
  && apt-get upgrade -y \
  && apt-get install -y --no-install-recommends build-essential python3-dev \
  && python -m pip install --no-cache-dir -U pip \
  && pip install --no-cache-dir -r /app/backend/requirements.txt \
  && apt-get remove -y build-essential python3-dev \
  && rm -rf /var/lib/apt/lists/*

COPY backend/ /app/backend/

EXPOSE 8000

VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

USER appuser

CMD ["gunicorn", "-c", "/app/backend/gunicorn_conf.py", "server:app"]
