#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py -- Orchestrator 支線監控 daemon

獨立非 AI 程式，負責:
  1. 輪詢 worker_tasks 偵測逾時與異常
  2. 逾時任務: kill tmux pane + 標記 timeout
  3. 輸出過大: kill tmux pane + 標記 failed (疑似幻覺)
  4. tmux 消失: 標記 failed (process 異常終止)
  5. 批次完成: 透過 notify_windows.py 通知主線

使用方式:
  python monitor.py                    顯示說明
  python monitor.py --start            啟動監控 (前景)
  python monitor.py --once             執行單次檢查
  python monitor.py --start -i 15      自訂輪詢間隔 (秒)
  python monitor.py --status           顯示目前活躍任務狀態
"""
import argparse
import datetime
import logging
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom  # noqa: F401 -- FK 依賴
from orchestrator.models import WorkerTask

# ============================================================
# 常數
# ============================================================

TERMINAL_STATUSES = ('completed', 'failed', 'timeout', 'cancelled')
ACTIVE_STATUSES = ('pending', 'dispatched', 'running')
OUTPUT_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB
DEFAULT_POLL_INTERVAL = 10
LOG_FILE = '/opt/tmp/BeakCortex-orchestrator-monitor.log'
RUNTIME_CONFIG = '/opt/BeakCortex/config.ini'
PANE_GRACE_SECONDS = 30  # pane 消失後的寬限期
NOTIFY_COOLDOWN = 3600   # 同群組通知��卻 (秒)
GROUP_WINDOW_HOURS = 24  # ��組判定時間窗口
HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'orchestrator-monitor'


# ============================================================
# Logging
# ============================================================

logger = logging.getLogger('orchestrator.monitor')


def setup_logging(verbose: bool = False):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )


# ============================================================
# tmux 操作
# ============================================================

def get_active_tmux_panes() -> set[str]:
    """取得所有存活的 tmux pane ID"""
    try:
        result = subprocess.run(
            ['tmux', 'list-panes', '-a', '-F', '#{pane_id}'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return set(line for line in result.stdout.strip().split('\n') if line)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning('無法列舉 tmux panes (tmux 未啟動?)')
    return set()


def kill_tmux_pane(pane_id: str) -> bool:
    """終止指定 tmux pane"""
    if not pane_id:
        return False
    try:
        result = subprocess.run(
            ['tmux', 'kill-pane', '-t', pane_id],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# ============================================================
# 通知
# ============================================================

def send_notification(message: str, target: str, host: str, port: int) -> bool:
    """透過 notify_windows.py 向 Windows relay 發送通知"""
    from orchestrator.notify_windows import send_message
    rc = send_message(
        message=message,
        host=host,
        port=port,
        action='paste',
        target=target,
    )
    if rc == 0:
        logger.info(f'通知已發送 -> {target}')
        return True
    else:
        logger.error(f'通知發送失敗 (rc={rc})')
        return False


# ============================================================
# 核心監控
# ============================================================

class TaskMonitor:

    def __init__(
        self,
        poll_interval: int = DEFAULT_POLL_INTERVAL,
        notify_host: str = '192.168.0.10',
        notify_port: int = 5200,
        notify_target: str = '',
        dry_run: bool = False,
        config_path: str = RUNTIME_CONFIG,
    ):
        self.poll_interval = poll_interval
        self.notify_host = notify_host
        self.notify_port = notify_port
        self.notify_target = notify_target or '([BeakCortex])'
        self.dry_run = dry_run
        self.config_path = config_path
        # 已通知群組: {frozenset(task_ids): unix_timestamp}
        self._notified: dict[frozenset, float] = {}

    # ----------------------------------------------------------
    # 入口
    # ----------------------------------------------------------

    def run(self):
        """主迴圈"""
        logger.info(
            f'監控啟動 (interval={self.poll_interval}s, '
            f'target={self.notify_target}, dry_run={self.dry_run})'
        )
        init_engine(self.config_path)
        try:
            while True:
                self._tick()
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            logger.info('收到中斷信號，監控停止')

    def run_once(self):
        """單次檢查"""
        init_engine(self.config_path)
        self._tick()

    # ----------------------------------------------------------
    # 單次週期
    # ----------------------------------------------------------

    def _tick(self):
        try:
            self._cleanup_notified()
            active_panes = get_active_tmux_panes()

            with session_scope() as s:
                active_tasks = (
                    s.query(WorkerTask)
                    .filter(WorkerTask.status.in_(ACTIVE_STATUSES))
                    .all()
                )

                if active_tasks:
                    logger.debug(f'活躍任務: {len(active_tasks)}')
                    for task in active_tasks:
                        self._check_task(task, active_panes)
                    s.flush()

                self._check_groups(s)

            self._write_heartbeat()
        except Exception:
            logger.exception('監控週期異常')

    # ----------------------------------------------------------
    # 單一任務檢查
    # ----------------------------------------------------------

    def _check_task(self, task: WorkerTask, active_panes: set[str]):
        now = datetime.datetime.now()

        # --- 逾時 ---
        if task.status in ('dispatched', 'running') and task.dispatched_at:
            elapsed = (now - task.dispatched_at).total_seconds()
            if elapsed > task.timeout_seconds:
                self._terminate(
                    task, 'timeout',
                    f'執行 {elapsed:.0f}s / 上限 {task.timeout_seconds}s',
                )
                return

        # --- 輸出過大 (疑似幻覺) ---
        output_file = f'/tmp/beak-output-{task.id}.txt'
        if os.path.exists(output_file):
            size = os.path.getsize(output_file)
            if size > OUTPUT_SIZE_LIMIT:
                mb = size / (1024 * 1024)
                limit_mb = OUTPUT_SIZE_LIMIT / (1024 * 1024)
                self._terminate(
                    task, 'failed',
                    f'輸出 {mb:.1f}MB > {limit_mb:.0f}MB (疑似幻覺)',
                )
                return

        # --- tmux pane 消失 ---
        if task.status == 'dispatched' and task.tmux_pane:
            if task.tmux_pane not in active_panes:
                if task.dispatched_at:
                    elapsed = (now - task.dispatched_at).total_seconds()
                    if elapsed > PANE_GRACE_SECONDS:
                        self._terminate(
                            task, 'failed',
                            f'tmux pane {task.tmux_pane} 已消失 (process 異常終止)',
                        )
                        return

    def _terminate(self, task: WorkerTask, status: str, reason: str):
        """終止任務: kill pane + 更新 DB"""
        logger.warning(f'Task #{task.id} [{task.title}] -> {status}: {reason}')

        if not self.dry_run and task.tmux_pane:
            killed = kill_tmux_pane(task.tmux_pane)
            if killed:
                logger.info(f'  已 kill pane {task.tmux_pane}')

        task.status = status
        task.completed_at = datetime.datetime.now()

    # ----------------------------------------------------------
    # 群組完成檢查
    # ----------------------------------------------------------

    def _check_groups(self, session):
        """按 main_pane 分群，全部完成時發送通知"""
        cutoff = datetime.datetime.now() - datetime.timedelta(hours=GROUP_WINDOW_HOURS)

        tasks = (
            session.query(WorkerTask)
            .filter(
                WorkerTask.main_pane != '',
                WorkerTask.status != 'cancelled',
                WorkerTask.created_at > cutoff,
            )
            .all()
        )

        groups: dict[str, list[WorkerTask]] = defaultdict(list)
        for t in tasks:
            groups[t.main_pane].append(t)

        for main_pane, group_tasks in groups.items():
            all_terminal = all(t.status in TERMINAL_STATUSES for t in group_tasks)
            if not all_terminal:
                continue

            group_key = frozenset(t.id for t in group_tasks)
            if group_key in self._notified:
                continue

            self._send_group_notification(main_pane, group_tasks, group_key)

    def _send_group_notification(
        self,
        main_pane: str,
        tasks: list[WorkerTask],
        group_key: frozenset,
    ):
        completed = sum(1 for t in tasks if t.status == 'completed')
        failed = sum(1 for t in tasks if t.status == 'failed')
        timeout = sum(1 for t in tasks if t.status == 'timeout')
        total = len(tasks)

        details = []
        for t in sorted(tasks, key=lambda x: x.id):
            mark = 'OK' if t.status == 'completed' else t.status.upper()
            details.append(f'#{t.id}({mark})')

        parts = [f'{total}個任務:']
        if completed:
            parts.append(f'{completed}成功')
        if failed:
            parts.append(f'{failed}失敗')
        if timeout:
            parts.append(f'{timeout}逾時')

        message = (
            f'[Orchestrator] 支線批次完成 '
            f'({" ".join(parts)}) '
            f'{" ".join(details)} '
            f'-- 請用 task_collect 驗收結果'
        )

        logger.info(f'群組完成: pane={main_pane} | {message}')

        if not self.dry_run:
            send_notification(
                message=message,
                target=self.notify_target,
                host=self.notify_host,
                port=self.notify_port,
            )

        self._notified[group_key] = time.time()

    # ----------------------------------------------------------
    # 內部維護
    # ----------------------------------------------------------

    def _cleanup_notified(self):
        """清理��期的通知記錄"""
        now = time.time()
        expired = [k for k, ts in self._notified.items() if now - ts > NOTIFY_COOLDOWN]
        for k in expired:
            del self._notified[k]

    @staticmethod
    def _write_heartbeat():
        """每次成功檢查後寫入 heartbeat"""
        os.makedirs(HEARTBEAT_DIR, exist_ok=True)
        Path(os.path.join(HEARTBEAT_DIR, f'{HEARTBEAT_BASE}.ok')).write_text(
            datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )


# ============================================================
# 狀態顯示
# ============================================================

def show_status():
    """顯示目前活躍任務狀態（呼叫前須先 init_engine）"""
    with session_scope() as s:
        active = [
            t.to_dict() for t in
            s.query(WorkerTask)
            .filter(WorkerTask.status.in_(ACTIVE_STATUSES))
            .order_by(WorkerTask.created_at.desc())
            .all()
        ]
        recent_done = [
            t.to_dict() for t in
            s.query(WorkerTask)
            .filter(WorkerTask.status.in_(TERMINAL_STATUSES))
            .order_by(WorkerTask.completed_at.desc())
            .limit(10)
            .all()
        ]

    active_panes = get_active_tmux_panes()

    print('=== Orchestrator Monitor 狀態 ===')
    print(f'時間: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}')
    print(f'tmux panes: {len(active_panes)} 個存活')
    print()

    if active:
        print(f'--- 活躍任務 ({len(active)}) ---')
        for t in active:
            elapsed = ''
            if t['dispatched_at']:
                da = datetime.datetime.fromisoformat(t['dispatched_at'])
                secs = (datetime.datetime.now() - da).total_seconds()
                elapsed = f' ({secs:.0f}s/{t.get("timeout_seconds", "?")}s)'
            pane_id = t.get('tmux_pane', '')
            pane_alive = 'alive' if pane_id in active_panes else 'GONE'
            print(
                f'  #{t["id"]:3d} [{t["status"]:10s}] {t["title"][:40]}'
                f'{elapsed}  pane={pane_id}({pane_alive})'
            )
    else:
        print('--- 無活躍任務 ---')

    print()
    if recent_done:
        print(f'--- 最近完成 (最多 10 筆) ---')
        for t in recent_done:
            ca = t['completed_at']
            if ca:
                completed = datetime.datetime.fromisoformat(ca).strftime('%H:%M:%S')
            else:
                completed = '?'
            print(
                f'  #{t["id"]:3d} [{t["status"]:10s}] {t["title"][:40]}'
                f'  完成於 {completed}'
            )
    else:
        print('--- 無已完成任務 ---')


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        prog='monitor.py',
        description='BeakCortex Orchestrator 支線監控 daemon',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python monitor.py --start              啟動監控 (前景)
  python monitor.py --start -i 15        自訂輪詢間隔 15 秒
  python monitor.py --once               執行單次檢查
  python monitor.py --once --dry-run     單次檢查 (不執行 kill/通知)
  python monitor.py --status             顯示目前任務狀態

監控行為:
  逾時偵測   dispatched 超過 timeout_seconds -> kill + 標記 timeout
  輸出異常   /tmp/beak-output-*.txt > 10MB -> kill + 標記 failed
  tmux 消失  pane 不存在但任務仍 dispatched -> 標記 failed
  批次完成   同 main_pane 任務全部完成 -> notify_windows.py 通知主線

Log: {LOG_FILE}
"""
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--start', action='store_true',
                      help='啟動監控 daemon (前景執行)')
    mode.add_argument('--once', action='store_true',
                      help='執行單次檢查後退出')
    mode.add_argument('--status', action='store_true',
                      help='顯示目前活躍任務狀態')

    parser.add_argument('-i', '--interval', type=int, default=DEFAULT_POLL_INTERVAL,
                        metavar='SEC', help=f'輪詢間隔秒數 (預設 {DEFAULT_POLL_INTERVAL})')
    parser.add_argument('--target', default='', metavar='TGT',
                        help='Windows relay 目標分頁 (預設 ([BeakCortex]))')
    parser.add_argument('--host', default='192.168.0.10', metavar='IP',
                        help='Windows relay IP (預設 192.168.0.10)')
    parser.add_argument('--port', type=int, default=5200, metavar='PORT',
                        help='Windows relay port (預設 5200)')
    parser.add_argument('--dry-run', action='store_true',
                        help='乾跑模式 (不執行 kill/通知，僅 log)')
    parser.add_argument('-c', '--config', default='', metavar='INI',
                        help=f'組態檔路徑 (預設 {RUNTIME_CONFIG})')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='顯示 debug 層級 log')

    if len(sys.argv) == 1:
        print('BeakCortex Orchestrator 支線監控 daemon')
        print()
        print('獨立非 AI 程式，自動偵測支線任務逾時/異常/完成，')
        print('並透過 Windows relay 通知主線驗收。')
        print()
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    config_path = args.config or RUNTIME_CONFIG

    if args.status:
        init_engine(config_path)
        show_status()
        return

    setup_logging(verbose=args.verbose)

    monitor = TaskMonitor(
        poll_interval=args.interval,
        notify_host=args.host,
        notify_port=args.port,
        notify_target=args.target,
        dry_run=args.dry_run,
        config_path=config_path,
    )

    if args.once:
        monitor.run_once()
    elif args.start:
        monitor.run()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
