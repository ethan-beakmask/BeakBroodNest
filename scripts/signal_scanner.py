#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex 復盤系統 - 訊號掃描器 (P1 階段)

掃描 P0 產出的結構化 MD 檔案，找出「曾經卡關、出錯、回退、低效」的
高訊號主題位置，供後續 P2 語意摘要聚焦分析。

輸入：P0 產出的 MD 檔案（單檔或目錄）+ 可選 git repo
輸出：JSON 檔案（訊號清單 + git 訊號 + 檔案編輯熱圖）

零外部依賴，僅使用 Python 標準庫。
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 常數
# ============================================================

VERSION = '1.0.0'

# 嚴重度排序權重（越大越嚴重）
SEVERITY_WEIGHT = {
    'high': 3,
    'medium': 2,
    'low': 1,
}

# 上下文摘錄行數
CONTEXT_LINES = 3

# 同一檔案編輯次數門檻（超過此值產生 repeated_edit 訊號）
REPEATED_EDIT_THRESHOLD = 3

# 連續掙扎輪次門檻
LONG_STRUGGLE_THRESHOLD = 5


# ============================================================
# 對話訊號偵測模式
# ============================================================

# 回退語意關鍵字（用戶發言）
ROLLBACK_PATTERNS_ZH = [
    r'不對', r'重來', r'換個方向', r'換個方式', r'試試另一種',
    r'改回', r'還原', r'回退', r'不行', r'放棄這個', r'算了',
    r'這樣不對', r'這不對', r'先不要', r'退回', r'撤銷',
    r'回到之前', r'回到原本', r'恢復', r'不要這樣',
]

ROLLBACK_PATTERNS_EN = [
    r'roll\s*back', r'revert', r'undo', r'go back', r'start over',
    r'try another', r'different approach', r'scratch that',
    r"that'?s not right", r"that'?s wrong", r'never\s*mind',
]

# 重試語意關鍵字（Claude 發言）
RETRY_PATTERNS_ZH = [
    r'讓我重新', r'再試一次', r'之前的方法有問題', r'換個方式',
    r'改用', r'重新嘗試', r'換個思路', r'修正一下',
    r'我之前', r'先前的做法', r'上一個方案',
]

RETRY_PATTERNS_EN = [
    r'let me try again', r'let me redo', r'previous approach.*(?:wrong|issue|problem)',
    r'switch(?:ing)? to', r'instead,?\s+(?:let me|I\'ll)',
    r'that didn\'t work', r'try a different',
]

# 錯誤偵測模式（工具回傳）
ERROR_PATTERNS = [
    r'Traceback \(most recent call last\)',
    r'(?:^|\s)Error:', r'(?:^|\s)ERROR[:\s]',
    r'Exception:', r'EXCEPTION:',
    r'(?:^|\s)failed\b', r'(?:^|\s)FAILED\b',
    r'SyntaxError:', r'TypeError:', r'ValueError:',
    r'NameError:', r'AttributeError:', r'KeyError:',
    r'ImportError:', r'ModuleNotFoundError:',
    r'FileNotFoundError:', r'OSError:',
    r'RuntimeError:', r'ConnectionError:',
    r'PermissionError:', r'IndentationError:',
    r'UnicodeDecodeError:', r'UnicodeEncodeError:',
    r'JSONDecodeError:',
    r'psycopg2\.', r'sqlalchemy\.exc\.',
    r'CalledProcessError',
]

# 需要排除的正常 stderr 輸出（避免誤報）
ERROR_EXCLUDE_PATTERNS = [
    r'DeprecationWarning', r'FutureWarning', r'UserWarning',
    r'PendingDeprecationWarning', r'ResourceWarning',
    r'InsecureRequestWarning',
    r'npm warn', r'npm WARN',
    r'"failed":\s*0',  # API 回傳中 failed: 0 不是錯誤
]

# 工具失敗指標
TOOL_FAILURE_PATTERNS = [
    r'exit code[:\s]+[1-9]\d*',
    r'non-zero exit',
    r'permission denied',
    r'denied',
    r'command not found',
    r'No such file or directory',
    r'not found',
    r'ENOENT',
    r'EACCES',
    r'EPERM',
]


# ============================================================
# 編譯正規表達式（效能考量，只編譯一次）
# ============================================================

def _compile_patterns(patterns: List[str], flags: int = re.IGNORECASE) -> List[re.Pattern]:
    """編譯正規表達式清單"""
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, flags))
        except re.error:
            # 跳過無法編譯的 pattern
            pass
    return compiled


RE_ROLLBACK_ZH = _compile_patterns(ROLLBACK_PATTERNS_ZH, re.IGNORECASE)
RE_ROLLBACK_EN = _compile_patterns(ROLLBACK_PATTERNS_EN, re.IGNORECASE)
RE_RETRY_ZH = _compile_patterns(RETRY_PATTERNS_ZH, re.IGNORECASE)
RE_RETRY_EN = _compile_patterns(RETRY_PATTERNS_EN, re.IGNORECASE)
RE_ERROR = _compile_patterns(ERROR_PATTERNS, re.IGNORECASE)
RE_ERROR_EXCLUDE = _compile_patterns(ERROR_EXCLUDE_PATTERNS, re.IGNORECASE)
RE_TOOL_FAILURE = _compile_patterns(TOOL_FAILURE_PATTERNS, re.IGNORECASE)

# 角色區塊標題的正規表達式
RE_ROLE_HEADER = re.compile(
    r'^### (用戶|Claude|工具回傳|Agent)\s*'
    r'\((\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*(?:UTC)?\)'
)

# 工具呼叫標記
RE_TOOL_CALL = re.compile(
    r'\*\*\[Tool Call\]\*\*\s*`([^`]+)`'
)

# 工具回傳標記
RE_TOOL_RESULT = re.compile(
    r'\*\*\[Tool Result\]\*\*'
)

# 檔案路徑提取 -- 多種格式
# Edit/Read/Write 的 file_path 參數
RE_FILE_PATH_PARAM = re.compile(
    r'(?:file_path|path):\s*(/[^\s\n]+)'
)

# Bash 命令中的絕對路徑
RE_FILE_PATH_BASH = re.compile(
    r'(?:command:\s*.+?)?(/opt/[^\s\'"`;|>&]+|/home/[^\s\'"`;|>&]+|/tmp/[^\s\'"`;|>&]+)'
)

# YAML front matter 的欄位
RE_YAML_FIELD = re.compile(r'^(\w[\w_]*)\s*:\s*(.+)$')


# ============================================================
# YAML Front Matter 解析（簡易版，不依賴 PyYAML）
# ============================================================

def parse_front_matter(lines: List[str]) -> Dict[str, Any]:
    """解析 MD 檔案開頭的 YAML front matter

    Args:
        lines: 檔案所有行

    Returns:
        解析後的 dict（source, project, converted_at, total_messages 等）
    """
    meta = {}
    if not lines or lines[0].rstrip() != '---':
        return meta

    for i, line in enumerate(lines[1:], start=1):
        stripped = line.rstrip()
        if stripped == '---':
            break
        m = RE_YAML_FIELD.match(stripped)
        if m:
            key = m.group(1)
            value = m.group(2).strip()
            # 嘗試轉數字
            if value.isdigit():
                value = int(value)
            elif value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            meta[key] = value

    return meta


# ============================================================
# 區塊解析器
# ============================================================

class Block:
    """代表一個角色區塊（用戶/Claude/工具回傳/Agent）"""

    def __init__(self, role: str, timestamp: str, line_start: int):
        self.role = role            # 用戶/Claude/工具回傳/Agent
        self.timestamp = timestamp  # 原始時間字串
        self.line_start = line_start  # 起始行號（1-based）
        self.line_end = line_start    # 結束行號（1-based）
        self.lines: List[str] = []    # 區塊內容
        self.tool_name: Optional[str] = None   # 如果是工具呼叫區塊
        self.is_tool_call = False
        self.is_tool_result = False

    @property
    def text(self) -> str:
        """合併全部行為文字"""
        return '\n'.join(self.lines)

    def __repr__(self) -> str:
        return f'<Block {self.role} L{self.line_start}-{self.line_end} tool={self.tool_name}>'


def parse_blocks(lines: List[str]) -> List[Block]:
    """將 MD 行切分為角色區塊

    Args:
        lines: 整份 MD 的行（含 front matter）

    Returns:
        Block 物件清單
    """
    blocks: List[Block] = []
    current_block: Optional[Block] = None

    # 跳過 front matter
    in_front_matter = False
    content_start = 0
    if lines and lines[0].rstrip() == '---':
        in_front_matter = True
        for i, line in enumerate(lines[1:], start=1):
            if line.rstrip() == '---':
                content_start = i + 1
                break

    for line_idx in range(content_start, len(lines)):
        line = lines[line_idx]
        line_no = line_idx + 1  # 1-based

        # 檢查是否為新的角色區塊標題
        m = RE_ROLE_HEADER.match(line.rstrip())
        if m:
            # 關閉前一個區塊
            if current_block:
                current_block.line_end = line_no - 1
                blocks.append(current_block)

            role = m.group(1)
            timestamp = m.group(2)
            current_block = Block(role=role, timestamp=timestamp, line_start=line_no)
            continue

        if current_block is None:
            continue

        # 偵測工具呼叫/結果標記
        tc = RE_TOOL_CALL.search(line)
        if tc:
            current_block.is_tool_call = True
            current_block.tool_name = tc.group(1)

        tr = RE_TOOL_RESULT.search(line)
        if tr:
            current_block.is_tool_result = True

        current_block.lines.append(line)

    # 關閉最後一個區塊
    if current_block:
        current_block.line_end = len(lines)
        blocks.append(current_block)

    return blocks


# ============================================================
# 檔案路徑提取
# ============================================================

def extract_file_paths(block: Block) -> List[str]:
    """從區塊中提取檔案路徑

    支援：
    - Edit/Read/Write 的 file_path/path 參數
    - Bash 命令中的絕對路徑（/opt/*, /home/*, /tmp/*）
    """
    paths = set()
    text = block.text

    # file_path: /path/to/file 格式
    for m in RE_FILE_PATH_PARAM.finditer(text):
        p = m.group(1).rstrip(')')
        # 過濾掉非檔案路徑（如 URL）
        if not p.startswith('http') and os.sep in p:
            paths.add(_normalize_path(p))

    # Bash 命令中的路徑
    if block.tool_name == 'Bash' or (block.is_tool_call and 'command:' in text):
        for m in RE_FILE_PATH_BASH.finditer(text):
            p = m.group(1)
            # 過濾掉常見的非檔案路徑
            if _is_likely_file_path(p):
                paths.add(_normalize_path(p))

    return list(paths)


def _normalize_path(path: str) -> str:
    """正規化路徑（移除結尾引號、逗號等雜字元）"""
    # 移除結尾的常見雜字元
    path = path.rstrip('"\',;:)}>]')
    # 移除結尾的 2>&1 等 shell 導向殘留
    path = re.sub(r'\s*2?>&?\d*$', '', path)
    return path


def _is_likely_file_path(path: str) -> bool:
    """判斷是否像檔案路徑（排除命令、選項等）"""
    # 太短不太可能是有意義的檔案路徑
    if len(path) < 5:
        return False
    # 排除常見的命令路徑
    skip_prefixes = (
        '/opt/BeakCortex/venv/',
        '/tmp/heartbeat/',
    )
    for prefix in skip_prefixes:
        if path.startswith(prefix):
            return False
    # 有副檔名或有多層路徑比較可能是檔案
    _, ext = os.path.splitext(path)
    if ext and ext not in ('.', '..'):
        return True
    # 至少兩層路徑
    parts = path.strip('/').split('/')
    return len(parts) >= 2


# ============================================================
# 訊號偵測
# ============================================================

class Signal:
    """一個偵測到的訊號"""

    _counter = 0

    def __init__(self, signal_type: str, severity: str,
                 line_start: int, line_end: int,
                 trigger: str, context_before: str, context_after: str,
                 related_files: Optional[List[str]] = None):
        Signal._counter += 1
        self.id = f'S{Signal._counter:03d}'
        self.type = signal_type
        self.severity = severity
        self.line_start = line_start
        self.line_end = line_end
        self.trigger = trigger
        self.context_before = context_before
        self.context_after = context_after
        self.related_files = related_files or []
        self.git_commits: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'type': self.type,
            'severity': self.severity,
            'line_start': self.line_start,
            'line_end': self.line_end,
            'trigger': self.trigger,
            'context_before': self.context_before,
            'context_after': self.context_after,
            'related_files': self.related_files,
            'git_commits': self.git_commits,
        }


def _get_context(lines: List[str], line_start: int, line_end: int,
                 n: int = CONTEXT_LINES) -> Tuple[str, str]:
    """取得指定範圍前後的上下文

    Args:
        lines: 所有行（0-based 索引）
        line_start: 起始行號（1-based）
        line_end: 結束行號（1-based）
        n: 上下文行數

    Returns:
        (context_before, context_after) 都是字串
    """
    idx_start = line_start - 1  # 轉 0-based
    idx_end = line_end  # line_end 本身是 1-based，做 slice 時直接當上界

    before_start = max(0, idx_start - n)
    before_lines = lines[before_start:idx_start]
    context_before = '\n'.join(l.rstrip() for l in before_lines).strip()

    after_end = min(len(lines), idx_end + n)
    after_lines = lines[idx_end:after_end]
    context_after = '\n'.join(l.rstrip() for l in after_lines).strip()

    return context_before, context_after


def _match_any(text: str, patterns: List[re.Pattern]) -> Optional[str]:
    """嘗試匹配任一模式，回傳觸發的匹配文字或 None"""
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def _is_excluded_error(text: str) -> bool:
    """檢查是否為應排除的正常 stderr 輸出"""
    return _match_any(text, RE_ERROR_EXCLUDE) is not None


def detect_conversation_signals(
    lines: List[str],
    blocks: List[Block],
) -> Tuple[List[Signal], Dict[str, int]]:
    """偵測對話中的各類訊號

    Args:
        lines: 所有行（含 front matter）
        blocks: 已解析的區塊清單

    Returns:
        (signals, file_heatmap)
    """
    Signal._counter = 0  # 重置計數器
    signals: List[Signal] = []
    file_counter: Counter = Counter()

    # 追蹤連續掙扎（同檔案/同錯誤）
    struggle_tracker: Dict[str, int] = defaultdict(int)
    last_struggle_key: Optional[str] = None
    consecutive_struggle = 0
    struggle_start_block: Optional[Block] = None

    for block in blocks:
        text = block.text
        files_in_block = extract_file_paths(block)

        # 更新檔案熱圖
        for f in files_in_block:
            file_counter[f] += 1

        # -------------------------------------------
        # 1. error 訊號（工具回傳中出現 traceback/Error 等）
        # -------------------------------------------
        if block.role == '工具回傳' or block.is_tool_result:
            error_match = _match_any(text, RE_ERROR)
            if error_match and not _is_excluded_error(text):
                ctx_before, ctx_after = _get_context(
                    lines, block.line_start, block.line_end
                )
                signals.append(Signal(
                    signal_type='error',
                    severity='high',
                    line_start=block.line_start,
                    line_end=block.line_end,
                    trigger=_truncate(error_match, 200),
                    context_before=_truncate(ctx_before, 300),
                    context_after=_truncate(ctx_after, 300),
                    related_files=files_in_block,
                ))

                # 追蹤連續掙扎
                struggle_key = error_match[:50]
                if struggle_key == last_struggle_key:
                    consecutive_struggle += 1
                else:
                    # 檢查前一段是否達到門檻
                    _emit_struggle_signal(
                        signals, lines, consecutive_struggle,
                        struggle_start_block, block, last_struggle_key,
                    )
                    last_struggle_key = struggle_key
                    consecutive_struggle = 1
                    struggle_start_block = block

        # -------------------------------------------
        # 2. tool_failure 訊號（工具回傳中出現失敗指標）
        # -------------------------------------------
        if block.role == '工具回傳' or block.is_tool_result:
            failure_match = _match_any(text, RE_TOOL_FAILURE)
            if failure_match:
                ctx_before, ctx_after = _get_context(
                    lines, block.line_start, block.line_end
                )
                signals.append(Signal(
                    signal_type='tool_failure',
                    severity='medium',
                    line_start=block.line_start,
                    line_end=block.line_end,
                    trigger=_truncate(failure_match, 200),
                    context_before=_truncate(ctx_before, 300),
                    context_after=_truncate(ctx_after, 300),
                    related_files=files_in_block,
                ))

        # -------------------------------------------
        # 3. rollback 訊號（用戶發言含回退語意）
        # -------------------------------------------
        if block.role == '用戶':
            rb_zh = _match_any(text, RE_ROLLBACK_ZH)
            rb_en = _match_any(text, RE_ROLLBACK_EN)
            trigger_text = rb_zh or rb_en
            if trigger_text:
                ctx_before, ctx_after = _get_context(
                    lines, block.line_start, block.line_end
                )
                signals.append(Signal(
                    signal_type='rollback',
                    severity='high',
                    line_start=block.line_start,
                    line_end=block.line_end,
                    trigger=_truncate(f'用戶說「{trigger_text}」', 200),
                    context_before=_truncate(ctx_before, 300),
                    context_after=_truncate(ctx_after, 300),
                    related_files=files_in_block,
                ))

        # -------------------------------------------
        # 4. retry 訊號（Claude 發言含重試語意）
        # -------------------------------------------
        if block.role == 'Claude' and not block.is_tool_call:
            rt_zh = _match_any(text, RE_RETRY_ZH)
            rt_en = _match_any(text, RE_RETRY_EN)
            trigger_text = rt_zh or rt_en
            if trigger_text:
                ctx_before, ctx_after = _get_context(
                    lines, block.line_start, block.line_end
                )
                signals.append(Signal(
                    signal_type='retry',
                    severity='high',
                    line_start=block.line_start,
                    line_end=block.line_end,
                    trigger=_truncate(f'Claude 說「{trigger_text}」', 200),
                    context_before=_truncate(ctx_before, 300),
                    context_after=_truncate(ctx_after, 300),
                    related_files=files_in_block,
                ))

        # -------------------------------------------
        # 5. 連續掙扎追蹤（同檔案的工具呼叫）
        # -------------------------------------------
        if block.is_tool_call and files_in_block:
            file_key = ','.join(sorted(files_in_block))
            if file_key == last_struggle_key:
                consecutive_struggle += 1
            else:
                _emit_struggle_signal(
                    signals, lines, consecutive_struggle,
                    struggle_start_block, block, last_struggle_key,
                )
                last_struggle_key = file_key
                consecutive_struggle = 1
                struggle_start_block = block

    # 最後一段掙扎檢查
    if blocks:
        _emit_struggle_signal(
            signals, lines, consecutive_struggle,
            struggle_start_block, blocks[-1], last_struggle_key,
        )

    # -------------------------------------------
    # 6. repeated_edit 訊號（同一檔案出現超過門檻次數）
    # -------------------------------------------
    for filepath, count in file_counter.items():
        if count > REPEATED_EDIT_THRESHOLD:
            signals.append(Signal(
                signal_type='repeated_edit',
                severity='medium',
                line_start=0,
                line_end=0,
                trigger=f'檔案 {filepath} 在對話中被操作 {count} 次（門檻 {REPEATED_EDIT_THRESHOLD}）',
                context_before='',
                context_after='',
                related_files=[filepath],
            ))

    return signals, dict(file_counter)


def _emit_struggle_signal(
    signals: List[Signal],
    lines: List[str],
    consecutive_count: int,
    start_block: Optional[Block],
    end_block: Optional[Block],
    struggle_key: Optional[str],
) -> None:
    """若連續掙扎次數達門檻，發出 long_struggle 訊號"""
    if consecutive_count < LONG_STRUGGLE_THRESHOLD:
        return
    if start_block is None or end_block is None:
        return

    ctx_before, ctx_after = _get_context(
        lines, start_block.line_start, end_block.line_end
    )
    signals.append(Signal(
        signal_type='long_struggle',
        severity='medium',
        line_start=start_block.line_start,
        line_end=end_block.line_end,
        trigger=f'連續 {consecutive_count} 輪針對同一目標: {_truncate(struggle_key or "", 100)}',
        context_before=_truncate(ctx_before, 300),
        context_after=_truncate(ctx_after, 300),
    ))


def _truncate(text: str, max_len: int) -> str:
    """截斷文字"""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + '...'


# ============================================================
# Git 訊號偵測
# ============================================================

class GitSignal:
    """Git 相關訊號"""

    _counter = 0

    def __init__(self, signal_type: str, severity: str,
                 commit_hash: str = '', file: str = '',
                 detail: str = '', amend_count: int = 0):
        GitSignal._counter += 1
        self.id = f'G{GitSignal._counter:03d}'
        self.type = signal_type
        self.severity = severity
        self.commit_hash = commit_hash
        self.file = file
        self.detail = detail
        self.amend_count = amend_count

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            'id': self.id,
            'type': self.type,
            'severity': self.severity,
        }
        if self.commit_hash:
            d['commit_hash'] = self.commit_hash
        if self.file:
            d['file'] = self.file
        if self.amend_count:
            d['amend_count'] = self.amend_count
        if self.detail:
            d['detail'] = self.detail
        return d


def _run_git(repo_path: str, args: List[str],
             timeout: int = 30) -> Optional[str]:
    """執行 git 命令並回傳 stdout

    Args:
        repo_path: git repo 路徑
        args: git 子命令和參數
        timeout: 超時秒數

    Returns:
        stdout 字串，或 None（失敗時）
    """
    cmd = ['git', '-C', repo_path] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def detect_git_signals(
    repo_path: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> List[GitSignal]:
    """掃描 git repo 中的異常訊號

    Args:
        repo_path: git repo 的根目錄
        start_time: 掃描起始時間（ISO 格式）
        end_time: 掃描結束時間（ISO 格式）

    Returns:
        GitSignal 清單
    """
    GitSignal._counter = 0
    signals: List[GitSignal] = []

    # 驗證是否為 git repo
    check = _run_git(repo_path, ['rev-parse', '--is-inside-work-tree'])
    if check is None or check.strip() != 'true':
        return signals

    # 構建時間範圍參數
    time_args = []
    if start_time:
        time_args.extend(['--after', start_time])
    if end_time:
        time_args.extend(['--before', end_time])

    # -------------------------------------------
    # 1. revert 訊號
    # -------------------------------------------
    log_output = _run_git(repo_path, [
        'log', '--oneline', '--grep=revert', '-i',
    ] + time_args)
    if log_output:
        for log_line in log_output.strip().split('\n'):
            if not log_line.strip():
                continue
            parts = log_line.split(None, 1)
            commit_hash = parts[0] if parts else ''
            msg = parts[1] if len(parts) > 1 else ''
            signals.append(GitSignal(
                signal_type='revert',
                severity='high',
                commit_hash=commit_hash,
                detail=msg,
            ))

    # -------------------------------------------
    # 2. repeated_amend 訊號（同一檔案在短時間內被多次 commit）
    # -------------------------------------------
    log_output = _run_git(repo_path, [
        'log', '--format=%H %aI', '--name-only',
    ] + time_args)
    if log_output:
        # 解析 commit 和關聯檔案
        file_commits: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        current_hash = ''
        current_time = ''
        for log_line in log_output.strip().split('\n'):
            log_line = log_line.strip()
            if not log_line:
                continue
            # 格式：hash ISO_timestamp
            parts = log_line.split()
            if len(parts) == 2 and len(parts[0]) == 40:
                current_hash = parts[0][:7]
                current_time = parts[1]
            elif log_line and current_hash:
                # 這是檔案名稱
                file_commits[log_line].append((current_hash, current_time))

        # 檢查每個檔案的 commit 頻率
        for filepath, commits in file_commits.items():
            if len(commits) < 3:
                continue
            # 按時間排序
            commits.sort(key=lambda x: x[1])
            # 檢查是否有一小時內超過 2 次的情況
            for i in range(len(commits)):
                window_commits = []
                try:
                    base_time = datetime.fromisoformat(commits[i][1])
                except (ValueError, TypeError):
                    continue
                for j in range(i, len(commits)):
                    try:
                        cmp_time = datetime.fromisoformat(commits[j][1])
                    except (ValueError, TypeError):
                        continue
                    if (cmp_time - base_time) <= timedelta(hours=1):
                        window_commits.append(commits[j])
                    else:
                        break
                if len(window_commits) > 2:
                    signals.append(GitSignal(
                        signal_type='repeated_amend',
                        severity='medium',
                        commit_hash=window_commits[-1][0],
                        file=filepath,
                        amend_count=len(window_commits),
                    ))
                    break  # 每個檔案只報一次

    # -------------------------------------------
    # 3. force_push 訊號（reflog 中偵測）
    # -------------------------------------------
    reflog_output = _run_git(repo_path, [
        'reflog', '--format=%H %gD %gs',
    ])
    if reflog_output:
        for log_line in reflog_output.strip().split('\n'):
            if 'forced-update' in log_line.lower() or 'force' in log_line.lower():
                parts = log_line.split(None, 1)
                commit_hash = parts[0][:7] if parts else ''
                # 檢查時間範圍（reflog 沒有直接的時間篩選，用 commit 時間近似）
                signals.append(GitSignal(
                    signal_type='force_push',
                    severity='high',
                    commit_hash=commit_hash,
                    detail=log_line.strip(),
                ))

    return signals


# ============================================================
# 對話時間範圍提取
# ============================================================

def extract_conversation_period(blocks: List[Block]) -> Dict[str, str]:
    """從區塊中提取對話的時間範圍

    Returns:
        {'start': '...', 'end': '...'}
    """
    timestamps = []
    for block in blocks:
        if block.timestamp:
            timestamps.append(block.timestamp)
    if not timestamps:
        return {'start': '', 'end': ''}
    return {
        'start': timestamps[0],
        'end': timestamps[-1],
    }


# ============================================================
# 主掃描邏輯
# ============================================================

def scan_md_file(
    md_path: str,
    git_repo: Optional[str] = None,
    min_severity: str = 'low',
) -> Dict[str, Any]:
    """掃描單一 MD 檔案

    Args:
        md_path: MD 檔案路徑
        git_repo: git repo 路徑（可選）
        min_severity: 最低嚴重度過濾

    Returns:
        完整的掃描結果 dict
    """
    md_path = os.path.abspath(md_path)

    # 讀取檔案
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # 解析 front matter
    meta = parse_front_matter(lines)
    project = meta.get('project', '')

    # 解析區塊
    blocks = parse_blocks(lines)

    # 取得對話時間範圍
    period = extract_conversation_period(blocks)

    # 偵測對話訊號
    conv_signals, file_heatmap = detect_conversation_signals(lines, blocks)

    # 偵測 git 訊號
    git_signals: List[GitSignal] = []
    if git_repo:
        git_signals = detect_git_signals(
            git_repo,
            start_time=period.get('start'),
            end_time=period.get('end'),
        )

    # 過濾嚴重度
    min_weight = SEVERITY_WEIGHT.get(min_severity, 0)
    conv_signals = [
        s for s in conv_signals
        if SEVERITY_WEIGHT.get(s.severity, 0) >= min_weight
    ]
    git_signals = [
        s for s in git_signals
        if SEVERITY_WEIGHT.get(s.severity, 0) >= min_weight
    ]

    # 按 severity 排序（高到低）
    conv_signals.sort(
        key=lambda s: SEVERITY_WEIGHT.get(s.severity, 0),
        reverse=True,
    )
    git_signals.sort(
        key=lambda s: SEVERITY_WEIGHT.get(s.severity, 0),
        reverse=True,
    )

    # 檔案熱圖排序（高頻優先）
    sorted_heatmap = dict(
        sorted(file_heatmap.items(), key=lambda x: x[1], reverse=True)
    )

    # 組裝結果
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result = {
        'source_md': md_path,
        'project': project,
        'scan_time': now_str,
        'conversation_period': period,
        'total_signals': len(conv_signals) + len(git_signals),
        'signals': [s.to_dict() for s in conv_signals],
        'git_signals': [s.to_dict() for s in git_signals],
        'file_edit_heatmap': sorted_heatmap,
    }

    return result


def scan_directory(
    dir_path: str,
    git_repo: Optional[str] = None,
    min_severity: str = 'low',
) -> List[Dict[str, Any]]:
    """掃描目錄下所有 MD 檔案

    Args:
        dir_path: 目錄路徑
        git_repo: git repo 路徑（可選）
        min_severity: 最低嚴重度過濾

    Returns:
        每個 MD 檔案的掃描結果 list
    """
    results = []
    md_files = sorted([
        os.path.join(dir_path, f)
        for f in os.listdir(dir_path)
        if f.endswith('.md')
    ])
    if not md_files:
        print(f'[WARN] 目錄 {dir_path} 下沒有 .md 檔案', file=sys.stderr)
        return results

    for md_file in md_files:
        print(f'[INFO] 掃描: {md_file}', file=sys.stderr)
        try:
            result = scan_md_file(md_file, git_repo, min_severity)
            results.append(result)
        except Exception as e:
            print(f'[ERROR] 掃描 {md_file} 失敗: {e}', file=sys.stderr)

    return results


# ============================================================
# 輸出
# ============================================================

def write_output(data: Any, output_path: str) -> None:
    """寫入 JSON 輸出"""
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'[INFO] 輸出: {output_path}', file=sys.stderr)


def print_summary(data: Any) -> None:
    """在 stderr 上印出摘要

    Args:
        data: 單一結果 dict 或結果 list
    """
    if isinstance(data, list):
        total_files = len(data)
        total_signals = sum(r.get('total_signals', 0) for r in data)
        print(f'\n{"=" * 60}', file=sys.stderr)
        print(f'掃描完成: {total_files} 個檔案, 共 {total_signals} 個訊號',
              file=sys.stderr)
        for r in data:
            _print_single_summary(r)
    else:
        _print_single_summary(data)


def _print_single_summary(result: Dict[str, Any]) -> None:
    """印出單一檔案的掃描摘要"""
    source = result.get('source_md', '')
    total = result.get('total_signals', 0)
    signals = result.get('signals', [])
    git_signals = result.get('git_signals', [])
    heatmap = result.get('file_edit_heatmap', {})

    print(f'\n{"=" * 60}', file=sys.stderr)
    print(f'來源: {os.path.basename(source)}', file=sys.stderr)
    print(f'訊號總數: {total}', file=sys.stderr)

    # 類型分布
    type_counter: Counter = Counter()
    for s in signals:
        type_counter[s['type']] += 1
    for s in git_signals:
        type_counter[f"git:{s['type']}"] += 1

    if type_counter:
        print(f'\n訊號類型分布:', file=sys.stderr)
        for stype, count in type_counter.most_common():
            print(f'  {stype}: {count}', file=sys.stderr)

    # 嚴重度分布
    sev_counter: Counter = Counter()
    for s in signals + git_signals:
        sev_counter[s['severity']] += 1
    if sev_counter:
        print(f'\n嚴重度分布:', file=sys.stderr)
        for sev in ('high', 'medium', 'low'):
            if sev in sev_counter:
                print(f'  {sev}: {sev_counter[sev]}', file=sys.stderr)

    # 檔案熱圖前 5 名
    if heatmap:
        print(f'\n檔案編輯熱圖 (前 5):', file=sys.stderr)
        for filepath, count in list(heatmap.items())[:5]:
            print(f'  {filepath}: {count}', file=sys.stderr)

    print(f'{"=" * 60}', file=sys.stderr)


# ============================================================
# 使用說明
# ============================================================

USAGE_TEXT = f"""
BeakCortex 復盤系統 - 訊號掃描器 (P1) v{VERSION}
==================================================

掃描 P0 產出的結構化 MD 檔案，找出卡關、出錯、回退、低效的
高訊號主題位置，供後續 P2 語意摘要聚焦分析。

用法:
  signal_scanner.py                              顯示此使用說明
  signal_scanner.py -i <md檔案>                  掃描單一 MD 檔案
  signal_scanner.py -i <目錄>                    掃描目錄下所有 MD 檔案
  signal_scanner.py -i <md檔案> -g <git_repo>   含 git log 掃描
  signal_scanner.py -i <md檔案> -o <output.json> 指定輸出路徑
  signal_scanner.py -i <md檔案> --min-severity medium  只輸出 medium 以上

參數:
  -i, --input          MD 檔案或目錄路徑（必要）
  -o, --output         輸出 JSON 路徑（預設: 輸入檔同名 .signals.json）
  -g, --git-repo       git repo 路徑（可選，掃描對話時段內的 git log）
  --min-severity       最低嚴重度過濾: low / medium / high（預設: low）

訊號類型:
  對話訊號（從 MD 掃描）:
    error           [high]   工具回傳中出現 traceback/Error/Exception/failed
    rollback        [high]   用戶發言含回退語意（不對/重來/換個方向...）
    retry           [high]   Claude 發言含重試語意（讓我重新/再試一次...）
    repeated_edit   [medium] 同一檔案被操作超過 {REPEATED_EDIT_THRESHOLD} 次
    tool_failure    [medium] 工具回傳中出現失敗指標（非零 exit code/denied...）
    long_struggle   [medium] 連續 {LONG_STRUGGLE_THRESHOLD}+ 輪針對同一目標

  Git 訊號（從 git log 掃描）:
    revert          [high]   出現 revert commit
    repeated_amend  [medium] 同一檔案短時間內被多次 commit（>2 次/小時）
    force_push      [high]   reflog 中出現 force push

輸出:
  JSON 檔案，包含 signals（對話訊號）、git_signals（Git 訊號）、
  file_edit_heatmap（檔案編輯熱圖）。
"""


# ============================================================
# CLI 入口
# ============================================================

def main() -> int:
    """主程式入口"""
    # 無參數時顯示使用說明
    if len(sys.argv) == 1:
        print(USAGE_TEXT)
        return 0

    parser = argparse.ArgumentParser(
        description='BeakCortex P1 訊號掃描器',
        add_help=True,
    )
    parser.add_argument(
        '-i', '--input',
        required=True,
        help='MD 檔案或目錄路徑',
    )
    parser.add_argument(
        '-o', '--output',
        default=None,
        help='輸出 JSON 路徑（預設: 輸入檔同名 .signals.json）',
    )
    parser.add_argument(
        '-g', '--git-repo',
        default=None,
        help='git repo 路徑（可選）',
    )
    parser.add_argument(
        '--min-severity',
        choices=['low', 'medium', 'high'],
        default='low',
        help='最低嚴重度過濾（預設: low）',
    )

    args = parser.parse_args()

    input_path = os.path.abspath(args.input)

    # 檢查輸入是否存在
    if not os.path.exists(input_path):
        print(f'[ERROR] 輸入路徑不存在: {input_path}', file=sys.stderr)
        return 1

    # 決定輸出路徑
    output_path = args.output
    is_dir = os.path.isdir(input_path)

    if is_dir:
        # 掃描目錄
        results = scan_directory(
            input_path,
            git_repo=args.git_repo,
            min_severity=args.min_severity,
        )
        if not results:
            print('[WARN] 沒有掃描到任何結果', file=sys.stderr)
            return 0

        if not output_path:
            dir_name = os.path.basename(input_path.rstrip('/'))
            output_path = os.path.join(input_path, f'{dir_name}.signals.json')

        write_output(results, output_path)
        print_summary(results)
    else:
        # 掃描單檔
        result = scan_md_file(
            input_path,
            git_repo=args.git_repo,
            min_severity=args.min_severity,
        )

        if not output_path:
            base, _ = os.path.splitext(input_path)
            output_path = f'{base}.signals.json'

        write_output(result, output_path)
        print_summary(result)

    return 0


if __name__ == '__main__':
    sys.exit(main())
