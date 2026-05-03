# -*- coding: utf-8 -*-
"""Conversation Map API: trace 列表與 trace 詳情"""
import re
import logging
from flask import Blueprint, request, jsonify
from core.db import get_engine
import sqlalchemy as sa

bp = Blueprint('conversation_map', __name__)
logger = logging.getLogger('beak_broodnest')

_RE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _raw_query(sql, params=None):
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(sa.text(sql), params or {})
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as e:
        err = str(e)
        if 'does not exist' in err or 'UndefinedColumn' in err:
            logger.debug('Column/table not found: %s', err[:120])
            return []
        raise


def _serialize(rows):
    import datetime
    out = []
    for row in rows:
        d = {}
        for k, v in row.items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                d[k] = v.isoformat()
            elif hasattr(v, '__str__') and not isinstance(v, (str, int, float, bool, type(None))):
                d[k] = str(v)
            else:
                d[k] = v
        out.append(d)
    return out


# ============================================================
# GET /api/conversation-map/traces
# ============================================================

@bp.route('/api/conversation-map/traces', methods=['GET'])
def list_traces():
    """列出 trace 清單（post-migration: 依 trace_id 分組；pre-migration: 依 conversation_id）"""
    project_path = request.args.get('project_path', '')
    limit = request.args.get('limit', 20, type=int)

    params = {'limit': limit}

    # post-migration 路徑：trace_id 欄位存在且有資料
    try:
        sql = """
            SELECT
                trace_id::text                                          AS trace_id,
                MIN(timestamp)                                          AS first_ts,
                MAX(timestamp)                                          AS last_ts,
                COUNT(*)                                                AS turn_count,
                array_agg(DISTINCT actor_id ORDER BY actor_id)
                    FILTER (WHERE actor_id IS NOT NULL)                 AS actors
            FROM conversation_turns
            WHERE trace_id IS NOT NULL
        """
        if project_path:
            sql += " AND project_path = :project_path"
            params['project_path'] = project_path
        sql += """
            GROUP BY trace_id
            ORDER BY MAX(timestamp) DESC
            LIMIT :limit
        """
        rows = _raw_query(sql, params)
        if rows:
            return jsonify(_serialize(rows))
    except Exception:
        pass

    # pre-migration fallback：以 conversation_id 視為 trace_id
    params2 = {'limit': limit}
    sql2 = """
        SELECT
            conversation_id::text   AS trace_id,
            MIN(timestamp)          AS first_ts,
            MAX(timestamp)          AS last_ts,
            COUNT(*)                AS turn_count,
            ARRAY[]::text[]         AS actors
        FROM conversation_turns
        WHERE 1=1
    """
    if project_path:
        sql2 += " AND project_path = :project_path"
        params2['project_path'] = project_path
    sql2 += """
        GROUP BY conversation_id
        ORDER BY MAX(timestamp) DESC
        LIMIT :limit
    """
    rows2 = _raw_query(sql2, params2)
    return jsonify(_serialize(rows2))


# ============================================================
# GET /api/conversation-map/trace/<trace_id>
# ============================================================

@bp.route('/api/conversation-map/trace/<trace_id>', methods=['GET'])
def get_trace(trace_id):
    """取得單一 trace 的所有 turn 詳情"""
    if not _RE_UUID.match(trace_id):
        return jsonify({'error': 'invalid trace_id format'}), 400

    # post-migration 路徑
    try:
        sql = """
            SELECT
                id, trace_id, parent_span_id, actor_id, span_kind,
                timestamp, usage_input_tokens, usage_output_tokens,
                role, tool_name
            FROM conversation_turns
            WHERE trace_id = CAST(:tid AS uuid)
            ORDER BY timestamp ASC NULLS LAST, turn_seq ASC
        """
        rows = _raw_query(sql, {'tid': trace_id})
        if rows:
            return jsonify({'turns': _serialize(rows)})
    except Exception as exc:
        logger.warning('get_trace post-migration failed: %s', exc)

    # pre-migration fallback：conversation_id 當 trace_id
    sql2 = """
        SELECT
            id,
            NULL::uuid                  AS trace_id,
            parent_uuid::uuid           AS parent_span_id,
            NULL                        AS actor_id,
            NULL                        AS span_kind,
            timestamp,
            usage_input_tokens,
            usage_output_tokens,
            role,
            tool_name
        FROM conversation_turns
        WHERE conversation_id = :cid
        ORDER BY timestamp ASC NULLS LAST, turn_seq ASC
    """
    rows2 = _raw_query(sql2, {'cid': trace_id})
    return jsonify({'turns': _serialize(rows2)})
