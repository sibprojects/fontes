FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY fontes ./fontes
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --create-home --uid 1000 fontes \
    && mkdir -p /data/uploads && chown fontes:fontes /data/uploads
WORKDIR /app
COPY --from=build --chown=fontes:fontes /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 STORAGE_DIR=/data/uploads
USER fontes
EXPOSE 8000
CMD ["uvicorn", "fontes.main:app", "--host", "0.0.0.0", "--port", "8000"]
