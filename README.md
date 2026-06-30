# UI Feedback Bridge MCP

This MCP captures real Godot UI screenshots and node metadata for a
browser-annotatable workflow.

It is designed for this real-world loop:

1. The user provides a screenshot or text description of the game UI surface.
2. The agent calls `suggest_godot_scenes` to find likely Godot scene files.
3. The agent calls `ensure_exporter_installed` if the target project does not already have the exporter scripts.
4. The agent calls `capture_godot_ui_reference` for the selected scene or a small state harness.
5. Codex uses the captured screenshot as the visual source of truth and creates a separate structured HTML proxy that visually recreates the screen.
6. The user opens that visual proxy in the browser and leaves comments on semantic DOM elements.
7. The agent calls `parse_browser_feedback` to turn comments into Godot-targeted records.
8. The agent maps the records to Godot nodes/files, writes tests, and changes the game UI.

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
  "title": "Main UI Proxy",
  "godot_bin": "godot",
  "calls": ["_on_difficulty_selected:0"]
}
```

Output includes the generated capture file path, screenshot path, command, and
exported Godot UI node count.
Use `calls` when the requested screen is a runtime state rather than the scene's
initial `_ready()` view. If a screen needs setup that cannot be expressed as a
simple method call, create a small Godot scene or script harness that opens that
state, then export the harness.

Use a `*-capture.html` name for this output when possible. The generated HTML
is a capture artifact, not the final review proxy. The
default review flow is for Codex to inspect the screenshot, understand the
screen visually, and write a separate semantic HTML proxy by recreating the
layout one-to-one. Do not auto-slice the screenshot into the final proxy.

### `ensure_exporter_installed`

Input:

```json
{
  "project_path": "C:/path/to/GodotProject"
}
```

Output lists copied exporter scripts. `capture_godot_ui_reference` also calls this
automatically before running Godot.

### `generate_godot_ui_proxy`

Deprecated compatibility alias for `capture_godot_ui_reference`. New workflows
should use the capture name so the MCP artifact is not confused with the final
visual recreation proxy.

### `parse_browser_feedback`

Input:

```json
{
  "comments_text": "# Browser comments:\n\n## Comment 1\n..."
}
```

Output includes structured records and Markdown intake notes. Records target Godot by default.

### `describe_workflow`

Returns the end-to-end usage flow.

## Local Smoke Tests

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

The Python `mcp` package is required only for stdio server mode. The core API
and tests do not require it.
