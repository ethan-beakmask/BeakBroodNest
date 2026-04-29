#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex 復盤系統 - DB 匯入模組

將 Claude Code JSONL 對話記錄匯入 PostgreSQL，供後續訊號掃描及語意摘要處理。
從 parse_conversation.py 拆分而來，可獨立執行或由 parse_conversation.py 呼叫。

外部依賴：psycopg2（僅匯入時需要）。
"""

import json
import argparse
import configparser
import os
import re
import sys
import glob
import uuid as uuid_mod
from datetime import datetime
from typing import Dict, List, Optional

# 從 parse_conversation 匯入共用函式與常數
from parse_conversation import (
    extract_cwd_from_jsonl,
    get_claude_projects_path,
    list_jsonl_files,
    resolve_input_file,
    SILENT_SKIP_TYPES,
)


# ============================================================
# 常數
# ============================================================

# config.ini 搜尋路徑（優先順序）
CONFIG_SEARCH_PATHS = [
    '/opt/BeakCortex/config.ini',
]

# 預設 DB 連線參數（找不到 config.ini 時使用）
DEFAULT_DB_PARAMS = {
    'host': 'localhost',
    'port': 5432,
    'database': 'beak_cortex',
    'user': 'beak_cortex',
    'password': 'postgres123',
}

# UUID 格式正則
RE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# 從 Bash command 中提取檔案路徑的正則（簡單匹配）
RE_FILE_PATH = re.compile(r'(?:^|\s)(/(?:opt|home|tmp|var|etc|usr|mnt)/[\w./_-]+)')


# ============================================================
# DB 連線
# ============================================================

def _load_db_params() -> dict:
    """從 config.ini 讀取 DB 連線參數，找不到時用預設值"""
    for path in CONFIG_SEARCH_PATHS:
        if os.path.isfile(path):
            cfg = configparser.ConfigParser()
            cfg.read(path, encoding='utf-8')
            if cfg.has_section('postgresql'):
                return {
                    'host': cfg.get('postgresql', 'host', fallback='localhost'),
                    'port': cfg.getint('postgresql', 'port', fallback=5432),
                    'database': cfg.get('postgresql', 'database', fallback='beak_cortex'),
                    'user': cfg.get('postgresql', 'username', fallback='beak_cortex'),
                    'password': cfg.get('postgresql', 'password', fallback='postgres123'),
                }
    return DEFAULT_DB_PARAMS.copy()


def _get_db_connection():
    """建立 psycopg2 連線"""
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 未安裝。請執行: pip install psycopg2-binary")
        print("        或使用 BeakCortex venv: /opt/BeakCortex/venv/bin/pip install psycopg2-binary")
        sys.exit(1)

    params = _load_db_params()
    try:
        conn = psycopg2.connect(
            host=params['host'],
            port=params['port'],
            dbname=params['database'],
            user=params['user'],
            password=params['password'],
        )
        return conn
    except psycopg2.OperationalError as e:
        print(f"[ERROR] 無法連線 PostgreSQL: {e}")
        sys.exit(1)


# ============================================================
# 工具函式
# ============================================================

def _conversation_id_from_filename(jsonl_path: str) -> str:
    """從 JSONL 檔名取得 conversation_id (UUID)

    - UUID 格式檔名：直接使用
    - 非 UUID 格式（如 agent-xxx）：用 SHA-1 hash 產生 deterministic UUID v5
    """
    basename = os.path.splitext(os.path.basename(jsonl_path))[0]
    if RE_UUID.match(basename):
        return basename

    # 非 UUID：用完整路徑的 hash 產生 deterministic UUID
    # 使用 uuid5 with DNS namespace + 完整路徑確保唯一且可重複
    return str(uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, jsonl_path))


def _extract_files_touched_from_tool(tool_name: str, tool_input: dict) -> List[str]:
    """從 tool_use 的參數中提取 files_touched"""
    files = []
    if not tool_input:
        return files

    if tool_name in ('Read', 'Edit', 'Write'):
        fp = tool_input.get('file_path', '')
        if fp:
            files.append(fp)
    elif tool_name in ('Glob', 'Grep'):
        p = tool_input.get('path', '')
        if p:
            files.append(p)
    elif tool_name == 'Bash':
        cmd = tool_input.get('command', '')
        if cmd:
            matches = RE_FILE_PATH.findall(cmd)
            files.extend(matches)

    return files


def _parse_timestamp(ts_str: Optional[str]) -> Optional[datetime]:
    """將 ISO 時間戳記解析為 datetime (timezone-aware)"""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


# ============================================================
# 核心匯入邏輯
# ============================================================

def _import_single_jsonl(conn, jsonl_path: str) -> dict:
    """匯入單一 JSONL 檔案到 DB

    Returns:
        統計 dict: {turns, roles, files_touched_counter, skipped_reason}
        若 skipped_reason 有值，表示整個檔案被跳過
    """
    import psycopg2.extras

    conv_id = _conversation_id_from_filename(jsonl_path)
    stats = {
        'turns': 0,
        'roles': {},
        'files_touched': {},
        'skipped_reason': None,
    }

    # 檢查是否已匯入
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM conversations WHERE id = %s", (conv_id,))
        if cur.fetchone():
            stats['skipped_reason'] = '已匯入'
            return stats

    # 讀取並解析 JSONL
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    records = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not records:
        stats['skipped_reason'] = '空檔案'
        return stats

    # --- 提取 metadata ---
    project_path = None
    session_id = None
    is_sidechain = False
    parent_uuid = None
    git_branch = None
    first_ts = None
    last_ts = None

    for rec in records:
        rec_type = rec.get('type', '')

        # 從 system 行提取（優先）
        if rec_type == 'system':
            if not project_path:
                project_path = rec.get('cwd')
            if not session_id:
                session_id = rec.get('sessionId')
            is_sidechain = rec.get('isSidechain', False)
            parent_uuid = rec.get('parentUuid') or None
            if not git_branch:
                git_branch = rec.get('gitBranch')
            ts = _parse_timestamp(rec.get('timestamp'))
            if ts:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            continue

        # 從 user/assistant 行補充
        if rec_type in ('user', 'assistant'):
            if not project_path:
                project_path = rec.get('cwd')
            if not session_id:
                session_id = rec.get('sessionId')
            if not git_branch:
                git_branch = rec.get('gitBranch')
            if rec.get('isSidechain'):
                is_sidechain = True
            if not parent_uuid:
                pu = rec.get('parentUuid')
                if pu:
                    parent_uuid = pu
            ts = _parse_timestamp(rec.get('timestamp'))
            if ts:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts

    if not project_path:
        project_path = extract_cwd_from_jsonl(jsonl_path) or 'Unknown'

    # --- 拆 turns ---
    turns = []
    turn_seq = 0

    for rec in records:
        rec_type = rec.get('type', '')

        # 跳過非對話行
        if rec_type in SILENT_SKIP_TYPES:
            continue

        rec_timestamp = _parse_timestamp(rec.get('timestamp'))
        rec_is_sidechain = rec.get('isSidechain', False)
        rec_parent_uuid = rec.get('parentUuid') or None

        # --- attachment ---
        if rec_type == 'attachment':
            turn_seq += 1
            att = rec.get('attachment', {})
            att_type = att.get('type', 'unknown')
            att_names = att.get('addedNames', [])
            content_text = f"[Attachment: {att_type}]"
            if att_names:
                content_text += ' ' + ', '.join(att_names[:20])

            turns.append({
                'turn_seq': turn_seq,
                'role': 'attachment',
                'timestamp': rec_timestamp,
                'content': content_text,
                'tool_name': None,
                'tool_use_id': None,
                'tool_params': None,
                'tool_is_error': None,
                'files_touched': att_names[:50] if att_names else None,
                'has_thinking': False,
                'thinking_text': None,
                'is_sidechain': rec_is_sidechain,
                'parent_uuid': rec_parent_uuid,
                'model': None,
                'usage_input': None,
                'usage_output': None,
            })
            continue

        # --- summary ---
        if rec_type == 'summary':
            turn_seq += 1
            summary_text = rec.get('summary', '')
            if not summary_text:
                msg = rec.get('message', {})
                if isinstance(msg, dict):
                    c = msg.get('content', '')
                    if isinstance(c, list):
                        parts = []
                        for item in c:
                            if isinstance(item, dict):
                                parts.append(item.get('text', ''))
                            else:
                                parts.append(str(item))
                        summary_text = '\n'.join(parts)
                    elif isinstance(c, str):
                        summary_text = c

            turns.append({
                'turn_seq': turn_seq,
                'role': 'system',
                'timestamp': rec_timestamp,
                'content': f"[Summary] {summary_text}",
                'tool_name': None,
                'tool_use_id': None,
                'tool_params': None,
                'tool_is_error': None,
                'files_touched': None,
                'has_thinking': False,
                'thinking_text': None,
                'is_sidechain': rec_is_sidechain,
                'parent_uuid': rec_parent_uuid,
                'model': None,
                'usage_input': None,
                'usage_output': None,
            })
            continue

        # --- user / assistant ---
        if rec_type not in ('user', 'assistant'):
            continue

        msg = rec.get('message', {})
        if not isinstance(msg, dict):
            continue

        content = msg.get('content', '')
        model = msg.get('model') if rec_type == 'assistant' else None
        usage = msg.get('usage', {}) if rec_type == 'assistant' else {}
        usage_input = usage.get('input_tokens') if usage else None
        usage_output = usage.get('output_tokens') if usage else None

        # content 是字串（通常是 user 的純文字）
        if isinstance(content, str):
            turn_seq += 1
            role = 'user' if rec_type == 'user' else 'assistant'
            turns.append({
                'turn_seq': turn_seq,
                'role': role,
                'timestamp': rec_timestamp,
                'content': content,
                'tool_name': None,
                'tool_use_id': None,
                'tool_params': None,
                'tool_is_error': None,
                'files_touched': None,
                'has_thinking': False,
                'thinking_text': None,
                'is_sidechain': rec_is_sidechain,
                'parent_uuid': rec_parent_uuid,
                'model': model,
                'usage_input': usage_input,
                'usage_output': usage_output,
            })
            continue

        # content 是 list：拆成多個 turn
        if not isinstance(content, list):
            continue

        for item in content:
            if not isinstance(item, dict):
                continue

            item_type = item.get('type', '')

            if item_type == 'text':
                text = item.get('text', '')
                if not text:
                    continue
                turn_seq += 1
                role = 'user' if rec_type == 'user' else 'assistant'
                turns.append({
                    'turn_seq': turn_seq,
                    'role': role,
                    'timestamp': rec_timestamp,
                    'content': text,
                    'tool_name': None,
                    'tool_use_id': None,
                    'tool_params': None,
                    'tool_is_error': None,
                    'files_touched': None,
                    'has_thinking': False,
                    'thinking_text': None,
                    'is_sidechain': rec_is_sidechain,
                    'parent_uuid': rec_parent_uuid,
                    'model': model,
                    'usage_input': usage_input,
                    'usage_output': usage_output,
                })

            elif item_type == 'thinking':
                thinking_text = item.get('thinking', '')
                if not thinking_text:
                    continue
                turn_seq += 1
                turns.append({
                    'turn_seq': turn_seq,
                    'role': 'assistant',
                    'timestamp': rec_timestamp,
                    'content': None,
                    'tool_name': None,
                    'tool_use_id': None,
                    'tool_params': None,
                    'tool_is_error': None,
                    'files_touched': None,
                    'has_thinking': True,
                    'thinking_text': thinking_text,
                    'is_sidechain': rec_is_sidechain,
                    'parent_uuid': rec_parent_uuid,
                    'model': model,
                    'usage_input': usage_input,
                    'usage_output': usage_output,
                })

            elif item_type == 'tool_use':
                tool_name = item.get('name', '')
                tool_input = item.get('input', {})
                files = _extract_files_touched_from_tool(tool_name, tool_input)
                turn_seq += 1
                turns.append({
                    'turn_seq': turn_seq,
                    'role': 'tool_use',
                    'timestamp': rec_timestamp,
                    'content': None,
                    'tool_name': tool_name,
                    'tool_use_id': item.get('id'),
                    'tool_params': tool_input if tool_input else None,
                    'tool_is_error': None,
                    'files_touched': files if files else None,
                    'has_thinking': False,
                    'thinking_text': None,
                    'is_sidechain': rec_is_sidechain,
                    'parent_uuid': rec_parent_uuid,
                    'model': model,
                    'usage_input': usage_input,
                    'usage_output': usage_output,
                })
                # 統計 files_touched
                for fp in files:
                    stats['files_touched'][fp] = stats['files_touched'].get(fp, 0) + 1

            elif item_type == 'tool_result':
                tool_content = item.get('content', '')
                if isinstance(tool_content, list):
                    parts = []
                    for sub in tool_content:
                        if isinstance(sub, dict):
                            parts.append(sub.get('text', json.dumps(sub, ensure_ascii=False)))
                        else:
                            parts.append(str(sub))
                    tool_content = '\n'.join(parts)
                elif not isinstance(tool_content, str):
                    tool_content = json.dumps(tool_content, ensure_ascii=False) if tool_content else ''

                turn_seq += 1
                turns.append({
                    'turn_seq': turn_seq,
                    'role': 'tool_result',
                    'timestamp': rec_timestamp,
                    'content': tool_content,
                    'tool_name': None,
                    'tool_use_id': item.get('tool_use_id'),
                    'tool_params': None,
                    'tool_is_error': item.get('is_error', False),
                    'files_touched': None,
                    'has_thinking': False,
                    'thinking_text': None,
                    'is_sidechain': rec_is_sidechain,
                    'parent_uuid': rec_parent_uuid,
                    'model': None,
                    'usage_input': None,
                    'usage_output': None,
                })

    if not turns:
        stats['skipped_reason'] = '無可匯入的 turn'
        return stats

    # --- 寫入 DB ---
    jsonl_size = os.path.getsize(jsonl_path)

    # 驗證 parent_uuid 是否為合法 UUID
    parent_uuid_val = None
    if parent_uuid and RE_UUID.match(parent_uuid):
        parent_uuid_val = parent_uuid

    with conn.cursor() as cur:
        # 寫入 conversations
        cur.execute("""
            INSERT INTO conversations
                (id, project_path, session_id, jsonl_path, jsonl_size,
                 total_turns, first_timestamp, last_timestamp,
                 is_sidechain, parent_uuid, git_branch)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            conv_id, project_path, session_id, jsonl_path, jsonl_size,
            len(turns), first_ts, last_ts,
            is_sidechain, parent_uuid_val, git_branch,
        ))

        # 批次寫入 conversation_turns
        inserted = 0
        for i, t in enumerate(turns):
            # parent_uuid 驗證
            t_parent = None
            if t['parent_uuid'] and RE_UUID.match(str(t['parent_uuid'])):
                t_parent = t['parent_uuid']

            # tool_params -> JSON
            tool_params_json = None
            if t['tool_params']:
                tool_params_json = json.dumps(t['tool_params'], ensure_ascii=False)

            try:
                cur.execute("""
                    INSERT INTO conversation_turns
                        (conversation_id, project_path, turn_seq, role, timestamp,
                         content, tool_name, tool_use_id, tool_params, tool_is_error,
                         files_touched, has_thinking, thinking_text,
                         is_sidechain, parent_uuid, model,
                         usage_input_tokens, usage_output_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (conversation_id, turn_seq) DO NOTHING
                """, (
                    conv_id, project_path, t['turn_seq'], t['role'], t['timestamp'],
                    t['content'], t['tool_name'], t['tool_use_id'],
                    tool_params_json, t['tool_is_error'],
                    t['files_touched'], t['has_thinking'], t['thinking_text'],
                    t['is_sidechain'], t_parent, t['model'],
                    t['usage_input'], t['usage_output'],
                ))
                inserted += 1
            except Exception as e:
                # 單筆失敗不中斷，記錄後繼續
                print(f"  [WARN] turn_seq={t['turn_seq']} 寫入失敗: {e}")
                conn.rollback()
                # 重新開始 transaction
                continue

            # 進度顯示
            if inserted > 0 and inserted % 100 == 0:
                print(f"  [進度] 已寫入 {inserted} turns...")

        conn.commit()

    stats['turns'] = inserted
    for t in turns:
        role = t['role']
        stats['roles'][role] = stats['roles'].get(role, 0) + 1

    return stats


# ============================================================
# 公開介面
# ============================================================

def import_single_db(jsonl_path: str) -> bool:
    """匯入單一 JSONL 到 DB，回傳是否成功"""
    conn = _get_db_connection()
    try:
        print(f"[INFO] 匯入: {jsonl_path}")
        print(f"[INFO] conversation_id: {_conversation_id_from_filename(jsonl_path)}")

        stats = _import_single_jsonl(conn, jsonl_path)

        if stats['skipped_reason']:
            print(f"[SKIP] {stats['skipped_reason']}")
            return True

        print(f"[OK] 匯入完成: {stats['turns']} turns")
        print(f"     角色分布: {stats['roles']}")

        # files_touched 前 5 名
        if stats['files_touched']:
            sorted_files = sorted(stats['files_touched'].items(),
                                  key=lambda x: x[1], reverse=True)
            print(f"     files_touched 前 5:")
            for fp, count in sorted_files[:5]:
                print(f"       {count:>3}x {fp}")

        return True
    except Exception as e:
        print(f"[ERROR] 匯入失敗: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        conn.close()


def import_batch_db(since_days: int = 0, limit: int = 0) -> None:
    """批次匯入 JSONL 到 DB

    since_days: 只處理 mtime 在近 N 天內的檔案（0=不限）
    limit:      最多處理 N 個檔案（0=不限），按 mtime 由舊到新
    """
    projects_dir, display_path = get_claude_projects_path()

    if not projects_dir:
        print(f"[ERROR] 找不到 Claude 對話記錄目錄: {display_path}")
        return

    pattern = os.path.join(projects_dir, "**", "*.jsonl")
    files = glob.glob(pattern, recursive=True)

    if not files:
        print(f"[INFO] {projects_dir} 中沒有找到 .jsonl 檔案")
        return

    # mtime 過濾（since_days）
    if since_days > 0:
        import time
        cutoff = time.time() - since_days * 86400
        before_n = len(files)
        files = [f for f in files if os.path.getmtime(f) >= cutoff]
        print(f"[INFO] --since {since_days} 天過濾：{before_n} -> {len(files)} 個檔案")

    # 按修改時間排序（舊到新）
    files.sort(key=lambda x: os.path.getmtime(x))

    # limit 截斷
    if limit > 0 and len(files) > limit:
        print(f"[INFO] --limit {limit} 截斷：{len(files)} -> {limit} 個檔案")
        files = files[:limit]

    conn = _get_db_connection()
    print(f"[INFO] 開始批次匯入 {len(files)} 個 JSONL 檔案")
    print(f"[INFO] DB: {_load_db_params()['database']}@{_load_db_params()['host']}")
    print("-" * 60)

    success = 0
    skipped = 0
    failed_list = []
    total_turns = 0
    all_roles = {}
    all_files_touched = {}

    for i, fpath in enumerate(files, 1):
        basename = os.path.basename(fpath)
        try:
            stats = _import_single_jsonl(conn, fpath)

            if stats['skipped_reason']:
                skipped += 1
                if (i % 200 == 0) or (i == len(files)):
                    print(f"[{i}/{len(files)}] 進度: 成功={success}, 跳過={skipped}, 失敗={len(failed_list)}")
                continue

            success += 1
            total_turns += stats['turns']
            for role, count in stats['roles'].items():
                all_roles[role] = all_roles.get(role, 0) + count
            for fp, count in stats['files_touched'].items():
                all_files_touched[fp] = all_files_touched.get(fp, 0) + count

            if success % 50 == 0:
                print(f"[{i}/{len(files)}] 成功匯入 {success} 個, turns={total_turns}")

        except Exception as e:
            failed_list.append((fpath, str(e)))
            try:
                conn.rollback()
            except Exception:
                pass
            if len(failed_list) <= 5:
                print(f"  [FAIL] {basename}: {e}")

    conn.close()

    print("\n" + "=" * 60)
    print(f"[DONE] 成功: {success}, 跳過(已匯入): {skipped}, 失敗: {len(failed_list)}")
    print(f"       總 turns: {total_turns}")
    if all_roles:
        print(f"       角色分布: {all_roles}")
    if all_files_touched:
        sorted_files = sorted(all_files_touched.items(),
                              key=lambda x: x[1], reverse=True)
        print(f"       files_touched 前 5:")
        for fp, count in sorted_files[:5]:
            print(f"         {count:>5}x {fp}")

    if failed_list:
        print(f"\n[WARN] 失敗清單 ({len(failed_list)} 個):")
        for fpath, err in failed_list[:20]:
            print(f"  {os.path.basename(fpath)}: {err}")
        if len(failed_list) > 20:
            print(f"  ... 還有 {len(failed_list) - 20} 個")


# ============================================================
# 使用說明
# ============================================================

USAGE_TEXT = """BeakCortex 復盤系統 - DB 匯入模組

將 Claude Code JSONL 對話記錄匯入 PostgreSQL。

用法:
  {prog}                                  列出所有可用的 JSONL 檔案
  {prog} -i <編號|路徑>                   匯入單一檔案到 PostgreSQL
  {prog} -convertall                      批次匯入所有檔案到 PostgreSQL

參數:
  -i, --input FILE          輸入的 JSONL 檔案路徑或清單編號
  -convertall               批次匯入所有 JSONL

DB 匯入說明:
  DB 連線從 config.ini 讀取（postgresql 區段），找不到用預設值
  已匯入的檔案會自動跳過（增量處理）
  conversation_id 從檔名的 UUID 取得，非 UUID 檔名用 hash 產生

範例:
  {prog}
  {prog} -i 1
  {prog} -i /path/to/file.jsonl
  {prog} -convertall
"""


# ============================================================
# 主程式（獨立執行入口）
# ============================================================

def main():
    prog = os.path.basename(sys.argv[0])

    # 無參數時顯示使用說明 + 檔案清單
    if len(sys.argv) == 1:
        print(USAGE_TEXT.format(prog=prog))
        file_list = list_jsonl_files()
        if file_list:
            print(f"\n使用方式: {prog} -i [編號]")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description='BeakCortex 復盤系統 - JSONL 對話匯入 PostgreSQL',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('-i', '--input',
                        help='輸入的 JSONL 檔案路徑或編號')
    parser.add_argument('-convertall', action='store_true',
                        help='批次匯入所有檔案')
    parser.add_argument('--since', type=int, default=0, metavar='DAYS',
                        help='僅匯入最近 N 天內修改的 jsonl（0=不限）')
    parser.add_argument('--limit', type=int, default=0, metavar='N',
                        help='最多匯入 N 個檔案（0=不限，按 mtime 由舊到新）')

    args = parser.parse_args()

    # 批次匯入
    if args.convertall:
        import_batch_db(since_days=args.since, limit=args.limit)
        sys.exit(0)

    # 單檔匯入
    if not args.input:
        print("[ERROR] 必須指定 -i 參數")
        parser.print_help()
        sys.exit(1)

    # 解析輸入檔案
    if args.input.isdigit():
        file_list = list_jsonl_files()
        input_file = resolve_input_file(args.input, file_list)
    elif os.path.exists(args.input):
        input_file = args.input
    else:
        print(f"[ERROR] 找不到檔案: {args.input}")
        sys.exit(1)

    import_single_db(input_file)


if __name__ == "__main__":
    main()
