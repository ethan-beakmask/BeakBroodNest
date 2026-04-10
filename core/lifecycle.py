#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lifecycle 自動轉換引擎

轉換規則:
  active  -> aging     : vitality_score < 0.3
  aging   -> archived  : vitality_score < 0.1 且 aging 超過 AGING_GRACE_DAYS 天
  任何狀態 -> terminal  : 被 refutes 關係否定

所有轉換記錄寫入 lifecycle_transitions 表供稽核追溯。

使用方式:
  python lifecycle.py                 顯示說明
  python lifecycle.py --run           執行自動轉換
  python lifecycle.py --run -v        執行並顯示明細
  python lifecycle.py --dry-run       試跑不寫入
"""
import argparse
import sys
import os
import datetime
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope, get_engine, Base
from core.models import KnowledgeAtom, AtomRelation
from sqlalchemy import Integer, String, Text, DateTime, Index
from sqlalchemy.orm import Mapped, mapped_column

logger = logging.getLogger('beak_note.lifecycle')

HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'lifecycle'

# 轉換閾值
THRESHOLD_AGING = 0.3      # vitality < 此值: active -> aging
THRESHOLD_ARCHIVED = 0.1   # vitality < 此值 + 超過寬限天數: aging -> archived
AGING_GRACE_DAYS = 7       # aging 狀態至少持續這麼多天才會轉 archived


def _write_heartbeat(suffix=None):
    """正常完成時寫入 heartbeat 檔案"""
    name = f"{HEARTBEAT_BASE}_{suffix}.ok" if suffix else f"{HEARTBEAT_BASE}.ok"
    Path(os.path.join(HEARTBEAT_DIR, name)).write_text(
        datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


# ============================================================
# 轉換紀錄表
# ============================================================

class LifecycleTransition(Base):
    __tablename__ = 'lifecycle_transitions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    atom_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    from_lifecycle: Mapped[str] = mapped_column(String(20), nullable=False)
    to_lifecycle: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, default='')
    triggered_by: Mapped[str] = mapped_column(String(30), default='auto')
    vitality_at_transition: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now
    )

    __table_args__ = (
        Index('idx_transitions_atom', 'atom_id'),
        Index('idx_transitions_created', 'created_at'),
    )


def ensure_table():
    """確保 lifecycle_transitions 表存在"""
    engine = get_engine()
    LifecycleTransition.__table__.create(engine, checkfirst=True)


def run_transitions(dry_run=False, verbose=False):
    """執行所有自動轉換，回傳轉換筆數"""
    now = datetime.datetime.now()
    transitions = []

    with session_scope() as s:
        # 1. active -> aging (vitality < THRESHOLD_AGING)
        aging_candidates = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.lifecycle == 'active',
                KnowledgeAtom.vitality_score < THRESHOLD_AGING,
            )
            .all()
        )

        for atom in aging_candidates:
            transitions.append({
                'atom': atom,
                'from': 'active',
                'to': 'aging',
                'reason': f'vitality_score={atom.vitality_score:.4f} < {THRESHOLD_AGING}',
            })

        # 2. aging -> archived (vitality < THRESHOLD_ARCHIVED 且超過寬限天數)
        archived_candidates = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.lifecycle == 'aging',
                KnowledgeAtom.vitality_score < THRESHOLD_ARCHIVED,
            )
            .all()
        )

        for atom in archived_candidates:
            # 檢查是否有轉換紀錄來判斷 aging 持續時間
            last_transition = (
                s.query(LifecycleTransition)
                .filter(
                    LifecycleTransition.atom_id == atom.id,
                    LifecycleTransition.to_lifecycle == 'aging',
                )
                .order_by(LifecycleTransition.created_at.desc())
                .first()
            )

            if last_transition:
                days_aging = (now - last_transition.created_at).total_seconds() / 86400
            else:
                # 沒有轉換紀錄，用 updated_at 估算
                days_aging = (now - (atom.updated_at or now)).total_seconds() / 86400

            if days_aging >= AGING_GRACE_DAYS:
                transitions.append({
                    'atom': atom,
                    'from': 'aging',
                    'to': 'archived',
                    'reason': (f'vitality_score={atom.vitality_score:.4f} < {THRESHOLD_ARCHIVED}, '
                              f'aging {days_aging:.1f} 天 >= {AGING_GRACE_DAYS} 天'),
                })

        # 3. 被 refutes 否定 -> terminal
        refuted_atoms = (
            s.query(KnowledgeAtom)
            .join(
                AtomRelation,
                AtomRelation.to_atom_id == KnowledgeAtom.id,
            )
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                AtomRelation.relation_type == 'refutes',
            )
            .all()
        )

        for atom in refuted_atoms:
            transitions.append({
                'atom': atom,
                'from': atom.lifecycle,
                'to': 'terminal',
                'reason': '被 refutes 關係否定',
            })

        # 去重（同一原子可能同時命中多個規則，取最終狀態）
        seen = {}
        for t in transitions:
            aid = t['atom'].id
            if aid not in seen:
                seen[aid] = t
            else:
                # terminal 優先
                if t['to'] == 'terminal':
                    seen[aid] = t

        final_transitions = list(seen.values())

        if verbose or dry_run:
            prefix = '[DRY-RUN] ' if dry_run else ''
            for t in final_transitions:
                print(f"  {prefix}[{t['atom'].id:3d}] {t['atom'].title[:40]:<40s}  "
                      f"{t['from']} -> {t['to']}  ({t['reason']})")

        if not dry_run:
            for t in final_transitions:
                atom = t['atom']
                atom.lifecycle = t['to']

                record = LifecycleTransition(
                    atom_id=atom.id,
                    from_lifecycle=t['from'],
                    to_lifecycle=t['to'],
                    reason=t['reason'],
                    triggered_by='auto',
                    vitality_at_transition=atom.vitality_score,
                )
                s.add(record)

    return len(final_transitions)


def main():
    parser = argparse.ArgumentParser(
        description='BeakNote lifecycle 自動轉換引擎',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python lifecycle.py --run           執行自動轉換
  python lifecycle.py --run -v        執行並顯示明細
  python lifecycle.py --dry-run       試跑不寫入
        """
    )
    parser.add_argument('--run', action='store_true', help='執行自動轉換')
    parser.add_argument('--dry-run', action='store_true', help='試跑，不實際寫入')
    parser.add_argument('-v', '--verbose', action='store_true', help='顯示每筆轉換明細')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')

    if len(sys.argv) == 1:
        print('BeakNote lifecycle 自動轉換引擎')
        print()
        print('必要參數（擇一）:')
        print('  --run       執行自動轉換')
        print('  --dry-run   試跑，不實際寫入')
        print()
        print('選項:')
        print('  -v          顯示每筆轉換明細')
        print('  --config    組態檔路徑 (預設: ../config.ini)')
        print()
        print('轉換規則:')
        print(f'  active  -> aging    : vitality_score < {THRESHOLD_AGING}')
        print(f'  aging   -> archived : vitality_score < {THRESHOLD_ARCHIVED} 且 aging >= {AGING_GRACE_DAYS} 天')
        print(f'  *       -> terminal : 被 refutes 關係否定')
        print()
        print('排程建議: 緊跟在 vitality.py 之後執行')
        print('  5 * * * * ethan /opt/BeakNote/venv/bin/python /opt/BeakNote/core/lifecycle.py --run')
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

    ensure_table()

    if args.run or args.dry_run:
        is_dry = args.dry_run
        if args.verbose or is_dry:
            print(f'lifecycle 自動轉換{"(試跑)" if is_dry else ""}開始...')
        count = run_transitions(dry_run=is_dry, verbose=args.verbose or is_dry)
        print(f'完成: {count} 筆轉換{"(試跑，未寫入)" if is_dry else ""}')
        if not is_dry:
            _write_heartbeat()


if __name__ == '__main__':
    main()
