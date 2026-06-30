import tempfile
import unittest
from pathlib import Path

from godot_ui_feedback_mcp import server


class UiFeedbackMcpServerTests(unittest.TestCase):
    def test_tool_registry_exposes_v1_tools(self):
        tools = server.get_tool_registry()

        self.assertIn("capture_godot_ui_reference", tools)
        self.assertIn("generate_godot_ui_proxy", tools)
        self.assertIn("parse_browser_feedback", tools)
        self.assertIn("suggest_godot_scenes", tools)
        self.assertIn("ensure_exporter_installed", tools)
        self.assertIn("describe_workflow", tools)

    def test_describe_workflow_handler_returns_text(self):
        result = server.call_tool("describe_workflow", {})

        self.assertIn("capture_godot_ui_reference", result["text"])
        self.assertIn("parse_browser_feedback", result["text"])

    def test_parse_browser_feedback_handler_reuses_existing_parser(self):
        comment_text = """# Browser comments:

## Comment 1
Page URL: file:///tmp/proxy.html
Target: "Menu"
Target selector: button.menu
Comment:
no response
"""

        result = server.call_tool("parse_browser_feedback", {"comments_text": comment_text})

        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["target_surface"], "godot")
        self.assertEqual(result["records"][0]["proxy_text"], "Menu")
        self.assertIn("```json", result["markdown"])

    def test_suggest_godot_scenes_handler_returns_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")
            (project / "scenes").mkdir()
            (project / "scenes" / "main.tscn").write_text("[node name=\"Main\"]\n", encoding="utf-8")

            result = server.call_tool("suggest_godot_scenes", {
                "project_path": str(project),
                "description": "main",
            })

        self.assertEqual(result["suggestions"][0]["scene_path"], "res://scenes/main.tscn")

    def test_ensure_exporter_installed_handler_copies_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "project.godot").write_text("", encoding="utf-8")

            result = server.call_tool("ensure_exporter_installed", {"project_path": str(project)})

        self.assertIn("addons/ui_feedback_bridge_mcp/tools/export_ui_proxy.gd", result["installed_files"])
        self.assertIn("addons/ui_feedback_bridge_mcp/tools/ui_proxy_exporter.gd", result["installed_files"])

    def test_minimal_mcp_dispatch_lists_and_calls_tools_without_mcp_package(self):
        list_response = server.dispatch_json_rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        })
        call_response = server.dispatch_json_rpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "describe_workflow",
                "arguments": {},
            },
        })

        tool_names = [tool["name"] for tool in list_response["result"]["tools"]]
        self.assertIn("capture_godot_ui_reference", tool_names)
        self.assertIn("generate_godot_ui_proxy", tool_names)
        self.assertIn("capture_godot_ui_reference", call_response["result"]["content"][0]["text"])

    def test_minimal_schema_exposes_calls_and_not_godot_bin(self):
        capture = next(tool for tool in server._tool_descriptions() if tool["name"] == "capture_godot_ui_reference")
        properties = capture["inputSchema"]["properties"]

        self.assertIn("calls", properties)
        self.assertIn("timeout_seconds", properties)
        self.assertNotIn("godot_bin", properties)
        self.assertFalse(capture["inputSchema"].get("additionalProperties", True))

    def test_dispatch_maps_invalid_arguments_to_invalid_params(self):
        response = server.dispatch_json_rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "describe_workflow", "arguments": []},
        })

        self.assertEqual(response["error"]["code"], -32602)

    def test_capture_rejects_removed_godot_bin_argument(self):
        with self.assertRaisesRegex(Exception, "godot_bin"):
            server.call_tool("capture_godot_ui_reference", {
                "project_path": "/tmp/project",
                "scene_path": "res://scenes/main.tscn",
                "out_path": "res://docs/ui_proxy/main-capture.html",
                "godot_bin": "godot",
            })

    def test_legacy_generate_proxy_tool_is_described_as_deprecated_alias(self):
        tools = server._tool_descriptions()
        legacy = next(tool for tool in tools if tool["name"] == "generate_godot_ui_proxy")

        self.assertIn("Deprecated alias", legacy["description"])


if __name__ == "__main__":
    unittest.main()
