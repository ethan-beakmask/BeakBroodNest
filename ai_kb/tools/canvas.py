# -*- coding: utf-8 -*-
"""Canvas 工具: canvas_list/create/get/place_atom/remove_atom"""
import json

from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, CanvasConnection, CanvasGroup,
)


def register(mcp):

    @mcp.tool()
    def canvas_list(
        include_archived: bool = False,
    ) -> str:
        """列出所有畫布及其基本資訊。

        include_archived: 是否包含已歸檔的畫布（預設 False）
        """
        with session_scope() as s:
            q = s.query(Canvas)
            if not include_archived:
                q = q.filter(Canvas.is_archived == False)
            canvases = q.order_by(Canvas.updated_at.desc()).all()
            return json.dumps({
                'total': len(canvases),
                'items': [c.to_dict() for c in canvases],
            }, ensure_ascii=False)

    @mcp.tool()
    def canvas_create(
        name: str,
        description: str = '',
        canvas_type: str = 'whiteboard',
        owner: str = 'claude',
        audience: str = 'ai',
    ) -> str:
        """建立新畫布。

        canvas_type: whiteboard / mindmap / flowchart / cornell / template
        owner: 擁有者 (ethan/claude/agent:xxx)，預設 claude
        audience: 受眾，決定 AI 搜尋時讀不讀這張白板上的卡片
          ai     -- AI 工作區（預設，AI 自己建的白板）
          shared -- 雙方共用
          human  -- 使用者自用，AI 預設不讀；名稱慣例加 👤 前綴

        AI 不要建 audience='human' 的白板，那是使用者自己的空間。
        """
        valid_types = ('whiteboard', 'mindmap', 'flowchart', 'cornell', 'template')
        if canvas_type not in valid_types:
            return json.dumps({'error': f'無效的 canvas_type: {canvas_type}'})
        if audience not in ('human', 'ai', 'shared'):
            return json.dumps({'error': f'無效的 audience: {audience}'}, ensure_ascii=False)

        with session_scope() as s:
            canvas = Canvas(
                name=name,
                description=description,
                canvas_type=canvas_type,
                owner=owner,
                audience=audience,
            )
            s.add(canvas)
            s.flush()
            return json.dumps({
                'id': canvas.id,
                'slug': canvas.slug,
                'name': canvas.name,
                'canvas_type': canvas.canvas_type,
                'audience': canvas.audience,
                'message': f'畫布已建立 (id={canvas.id}, slug={canvas.slug})',
            }, ensure_ascii=False)

    @mcp.tool()
    def canvas_get(canvas_id: int) -> str:
        """取得畫布的完整內容（所有原子位置、連線、群組）。

        用途：了解畫布上有哪些原子及其空間配置。
        """
        with session_scope() as s:
            canvas = s.query(Canvas).filter(Canvas.id == canvas_id).first()
            if not canvas:
                return json.dumps({'error': f'畫布 {canvas_id} 不存在'})

            atoms = (
                s.query(CanvasAtom)
                .options(joinedload(CanvasAtom.atom))
                .filter(CanvasAtom.canvas_id == canvas_id)
                .all()
            )
            connections = (
                s.query(CanvasConnection)
                .filter(CanvasConnection.canvas_id == canvas_id)
                .all()
            )
            groups = (
                s.query(CanvasGroup)
                .filter(CanvasGroup.canvas_id == canvas_id)
                .all()
            )

            return json.dumps({
                'canvas': canvas.to_dict(),
                'atoms': [ca.to_dict() for ca in atoms],
                'connections': [c.to_dict() for c in connections],
                'groups': [g.to_dict() for g in groups],
            }, ensure_ascii=False)

    @mcp.tool()
    def canvas_place_atom(
        canvas_id: int,
        atom_id: int,
        pos_x: float = 0,
        pos_y: float = 0,
        width: float | None = None,
        height: float | None = None,
    ) -> str:
        """將原子放置到畫布的指定位置。

        若原子已在畫布上，會更新其位置與尺寸。
        """
        with session_scope() as s:
            canvas = s.query(Canvas).filter(Canvas.id == canvas_id).first()
            if not canvas:
                return json.dumps({'error': f'畫布 {canvas_id} 不存在'})

            atom = s.query(KnowledgeAtom).filter(
                KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
            ).first()
            if not atom:
                return json.dumps({'error': f'原子 {atom_id} 不存在'})

            existing = s.query(CanvasAtom).filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.atom_id == atom_id,
            ).first()

            if existing:
                existing.pos_x = pos_x
                existing.pos_y = pos_y
                if width is not None:
                    existing.width = width
                if height is not None:
                    existing.height = height
                s.flush()
                return json.dumps({
                    'id': existing.id,
                    'canvas_id': canvas_id,
                    'atom_id': atom_id,
                    'pos_x': pos_x,
                    'pos_y': pos_y,
                    'message': f'原子 {atom_id} 位置已更新',
                }, ensure_ascii=False)

            ca = CanvasAtom(
                canvas_id=canvas_id,
                atom_id=atom_id,
                pos_x=pos_x,
                pos_y=pos_y,
                width=width,
                height=height,
            )
            s.add(ca)
            s.flush()
            return json.dumps({
                'id': ca.id,
                'canvas_id': canvas_id,
                'atom_id': atom_id,
                'pos_x': pos_x,
                'pos_y': pos_y,
                'message': f'原子 {atom_id} 已放置到畫布 {canvas_id}',
            }, ensure_ascii=False)

    @mcp.tool()
    def canvas_remove_atom(
        canvas_id: int,
        atom_id: int,
    ) -> str:
        """從畫布移除原子（不刪除原子本身，只移除畫布上的位置）。"""
        with session_scope() as s:
            ca = s.query(CanvasAtom).filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.atom_id == atom_id,
            ).first()
            if not ca:
                return json.dumps({'error': f'原子 {atom_id} 不在畫布 {canvas_id} 上'})

            s.delete(ca)
            return json.dumps({
                'canvas_id': canvas_id,
                'atom_id': atom_id,
                'message': f'原子 {atom_id} 已從畫布 {canvas_id} 移除',
            }, ensure_ascii=False)
