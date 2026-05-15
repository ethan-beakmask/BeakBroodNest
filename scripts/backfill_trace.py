#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest -- 回填 trace 欄位

對 trace_id IS NULL 的舊資料，依 heuristic 批次補填：
  trace_id / parent_span_id / actor_id / span_kind

執行前提：已完成 Phase 1 migration（conversation_turns 已有這四個欄位）。

用法:
  python3 scripts/backfill_trace.py             # 正式回填
  python3 scripts/backfill_trace.py --dry-run   # 僅輸出計畫，不寫入
"""

import argparse
import configparser
import os
import re
import sys
import uuid as uuid_mod

RE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)
RE_SUBAGENT_PATH = re.compile(
    r'/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/subagents/([^/]+)\.jsonl$',
    re.IGNORECASE,
)

CONFIG_SEARCH_PATHS = ['/opt/BeakBroodNest/config.ini']
BATCH_SIZE = 1000


# ============================================================
# DB 連線
# ============================================================

def _load_db_params():
    """從 config.ini 讀取 DB 連線參數。密碼必須由 config.ini 提供，否則直接終止。"""
    for path in CONFIG_SEARCH_PATHS:
        if os.path.isfile(path):
            cfg = configparser.ConfigParser()
            cfg.read(path, encoding='utf-8')
            if cfg.has_section('postgresql'):
                password = cfg.get('postgresql', 'password', fallback='')
                if not password:
                    print(f'[ERROR] {path} 的 [postgresql] 區段缺少 password', file=sys.stderr)
                    sys.exit(1)
                return {
                    'host': cfg.get('postgresql', 'host', fallback='localhost'),
                    'port': cfg.getint('postgresql', 'port', fallback=5432),
                    'database': cfg.get('postgresql', 'database', fallback='beak_broodnest'),
                    'user': cfg.get('postgresql', 'username', fallback='beak_broodnest'),
                    'password': password,
                }
    print(f'[ERROR] 找不到 config.ini（搜尋路徑：{CONFIG_SEARCH_PATHS}），請先執行 install.sh', file=sys.stderr)
    sys.exit(1)


def _get_conn():
    try:
        import psycopg2
    except ImportError:
        print('[ERROR] psycopg2 未安裝')
        sys.exit(1)
    p = _load_db_params()
    try:
        return psycopg2.connect(
            host=p['host'], port=p['port'],
            dbname=p['database'], user=p['user'], password=p['password'],
        )
    except Exception as e:
        print(f'[ERROR] 無法連線 PostgreSQL: {e}')
        sys.exit(1)


# ============================================================
# 推斷邏輯
# ============================================================

def _infer_actor_id(jsonl_path: str) -> str:
    """從 jsonl_path 推斷 actor_id"""
    if not jsonl_path:
        return 'cc-main'
    m = RE_SUBAGENT_PATH.search(jsonl_path)
    if m:
        agent_filename = m.group(2)  # e.g. "agent-abc123"
        if agent_filename.startswith('agent-'):
            agent_part = 'agent:' + agent_filename[len('agent-'):]
        else:
            agent_part = 'agent:' + agent_filename
        return 'cc-main:' + agent_part
    return 'cc-main'


def _infer_span_kind(role: str) -> str | None:
    """從 role 推斷 span_kind"""
    mapping = {
        'user': 'user_message',
        'assistant': 'assistant_message',
        'tool_use': 'tool_call',
        'tool_result': 'tool_result',
    }
    return mapping.get(role)


# ============================================================
# 核心回填
# ============================================================

def backfill(dry_run: bool = False):
    conn = _get_conn()
    cur = conn.cursor()

    # 確認欄位存在
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'conversation_turns'
          AND column_name IN ('trace_id', 'actor_id', 'span_kind', 'parent_span_id')
    """)
    cols = {r[0] for r in cur.fetchall()}
    required = {'trace_id', 'actor_id', 'span_kind', 'parent_span_id'}
    missing = required - cols
    if missing:
        print(f'[ERROR] 欄位不存在，請先執行 migration: {missing}')
        cur.close(); conn.close(); sys.exit(1)

    # 統計待回填
    cur.execute("SELECT COUNT(*) FROM conversation_turns WHERE trace_id IS NULL")
    total = cur.fetchone()[0]
    print(f'[INFO] 待回填筆數: {total}')
    if total == 0:
        print('[INFO] 無需回填，結束')
        cur.close(); conn.close(); return

    # 取得所有待回填的 conversation_id（含 jsonl_path 與 parent）
    cur.execute("""
        SELECT c.id, c.jsonl_path, c.parent_conversation_id
        FROM conversations c
        WHERE EXISTS (
            SELECT 1 FROM conversation_turns ct
            WHERE ct.conversation_id = c.id AND ct.trace_id IS NULL
        )
        ORDER BY c.first_timestamp ASC NULLS LAST
    """)
    conversations = cur.fetchall()
    print(f'[INFO] 涉及對話數: {len(conversations)}')

    # 先計算主對話的 trace_id（用於 subagent 繼承）
    # main_trace: conv_id -> trace_id (str)
    main_trace: dict[str, str] = {}

    processed = 0

    for (conv_id, jsonl_path, parent_conv_id) in conversations:
        actor_id = _infer_actor_id(jsonl_path or '')

        # 決定 trace_id：
        # 1. sub-agent：繼承 parent 的 trace_id（若已算好）
        # 2. 主對話：指定一個新 UUID
        trace_id = None
        if parent_conv_id and parent_conv_id in main_trace:
            trace_id = main_trace[parent_conv_id]
        else:
            # 看 DB 中此 conv 是否已有部分 turn 有 trace_id
            cur.execute("""
                SELECT DISTINCT trace_id FROM conversation_turns
                WHERE conversation_id = %s AND trace_id IS NOT NULL
                LIMIT 1
            """, (conv_id,))
            r = cur.fetchone()
            if r:
                trace_id = str(r[0])

        if trace_id is None:
            trace_id = str(uuid_mod.uuid4())

        main_trace[str(conv_id)] = trace_id

        # 取此 conversation 所有待回填的 turn
        cur.execute("""
            SELECT id, role, parent_uuid
            FROM conversation_turns
            WHERE conversation_id = %s AND trace_id IS NULL
            ORDER BY turn_seq ASC
        """, (conv_id,))
        turns = cur.fetchall()

        for (turn_id, role, parent_uuid) in turns:
            span_kind = _infer_span_kind(role or '')
            turn_actor_id = 'human' if role == 'user' else actor_id

            # parent_span_id = parent_uuid（若合法 UUID）
            parent_span_id = None
            if parent_uuid and RE_UUID.match(str(parent_uuid)):
                parent_span_id = str(parent_uuid)

            if dry_run:
                print(f'  [DRY] turn={turn_id} actor={turn_actor_id} '
                      f'span_kind={span_kind} trace={trace_id[:8]}… parent_span={parent_span_id}')
            else:
                cur.execute("""
                    UPDATE conversation_turns
                    SET trace_id       = %s::uuid,
                        actor_id       = %s,
                        span_kind      = %s,
                        parent_span_id = %s::uuid
                    WHERE id = %s AND trace_id IS NULL
                """, (
                    trace_id, turn_actor_id, span_kind,
                    parent_span_id,
                    turn_id,
                ))

            processed += 1
            if processed % BATCH_SIZE == 0:
                if not dry_run:
                    conn.commit()
                pct = processed * 100 // total
                print(f'[進度] {processed}/{total} ({pct}%)')

    if not dry_run:
        conn.commit()

    print(f'[DONE] 處理完成: {processed} 筆{"（dry-run，未寫入）" if dry_run else ""}')
    cur.close()
    conn.close()


# ============================================================
# 使用說明 & 主程式
# ============================================================

USAGE_TEXT = """BeakBroodNest -- 回填 trace 欄位

用法:
  {prog}             正式回填（寫入 DB）
  {prog} --dry-run   僅輸出計畫，不寫入

執行前提：已完成 Phase 1 migration（含 trace_id/parent_span_id/actor_id/span_kind 欄位）。
"""


def main():
    prog = os.path.basename(sys.argv[0])
    if len(sys.argv) == 1:
        print(USAGE_TEXT.format(prog=prog))
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description='回填 conversation_turns trace 欄位',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--dry-run', action='store_true', help='僅輸出，不寫入 DB')
    args = parser.parse_args()

    backfill(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
