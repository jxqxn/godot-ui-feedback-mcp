from __future__ import annotations

import os
import re
import subprocess
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any


class UiFeedbackMcpError(RuntimeError):
    """Raised when a UI feedback MCP operation cannot run safely."""


class InvalidToolArgumentsError(UiFeedbackMcpError):
    """Raised when a caller provides invalid MCP tool arguments."""


EXPORTER_MANAGED_MARKER = "UI_FEEDBACK_BRIDGE_MCP_MANAGED"
EXPORTER_TARGET_PREFIX = PurePosixPath("addons/ui_feedback_bridge_mcp/tools")
SAFE_OUTPUT_PREFIX = PurePosixPath("docs/ui_proxy")
MAX_STDIO_CHARS = 4000
MAX_CALLS = 10
MAX_CALL_LENGTH = 200
CAPTURE_METHOD_RE = re.compile(r"^_mcp_capture_[A-Za-z0-9_]*$")
ALLOWED_GODOT_BIN_BASENAMES = {"godot", "godot4", "godot.exe", "godot4.exe"}
DEFAULT_CONTEXT_SCENE_LIMIT = 20
DEFAULT_CONTEXT_ASSET_LIMIT = 50
MAX_CONTEXT_FILE_CHARS = 200_000
MAX_CONTEXT_FILES_SCANNED = 5000
MAX_CONTEXT_SCENE_FILES_READ = 500
STRONG_UI_SCENE_ROOTS = {"ui", "gui", "hud", "menus"}
IGNORED_SCAN_ROOTS = {".godot", ".import", "addons", "build", "dist", "export"}
UI_PATH_TOKENS = ("ui", "gui", "hud", "menu", "menus", "panel", "button", "icon", "font", "theme")
UI_CONTROL_TYPES = {
    "AcceptDialog",
    "BoxContainer",
    "Button",
    "CanvasLayer",
    "CenterContainer",
    "CheckBox",
    "ColorPicker",
    "ColorRect",
    "ConfirmationDialog",
    "Container",
    "Control",
    "FileDialog",
    "FlowContainer",
    "GridContainer",
    "HBoxContainer",
    "HFlowContainer",
    "HScrollBar",
    "HSeparator",
    "HSlider",
    "ItemList",
    "Label",
    "LineEdit",
    "MarginContainer",
    "MenuButton",
    "NinePatchRect",
    "OptionButton",
    "Panel",
    "PanelContainer",
    "Popup",
    "PopupMenu",
    "ProgressBar",
    "ReferenceRect",
    "RichTextLabel",
    "ScrollContainer",
    "SpinBox",
    "TabBar",
    "TabContainer",
    "TextEdit",
    "TextureButton",
    "TextureProgressBar",
    "TextureRect",
    "Tree",
    "VBoxContainer",
    "VFlowContainer",
    "VideoStreamPlayer",
    "VScrollBar",
    "VSeparator",
    "VSlider",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".tga"}
FONT_EXTENSIONS = {".ttf", ".otf", ".woff", ".woff2", ".fnt", ".font"}
THEME_EXTENSIONS = {".tres", ".res"}
NODE_RE = re.compile(r'^\[node\s+([^\]]+)\]', re.MULTILINE)
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
RESOURCE_PATH_RE = re.compile(r'path="(res://[^"]+)"')
PROPERTY_RE = re.compile(r"^([A-Za-z0-9_./]+)\s*=\s*(.+)$")


class _ExporterFile:
    def __init__(self, source_rel: str, target_rel: str) -> None:
        self.source_rel = PurePosixPath(source_rel)
        self.target_rel = PurePosixPath(target_rel)


EXPORTER_FILES = [
    _ExporterFile("tools/export_ui_proxy.gd", "addons/ui_feedback_bridge_mcp/tools/export_ui_proxy.gd"),
    _ExporterFile("tools/ui_proxy_exporter.gd", "addons/ui_feedback_bridge_mcp/tools/ui_proxy_exporter.gd"),
]


def validate_godot_project(project_path: str | Path) -> dict[str, str]:
    project = Path(project_path).expanduser().resolve()
    project_file = project / "project.godot"
    if not project_file.is_file():
        raise InvalidToolArgumentsError(f"Godot project file not found: {project_file}")
    return {
        "project_path": str(project),
        "project_file": str(project_file),
    }


def suggest_godot_scenes(project_path: str | Path, description: str = "", limit: int = 10) -> list[dict[str, Any]]:
    project = Path(validate_godot_project(project_path)["project_path"])
    limit = _validate_int("limit", limit, minimum=1, maximum=100)
    terms = _tokenize(str(description)[:1000])
    suggestions: list[dict[str, Any]] = []
    for scene in sorted(project.rglob("*.tscn")):
        rel = scene.relative_to(project).as_posix()
        if _is_ignored_scan_path(rel):
            continue
        scene_path = "res://" + rel
        haystack = _tokenize(rel.replace("/", " ") + " " + scene.stem)
        score = 1
        reasons = ["scene_file"]
        if terms:
            matches = terms.intersection(haystack)
            if matches:
                score += 10 * len(matches)
                reasons.append("description")
        if rel.startswith(("scenes/", "ui/")):
            score += 2
            reasons.append("ui_or_scenes_folder")
        suggestions.append({
            "scene_path": scene_path,
            "project_relative_path": rel,
            "score": score,
            "reasons": reasons,
        })
    suggestions.sort(key=lambda item: (-int(item["score"]), str(item["scene_path"])))
    return suggestions[:limit]


def collect_godot_ui_context(
    project_path: str | Path,
    *,
    scene_limit: int = DEFAULT_CONTEXT_SCENE_LIMIT,
    asset_limit: int = DEFAULT_CONTEXT_ASSET_LIMIT,
) -> dict[str, Any]:
    project = Path(validate_godot_project(project_path)["project_path"])
    scene_limit = _validate_int("scene_limit", scene_limit, minimum=1, maximum=100)
    asset_limit = _validate_int("asset_limit", asset_limit, minimum=1, maximum=200)
    scenes = _collect_ui_scenes(project, scene_limit)
    themes = _collect_theme_paths(project, asset_limit)
    fonts = _collect_resource_paths(project, FONT_EXTENSIONS, asset_limit, ui_only=True)
    image_assets = _collect_resource_paths(project, IMAGE_EXTENSIONS, asset_limit, ui_only=True)
    referenced_resources = sorted({
        resource
        for scene in scenes
        for resource in scene["referenced_resources"]
    })[:asset_limit]
    referenced_ui_assets = [
        resource for resource in referenced_resources if PurePosixPath(resource.removeprefix("res://")).suffix.lower()
        in IMAGE_EXTENSIONS.union(FONT_EXTENSIONS, THEME_EXTENSIONS)
    ][:asset_limit]
    style_notes = _build_style_notes(scenes, themes, fonts, image_assets)
    return {
        "project_path": str(project),
        "scope": "new_page_design_context",
        "limits": {
            "scene_limit": scene_limit,
            "asset_limit": asset_limit,
            "max_file_chars": MAX_CONTEXT_FILE_CHARS,
            "max_files_scanned_per_pass": MAX_CONTEXT_FILES_SCANNED,
            "max_scene_files_read": MAX_CONTEXT_SCENE_FILES_READ,
        },
        "ui_scenes": scenes,
        "themes": themes,
        "fonts": fonts,
        "candidate_ui_assets": image_assets,
        "image_assets": image_assets,
        "referenced_ui_assets": referenced_ui_assets,
        "referenced_resources": referenced_resources,
        "recommended_reference_scenes": _recommend_reference_scenes(scenes),
        "style_notes": style_notes,
        "confidence": "partial_static_context",
        "limitations": [
            "Static scanning can miss runtime UI state, theme inheritance, shader effects, dynamic text, and script-driven layout changes.",
            "Use full-screen capture_godot_ui_reference results as the reliable basis before making visual design decisions.",
        ],
        "visual_evidence_rule": "Always treat complete Godot screenshots from capture_godot_ui_reference as the reliable visual basis. Static context is only candidate/supporting evidence.",
        "next_step": "Capture complete representative screens, then use this context as supporting evidence to create a separate semantic HTML design proxy for the new page.",
    }


def ensure_exporter_installed(project_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    project = Path(validate_godot_project(project_path)["project_path"])
    dry_run = _validate_bool("dry_run", dry_run)
    installed: list[str] = []
    unchanged: list[str] = []
    planned_files: list[dict[str, str]] = []
    for exporter_file in EXPORTER_FILES:
        target = _resolve_managed_target(project, exporter_file.target_rel)
        source_text = _read_exporter_template(exporter_file)
        if EXPORTER_MANAGED_MARKER not in source_text:
            raise UiFeedbackMcpError(f"Exporter template is missing managed marker: {exporter_file.source_rel}")
        action = "install"
        if target.is_file():
            existing_text = target.read_text(encoding="utf-8")
            if existing_text == source_text:
                unchanged.append(exporter_file.target_rel.as_posix())
                planned_files.append({"path": exporter_file.target_rel.as_posix(), "action": "unchanged"})
                continue
            if EXPORTER_MANAGED_MARKER not in existing_text:
                raise UiFeedbackMcpError(
                    "Refusing to overwrite unmanaged Godot file: "
                    f"{target}. Remove or rename it, then run ensure_exporter_installed again."
                )
            action = "update"
        planned_files.append({"path": exporter_file.target_rel.as_posix(), "action": action})
        if dry_run:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text, encoding="utf-8")
        installed.append(exporter_file.target_rel.as_posix())
    return {
        "project_path": str(project),
        "dry_run": dry_run,
        "installed_files": installed,
        "unchanged_files": unchanged,
        "planned_files": planned_files,
        "managed_prefix": "res://" + EXPORTER_TARGET_PREFIX.as_posix(),
    }


def uninstall_exporter(project_path: str | Path, dry_run: bool = False) -> dict[str, Any]:
    project = Path(validate_godot_project(project_path)["project_path"])
    dry_run = _validate_bool("dry_run", dry_run)
    removed: list[str] = []
    missing: list[str] = []
    planned_files: list[dict[str, str]] = []
    for exporter_file in EXPORTER_FILES:
        target = _resolve_managed_target(project, exporter_file.target_rel)
        rel = exporter_file.target_rel.as_posix()
        if not target.exists():
            missing.append(rel)
            planned_files.append({"path": rel, "action": "missing"})
            continue
        if not target.is_file():
            raise UiFeedbackMcpError(f"Refusing to remove non-file exporter path: {target}")
        existing_text = target.read_text(encoding="utf-8")
        if EXPORTER_MANAGED_MARKER not in existing_text:
            raise UiFeedbackMcpError(f"Refusing to remove unmanaged Godot file: {target}")
        planned_files.append({"path": rel, "action": "remove"})
        if dry_run:
            continue
        target.unlink()
        removed.append(rel)
    if not dry_run:
        _remove_empty_managed_dirs(project)
    return {
        "project_path": str(project),
        "dry_run": dry_run,
        "removed_files": removed,
        "missing_files": missing,
        "planned_files": planned_files,
        "managed_prefix": "res://" + EXPORTER_TARGET_PREFIX.as_posix(),
    }


def build_capture_reference_command(
    *,
    project_path: str | Path,
    scene_path: str,
    out_path: str,
    width: int = 1280,
    height: int = 720,
    title: str = "Godot UI Capture",
    godot_bin: str | None = None,
    calls: list[str] | None = None,
) -> list[str]:
    project_path_obj = Path(project_path).expanduser().resolve()
    width = _validate_int("width", width, minimum=320, maximum=3840)
    height = _validate_int("height", height, minimum=240, maximum=2160)
    title = _validate_text("title", title, maximum=200)
    godot_bin = _validate_godot_bin(godot_bin)
    calls = _validate_calls(calls)
    script_path = str((project_path_obj / EXPORTER_TARGET_PREFIX.as_posix() / "export_ui_proxy.gd").resolve())
    command = [
        godot_bin,
        "--resolution",
        "%dx%d" % (width, height),
        "--path",
        str(project_path_obj),
        "--script",
        script_path,
        "--",
        "--scene",
        scene_path,
        "--out",
        out_path,
        "--title",
        title,
        "--width",
        str(width),
        "--height",
        str(height),
    ]
    for call in calls:
        command.extend(["--call", call])
    return command


def build_generate_proxy_command(**kwargs) -> list[str]:
    """Backward-compatible alias for older callers."""
    return build_capture_reference_command(**kwargs)


def capture_godot_ui_reference(
    *,
    project_path: str | Path,
    scene_path: str,
    out_path: str,
    width: int = 1280,
    height: int = 720,
    title: str = "Godot UI Capture",
    godot_bin: str | None = None,
    calls: list[str] | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    project = Path(validate_godot_project(project_path)["project_path"])
    _resolve_scene_path(project, scene_path)
    output_file = _resolve_safe_output_path(project, out_path)
    screenshot_file = output_file.with_suffix(".png")
    timeout_seconds = _validate_int("timeout_seconds", timeout_seconds, minimum=1, maximum=120)
    install_result = ensure_exporter_installed(project)
    command = build_capture_reference_command(
        project_path=project,
        scene_path=scene_path,
        out_path=out_path,
        width=width,
        height=height,
        title=title,
        godot_bin=godot_bin,
        calls=calls,
    )
    try:
        completed = subprocess.run(
            command,
            cwd=str(project),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UiFeedbackMcpError(
            "Godot UI capture timed out after %d seconds\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (timeout_seconds, _truncate(exc.stdout or ""), _truncate(exc.stderr or ""))
        ) from exc
    if completed.returncode != 0:
        raise UiFeedbackMcpError(
            "Godot UI capture failed with exit code %d\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (completed.returncode, _truncate(completed.stdout), _truncate(completed.stderr))
        )
    if not output_file.is_file():
        raise UiFeedbackMcpError(f"Godot reported success but capture HTML was not created: {output_file}")
    if not screenshot_file.is_file():
        raise UiFeedbackMcpError(f"Godot reported success but screenshot was not created: {screenshot_file}")
    node_count = _count_proxy_nodes(output_file)
    return {
        "project_path": str(project),
        "scene_path": scene_path,
        "out_path": out_path,
        "output_file": str(output_file),
        "screenshot_file": str(screenshot_file),
        "node_count": node_count,
        "artifact_role": "capture_reference",
        "review_proxy_next_step": "Create a separate semantic HTML visual recreation from the screenshot; do not use this capture artifact as the user review page.",
        "naming_warning": _capture_naming_warning(output_file),
        "exporter_install": install_result,
        "command": command,
        "stdout": _truncate(completed.stdout),
        "stderr": _truncate(completed.stderr),
    }


def generate_godot_ui_proxy(**kwargs) -> dict[str, Any]:
    """Backward-compatible alias for capture_godot_ui_reference."""
    result = capture_godot_ui_reference(**kwargs)
    result["deprecated_alias"] = "generate_godot_ui_proxy"
    return result


def describe_workflow() -> str:
    return "\n".join([
        "UI Feedback MCP workflow:",
        "1. The user provides text, a partial screenshot, or a full screenshot identifying the game UI surface.",
        "2. Call suggest_godot_scenes to find likely Godot scenes for that surface.",
        "3. Optionally call collect_godot_ui_context when the fix should preserve broader project UI style, resources, or layout conventions.",
        "4. Call ensure_exporter_installed if the target project does not already have the managed exporter scripts.",
        "5. Call capture_godot_ui_reference for the selected scene or a small state harness to capture the real Godot screenshot and node metadata.",
        "6. Treat the complete capture screenshot as the reliable evidence for existing-page fixes; context is only supporting evidence.",
        "7. The agent reads the screenshot and creates a separate structured HTML proxy by visually recreating the screen.",
        "8. Open that visual proxy in the browser and let the user place comments on semantic DOM elements.",
        "9. Call parse_browser_feedback to turn browser comments into Godot-targeted records.",
        "10. Map those records to Godot files/nodes, write tests, implement, and ask for real-game retest.",
        "",
        "New page design workflow:",
        "1. Call collect_godot_ui_context to gather bounded existing UI scene, Theme, font, asset, and layout context.",
        "2. Capture 1-3 complete representative existing screens so the new design has reliable visual anchors.",
        "3. Let the agent create a separate semantic HTML design proxy for review; the MCP provides context, not design judgment.",
    ])


def _resolve_scene_path(project: Path, scene_path: str) -> Path:
    rel = _resource_relative_path("scene_path", scene_path, suffix=".tscn")
    scene_file = (project / rel.as_posix()).resolve()
    _ensure_inside_project(project, scene_file, "scene_path")
    if not scene_file.is_file():
        raise InvalidToolArgumentsError(f"Scene file not found: {scene_file}")
    return scene_file


def _resolve_safe_output_path(project: Path, out_path: str) -> Path:
    rel = _resource_relative_path("out_path", out_path, suffix=".html")
    if not rel.is_relative_to(SAFE_OUTPUT_PREFIX):
        raise InvalidToolArgumentsError("out_path must be under res://docs/ui_proxy/ and end with .html")
    target = (project / rel.as_posix()).resolve()
    _ensure_inside_project(project, target, "out_path")
    return target


def _resolve_godot_path(project_path: str | Path, godot_path: str) -> Path:
    project = Path(project_path).resolve()
    rel = _resource_relative_path("godot_path", godot_path)
    target = (project / rel.as_posix()).resolve()
    _ensure_inside_project(project, target, "godot_path")
    return target


def _resource_relative_path(name: str, value: str, *, suffix: str | None = None) -> PurePosixPath:
    if not isinstance(value, str) or not value.startswith("res://"):
        raise InvalidToolArgumentsError(f"{name} must be a res:// path")
    raw_rel = value.removeprefix("res://")
    if raw_rel == "" or raw_rel.startswith("/") or "\\" in raw_rel:
        raise InvalidToolArgumentsError(f"{name} must be a normalized res:// path")
    rel = PurePosixPath(raw_rel)
    if any(part in ("", ".", "..") for part in rel.parts):
        raise InvalidToolArgumentsError(f"{name} may not contain empty, current, or parent path segments")
    if suffix and rel.suffix.lower() != suffix:
        raise InvalidToolArgumentsError(f"{name} must end with {suffix}")
    return rel


def _ensure_inside_project(project: Path, target: Path, name: str) -> None:
    try:
        target.relative_to(project)
    except ValueError as exc:
        raise InvalidToolArgumentsError(f"{name} resolves outside project: {target}") from exc


def _resolve_managed_target(project: Path, rel: PurePosixPath) -> Path:
    target = project / rel.as_posix()
    _ensure_managed_parent_inside_project(project, target.parent)
    if target.is_symlink():
        raise UiFeedbackMcpError(f"Refusing to follow symlink exporter path: {target}")
    return target


def _ensure_managed_parent_inside_project(project: Path, parent: Path) -> None:
    try:
        relative_parent = parent.relative_to(project)
    except ValueError as exc:
        raise InvalidToolArgumentsError(f"exporter target parent resolves outside project: {parent}") from exc
    current = project
    for part in relative_parent.parts:
        current = current / part
        if current.is_symlink():
            raise UiFeedbackMcpError(f"Refusing to use symlink exporter parent path: {current}")
        if current.exists():
            _ensure_inside_project(project, current.resolve(), "exporter target parent")


def _count_proxy_nodes(html_path: Path) -> int:
    if not html_path.is_file():
        return 0
    return html_path.read_text(encoding="utf-8").count("data-godot-node-path=")


def _capture_naming_warning(output_file: Path) -> str:
    stem = output_file.stem.lower()
    if stem.endswith("-capture") or stem.endswith("_capture"):
        return ""
    return "Capture artifacts should usually be named '*-capture.html' so they are not confused with the user-facing visual recreation proxy."


def _validate_int(name: str, value: Any, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise InvalidToolArgumentsError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidToolArgumentsError(f"{name} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise InvalidToolArgumentsError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _validate_text(name: str, value: Any, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise InvalidToolArgumentsError(f"{name} must be a string")
    if len(value) > maximum:
        raise InvalidToolArgumentsError(f"{name} must be at most {maximum} characters")
    return value


def _validate_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise InvalidToolArgumentsError(f"{name} must be a boolean")
    return value


def _validate_calls(calls: list[str] | None) -> list[str]:
    if calls is None:
        return []
    if not isinstance(calls, list):
        raise InvalidToolArgumentsError("calls must be an array of strings")
    if len(calls) > MAX_CALLS:
        raise InvalidToolArgumentsError(f"calls may contain at most {MAX_CALLS} entries")
    validated: list[str] = []
    for call in calls:
        if not isinstance(call, str):
            raise InvalidToolArgumentsError("calls must be an array of strings")
        if len(call) > MAX_CALL_LENGTH:
            raise InvalidToolArgumentsError(f"call entries must be at most {MAX_CALL_LENGTH} characters")
        method = call.split(":", 1)[0]
        if not CAPTURE_METHOD_RE.match(method):
            raise InvalidToolArgumentsError("calls may only target methods named _mcp_capture_* on the scene root")
        validated.append(call)
    return validated


def _validate_godot_bin(godot_bin: str | None = None) -> str:
    configured = os.environ.get("GODOT_BIN")
    value = godot_bin if godot_bin not in (None, "") else configured or "godot"
    if not isinstance(value, str):
        raise InvalidToolArgumentsError("godot_bin must be a string")
    if Path(value).name.lower() not in ALLOWED_GODOT_BIN_BASENAMES:
        raise InvalidToolArgumentsError(
            "Godot executable must be named godot/godot4. Configure a trusted path with the GODOT_BIN environment variable."
        )
    if godot_bin and ("/" in godot_bin or "\\" in godot_bin):
        raise InvalidToolArgumentsError("Tool arguments may not provide an executable path; set GODOT_BIN in the MCP server environment")
    return value


def _truncate(value: str | bytes | None, limit: int = MAX_STDIO_CHARS) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} characters]"


def _read_exporter_template(exporter_file: _ExporterFile) -> str:
    template_path = resources.files("godot_ui_feedback_mcp").joinpath(
        "templates",
        *exporter_file.source_rel.parts,
    )
    return template_path.read_text(encoding="utf-8")


def _iter_project_files(
    project: Path,
    *,
    suffixes: set[str] | None = None,
    max_files_scanned: int = MAX_CONTEXT_FILES_SCANNED,
):
    seen: set[Path] = set()
    scanned = 0
    roots = [project / root for root in sorted(STRONG_UI_SCENE_ROOTS.union({"scenes"}))]
    roots.append(project)
    for root in roots:
        if not root.exists() or root.is_symlink():
            continue
        for path in root.rglob("*"):
            if scanned >= max_files_scanned:
                return
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            scanned += 1
            if path in seen:
                continue
            seen.add(path)
            rel = path.relative_to(project).as_posix()
            if _is_ignored_scan_path(rel):
                continue
            if suffixes is not None and path.suffix.lower() not in suffixes:
                continue
            yield path


def _collect_ui_scenes(project: Path, scene_limit: int) -> list[dict[str, Any]]:
    scene_summaries: list[dict[str, Any]] = []
    scene_files_read = 0
    for scene in _iter_project_files(project, suffixes={".tscn"}):
        if scene_files_read >= MAX_CONTEXT_SCENE_FILES_READ:
            break
        rel = scene.relative_to(project).as_posix()
        if _is_ignored_scan_path(rel):
            continue
        scene_files_read += 1
        text = _read_limited_text(scene)
        nodes = _parse_scene_nodes(text)
        control_nodes = [node for node in nodes if _is_ui_node_type(node.get("type", ""))]
        referenced_resources = _extract_resource_paths(text)
        if not _is_probable_ui_scene(rel, control_nodes, referenced_resources):
            continue
        control_counts: dict[str, int] = {}
        for node in control_nodes:
            node_type = node.get("type", "")
            control_counts[node_type] = control_counts.get(node_type, 0) + 1
        root = nodes[0] if nodes else {}
        layout_summary = _summarize_layout_properties(control_nodes)
        style_overrides = _summarize_style_overrides(control_nodes)
        scene_summaries.append({
            "scene_path": "res://" + rel,
            "project_relative_path": rel,
            "root_name": root.get("name", ""),
            "root_type": root.get("type", ""),
            "control_count": len(control_nodes),
            "container_node_count": sum(1 for node in control_nodes if "Container" in node.get("type", "")),
            "control_types": sorted(control_counts.items(), key=lambda item: (-item[1], item[0]))[:20],
            "sample_node_names": [node.get("name", "") for node in control_nodes[:20] if node.get("name")],
            "layout_summary": layout_summary,
            "style_overrides": style_overrides,
            "referenced_resources": referenced_resources[:30],
        })
    scene_summaries.sort(key=lambda item: (-int(item["control_count"]), str(item["scene_path"])))
    return scene_summaries[:scene_limit]


def _collect_theme_paths(project: Path, limit: int) -> list[str]:
    themes: list[str] = []
    for path in _iter_project_files(project, suffixes=THEME_EXTENSIONS):
        if not path.is_file():
            continue
        rel = path.relative_to(project).as_posix()
        if _is_ignored_scan_path(rel) or path.suffix.lower() not in THEME_EXTENSIONS:
            continue
        lower_name = path.name.lower()
        if "theme" in lower_name:
            themes.append("res://" + rel)
        else:
            text = _read_limited_text(path, limit=20_000)
            if 'type="Theme"' in text or "[resource type=\"Theme\"" in text:
                themes.append("res://" + rel)
        if len(themes) >= limit:
            break
    return themes


def _collect_resource_paths(project: Path, extensions: set[str], limit: int, *, ui_only: bool = False) -> list[str]:
    resources_found: list[str] = []
    for path in _iter_project_files(project, suffixes=extensions):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        rel = path.relative_to(project).as_posix()
        if _is_ignored_scan_path(rel):
            continue
        if ui_only and not _looks_like_ui_resource(rel):
            continue
        resources_found.append("res://" + rel)
        if len(resources_found) >= limit:
            break
    return resources_found


def _parse_scene_nodes(text: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for match in NODE_RE.finditer(text):
        attrs = {key: value for key, value in ATTR_RE.findall(match.group(1))}
        attrs["properties"] = _node_properties_after(text, match.end())
        nodes.append(attrs)
    return nodes


def _node_properties_after(text: str, start: int) -> dict[str, str]:
    properties: dict[str, str] = {}
    for line in text[start:].splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("["):
            break
        match = PROPERTY_RE.match(stripped)
        if match:
            properties[match.group(1)] = match.group(2).strip()
    return properties


def _extract_resource_paths(text: str) -> list[str]:
    resources_found: list[str] = []
    seen: set[str] = set()
    for resource in RESOURCE_PATH_RE.findall(text):
        if resource not in seen:
            seen.add(resource)
            resources_found.append(resource)
    return resources_found


def _read_limited_text(path: Path, *, limit: int = MAX_CONTEXT_FILE_CHARS) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit)


def _is_ui_node_type(node_type: str) -> bool:
    if node_type in UI_CONTROL_TYPES:
        return True
    return node_type.endswith("Container") or node_type.endswith("Button") or node_type.endswith("Label")


def _is_probable_ui_scene(rel: str, control_nodes: list[dict[str, Any]], referenced_resources: list[str]) -> bool:
    root = rel.split("/", 1)[0].lower()
    if root in STRONG_UI_SCENE_ROOTS:
        return True
    if control_nodes:
        return True
    if root == "scenes" and any(_looks_like_ui_resource(resource.removeprefix("res://")) for resource in referenced_resources):
        return True
    return False


def _looks_like_ui_resource(rel: str) -> bool:
    normalized = rel.replace("\\", "/").lower()
    parts = normalized.replace("-", "_").split("/")
    stem = PurePosixPath(normalized).stem.replace("-", "_")
    tokens = set(parts)
    tokens.update(stem.split("_"))
    return any(token in UI_PATH_TOKENS or token.startswith("ui_") for token in tokens)


def _is_ignored_scan_path(rel: str) -> bool:
    return rel.split("/", 1)[0].lower() in IGNORED_SCAN_ROOTS


def _summarize_layout_properties(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "layout_modes": _count_property_values(nodes, "layout_mode"),
        "anchors_presets": _count_property_values(nodes, "anchors_preset"),
        "size_flags_horizontal": _count_property_values(nodes, "size_flags_horizontal"),
        "size_flags_vertical": _count_property_values(nodes, "size_flags_vertical"),
        "custom_minimum_size_count": _count_nodes_with_property(nodes, "custom_minimum_size"),
        "container_types": _count_node_types([node for node in nodes if "Container" in node.get("type", "")]),
    }
    return {key: value for key, value in summary.items() if value not in ({}, 0)}


def _summarize_style_overrides(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    colors: dict[str, list[str]] = {}
    font_sizes: dict[str, list[str]] = {}
    for node in nodes:
        properties = node.get("properties", {})
        for key, value in properties.items():
            if key.startswith("theme_override_colors/"):
                colors.setdefault(key.removeprefix("theme_override_colors/"), [])
                if value not in colors[key.removeprefix("theme_override_colors/")]:
                    colors[key.removeprefix("theme_override_colors/")].append(value)
            if key.startswith("theme_override_font_sizes/"):
                font_sizes.setdefault(key.removeprefix("theme_override_font_sizes/"), [])
                if value not in font_sizes[key.removeprefix("theme_override_font_sizes/")]:
                    font_sizes[key.removeprefix("theme_override_font_sizes/")].append(value)
    return {
        "theme_override_colors": {key: values[:5] for key, values in sorted(colors.items())[:10]},
        "theme_override_font_sizes": {key: values[:5] for key, values in sorted(font_sizes.items())[:10]},
    }


def _count_property_values(nodes: list[dict[str, Any]], property_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        value = node.get("properties", {}).get(property_name)
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10])


def _count_nodes_with_property(nodes: list[dict[str, Any]], property_name: str) -> int:
    return sum(1 for node in nodes if property_name in node.get("properties", {}))


def _count_node_types(nodes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in nodes:
        node_type = node.get("type", "")
        counts[node_type] = counts.get(node_type, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10])


def _recommend_reference_scenes(scenes: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for scene in scenes:
        reasons: list[str] = []
        score = int(scene["control_count"])
        rel = str(scene["project_relative_path"])
        if rel.split("/", 1)[0].lower() in STRONG_UI_SCENE_ROOTS:
            score += 10
            reasons.append("ui_directory")
        if scene.get("container_node_count", 0):
            score += int(scene["container_node_count"])
            reasons.append("container_layout")
        if scene.get("referenced_resources"):
            score += 3
            reasons.append("resource_references")
        if scene.get("style_overrides", {}).get("theme_override_colors"):
            score += 3
            reasons.append("color_overrides")
        if scene.get("style_overrides", {}).get("theme_override_font_sizes"):
            score += 3
            reasons.append("font_size_overrides")
        recommendations.append({
            "scene_path": scene["scene_path"],
            "score": score,
            "reasons": reasons or ["ui_controls"],
        })
    recommendations.sort(key=lambda item: (-int(item["score"]), str(item["scene_path"])))
    return recommendations[:limit]


def _build_style_notes(
    scenes: list[dict[str, Any]],
    themes: list[str],
    fonts: list[str],
    image_assets: list[str],
) -> list[str]:
    notes: list[str] = []
    if themes:
        notes.append("Theme resources are present; prefer reusing existing Theme files before hardcoding control styles.")
    if fonts:
        notes.append("Font resources are present; inspect existing font usage before choosing type scale for new pages.")
    if image_assets:
        notes.append("UI image assets are present; prefer project-local textures for panels, icons, and button states.")
    aggregate_counts: dict[str, int] = {}
    for scene in scenes:
        for node_type, count in scene["control_types"]:
            aggregate_counts[node_type] = aggregate_counts.get(node_type, 0) + int(count)
    common_types = [node_type for node_type, _ in sorted(aggregate_counts.items(), key=lambda item: (-item[1], item[0]))[:5]]
    if common_types:
        notes.append("Common UI node types: " + ", ".join(common_types) + ".")
    if any("Container" in node_type for node_type in common_types):
        notes.append("Existing UI appears to use Godot container layout; keep new page hierarchy container-driven where practical.")
    if not notes:
        notes.append("No strong UI style signals were found; capture representative existing screens before designing a new page.")
    return notes


def _remove_empty_managed_dirs(project: Path) -> None:
    for rel in [
        EXPORTER_TARGET_PREFIX,
        EXPORTER_TARGET_PREFIX.parent,
        EXPORTER_TARGET_PREFIX.parent.parent,
    ]:
        directory = project / rel.as_posix()
        try:
            directory.rmdir()
        except OSError:
            continue


def _tokenize(text: str) -> set[str]:
    return {token for token in text.lower().replace("-", " ").replace("_", " ").split() if token}
