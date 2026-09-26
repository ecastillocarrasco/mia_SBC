# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip wheel --wheel-dir /wheels ".[azure]"

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MIA_HOST=0.0.0.0 MIA_PORT=8000
RUN useradd --create-home --uid 10001 mia
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
COPY alembic.ini ./
COPY migrations ./migrations
USER mia
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live',timeout=2).status==200 else 1)"
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn --factory mia.main:create_app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
