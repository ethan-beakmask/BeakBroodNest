#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest 復盤系統 - P2 語意摘要器

從 PostgreSQL conversation_turns 表讀取 P1 訊號，
將鄰近訊號合併為主題 (topic)，擷取上下文後呼叫 claude -p 產生結構化摘要。

資料流：
  conversation_turns (p1_signals IS NOT NULL, p2_summarized_at IS NULL)
    -> 主題分群 (turn_seq 鄰近合併)
    -> Context 擷取 (前後 N turns)
    -> claude -p --append-system-prompt-file (摘要生成)
    -> JSON 驗證
    -> 回寫 p2_topic_id / p2_summarized_at

由 signal_scanner.py / signal_scanner_db.py 的 P1 產出驅動。
不可獨立執行（需 db_importer 的 DB 連線）。
"""

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 從 db_importer 復用 DB 連線
from db_importer import _load_db_params, _get_db_connection


# ============================================================
# 常數
# ============================================================

# 主題分群：兩個訊號 turn_seq 差距小於此值時合併為同一 topic
TOPIC_GAP_THRESHOLD = 10

# Context 擷取：每個 topic 向前/向後擴展的 turn 數
CONTEXT_RADIUS = 30

# Context 上限：單一 topic 最多取多少 turns
CONTEXT_MAX_TURNS = 120

# 摘要模型選擇
MODEL_DEFAULT = 'sonnet'
MODEL_FALLBACK = 'haiku'

# claude -p 超時（秒）
CLAUDE_TIMEOUT = 180

# JSON 重試次數（0 = 不重試，失敗只記入 p2_failures）
MAX_RETRIES = 0

# 預設 since_days（0 = 不限，>0 = 僅處理 last_timestamp 在 N 天內的對話）
DEFAULT_SINCE_DAYS = 0


# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT_TEMPLATE = """\
你是 BeakBroodNest 復盤系統的語意摘要器。你的任務是對一段 Claude Code 對話中的「高訊號片段」產出結構化摘要。

## 嚴格規則

1. **只依據提供的對話內容作答**，不要從你的訓練資料推測。
2. 每個欄位的 evidence 必須標記為 [OBSERVED Tn] 或 [INFERRED]：
   - OBSERVED：直接引用對話中的內容，Tn 是 turn 序號
   - INFERRED：根據上下文推論，必須附 inference_basis 說明依據
3. 如果片段被截斷導致資訊不完整，在 confidence_note 中說明。
4. **不要虛構**不在片段中的錯誤訊息、檔案路徑或 commit hash。

## 輸出格式

只輸出一個 JSON 物件，不要加 markdown 包裝（不要 ```json）。格式如下：

{
  "topic_id": "由我提供的 topic_id",
  "title": "簡短標題（20 字以內）",
  "signals_included": ["訊號 ID 列表"],
  "goal": {
    "text": "這段對話在做什麼",
    "evidence": "[OBSERVED Tn] 或 [INFERRED] + 引用"
  },
  "process": {
    "text": "執行過程概述",
    "evidence": "[OBSERVED Tn] 引用關鍵步驟"
  },
  "stuck_point": {
    "text": "卡關點描述（若無卡關寫 null）",
    "evidence": "引用",
    "error_type": "runtime_error | build_error | design_error | config_error | none"
  },
  "resolution": {
    "text": "如何解決（或未解決）",
    "evidence": "引用",
    "resolution_type": "fixed | workaround | unresolved | not_applicable"
  },
  "outcome": {
    "text": "最終結果",
    "evidence": "引用"
  },
  "confidence": 0.0 到 1.0 之間的數值,
  "confidence_note": "影響可信度的因素說明"
}

若此片段實際上無卡關（訊號為誤報），仍產出摘要但 stuck_point.text 設為 null，
confidence_note 說明「訊號為誤報」，confidence 設為 0.3 以下。
"""

MAIN_PROMPT_TEMPLATE = """\
[CC-LAUNCH-KIND=p2-dispatcher]
請對以下 topic 產出結構化摘要。

topic_id: {topic_id}
包含的訊號: {signal_ids}
對話專案: {project_path}
"""


# ============================================================
# DB 查詢
# ============================================================

def get_signal_turns(conn, conversation_id: str = None,
                     only_unsummarized: bool = True,
                     skip_subagents: bool = False,
                     since_days: int = 0) -> List[Dict[str, Any]]:
    """取得含 P1 訊號的 turns。

    skip_subagents=True 時排除 jsonl_path 在 /subagents/ 子目錄下的對話。
    since_days>0 時只取 conversations.last_timestamp 在近 N 天內的。
    skip_analysis IS NOT NULL 的對話一律排除（pipeline/discard/no_analyze）。
    """
    conditions = [
        "ct.p1_signals IS NOT NULL",
        "ct.conversation_id NOT IN (SELECT id FROM conversations WHERE skip_analysis IS NOT NULL)",
    ]
    params: list = []

    if conversation_id:
        conditions.append("ct.conversation_id = %s")
        params.append(conversation_id)

    if only_unsummarized:
        conditions.append("ct.p2_summarized_at IS NULL")

    if skip_subagents:
        conditions.append(
            "ct.conversation_id NOT IN ("
            "SELECT id FROM conversations WHERE jsonl_path LIKE %s"
            ")"
        )
        params.append('%/subagents/%')

    if since_days and since_days > 0:
        conditions.append(
            "ct.conversation_id IN ("
            "SELECT id FROM conversations "
            "WHERE last_timestamp >= NOW() - make_interval(days => %s)"
            ")"
        )
        params.append(since_days)

    where = " AND ".join(conditions)

    with conn.cursor() as cur:
        cur.execute(f"""
            SELECT ct.id, ct.conversation_id, ct.turn_seq, ct.role,
                   ct.p1_signals, ct.project_path
            FROM conversation_turns ct
            WHERE {where}
            ORDER BY ct.conversation_id, ct.turn_seq
        """, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_context_turns(conn, conversation_id: str,
                      seq_start: int, seq_end: int) -> List[Dict[str, Any]]:
    """取得指定 turn_seq 範圍內的完整 turns（含 content）"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT ct.id, ct.turn_seq, ct.role, ct.timestamp,
                   ct.content, ct.tool_name, ct.tool_is_error,
                   ct.files_touched, ct.has_thinking, ct.thinking_text,
                   ct.is_sidechain, ct.model
            FROM conversation_turns ct
            WHERE ct.conversation_id = %s
              AND ct.turn_seq BETWEEN %s AND %s
            ORDER BY ct.turn_seq
        """, (conversation_id, seq_start, seq_end))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_conversation_info(conn, conversation_id: str) -> Optional[Dict]:
    """取得對話基本資訊"""
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
# 主題分群
# ============================================================

def group_signals_into_topics(
    signal_turns: List[Dict[str, Any]],
    gap_threshold: int = TOPIC_GAP_THRESHOLD,
) -> List[Dict[str, Any]]:
    """
    將同一對話內的訊號 turns 依 turn_seq 鄰近度分群為 topics。

    Returns:
        [
            {
                'topic_id': 'T001',
                'conversation_id': uuid,
                'project_path': str,
                'signal_turns': [turn_dict, ...],
                'seq_min': int,
                'seq_max': int,
                'signal_ids': ['S001', ...],
                'max_severity': 'high' | 'medium' | 'low',
                'signal_count': int,
            },
            ...
        ]
    """
    if not signal_turns:
        return []

    # 按 conversation_id 分組
    by_conv: Dict[str, List[Dict]] = defaultdict(list)
    for turn in signal_turns:
        cid = str(turn['conversation_id'])
        by_conv[cid].append(turn)

    all_topics = []
    topic_counter = 0

    for conv_id, turns in by_conv.items():
        turns.sort(key=lambda t: t['turn_seq'])

        # 貪心合併：turn_seq 差 < gap_threshold 就合併
        groups: List[List[Dict]] = []
        current_group: List[Dict] = [turns[0]]

        for i in range(1, len(turns)):
            gap = turns[i]['turn_seq'] - turns[i - 1]['turn_seq']
            if gap <= gap_threshold:
                current_group.append(turns[i])
            else:
                groups.append(current_group)
                current_group = [turns[i]]
        groups.append(current_group)

        # 轉為 topic dict
        for group in groups:
            topic_counter += 1
            topic_id = f'T{topic_counter:03d}'

            # 收集所有 signal IDs
            signal_ids = []
            max_severity = 'low'
            severity_rank = {'high': 3, 'medium': 2, 'low': 1}

            for turn in group:
                signals = turn.get('p1_signals') or []
                if isinstance(signals, str):
                    signals = json.loads(signals)
                for sig in signals:
                    sid = f"S{turn['turn_seq']:04d}"
                    if sid not in signal_ids:
                        signal_ids.append(sid)
                    sev = sig.get('severity', 'low')
                    if severity_rank.get(sev, 0) > severity_rank.get(max_severity, 0):
                        max_severity = sev

            all_topics.append({
                'topic_id': topic_id,
                'conversation_id': conv_id,
                'project_path': group[0].get('project_path', ''),
                'signal_turns': group,
                'seq_min': group[0]['turn_seq'],
                'seq_max': group[-1]['turn_seq'],
                'signal_ids': signal_ids,
                'max_severity': max_severity,
                'signal_count': len(signal_ids),
            })

    return all_topics


# ============================================================
# Context 擷取 + Prompt 組裝
# ============================================================

def extract_topic_context(
    conn,
    topic: Dict[str, Any],
    radius: int = CONTEXT_RADIUS,
    max_turns: int = CONTEXT_MAX_TURNS,
) -> str:
    """
    擷取 topic 周圍的 turns 並格式化為文本。

    格式：每行以 T{turn_seq} | {role} | 開頭，讓 LLM 可引用 turn 序號。
    """
    seq_start = max(0, topic['seq_min'] - radius)
    seq_end = topic['seq_max'] + radius

    turns = get_context_turns(
        conn, topic['conversation_id'], seq_start, seq_end,
    )

    # 若超過 max_turns，從兩端等比例裁切
    if len(turns) > max_turns:
        # 保留訊號 turns 的核心範圍，裁切兩端
        center_start = topic['seq_min']
        center_end = topic['seq_max']
        # 找出核心 turns 的索引
        core_indices = [
            i for i, t in enumerate(turns)
            if center_start <= t['turn_seq'] <= center_end
        ]
        if core_indices:
            core_start_idx = core_indices[0]
            core_end_idx = core_indices[-1]
            # 核心前後各分配剩餘空間
            core_count = core_end_idx - core_start_idx + 1
            remaining = max_turns - core_count
            before = remaining // 2
            after = remaining - before
            start_idx = max(0, core_start_idx - before)
            end_idx = min(len(turns), core_end_idx + 1 + after)
            turns = turns[start_idx:end_idx]

    # 格式化
    lines = []
    signal_seqs = {t['turn_seq'] for t in topic['signal_turns']}

    for turn in turns:
        seq = turn['turn_seq']
        role = turn['role']
        marker = ' *SIGNAL*' if seq in signal_seqs else ''

        # 角色標記
        if role == 'user':
            role_label = 'USER'
        elif role == 'assistant':
            role_label = 'CLAUDE'
        elif role == 'tool_use':
            tool_name = turn.get('tool_name') or '?'
            role_label = f'TOOL_CALL:{tool_name}'
        elif role == 'tool_result':
            is_err = turn.get('tool_is_error')
            role_label = 'TOOL_ERROR' if is_err else 'TOOL_RESULT'
        else:
            role_label = role.upper()

        # 時間戳
        ts = turn.get('timestamp')
        ts_str = ts.strftime('%H:%M:%S') if ts else ''

        header = f'T{seq} | {role_label} | {ts_str}{marker}'
        lines.append(header)

        # Content（截斷過長的內容）
        content = turn.get('content') or ''
        if len(content) > 3000:
            content = content[:2800] + f'\n[...truncated, total {len(content)} chars]'
        if content.strip():
            lines.append(content.strip())

        # Thinking（如有，摘要前 500 字）
        if turn.get('has_thinking') and turn.get('thinking_text'):
            thinking = turn['thinking_text']
            if len(thinking) > 500:
                thinking = thinking[:480] + '...[truncated]'
            lines.append(f'[THINKING] {thinking}')

        lines.append('---')

    return '\n'.join(lines)


def build_prompt_files(
    topic: Dict[str, Any],
    context_text: str,
) -> Tuple[str, str]:
    """
    組裝 claude -p 的 prompt 和 context file。

    Returns:
        (main_prompt, context_file_path)
        context_file_path 為暫存檔路徑，呼叫者負責清理。
    """
    # 訊號摘要（放進 context 檔案）
    signal_summary_lines = ['## 訊號列表\n']
    for turn in topic['signal_turns']:
        signals = turn.get('p1_signals') or []
        if isinstance(signals, str):
            signals = json.loads(signals)
        for sig in signals:
            signal_summary_lines.append(
                f"- T{turn['turn_seq']} | type={sig['type']} | "
                f"severity={sig['severity']} | trigger={sig.get('trigger', '')}"
            )
    signal_summary = '\n'.join(signal_summary_lines)

    # Context 檔案內容（system prompt + 對話片段）
    context_content = (
        f'{SYSTEM_PROMPT_TEMPLATE}\n\n'
        f'---\n\n'
        f'## 對話片段 (topic {topic["topic_id"]})\n\n'
        f'專案: {topic["project_path"]}\n'
        f'Turn 範圍: T{topic["seq_min"]} ~ T{topic["seq_max"]}\n'
        f'訊號數: {topic["signal_count"]}\n\n'
        f'{signal_summary}\n\n'
        f'## 對話內容\n\n'
        f'{context_text}\n'
    )

    # 寫入暫存檔
    ctx_file = tempfile.NamedTemporaryFile(
        mode='w', prefix=f'p2-ctx-{topic["topic_id"]}-',
        suffix='.md', dir='/tmp', delete=False, encoding='utf-8',
    )
    ctx_file.write(context_content)
    ctx_file.close()

    # 主 prompt
    main_prompt = MAIN_PROMPT_TEMPLATE.format(
        topic_id=topic['topic_id'],
        signal_ids=', '.join(topic['signal_ids']),
        project_path=topic['project_path'],
    )

    return main_prompt, ctx_file.name


# ============================================================
# claude -p 執行 + 驗證
# ============================================================

def select_model(topic: Dict[str, Any]) -> str:
    """依 topic 嚴重度和訊號數選擇模型"""
    if topic['max_severity'] == 'high' and topic['signal_count'] >= 2:
        return MODEL_DEFAULT  # sonnet
    if topic['max_severity'] == 'high':
        return MODEL_DEFAULT
    return MODEL_FALLBACK  # haiku


def run_claude_summarize(
    main_prompt: str,
    context_file: str,
    model: str = MODEL_DEFAULT,
    timeout: int = CLAUDE_TIMEOUT,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    呼叫 claude -p 產生摘要。

    用 Popen + start_new_session=True 把 claude CLI 開到獨立 process group，
    timeout 後對整個 group 發 SIGKILL，避免 grandchild 殘留 (claude CLI
    會 fork 出 node child，subprocess.run 的 timeout 只會殺直接子行程)。

    Returns:
        (output_text, error_message, new_conversation_uuid)
        new_conversation_uuid 為此次 claude -p 產生的 session UUID（可能為 None）
    """
    import glob as _glob

    # 執行前快照 claude project 目錄，用來識別新建的 session jsonl
    project_dir = Path.home() / '.claude' / 'projects' / '-opt-BeakBroodNest'
    try:
        before_files = set(project_dir.glob('*.jsonl'))
    except Exception:
        before_files = set()

    cmd = [
        'claude', '-p', main_prompt,
        '--append-system-prompt-file', context_file,
        '--output-format', 'text',
        '--model', model,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError:
        return None, 'claude CLI not found in PATH', None

    def _detect_new_conv_uuid() -> Optional[str]:
        # claude CLI 啟動後即建立 jsonl 並寫入 user_message，無論 timeout 或正常結束
        # 都應掃描；timeout 情境下這個 jsonl 是半成品（沒 assistant），需要被 mark 為 pipeline
        try:
            after_files = set(project_dir.glob('*.jsonl'))
            new_files = after_files - before_files
            if new_files:
                return new_files.pop().stem
        except Exception:
            pass
        return None

    timed_out = False
    stdout, stderr = '', ''
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    new_conv_uuid = _detect_new_conv_uuid()

    if timed_out:
        return None, f'claude -p timeout ({timeout}s)', new_conv_uuid
    if proc.returncode != 0:
        return None, f'claude -p exit code {proc.returncode}: {(stderr or "")[:500]}', new_conv_uuid
    return stdout, None, new_conv_uuid


def _extract_json_object(text: str) -> Optional[str]:
    """從混合文本中提取第一個完整的 JSON object。

    claude -p 可能因全域 CLAUDE.md 指令在 JSON 前後加上說明文字，
    需要找到第一個 { 到對應的 } 之間的完整 JSON。
    """
    # 先嘗試 markdown 區塊提取
    md_match = re.search(r'```(?:json)?\s*\n(\{.*?\})\s*\n```', text, re.DOTALL)
    if md_match:
        return md_match.group(1)

    # 找第一個 { 和最後一個 } 的配對
    start = text.find('{')
    if start == -1:
        return None

    # 從 start 開始追蹤大括號配對
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


def validate_summary(raw_output: str) -> Tuple[Optional[Dict], str]:
    """
    驗證 claude -p 的 JSON 輸出。

    支援從混合文本（含 CLAUDE.md 格式頭、markdown 包裝、尾部說明）中提取 JSON。

    Returns:
        (parsed_dict, error_message)
        error_message 為空字串表示驗證通過。
    """
    json_text = _extract_json_object(raw_output)
    if not json_text:
        return None, f'找不到 JSON object（輸出長度 {len(raw_output)}）'

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        return None, f'JSON 解析失敗: {e}'

    if not isinstance(data, dict):
        return None, f'預期 JSON object，得到 {type(data).__name__}'

    # 必要欄位檢查
    required_fields = ['topic_id', 'title', 'goal', 'process',
                       'stuck_point', 'resolution', 'outcome', 'confidence']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return None, f'缺少欄位: {", ".join(missing)}'

    # confidence 範圍檢查
    conf = data.get('confidence')
    if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
        return None, f'confidence 值無效: {conf}'

    # 子欄位檢查（每個主要欄位必須有 text + evidence）
    for field in ['goal', 'process', 'outcome']:
        sub = data.get(field, {})
        if not isinstance(sub, dict):
            return None, f'{field} 應為 object'
        if 'text' not in sub or 'evidence' not in sub:
            return None, f'{field} 缺少 text 或 evidence'

    return data, ''


def summarize_topic(
    conn,
    topic: Dict[str, Any],
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    對單一 topic 執行完整的 P2 摘要流程。

    Returns:
        結果 dict，含 topic_id, status, summary 或 error
    """
    topic_id = topic['topic_id']

    if verbose:
        print(f'[P2] {topic_id}: T{topic["seq_min"]}~T{topic["seq_max"]} '
              f'({topic["signal_count"]} signals, {topic["max_severity"]})',
              file=sys.stderr)

    # 1. 擷取 context
    context_text = extract_topic_context(conn, topic)
    if verbose:
        print(f'[P2] {topic_id}: context {len(context_text)} chars', file=sys.stderr)

    # 2. 組裝 prompt
    main_prompt, ctx_file = build_prompt_files(topic, context_text)

    if dry_run:
        print(f'[DRY-RUN] {topic_id}: would call claude -p', file=sys.stderr)
        print(f'  context file: {ctx_file}', file=sys.stderr)
        print(f'  model: {select_model(topic)}', file=sys.stderr)
        return {
            'topic_id': topic_id,
            'status': 'dry_run',
            'context_file': ctx_file,
            'context_chars': len(context_text),
        }

    # 3. 呼叫 claude -p
    model = select_model(topic)
    if verbose:
        print(f'[P2] {topic_id}: calling claude -p (model={model})', file=sys.stderr)

    raw_output, error, new_conv_uuid = run_claude_summarize(main_prompt, ctx_file, model)

    if error:
        _safe_unlink(ctx_file)
        kind = 'claude_timeout' if 'timeout' in error else 'claude_error'
        return {
            'topic_id': topic_id,
            'status': 'error',
            'failure_kind': kind,
            'error': error,
            'model': model,
            'raw_output': '',
            'pipeline_conv_uuid': new_conv_uuid,
        }

    # 4. 驗證 JSON
    summary, validation_error = validate_summary(raw_output)

    if validation_error and MAX_RETRIES > 0:
        if verbose:
            print(f'[P2] {topic_id}: validation failed: {validation_error}, retrying',
                  file=sys.stderr)
        retry_model = MODEL_DEFAULT  # 強制升 sonnet
        raw_output2, error2, new_conv_uuid2 = run_claude_summarize(main_prompt, ctx_file, retry_model)
        if error2:
            _safe_unlink(ctx_file)
            kind = 'claude_timeout' if 'timeout' in error2 else 'claude_error'
            return {
                'topic_id': topic_id,
                'status': 'error',
                'failure_kind': kind,
                'error': f'retry failed: {error2}',
                'first_error': validation_error,
                'model': retry_model,
                'raw_output': raw_output or '',
                'pipeline_conv_uuid': new_conv_uuid2 or new_conv_uuid,
            }
        summary, validation_error = validate_summary(raw_output2)
        raw_output = raw_output2
        model = retry_model
        new_conv_uuid = new_conv_uuid2 or new_conv_uuid

    if validation_error:
        _safe_unlink(ctx_file)
        kind = 'json_missing' if '找不到 JSON' in validation_error else 'validation_failed'
        return {
            'topic_id': topic_id,
            'status': 'validation_failed',
            'failure_kind': kind,
            'error': validation_error,
            'raw_output': raw_output or '',
            'model': model,
            'pipeline_conv_uuid': new_conv_uuid,
        }

    # 清理暫存檔
    _safe_unlink(ctx_file)

    return {
        'topic_id': topic_id,
        'status': 'ok',
        'summary': summary,
        'model': model,
        'pipeline_conv_uuid': new_conv_uuid,
    }


def _safe_unlink(path: str) -> None:
    """安全刪除檔案"""
    try:
        os.unlink(path)
    except OSError:
        pass


# ============================================================
# DB 回寫
# ============================================================

def update_topic_results(
    conn,
    topic: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """將 P2 結果回寫到 conversation_turns"""
    now = datetime.now().astimezone()
    topic_id = topic['topic_id']

    # 取得此 topic 涵蓋的所有 turn IDs
    turn_ids = [t['id'] for t in topic['signal_turns']]

    with conn.cursor() as cur:
        # 更新所有相關 turns 的 p2_topic_id 和 p2_summarized_at
        cur.execute("""
            UPDATE conversation_turns
            SET p2_topic_id = %s,
                p2_summarized_at = %s
            WHERE id = ANY(%s)
        """, (topic_id, now, turn_ids))

    conn.commit()


def mark_pipeline_session(conn, conv_uuid: Optional[str]) -> None:
    """將 P2 claude -p 自動產生的 session 標記為 pipeline，阻止被 P1/P2 再次分析。"""
    if not conv_uuid:
        return
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE conversations SET skip_analysis = 'pipeline'
            WHERE id = %s AND skip_analysis IS NULL
        """, (conv_uuid,))
    conn.commit()


def maybe_mark_discard(conn, conversation_id: str, threshold: int = 3) -> bool:
    """同一 conversation 累積 p2_failures 達 threshold 次時標記為 discard。
    回傳 True 表示已標記。"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) FROM p2_failures WHERE conversation_id = %s
        """, (conversation_id,))
        count = cur.fetchone()[0]
    if count >= threshold:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE conversations SET skip_analysis = 'discard'
                WHERE id = %s AND skip_analysis IS NULL
            """, (conversation_id,))
        conn.commit()
        return True
    return False


def record_p2_failure(
    conn,
    topic: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """寫入 p2_failures 表，供事後人工檢視/重跑。

    raw_output 截到 64KB，避免單筆過大。
    """
    raw = (result.get('raw_output') or '')[:65536]
    err_msg = (result.get('error') or '')[:4000]
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO p2_failures
                (topic_id, conversation_id, seq_min, seq_max,
                 signal_count, max_severity, failure_kind,
                 error_message, raw_output, model, failed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            topic['topic_id'],
            topic['conversation_id'],
            topic['seq_min'],
            topic['seq_max'],
            topic['signal_count'],
            topic['max_severity'],
            result.get('failure_kind', ''),
            err_msg,
            raw,
            result.get('model', ''),
        ))
    conn.commit()


def check_conversation_p2_complete(conn, conversation_id: str) -> bool:
    """檢查對話的所有訊號 turns 是否都已 P2 處理完成"""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM conversation_turns
            WHERE conversation_id = %s
              AND p1_signals IS NOT NULL
              AND p2_summarized_at IS NULL
        """, (conversation_id,))
        remaining = cur.fetchone()[0]

    if remaining == 0:
        now = datetime.now().astimezone()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE conversations
                SET p2_completed_at = %s
                WHERE id = %s
            """, (now, conversation_id))
        conn.commit()
        return True
    return False


# ============================================================
# 主流程
# ============================================================

def run_p2_pipeline(
    conversation_id: str = None,
    rescan: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    gap_threshold: int = TOPIC_GAP_THRESHOLD,
    skip_subagents: bool = False,
    since_days: int = 0,
    batch_size: int = 0,
) -> List[Dict[str, Any]]:
    """
    執行 P2 語意摘要 pipeline。

    Args:
        conversation_id: 指定對話 UUID，None 則處理所有未摘要的
        rescan: True 忽略已摘要的 turns，強制重新處理
        dry_run: True 只組裝 prompt 不呼叫 claude
        verbose: 詳細輸出
        gap_threshold: 主題分群的 turn_seq 間距閾值
        skip_subagents: 排除 sub-agent 對話 (jsonl_path 含 /subagents/)
        since_days: 只處理 last_timestamp 在近 N 天內的對話 (0=不限)
        batch_size: 單次最多處理 N 個 topics (0=不限)，給 systemd timer 接力用

    Returns:
        每個 topic 的處理結果 list
    """
    conn = _get_db_connection()
    results = []

    try:
        # 1. 取得訊號 turns
        signal_turns = get_signal_turns(
            conn, conversation_id,
            only_unsummarized=not rescan,
            skip_subagents=skip_subagents,
            since_days=since_days,
        )

        if not signal_turns:
            print('[P2] 無待處理的訊號 turns', file=sys.stderr)
            return results

        print(f'[P2] 找到 {len(signal_turns)} 個訊號 turns', file=sys.stderr)

        # 2. 主題分群
        topics = group_signals_into_topics(signal_turns, gap_threshold)
        total_topics = len(topics)
        print(f'[P2] 分群為 {total_topics} 個 topics', file=sys.stderr)

        # batch_size 限制：取前 N 個（後續 timer 觸發時會跑下一批，因為已處理者
        # p2_summarized_at 已寫入而被 only_unsummarized 排除）
        if batch_size and batch_size > 0 and len(topics) > batch_size:
            topics = topics[:batch_size]
            print(f'[P2] batch_size={batch_size}，本次處理前 {len(topics)} 個 '
                  f'(剩 {total_topics - len(topics)} 個待後續批次)', file=sys.stderr)

        if verbose:
            for t in topics:
                print(f'  {t["topic_id"]}: T{t["seq_min"]}~T{t["seq_max"]} '
                      f'({t["signal_count"]} signals, {t["max_severity"]})',
                      file=sys.stderr)

        # 3. 串行處理每個 topic
        for i, topic in enumerate(topics, 1):
            print(f'\n[P2] [{i}/{len(topics)}] {topic["topic_id"]}',
                  file=sys.stderr)

            result = summarize_topic(conn, topic, dry_run=dry_run, verbose=verbose)
            results.append(result)

            # 每次 claude -p 結束後，立即標記新建的 pipeline session，阻止 P1/P2 再掃
            if not dry_run:
                mark_pipeline_session(conn, result.get('pipeline_conv_uuid'))

            # 4. 依結果回寫 DB
            if result['status'] == 'ok' and not dry_run:
                update_topic_results(conn, topic, result)
                if verbose:
                    conf = result['summary'].get('confidence', '?')
                    title = result['summary'].get('title', '?')
                    print(f'[P2] {topic["topic_id"]}: {title} '
                          f'(confidence={conf})', file=sys.stderr)

            elif result['status'] == 'error' and not dry_run:
                print(f'[P2] {topic["topic_id"]}: ERROR - {result.get("error", "?")}',
                      file=sys.stderr)
                try:
                    record_p2_failure(conn, topic, result)
                    discarded = maybe_mark_discard(conn, topic['conversation_id'])
                    if discarded:
                        print(f'[P2] {topic["topic_id"]}: conversation {topic["conversation_id"][:12]}... '
                              f'累積失敗過多，標記 discard', file=sys.stderr)
                except Exception as e:
                    print(f'[P2] {topic["topic_id"]}: 記錄 p2_failures 失敗: {e}',
                          file=sys.stderr)
                    conn.rollback()

            elif result['status'] == 'validation_failed' and not dry_run:
                print(f'[P2] {topic["topic_id"]}: VALIDATION FAILED - '
                      f'{result.get("error", "?")}', file=sys.stderr)
                try:
                    record_p2_failure(conn, topic, result)
                    discarded = maybe_mark_discard(conn, topic['conversation_id'])
                    if discarded:
                        print(f'[P2] {topic["topic_id"]}: conversation {topic["conversation_id"][:12]}... '
                              f'累積失敗過多，標記 discard', file=sys.stderr)
                except Exception as e:
                    print(f'[P2] {topic["topic_id"]}: 記錄 p2_failures 失敗: {e}',
                          file=sys.stderr)
                    conn.rollback()

        # 5. 檢查對話是否全部完成
        if not dry_run:
            conv_ids = set(t['conversation_id'] for t in topics)
            for cid in conv_ids:
                if check_conversation_p2_complete(conn, cid):
                    print(f'[P2] 對話 {cid[:12]}... P2 完成', file=sys.stderr)

        return results

    finally:
        conn.close()


def print_results_summary(results: List[Dict[str, Any]]) -> None:
    """印出結果摘要"""
    total = len(results)
    ok = sum(1 for r in results if r['status'] == 'ok')
    errors = sum(1 for r in results if r['status'] == 'error')
    failed = sum(1 for r in results if r['status'] == 'validation_failed')
    dry = sum(1 for r in results if r['status'] == 'dry_run')

    print(f'\n{"=" * 60}', file=sys.stderr)
    print(f'P2 語意摘要完成', file=sys.stderr)
    print(f'  Topics: {total}', file=sys.stderr)
    if dry:
        print(f'  Dry-run: {dry}', file=sys.stderr)
    else:
        print(f'  成功: {ok}', file=sys.stderr)
        if errors:
            print(f'  錯誤: {errors}', file=sys.stderr)
        if failed:
            print(f'  驗證失敗: {failed}', file=sys.stderr)

    # 印出成功的摘要標題和 confidence
    if ok > 0:
        print(f'\n  摘要結果:', file=sys.stderr)
        for r in results:
            if r['status'] == 'ok' and 'summary' in r:
                s = r['summary']
                print(f'    {s.get("topic_id", "?")} | '
                      f'{s.get("title", "?")} | '
                      f'confidence={s.get("confidence", "?")}',
                      file=sys.stderr)

    print(f'{"=" * 60}', file=sys.stderr)


# ============================================================
# CLI
# ============================================================

def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest P2 語意摘要器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python semantic_summarizer.py --all                          處理所有未摘要的訊號
  python semantic_summarizer.py -c <uuid>                      處理指定對話
  python semantic_summarizer.py --all --dry-run                乾跑，只組裝 prompt 不呼叫 claude
  python semantic_summarizer.py --all --rescan                 忽略已摘要的，強制重新處理
  python semantic_summarizer.py --all --json                   輸出 JSON 結果到 stdout
  python semantic_summarizer.py --all --gap 50                 調整主題分群間距
  python semantic_summarizer.py --all --skip-subagents         排除 sub-agent 對話
  python semantic_summarizer.py --all --since-days 7           只處理近 7 天的對話
        """
    )

    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--all', action='store_true',
                        help='處理所有未摘要的訊號 turns')
    target.add_argument('-c', '--conversation', type=str, metavar='UUID',
                        help='指定對話 UUID')

    parser.add_argument('--rescan', action='store_true',
                        help='忽略已摘要的 turns，強制重新處理')
    parser.add_argument('--dry-run', action='store_true',
                        help='乾跑模式：組裝 prompt 但不呼叫 claude -p')
    parser.add_argument('--json', action='store_true',
                        help='輸出 JSON 結果到 stdout')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='詳細輸出')
    parser.add_argument('--gap', type=int, default=TOPIC_GAP_THRESHOLD,
                        metavar='N',
                        help=f'主題分群 turn_seq 間距閾值 (預設: {TOPIC_GAP_THRESHOLD})')
    parser.add_argument('--skip-subagents', action='store_true',
                        help='排除 sub-agent 對話 (jsonl_path 含 /subagents/)')
    parser.add_argument('--since-days', type=int, default=DEFAULT_SINCE_DAYS,
                        metavar='N',
                        help='只處理 last_timestamp 在近 N 天內的對話 (預設 0=不限)')
    parser.add_argument('--batch-size', type=int, default=0, metavar='N',
                        help='單次最多處理 N 個 topics (0=不限)，給 systemd timer 接力用')

    return parser


def main():
    parser = create_argument_parser()

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    conversation_id = args.conversation if hasattr(args, 'conversation') else None

    results = run_p2_pipeline(
        conversation_id=conversation_id,
        rescan=args.rescan,
        dry_run=args.dry_run,
        verbose=args.verbose,
        gap_threshold=args.gap,
        skip_subagents=args.skip_subagents,
        since_days=args.since_days,
        batch_size=args.batch_size,
    )

    # JSON 輸出
    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2,
                  default=str)
        print()

    # 摘要輸出
    print_results_summary(results)


if __name__ == '__main__':
    main()
