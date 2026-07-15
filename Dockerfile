# One service, one image: the React SPA and the FastAPI API ship together and are served from
# the same origin. That is the invariant (see CLAUDE.md) — it's why there's no CORS middleware
# anywhere and no second deploy target.
#
# Build context is the REPO ROOT, not backend/ — a stage that compiles frontend/ cannot see it
# from a backend/ context. Deploy with `gcloud run deploy --source .` from this directory.

# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-slim AS frontend

WORKDIR /frontend

# Manifests first so the (slow) install layer caches across source-only changes.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# `npm run build` = tsc -b && vite build. The typecheck is deliberately part of the image build:
# a type error should fail the deploy, not ship.
RUN npm run build

# --- stage 2: the app -------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Deps first, same caching reason as above.
COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App + ETL package (etl/ca/sip is imported by app/plans.py).
COPY backend/ .

# The built SPA. app/main.py resolves this as <repo>/frontend/dist relative to itself, so the
# layout here must mirror the repo: /app is backend/, and /frontend/dist sits beside it.
COPY --from=frontend /frontend/dist /frontend/dist

# Cloud Run injects $PORT (default 8080). Shell form so it expands.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
