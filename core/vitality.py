#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vitality_score 計算引擎

計算公式:
  V = w1 * decay + w2 * reuse + w3 * chain_activity + penalty

  decay (時間衰減):
    基於 last_accessed_at 距今天數，半衰期 30 天
    score = 0.5 ^ (days_since_access / half_life)

  reuse (再利用率):
    基於 access_count 和存活天數
    score = min(access_count / max(age_days, 1), 1.0)
    正規化到 [0, 1] 區間

  chain_activity (因果鍊活性):
    上下游關聯的 active 原子占比
    score = active_relations / total_relations (無關聯則 1.0)

  penalty (矛盾懲罰):
    被 contradicts 關係否定時 -0.5

權重: decay=0.5, reuse=0.2, chain=0.2, penalty 直接扣除
最終 clamp 到 [0.0, 1.0]

使用方式:
  python vitality.py                顯示說明
  python vitality.py --recalc       重算所有 active/aging 原子
  python vitality.py --recalc -v    重算並顯示明細
"""
import argparse
import sys
import os
import math
import datetime
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'vitality'


def _write_heartbeat(suffix=None):
    """正常完成時寫入 heartbeat 檔案"""
    name = f"{HEARTBEAT_BASE}_{suffix}.ok" if suffix else f"{HEARTBEAT_BASE}.ok"
    Path(os.path.join(HEARTBEAT_DIR, name)).write_text(
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom, AtomRelation

logger = logging.getLogger('beak_cortex.vitality')

# 權重與參數
W_DECAY = 0.5
W_REUSE = 0.2
W_CHAIN = 0.2
HALF_LIFE_DAYS = 30.0
REFUTE_PENALTY = 0.5
REUSE_CAP = 20  # access_count 達到此值視為滿分


def calc_vitality(atom, active_relation_ratio, is_refuted, now=None):
    """計算單一原子的 vitality_score，回傳 float [0.0, 1.0]"""
    if now is None:
        now = datetime.datetime.now()

    # 1. 時間衰減
    last_access = atom.last_accessed_at or atom.created_at or now
    days_since = max((now - last_access).total_seconds() / 86400, 0)
    decay = math.pow(0.5, days_since / HALF_LIFE_DAYS)

    # 2. 再利用率
    age_days = max((now - (atom.created_at or now)).total_seconds() / 86400, 1)
    raw_reuse = atom.access_count / age_days
    reuse = min(raw_reuse / (REUSE_CAP / max(age_days, 1)), 1.0)
    # 簡化: 直接用 access_count / REUSE_CAP
    reuse = min(atom.access_count / REUSE_CAP, 1.0)

    # 3. 因果鍊活性
    chain = active_relation_ratio

    # 4. 矛盾懲罰
    penalty = REFUTE_PENALTY if is_refuted else 0.0

    score = W_DECAY * decay + W_REUSE * reuse + W_CHAIN * chain - penalty
    return max(0.0, min(1.0, score))


def recalc_all(verbose=False):
    """重算所有 active/aging 原子的 vitality_score"""
    now = datetime.datetime.now()
    updated = 0

    with session_scope() as s:
        atoms = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.lifecycle.in_(['active', 'aging']),
            )
            .all()
        )

        for atom in atoms:
            # 計算因果鍊活性
            relations = (
                s.query(AtomRelation)
                .filter(
                    (AtomRelation.from_atom_id == atom.id) |
                    (AtomRelation.to_atom_id == atom.id)
                )
                .all()
            )

            if relations:
                related_ids = set()
                for r in relations:
                    if r.from_atom_id != atom.id:
                        related_ids.add(r.from_atom_id)
                    if r.to_atom_id != atom.id:
                        related_ids.add(r.to_atom_id)

                if related_ids:
                    active_count = (
                        s.query(KnowledgeAtom)
                        .filter(
                            KnowledgeAtom.id.in_(related_ids),
                            KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                            KnowledgeAtom.is_deleted == False,
                        )
                        .count()
                    )
                    chain_ratio = active_count / len(related_ids)
                else:
                    chain_ratio = 1.0
            else:
                chain_ratio = 1.0  # 無關聯的孤立原子不扣分

            # 檢查是否被 contradicts
            is_refuted = (
                s.query(AtomRelation)
                .filter(
                    AtomRelation.to_atom_id == atom.id,
                    AtomRelation.relation_type == 'contradicts',
                )
                .first()
            ) is not None

            old_score = atom.vitality_score
            new_score = calc_vitality(atom, chain_ratio, is_refuted, now)
            atom.vitality_score = round(new_score, 4)
            updated += 1

            if verbose:
                delta = new_score - old_score
                sign = '+' if delta >= 0 else ''
                print(f'  [{atom.id:3d}] {atom.title[:40]:<40s}  '
                      f'{old_score:.4f} -> {new_score:.4f} ({sign}{delta:.4f})')

    return updated


def main():
    parser = argparse.ArgumentParser(
        description='BeakCortex vitality_score 計算引擎',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python vitality.py --recalc       重算所有 active/aging 原子
  python vitality.py --recalc -v    重算並顯示明細
        """
    )
    parser.add_argument('--recalc', action='store_true', help='重算所有 active/aging 原子的 vitality_score')
    parser.add_argument('-v', '--verbose', action='store_true', help='顯示每筆原子的計算明細')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')

    if len(sys.argv) == 1:
        print('BeakCortex vitality_score 計算引擎')
        print()
        print('必要參數:')
        print('  --recalc    重算所有 active/aging 原子的 vitality_score')
        print()
        print('選項:')
        print('  -v          顯示每筆原子的計算明細')
        print('  --config    組態檔路徑 (預設: ../config.ini)')
        print()
        print('公式: V = 0.5*decay + 0.2*reuse + 0.2*chain - refute_penalty')
        print('  decay:   時間衰減 (半衰期 30 天)')
        print('  reuse:   再利用率 (access_count / 20)')
        print('  chain:   因果鍊活性 (上下游 active 占比)')
        print('  refute:  被 contradicts 關係否定時 -0.5')
        print()
        print('排程建議: 每小時執行一次')
        print('  0 * * * * ethan /opt/BeakCortex/venv/bin/python /opt/BeakCortex/core/vitality.py --recalc')
        sys.exit(1)

    args = parser.parse_args()

    config_path = args.config
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    init_engine(config_path)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )

    if args.recalc:
        if args.verbose:
            print('vitality_score 重算開始...')
        count = recalc_all(verbose=args.verbose)
        print(f'完成: {count} 筆原子已更新 vitality_score')
        _write_heartbeat()


if __name__ == '__main__':
    main()
