# -*- coding: utf-8 -*-
"""Observe API: pipeline runs, session logs, conversation stats"""
import logging
import os
from flask import Blueprint, request, jsonify
from core.db import get_engine

bp = Blueprint('observe', __name__)
logger = logging.getLogger('beak_broodnest')


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
    """列出已匯入的對話及統計。

    Query params:
        hide_zero_signals  -- '1' 過濾沒有 P1 訊號的對話（預設啟用）
    """
    limit = request.args.get('limit', 50, type=int)
    project = request.args.get('project', '')
    hide_zero = request.args.get('hide_zero_signals', '1') in ('1', 'true', 'yes')

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
    if hide_zero:
        sql += """
            AND EXISTS (
                SELECT 1 FROM conversation_turns ct
                WHERE ct.conversation_id = c.id AND ct.p1_signals IS NOT NULL
            )
        """
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

_P2_PROMPT_PREFIXES = (
    '請對以下 topic 產出結構化摘要',
    '[CC-LAUNCH-KIND=p2-dispatcher]',
)


def _is_p2_dispatcher_mention(m):
    """判定 mention 是否來自 P2 dispatcher 灌入的 prompt（regex 命中『請對以下 topic』）"""
    text = (m.get('text') or '').lstrip()
    return any(text.startswith(p) for p in _P2_PROMPT_PREFIXES)


@bp.route('/api/observe/reviews', methods=['GET'])
def reviews():
    """列出 P3 復盤分析結果。

    Query params:
        hide_p2_dispatcher  -- '1' 過濾 P2 摘要器灌入的「請對以下 topic」提及（預設啟用）
    """
    import os, json as jsonlib
    hide_p2 = request.args.get('hide_p2_dispatcher', '1') in ('1', 'true', 'yes')
    install_dir = os.environ.get('BBN_INSTALL_DIR') or '/opt/BeakBroodNest'
    results_dir = os.path.join(install_dir, 'data/reviews')
    items = []
    if os.path.isdir(results_dir):
        for fname in sorted(os.listdir(results_dir), reverse=True):
            if fname.startswith('_') or not fname.endswith('.json'):
                continue
            fpath = os.path.join(results_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = jsonlib.load(f)
                if hide_p2 and isinstance(data.get('user_mentions'), list):
                    data['user_mentions'] = [
                        m for m in data['user_mentions']
                        if not _is_p2_dispatcher_mention(m)
                    ]
                items.append(data)
            except Exception:
                continue
    return jsonify(items)


@bp.route('/api/observe/reviews/global-stats', methods=['GET'])
def review_global_stats():
    """全域技術統計"""
    import json as jsonlib
    install_dir = os.environ.get('BBN_INSTALL_DIR') or '/opt/BeakBroodNest'
    fpath = os.path.join(install_dir, 'data/reviews/_global_stats.json')
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


# ============================================================
# Backlog -- 待辦清單(AI atom + 人類 entry 兩源整合)
# ============================================================

_BACKLOG_SQL = """
WITH unified AS (
    -- AI atom 來源:tag='待辦' 的 knowledge_atoms
    SELECT
        'atom'::text AS source,
        ka.id AS row_id,
        ka.title AS title,
        ka.atom_type AS atom_type,
        ka.lifecycle AS lifecycle,
        NULL::text AS entry_status,
        ka.vitality_score AS vitality_score,
        ka.owner AS owner,
        ka.updated_at AS updated_at,
        ka.created_at AS created_at,
        ARRAY(
            SELECT ca.canvas_id FROM canvas_atoms ca
            JOIN canvases c ON c.id = ca.canvas_id
            WHERE ca.atom_id = ka.id AND c.is_archived = false AND c.is_project = true
        ) AS canvas_ids,
        (
            SELECT COUNT(*) FROM atom_relations ar
            WHERE ar.to_atom_id = ka.id
              AND ar.relation_type = 'blocks'
        ) AS blocker_count,
        ka.id AS atom_id,
        NULL::int AS entry_id,
        NULL::int AS schema_id
    FROM knowledge_atoms ka
    WHERE ka.is_deleted = false
      AND ka.id IN (
          SELECT at_.atom_id FROM atom_tags at_
          JOIN tags t ON t.id = at_.tag_id
          WHERE t.name = '待辦'
      )

    UNION ALL

    -- 人類 entry 來源:schema=task 的 atom_entries
    SELECT
        'entry'::text AS source,
        ae.id AS row_id,
        COALESCE(NULLIF(ae.summary, ''), LEFT(ae.raw_text, 80)) AS title,
        'task'::text AS atom_type,
        NULL::text AS lifecycle,
        efv_status.value AS entry_status,
        ka.vitality_score AS vitality_score,
        ka.owner AS owner,
        ae.updated_at AS updated_at,
        ae.created_at AS created_at,
        ARRAY(
            SELECT ca.canvas_id FROM canvas_atoms ca
            JOIN canvases c ON c.id = ca.canvas_id
            WHERE ca.atom_id = ae.atom_id AND c.is_archived = false AND c.is_project = true
        ) AS canvas_ids,
        (
            SELECT COUNT(*) FROM unified_relations ur
            WHERE ur.to_entry_id = ae.id
              AND ur.relation_type = 'blocks'
              AND ur.is_deleted = false
        ) AS blocker_count,
        ka.id AS atom_id,
        ae.id AS entry_id,
        ae.schema_id AS schema_id
    FROM atom_entries ae
    JOIN knowledge_atoms ka ON ka.id = ae.atom_id
    LEFT JOIN entry_field_values efv_status
      ON efv_status.entry_id = ae.id
     AND efv_status.field_id = (
         SELECT id FROM entry_schema_fields
         WHERE schema_id = 2 AND name = 'status' LIMIT 1
     )
    WHERE ae.schema_id = 2
      AND ka.is_deleted = false
)
SELECT
    source, row_id, title, atom_type, lifecycle, entry_status,
    vitality_score, owner, updated_at, created_at,
    canvas_ids, blocker_count, atom_id, entry_id, schema_id,
    CASE
        WHEN source = 'atom' AND lifecycle = 'archived' THEN 'archived'
        WHEN source = 'entry' AND entry_status = 'completed' THEN 'archived'
        WHEN blocker_count > 0 THEN 'blocked'
        ELSE 'active'
    END AS unified_state
FROM unified
WHERE 1=1
"""


@bp.route('/api/observe/backlog', methods=['GET'])
def backlog():
    """待辦清單:AI atom(tag=待辦) + 人類 entry(schema=task) 兩源整合。

    Query params:
        tab     -- 'active' | 'blocked' | 'archived'(預設 active)
        source  -- 'atom' | 'entry' | ''(全部)
        owner   -- 'claude' | 'ethan' | ''(全部)
        project -- canvas_id(int) | 'unassigned'(無專案) | ''(全部)
        atom_type -- 多選 csv,如 'A,B,F';只對 source=atom 有效
    """
    tab = request.args.get('tab', 'active')
    if tab not in ('active', 'blocked', 'archived'):
        tab = 'active'
    source_f = request.args.get('source', '').strip()
    owner_f = request.args.get('owner', '').strip()
    project_f = request.args.get('project', '').strip()
    type_f = request.args.get('atom_type', '').strip()

    sql = _BACKLOG_SQL
    params = {}

    # 外層套篩選
    sql = f"SELECT * FROM ({sql}) bk WHERE bk.unified_state = :tab"
    params['tab'] = tab

    if source_f in ('atom', 'entry'):
        sql += " AND bk.source = :source"
        params['source'] = source_f

    if owner_f:
        sql += " AND bk.owner = :owner"
        params['owner'] = owner_f

    if project_f == 'unassigned':
        sql += " AND cardinality(bk.canvas_ids) = 0"
    elif project_f:
        try:
            cid = int(project_f)
            sql += " AND :canvas_id = ANY(bk.canvas_ids)"
            params['canvas_id'] = cid
        except ValueError:
            pass  # 非合法 canvas_id 視為不過濾

    if type_f:
        type_list = [t.strip() for t in type_f.split(',') if t.strip()]
        if type_list:
            sql += " AND (bk.source = 'entry' OR bk.atom_type = ANY(:types))"
            params['types'] = type_list

    sql += " ORDER BY bk.blocker_count DESC, bk.vitality_score DESC NULLS LAST, bk.updated_at DESC"

    rows = _raw_query(sql, params)
    return jsonify(_serialize(rows))


@bp.route('/api/observe/backlog/counts', methods=['GET'])
def backlog_counts():
    """三個 tab 的計數 + 篩選器選項(供前端建立)。

    回傳:
        counts: {active, blocked, archived}
        projects: [{id, name, slug}, ...]  -- is_project=true 的白板清單
    """
    counts_sql = f"SELECT bk.unified_state, COUNT(*) AS cnt FROM ({_BACKLOG_SQL}) bk GROUP BY bk.unified_state"
    rows = _raw_query(counts_sql)
    counts = {'active': 0, 'blocked': 0, 'archived': 0}
    for r in rows:
        if r['unified_state'] in counts:
            counts[r['unified_state']] = r['cnt']

    proj_rows = _raw_query("""
        SELECT id, name, slug FROM canvases
        WHERE is_archived = false AND is_project = true
        ORDER BY name
    """)
    projects = [{'id': r['id'], 'name': r['name'], 'slug': r['slug']} for r in proj_rows]

    return jsonify({'counts': counts, 'projects': projects})
