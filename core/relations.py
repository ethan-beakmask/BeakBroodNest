"""
因果鍊操作 -- CRUD 與圖查詢
"""
from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from core.models import AtomRelation, KnowledgeAtom


def create_relation(
    session: Session,
    from_atom_id: int,
    to_atom_id: int,
    relation_type: str,
    label: str = '',
    confidence: float = 1.0,
    created_by: str = 'human',
) -> AtomRelation:
    """建立一條因果關係"""
    if relation_type not in AtomRelation.VALID_TYPES:
        raise ValueError(
            f"無效的關係類型: {relation_type}，"
            f"允許值: {', '.join(AtomRelation.VALID_TYPES)}"
        )
    rel = AtomRelation(
        from_atom_id=from_atom_id,
        to_atom_id=to_atom_id,
        relation_type=relation_type,
        label=label,
        confidence=confidence,
        created_by=created_by,
    )
    session.add(rel)
    session.flush()
    return rel


def get_relations_from(session: Session, atom_id: int) -> list[AtomRelation]:
    """取得從某原子出發的所有關係"""
    return (
        session.query(AtomRelation)
        .options(joinedload(AtomRelation.to_atom))
        .filter(AtomRelation.from_atom_id == atom_id)
        .all()
    )


def get_relations_to(session: Session, atom_id: int) -> list[AtomRelation]:
    """取得指向某原子的所有關係"""
    return (
        session.query(AtomRelation)
        .options(joinedload(AtomRelation.from_atom))
        .filter(AtomRelation.to_atom_id == atom_id)
        .all()
    )


def get_blockers(session: Session, atom_id: int) -> list[KnowledgeAtom]:
    """
    取得阻塞某原子的所有上游原子（relation_type='blocks'）
    回傳尚未 archived/terminal 的阻塞者
    """
    rels = (
        session.query(AtomRelation)
        .filter(
            AtomRelation.to_atom_id == atom_id,
            AtomRelation.relation_type == 'blocks',
        )
        .all()
    )
    blocker_ids = [r.from_atom_id for r in rels]
    if not blocker_ids:
        return []
    return (
        session.query(KnowledgeAtom)
        .filter(
            KnowledgeAtom.id.in_(blocker_ids),
            KnowledgeAtom.lifecycle.in_(['active', 'aging']),
            KnowledgeAtom.is_deleted == False,
        )
        .all()
    )


def is_blocked(session: Session, atom_id: int) -> bool:
    """檢查某原子是否被阻塞"""
    return len(get_blockers(session, atom_id)) > 0


def trace_block_chain(session: Session, atom_id: int, max_depth: int = 10) -> list[dict]:
    """
    追溯阻塞鍊的根節點
    回傳 [{atom, depth, blockers: [...]}, ...] 由近到遠
    """
    visited = set()
    chain = []

    def _trace(aid, depth):
        if aid in visited or depth > max_depth:
            return
        visited.add(aid)
        blockers = get_blockers(session, aid)
        if blockers:
            for b in blockers:
                chain.append({
                    'atom_id': b.id,
                    'title': b.title,
                    'lifecycle': b.lifecycle,
                    'depth': depth,
                })
                _trace(b.id, depth + 1)

    _trace(atom_id, 1)
    return chain


def delete_relation(session: Session, relation_id: int) -> bool:
    """刪除一條關係"""
    rel = session.get(AtomRelation, relation_id)
    if rel:
        session.delete(rel)
        return True
    return False


def trace_subgraph(
    session: Session,
    atom_id: int,
    direction: str = 'both',
    relation_types: list[str] | None = None,
    max_depth: int = 3,
    include_archived: bool = False,
) -> dict:
    """
    從起點原子出發，沿指定方向/關係類型展開 N 層，回傳子圖。

    direction: 'outgoing' / 'incoming' / 'both'
    relation_types: 過濾關係類型，None 表示全部
    max_depth: 最大展開層數（呼叫端應限制上限）
    include_archived: 是否包含 archived/terminal 原子

    回傳 {'root': {...}, 'nodes': [...], 'edges': [...], 'stats': {...}}
    """
    root_atom = (
        session.query(KnowledgeAtom)
        .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
        .first()
    )
    if not root_atom:
        return {'error': f'原子 {atom_id} 不存在'}

    lifecycle_filter = ['active', 'aging']
    if include_archived:
        lifecycle_filter.extend(['archived', 'terminal'])

    # 收集結果（用 dict 避免重複）
    nodes = {}  # atom_id -> {node_data}
    edges = []  # [{from, to, type, label, confidence}]
    seen_edges = set()  # (from_id, to_id, type) 去重
    visited = set()

    def _expand(current_id: int, depth: int):
        if current_id in visited or depth > max_depth:
            return
        visited.add(current_id)

        queries = []

        if direction in ('outgoing', 'both'):
            q_out = session.query(AtomRelation).filter(
                AtomRelation.from_atom_id == current_id
            )
            if relation_types:
                q_out = q_out.filter(AtomRelation.relation_type.in_(relation_types))
            queries.append(('outgoing', q_out.all()))

        if direction in ('incoming', 'both'):
            q_in = session.query(AtomRelation).filter(
                AtomRelation.to_atom_id == current_id
            )
            if relation_types:
                q_in = q_in.filter(AtomRelation.relation_type.in_(relation_types))
            queries.append(('incoming', q_in.all()))

        for dir_label, rels in queries:
            for rel in rels:
                neighbor_id = rel.to_atom_id if dir_label == 'outgoing' else rel.from_atom_id

                # 去重 edge
                edge_key = (rel.from_atom_id, rel.to_atom_id, rel.relation_type)
                if edge_key in seen_edges:
                    continue

                # 取鄰居原子
                if neighbor_id not in nodes and neighbor_id != atom_id:
                    neighbor = session.get(KnowledgeAtom, neighbor_id)
                    if not neighbor or neighbor.is_deleted:
                        continue
                    if neighbor.lifecycle not in lifecycle_filter:
                        continue
                    nodes[neighbor_id] = {
                        'id': neighbor.id,
                        'title': neighbor.title,
                        'atom_type': neighbor.atom_type,
                        'lifecycle': neighbor.lifecycle,
                        'vitality_score': neighbor.vitality_score,
                        'depth': depth,
                    }

                # 即使鄰居已在 nodes 中（被更淺的路徑加入），edge 仍要記錄
                if neighbor_id in nodes or neighbor_id == atom_id:
                    seen_edges.add(edge_key)
                    edges.append({
                        'from': rel.from_atom_id,
                        'to': rel.to_atom_id,
                        'type': rel.relation_type,
                        'label': rel.label,
                        'confidence': rel.confidence,
                    })

                # 遞迴展開鄰居
                if neighbor_id in nodes:
                    _expand(neighbor_id, depth + 1)

    _expand(atom_id, 1)

    actual_max_depth = max(
        (n['depth'] for n in nodes.values()), default=0
    )

    return {
        'root': {
            'id': root_atom.id,
            'title': root_atom.title,
            'atom_type': root_atom.atom_type,
            'lifecycle': root_atom.lifecycle,
        },
        'nodes': sorted(nodes.values(), key=lambda n: (n['depth'], n['id'])),
        'edges': edges,
        'stats': {
            'total_nodes': len(nodes) + 1,  # +1 for root
            'total_edges': len(edges),
            'max_depth_reached': actual_max_depth,
        },
    }
