#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest 復盤系統 - 訊號掃描器 DB 模式

從 PostgreSQL conversation_turns 表讀取對話資料，
掃描訊號後更新 p1_scanned_at 和 p1_signals 欄位。

由 signal_scanner.py 呼叫，不可獨立執行。
"""

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# 從 signal_scanner 匯入共用元件
from signal_scanner import (
    SEVERITY_WEIGHT,
    REPEATED_EDIT_THRESHOLD,
    LONG_STRUGGLE_THRESHOLD,
    RE_ERROR,
    RE_ERROR_EXCLUDE,
    RE_TOOL_FAILURE,
    RE_ROLLBACK_ZH,
    RE_ROLLBACK_EN,
    RE_RETRY_ZH,
    RE_RETRY_EN,
    _match_any,
    _is_excluded_error,
    _truncate,
    detect_git_signals,
    write_output,
)

# 從 db_importer 復用 DB 連線
from db_importer import _load_db_params, _get_db_connection


# ============================================================
# DB 查詢
# ============================================================

def _get_unscanned_conversations(conn) -> List[Dict[str, Any]]:
    """取得所有含未掃描 turns 的對話

    skip_analysis IS NOT NULL（pipeline/discard/no_analyze）的對話一律排除，
    作為 P0 匯入時同步標記之後的第二道防線。
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ct.conversation_id, c.project_path,
                   c.first_timestamp, c.last_timestamp
            FROM conversation_turns ct
            JOIN conversations c ON c.id = ct.conversation_id
            WHERE ct.p1_scanned_at IS NULL
              AND c.skip_analysis IS NULL
            ORDER BY c.first_timestamp
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_conversation_turns(conn, conversation_id: str,
                            only_unscanned: bool = True) -> List[Dict[str, Any]]:
    """取得指定對話的所有 turns（按 turn_seq 排序）

    Args:
        conn: DB 連線
        conversation_id: 對話 UUID
        only_unscanned: True 只取未掃描的 turns，False 取全部
    """
    where_clause = "WHERE ct.conversation_id = %s"
    if only_unscanned:
        where_clause += " AND ct.p1_scanned_at IS NULL"

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT ct.id, ct.turn_seq, ct.role, ct.timestamp,
                   ct.content, ct.tool_name, ct.tool_use_id,
                   ct.tool_params, ct.tool_is_error,
                   ct.files_touched, ct.has_thinking,
                   ct.is_sidechain, ct.model
            FROM conversation_turns ct
            {where_clause}
            ORDER BY ct.turn_seq
        """, (conversation_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_conversation_info(conn, conversation_id: str) -> Optional[Dict[str, Any]]:
    """取得對話的基本資訊"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, project_path, first_timestamp, last_timestamp,
                   total_turns, git_branch
            FROM conversations
            WHERE id = %s
        """, (conversation_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


# ============================================================
# DB 模式訊號偵測
# ============================================================

def _detect_error_signals(turns: List[Dict]) -> List[Dict[str, Any]]:
    """偵測 error 訊號：tool_result 中含錯誤"""
    signals = []
    for turn in turns:
        if turn['role'] != 'tool_result':
            continue
        content = turn.get('content') or ''
        if not content:
            continue

        # 檢查 tool_is_error 欄位
        is_error = turn.get('tool_is_error', False)

        # 檢查 content 中的錯誤模式
        error_match = _match_any(content, RE_ERROR)
        if (is_error or error_match) and not _is_excluded_error(content):
            trigger = error_match if error_match else 'tool_is_error=TRUE'
            signals.append({
                'type': 'error',
                'severity': 'high',
                'trigger': _truncate(trigger, 200),
                'turn_id': turn['id'],
                'turn_seq': turn['turn_seq'],
                'context_turns': _context_turn_seqs(turns, turn['turn_seq']),
                'related_files': turn.get('files_touched') or [],
            })
    return signals


def _detect_tool_failure_signals(turns: List[Dict]) -> List[Dict[str, Any]]:
    """偵測 tool_failure 訊號：tool_result 中出現失敗指標"""
    signals = []
    for turn in turns:
        if turn['role'] != 'tool_result':
            continue

        # tool_is_error 為 True 直接計入
        if turn.get('tool_is_error'):
            content = turn.get('content') or ''
            trigger = _match_any(content, RE_TOOL_FAILURE) if content else None
            if not trigger:
                trigger = 'tool_is_error=TRUE'
            signals.append({
                'type': 'tool_failure',
                'severity': 'medium',
                'trigger': _truncate(trigger, 200),
                'turn_id': turn['id'],
                'turn_seq': turn['turn_seq'],
                'context_turns': _context_turn_seqs(turns, turn['turn_seq']),
                'related_files': turn.get('files_touched') or [],
            })
            continue

        # 檢查 content 中的失敗模式
        content = turn.get('content') or ''
        if not content:
            continue
        failure_match = _match_any(content, RE_TOOL_FAILURE)
        if failure_match:
            signals.append({
                'type': 'tool_failure',
                'severity': 'medium',
                'trigger': _truncate(failure_match, 200),
                'turn_id': turn['id'],
                'turn_seq': turn['turn_seq'],
                'context_turns': _context_turn_seqs(turns, turn['turn_seq']),
                'related_files': turn.get('files_touched') or [],
            })
    return signals


def _detect_rollback_signals(turns: List[Dict]) -> List[Dict[str, Any]]:
    """偵測 rollback 訊號：用戶發言含回退語意"""
    signals = []
    for turn in turns:
        if turn['role'] != 'user':
            continue
        content = turn.get('content') or ''
        if not content:
            continue

        rb_zh = _match_any(content, RE_ROLLBACK_ZH)
        rb_en = _match_any(content, RE_ROLLBACK_EN)
        trigger_text = rb_zh or rb_en
        if trigger_text:
            signals.append({
                'type': 'rollback',
                'severity': 'high',
                'trigger': _truncate(f'user: {trigger_text}', 200),
                'turn_id': turn['id'],
                'turn_seq': turn['turn_seq'],
                'context_turns': _context_turn_seqs(turns, turn['turn_seq']),
                'related_files': _nearby_files(turns, turn['turn_seq']),
            })
    return signals


def _detect_retry_signals(turns: List[Dict]) -> List[Dict[str, Any]]:
    """偵測 retry 訊號：Claude 發言含重試語意"""
    signals = []
    for turn in turns:
        if turn['role'] != 'assistant':
            continue
        content = turn.get('content') or ''
        if not content:
            continue

        rt_zh = _match_any(content, RE_RETRY_ZH)
        rt_en = _match_any(content, RE_RETRY_EN)
        trigger_text = rt_zh or rt_en
        if trigger_text:
            signals.append({
                'type': 'retry',
                'severity': 'high',
                'trigger': _truncate(f'assistant: {trigger_text}', 200),
                'turn_id': turn['id'],
                'turn_seq': turn['turn_seq'],
                'context_turns': _context_turn_seqs(turns, turn['turn_seq']),
                'related_files': _nearby_files(turns, turn['turn_seq']),
            })
    return signals


def _detect_repeated_edit_signals(turns: List[Dict]) -> List[Dict[str, Any]]:
    """偵測 repeated_edit 訊號：同檔案被操作超過 N 次"""
    file_counter = Counter()
    file_turns = defaultdict(list)

    for turn in turns:
        files = turn.get('files_touched') or []
        for f in files:
            file_counter[f] += 1
            file_turns[f].append(turn['turn_seq'])

    signals = []
    for filepath, count in file_counter.items():
        if count > REPEATED_EDIT_THRESHOLD:
            signals.append({
                'type': 'repeated_edit',
                'severity': 'medium',
                'trigger': f'{filepath} x{count} (threshold={REPEATED_EDIT_THRESHOLD})',
                'turn_id': None,
                'turn_seq': None,
                'context_turns': file_turns[filepath][:20],
                'related_files': [filepath],
            })

    return signals


def _detect_long_struggle_signals(turns: List[Dict]) -> List[Dict[str, Any]]:
    """偵測 long_struggle 訊號：連續 N+ 個 tool_use/tool_result 針對同一檔案"""
    signals = []
    consecutive = 0
    current_files_key = None
    streak_start_seq = None

    for turn in turns:
        if turn['role'] not in ('tool_use', 'tool_result'):
            # 非工具操作，重置
            if consecutive >= LONG_STRUGGLE_THRESHOLD and current_files_key:
                signals.append({
                    'type': 'long_struggle',
                    'severity': 'medium',
                    'trigger': f'{consecutive} consecutive tool ops on: {_truncate(current_files_key, 100)}',
                    'turn_id': None,
                    'turn_seq': streak_start_seq,
                    'context_turns': list(range(
                        streak_start_seq,
                        streak_start_seq + consecutive
                    )),
                    'related_files': current_files_key.split(',') if current_files_key else [],
                })
            consecutive = 0
            current_files_key = None
            streak_start_seq = None
            continue

        files = turn.get('files_touched') or []
        files_key = ','.join(sorted(files)) if files else None

        if files_key and files_key == current_files_key:
            consecutive += 1
        else:
            # 檢查前一段是否達到門檻
            if consecutive >= LONG_STRUGGLE_THRESHOLD and current_files_key:
                signals.append({
                    'type': 'long_struggle',
                    'severity': 'medium',
                    'trigger': f'{consecutive} consecutive tool ops on: {_truncate(current_files_key, 100)}',
                    'turn_id': None,
                    'turn_seq': streak_start_seq,
                    'context_turns': list(range(
                        streak_start_seq,
                        streak_start_seq + consecutive
                    )),
                    'related_files': current_files_key.split(',') if current_files_key else [],
                })
            if files_key:
                current_files_key = files_key
                consecutive = 1
                streak_start_seq = turn['turn_seq']
            else:
                current_files_key = None
                consecutive = 0
                streak_start_seq = None

    # 檢查最後一段
    if consecutive >= LONG_STRUGGLE_THRESHOLD and current_files_key:
        signals.append({
            'type': 'long_struggle',
            'severity': 'medium',
            'trigger': f'{consecutive} consecutive tool ops on: {_truncate(current_files_key, 100)}',
            'turn_id': None,
            'turn_seq': streak_start_seq,
            'context_turns': list(range(
                streak_start_seq,
                streak_start_seq + consecutive
            )),
            'related_files': current_files_key.split(',') if current_files_key else [],
        })

    return signals


# ============================================================
# 輔助函式
# ============================================================

def _context_turn_seqs(turns: List[Dict], center_seq: int,
                       radius: int = 2) -> List[int]:
    """取得以 center_seq 為中心的前後 turn_seq 清單"""
    all_seqs = [t['turn_seq'] for t in turns]
    try:
        idx = all_seqs.index(center_seq)
    except ValueError:
        return [center_seq]
    start = max(0, idx - radius)
    end = min(len(all_seqs), idx + radius + 1)
    return all_seqs[start:end]


def _nearby_files(turns: List[Dict], center_seq: int,
                  radius: int = 5) -> List[str]:
    """取得 center_seq 附近 turns 中的 files_touched"""
    files = set()
    all_seqs = [t['turn_seq'] for t in turns]
    try:
        idx = all_seqs.index(center_seq)
    except ValueError:
        return []
    start = max(0, idx - radius)
    end = min(len(all_seqs), idx + radius + 1)
    for t in turns[start:end]:
        for f in (t.get('files_touched') or []):
            files.add(f)
    return list(files)


def _build_file_heatmap(turns: List[Dict]) -> Dict[str, int]:
    """建立檔案編輯熱圖"""
    counter = Counter()
    for turn in turns:
        for f in (turn.get('files_touched') or []):
            counter[f] += 1
    return dict(counter.most_common())


# ============================================================
# DB 更新
# ============================================================

def _update_turn_signals(conn, turn_id: int,
                         signals: List[Dict[str, Any]]) -> None:
    """更新單一 turn 的 p1_scanned_at 和 p1_signals"""
    now = datetime.now().astimezone()
    signals_json = json.dumps(signals, ensure_ascii=False) if signals else None

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversation_turns
            SET p1_scanned_at = %s,
                p1_signals = %s
            WHERE id = %s
        """, (now, signals_json, turn_id))


def _mark_turns_scanned(conn, turn_ids: List[int]) -> None:
    """批次標記 turns 為已掃描（無訊號的 turns）"""
    if not turn_ids:
        return
    now = datetime.now().astimezone()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversation_turns
            SET p1_scanned_at = %s
            WHERE id = ANY(%s) AND p1_scanned_at IS NULL
        """, (now, turn_ids))


def _update_conversation_p1(conn, conversation_id: str) -> None:
    """更新 conversations.p1_completed_at"""
    now = datetime.now().astimezone()
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversations
            SET p1_completed_at = %s
            WHERE id = %s
        """, (now, conversation_id))


# ============================================================
# 主掃描邏輯
# ============================================================

def scan_conversation_db(
    conn,
    conversation_id: str,
    rescan: bool = False,
    git_repo: Optional[str] = None,
    min_severity: str = 'low',
) -> Dict[str, Any]:
    """掃描單一對話（DB 模式）

    Args:
        conn: DB 連線
        conversation_id: 對話 UUID
        rescan: True 強制重新掃描全部 turns
        git_repo: git repo 路徑（可選）
        min_severity: 最低嚴重度過濾

    Returns:
        完整的掃描結果 dict
    """
    # 取得對話資訊
    conv_info = _get_conversation_info(conn, conversation_id)
    if not conv_info:
        return {
            'error': f'找不到對話: {conversation_id}',
            'conversation_id': str(conversation_id),
        }

    # 取得 turns
    turns = _get_conversation_turns(conn, conversation_id,
                                    only_unscanned=not rescan)
    if not turns:
        return {
            'conversation_id': str(conversation_id),
            'project_path': conv_info.get('project_path', ''),
            'scan_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_signals': 0,
            'message': '所有 turns 已掃描（使用 --rescan 強制重新掃描）' if not rescan else '無 turns',
            'signals': [],
            'git_signals': [],
            'file_edit_heatmap': {},
        }

    print(f'[INFO] 掃描對話: {conversation_id}', file=sys.stderr)
    print(f'[INFO] 專案: {conv_info.get("project_path", "")}', file=sys.stderr)
    print(f'[INFO] turns 數: {len(turns)}', file=sys.stderr)

    # --- 掃描訊號 ---
    all_signals = []
    all_signals.extend(_detect_error_signals(turns))
    all_signals.extend(_detect_tool_failure_signals(turns))
    all_signals.extend(_detect_rollback_signals(turns))
    all_signals.extend(_detect_retry_signals(turns))
    all_signals.extend(_detect_repeated_edit_signals(turns))
    all_signals.extend(_detect_long_struggle_signals(turns))

    # --- 建立 turn_id -> signals 的映射 ---
    turn_signals_map: Dict[int, List[Dict]] = defaultdict(list)
    for sig in all_signals:
        tid = sig.get('turn_id')
        if tid:
            turn_signals_map[tid].append(sig)

    # --- 過濾嚴重度 ---
    min_weight = SEVERITY_WEIGHT.get(min_severity, 0)
    filtered_signals = [
        s for s in all_signals
        if SEVERITY_WEIGHT.get(s['severity'], 0) >= min_weight
    ]

    # --- 排序（高嚴重度優先） ---
    filtered_signals.sort(
        key=lambda s: SEVERITY_WEIGHT.get(s['severity'], 0),
        reverse=True,
    )

    # --- 檔案熱圖 ---
    file_heatmap = _build_file_heatmap(turns)

    # --- Git 訊號 ---
    git_signals_list = []
    if git_repo:
        first_ts = conv_info.get('first_timestamp')
        last_ts = conv_info.get('last_timestamp')
        start_str = first_ts.isoformat() if first_ts else None
        end_str = last_ts.isoformat() if last_ts else None
        git_signal_objs = detect_git_signals(git_repo, start_str, end_str)
        git_signals_list = [
            gs.to_dict() for gs in git_signal_objs
            if SEVERITY_WEIGHT.get(gs.severity, 0) >= min_weight
        ]

    # --- 更新 DB ---
    # 1. 有訊號的 turns：寫入 p1_signals + p1_scanned_at
    turns_with_signals = set()
    for sig in all_signals:
        tid = sig.get('turn_id')
        if tid:
            turns_with_signals.add(tid)

    for tid in turns_with_signals:
        sigs_for_turn = turn_signals_map[tid]
        _update_turn_signals(conn, tid, sigs_for_turn)

    # 2. 無訊號的 turns：只標記 p1_scanned_at
    all_turn_ids = [t['id'] for t in turns]
    no_signal_ids = [tid for tid in all_turn_ids if tid not in turns_with_signals]
    _mark_turns_scanned(conn, no_signal_ids)

    # 3. 若全部 turns 已掃描，更新 conversations.p1_completed_at
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM conversation_turns
            WHERE conversation_id = %s AND p1_scanned_at IS NULL
        """, (conversation_id,))
        remaining = cur.fetchone()[0]
    if remaining == 0:
        _update_conversation_p1(conn, conversation_id)
        print(f'[INFO] 對話 P1 完成，已更新 p1_completed_at', file=sys.stderr)

    conn.commit()

    # --- 組裝結果 ---
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    period = {
        'start': conv_info['first_timestamp'].isoformat() if conv_info.get('first_timestamp') else '',
        'end': conv_info['last_timestamp'].isoformat() if conv_info.get('last_timestamp') else '',
    }

    result = {
        'conversation_id': str(conversation_id),
        'project_path': conv_info.get('project_path', ''),
        'scan_time': now_str,
        'conversation_period': period,
        'total_turns_scanned': len(turns),
        'total_signals': len(filtered_signals) + len(git_signals_list),
        'signals': filtered_signals,
        'git_signals': git_signals_list,
        'file_edit_heatmap': file_heatmap,
    }

    return result


def scan_all_unscanned(
    git_repo: Optional[str] = None,
    min_severity: str = 'low',
) -> List[Dict[str, Any]]:
    """掃描 DB 中所有未掃描的對話

    Returns:
        每個對話的掃描結果 list
    """
    conn = _get_db_connection()
    results = []

    try:
        conversations = _get_unscanned_conversations(conn)
        if not conversations:
            print('[INFO] 所有對話都已掃描', file=sys.stderr)
            return results

        print(f'[INFO] 找到 {len(conversations)} 個待掃描對話', file=sys.stderr)
        print('-' * 60, file=sys.stderr)

        for i, conv in enumerate(conversations, 1):
            conv_id = str(conv['conversation_id'])
            print(f'\n[{i}/{len(conversations)}] {conv_id}', file=sys.stderr)
            try:
                result = scan_conversation_db(
                    conn, conv_id,
                    rescan=False,
                    git_repo=git_repo,
                    min_severity=min_severity,
                )
                results.append(result)
            except Exception as e:
                print(f'[ERROR] {conv_id}: {e}', file=sys.stderr)
                try:
                    conn.rollback()
                except Exception:
                    pass

        return results
    finally:
        conn.close()


def scan_single_conversation(
    conversation_id: str,
    rescan: bool = False,
    git_repo: Optional[str] = None,
    min_severity: str = 'low',
) -> Dict[str, Any]:
    """掃描指定對話（DB 模式）

    Returns:
        掃描結果 dict
    """
    conn = _get_db_connection()
    try:
        result = scan_conversation_db(
            conn, conversation_id,
            rescan=rescan,
            git_repo=git_repo,
            min_severity=min_severity,
        )
        return result
    except Exception as e:
        print(f'[ERROR] 掃描失敗: {e}', file=sys.stderr)
        try:
            conn.rollback()
        except Exception:
            pass
        return {'error': str(e), 'conversation_id': conversation_id}
    finally:
        conn.close()


def print_db_summary(results) -> None:
    """印出 DB 模式掃描摘要

    Args:
        results: 單一結果 dict 或結果 list
    """
    if isinstance(results, dict):
        results = [results]

    total_conversations = len(results)
    total_signals = sum(r.get('total_signals', 0) for r in results)
    total_turns = sum(r.get('total_turns_scanned', 0) for r in results)

    print(f'\n{"=" * 60}', file=sys.stderr)
    print(f'DB 模式掃描完成', file=sys.stderr)
    print(f'  對話數: {total_conversations}', file=sys.stderr)
    print(f'  掃描 turns: {total_turns}', file=sys.stderr)
    print(f'  訊號總數: {total_signals}', file=sys.stderr)

    # 訊號類型分布
    type_counter = Counter()
    sev_counter = Counter()
    all_heatmap = Counter()

    for r in results:
        for s in r.get('signals', []):
            type_counter[s['type']] += 1
            sev_counter[s['severity']] += 1
        for s in r.get('git_signals', []):
            type_counter[f"git:{s['type']}"] += 1
            sev_counter[s['severity']] += 1
        for fp, cnt in r.get('file_edit_heatmap', {}).items():
            all_heatmap[fp] += cnt

    if type_counter:
        print(f'\n  訊號類型分布:', file=sys.stderr)
        for stype, count in type_counter.most_common():
            print(f'    {stype}: {count}', file=sys.stderr)

    if sev_counter:
        print(f'\n  嚴重度分布:', file=sys.stderr)
        for sev in ('high', 'medium', 'low'):
            if sev in sev_counter:
                print(f'    {sev}: {sev_counter[sev]}', file=sys.stderr)

    if all_heatmap:
        print(f'\n  檔案編輯熱圖 (前 10):', file=sys.stderr)
        for fp, cnt in all_heatmap.most_common(10):
            print(f'    {cnt:>3}x {fp}', file=sys.stderr)

    # 個別對話摘要（只在多對話時顯示）
    if total_conversations > 1:
        print(f'\n  各對話概況:', file=sys.stderr)
        for r in results:
            cid = r.get('conversation_id', '?')[:12]
            proj = r.get('project_path', '')
            ns = r.get('total_signals', 0)
            nt = r.get('total_turns_scanned', 0)
            print(f'    {cid}... | {proj} | {nt} turns | {ns} signals',
                  file=sys.stderr)

    print(f'{"=" * 60}', file=sys.stderr)
