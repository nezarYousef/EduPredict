# Build context: deliverable/. Runtime credentials must never be build arguments.
FROM python:3.11-slim-bookworm@sha256:eb769d88622468aea09986df8172151981bf6622b5eec58dc38301e20673ff84

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EDUPREDICT_ALLOW_DATABASE_WRITES=false

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin edupredict

WORKDIR /app/api
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY api/*.py /app/api/
COPY api/edu_model/temporal_lgbm_model_final.pkl /app/api/edu_model/
USER 10001:10001
EXPOSE 8000
# Liveness checks the loaded model; /ready remains a separate database release gate.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).close()"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
