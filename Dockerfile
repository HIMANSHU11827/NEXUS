FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXUS_HOME=/home/nexus/.nexus \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system nexus && adduser --system --group nexus \
    && mkdir -p /home/nexus/.nexus \
    && chown -R nexus:nexus /home/nexus

COPY pyproject.toml uv.lock ./
COPY . .

RUN pip install --no-cache-dir -e ".[dev]"

USER nexus

EXPOSE 8000

CMD ["python", "-m", "nexus"]
