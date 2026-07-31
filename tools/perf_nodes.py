#!/usr/bin/env python3
"""效能測試：建立指定數量 node + edge 的星狀白板，供人工拖拉測試。

這是**開發輔助工具**不是自動化測試（會實際寫入 DB、需人工開瀏覽器判斷順不順），
所以放在 tools/ 而非 tests/；pytest 不會收它。

用法:
  python tools/perf_nodes.py create 150 300 500    建立多張測試白板
  python tools/perf_nodes.py delete                清除所有測試資料

建立的資料以 source_detail='__perf_test__' 與白板名稱前綴 '[PERF TEST]' 標記，
delete 只會清掉這些標記過的資料。
"""
import sys, math, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.db import init_engine, session_scope
init_engine(config_path=os.path.join(PROJECT_ROOT, 'config.ini'))

from core.models import (
    KnowledgeAtom, AtomRelation, Canvas, CanvasAtom, CanvasConnection,
)

TAG_MARKER = '__perf_test__'
CANVAS_PREFIX = '[PERF TEST]'


def calc_radius(node_count):
    """依節點數量動態計算半徑，避免太擠或太散"""
    return max(1500, node_count * 4)


def create_test(node_count):
    canvas_name = f'{CANVAS_PREFIX} {node_count} nodes'
    edge_count = node_count - 1
    radius = calc_radius(node_count)

    with session_scope() as s:
        existing = s.query(Canvas).filter(Canvas.name == canvas_name).first()
        if existing:
            print(f'  [{node_count}] 已存在 (id={existing.id})，跳過')
            return

        # 1. 知識原子
        atoms = []
        for i in range(node_count):
            atoms.append(KnowledgeAtom(
                title=f'Perf-{node_count} #{i:04d}',
                content=f'## 測試節點 {i:04d}\n\n效能測試用 ({node_count} nodes)。\n\n- 項目 A\n- 項目 B\n- 項目 C',
                atom_type='F',
                source='ai',
                source_detail=TAG_MARKER,
            ))
        s.add_all(atoms)
        s.flush()

        # 2. 白板
        canvas = Canvas(
            name=canvas_name,
            description=f'效能測試：{node_count} node + {edge_count} edge 星狀佈局',
            canvas_type='whiteboard',
        )
        s.add(canvas)
        s.flush()

        # 3. 佈局（中央 + 環繞）
        cx, cy = 5000, 5000
        canvas_atoms = [CanvasAtom(
            canvas_id=canvas.id, atom_id=atoms[0].id,
            pos_x=cx, pos_y=cy, width=200, height=120,
            z_index=10, visual_style='{"bg":"#ef4444"}',
        )]
        for i in range(1, node_count):
            angle = 2 * math.pi * i / (node_count - 1)
            canvas_atoms.append(CanvasAtom(
                canvas_id=canvas.id, atom_id=atoms[i].id,
                pos_x=cx + radius * math.cos(angle),
                pos_y=cy + radius * math.sin(angle),
                width=160, height=80, z_index=1,
            ))
        s.add_all(canvas_atoms)
        s.flush()

        # 4. 關係 + 連線
        relations = []
        for i in range(1, node_count):
            relations.append(AtomRelation(
                from_atom_id=atoms[i].id, to_atom_id=atoms[0].id,
                relation_type='references', confidence=1.0,
            ))
        s.add_all(relations)
        s.flush()

        connections = []
        for i, rel in enumerate(relations):
            connections.append(CanvasConnection(
                canvas_id=canvas.id,
                source_atom_id=canvas_atoms[i + 1].atom_id,
                target_atom_id=canvas_atoms[0].atom_id,
                relation_id=rel.id,
            ))
        s.add_all(connections)
        s.flush()

        print(f'  [{node_count}] 建立完成: {node_count} nodes + {edge_count} edges (canvas id={canvas.id})')


def delete_all():
    with session_scope() as s:
        canvases = s.query(Canvas).filter(Canvas.name.like(f'{CANVAS_PREFIX}%')).all()
        if not canvases:
            print('沒有測試白板')
            return

        for canvas in canvases:
            s.query(CanvasConnection).filter(CanvasConnection.canvas_id == canvas.id).delete()
            s.query(CanvasAtom).filter(CanvasAtom.canvas_id == canvas.id).delete()

        test_atom_ids = [
            a.id for a in s.query(KnowledgeAtom.id).filter(
                KnowledgeAtom.source_detail == TAG_MARKER
            ).all()
        ]
        if test_atom_ids:
            s.query(AtomRelation).filter(
                AtomRelation.from_atom_id.in_(test_atom_ids)
            ).delete(synchronize_session='fetch')

        atom_count = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.source_detail == TAG_MARKER
        ).delete()

        canvas_count = len(canvases)
        for c in canvases:
            s.delete(c)

        print(f'已清除: {canvas_count} 張白板, {atom_count} 原子')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == 'create':
        if len(sys.argv) < 3:
            print('請指定節點數，例如: create 150 300 500')
            sys.exit(1)
        counts = [int(x) for x in sys.argv[2:]]
        for n in counts:
            create_test(n)
        print('\n完成！開啟白板列表選擇名稱以 "[PERF TEST]" 開頭的白板')
    elif cmd == 'delete':
        delete_all()
    else:
        print(__doc__)
        sys.exit(1)
