#!/usr/bin/env python3
"""
window_inspector.py - Windows 視窗結構探測工具
用途：探測視窗層級結構，特別用於診斷 MobaXterm 分頁標題取得方式

使用方式：
  python window_inspector.py
      列出所有頂層視窗

  python window_inspector.py --filter "MobaXterm"
      只列出 title 或 class 含 MobaXterm 的頂層視窗

  python window_inspector.py --deep "MobaXterm"
      找到 MobaXterm 視窗後，遞迴列出完整子控件樹
      特別標記含 [X390] 的控件
"""

import ctypes
import ctypes.wintypes
import sys
import argparse

# ─── Win32 API 初始化 ────────────────────────────────────────────────────────

user32 = ctypes.windll.user32
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.restype = ctypes.c_int
user32.IsWindowVisible.restype = ctypes.c_bool
user32.IsWindowEnabled.restype = ctypes.c_bool
user32.GetParent.restype = ctypes.wintypes.HWND
user32.GetWindowRect.restype = ctypes.c_bool
user32.EnumWindows.restype = ctypes.c_bool
user32.EnumChildWindows.restype = ctypes.c_bool

EnumWindowsProc = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPARAM,
)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left",   ctypes.c_long),
        ("top",    ctypes.c_long),
        ("right",  ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


# ─── 基礎 Win32 包裝函式 ─────────────────────────────────────────────────────

def get_window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def get_window_rect(hwnd: int) -> RECT:
    rect = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect


def is_visible(hwnd: int) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def is_enabled(hwnd: int) -> bool:
    return bool(user32.IsWindowEnabled(hwnd))


# ─── 列舉函式 ────────────────────────────────────────────────────────────────

def enum_top_level_windows() -> list:
    windows = []

    def _cb(hwnd, _lparam):
        windows.append(hwnd)
        return True

    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return windows


def enum_direct_children(parent_hwnd: int) -> list:
    """只回傳直接子視窗（排除孫代以下）"""
    children = []

    def _cb(hwnd, _lparam):
        if user32.GetParent(hwnd) == parent_hwnd:
            children.append(hwnd)
        return True

    user32.EnumChildWindows(parent_hwnd, EnumWindowsProc(_cb), 0)
    return children


# ─── 輸出格式 ────────────────────────────────────────────────────────────────

HIGHLIGHT_KEYWORD = "[X390]"


def format_info(hwnd: int, depth: int = 0) -> str:
    indent = "  " * depth
    title = get_window_text(hwnd)
    cls   = get_class_name(hwnd)
    rect  = get_window_rect(hwnd)
    vis   = is_visible(hwnd)
    ena   = is_enabled(hwnd)
    w     = rect.right  - rect.left
    h     = rect.bottom - rect.top

    # 特別標記含 [X390] 的控件
    flag = ""
    if HIGHLIGHT_KEYWORD in title or HIGHLIGHT_KEYWORD in cls:
        flag = f"  <<<< HIGHLIGHT: {HIGHLIGHT_KEYWORD} >>>>"

    lines = [
        f"{indent}HWND    : 0x{hwnd:08X}",
        f"{indent}Class   : {cls}",
        f"{indent}Title   : {title!r}{flag}",
        f"{indent}Rect    : ({rect.left}, {rect.top})  {w} x {h}",
        f"{indent}Visible : {vis}   Enabled : {ena}",
    ]
    return "\n".join(lines)


def print_tree(hwnd: int, depth: int = 0, max_depth: int = 12):
    print(format_info(hwnd, depth))
    print()

    if depth >= max_depth:
        indent = "  " * (depth + 1)
        print(f"{indent}[已達最大深度 {max_depth}，停止遞迴]")
        print()
        return

    children = enum_direct_children(hwnd)
    if children:
        indent = "  " * depth
        print(f"{indent}  [子控件數: {len(children)}]")
        print()
        for child in children:
            print_tree(child, depth + 1, max_depth)


# ─── 主要指令 ────────────────────────────────────────────────────────────────

def cmd_list(filter_kw: str | None):
    label = f"（過濾: {filter_kw}）" if filter_kw else ""
    print(f"=== 頂層視窗列表 {label}===")
    print()

    all_wins = enum_top_level_windows()
    if filter_kw:
        kw = filter_kw.lower()
        all_wins = [
            h for h in all_wins
            if kw in get_window_text(h).lower() or kw in get_class_name(h).lower()
        ]

    print(f"共 {len(all_wins)} 個視窗\n")
    print("=" * 60)

    for hwnd in all_wins:
        print(format_info(hwnd, depth=0))
        print()
    print("=" * 60)


def cmd_deep(target_kw: str):
    print(f"=== 深入探測含 '{target_kw}' 的視窗 ===")
    print()

    kw = target_kw.lower()
    found = [
        h for h in enum_top_level_windows()
        if kw in get_window_text(h).lower() or kw in get_class_name(h).lower()
    ]

    if not found:
        print(f"未找到含 '{target_kw}' 的頂層視窗")
        return

    print(f"找到 {len(found)} 個符合的頂層視窗")
    print(f"特別標記關鍵字：{HIGHLIGHT_KEYWORD}\n")

    for idx, hwnd in enumerate(found, 1):
        print(f"{'=' * 60}")
        print(f"[頂層視窗 {idx}/{len(found)}]")
        print(f"{'=' * 60}")
        print()
        print_tree(hwnd, depth=0)
        print(f"{'=' * 60}\n")


# ─── 入口 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="window_inspector.py",
        description="Windows 視窗結構探測工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
範例:
  python window_inspector.py
      列出所有頂層視窗

  python window_inspector.py --filter "MobaXterm"
      只列出 title/class 含 MobaXterm 的視窗

  python window_inspector.py --deep "MobaXterm"
      深入列出 MobaXterm 完整子控件樹，標記含 [X390] 的控件

  python window_inspector.py --deep "Notepad"
      深入列出記事本的控件結構（測試用）
""",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--filter",
        metavar="關鍵字",
        help="只列出 title 或 class 含該關鍵字的頂層視窗",
    )
    group.add_argument(
        "--deep",
        metavar="關鍵字",
        help="找到含該關鍵字的視窗後，遞迴列出所有子控件（含 [X390] 標記）",
    )

    args = parser.parse_args()

    if args.deep:
        cmd_deep(args.deep)
    else:
        cmd_list(args.filter)


if __name__ == "__main__":
    main()
