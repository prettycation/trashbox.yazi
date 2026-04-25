--- @since 26.1.22

local SEP = package.config:sub(1, 1)
local IS_WINDOWS = SEP == "\\"

local DEFAULTS = {
	confirm_restore = true,
	confirm_delete = true,
	confirm_empty = true,
}

local PLUGIN_NAME = "trashbox"
local _resolved_python = nil

local function clone(tbl)
	local out = {}
	for k, v in pairs(tbl or {}) do
		if type(v) == "table" then
			out[k] = clone(v)
		else
			out[k] = v
		end
	end
	return out
end

local function merge(dst, src)
	dst = dst or {}
	src = src or {}

	for k, v in pairs(src) do
		if type(v) == "table" and type(dst[k]) == "table" then
			dst[k] = merge(dst[k], v)
		else
			dst[k] = v
		end
	end

	return dst
end

local function merged_opts(opts)
	return merge(clone(DEFAULTS), opts or {})
end

local get_opts = ya.sync(function(state)
	return merged_opts(state.opts)
end)

local get_selected_real_paths = ya.sync(function()
	local paths = {}

	if #cx.active.selected > 0 then
		for _, url in pairs(cx.active.selected) do
			table.insert(paths, tostring(url))
		end
	else
		local hovered = cx.active.current.hovered
		if hovered then
			table.insert(paths, tostring(hovered.url))
		end
	end

	return paths
end)

local get_current_dir_and_selection = ya.sync(function()
	local cwd = ""
	if cx.active and cx.active.current and cx.active.current.cwd then
		cwd = tostring(cx.active.current.cwd)
	end

	local paths = {}
	if #cx.active.selected > 0 then
		for _, url in pairs(cx.active.selected) do
			table.insert(paths, tostring(url))
		end
	else
		local hovered = cx.active.current.hovered
		if hovered then
			table.insert(paths, tostring(hovered.url))
		end
	end

	return { cwd = cwd, paths = paths }
end)

local function sanitize_utf8(s)
	s = tostring(s or "")

	if utf8.len(s) then
		return s
	end

	s = s:gsub("[\128-\255]", "?")
	s = s:gsub("[%z\1-\8\11\12\14-\31]", " ")
	return s
end

local function notify(level, content, timeout)
	ya.notify({
		title = PLUGIN_NAME,
		content = sanitize_utf8(content),
		level = level or "info",
		timeout = timeout or 3,
	})
end

local function path_join(...)
	local parts = { ... }
	local out = nil

	for _, part in ipairs(parts) do
		if part and part ~= "" then
			part = tostring(part)
			if not out then
				out = part
			else
				local left = out:gsub("[/\\]+$", "")
				local right = part:gsub("^[/\\]+", "")
				out = left .. SEP .. right
			end
		end
	end

	return out
end

local function file_exists(path)
	if not path or path == "" then
		return false
	end

	local f = io.open(path, "r")
	if not f then
		return false
	end
	f:close()
	return true
end

local function file_name(path)
	if not path or path == "" then
		return ""
	end
	local normalized = path:gsub("[/\\]+$", "")
	local name = normalized:match("^.*[/\\](.*)$")
	return name or normalized
end

local function normalize_path(path)
	path = tostring(path or "")
	path = path:gsub("[/\\]+$", "")
	if IS_WINDOWS then
		path = path:gsub("/", "\\")
		path = string.lower(path)
	else
		path = path:gsub("\\", "/")
	end
	return path
end

local function yazi_config_home()
	local yazi = os.getenv("YAZI_CONFIG_HOME")
	if yazi and yazi ~= "" then
		return yazi
	end

	if IS_WINDOWS then
		local appdata = os.getenv("APPDATA")
		if appdata and appdata ~= "" then
			return path_join(appdata, "yazi", "config")
		end
	end

	local home = os.getenv("HOME") or os.getenv("USERPROFILE")
	if home and home ~= "" then
		return path_join(home, ".config", "yazi")
	end

	return nil
end

local function plugin_dir()
	local conf = yazi_config_home()
	if not conf then
		return nil
	end
	return path_join(conf, "plugins", "trashbox.yazi")
end

local function adapter_script()
	local dir = plugin_dir()
	if not dir then
		return nil
	end
	return path_join(dir, "adapter", "cli.py")
end

local function command_success(cmd, args)
	local status, err = Command(cmd):arg(args or {}):status()
	if not status then
		return false, err
	end
	return status.success == true
end

local function resolve_python_launcher()
	if _resolved_python ~= nil then
		return _resolved_python or nil
	end

	local candidates
	if IS_WINDOWS then
		candidates = {
			{ cmd = "py", args = { "-3" } },
			{ cmd = "python", args = {} },
			{ cmd = "python3", args = {} },
		}
	else
		candidates = {
			{ cmd = "python3", args = {} },
			{ cmd = "python", args = {} },
			{ cmd = "py", args = { "-3" } },
		}
	end

	for _, cand in ipairs(candidates) do
		local probe = {}
		for _, a in ipairs(cand.args) do
			table.insert(probe, a)
		end
		table.insert(probe, "--version")

		if command_success(cand.cmd, probe) then
			_resolved_python = cand
			return cand
		end
	end

	_resolved_python = false
	return nil
end

local function adapter_invocation(extra_args)
	local script = adapter_script()
	if not script then
		return nil, nil, "could not resolve Yazi config directory"
	end
	if not file_exists(script) then
		return nil, nil, "adapter script not found: " .. script
	end

	local py = resolve_python_launcher()
	if not py then
		return nil, nil, "python launcher not found (tried py -3 / python / python3)"
	end

	local cmd = py.cmd
	local args = {}

	for _, a in ipairs(py.args) do
		table.insert(args, a)
	end
	table.insert(args, script)

	for _, a in ipairs(extra_args or {}) do
		table.insert(args, tostring(a))
	end

	return cmd, args, nil
end

local function run_adapter(extra_args, silent)
	local cmd, args, cerr = adapter_invocation(extra_args)
	if not cmd then
		if not silent then
			notify("error", cerr, 8)
		end
		return nil, cerr
	end

	local output, err = Command(cmd):arg(args):output()
	if not output then
		if not silent then
			notify("error", ("failed to start adapter: %s"):format(tostring(err)), 8)
		end
		return nil, err
	end

	local stdout = sanitize_utf8(output.stdout or "")
	local stderr = sanitize_utf8(output.stderr or "")

	if not output.status.success then
		local msg = stderr ~= "" and stderr or stdout
		if msg == "" then
			msg = "adapter command failed"
		end
		if not silent then
			notify("error", msg, 8)
		end
		return nil, msg
	end

	return stdout:gsub("%s+$", ""), nil
end

local function adapter_ok()
	local out = run_adapter({ "--help" }, true)
	return out ~= nil
end

local function adapter_open_path(refresh)
	local args = { "open", "--path" }
	if refresh then
		table.insert(args, "--refresh")
	end
	return run_adapter(args, false)
end

local function open_view(refresh)
	local view_dir, err = adapter_open_path(refresh)
	if err or not view_dir or view_dir == "" then
		return false
	end

	ya.emit("cd", { Url(view_dir) })
	return true
end

local function in_trashbox_root()
	local root_dir, err = adapter_open_path(false)
	if err or not root_dir or root_dir == "" then
		return false, nil
	end

	local info = get_current_dir_and_selection()
	return normalize_path(info.cwd) == normalize_path(root_dir), info
end

local function current_view_names()
	local ok, info = in_trashbox_root()
	if not ok then
		return nil, "current directory is not the trashbox root"
	end

	local names = {}
	for _, p in ipairs(info.paths or {}) do
		local name = file_name(p)
		if name ~= "" then
			table.insert(names, name)
		end
	end

	if #names == 0 then
		return nil, "no trash item selected"
	end

	return names, nil
end

local function confirm_yes_no(title_yes, title_no)
	local choice = ya.which({
		cands = {
			{ on = "y", desc = title_yes },
			{ on = "n", desc = title_no or "Cancel" },
		},
	})
	return choice == 1
end

local function adapter_put()
	local paths = get_selected_real_paths()
	if #paths == 0 then
		notify("warn", "no file selected", 5)
		return
	end

	local args = { "put" }
	for _, p in ipairs(paths) do
		table.insert(args, p)
	end

	local _, err = run_adapter(args, false)
	if err then
		return
	end

	notify("info", ("trashed %d item(s)"):format(#paths), 4)
	ya.emit("refresh", {})
end

local function adapter_restore(opts)
	local names, err = current_view_names()
	if err then
		notify("warn", err, 5)
		return
	end

	if opts.confirm_restore and not confirm_yes_no(("Restore %d selected item(s)"):format(#names), "Cancel") then
		return
	end

	local args = { "restore", "--view-names" }
	for _, n in ipairs(names) do
		table.insert(args, n)
	end

	local _, rerr = run_adapter(args, false)
	if rerr then
		return
	end

	notify("info", ("restored %d item(s)"):format(#names), 4)
	open_view(true)
end

local function adapter_delete(opts)
	local names, err = current_view_names()
	if err then
		notify("warn", err, 5)
		return
	end

	if
		opts.confirm_delete
		and not confirm_yes_no(("Delete %d selected item(s) permanently"):format(#names), "Cancel")
	then
		return
	end

	local args = { "delete", "--view-names" }
	for _, n in ipairs(names) do
		table.insert(args, n)
	end

	local _, derr = run_adapter(args, false)
	if derr then
		return
	end

	notify("info", ("deleted %d item(s) permanently"):format(#names), 4)
	open_view(true)
end

local function adapter_empty(opts)
	if opts.confirm_empty and not confirm_yes_no("Empty all trash", "Cancel") then
		return
	end

	local _, err = run_adapter({ "empty", "--all" }, false)
	if err then
		return
	end

	notify("info", "trash emptied", 4)
	open_view(true)
end

local function adapter_empty_days(opts)
	local value, event = ya.input({
		title = "Empty trash items older than how many days?",
		pos = { "top-center", y = 2, w = 50 },
		value = "30",
	})

	if event ~= 1 or not value or value == "" then
		return
	end

	local days = tonumber(value)
	if not days or days < 0 then
		notify("warn", "days must be a non-negative number", 5)
		return
	end

	days = math.floor(days)

	if opts.confirm_empty and not confirm_yes_no(("Delete trash items older than %d days"):format(days), "Cancel") then
		return
	end

	local _, err = run_adapter({ "emptyDays", "--days", tostring(days) }, false)
	if err then
		return
	end

	notify("info", ("deleted trash items older than %d days"):format(days), 4)
	open_view(true)
end

local function action_menu(opts)
	local choice = ya.which({
		cands = {
			{ on = "o", desc = "Open Trash" },
			{ on = "p", desc = "Put selected / hovered item(s) into Trash" },
			{ on = "r", desc = "Restore selected Trash item(s)" },
			{ on = "d", desc = "Delete selected Trash item(s)" },
			{ on = "e", desc = "Empty Trash" },
			{ on = "D", desc = "Empty by days deleted" },
			{ on = "q", desc = "Cancel" },
		},
	})

	if choice == 1 then
		open_view(true)
	elseif choice == 2 then
		adapter_put()
	elseif choice == 3 then
		adapter_restore(opts)
	elseif choice == 4 then
		adapter_delete(opts)
	elseif choice == 5 then
		adapter_empty(opts)
	elseif choice == 6 then
		adapter_empty_days(opts)
	end
end

return {
	setup = function(state, opts)
		state.opts = merged_opts(opts)
	end,

	entry = function(_, job)
		local opts = get_opts()

		if not adapter_ok() then
			notify("error", "adapter not found or not runnable", 8)
			return
		end

		local action = job and job.args and job.args[1] or nil

		if action == nil then
			action_menu(opts)
		elseif action == "open" or action == "list" then
			open_view(true)
		elseif action == "put" then
			adapter_put()
		elseif action == "restore" then
			adapter_restore(opts)
		elseif action == "delete" then
			adapter_delete(opts)
		elseif action == "empty" then
			adapter_empty(opts)
		elseif action == "emptyDays" then
			adapter_empty_days(opts)
		else
			notify("error", "unknown action: " .. tostring(action), 8)
		end
	end,
}
