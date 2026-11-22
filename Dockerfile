# syntax=docker/dockerfile:1
# 多阶段构建：先构建前端，再装后端。数据目录挂卷到 /data。

FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts && npm rebuild esbuild
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY smartkeeper/ ./smartkeeper/
COPY maps/ ./maps/
COPY scenarios/ ./scenarios/
COPY rulepacks/ ./rulepacks/
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV PATH="/opt/venv/bin:$PATH" \
    SMARTKEEPER_DB_PATH=/data/smartkeeper.db \
    SMARTKEEPER_STATIC_DIR=/app/frontend/dist
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "smartkeeper.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
