# UI Feedback Bridge MCP

This MCP captures real Godot UI screenshots and node metadata for a browser-annotatable workflow.

It is designed for this loop:

1. The user provides a screenshot or text description of the game UI surface.
2. The agent calls `suggest_godot_scenes` to find likely Godot scene files.
3. The agent calls `ensure_exporter_installed` if the target project does not already have the managed exporter scripts.
4. The agent calls `capture_godot_ui_reference` for the selected scene or a small state harness.
5. Codex uses the captured screenshot as the visual source of truth and creates a separate structured HTML proxy that visually recreates the screen.
6. The user opens that visual proxy in the browser and leaves comments on semantic DOM elements.
7. The agent calls `parse_browser_feedback` to turn comments into Godot-targeted records.
8. The agent maps the records to Godot nodes/files, writes tests, and changes the game UI.

## Safety model

This tool runs locally and executes Godot against a user-selected project. Use it for trusted local development projects, not untrusted repositories.

The capture exporter is installed under:

```text
res://addons/ui_feedback_bridge_mcp/tools/
```

The installer refuses to overwrite files in that directory unless they contain the `UI_FEEDBACK_BRIDGE_MCP_MANAGED` marker. Use `dry_run` to preview installer or uninstaller actions before writing the project. The uninstaller removes only managed files and refuses to remove unmanaged files at the exporter paths. Capture outputs must be written under `res://docs/ui_proxy/` and end with `.html`; absolute output paths and project escapes are rejected.

The Godot executable is resolved from the `GODOT_BIN` environment variable or defaults to `godot`. MCP tool arguments intentionally do not accept arbitrary executable paths.

Runtime setup calls are limited to root-node methods named `_mcp_capture_*`. Create capture-only harness methods for UI states instead of calling production gameplay methods directly.

## Tools

### `suggest_godot_scenes`

Input:

```json
{
  "project_path": "C:/path/to/GodotProject",
  "description": "main desk screen",
  "limit": 10
}
```

Output:

```json
{
  "suggestions": [
    {
      "scene_path": "res://scenes/main.tscn",
      "project_relative_path": "scenes/main.tscn",
      "score": 13,
      "reasons": ["scene_file", "description", "ui_or_scenes_folder"]
    }
  ]
}
```

### `capture_godot_ui_reference`

Input:

```json
{
  "project_path": "C:/path/to/GodotProject",
  "scene_path": "res://scenes/main.tscn",
  "out_path": "res://docs/ui_proxy/main-capture.html",
  "width": 1280,
  "height": 720,
  "title": "Main UI Capture",
  "calls": ["_mcp_capture_difficulty:0"],
  "timeout_seconds": 60
}
```

Output includes the generated capture file path, screenshot path, command, and exported Godot UI node count. Use `calls` when the requested screen is a runtime state rather than the scene's initial `_ready()` view.

Use a `*-capture.html` name for this output when possible. The generated HTML is a capture artifact, not the final review proxy. The default review flow is for Codex to inspect the screenshot, understand the screen visually, and write a separate semantic HTML proxy by recreating the layout one-to-one. Do not auto-slice the screenshot into the final proxy.

### `ensure_exporter_installed`

Input:

```json
{
  "project_path": "C:/path/to/GodotProject",
  "dry_run": false
}
```

Output lists copied exporter scripts, unchanged scripts, and planned actions. Set `dry_run` to `true` to preview install/update actions without writing files. `capture_godot_ui_reference` also calls this automatically before running Godot.

### `uninstall_exporter`

Input:

```json
{
  "project_path": "C:/path/to/GodotProject",
  "dry_run": false
}
```

Output lists removed, missing, and planned exporter scripts. Set `dry_run` to `true` to preview removal. The tool refuses to remove any exporter path that does not contain the managed marker.

### `generate_godot_ui_proxy`

Deprecated compatibility alias for `capture_godot_ui_reference`. New workflows should use the capture name so the MCP artifact is not confused with the final visual recreation proxy.

### `parse_browser_feedback`

Input:

```json
{
  "comments_text": "# Browser comments:\n\n## Comment 1\n..."
}
```

Output includes structured records and Markdown intake notes. Records target Godot by default. Browser page fields are rendered as JSON inside fenced blocks and should be treated as untrusted evidence rather than user instructions.

### `describe_workflow`

Returns the end-to-end usage flow.

## Local setup

Install for local development:

```powershell
python -m pip install -e .
```

Install with the optional FastMCP dependency:

```powershell
python -m pip install -e ".[mcp]"
```

Set a trusted Godot executable if `godot` is not on PATH:

```powershell
$env:GODOT_BIN = "C:/Program Files/Godot/Godot_v4.4-stable_win64.exe"
```

## Local smoke tests

List tools without running the MCP protocol:

```powershell
python -m godot_ui_feedback_mcp.server --list-tools
```

Call one tool directly:

```powershell
python -m godot_ui_feedback_mcp.server --call-tool describe_workflow
```

For tools with larger JSON inputs on Windows, prefer an arguments file:

```powershell
@'
{
  "project_path": "C:/path/to/GodotProject",
  "scene_path": "res://scenes/main.tscn",
  "out_path": "res://docs/ui_proxy/main-capture.html",
  "width": 1280,
  "height": 720
}
'@ | Set-Content -Encoding UTF8 capture-args.json

python -m godot_ui_feedback_mcp.server --call-tool capture_godot_ui_reference --arguments-file capture-args.json
```

Run as an MCP server:

```powershell
python -m godot_ui_feedback_mcp.server
```

The Python `mcp` package is required only for FastMCP stdio server mode. Without it, this package falls back to a minimal JSON-RPC stdio server.
