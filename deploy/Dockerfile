# Serving image: no training stack, no deep learning framework.
FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-group ml --no-editable

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 imbuto
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY src/imbuto/api/static ./src/imbuto/api/static
COPY artifacts ./artifacts
COPY knowledge ./knowledge
COPY locale ./locale
RUN mkdir /data && chown imbuto /data
ENV PATH=/app/.venv/bin:$PATH IMBUTO_ROOT=/app IMBUTO_DB_PATH=/data/imbuto.sqlite PYTHONUNBUFFERED=1
USER imbuto
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/readyz', timeout=2)"
CMD ["uvicorn", "imbuto.api.main:app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
