# -*- coding: utf-8 -*-
"""Knowledge Atoms API + Semantic/Hybrid Search"""
import datetime
import logging

from flask import Blueprint, request, jsonify
from sqlalchemy import func, text
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import KnowledgeAtom, Tag, CanvasAtom, Canvas
from core import relations as rel_service
from core import embeddings as embed_service
from core.tiptap_node_id import backfill_missing_node_ids

bp = Blueprint('atoms', __name__)
logger = logging.getLogger('beak_broodnest')


@bp.route('/api/atoms', methods=['GET'])
def list_atoms():
    """列出知識原子，支援篩選（ILIKE + pg_trgm 相似度排序）"""
    with session_scope() as s:
        keyword = request.args.get('q')
        use_trgm = keyword and len(keyword) > 2

        sim_expr = None
        if use_trgm:
            sim_expr = func.greatest(
                func.similarity(KnowledgeAtom.title, keyword),
                func.similarity(KnowledgeAtom.content_plain, keyword),
            )
            pattern = f'%{keyword}%'
            q = (
                s.query(KnowledgeAtom, sim_expr.label('sim'))
                .filter(KnowledgeAtom.is_deleted == False)
                .filter(
                    KnowledgeAtom.title.ilike(pattern) |
                    KnowledgeAtom.content_plain.ilike(pattern)
                )
            )
        else:
            q = s.query(KnowledgeAtom).filter(KnowledgeAtom.is_deleted == False)

            if keyword:
                pattern = f'%{keyword}%'
                q = q.filter(
                    KnowledgeAtom.title.ilike(pattern) |
                    KnowledgeAtom.content_plain.ilike(pattern)
                )

        # 篩選參數
        atom_type = request.args.get('type')
        if atom_type:
            q = q.filter(KnowledgeAtom.atom_type == atom_type)

        lifecycle = request.args.get('lifecycle')
        if lifecycle:
            q = q.filter(KnowledgeAtom.lifecycle == lifecycle)

        source = request.args.get('source')
        if source:
            q = q.filter(KnowledgeAtom.source == source)

        # 排序
        sort = request.args.get('sort', 'updated_at')
        if use_trgm:
            q = q.order_by(
                sim_expr.desc(),
                KnowledgeAtom.vitality_score.desc(),
            )
        elif sort == 'vitality':
            q = q.order_by(KnowledgeAtom.vitality_score.desc())
        elif sort == 'created_at':
            q = q.order_by(KnowledgeAtom.created_at.desc())
        else:
            q = q.order_by(KnowledgeAtom.updated_at.desc())

        # 分頁
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = min(per_page, 200)
        total = q.count()

        rows = q.offset((page - 1) * per_page).limit(per_page).all()
        atoms = [row[0] for row in rows] if use_trgm else rows

        return jsonify({
            'total': total,
            'page': page,
            'per_page': per_page,
            'items': [a.to_dict(include_tags=True) for a in atoms],
        })


def _extract_thumbnail_url(content_json):
    """從 Tiptap doc 中找出 attrs.thumbnail=true 的 image src。
    深度遞迴整棵 doc tree（table/listItem/blockquote 內的 image 也能命中）。
    多張被標時取第一個（編輯器端應維持單選紀律）。
    """
    if not isinstance(content_json, dict):
        return None

    def walk(node):
        if not isinstance(node, dict):
            return None
        if node.get('type') == 'image':
            attrs = node.get('attrs') or {}
            if attrs.get('thumbnail') and attrs.get('src'):
                return attrs['src']
        for child in node.get('content') or []:
            found = walk(child)
            if found:
                return found
        return None

    return walk(content_json)


@bp.route('/api/atoms', methods=['POST'])
def create_atom():
    """建立知識原子"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    content_json = data.get('content_json')
    # thumbnail_url：呼叫端顯式給定優先；否則從 content_json image attrs.thumbnail 萃取
    if 'thumbnail_url' in data:
        thumbnail_url = data['thumbnail_url']
    else:
        thumbnail_url = _extract_thumbnail_url(content_json)

    with session_scope() as s:
        # 守門：對結構性節點缺 nodeId 自動補（容錯前端遺漏）
        if isinstance(content_json, dict):
            filled, content_json = backfill_missing_node_ids(s, content_json)
            if filled:
                logger.info(f'create_atom: 守門補了 {filled} 個 nodeId')
        atom = KnowledgeAtom(
            title=data.get('title', ''),
            content=data.get('content', ''),
            content_json=content_json,
            content_type=data.get('content_type', 'markdown'),
            thumbnail_url=thumbnail_url,
            atom_type=data.get('atom_type', 'F'),
            schema_id=data.get('schema_id'),
            lifecycle=data.get('lifecycle', 'active'),
            source=data.get('source', 'human'),
            source_detail=data.get('source_detail', ''),
            owner=data.get('owner', 'ethan'),
        )
        s.add(atom)
        s.flush()

        # 處理標籤
        tag_ids = data.get('tag_ids', [])
        if tag_ids:
            tags = s.query(Tag).filter(Tag.id.in_(tag_ids)).all()
            atom.tags = tags

        s.flush()
        result = atom.to_dict(include_tags=True)
        # needs_embedding=True (default)，由背景 embedder 處理

        return jsonify(result), 201


@bp.route('/api/atoms/<int:atom_id>', methods=['GET'])
def get_atom(atom_id):
    """取得單一知識原子"""
    with session_scope() as s:
        atom = (
            s.query(KnowledgeAtom)
            .options(joinedload(KnowledgeAtom.tags))
            .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
            .first()
        )
        if not atom:
            return jsonify({'error': '卡片不存在'}), 404

        # 更新存取紀錄（用原生 SQL 避免觸發 ORM onupdate 改變 updated_at）
        s.execute(
            text('UPDATE knowledge_atoms SET last_accessed_at = :now, access_count = access_count + 1 WHERE id = :id'),
            {'now': datetime.datetime.now(), 'id': atom_id}
        )
        s.expire(atom, ['last_accessed_at', 'access_count'])

        result = atom.to_dict(include_tags=True, include_values=True)

        # 附加關係
        outgoing = rel_service.get_relations_from(s, atom_id)
        incoming = rel_service.get_relations_to(s, atom_id)
        result['relations_from'] = [r.to_dict(include_endpoints=True) for r in outgoing]
        result['relations_to'] = [r.to_dict(include_endpoints=True) for r in incoming]

        # 附加阻塞資訊
        blockers = rel_service.get_blockers(s, atom_id)
        result['is_blocked'] = len(blockers) > 0
        result['blockers'] = [{'id': b.id, 'title': b.title, 'lifecycle': b.lifecycle} for b in blockers]

        return jsonify(result)


@bp.route('/api/atoms/<int:atom_id>', methods=['PUT'])
def update_atom(atom_id):
    """更新知識原子"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False
        ).first()
        if not atom:
            return jsonify({'error': '卡片不存在'}), 404

        # Owner 保護：UI 預設身份 ethan，非本人原子拒絕寫入
        if atom.owner != 'ethan' and not data.get('force_owner_override'):
            return jsonify({
                'error': f'原子屬於 {atom.owner}，無法從 UI 修改。',
                'owner': atom.owner,
                'readonly': True,
            }), 403

        # 守門：對結構性節點缺 nodeId 自動補（容錯前端遺漏）
        if 'content_json' in data and isinstance(data['content_json'], dict):
            filled, data['content_json'] = backfill_missing_node_ids(s, data['content_json'])
            if filled:
                logger.info(f'update_atom({atom_id}): 守門補了 {filled} 個 nodeId')

        for field in ('title', 'content', 'content_json', 'content_type',
                       'atom_type', 'schema_id', 'lifecycle', 'source',
                       'source_detail', 'owner'):
            if field in data:
                setattr(atom, field, data[field])

        # thumbnail_url 同步邏輯：
        #   - 呼叫端顯式給 thumbnail_url（包含 None）→ 直接以該值為準
        #   - 沒給 thumbnail_url 但 content_json 有變更 → 從 content_json 重新萃取
        if 'thumbnail_url' in data:
            atom.thumbnail_url = data['thumbnail_url']
        elif 'content_json' in data:
            atom.thumbnail_url = _extract_thumbnail_url(data['content_json'])

        if 'tag_ids' in data:
            tags = s.query(Tag).filter(Tag.id.in_(data['tag_ids'])).all()
            atom.tags = tags

        # 若 title 或 content 有變更，標記需重新 embed
        if 'title' in data or 'content' in data:
            atom.needs_embedding = True

        s.flush()
        return jsonify(atom.to_dict(include_tags=True))


@bp.route('/api/atoms/<int:atom_id>', methods=['DELETE'])
def delete_atom(atom_id):
    """軟刪除知識原子"""
    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return jsonify({'error': '卡片不存在'}), 404
        atom.is_deleted = True
        # 清理白板上的殘留卡片
        s.query(CanvasAtom).filter(CanvasAtom.atom_id == atom_id).delete()
        return jsonify({'message': f'原子 {atom_id} 已刪除'})


@bp.route('/api/atoms/trash', methods=['GET'])
def list_trash():
    """列出字紙簍（is_deleted=true）的卡片，按 updated_at desc。
    回傳輕量摘要：id / title / content preview / thumbnail_url / updated_at。
    """
    PREVIEW = 200
    with session_scope() as s:
        rows = (
            s.query(
                KnowledgeAtom.id,
                KnowledgeAtom.title,
                func.left(KnowledgeAtom.content, PREVIEW).label('content_preview'),
                KnowledgeAtom.thumbnail_url,
                KnowledgeAtom.atom_type,
                KnowledgeAtom.updated_at,
            )
            .filter(KnowledgeAtom.is_deleted == True)
            .order_by(KnowledgeAtom.updated_at.desc())
            .all()
        )
        return jsonify({
            'total': len(rows),
            'items': [{
                'id': r.id,
                'title': r.title,
                'content': r.content_preview or '',
                'thumbnail_url': r.thumbnail_url,
                'atom_type': r.atom_type,
                'updated_at': r.updated_at.isoformat() if r.updated_at else None,
            } for r in rows],
        })


@bp.route('/api/atoms/<int:atom_id>/restore', methods=['POST'])
def restore_atom(atom_id):
    """從字紙簍救回卡片到指定白板。
    body: {canvas_id, pos_x, pos_y, width?, height?}
    """
    data = request.get_json() or {}
    canvas_id = data.get('canvas_id')
    if not canvas_id:
        return jsonify({'error': '需要 canvas_id'}), 400
    pos_x = float(data.get('pos_x', 100))
    pos_y = float(data.get('pos_y', 100))
    width = data.get('width')
    height = data.get('height')

    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return jsonify({'error': '卡片不存在'}), 404
        if not atom.is_deleted:
            return jsonify({'error': '此卡片不在字紙簍中'}), 400
        canvas = s.query(Canvas).filter(Canvas.id == canvas_id).first()
        if not canvas:
            return jsonify({'error': '白板不存在'}), 404

        atom.is_deleted = False

        ca_kwargs = {
            'canvas_id': canvas_id,
            'atom_id': atom_id,
            'pos_x': pos_x,
            'pos_y': pos_y,
        }
        if width is not None:
            ca_kwargs['width'] = float(width)
        if height is not None:
            ca_kwargs['height'] = float(height)
        ca = CanvasAtom(**ca_kwargs)
        s.add(ca)
        s.flush()

        return jsonify({
            'message': '已救回',
            'canvas_atom': {
                'id': ca.id,
                'canvas_id': ca.canvas_id,
                'atom_id': ca.atom_id,
                'pos_x': ca.pos_x,
                'pos_y': ca.pos_y,
                'width': ca.width,
                'height': ca.height,
                'z_index': ca.z_index,
            },
        })


@bp.route('/api/atoms/<int:atom_id>/hard', methods=['DELETE'])
def hard_delete_atom(atom_id):
    """真 hard delete：直接從 DB 刪除原子，不可逆。
    用 raw SQL 跳過 ORM 的 cascade 處理（ORM 預設會嘗試 SET NULL 反向關聯，
    撞 atom_entries.atom_id 等 NOT NULL 欄位）。讓 DB 的 ON DELETE CASCADE 接手即可。
    用於右鍵「徹底刪除卡片」-- 與 Delete 鍵的「白板私有字紙簍」不同層級。
    """
    with session_scope() as s:
        # 解除 worker_reports 指向（NO ACTION，否則 DELETE 會卡住）
        s.execute(
            text('UPDATE worker_reports SET promoted_atom_id = NULL '
                 'WHERE promoted_atom_id = :aid'),
            {'aid': atom_id},
        )
        result = s.execute(
            text('DELETE FROM knowledge_atoms WHERE id = :aid'),
            {'aid': atom_id},
        )
        if result.rowcount == 0:
            return jsonify({'error': '卡片不存在'}), 404
        logger.info(f'hard_delete_atom: 真刪原子 {atom_id}')
        return jsonify({'message': f'原子 {atom_id} 已徹底刪除'})


@bp.route('/api/atoms/<int:atom_id>/usage', methods=['GET'])
def atom_usage(atom_id):
    """列出此 atom 在哪些白板與交換包被引用，含各白板的視覺連線數。
    用於右鍵「徹底刪除」前的防呆對話框。
    """
    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return jsonify({'error': '卡片不存在'}), 404

        # 此 atom 在哪些白板 (canvas_atoms)
        rows = s.execute(
            text('''
                SELECT ca.id AS canvas_atom_id, ca.canvas_id,
                       c.slug, c.name,
                       (SELECT COUNT(*) FROM canvas_connections cc
                        WHERE cc.canvas_id = c.id
                          AND (cc.source_atom_id = :aid OR cc.target_atom_id = :aid)
                       ) AS connection_count
                FROM canvas_atoms ca
                JOIN canvases c ON c.id = ca.canvas_id
                WHERE ca.atom_id = :aid
                ORDER BY c.name
            '''),
            {'aid': atom_id},
        ).fetchall()
        canvases = [{
            'canvas_atom_id': r.canvas_atom_id,
            'canvas_id': r.canvas_id,
            'slug': r.slug,
            'name': r.name,
            'connection_count': r.connection_count,
        } for r in rows]

        # 此 atom 在哪些交換包
        pack_rows = s.execute(
            text('''
                SELECT epa.id AS pack_atom_id, ep.id AS pack_id, ep.name
                FROM exchange_pack_atoms epa
                JOIN exchange_packs ep ON ep.id = epa.pack_id
                WHERE epa.atom_id = :aid
                ORDER BY ep.created_at DESC
            '''),
            {'aid': atom_id},
        ).fetchall()
        packs = [{
            'pack_atom_id': r.pack_atom_id,
            'pack_id': r.pack_id,
            'name': r.name,
        } for r in pack_rows]

        # 此 atom 在哪些白板字紙簍
        trash_rows = s.execute(
            text('''
                SELECT ct.id AS trash_id, ct.canvas_id, c.slug, c.name
                FROM canvas_trash ct
                JOIN canvases c ON c.id = ct.canvas_id
                WHERE ct.atom_id = :aid
                ORDER BY c.name
            '''),
            {'aid': atom_id},
        ).fetchall()
        trashes = [{
            'trash_id': r.trash_id,
            'canvas_id': r.canvas_id,
            'slug': r.slug,
            'name': r.name,
        } for r in trash_rows]

        return jsonify({
            'atom_id': atom_id,
            'title': atom.title,
            'is_deleted': atom.is_deleted,
            'canvases': canvases,
            'exchange_packs': packs,
            'canvas_trashes': trashes,
        })


@bp.route('/api/atoms/trash/empty', methods=['DELETE'])
def empty_trash():
    """真正刪除所有 is_deleted=true 的原子（不可逆）。
    透過 FK ON DELETE CASCADE 自動清掉 atom_tags / canvas_atoms /
    atom_entries / unified_relations / atom_field_values / atom_embeddings。
    worker_reports.promoted_atom_id 為 NO ACTION，先解除指向避免阻擋。
    """
    with session_scope() as s:
        ids = [r[0] for r in s.query(KnowledgeAtom.id).filter(
            KnowledgeAtom.is_deleted == True
        ).all()]
        if not ids:
            return jsonify({'deleted': 0, 'message': '字紙簍已是空的'})
        # 解除 worker_reports 指向（NO ACTION，否則 DELETE 會卡住）
        s.execute(
            text('UPDATE worker_reports SET promoted_atom_id = NULL '
                 'WHERE promoted_atom_id = ANY(:ids)'),
            {'ids': ids},
        )
        deleted = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.id.in_(ids)
        ).delete(synchronize_session=False)
        logger.info(f'empty_trash: 真刪 {deleted} 個原子')
        return jsonify({'deleted': deleted, 'message': f'已永久刪除 {deleted} 張卡片'})


# ============================================================
# Semantic / Hybrid Search
# ============================================================

@bp.route('/api/search/semantic', methods=['GET'])
def semantic_search():
    """語意搜尋：向量相似度"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': '需要 q 參數'}), 400

    limit = request.args.get('limit', 10, type=int)
    limit = min(limit, 50)
    lifecycle = request.args.get('lifecycle', '')

    with session_scope() as s:
        results = embed_service.search_similar(s, q, limit=limit, lifecycle=lifecycle)
        return jsonify({
            'query': q,
            'total': len(results),
            'items': results,
        })


@bp.route('/api/search/hybrid', methods=['GET'])
def hybrid_search():
    """混合搜尋：向量相似度 + 文字 ILIKE，去重合併"""
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'error': '需要 q 參數'}), 400

    limit = request.args.get('limit', 10, type=int)
    limit = min(limit, 50)

    with session_scope() as s:
        # 向量搜尋
        semantic_results = embed_service.search_similar(s, q, limit=limit)

        # 文字搜尋
        pattern = f'%{q}%'
        text_atoms = (
            s.query(KnowledgeAtom)
            .filter(
                KnowledgeAtom.is_deleted == False,
                KnowledgeAtom.title.ilike(pattern) |
                KnowledgeAtom.content_plain.ilike(pattern)
            )
            .order_by(KnowledgeAtom.vitality_score.desc())
            .limit(limit)
            .all()
        )

        # 合併去重（語意優先）
        seen_ids = set()
        merged = []
        for r in semantic_results:
            if r['id'] not in seen_ids:
                r['match_type'] = 'semantic'
                merged.append(r)
                seen_ids.add(r['id'])

        for a in text_atoms:
            if a.id not in seen_ids:
                merged.append({
                    'id': a.id,
                    'title': a.title,
                    'content': a.content[:200] if a.content else '',
                    'atom_type': a.atom_type,
                    'lifecycle': a.lifecycle,
                    'vitality_score': a.vitality_score,
                    'source': a.source,
                    'similarity': 0,
                    'match_type': 'text',
                })
                seen_ids.add(a.id)

        return jsonify({
            'query': q,
            'total': len(merged),
            'items': merged[:limit],
        })
