"""Run MCP server over stdio transport."""

from app.mcp_tools import mcp_server


if __name__ == "__main__":
    mcp_server.run()
