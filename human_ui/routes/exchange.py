# -*- coding: utf-8 -*-
"""Exchange Packs API: 交換卡片功能（寄存/取出）"""

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from core.db import session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, CanvasGroup,
    ExchangePack, ExchangePackAtom,
    canvas_group_members, atom_tags, Tag,
)

bp = Blueprint('exchange', __name__)


# ============================================================
# 共用：包列表序列化（含 atom_count + source_canvas_name）
# ============================================================

def _pack_with_meta(s, pack: ExchangePack) -> dict:
    cnt = s.query(func.count(ExchangePackAtom.id)).filter(
        ExchangePackAtom.pack_id == pack.id
    ).scalar() or 0
    src_name = None
    if pack.source_canvas_id:
        c = s.get(Canvas, pack.source_canvas_id)
        src_name = c.name if c else None
    return pack.to_dict(include_source_name=src_name, atom_count=cnt)


def _build_atom_brief(s, atom: KnowledgeAtom) -> dict:
    """取出包內卡片預覽用的精簡資料（避免 atom.to_dict() 過大）"""
    return {
        'id': atom.id,
        'title': atom.title,
        'atom_type': atom.atom_type,
        'lifecycle': atom.lifecycle,
        'thumbnail_url': atom.thumbnail_url,
        'content_type': atom.content_type,
        'content_preview': (atom.content or '')[:200],
        'is_deleted': atom.is_deleted,
    }


# ============================================================
# GET /api/exchange-packs - 列所有包
# ============================================================

@bp.route('/api/exchange-packs', methods=['GET'])
def list_exchange_packs():
    """列出所有交換包，依 created_at desc 排序，含卡片數與來源白板名稱"""
    with session_scope() as s:
        packs = s.query(ExchangePack).order_by(ExchangePack.created_at.desc()).all()
        items = [_pack_with_meta(s, p) for p in packs]
        return jsonify({'items': items})


# ============================================================
# POST /api/exchange-packs - 建立交換包（寄存）
# body: {name, source_canvas_id, mode: 'copy'|'move', atom_ids: [int]}
# mode='move' 時同步從 source_canvas 解除 canvas_atoms 連結
# ============================================================

@bp.route('/api/exchange-packs', methods=['POST'])
def create_exchange_pack():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': '需要 name'}), 400
    if len(name) > 300:
        return jsonify({'error': 'name 過長（最大 300）'}), 400
    atom_ids = data.get('atom_ids') or []
    if not isinstance(atom_ids, list) or not atom_ids:
        return jsonify({'error': '需要 atom_ids（非空陣列）'}), 400
    mode = data.get('mode', 'copy')
    if mode not in ('copy', 'move'):
        return jsonify({'error': "mode 必須是 'copy' 或 'move'"}), 400
    source_canvas_id = data.get('source_canvas_id')

    with session_scope() as s:
        # 驗證 source canvas 存在（若有提供）
        if source_canvas_id is not None:
            sc = s.get(Canvas, source_canvas_id)
            if not sc:
                return jsonify({'error': '來源白板不存在'}), 404
            if mode == 'move':
                # 取得來源白板上對應的 canvas_atoms 以保留原座標到 pack
                src_cas = s.query(CanvasAtom).filter(
                    CanvasAtom.canvas_id == source_canvas_id,
                    CanvasAtom.atom_id.in_(atom_ids),
                ).all()
                src_pos_map = {ca.atom_id: ca for ca in src_cas}
            else:
                src_cas = s.query(CanvasAtom).filter(
                    CanvasAtom.canvas_id == source_canvas_id,
                    CanvasAtom.atom_id.in_(atom_ids),
                ).all()
                src_pos_map = {ca.atom_id: ca for ca in src_cas}
        else:
            src_pos_map = {}
            src_cas = []

        # 確認 atoms 存在且未軟刪
        valid_rows = s.query(KnowledgeAtom.id).filter(
            KnowledgeAtom.id.in_(atom_ids),
            KnowledgeAtom.is_deleted == False,
        ).all()
        valid_set = {r[0] for r in valid_rows}
        if not valid_set:
            return jsonify({'error': '無有效的 atom（已刪除或不存在）'}), 400

        # 建包
        pack = ExchangePack(
            name=name,
            source_canvas_id=source_canvas_id,
        )
        s.add(pack)
        s.flush()

        # 寫入 pack_atoms（保留原座標供未來參考）
        for idx, aid in enumerate(atom_ids):
            if aid not in valid_set:
                continue
            ca = src_pos_map.get(aid)
            ppa = ExchangePackAtom(
                pack_id=pack.id,
                atom_id=aid,
                sort_order=idx,
                original_pos_x=ca.pos_x if ca else None,
                original_pos_y=ca.pos_y if ca else None,
                original_width=ca.width if ca else None,
                original_height=ca.height if ca else None,
            )
            s.add(ppa)

        # mode=move：解除來源白板的 canvas_atoms 連結
        if mode == 'move' and source_canvas_id is not None:
            for ca in src_cas:
                if ca.atom_id in valid_set:
                    s.delete(ca)

        s.flush()
        return jsonify(_pack_with_meta(s, pack)), 201


# ============================================================
# GET /api/exchange-packs/<pack_id> - 包詳情（含卡片列表）
# ============================================================

@bp.route('/api/exchange-packs/<int:pack_id>', methods=['GET'])
def get_exchange_pack(pack_id):
    with session_scope() as s:
        pack = s.get(ExchangePack, pack_id)
        if not pack:
            return jsonify({'error': '交換包不存在'}), 404

        rows = (
            s.query(ExchangePackAtom, KnowledgeAtom)
            .join(KnowledgeAtom, KnowledgeAtom.id == ExchangePackAtom.atom_id)
            .filter(ExchangePackAtom.pack_id == pack_id)
            .order_by(ExchangePackAtom.sort_order, ExchangePackAtom.id)
            .all()
        )

        atom_ids = [a.id for _, a in rows]
        # 批次標籤
        tags_map = {}
        if atom_ids:
            tag_rows = (
                s.query(atom_tags.c.atom_id, Tag.id, Tag.name, Tag.color)
                .join(Tag, Tag.id == atom_tags.c.tag_id)
                .filter(atom_tags.c.atom_id.in_(atom_ids))
                .all()
            )
            for aid, tid, tname, tcolor in tag_rows:
                tags_map.setdefault(aid, []).append(
                    {'id': tid, 'name': tname, 'color': tcolor}
                )

        items = []
        for ppa, ka in rows:
            d = _build_atom_brief(s, ka)
            d['tags'] = tags_map.get(ka.id, [])
            d['original_pos_x'] = ppa.original_pos_x
            d['original_pos_y'] = ppa.original_pos_y
            d['original_width'] = ppa.original_width
            d['original_height'] = ppa.original_height
            d['pack_atom_id'] = ppa.id
            items.append(d)

        meta = _pack_with_meta(s, pack)
        meta['items'] = items
        return jsonify(meta)


# ============================================================
# POST /api/exchange-packs/<pack_id>/take - 取出到目標白板
# body: {
#   canvas_id: int,
#   items: [{atom_id, pos_x, pos_y, width?, height?}],
#   group_name?: str,            # 若提供 -> 建紅色群組包含這幾張
#   group_color?: str,           # 預設 #dc2626
#   group_pos: {x, y, w, h}?,    # 群組外框，未提供則由後端依 items 範圍計算
# }
# 永久寄存：取出後 pack 與 pack_atoms 不變
# ============================================================

@bp.route('/api/exchange-packs/<int:pack_id>/take', methods=['POST'])
def take_from_exchange_pack(pack_id):
    data = request.get_json() or {}
    canvas_id = data.get('canvas_id')
    items = data.get('items') or []
    if not canvas_id:
        return jsonify({'error': '需要 canvas_id'}), 400
    if not isinstance(items, list) or not items:
        return jsonify({'error': '需要 items（非空陣列）'}), 400

    with session_scope() as s:
        pack = s.get(ExchangePack, pack_id)
        if not pack:
            return jsonify({'error': '交換包不存在'}), 404
        canvas = s.get(Canvas, canvas_id)
        if not canvas:
            return jsonify({'error': '目標白板不存在'}), 404

        # 確認所有 atom_id 都在這個 pack 內
        pack_atom_ids = {
            r[0] for r in s.query(ExchangePackAtom.atom_id).filter(
                ExchangePackAtom.pack_id == pack_id
            ).all()
        }
        target_atom_ids = [it.get('atom_id') for it in items]
        invalid = [aid for aid in target_atom_ids if aid not in pack_atom_ids]
        if invalid:
            return jsonify({'error': f'atom_ids 不在此包內: {invalid}'}), 400

        # 自動復原 is_deleted=true 的 atom（兼容歷史殘留）
        # 用戶按「取用」即表達「我要這張卡」，符合動作單純原則
        restored_count = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id.in_(target_atom_ids),
            KnowledgeAtom.is_deleted == True,
        ).update({'is_deleted': False}, synchronize_session=False)
        if restored_count:
            s.flush()

        # 建 / 更新 canvas_atoms
        created_cas = []
        for it in items:
            aid = it.get('atom_id')
            existing = s.query(CanvasAtom).filter(
                CanvasAtom.canvas_id == canvas_id,
                CanvasAtom.atom_id == aid,
            ).first()
            if existing:
                # 已在該白板，更新位置即可
                if 'pos_x' in it:
                    existing.pos_x = it['pos_x']
                if 'pos_y' in it:
                    existing.pos_y = it['pos_y']
                if 'width' in it and it['width'] is not None:
                    existing.width = it['width']
                if 'height' in it and it['height'] is not None:
                    existing.height = it['height']
                created_cas.append(existing)
            else:
                ca = CanvasAtom(
                    canvas_id=canvas_id,
                    atom_id=aid,
                    pos_x=it.get('pos_x', 100),
                    pos_y=it.get('pos_y', 100),
                    width=it.get('width'),
                    height=it.get('height'),
                    z_index=it.get('z_index', 0),
                    visual_style=it.get('visual_style', '{}'),
                )
                s.add(ca)
                created_cas.append(ca)
        s.flush()

        # 多選 (>= 2) 自動建群組
        group_dict = None
        group_name = (data.get('group_name') or '').strip()
        if group_name and len(created_cas) >= 2:
            color = data.get('group_color') or '#dc2626'
            gp = data.get('group_pos') or {}
            # 若未提供 group_pos，依新放置範圍計算（外框 padding 20，標題列 24）
            if not gp:
                pad = 20
                label_h = 24
                xs = [ca.pos_x for ca in created_cas]
                ys = [ca.pos_y for ca in created_cas]
                ws = [(ca.width or 260) for ca in created_cas]
                hs = [(ca.height or 120) for ca in created_cas]
                min_x = min(xs)
                min_y = min(ys)
                max_x = max(x + w for x, w in zip(xs, ws))
                max_y = max(y + h for y, h in zip(ys, hs))
                gp = {
                    'x': min_x - pad,
                    'y': min_y - pad - label_h,
                    'w': (max_x - min_x) + pad * 2,
                    'h': (max_y - min_y) + pad * 2 + label_h,
                }

            g = CanvasGroup(
                canvas_id=canvas_id,
                name=group_name,
                color=color,
                pos_x=gp.get('x', 0),
                pos_y=gp.get('y', 0),
                width=gp.get('w', 300),
                height=gp.get('h', 200),
                z_index=1,
                border_style='solid',
            )
            s.add(g)
            s.flush()
            for ca in created_cas:
                s.execute(
                    canvas_group_members.insert().values(
                        canvas_atom_id=ca.id, group_id=g.id
                    )
                )
            s.flush()
            # 重查含 atom_ids 的字典
            member_rows = (
                s.query(CanvasAtom.atom_id)
                .join(canvas_group_members, canvas_group_members.c.canvas_atom_id == CanvasAtom.id)
                .filter(canvas_group_members.c.group_id == g.id)
                .all()
            )
            group_dict = {
                'id': g.id, 'canvas_id': g.canvas_id,
                'name': g.name, 'color': g.color,
                'pos_x': g.pos_x, 'pos_y': g.pos_y,
                'width': g.width, 'height': g.height,
                'z_index': g.z_index, 'border_style': g.border_style,
                'atom_ids': [r[0] for r in member_rows],
            }

        return jsonify({
            'created_canvas_atoms': [ca.to_dict() for ca in created_cas],
            'group': group_dict,
        }), 201


# ============================================================
# DELETE /api/exchange-packs/<pack_id>/atoms - 刪包內幾張
# body: {atom_ids: [int]}
# ============================================================

@bp.route('/api/exchange-packs/<int:pack_id>/atoms', methods=['DELETE'])
def remove_atoms_from_pack(pack_id):
    data = request.get_json() or {}
    atom_ids = data.get('atom_ids') or []
    if not isinstance(atom_ids, list) or not atom_ids:
        return jsonify({'error': '需要 atom_ids（非空陣列）'}), 400

    with session_scope() as s:
        pack = s.get(ExchangePack, pack_id)
        if not pack:
            return jsonify({'error': '交換包不存在'}), 404
        deleted = s.query(ExchangePackAtom).filter(
            ExchangePackAtom.pack_id == pack_id,
            ExchangePackAtom.atom_id.in_(atom_ids),
        ).delete(synchronize_session=False)
        s.flush()
        return jsonify({'message': f'已從交換包移除 {deleted} 張', 'deleted': deleted})


# ============================================================
# DELETE /api/exchange-packs/<pack_id> - 整包刪
# ============================================================

@bp.route('/api/exchange-packs/<int:pack_id>', methods=['DELETE'])
def delete_exchange_pack(pack_id):
    with session_scope() as s:
        pack = s.get(ExchangePack, pack_id)
        if not pack:
            return jsonify({'error': '交換包不存在'}), 404
        s.delete(pack)
        return jsonify({'message': '交換包已刪除'})
