FROM python:3.11.15-slim-bookworm

WORKDIR /app/backend

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

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

USER appuser

CMD ["gunicorn", "-c", "/app/backend/gunicorn_conf.py", "backend.server:app"]
