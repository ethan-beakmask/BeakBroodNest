#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest 復盤系統 - P2 語意摘要器 (Codex CLI 版本)

從 PostgreSQL conversation_turns 表讀取 P1 訊號，
將鄰近訊號合併為主題 (topic)，擷取上下文後呼叫 codex exec 產生結構化摘要。

本檔是 scripts/semantic_summarizer.py 的獨立 Codex 變體：
  - 不呼叫 claude -p
  - 不偵測 ~/.claude session jsonl
  - 不覆蓋舊 Claude 版本
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db_importer import _get_db_connection
from semantic_summarizer import (
    CONTEXT_MAX_TURNS,
    CONTEXT_RADIUS,
    DEFAULT_SINCE_DAYS,
    MAX_RETRIES,
    TOPIC_GAP_THRESHOLD,
    check_conversation_p2_complete,
    extract_topic_context,
    get_signal_turns,
    group_signals_into_topics,
    maybe_mark_discard,
    record_p2_failure,
    update_topic_results,
    validate_summary,
)


# ============================================================
# 常數
# ============================================================

REPO_ROOT = Path('/opt/BeakBroodNest')

# Codex 預設模型：此環境已實測 gpt-5.5 可用；若帳號支援更便宜/快速模型，
# 可用 BBN_P2_CODEX_MODEL 覆蓋，例：BBN_P2_CODEX_MODEL=<model>。
MODEL_DEFAULT_CODEX = os.environ.get('BBN_P2_CODEX_MODEL', 'gpt-5.5')
MODEL_FALLBACK_CODEX = os.environ.get('BBN_P2_CODEX_MODEL', 'gpt-5.5')

# codex exec 超時（秒）
CODEX_TIMEOUT = 180


# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT_TEMPLATE_CODEX = """\
你是 BeakBroodNest 復盤系統的語意摘要器。你的唯一任務是對一段 Claude Code 對話中的「高訊號片段」產出結構化 JSON 摘要。

## 硬性輸出規則

1. 最終回覆只能是一個 JSON object。
2. 不要輸出 markdown、不要輸出 ```json、不要輸出說明文字、不要輸出前言或後記。
3. JSON 必須包含下列必要欄位：
   topic_id, title, signals_included, goal, process, stuck_point, resolution, outcome, confidence, confidence_note
4. goal/process/outcome 必須都是 object，且都必須包含 text 與 evidence。
5. confidence 必須是 0.0 到 1.0 之間的數值。

## 內容規則

1. 只依據提供的對話內容作答，不要從你的訓練資料推測。
2. 每個 evidence 必須標記為 [OBSERVED Tn] 或 [INFERRED]：
   - OBSERVED：直接引用對話中的內容，Tn 是 turn 序號
   - INFERRED：根據上下文推論，必須附 inference_basis 說明依據
3. 如果片段被截斷導致資訊不完整，在 confidence_note 中說明。
4. 不要虛構不在片段中的錯誤訊息、檔案路徑或 commit hash。
5. 若片段實際上無卡關（訊號為誤報），仍產出摘要但 stuck_point.text 設為 null，confidence 設為 0.3 以下，confidence_note 說明「訊號為誤報」。

## 必須輸出的 JSON schema 形狀

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
  "confidence": 0.0,
  "confidence_note": "影響可信度的因素說明"
}
"""

MAIN_PROMPT_TEMPLATE_CODEX = """\
[CC-LAUNCH-KIND=p2-dispatcher-codex]
請對以下 topic 產出結構化摘要。

topic_id: {topic_id}
包含的訊號: {signal_ids}
對話專案: {project_path}

請再次確認：最終回覆只能是符合指定 schema 的單一 JSON object，不能有其他文字。
"""


# ============================================================
# Context 擷取 + Prompt 組裝
# ============================================================

def build_prompt_files(
    topic: Dict[str, Any],
    context_text: str,
) -> Tuple[str, str]:
    """
    組裝 codex exec 的 main prompt 和 context file。

    Returns:
        (main_prompt, context_file_path)
        context_file_path 為暫存檔路徑，呼叫者負責清理。
    """
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

    context_content = (
        f'{SYSTEM_PROMPT_TEMPLATE_CODEX}\n\n'
        f'---\n\n'
        f'## 對話片段 (topic {topic["topic_id"]})\n\n'
        f'專案: {topic["project_path"]}\n'
        f'Turn 範圍: T{topic["seq_min"]} ~ T{topic["seq_max"]}\n'
        f'訊號數: {topic["signal_count"]}\n\n'
        f'{signal_summary}\n\n'
        f'## 對話內容\n\n'
        f'{context_text}\n'
    )

    ctx_file = tempfile.NamedTemporaryFile(
        mode='w', prefix=f'p2-codex-ctx-{topic["topic_id"]}-',
        suffix='.md', dir='/tmp', delete=False, encoding='utf-8',
    )
    ctx_file.write(context_content)
    ctx_file.close()

    main_prompt = MAIN_PROMPT_TEMPLATE_CODEX.format(
        topic_id=topic['topic_id'],
        signal_ids=', '.join(topic['signal_ids']),
        project_path=topic['project_path'],
    )

    return main_prompt, ctx_file.name


# ============================================================
# codex exec 執行 + 驗證
# ============================================================

def select_model(topic: Dict[str, Any]) -> str:
    """依 topic 嚴重度和訊號數選擇 Codex 模型。"""
    if topic['max_severity'] == 'high' and topic['signal_count'] >= 2:
        return MODEL_DEFAULT_CODEX
    if topic['max_severity'] == 'high':
        return MODEL_DEFAULT_CODEX
    return MODEL_FALLBACK_CODEX


def _compose_codex_prompt(main_prompt: str, context_file: str) -> str:
    with open(context_file, 'r', encoding='utf-8') as f:
        context = f.read()
    return (
        f'{main_prompt}\n\n'
        f'以下是本次任務的完整規則與對話 context。不要讀取其他檔案，不要執行 shell 指令；'
        f'只根據這段 context 產出最終 JSON。\n\n'
        f'{context}\n\n'
        f'最終回覆只能是一個 JSON object，第一個字元必須是 {{，最後一個字元必須是 }}。\n'
    )


def run_codex_summarize(
    main_prompt: str,
    context_file: str,
    model: str = MODEL_DEFAULT_CODEX,
    timeout: int = CODEX_TIMEOUT,
) -> Tuple[Optional[str], Optional[str]]:
    """
    呼叫 codex exec 產生摘要。

    用 Popen + start_new_session=True 把 codex CLI 開到獨立 process group，
    timeout 後對整個 group 發 SIGKILL，避免 grandchild 殘留。

    Returns:
        (output_text, error_message)
    """
    full_prompt = _compose_codex_prompt(main_prompt, context_file)
    out_file = tempfile.NamedTemporaryFile(
        mode='w', prefix='p2-codex-out-', suffix='.txt',
        dir='/tmp', delete=False, encoding='utf-8',
    )
    out_path = out_file.name
    out_file.close()

    cmd = [
        'codex', 'exec',
        '--sandbox', 'read-only',
        '--skip-git-repo-check',
        '-C', str(REPO_ROOT),
        '-o', out_path,
        '-m', model,
        '-',
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except FileNotFoundError:
        _safe_unlink(out_path)
        return None, 'codex CLI not found in PATH'

    timed_out = False
    stdout, stderr = '', ''
    try:
        stdout, stderr = proc.communicate(input=full_prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    output_text = ''
    try:
        with open(out_path, 'r', encoding='utf-8') as f:
            output_text = f.read()
    except OSError:
        output_text = stdout or ''
    finally:
        _safe_unlink(out_path)

    if timed_out:
        return None, f'codex exec timeout ({timeout}s)'
    if proc.returncode != 0:
        err = (stderr or stdout or '')[:1000]
        return None, f'codex exec exit code {proc.returncode}: {err}'
    if not output_text.strip():
        return None, 'codex exec produced empty final message'
    return output_text, None


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
        print(f'[P2-CODEX] {topic_id}: T{topic["seq_min"]}~T{topic["seq_max"]} '
              f'({topic["signal_count"]} signals, {topic["max_severity"]})',
              file=sys.stderr)

    context_text = extract_topic_context(conn, topic, CONTEXT_RADIUS, CONTEXT_MAX_TURNS)
    if verbose:
        print(f'[P2-CODEX] {topic_id}: context {len(context_text)} chars', file=sys.stderr)

    main_prompt, ctx_file = build_prompt_files(topic, context_text)

    if dry_run:
        print(f'[DRY-RUN] {topic_id}: would call codex exec', file=sys.stderr)
        print(f'  context file: {ctx_file}', file=sys.stderr)
        print(f'  model: {select_model(topic)}', file=sys.stderr)
        return {
            'topic_id': topic_id,
            'status': 'dry_run',
            'context_file': ctx_file,
            'context_chars': len(context_text),
        }

    model = select_model(topic)
    if verbose:
        print(f'[P2-CODEX] {topic_id}: calling codex exec (model={model})',
              file=sys.stderr)

    raw_output, error = run_codex_summarize(main_prompt, ctx_file, model)

    if error:
        _safe_unlink(ctx_file)
        kind = 'codex_timeout' if 'timeout' in error else 'codex_error'
        return {
            'topic_id': topic_id,
            'status': 'error',
            'failure_kind': kind,
            'error': error,
            'model': model,
            'raw_output': raw_output or '',
        }

    summary, validation_error = validate_summary(raw_output)

    if validation_error and MAX_RETRIES > 0:
        if verbose:
            print(f'[P2-CODEX] {topic_id}: validation failed: {validation_error}, retrying',
                  file=sys.stderr)
        retry_model = MODEL_DEFAULT_CODEX
        raw_output2, error2 = run_codex_summarize(main_prompt, ctx_file, retry_model)
        if error2:
            _safe_unlink(ctx_file)
            kind = 'codex_timeout' if 'timeout' in error2 else 'codex_error'
            return {
                'topic_id': topic_id,
                'status': 'error',
                'failure_kind': kind,
                'error': f'retry failed: {error2}',
                'first_error': validation_error,
                'model': retry_model,
                'raw_output': raw_output or '',
            }
        summary, validation_error = validate_summary(raw_output2)
        raw_output = raw_output2
        model = retry_model

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
        }

    _safe_unlink(ctx_file)

    return {
        'topic_id': topic_id,
        'status': 'ok',
        'summary': summary,
        'model': model,
    }


def _safe_unlink(path: str) -> None:
    """安全刪除檔案。"""
    try:
        os.unlink(path)
    except OSError:
        pass


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
    執行 P2 語意摘要 pipeline (Codex CLI 版本)。
    """
    conn = _get_db_connection()
    results = []

    try:
        signal_turns = get_signal_turns(
            conn, conversation_id,
            only_unsummarized=not rescan,
            skip_subagents=skip_subagents,
            since_days=since_days,
        )

        if not signal_turns:
            print('[P2-CODEX] 無待處理的訊號 turns', file=sys.stderr)
            return results

        print(f'[P2-CODEX] 找到 {len(signal_turns)} 個訊號 turns', file=sys.stderr)

        topics = group_signals_into_topics(signal_turns, gap_threshold)
        total_topics = len(topics)
        print(f'[P2-CODEX] 分群為 {total_topics} 個 topics', file=sys.stderr)

        if batch_size and batch_size > 0 and len(topics) > batch_size:
            topics = topics[:batch_size]
            print(f'[P2-CODEX] batch_size={batch_size}，本次處理前 {len(topics)} 個 '
                  f'(剩 {total_topics - len(topics)} 個待後續批次)', file=sys.stderr)

        if verbose:
            for t in topics:
                print(f'  {t["topic_id"]}: T{t["seq_min"]}~T{t["seq_max"]} '
                      f'({t["signal_count"]} signals, {t["max_severity"]})',
                      file=sys.stderr)

        for i, topic in enumerate(topics, 1):
            print(f'\n[P2-CODEX] [{i}/{len(topics)}] {topic["topic_id"]}',
                  file=sys.stderr)

            result = summarize_topic(conn, topic, dry_run=dry_run, verbose=verbose)
            results.append(result)

            if result['status'] == 'ok' and not dry_run:
                update_topic_results(conn, topic, result)
                if verbose:
                    conf = result['summary'].get('confidence', '?')
                    title = result['summary'].get('title', '?')
                    print(f'[P2-CODEX] {topic["topic_id"]}: {title} '
                          f'(confidence={conf})', file=sys.stderr)

            elif result['status'] == 'error' and not dry_run:
                print(f'[P2-CODEX] {topic["topic_id"]}: ERROR - {result.get("error", "?")}',
                      file=sys.stderr)
                try:
                    record_p2_failure(conn, topic, result)
                    discarded = maybe_mark_discard(conn, topic['conversation_id'])
                    if discarded:
                        print(f'[P2-CODEX] {topic["topic_id"]}: conversation {topic["conversation_id"][:12]}... '
                              f'累積失敗過多，標記 discard', file=sys.stderr)
                except Exception as e:
                    print(f'[P2-CODEX] {topic["topic_id"]}: 記錄 p2_failures 失敗: {e}',
                          file=sys.stderr)
                    conn.rollback()

            elif result['status'] == 'validation_failed' and not dry_run:
                print(f'[P2-CODEX] {topic["topic_id"]}: VALIDATION FAILED - '
                      f'{result.get("error", "?")}', file=sys.stderr)
                try:
                    record_p2_failure(conn, topic, result)
                    discarded = maybe_mark_discard(conn, topic['conversation_id'])
                    if discarded:
                        print(f'[P2-CODEX] {topic["topic_id"]}: conversation {topic["conversation_id"][:12]}... '
                              f'累積失敗過多，標記 discard', file=sys.stderr)
                except Exception as e:
                    print(f'[P2-CODEX] {topic["topic_id"]}: 記錄 p2_failures 失敗: {e}',
                          file=sys.stderr)
                    conn.rollback()

        if not dry_run:
            conv_ids = set(t['conversation_id'] for t in topics)
            for cid in conv_ids:
                if check_conversation_p2_complete(conn, cid):
                    print(f'[P2-CODEX] 對話 {cid[:12]}... P2 完成', file=sys.stderr)

        return results

    finally:
        conn.close()


def print_results_summary(results: List[Dict[str, Any]]) -> None:
    """印出結果摘要。"""
    total = len(results)
    ok = sum(1 for r in results if r['status'] == 'ok')
    errors = sum(1 for r in results if r['status'] == 'error')
    failed = sum(1 for r in results if r['status'] == 'validation_failed')
    dry = sum(1 for r in results if r['status'] == 'dry_run')

    print(f'\n{"=" * 60}', file=sys.stderr)
    print('P2 語意摘要完成 (Codex)', file=sys.stderr)
    print(f'  Topics: {total}', file=sys.stderr)
    if dry:
        print(f'  Dry-run: {dry}', file=sys.stderr)
    else:
        print(f'  成功: {ok}', file=sys.stderr)
        if errors:
            print(f'  錯誤: {errors}', file=sys.stderr)
        if failed:
            print(f'  驗證失敗: {failed}', file=sys.stderr)

    if ok > 0:
        print('\n  摘要結果:', file=sys.stderr)
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
        description='BeakBroodNest P2 語意摘要器 (Codex CLI 版本)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python semantic_summarizer_codex.py --all                          處理所有未摘要的訊號
  python semantic_summarizer_codex.py -c <uuid>                      處理指定對話
  python semantic_summarizer_codex.py --all --dry-run                乾跑，只組裝 prompt 不呼叫 codex
  python semantic_summarizer_codex.py --all --rescan                 忽略已摘要的，強制重新處理
  python semantic_summarizer_codex.py --all --json                   輸出 JSON 結果到 stdout
  python semantic_summarizer_codex.py --all --gap 50                 調整主題分群間距
  python semantic_summarizer_codex.py --all --skip-subagents         排除 sub-agent 對話
  python semantic_summarizer_codex.py --all --since-days 7           只處理近 7 天的對話
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
                        help='乾跑模式：組裝 prompt 但不呼叫 codex exec')
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

    if args.json:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2,
                  default=str)
        print()

    print_results_summary(results)


if __name__ == '__main__':
    main()
