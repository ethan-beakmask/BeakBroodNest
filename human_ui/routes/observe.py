# -*- coding: utf-8 -*-
"""Observe API: pipeline runs, session logs, conversation stats"""
import logging
import os
from flask import Blueprint, request, jsonify
from core.db import get_engine

bp = Blueprint('observe', __name__)
logger = logging.getLogger('beak_cortex')


def _raw_query(sql, params=None):
    """執行 raw SQL 並回傳 list of dict。表不存在時回傳空列表。"""
    engine = get_engine()
    try:
        with engine.connect() as conn:
            result = conn.execute(sql if hasattr(sql, 'text') else __import__('sqlalchemy').text(sql),
                                  params or {})
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in result.fetchall()]
    except Exception as e:
        err_msg = str(e)
        if 'UndefinedTable' in err_msg or 'does not exist' in err_msg:
            logger.debug(f'Table not found, returning empty: {err_msg[:100]}')
            return []
        raise


def _serialize(rows):
    """將 datetime 等不可 JSON 序列化的型別轉為字串"""
    import datetime
    result = []
    for row in rows:
        d = {}
        for k, v in row.items():
            if isinstance(v, (datetime.datetime, datetime.date)):
                d[k] = v.isoformat()
            else:
                d[k] = v
        result.append(d)
    return result


# ============================================================
# Pipeline Runs API
# ============================================================

@bp.route('/api/observe/pipeline-runs', methods=['GET'])
def pipeline_runs():
    """列出 pipeline 執行記錄"""
    limit = request.args.get('limit', 50, type=int)
    status = request.args.get('status', '')

    sql = """
        SELECT id, pipeline_name, trigger_type, session_id, conversation_id,
               stages, current_stage, status, started_at, completed_at,
               error_detail, total_turns_processed, signals_found, topics_generated
        FROM pipeline_runs
        WHERE 1=1
    """
    params = {}
    if status:
        sql += " AND status = :status"
        params['status'] = status
    sql += " ORDER BY started_at DESC LIMIT :limit"
    params['limit'] = limit

    rows = _raw_query(sql, params)
    return jsonify(_serialize(rows))


# ============================================================
# Session Logs API
# ============================================================

@bp.route('/api/observe/session-logs', methods=['GET'])
def session_logs():
    """列出 Claude 對話 session 記錄"""
    limit = request.args.get('limit', 50, type=int)
    project = request.args.get('project', '')

    sql = """
        SELECT id, session_id, project_path, trigger_type,
               started_at, ended_at, duration_seconds, summary,
               total_turns, total_input_tokens, total_output_tokens,
               atoms_created, atoms_updated, messages_sent,
               context_peak_pct, agent_count, agent_max_duration,
               error_count, abnormal, abnormal_reason
        FROM session_logs
        WHERE 1=1
    """
    params = {}
    if project:
        sql += " AND project_path LIKE :project"
        params['project'] = f'%{project}%'
    sql += " ORDER BY started_at DESC LIMIT :limit"
    params['limit'] = limit

    rows = _raw_query(sql, params)
    return jsonify(_serialize(rows))


# ============================================================
# Conversations 統計 API
# ============================================================

@bp.route('/api/observe/conversations', methods=['GET'])
def conversations():
    """列出已匯入的對話及統計"""
    limit = request.args.get('limit', 50, type=int)
    project = request.args.get('project', '')

    sql = """
        SELECT c.id, c.project_path, c.session_id, c.jsonl_path,
               c.total_turns, c.first_timestamp, c.last_timestamp,
               c.imported_at, c.p1_completed_at, c.p2_completed_at,
               (SELECT COUNT(*) FROM conversation_turns ct
                WHERE ct.conversation_id = c.id AND ct.p1_signals IS NOT NULL) as signal_count,
               (SELECT COALESCE(SUM(ct.usage_input_tokens), 0) FROM conversation_turns ct
                WHERE ct.conversation_id = c.id) as total_input_tokens,
               (SELECT COALESCE(SUM(ct.usage_output_tokens), 0) FROM conversation_turns ct
                WHERE ct.conversation_id = c.id) as total_output_tokens
        FROM conversations c
        WHERE 1=1
    """
    params = {}
    if project:
        sql += " AND c.project_path LIKE :project"
        params['project'] = f'%{project}%'
    sql += " ORDER BY c.last_timestamp DESC NULLS LAST LIMIT :limit"
    params['limit'] = limit

    rows = _raw_query(sql, params)
    return jsonify(_serialize(rows))


@bp.route('/api/observe/conversations/<conv_id>/signals', methods=['GET'])
def conversation_signals(conv_id):
    """取得單一對話的訊號詳情"""
    sql = """
        SELECT turn_seq, role, timestamp, content,
               tool_name, p1_signals, p2_topic_id,
               usage_input_tokens, usage_output_tokens, model
        FROM conversation_turns
        WHERE conversation_id = :conv_id AND p1_signals IS NOT NULL
        ORDER BY turn_seq
    """
    rows = _raw_query(sql, {'conv_id': conv_id})
    return jsonify(_serialize(rows))


# ============================================================
# P3 Review 結果 API
# ============================================================

@bp.route('/api/observe/reviews', methods=['GET'])
def reviews():
    """列出 P3 復盤分析結果"""
    import os, json as jsonlib
    results_dir = '/opt/BeakCortex/data/reviews'
    items = []
    if os.path.isdir(results_dir):
        for fname in sorted(os.listdir(results_dir), reverse=True):
            if fname.startswith('_') or not fname.endswith('.json'):
                continue
            fpath = os.path.join(results_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = jsonlib.load(f)
                items.append(data)
            except Exception:
                continue
    return jsonify(items)


@bp.route('/api/observe/reviews/global-stats', methods=['GET'])
def review_global_stats():
    """全域技術統計"""
    import json as jsonlib
    fpath = '/opt/BeakCortex/data/reviews/_global_stats.json'
    if os.path.isfile(fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            return jsonify(jsonlib.load(f))
    return jsonify({})


# ============================================================
# Dashboard 總覽統計
# ============================================================

@bp.route('/api/observe/stats', methods=['GET'])
def observe_stats():
    """觀察儀表板總覽統計"""
    stats = {}

    rows = _raw_query("SELECT COUNT(*) as cnt FROM conversations")
    stats['total_conversations'] = rows[0]['cnt'] if rows else 0

    rows = _raw_query("SELECT COUNT(*) as cnt FROM conversation_turns")
    stats['total_turns'] = rows[0]['cnt'] if rows else 0

    rows = _raw_query(
        "SELECT COUNT(*) as cnt FROM conversation_turns WHERE p1_signals IS NOT NULL"
    )
    stats['total_signals'] = rows[0]['cnt'] if rows else 0

    rows = _raw_query(
        "SELECT COUNT(*) as cnt FROM conversation_turns WHERE p2_summarized_at IS NOT NULL"
    )
    stats['total_summarized'] = rows[0]['cnt'] if rows else 0

    rows = _raw_query(
        "SELECT COUNT(*) as cnt FROM pipeline_runs"
    )
    stats['total_pipeline_runs'] = rows[0]['cnt'] if rows else 0

    rows = _raw_query(
        "SELECT COUNT(*) as cnt FROM pipeline_runs WHERE status = 'running'"
    )
    stats['running_pipelines'] = rows[0]['cnt'] if rows else 0

    rows = _raw_query(
        "SELECT COUNT(*) as cnt FROM session_logs"
    )
    stats['total_sessions'] = rows[0]['cnt'] if rows else 0

    # 訊號類型分布
    rows = _raw_query("""
        SELECT signal_type, COUNT(*) as cnt FROM (
            SELECT jsonb_array_elements(p1_signals)->>'type' as signal_type
            FROM conversation_turns
            WHERE p1_signals IS NOT NULL
        ) sub
        GROUP BY signal_type
        ORDER BY cnt DESC
    """)
    stats['signal_distribution'] = {r['signal_type']: r['cnt'] for r in rows}

    # 最近 7 天每日對話數
    rows = _raw_query("""
        SELECT DATE(last_timestamp) as day, COUNT(*) as cnt
        FROM conversations
        WHERE last_timestamp >= NOW() - INTERVAL '7 days'
        GROUP BY DATE(last_timestamp)
        ORDER BY day
    """)
    stats['daily_conversations'] = _serialize(rows)

    return jsonify(stats)
