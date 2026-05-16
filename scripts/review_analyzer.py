#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest P3 復盤分析器 -- 雛形版

從 P1 訊號 + 對話內容產出三類分析：
  a. 改進評估：可改進的做法
  b. 易出錯技術統計：開發時常出錯的技術項目
  c. 項目追蹤：用戶提到的待辦是否有記錄

輸出存入 pipeline_runs 表，同時寫入 JSON 檔供觀察 UI 讀取。

用法:
  python review_analyzer.py --all                    分析所有已掃描的對話
  python review_analyzer.py -c <uuid>                分析指定對話
  python review_analyzer.py --stats                  僅輸出技術統計（不呼叫 claude）
  python review_analyzer.py --all --dry-run           乾跑模式
"""

import argparse
import configparser
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

# ============================================================
# DB 連線
# ============================================================

_INSTALL_DIR = os.environ.get('BBN_INSTALL_DIR') or '/opt/BeakBroodNest'
CONFIG_SEARCH_PATHS = [
    os.path.join(_INSTALL_DIR, 'config.ini'),
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
    params = _load_db_params()
    return psycopg2.connect(**params)


# ============================================================
# a. 技術錯誤統計（傳統程式，不需 AI）
# ============================================================

def collect_error_stats(conn, conversation_id: str = None) -> dict:
    """
    從 P1 訊號統計易出錯的技術項目。

    探索性失敗識別（C 案）：
      若 tool_failure / error 訊號發生後 EXPLORATION_WINDOW 個 turn 內出現 retry 訊號，
      視為「Claude 嘗試後換方式」的正常探索行為，從 by_type.tool_failure / by_type.error
      移到 by_type.exploration；對應的 error_pattern 也移到 by_exploration_pattern。
      可避免把日常探索誤計為真錯誤。

    回傳:
    {
        "by_type": {"error": 79, "tool_failure": 53, "exploration": 30, ...},
        "by_tool": {"Bash": 30, "Edit": 15, ...},
        "by_error_pattern": {...},          # 真錯誤
        "by_exploration_pattern": {...},    # 探索性失敗
        "by_file": {"/opt/xxx/app.py": 8, ...},
        "conversations_analyzed": 10
    }
    """
    import re

    EXPLORATION_WINDOW = 5  # tool_failure/error 後 N turn 內若有 retry，視為探索

    cur = conn.cursor()

    # 篩選條件
    where = "WHERE p1_signals IS NOT NULL"
    params = []
    if conversation_id:
        where += " AND conversation_id = %s"
        params.append(conversation_id)

    # 取所有有訊號的 turns
    cur.execute(f"""
        SELECT conversation_id, turn_seq, role, tool_name, content, p1_signals
        FROM conversation_turns
        {where}
        ORDER BY conversation_id, turn_seq
    """, params)

    rows = cur.fetchall()

    stats = {
        'by_type': {},
        'by_tool': {},
        'by_error_pattern': {},
        'by_exploration_pattern': {},
        'by_file': {},
        'conversations_analyzed': set(),
        'total_signal_turns': len(rows),
        'exploration_window': EXPLORATION_WINDOW,
    }

    # 常見錯誤模式
    error_patterns = [
        ('permission denied', 'permission denied'),
        ('ModuleNotFoundError', 'ModuleNotFoundError'),
        ('ImportError', 'ImportError'),
        ('FileNotFoundError', 'FileNotFoundError'),
        ('SyntaxError', 'SyntaxError'),
        ('TypeError', 'TypeError'),
        ('KeyError', 'KeyError'),
        ('ConnectionRefusedError', 'ConnectionRefusedError'),
        ('TimeoutError', 'TimeoutError'),
        ('relation .* does not exist', 'DB relation not exist'),
        ('column .* does not exist', 'DB column not exist'),
        ('No such file or directory', 'No such file or directory'),
        ('command not found', 'command not found'),
        ('UNIQUE constraint', 'UNIQUE constraint violation'),
        ('already exists', 'already exists'),
    ]

    # 第一輪：parse signals + 建 retry 索引
    parsed = []  # (conv_id_str, turn_seq, role, tool_name, content, signals_list)
    retry_turns = set()  # {(conv_id_str, turn_seq)}
    for row in rows:
        conv_id, turn_seq, role, tool_name, content, signals = row
        if isinstance(signals, str):
            signals = json.loads(signals)
        signals = signals or []
        cid = str(conv_id)
        parsed.append((cid, turn_seq, role, tool_name, content, signals))
        for sig in signals:
            if sig.get('type') == 'retry':
                retry_turns.add((cid, turn_seq))

    def _is_exploratory(cid, turn_seq):
        """tool_failure / error 後 EXPLORATION_WINDOW 個 turn 內有 retry → 探索性"""
        for i in range(1, EXPLORATION_WINDOW + 1):
            if (cid, turn_seq + i) in retry_turns:
                return True
        return False

    # 第二輪：統計
    for cid, turn_seq, role, tool_name, content, signals in parsed:
        stats['conversations_analyzed'].add(cid)

        # 該 turn 是否含 tool_failure / error 訊號 + 後續是否 retry
        has_failure_sig = any(s.get('type') in ('tool_failure', 'error') for s in signals)
        is_explore = has_failure_sig and _is_exploratory(cid, turn_seq)

        # by_type 統計
        for sig in signals:
            sig_type = sig.get('type', 'unknown')
            if is_explore and sig_type in ('tool_failure', 'error'):
                stats['by_type']['exploration'] = stats['by_type'].get('exploration', 0) + 1
            else:
                stats['by_type'][sig_type] = stats['by_type'].get(sig_type, 0) + 1

        # 工具統計
        if tool_name:
            stats['by_tool'][tool_name] = stats['by_tool'].get(tool_name, 0) + 1

        # 錯誤模式匹配 → 探索與真錯誤分桶
        content_str = content or ''
        for pattern, label in error_patterns:
            if re.search(pattern, content_str, re.IGNORECASE):
                if is_explore:
                    stats['by_exploration_pattern'][label] = stats['by_exploration_pattern'].get(label, 0) + 1
                else:
                    stats['by_error_pattern'][label] = stats['by_error_pattern'].get(label, 0) + 1
                break  # 每個 turn 只匹配第一個模式

    stats['conversations_analyzed'] = len(stats['conversations_analyzed'])

    # 排序
    for key in ['by_type', 'by_tool', 'by_error_pattern', 'by_exploration_pattern', 'by_file']:
        stats[key] = dict(sorted(stats[key].items(), key=lambda x: x[1], reverse=True))

    return stats


# ============================================================
# c. 用戶提到的項目追蹤
# ============================================================

def collect_user_mentions(conn, conversation_id: str = None) -> list:
    """
    掃描用戶發言中可能是待辦/任務/需求的句子。

    回傳: [{
        "conversation_id": "xxx",
        "turn_seq": 42,
        "text": "用戶原文片段",
        "mention_type": "todo | request | question | decision",
        "timestamp": "2026-04-20T..."
    }]
    """
    cur = conn.cursor()

    # 排除 P2 dispatcher 灌入的 user message（actor_id 標記 + prompt 前綴雙保險）
    where = (
        "WHERE role = 'user' AND content IS NOT NULL AND content != '' "
        "AND (actor_id IS NULL OR actor_id NOT LIKE 'p2-dispatcher%') "
        "AND content NOT LIKE '請對以下 topic 產出結構化摘要%' "
        "AND content NOT LIKE '[CC-LAUNCH-KIND=p2-dispatcher]%'"
    )
    params = []
    if conversation_id:
        where += " AND conversation_id = %s"
        params.append(conversation_id)

    cur.execute(f"""
        SELECT conversation_id, turn_seq, timestamp, content
        FROM conversation_turns
        {where}
        ORDER BY conversation_id, turn_seq
    """, params)

    rows = cur.fetchall()
    mentions = []

    import re

    # 待辦/需求關鍵字
    todo_patterns = [
        (r'(?:要|需要|必須|應該|記得|別忘了|待辦|TODO|FIXME|HACK)[\s：:].{5,80}', 'todo'),
        (r'(?:幫我|請|麻煩|能不能|可以).{5,80}', 'request'),
        (r'(?:之後|下次|明天|後續|將來|未來).{5,80}', 'todo'),
        (r'(?:為什麼|怎麼|如何|是否|有沒有).{5,60}', 'question'),
        (r'(?:決定|確定|就這樣|就用|採用|選擇).{5,60}', 'decision'),
    ]

    for row in rows:
        conv_id, turn_seq, timestamp, content = row
        content_str = content or ''

        # 跳過太短的發言
        if len(content_str) < 10:
            continue

        for pattern, mention_type in todo_patterns:
            matches = re.findall(pattern, content_str)
            for m in matches[:2]:  # 每種類型最多取 2 個
                mentions.append({
                    'conversation_id': str(conv_id),
                    'turn_seq': turn_seq,
                    'text': m.strip()[:200],
                    'mention_type': mention_type,
                    'timestamp': timestamp.isoformat() if timestamp else None,
                })

    return mentions


# ============================================================
# a. 改進評估（claude -p，先做簡單版）
# ============================================================

REVIEW_SYSTEM_PROMPT = """\
你是 BeakBroodNest 復盤系統的改進評估器。你的任務是根據對話中的錯誤訊號，評估是否有可改進的做法。

## 嚴格規則

1. 只依據提供的訊號和上下文作答，不要推測。
2. 區分「微觀修正」（當下解法沒問題）和「架構問題」（整個方向可能錯了）。
3. 不要給空泛建議如「下次注意」，要具體可行動。

## 輸出格式

只輸出一個 JSON 陣列，不要加 markdown 包裝。每個元素：

{
  "issue": "問題描述（30字以內）",
  "category": "architecture | implementation | config | workflow | false_alarm",
  "severity": "high | medium | low",
  "current_approach": "當時怎麼做的",
  "suggestion": "建議怎麼改（具體可行動）",
  "evidence_turns": [turn 序號列表],
  "confidence": 0.0 到 1.0
}

如果訊號全部是誤報或正常開發過程，回傳空陣列 []。
"""


def run_improvement_review(conn, conversation_id: str, dry_run: bool = False) -> Optional[list]:
    """對單一對話執行改進評估（呼叫 claude -p）"""
    cur = conn.cursor()

    # 取訊號 turns + 上下文
    cur.execute("""
        SELECT turn_seq, role, tool_name, content, p1_signals
        FROM conversation_turns
        WHERE conversation_id = %s AND p1_signals IS NOT NULL
        ORDER BY turn_seq
    """, (conversation_id,))
    signal_rows = cur.fetchall()

    if not signal_rows:
        return []

    # 組裝 context
    lines = [f"# 對話 {conversation_id} 的訊號片段\n"]
    for row in signal_rows:
        turn_seq, role, tool_name, content, signals = row
        if isinstance(signals, str):
            signals = json.loads(signals)

        sig_types = [s.get('type', '?') for s in (signals or [])]
        sig_sevs = [s.get('severity', '?') for s in (signals or [])]

        lines.append(f"## Turn {turn_seq} [{role}] tool={tool_name or '-'}")
        lines.append(f"signals: {sig_types} severity: {sig_sevs}")
        # 截斷內容
        content_str = (content or '')[:800]
        if content_str:
            lines.append(f"```\n{content_str}\n```")
        lines.append("")

    context = "\n".join(lines)

    if dry_run:
        print(f"  [DRY-RUN] {conversation_id}: {len(signal_rows)} signal turns, context {len(context)} chars")
        return None

    # 呼叫 claude -p
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, prefix='p3-review-') as f:
        f.write(context)
        ctx_file = f.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, prefix='p3-sys-') as f:
        f.write(REVIEW_SYSTEM_PROMPT)
        sys_file = f.name

    try:
        prompt = f"請分析以下對話訊號片段，產出改進評估。"
        cmd = [
            'claude', '-p', prompt,
            '--input-file', ctx_file,
            '--append-system-prompt-file', sys_file,
            '--output-format', 'text',
            '--model', 'haiku',
            '--max-turns', '1',
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            print(f"  [ERROR] claude -p 失敗: {result.stderr[:200]}")
            return None

        # 從輸出提取 JSON
        output = result.stdout.strip()
        return _extract_json_array(output)
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT] claude -p 超時")
        return None
    finally:
        os.unlink(ctx_file)
        os.unlink(sys_file)


def _extract_json_array(text: str) -> Optional[list]:
    """從混合文本中提取 JSON array"""
    # 找第一個 [ 到最後一個 ]
    start = text.find('[')
    if start < 0:
        return None
    # 從 start 找配對的 ]
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ============================================================
# 結果儲存
# ============================================================

def save_review_results(conn, conversation_id: str,
                        error_stats: dict,
                        user_mentions: list,
                        improvements: Optional[list]):
    """將分析結果存入 pipeline_runs 表"""
    cur = conn.cursor()

    stages = [
        {
            'name': 'error_stats',
            'status': 'completed',
            'output_summary': f"{error_stats.get('total_signal_turns', 0)} signal turns analyzed",
        },
        {
            'name': 'user_mentions',
            'status': 'completed',
            'output_summary': f"{len(user_mentions)} mentions found",
        },
        {
            'name': 'improvement_review',
            'status': 'completed' if improvements is not None else 'skipped',
            'output_summary': f"{len(improvements)} suggestions" if improvements else 'skipped',
        },
    ]

    cur.execute("""
        INSERT INTO pipeline_runs
            (pipeline_name, trigger_type, conversation_id, stages, current_stage,
             status, started_at, completed_at, signals_found)
        VALUES ('p3_review', 'manual', %s, %s, 'completed', 'completed', NOW(), NOW(), %s)
        RETURNING id
    """, (
        conversation_id,
        json.dumps(stages, ensure_ascii=False),
        error_stats.get('total_signal_turns', 0),
    ))

    run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


# ============================================================
# 結果寫入 JSON（供觀察 UI 讀取）
# ============================================================

RESULTS_DIR = os.path.join(_INSTALL_DIR, 'data/reviews')


def save_results_json(conversation_id: str, error_stats: dict,
                      user_mentions: list, improvements: Optional[list]):
    """將結果寫入 JSON 檔案"""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    result = {
        'conversation_id': conversation_id,
        'analyzed_at': datetime.now().isoformat(),
        'error_stats': error_stats,
        'user_mentions': user_mentions,
        'improvements': improvements,
    }
    path = os.path.join(RESULTS_DIR, f'{conversation_id}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


# ============================================================
# 主流程
# ============================================================

def analyze_conversation(conn, conversation_id: str, dry_run: bool = False,
                         skip_claude: bool = False) -> dict:
    """分析單一對話"""
    print(f"\n[P3] 分析對話: {conversation_id}")

    # b. 技術統計
    error_stats = collect_error_stats(conn, conversation_id)
    print(f"  [b] 訊號 turns: {error_stats['total_signal_turns']}")
    print(f"      類型: {error_stats['by_type']}")
    if error_stats['by_error_pattern']:
        print(f"      錯誤模式: {error_stats['by_error_pattern']}")

    # c. 用戶提到的項目
    user_mentions = collect_user_mentions(conn, conversation_id)
    print(f"  [c] 用戶提及: {len(user_mentions)} 條")
    for m in user_mentions[:5]:
        print(f"      [{m['mention_type']}] T{m['turn_seq']}: {m['text'][:60]}")
    if len(user_mentions) > 5:
        print(f"      ... 還有 {len(user_mentions) - 5} 條")

    # a. 改進評估
    improvements = None
    if not skip_claude and error_stats['total_signal_turns'] > 0:
        improvements = run_improvement_review(conn, conversation_id, dry_run)
        if improvements:
            print(f"  [a] 改進建議: {len(improvements)} 條")
            for imp in improvements:
                print(f"      [{imp.get('severity', '?')}] {imp.get('issue', '?')}")
        elif not dry_run:
            print(f"  [a] 無改進建議（正常開發過程或誤報）")
    else:
        print(f"  [a] 跳過 claude -p（{'--stats 模式' if skip_claude else '無訊號'}）")

    # 儲存
    if not dry_run:
        save_review_results(conn, conversation_id, error_stats, user_mentions, improvements)
        path = save_results_json(conversation_id, error_stats, user_mentions, improvements)
        print(f"  [OK] 結果: {path}")

    return {
        'error_stats': error_stats,
        'user_mentions': user_mentions,
        'improvements': improvements,
    }


def analyze_all(conn, dry_run: bool = False, skip_claude: bool = False):
    """分析所有已匯入的對話"""
    cur = conn.cursor()
    cur.execute("SELECT id FROM conversations ORDER BY last_timestamp DESC")
    conv_ids = [str(row[0]) for row in cur.fetchall()]
    print(f"[P3] 共 {len(conv_ids)} 個對話待分析")

    # 全域統計
    global_stats = collect_error_stats(conn)
    print(f"\n[P3] === 全域統計 ===")
    print(f"  對話數: {global_stats['conversations_analyzed']}")
    print(f"  訊號 turns: {global_stats['total_signal_turns']}")
    print(f"  類型分布: {global_stats['by_type']}")
    print(f"  工具分布: {global_stats['by_tool']}")
    print(f"  錯誤模式: {global_stats['by_error_pattern']}")

    if not dry_run:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        global_path = os.path.join(RESULTS_DIR, '_global_stats.json')
        with open(global_path, 'w', encoding='utf-8') as f:
            json.dump({
                'analyzed_at': datetime.now().isoformat(),
                'stats': global_stats,
            }, f, ensure_ascii=False, indent=2)
        print(f"  全域統計: {global_path}")

    for conv_id in conv_ids:
        analyze_conversation(conn, conv_id, dry_run, skip_claude)


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest P3 復盤分析器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python review_analyzer.py --stats                  全域技術統計（不呼叫 claude）
  python review_analyzer.py --all                    分析所有對話（含 claude -p）
  python review_analyzer.py --all --dry-run           乾跑模式
  python review_analyzer.py -c <uuid>                分析指定對話
  python review_analyzer.py -c <uuid> --stats        指定對話統計（不呼叫 claude）
        """
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--all', action='store_true', help='分析所有對話')
    group.add_argument('-c', '--conversation', help='指定對話 UUID')
    group.add_argument('--stats', action='store_true', help='僅輸出全域統計（不呼叫 claude）')

    parser.add_argument('--dry-run', action='store_true', help='乾跑模式')
    parser.add_argument('--skip-claude', action='store_true', help='跳過 claude -p 改進評估')

    args = parser.parse_args()

    conn = _get_db_connection()
    try:
        if args.stats:
            global_stats = collect_error_stats(conn)
            print(json.dumps(global_stats, ensure_ascii=False, indent=2))
        elif args.conversation:
            analyze_conversation(conn, args.conversation, args.dry_run, args.skip_claude)
        else:
            analyze_all(conn, args.dry_run, args.skip_claude)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
