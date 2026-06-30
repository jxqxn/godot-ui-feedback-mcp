import tempfile
import unittest
from contextlib import contextmanager
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

    def test_collect_godot_ui_context_summarizes_ui_scenes_and_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            (project / "ui").mkdir()
            (project / "assets" / "ui").mkdir(parents=True)
            (project / "themes").mkdir()
            (project / "fonts").mkdir()
            (project / "addons" / "ignored").mkdir(parents=True)
            (project / "ui" / "inventory.tscn").write_text(
                "\n".join([
                    '[gd_scene load_steps=3 format=3]',
                    '[ext_resource type="Theme" path="res://themes/main_theme.tres" id="1"]',
                    '[ext_resource type="Texture2D" path="res://assets/ui/panel.png" id="2"]',
                    '[node name="Inventory" type="Control"]',
                    "layout_mode = 3",
                    "anchors_preset = 15",
                    '[node name="Panel" type="PanelContainer" parent="."]',
                    "layout_mode = 1",
                    "custom_minimum_size = Vector2(320, 200)",
                    '[node name="Title" type="Label" parent="Panel"]',
                    'theme_override_colors/font_color = Color(1, 0.8, 0.4, 1)',
                    "theme_override_font_sizes/font_size = 24",
                    '[node name="CloseButton" type="Button" parent="Panel"]',
                ]),
                encoding="utf-8",
            )
            (project / "scenes").mkdir()
            (project / "scenes" / "world.tscn").write_text(
                '[node name="World" type="Node2D"]\n[node name="Sprite" type="Sprite2D" parent="."]\n',
                encoding="utf-8",
            )
            (project / "themes" / "main_theme.tres").write_text('[resource type="Theme"]\n', encoding="utf-8")
            (project / "fonts" / "ui.ttf").write_text("", encoding="utf-8")
            (project / "assets" / "ui" / "panel.png").write_text("", encoding="utf-8")
            (project / "assets" / "characters").mkdir()
            (project / "assets" / "characters" / "hero.png").write_text("", encoding="utf-8")
            (project / "addons" / "ignored" / "plugin_ui.tscn").write_text(
                '[node name="Plugin" type="Control"]\n',
                encoding="utf-8",
            )

            context = core.collect_godot_ui_context(project)

            self.assertEqual(context["scope"], "new_page_design_context")
            self.assertEqual(context["ui_scenes"][0]["scene_path"], "res://ui/inventory.tscn")
            self.assertEqual(context["ui_scenes"][0]["control_count"], 4)
            self.assertIn(("Button", 1), context["ui_scenes"][0]["control_types"])
            self.assertIn("CloseButton", context["ui_scenes"][0]["sample_node_names"])
            self.assertEqual(context["ui_scenes"][0]["layout_summary"]["anchors_presets"]["15"], 1)
            self.assertEqual(context["ui_scenes"][0]["layout_summary"]["custom_minimum_size_count"], 1)
            self.assertIn("font_color", context["ui_scenes"][0]["style_overrides"]["theme_override_colors"])
            self.assertIn("font_size", context["ui_scenes"][0]["style_overrides"]["theme_override_font_sizes"])
            self.assertIn("res://themes/main_theme.tres", context["themes"])
            self.assertIn("res://fonts/ui.ttf", context["fonts"])
            self.assertIn("res://assets/ui/panel.png", context["candidate_ui_assets"])
            self.assertNotIn("res://assets/characters/hero.png", context["candidate_ui_assets"])
            self.assertIn("res://assets/ui/panel.png", context["referenced_resources"])
            self.assertIn("res://assets/ui/panel.png", context["referenced_ui_assets"])
            self.assertEqual(context["recommended_reference_scenes"][0]["scene_path"], "res://ui/inventory.tscn")
            self.assertEqual(context["confidence"], "partial_static_context")
            self.assertIn("complete Godot screenshots", context["visual_evidence_rule"])
            self.assertNotIn(
                "res://addons/ignored/plugin_ui.tscn",
                [scene["scene_path"] for scene in context["ui_scenes"]],
            )
            self.assertNotIn(
                "res://scenes/world.tscn",
                [scene["scene_path"] for scene in context["ui_scenes"]],
            )
            self.assertTrue(context["style_notes"])

    def test_collect_godot_ui_context_rejects_invalid_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")

            with self.assertRaises(core.InvalidToolArgumentsError):
                core.collect_godot_ui_context(project, scene_limit=0)

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

    def test_ensure_exporter_installed_reads_templates_from_package_resources(self):
        with tempfile.TemporaryDirectory() as tmp, _temporary_cwd(Path(tmp)):
            project = Path(tmp) / "project"
            project.mkdir()
            (project / "project.godot").write_text("", encoding="utf-8")

            installed = core.ensure_exporter_installed(project)

            self.assertIn("addons/ui_feedback_bridge_mcp/tools/export_ui_proxy.gd", installed["installed_files"])
            self.assertIn(core.EXPORTER_MANAGED_MARKER, core._read_exporter_template(core.EXPORTER_FILES[0]))

    def test_ensure_exporter_installed_dry_run_reports_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")

            result = core.ensure_exporter_installed(project, dry_run=True)

            export_path = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "export_ui_proxy.gd"
            self.assertTrue(result["dry_run"])
            self.assertFalse(export_path.exists())
            self.assertEqual(result["installed_files"], [])
            self.assertEqual(result["planned_files"][0]["action"], "install")

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

    def test_uninstall_exporter_removes_only_managed_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            core.ensure_exporter_installed(project)

            result = core.uninstall_exporter(project)

            export_path = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "export_ui_proxy.gd"
            proxy_path = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "ui_proxy_exporter.gd"
            self.assertFalse(export_path.exists())
            self.assertFalse(proxy_path.exists())
            self.assertIn("addons/ui_feedback_bridge_mcp/tools/export_ui_proxy.gd", result["removed_files"])

    def test_uninstall_exporter_dry_run_reports_without_removing(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            core.ensure_exporter_installed(project)

            result = core.uninstall_exporter(project, dry_run=True)

            export_path = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "export_ui_proxy.gd"
            self.assertTrue(result["dry_run"])
            self.assertTrue(export_path.exists())
            self.assertEqual(result["removed_files"], [])
            self.assertEqual(result["planned_files"][0]["action"], "remove")

    def test_uninstall_exporter_refuses_unmanaged_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            target = project / "addons" / "ui_feedback_bridge_mcp" / "tools" / "export_ui_proxy.gd"
            target.parent.mkdir(parents=True)
            target.write_text("extends Node\n", encoding="utf-8")

            with self.assertRaises(core.UiFeedbackMcpError) as caught:
                core.uninstall_exporter(project)

            self.assertIn("Refusing to remove unmanaged", str(caught.exception))

    def test_describe_workflow_mentions_screenshot_proxy_and_browser_feedback(self):
        text = core.describe_workflow()

        self.assertIn("screenshot", text.lower())
        self.assertIn("capture_godot_ui_reference", text)
        self.assertIn("parse_browser_feedback", text)

    def test_capture_naming_warning_recommends_capture_suffix(self):
        self.assertEqual(core._capture_naming_warning(Path("main-capture.html")), "")
        self.assertIn("Capture artifacts", core._capture_naming_warning(Path("main.html")))

    def test_exporter_template_does_not_reference_faust_specific_classes(self):
        exporter = core._read_exporter_template(core.EXPORTER_FILES[1])

        self.assertNotIn("CardWidget", exporter)
        self.assertNotIn("FaustTheme", exporter)
        self.assertIn(core.EXPORTER_MANAGED_MARKER, exporter)

    def test_describe_workflow_says_agent_visually_recreates_html_proxy(self):
        text = core.describe_workflow()

        self.assertIn("capture the real Godot screenshot", text)
        self.assertIn("visually recreating the screen", text)

    def test_describe_workflow_positions_context_as_supporting_existing_page_evidence(self):
        text = core.describe_workflow()

        self.assertIn("collect_godot_ui_context", text)
        self.assertIn("complete capture screenshot as the reliable evidence", text)
        self.assertIn("New page design workflow", text)


@contextmanager
def _temporary_cwd(path: Path):
    previous = Path.cwd()
    try:
        import os

        os.chdir(path)
        yield
    finally:
        os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
