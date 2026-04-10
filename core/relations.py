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
