from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Any


class UiFeedbackMcpError(RuntimeError):
    """Raised when a UI feedback MCP operation cannot run safely."""


def validate_godot_project(project_path: str | Path) -> dict[str, str]:
    project = Path(project_path).expanduser().resolve()
    project_file = project / "project.godot"
    if not project_file.is_file():
        raise UiFeedbackMcpError(f"Godot project file not found: {project_file}")
    return {
        "project_path": str(project),
        "project_file": str(project_file),
    }


def suggest_godot_scenes(project_path: str | Path, description: str = "", limit: int = 10) -> list[dict[str, Any]]:
    project = Path(validate_godot_project(project_path)["project_path"])
    terms = _tokenize(description)
    suggestions: list[dict[str, Any]] = []
    for scene in sorted(project.rglob("*.tscn")):
        rel = scene.relative_to(project).as_posix()
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
    files = [
        "tools/export_ui_proxy.gd",
        "tools/ui_proxy_exporter.gd",
    ]
    installed: list[str] = []
    for rel in files:
        source = source_root / rel
        target = project / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_text(encoding="utf-8") != source.read_text(encoding="utf-8"):
            shutil.copyfile(source, target)
            installed.append(rel)
    return {
        "project_path": str(project),
        "installed_files": installed,
    }


def build_capture_reference_command(
    *,
    project_path: str | Path,
    scene_path: str,
    out_path: str,
    width: int = 1280,
    height: int = 720,
	title: str = "Godot UI Proxy",
	godot_bin: str = "godot",
	calls: list[str] | None = None,
) -> list[str]:
	project_path_obj = Path(project_path).expanduser()
	project = str(project_path_obj)
	script_path = str((project_path_obj / "tools" / "export_ui_proxy.gd").resolve())
	command = [
		godot_bin,
		"--resolution",
		"%dx%d" % (int(width), int(height)),
		"--path",
		project,
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
        str(int(width)),
		"--height",
		str(int(height)),
	]
	for call in calls or []:
		command.extend(["--call", str(call)])
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
	title: str = "Godot UI Proxy",
	godot_bin: str = "godot",
	calls: list[str] | None = None,
	timeout_seconds: int = 60,
) -> dict[str, Any]:
    validate_godot_project(project_path)
    install_result = ensure_exporter_installed(project_path)
    command = build_capture_reference_command(
        project_path=project_path,
        scene_path=scene_path,
        out_path=out_path,
        width=width,
		height=height,
		title=title,
		godot_bin=godot_bin,
		calls=calls,
	)
    completed = subprocess.run(
        command,
        cwd=str(Path(project_path).resolve()),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise UiFeedbackMcpError(
            "Godot proxy generation failed with exit code %d\nSTDOUT:\n%s\nSTDERR:\n%s"
            % (completed.returncode, completed.stdout, completed.stderr)
        )
    output_file = _resolve_godot_path(project_path, out_path)
    node_count = _count_proxy_nodes(output_file)
    screenshot_file = output_file.with_suffix(".png")
    return {
        "project_path": str(Path(project_path).resolve()),
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
        "stdout": completed.stdout,
        "stderr": completed.stderr,
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
		"3. Call ensure_exporter_installed if the target project does not already have the exporter scripts.",
		"4. Call capture_godot_ui_reference for the selected scene or a small state harness to capture the real Godot screenshot and node metadata.",
		"5. The agent reads the screenshot and creates a separate structured HTML proxy by visually recreating the screen.",
		"6. Open that visual proxy in the browser and let the user place comments on semantic DOM elements.",
		"7. Call parse_browser_feedback to turn browser comments into Godot-targeted records.",
		"8. Map those records to Godot files/nodes, write tests, implement, and ask for real-game retest.",
	])


def _resolve_godot_path(project_path: str | Path, godot_path: str) -> Path:
    project = Path(project_path).resolve()
    if godot_path.startswith("res://"):
        return project / godot_path.removeprefix("res://")
    return Path(godot_path).expanduser().resolve()


def _count_proxy_nodes(html_path: Path) -> int:
    if not html_path.is_file():
        return 0
    return html_path.read_text(encoding="utf-8").count("data-godot-node-path=")


def _capture_naming_warning(output_file: Path) -> str:
    stem = output_file.stem.lower()
    if stem.endswith("-capture") or stem.endswith("_capture"):
        return ""
    return "Capture artifacts should usually be named '*-capture.html' so they are not confused with the user-facing visual recreation proxy."


def _tokenize(text: str) -> set[str]:
    return {token for token in text.lower().replace("-", " ").replace("_", " ").split() if token}
