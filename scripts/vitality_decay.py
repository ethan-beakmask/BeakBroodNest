#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest Vitality Decay -- 知識原子活力衰減排程

根據 last_accessed_at 計算指數衰減，低於閾值自動轉 aging lifecycle。
排除受保護的原子（human source + 里程碑/架構設計/路線圖 tag）。

衰減公式: vitality = e^(-ln2 / half_life * days_since_access)
預設半衰期 30 天（30 天未存取 -> vitality 降至 0.5）
"""
import argparse
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom, Tag, atom_tags

# ============================================================
# 常數
# ============================================================

HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'vitality_decay'
LOG_PATH = '/opt/tmp/scripts-vitality_decay.log'

# 受保護的標籤（擁有這些標籤的 human 原子不衰減）
PROTECTED_TAGS = {'里程碑', '架構設計', '路線圖', '永久'}

# ============================================================
# Heartbeat
# ============================================================


def _write_heartbeat():
    """正常完成時寫入 heartbeat 檔案"""
    name = f'{HEARTBEAT_BASE}.ok'
    Path(os.path.join(HEARTBEAT_DIR, name)).write_text(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


# ============================================================
# 核心邏輯
# ============================================================


def calc_vitality(days_since_access: float, half_life: float) -> float:
    """指數衰減：vitality = e^(-ln2 / half_life * days)"""
    if days_since_access <= 0:
        return 1.0
    decay_rate = math.log(2) / half_life
    v = math.exp(-decay_rate * days_since_access)
    return round(v, 6)


def run_decay(
    half_life: float = 30.0,
    aging_threshold: float = 0.3,
    dry_run: bool = False,
    config_path: str | None = None,
):
    """執行 vitality 衰減計算"""
    logger = logging.getLogger('vitality_decay')

    # 初始化 DB
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    init_engine(config_path)

    now = datetime.now()

    with session_scope() as s:
        # 取得所有 active 且未刪除的原子
        atoms = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.lifecycle.in_(['active', 'aging']),
            )
            .all()
        )
        logger.info(f'待處理原子數: {len(atoms)}')

        # 取得受保護的原子 ID（human source + 保護標籤）
        protected_ids = set()
        if PROTECTED_TAGS:
            protected_rows = (
                s.query(atom_tags.c.atom_id)
                .join(Tag, Tag.id == atom_tags.c.tag_id)
                .join(KnowledgeAtom, KnowledgeAtom.id == atom_tags.c.atom_id)
                .filter(
                    Tag.name.in_(PROTECTED_TAGS),
                    KnowledgeAtom.source == 'human',
                )
                .distinct()
                .all()
            )
            protected_ids = {r[0] for r in protected_rows}
            logger.info(f'受保護原子數（human + 保護標籤）: {len(protected_ids)}')

        updated_count = 0
        aged_count = 0
        skipped_count = 0

        for atom in atoms:
            # 跳過受保護原子
            if atom.id in protected_ids:
                skipped_count += 1
                continue

            # 計算衰減
            last_access = atom.last_accessed_at or atom.updated_at or atom.created_at
            days_since = (now - last_access).total_seconds() / 86400
            new_vitality = calc_vitality(days_since, half_life)

            # 只在 vitality 有變化時更新（避免不必要的 DB write）
            old_vitality = atom.vitality_score or 1.0
            if abs(new_vitality - old_vitality) < 0.001:
                continue

            if dry_run:
                logger.info(
                    f'[DRY-RUN] #{atom.id} "{atom.title[:30]}" '
                    f'vitality {old_vitality:.4f} -> {new_vitality:.4f} '
                    f'(days={days_since:.1f})'
                )
            else:
                atom.vitality_score = new_vitality
                updated_count += 1

            # 低於閾值且為 active -> 自動轉 aging
            if new_vitality < aging_threshold and atom.lifecycle == 'active':
                if dry_run:
                    logger.info(
                        f'[DRY-RUN] #{atom.id} 將轉為 aging '
                        f'(vitality {new_vitality:.4f} < {aging_threshold})'
                    )
                else:
                    atom.lifecycle = 'aging'
                    aged_count += 1
                    logger.info(
                        f'#{atom.id} "{atom.title[:30]}" 轉為 aging '
                        f'(vitality {new_vitality:.4f})'
                    )

        if not dry_run:
            s.flush()

        logger.info(
            f'完成: 更新 {updated_count} 筆, '
            f'轉 aging {aged_count} 筆, '
            f'受保護跳過 {skipped_count} 筆'
        )

    return updated_count, aged_count, skipped_count


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest 知識原子活力衰減排程',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python vitality_decay.py --run              執行衰減計算
  python vitality_decay.py --dry-run          試跑，不寫入 DB
  python vitality_decay.py --run --half-life 60  使用 60 天半衰期
  python vitality_decay.py --run -c /path/config.ini  指定組態檔
        """,
    )
    parser.add_argument('--run', action='store_true', help='執行衰減計算')
    parser.add_argument('--dry-run', action='store_true', help='試跑模式，僅顯示變更不寫入')
    parser.add_argument('--half-life', type=float, default=30.0,
                        help='半衰期天數（預設 30）')
    parser.add_argument('--aging-threshold', type=float, default=0.3,
                        help='低於此 vitality 自動轉 aging（預設 0.3）')
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='組態檔路徑（預設: ../config.ini）')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    # 設定 logging
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

    updated, aged, skipped = run_decay(
        half_life=args.half_life,
        aging_threshold=args.aging_threshold,
        dry_run=args.dry_run,
        config_path=args.config,
    )

    if not args.dry_run:
        _write_heartbeat()


if __name__ == '__main__':
    main()
