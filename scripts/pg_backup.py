#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest PostgreSQL 備份排程

每日備份 beak_broodnest 資料庫，保留 N 天份，自動輪替。
備份格式: pg_dump custom format (.dump)

使用範例:
  python pg_backup.py --run              執行備份（預設保留 7 天）
  python pg_backup.py --run --keep 14    保留 14 天
  python pg_backup.py --dry-run          試跑，顯示動作不執行
  python pg_backup.py --run -c path.ini  指定組態檔
"""
import argparse
import configparser
import glob
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ============================================================
# 常數
# ============================================================

HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'pg_backup'
LOG_PATH = '/opt/tmp/scripts-pg_backup.log'
BACKUP_DIR = '/opt/BeakBroodNest/backups'


def _write_heartbeat():
    """正常完成時寫入 heartbeat 檔案"""
    name = f'{HEARTBEAT_BASE}.ok'
    Path(os.path.join(HEARTBEAT_DIR, name)).write_text(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


# ============================================================
# 核心邏輯
# ============================================================

def run_backup(keep_days: int = 7, dry_run: bool = False, config_path: str | None = None):
    """執行 PostgreSQL 備份"""
    logger = logging.getLogger('pg_backup')

    # 讀取組態
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding='utf-8')

    db_host = cfg.get('postgresql', 'host', fallback='localhost')
    db_port = cfg.get('postgresql', 'port', fallback='5432')
    db_name = cfg.get('postgresql', 'database', fallback='beak_broodnest')
    db_user = cfg.get('postgresql', 'user', fallback='beak_broodnest')
    db_password = cfg.get('postgresql', 'password', fallback='postgres123')

    # 確保備份目錄存在
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # 備份檔名
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    backup_file = os.path.join(BACKUP_DIR, f'beak_broodnest_{timestamp}.dump')

    logger.info(f'開始備份: {db_name}@{db_host}:{db_port} -> {backup_file}')

    if dry_run:
        logger.info(f'[DRY-RUN] 將執行 pg_dump -> {backup_file}')
        logger.info(f'[DRY-RUN] 保留天數: {keep_days}')
        _show_rotation(keep_days, logger, dry_run=True)
        return True

    # 執行 pg_dump
    env = os.environ.copy()
    env['PGPASSWORD'] = db_password

    cmd = [
        'pg_dump',
        '-h', db_host,
        '-p', db_port,
        '-U', db_user,
        '-d', db_name,
        '-F', 'c',         # custom format (壓縮 + 可選擇性還原)
        '-f', backup_file,
    ]

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error(f'pg_dump 失敗: {result.stderr}')
            return False
    except subprocess.TimeoutExpired:
        logger.error('pg_dump 逾時 (300 秒)')
        return False
    except FileNotFoundError:
        logger.error('pg_dump 未安裝或不在 PATH 中')
        return False

    # 檢查備份檔大小
    size = os.path.getsize(backup_file)
    logger.info(f'備份完成: {backup_file} ({size / 1024:.1f} KB)')

    if size < 1024:
        logger.warning(f'備份檔案過小 ({size} bytes)，可能有問題')

    # 輪替舊備份
    _show_rotation(keep_days, logger, dry_run=False)

    return True


def _show_rotation(keep_days: int, logger, dry_run: bool = False):
    """輪替舊備份，保留最近 keep_days 天"""
    pattern = os.path.join(BACKUP_DIR, 'beak_broodnest_*.dump')
    files = sorted(glob.glob(pattern), reverse=True)

    if len(files) <= keep_days:
        logger.info(f'現有 {len(files)} 份備份，保留上限 {keep_days}，無需輪替')
        return

    to_delete = files[keep_days:]
    for f in to_delete:
        if dry_run:
            logger.info(f'[DRY-RUN] 將刪除: {f}')
        else:
            os.remove(f)
            logger.info(f'已刪除舊備份: {f}')

    logger.info(f'輪替完成: 刪除 {len(to_delete)} 份，保留 {min(len(files), keep_days)} 份')


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest PostgreSQL 備份排程',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python pg_backup.py --run              執行備份（預設保留 7 天）
  python pg_backup.py --run --keep 14    保留 14 天
  python pg_backup.py --dry-run          試跑，顯示動作不執行
  python pg_backup.py --run -c path.ini  指定組態檔
        """,
    )
    parser.add_argument('--run', action='store_true', help='執行備份')
    parser.add_argument('--dry-run', action='store_true', help='試跑模式')
    parser.add_argument('--keep', type=int, default=7, help='保留天數（預設 7）')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')

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

    if not args.run and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    success = run_backup(
        keep_days=args.keep,
        dry_run=args.dry_run,
        config_path=args.config,
    )

    if success and not args.dry_run:
        _write_heartbeat()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
