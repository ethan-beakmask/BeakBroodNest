#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_schema_drift.py -- 比對 ORM model 定義 vs 實際 DB 的「欄位級」schema drift。

為什麼有這支:
  install.sh 升級時呼叫的 create_all_tables()（SQLAlchemy Base.metadata.create_all）
  只會建立「缺的表」，**不會**替既有表補上「後來新增的欄位」。因此:
    - 全新安裝：create_all 一次建出完整表，正常。
    - 舊機升級：model 後來加的欄位，DB 既有表沒有；而 ORM 查詢會 SELECT 所有
      mapped 欄位，只要少一個欄位，該表的任何查詢就整條 500。
  （實例：舊機 /beakbroodnest/ 首頁 500，因 canvases 表缺 model 後加的欄位。）

本工具把「哪張表缺哪個欄位」顯性列出，並可產生冪等的 ALTER 修補語句。

用法:
  python3 scripts/check_schema_drift.py              顯示本說明
  python3 scripts/check_schema_drift.py --check       列出所有缺欄位/缺表；有 drift 則 exit 1
  python3 scripts/check_schema_drift.py --emit-alter  對缺欄位產生 ALTER TABLE ... ADD COLUMN
                                                      IF NOT EXISTS 語句（印到 stdout，可導入 psql）
  python3 scripts/check_schema_drift.py --apply       直接執行上述 ALTER 補上缺欄位（冪等）；
                                                      install.sh 升級時會自動呼叫本模式自我修復
  --config <path>   指定 config.ini（預設專案根目錄的 config.ini）

說明:
  - 產生的 ALTER 一律「以可空欄位」補上（不帶 NOT NULL），確保既有列不會因缺 default 失敗；
    若某欄位語意上必須 NOT NULL，補完並回填後再自行 ALTER ... SET NOT NULL。
  - 「DB 有、model 沒有」的欄位只做提示（可能是尚未清掉的舊欄位），不會刪除。
  - 缺「整張表」的情況會標出來；那種 create_all_tables() 會自動建，通常不需手動處理。
"""
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def _load_metadata():
    # import 兩個 models 模組讓 Base.metadata 收齊所有表
    from core.db import Base
    import core.models  # noqa: F401
    try:
        from orchestrator import models as _om  # noqa: F401
    except Exception as e:
        print(f'[WARN] orchestrator.models 匯入失敗（略過其表）：{e}', file=sys.stderr)
    return Base


def _db_columns(conn, table):
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:t"
    ), {'t': table}).all()
    return {r[0] for r in rows}


def analyze(conn, Base):
    """回傳 (missing_tables, missing_cols, extra_cols)。
    missing_cols: list of (table, Column)
    extra_cols:   list of (table, colname)
    """
    missing_tables, missing_cols, extra_cols = [], [], []
    for table in Base.metadata.sorted_tables:
        db_cols = _db_columns(conn, table.name)
        if not db_cols:
            missing_tables.append(table.name)
            continue
        model_names = set()
        for col in table.columns:
            model_names.add(col.name)
            if col.name not in db_cols:
                missing_cols.append((table.name, col))
        for c in db_cols:
            if c not in model_names:
                extra_cols.append((table.name, c))
    return missing_tables, missing_cols, extra_cols


def emit_alter(engine, missing_cols):
    lines = []
    for table, col in missing_cols:
        coltype = col.type.compile(dialect=engine.dialect)
        # 一律可空，避免既有列因缺 default 破壞 ALTER
        lines.append(
            f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col.name} {coltype};'
        )
    return lines


def main():
    args = sys.argv[1:]
    if not args or '-h' in args or '--help' in args:
        print(__doc__)
        return 0

    config_path = os.path.join(PROJECT_ROOT, 'config.ini')
    if '--config' in args:
        config_path = args[args.index('--config') + 1]

    Base = _load_metadata()
    from core.db import init_engine, get_engine
    init_engine(config_path)
    engine = get_engine()

    with engine.connect() as conn:
        missing_tables, missing_cols, extra_cols = analyze(conn, Base)

    if '--emit-alter' in args:
        if not missing_cols:
            print('-- 無缺欄位，無需 ALTER')
            return 0
        print('-- 由 check_schema_drift.py 產生：補上 model 有、DB 缺的欄位（可空）')
        print('BEGIN;')
        for line in emit_alter(engine, missing_cols):
            print(line)
        print('COMMIT;')
        return 0

    if '--apply' in args:
        if not missing_cols:
            print('[OK] 無缺欄位，無需 ALTER')
            return 0
        from sqlalchemy import text
        stmts = emit_alter(engine, missing_cols)
        with engine.begin() as conn:
            for s in stmts:
                conn.execute(text(s))
        print(f'[OK] 已補上 {len(stmts)} 個缺欄位：')
        for t, col in missing_cols:
            print(f'  + {t}.{col.name}')
        return 0

    if '--check' in args:
        ok = not missing_tables and not missing_cols
        if missing_tables:
            print('[缺表]（create_all_tables 會自動建，通常免手動）：')
            for t in missing_tables:
                print(f'  - {t}')
        if missing_cols:
            print('[缺欄位]（會導致該表查詢 500，需補）：')
            for t, col in missing_cols:
                coltype = col.type.compile(dialect=engine.dialect)
                print(f'  - {t}.{col.name}  ({coltype})')
        if extra_cols:
            print('[DB 多出的欄位]（model 已無，僅提示，不處理）：')
            for t, c in extra_cols:
                print(f'  - {t}.{c}')
        if ok:
            print('[OK] ORM model 與 DB 欄位一致，無 schema drift')
            return 0
        print('\n=> 產生修補語句： python3 scripts/check_schema_drift.py --emit-alter')
        return 1

    print('未知參數。')
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
