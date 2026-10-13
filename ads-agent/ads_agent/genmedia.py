"""The local genmedia MCP servers (Veo, Gemini Omni, avtool), as genmedia-video-editing expects them."""
import logging
import os

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

from .config import GENMEDIA_BIN_DIR, GENMEDIA_BUCKET, GOOGLE_CLOUD_PROJECT, WORKSPACE

log = logging.getLogger(__name__)

# (binary, Vertex location, confirm every call). Veo and Omni calls are paid generations.
SERVERS = {
    "genmedia-veo": ("mcp-veo-go", "us-central1", True),
    "genmedia-omni": ("mcp-omni-go", "global", True),
    "genmedia-avtool": ("mcp-avtool-go", "us-central1", False),
}


def genmedia_toolsets() -> list[McpToolset]:
    if not GENMEDIA_BUCKET:
        return []
    toolsets = []
    for name, (binary, location, confirm) in SERVERS.items():
        command = GENMEDIA_BIN_DIR / binary
        if not command.exists():
            log.warning("Skipping %s: %s not found (run genmedia-video-editing/scripts/setup.sh)", name, command)
            continue
        env = {**os.environ, "GENMEDIA_BUCKET": GENMEDIA_BUCKET, "GOOGLE_CLOUD_LOCATION": location}
        if GOOGLE_CLOUD_PROJECT:
            env["GOOGLE_CLOUD_PROJECT"] = GOOGLE_CLOUD_PROJECT
        toolsets.append(McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(command=str(command), env=env, cwd=str(WORKSPACE)),
                timeout=30),
            require_confirmation=confirm))
    return toolsets
