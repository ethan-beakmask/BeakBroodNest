#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_reference_seed.py -- 從開發機 DB 產生 scripts/seed_reference.sql（參考資料種子）。

背景（為什麼有這支）:
  「UI 可見性依賴沒進版控的 DB 狀態」曾造成 bug -- 例如 nav_menu 的「閱覽器」
  只存在開發機、忘了寫進 seed，外部部署的選單就永遠少那一項；entry_schemas
  （;;物件 的物件類型）更是整組沒進 seed。這類「開發機正常、外部使用者靜默壞掉」
  的漏洞，靠人腦記憶手寫 seed 必然會再犯。

解法（翻轉來源）:
  讓開發機 DB 成為「參考資料」的唯一來源，seed 檔改成從 DB 自動產生的產物。
  push 前重新產生一次，git diff 就是 drift 偵測器：
    - diff 有變動 = 你有沒回寫的參考資料 → --write 後 commit
    - diff 乾淨   = 保證與版控同步
  如此「開發機獨有的參考列」在結構上不可能再存在。

白名單（WHITELIST）是唯一需要人腦判斷的地方:
  只有列在此的表會被匯出。新增參考表時必須「有意識地」加進來，
  把「漏 seed」從沉默失敗變成顯性決策。父表排前面（避免 FK 順序問題）。

永不匯出（刻意排除，勿加入白名單）:
  system_config      密鑰 / auth hash，install.sh 每台各自產生
  sensitive_terms    去敏詞庫，環境特定
  user_preferences   使用者個人設定
  以及所有對話 / 白板 / 上傳檔等使用者資料表

用法:
  python3 scripts/gen_reference_seed.py            顯示本說明
  python3 scripts/gen_reference_seed.py --check    重算但不寫檔；與現有檔比對，
                                                   有 drift 則列出差異並以 exit code 1 結束
  python3 scripts/gen_reference_seed.py --write     實際（重新）產生 seed_reference.sql
  python3 scripts/gen_reference_seed.py --stdout     把產生內容印到 stdout（不寫檔）

  --config <path>   指定 config.ini（預設專案根目錄的 config.ini）
"""
import sys
import os
from decimal import Decimal
from datetime import datetime, date

# 專案根目錄（本檔在 scripts/ 下）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# 白名單：只有這些表會被匯出。父表在前，子表在後（顧及 FK 插入順序）。
# 每個項目： (table, 說明) -- 說明僅寫進檔頭註解，方便閱讀。
# ---------------------------------------------------------------------------
WHITELIST = [
    ('atom_schemas',           'atom 動態 schema 定義'),
    ('schema_fields',          'atom schema 的欄位（FK -> atom_schemas）'),
    ('entry_schemas',          ';;物件 結構化物件類型（自由文字 / 待辦 / 記帳 ...）'),
    ('entry_schema_fields',    '結構化物件的欄位定義（FK -> entry_schemas）'),
    ('nav_menu',               '主選單項目'),
    ('relation_type_registry', '因果鍊關係類型'),
    ('tag_categories',         '標籤分類'),
    ('gantt_colors_default',   '甘特圖預設配色'),
]

OUTPUT_REL = 'scripts/seed_reference.sql'

# 明確禁止清單：即使誤加進 WHITELIST 也拒絕匯出（防呆，避免洩漏密鑰）。
FORBIDDEN = {'system_config', 'sensitive_terms', 'user_preferences'}


def _quote_str(s):
    return "'" + s.replace("'", "''") + "'"


def format_value(v):
    """把 Python 值格式化成 PostgreSQL 字面值。輸出需決定性（同輸入必同輸出）。"""
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, datetime):
        # 固定微秒 6 位，避免不同來源格式化不一致
        return _quote_str(v.strftime('%Y-%m-%d %H:%M:%S.%f'))
    if isinstance(v, date):
        return _quote_str(v.strftime('%Y-%m-%d'))
    if isinstance(v, (dict, list)):
        import json
        # sort_keys 保證同一 JSON 內容永遠序列化成同一字串
        return _quote_str(json.dumps(v, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')))
    if isinstance(v, (bytes, bytearray)):
        return "'\\x" + bytes(v).hex() + "'"
    return _quote_str(str(v))


def get_columns(conn, table):
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t ORDER BY ordinal_position"
    ), {'t': table}).all()
    return [r[0] for r in rows]


def get_pk_columns(conn, table):
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT a.attname "
        "FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = (:t)::regclass AND i.indisprimary "
        "ORDER BY array_position(i.indkey, a.attnum)"
    ), {'t': 'public.' + table}).all()
    return [r[0] for r in rows]


def has_id_sequence(conn, table):
    from sqlalchemy import text
    r = conn.execute(text("SELECT to_regclass(:s)"),
                     {'s': 'public.' + table + '_id_seq'}).scalar()
    return r is not None


def dump_table(conn, table):
    from sqlalchemy import text
    cols = get_columns(conn, table)
    if not cols:
        raise RuntimeError(f'表 {table} 不存在或無欄位')
    pk = get_pk_columns(conn, table)
    order_cols = pk if pk else cols  # 無 pk 時用全欄位排序，仍具決定性
    order_sql = ', '.join('"%s"' % c for c in order_cols)
    col_list = ', '.join(cols)
    rows = conn.execute(text(
        f'SELECT {col_list} FROM {table} ORDER BY {order_sql}'
    )).all()

    lines = []
    for row in rows:
        vals = ', '.join(format_value(v) for v in row)
        lines.append(
            f'INSERT INTO {table} ({col_list}) VALUES ({vals}) ON CONFLICT DO NOTHING;'
        )
    return cols, len(rows), lines


def build_sql(conn):
    header = [
        '-- =============================================================================',
        '-- BeakBroodNest 參考資料種子（seed_reference.sql）',
        '-- =============================================================================',
        '-- !!! 本檔為「產生檔」，請勿手動編輯 !!!',
        '-- 由 scripts/gen_reference_seed.py 從開發機 DB 自動產生。',
        '-- 要變更內容：改開發機 DB -> 執行 gen_reference_seed.py --write -> commit。',
        '-- push 前請跑 gen_reference_seed.py --check 確認無未回寫的 drift。',
        '--',
        '-- 涵蓋的參考表（白名單，父表在前）：',
    ]
    for t, desc in WHITELIST:
        header.append(f'--   {t:24s} {desc}')
    header += [
        '--',
        '-- 全部 INSERT 皆 ON CONFLICT DO NOTHING，可安全重複執行；',
        '-- 既有列不會被覆寫（只補缺列）。',
        '-- =============================================================================',
        '',
        'BEGIN;',
        '',
    ]

    body = []
    seq_lines = []
    for table, _desc in WHITELIST:
        if table in FORBIDDEN:
            raise RuntimeError(f'表 {table} 在禁止清單，不得匯出')
        cols, n, lines = dump_table(conn, table)
        body.append(f'-- ----- {table} ({n} 列) -----')
        body.extend(lines)
        body.append('')
        if 'id' in cols and has_id_sequence(conn, table):
            seq_lines.append(
                f"SELECT setval('{table}_id_seq', "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1));"
            )

    tail = []
    if seq_lines:
        tail.append('-- 重設 SERIAL 序列，確保下次 INSERT 不撞既有 id')
        tail.extend(seq_lines)
        tail.append('')
    tail.append('COMMIT;')
    tail.append('')

    return '\n'.join(header + body + tail)


def main():
    args = sys.argv[1:]
    if not args or '-h' in args or '--help' in args:
        print(__doc__)
        return 0

    config_path = os.path.join(PROJECT_ROOT, 'config.ini')
    if '--config' in args:
        i = args.index('--config')
        config_path = args[i + 1]

    from core.db import init_engine, get_engine
    init_engine(config_path)
    engine = get_engine()

    with engine.connect() as conn:
        sql = build_sql(conn)

    out_path = os.path.join(PROJECT_ROOT, OUTPUT_REL)

    if '--stdout' in args:
        sys.stdout.write(sql)
        return 0

    if '--write' in args:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(sql)
        print(f'[OK] 已寫入 {OUTPUT_REL}')
        return 0

    if '--check' in args:
        if not os.path.exists(out_path):
            print(f'[DRIFT] {OUTPUT_REL} 不存在；請先執行 --write')
            return 1
        with open(out_path, 'r', encoding='utf-8') as f:
            current = f.read()
        if current == sql:
            print(f'[OK] {OUTPUT_REL} 與開發機 DB 一致，無 drift')
            return 0
        # 印出行級差異，方便看出漏了哪些參考列
        import difflib
        diff = difflib.unified_diff(
            current.splitlines(), sql.splitlines(),
            fromfile=OUTPUT_REL + ' (版控現況)',
            tofile='開發機 DB 重算', lineterm='')
        print(f'[DRIFT] {OUTPUT_REL} 與開發機 DB 不一致：')
        for line in diff:
            print(line)
        print('\n=> 執行 gen_reference_seed.py --write 後 commit 以同步')
        return 1

    print('未知參數。')
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
