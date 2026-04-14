# -*- coding: utf-8 -*-
"""Worker KB API -- 支線情報共享"""
import datetime
import logging

from flask import Blueprint, request, jsonify

from core.db import session_scope
from core.models import KnowledgeAtom, Tag, atom_tags
from core import embeddings as embed_service
from orchestrator.models import WorkerTask

bp = Blueprint('worker', __name__)
logger = logging.getLogger('beak_cortex')


def _authenticate_worker(s):
    """驗證支線身份，回傳 (worker_task, error_response)。"""
    worker_id = request.headers.get('X-Worker-Id', '').strip()
    session_id = request.headers.get('X-Session-Id', '').strip()

    if not worker_id or not session_id:
        return None, (jsonify({'error': '缺少 X-Worker-Id 或 X-Session-Id header'}), 401)

    task = (
        s.query(WorkerTask)
        .filter(
            WorkerTask.worker_id == worker_id,
            WorkerTask.session_id == session_id,
            WorkerTask.status.in_(['dispatched', 'running']),
        )
        .first()
    )
    if not task:
        return None, (jsonify({'error': '無效的 worker 憑證或任務已結束'}), 403)

    return task, None


@bp.route('/api/worker/kb/search', methods=['GET'])
def worker_kb_search():
    """支線搜尋知識原子（需 worker 認證）"""
    with session_scope() as s:
        worker_task, err = _authenticate_worker(s)
        if err:
            return err

        keyword = request.args.get('q', '').strip()
        tag_name = request.args.get('tag', '').strip()
        limit = min(request.args.get('limit', 20, type=int), 50)

        q = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.is_deleted == False,
            KnowledgeAtom.lifecycle.in_(['active', 'aging']),
        )

        if keyword:
            pattern = f'%{keyword}%'
            q = q.filter(
                KnowledgeAtom.title.ilike(pattern) |
                KnowledgeAtom.content.ilike(pattern)
            )

        if tag_name:
            tag_subq = (
                s.query(atom_tags.c.atom_id)
                .join(Tag, Tag.id == atom_tags.c.tag_id)
                .filter(Tag.name == tag_name)
            )
            q = q.filter(KnowledgeAtom.id.in_(tag_subq.subquery().select()))

        atoms = (
            q.order_by(KnowledgeAtom.vitality_score.desc(), KnowledgeAtom.updated_at.desc())
            .limit(limit)
            .all()
        )

        return jsonify({
            'total': len(atoms),
            'items': [
                {
                    'id': a.id,
                    'title': a.title,
                    'content': a.content[:500] if a.content else '',
                    'atom_type': a.atom_type,
                    'source': a.source,
                    'updated_at': a.updated_at.isoformat() if a.updated_at else None,
                }
                for a in atoms
            ],
        })


@bp.route('/api/worker/kb/atoms/<int:atom_id>', methods=['GET'])
def worker_kb_get_atom(atom_id):
    """支線讀取單一知識原子（需 worker 認證）"""
    with session_scope() as s:
        worker_task, err = _authenticate_worker(s)
        if err:
            return err

        atom = (
            s.query(KnowledgeAtom)
            .filter(KnowledgeAtom.id == atom_id, KnowledgeAtom.is_deleted == False)
            .first()
        )
        if not atom:
            return jsonify({'error': f'原子 #{atom_id} 不存在'}), 404

        atom.last_accessed_at = datetime.datetime.now()
        atom.access_count += 1

        return jsonify(atom.to_dict(include_tags=True))


@bp.route('/api/worker/kb/atoms', methods=['POST'])
def worker_kb_store_atom():
    """支線寫入知識原子（需 worker 認證）。"""
    data = request.get_json()
    if not data or 'title' not in data:
        return jsonify({'error': '需要 title 欄位'}), 400

    with session_scope() as s:
        worker_task, err = _authenticate_worker(s)
        if err:
            return err

        atom = KnowledgeAtom(
            title=data['title'],
            content=data.get('content', ''),
            content_type=data.get('content_type', 'markdown'),
            atom_type=data.get('atom_type', 'F'),
            lifecycle='active',
            source='derived',
            source_detail=f'worker:{worker_task.worker_id}, task:{worker_task.id}',
        )
        s.add(atom)
        s.flush()

        tag_names = data.get('tags', [])
        if tag_names:
            tag_objects = []
            for tag_name in tag_names:
                tag = s.query(Tag).filter(Tag.name == tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name, tag_type='tag')
                    s.add(tag)
                    s.flush()
                tag_objects.append(tag)
            atom.tags = tag_objects

        s.flush()
        result = atom.to_dict(include_tags=True)

        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for worker atom {atom.id}: {e}')

        return jsonify(result), 201
