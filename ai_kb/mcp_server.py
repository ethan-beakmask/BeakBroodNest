#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex MCP Server -- AI 知識庫介面
讓 Claude Code 直接操作知識原子，取代 MEMORY.md 的讀寫流程

啟動方式:
  python mcp_server.py                    顯示說明
  python mcp_server.py --stdio            以 stdio 模式啟動（供 Claude Code 使用）
  python mcp_server.py --config path.ini  指定組態檔
"""
import argparse
import sys
import os
import json
import datetime
import logging
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP

from core.db import init_engine, session_scope
from core.models import (
    KnowledgeAtom, AtomRelation, Tag, atom_tags, Canvas, CanvasAtom,
    CanvasConnection, CanvasGroup,
    AtomSchema, SchemaField, AtomFieldValue,
)
from core import relations as rel_service
from core import consistency as consistency_service
from core import embeddings as embed_service
from orchestrator.models import WorkerTask, WorkerReport
from orchestrator import dispatcher as orch_dispatcher
from sqlalchemy import func, text as sa_text
from sqlalchemy.orm import joinedload

logger = logging.getLogger('beak_cortex.mcp')

# ============================================================
# MCP Server 定義
# ============================================================

mcp = FastMCP(
    "BeakCortex",
    instructions="知識白板與 AI 共用知識庫 -- 結構化知識存取，取代 MEMORY.md",
)


# ============================================================
# note_store -- 儲存知識原子
# ============================================================

@mcp.tool()
def note_store(
    title: str,
    content: str = '',
    atom_type: str = 'F',
    content_type: str = 'markdown',
    source: str = 'ai',
    source_detail: str = '',
    tags: list[str] | None = None,
    lifecycle: str = 'active',
    schema_id: int | None = None,
    field_values: dict[str, str] | None = None,
) -> str:
    """儲存一筆知識原子到知識庫。

    atom_type 分類:
      A=萬用  B=創意發散  C=思考過程/流程  D=總結歸納  E=套表  F=碎片
    lifecycle: active(活躍) / aging(老化) / archived(歸檔) / terminal(終止)
    source: human / ai / import / derived
    tags: 標籤名稱列表，不存在的標籤會自動建立
    schema_id: E 類型時關聯的 schema ID
    field_values: E 類型的結構化欄位值，格式 {"欄位name": "值"}

    回傳建立的原子 ID 與摘要。
    """
    valid_types = ('A', 'B', 'C', 'D', 'E', 'F')
    if atom_type not in valid_types:
        return json.dumps({'error': f'無效的 atom_type: {atom_type}，允許值: {", ".join(valid_types)}'})

    with session_scope() as s:
        # E 類型驗證 schema
        if atom_type == 'E' and schema_id:
            schema = s.query(AtomSchema).filter(AtomSchema.id == schema_id).first()
            if not schema:
                return json.dumps({'error': f'Schema {schema_id} 不存在'})

        atom = KnowledgeAtom(
            title=title,
            content=content,
            content_type=content_type,
            atom_type=atom_type,
            lifecycle=lifecycle,
            source=source,
            source_detail=source_detail,
            schema_id=schema_id,
        )
        s.add(atom)
        s.flush()

        # 處理標籤
        if tags:
            tag_objects = []
            for tag_name in tags:
                tag = s.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name, tag_type='tag')
                    s.add(tag)
                    s.flush()
                tag_objects.append(tag)
            atom.tags = tag_objects

        # 處理欄位值
        if field_values and schema_id:
            schema_fields = s.query(SchemaField).filter(
                SchemaField.schema_id == schema_id
            ).all()
            field_map = {f.name: f for f in schema_fields}
            for fname, fval in field_values.items():
                if fname in field_map:
                    s.add(AtomFieldValue(
                        atom_id=atom.id,
                        field_id=field_map[fname].id,
                        value=str(fval) if fval is not None else None,
                    ))

        s.flush()

        # Auto-embed（背景容錯，不阻塞回應）
        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for atom {atom.id}: {e}')

        result = {
            'id': atom.id,
            'title': atom.title,
            'atom_type': atom.atom_type,
            'lifecycle': atom.lifecycle,
            'tags': [t.name for t in atom.tags],
            'message': f'知識原子已建立 (id={atom.id})',
        }
        if schema_id:
            result['schema_id'] = schema_id
        if field_values:
            result['field_values'] = field_values
        return json.dumps(result, ensure_ascii=False)


# ============================================================
# note_search -- 搜尋知識原子
# ============================================================

@mcp.tool()
def note_search(
    query: str = '',
    atom_type: str = '',
    lifecycle: str = '',
    tag: str = '',
    tags: list[str] | None = None,
    source: str = '',
    schema_id: int | None = None,
    limit: int = 20,
    search_mode: str = 'keyword',
    sort: str = '',
) -> str:
    """搜尋知識庫中的原子。

    query: 關鍵字搜尋(ILIKE 匹配 + pg_trgm 相似度排序)
    atom_type: 篩選類型 (A/B/C/D/E/F)
    lifecycle: 篩選生命週期 (active/aging/archived/terminal)
    tag: 篩選單一標籤名稱(向下相容)
    tags: 多標籤 AND 篩選,原子必須同時擁有所有指定標籤
    source: 篩選來源 (human/ai/import/derived)
    schema_id: 篩選 E 類型的 schema ID
    limit: 回傳上限(預設 20,最大 100)
    search_mode: 搜尋模式
      keyword  -- ILIKE + pg_trgm(預設,向下相容)
      semantic -- pgvector 向量語意搜尋(需 query 非空)
      hybrid   -- 關鍵字 + 語意混合搜尋,召回率最高(需 query 非空)
    sort: 排序方式(空字串=依 search_mode 預設排序)
      vitality   -- 依 vitality_score 排序(高到低)
      created_at -- 依建立時間排序(新到舊)
      updated_at -- 依更新時間排序(新到舊)

    tag 與 tags 同時提供時,tag 會併入 tags 一起做 AND 篩選。
    semantic/hybrid 模式需要 query 非空,否則自動退回 keyword 模式。
    E 類型原子會附帶 field_values 結構化欄位值。
    """
    limit = min(limit, 100)

    if search_mode not in ('keyword', 'semantic', 'hybrid'):
        search_mode = 'keyword'
    if search_mode in ('semantic', 'hybrid') and not query.strip():
        search_mode = 'keyword'

    with session_scope() as s:
        # 合併 tag/tags
        all_tags = list(tags) if tags else []
        if tag and tag not in all_tags:
            all_tags.append(tag)

        # 若有 tag 篩選，先取得符合的 atom IDs（供 keyword 和 semantic 共用）
        tag_filtered_ids = None
        if all_tags:
            tag_rows = (
                s.query(atom_tags.c.atom_id)
                .join(Tag, Tag.id == atom_tags.c.tag_id)
                .filter(Tag.name.in_(all_tags))
                .group_by(atom_tags.c.atom_id)
                .having(func.count(func.distinct(Tag.name)) == len(all_tags))
                .all()
            )
            tag_filtered_ids = [r[0] for r in tag_rows]
            if not tag_filtered_ids:
                return json.dumps({
                    'total': 0, 'returned': 0,
                    'search_mode': search_mode, 'items': [],
                }, ensure_ascii=False)

        # ---- 格式化原子 ----
        def _format_atom(a, match_type='keyword', similarity=0):
            content = a.content or ''
            item = {
                'id': a.id,
                'title': a.title,
                'content': (content[:200] + '...') if len(content) > 200 else content,
                'atom_type': a.atom_type,
                'lifecycle': a.lifecycle,
                'vitality_score': a.vitality_score,
                'source': a.source,
                'tags': [t.name for t in a.tags],
                'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                'match_type': match_type,
            }
            if similarity:
                item['similarity'] = round(similarity, 4)
            if a.atom_type == 'E' and a.schema_id:
                fvs = s.query(AtomFieldValue).options(
                    joinedload(AtomFieldValue.field)
                ).filter(AtomFieldValue.atom_id == a.id).all()
                item['field_values'] = {fv.field.name: fv.value for fv in fvs if fv.field}
                item['schema_id'] = a.schema_id
            return item

        # ---- 共用 ORM 篩選 ----
        def _apply_filters(q):
            if atom_type:
                q = q.filter(KnowledgeAtom.atom_type == atom_type)
            if lifecycle:
                q = q.filter(KnowledgeAtom.lifecycle == lifecycle)
            if source:
                q = q.filter(KnowledgeAtom.source == source)
            if schema_id is not None:
                q = q.filter(KnowledgeAtom.schema_id == schema_id)
            if tag_filtered_ids is not None:
                q = q.filter(KnowledgeAtom.id.in_(tag_filtered_ids))
            return q

        # ---- keyword 搜尋 ----
        def _keyword_search():
            use_trgm = query and len(query) > 2

            if use_trgm:
                sim_expr = func.greatest(
                    func.similarity(KnowledgeAtom.title, query),
                    func.similarity(KnowledgeAtom.content, query),
                )
                pattern = f'%{query}%'
                q = (
                    s.query(KnowledgeAtom, sim_expr.label('sim'))
                    .options(joinedload(KnowledgeAtom.tags))
                    .filter(KnowledgeAtom.is_deleted == False)
                    .filter(
                        KnowledgeAtom.title.ilike(pattern) |
                        KnowledgeAtom.content.ilike(pattern)
                    )
                )
            else:
                sim_expr = None
                q = (
                    s.query(KnowledgeAtom)
                    .options(joinedload(KnowledgeAtom.tags))
                    .filter(KnowledgeAtom.is_deleted == False)
                )
                if query:
                    pattern = f'%{query}%'
                    q = q.filter(
                        KnowledgeAtom.title.ilike(pattern) |
                        KnowledgeAtom.content.ilike(pattern)
                    )

            q = _apply_filters(q)

            if sort == 'vitality':
                q = q.order_by(KnowledgeAtom.vitality_score.desc(), KnowledgeAtom.updated_at.desc())
            elif sort == 'created_at':
                q = q.order_by(KnowledgeAtom.created_at.desc())
            elif sort == 'updated_at':
                q = q.order_by(KnowledgeAtom.updated_at.desc())
            elif use_trgm:
                q = q.order_by(sim_expr.desc(), KnowledgeAtom.vitality_score.desc(), KnowledgeAtom.updated_at.desc())
            else:
                q = q.order_by(KnowledgeAtom.vitality_score.desc(), KnowledgeAtom.updated_at.desc())

            rows = q.limit(limit).all()
            results = []
            if use_trgm:
                for row_atom, sim_val in rows:
                    results.append(_format_atom(row_atom, 'keyword'))
            else:
                for a in rows:
                    results.append(_format_atom(a, 'keyword'))
            return results

        # ---- semantic 搜尋 ----
        def _semantic_search():
            from core.embeddings import generate_embedding, MODEL_NAME
            query_vec = generate_embedding(query)

            conditions = ["a.is_deleted = FALSE", "e.model_name = :model_name"]
            params = {
                'query_vec': str(query_vec),
                'model_name': MODEL_NAME,
                'limit': limit,
            }
            if atom_type:
                conditions.append("a.atom_type = :atom_type")
                params['atom_type'] = atom_type
            if lifecycle:
                conditions.append("a.lifecycle = :lifecycle")
                params['lifecycle'] = lifecycle
            if source:
                conditions.append("a.source = :source")
                params['source'] = source
            if schema_id is not None:
                conditions.append("a.schema_id = :schema_id")
                params['schema_id'] = schema_id
            if tag_filtered_ids is not None:
                conditions.append("a.id = ANY(:tag_ids)")
                params['tag_ids'] = tag_filtered_ids

            where_sql = " AND ".join(conditions)

            if sort == 'vitality':
                order_sql = "a.vitality_score DESC, a.updated_at DESC"
            elif sort == 'created_at':
                order_sql = "a.created_at DESC"
            elif sort == 'updated_at':
                order_sql = "a.updated_at DESC"
            else:
                order_sql = "e.embedding <=> :query_vec"

            sql = sa_text(f"""
                SELECT
                    a.id, a.title, a.content, a.atom_type, a.lifecycle,
                    a.vitality_score, a.source, a.updated_at, a.schema_id,
                    1 - (e.embedding <=> :query_vec) AS similarity
                FROM atom_embeddings e
                JOIN knowledge_atoms a ON a.id = e.atom_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT :limit
            """)
            rows = s.execute(sql, params).fetchall()

            # 載入 tag 資訊
            atom_ids = [row[0] for row in rows]
            atoms_map = {}
            if atom_ids:
                loaded = (
                    s.query(KnowledgeAtom)
                    .options(joinedload(KnowledgeAtom.tags))
                    .filter(KnowledgeAtom.id.in_(atom_ids))
                    .all()
                )
                atoms_map = {a.id: a for a in loaded}

            results = []
            for row in rows:
                aid = row[0]
                atom_obj = atoms_map.get(aid)
                content = row[2] or ''
                item = {
                    'id': aid,
                    'title': row[1],
                    'content': (content[:200] + '...') if len(content) > 200 else content,
                    'atom_type': row[3],
                    'lifecycle': row[4],
                    'vitality_score': row[5],
                    'source': row[6],
                    'tags': [t.name for t in atom_obj.tags] if atom_obj else [],
                    'updated_at': row[7].isoformat() if row[7] else None,
                    'similarity': round(float(row[9]), 4),
                    'match_type': 'semantic',
                }
                if row[3] == 'E' and row[8] and atom_obj:
                    item['schema_id'] = row[8]
                    fvs = s.query(AtomFieldValue).options(
                        joinedload(AtomFieldValue.field)
                    ).filter(AtomFieldValue.atom_id == aid).all()
                    item['field_values'] = {fv.field.name: fv.value for fv in fvs if fv.field}
                results.append(item)
            return results

        # ---- 執行搜尋 ----
        if search_mode == 'keyword':
            results = _keyword_search()
        elif search_mode == 'semantic':
            results = _semantic_search()
        else:  # hybrid
            sem_results = _semantic_search()
            kw_results = _keyword_search()
            seen_ids = set()
            merged = []
            for item in sem_results:
                if item['id'] not in seen_ids:
                    merged.append(item)
                    seen_ids.add(item['id'])
            for item in kw_results:
                if item['id'] not in seen_ids:
                    item['similarity'] = 0
                    merged.append(item)
                    seen_ids.add(item['id'])
            results = merged[:limit]

        return json.dumps({
            'total': len(results),
            'returned': len(results),
            'search_mode': search_mode,
            'items': results,
        }, ensure_ascii=False)


# ============================================================
# note_get -- 取得完整原子（含關係與阻塞）
# ============================================================

@mcp.tool()
def note_get(atom_id: int) -> str:
    """取得單一知識原子的完整資訊，包含因果關係與阻塞狀態。

    自動更新存取紀錄（last_accessed_at, access_count）。
    """
    with session_scope() as s:
        atom = (
            s.query(KnowledgeAtom)
            .options(
                joinedload(KnowledgeAtom.tags),
                joinedload(KnowledgeAtom.field_values).joinedload(AtomFieldValue.field),
            )
            .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
            .first()
        )
        if not atom:
            return json.dumps({'error': f'原子 {atom_id} 不存在'})

        atom.last_accessed_at = datetime.datetime.now()
        atom.access_count += 1

        result = atom.to_dict(include_tags=True, include_values=True)

        # E 類型附加 schema 資訊
        if atom.schema_id and atom.schema:
            result['schema'] = atom.schema.to_dict()
            result['schema']['fields'] = [f.to_dict() for f in atom.schema.fields]

        # 關係
        outgoing = rel_service.get_relations_from(s, atom_id)
        incoming = rel_service.get_relations_to(s, atom_id)
        result['relations_from'] = [
            {
                'id': r.id,
                'to_atom_id': r.to_atom_id,
                'to_title': r.to_atom.title if r.to_atom else '',
                'type': r.relation_type,
                'label': r.label,
            }
            for r in outgoing
        ]
        result['relations_to'] = [
            {
                'id': r.id,
                'from_atom_id': r.from_atom_id,
                'from_title': r.from_atom.title if r.from_atom else '',
                'type': r.relation_type,
                'label': r.label,
            }
            for r in incoming
        ]

        # 阻塞
        blockers = rel_service.get_blockers(s, atom_id)
        result['is_blocked'] = len(blockers) > 0
        result['blockers'] = [
            {'id': b.id, 'title': b.title, 'lifecycle': b.lifecycle}
            for b in blockers
        ]

        return json.dumps(result, ensure_ascii=False)


# ============================================================
# note_update -- 更新知識原子
# ============================================================

@mcp.tool()
def note_update(
    atom_id: int,
    title: str = '',
    content: str = '',
    atom_type: str = '',
    lifecycle: str = '',
    tags: list[str] | None = None,
    append_content: str = '',
) -> str:
    """更新現有知識原子的欄位。

    只有提供的欄位會被更新（空字串表示不更新）。
    append_content: 在現有內容後追加（不覆蓋），適合漸進式補充。
    tags: 提供時會替換所有標籤，不存在的標籤會自動建立。
    """
    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
        ).first()
        if not atom:
            return json.dumps({'error': f'原子 {atom_id} 不存在'})

        if title:
            atom.title = title
        if content:
            atom.content = content
        if append_content:
            atom.content = (atom.content or '') + '\n' + append_content
        if atom_type:
            atom.atom_type = atom_type
        if lifecycle:
            atom.lifecycle = lifecycle

        if tags is not None:
            tag_objects = []
            for tag_name in tags:
                tag = s.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name, tag_type='tag')
                    s.add(tag)
                    s.flush()
                tag_objects.append(tag)
            atom.tags = tag_objects

        s.flush()

        # 若 title 或 content 有變更，重新 embed
        if title or content or append_content:
            try:
                embed_service.embed_atom(s, atom.id)
            except Exception as e:
                logger.warning(f'Auto-embed failed for atom {atom.id}: {e}')

        return json.dumps({
            'id': atom.id,
            'title': atom.title,
            'lifecycle': atom.lifecycle,
            'tags': [t.name for t in atom.tags],
            'message': f'原子 {atom_id} 已更新',
        }, ensure_ascii=False)


# ============================================================
# note_relate -- 建立因果關係
# ============================================================

@mcp.tool()
def note_relate(
    from_atom_id: int,
    to_atom_id: int,
    relation_type: str,
    label: str = '',
    confidence: float = 1.0,
) -> str:
    """在兩個知識原子之間建立有向關係。

    relation_type 允許值（按維度分類）:
      因果: causes       -- A 導致了 B
            enables      -- A 使 B 成為可能（比 causes 弱）
      論證: supports     -- 證據 A 支持結論 B
            contradicts  -- A 與 B 矛盾
      結構: contains     -- A 包含 B
      時序: follows      -- 時序上 A 在 B 之後
      衍生: derives_from -- A 衍生自 B
            supersedes   -- A 取代 B（新版取代舊版）
            references   -- A 引用/提到 B（純引用，不帶因果）
      工作流: blocks     -- A 未完成前 B 無法開始

    confidence: 0.0~1.0，AI 產生的關聯建議標低一些（如 0.7）。
    """
    with session_scope() as s:
        try:
            rel = rel_service.create_relation(
                s, from_atom_id, to_atom_id, relation_type,
                label=label, confidence=confidence, created_by='ai',
            )
            return json.dumps({
                'id': rel.id,
                'from_atom_id': rel.from_atom_id,
                'to_atom_id': rel.to_atom_id,
                'relation_type': rel.relation_type,
                'label': rel.label,
                'message': '因果關係已建立',
            }, ensure_ascii=False)
        except ValueError as e:
            return json.dumps({'error': str(e)})


# ============================================================
# note_relate_batch -- 批次建立因果關係
# ============================================================

@mcp.tool()
def note_relate_batch(
    relations: list[dict],
) -> str:
    """批次建立多條因果關係。

    relations: 關係列表，每個元素為 dict:
      {
        "from_atom_id": int,
        "to_atom_id": int,
        "relation_type": str,  -- 同 note_relate 的允許值
        "label": str,          -- 選填
        "confidence": float    -- 選填，預設 1.0
      }

    回傳每條關係的建立結果（成功或錯誤）。
    用途：一次建立多條關係，避免逐條呼叫的往返開銷。
    """
    if not relations:
        return json.dumps({'error': 'relations 不可為空'})

    results = []
    with session_scope() as s:
        for i, r in enumerate(relations):
            from_id = r.get('from_atom_id')
            to_id = r.get('to_atom_id')
            rel_type = r.get('relation_type', '')
            label = r.get('label', '')
            confidence = r.get('confidence', 1.0)

            if not from_id or not to_id or not rel_type:
                results.append({
                    'index': i,
                    'error': '缺少必要欄位 (from_atom_id, to_atom_id, relation_type)',
                })
                continue

            try:
                rel = rel_service.create_relation(
                    s, from_id, to_id, rel_type,
                    label=label, confidence=confidence, created_by='ai',
                )
                results.append({
                    'index': i,
                    'id': rel.id,
                    'from_atom_id': rel.from_atom_id,
                    'to_atom_id': rel.to_atom_id,
                    'relation_type': rel.relation_type,
                    'status': 'created',
                })
            except ValueError as e:
                results.append({'index': i, 'error': str(e)})
            except Exception as e:
                results.append({'index': i, 'error': f'建立失敗: {str(e)}'})

    created = sum(1 for r in results if r.get('status') == 'created')
    failed = len(results) - created

    return json.dumps({
        'total': len(results),
        'created': created,
        'failed': failed,
        'results': results,
    }, ensure_ascii=False)


# ============================================================
# note_forget -- 軟刪除/歸檔知識
# ============================================================

@mcp.tool()
def note_forget(
    atom_id: int,
    mode: str = 'archive',
) -> str:
    """將知識原子標記為過時或刪除。

    mode:
      archive  -- 設為 archived（歸檔，搜尋仍可達但不主動顯示）
      terminal -- 設為 terminal（終止，僅明確搜尋時顯示）
      delete   -- 軟刪除（is_deleted=True，一般搜尋不會出現）
    """
    valid_modes = ('archive', 'terminal', 'delete')
    if mode not in valid_modes:
        return json.dumps({'error': f'無效的 mode: {mode}，允許值: {", ".join(valid_modes)}'})

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return json.dumps({'error': f'原子 {atom_id} 不存在'})

        if mode == 'delete':
            atom.is_deleted = True
            action = '已軟刪除'
        elif mode == 'terminal':
            atom.lifecycle = 'terminal'
            action = '已標記為終止'
        else:
            atom.lifecycle = 'archived'
            action = '已歸檔'

        return json.dumps({
            'id': atom.id,
            'title': atom.title,
            'message': f'原子 {atom_id} {action}',
        }, ensure_ascii=False)


# ============================================================
# note_blocked -- 阻塞鍊追溯
# ============================================================

@mcp.tool()
def note_blocked(atom_id: int, max_depth: int = 10) -> str:
    """追溯某知識原子的阻塞鍊。

    回傳所有阻塞此原子的上游原子（遞迴追溯到根節點）。
    用途：了解「為什麼這件事不能開始」。
    """
    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return json.dumps({'error': f'原子 {atom_id} 不存在'})

        chain = rel_service.trace_block_chain(s, atom_id, max_depth)
        blockers = rel_service.get_blockers(s, atom_id)

        return json.dumps({
            'atom_id': atom_id,
            'title': atom.title,
            'is_blocked': len(blockers) > 0,
            'direct_blockers': [
                {'id': b.id, 'title': b.title, 'lifecycle': b.lifecycle}
                for b in blockers
            ],
            'full_chain': chain,
        }, ensure_ascii=False)


# ============================================================
# note_trace -- 圖譜遍歷
# ============================================================

@mcp.tool()
def note_trace(
    atom_id: int,
    direction: str = 'both',
    relation_types: list[str] | None = None,
    max_depth: int = 3,
    include_archived: bool = False,
) -> str:
    """從起點原子沿關係展開 N 層，回傳子圖（nodes + edges）。

    用途：一次取得完整脈絡，而非逐個 note_get 手動追。

    direction: outgoing（我指向誰）/ incoming（誰指向我）/ both（雙向）
    relation_types: 過濾關係類型，如 ["causes", "supports"]，None 表示全部
    max_depth: 展開層數（1~10，預設 3）
    include_archived: 是否包含 archived/terminal 原子（預設 False）

    回傳的 nodes 不含 content（避免子圖過大），需要細節用 note_get 取單個。
    """
    max_depth = max(1, min(max_depth, 10))

    valid_directions = ('outgoing', 'incoming', 'both')
    if direction not in valid_directions:
        return json.dumps({'error': f'無效的 direction: {direction}，允許值: {", ".join(valid_directions)}'})

    if relation_types:
        invalid = [t for t in relation_types if t not in AtomRelation.VALID_TYPES]
        if invalid:
            return json.dumps({'error': f'無效的關係類型: {", ".join(invalid)}'})

    with session_scope() as s:
        result = rel_service.trace_subgraph(
            s, atom_id,
            direction=direction,
            relation_types=relation_types,
            max_depth=max_depth,
            include_archived=include_archived,
        )
        return json.dumps(result, ensure_ascii=False)


# ============================================================
# note_check -- 一致性檢查
# ============================================================

@mcp.tool()
def note_check(
    content: str,
    check_scope: str = 'all',
    limit: int = 10,
) -> str:
    """比對一段文字與既有知識庫，回報重複、矛盾、相關原子。

    用途：新想法進來時，檢查是否與既有知識重複或矛盾。

    content: 要檢查的文字內容
    check_scope: 'all' 或指定 tag 名稱縮小檢查範圍
    limit: 回傳相似原子上限（預設 10，最大 50）

    回傳:
      similar: 相似度最高的原子列表（含 similarity 分數）
      contradictions: 相似原子的 contradicts 關係鏈
      suggestion: 'duplicate_suspect' / 'contradiction_found' / 'novel'

    suggestion 是純規則判斷（similarity>0.8 或有矛盾鏈），AI 自行決定是否採信。
    """
    with session_scope() as s:
        result = consistency_service.check_consistency(
            s, content,
            check_scope=check_scope,
            limit=min(limit, 50),
        )
        return json.dumps(result, ensure_ascii=False)


# ============================================================
# schema_create -- 建立套表 schema
# ============================================================

@mcp.tool()
def schema_create(
    name: str,
    slug: str,
    description: str = '',
    icon: str = '',
    fields: list[dict] | None = None,
) -> str:
    """建立一個 E 類型套表的 schema 定義。

    name: schema 顯示名稱
    slug: 唯一識別碼（英文小寫+底線，如 perf_test）
    description: 用途說明
    icon: 圖示（選填）
    fields: 欄位定義列表，每個欄位為 dict:
      {
        "name": "欄位識別名（英文）",
        "label": "欄位顯示名（中文）",
        "field_type": "text|number|date|select|multiselect|checkbox|url|relation",
        "options": "select/multiselect 的選項，逗號分隔",
        "required": false,
        "sort_order": 0
      }

    回傳建立的 schema ID 與欄位列表。
    """
    with session_scope() as s:
        existing = s.query(AtomSchema).filter(AtomSchema.slug == slug).first()
        if existing:
            return json.dumps({'error': f'slug "{slug}" 已存在 (id={existing.id})'})

        schema = AtomSchema(
            name=name,
            slug=slug,
            description=description,
            icon=icon,
        )
        s.add(schema)
        s.flush()

        if fields:
            for i, fd in enumerate(fields):
                sf = SchemaField(
                    schema_id=schema.id,
                    name=fd.get('name', ''),
                    label=fd.get('label', fd.get('name', '')),
                    field_type=fd.get('field_type', 'text'),
                    options=fd.get('options', ''),
                    required=fd.get('required', False),
                    sort_order=fd.get('sort_order', i),
                )
                s.add(sf)
            s.flush()

        schema_fields = s.query(SchemaField).filter(
            SchemaField.schema_id == schema.id
        ).order_by(SchemaField.sort_order).all()

        return json.dumps({
            'id': schema.id,
            'name': schema.name,
            'slug': schema.slug,
            'description': schema.description,
            'fields': [f.to_dict() for f in schema_fields],
            'message': f'Schema "{name}" 已建立 (id={schema.id})',
        }, ensure_ascii=False)


# ============================================================
# schema_list -- 列出所有 schema
# ============================================================

@mcp.tool()
def schema_list() -> str:
    """列出所有套表 schema 及其欄位定義。

    用途：查看可用的 E 類型 schema，以便建立套表原子時指定 schema_id。
    """
    with session_scope() as s:
        schemas = (
            s.query(AtomSchema)
            .options(joinedload(AtomSchema.fields))
            .order_by(AtomSchema.id)
            .all()
        )

        # 統計每個 schema 被多少原子使用
        result = []
        for schema in schemas:
            atom_count = s.query(KnowledgeAtom).filter(
                KnowledgeAtom.schema_id == schema.id,
                KnowledgeAtom.is_deleted == False,
            ).count()
            result.append({
                'id': schema.id,
                'name': schema.name,
                'slug': schema.slug,
                'description': schema.description,
                'atom_count': atom_count,
                'fields': [f.to_dict() for f in schema.fields],
            })

        return json.dumps({
            'total': len(result),
            'schemas': result,
        }, ensure_ascii=False)


# ============================================================
# note_overview -- 知識庫概覽
# ============================================================

@mcp.tool()
def note_overview() -> str:
    """取得知識庫整體概覽：各類型/生命週期計數、最近活躍原子、阻塞中的項目。

    用途：快速了解當前知識庫的狀態，而非逐條翻閱。
    """
    with session_scope() as s:
        base = s.query(KnowledgeAtom).filter(KnowledgeAtom.is_deleted == False)

        # 各 atom_type 計數
        type_counts = dict(
            base.with_entities(
                KnowledgeAtom.atom_type,
                func.count(KnowledgeAtom.id),
            ).group_by(KnowledgeAtom.atom_type).all()
        )

        # 各 lifecycle 計數
        lifecycle_counts = dict(
            base.with_entities(
                KnowledgeAtom.lifecycle,
                func.count(KnowledgeAtom.id),
            ).group_by(KnowledgeAtom.lifecycle).all()
        )

        # 各 source 計數
        source_counts = dict(
            base.with_entities(
                KnowledgeAtom.source,
                func.count(KnowledgeAtom.id),
            ).group_by(KnowledgeAtom.source).all()
        )

        total = base.count()

        # 最近更新的 10 筆
        recent = (
            base.order_by(KnowledgeAtom.updated_at.desc())
            .limit(10)
            .all()
        )

        # 被阻塞的原子（有 incoming blocks 關係且 lifecycle 為 active/aging）
        blocked_atom_ids = (
            s.query(AtomRelation.to_atom_id)
            .filter(AtomRelation.relation_type == 'blocks')
            .distinct()
            .subquery()
        )
        blocked_atoms = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.id.in_(blocked_atom_ids),
                KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                KnowledgeAtom.is_deleted == False,
            )
            .all()
        )
        # 過濾出真正被阻塞的（上游尚未完成）
        truly_blocked = []
        for ba in blocked_atoms:
            blockers = rel_service.get_blockers(s, ba.id)
            if blockers:
                truly_blocked.append({
                    'id': ba.id,
                    'title': ba.title,
                    'blocked_by': [{'id': b.id, 'title': b.title} for b in blockers],
                })

        # 標籤統計
        tag_counts = (
            s.query(Tag.name, func.count(atom_tags.c.atom_id))
            .join(atom_tags, Tag.id == atom_tags.c.tag_id)
            .group_by(Tag.name)
            .order_by(func.count(atom_tags.c.atom_id).desc())
            .limit(20)
            .all()
        )

        type_labels = {
            'A': '萬用', 'B': '發散', 'C': '流程',
            'D': '歸納', 'E': '套表', 'F': '碎片',
        }

        return json.dumps({
            'total_atoms': total,
            'by_type': {f'{k}({type_labels.get(k, k)})': v for k, v in type_counts.items()},
            'by_lifecycle': lifecycle_counts,
            'by_source': source_counts,
            'top_tags': [{'name': name, 'count': cnt} for name, cnt in tag_counts],
            'recently_updated': [
                {
                    'id': a.id,
                    'title': a.title,
                    'atom_type': a.atom_type,
                    'lifecycle': a.lifecycle,
                    'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                }
                for a in recent
            ],
            'blocked_items': truly_blocked,
        }, ensure_ascii=False)


# ============================================================
# task_dispatch -- 派發支線任務
# ============================================================

@mcp.tool()
def task_dispatch(
    title: str,
    instruction: str,
    model: str = 'sonnet',
    working_dir: str = '/opt/BeakCortex',
    priority: int = 5,
    timeout_seconds: int = 600,
) -> str:
    """派發一個任務到支線 claude process 執行。

    在 tmux 新建 window，啟動 claude -p 執行指令。
    結果會存入 worker_reports，經中間層審查後可供主線讀取。

    model: sonnet / opus / haiku (支線使用的模型)
    working_dir: 支線的工作目錄
    priority: 0-9 (目前僅記錄，未來排程用)
    timeout_seconds: 逾時秒數 (預設 600)

    回傳任務 ID 與狀態。完成後用 task_status 查詢結果。
    """
    result = orch_dispatcher.create_and_dispatch(
        title=title,
        instruction=instruction,
        model=model,
        working_dir=working_dir,
        priority=priority,
        timeout_seconds=timeout_seconds,
    )
    return json.dumps(result, ensure_ascii=False)


# ============================================================
# task_status -- 查詢任務狀態
# ============================================================

@mcp.tool()
def task_status(task_id: int) -> str:
    """查詢支線任務的狀態與結果。

    回傳任務詳情。若已完成，同時回傳 worker_report 內容。
    """
    with session_scope() as s:
        task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        if not task:
            return json.dumps({'error': f'任務 #{task_id} 不存在'})

        result = task.to_dict()
        result['reports'] = []

        if task.status in ('completed', 'failed'):
            reports = (
                s.query(WorkerReport)
                .filter(WorkerReport.task_id == task_id)
                .order_by(WorkerReport.created_at.desc())
                .all()
            )
            result['reports'] = [r.to_dict() for r in reports]

        return json.dumps(result, ensure_ascii=False)


# ============================================================
# task_list -- 列出任務
# ============================================================

@mcp.tool()
def task_list(
    status: str = '',
    limit: int = 20,
) -> str:
    """列出支線任務。

    status: 篩選狀態 (pending/dispatched/running/completed/failed/timeout/cancelled)
            空字串表示列出所有非 cancelled 的任務
    limit: 回傳上限 (預設 20)
    """
    limit = min(limit, 100)

    with session_scope() as s:
        q = s.query(WorkerTask)

        if status:
            q = q.filter(WorkerTask.status == status)
        else:
            q = q.filter(WorkerTask.status != 'cancelled')

        tasks = (
            q.order_by(WorkerTask.created_at.desc())
            .limit(limit)
            .all()
        )

        return json.dumps({
            'total': len(tasks),
            'items': [t.to_dict(brief=True) for t in tasks],
        }, ensure_ascii=False)


# ============================================================
# task_collect -- 收集任務結果
# ============================================================

@mcp.tool()
def task_collect(task_id: int, include_raw: bool = False) -> str:
    """取得支線任務的完整報告。

    回傳 worker_report 的內容。
    include_raw: 是否包含 tmux capture 的原始輸出 (預設 False，避免過長)

    report 的 review_status:
      pending   -- 尚未經過中間層處理
      approved  -- 中間層審查通過
      rejected  -- 中間層審查未通過
      promoted  -- 已提升為正式知識原子 (promoted_atom_id)
    """
    with session_scope() as s:
        task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        if not task:
            return json.dumps({'error': f'任務 #{task_id} 不存在'})

        reports = (
            s.query(WorkerReport)
            .filter(WorkerReport.task_id == task_id)
            .order_by(WorkerReport.created_at.desc())
            .all()
        )

        if not reports:
            return json.dumps({
                'task_id': task_id,
                'task_status': task.status,
                'message': '尚無報告（任務可能仍在執行中）',
            })

        return json.dumps({
            'task_id': task_id,
            'task_title': task.title,
            'task_status': task.status,
            'reports': [r.to_dict(include_raw=include_raw) for r in reports],
        }, ensure_ascii=False)


# ============================================================
# canvas_list -- 列出畫布
# ============================================================

@mcp.tool()
def canvas_list() -> str:
    """列出所有畫布及其基本資訊。"""
    with session_scope() as s:
        canvases = s.query(Canvas).order_by(Canvas.updated_at.desc()).all()
        return json.dumps({
            'total': len(canvases),
            'items': [c.to_dict() for c in canvases],
        }, ensure_ascii=False)


# ============================================================
# canvas_create -- 建立畫布
# ============================================================

@mcp.tool()
def canvas_create(
    name: str,
    description: str = '',
    canvas_type: str = 'whiteboard',
) -> str:
    """建立新畫布。

    canvas_type: whiteboard / mindmap / flowchart / cornell / template
    """
    valid_types = ('whiteboard', 'mindmap', 'flowchart', 'cornell', 'template')
    if canvas_type not in valid_types:
        return json.dumps({'error': f'無效的 canvas_type: {canvas_type}'})

    with session_scope() as s:
        canvas = Canvas(
            name=name,
            description=description,
            canvas_type=canvas_type,
        )
        s.add(canvas)
        s.flush()
        return json.dumps({
            'id': canvas.id,
            'name': canvas.name,
            'canvas_type': canvas.canvas_type,
            'message': f'畫布已建立 (id={canvas.id})',
        }, ensure_ascii=False)


# ============================================================
# canvas_get -- 取得畫布內容
# ============================================================

@mcp.tool()
def canvas_get(canvas_id: int) -> str:
    """取得畫布的完整內容（所有原子位置、連線、群組）。

    用途：了解畫布上有哪些原子及其空間配置。
    """
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.id == canvas_id).first()
        if not canvas:
            return json.dumps({'error': f'畫布 {canvas_id} 不存在'})

        atoms = (
            s.query(CanvasAtom)
            .options(joinedload(CanvasAtom.atom))
            .filter(CanvasAtom.canvas_id == canvas_id)
            .all()
        )
        connections = (
            s.query(CanvasConnection)
            .filter(CanvasConnection.canvas_id == canvas_id)
            .all()
        )
        groups = (
            s.query(CanvasGroup)
            .filter(CanvasGroup.canvas_id == canvas_id)
            .all()
        )

        return json.dumps({
            'canvas': canvas.to_dict(),
            'atoms': [ca.to_dict() for ca in atoms],
            'connections': [c.to_dict() for c in connections],
            'groups': [g.to_dict() for g in groups],
        }, ensure_ascii=False)


# ============================================================
# canvas_place_atom -- 放置原子到畫布
# ============================================================

@mcp.tool()
def canvas_place_atom(
    canvas_id: int,
    atom_id: int,
    pos_x: float = 0,
    pos_y: float = 0,
    width: float | None = None,
    height: float | None = None,
) -> str:
    """將原子放置到畫布的指定位置。

    若原子已在畫布上，會更新其位置與尺寸。
    """
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.id == canvas_id).first()
        if not canvas:
            return json.dumps({'error': f'畫布 {canvas_id} 不存在'})

        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
        ).first()
        if not atom:
            return json.dumps({'error': f'原子 {atom_id} 不存在'})

        existing = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == canvas_id,
            CanvasAtom.atom_id == atom_id,
        ).first()

        if existing:
            existing.pos_x = pos_x
            existing.pos_y = pos_y
            if width is not None:
                existing.width = width
            if height is not None:
                existing.height = height
            s.flush()
            return json.dumps({
                'id': existing.id,
                'canvas_id': canvas_id,
                'atom_id': atom_id,
                'pos_x': pos_x,
                'pos_y': pos_y,
                'message': f'原子 {atom_id} 位置已更新',
            }, ensure_ascii=False)

        ca = CanvasAtom(
            canvas_id=canvas_id,
            atom_id=atom_id,
            pos_x=pos_x,
            pos_y=pos_y,
            width=width,
            height=height,
        )
        s.add(ca)
        s.flush()
        return json.dumps({
            'id': ca.id,
            'canvas_id': canvas_id,
            'atom_id': atom_id,
            'pos_x': pos_x,
            'pos_y': pos_y,
            'message': f'原子 {atom_id} 已放置到畫布 {canvas_id}',
        }, ensure_ascii=False)


# ============================================================
# canvas_remove_atom -- 從畫布移除原子
# ============================================================

@mcp.tool()
def canvas_remove_atom(
    canvas_id: int,
    atom_id: int,
) -> str:
    """從畫布移除原子（不刪除原子本身，只移除畫布上的位置）。"""
    with session_scope() as s:
        ca = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == canvas_id,
            CanvasAtom.atom_id == atom_id,
        ).first()
        if not ca:
            return json.dumps({'error': f'原子 {atom_id} 不在畫布 {canvas_id} 上'})

        s.delete(ca)
        return json.dumps({
            'canvas_id': canvas_id,
            'atom_id': atom_id,
            'message': f'原子 {atom_id} 已從畫布 {canvas_id} 移除',
        }, ensure_ascii=False)


# ============================================================
# note_suggest_relations -- AI 自動建議關聯
# ============================================================

@mcp.tool()
def note_suggest_relations(
    atom_id: int,
    limit: int = 5,
    min_similarity: float = 0.5,
) -> str:
    """根據語意相似度，自動建議與指定原子可能相關的其他原子。

    對每個語意相似原子，標記是否已建立關係。
    回傳建議列表，可選擇性地用 note_relate 或 note_relate_batch 建立。

    atom_id: 要分析的原子 ID
    limit: 回傳建議數量上限（預設 5，最大 20）
    min_similarity: 最低相似度閾值（預設 0.5）
    """
    limit = min(limit, 20)

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id,
            KnowledgeAtom.is_deleted == False,
        ).first()
        if not atom:
            return json.dumps({'error': f'原子 {atom_id} 不存在'})

        from core.embeddings import generate_embedding, MODEL_NAME
        text_content = (atom.title or '') + '\n' + (atom.content or '')
        query_vec = generate_embedding(text_content)

        sql = sa_text("""
            SELECT
                a.id, a.title, a.atom_type, a.lifecycle,
                1 - (e.embedding <=> :query_vec) AS similarity
            FROM atom_embeddings e
            JOIN knowledge_atoms a ON a.id = e.atom_id
            WHERE a.is_deleted = FALSE
              AND a.id != :atom_id
              AND e.model_name = :model_name
              AND 1 - (e.embedding <=> :query_vec) >= :min_sim
            ORDER BY e.embedding <=> :query_vec
            LIMIT :limit
        """)

        rows = s.execute(sql, {
            'query_vec': str(query_vec),
            'atom_id': atom_id,
            'model_name': MODEL_NAME,
            'min_sim': min_similarity,
            'limit': limit,
        }).fetchall()

        # 檢查已存在的關係
        existing_pairs = set()
        outgoing = rel_service.get_relations_from(s, atom_id)
        incoming = rel_service.get_relations_to(s, atom_id)
        for r in outgoing:
            existing_pairs.add(r.to_atom_id)
        for r in incoming:
            existing_pairs.add(r.from_atom_id)

        suggestions = []
        for row in rows:
            target_id = row[0]
            suggestions.append({
                'target_id': target_id,
                'target_title': row[1],
                'target_type': row[2],
                'target_lifecycle': row[3],
                'similarity': round(float(row[4]), 4),
                'already_related': target_id in existing_pairs,
                'suggested_type': 'references',
            })

        return json.dumps({
            'atom_id': atom_id,
            'atom_title': atom.title,
            'suggestions': suggestions,
            'message': f'找到 {len(suggestions)} 個語意相似原子',
        }, ensure_ascii=False)


# ============================================================
# 啟動
# ============================================================

def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='BeakCortex MCP Server -- AI 知識庫介面',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python mcp_server.py --stdio              以 stdio 模式啟動（供 Claude Code）
  python mcp_server.py --stdio -c path.ini  指定組態檔
        """
    )
    parser.add_argument('--stdio', action='store_true', help='以 stdio 傳輸模式啟動')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')
    return parser


def main():
    parser = create_argument_parser()

    if len(sys.argv) == 1:
        print('BeakCortex MCP Server -- AI 知識庫介面')
        print()
        print('此程式為 MCP (Model Context Protocol) 伺服器，')
        print('供 Claude Code 等 AI 工具透過 stdio 存取知識庫。')
        print()
        print('必要參數:')
        print('  --stdio     以 stdio 傳輸模式啟動')
        print()
        print('選項:')
        print('  --config    組態檔路徑 (預設: ../config.ini)')
        print()
        print('知識庫工具:')
        print('  note_store              儲存知識原子')
        print('  note_search             搜尋知識原子（keyword/semantic/hybrid）')
        print('  note_get                取得原子完整資訊（含關係與阻塞）')
        print('  note_update             更新知識原子')
        print('  note_relate             建立因果關係')
        print('  note_relate_batch       批次建立因果關係')
        print('  note_forget             歸檔/終止/刪除知識')
        print('  note_blocked            追溯阻塞鍊')
        print('  note_trace              圖譜遍歷（子圖展開）')
        print('  note_check              一致性檢查（重複/矛盾偵測）')
        print('  note_overview           知識庫概覽')
        print('  note_suggest_relations  AI 自動建議關聯')
        print()
        print('畫布工具:')
        print('  canvas_list             列出所有畫布')
        print('  canvas_create           建立新畫布')
        print('  canvas_get              取得畫布內容')
        print('  canvas_place_atom       放置/移動原子到畫布')
        print('  canvas_remove_atom      從畫布移除原子')
        print()
        print('Orchestrator 工具:')
        print('  task_dispatch           派發支線任務到 tmux')
        print('  task_status             查詢任務狀態')
        print('  task_list               列出所有任務')
        print('  task_collect            取得任務報告')
        print()
        print('Claude Code 設定範例 (~/.claude/settings.json):')
        print('  "mcpServers": {')
        print('    "beak_cortex": {')
        print('      "command": "/opt/BeakCortex/venv/bin/python",')
        print('      "args": ["/opt/BeakCortex/ai_kb/mcp_server.py", "--stdio"]')
        print('    }')
        print('  }')
        print()
        sys.exit(1)

    args = parser.parse_args()

    # 初始化資料庫
    config_path = args.config
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    init_engine(config_path)

    if args.stdio:
        mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
