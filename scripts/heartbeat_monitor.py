#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BeakBroodNest heartbeat 監控

由 scheduler 每 30 分鐘觸發一次 --check。檢查 heartbeat_monitor.json 內列出的
heartbeat 檔案 mtime，超過 max_age_seconds 即視為異常並：
  1. 寫 ERROR log
  2. 寫一則 alert 訊息到 BBN inbox（sender=task:heartbeat-monitor,
     recipient=project:beakbroodnest），下次對話啟動 note_inbox 必看到

冪等：每個項目有 alert_cooldown_seconds 冷卻期，避免每 30 分鐘重複 spam。
heartbeat 恢復後 cooldown 自動 reset。

CLI:
  --check     正常檢查（給 scheduler 用）
  --status    顯示全部 heartbeat 狀態（人類用）
  --dry-run   檢查但不寫 inbox

歷史：本工具是用戶察覺「復盤 pipeline 失敗 9 天無人發現」後產出的補救機制
（commit 244e4e9 修了表象，本工具修了「異常無告警通道」這個根因）。
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPTS_DIR / 'heartbeat_monitor.json'
STATE_PATH = SCRIPTS_DIR / '.heartbeat_monitor_state.json'
LOG_PATH = '/opt/tmp/scripts-heartbeat_monitor.log'
HEARTBEAT_FILE = '/opt/tmp/heartbeat/heartbeat_monitor.ok'

sys.path.insert(0, str(BASE_DIR))


def _load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')


def _write_self_heartbeat():
    Path(HEARTBEAT_FILE).write_text(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))


def _check_one(item: dict, heartbeat_dir: str) -> dict:
    """檢查單一 heartbeat。回傳 {name, ok, mtime, age_seconds, max_age_seconds, reason}"""
    path = Path(heartbeat_dir) / item['file']
    max_age = int(item['max_age_seconds'])
    if not path.exists():
        return {
            'name': item['name'],
            'ok': False,
            'mtime': None,
            'age_seconds': None,
            'max_age_seconds': max_age,
            'reason': f'heartbeat 檔案不存在: {path}',
        }
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    age = (datetime.now() - mtime).total_seconds()
    return {
        'name': item['name'],
        'ok': age <= max_age,
        'mtime': mtime,
        'age_seconds': age,
        'max_age_seconds': max_age,
        'reason': '' if age <= max_age else f'已 {int(age)} 秒未更新（上限 {max_age}）',
    }


def _emit_inbox_alert(item: dict, result: dict, logger: logging.Logger):
    """寫一則 alert 訊息到 BBN inbox。"""
    try:
        from core.db import session_scope
        from core.models import Message
    except ImportError as e:
        logger.error(f'無法匯入 Message ORM，跳過 inbox 寫入: {e}')
        return False

    mtime_str = result['mtime'].strftime('%Y-%m-%d %H:%M:%S') if result['mtime'] else '從未寫入'
    age_human = (
        f"{int(result['age_seconds']) // 3600} 小時 "
        f"{(int(result['age_seconds']) % 3600) // 60} 分鐘"
        if result['age_seconds'] else '無'
    )
    subject = f'[Heartbeat] {item["name"]} 異常'
    body = (
        f"**監控項目**：{item['name']}\n"
        f"**說明**：{item.get('description', '')}\n"
        f"**heartbeat 檔案**：{item['file']}\n"
        f"**最後更新**：{mtime_str}\n"
        f"**已延遲**：{age_human}（容忍上限 {result['max_age_seconds']} 秒）\n"
        f"**原因**：{result['reason']}\n\n"
        f"請檢查對應排程或腳本是否異常。"
    )
    try:
        with session_scope() as s:
            existing = s.query(Message).filter(
                Message.recipient == 'project:beakbroodnest',
                Message.subject == subject,
                Message.is_read == False,
            ).first()
            if existing:
                logger.info(f'  {item["name"]}: 已有未讀 alert（id={existing.id}），跳過重複發送')
                return False
            msg = Message(
                sender='task:heartbeat-monitor',
                sender_cwd=str(BASE_DIR),
                recipient='project:beakbroodnest',
                subject=subject,
                body=body,
                message_type='alert',
            )
            s.add(msg)
        return True
    except Exception as e:
        logger.error(f'寫 inbox alert 失敗: {e}')
        return False


def check_all(dry_run: bool = False) -> int:
    """檢查所有 heartbeat，回傳異常項目數。"""
    logger = logging.getLogger('heartbeat_monitor')
    cfg = _load_config()
    state = _load_state()
    now_ts = datetime.now().timestamp()
    default_cooldown = int(cfg.get('default_alert_cooldown_seconds', 21600))
    heartbeat_dir = cfg['heartbeat_dir']
    items = cfg['items']

    fail_count = 0
    for item in items:
        result = _check_one(item, heartbeat_dir)
        name = item['name']
        if result['ok']:
            logger.info(f'[OK] {name}: age={int(result["age_seconds"])}s')
            # 恢復則清掉 cooldown 與 last_alert
            if name in state:
                state.pop(name, None)
            continue

        fail_count += 1
        logger.error(f'[STALE] {name}: {result["reason"]}')

        if dry_run:
            continue

        cooldown = int(item.get('alert_cooldown_seconds', default_cooldown))
        last_alert_ts = state.get(name, {}).get('last_alert_ts', 0)
        if now_ts - last_alert_ts < cooldown:
            logger.info(f'  {name}: cooldown 期內（{int(now_ts - last_alert_ts)}s < {cooldown}s），不重複告警')
            continue

        if _emit_inbox_alert(item, result, logger):
            state[name] = {'last_alert_ts': now_ts, 'last_alert_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            logger.info(f'  {name}: alert 已寫入 BBN inbox')

    if not dry_run:
        _save_state(state)
        _write_self_heartbeat()

    logger.info(f'check 完成，{fail_count} 個異常 / 共 {len(items)} 個監控項')
    return fail_count


def show_status():
    cfg = _load_config()
    heartbeat_dir = cfg['heartbeat_dir']
    state = _load_state()
    print(f'設定: {CONFIG_PATH}')
    print(f'heartbeat 目錄: {heartbeat_dir}')
    print()
    print(f'{"項目":<22} {"狀態":<6} {"最後更新":<20} {"延遲":<12} {"上限":<10} {"上次告警":<20}')
    print('-' * 100)
    for item in cfg['items']:
        result = _check_one(item, heartbeat_dir)
        st = state.get(item['name'], {})
        mtime_str = result['mtime'].strftime('%Y-%m-%d %H:%M:%S') if result['mtime'] else '-'
        age_str = f'{int(result["age_seconds"])}s' if result['age_seconds'] is not None else '-'
        max_age_str = f'{result["max_age_seconds"]}s'
        ok_str = 'OK' if result['ok'] else 'STALE'
        last_alert = st.get('last_alert_at', '-')
        print(f'{item["name"]:<22} {ok_str:<6} {mtime_str:<20} {age_str:<12} {max_age_str:<10} {last_alert:<20}')


def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest heartbeat 監控',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  heartbeat_monitor.py --check        檢查所有 heartbeat，異常則寫 inbox alert
  heartbeat_monitor.py --status       顯示狀態總覽
  heartbeat_monitor.py --dry-run      檢查但不寫 inbox，不更新 state
""",
    )
    parser.add_argument('--check', action='store_true', help='正常檢查')
    parser.add_argument('--status', action='store_true', help='顯示狀態總覽')
    parser.add_argument('--dry-run', action='store_true', help='試跑，不寫 inbox')

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

    if args.check or args.dry_run:
        fail = check_all(dry_run=args.dry_run)
        sys.exit(0 if fail == 0 else 1)

    parser.print_help()


if __name__ == '__main__':
    main()
