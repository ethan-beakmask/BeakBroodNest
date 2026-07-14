#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest 復盤系統 - 事件驅動 pipeline listener

常駐 process，透過 PostgreSQL LISTEN/NOTIFY 監聽 conversation_turns 新資料
（trigger 見 init_pipeline_notify.sql），收到通知並 debounce 後依序執行：

  P1  signal_scanner.py --db          掃描新 turns 產生 p1_signals
  P2  依 config.ini [pipeline] summarizer 選擇 claude / codex 版摘要器
      （主要摘要器失敗時退 summarizer_fallback）

取代舊的 p1_scan_frequent（每 10 分鐘輪詢）與 beakbroodnest-p2-codex.timer
（每 30 分鐘輪詢）：模型呼叫只在真的有新資料時發生。

事件鏈：
  P0（scheduler 每 10 分鐘 db_importer -convertall）
    -> INSERT conversation_turns
    -> DB trigger pg_notify('bbn_new_turns')
    -> 本 listener debounce 後跑 P1 + P2

nightly_pipeline.py 保留為每日兜底全量掃描；P2 執行期間持有
/tmp/beak-p2.lock 與 nightly 及舊 timer 互斥。

由 systemd/beakbroodnest-listener.service 管理。
"""

import argparse
import configparser
import os
import select
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPT_DIR.parent
VENV_PY = str(BASE_DIR / 'venv' / 'bin' / 'python')
CONFIG_PATH = str(BASE_DIR / 'config.ini')

sys.path.insert(0, str(SCRIPT_DIR))
from db_importer import _load_db_params  # noqa: E402

# ============================================================
# 常數
# ============================================================

NOTIFY_CHANNEL = 'bbn_new_turns'
P2_LOCK_FILE = '/tmp/beak-p2.lock'

LOG_PATH = '/opt/tmp/scripts-pipeline_listener.log'
HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_FILE = os.path.join(HEARTBEAT_DIR, 'pipeline_listener.ok')

# 預設值（可由 config.ini [pipeline] 覆蓋）
DEFAULT_SUMMARIZER = 'codex'
DEFAULT_SUMMARIZER_FALLBACK = ''          # 空字串 = 不做 failover
DEFAULT_DEBOUNCE_SECONDS = 60             # 收到 notify 後靜默 N 秒才開跑
DEFAULT_MIN_INTERVAL_SECONDS = 300        # 兩輪 cycle 的最小間隔

# P1/P2 逾時與 P2 參數（與 p2_daemon_run*.sh、nightly_pipeline.py 對齊）
P1_TIMEOUT = 600
P2_TIMEOUT = 2700
P2_ARGS = ['--all', '--skip-subagents', '--since-days', '14',
           '--gap', '50', '--batch-size', '15']

SUMMARIZER_SCRIPTS = {
    'claude': str(SCRIPT_DIR / 'semantic_summarizer.py'),
    'codex': str(SCRIPT_DIR / 'semantic_summarizer_codex.py'),
}


# ============================================================
# 工具
# ============================================================

def _log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [listener] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def _write_heartbeat() -> None:
    try:
        os.makedirs(HEARTBEAT_DIR, exist_ok=True)
        Path(HEARTBEAT_FILE).write_text(
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'), encoding='utf-8')
    except OSError:
        pass


def _load_listener_config() -> dict:
    """讀取 config.ini [pipeline] 的 listener 相關設定"""
    cfg = configparser.RawConfigParser()
    cfg.read(CONFIG_PATH, encoding='utf-8')
    get = lambda key, fb: cfg.get('pipeline', key, fallback=fb) \
        if cfg.has_section('pipeline') else fb
    conf = {
        'summarizer': get('summarizer', DEFAULT_SUMMARIZER).strip().lower(),
        'fallback': get('summarizer_fallback', DEFAULT_SUMMARIZER_FALLBACK).strip().lower(),
        'debounce': int(get('listener_debounce_seconds', str(DEFAULT_DEBOUNCE_SECONDS))),
        'min_interval': int(get('listener_min_interval_seconds', str(DEFAULT_MIN_INTERVAL_SECONDS))),
    }
    if conf['summarizer'] not in SUMMARIZER_SCRIPTS:
        _log(f"[WARN] 未知 summarizer '{conf['summarizer']}'，改用預設 {DEFAULT_SUMMARIZER}")
        conf['summarizer'] = DEFAULT_SUMMARIZER
    if conf['fallback'] and conf['fallback'] not in SUMMARIZER_SCRIPTS:
        _log(f"[WARN] 未知 summarizer_fallback '{conf['fallback']}'，停用 failover")
        conf['fallback'] = ''
    if conf['fallback'] == conf['summarizer']:
        conf['fallback'] = ''
    return conf


def _run_cmd(name: str, cmd: list, timeout: int) -> int:
    """執行子命令，回傳 exit code（timeout / 例外回 -1）"""
    _log(f"[{name}] start: {' '.join(cmd)}")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        rc = proc.returncode
        tail = (proc.stderr or proc.stdout or '')[-500:].strip()
    except subprocess.TimeoutExpired:
        rc, tail = -1, f'timeout after {timeout}s'
    except Exception as e:
        rc, tail = -1, repr(e)
    elapsed = round(time.time() - t0, 1)
    if rc == 0:
        _log(f"[{name}] ok ({elapsed}s)")
    else:
        _log(f"[{name}] failed rc={rc} ({elapsed}s): {tail}")
    return rc


# ============================================================
# Pipeline cycle
# ============================================================

def run_cycle(conf: dict) -> bool:
    """跑一輪 P1 + P2。回傳整輪是否成功。"""
    ok = True

    # P1：訊號掃描（輕量，直接跑）
    rc = _run_cmd('P1', [VENV_PY, str(SCRIPT_DIR / 'signal_scanner.py'), '--db'],
                  P1_TIMEOUT)
    if rc != 0:
        ok = False

    # P2：語意摘要（flock 與 nightly / 舊 timer 互斥；-E 0 取不到鎖視為跳過）
    def p2_cmd(kind: str) -> list:
        return ['/usr/bin/flock', '-E', '0', '-n', P2_LOCK_FILE,
                VENV_PY, SUMMARIZER_SCRIPTS[kind]] + P2_ARGS

    rc = _run_cmd(f"P2:{conf['summarizer']}", p2_cmd(conf['summarizer']), P2_TIMEOUT)
    if rc != 0 and conf['fallback']:
        _log(f"[P2] 主要摘要器 {conf['summarizer']} 失敗，failover -> {conf['fallback']}")
        rc = _run_cmd(f"P2:{conf['fallback']}", p2_cmd(conf['fallback']), P2_TIMEOUT)
    if rc != 0:
        ok = False

    if ok:
        _write_heartbeat()
    return ok


# ============================================================
# LISTEN/NOTIFY 主迴圈
# ============================================================

def listen_loop(conf: dict) -> None:
    import psycopg2
    import psycopg2.extensions

    params = _load_db_params()
    while True:
        try:
            conn = psycopg2.connect(
                host=params['host'], port=params['port'],
                dbname=params['database'], user=params['user'],
                password=params['password'],
            )
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            with conn.cursor() as cur:
                cur.execute(f'LISTEN {NOTIFY_CHANNEL};')
            _log(f"已連線並 LISTEN {NOTIFY_CHANNEL} "
                 f"(summarizer={conf['summarizer']}"
                 f"{', fallback=' + conf['fallback'] if conf['fallback'] else ''}, "
                 f"debounce={conf['debounce']}s, min_interval={conf['min_interval']}s)")

            pending_since = None      # 第一次收到 notify 的時間（等 debounce）
            last_notify = None        # 最近一次收到 notify 的時間
            last_cycle_end = 0.0

            while True:
                # 等待 notify（最多 5 秒醒來檢查 debounce 條件）
                if select.select([conn], [], [], 5) != ([], [], []):
                    conn.poll()
                    if conn.notifies:
                        conn.notifies.clear()
                        now = time.time()
                        last_notify = now
                        if pending_since is None:
                            pending_since = now
                            _log('收到 NOTIFY，進入 debounce 等待')

                if pending_since is None:
                    continue

                now = time.time()
                quiet_enough = (now - last_notify) >= conf['debounce']
                interval_ok = (now - last_cycle_end) >= conf['min_interval']
                if quiet_enough and interval_ok:
                    pending_since = None
                    run_cycle(conf)
                    last_cycle_end = time.time()

        except KeyboardInterrupt:
            _log('收到中斷，結束')
            return
        except Exception as e:
            _log(f"[ERROR] 連線/監聽異常: {e!r}，30 秒後重連")
            time.sleep(30)
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================
# 主程式
# ============================================================

USAGE_TEXT = """BeakBroodNest 事件驅動 pipeline listener

透過 PostgreSQL LISTEN/NOTIFY 監聽 conversation_turns 新資料，
debounce 後執行 P1 訊號掃描 + P2 語意摘要（模型依 config.ini 選擇）。

用法:
  {prog} --run       常駐監聽（由 systemd beakbroodnest-listener.service 啟動）
  {prog} --once      立即跑一輪 P1+P2 後結束（測試用，不監聽）

設定（config.ini [pipeline]）:
  summarizer                    = codex | claude（預設 codex）
  summarizer_fallback           = 主要摘要器失敗時的退路（預設空 = 不 failover）
  listener_debounce_seconds     = 收到通知後靜默 N 秒才開跑（預設 60）
  listener_min_interval_seconds = 兩輪之間最小間隔（預設 300）

前置需求:
  psql -f scripts/init_pipeline_notify.sql  建立 NOTIFY trigger
"""


def main():
    prog = os.path.basename(sys.argv[0])
    if len(sys.argv) == 1:
        print(USAGE_TEXT.format(prog=prog))
        sys.exit(0)

    parser = argparse.ArgumentParser(description='BeakBroodNest 事件驅動 pipeline listener')
    parser.add_argument('--run', action='store_true', help='常駐監聽 NOTIFY')
    parser.add_argument('--once', action='store_true', help='立即跑一輪後結束（測試用）')
    args = parser.parse_args()

    conf = _load_listener_config()

    if args.once:
        ok = run_cycle(conf)
        sys.exit(0 if ok else 1)

    if args.run:
        listen_loop(conf)
        sys.exit(0)

    print(USAGE_TEXT.format(prog=prog))
    sys.exit(1)


if __name__ == '__main__':
    main()
