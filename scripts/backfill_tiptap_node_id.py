#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性回填腳本：為所有 knowledge_atoms.content_json 內的 Tiptap 結構性節點補 nodeId

設計原則
========
- 等冪：已有 nodeId 的節點不會被覆寫，可重複執行
- 結構性節點清單見 STRUCTURAL_NODE_TYPES（見原子 #4389 路線圖）
- 不更動 updated_at（PostgreSQL 該欄位無 trigger，UPDATE 不會自動更新）
- nodeId 來源：PostgreSQL sequence tiptap_node_id_seq（需先以 init_tiptap_node_id.sql 建立）

使用方式
========
無參數會顯示中文說明：
    /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/backfill_tiptap_node_id.py
    /opt/BeakBroodNest/venv/bin/python .../backfill_tiptap_node_id.py --dry-run
    /opt/BeakBroodNest/venv/bin/python .../backfill_tiptap_node_id.py --run
    /opt/BeakBroodNest/venv/bin/python .../backfill_tiptap_node_id.py --atom-id 4388 --run

Log: /opt/tmp/scripts-backfill_tiptap_node_id.log
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

from core.db import init_engine, get_engine  # noqa: E402


# 必須補 nodeId 的節點型別（見原子 #4389）
STRUCTURAL_NODE_TYPES = frozenset({
    # 自訂 extension
    'structuredEntry',
    'image',
    'imageAlbum',
    'htmlBlock',
    'pdfThumbnail',
    'pdfReader',
    'mermaidBlock',
    # Tiptap 內建（容器級）
    'heading',
    'table',
    'taskList',
    'taskItem',
    'bulletList',
    'orderedList',
    'blockquote',
    'codeBlock',
})


LOG_PATH = '/opt/tmp/scripts-backfill_tiptap_node_id.log'


def _ensure_log_dir() -> None:
    Path('/opt/tmp').mkdir(parents=True, exist_ok=True)


def _setup_logger() -> logging.Logger:
    _ensure_log_dir()
    logger = logging.getLogger('backfill_tiptap_node_id')
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S')
    fh = logging.FileHandler(LOG_PATH, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


class NodeIdAllocator:
    """nodeId 分配器：包裝 sequence nextval，dry-run 模式改用本地計數器（不動 DB）"""

    def __init__(self, conn, dry_run: bool):
        self._conn = conn
        self._dry_run = dry_run
        self._dry_counter = 0
        if dry_run:
            try:
                cur = conn.execute(text("SELECT last_value FROM tiptap_node_id_seq")).scalar()
                self._dry_counter = int(cur or 0)
            except Exception:
                self._dry_counter = 0

    def next(self) -> int:
        if self._dry_run:
            self._dry_counter += 1
            return self._dry_counter
        return int(self._conn.execute(text("SELECT nextval('tiptap_node_id_seq')")).scalar())

    def peek(self) -> int:
        if self._dry_run:
            return self._dry_counter
        return int(self._conn.execute(text("SELECT last_value FROM tiptap_node_id_seq")).scalar())


def walk_and_fill(node: dict, allocator: NodeIdAllocator, stats: dict) -> bool:
    """遞迴走訪 Tiptap 節點樹，為結構性節點補 nodeId。

    回傳 True 若有任何節點被補 ID。
    直接改 node dict（in-place），呼叫者要保證傳入是可變的副本。
    """
    changed = False
    if not isinstance(node, dict):
        return False

    node_type = node.get('type')
    if node_type in STRUCTURAL_NODE_TYPES:
        attrs = node.get('attrs')
        if not isinstance(attrs, dict):
            attrs = {}
            node['attrs'] = attrs
        if attrs.get('nodeId') is None:
            attrs['nodeId'] = allocator.next()
            stats['nodes_filled'] = stats.get('nodes_filled', 0) + 1
            stats.setdefault('by_type', {})
            stats['by_type'][node_type] = stats['by_type'].get(node_type, 0) + 1
            changed = True
        else:
            stats['nodes_skipped'] = stats.get('nodes_skipped', 0) + 1

    content = node.get('content')
    if isinstance(content, list):
        for child in content:
            if walk_and_fill(child, allocator, stats):
                changed = True

    return changed


def process_atom(conn, row, allocator: NodeIdAllocator, dry_run: bool, logger: logging.Logger) -> dict:
    """處理單一 atom，回傳此 atom 的統計。"""
    aid, content_json = row[0], row[1]
    stats = {'nodes_filled': 0, 'nodes_skipped': 0}

    if not isinstance(content_json, dict):
        return stats

    new_doc = deepcopy(content_json)
    changed = walk_and_fill(new_doc, allocator, stats)

    if changed and not dry_run:
        conn.execute(
            text('UPDATE knowledge_atoms SET content_json = CAST(:j AS jsonb) WHERE id = :id'),
            {'j': json.dumps(new_doc, ensure_ascii=False), 'id': aid},
        )

    if stats['nodes_filled'] > 0:
        logger.debug(f'  atom {aid}: 補 {stats["nodes_filled"]} 節點 (skip {stats["nodes_skipped"]})')

    return stats


def ensure_sequence_exists(conn, logger: logging.Logger) -> bool:
    exists = conn.execute(
        text("SELECT to_regclass('public.tiptap_node_id_seq') IS NOT NULL")
    ).scalar()
    if not exists:
        logger.error('sequence tiptap_node_id_seq 不存在，請先執行 scripts/init_tiptap_node_id.sql')
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description='為所有 knowledge_atoms.content_json 內的 Tiptap 結構性節點補 nodeId',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            '範例:\n'
            '  --dry-run            : 試跑，僅統計不寫 DB\n'
            '  --run                : 實際執行回填\n'
            '  --atom-id N --run    : 只處理單一 atom（測試用）\n'
            '  --atom-id N --dry-run: 試跑單一 atom\n'
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true', help='試跑，不寫 DB（會用本地計數模擬 nodeId）')
    mode.add_argument('--run', action='store_true', help='實際執行回填')
    parser.add_argument('--atom-id', type=int, default=None, help='僅處理單一 atom_id（測試用）')
    parser.add_argument('--config', type=str, default=str(Path(__file__).resolve().parent.parent / 'config.ini'))

    if len(sys.argv) == 1:
        parser.print_help(sys.stdout)
        sys.exit(0)

    args = parser.parse_args()
    dry_run = args.dry_run

    logger = _setup_logger()
    logger.info(f'啟動 backfill_tiptap_node_id (mode={"dry-run" if dry_run else "run"}, atom_id={args.atom_id})')

    init_engine(args.config)
    engine = get_engine()

    # 預檢
    with engine.connect() as conn:
        if not ensure_sequence_exists(conn, logger):
            sys.exit(2)
        seq_before = int(conn.execute(text('SELECT last_value FROM tiptap_node_id_seq')).scalar())
        logger.info(f'sequence tiptap_node_id_seq 當前 last_value = {seq_before}')

    sql = (
        'SELECT id, content_json FROM knowledge_atoms '
        'WHERE is_deleted = false AND content_json IS NOT NULL'
    )
    params = {}
    if args.atom_id is not None:
        sql += ' AND id = :aid'
        params['aid'] = args.atom_id
    sql += ' ORDER BY id'

    t0 = time.time()
    total_atoms = 0
    atoms_changed = 0
    total_filled = 0
    total_skipped = 0
    by_type_total: dict[str, int] = {}

    # 開單一交易（dry-run 結束 rollback；run 結束 commit）
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            allocator = NodeIdAllocator(conn, dry_run=dry_run)

            result = conn.execute(text(sql), params)
            rows = result.fetchall()
            total_atoms = len(rows)
            logger.info(f'撈到 {total_atoms} 個待掃描 atom')

            for i, row in enumerate(rows, 1):
                stats = process_atom(conn, row, allocator, dry_run, logger)
                if stats['nodes_filled'] > 0:
                    atoms_changed += 1
                    total_filled += stats['nodes_filled']
                    for t, c in stats.get('by_type', {}).items():
                        by_type_total[t] = by_type_total.get(t, 0) + c
                total_skipped += stats['nodes_skipped']
                if i % 50 == 0:
                    elapsed = time.time() - t0
                    rate = i / elapsed if elapsed > 0 else 0
                    logger.info(f'  進度 {i}/{total_atoms} ({100*i/total_atoms:.1f}%) rate={rate:.1f}/s')

            seq_after = allocator.peek()

            if dry_run:
                trans.rollback()
                logger.info('dry-run 結束，已 rollback')
            else:
                trans.commit()
                logger.info('已 commit')
        except Exception:
            trans.rollback()
            raise

    elapsed = time.time() - t0
    logger.info('=' * 60)
    logger.info(f'處理 atom 總數         : {total_atoms}')
    logger.info(f'有節點被補 ID 的 atom  : {atoms_changed}')
    logger.info(f'補上的節點數          : {total_filled}')
    logger.info(f'已有 nodeId 跳過數    : {total_skipped}')
    logger.info(f'sequence 目前值        : {seq_after}')
    logger.info(f'耗時                   : {elapsed:.1f}s')
    if by_type_total:
        logger.info('各型別補 ID 數:')
        for t, c in sorted(by_type_total.items(), key=lambda x: -x[1]):
            logger.info(f'  {t:20s} {c}')
    logger.info('=' * 60)


if __name__ == '__main__':
    main()
