FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV BACKEND_PORT=8000
ENV PYTHONPATH=/app/backend:/app

WORKDIR /app/backend

# opencv-python, shapely, psycopg2 등 런타임 의존성 대비
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./requirements.txt

RUN python -m pip install --upgrade pip \
    && pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

COPY backend/ ./

COPY backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /app/backend/data/uploads \
    /app/backend/data/masks \
    /app/backend/data/assets \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]