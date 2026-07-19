FROM python:3.13-slim AS base

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

RUN addgroup --system nexus && adduser --system --ingroup nexus nexus \
    && mkdir -p /home/nexus/.nexus \
    && chown -R nexus:nexus /home/nexus

COPY --chown=nexus:nexus pyproject.toml uv.lock /app/

RUN pip install uv && uv sync --no-dev --frozen

COPY --chown=nexus:nexus . /app/

RUN uv sync --no-dev --frozen

USER nexus

EXPOSE 8000

CMD ["python", "-m", "nexus"]
