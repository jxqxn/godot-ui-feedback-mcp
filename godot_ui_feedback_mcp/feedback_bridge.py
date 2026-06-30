"""Convert Codex browser UI comments into Godot feedback records.

The browser page is an annotation proxy. Generated records target Godot by
default and should be reviewed before implementation.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Iterable


COMMENT_HEADER_RE = re.compile(r"^##\s+(Comment\s+\d+)\s*$", re.MULTILINE)


def parse_browser_comments(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    matches = list(COMMENT_HEADER_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        feedback = _after_label(block, "Comment:")
        record = {
            "id": match.group(1),
            "source": "browser_comment",
            "target_surface": "godot",
            "page_url": _value_after_prefix(block, "Page URL:"),
            "proxy_text": _quoted_value_after_prefix(block, "Target:"),
            "proxy_selector": _value_after_prefix(block, "Target selector:"),
            "feedback": feedback,
            "type": classify_feedback(feedback),
            "godot_node": "needs_mapping",
            "godot_file": "needs_mapping",
            "status": "captured",
        }
        records.append(record)
    return records


def classify_feedback(comment: str) -> str:
    normalized = comment.strip().lower()
    if _contains_any(normalized, [
        "no response", "doesn't respond", "does not respond", "no effect", "not clickable",
        "click has no", "nothing happens", "cannot click", "can't click",
    ]):
        return "interaction_missing"
    if _contains_any(normalized, [
        "already shown", "already there", "duplicate", "duplicated", "isn't this already",
        "is this already", "shown twice", "appears twice",
    ]):
        return "duplicate_entry"
    if "coin" in normalized and _contains_any(normalized, ["card", "hand", "item"]):
        return "hud_counter_misuse"
    if _contains_any(normalized, [
        "what does", "what is", "terminology", "mean here", "meaning", "unclear label",
    ]):
        return "terminology_confusion"
    return "needs_mapping"


def render_markdown(records: Iterable[dict[str, str]]) -> str:
    lines = [
        "# UI Feedback Intake",
        "",
        "Browser comments target Godot UI by default. Do not edit the HTML proxy unless explicitly requested.",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"## {record['id']}",
                "",
                "```yaml",
                f"source: {record['source']}",
                f"target_surface: {record['target_surface']}",
                f"page_url: {record['page_url']}",
                f"proxy_text: {record['proxy_text']}",
                f"proxy_selector: {record['proxy_selector']}",
                f"godot_node: {record['godot_node']}",
                f"godot_file: {record['godot_file']}",
                f"feedback: {record['feedback']}",
                f"type: {record['type']}",
                f"status: {record['status']}",
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert browser comments to Godot UI feedback Markdown.")
    parser.add_argument("input", help="Text file containing pasted browser comments.")
    parser.add_argument("--out", help="Output Markdown path. Defaults to stdout.")
    args = parser.parse_args(argv)

    source = Path(args.input).read_text(encoding="utf-8")
    rendered = render_markdown(parse_browser_comments(source))
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def _contains_any(text: str, tokens: Iterable[str]) -> bool:
    return any(token in text for token in tokens)


def _value_after_prefix(block: str, prefix: str) -> str:
    for line in block.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def _quoted_value_after_prefix(block: str, prefix: str) -> str:
    raw = _value_after_prefix(block, prefix)
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        return raw[1:-1]
    return raw


def _after_label(block: str, label: str) -> str:
    marker = block.find(label)
    if marker < 0:
        return ""
    return block[marker + len(label):].strip()


if __name__ == "__main__":
    raise SystemExit(main())
