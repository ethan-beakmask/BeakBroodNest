"""
關係操作 -- CRUD 與圖查詢
統一使用 unified_relations 表，支援 atom/entry 混合端點。
所有查詢加入 is_deleted = FALSE 過濾。
"""
from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session, joinedload

from core.models import UnifiedRelation, KnowledgeAtom, RelationTypeRegistry


def create_relation(
    session: Session,
    relation_type: str,
    from_atom_id: int | None = None,
    from_entry_id: int | None = None,
    to_atom_id: int | None = None,
    to_entry_id: int | None = None,
    label: str = '',
    confidence: float = 1.0,
    created_by: str = 'human',
) -> UnifiedRelation:
    """建立一條關係。

    端點二擇一：
      from_atom_id 或 from_entry_id 填其一
      to_atom_id 或 to_entry_id 填其一

    graph_family / semantic_layer / affects_scheduling
    由 DB trigger 從 relation_type_registry 自動填入。
    """
    if relation_type not in UnifiedRelation.VALID_TYPES:
        raise ValueError(
            f"無效的關係類型: {relation_type}，"
            f"允許值: {', '.join(UnifiedRelation.VALID_TYPES)}"
        )

    # 驗證端點
    from_count = (from_atom_id is not None) + (from_entry_id is not None)
    to_count = (to_atom_id is not None) + (to_entry_id is not None)
    if from_count != 1:
        raise ValueError("來源端必須且僅能填 from_atom_id 或 from_entry_id 其一")
    if to_count != 1:
        raise ValueError("目標端必須且僅能填 to_atom_id 或 to_entry_id 其一")

    rel = UnifiedRelation(
        from_atom_id=from_atom_id,
        from_entry_id=from_entry_id,
        to_atom_id=to_atom_id,
        to_entry_id=to_entry_id,
        relation_type=relation_type,
        label=label,
        confidence=confidence,
        created_by=created_by,
    )
    session.add(rel)
    session.flush()
    session.refresh(rel)
    return rel


# ============================================================
# Atom-level 查詢（向後相容 MCP 工具）
# ============================================================

def get_relations_from(session: Session, atom_id: int) -> list[UnifiedRelation]:
    """取得從某 Card 出發的所有關係（排除已軟刪除）"""
    return (
        session.query(UnifiedRelation)
        .options(joinedload(UnifiedRelation.to_atom))
        .filter(
            UnifiedRelation.from_atom_id == atom_id,
            UnifiedRelation.is_deleted == False,
        )
        .all()
    )


def get_relations_to(session: Session, atom_id: int) -> list[UnifiedRelation]:
    """取得指向某 Card 的所有關係（排除已軟刪除）"""
    return (
        session.query(UnifiedRelation)
        .options(joinedload(UnifiedRelation.from_atom))
        .filter(
            UnifiedRelation.to_atom_id == atom_id,
            UnifiedRelation.is_deleted == False,
        )
        .all()
    )


def get_blockers(session: Session, atom_id: int) -> list[KnowledgeAtom]:
    """
    取得阻塞某 Card 的所有上游 Card（relation_type='blocks'）
    回傳尚未 archived/terminal 的阻塞者
    """
    rels = (
        session.query(UnifiedRelation)
        .filter(
            UnifiedRelation.to_atom_id == atom_id,
            UnifiedRelation.relation_type == 'blocks',
            UnifiedRelation.is_deleted == False,
        )
        .all()
    )
    blocker_ids = [r.from_atom_id for r in rels if r.from_atom_id]
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
    """檢查某 Card 是否被阻塞"""
    return len(get_blockers(session, atom_id)) > 0


def trace_block_chain(session: Session, atom_id: int, max_depth: int = 10) -> list[dict]:
    """
    追溯阻塞鍊的根節點
    回傳 [{atom_id, title, lifecycle, depth}, ...] 由近到遠
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


# ============================================================
# 軟刪除 / 還原 / 硬刪除
# ============================================================

def soft_delete_relation(session: Session, relation_id: int) -> bool:
    """軟刪除一條關係"""
    rel = session.get(UnifiedRelation, relation_id)
    if rel and not rel.is_deleted:
        rel.is_deleted = True
        session.flush()
        return True
    return False


def restore_relation(session: Session, relation_id: int) -> bool:
    """還原一條軟刪除的關係"""
    rel = session.get(UnifiedRelation, relation_id)
    if rel and rel.is_deleted:
        rel.is_deleted = False
        session.flush()
        return True
    return False


def delete_relation(session: Session, relation_id: int) -> bool:
    """硬刪除一條關係"""
    rel = session.get(UnifiedRelation, relation_id)
    if rel:
        session.delete(rel)
        return True
    return False


# ============================================================
# 環偵測
# ============================================================

def check_cycle(
    session: Session,
    from_atom_id: int | None,
    to_atom_id: int | None,
    graph_family: str,
) -> bool:
    """檢查新增 atom-atom 邊是否會在指定 graph_family 中產生環。

    使用 Python 層 BFS 偵測（不依賴 DB function）。
    回傳 True 表示會產生環。
    """
    if not from_atom_id or not to_atom_id:
        return False
    if from_atom_id == to_atom_id:
        return True

    # BFS: 從 to 出發，沿 from_atom_id -> to_atom_id 方向走，看能否到達 from
    visited = set()
    queue = [to_atom_id]
    while queue:
        current = queue.pop(0)
        if current == from_atom_id:
            return True
        if current in visited:
            continue
        visited.add(current)
        neighbors = (
            session.query(UnifiedRelation.to_atom_id)
            .filter(
                UnifiedRelation.from_atom_id == current,
                UnifiedRelation.graph_family == graph_family,
                UnifiedRelation.is_deleted == False,
                UnifiedRelation.to_atom_id.isnot(None),
            )
            .all()
        )
        for (nid,) in neighbors:
            if nid not in visited:
                queue.append(nid)
    return False


# ============================================================
# 子圖展開
# ============================================================

def trace_subgraph(
    session: Session,
    atom_id: int,
    direction: str = 'both',
    relation_types: list[str] | None = None,
    max_depth: int = 3,
    include_archived: bool = False,
) -> dict:
    """
    從起點 Card 出發，沿指定方向/關係類型展開 N 層，回傳子圖。

    direction: 'outgoing' / 'incoming' / 'both'
    relation_types: 過濾關係類型，None 表示全部
    max_depth: 最大展開層數
    include_archived: 是否包含 archived/terminal

    回傳 {'root': {...}, 'nodes': [...], 'edges': [...], 'stats': {...}}
    """
    root_atom = (
        session.query(KnowledgeAtom)
        .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
        .first()
    )
    if not root_atom:
        return {'error': f'卡片 {atom_id} 不存在'}

    lifecycle_filter = ['active', 'aging']
    if include_archived:
        lifecycle_filter.extend(['archived', 'terminal'])

    nodes = {}
    edges = []
    seen_edges = set()
    visited = set()

    def _expand(current_id: int, depth: int):
        if current_id in visited or depth > max_depth:
            return
        visited.add(current_id)

        queries = []

        if direction in ('outgoing', 'both'):
            q_out = session.query(UnifiedRelation).filter(
                UnifiedRelation.from_atom_id == current_id,
                UnifiedRelation.is_deleted == False,
            )
            if relation_types:
                q_out = q_out.filter(UnifiedRelation.relation_type.in_(relation_types))
            queries.append(('outgoing', q_out.all()))

        if direction in ('incoming', 'both'):
            q_in = session.query(UnifiedRelation).filter(
                UnifiedRelation.to_atom_id == current_id,
                UnifiedRelation.is_deleted == False,
            )
            if relation_types:
                q_in = q_in.filter(UnifiedRelation.relation_type.in_(relation_types))
            queries.append(('incoming', q_in.all()))

        for dir_label, rels in queries:
            for rel in rels:
                neighbor_id = rel.to_atom_id if dir_label == 'outgoing' else rel.from_atom_id
                if not neighbor_id:
                    continue

                edge_key = (rel.from_atom_id, rel.to_atom_id, rel.relation_type)
                if edge_key in seen_edges:
                    continue

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

                if neighbor_id in nodes or neighbor_id == atom_id:
                    seen_edges.add(edge_key)
                    edges.append({
                        'from': rel.from_atom_id,
                        'to': rel.to_atom_id,
                        'type': rel.relation_type,
                        'label': rel.label,
                        'confidence': rel.confidence,
                    })

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
            'total_nodes': len(nodes) + 1,
            'total_edges': len(edges),
            'max_depth_reached': actual_max_depth,
        },
    }


# ============================================================
# Registry 查詢
# ============================================================

def get_relation_types(session: Session) -> list[dict]:
    """取得所有關係類型定義"""
    regs = (
        session.query(RelationTypeRegistry)
        .order_by(RelationTypeRegistry.sort_order)
        .all()
    )
    return [r.to_dict() for r in regs]
