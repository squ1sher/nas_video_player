FROM node:20-alpine AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json ./
RUN npm install
# Copy only required frontend sources to avoid host node_modules contamination.
COPY frontend/index.html ./
COPY frontend/tsconfig.json ./
COPY frontend/vite.config.ts ./
COPY frontend/src ./src
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend/app /app/app
COPY --from=frontend-builder /build/frontend/dist /app/app/static
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8080
ENTRYPOINT ["/app/docker/entrypoint.sh"]

