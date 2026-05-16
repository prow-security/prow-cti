FROM node:22-slim AS ui-builder
WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm ci --prefer-offline
COPY ui/ ./
RUN npm run build

FROM python:3.12-slim AS python-builder
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src/ ./src/
RUN python -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir .

FROM python:3.12-slim AS runtime
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash prow

COPY --from=python-builder /venv /venv
COPY --from=python-builder /app/src ./src
COPY alembic.ini ./

COPY --from=ui-builder /app/src/prow/api/static ./src/prow/api/static

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER prow

ENV PATH="/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--", "/entrypoint.sh"]
