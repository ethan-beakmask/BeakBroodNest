# -*- coding: utf-8 -*-
"""Knowledge Atoms API + Semantic/Hybrid Search"""
import datetime
import logging

from flask import Blueprint, request, jsonify
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from core.db import session_scope
from core.models import KnowledgeAtom, Tag, CanvasAtom
from core import relations as rel_service
from core import embeddings as embed_service

bp = Blueprint('atoms', __name__)
logger = logging.getLogger('beak_cortex')


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
                func.similarity(KnowledgeAtom.content, keyword),
            )
            pattern = f'%{keyword}%'
            q = (
                s.query(KnowledgeAtom, sim_expr.label('sim'))
                .filter(KnowledgeAtom.is_deleted == False)
                .filter(
                    KnowledgeAtom.title.ilike(pattern) |
                    KnowledgeAtom.content.ilike(pattern)
                )
            )
        else:
            q = s.query(KnowledgeAtom).filter(KnowledgeAtom.is_deleted == False)

            if keyword:
                pattern = f'%{keyword}%'
                q = q.filter(
                    KnowledgeAtom.title.ilike(pattern) |
                    KnowledgeAtom.content.ilike(pattern)
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


@bp.route('/api/atoms', methods=['POST'])
def create_atom():
    """建立知識原子"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    with session_scope() as s:
        atom = KnowledgeAtom(
            title=data.get('title', ''),
            content=data.get('content', ''),
            content_json=data.get('content_json'),
            content_type=data.get('content_type', 'markdown'),
            atom_type=data.get('atom_type', 'F'),
            schema_id=data.get('schema_id'),
            lifecycle=data.get('lifecycle', 'active'),
            source=data.get('source', 'human'),
            source_detail=data.get('source_detail', ''),
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

        # Auto-embed
        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for atom {atom.id}: {e}')

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
            return jsonify({'error': '原子不存在'}), 404

        # 更新存取紀錄
        atom.last_accessed_at = datetime.datetime.now()
        atom.access_count += 1

        result = atom.to_dict(include_tags=True, include_values=True)

        # 附加關係
        outgoing = rel_service.get_relations_from(s, atom_id)
        incoming = rel_service.get_relations_to(s, atom_id)
        result['relations_from'] = [r.to_dict(include_atoms=True) for r in outgoing]
        result['relations_to'] = [r.to_dict(include_atoms=True) for r in incoming]

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
            return jsonify({'error': '原子不存在'}), 404

        for field in ('title', 'content', 'content_json', 'content_type',
                       'atom_type', 'schema_id', 'lifecycle', 'source',
                       'source_detail'):
            if field in data:
                setattr(atom, field, data[field])

        if 'tag_ids' in data:
            tags = s.query(Tag).filter(Tag.id.in_(data['tag_ids'])).all()
            atom.tags = tags

        s.flush()

        # 若 title 或 content 有變更，重新 embed
        if 'title' in data or 'content' in data:
            try:
                embed_service.embed_atom(s, atom_id)
            except Exception as e:
                logger.warning(f'Auto-embed failed for atom {atom_id}: {e}')

        return jsonify(atom.to_dict(include_tags=True))


@bp.route('/api/atoms/<int:atom_id>', methods=['DELETE'])
def delete_atom(atom_id):
    """軟刪除知識原子"""
    with session_scope() as s:
        atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == atom_id).first()
        if not atom:
            return jsonify({'error': '原子不存在'}), 404
        atom.is_deleted = True
        # 清理白板上的殘留卡片
        s.query(CanvasAtom).filter(CanvasAtom.atom_id == atom_id).delete()
        return jsonify({'message': f'原子 {atom_id} 已刪除'})


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
                KnowledgeAtom.content.ilike(pattern)
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
