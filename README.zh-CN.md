# trashbox.yazi

[English](./README.md)

一个在 Yazi 主文件管理界面中直接浏览和管理回收站的插件。

支持的操作包括：

- 打开回收站
- 恢复选中条目
- 永久删除选中条目
- 清空全部回收站
- 按删除天数清理旧条目

## 特性

- 在 Yazi 主界面中直接浏览回收站
- Linux 通过真实的 FreeDesktop Trash `files/` 目录工作
- Windows 通过聚合各分区的 Recycle Bin 视图工作
- 支持 restore / delete / empty / empty-by-days 操作
- 支持真实内容预览：
  - Linux：直接打开真实的 trash 内容目录
  - Windows：基于各分区回收站条目构建统一视图
- 视图命名优先使用原始文件名，只有冲突时才追加后缀

## 平台行为

### Linux

在 Linux 上，`trashbox.yazi` 会直接打开真实的 Trash 内容目录：

- 回收站文件直接来自真实的 `files/` 目录
- restore 和 delete 通过匹配的 `.trashinfo` 元数据解析

这意味着预览可以自然工作，因为 Yazi 看到的就是实际被移入回收站的文件。

### Windows

Windows 回收站并不是一个单一的全局目录。

每个分区都有自己的 Recycle Bin 存储位置，所以 `trashbox.yazi` 会把所有可用驱动器上的条目聚合成一个统一视图。

这样你就可以在 Yazi 中通过一个入口浏览回收站。

## 依赖

- [Yazi](https://github.com/sxyazi/yazi)
- `PATH` 中可用的 Python 3
- `PATH` 中可用的 [`trashy`](https://github.com/oberblastmeister/trashy)

## 安装

```sh
ya pkg add prettycation/trashbox
```

## 配置

把下面内容加入你的 Yazi `init.lua`：

```lua
require("trashbox"):setup({
 confirm_restore = true,
 confirm_delete = true,
 confirm_empty = true,
})
```

## 路径解析

插件目录解析顺序：

1. `YAZI_CONFIG_HOME`
2. Windows 回退到 `%APPDATA%\yazi\config`
3. 其他平台回退到 `~/.config/yazi`

adapter 运行时数据使用 XDG 风格目录：

- cache：`XDG_CACHE_HOME` 或 `~/.cache`
- state：`XDG_STATE_HOME` 或 `~/.local/state`

## 键位绑定

### 推荐：Preset

把下面内容加入你的 `~/.config/yazi/keymap.toml`：

```toml
[mgr]
prepend_keymap = [
  { on = ["R","t"], run = "plugin trashbox", desc = "打开回收站菜单" },
]
```

`R t` 会打开一个菜单，提供所有回收站管理功能：

- `o` → 打开回收站
- `r` → 从回收站恢复
- `d` → 从回收站删除
- `e` → 清空回收站
- `D` → 按删除天数清理

> 提示
>
> `trashbox.yazi` 的示例使用的是数组形式的 keymap。
> 在同一个文件中你必须只选择一种写法；不要和 `[[mgr.prepend_keymap]]` 混用，否则会失败。
>
> 另外还要注意：有些插件会建议绑定裸键，比如 `on = "R"`，这会阻塞所有 `R <key>` 组合键，包括 `R t`。
> 请把这类绑定改成组合键，比如 `["R","r"]`，或者改用其他不冲突的前缀。

### 可选：自定义 Direct Keybinds

如果你更喜欢直接绑定每个动作，也可以这样配置：

```toml
[mgr]
prepend_keymap = [
  { on = ["R","o"], run = "plugin trashbox -- open",      desc = "打开回收站" },
  { on = ["R","e"], run = "plugin trashbox -- empty",     desc = "清空回收站" },
  { on = ["R","D"], run = "plugin trashbox -- emptyDays", desc = "按删除天数清理" },
  { on = ["R","d"], run = "plugin trashbox -- delete",    desc = "从回收站删除" },
  { on = ["R","r"], run = "plugin trashbox -- restore",   desc = "从回收站恢复" },
]
```

## 命令

### `plugin trashbox`

打开插件动作菜单。

### `plugin trashbox -- open`

在 Yazi 主界面中打开回收站。

- Linux：打开真实的 Trash 内容目录
- Windows：打开聚合后的 Recycle Bin 视图

### `plugin trashbox -- put`

把当前选中或悬停的文件移入回收站。

### `plugin trashbox -- restore`

恢复当前回收站视图中选中的条目。

### `plugin trashbox -- delete`

永久删除当前回收站视图中选中的条目。

### `plugin trashbox -- empty`

清空全部回收站内容。

### `plugin trashbox -- emptyDays`

删除早于指定天数的回收站条目。

默认提示值为 `30`。

## 工作原理

### Linux

`trashbox.yazi` 直接基于真实 Trash 结构工作：

- `files/`
- `info/`

插件会在 Yazi 中直接打开真实内容目录，因此预览和文件查看可以自然工作。

### Windows

`trashbox.yazi` 会扫描各分区的 Recycle Bin 存储，并为 Yazi 构建一个统一视图。

关键点包括：

- 聚合所有可用驱动器上的回收站条目
- 显示名优先使用原始文件名
- 如果名称冲突，会自动追加 `[2]`、`[3]` 等后缀
- 刷新时会自动重建统一视图

## 说明

- 在 Windows 上，刷新时会创建新的 view 目录，以避免 Yazi 当前正停留在旧 view 中时出现目录锁问题。
- 在 Linux 上，restore 和 delete 依赖匹配的 `.trashinfo` 元数据。
- 在 Windows 上，restore 和 delete 依赖聚合视图映射以及 Recycle Bin 元数据。
- 如果某个条目无法预览，通常意味着当前环境下无法把该条目安全地 materialize 成可预览目标。

## 故障排查

### `adapter not found or not runnable`

请确认：

- 插件已正确安装
- Python 已在 `PATH` 中
- `trashy` 已在 `PATH` 中

### `trashy executable not found in PATH`

请安装 `trashy`，并确认当前 shell 可以直接运行它。

### Windows 上刷新失败

旧的 view 目录可能仍然被其他进程占用。

插件会通过“刷新时生成新的 view 目录”的方式来避免删除当前正在使用的视图。

### Windows 回收站中出现奇怪名字

这通常意味着 Recycle Bin 元数据解析不完整或存在异常。

当前 adapter 会尽量优先使用原始文件名，并采用更保守的回退逻辑。

## 致谢

本插件在设计上借鉴了 [`recycle-bin.yazi`](https://github.com/uhs-robert/recycle-bin.yazi)，尤其包括：

- 尽可能把回收站操作留在 Yazi 主界面中完成
- 提供 `open / restore / delete / empty / emptyDays` 这组核心动作
- 采用贴近 Yazi 工作流的键位设计

同时，为了支持 Windows + Linux，本插件在底层实现路径上做了不同的适配。

## 许可证

MIT
