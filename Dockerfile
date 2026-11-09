FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /project
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -m reconcile
COPY app/ app/
COPY datasets/ datasets/
COPY scripts/container-start.sh scripts/container-start.sh
COPY --from=frontend /build/dist frontend/dist/
RUN mkdir -p data && chown -R reconcile:reconcile /project && chmod +x scripts/container-start.sh
USER reconcile
ENV RECON_DB=/project/data/reconciliation.sqlite3
EXPOSE 8000
CMD ["scripts/container-start.sh"]
