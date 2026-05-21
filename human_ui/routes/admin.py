# -*- coding: utf-8 -*-
"""Admin: 系統管理頁面（資料表總覽等）。

/beakbroodnest/admin/tables           頁面
/beakbroodnest/api/admin/tables       JSON: 所有 public schema 的資料表清單，
                                   含 PG comment、筆數、最後寫入時間。
"""
import logging
import re

import datetime
import decimal
import json

from flask import Blueprint, jsonify, render_template, request

from core.db import get_engine
from sqlalchemy import text

bp = Blueprint('admin', __name__)
logger = logging.getLogger('beak_broodnest')


_IDENT_RE = re.compile(r'^[a-z_][a-z0-9_]*$')


# 探測「最後寫入時間」用的欄位白名單（嚴格白名單，未列入的欄位即使是 timestamp 也不採用）。
# 越前面越優先。原則：只放「代表此 row 被寫入或更新」的審計欄位，
# 排除業務語意欄位（如 expires_at / value_datetime / first_timestamp -- 那是業務值不是審計時間）。
_TS_COL_PRIORITY = [
    'updated_at',
    'changed_at',
    'last_accessed_at',
    'imported_at',
    'completed_at',
    'reviewed_at',
    'p2_completed_at',
    'p1_completed_at',
    'ended_at',
    'started_at',
    'dispatched_at',
    'uploaded_at',
    'deleted_at',
    'read_at',
    'created_at',
    'timestamp',  # conversation_turns：每輪對話發生時間，等同寫入時間
]


def _list_tables_with_meta():
    """從 pg_class / pg_attribute 一次取得：表名、kind、PG comment、所有 timestamp 欄位。

    relkind: r=table, v=view, m=matview。view/matview 也納入清單，
    未來新增 view 會自動出現，不必另外開分頁。

    回傳: list[dict]，每項含 name / kind / comment / ts_cols (list[str])
    """
    sql = text("""
        SELECT
            c.relname AS name,
            c.relkind AS relkind,
            COALESCE(obj_description(c.oid, 'pg_class'), '') AS comment,
            COALESCE(
                array_agg(a.attname ORDER BY a.attname)
                    FILTER (WHERE a.atttypid IN (1114, 1184)),
                ARRAY[]::name[]
            ) AS ts_cols
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_attribute a
               ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'v', 'm')
        GROUP BY c.relname, c.relkind, c.oid
        ORDER BY c.relname
    """)
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()

    kind_map = {'r': 'table', 'v': 'view', 'm': 'matview'}
    out = []
    for r in rows:
        out.append({
            'name': r.name,
            'kind': kind_map.get(r.relkind, r.relkind),
            'comment': r.comment,
            'ts_cols': list(r.ts_cols or []),
        })
    return out


def _pick_ts_col(ts_cols):
    """從一張表的 timestamp 欄位中挑一個當作「最後寫入時間」來源。
    嚴格白名單：未列入 _TS_COL_PRIORITY 的欄位一律不採用，
    避免把業務語意欄位（如 value_datetime / expires_at）誤當審計時間。
    """
    for cand in _TS_COL_PRIORITY:
        if cand in ts_cols:
            return cand
    return None


def _safe_ident(name):
    """白名單驗證 identifier，避免 SQL 注入。
    來源是 pg_class，理論上安全，但守一道。
    """
    if not _IDENT_RE.match(name or ''):
        raise ValueError(f'invalid identifier: {name}')
    return name


def _query_count_and_last_write(table_name, ts_col):
    """對單一表查 count(*) 與 max(ts_col)。失敗回傳 (None, None)。"""
    table_name = _safe_ident(table_name)
    if ts_col:
        ts_col = _safe_ident(ts_col)
        sql_str = (
            f'SELECT count(*) AS cnt, max("{ts_col}") AS last_write '
            f'FROM "{table_name}"'
        )
    else:
        sql_str = f'SELECT count(*) AS cnt, NULL::timestamptz AS last_write FROM "{table_name}"'

    engine = get_engine()
    try:
        with engine.connect() as conn:
            row = conn.execute(text(sql_str)).fetchone()
            cnt = int(row.cnt) if row.cnt is not None else 0
            lw = row.last_write
            return cnt, (lw.isoformat() if lw is not None else None)
    except Exception as e:
        logger.warning(f'count/max failed for {table_name}: {e}')
        return None, None


@bp.route('/admin/tables')
def admin_tables_page():
    """資料表總覽頁面"""
    return render_template('admin_tables.html')


@bp.route('/api/admin/tables')
def api_admin_tables():
    """回傳所有 public schema 資料表的清單 + meta。

    回傳格式:
      {
        "tables": [
          {
            "name": "knowledge_atoms",
            "comment": "核心原子表...",
            "ts_col": "updated_at",
            "row_count": 852,
            "last_write_at": "2026-04-29T01:14:16.604406"
          },
          ...
        ],
        "summary": {
            "total_tables": 40,
            "no_comment": 3,
            "stale_candidates": 5
        }
      }
    """
    tables_meta = _list_tables_with_meta()

    items = []
    no_comment = 0
    stale = 0

    for t in tables_meta:
        ts_col = _pick_ts_col(t['ts_cols'])
        cnt, last_write = _query_count_and_last_write(t['name'], ts_col)
        item = {
            'name': t['name'],
            'kind': t['kind'],
            'comment': t['comment'],
            'ts_col': ts_col or '',
            'all_ts_cols': t['ts_cols'],
            'row_count': cnt,
            'last_write_at': last_write,
        }
        items.append(item)
        if not t['comment']:
            no_comment += 1
        # 廢棄候選：筆數=0 且找不到任何寫入時間
        if (cnt == 0) and (last_write is None):
            stale += 1

    # knowledge_atoms 永遠置頂；其餘依表名字母序
    items.sort(key=lambda it: (0 if it['name'] == 'knowledge_atoms' else 1, it['name']))

    return jsonify({
        'tables': items,
        'summary': {
            'total_tables': len(items),
            'no_comment': no_comment,
            'stale_candidates': stale,
        },
    })


# ============================================================
# 單表最新 N 筆內容（給右側 panel 用）
# ============================================================

# 顯示時自動截斷的字串長度
_TEXT_PREVIEW_LEN = 100

# 不會出現在預設顯示列表的型別（仍會列在 columns metadata，但 row 資料不傳）
_SKIP_TYPES = {'vector'}

# 主要識別欄位優先序（顯示時排在 PK 之後、其他欄位之前）
_IDENTITY_COLS = ['title', 'name', 'code', 'label', 'subject']


def _table_columns(table_name):
    """取得欄位 metadata：name / type_name / is_text / is_json / is_vector / kind / display_priority"""
    sql = text("""
        SELECT a.attname AS name, t.typname AS type_name
        FROM pg_attribute a
        JOIN pg_type t ON t.oid = a.atttypid
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname='public' AND c.relname=:t
          AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY a.attnum
    """)
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, {'t': table_name}).fetchall()

    cols = []
    for r in rows:
        type_name = r.type_name
        is_vector = type_name == 'vector'
        is_json = type_name in ('jsonb', 'json')
        is_text = type_name in ('text', 'varchar', 'bpchar', 'name')
        is_bytea = type_name == 'bytea'
        cols.append({
            'name': r.name,
            'type': type_name,
            'is_vector': is_vector,
            'is_json': is_json,
            'is_text': is_text,
            'is_bytea': is_bytea,
            'kind': (
                'vector' if is_vector else
                'json' if is_json else
                'bytea' if is_bytea else
                'text' if is_text else
                'scalar'
            ),
        })
    return cols


def _table_primary_keys(table_name):
    """取得 primary key 欄位名稱列表（按 index 順序）"""
    sql = text("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname='public' AND c.relname=:t AND i.indisprimary
        ORDER BY array_position(i.indkey, a.attnum)
    """)
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(sql, {'t': table_name}).fetchall()
    return [r.attname for r in rows]


def _annotate_display_columns(cols, pk_names, ts_col):
    """標記欄位顯示優先順序與是否預設顯示。

    優先順序：PK → 識別欄位（title/name/code）→ ts_col → 其他
    is_default_visible：vector 不顯示；其他都顯示（text 會在資料層截斷）
    """
    pk_set = set(pk_names)
    annotated = []
    for c in cols:
        is_pk = c['name'] in pk_set
        is_identity = c['name'] in _IDENTITY_COLS
        is_ts = c['name'] == ts_col
        if is_pk:
            order = 0
        elif is_identity:
            order = 1
        elif is_ts:
            order = 2
        else:
            order = 3
        annotated.append({
            **c,
            'is_pk': is_pk,
            'is_identity': is_identity,
            'is_ts': is_ts,
            'is_default_visible': not c['is_vector'],
            'display_order': order,
        })
    annotated.sort(key=lambda x: (x['display_order'], x['name']))
    return annotated


def _serialize_value(val, col):
    """把 row 的單一欄位值轉成 JSON 安全 + 帶截斷標記。

    回傳: {value, truncated?, full_len?, summary?}
      - text 大於 _TEXT_PREVIEW_LEN：回傳截斷 + truncated=True + full_len
      - jsonb：回傳 {keys?, summary} 摘要 + 完整值另存於 _full
      - vector：不應走到（已在 SQL select 排除）
      - bytea：summary
      - 其他：直接傳
    """
    if val is None:
        return None
    if col['is_text']:
        if isinstance(val, str) and len(val) > _TEXT_PREVIEW_LEN:
            return {
                '_preview': val[:_TEXT_PREVIEW_LEN],
                '_truncated': True,
                '_full_len': len(val),
                '_full': val,
            }
        return val
    if col['is_json']:
        if isinstance(val, (dict, list)):
            if isinstance(val, dict):
                summary = f"{{{len(val)} keys}}"
            else:
                summary = f"[{len(val)} items]"
            return {
                '_preview': summary,
                '_truncated': True,
                '_full': val,
            }
        return val
    if col['is_bytea']:
        try:
            n = len(val) if val is not None else 0
        except TypeError:
            n = 0
        return {'_preview': f'[binary, {n} bytes]', '_truncated': False}
    if isinstance(val, (datetime.datetime, datetime.date)):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return str(val)
    if isinstance(val, (bytes, memoryview)):
        return f'[binary, {len(val)} bytes]'
    return val


@bp.route('/api/admin/tables/<name>/latest')
def api_admin_table_latest(name):
    """取得單一表的最新 N 筆資料（給右側內容 panel 用）。

    排序鍵：_pick_ts_col 結果 DESC；無 ts_col 則用 PK DESC；無 PK（極少見）則自然順序。
    自動排除 vector 欄位（避免 768 維噪音）。
    text 大於 100 字截斷，JSONB 顯示摘要，完整值供前端展開時讀取。

    回傳:
      {
        "table": "knowledge_atoms",
        "kind": "table",
        "comment": "...",
        "primary_keys": ["id"],
        "ts_col": "updated_at",
        "order_by": {"col": "updated_at", "dir": "DESC"} | null,
        "columns": [{name, type, kind, is_pk, is_identity, is_ts, is_default_visible, display_order}],
        "rows": [{col_name: value | {_preview, _truncated, _full, ...}}, ...]
      }
    """
    try:
        table_name = _safe_ident(name)
    except ValueError:
        return jsonify({'error': 'invalid table name'}), 400

    limit = request.args.get('limit', 30, type=int)
    # knowledge_atoms 是 admin 唯讀工具，放寬到 10000 並允許 limit=0 表示無上限；
    # 其餘表維持 200 安全上限避免誤撈大表。
    if table_name == 'knowledge_atoms':
        limit = max(0, min(limit, 10000))
    else:
        limit = max(1, min(limit, 200))

    # knowledge_atoms 專屬：owner=human 只顯示 ethan 自己寫的（過濾掉 1500+ AI 知識）
    owner_filter = request.args.get('owner', 'all')
    if owner_filter not in ('all', 'human'):
        owner_filter = 'all'

    # 確認表存在 + 取得 metadata
    tables_meta = _list_tables_with_meta()
    meta = next((t for t in tables_meta if t['name'] == table_name), None)
    if meta is None:
        return jsonify({'error': f'table {table_name} not found'}), 404

    cols = _table_columns(table_name)
    if not cols:
        return jsonify({'error': f'no columns for {table_name}'}), 404

    pk_names = _table_primary_keys(table_name)
    ts_col = _pick_ts_col(meta['ts_cols'])
    annotated_cols = _annotate_display_columns(cols, pk_names, ts_col)

    # 排序鍵
    if ts_col:
        order_clause = f'"{_safe_ident(ts_col)}" DESC NULLS LAST'
        order_by = {'col': ts_col, 'dir': 'DESC'}
    elif pk_names:
        # 多欄 PK 也用全部排，PK 應為 unique
        parts = ', '.join(f'"{_safe_ident(p)}" DESC' for p in pk_names)
        order_clause = parts
        order_by = {'col': '+'.join(pk_names), 'dir': 'DESC'}
    else:
        order_clause = None
        order_by = None

    # SELECT 欄位列表：排除 vector
    select_cols = [c for c in cols if c['type'] not in _SKIP_TYPES]
    if not select_cols:
        return jsonify({'error': f'{table_name} has no displayable columns'}), 500

    select_list = ', '.join(f'"{_safe_ident(c["name"])}"' for c in select_cols)
    sql_str = f'SELECT {select_list} FROM "{table_name}"'
    where_parts = []
    sql_params = {}
    if table_name == 'knowledge_atoms' and owner_filter == 'human':
        where_parts.append('owner = :owner_val')
        sql_params['owner_val'] = 'ethan'
    if where_parts:
        sql_str += ' WHERE ' + ' AND '.join(where_parts)
    if order_clause:
        sql_str += f' ORDER BY {order_clause}'
    if limit > 0:
        sql_str += f' LIMIT {limit}'

    # 順便算 filtered_count，讓前端能顯示「30 / 1312」這種比率
    filtered_count = None
    if table_name == 'knowledge_atoms':
        count_sql = f'SELECT count(*) FROM "{table_name}"'
        if where_parts:
            count_sql += ' WHERE ' + ' AND '.join(where_parts)

    engine = get_engine()
    rows_out = []
    try:
        with engine.connect() as conn:
            if table_name == 'knowledge_atoms':
                filtered_count = int(conn.execute(text(count_sql), sql_params).scalar() or 0)
            result = conn.execute(text(sql_str), sql_params)
            col_meta_by_name = {c['name']: c for c in cols}
            for row in result.fetchall():
                row_dict = {}
                for i, col_name in enumerate(result.keys()):
                    col_meta = col_meta_by_name.get(col_name)
                    val = row[i]
                    if col_meta is None:
                        # 不應發生
                        row_dict[col_name] = val
                    else:
                        row_dict[col_name] = _serialize_value(val, col_meta)
                rows_out.append(row_dict)
    except Exception as e:
        logger.warning(f'fetch latest rows failed for {table_name}: {e}')
        return jsonify({'error': f'query failed: {e}'}), 500

    return jsonify({
        'table': table_name,
        'kind': meta['kind'],
        'comment': meta['comment'],
        'primary_keys': pk_names,
        'ts_col': ts_col or '',
        'order_by': order_by,
        'columns': annotated_cols,
        'rows': rows_out,
        'returned': len(rows_out),
        'limit': limit,
        'owner_filter': owner_filter if table_name == 'knowledge_atoms' else None,
        'filtered_count': filtered_count,
    })

