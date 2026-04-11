"""
一致性檢查 -- 比對新內容與既有知識庫的重複/矛盾
"""
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from core.models import KnowledgeAtom, AtomRelation, Tag, atom_tags


def check_consistency(
    session: Session,
    content: str,
    check_scope: str = 'all',
    limit: int = 10,
) -> dict:
    """
    給定一段文字，比對既有知識庫回報：
    - similar: pg_trgm 相似度最高的原子
    - contradictions: 相似原子的 contradicts/refutes 關係鏈
    - suggestion: duplicate_suspect / contradiction_found / novel

    check_scope: 'all' 或指定 tag 名稱縮小範圍
    """
    if not content or not content.strip():
        return {'error': '內容不可為空'}

    limit = min(limit, 50)

    # 相似度計算：取 title 和 content 的最大相似度
    sim_expr = func.greatest(
        func.similarity(KnowledgeAtom.title, content),
        func.similarity(KnowledgeAtom.content, content),
    )

    q = (
        session.query(KnowledgeAtom, sim_expr.label('sim'))
        .filter(
            KnowledgeAtom.is_deleted == False,
            KnowledgeAtom.lifecycle.in_(['active', 'aging']),
        )
        # pg_trgm 相似度 > 0 才回傳
        .filter(sim_expr > 0.1)
    )

    # 縮小範圍到指定 tag
    if check_scope and check_scope != 'all':
        q = q.join(KnowledgeAtom.tags).filter(Tag.name == check_scope)

    q = q.order_by(sim_expr.desc()).limit(limit)
    rows = q.all()

    similar = []
    similar_ids = []
    for atom, sim_score in rows:
        similar.append({
            'id': atom.id,
            'title': atom.title,
            'atom_type': atom.atom_type,
            'lifecycle': atom.lifecycle,
            'similarity': round(float(sim_score), 4),
            'match_type': 'trgm',
        })
        similar_ids.append(atom.id)

    # 矛盾偵測：檢查相似原子的 contradicts / refutes 關係
    contradictions = []
    if similar_ids:
        # 從相似原子出發，找 contradicts/refutes 的 outgoing 和 incoming
        conflict_rels = (
            session.query(AtomRelation)
            .filter(
                AtomRelation.relation_type.in_(['contradicts', 'refutes']),
                or_(
                    AtomRelation.from_atom_id.in_(similar_ids),
                    AtomRelation.to_atom_id.in_(similar_ids),
                ),
            )
            .all()
        )

        seen_conflicts = set()
        for rel in conflict_rels:
            # 找到衝突的另一端
            if rel.from_atom_id in similar_ids:
                conflict_atom_id = rel.to_atom_id
                direction = 'outgoing'
            else:
                conflict_atom_id = rel.from_atom_id
                direction = 'incoming'

            if conflict_atom_id in seen_conflicts:
                continue
            seen_conflicts.add(conflict_atom_id)

            conflict_atom = session.get(KnowledgeAtom, conflict_atom_id)
            if not conflict_atom or conflict_atom.is_deleted:
                continue

            # 找到相似原子中與此衝突相關的那個
            anchor_id = rel.from_atom_id if direction == 'outgoing' else rel.to_atom_id
            anchor = next((s for s in similar if s['id'] == anchor_id), None)
            anchor_title = anchor['title'] if anchor else f'#{anchor_id}'

            contradictions.append({
                'id': conflict_atom.id,
                'title': conflict_atom.title,
                'lifecycle': conflict_atom.lifecycle,
                'relation_type': rel.relation_type,
                'relation_chain': (
                    f'#{anchor_id} ({anchor_title}) '
                    f'{rel.relation_type} #{conflict_atom.id} ({conflict_atom.title})'
                ),
            })

    # 建議判斷（純規則，不替 AI 做決策）
    suggestion = 'novel'
    if similar and similar[0]['similarity'] > 0.8:
        suggestion = 'duplicate_suspect'
    if contradictions:
        suggestion = 'contradiction_found'

    return {
        'similar': similar,
        'contradictions': contradictions,
        'suggestion': suggestion,
    }
