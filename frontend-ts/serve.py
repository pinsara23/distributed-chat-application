"""Static file server + same-origin proxy for the chat web UI.

The backend has no CORS middleware (and must not be changed), so the browser
talks to THIS server instead:

    /                              -> the web UI (frontend-ts/dist)
    /backend/<port>/<path>         -> http://127.0.0.1:<port>/<path>   (REST)
    /backend/<port>/ws/chat?token= -> ws://127.0.0.1:<port>/ws/chat    (WebSocket)

Only ports listed in FRONTEND_BACKEND_PORTS (default 8000-8003) can be proxied.

Run (conda env chat-stage2):
    npm run build                       # once, in frontend-ts/
    python frontend-ts/serve.py         # http://localhost:3000 (serves dist/)
    FRONTEND_PORT=3001 python frontend-ts/serve.py
"""

import asyncio
import os
from pathlib import Path

import aiohttp
from aiohttp import web

ROOT = Path(os.environ.get("FRONTEND_DIR") or Path(__file__).resolve().parent / "dist").resolve()
HOST = os.environ.get("FRONTEND_HOST", "127.0.0.1")
PORT = int(os.environ.get("FRONTEND_PORT", "3000"))
BACKEND_HOST = os.environ.get("FRONTEND_BACKEND_HOST", "127.0.0.1")
ALLOWED_PORTS = {
    p.strip() for p in os.environ.get("FRONTEND_BACKEND_PORTS", "8000,8001,8002,8003").split(",") if p.strip()
}

FORWARD_REQUEST_HEADERS = ("authorization", "content-type", "accept")
FORWARD_RESPONSE_HEADERS = ("content-type",)


def _check_port(request: web.Request) -> str:
    port = request.match_info["port"]
    if port not in ALLOWED_PORTS:
        raise web.HTTPForbidden(text=f"Port {port} is not an allowed backend.")
    return port


async def proxy_http(request: web.Request) -> web.StreamResponse:
    port = _check_port(request)
    url = f"http://{BACKEND_HOST}:{port}/{request.match_info['tail']}"
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_REQUEST_HEADERS}
    body = await request.read()
    try:
        async with request.app["client"].request(
            request.method, url, params=request.query, headers=headers, data=body or None,
        ) as upstream:
            payload = await upstream.read()
            response = web.Response(status=upstream.status, body=payload)
            for name in FORWARD_RESPONSE_HEADERS:
                if name in upstream.headers:
                    response.headers[name] = upstream.headers[name]
            return response
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        # 502 tells the browser client to try another server.
        return web.json_response({"detail": f"Backend on port {port} unreachable: {exc.__class__.__name__}"}, status=502)


async def proxy_ws(request: web.Request) -> web.StreamResponse:
    port = _check_port(request)
    url = f"ws://{BACKEND_HOST}:{port}/ws/chat"
    try:
        upstream = await request.app["client"].ws_connect(url, params=request.query, heartbeat=None)
    except aiohttp.WSServerHandshakeError as exc:
        # e.g. the backend rejected the token -> let the browser see a failed upgrade.
        return web.Response(status=exc.status if exc.status >= 400 else 502, text="Backend rejected WebSocket.")
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return web.Response(status=502, text=f"Backend on port {port} unreachable.")

    client = web.WebSocketResponse(heartbeat=None)
    await client.prepare(request)

    async def pump(src, dst):
        async for msg in src:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await dst.send_str(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await dst.send_bytes(msg.data)
            else:
                break
        # Mirror the close (code + reason) so the UI sees e.g. 1008 / 1001.
        code = src.close_code or 1000
        if not dst.closed:
            await dst.close(code=code if 1000 <= code < 5000 and code not in (1005, 1006) else 1000)

    tasks = [asyncio.create_task(pump(client, upstream)), asyncio.create_task(pump(upstream, client))]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not upstream.closed:
            await upstream.close()
        if not client.closed:
            await client.close()
    return client


async def backend_entry(request: web.Request) -> web.StreamResponse:
    if request.match_info["tail"] == "ws/chat" and request.headers.get("Upgrade", "").lower() == "websocket":
        return await proxy_ws(request)
    return await proxy_http(request)


async def index(_request: web.Request) -> web.StreamResponse:
    return web.FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@web.middleware
async def no_cache(request, handler):
    response = await handler(request)
    if not request.path.startswith("/backend/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


async def client_ctx(app: web.Application):
    app["client"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
    yield
    await app["client"].close()


def make_app() -> web.Application:
    app = web.Application(middlewares=[no_cache])
    app.cleanup_ctx.append(client_ctx)
    app.router.add_route("*", "/backend/{port}/{tail:.*}", backend_entry)
    app.router.add_get("/", index)
    if (ROOT / "assets").is_dir():
        app.router.add_static("/assets", ROOT / "assets", show_index=False)
    return app


if __name__ == "__main__":
    print(f"Chat UI on http://{HOST}:{PORT}  (proxying backend ports: {', '.join(sorted(ALLOWED_PORTS))})")
    web.run_app(make_app(), host=HOST, port=PORT, print=None)
