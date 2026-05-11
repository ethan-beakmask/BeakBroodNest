#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase (a) schema migration：把 task schema 升級成三層時間 + 暫停/取消/重啟支援。

執行：
    /opt/BeakBroodNest/venv/bin/python /opt/BeakBroodNest/scripts/migrate_task_baseline.py [--dry-run]

冪等：欄位若已存在 / 已是新值，會略過該步驟。

變更內容：
  1. baseline_start / baseline_end：field_type date -> datetime
  2. status options：["pending","in_progress","done"]
       -> ["planning","in_progress","paused","completed","cancelled"]
  3. 新增 pause_log / cancel_info / reopen_log（text 型存 JSON）
  4. 既有 atom_field_values backfill：
       pending -> planning
       done    -> completed
       baseline_start/end 空白且 planned_start/end 有值 -> 複製
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from core.db import init_engine, get_engine


# === 期望最終狀態 ===
TASK_STATUS_OPTIONS = ['planning', 'in_progress', 'paused', 'completed', 'cancelled']

NEW_JSON_FIELDS = [
    # (name, label, sort_order)
    ('pause_log',   '暫停紀錄', 14),
    ('cancel_info', '取消資訊', 15),
    ('reopen_log',  '重啟紀錄', 16),
]


def main():
    dry_run = '--dry-run' in sys.argv
    init_engine(str(Path(__file__).resolve().parent.parent / 'config.ini'))
    engine = get_engine()

    with engine.begin() as conn:
        task_schema_id = conn.execute(
            text("SELECT id FROM entry_schemas WHERE code = 'task'")
        ).scalar()
        if not task_schema_id:
            print('找不到 task schema，沒事可做。')
            return
        print(f'task schema id = {task_schema_id}')

        # === 1. baseline_start / baseline_end 型別改 datetime ===
        for fname in ('baseline_start', 'baseline_end'):
            row = conn.execute(text(
                'SELECT id, field_type FROM entry_schema_fields '
                'WHERE schema_id = :sid AND name = :n'
            ), {'sid': task_schema_id, 'n': fname}).first()
            if not row:
                print(f'  [skip] {fname} 不存在')
                continue
            if row.field_type == 'datetime':
                print(f'  [skip] {fname} 已是 datetime')
                continue
            print(f'  [+] {fname}: {row.field_type} -> datetime')
            if not dry_run:
                conn.execute(text(
                    "UPDATE entry_schema_fields SET field_type = 'datetime' "
                    'WHERE id = :id'
                ), {'id': row.id})

        # === 2. status options 升級 ===
        status_row = conn.execute(text(
            "SELECT id, options FROM entry_schema_fields "
            "WHERE schema_id = :sid AND name = 'status'"
        ), {'sid': task_schema_id}).first()
        if status_row:
            try:
                current = json.loads(status_row.options) if status_row.options else []
            except json.JSONDecodeError:
                current = []
            if set(current) == set(TASK_STATUS_OPTIONS):
                print('  [skip] status options 已是新版')
            else:
                print(f'  [+] status options: {current} -> {TASK_STATUS_OPTIONS}')
                if not dry_run:
                    conn.execute(text(
                        'UPDATE entry_schema_fields SET options = :opts '
                        'WHERE id = :id'
                    ), {'opts': json.dumps(TASK_STATUS_OPTIONS), 'id': status_row.id})

        # === 3. 新增 JSON 欄位（pause_log / cancel_info / reopen_log） ===
        for fname, flabel, fsort in NEW_JSON_FIELDS:
            exists = conn.execute(text(
                'SELECT 1 FROM entry_schema_fields '
                'WHERE schema_id = :sid AND name = :n'
            ), {'sid': task_schema_id, 'n': fname}).first()
            if exists:
                print(f'  [skip] {fname} 已存在')
                continue
            print(f'  [+] 新增 {fname} ({flabel})')
            if not dry_run:
                conn.execute(text(
                    'INSERT INTO entry_schema_fields '
                    '(schema_id, name, label, field_type, options, default_value, '
                    ' required, sort_order, dimension, is_frozen) '
                    "VALUES (:sid, :n, :l, 'text', '', NULL, "
                    ' false, :so, NULL, false)'
                ), {'sid': task_schema_id, 'n': fname, 'l': flabel, 'so': fsort})

        # === 3b. baseline_*：把 value_date 搬到 value_datetime（型別改了之後讀的欄位變） ===
        # 此步驟必須在型別改完之後做，且只搬還沒搬過的（value_datetime 為 null 才搬）
        for fname in ('baseline_start', 'baseline_end'):
            fid = conn.execute(text(
                'SELECT id FROM entry_schema_fields '
                'WHERE schema_id = :sid AND name = :n'
            ), {'sid': task_schema_id, 'n': fname}).scalar()
            if not fid:
                continue
            cnt = conn.execute(text(
                'SELECT COUNT(*) FROM entry_field_values '
                'WHERE field_id = :fid '
                '  AND value_date IS NOT NULL AND value_datetime IS NULL'
            ), {'fid': fid}).scalar()
            if cnt:
                print(f'  [+] {fname} value_date -> value_datetime: {cnt} 筆')
                if not dry_run:
                    conn.execute(text(
                        'UPDATE entry_field_values '
                        'SET value_datetime = value_date::timestamp, value_date = NULL '
                        'WHERE field_id = :fid '
                        '  AND value_date IS NOT NULL AND value_datetime IS NULL'
                    ), {'fid': fid})
            else:
                print(f'  [skip] {fname} 無 date 值需搬移')

        # === 4. backfill entry_field_values ===
        # 4a. status 名稱遷移
        for old, new in (('pending', 'planning'), ('done', 'completed')):
            cnt = conn.execute(text(
                'SELECT COUNT(*) FROM entry_field_values efv '
                'JOIN entry_schema_fields esf ON esf.id = efv.field_id '
                'WHERE esf.schema_id = :sid AND esf.name = :n AND efv.value = :old'
            ), {'sid': task_schema_id, 'n': 'status', 'old': old}).scalar()
            if cnt:
                print(f'  [+] backfill status {old} -> {new}: {cnt} 筆')
                if not dry_run:
                    conn.execute(text(
                        'UPDATE entry_field_values efv SET value = :new '
                        'FROM entry_schema_fields esf '
                        'WHERE esf.id = efv.field_id AND esf.schema_id = :sid '
                        "AND esf.name = 'status' AND efv.value = :old"
                    ), {'sid': task_schema_id, 'new': new, 'old': old})
            else:
                print(f'  [skip] 沒有 status={old} 需要遷移')

        # 4b. baseline_start/end 空白時複製 planned_start/end (都是 datetime)
        for base_name, plan_name in (
            ('baseline_start', 'planned_start'),
            ('baseline_end',   'planned_end'),
        ):
            base_field_id = conn.execute(text(
                'SELECT id FROM entry_schema_fields '
                'WHERE schema_id = :sid AND name = :n'
            ), {'sid': task_schema_id, 'n': base_name}).scalar()
            plan_field_id = conn.execute(text(
                'SELECT id FROM entry_schema_fields '
                'WHERE schema_id = :sid AND name = :n'
            ), {'sid': task_schema_id, 'n': plan_name}).scalar()
            if not base_field_id or not plan_field_id:
                continue

            # 找出「有 planned datetime 值、但 baseline 還沒值」的 entries
            missing = conn.execute(text(
                'SELECT plan.entry_id, plan.value, plan.value_datetime '
                'FROM entry_field_values plan '
                'LEFT JOIN entry_field_values base '
                '  ON base.entry_id = plan.entry_id AND base.field_id = :bfid '
                'WHERE plan.field_id = :pfid '
                '  AND plan.value_datetime IS NOT NULL '
                '  AND (base.id IS NULL OR base.value_datetime IS NULL)'
            ), {'bfid': base_field_id, 'pfid': plan_field_id}).fetchall()

            if not missing:
                print(f'  [skip] {base_name} backfill 無需處理')
                continue

            print(f'  [+] backfill {base_name} <- {plan_name}: {len(missing)} 筆')
            if dry_run:
                continue
            for r in missing:
                conn.execute(text(
                    'INSERT INTO entry_field_values (entry_id, field_id, value, value_datetime) '
                    'VALUES (:eid, :fid, :v, :vdt) '
                    'ON CONFLICT (entry_id, field_id) DO UPDATE '
                    'SET value = EXCLUDED.value, value_datetime = EXCLUDED.value_datetime'
                ), {'eid': r.entry_id, 'fid': base_field_id, 'v': r.value, 'vdt': r.value_datetime})

        # === 5. 補齊 value_datetime：value 有 ISO 字串但 value_datetime 為 NULL ===
        # 過去存檔流程偶爾沒寫入 typed 欄位，導致 gantt 讀取時看不到值。
        dt_field_ids = conn.execute(text(
            'SELECT id FROM entry_schema_fields '
            "WHERE schema_id = :sid AND field_type = 'datetime'"
        ), {'sid': task_schema_id}).fetchall()
        dt_field_ids = [r.id for r in dt_field_ids]
        if dt_field_ids:
            dirty = conn.execute(text(
                'SELECT id, value FROM entry_field_values '
                'WHERE field_id = ANY(:fids) '
                "  AND value IS NOT NULL AND value != '' AND value_datetime IS NULL"
            ), {'fids': dt_field_ids}).fetchall()
            fixed = 0
            for r in dirty:
                try:
                    import datetime as _dt
                    dt = _dt.datetime.fromisoformat(r.value)
                except ValueError:
                    continue
                fixed += 1
                if not dry_run:
                    conn.execute(text(
                        'UPDATE entry_field_values SET value_datetime = :v WHERE id = :id'
                    ), {'v': dt, 'id': r.id})
            if fixed:
                print(f'  [+] 修補 value_datetime 缺漏: {fixed} 筆')
            else:
                print('  [skip] value_datetime 無缺漏')

            # 反向：value_datetime 有值但 value 空白，回填文字版（gantt 讀的是 value）
            inverse = conn.execute(text(
                'SELECT id, value_datetime FROM entry_field_values '
                'WHERE field_id = ANY(:fids) '
                "  AND value_datetime IS NOT NULL AND (value IS NULL OR value = '')"
            ), {'fids': dt_field_ids}).fetchall()
            if inverse:
                print(f'  [+] 回填 value 文字版: {len(inverse)} 筆')
                if not dry_run:
                    for r in inverse:
                        conn.execute(text(
                            'UPDATE entry_field_values SET value = :v WHERE id = :id'
                        ), {'v': r.value_datetime.isoformat(timespec='minutes'), 'id': r.id})
            else:
                print('  [skip] value 文字版無缺漏')

    print('完成。' + (' (dry-run, 未實際寫入)' if dry_run else ''))


if __name__ == '__main__':
    main()
