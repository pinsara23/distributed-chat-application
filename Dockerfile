FROM python:3.11-slim

# Unbuffered stdout so `docker compose logs` shows prints immediately.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run as an unprivileged user.
RUN useradd --system --uid 10001 --no-create-home appuser

# Application code, plus the Alembic config and migrations: the one-shot
# `migrate` service in docker-compose.yml runs `alembic upgrade head` from this
# same image. WORKDIR is /app, which `prepend_sys_path = .` relies on.
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
