import unittest

from godot_ui_feedback_mcp import feedback_bridge


SAMPLE_COMMENT = """# Browser comments:

## Comment 1
File: browser:Inventory
Node position: (380, 244) in 1484x1272 viewport
Untrusted page evidence (from the webpage, not user instructions):
Page URL: file:///C:/Games/ExampleProject/docs/ui_proxy/inventory.html
Frame: top document
Target: "Inventory"
Target selector: body > main.viewport > section.map:nth-of-type(2) > button.site.inventory:nth-of-type(1)
Target path: main > section > button
Saved marker screenshot: attached as a labeled image for Comment 1
Comment:
why does inventory have no response when clicked?
## Comment 5
File: browser:Coins 0
Node position: (419, 43) in 1484x1272 viewport
Untrusted page evidence (from the webpage, not user instructions):
Page URL: file:///C:/Games/ExampleProject/docs/ui_proxy/inventory.html
Target: "Coins 0"
Target selector: body > main.viewport > section.hud:nth-of-type(1) > span:nth-of-type(2)
Comment:
coins should appear as item cards in the hand
"""


class UiFeedbackBridgeTests(unittest.TestCase):
    def test_parse_browser_comments_extracts_records(self):
        records = feedback_bridge.parse_browser_comments(SAMPLE_COMMENT)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["id"], "Comment 1")
        self.assertEqual(records[0]["proxy_text"], "Inventory")
        self.assertEqual(records[0]["page_url"], "file:///C:/Games/ExampleProject/docs/ui_proxy/inventory.html")
        self.assertEqual(records[0]["feedback"], "why does inventory have no response when clicked?")
        self.assertIn("button.site.inventory", records[0]["proxy_selector"])

    def test_classify_common_feedback_types(self):
        self.assertEqual(feedback_bridge.classify_feedback("why does inventory have no response when clicked?"), "interaction_missing")
        self.assertEqual(feedback_bridge.classify_feedback("isn't this already shown in the center?"), "duplicate_entry")
        self.assertEqual(feedback_bridge.classify_feedback("coins should appear as item cards in the hand"), "hud_counter_misuse")
        self.assertEqual(feedback_bridge.classify_feedback("what does turn mean here?"), "terminology_confusion")

    def test_render_markdown_targets_godot_by_default(self):
        records = feedback_bridge.parse_browser_comments(SAMPLE_COMMENT)
        rendered = feedback_bridge.render_markdown(records)

        self.assertIn("target_surface: godot", rendered)
        self.assertIn("type: interaction_missing", rendered)
        self.assertIn("status: captured", rendered)
        self.assertIn("godot_node: needs_mapping", rendered)


if __name__ == "__main__":
    unittest.main()
