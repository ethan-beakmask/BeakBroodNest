#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性回填腳本：對所有 knowledge_atoms 計算 content_plain。

執行：
    /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/backfill_content_plain.py

冪等：可重複執行，每次都會根據當下 content 重算。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from core.db import init_engine, get_engine
from core.html_strip import strip_html


def main():
    init_engine(str(Path(__file__).resolve().parent.parent / 'config.ini'))
    engine = get_engine()

    # 撈所有 atoms 的 id + content（含已軟刪除的，一視同仁回填）
    with engine.connect() as conn:
        rows = conn.execute(text(
            'SELECT id, content FROM knowledge_atoms ORDER BY id'
        )).fetchall()

    total = len(rows)
    print(f'共 {total} 筆需回填')

    updated = 0
    skipped = 0
    t0 = time.time()
    BATCH = 200

    with engine.begin() as conn:
        for i, row in enumerate(rows, 1):
            aid = row[0]
            content = row[1] or ''
            plain = strip_html(content)
            conn.execute(
                text('UPDATE knowledge_atoms SET content_plain = :p WHERE id = :id'),
                {'p': plain, 'id': aid},
            )
            updated += 1
            if i % BATCH == 0:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                print(f'  進度 {i}/{total} ({100*i/total:.1f}%)  rate={rate:.1f}/s')

    elapsed = time.time() - t0
    print(f'\n完成：更新 {updated} 筆，耗時 {elapsed:.1f}s')


if __name__ == '__main__':
    main()
