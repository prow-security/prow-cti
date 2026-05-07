FROM python:3.12-slim AS builder

WORKDIR /build

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src

RUN pip install --no-cache-dir .

FROM python:3.12-slim AS runtime

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH"

WORKDIR /app

CMD ["python", "-m", "prow"]
