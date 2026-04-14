#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex 集中式排程器

單一 crontab 入口，取代多行個別排程。
每 5 分鐘由 crontab 呼叫 --tick，檢查 schedule.json 中哪些任務到期並執行。

設計原則：
- 所有 BeakCortex 排程任務集中在 schedule.json
- crontab 只保留這一行 scheduler 入口
- 各任務仍為獨立 script，scheduler 負責觸發時機
- 任務自行管理 heartbeat、log
- scheduler 本身也寫 heartbeat

使用範例:
  python scheduler.py --tick                  執行一次排程檢查
  python scheduler.py --status                顯示所有任務狀態
  python scheduler.py --run-now vitality_decay 立即執行指定任務
  python scheduler.py --dry-run               試跑，不執行任務
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ============================================================
# 常數
# ============================================================

HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'scheduler'
LOG_PATH = '/opt/tmp/scripts-scheduler.log'
BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
SCHEDULE_PATH = SCRIPTS_DIR / 'schedule.json'
STATE_PATH = SCRIPTS_DIR / '.scheduler_state.json'
VENV_PYTHON = sys.executable  # 用啟動 scheduler 的 Python，確保 venv 一致


def _write_heartbeat():
    name = f'{HEARTBEAT_BASE}.ok'
    Path(os.path.join(HEARTBEAT_DIR, name)).write_text(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


# ============================================================
# Cron 表達式解析（簡易版，支援 m h dom mon dow）
# ============================================================

def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """檢查 cron 表達式是否匹配指定時間（精確到分鐘）"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False

    fields = [
        (parts[0], dt.minute, 0, 59),
        (parts[1], dt.hour, 0, 23),
        (parts[2], dt.day, 1, 31),
        (parts[3], dt.month, 1, 12),
        (parts[4], dt.weekday() if dt.weekday() != 6 else 0, 0, 6),
        # Python weekday: Mon=0..Sun=6; cron: Sun=0..Sat=6
    ]
    # 修正: cron dow: 0=Sun, 1=Mon..6=Sat; Python: 0=Mon..6=Sun
    dow_cron = (dt.weekday() + 1) % 7  # Mon=1..Sat=6, Sun=0
    fields[4] = (parts[4], dow_cron, 0, 6)

    for expr, current, lo, hi in fields:
        if not _field_matches(expr, current, lo, hi):
            return False
    return True


def _field_matches(expr: str, current: int, lo: int, hi: int) -> bool:
    """解析單一 cron 欄位"""
    if expr == '*':
        return True

    for part in expr.split(','):
        # 處理 step: */N 或 M-N/S
        if '/' in part:
            range_part, step = part.split('/', 1)
            step = int(step)
            if range_part == '*':
                if current % step == 0:
                    return True
            elif '-' in range_part:
                a, b = map(int, range_part.split('-', 1))
                if a <= current <= b and (current - a) % step == 0:
                    return True
            continue

        # 處理 range: M-N
        if '-' in part:
            a, b = map(int, part.split('-', 1))
            if a <= current <= b:
                return True
            continue

        # 處理單值
        if int(part) == current:
            return True

    return False


# ============================================================
# 狀態管理
# ============================================================

def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


# ============================================================
# 排程載入
# ============================================================

def _load_schedule() -> list[dict]:
    if not SCHEDULE_PATH.exists():
        return []
    data = json.loads(SCHEDULE_PATH.read_text(encoding='utf-8'))
    return data.get('tasks', [])


def _expand_command(cmd_parts: list[str]) -> list[str]:
    """展開 command 中的變數"""
    replacements = {
        '{venv_python}': VENV_PYTHON,
        '{scripts_dir}': str(SCRIPTS_DIR),
        '{base_dir}': str(BASE_DIR),
    }
    result = []
    for part in cmd_parts:
        for key, value in replacements.items():
            part = part.replace(key, value)
        result.append(part)
    return result


# ============================================================
# 核心邏輯
# ============================================================

def tick(dry_run: bool = False):
    """一次 tick：檢查所有任務，執行到期的"""
    logger = logging.getLogger('scheduler')
    now = datetime.now()
    tasks = _load_schedule()
    state = _load_state()

    if not tasks:
        logger.warning('schedule.json 無任務或不存在')
        return

    executed = 0
    for task in tasks:
        name = task.get('name', 'unknown')
        if not task.get('enabled', True):
            continue

        cron_expr = task.get('cron', '')
        if not cron_expr:
            continue

        # 檢查是否匹配當前時間
        if not _cron_matches(cron_expr, now):
            continue

        # 防止同一分鐘重複執行（5 分鐘 tick 但 cron 可能精確到分鐘）
        last_run = state.get(name, {}).get('last_run', '')
        current_minute = now.strftime('%Y-%m-%d %H:%M')
        if last_run == current_minute:
            continue

        # 到期，執行
        cmd = _expand_command(task.get('command', []))
        timeout = task.get('timeout_seconds', 300)

        if dry_run:
            logger.info(f'[DRY-RUN] 到期: {name} ({task.get("description", "")}) -> {" ".join(cmd)}')
            continue

        logger.info(f'執行任務: {name} ({task.get("description", "")})')
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            success = result.returncode == 0
            state[name] = {
                'last_run': current_minute,
                'last_status': 'ok' if success else 'failed',
                'last_exit_code': result.returncode,
                'last_timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            }
            if success:
                logger.info(f'任務完成: {name} (exit=0)')
            else:
                logger.error(f'任務失敗: {name} (exit={result.returncode})')
                if result.stderr:
                    logger.error(f'  stderr: {result.stderr[:500]}')
            executed += 1
        except subprocess.TimeoutExpired:
            logger.error(f'任務逾時: {name} ({timeout}s)')
            state[name] = {
                'last_run': current_minute,
                'last_status': 'timeout',
                'last_timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            }
        except Exception as e:
            logger.error(f'任務例外: {name}: {e}')
            state[name] = {
                'last_run': current_minute,
                'last_status': 'error',
                'last_timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
            }

    if not dry_run:
        _save_state(state)

    logger.info(f'tick 完成: {now.strftime("%H:%M")}, 執行 {executed} 個任務')


def run_now(task_name: str):
    """立即執行指定任務"""
    logger = logging.getLogger('scheduler')
    tasks = _load_schedule()
    task = next((t for t in tasks if t.get('name') == task_name), None)
    if not task:
        logger.error(f'任務不存在: {task_name}')
        return False

    cmd = _expand_command(task.get('command', []))
    timeout = task.get('timeout_seconds', 300)
    logger.info(f'立即執行: {task_name} -> {" ".join(cmd)}')

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode == 0:
        logger.info(f'完成: {task_name} (exit=0)')
    else:
        logger.error(f'失敗: {task_name} (exit={result.returncode})')
        if result.stderr:
            logger.error(f'  stderr: {result.stderr[:500]}')

    # 更新 state
    state = _load_state()
    state[task_name] = {
        'last_run': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'last_status': 'ok' if result.returncode == 0 else 'failed',
        'last_exit_code': result.returncode,
        'last_timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    _save_state(state)
    return result.returncode == 0


def show_status():
    """顯示所有任務狀態"""
    tasks = _load_schedule()
    state = _load_state()

    print(f'排程設定: {SCHEDULE_PATH}')
    print(f'狀態檔案: {STATE_PATH}')
    print(f'任務數量: {len(tasks)}')
    print()
    print(f'{"任務名稱":<20} {"啟用":<6} {"Cron":<15} {"上次執行":<20} {"狀態":<10} {"說明"}')
    print('-' * 100)

    for task in tasks:
        name = task.get('name', 'unknown')
        enabled = 'Y' if task.get('enabled', True) else 'N'
        cron = task.get('cron', '-')
        desc = task.get('description', '')
        st = state.get(name, {})
        last_ts = st.get('last_timestamp', '-')
        last_status = st.get('last_status', '-')
        print(f'{name:<20} {enabled:<6} {cron:<15} {last_ts:<20} {last_status:<10} {desc}')


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='BeakCortex 集中式排程器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python scheduler.py --tick                  執行一次排程檢查
  python scheduler.py --status                顯示所有任務狀態
  python scheduler.py --run-now vitality_decay 立即執行指定任務
  python scheduler.py --dry-run               試跑，不執行任務
        """,
    )
    parser.add_argument('--tick', action='store_true', help='執行一次排程檢查')
    parser.add_argument('--status', action='store_true', help='顯示所有任務狀態')
    parser.add_argument('--run-now', type=str, metavar='TASK', help='立即執行指定任務')
    parser.add_argument('--dry-run', action='store_true', help='試跑模式')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_PATH, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )

    if args.status:
        show_status()
        return

    if args.run_now:
        success = run_now(args.run_now)
        sys.exit(0 if success else 1)

    if args.tick or args.dry_run:
        tick(dry_run=args.dry_run)
        if not args.dry_run:
            _write_heartbeat()
        return

    parser.print_help()


if __name__ == '__main__':
    main()
