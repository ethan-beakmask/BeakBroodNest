# -*- coding: utf-8 -*-
"""Project Dashboard API: 以白板為邊界的專案進度總覽"""

from flask import Blueprint, jsonify
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, UnifiedRelation,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
    CanvasStandaloneEntry, StandaloneEntry,
)

bp = Blueprint('project', __name__)


def _get_entry_field_values(s, entry_ids):
    """批次取得 entry 的欄位值，回傳 {entry_id: {field_name: value}}"""
    if not entry_ids:
        return {}
    rows = (
        s.query(EntryFieldValue)
        .options(joinedload(EntryFieldValue.field))
        .filter(EntryFieldValue.entry_id.in_(entry_ids))
        .all()
    )
    result = {}
    for fv in rows:
        if fv.field:
            result.setdefault(fv.entry_id, {})[fv.field.name] = fv.value
    return result


@bp.route('/api/project/<slug>/summary')
def project_summary(slug):
    """取得專案（白板）的 todo 進度摘要 + 完整任務列表"""

    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        # 取出白板上所有原子 ID
        atom_ids = [
            row[0] for row in
            s.query(CanvasAtom.atom_id)
            .filter(CanvasAtom.canvas_id == canvas.id)
            .all()
        ]
        if not atom_ids:
            return jsonify({
                'canvas': {'id': canvas.id, 'name': canvas.name, 'slug': canvas.slug},
                'summary': {'total': 0, 'planning': 0, 'in_progress': 0,
                            'paused': 0, 'completed': 0, 'cancelled': 0,
                            'blocked': 0, 'h': 0, 'm': 0, 'l': 0},
                'items': [],
                'blocks': [],
            })

        # 取出這些原子的 task entries
        task_schema = s.query(EntrySchema).filter_by(code='task').first()
        if not task_schema:
            return jsonify({'error': 'task schema 不存在'}), 500

        entries = (
            s.query(AtomEntry)
            .options(joinedload(AtomEntry.atom))
            .filter(
                AtomEntry.atom_id.in_(atom_ids),
                AtomEntry.schema_id == task_schema.id,
            )
            .all()
        )

        entry_ids = [e.id for e in entries]
        all_fv = _get_entry_field_values(s, entry_ids)

        # 阻塞狀態：哪些原子被 blocks
        blocking_rels = (
            s.query(UnifiedRelation)
            .join(KnowledgeAtom, KnowledgeAtom.id == UnifiedRelation.from_atom_id)
            .filter(
                UnifiedRelation.to_atom_id.in_(atom_ids),
                UnifiedRelation.relation_type == 'blocks',
                UnifiedRelation.is_deleted == False,
                KnowledgeAtom.lifecycle.in_(['active', 'aging']),
                KnowledgeAtom.is_deleted == False,
            )
            .all()
        )
        blocked_map = {}  # {to_atom_id: [from_atom_id, ...]}
        for rel in blocking_rels:
            blocked_map.setdefault(rel.to_atom_id, []).append(rel.from_atom_id)

        # 所有 blocks 關係（含已完成的，用於依賴圖）
        all_blocks = (
            s.query(UnifiedRelation)
            .filter(
                UnifiedRelation.from_atom_id.in_(atom_ids),
                UnifiedRelation.to_atom_id.in_(atom_ids),
                UnifiedRelation.relation_type == 'blocks',
                UnifiedRelation.is_deleted == False,
            )
            .all()
        )

        # 原子標題快查
        atom_title_map = {}
        for a in s.query(KnowledgeAtom).filter(KnowledgeAtom.id.in_(atom_ids)).all():
            atom_title_map[a.id] = a.title

        # 組裝 items
        items = []
        counts = {'planning': 0, 'in_progress': 0, 'paused': 0,
                  'completed': 0, 'cancelled': 0, 'blocked': 0}
        urgency_counts = {'H': 0, 'M': 0, 'L': 0}

        for entry in entries:
            fv = all_fv.get(entry.id, {})
            status = fv.get('status', 'planning')
            urgency = fv.get('urgency', 'M')
            category = fv.get('category', '')
            # 已完成 / 取消的不視為被阻塞（任務本身已結案）
            is_blocked = (entry.atom_id in blocked_map
                          and status not in ('completed', 'cancelled'))

            if status in counts:
                counts[status] += 1
            if is_blocked:
                counts['blocked'] += 1
            urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1

            blockers = []
            if is_blocked:
                for bid in blocked_map[entry.atom_id]:
                    blockers.append({
                        'atom_id': bid,
                        'title': atom_title_map.get(bid, f'#{bid}'),
                    })

            items.append({
                'atom_id': entry.atom_id,
                'entry_id': entry.id,
                'title': entry.atom.title if entry.atom else '',
                'description': entry.raw_text or entry.atom.content if entry.atom else '',
                'status': status,
                'urgency': urgency,
                'category': category,
                'planned_start': fv.get('planned_start', ''),
                'planned_end': fv.get('planned_end', ''),
                'planned_duration': fv.get('planned_duration', ''),
                'actual_start': fv.get('actual_start', ''),
                'actual_end': fv.get('actual_end', ''),
                'is_blocked': is_blocked,
                'blockers': blockers,
            })

        # ----- standalone_entries（白板獨立 task entry，P3a 新增物件） -----
        se_rows = (
            s.query(StandaloneEntry, CanvasStandaloneEntry)
            .join(CanvasStandaloneEntry,
                  CanvasStandaloneEntry.standalone_entry_id == StandaloneEntry.id)
            .filter(
                CanvasStandaloneEntry.canvas_id == canvas.id,
                StandaloneEntry.is_deleted == False,  # noqa: E712
                StandaloneEntry.schema_id == task_schema.id,
            )
            .all()
        )
        for se, _cse in se_rows:
            fv = se.field_values or {}
            status = str(fv.get('status') or 'planning')
            urgency = str(fv.get('urgency') or 'M')
            category = str(fv.get('category') or '')

            if status in counts:
                counts[status] += 1
            urgency_counts[urgency] = urgency_counts.get(urgency, 0) + 1

            entry_text = (se.raw_text or '').strip() or (se.summary or '').strip()
            title = entry_text[:80] if entry_text else f'#se{se.id}'

            items.append({
                'atom_id': None,
                'entry_id': se.id,
                'standalone_entry_id': se.id,
                'source': 'standalone_entry',
                'title': title,
                'description': se.raw_text or '',
                'status': status,
                'urgency': urgency,
                'category': category,
                'planned_start': str(fv.get('planned_start') or ''),
                'planned_end': str(fv.get('planned_end') or ''),
                'planned_duration': str(fv.get('planned_duration') or ''),
                'actual_start': str(fv.get('actual_start') or ''),
                'actual_end': str(fv.get('actual_end') or ''),
                'is_blocked': False,
                'blockers': [],
            })

        # 既有 atom-entry items 加 source 標記
        for it in items:
            it.setdefault('source', 'atom_entry')

        # urgency 排序: H > M > L, blocked 優先顯示
        urgency_order = {'H': 0, 'M': 1, 'L': 2}
        status_order = {'planning': 0, 'in_progress': 1, 'paused': 2,
                        'completed': 3, 'cancelled': 4}
        items.sort(key=lambda x: (
            status_order.get(x['status'], 9),
            -int(x['is_blocked']),
            urgency_order.get(x['urgency'], 9),
        ))

        blocks_list = [
            {
                'from_id': r.from_atom_id,
                'from_title': atom_title_map.get(r.from_atom_id, ''),
                'to_id': r.to_atom_id,
                'to_title': atom_title_map.get(r.to_atom_id, ''),
            }
            for r in all_blocks
        ]

        # 組裝 BeakTrellis 樹狀資料（依 category 分組）
        # blocks 關係轉為 {from_atom_id: [to_atom_id, ...]}
        blocks_by_from = {}
        for rel in all_blocks:
            blocks_by_from.setdefault(rel.from_atom_id, []).append(rel.to_atom_id)

        cat_groups = {}  # {category: [item, ...]}
        for item in items:
            cat = item['category'] or '未分類'
            cat_groups.setdefault(cat, []).append(item)

        # 計算每個 category 的聚合狀態
        cat_order = ['安全性', '文件', '測試', '功能', '復盤Pipeline', '基建']
        trellis_data = []
        for cat in cat_order + [c for c in cat_groups if c not in cat_order]:
            if cat not in cat_groups:
                continue
            group_items = cat_groups[cat]
            done_count = sum(1 for i in group_items if i['status'] == 'completed')
            total = len(group_items)
            group_status = 'completed' if done_count == total else (
                'in_progress' if any(i['status'] == 'in_progress' for i in group_items) else 'planning'
            )
            children = []
            for item in group_items:
                if item.get('source') == 'standalone_entry':
                    node_id = f"se-{item['entry_id']}"
                else:
                    node_id = str(item['atom_id'])
                children.append({
                    'id': node_id,
                    'label': item['title'],
                    'data': {
                        'status': item['status'],
                        'urgency': item['urgency'],
                        'planned_start': item['planned_start'] or None,
                        'planned_end': item['planned_end'] or item['actual_end'] or item['planned_duration'] or None,
                        'actual_start': item['actual_start'] or None,
                        'actual_end': item['actual_end'] or None,
                        'blocks': [str(tid) for tid in blocks_by_from.get(item['atom_id'], [])] if item.get('atom_id') else [],
                        'is_blocked': item['is_blocked'],
                        'category': item['category'],
                        'description': item['description'],
                    },
                    'children': [],
                })
            trellis_data.append({
                'id': 'cat-' + cat,
                'label': cat,
                'expanded': True,
                'data': {
                    'status': group_status,
                    'urgency': 'H' if any(i['urgency'] == 'H' for i in group_items) else 'M',
                    'planned_start': None,
                    'planned_end': None,
                    'actual_start': None,
                    'actual_end': None,
                    'blocks': [],
                    'is_blocked': False,
                    'category': cat,
                    'description': f'{done_count}/{total} 完成',
                },
                'children': children,
            })

        return jsonify({
            'canvas': {
                'id': canvas.id,
                'name': canvas.name,
                'slug': canvas.slug,
            },
            'summary': {
                'total': len(items),
                'planning': counts['planning'],
                'in_progress': counts['in_progress'],
                'paused': counts['paused'],
                'completed': counts['completed'],
                'cancelled': counts['cancelled'],
                'blocked': counts['blocked'],
                'h': urgency_counts.get('H', 0),
                'm': urgency_counts.get('M', 0),
                'l': urgency_counts.get('L', 0),
            },
            'items': items,
            'blocks': blocks_list,
            'trellis_data': trellis_data,
        })


# ------------------------------------------------------------------
# WBS (Work Breakdown Structure) API
# ------------------------------------------------------------------

def _topo_sort_siblings(nodes, predecessor_map):
    """在同層 siblings 中依前置關係做拓撲排序，無關係的按 title 排"""
    if len(nodes) <= 1:
        return nodes

    sibling_ids = {n['atom_id'] for n in nodes}
    node_map = {n['atom_id']: n for n in nodes}

    in_degree = {n['atom_id']: 0 for n in nodes}
    adj = {n['atom_id']: [] for n in nodes}

    for node in nodes:
        for pred_id in predecessor_map.get(node['atom_id'], []):
            if pred_id in sibling_ids:
                adj[pred_id].append(node['atom_id'])
                in_degree[node['atom_id']] += 1

    queue = sorted(
        [nid for nid, deg in in_degree.items() if deg == 0],
        key=lambda x: node_map[x]['title'],
    )
    result = []
    while queue:
        nid = queue.pop(0)
        result.append(node_map[nid])
        for next_id in adj.get(nid, []):
            in_degree[next_id] -= 1
            if in_degree[next_id] == 0:
                queue.append(next_id)
        queue.sort(key=lambda x: node_map[x]['title'])

    seen = {r['atom_id'] for r in result}
    result.extend(n for n in nodes if n['atom_id'] not in seen)
    return result


@bp.route('/api/project/<slug>/wbs')
def project_wbs(slug):
    """WBS 樹狀結構：contains 為階層，follows/blocks 為先後"""

    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        atom_ids = [
            row[0] for row in
            s.query(CanvasAtom.atom_id)
            .filter(CanvasAtom.canvas_id == canvas.id)
            .all()
        ]
        if not atom_ids:
            return jsonify({
                'canvas': {'id': canvas.id, 'name': canvas.name, 'slug': canvas.slug},
                'tree': [], 'edges': [],
            })

        atoms = {
            a.id: a for a in
            s.query(KnowledgeAtom).filter(KnowledgeAtom.id.in_(atom_ids)).all()
        }

        # task entries + field values
        task_schema = s.query(EntrySchema).filter_by(code='task').first()
        entries_by_atom = {}
        if task_schema:
            entries = (
                s.query(AtomEntry)
                .filter(
                    AtomEntry.atom_id.in_(atom_ids),
                    AtomEntry.schema_id == task_schema.id,
                )
                .all()
            )
            all_fv = _get_entry_field_values(s, [e.id for e in entries])
            for entry in entries:
                fv = all_fv.get(entry.id, {})
                entries_by_atom[entry.atom_id] = {
                    'entry_id': entry.id,
                    'status': fv.get('status', 'planning'),
                    'urgency': fv.get('urgency', 'M'),
                    'category': fv.get('category', ''),
                    'planned_start': fv.get('planned_start', ''),
                    'planned_end': fv.get('planned_end', ''),
                    'actual_start': fv.get('actual_start', ''),
                    'actual_end': fv.get('actual_end', ''),
                    'planned_duration': fv.get('planned_duration', ''),
                    'progress': fv.get('progress', ''),
                }

        # 取出白板原子間的三種關係
        relations = (
            s.query(UnifiedRelation)
            .filter(
                UnifiedRelation.from_atom_id.in_(atom_ids),
                UnifiedRelation.to_atom_id.in_(atom_ids),
                UnifiedRelation.relation_type.in_(['contains', 'follows', 'blocks']),
                UnifiedRelation.is_deleted == False,
            )
            .all()
        )

        contains_children = {}   # parent -> [child, ...]
        contained_set = set()
        follows_map = {}         # atom -> [predecessors via follows]
        blocked_by_map = {}      # atom -> [predecessors via blocks]
        edges = []

        for rel in relations:
            edges.append({
                'from_id': rel.from_atom_id,
                'to_id': rel.to_atom_id,
                'type': rel.relation_type,
                'from_title': atoms[rel.from_atom_id].title if rel.from_atom_id in atoms else '',
                'to_title': atoms[rel.to_atom_id].title if rel.to_atom_id in atoms else '',
            })
            if rel.relation_type == 'contains':
                contains_children.setdefault(rel.from_atom_id, []).append(rel.to_atom_id)
                contained_set.add(rel.to_atom_id)
            elif rel.relation_type == 'follows':
                # from follows to = to 是 from 的前置
                follows_map.setdefault(rel.from_atom_id, []).append(rel.to_atom_id)
            elif rel.relation_type == 'blocks':
                # from blocks to = from 是 to 的前置
                blocked_by_map.setdefault(rel.to_atom_id, []).append(rel.from_atom_id)

        # 合併前置關係
        predecessor_map = {}
        all_ids = set(atom_ids)
        for aid in all_ids:
            preds = list(set(
                follows_map.get(aid, []) + blocked_by_map.get(aid, [])
            ))
            if preds:
                predecessor_map[aid] = preds

        def build_node(atom_id):
            atom = atoms.get(atom_id)
            if not atom:
                return None
            ed = entries_by_atom.get(atom_id, {})

            children = []
            for cid in contains_children.get(atom_id, []):
                child = build_node(cid)
                if child:
                    children.append(child)
            children = _topo_sort_siblings(children, predecessor_map)

            preds = []
            for pid in predecessor_map.get(atom_id, []):
                if pid in atoms:
                    rel_type = 'follows' if pid in follows_map.get(atom_id, []) else 'blocks'
                    preds.append({
                        'atom_id': pid,
                        'title': atoms[pid].title,
                        'rel': rel_type,
                    })

            return {
                'atom_id': atom_id,
                'title': atom.title,
                'content': atom.content or '',
                'status': ed.get('status', ''),
                'urgency': ed.get('urgency', ''),
                'category': ed.get('category', ''),
                'entry_id': ed.get('entry_id'),
                'planned_start': ed.get('planned_start', ''),
                'planned_end': ed.get('planned_end', ''),
                'actual_start': ed.get('actual_start', ''),
                'actual_end': ed.get('actual_end', ''),
                'planned_duration': ed.get('planned_duration', ''),
                'progress': ed.get('progress', ''),
                'predecessors': preds,
                'children': children,
            }

        root_ids = [aid for aid in atom_ids if aid not in contained_set]
        tree = [n for n in (build_node(rid) for rid in root_ids) if n]
        tree = _topo_sort_siblings(tree, predecessor_map)

        return jsonify({
            'canvas': {'id': canvas.id, 'name': canvas.name, 'slug': canvas.slug},
            'tree': tree,
            'edges': edges,
        })
