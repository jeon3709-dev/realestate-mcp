"""부동산 통합 조회 MCP 서버 진입점.

VWorld(지오코딩·필지·용도지역·공시지가) + 건축HUB 건축물대장 + 국토부 실거래가(RTMS)
세 API 를 단일 FastMCP 인스턴스로 제공한다.

실행 모드
- `python server.py stdio` : 로컬 MCP 클라이언트용 stdio
- 그 외(인자 없음, `sse` 등): HTTP 모드. Streamable HTTP(/mcp) + 레거시 SSE(/sse, /messages/)
  + GET / 헬스 응답. 포트는 PORT 환경변수(기본 8080).
  (클라우드 플랫폼이 인자 없이 `python server.py` 로 띄워도 stdin EOF 로 죽지 않도록
   원본 서버들과 같이 HTTP 를 기본으로 한다.)
"""
import logging
import sys
from typing import Any, List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from realestate_mcp import config
from realestate_mcp.common import configure_logging
from realestate_mcp.tools import register_all

configure_logging()
logger = logging.getLogger("realestate-mcp")

SERVER_NAME = "Real Estate Integrated MCP Server"


def create_server(argv: Optional[List[str]] = None) -> FastMCP:
    """Create the single FastMCP instance and register every tool module."""
    args = sys.argv if argv is None else argv
    port_env = config.port()
    is_http = not (len(args) > 1 and args[1] == "stdio")
    # Disable MCP's DNS-rebinding (Host header) protection. It defaults to allowing
    # only localhost, so behind a cloud host (e.g. *.cloudtype.app) every request is
    # rejected with "Invalid Host header" (HTTP 421) and clients like claude.ai cannot
    # connect. This server is a public, unauthenticated API proxy with no local
    # resources to protect, so relaxing the host check is safe here.
    server = FastMCP(
        SERVER_NAME,
        host="0.0.0.0" if is_http else "127.0.0.1",
        port=port_env,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    register_all(server)
    return server


mcp = create_server()


def build_http_app(server: FastMCP) -> Starlette:
    """Build the ASGI app (BDLedger_MCP bootstrap): /mcp + /sse + / + OAuth-discovery 404s."""
    from starlette.middleware.cors import CORSMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, PlainTextResponse
    from starlette.routing import Route

    mcp_http_app = server.streamable_http_app()
    mcp_sse_app = server.sse_app()

    # OAuth Discovery endpoints returning 404 to indicate no OAuth authentication is required
    async def _no_oauth(request: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "no_auth_required", "message": "This MCP server does not require OAuth authentication."},
            status_code=404
        )

    # Health-check route. Cloud platforms (Cloudtype/Render) probe "/" to decide
    # if the pod is ready; without a 2xx here the deploy can hang in "waiting".
    async def _health(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    routes = [
        Route("/", _health, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", _no_oauth, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", _no_oauth, methods=["GET"]),
        Route("/.well-known/mcp-configuration", _no_oauth, methods=["GET"]),
    ]

    app = Starlette(routes=routes, lifespan=mcp_http_app.router.lifespan_context)
    app.router.routes.extend(mcp_http_app.router.routes)
    app.router.routes.extend(mcp_sse_app.router.routes)

    # Middleware to normalize Accept header and support POST to / as /mcp
    class NormalizeAcceptHeaderMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] == "http":
                path = scope.get("path", "")
                method = scope.get("method", "")

                # If client POSTs to root /, rewrite path to /mcp so root works as MCP endpoint
                if path == "/" and method == "POST":
                    scope["path"] = "/mcp"
                    scope["raw_path"] = b"/mcp"
                    path = "/mcp"

                if path in ["/mcp", "/sse", "/"] or path.startswith("/messages"):
                    new_headers = []
                    has_accept = False
                    for k, v in scope.get("headers", []):
                        if k.lower() == b"accept":
                            has_accept = True
                            accept_str = v.decode("utf-8", errors="ignore")
                            if "text/event-stream" not in accept_str or "application/json" not in accept_str:
                                new_headers.append((b"accept", b"application/json, text/event-stream, */*"))
                            else:
                                new_headers.append((k, v))
                        else:
                            new_headers.append((k, v))
                    if not has_accept:
                        new_headers.append((b"accept", b"application/json, text/event-stream, */*"))
                    scope["headers"] = new_headers
            await self.app(scope, receive, send)

    # Disable buffering for cloud proxies (prevents 502 / timeouts in SSE)
    class DisableBufferingMiddleware:
        def __init__(self, app: Any) -> None:
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            async def send_wrapper(message: Any) -> None:
                if message["type"] == "http.response.start":
                    headers = message.setdefault("headers", [])
                    headers.append((b"x-accel-buffering", b"no"))
                    headers.append((b"cache-control", b"no-cache, no-transform"))
                await send(message)
            await self.app(scope, receive, send_wrapper)

    app.add_middleware(NormalizeAcceptHeaderMiddleware)
    app.add_middleware(DisableBufferingMiddleware)

    # Permissive CORS (allow_credentials must be False when allow_origins is "*")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id", "content-type", "authorization", "x-accel-buffering"],
    )
    return app


def main(argv: Optional[List[str]] = None) -> None:
    args = sys.argv if argv is None else argv
    use_stdio = len(args) > 1 and args[1] == "stdio"
    if use_stdio:
        mcp.run()
        return

    import uvicorn

    port = config.port()
    logger.info(f"Starting {SERVER_NAME} in HTTP transport mode on 0.0.0.0:{port} (/mcp, /sse)...")
    uvicorn.run(build_http_app(mcp), host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
