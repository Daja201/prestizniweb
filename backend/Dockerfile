# Builds the small, non-root FastAPI runtime image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY entrypoint.sh ./entrypoint.sh
RUN mkdir -p app/static/vendor \
    && python -c "from urllib.request import urlretrieve; urlretrieve('https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js', 'app/static/vendor/htmx.min.js')" \
    && chmod 755 ./entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /data/uploads \
    && chown -R appuser:appuser /data/uploads

USER appuser
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]