#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_message_sender.py -- 回填 messages 表被錯誤覆寫的 sender。

為什麼有這支:
  舊版 install.sh 會把實例名稱寫進 config.ini [identity] project_id，而舊版
  mcp_server.py 把該鍵當成呼叫端身份的最高優先來源。結果任何 /opt/* 專案的
  Claude Code 透過 note_send 寄信，sender 全被記成 project:beakbroodnest，
  只有 sender_cwd 記到真實目錄（2026-10-14 公司端回報，6 筆未讀訊息從未被收到）。

  本工具用 sender_cwd 依現行推斷規則（ai_kb.tools.messaging.infer_identity_from_cwd）
  重算 sender，只改不一致的列；is_read 等狀態不動，收件專案升級後自然看得到。

用法:
  python3 scripts/fix_message_sender.py              顯示本說明
  python3 scripts/fix_message_sender.py --check       列出 sender 與 cwd 推斷不一致的列，不改 DB
  python3 scripts/fix_message_sender.py --apply       實際回填（冪等，可重複執行）
  --config <path>   指定 config.ini（預設專案根目錄的 config.ini）

說明:
  - 只處理 sender 以 project: 開頭且 sender_cwd 非空的列；task:/user: 等明確身份不動
  - sender 曾由 note_send 的 sender 參數明確指定、且與 cwd 推斷不同的列也會被改寫。
    若有這種需要保留的列，請先用 --check 看清單再決定是否 --apply
"""
import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--config', default=os.path.join(PROJECT_ROOT, 'config.ini'))
    parser.add_argument('-h', '--help', action='store_true')
    args = parser.parse_args()

    if args.help or not (args.check or args.apply):
        print(__doc__)
        sys.exit(0 if args.help else 1)

    from sqlalchemy import select
    from core.db import init_engine, session_scope
    from core.models import Message
    from ai_kb.tools.messaging import infer_identity_from_cwd

    init_engine(args.config)

    changes = []
    with session_scope() as s:
        rows = s.execute(
            select(Message).where(
                Message.sender.like('project:%'),
                Message.sender_cwd != '',
            ).order_by(Message.id)
        ).scalars().all()
        for m in rows:
            expected = infer_identity_from_cwd(m.sender_cwd)
            if expected != m.sender:
                changes.append((m.id, m.sender, expected, m.sender_cwd))
                if args.apply:
                    m.sender = expected

    if not changes:
        print('[OK] 沒有需要回填的訊息')
        return

    mode = '已回填' if args.apply else '待回填'
    print(f'[{mode}] {len(changes)} 筆:')
    print(f'{"id":>5}  {"原 sender":<28} {"新 sender":<28} sender_cwd')
    for mid, old, new, cwd in changes:
        print(f'{mid:>5}  {old:<28} {new:<28} {cwd}')
    if not args.apply:
        sys.exit(1)


if __name__ == '__main__':
    main()
