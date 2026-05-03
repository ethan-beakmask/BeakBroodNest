#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BeakBroodNest 復盤 Pipeline -- 集中執行 P0~P3。

由 scheduler 每天 08:25 觸發（cron 表達式 25 8 * * *，因 scheduler 每 5 分鐘 tick，
無法精確命中 08:22；08:25 是離 08:22 最近且對齊 5 分鐘的時刻）。

階段：
  P0  db_importer.py -convertall            匯入新 jsonl 到 conversations / conversation_turns
  P1  signal_scanner.py --db                掃描 P0 寫入的 turns（更新 p1_signals）
  P2  semantic_summarizer.py --all          產生 topic 摘要（呼叫 claude -p）
  P3  review_analyzer.py --all --skip-claude  全域統計 + 個別對話 review（先不呼叫 claude）

每階段：
  - 計時、記 stdout/stderr 至 log
  - 失敗 → 標記 status=failed、不中斷後續階段（避免 P0 fail 卡住 P3 統計）
  - 寫入 pipeline_runs 表（task A 已實作後生效）

完成後：
  - 寫 heartbeat /opt/tmp/heartbeat/nightly_pipeline.ok
  - 印一行摘要到 stdout
"""
import argparse
import datetime
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
VENV_PY = str(BASE_DIR / 'venv' / 'bin' / 'python')
LOG_PATH = '/opt/tmp/scripts-nightly_pipeline.log'
HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_FILE = os.path.join(HEARTBEAT_DIR, 'nightly_pipeline.ok')


def _setup_logger():
    logger = logging.getLogger('nightly_pipeline')
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    fh = logging.FileHandler(LOG_PATH, encoding='utf-8')
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def _write_heartbeat():
    os.makedirs(HEARTBEAT_DIR, exist_ok=True)
    Path(HEARTBEAT_FILE).write_text(
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        encoding='utf-8',
    )


def _run_stage(logger, name, cmd, timeout):
    """執行單一階段，回傳 dict(name, status, started_at, completed_at, duration_s, exit_code, stdout_tail, stderr_tail)"""
    started = datetime.datetime.now()
    t0 = time.time()
    logger.info(f'[{name}] start: {" ".join(cmd)}')
    result = {
        'name': name,
        'started_at': started.isoformat(),
        'status': 'running',
    }
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        result['exit_code'] = proc.returncode
        result['stdout_tail'] = (proc.stdout or '')[-2000:]
        result['stderr_tail'] = (proc.stderr or '')[-2000:]
        result['status'] = 'completed' if proc.returncode == 0 else 'failed'
    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
        result['exit_code'] = -1
        result['stdout_tail'] = ''
        result['stderr_tail'] = f'timeout after {timeout}s'
    except Exception as e:
        result['status'] = 'error'
        result['exit_code'] = -1
        result['stdout_tail'] = ''
        result['stderr_tail'] = repr(e)

    completed = datetime.datetime.now()
    result['completed_at'] = completed.isoformat()
    result['duration_s'] = round(time.time() - t0, 1)
    msg = f'[{name}] {result["status"]} exit={result["exit_code"]} duration={result["duration_s"]}s'
    if result['status'] == 'completed':
        logger.info(msg)
    else:
        logger.warning(msg)
        if result['stderr_tail']:
            logger.warning(f'[{name}] stderr_tail: {result["stderr_tail"][:500]}')
    return result


def _record_pipeline_run(stages, overall_status, error_detail=''):
    """寫入 pipeline_runs 表（task A 階段使用）。失敗不影響流程。"""
    try:
        sys.path.insert(0, str(BASE_DIR))
        from sqlalchemy import text
        from core.db import init_engine, get_engine
        init_engine(str(BASE_DIR / 'config.ini'))
        engine = get_engine()
        stages_json = json.dumps(stages, ensure_ascii=False, default=str)
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO pipeline_runs
                    (pipeline_name, trigger_type, stages, current_stage, status,
                     started_at, completed_at, error_detail)
                VALUES
                    ('nightly_review', 'cron', CAST(:stages AS JSONB), '', :status,
                     :started, :completed, :err)
            """), {
                'stages': stages_json,
                'status': overall_status,
                'started': stages[0]['started_at'] if stages else datetime.datetime.now().isoformat(),
                'completed': datetime.datetime.now().isoformat(),
                'err': error_detail or '',
            })
    except Exception as e:
        # 寫入失敗不要阻斷主流程
        logging.getLogger('nightly_pipeline').warning(f'write pipeline_runs failed: {e}')


def main():
    parser = argparse.ArgumentParser(description='BeakBroodNest 每日復盤 Pipeline')
    parser.add_argument('--dry-run', action='store_true', help='印命令但不執行')
    parser.add_argument('--skip', action='append', default=[],
                        choices=['p0', 'p1', 'p2', 'p3'],
                        help='跳過指定階段（可多次）')
    parser.add_argument('--since', type=int, default=7, metavar='DAYS',
                        help='P0 只匯入近 N 天內的 jsonl（預設 7；0=不限/首次補歷史用）')
    parser.add_argument('--p0-limit', type=int, default=0, metavar='N',
                        help='P0 最多處理 N 個檔案（0=不限）')
    args = parser.parse_args()

    logger = _setup_logger()
    logger.info('===== nightly_pipeline 開始 =====')

    p0_cmd = [VENV_PY, str(SCRIPTS_DIR / 'db_importer.py'), '-convertall']
    if args.since > 0:
        p0_cmd += ['--since', str(args.since)]
    if args.p0_limit > 0:
        p0_cmd += ['--limit', str(args.p0_limit)]

    # 與 P2-3 daemon (beakbroodnest-p2.service) 共用 /tmp/beak-p2.lock，
    # 取不到鎖時 flock -E 0 回 exit 0，nightly 把這次 P2 stage 視為 OK 跳過。
    p2_cmd = [
        '/usr/bin/flock', '-E', '0', '-n', '/tmp/beak-p2.lock',
        VENV_PY, str(SCRIPTS_DIR / 'semantic_summarizer.py'),
        '--all',
        '--skip-subagents',
        '--since-days', '7',
        '--gap', '50',
    ]

    stages_def = [
        ('p0_import',   p0_cmd, 1800),
        ('p1_scan',     [VENV_PY, str(SCRIPTS_DIR / 'signal_scanner.py'), '--db'],          600),
        ('p2_summary',  p2_cmd, 7200),
        ('p3_review',   [VENV_PY, str(SCRIPTS_DIR / 'review_analyzer.py'), '--all', '--skip-claude'], 600),
    ]

    skip_keys = {'p0_import' if s == 'p0' else
                 'p1_scan'   if s == 'p1' else
                 'p2_summary' if s == 'p2' else
                 'p3_review'  if s == 'p3' else s
                 for s in args.skip}

    stages = []
    overall_status = 'completed'
    for name, cmd, timeout in stages_def:
        if name in skip_keys:
            logger.info(f'[{name}] skipped')
            stages.append({'name': name, 'status': 'skipped',
                           'started_at': datetime.datetime.now().isoformat(),
                           'completed_at': datetime.datetime.now().isoformat(),
                           'duration_s': 0, 'exit_code': 0,
                           'stdout_tail': '', 'stderr_tail': ''})
            continue
        if args.dry_run:
            logger.info(f'[{name}] DRY-RUN: {" ".join(cmd)}')
            stages.append({'name': name, 'status': 'dry-run',
                           'started_at': datetime.datetime.now().isoformat(),
                           'completed_at': datetime.datetime.now().isoformat(),
                           'duration_s': 0, 'exit_code': 0,
                           'stdout_tail': '', 'stderr_tail': ''})
            continue

        result = _run_stage(logger, name, cmd, timeout)
        stages.append(result)
        if result['status'] != 'completed':
            overall_status = 'failed'
            # 不中斷：P0 失敗時 P3 仍可對舊資料統計

    if not args.dry_run:
        _record_pipeline_run(stages, overall_status)

    _write_heartbeat()
    summary = ' | '.join(f'{s["name"]}={s["status"]}/{s["duration_s"]}s' for s in stages)
    logger.info(f'===== nightly_pipeline 結束 status={overall_status} | {summary} =====')


if __name__ == '__main__':
    main()
