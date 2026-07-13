FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/apps/api

WORKDIR /app

COPY apps/api/requirements.txt /app/apps/api/requirements.txt
RUN pip install --no-cache-dir -r /app/apps/api/requirements.txt

FROM base AS test

COPY apps/api/requirements-dev.txt /app/apps/api/requirements-dev.txt
RUN pip install --no-cache-dir -r /app/apps/api/requirements-dev.txt
COPY apps/api /app/apps/api
WORKDIR /app/apps/api

FROM base AS runtime

COPY apps/api /app/apps/api
WORKDIR /app/apps/api

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn learn_platform_api.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
