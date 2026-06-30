from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from godot_ui_feedback_mcp import core
from godot_ui_feedback_mcp import feedback_bridge


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def get_tool_registry() -> dict[str, ToolHandler]:
    return {
        "capture_godot_ui_reference": _handle_capture_godot_ui_reference,
        "generate_godot_ui_proxy": _handle_generate_godot_ui_proxy,
        "parse_browser_feedback": _handle_parse_browser_feedback,
        "suggest_godot_scenes": _handle_suggest_godot_scenes,
        "ensure_exporter_installed": _handle_ensure_exporter_installed,
        "describe_workflow": _handle_describe_workflow,
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise core.InvalidToolArgumentsError("Tool arguments must be a JSON object")
    registry = get_tool_registry()
    if name not in registry:
        raise core.InvalidToolArgumentsError(f"Unknown UI feedback MCP tool: {name}")
    return registry[name](arguments)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UI Feedback Bridge MCP server.")
    parser.add_argument("--list-tools", action="store_true", help="Print tool names as JSON and exit.")
    parser.add_argument("--call-tool", help="Call one tool directly with --arguments JSON. Useful for smoke tests.")
    parser.add_argument("--arguments", default="{}", help="JSON object for --call-tool.")
    parser.add_argument("--arguments-file", help="Path to a JSON object file for --call-tool.")
    args = parser.parse_args(argv)

    if args.list_tools:
        print(json.dumps(sorted(get_tool_registry().keys()), ensure_ascii=False))
        return 0
    if args.call_tool:
        raw_arguments = Path(args.arguments_file).read_text(encoding="utf-8-sig") if args.arguments_file else args.arguments
        result = call_tool(args.call_tool, json.loads(raw_arguments))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    return _run_mcp_server()


def dispatch_json_rpc(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    try:
        if method == "initialize":
            return _rpc_result(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ui-feedback-bridge", "version": "0.1.0"},
            })
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return _rpc_result(request_id, {"tools": _tool_descriptions()})
        if method == "tools/call":
            params = message.get("params", {})
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = call_tool(name, arguments)
            return _rpc_result(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]})
        return _rpc_error(request_id, -32601, f"Method not found: {method}")
    except core.InvalidToolArgumentsError as exc:
        return _rpc_error(request_id, -32602, str(exc))
    except Exception as exc:
        return _rpc_error(request_id, -32000, str(exc))


def _handle_capture_godot_ui_reference(arguments: dict[str, Any]) -> dict[str, Any]:
    _reject_removed_arguments(arguments)
    return core.capture_godot_ui_reference(
        project_path=_required(arguments, "project_path"),
        scene_path=_required(arguments, "scene_path"),
        out_path=_required(arguments, "out_path"),
        width=arguments.get("width", 1280),
        height=arguments.get("height", 720),
        title=str(arguments.get("title", "Godot UI Capture")),
        calls=arguments.get("calls"),
        timeout_seconds=arguments.get("timeout_seconds", 60),
    )


def _handle_generate_godot_ui_proxy(arguments: dict[str, Any]) -> dict[str, Any]:
    _reject_removed_arguments(arguments)
    return core.generate_godot_ui_proxy(
        project_path=_required(arguments, "project_path"),
        scene_path=_required(arguments, "scene_path"),
        out_path=_required(arguments, "out_path"),
        width=arguments.get("width", 1280),
        height=arguments.get("height", 720),
        title=str(arguments.get("title", "Godot UI Proxy")),
        calls=arguments.get("calls"),
        timeout_seconds=arguments.get("timeout_seconds", 60),
    )


def _handle_parse_browser_feedback(arguments: dict[str, Any]) -> dict[str, Any]:
    comments_text = _required(arguments, "comments_text")
    records = feedback_bridge.parse_browser_comments(comments_text)
    return {
        "records": records,
        "markdown": feedback_bridge.render_markdown(records),
    }


def _handle_suggest_godot_scenes(arguments: dict[str, Any]) -> dict[str, Any]:
    suggestions = core.suggest_godot_scenes(
        _required(arguments, "project_path"),
        str(arguments.get("description", "")),
        arguments.get("limit", 10),
    )
    return {"suggestions": suggestions}


def _handle_ensure_exporter_installed(arguments: dict[str, Any]) -> dict[str, Any]:
    return core.ensure_exporter_installed(_required(arguments, "project_path"))


def _handle_describe_workflow(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"text": core.describe_workflow()}


def _required(arguments: dict[str, Any], key: str) -> Any:
    if key not in arguments or arguments[key] in ("", None):
        raise core.InvalidToolArgumentsError(f"Missing required argument: {key}")
    return arguments[key]


def _reject_removed_arguments(arguments: dict[str, Any]) -> None:
    if "godot_bin" in arguments:
        raise core.InvalidToolArgumentsError("godot_bin is no longer accepted as a tool argument; set GODOT_BIN in the MCP server environment")


def _run_mcp_server() -> int:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return _run_minimal_stdio_server()

    mcp = FastMCP("ui-feedback-bridge")

    @mcp.tool()
    def capture_godot_ui_reference(
        project_path: str,
        scene_path: str,
        out_path: str,
        width: int = 1280,
        height: int = 720,
        title: str = "Godot UI Capture",
        calls: list[str] | None = None,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Capture a real Godot UI screenshot and node metadata from a scene."""
        return _handle_capture_godot_ui_reference(locals())

    @mcp.tool()
    def generate_godot_ui_proxy(
        project_path: str,
        scene_path: str,
        out_path: str,
        width: int = 1280,
        height: int = 720,
        title: str = "Godot UI Proxy",
        calls: list[str] | None = None,
        timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        """Deprecated alias for capture_godot_ui_reference."""
        return _handle_generate_godot_ui_proxy(locals())

    @mcp.tool()
    def parse_browser_feedback(comments_text: str) -> dict[str, Any]:
        """Parse Codex browser comments into Godot-targeted feedback records."""
        return _handle_parse_browser_feedback(locals())

    @mcp.tool()
    def suggest_godot_scenes(project_path: str, description: str = "", limit: int = 10) -> dict[str, Any]:
        """Suggest Godot scenes that may match a screenshot or text description."""
        return _handle_suggest_godot_scenes(locals())

    @mcp.tool()
    def ensure_exporter_installed(project_path: str) -> dict[str, Any]:
        """Install the managed Godot capture exporter scripts into the target Godot project."""
        return _handle_ensure_exporter_installed(locals())

    @mcp.tool()
    def describe_workflow() -> dict[str, Any]:
        """Describe the screenshot-to-proxy-to-feedback workflow."""
        return _handle_describe_workflow({})

    mcp.run()
    return 0


def _run_minimal_stdio_server() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            print(json.dumps(_rpc_error(None, -32700, str(exc)), ensure_ascii=False), flush=True)
            continue
        response = dispatch_json_rpc(request)
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def _tool_descriptions() -> list[dict[str, Any]]:
    capture_properties = {
        "project_path": {"type": "string"},
        "scene_path": {"type": "string"},
        "out_path": {"type": "string", "description": "Must be under res://docs/ui_proxy/ and end with .html."},
        "width": {"type": "integer", "default": 1280, "minimum": 320, "maximum": 3840},
        "height": {"type": "integer", "default": 720, "minimum": 240, "maximum": 2160},
        "title": {"type": "string", "default": "Godot UI Capture"},
        "calls": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "Optional root-node methods named _mcp_capture_* to enter a capture state.",
        },
        "timeout_seconds": {"type": "integer", "default": 60, "minimum": 1, "maximum": 120},
    }
    return [
        {
            "name": "capture_godot_ui_reference",
            "description": "Capture a real Godot UI screenshot and node metadata from a scene.",
            "inputSchema": {
                "type": "object",
                "properties": capture_properties,
                "required": ["project_path", "scene_path", "out_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "generate_godot_ui_proxy",
            "description": "Deprecated alias for capture_godot_ui_reference.",
            "inputSchema": {
                "type": "object",
                "properties": capture_properties,
                "required": ["project_path", "scene_path", "out_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "parse_browser_feedback",
            "description": "Parse Codex browser comments into Godot-targeted feedback records.",
            "inputSchema": {
                "type": "object",
                "properties": {"comments_text": {"type": "string"}},
                "required": ["comments_text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "suggest_godot_scenes",
            "description": "Suggest Godot scenes for a screenshot or text description.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project_path": {"type": "string"},
                    "description": {"type": "string", "default": ""},
                    "limit": {"type": "integer", "default": 10, "minimum": 1, "maximum": 100},
                },
                "required": ["project_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "ensure_exporter_installed",
            "description": "Install the managed Godot capture exporter scripts into the target project.",
            "inputSchema": {
                "type": "object",
                "properties": {"project_path": {"type": "string"}},
                "required": ["project_path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "describe_workflow",
            "description": "Describe the screenshot-to-proxy-to-feedback workflow.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ]


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    raise SystemExit(main())
