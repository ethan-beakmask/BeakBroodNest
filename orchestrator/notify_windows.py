#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify_windows.py - 向 Windows 端 relay receiver 發送通知訊息
用途：orchestrator 支線完成時通知主線（或其他用途）
"""

import os
import re
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


def derive_project_name():
    """從 $PWD 推導專案名稱：取最後一層目錄名，去掉 -dev 尾碼。
    例如 /opt/BeakMeshWall-dev -> BeakMeshWall
         /opt/BeakSeal -> BeakSeal
    """
    cwd = os.getcwd()
    dirname = os.path.basename(cwd)
    return re.sub(r'-dev$', '', dirname)


def derive_target():
    """從專案名稱推導 MobaXterm 分頁比對字串。
    格式：([專案名稱])，對應 MobaXterm 標題中的 192.168.0.16 ([專案名稱])
    """
    name = derive_project_name()
    return f"([{name}])"


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
  python notify_windows.py -m "訊息" --target "([BeakSeal])"
  python notify_windows.py --launch
  python notify_windows.py --launch --bookmark "User sessions\\192.168.0.16 ([BeakSeal])"

target/bookmark 自動推導（從 $PWD）：
  /opt/BeakMeshWall-dev -> target=([BeakMeshWall]) bookmark=User sessions\\192.168.0.16 ([BeakMeshWall])
  /opt/BeakSeal         -> target=([BeakSeal])     bookmark=User sessions\\192.168.0.16 ([BeakSeal])

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
    parser.add_argument("--target", default="", metavar="視窗識別字串",
                        help="目標分頁識別字串（預設從 $PWD 推導專案名稱）")
    parser.add_argument("--launch", action="store_true",
                        help="啟動 MobaXterm（可搭配 --bookmark）")
    parser.add_argument("--bookmark", default="", metavar="BOOKMARK",
                        help="指定 MobaXterm bookmark（預設從 $PWD 推導）")

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    # 自動推導 target 和 bookmark
    target = args.target if args.target else derive_target()

    if args.launch:
        bookmark = args.bookmark
        if not bookmark:
            name = derive_project_name()
            bookmark = f"User sessions\\192.168.0.16 ([{name}])"
        exit_code = launch_mobaxterm(
            host=args.host,
            port=args.port,
            bookmark=bookmark
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
        target=target
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
