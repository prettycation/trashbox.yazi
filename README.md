# trashbox.yazi

[简体中文](./README.zh-CN.md)

A Yazi plugin for browsing and managing Trash / Recycle Bin directly from the main file manager UI.

Supported actions include:

- open Trash
- restore selected items
- permanently delete selected items
- empty all Trash
- empty items older than a given number of days

## Features

- Browse Trash directly in the Yazi main view
- Linux support via the real FreeDesktop Trash `files/` directory
- Windows support via aggregated per-volume Recycle Bin views
- Restore / delete / empty / empty-by-days actions
- Real-content preview support:
  - Linux: directly opens the real trash content directory
  - Windows: builds a merged view from per-volume Recycle Bin entries
- View names prefer original names, and only add suffixes on conflicts

## Platform Behavior

### Linux

On Linux, `trashbox.yazi` opens the real Trash content directory directly:

- Trash files are browsed from the actual `files/` directory
- restore and delete operations are resolved through the matching `.trashinfo` metadata

This means preview works naturally because Yazi is looking at the real trashed files.

### Windows

Windows Recycle Bin is not stored as one single global directory.

Each volume has its own Recycle Bin storage, so `trashbox.yazi` aggregates entries across available drives into a unified view.

This lets you browse Trash from one place inside Yazi.

## Requirements

- [Yazi](https://github.com/sxyazi/yazi)
- Python 3 available in `PATH`
- [`trashy`](https://github.com/oberblastmeister/trashy) available in `PATH`

## Installation

```sh
ya pkg add prettycation/trashbox
```

## Configuration

Add this to your Yazi `init.lua`:

```lua
require("trashbox"):setup({
 confirm_restore = true,
 confirm_delete = true,
 confirm_empty = true,
})
```

## Path Resolution

Plugin directory resolution order:

1. `YAZI_CONFIG_HOME`
2. Windows fallback: `%APPDATA%\yazi\config`
3. Other platforms fallback: `~/.config/yazi`

The adapter runtime data uses XDG-style directories:

- cache: `XDG_CACHE_HOME` or `~/.cache`
- state: `XDG_STATE_HOME` or `~/.local/state`

## Keybindings

### Recommended: Preset

Add this to your `~/.config/yazi/keymap.toml`:

```toml
[mgr]
prepend_keymap = [
  { on = ["R","t"], run = "plugin trashbox", desc = "Open Trash menu" },
]
```

`R t` opens a menu that provides access to all Trash management functions:

- `o` → Open Trash
- `r` → Restore from Trash
- `d` → Delete from Trash
- `e` → Empty Trash
- `D` → Empty by Days

> Tip
>
> `trashbox.yazi` uses the array form for its keymap example.
> You must pick only one style per file; mixing with `[[mgr.prepend_keymap]]` will fail.
>
> Also note: some plugins may suggest binding a bare key like `on = "R"`, which blocks all `R <key>` chords, including `R t`.
> Change those to chords such as `["R","r"]`, or choose a different non-conflicting prefix.

### Alternative: Custom Direct Keybinds

If you prefer direct keybinds, you can configure them like this:

```toml
[mgr]
prepend_keymap = [
  { on = ["R","o"], run = "plugin trashbox -- open",      desc = "Open Trash" },
  { on = ["R","e"], run = "plugin trashbox -- empty",     desc = "Empty Trash" },
  { on = ["R","D"], run = "plugin trashbox -- emptyDays", desc = "Empty by days deleted" },
  { on = ["R","d"], run = "plugin trashbox -- delete",    desc = "Delete from Trash" },
  { on = ["R","r"], run = "plugin trashbox -- restore",   desc = "Restore from Trash" },
]
```

## Commands

### `plugin trashbox`

Open the plugin action menu.

### `plugin trashbox -- open`

Open Trash in the Yazi main view.

- Linux: opens the real Trash content directory
- Windows: opens the aggregated Recycle Bin view

### `plugin trashbox -- put`

Move the selected or hovered file(s) to Trash.

### `plugin trashbox -- restore`

Restore the selected item(s) from the current Trash view.

### `plugin trashbox -- delete`

Permanently delete the selected item(s) from the current Trash view.

### `plugin trashbox -- empty`

Empty all Trash contents.

### `plugin trashbox -- emptyDays`

Delete Trash items older than a specified number of days.

The default prompt value is `30`.

## How It Works

### Linux

`trashbox.yazi` works directly against the real Trash structure:

- `files/`
- `info/`

The plugin opens the real content directory in Yazi, so preview and file inspection work naturally.

### Windows

`trashbox.yazi` scans per-volume Recycle Bin storage and builds a merged view for Yazi.

Important details:

- Recycle Bin entries are aggregated across available drives
- display names prefer the original filename
- if names conflict, suffixes such as `[2]`, `[3]`, etc. are added
- the merged view is rebuilt automatically when refreshed

## Notes

- On Windows, refresh creates a new view directory to avoid directory-lock issues when Yazi is currently inside the old view.
- On Linux, restore and delete rely on matching `.trashinfo` metadata.
- On Windows, restore and delete rely on aggregated view mapping and Recycle Bin metadata.
- If preview does not work for a specific item, it usually means the current environment could not materialize that entry into a previewable target safely.

## Troubleshooting

### `adapter not found or not runnable`

Make sure:

- the plugin is installed correctly
- Python is available in `PATH`
- `trashy` is available in `PATH`

### `trashy executable not found in PATH`

Install `trashy` and make sure it is accessible from your shell.

### Refresh fails on Windows

Older generated views may still be in use by another process.

The plugin avoids deleting the currently-open view by generating a fresh view directory during refresh.

### Weird names in Windows Trash view

This usually indicates problematic or incomplete Recycle Bin metadata parsing.

The current adapter prefers the original filename when possible and falls back more conservatively.

## Acknowledgements

This plugin draws design inspiration from [`recycle-bin.yazi`](https://github.com/uhs-robert/recycle-bin.yazi), especially in:

- keeping Trash operations inside the Yazi main UI as much as possible
- exposing the core action set of `open / restore / delete / empty / emptyDays`
- following a Yazi-friendly keybinding workflow

At the same time, this plugin uses a different backend implementation path in order to support Windows + Linux.

## License

MIT
