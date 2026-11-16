from __future__ import annotations

import json
from pathlib import Path

from mcp import types
from mcp.server import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

from .service import Monitor

WEB = Path(__file__).parent / "web"
URI = "ui://cache-monitor/dashboard.html"
MIME = "text/html;profile=mcp-app"
UI_META = {
    "ui": {"resourceUri": URI},
    "ui/resourceUri": URI,
    "openai/outputTemplate": URI,
    "openai/ui": {"preferredModelDisplayMode": "fullscreen"},
}
ANNOTATIONS = types.ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
RESOURCE_META = {
    "ui": {"csp": {"connectDomains": [], "resourceDomains": []}, "prefersBorder": True},
    "openai/ui": {"availableDisplayModes": ["fullscreen"]},
}


def create_server(monitor: Monitor) -> Server:
    server = Server("gauge")
    selection = {"type": "object", "properties": {
        "session_id": {"type": "string", "minLength": 1, "description": "The current chat ID. Never substitute another chat."},
        "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 500},
    }, "additionalProperties": False}
    internal_option = {"type": "boolean", "default": False,
                       "description": "Include internal automatic review sessions (hidden by default)."}
    dashboard_selection = {**selection, "required": ["session_id"]}

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(name="show_cache_dashboard", title="Open Gauge",
                       description="Open Gauge, a local dashboard for token usage, prompt-cache reuse and estimated credits, fixed to the current chat. Always pass the current chat ID. Usage reflects completed recorded model calls.",
                       inputSchema=dashboard_selection, annotations=ANNOTATIONS, _meta=UI_META),
            types.Tool(name="refresh_cache_dashboard", title="Refresh cache dashboard",
                       description="Refresh Gauge for the current chat without a model call.",
                       inputSchema=dashboard_selection, annotations=ANNOTATIONS, _meta={"ui": {"visibility": ["app"]}}),
            types.Tool(name="list_cache_sessions", description="List locally recorded chats and token-weighted cache summaries. Conversation text is excluded.",
                       inputSchema={"type": "object", "properties": {"include_internal": internal_option}, "additionalProperties": False}, annotations=ANNOTATIONS),
            types.Tool(name="get_cache_history", description="Get completed model-call history and per-prompt token-weighted totals for one chat.",
                       inputSchema={**selection, "required": ["session_id"]}, annotations=ANNOTATIONS),
            types.Tool(name="get_cache_summary", description="Get whole-chat, latest-call and latest-prompt cache reuse for a specified chat.",
                       inputSchema={**selection, "required": ["session_id"]}, annotations=ANNOTATIONS),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        sid, limit = arguments.get("session_id"), arguments.get("limit", 500)
        if name in ("show_cache_dashboard", "refresh_cache_dashboard"):
            if not isinstance(sid, str) or not sid.strip():
                return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text="Open the monitor with the current chat ID.")])
            data = monitor.dashboard(sid, limit)
            data["sessions"] = [session for session in data["sessions"] if session["id"] == sid]
            detail = data["detail"]
            text = summary_text(detail) if detail else "Waiting for this chat's usage records. The dashboard remains fixed to this chat."
        elif name == "list_cache_sessions":
            data = {"sessions": monitor.store.sessions(include_internal=arguments.get("include_internal", False)), "collector": monitor.collector.status()}
            text = json.dumps(data)
        elif name in ("get_cache_summary", "get_cache_history"):
            try:
                data = monitor.store.history(sid, limit)
            except KeyError:
                return types.CallToolResult(isError=True, content=[types.TextContent(type="text", text="Chat not found. List sessions, or wait for the initial scan to finish.")])
            if name == "get_cache_summary":
                latest_turn = {k: data["turns"][-1][k] for k in ("id", "attributed", "timestamp", "summary")} if data["turns"] else None
                data = {k: data[k] for k in ("session", "summary", "usage_by_model", "latest", "quality", "last_record_at") } | {"latest_turn": latest_turn}
            text = summary_text(data)
        else:
            raise ValueError("Unknown tool")
        if name == "show_cache_dashboard":
            # The full chart payload is UI-only, keeping monitoring data out of model context.
            compact = {"selected_session_id": sid, "session_count": len(data["sessions"]),
                       "summary": data["detail"]["summary"] if data["detail"] else None}
            return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                        structuredContent=compact, _meta={"dashboard": data})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)], structuredContent=data)

    @server.list_resources()
    async def list_resources():
        return [types.Resource(uri=URI, name="Gauge dashboard", mimeType=MIME,
                               description="Self-contained dashboard; all data refreshes go through MCP tools.",
                               _meta=RESOURCE_META)]

    @server.read_resource()
    async def read_resource(uri):
        if str(uri) != URI:
            raise ValueError("Unknown resource")
        return [ReadResourceContents((WEB / "mcp-app.html").read_text(encoding="utf-8"), MIME,
                                     RESOURCE_META)]

    return server


def summary_text(data):
    summary = data["summary"]
    ratio = summary["cache_reuse"]
    rate = f"{100 * ratio:.2f}%" if ratio is not None else "unavailable"
    kind = "Internal review" if data["session"].get("session_kind") == "internal_review" else "Chat"
    return (f"{kind} {data['session']['id']}: cache reuse {rate}; "
            f"{summary['cached_input_tokens']:,} cached / {summary['input_tokens']:,} input tokens "
            f"across {summary['calls']} completed calls. Data quality: {data['quality']['status']}. "
            "This measures reported prompt-cache token reuse. Unfinished calls have no usage yet.")


async def run(monitor: Monitor):
    server = create_server(monitor)
    async with stdio_server() as (read, write):
        await server.run(read, write, InitializationOptions(
            server_name="gauge", server_version="0.1.0",
            capabilities=types.ServerCapabilities(
                tools=types.ToolsCapability(listChanged=False), resources=types.ResourcesCapability(),
                extensions={"io.modelcontextprotocol/ui": {"mimeTypes": [MIME]}},
            ),
            instructions="Gauge is a read-only local Codex token, prompt-cache and estimated-credit monitor. Use the chat ID supplied by the user or current chat context; never silently select the most recently active unrelated chat. No model calls are needed for dashboard refresh.",
        ))
