# FastAPI backend for Cloud Run. Build context is backend/.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the layer caches across code changes.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App + ETL package (etl/ca/sip is imported by app/plans.py).
COPY . .

# Cloud Run injects $PORT (default 8080). Shell form so it expands.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
