#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_windows.py - 向 Windows 端 relay receiver 發送通知訊息
用途：orchestrator 支線完成時通知主線（或其他用途）
"""

import sys
import argparse
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("錯誤：缺少 requests 套件，請執行 pip install requests", file=sys.stderr)
    sys.exit(1)


def send_message(message, host, port, action, target):
    url = f"http://{host}:{port}/relay"
    payload = {
        "action": action,
        "message": message,
        "target": target,
        "source": "orchestrator",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    try:
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            print(f"發送成功：{url}  HTTP {resp.status_code}")
            return 0
        else:
            print(f"發送失敗：HTTP {resp.status_code}  回應：{resp.text}", file=sys.stderr)
            return 1
    except requests.exceptions.ConnectionError as e:
        print(f"連線錯誤：無法連線到 {url}  ({e})", file=sys.stderr)
        return 1
    except requests.exceptions.Timeout:
        print(f"連線逾時：等待 {url} 超過 5 秒", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"未預期錯誤：{e}", file=sys.stderr)
        return 1


def launch_mobaxterm(host, port, bookmark):
    """呼叫 Windows 端 /launch 端點啟動 MobaXterm"""
    url = f"http://{host}:{port}/launch"
    payload = {}
    if bookmark:
        payload["bookmark"] = bookmark
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            print(f"MobaXterm 啟動成功：{url}")
            return 0
        else:
            print(f"啟動失敗：HTTP {resp.status_code}  回應：{resp.text}", file=sys.stderr)
            return 1
    except requests.exceptions.ConnectionError as e:
        print(f"連線錯誤：無法連線到 {url}  ({e})", file=sys.stderr)
        return 1
    except requests.exceptions.Timeout:
        print(f"連線逾時：等待 {url} 超過 10 秒", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"未預期錯誤：{e}", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog="notify_windows.py",
        description="向 Windows 端 relay receiver 發送文字訊息",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例：
  python notify_windows.py -m "支線任務已完成"
  python notify_windows.py -m "訊息" --host 192.168.0.10 --port 5200
  python notify_windows.py -m "訊息" --action notify --target "MobaXterm-1"
  python notify_windows.py --launch
  python notify_windows.py --launch --bookmark "User sessions\\host ([X390])"

動作類型說明：
  paste      貼上訊息到目標視窗（預設）
  notify     彈出通知提示
  clipboard  僅寫入剪貼簿
  --launch   啟動 Windows 端 MobaXterm（可搭配 --bookmark）
"""
    )
    parser.add_argument("-m", "--message", metavar="訊息內容",
                        help="要發送的文字訊息（必填）")
    parser.add_argument("--host", default="192.168.0.10", metavar="IP",
                        help="Windows 端 IP（預設 192.168.0.10）")
    parser.add_argument("--port", type=int, default=5200, metavar="PORT",
                        help="接收端 port（預設 5200）")
    parser.add_argument("--action", default="paste",
                        choices=["notify", "paste", "clipboard"],
                        help="動作類型（預設 paste）")
    parser.add_argument("--target", default="[X390]", metavar="視窗識別字串",
                        help="目標視窗識別字串（預設 [X390]）")
    parser.add_argument("--launch", action="store_true",
                        help="啟動 MobaXterm（使用設定檔預設 bookmark）")
    parser.add_argument("--bookmark", default="", metavar="BOOKMARK",
                        help="指定 MobaXterm bookmark（搭配 --launch 使用）")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    if args.launch:
        exit_code = launch_mobaxterm(
            host=args.host,
            port=args.port,
            bookmark=args.bookmark
        )
        sys.exit(exit_code)

    if not args.message:
        print("錯誤：必須提供 -m 訊息內容", file=sys.stderr)
        parser.print_usage(sys.stderr)
        sys.exit(1)

    exit_code = send_message(
        message=args.message,
        host=args.host,
        port=args.port,
        action=args.action,
        target=args.target
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
