# e& Lahja Studio — backend (FastAPI) + frontend (Vite) via run_all.py
# Build:  docker build -t voicelab-studio .
# Run:    docker run --rm -p 8000:8000 -p 5173:5173 -v voicelab-data:/app/data voicelab-studio
# Open:   http://localhost:5173  (UI)   http://localhost:8000/docs  (API)

# --- stage 1: frontend deps + production build -------------------------------
FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- stage 2: runtime (Python + Node) ----------------------------------------
FROM python:3.13-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Node/npm for Vite (same major as build stage; keeps /usr/local/bin/python intact)
COPY --from=node:22-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY run_all.py ./
COPY --from=frontend /frontend ./frontend

RUN mkdir -p /app/data

ENV DATA_DIR=/app/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    VITE_HOST=0.0.0.0 \
    PYTHONUNBUFFERED=1

EXPOSE 8000 5173

VOLUME ["/app/data"]

CMD ["python", "run_all.py"]
