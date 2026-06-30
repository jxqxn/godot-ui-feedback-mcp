import tempfile
import unittest
from pathlib import Path

from godot_ui_feedback_mcp import core


class UiFeedbackMcpCoreTests(unittest.TestCase):
    def test_validate_godot_project_accepts_project_with_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("; Engine configuration file.\n", encoding="utf-8")

            result = core.validate_godot_project(project)

            self.assertEqual(result["project_path"], str(project.resolve()))
            self.assertTrue(result["project_file"].endswith("project.godot"))

    def test_validate_godot_project_rejects_missing_project_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.UiFeedbackMcpError) as caught:
                core.validate_godot_project(tmp)

        self.assertIn("project.godot", str(caught.exception))

    def test_suggest_godot_scenes_scores_description_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            (project / "scenes").mkdir()
            (project / "ui").mkdir()
            (project / "scenes" / "main.tscn").write_text("[node name=\"Main\"]\n", encoding="utf-8")
            (project / "ui" / "estate_screen.tscn").write_text("[node name=\"EstateScreen\"]\n", encoding="utf-8")

            suggestions = core.suggest_godot_scenes(project, "estate screen")

            self.assertGreaterEqual(len(suggestions), 2)
            self.assertEqual(suggestions[0]["scene_path"], "res://ui/estate_screen.tscn")
            self.assertGreater(suggestions[0]["score"], suggestions[1]["score"])
            self.assertIn("description", suggestions[0]["reasons"])

    def test_build_capture_reference_command_uses_project_scene_and_output(self):
        command = core.build_capture_reference_command(
            project_path=Path("C:/Game"),
            scene_path="res://scenes/main.tscn",
            out_path="res://docs/ui_proxy/main-capture.html",
            width=1280,
            height=720,
            title="Main Proxy",
            godot_bin="godot",
            calls=["_on_difficulty_selected:0"],
        )

        self.assertEqual(command[0], "godot")
        self.assertNotIn("--headless", command)
        self.assertIn("--resolution", command)
        self.assertIn("1280x720", command)
        self.assertIn("--path", command)
        self.assertIn("C:\\Game", command)
        script_index = command.index("--script") + 1
        self.assertTrue(Path(command[script_index]).is_absolute())
        self.assertIn("--scene", command)
        self.assertIn("res://scenes/main.tscn", command)
        self.assertIn("--out", command)
        self.assertIn("res://docs/ui_proxy/main-capture.html", command)
        self.assertIn("--title", command)
        self.assertIn("Main Proxy", command)
        self.assertIn("--call", command)
        self.assertIn("_on_difficulty_selected:0", command)

    def test_ensure_exporter_installed_copies_required_godot_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")

            installed = core.ensure_exporter_installed(project)

            self.assertTrue((project / "tools" / "export_ui_proxy.gd").is_file())
            self.assertTrue((project / "tools" / "ui_proxy_exporter.gd").is_file())
            self.assertIn("tools/export_ui_proxy.gd", installed["installed_files"])
            self.assertIn("tools/ui_proxy_exporter.gd", installed["installed_files"])

    def test_describe_workflow_mentions_screenshot_proxy_and_browser_feedback(self):
        text = core.describe_workflow()

        self.assertIn("screenshot", text.lower())
        self.assertIn("capture_godot_ui_reference", text)
        self.assertIn("parse_browser_feedback", text)

    def test_capture_naming_warning_recommends_capture_suffix(self):
        self.assertEqual(core._capture_naming_warning(Path("main-capture.html")), "")
        self.assertIn("Capture artifacts", core._capture_naming_warning(Path("main.html")))

    def test_exporter_template_does_not_reference_faust_specific_classes(self):
        exporter = Path("templates/tools/ui_proxy_exporter.gd").read_text(encoding="utf-8")

        self.assertNotIn("CardWidget", exporter)
        self.assertNotIn("FaustTheme", exporter)

    def test_describe_workflow_says_agent_visually_recreates_html_proxy(self):
        text = core.describe_workflow()

        self.assertIn("capture the real Godot screenshot", text)
        self.assertIn("visually recreating the screen", text)
