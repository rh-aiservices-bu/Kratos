# Stage 1: build the React UI
FROM node:20-alpine AS node-builder
WORKDIR /build/ui
COPY ui/package*.json ./
RUN npm ci --silent
COPY ui/ ./
RUN npm run build

# Stage 2: final image — API server + harness entrypoint
FROM python:3.11-slim
WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY harness/ harness/
COPY api/ api/
COPY scenarios/ scenarios/

COPY --from=node-builder /build/ui/dist/ ui/dist/

ENV SCENARIOS_DIR=/app/scenarios
ENV DB_PATH=/data/kratos.db

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
