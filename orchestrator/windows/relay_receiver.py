# relay_receiver.py -- Windows 端 Relay Receiver (Phase 2)
#
# == 安裝說明 ==
# 1. 確認 Python 3.8+ 已安裝
# 2. 安裝依賴套件：
#    pip install flask pyperclip
#    （pyperclip 在 Windows 無需額外安裝即可使用剪貼簿）
#    ctypes 為 Python 內建，不需額外安裝
#
# == 執行說明 ==
# 顯示使用說明：
#    python relay_receiver.py
#
# 啟動 server（預設 port 5200）：
#    python relay_receiver.py --serve
#
# 指定 port：
#    python relay_receiver.py --serve --port 5200
#
# == 測試方式（從 Ubuntu 端） ==
# curl -X POST http://192.168.0.10:5200/relay \
#   -H "Content-Type: application/json" \
#   -d '{"action":"paste","message":"echo hello","target":"[X390]","source":"ubuntu","timestamp":"2026-04-11T19:00:00"}'
#
# == Phase 2 功能 ==
# action="paste" 將自動：
#   1. 尋找 MobaXterm 主視窗
#   2. 若當前分頁不含 target 關鍵字，循環 Ctrl+Tab 直到找到（最多 10 次）
#   3. 用 pyperclip 設定剪貼簿，模擬 Ctrl+V + Enter
#   4. 找不到時退回 Phase 1（僅剪貼簿 + 提示）

import sys
import time
import argparse
import logging
import platform
from datetime import datetime
from collections import deque

from flask import Flask, request, jsonify

# 嘗試匯入 pyperclip（非強制依賴）
try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

# 嘗試匯入 ctypes Windows 模組（僅 Windows 可用）
IS_WINDOWS = platform.system() == "Windows"
if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
else:
    ctypes = None
    wintypes = None
    _user32 = None
    _kernel32 = None

# --------------------------------------------------------------------------
# 初始化
# --------------------------------------------------------------------------

app = Flask(__name__)
log = logging.getLogger("relay_receiver")

# 保留最近 10 筆收到的訊息摘要
_recent_messages: deque = deque(maxlen=10)

# --------------------------------------------------------------------------
# Windows ctypes 結構定義（Phase 2）
# --------------------------------------------------------------------------

if IS_WINDOWS:
    # Virtual Key Codes
    VK_CONTROL = 0x11
    VK_SHIFT   = 0x10
    VK_V       = 0x56
    VK_INSERT  = 0x2D
    VK_RETURN  = 0x0D
    VK_TAB     = 0x09

    INPUT_KEYBOARD      = 1
    KEYEVENTF_KEYUP     = 0x0002
    KEYEVENTF_EXTENDEDKEY = 0x0001

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         wintypes.WORD),
            ("wScan",       wintypes.WORD),
            ("dwFlags",     wintypes.DWORD),
            ("time",        wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("ki",      KEYBDINPUT),
            ("padding", ctypes.c_byte * 32),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type",   wintypes.DWORD),
            ("_input", _INPUT_UNION),
        ]

    def _make_key_input(vk: int, flags: int = 0) -> "INPUT":
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp._input.ki.wVk = vk
        inp._input.ki.dwFlags = flags
        return inp

    def _send_keys(*key_inputs):
        """批次送出 INPUT 序列。"""
        arr = (INPUT * len(key_inputs))(*key_inputs)
        _user32.SendInput(len(key_inputs), arr, ctypes.sizeof(INPUT))


# --------------------------------------------------------------------------
# Phase 2 核心函式
# --------------------------------------------------------------------------

def _get_window_title(hwnd: int) -> str:
    """取得指定 hwnd 的視窗標題。"""
    if not IS_WINDOWS:
        return ""
    buf = ctypes.create_unicode_buffer(512)
    _user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def _enum_windows_callback(target_kw: str, result_list: list):
    """回傳供 EnumWindows 使用的 callback，找到含 target_kw 的視窗就存入 result_list。"""
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _get_window_title(hwnd)
        if target_kw.lower() in title.lower():
            result_list.append(hwnd)
        return True

    return WNDENUMPROC(callback)


def _find_mobaxterm_hwnd() -> int:
    """
    尋找 MobaXterm 主視窗（任意標題）。
    MobaXterm 的 class name 通常含 "TMobaXtermForm" 或視窗標題含 "MobaXterm"。
    回傳 hwnd，找不到回傳 0。
    """
    if not IS_WINDOWS:
        return 0

    found = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _get_window_title(hwnd)
        # 取 class name
        cls_buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls_buf, 256)
        cls = cls_buf.value
        if "MobaXterm" in title or "TMobaXterm" in cls:
            found.append((hwnd, title, cls))
        return True

    cb = WNDENUMPROC(callback)
    _user32.EnumWindows(cb, 0)

    if not found:
        log.info("[Phase2] 找不到 MobaXterm 視窗")
        return 0

    # 優先取最上層（EnumWindows 順序不保證，取第一個）
    hwnd, title, cls = found[0]
    log.info("[Phase2] 找到 MobaXterm hwnd=%d title=%r cls=%r", hwnd, title, cls)
    return hwnd


def _find_target_window(target: str) -> int:
    """
    在 Windows 桌面上尋找含 target 關鍵字的視窗。
    先找 MobaXterm 主視窗；若其標題已含 target 則直接回傳。
    否則循環 Ctrl+Tab（最多 10 次）直到標題含 target。

    Returns:
        hwnd (int)：找到並切換到正確分頁的視窗 handle
        0 ：找不到 MobaXterm 或找不到目標分頁
    """
    if not IS_WINDOWS:
        log.info("[Phase2] 非 Windows 環境，跳過視窗搜尋")
        return 0

    hwnd = _find_mobaxterm_hwnd()
    if not hwnd:
        return 0

    # 先把 MobaXterm 帶到前景
    _user32.ShowWindow(hwnd, 9)   # SW_RESTORE = 9
    _user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    # 檢查當前分頁標題是否已含 target
    current_title = _get_window_title(hwnd)
    if target.lower() in current_title.lower():
        log.info("[Phase2] 當前分頁標題已含 target=%r，不需切換", target)
        return hwnd

    # 循環 Ctrl+Tab 最多 10 次
    log.info("[Phase2] 當前標題 %r 不含 target=%r，開始循環切換分頁", current_title, target)
    for i in range(10):
        # 送 Ctrl+Tab
        _send_keys(
            _make_key_input(VK_CONTROL),
            _make_key_input(VK_TAB),
            _make_key_input(VK_TAB,     KEYEVENTF_KEYUP),
            _make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
        )
        time.sleep(0.3)
        new_title = _get_window_title(hwnd)
        log.info("[Phase2] Ctrl+Tab #%d => 標題=%r", i + 1, new_title)
        if target.lower() in new_title.lower():
            log.info("[Phase2] 找到目標分頁 target=%r 於第 %d 次切換", target, i + 1)
            return hwnd

    log.warning("[Phase2] 循環 10 次後仍找不到含 target=%r 的分頁", target)
    return 0


def _find_cmotty_hwnd(parent_hwnd: int) -> int:
    """在 MobaXterm 主視窗下找到可見的 CMoTTY 控件（活躍分頁的 terminal）。"""
    if not IS_WINDOWS:
        return 0

    found = []
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_size_t, ctypes.c_void_p)

    def callback(hwnd, _lparam):
        cls_buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, cls_buf, 256)
        if cls_buf.value == "CMoTTY" and _user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    _user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(callback), 0)
    if found:
        log.info("[Phase2] 找到可見 CMoTTY hwnd=0x%08X", found[0])
        return found[0]
    return 0


def _activate_and_paste(hwnd: int, text: str) -> bool:
    """
    將 hwnd 帶到前景，設定剪貼簿，嘗試多種方式貼上 + Enter。

    策略順序：
    1. 逐字元 WM_CHAR 送入 CMoTTY（最可靠，繞過剪貼簿快捷鍵問題）
    2. 若找不到 CMoTTY，退回鍵盤模擬

    Returns:
        True 成功，False 失敗
    """
    if not IS_WINDOWS:
        return False

    WM_CHAR = 0x0102

    try:
        # 確保視窗在前景
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)

        # 找 CMoTTY 控件
        cmotty = _find_cmotty_hwnd(hwnd)

        if cmotty:
            # 策略 1：逐字元 WM_CHAR 送入 CMoTTY
            log.info("[Phase2] 使用 WM_CHAR 逐字送入 CMoTTY")
            for ch in text:
                _user32.SendMessageW(cmotty, WM_CHAR, ord(ch), 0)
                time.sleep(0.005)

            # 送 Enter
            time.sleep(0.1)
            _user32.SendMessageW(cmotty, WM_CHAR, ord('\r'), 0)

            log.info("[Phase2] WM_CHAR + Enter 已送出，text[:60]=%r", text[:60])
            return True

        else:
            # 策略 2：找不到 CMoTTY，用鍵盤模擬 Shift+Ctrl+Insert
            log.warning("[Phase2] 找不到 CMoTTY，退回鍵盤模擬")
            if PYPERCLIP_AVAILABLE:
                pyperclip.copy(text)
            else:
                return False

            time.sleep(0.2)
            _send_keys(
                _make_key_input(VK_SHIFT),
                _make_key_input(VK_CONTROL),
                _make_key_input(VK_INSERT),
                _make_key_input(VK_INSERT,  KEYEVENTF_KEYUP),
                _make_key_input(VK_CONTROL, KEYEVENTF_KEYUP),
                _make_key_input(VK_SHIFT,   KEYEVENTF_KEYUP),
            )
            time.sleep(0.2)
            _send_keys(
                _make_key_input(VK_RETURN),
                _make_key_input(VK_RETURN, KEYEVENTF_KEYUP),
            )
            time.sleep(0.1)
            log.info("[Phase2] 鍵盤模擬 Shift+Ctrl+Insert + Enter 已送出")
            return True

    except Exception as e:
        log.error("[Phase2] _activate_and_paste 失敗: %s", e)
        return False


# --------------------------------------------------------------------------
# 動作處理
# --------------------------------------------------------------------------

def _handle_notify(payload: dict) -> str:
    """action=notify：只印到 console。"""
    msg = payload.get("message", "")
    src = payload.get("source", "unknown")
    log.info("[NOTIFY] source=%s | %s", src, msg)
    print(f"[{_now()}] [NOTIFY] 來源={src} | {msg}", flush=True)
    return "logged to console"


def _handle_clipboard(payload: dict) -> str:
    """action=clipboard：複製文字到剪貼簿。"""
    msg = payload.get("message", "")
    src = payload.get("source", "unknown")
    if PYPERCLIP_AVAILABLE:
        try:
            pyperclip.copy(msg)
            result = "copied to clipboard"
            print(f"[{_now()}] [CLIPBOARD] 來源={src} | 已複製到剪貼簿: {msg[:80]}", flush=True)
        except Exception as e:
            result = f"clipboard copy failed: {e}"
            log.warning("[CLIPBOARD] 複製失敗: %s", e)
    else:
        result = "pyperclip not available, skipped"
        log.warning("[CLIPBOARD] pyperclip 未安裝，跳過剪貼簿操作")
        print(f"[{_now()}] [CLIPBOARD] 來源={src} | pyperclip 不可用，訊息: {msg[:80]}", flush=True)
    return result


def _handle_paste(payload: dict) -> str:
    """
    action=paste：
      Phase 2：自動尋找 MobaXterm 目標分頁並貼上 + Enter
      Phase 1 fallback：複製到剪貼簿 + 提示手動貼上
    """
    msg    = payload.get("message", "")
    target = payload.get("target", "") or "[X390]"   # 預設目標
    src    = payload.get("source", "unknown")

    # Phase 2：嘗試自動貼上
    if IS_WINDOWS:
        hwnd = _find_target_window(target)
        if hwnd:
            # 剪貼簿先設好（_activate_and_paste 內也會設，這裡確保）
            if PYPERCLIP_AVAILABLE:
                try:
                    pyperclip.copy(msg)
                except Exception:
                    pass
            success = _activate_and_paste(hwnd, msg)
            if success:
                result = f"phase2:ok | target={target!r} | pasted+enter"
                print(
                    f"[{_now()}] [PASTE] 來源={src} | 目標={target!r} | "
                    f"Phase2: 已自動貼上並送出 Enter",
                    flush=True,
                )
                log.info("[PASTE] Phase2 成功: %s", result)
                return result
            else:
                log.warning("[PASTE] Phase2 _activate_and_paste 失敗，退回 Phase1")
        else:
            log.warning("[PASTE] Phase2 找不到目標視窗 target=%r，退回 Phase1", target)

    # Phase 1 fallback：只寫剪貼簿 + 提示
    clipboard_result = _handle_clipboard(payload)
    print(
        f"[{_now()}] [PASTE] 來源={src} | 目標視窗={target!r} | "
        f"Phase1: 已複製到剪貼簿，請手動貼上 (Ctrl+V)",
        flush=True,
    )
    log.info("[PASTE] Phase1 fallback -- target=%r, clipboard=%s", target, clipboard_result)
    return f"clipboard:{clipboard_result} | paste:phase1-fallback"


# --------------------------------------------------------------------------
# 工具函式
# --------------------------------------------------------------------------

def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _record_message(payload: dict, action_taken: str):
    """記錄摘要到 deque，供 /status 端點使用。"""
    _recent_messages.append(
        {
            "received_at": _now(),
            "action": payload.get("action", ""),
            "source": payload.get("source", ""),
            "target": payload.get("target", ""),
            "message_preview": payload.get("message", "")[:100],
            "action_taken": action_taken,
        }
    )


# --------------------------------------------------------------------------
# Flask 路由
# --------------------------------------------------------------------------

@app.route("/relay", methods=["POST"])
def relay():
    """接收來自 Ubuntu orchestrator 的 relay 訊息。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "reason": "invalid JSON body"}), 400

    action = data.get("action", "notify")
    ts = data.get("timestamp", _now())
    src = data.get("source", "unknown")

    log.info("收到 relay: action=%s, source=%s, timestamp=%s", action, src, ts)

    if action == "notify":
        action_taken = _handle_notify(data)
    elif action == "clipboard":
        action_taken = _handle_clipboard(data)
    elif action == "paste":
        action_taken = _handle_paste(data)
    else:
        log.warning("未知 action: %s", action)
        action_taken = f"unknown action: {action}"
        print(f"[{_now()}] [UNKNOWN] action={action}, source={src}", flush=True)

    _record_message(data, action_taken)

    return jsonify({"status": "received", "action_taken": action_taken})


@app.route("/status", methods=["GET"])
def status():
    """回傳 server 狀態與最近 10 筆訊息摘要。"""
    return jsonify(
        {
            "status": "running",
            "server_time": _now(),
            "pyperclip_available": PYPERCLIP_AVAILABLE,
            "is_windows": IS_WINDOWS,
            "phase": "2" if IS_WINDOWS else "1(non-windows)",
            "recent_messages": list(_recent_messages),
        }
    )


# --------------------------------------------------------------------------
# 進入點
# --------------------------------------------------------------------------

def _print_usage():
    print(
        """
relay_receiver.py -- Windows 端 Relay Receiver (Phase 2)

用法：
  python relay_receiver.py              顯示此說明
  python relay_receiver.py --serve      啟動 HTTP server（預設 port 5200）
  python relay_receiver.py --serve --port 5200  指定 port

端點：
  POST /relay    接收來自 orchestrator 的訊息
  GET  /status   查詢 server 狀態與最近訊息

支援的 action：
  notify     印到 console
  clipboard  複製到剪貼簿
  paste      Phase 2：自動找 MobaXterm 分頁並貼上 + Enter
             Phase 1 fallback：複製到剪貼簿 + 提示手動貼上

paste payload 欄位：
  target     目標分頁標題關鍵字（預設 "[X390]"）
  message    要貼上的文字

依賴套件：
  pip install flask pyperclip
  ctypes 為 Python 內建，無需安裝
"""
    )


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=5200)
    args, _ = parser.parse_known_args()

    if not args.serve:
        _print_usage()
        sys.exit(0)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print(f"[{_now()}] relay_receiver 啟動中，監聽 0.0.0.0:{args.port}", flush=True)
    print(f"[{_now()}] pyperclip 可用: {PYPERCLIP_AVAILABLE}", flush=True)
    print(f"[{_now()}] Windows 環境: {IS_WINDOWS} | Phase: {'2' if IS_WINDOWS else '1(non-windows)'}", flush=True)
    app.run(host="0.0.0.0", port=args.port, debug=False)


if __name__ == "__main__":
    main()
