# STEG HelioCast AI - image de service (job + API + dashboard statique)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Africa/Tunis

WORKDIR /app

# Client MySQL (mysqladmin) pour le wait-for dans l'entrypoint + libgomp1 (requis par LightGBM)
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-mysql-client \
        libgomp1 \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Layout conserve la structure projet (config.py derive PROJECT_ROOT = /app)
COPY deploy /app/deploy
COPY modeling /app/modeling
COPY scripts/modeling_v14.py /app/scripts/modeling_v14.py
COPY models_final_14 /app/models_final_14

COPY deploy/entrypoint_docker.sh /entrypoint_docker.sh
RUN chmod +x /entrypoint_docker.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint_docker.sh"]