#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import ctypes
import json
import os
import re
import shutil
import string
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


APP_NAME = "trashbox-adapter"
MAP_FILE_NAME = "view-map.json"
CURRENT_VIEW_FILE_NAME = "current-view.txt"


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def fail(message: str, code: int = 1) -> None:
    message = str(message or "")
    try:
        sys.stderr.write(message + "\n")
    except Exception:
        sys.stderr.write(
            message.encode("utf-8", errors="replace").decode("utf-8") + "\n"
        )
    raise SystemExit(code)


def is_windows() -> bool:
    return os.name == "nt"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def parse_iso_datetime(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None

    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)

    return dt


def xdg_home(kind: str) -> Path:
    home = Path.home()

    if kind == "cache":
        return Path(os.environ.get("XDG_CACHE_HOME", home / ".cache"))
    if kind == "state":
        return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state"))
    if kind == "data":
        return Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

    raise ValueError(f"unknown XDG kind: {kind}")


def cache_root() -> Path:
    return xdg_home("cache") / APP_NAME


def state_root() -> Path:
    return xdg_home("state") / APP_NAME


def windows_views_root() -> Path:
    return cache_root() / "views"


def map_file() -> Path:
    return state_root() / MAP_FILE_NAME


def current_view_file() -> Path:
    return state_root() / CURRENT_VIEW_FILE_NAME


def ensure_dirs() -> None:
    cache_root().mkdir(parents=True, exist_ok=True)
    state_root().mkdir(parents=True, exist_ok=True)
    if is_windows():
        windows_views_root().mkdir(parents=True, exist_ok=True)


def print_json(data: Any) -> None:
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def print_path(path: Path) -> None:
    sys.stdout.write(str(path))
    sys.stdout.write("\n")


def trashy_bin() -> str:
    candidates = ["trashy"]
    if is_windows():
        candidates.extend(["trash.exe", "trash"])

    for name in candidates:
        if shutil.which(name):
            return name

    fail("`trashy` executable not found in PATH")


def run_trashy(args: list[str]) -> subprocess.CompletedProcess[str]:
    exe = trashy_bin()
    proc = subprocess.run(
        [exe, *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        msg = (
            proc.stderr.strip()
            or proc.stdout.strip()
            or f"`{exe}` exited with {proc.returncode}"
        )
        fail(msg, proc.returncode)
    return proc


@dataclass
class LinuxEntry:
    name: str
    file_path: str
    info_path: str
    original_path: str
    deleted_at: str
    is_dir: bool


@dataclass
class WindowsEntry:
    backend_id: str
    volume: str
    sid: str
    i_path: str
    r_path: str
    original_path: str
    deleted_at: str
    display_name: str
    is_dir: bool
    view_name: str = ""


def basename_any(path: str) -> str:
    path = path.rstrip("/\\")
    if not path:
        return ""
    return re.split(r"[\\/]", path)[-1]


def sanitize_view_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        name = "item"

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"\s+", " ", name).strip()

    if name in {"", ".", ".."}:
        name = "item"

    return name


def split_name_ext(name: str) -> tuple[str, str]:
    if name.startswith(".") and name.count(".") == 1:
        return name, ""
    p = Path(name)
    suffix = p.suffix
    if suffix:
        return name[: -len(suffix)], suffix
    return name, ""


def used_key(name: str) -> str:
    return name.lower() if is_windows() else name


def unique_view_name(original_name: str, used: set[str]) -> str:
    base = sanitize_view_name(original_name)
    key = used_key(base)
    if key not in used:
        used.add(key)
        return base

    stem, ext = split_name_ext(base)
    i = 2
    while True:
        candidate = f"{stem} [{i}]{ext}"
        key = used_key(candidate)
        if key not in used:
            used.add(key)
            return candidate
        i += 1


def looks_suspicious_display_name(name: str) -> bool:
    s = (name or "").strip()
    if not s:
        return True

    low = s.lower()
    if low.startswith("$i") or low.startswith("$r"):
        return True

    if len(s) == 1 and not s.isalnum():
        return True

    if len(s) <= 3 and all(not ch.isalnum() for ch in s):
        return True

    return False


def choose_display_name(original_path: str, r_file: Path, i_file: Path) -> str:
    candidates = [
        basename_any(original_path),
        basename_any(str(r_file)),
        i_file.name,
    ]

    for c in candidates:
        if c and not looks_suspicious_display_name(c):
            return c

    for c in candidates:
        if c:
            return c

    return "item"


# -------------------------
# Linux
# -------------------------


def linux_trash_root() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home) / "Trash"
    return Path.home() / ".local" / "share" / "Trash"


def linux_files_dir() -> Path:
    return linux_trash_root() / "files"


def linux_info_dir() -> Path:
    return linux_trash_root() / "info"


def ensure_linux_trash_dirs() -> None:
    linux_files_dir().mkdir(parents=True, exist_ok=True)
    linux_info_dir().mkdir(parents=True, exist_ok=True)


def linux_parse_trashinfo(path: Path) -> tuple[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    if not parser.has_section("Trash Info"):
        fail(f"invalid trashinfo: {path}")

    original_path = parser.get("Trash Info", "Path", fallback="")
    deleted_at = parser.get("Trash Info", "DeletionDate", fallback="")

    try:
        from urllib.parse import unquote

        original_path = unquote(original_path)
    except Exception:
        pass

    return original_path, deleted_at


def linux_entries() -> list[LinuxEntry]:
    ensure_linux_trash_dirs()

    out: list[LinuxEntry] = []
    files_dir = linux_files_dir()
    info_dir = linux_info_dir()

    for child in sorted(files_dir.iterdir(), key=lambda p: p.name.lower()):
        info_path = info_dir / f"{child.name}.trashinfo"
        if not info_path.exists():
            continue

        original_path, deleted_at = linux_parse_trashinfo(info_path)
        out.append(
            LinuxEntry(
                name=child.name,
                file_path=str(child),
                info_path=str(info_path),
                original_path=original_path,
                deleted_at=deleted_at,
                is_dir=child.is_dir(),
            )
        )

    return out


def linux_open_path() -> Path:
    ensure_linux_trash_dirs()
    return linux_files_dir()


def linux_restore(view_names: list[str]) -> None:
    files_dir = linux_files_dir()
    info_dir = linux_info_dir()

    for name in view_names:
        name = basename_any(name)
        file_path = files_dir / name
        trashinfo = info_dir / f"{name}.trashinfo"

        if not file_path.exists():
            fail(f"trash item not found: {name}")
        if not trashinfo.exists():
            fail(f"trash metadata not found: {trashinfo}")

        original_path, _ = linux_parse_trashinfo(trashinfo)
        if not original_path:
            fail(f"original path missing in trashinfo: {trashinfo}")

        target = Path(original_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            fail(f"restore target already exists: {target}")

        shutil.move(str(file_path), str(target))
        trashinfo.unlink(missing_ok=True)


def linux_delete(view_names: list[str]) -> None:
    files_dir = linux_files_dir()
    info_dir = linux_info_dir()

    for name in view_names:
        name = basename_any(name)
        file_path = files_dir / name
        trashinfo = info_dir / f"{name}.trashinfo"

        if file_path.exists():
            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()

        trashinfo.unlink(missing_ok=True)


def linux_empty() -> None:
    files_dir = linux_files_dir()
    info_dir = linux_info_dir()

    if files_dir.exists():
        for child in files_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    if info_dir.exists():
        for child in info_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()


def linux_empty_days(days: int) -> None:
    cutoff = datetime.now().astimezone() - timedelta(days=days)

    for entry in linux_entries():
        dt = parse_iso_datetime(entry.deleted_at)
        if dt is None:
            continue
        if dt > cutoff:
            continue

        file_path = Path(entry.file_path)
        info_path = Path(entry.info_path)

        if file_path.exists():
            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()

        info_path.unlink(missing_ok=True)


# -------------------------
# Windows
# -------------------------


def windows_logical_drives() -> list[str]:
    kernel32 = ctypes.windll.kernel32

    DRIVE_UNKNOWN = 0
    DRIVE_NO_ROOT_DIR = 1
    DRIVE_REMOVABLE = 2
    DRIVE_FIXED = 3
    DRIVE_REMOTE = 4
    DRIVE_CDROM = 5
    DRIVE_RAMDISK = 6

    bitmask = kernel32.GetLogicalDrives()
    if bitmask == 0:
        return []

    drives: list[str] = []

    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask & (1 << i)):
            continue

        root = f"{letter}:\\"
        drive_type = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))

        if drive_type in (DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR, DRIVE_CDROM):
            continue

        try:
            os.listdir(root)
        except OSError:
            continue

        if drive_type in (DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_RAMDISK):
            drives.append(root)

    return drives


def filetime_to_iso(filetime_value: int) -> str:
    if not filetime_value:
        return ""
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    dt = epoch + timedelta(microseconds=filetime_value / 10)
    return dt.astimezone().isoformat(timespec="seconds")


def parse_windows_i_file(i_path: Path) -> tuple[str, str]:
    data = i_path.read_bytes()
    if len(data) < 24:
        return "", ""

    version = int.from_bytes(data[0:8], "little", signed=False)
    deleted_filetime = int.from_bytes(data[16:24], "little", signed=False)
    deleted_at = filetime_to_iso(deleted_filetime)

    original_path = ""

    if version == 1:
        raw = data[24:]
        original_path = raw.decode("utf-16le", errors="ignore").split("\x00", 1)[0]

    elif version == 2:
        if len(data) >= 28:
            char_count = int.from_bytes(data[24:28], "little", signed=False)
            raw = data[28:]
            if char_count > 0:
                raw = raw[: char_count * 2]
            original_path = raw.decode("utf-16le", errors="ignore").split("\x00", 1)[0]

    else:
        if len(data) >= 28:
            char_count = int.from_bytes(data[24:28], "little", signed=False)
            raw = data[28:]
            if 0 < char_count < 32768:
                try:
                    raw2 = raw[: char_count * 2]
                    original_path = raw2.decode("utf-16le", errors="ignore").split(
                        "\x00", 1
                    )[0]
                except Exception:
                    original_path = ""

        if not original_path:
            raw = data[24:]
            original_path = raw.decode("utf-16le", errors="ignore").split("\x00", 1)[0]

    original_path = original_path.strip()
    return original_path, deleted_at


def windows_entries() -> list[WindowsEntry]:
    out: list[WindowsEntry] = []

    for drive in windows_logical_drives():
        recycle_root = Path(drive) / "$Recycle.Bin"
        if not recycle_root.exists():
            continue

        try:
            sid_dirs = list(recycle_root.iterdir())
        except Exception:
            continue

        for sid_dir in sid_dirs:
            if not sid_dir.is_dir():
                continue

            sid = sid_dir.name
            try:
                i_files = list(sid_dir.glob("$I*"))
            except Exception:
                continue

            for i_file in i_files:
                if not i_file.is_file():
                    continue

                r_file = i_file.with_name("$R" + i_file.name[2:])
                if not r_file.exists():
                    continue

                try:
                    original_path, deleted_at = parse_windows_i_file(i_file)
                except Exception:
                    original_path, deleted_at = "", ""

                display_name = choose_display_name(original_path, r_file, i_file)
                backend_id = f"win:{drive}:{sid}:{i_file.name}"

                out.append(
                    WindowsEntry(
                        backend_id=backend_id,
                        volume=drive,
                        sid=sid,
                        i_path=str(i_file),
                        r_path=str(r_file),
                        original_path=original_path,
                        deleted_at=deleted_at,
                        display_name=display_name,
                        is_dir=r_file.is_dir(),
                    )
                )

    out.sort(
        key=lambda e: (
            (e.display_name or "").lower(),
            e.deleted_at,
            (e.original_path or "").lower(),
            e.backend_id.lower(),
        )
    )
    return out


def remove_path(path: Path) -> None:
    try:
        if not path.exists() and not path.is_symlink():
            return
    except Exception:
        pass

    try:
        if path.is_symlink():
            path.unlink(missing_ok=True)
            return
    except Exception:
        pass

    if path.exists():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def create_symlink(link: Path, target: Path, is_dir: bool) -> bool:
    try:
        os.symlink(str(target), str(link), target_is_directory=is_dir)
        return True
    except Exception:
        return False


def create_hardlink(link: Path, target: Path) -> bool:
    try:
        os.link(str(target), str(link))
        return True
    except Exception:
        return False


def create_junction(link: Path, target: Path) -> bool:
    try:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode == 0
    except Exception:
        return False


def materialize_file(link: Path, target: Path) -> None:
    remove_path(link)

    if create_symlink(link, target, False):
        return

    same_drive = link.drive.lower() == target.drive.lower()
    if same_drive and create_hardlink(link, target):
        return

    remove_path(link)
    shutil.copy2(target, link)


def materialize_dir(link: Path, target: Path) -> None:
    remove_path(link)

    if create_symlink(link, target, True):
        return

    remove_path(link)
    if create_junction(link, target):
        return

    remove_path(link)
    shutil.copytree(target, link)


def write_current_view(path: Path) -> None:
    current_view_file().write_text(str(path), encoding="utf-8")


def read_current_view() -> Path | None:
    path = current_view_file()
    if not path.exists():
        return None

    try:
        value = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None

    if not value:
        return None

    p = Path(value)
    if p.exists():
        return p
    return None


def best_effort_cleanup_old_views(keep: Path) -> None:
    root = windows_views_root()
    if not root.exists():
        return

    for child in root.iterdir():
        if child == keep:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            pass


def materialize_windows_view(entries: list[WindowsEntry]) -> Path:
    ensure_dirs()

    root_parent = windows_views_root()
    root_parent.mkdir(parents=True, exist_ok=True)

    view_root = root_parent / f"view-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
    view_root.mkdir(parents=True, exist_ok=False)

    used: set[str] = set()
    mapping: dict[str, Any] = {}

    for entry in entries:
        view_name = unique_view_name(entry.display_name or "item", used)
        entry.view_name = view_name

        target = Path(entry.r_path)
        link = view_root / view_name

        if entry.is_dir:
            materialize_dir(link, target)
        else:
            materialize_file(link, target)

        mapping[view_name] = {
            "backend_id": entry.backend_id,
            "volume": entry.volume,
            "sid": entry.sid,
            "i_path": entry.i_path,
            "r_path": entry.r_path,
            "original_path": entry.original_path,
            "deleted_at": entry.deleted_at,
            "display_name": entry.display_name,
            "is_dir": entry.is_dir,
        }

    payload = {
        "version": 1,
        "platform": "windows",
        "generated_at": now_iso(),
        "view_dir": str(view_root),
        "items": mapping,
    }

    map_file().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_current_view(view_root)
    best_effort_cleanup_old_views(view_root)

    return view_root


def load_windows_map() -> dict[str, Any]:
    path = map_file()
    if not path.exists():
        fail("view map not found, run `open --path --refresh` first")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"failed to read view map: {exc}")

    return payload.get("items", {})


def resolve_windows_view_names(view_names: list[str]) -> list[dict[str, Any]]:
    if not view_names:
        fail("no view names provided")

    mapping = load_windows_map()
    out = []

    for name in view_names:
        entry = mapping.get(basename_any(name))
        if not entry:
            fail(f"unknown view item: {name}")
        out.append(entry)

    return out


def windows_open_path(refresh: bool) -> Path:
    ensure_dirs()

    current = read_current_view()
    if refresh or current is None or not map_file().exists():
        entries = windows_entries()
        return materialize_windows_view(entries)

    return current


def windows_restore(view_names: list[str]) -> None:
    entries = resolve_windows_view_names(view_names)

    for entry in entries:
        r_path = Path(entry["r_path"])
        i_path = Path(entry["i_path"])
        original_path = Path(entry["original_path"])

        if not r_path.exists():
            fail(f"missing recycle data file: {r_path}")

        original_path.parent.mkdir(parents=True, exist_ok=True)
        if original_path.exists():
            fail(f"restore target already exists: {original_path}")

        shutil.move(str(r_path), str(original_path))
        i_path.unlink(missing_ok=True)


def windows_delete(view_names: list[str]) -> None:
    entries = resolve_windows_view_names(view_names)

    for entry in entries:
        r_path = Path(entry["r_path"])
        i_path = Path(entry["i_path"])

        remove_path(r_path)
        i_path.unlink(missing_ok=True)


def windows_empty() -> None:
    entries = windows_entries()
    for entry in entries:
        remove_path(Path(entry.r_path))
        Path(entry.i_path).unlink(missing_ok=True)


def windows_empty_days(days: int) -> None:
    cutoff = datetime.now().astimezone() - timedelta(days=days)

    for entry in windows_entries():
        dt = parse_iso_datetime(entry.deleted_at)
        if dt is None:
            continue
        if dt > cutoff:
            continue

        remove_path(Path(entry.r_path))
        Path(entry.i_path).unlink(missing_ok=True)


# -------------------------
# Common commands
# -------------------------


def cmd_put(paths: list[str]) -> None:
    if not paths:
        fail("no input paths")
    run_trashy(["put", *paths])
    print_json(
        {
            "ok": True,
            "action": "put",
            "count": len(paths),
            "paths": paths,
        }
    )


def cmd_open(refresh: bool, want_path: bool, want_json: bool) -> None:
    if is_windows():
        root = windows_open_path(refresh)
    else:
        root = linux_open_path()

    if want_path:
        print_path(root)
        return

    if want_json:
        print_json(
            {
                "ok": True,
                "path": str(root),
                "platform": "windows" if is_windows() else "linux",
            }
        )
        return

    fail("one of --path / --json is required")


def cmd_restore(view_names: list[str]) -> None:
    if is_windows():
        windows_restore(view_names)
    else:
        linux_restore(view_names)

    print_json(
        {
            "ok": True,
            "action": "restore",
            "count": len(view_names),
            "view_names": view_names,
        }
    )


def cmd_delete(view_names: list[str]) -> None:
    if is_windows():
        windows_delete(view_names)
    else:
        linux_delete(view_names)

    print_json(
        {
            "ok": True,
            "action": "delete",
            "count": len(view_names),
            "view_names": view_names,
        }
    )


def cmd_empty(all_flag: bool) -> None:
    if not all_flag:
        fail("only `empty --all` is supported")

    if is_windows():
        windows_empty()
    else:
        linux_empty()

    print_json(
        {
            "ok": True,
            "action": "empty",
            "all": True,
        }
    )


def cmd_empty_days(days: int) -> None:
    if days < 0:
        fail("days must be non-negative")

    if is_windows():
        windows_empty_days(days)
    else:
        linux_empty_days(days)

    print_json(
        {
            "ok": True,
            "action": "emptyDays",
            "days": days,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME)
    sub = parser.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser("open")
    g = p_open.add_mutually_exclusive_group(required=True)
    g.add_argument("--path", action="store_true")
    g.add_argument("--json", action="store_true")
    p_open.add_argument("--refresh", action="store_true")

    p_put = sub.add_parser("put")
    p_put.add_argument("paths", nargs="+")

    p_restore = sub.add_parser("restore")
    p_restore.add_argument("--view-names", nargs="+", required=True)

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("--view-names", nargs="+", required=True)

    p_empty = sub.add_parser("empty")
    p_empty.add_argument("--all", action="store_true")

    p_empty_days = sub.add_parser("emptyDays")
    p_empty_days.add_argument("--days", type=int, required=True)

    return parser


def main() -> None:
    ensure_dirs()

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "open":
        cmd_open(refresh=args.refresh, want_path=args.path, want_json=args.json)
    elif args.command == "put":
        cmd_put(args.paths)
    elif args.command == "restore":
        cmd_restore(args.view_names)
    elif args.command == "delete":
        cmd_delete(args.view_names)
    elif args.command == "empty":
        cmd_empty(args.all)
    elif args.command == "emptyDays":
        cmd_empty_days(args.days)
    else:
        fail(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
