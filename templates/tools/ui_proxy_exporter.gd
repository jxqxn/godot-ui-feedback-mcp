extends RefCounted

## Captures a Control tree as reference metadata for a visual recreation proxy.
## The generated HTML is not the user-facing review page; it carries
## data-godot-* attributes so Codex can map visual proxy comments back to Godot.


static func render_html(root: Control, viewport_size: Vector2, options: Dictionary = {}) -> String:
	var title := str(options.get("title", "Godot UI Proxy"))
	var scene := str(options.get("scene", ""))
	var nodes: Array[String] = []
	for child in root.get_children():
		_collect_node_html(child, root.name, Vector2.ZERO, scene, nodes)
	return _render_document(title, scene, viewport_size, nodes)


static func render_scene_html(root: Node, viewport_size: Vector2, options: Dictionary = {}) -> String:
	var title := str(options.get("title", "Godot UI Proxy"))
	var scene := str(options.get("scene", ""))
	var screenshot := str(options.get("screenshot", ""))
	var nodes: Array[String] = []
	if screenshot != "":
		_collect_hotspot_svg(root, "", scene, viewport_size, nodes)
		return _render_screenshot_document(title, scene, viewport_size, screenshot, nodes)
	else:
		_collect_node_html(root, "", Vector2.ZERO, scene, nodes)
		return _render_document(title, scene, viewport_size, nodes)


static func write_scene_html(path: String, root: Node, viewport_size: Vector2, options: Dictionary = {}) -> Error:
	var html := render_scene_html(root, viewport_size, options)
	return _write_text(path, html)


static func _render_document(title: String, scene: String, viewport_size: Vector2, nodes: Array[String]) -> String:
	return "\n".join([
		"<!doctype html>",
		"<html lang=\"zh-CN\">",
		"<head>",
		"  <meta charset=\"utf-8\" />",
		"  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />",
		"  <title>%s</title>" % _escape_html(title),
		"  <style>",
		"    * { box-sizing: border-box; }",
		"    body { margin: 0; min-height: 100vh; background: #151515; display: grid; place-items: start center; font-family: system-ui, sans-serif; }",
		"    .viewport { position: relative; overflow: hidden; background: #50504f; color: #e8dcc8; width:%dpx; height:%dpx; }" % [roundi(viewport_size.x), roundi(viewport_size.y)],
		"    .godot-control { position: absolute; border: 1px solid rgba(224,196,134,.7); background: rgba(33,25,20,.92); color: #e0c486; border-radius: 4px; font: 700 14px system-ui, sans-serif; overflow: hidden; }",
		"    .proxy-scaffold { border-color: rgba(224,196,134,.18); background: transparent; color: rgba(224,196,134,.24); pointer-events: none; z-index: 0; }",
		"    .proxy-surface { border-color: rgba(224,196,134,.55); background: rgba(33,25,20,.88); color: transparent; pointer-events: none; z-index: 1; }",
		"    .proxy-content { z-index: 2; }",
		"    button.godot-control { cursor: pointer; }",
		"  </style>",
		"</head>",
		"<body>",
		"  <main class=\"viewport\" data-engine=\"godot\" data-godot-scene=\"%s\">" % _escape_attr(scene),
		"\n".join(nodes),
		"  </main>",
		"</body>",
		"</html>",
	])


static func _render_screenshot_document(title: String, scene: String, viewport_size: Vector2, screenshot: String, nodes: Array[String]) -> String:
	return "\n".join([
		"<!doctype html>",
		"<html lang=\"zh-CN\">",
		"<head>",
		"  <meta charset=\"utf-8\" />",
		"  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />",
		"  <title>%s</title>" % _escape_html(title),
		"  <style>",
		"    * { box-sizing: border-box; }",
		"    body { margin: 0; min-height: 100vh; background: #151515; display: grid; place-items: start center; font-family: system-ui, sans-serif; }",
		"    .viewport { position: relative; overflow: hidden; width:%dpx; height:%dpx; }" % [roundi(viewport_size.x), roundi(viewport_size.y)],
		"    .proxy-screenshot { position:absolute; inset:0; width:100%; height:100%; object-fit:fill; user-select:none; pointer-events:none; }",
		"    .hotspot-map { position:absolute; inset:0; width:100%; height:100%; }",
		"    .godot-hotspot rect { fill:rgba(224,196,134,0); stroke:rgba(224,196,134,0); stroke-width:0; vector-effect:non-scaling-stroke; }",
		"    .godot-hotspot:hover rect, .godot-hotspot:focus rect { fill:rgba(224,196,134,.08); stroke:rgba(224,196,134,.95); stroke-width:2; outline:none; }",
		"  </style>",
		"</head>",
		"<body>",
		"  <main class=\"viewport screenshot-proxy\" data-engine=\"godot\" data-godot-scene=\"%s\">" % _escape_attr(scene),
		"    <img class=\"proxy-screenshot\" src=\"%s\" alt=\"Godot viewport screenshot\" />" % _escape_attr(screenshot),
		"    <svg class=\"hotspot-map\" viewBox=\"0 0 %d %d\" role=\"group\" aria-label=\"Godot UI annotation hotspots\">" % [roundi(viewport_size.x), roundi(viewport_size.y)],
		"\n".join(nodes),
		"    </svg>",
		"  </main>",
		"</body>",
		"</html>",
	])


static func write_html(path: String, root: Control, viewport_size: Vector2, options: Dictionary = {}) -> Error:
	var html := render_html(root, viewport_size, options)
	return _write_text(path, html)


static func _collect_node_html(node: Node, parent_path: String, parent_offset: Vector2, scene: String, out: Array[String]) -> void:
	if node is CanvasItem and not (node as CanvasItem).visible:
		return
	var node_name := str(node.name)
	var node_path := node_name if parent_path == "" else "%s/%s" % [parent_path, node_name]
	var child_offset := parent_offset
	if node is Control:
		var control := node as Control
		var absolute_pos := parent_offset + control.position
		child_offset = absolute_pos
		var size := control.size
		if size.x <= 0.0 or size.y <= 0.0:
			size = control.get_combined_minimum_size()
		var tag := "button" if control is Button else "div"
		var type_name := control.get_class()
		var style := "left:%dpx;top:%dpx;width:%dpx;height:%dpx" % [
			roundi(absolute_pos.x),
			roundi(absolute_pos.y),
			roundi(size.x),
			roundi(size.y),
		]
		var role_class := _proxy_role_class(control)
		var text := _control_text(control) if role_class == "proxy-content" else ""
		out.append("    <%s class=\"godot-control %s %s\" style=\"%s\" data-engine=\"godot\" data-godot-scene=\"%s\" data-godot-node-path=\"%s\" data-godot-node-name=\"%s\" data-godot-control-type=\"%s\">%s</%s>" % [
			tag,
			_escape_attr(type_name),
			role_class,
			_escape_attr(style),
			_escape_attr(scene),
			_escape_attr(node_path),
			_escape_attr(node_name),
			_escape_attr(type_name),
			_escape_html(text),
			tag,
		])
	for child in node.get_children():
		_collect_node_html(child, node_path, child_offset, scene, out)


static func _collect_hotspot_svg(node: Node, parent_path: String, scene: String, viewport_size: Vector2, out: Array[String]) -> void:
	if node is CanvasItem and not (node as CanvasItem).visible:
		return
	var node_name := str(node.name)
	var node_path := node_name if parent_path == "" else "%s/%s" % [parent_path, node_name]
	if node is Control:
		var control := node as Control
		var rect := control.get_global_rect()
		var absolute_pos := rect.position
		var size := rect.size
		if size.x <= 0.0 or size.y <= 0.0:
			size = control.get_combined_minimum_size()
		if size.x > 0.0 and size.y > 0.0 and _should_emit_screenshot_hotspot(control, parent_path, absolute_pos, size, viewport_size):
			var type_name := control.get_class()
			var text := _control_text(control)
			var label := "%s | %s | %s" % [node_path, type_name, text]
			out.append("      <a class=\"godot-hotspot\" href=\"#\" title=\"%s\" aria-label=\"%s\" data-engine=\"godot\" data-godot-scene=\"%s\" data-godot-node-path=\"%s\" data-godot-node-name=\"%s\" data-godot-control-type=\"%s\"><rect x=\"%d\" y=\"%d\" width=\"%d\" height=\"%d\" /></a>" % [
				_escape_attr(label),
				_escape_attr(label),
				_escape_attr(scene),
				_escape_attr(node_path),
				_escape_attr(node_name),
				_escape_attr(type_name),
				roundi(absolute_pos.x),
				roundi(absolute_pos.y),
				roundi(size.x),
				roundi(size.y),
			])
	for child in node.get_children():
		_collect_hotspot_svg(child, node_path, scene, viewport_size, out)


static func _control_text(control: Control) -> String:
	if control is Button:
		return (control as Button).text
	if control is Label:
		return (control as Label).text
	if control is RichTextLabel:
		return (control as RichTextLabel).text
	return str(control.name)


static func _is_content_control(control: Control) -> bool:
	if control is Button or control is Label or control is RichTextLabel:
		return true
	if control is Range:
		return true
	if control.get_class() in ["ColorRect", "Control", "PanelContainer", "HBoxContainer", "VBoxContainer", "CenterContainer", "ScrollContainer", "MarginContainer"]:
		return false
	return control.get_child_count() == 0


static func _should_emit_screenshot_hotspot(control: Control, parent_path: String, absolute_pos: Vector2, size: Vector2, viewport_size: Vector2) -> bool:
	if parent_path == "" and absolute_pos == Vector2.ZERO and size.distance_to(viewport_size) < 1.0:
		return false
	return _is_content_control(control)


static func _proxy_role_class(control: Control) -> String:
	if _is_content_control(control):
		return "proxy-content"
	if _is_surface_control(control):
		return "proxy-surface"
	return "proxy-scaffold"


static func _is_surface_control(control: Control) -> bool:
	var type_name := control.get_class()
	if type_name == "PanelContainer":
		return true
	return false


static func _write_text(path: String, text: String) -> Error:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(text)
	file.close()
	return OK


static func _escape_html(value: String) -> String:
	return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


static func _escape_attr(value: String) -> String:
	return _escape_html(value).replace("\"", "&quot;")
