"""MCP server entrypoint with health and tool schema endpoints."""

from fastapi import FastAPI

from app.bootstrap import bootstrap_database
from app.mcp_tools import mcp_server
from app.tool_schemas import TOOL_SCHEMAS

app = FastAPI(title="MedVoice Scheduler MCP Server", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    bootstrap_database()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/tools/schemas")
def get_tool_schemas() -> dict:
    """Expose MCP tool JSON schemas for contract inspection."""
    return {"tools": TOOL_SCHEMAS}


@app.get("/tools")
def list_tools() -> dict:
    return {"tool_names": list(TOOL_SCHEMAS.keys())}


# Expose MCP ASGI app for Streamable HTTP transport when supported by the SDK.
# If transport wiring changes in SDK versions, tools remain available via stdio through mcp_server.
try:
    app.mount("/mcp", mcp_server.streamable_http_app())
except Exception:  # pragma: no cover
    pass
