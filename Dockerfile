#FROM python:3.12-slim
#WORKDIR /app
#COPY requirements.txt .
#RUN pip install --no-cache-dir -r requirements.txt
#COPY . .
#CMD ["uvicorn", "qdrant_mcp_server:app", "--host", "0.0.0.0", "--port", "10000"]


# ========== Этап 1: Сборка MCP Hub (Node.js) ==========
FROM node:20-alpine AS mcphub-builder

WORKDIR /app/mcphub
RUN apk add --no-cache git python3 make g++

# Клонируем MCP Hub
RUN git clone https://github.com/huangjunsen0406/xiaozhi-mcphub.git .

# Устанавливаем pnpm и зависимости
RUN npm install -g pnpm
RUN pnpm install --frozen-lockfile
RUN pnpm build

# ========== Этап 2: Финальный образ ==========
FROM python:3.11-slim

# Устанавливаем Node.js и supervisord
RUN apt-get update && apt-get install -y \
    curl \
    supervisor \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем pnpm
RUN npm install -g pnpm

# Копируем собранный MCP Hub
COPY --from=mcphub-builder /app/mcphub /app/mcphub

# Копируем Python-сервер
WORKDIR /app/qdrant
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn httpx

# Конфигурация supervisord
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Открываем порты (Render слушает $PORT)
EXPOSE 3000 8300

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
