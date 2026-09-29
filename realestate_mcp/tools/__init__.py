"""도메인별 MCP 도구 모듈. 각 모듈은 register(mcp) 로 도구를 등록한다."""
from importlib import import_module

from mcp.server.fastmcp import FastMCP

# 등록 순서 = 도구 목록 순서
TOOL_MODULES: tuple[str, ...] = ("vworld", "bldrgst", "rtms", "composite")


def register_all(mcp: FastMCP) -> None:
    for name in TOOL_MODULES:
        module = import_module(f"{__name__}.{name}")
        module.register(mcp)
