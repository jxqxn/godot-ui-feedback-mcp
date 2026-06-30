from __future__ import annotations

import os
import re
import subprocess
import shutil
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
    ignored_roots = {".godot", ".import", "addons", "build", "dist", "export"}
    suggestions: list[dict[str, Any]] = []
    for scene in sorted(project.rglob("*.tscn")):
        rel = scene.relative_to(project).as_posix()
        if rel.split("/", 1)[0] in ignored_roots:
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


def ensure_exporter_installed(project_path: str | Path) -> dict[str, Any]:
    project = Path(validate_godot_project(project_path)["project_path"])
    source_root = Path(__file__).resolve().parents[1] / "templates"
    installed: list[str] = []
    unchanged: list[str] = []
    for exporter_file in EXPORTER_FILES:
        source = source_root / exporter_file.source_rel.as_posix()
        target = project / exporter_file.target_rel.as_posix()
        source_text = source.read_text(encoding="utf-8")
        if EXPORTER_MANAGED_MARKER not in source_text:
            raise UiFeedbackMcpError(f"Exporter template is missing managed marker: {source}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            existing_text = target.read_text(encoding="utf-8")
            if existing_text == source_text:
                unchanged.append(exporter_file.target_rel.as_posix())
                continue
            if EXPORTER_MANAGED_MARKER not in existing_text:
                raise UiFeedbackMcpError(
                    "Refusing to overwrite unmanaged Godot file: "
                    f"{target}. Remove or rename it, then run ensure_exporter_installed again."
                )
        shutil.copyfile(source, target)
        installed.append(exporter_file.target_rel.as_posix())
    return {
        "project_path": str(project),
        "installed_files": installed,
        "unchanged_files": unchanged,
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
        "3. Call ensure_exporter_installed if the target project does not already have the managed exporter scripts.",
        "4. Call capture_godot_ui_reference for the selected scene or a small state harness to capture the real Godot screenshot and node metadata.",
        "5. The agent reads the screenshot and creates a separate structured HTML proxy by visually recreating the screen.",
        "6. Open that visual proxy in the browser and let the user place comments on semantic DOM elements.",
        "7. Call parse_browser_feedback to turn browser comments into Godot-targeted records.",
        "8. Map those records to Godot files/nodes, write tests, implement, and ask for real-game retest.",
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


def _tokenize(text: str) -> set[str]:
    return {token for token in text.lower().replace("-", " ").replace("_", " ").split() if token}
