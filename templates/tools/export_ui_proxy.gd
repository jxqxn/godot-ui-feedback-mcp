extends SceneTree

const UiProxyExporter = preload("res://tools/ui_proxy_exporter.gd")

var _scene_path := ""
var _out_path := "res://docs/ui_proxy/proxy.html"
var _title := "Godot UI Proxy"
var _viewport_size := Vector2(1280, 720)
var _calls: Array[String] = []


func _init() -> void:
	call_deferred("_start")


func _start() -> void:
	var ok := _parse_args()
	if not ok:
		_print_usage()
		quit(2)
		return
	var packed := load(_scene_path) as PackedScene
	if packed == null:
		push_error("Cannot load scene: %s" % _scene_path)
		quit(1)
		return
	var root_node := packed.instantiate()
	get_root().add_child(root_node)
	if root_node is Control:
		(root_node as Control).size = _viewport_size
	await process_frame
	await process_frame
	for call_spec in _calls:
		_apply_call(root_node, call_spec)
		await process_frame
		await process_frame
	DirAccess.make_dir_recursive_absolute(ProjectSettings.globalize_path(_out_path.get_base_dir()))
	var screenshot_path := _out_path.get_basename() + ".png"
	var screenshot_image := await _capture_viewport_screenshot()
	if screenshot_image == null or screenshot_image.is_empty():
		push_error("Failed to capture proxy screenshot")
		quit(1)
		return
	var screenshot_err := _save_screenshot_image(screenshot_image, screenshot_path)
	if screenshot_err != OK:
		push_error("Failed to write proxy screenshot: %s" % screenshot_path)
		quit(1)
		return
	var err := UiProxyExporter.write_scene_html(_out_path, root_node, _viewport_size, {
		"scene": _scene_path,
		"title": _title,
		"screenshot": screenshot_path.get_file(),
	})
	if err != OK:
		push_error("Failed to write proxy: %s" % _out_path)
		quit(1)
		return
	print("UI proxy written: %s" % _out_path)
	quit(0)


func _parse_args() -> bool:
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		match args[i]:
			"--scene":
				i += 1
				if i < args.size():
					_scene_path = args[i]
			"--out":
				i += 1
				if i < args.size():
					_out_path = args[i]
			"--title":
				i += 1
				if i < args.size():
					_title = args[i]
			"--width":
				i += 1
				if i < args.size():
					_viewport_size.x = float(args[i])
			"--height":
				i += 1
				if i < args.size():
					_viewport_size.y = float(args[i])
			"--call":
				i += 1
				if i < args.size():
					_calls.append(args[i])
		i += 1
	return _scene_path != ""


func _apply_call(root_node: Node, call_spec: String) -> void:
	var method := call_spec
	var arg_text := ""
	var sep := call_spec.find(":")
	if sep >= 0:
		method = call_spec.substr(0, sep)
		arg_text = call_spec.substr(sep + 1)
	if not root_node.has_method(method):
		push_warning("Export call skipped; method not found: %s" % method)
		return
	if arg_text == "":
		root_node.call(method)
	elif arg_text.is_valid_int():
		root_node.call(method, int(arg_text))
	elif arg_text.is_valid_float():
		root_node.call(method, float(arg_text))
	else:
		root_node.call(method, arg_text)


func _capture_viewport_screenshot() -> Image:
	await process_frame
	await process_frame
	var image := get_root().get_viewport().get_texture().get_image()
	if image == null or image.is_empty():
		return null
	return image


func _save_screenshot_image(image: Image, path: String) -> Error:
	var absolute_path := ProjectSettings.globalize_path(path)
	DirAccess.make_dir_recursive_absolute(absolute_path.get_base_dir())
	print("UI proxy screenshot written: %s" % path)
	return image.save_png(absolute_path)


func _print_usage() -> void:
	print("Usage: godot --resolution 1280x720 --path . --script tools/export_ui_proxy.gd -- --scene res://scenes/main.tscn --out res://docs/ui_proxy/main.html [--call enter_ui_state]")
