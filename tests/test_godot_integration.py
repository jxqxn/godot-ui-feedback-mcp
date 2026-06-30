import os
import shutil
import tempfile
import unittest
from pathlib import Path

from godot_ui_feedback_mcp import core


def _available_godot_bin() -> str | None:
    configured = os.environ.get("GODOT_BIN")
    if configured:
        try:
            return core._validate_godot_bin(None)
        except core.InvalidToolArgumentsError:
            return None
    return shutil.which("godot4") or shutil.which("godot")


@unittest.skipUnless(_available_godot_bin(), "Godot executable not configured or found on PATH")
class GodotCaptureIntegrationTests(unittest.TestCase):
    def test_capture_godot_ui_reference_writes_html_and_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            _write_minimal_project(project)

            result = core.capture_godot_ui_reference(
                project_path=project,
                scene_path="res://scenes/capture_fixture.tscn",
                out_path="res://docs/ui_proxy/fixture-capture.html",
                width=640,
                height=480,
                title="Fixture Capture",
                timeout_seconds=30,
            )

            output_file = Path(result["output_file"])
            screenshot_file = Path(result["screenshot_file"])
            self.assertTrue(output_file.is_file())
            self.assertTrue(screenshot_file.is_file())
            self.assertGreater(screenshot_file.stat().st_size, 0)
            html = output_file.read_text(encoding="utf-8")
            self.assertIn("Fixture Capture", html)
            self.assertIn("data-godot-node-path=", html)
            self.assertGreaterEqual(result["node_count"], 1)


def _write_minimal_project(project: Path) -> None:
    (project / "scenes").mkdir()
    (project / "project.godot").write_text(
        "\n".join([
            "; Engine configuration file.",
            "config_version=5",
            "",
            "[application]",
            'config/name="MCP Capture Fixture"',
            "",
        ]),
        encoding="utf-8",
    )
    (project / "scenes" / "capture_fixture.tscn").write_text(
        "\n".join([
            "[gd_scene format=3]",
            "",
            '[node name="FixtureRoot" type="Control"]',
            "layout_mode = 3",
            "anchors_preset = 15",
            "anchor_right = 1.0",
            "anchor_bottom = 1.0",
            "",
            '[node name="CaptureButton" type="Button" parent="."]',
            "layout_mode = 0",
            "offset_left = 40.0",
            "offset_top = 32.0",
            "offset_right = 220.0",
            "offset_bottom = 88.0",
            'text = "Capture Me"',
            "",
        ]),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
