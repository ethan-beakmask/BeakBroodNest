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
    """列出 trace 清單（post-migration: 依 trace_id 分組；pre-migration: 依 conversation_id）

    Query params:
        project_path     -- 過濾專案
        limit            -- 上限 (預設 100)
        with_agent       -- '1' 僅含 agent (cc-main:agent:%)
        with_ccp         -- '1' 僅含 cc-p 子代理 (cc-p:%)
        only_unanswered  -- '1' 真正無任何 assistant 回應（無 assistant_message 且無 tool_call）
        only_tool_only   -- '1' 僅 tool 互動但無 final assistant_message（agent 中斷類，#4158 盲點）
        min_turns        -- 最小 turn 數
    """
    project_path = request.args.get('project_path', '')
    limit = request.args.get('limit', 100, type=int)
    with_agent = request.args.get('with_agent', '') in ('1', 'true', 'yes')
    with_ccp = request.args.get('with_ccp', '') in ('1', 'true', 'yes')
    only_unanswered = request.args.get('only_unanswered', '') in ('1', 'true', 'yes')
    only_tool_only = request.args.get('only_tool_only', '') in ('1', 'true', 'yes')
    min_turns = request.args.get('min_turns', 0, type=int)

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
                    FILTER (WHERE actor_id IS NOT NULL)                 AS actors,
                COUNT(DISTINCT actor_id) FILTER
                    (WHERE actor_id LIKE 'cc-main:agent:%')             AS agent_count,
                BOOL_OR(span_kind = 'assistant_message')                 AS has_assistant,
                BOOL_OR(span_kind = 'tool_call')                         AS has_tool_call,
                BOOL_OR(actor_id LIKE 'cc-main:agent:%')                 AS has_agent,
                BOOL_OR(actor_id LIKE 'cc-p:%')                          AS has_ccp
            FROM conversation_turns
            WHERE trace_id IS NOT NULL
        """
        if project_path:
            sql += " AND project_path = :project_path"
            params['project_path'] = project_path
        sql += " GROUP BY trace_id"

        havings = []
        if with_agent:
            havings.append("BOOL_OR(actor_id LIKE 'cc-main:agent:%')")
        if with_ccp:
            havings.append("BOOL_OR(actor_id LIKE 'cc-p:%')")
        if only_unanswered:
            # 真正無任何 assistant 痕跡（連 tool_call 都沒有）
            havings.append(
                "NOT BOOL_OR(span_kind = 'assistant_message') "
                "AND NOT BOOL_OR(span_kind = 'tool_call')"
            )
        if only_tool_only:
            # 有 tool_call 但無 final assistant_message，常見於 agent 被中斷
            havings.append(
                "NOT BOOL_OR(span_kind = 'assistant_message') "
                "AND BOOL_OR(span_kind = 'tool_call')"
            )
        if min_turns > 0:
            havings.append("COUNT(*) >= :min_turns")
            params['min_turns'] = min_turns
        if havings:
            sql += " HAVING " + " AND ".join(havings)

        sql += " ORDER BY MAX(timestamp) DESC LIMIT :limit"
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
            ARRAY[]::text[]         AS actors,
            0                       AS agent_count,
            BOOL_OR(role = 'assistant') AS has_assistant,
            FALSE                   AS has_tool_call,
            FALSE                   AS has_agent,
            FALSE                   AS has_ccp
        FROM conversation_turns
        WHERE 1=1
    """
    if project_path:
        sql2 += " AND project_path = :project_path"
        params2['project_path'] = project_path
    sql2 += " GROUP BY conversation_id"
    havings2 = []
    if only_unanswered:
        havings2.append("NOT BOOL_OR(role = 'assistant')")
    if min_turns > 0:
        havings2.append("COUNT(*) >= :min_turns")
        params2['min_turns'] = min_turns
    # with_agent / with_ccp / only_tool_only 在 pre-migration 無法判斷 → 直接回空
    if with_agent or with_ccp or only_tool_only:
        return jsonify([])
    if havings2:
        sql2 += " HAVING " + " AND ".join(havings2)
    sql2 += " ORDER BY MAX(timestamp) DESC LIMIT :limit"
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
                id, turn_seq, trace_id, parent_span_id, actor_id, span_kind,
                timestamp, usage_input_tokens, usage_output_tokens,
                role, tool_name, is_sidechain,
                LEFT(COALESCE(content, ''), 4000) AS content,
                LENGTH(COALESCE(content, '')) AS content_full_len,
                tool_params
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
            id, turn_seq,
            NULL::uuid                  AS trace_id,
            parent_uuid::uuid           AS parent_span_id,
            NULL                        AS actor_id,
            NULL                        AS span_kind,
            timestamp,
            usage_input_tokens,
            usage_output_tokens,
            role,
            tool_name,
            is_sidechain,
            LEFT(COALESCE(content, ''), 4000) AS content,
            LENGTH(COALESCE(content, '')) AS content_full_len,
            tool_params
        FROM conversation_turns
        WHERE conversation_id = :cid
        ORDER BY timestamp ASC NULLS LAST, turn_seq ASC
    """
    rows2 = _raw_query(sql2, {'cid': trace_id})
    return jsonify({'turns': _serialize(rows2)})


@bp.route('/api/conversation-map/turn/<int:turn_id>', methods=['GET'])
def get_turn_full(turn_id):
    """取得單一 turn 的完整 content（不截斷）。供 node 點擊展開全文用。"""
    sql = """
        SELECT id, turn_seq, role, span_kind, tool_name, timestamp,
               usage_input_tokens, usage_output_tokens, actor_id,
               content, tool_params, is_sidechain
        FROM conversation_turns
        WHERE id = :tid
        LIMIT 1
    """
    rows = _raw_query(sql, {'tid': turn_id})
    if not rows:
        return jsonify({'error': 'turn not found'}), 404
    return jsonify(_serialize(rows)[0])
