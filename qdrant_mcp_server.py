"""MCP-сервер для Qdrant через read-only прокси.
Публикует инструмент qdrant_find для MCP Hub → Xiaozhi.
НЕ содержит ключей Qdrant/Polza — только URL прокси.
"""
import os
import json
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import httpx


# ============================================================
# НАСТРОЙКИ
# ============================================================
PROXY_URL = os.getenv(
    "PROXY_URL",
    "https://qdrant-proxy-e9ov.onrender.com/search"
)
PROXY_TOKEN = os.getenv("PROXY_TOKEN", "")
DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", "10"))


# ============================================================
# APP
# ============================================================
app = FastAPI(title="Qdrant MCP Server")

# Активные SSE-сессии
sessions: dict[str, asyncio.Queue] = {}


# ============================================================
# ВЫЗОВ ПРОКСИ
# ============================================================
async def qdrant_find(query: str, limit: int = DEFAULT_LIMIT) -> str:
    """Ищет в Qdrant через read-only прокси."""
    if not query.strip():
        return "Пустой запрос."

    headers = {"Content-Type": "application/json"}
    if PROXY_TOKEN:
        headers["x-proxy-token"] = PROXY_TOKEN

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                PROXY_URL,
                json={"query": query, "limit": limit},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"Ошибка поиска: {e}"

    chunks = [c.get("text", "") for c in data.get("chunks", []) if c.get("text")]
    if not chunks:
        return "В базе знаний ничего не найдено по этому запросу."

    return "\n\n---\n\n".join(chunks)


# ============================================================
# ОПИСАНИЕ ИНСТРУМЕНТОВ
# ============================================================
TOOLS = [
    {
        "name": "qdrant_find",
        "description": (
            "Ищет информацию в православной базе знаний (41 000+ документов: "
            "святые отцы, догматика, патрология, каноны, история Церкви). "
            "ВСЕГДА используй этот инструмент, когда пользователь задаёт вопрос "
            "по православному богословию, патристике, догматике или истории Церкви. "
            "Возвращает до 5 релевантных фрагментов. "
            "После получения фрагментов — сформулируй ответ на их основе."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос — вопрос пользователя или его суть."
                },
                "limit": {
                    "type": "integer",
                    "description": "Сколько фрагментов вернуть (1-20).",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    }
]


# ============================================================
# MCP ПРОТОКОЛ (JSON-RPC 2.0 поверх SSE)
# ============================================================
@app.get("/sse")
async def sse_endpoint(request: Request):
    """Основной SSE-канал MCP."""
    session_id = os.urandom(8).hex()
    queue: asyncio.Queue = asyncio.Queue()
    sessions[session_id] = queue
    print(f"🔌 Новая MCP-сессия: {session_id}")

    async def event_stream():
        # Сообщаем клиенту endpoint для POST-запросов
        yield f"event: endpoint\ndata: /messages?session_id={session_id}\n\n"

        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            print(f"🔌 MCP-сессия закрыта: {session_id}")
        finally:
            sessions.pop(session_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/messages")
async def messages_endpoint(request: Request, session_id: str):
    """Обработка JSON-RPC запросов от MCP-клиента."""
    try:
        msg = await request.json()
    except Exception as e:
        return {"ok": False, "error": f"Invalid JSON: {e}"}

    method = msg.get("method")
    req_id = msg.get("id")

    print(f"📥 MCP: {method} (id={req_id})")

    queue = sessions.get(session_id)
    if not queue:
        return {"ok": False, "error": "Session not found"}

    # === initialize ===
    if method == "initialize":
        await queue.put({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "qdrant-mcp",
                    "version": "1.0.0"
                }
            }
        })

    # === notifications/initialized (без ответа) ===
    elif method == "notifications/initialized":
        pass

    # === tools/list ===
    elif method == "tools/list":
        await queue.put({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        })

    # === tools/call ===
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})

        if name == "qdrant_find":
            query = args.get("query", "")
            limit = int(args.get("limit", DEFAULT_LIMIT))
            print(f"🔍 qdrant_find: query='{query[:60]}', limit={limit}")

            try:
                result = await qdrant_find(query, limit)
                await queue.put({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result}]
                    }
                })
                print(f"✅ qdrant_find: {len(result)} симв. возвращено")
            except Exception as e:
                print(f"❌ qdrant_find error: {e}")
                await queue.put({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)}
                })
        else:
            await queue.put({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"}
            })

    # === ping ===
    elif method == "ping":
        await queue.put({"jsonrpc": "2.0", "id": req_id, "result": {}})

    else:
        print(f"⚠️ Неизвестный метод: {method}")
        await queue.put({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        })

    return {"ok": True}


# ============================================================
# ПРОЧЕЕ
# ============================================================
@app.get("/health")
async def health():
    """Проверка работоспособности."""
    return {
        "status": "ok",
        "service": "qdrant-mcp-server",
        "proxy_url": PROXY_URL,
        "tools": ["qdrant_find"],
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8300))
    print("=" * 60)
    print(f"  Qdrant MCP Server (port {port})")
    print(f"  Proxy: {PROXY_URL}")
    print(f"  Tools: qdrant_find")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=port)
