# ========== Этап 1: Сборка MCP Hub (Node.js) ==========
FROM node:20-alpine AS mcphub-builder

WORKDIR /app/mcphub

# Устанавливаем необходимые пакеты для сборки
RUN apk add --no-cache git python3 make g++

# Клонируем репозиторий MCP Hub
RUN git clone https://github.com/huangjunsen0406/xiaozhi-mcphub.git .

# Активируем corepack и устанавливаем нужную версию pnpm
# Версия должна совпадать с той, что указана в package.json проекта
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate

# Устанавливаем зависимости и собираем проект
RUN pnpm install --frozen-lockfile
RUN pnpm build

# ========== Этап 2: Финальный образ ==========
FROM python:3.11-slim

# Устанавливаем Node.js, curl и supervisor
RUN apt-get update && apt-get install -y \
    curl \
    supervisor \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Копируем собранный MCP Hub из первого этапа
COPY --from=mcphub-builder /app/mcphub /app/mcphub

# Копируем Python-сервер (ваш qdrant-mcp-server)
WORKDIR /app/qdrant
COPY . .
RUN pip install --no-cache-dir fastapi uvicorn httpx

# Копируем конфигурацию supervisord
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Открываем порты (внутренние порты контейнера)
EXPOSE 3000 8300

# Запускаем supervisord, который поднимет оба процесса
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
