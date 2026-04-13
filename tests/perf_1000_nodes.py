#!/usr/bin/env python3
"""效能測試：建立 1000 node + 999 edge 的星狀白板，供人工拖拉測試。

用法:
  python tests/perf_1000_nodes.py create   建立測試白板
  python tests/perf_1000_nodes.py delete   清除測試資料
"""
import sys, math, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import init_engine, session_scope

# dev 目錄沒有 config.ini，指向運行目錄
init_engine(config_path='/opt/BeakCortex/config.ini')
from core.models import (
    KnowledgeAtom, AtomRelation, Canvas, CanvasAtom, CanvasConnection,
)

CANVAS_NAME = '[PERF TEST] 1000 nodes'
TAG_MARKER = '__perf_test__'
NODE_COUNT = 1000
RADIUS = 4000  # 外圈半徑（px）


def create_test():
    with session_scope() as s:
        # 檢查是否已存在
        existing = s.query(Canvas).filter(Canvas.name == CANVAS_NAME).first()
        if existing:
            print(f'測試白板已存在 (id={existing.id})，請先執行 delete')
            return

        # 1. 建立 1000 個知識原子
        atoms = []
        for i in range(NODE_COUNT):
            atom = KnowledgeAtom(
                title=f'Perf Node {i:04d}',
                content=f'## 效能測試節點 {i:04d}\n\n這是第 {i} 個測試節點，用於驗證白板在大量卡片下的拖拉效能。\n\n- 項目 A\n- 項目 B\n- 項目 C',
                atom_type='F',
                source='ai',
                source_detail=TAG_MARKER,
            )
            atoms.append(atom)
        s.add_all(atoms)
        s.flush()
        print(f'建立 {NODE_COUNT} 個原子 (id {atoms[0].id} ~ {atoms[-1].id})')

        # 2. 建立白板
        canvas = Canvas(
            name=CANVAS_NAME,
            description='效能測試：1000 node + 999 edge 星狀佈局',
            canvas_type='whiteboard',
        )
        s.add(canvas)
        s.flush()
        print(f'建立白板 id={canvas.id}')

        # 3. 放置原子到白板（星狀佈局：node 0 在中央，其餘環繞）
        center_x, center_y = 5000, 5000
        canvas_atoms = []

        # 中央節點
        ca_center = CanvasAtom(
            canvas_id=canvas.id,
            atom_id=atoms[0].id,
            pos_x=center_x,
            pos_y=center_y,
            width=200,
            height=120,
            z_index=10,
            visual_style='{"bg":"#ef4444"}',
        )
        canvas_atoms.append(ca_center)

        # 外圈節點（均勻分布）
        for i in range(1, NODE_COUNT):
            angle = 2 * math.pi * i / (NODE_COUNT - 1)
            px = center_x + RADIUS * math.cos(angle)
            py = center_y + RADIUS * math.sin(angle)
            ca = CanvasAtom(
                canvas_id=canvas.id,
                atom_id=atoms[i].id,
                pos_x=px,
                pos_y=py,
                width=160,
                height=80,
                z_index=1,
            )
            canvas_atoms.append(ca)

        s.add_all(canvas_atoms)
        s.flush()
        print(f'放置 {len(canvas_atoms)} 個卡片到白板')

        # 4. 建立 999 條關係 + 連線（每個外圈 -> 中央）
        relations = []
        for i in range(1, NODE_COUNT):
            rel = AtomRelation(
                from_atom_id=atoms[i].id,
                to_atom_id=atoms[0].id,
                relation_type='references',
                confidence=1.0,
            )
            relations.append(rel)
        s.add_all(relations)
        s.flush()

        connections = []
        for i, rel in enumerate(relations):
            conn = CanvasConnection(
                canvas_id=canvas.id,
                source_atom_id=canvas_atoms[i + 1].atom_id,
                target_atom_id=canvas_atoms[0].atom_id,
                relation_id=rel.id,
            )
            connections.append(conn)
        s.add_all(connections)
        s.flush()
        print(f'建立 {len(relations)} 條關係 + 連線')

        print(f'\n完成！開啟白板: http://192.168.0.16:5170/ 選擇 "{CANVAS_NAME}"')


def delete_test():
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.name == CANVAS_NAME).first()
        if not canvas:
            print('測試白板不存在')
            return

        # 刪連線
        conn_count = s.query(CanvasConnection).filter(
            CanvasConnection.canvas_id == canvas.id
        ).delete()

        # 取得測試原子 ID
        test_atom_ids = [
            a.id for a in s.query(KnowledgeAtom.id).filter(
                KnowledgeAtom.source_detail == TAG_MARKER
            ).all()
        ]

        # 刪白板原子
        ca_count = s.query(CanvasAtom).filter(
            CanvasAtom.canvas_id == canvas.id
        ).delete()

        # 刪關係
        if test_atom_ids:
            rel_count = s.query(AtomRelation).filter(
                AtomRelation.from_atom_id.in_(test_atom_ids)
            ).delete(synchronize_session='fetch')
        else:
            rel_count = 0

        # 刪原子
        atom_count = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.source_detail == TAG_MARKER
        ).delete()

        # 刪白板
        s.delete(canvas)

        print(f'已清除: {atom_count} 原子, {rel_count} 關係, {ca_count} 白板卡片, {conn_count} 連線, 1 白板')


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in ('create', 'delete'):
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == 'create':
        create_test()
    else:
        delete_test()
