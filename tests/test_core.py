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

    def test_suggest_godot_scenes_scores_description_matches_and_ignores_addons(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            (project / "scenes").mkdir()
            (project / "ui").mkdir()
            (project / "addons" / "plugin").mkdir(parents=True)
            (project / "scenes" / "main.tscn").write_text("[node name=\"Main\"]\n", encoding="utf-8")
            (project / "ui" / "estate_screen.tscn").write_text("[node name=\"EstateScreen\"]\n", encoding="utf-8")
            (project / "addons" / "plugin" / "estate_screen.tscn").write_text("[node name=\"Plugin\"]\n", encoding="utf-8")

            suggestions = core.suggest_godot_scenes(project, "estate screen")

            self.assertGreaterEqual(len(suggestions), 2)
            self.assertEqual(suggestions[0]["scene_path"], "res://ui/estate_screen.tscn")
            self.assertGreater(suggestions[0]["score"], suggestions[1]["score"])
            self.assertIn("description", suggestions[0]["reasons"])
            self.assertNotIn("res://addons/plugin/estate_screen.tscn", [item["scene_path"] for item in suggestions])

    def test_build_capture_reference_command_uses_managed_exporter_and_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = core.build_capture_reference_command(
                project_path=Path(tmp),
                scene_path="res://scenes/main.tscn",
                out_path="res://docs/ui_proxy/main-capture.html",
                width=1280,
                height=720,
                title="Main Proxy",
                godot_bin="godot",
                calls=["_mcp_capture_difficulty:0"],
            )

        self.assertEqual(command[0], "godot")
        self.assertNotIn("--headless", command)
        self.assertIn("--resolution", command)
        self.assertIn("1280x720", command)
        script_index = command.index("--script") + 1
        self.assertTrue(Path(command[script_index]).is_absolute())
        self.assertIn("addons/ui_feedback_bridge_mcp/tools/export_ui_proxy.gd", command[script_index].replace("\\", "/"))
        self.assertIn("--scene", command)
        self.assertIn("res://scenes/main.tscn", command)
        self.assertIn("--out", command)
        self.assertIn("res://docs/ui_proxy/main-capture.html", command)
        self.assertIn("--title", command)
        self.assertIn("Main Proxy", command)
        self.assertIn("--call", command)
        self.assertIn("_mcp_capture_difficulty:0", command)

    def test_build_capture_reference_command_rejects_executable_path_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.InvalidToolArgumentsError):
                core.build_capture_reference_command(
                    project_path=tmp,
                    scene_path="res://scenes/main.tscn",
                    out_path="res://docs/ui_proxy/main-capture.html",
                    godot_bin="/tmp/not-godot",
                )

    def test_calls_must_target_capture_prefixed_methods(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(core.InvalidToolArgumentsError):
                core.build_capture_reference_command(
                    project_path=tmp,
                    scene_path="res://scenes/main.tscn",
                    out_path="res://docs/ui_proxy/main-capture.html",
                    calls=["_on_difficulty_selected:0"],
                )

    def test_capture_rejects_output_paths_outside_docs_ui_proxy_before_running_godot(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            (project / "scenes").mkdir()
            (project / "scenes" / "main.tscn").write_text("[node name=\"Main\"]\n", encoding="utf-8")

            with self.assertRaises(core.InvalidToolArgumentsError):
                core.capture_godot_ui_reference(
                    project_path=project,
                    scene_path="res://scenes/main.tscn",
                    out_path="/tmp/main.html",
                )
            with self.assertRaises(core.InvalidToolArgumentsError):
                core.capture_godot_ui_reference(
                    project_path=project,
                    scene_path="res://scenes/main.tscn",
                    out_path="res://main.html",
                )
            with self.assertRaises(core.InvalidToolArgumentsError):
                core.capture_godot_ui_reference(
                    project_path=project,
                    scene_path="res://../main.tscn",
                    out_path="res://docs/ui_proxy/main-capture.html",
                )

    def test_ensure_exporter_installed_copies_managed_godot_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")

            installed = core.ensure_exporter_installed(project)

            export_path = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "export_ui_proxy.gd"
            proxy_path = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "ui_proxy_exporter.gd"
            self.assertTrue(export_path.is_file())
            self.assertTrue(proxy_path.is_file())
            self.assertIn(core.EXPORTER_MANAGED_MARKER, export_path.read_text(encoding="utf-8"))
            self.assertIn("addons/ui_feedback_bridge_mcp/tools/export_ui_proxy.gd", installed["installed_files"])
            self.assertIn("addons/ui_feedback_bridge_mcp/tools/ui_proxy_exporter.gd", installed["installed_files"])

    def test_ensure_exporter_installed_refuses_unmanaged_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            target = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "export_ui_proxy.gd"
            target.parent.mkdir(parents=True)
            target.write_text("extends Node\n", encoding="utf-8")

            with self.assertRaises(core.UiFeedbackMcpError) as caught:
                core.ensure_exporter_installed(project)

            self.assertIn("Refusing to overwrite unmanaged", str(caught.exception))

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
        self.assertIn(core.EXPORTER_MANAGED_MARKER, exporter)

    def test_describe_workflow_says_agent_visually_recreates_html_proxy(self):
        text = core.describe_workflow()

        self.assertIn("capture the real Godot screenshot", text)
        self.assertIn("visually recreating the screen", text)


if __name__ == "__main__":
    unittest.main()
