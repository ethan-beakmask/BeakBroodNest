#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest Session Watchdog -- 對話監控器

監控正在進行的 Claude Code 對話，偵測異常狀態並記錄到 session_logs 表。
可配合 crontab 每分鐘執行一次。

監控項目:
  - JSONL 檔案大小/修改時間變化（偵測卡住）
  - Token 消耗速率
  - Agent 子對話的持續時間
  - 總對話時長

異常處理:
  - 超過閾值時，透過 tmux send-keys 對主線 pane 送出提醒
  - 記錄異常到 session_logs 表

用法:
  python session_watchdog.py --check              單次檢查
  python session_watchdog.py --check --verbose     詳細輸出
  python session_watchdog.py --status              顯示目前活躍對話狀態
  python session_watchdog.py --import-current      將目前活躍對話的統計寫入 session_logs
"""

import argparse
import configparser
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
# 設定
# ============================================================

# JSONL 路徑
CLAUDE_PROJECTS_DIR = os.path.expanduser('~/.claude/projects')

# 狀態檔（記錄上次檢查時的 JSONL 狀態）
STATE_FILE = '/opt/BeakBroodNest/data/watchdog_state.json'

# 閾值
THRESHOLDS = {
    'stale_minutes': 10,         # JSONL 超過 N 分鐘沒更新視為可能卡住
    'agent_max_minutes': 40,     # 單一 agent 超過 N 分鐘
    'session_max_hours': 2,      # 主線對話超過 N 小時
    'zero_output_minutes': 5,    # 連續 N 分鐘 output_tokens 為 0
}

# DB 連線
CONFIG_SEARCH_PATHS = [
    '/opt/BeakBroodNest/config.ini',
]


def _load_db_params() -> dict:
    """從 config.ini 讀取 DB 連線參數。密碼必須由 config.ini 提供，否則直接終止。"""
    for path in CONFIG_SEARCH_PATHS:
        if os.path.isfile(path):
            cfg = configparser.RawConfigParser()
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


def _get_db_connection():
    import psycopg2
    return psycopg2.connect(**_load_db_params())


# ============================================================
# JSONL 掃描
# ============================================================

def find_active_sessions() -> List[dict]:
    """
    找出最近有更新的 JSONL 檔案（視為活躍對話）。
    只看最近 3 小時內有修改的檔案。
    """
    cutoff = time.time() - 3 * 3600
    active = []

    for proj_dir in glob.glob(f'{CLAUDE_PROJECTS_DIR}/-opt-*'):
        project_name = proj_dir.split('/')[-1].replace('-opt-', '/opt/')

        for jsonl in glob.glob(f'{proj_dir}/*.jsonl'):
            stat = os.stat(jsonl)
            if stat.st_mtime < cutoff:
                continue

            fname = os.path.basename(jsonl)
            is_agent = fname.startswith('agent-')
            session_id = fname.replace('.jsonl', '')

            active.append({
                'session_id': session_id,
                'project_path': project_name,
                'jsonl_path': jsonl,
                'file_size': stat.st_size,
                'last_modified': datetime.fromtimestamp(stat.st_mtime),
                'is_agent': is_agent,
            })

    # 按修改時間排序（最新在前）
    active.sort(key=lambda x: x['last_modified'], reverse=True)
    return active


def analyze_jsonl(jsonl_path: str) -> dict:
    """
    分析單一 JSONL 檔案的統計資料。
    只讀最後部分以提高效率。
    """
    stats = {
        'total_lines': 0,
        'total_input_tokens': 0,
        'total_output_tokens': 0,
        'first_timestamp': None,
        'last_timestamp': None,
        'model': '',
        'roles': {},
        'agent_sessions': [],  # agent 子對話 ID
        'last_assistant_time': None,
        'last_user_time': None,
    }

    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                stats['total_lines'] += 1

                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = d.get('type', '')
                timestamp = d.get('timestamp')
                role = msg_type
                stats['roles'][role] = stats['roles'].get(role, 0) + 1

                if timestamp:
                    if stats['first_timestamp'] is None:
                        stats['first_timestamp'] = timestamp
                    stats['last_timestamp'] = timestamp

                    if msg_type == 'assistant':
                        stats['last_assistant_time'] = timestamp
                    elif msg_type == 'user':
                        stats['last_user_time'] = timestamp

                # Token 統計
                if msg_type == 'assistant':
                    msg = d.get('message', {})
                    usage = msg.get('usage', {})
                    stats['total_input_tokens'] += usage.get('input_tokens', 0)
                    stats['total_output_tokens'] += usage.get('output_tokens', 0)
                    stats['model'] = msg.get('model', stats['model'])

                    # cache tokens
                    stats['total_input_tokens'] += usage.get('cache_read_input_tokens', 0)
                    stats['total_input_tokens'] += usage.get('cache_creation_input_tokens', 0)

    except Exception as e:
        stats['error'] = str(e)

    return stats


# ============================================================
# 狀態追蹤
# ============================================================

def load_state() -> dict:
    """載入上次的狀態"""
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    """儲存狀態"""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)


# ============================================================
# 異常偵測
# ============================================================

def detect_anomalies(session: dict, stats: dict, prev_state: dict) -> List[dict]:
    """
    偵測單一對話的異常狀態。

    回傳: [{"type": "stale", "message": "...", "severity": "warning|critical"}]
    """
    anomalies = []
    now = datetime.now()
    sid = session['session_id']

    # 1. JSONL 長時間沒更新
    age_minutes = (now - session['last_modified']).total_seconds() / 60
    if age_minutes > THRESHOLDS['stale_minutes'] and not session['is_agent']:
        anomalies.append({
            'type': 'stale',
            'message': f'JSONL {age_minutes:.0f} 分鐘未更新',
            'severity': 'critical' if age_minutes > 30 else 'warning',
        })

    # 2. 對話總時長過長
    if stats.get('first_timestamp') and stats.get('last_timestamp'):
        try:
            first = datetime.fromisoformat(stats['first_timestamp'].replace('Z', '+00:00'))
            last = datetime.fromisoformat(stats['last_timestamp'].replace('Z', '+00:00'))
            duration_hours = (last - first).total_seconds() / 3600
            if duration_hours > THRESHOLDS['session_max_hours']:
                anomalies.append({
                    'type': 'long_session',
                    'message': f'對話已持續 {duration_hours:.1f} 小時',
                    'severity': 'warning',
                })
        except Exception:
            pass

    # 3. Agent 子對話持續時間
    if session['is_agent']:
        try:
            first = datetime.fromisoformat(stats['first_timestamp'].replace('Z', '+00:00'))
            agent_minutes = (now - first.replace(tzinfo=None)).total_seconds() / 60
            if agent_minutes > THRESHOLDS['agent_max_minutes']:
                anomalies.append({
                    'type': 'agent_timeout',
                    'message': f'Agent 已執行 {agent_minutes:.0f} 分鐘（閾值 {THRESHOLDS["agent_max_minutes"]}）',
                    'severity': 'critical',
                })
        except Exception:
            pass

    # 4. Token 消耗停滯
    prev = prev_state.get(sid, {})
    if prev.get('total_output_tokens'):
        prev_tokens = prev['total_output_tokens']
        curr_tokens = stats.get('total_output_tokens', 0)
        if curr_tokens == prev_tokens and not session['is_agent']:
            stale_count = prev.get('stale_count', 0) + 1
            if stale_count >= THRESHOLDS['zero_output_minutes']:
                anomalies.append({
                    'type': 'token_stale',
                    'message': f'Output tokens 連續 {stale_count} 次檢查未增加（停在 {curr_tokens}）',
                    'severity': 'warning',
                })

    # 5. 檔案大小未增長
    if prev.get('file_size'):
        if session['file_size'] == prev['file_size'] and age_minutes < THRESHOLDS['stale_minutes']:
            # 大小沒變但還在閾值內，正常
            pass
        elif session['file_size'] == prev['file_size'] and age_minutes >= THRESHOLDS['stale_minutes']:
            anomalies.append({
                'type': 'size_stale',
                'message': f'檔案大小 {session["file_size"]} bytes 持續未變化',
                'severity': 'warning',
            })

    return anomalies


# ============================================================
# tmux 提醒
# ============================================================

def send_tmux_reminder(pane: str, message: str):
    """透過 tmux send-keys 對指定 pane 送出提醒"""
    try:
        # 先送一個空行確保在新行
        subprocess.run(
            ['tmux', 'send-keys', '-t', pane, '', 'Enter'],
            capture_output=True, timeout=5,
        )
        time.sleep(0.3)
        # 送出提醒訊息
        subprocess.run(
            ['tmux', 'send-keys', '-t', pane, message, 'Enter'],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        print(f'[WARN] tmux send-keys 失敗: {e}')


def find_claude_panes() -> List[dict]:
    """找出正在運行 claude 的 tmux panes"""
    try:
        result = subprocess.run(
            ['tmux', 'list-panes', '-a', '-F',
             '#{session_name}:#{window_index}.#{pane_index} #{pane_pid} #{pane_current_command}'],
            capture_output=True, text=True, timeout=5,
        )
        panes = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 3 and parts[2] == 'claude':
                panes.append({
                    'pane_id': parts[0],
                    'pid': int(parts[1]),
                    'command': parts[2],
                })
        return panes
    except Exception:
        return []


# ============================================================
# session_logs 寫入
# ============================================================

def upsert_session_log(conn, session: dict, stats: dict, anomalies: List[dict]):
    """新增或更新 session_logs 記錄"""
    cur = conn.cursor()

    duration_seconds = None
    if stats.get('first_timestamp') and stats.get('last_timestamp'):
        try:
            first = datetime.fromisoformat(stats['first_timestamp'].replace('Z', '+00:00'))
            last = datetime.fromisoformat(stats['last_timestamp'].replace('Z', '+00:00'))
            duration_seconds = int((last - first).total_seconds())
        except Exception:
            pass

    abnormal = len(anomalies) > 0
    abnormal_reason = '; '.join(a['message'] for a in anomalies) if anomalies else ''

    # 先檢查是否已有記錄
    cur.execute(
        "SELECT id FROM session_logs WHERE session_id = %s",
        (session['session_id'],)
    )
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE session_logs SET
                ended_at = NOW(),
                duration_seconds = %s,
                total_turns = %s,
                total_input_tokens = %s,
                total_output_tokens = %s,
                abnormal = %s,
                abnormal_reason = %s,
                error_count = %s
            WHERE session_id = %s
        """, (
            duration_seconds,
            stats.get('total_lines', 0),
            stats.get('total_input_tokens', 0),
            stats.get('total_output_tokens', 0),
            abnormal,
            abnormal_reason[:500],
            len([a for a in anomalies if a['severity'] == 'critical']),
            session['session_id'],
        ))
    else:
        trigger_type = 'agent' if session['is_agent'] else 'interactive'
        started_at = stats.get('first_timestamp')

        cur.execute("""
            INSERT INTO session_logs
                (session_id, project_path, trigger_type, started_at, ended_at,
                 duration_seconds, total_turns, total_input_tokens, total_output_tokens,
                 abnormal, abnormal_reason, error_count)
            VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s)
        """, (
            session['session_id'],
            session['project_path'],
            trigger_type,
            started_at,
            duration_seconds,
            stats.get('total_lines', 0),
            stats.get('total_input_tokens', 0),
            stats.get('total_output_tokens', 0),
            abnormal,
            abnormal_reason[:500],
            len([a for a in anomalies if a['severity'] == 'critical']),
        ))

    conn.commit()


# ============================================================
# 主流程
# ============================================================

def check_once(verbose: bool = False, send_alerts: bool = False):
    """單次檢查所有活躍對話"""
    active = find_active_sessions()
    if not active:
        if verbose:
            print('[INFO] 沒有活躍的對話')
        return

    prev_state = load_state()
    new_state = {}
    conn = None

    try:
        conn = _get_db_connection()
    except Exception as e:
        print(f'[WARN] DB 連線失敗，跳過寫入: {e}')

    claude_panes = find_claude_panes()

    print(f'[{datetime.now().strftime("%H:%M:%S")}] 檢查 {len(active)} 個活躍對話')

    all_anomalies = []

    for session in active:
        sid = session['session_id']
        stats = analyze_jsonl(session['jsonl_path'])
        anomalies = detect_anomalies(session, stats, prev_state)

        # 更新狀態
        prev_sid_state = prev_state.get(sid, {})
        stale_count = prev_sid_state.get('stale_count', 0)
        if stats.get('total_output_tokens') == prev_sid_state.get('total_output_tokens'):
            stale_count += 1
        else:
            stale_count = 0

        new_state[sid] = {
            'file_size': session['file_size'],
            'total_output_tokens': stats.get('total_output_tokens', 0),
            'total_input_tokens': stats.get('total_input_tokens', 0),
            'last_check': datetime.now().isoformat(),
            'stale_count': stale_count,
            'total_lines': stats.get('total_lines', 0),
        }

        if verbose or anomalies:
            age = (datetime.now() - session['last_modified']).total_seconds()
            prefix = 'AGENT' if session['is_agent'] else 'MAIN'
            print(f'  [{prefix}] {sid[:12]}... '
                  f'project={session["project_path"].split("/")[-1]} '
                  f'lines={stats["total_lines"]} '
                  f'out_tokens={stats.get("total_output_tokens", 0)} '
                  f'age={age:.0f}s '
                  f'model={stats.get("model", "?")}')

        for a in anomalies:
            icon = '!!' if a['severity'] == 'critical' else '!'
            print(f'    [{icon}] {a["type"]}: {a["message"]}')
            all_anomalies.append({**a, 'session_id': sid})

        # 寫入 session_logs
        if conn:
            try:
                upsert_session_log(conn, session, stats, anomalies)
            except Exception as e:
                print(f'    [WARN] session_logs 寫入失敗: {e}')
                conn.rollback()

    # 異常提醒
    # 注意：tmux send-keys 會干擾正在進行的對話，
    # 且目前無法區分哪個 pane 對應哪個異常對話，
    # 因此暫時只記錄到 log，不透過 tmux 送提醒。
    # 未來建立 pane <-> session 對應後再啟用。
    if send_alerts and all_anomalies:
        critical = [a for a in all_anomalies if a['severity'] == 'critical']
        if critical:
            print(f'  [ALERT] {len(critical)} 個嚴重異常（已記錄到 session_logs，未送 tmux 提醒）')

    save_state(new_state)
    if conn:
        conn.close()

    print(f'  合計: {len(active)} 對話, {len(all_anomalies)} 異常')


def show_status():
    """顯示目前活躍對話的詳細狀態"""
    active = find_active_sessions()
    if not active:
        print('沒有活躍的對話')
        return

    print(f'活躍對話: {len(active)} 個')
    print(f'{"=" * 80}')

    for session in active:
        stats = analyze_jsonl(session['jsonl_path'])
        prefix = 'AGENT' if session['is_agent'] else 'MAIN '
        age_min = (datetime.now() - session['last_modified']).total_seconds() / 60

        duration = ''
        if stats.get('first_timestamp') and stats.get('last_timestamp'):
            try:
                first = datetime.fromisoformat(stats['first_timestamp'].replace('Z', '+00:00'))
                last = datetime.fromisoformat(stats['last_timestamp'].replace('Z', '+00:00'))
                dur_min = (last - first).total_seconds() / 60
                duration = f'{dur_min:.0f}min'
            except Exception:
                pass

        print(f'  [{prefix}] {session["session_id"][:20]}...')
        print(f'         專案: {session["project_path"]}')
        print(f'         模型: {stats.get("model", "?")}')
        print(f'         行數: {stats["total_lines"]}  |  大小: {session["file_size"] / 1024:.1f}KB')
        print(f'         持續: {duration}  |  上次更新: {age_min:.1f}min ago')
        print(f'         Input: {stats.get("total_input_tokens", 0):,}  |  '
              f'Output: {stats.get("total_output_tokens", 0):,}')
        print(f'         角色: {stats.get("roles", {})}')
        print()


def import_current():
    """將目前活躍對話寫入 session_logs"""
    active = find_active_sessions()
    if not active:
        print('沒有活躍的對話')
        return

    conn = _get_db_connection()
    imported = 0
    for session in active:
        stats = analyze_jsonl(session['jsonl_path'])
        anomalies = detect_anomalies(session, stats, {})
        try:
            upsert_session_log(conn, session, stats, anomalies)
            imported += 1
            print(f'  [OK] {session["session_id"][:12]}... -> session_logs')
        except Exception as e:
            print(f'  [FAIL] {session["session_id"][:12]}...: {e}')
            conn.rollback()

    conn.close()
    print(f'匯入完成: {imported}/{len(active)}')


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest Session Watchdog -- 對話監控器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python session_watchdog.py --check               單次檢查
  python session_watchdog.py --check -v            詳細輸出
  python session_watchdog.py --check --alert       檢查並送 tmux 提醒
  python session_watchdog.py --status              顯示活躍對話狀態
  python session_watchdog.py --import-current      寫入 session_logs

搭配 crontab:
  * * * * * ethan /opt/BeakBroodNest/venv/bin/python3 /opt/BeakBroodNest/scripts/session_watchdog.py --check --alert >> /opt/tmp/BeakBroodNest-session_watchdog.log 2>&1
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='單次檢查所有活躍對話')
    group.add_argument('--status', action='store_true', help='顯示活躍對話狀態')
    group.add_argument('--import-current', action='store_true', help='匯入活躍對話到 session_logs')

    parser.add_argument('-v', '--verbose', action='store_true', help='詳細輸出')
    parser.add_argument('--alert', action='store_true', help='異常時送 tmux 提醒')

    args = parser.parse_args()

    if args.check:
        check_once(verbose=args.verbose, send_alerts=args.alert)
    elif args.status:
        show_status()
    elif args.import_current:
        import_current()


if __name__ == '__main__':
    main()
