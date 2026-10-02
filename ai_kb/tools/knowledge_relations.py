# -*- coding: utf-8 -*-
"""知識關係工具: note_relate/relate_batch/blocked/trace/suggest_relations"""
import json

from sqlalchemy import text as sa_text

from core.db import session_scope
from core.models import KnowledgeAtom, UnifiedRelation
from core import relations as rel_service
from core.ref_code import resolve_ref
from .param_forms import (
    ParamFormatError,
    param_format_error_payload,
    parse_relations,
)


def register(mcp):

    @mcp.tool()
    def note_relate(
        from_atom_id: int = 0,
        to_atom_id: int = 0,
        relation_type: str = '',
        label: str = '',
        confidence: float = 1.0,
        from_ref: str = '',
        to_ref: str = '',
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
        建議用 from_ref="BBN-137" / to_ref="BBN-138" 這種短代號，比記數字 id 可靠。
        既有 from_atom_id / to_atom_id 數字 id 呼叫方式仍可使用。
        """
        with session_scope() as s:
            try:
                if from_ref:
                    atom = resolve_ref(s, from_ref)
                    if not atom:
                        return json.dumps({'error': f'找不到來源卡片：{from_ref}'}, ensure_ascii=False)
                    from_atom_id = atom.id
                if to_ref:
                    atom = resolve_ref(s, to_ref)
                    if not atom:
                        return json.dumps({'error': f'找不到目標卡片：{to_ref}'}, ensure_ascii=False)
                    to_atom_id = atom.id
                if not from_atom_id or not to_atom_id:
                    return json.dumps({'error': '必須提供 from_ref/from_atom_id 與 to_ref/to_atom_id'}, ensure_ascii=False)
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
        relations: str | list[dict],
    ) -> str:
        """批次建立多條因果關係。

        relations: 推薦字串形式，多行「from_ref -> to_ref : relation_type [: label]」，例如:
          BBN-137 -> BBN-138 : supports : 補充中文標籤
          BBN-139 -> BBN-140 : references
          字串形式不支援 confidence，固定使用預設 1.0。
          請勿用陣列 / 物件傳中文，會被拒絕。相容形式為 list[dict]（僅限純 ASCII）:
          {
            "from_atom_id": int,
            "to_atom_id": int,
            "from_ref": "BBN-137",
            "to_ref": "BBN-138",
            "relation_type": str,  -- 同 note_relate 的允許值
            "label": str,          -- 選填
            "confidence": float    -- 選填，預設 1.0
          }

        回傳每條關係的建立結果（成功或錯誤）。
        """
        if isinstance(relations, str):
            try:
                relations = parse_relations(relations)
            except ParamFormatError as e:
                return json.dumps(param_format_error_payload(e), ensure_ascii=False)

        if not relations:
            return json.dumps({'error': 'relations 不可為空'})

        results = []
        with session_scope() as s:
            for i, r in enumerate(relations):
                from_id = r.get('from_atom_id')
                to_id = r.get('to_atom_id')
                from_ref = r.get('from_ref', '')
                to_ref = r.get('to_ref', '')
                rel_type = r.get('relation_type', '')
                label = r.get('label', '')
                confidence = r.get('confidence', 1.0)

                if from_ref:
                    atom = resolve_ref(s, from_ref)
                    if not atom:
                        results.append({'index': i, 'error': f'找不到來源卡片：{from_ref}'})
                        continue
                    from_id = atom.id
                if to_ref:
                    atom = resolve_ref(s, to_ref)
                    if not atom:
                        results.append({'index': i, 'error': f'找不到目標卡片：{to_ref}'})
                        continue
                    to_id = atom.id

                if not from_id or not to_id or not rel_type:
                    results.append({
                        'index': i,
                        'error': '缺少必要欄位 (from_ref/from_atom_id, to_ref/to_atom_id, relation_type)',
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
