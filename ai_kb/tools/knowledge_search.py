# -*- coding: utf-8 -*-
"""知識搜尋工具: note_search"""
import json
import logging

from sqlalchemy import func, text as sa_text
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Tag, atom_tags,
    AtomFieldValue, AtomEmbedding,
)
from core import visibility
from .param_forms import normalize_tags


logger = logging.getLogger('beak_broodnest.mcp')


def register(mcp):

    @mcp.tool()
    def note_search(
        query: str = '',
        atom_type: str = '',
        lifecycle: str = '',
        tag: str = '',
        tags: str | list[str] | None = None,
        source: str = '',
        owner: str = '',
        schema_id: int | None = None,
        limit: int = 20,
        search_mode: str = 'keyword',
        sort: str = '',
        scope: str = 'default',
        include_human_boards: bool = False,
    ) -> str:
        """搜尋知識庫中的原子。

        query: 關鍵字搜尋(ILIKE 匹配 + pg_trgm 相似度排序)
        atom_type: 篩選類型 (A/B/C/D/E/F)
        lifecycle: 篩選生命週期 (active/aging/archived/terminal)
        tag: 篩選單一標籤名稱(向下相容)
        tags: 多標籤 AND 篩選，逗號分隔字串（請用字串不要用陣列），原子必須同時擁有所有指定標籤
        source: 篩選來源 (human/ai/import/derived)
        owner: 篩選擁有者 (ethan/claude/agent:xxx)
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
        scope: 搜尋範圍
          default -- 僅搜尋 active + aging（預設，減少噪音）
          full    -- 搜尋全部生命週期（含 archived/terminal）
        include_human_boards: 是否納入使用者自用白板上的內容（預設 False）

        白板分成 human / ai / shared 三種受眾。只出現在 human 白板上的卡片是
        使用者的草稿與想法，預設一律排除，避免被當成知識引用；卡片只要同時放在
        ai 或 shared 白板上就視為刻意分享，照樣會回傳。要查使用者白板的內容，
        把 include_human_boards 設為 True。排除生效時回傳會多一個
        human_boards_hidden，數字是被隔離的卡片總數（不是本次查詢的命中數）。

        tag 與 tags 同時提供時,tag 會併入 tags 一起做 AND 篩選。
        semantic/hybrid 模式需要 query 非空,否則自動退回 keyword 模式。
        lifecycle 參數明確指定時,scope 設定會被忽略（以 lifecycle 為準）。
        E 類型原子會附帶 field_values 結構化欄位值。
        """
        limit = min(limit, 100)

        if search_mode not in ('keyword', 'semantic', 'hybrid'):
            search_mode = 'keyword'
        if search_mode in ('semantic', 'hybrid') and not query.strip():
            search_mode = 'keyword'

        if query:
            from core.term_dict import normalize as _term_normalize
            new_query, applied = _term_normalize(query)
            if applied:
                logger.info(
                    f'note_search query normalized: {query!r} -> {new_query!r} via {applied}'
                )
                query = new_query

        with session_scope() as s:
            all_tags = normalize_tags(tags) or []
            if tag and tag not in all_tags:
                all_tags.append(tag)

            exclude_human_boards = visibility.should_exclude(include_human_boards)

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
                    'owner': a.owner,
                    'sensitivity': a.sensitivity,
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

            def _apply_filters(q):
                if atom_type:
                    q = q.filter(KnowledgeAtom.atom_type == atom_type)
                if lifecycle:
                    q = q.filter(KnowledgeAtom.lifecycle == lifecycle)
                elif scope != 'full':
                    q = q.filter(KnowledgeAtom.lifecycle.in_(['active', 'aging']))
                if source:
                    q = q.filter(KnowledgeAtom.source == source)
                if owner:
                    q = q.filter(KnowledgeAtom.owner == owner)
                if schema_id is not None:
                    q = q.filter(KnowledgeAtom.schema_id == schema_id)
                if tag_filtered_ids is not None:
                    q = q.filter(KnowledgeAtom.id.in_(tag_filtered_ids))
                if exclude_human_boards:
                    q = q.filter(
                        sa_text(visibility.sql_condition('knowledge_atoms'))
                        .bindparams(**visibility.bind_params())
                    )
                return q

            def _keyword_search():
                use_trgm = query and len(query) > 2

                # 搜尋走 content_plain（HTML stripped），避免 <font> / <span style> 把關鍵字切斷
                if use_trgm:
                    sim_expr = func.greatest(
                        func.similarity(KnowledgeAtom.title, query),
                        func.similarity(KnowledgeAtom.content_plain, query),
                    )
                    pattern = f'%{query}%'
                    q = (
                        s.query(KnowledgeAtom, sim_expr.label('sim'))
                        .options(joinedload(KnowledgeAtom.tags))
                        .filter(KnowledgeAtom.is_deleted == False)
                        .filter(
                            KnowledgeAtom.title.ilike(pattern) |
                            KnowledgeAtom.content_plain.ilike(pattern)
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
                            KnowledgeAtom.content_plain.ilike(pattern)
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

            def _semantic_search():
                from core.embeddings import generate_embedding, MODEL_NAME
                query_vec = generate_embedding(query)
                distance_expr = AtomEmbedding.embedding.cosine_distance(query_vec)
                similarity_expr = (1 - distance_expr).label('similarity')

                q = (
                    s.query(
                        KnowledgeAtom.id,
                        KnowledgeAtom.title,
                        KnowledgeAtom.content,
                        KnowledgeAtom.atom_type,
                        KnowledgeAtom.lifecycle,
                        KnowledgeAtom.vitality_score,
                        KnowledgeAtom.source,
                        KnowledgeAtom.updated_at,
                        KnowledgeAtom.schema_id,
                        similarity_expr,
                    )
                    .select_from(AtomEmbedding)
                    .join(KnowledgeAtom, KnowledgeAtom.id == AtomEmbedding.atom_id)
                    .filter(KnowledgeAtom.is_deleted == False)
                    .filter(AtomEmbedding.model_name == MODEL_NAME)
                )

                q = _apply_filters(q)

                if sort == 'vitality':
                    q = q.order_by(KnowledgeAtom.vitality_score.desc(), KnowledgeAtom.updated_at.desc())
                elif sort == 'created_at':
                    q = q.order_by(KnowledgeAtom.created_at.desc())
                elif sort == 'updated_at':
                    q = q.order_by(KnowledgeAtom.updated_at.desc())
                else:
                    q = q.order_by(distance_expr)

                rows = q.limit(limit).all()

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
                        'owner': atom_obj.owner if atom_obj else 'ethan',
                        'sensitivity': atom_obj.sensitivity if atom_obj else 'internal',
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

            payload = {
                'total': len(results),
                'returned': len(results),
                'search_mode': search_mode,
                'items': results,
            }
            if exclude_human_boards:
                payload['human_boards_hidden'] = visibility.count_hidden(s, lifecycle, scope)
            return json.dumps(payload, ensure_ascii=False)
