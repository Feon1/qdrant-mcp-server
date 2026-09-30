# ========== Этап 1: Сборка MCP Hub (Node.js) ==========
FROM node:20-alpine AS mcphub-builder

WORKDIR /app/mcphub
RUN apk add --no-cache git python3 make g++

RUN wget -qO- https://github.com/Feon1/xiaozhi-mcphub/archive/refs/heads/main.tar.gz | tar xz --strip-components=1

RUN corepack enable && corepack prepare pnpm@10.33.0 --activate
RUN pnpm install --frozen-lockfile
RUN pnpm build

# ========== Этап 2: Финальный образ ==========
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl \
    supervisor \
    git \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g pnpm

# ---------- MCP Hub (Node.js) ----------
COPY --from=mcphub-builder /app/mcphub /app/mcphub

# В финальном этапе (stage-1) после установки python
RUN pip install --no-cache-dir uv
# ---------- qdrant-proxy (Python) ----------
WORKDIR /app/qdrant-proxy
RUN git clone https://github.com/Feon1/qdrant-proxy.git .
RUN pip install --no-cache-dir -r requirements.txt

# ---------- qdrant-mcp (Python, ваш сервер) ----------
WORKDIR /app/qdrant
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn httpx

# ---------- supervisord ----------
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 3000

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
