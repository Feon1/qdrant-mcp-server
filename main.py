"""MCP-сервер для Qdrant через Streamable HTTP (без SSE)."""
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import httpx


PROXY_URL = os.getenv("PROXY_URL", "https://qdrant-proxy-e9ov.onrender.com/search")
PROXY_TOKEN = os.getenv("PROXY_TOKEN", "")
DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", "10"))


app = FastAPI(title="Qdrant MCP Server (Streamable HTTP)")


async def qdrant_find(query: str, limit: int = DEFAULT_LIMIT) -> str:
    if not query.strip():
        return "Пустой запрос."
    headers = {"Content-Type": "application/json"}
    if PROXY_TOKEN:
        headers["x-proxy-token"] = PROXY_TOKEN
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(PROXY_URL, json={"query": query, "limit": limit}, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return f"Ошибка поиска: {e}"
    chunks = [c.get("text", "") for c in data.get("chunks", []) if c.get("text")]
    if not chunks:
        return "В базе знаний ничего не найдено."
    return "\n\n---\n\n".join(chunks)


TOOLS = [{
    "name": "qdrant_find",
    "description": (
        "Ищет в православной базе знаний (41000+ документов: святые отцы, "
        "догматика, патрология, каноны, история Церкви). Используй ВСЕГДА, "
        "когда пользователь задаёт вопрос по богословию."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"}
        },
        "required": ["query"]
    }
}]


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """Единственный эндпоинт для MCP Streamable HTTP."""
    try:
        msg = await request.json()
    except Exception as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)

    method = msg.get("method")
    req_id = msg.get("id")
    print(f"📥 MCP: {method} (id={req_id})")

    # initialize
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "qdrant-mcp", "version": "1.0.0"}
            }
        })

    # notifications/initialized — без ответа
    if method == "notifications/initialized":
        return JSONResponse({"ok": True})

    # tools/list
    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        })

    # tools/call
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "qdrant_find":
            query = args.get("query", "")
            print(f"🔍 qdrant_find: query='{query[:60]}'")
            result = await qdrant_find(query)
            print(f"✅ qdrant_find: {len(result)} симв.")
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": result}]}
            })
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unknown tool: {name}"}
        })

    # ping
    if method == "ping":
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": {}})

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    })


@app.get("/health")
async def health():
    return {"status": "ok", "service": "qdrant-mcp-server", "transport": "streamable-http"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8300))
    uvicorn.run(app, host="0.0.0.0", port=port)
