FROM node:22-alpine AS frontend-builder

WORKDIR /workspace

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm --prefix frontend ci

COPY frontend ./frontend
RUN npm --prefix frontend run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY --from=frontend-builder /workspace/src/retail_analytics_agent/static ./src/retail_analytics_agent/static
COPY db ./db

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 appuser

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn retail_analytics_agent.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
