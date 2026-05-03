# -*- coding: utf-8 -*-
"""核心知識工具: note_store/search/get/update/relate/relate_batch/forget/blocked/trace/check/suggest_relations"""
import json
import datetime
import logging

from sqlalchemy import func, text as sa_text
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, UnifiedRelation, Tag, atom_tags,
    AtomSchema, SchemaField, AtomFieldValue,
)
from core import relations as rel_service
from core import consistency as consistency_service
from core import embeddings as embed_service

logger = logging.getLogger('beak_broodnest.mcp')


def register(mcp):

    @mcp.tool()
    def note_store(
        title: str,
        content: str = '',
        atom_type: str = 'F',
        content_type: str = 'markdown',
        source: str = 'ai',
        source_detail: str = '',
        owner: str = 'claude',
        tags: list[str] | None = None,
        lifecycle: str = 'active',
        schema_id: int | None = None,
        field_values: dict[str, str] | None = None,
        sensitivity: str = 'internal',
    ) -> str:
        """儲存一筆知識原子到知識庫。

        atom_type 分類:
          A=萬用  B=創意發散  C=思考過程/流程  D=總結歸納  E=套表  F=碎片
        lifecycle: active(活躍) / aging(老化) / archived(歸檔) / terminal(終止)
        source: human / ai / import / derived
        owner: 擁有者 (ethan/claude/agent:xxx/claude@host/tool:name)，預設 claude
        tags: 標籤名稱列表，不存在的標籤會自動建立
        schema_id: E 類型時關聯的 schema ID
        field_values: E 類型的結構化欄位值，格式 {"欄位name": "值"}
        sensitivity: 敏感度 (public/internal/confidential/restricted)，預設 internal

        回傳建立的原子 ID 與摘要。
        """
        valid_types = ('A', 'B', 'C', 'D', 'E', 'F')
        if atom_type not in valid_types:
            return json.dumps({'error': f'無效的 atom_type: {atom_type}，允許值: {", ".join(valid_types)}'})

        valid_sensitivity = ('public', 'internal', 'confidential', 'restricted')
        if sensitivity not in valid_sensitivity:
            return json.dumps({'error': f'無效的 sensitivity: {sensitivity}，允許值: {", ".join(valid_sensitivity)}'})

        with session_scope() as s:
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
                owner=owner,
                schema_id=schema_id,
                sensitivity=sensitivity,
            )
            s.add(atom)
            s.flush()

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
            # needs_embedding=True (default)，由背景 embedder 處理

            result = {
                'id': atom.id,
                'title': atom.title,
                'atom_type': atom.atom_type,
                'lifecycle': atom.lifecycle,
                'owner': atom.owner,
                'tags': [t.name for t in atom.tags],
                'message': f'知識原子已建立 (id={atom.id})',
            }
            if schema_id:
                result['schema_id'] = schema_id
            if field_values:
                result['field_values'] = field_values
            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def note_search(
        query: str = '',
        atom_type: str = '',
        lifecycle: str = '',
        tag: str = '',
        tags: list[str] | None = None,
        source: str = '',
        owner: str = '',
        schema_id: int | None = None,
        limit: int = 20,
        search_mode: str = 'keyword',
        sort: str = '',
        scope: str = 'default',
    ) -> str:
        """搜尋知識庫中的原子。

        query: 關鍵字搜尋(ILIKE 匹配 + pg_trgm 相似度排序)
        atom_type: 篩選類型 (A/B/C/D/E/F)
        lifecycle: 篩選生命週期 (active/aging/archived/terminal)
        tag: 篩選單一標籤名稱(向下相容)
        tags: 多標籤 AND 篩選,原子必須同時擁有所有指定標籤
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

        with session_scope() as s:
            all_tags = list(tags) if tags else []
            if tag and tag not in all_tags:
                all_tags.append(tag)

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
                elif scope != 'full':
                    conditions.append("a.lifecycle IN ('active', 'aging')")
                if source:
                    conditions.append("a.source = :source")
                    params['source'] = source
                if owner:
                    conditions.append("a.owner = :owner")
                    params['owner'] = owner
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

            return json.dumps({
                'total': len(results),
                'returned': len(results),
                'search_mode': search_mode,
                'items': results,
            }, ensure_ascii=False)

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

            if atom.schema_id and atom.schema:
                result['schema'] = atom.schema.to_dict()
                result['schema']['fields'] = [f.to_dict() for f in atom.schema.fields]

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

            blockers = rel_service.get_blockers(s, atom_id)
            result['is_blocked'] = len(blockers) > 0
            result['blockers'] = [
                {'id': b.id, 'title': b.title, 'lifecycle': b.lifecycle}
                for b in blockers
            ]

            return json.dumps(result, ensure_ascii=False)

    @mcp.tool()
    def note_update(
        atom_id: int,
        title: str = '',
        content: str = '',
        atom_type: str = '',
        lifecycle: str = '',
        tags: list[str] | None = None,
        append_content: str = '',
        sensitivity: str = '',
        force_owner_override: bool = False,
    ) -> str:
        """更新現有知識原子的欄位。

        只有提供的欄位會被更新（空字串表示不更新）。
        append_content: 在現有內容後追加（不覆蓋），適合漸進式補充。
        tags: 提供時會替換所有標籤，不存在的標籤會自動建立。
        sensitivity: 敏感度 (public/internal/confidential/restricted)
        force_owner_override: 強制覆寫非自己擁有的原子（預設 False，需明確啟用）

        owner 保護：MCP 呼叫者預設身份為 claude，無法修改 owner != claude 的原子。
        需跨 owner 寫入時設 force_owner_override=True。
        """
        valid_sensitivity = ('public', 'internal', 'confidential', 'restricted')
        if sensitivity and sensitivity not in valid_sensitivity:
            return json.dumps({'error': f'無效的 sensitivity: {sensitivity}，允許值: {", ".join(valid_sensitivity)}'})

        with session_scope() as s:
            atom = s.query(KnowledgeAtom).filter(
                KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
            ).first()
            if not atom:
                return json.dumps({'error': f'原子 {atom_id} 不存在'})

            if atom.owner != 'claude' and not force_owner_override:
                return json.dumps({
                    'error': f'原子 {atom_id} 屬於 {atom.owner}，MCP 預設不可修改。'
                             f'需要跨 owner 寫入請設 force_owner_override=True',
                    'owner': atom.owner,
                })

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
            if sensitivity:
                atom.sensitivity = sensitivity

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

            if title or content or append_content:
                atom.needs_embedding = True

            s.flush()

            return json.dumps({
                'id': atom.id,
                'title': atom.title,
                'lifecycle': atom.lifecycle,
                'owner': atom.owner,
                'sensitivity': atom.sensitivity,
                'tags': [t.name for t in atom.tags],
                'message': f'原子 {atom_id} 已更新',
            }, ensure_ascii=False)

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
          自由: freeform     -- A -> B（無語意約束，純視覺連線）
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
                    s, relation_type=relation_type,
                    from_atom_id=from_atom_id, to_atom_id=to_atom_id,
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
                        s, relation_type=rel_type,
                        from_atom_id=from_id, to_atom_id=to_id,
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
            invalid = [t for t in relation_types if t not in UnifiedRelation.VALID_TYPES]
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
        """
        with session_scope() as s:
            result = consistency_service.check_consistency(
                s, content,
                check_scope=check_scope,
                limit=min(limit, 50),
            )
            return json.dumps(result, ensure_ascii=False)

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
