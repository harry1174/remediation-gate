FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

RUN adduser --disabled-password --gecos "" --uid 10001 app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY issues ./issues
COPY knowledge ./knowledge
COPY playbooks ./playbooks
COPY scripts ./scripts
COPY tests ./tests

RUN mkdir -p /data && chown -R app:app /data /srv
USER app

EXPOSE 8000
HEALTHCHECK --interval=3s --timeout=4s --start-period=2s --retries=10 \
  CMD python -c "import httpx,sys; sys.exit(0 if httpx.get('http://localhost:8000/healthz').status_code == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
