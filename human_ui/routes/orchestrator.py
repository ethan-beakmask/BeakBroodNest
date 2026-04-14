# -*- coding: utf-8 -*-
"""Orchestrator Dashboard API: stats, tasks, reports review & promote"""
import datetime
import logging

from flask import Blueprint, request, jsonify
from sqlalchemy import func

from core.db import session_scope
from core.models import KnowledgeAtom, Tag
from core import embeddings as embed_service
from orchestrator.models import WorkerTask, WorkerReport

bp = Blueprint('orchestrator', __name__)
logger = logging.getLogger('beak_cortex')


@bp.route('/api/orchestrator/stats', methods=['GET'])
def orchestrator_stats():
    """Orchestrator 統計摘要"""
    with session_scope() as s:
        tasks = s.query(WorkerTask).all()

        by_status = {}
        sessions = set()
        for t in tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            if t.session_id:
                sessions.add(t.session_id)

        active_sessions = set()
        terminal = ('completed', 'failed', 'timeout', 'cancelled')
        for t in tasks:
            if t.session_id and t.status not in terminal:
                active_sessions.add(t.session_id)

        return jsonify({
            'total': len(tasks),
            'by_status': by_status,
            'session_count': len(sessions),
            'active_session_count': len(active_sessions),
        })


@bp.route('/api/orchestrator/tasks', methods=['GET'])
def orchestrator_tasks():
    """列出 Orchestrator 任務"""
    with session_scope() as s:
        q = s.query(WorkerTask)

        status = request.args.get('status')
        if status:
            q = q.filter(WorkerTask.status == status)

        session_id = request.args.get('session_id')
        if session_id:
            q = q.filter(WorkerTask.session_id == session_id)

        q = q.order_by(WorkerTask.created_at.desc())

        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)
        per_page = min(per_page, 200)
        total = q.count()

        tasks = q.offset((page - 1) * per_page).limit(per_page).all()

        task_ids = [t.id for t in tasks]
        report_counts = {}
        if task_ids:
            rows = (
                s.query(WorkerReport.task_id, func.count(WorkerReport.id))
                .filter(WorkerReport.task_id.in_(task_ids))
                .group_by(WorkerReport.task_id)
                .all()
            )
            report_counts = dict(rows)

        items = []
        for t in tasks:
            d = t.to_dict()
            d['report_count'] = report_counts.get(t.id, 0)
            items.append(d)

        return jsonify({
            'total': total,
            'page': page,
            'per_page': per_page,
            'items': items,
        })


@bp.route('/api/orchestrator/tasks/<int:task_id>', methods=['GET'])
def orchestrator_task_detail(task_id):
    """單一任務詳情含 reports"""
    with session_scope() as s:
        task = s.query(WorkerTask).filter(WorkerTask.id == task_id).first()
        if not task:
            return jsonify({'error': '任務不存在'}), 404

        result = task.to_dict()
        result['reports'] = [r.to_dict() for r in task.reports]
        return jsonify(result)


@bp.route('/api/orchestrator/reports/<int:report_id>/review', methods=['PUT'])
def review_report(report_id):
    """審查支線報告：approve 或 reject"""
    data = request.get_json()
    if not data or 'action' not in data:
        return jsonify({'error': '需要 action 欄位 (approve/reject)'}), 400

    action = data['action']
    if action not in ('approve', 'reject'):
        return jsonify({'error': f'無效的 action: {action}，允許值: approve, reject'}), 400

    with session_scope() as s:
        report = s.query(WorkerReport).filter(WorkerReport.id == report_id).first()
        if not report:
            return jsonify({'error': f'報告 #{report_id} 不存在'}), 404

        if report.review_status not in ('pending',):
            return jsonify({
                'error': f'報告 #{report_id} 目前狀態為 {report.review_status}，僅 pending 可審查',
            }), 409

        if action == 'approve':
            report.review_status = 'approved'
        else:
            report.review_status = 'rejected'

        report.reviewer_id = data.get('reviewer_id', 'human')
        report.reviewed_at = datetime.datetime.now()
        report.review_notes = data.get('notes', '')

        return jsonify(report.to_dict())


@bp.route('/api/orchestrator/reports/<int:report_id>/promote', methods=['POST'])
def promote_report(report_id):
    """將報告提升為正式知識原子"""
    data = request.get_json() or {}

    with session_scope() as s:
        report = (
            s.query(WorkerReport)
            .filter(WorkerReport.id == report_id)
            .first()
        )
        if not report:
            return jsonify({'error': f'報告 #{report_id} 不存在'}), 404

        if report.review_status == 'promoted':
            return jsonify({
                'error': f'報告 #{report_id} 已被提升為原子 #{report.promoted_atom_id}',
            }), 409

        if report.review_status not in ('pending', 'approved'):
            return jsonify({
                'error': f'報告 #{report_id} 狀態為 {report.review_status}，僅 pending/approved 可提升',
            }), 409

        task = s.query(WorkerTask).filter(WorkerTask.id == report.task_id).first()

        atom = KnowledgeAtom(
            title=data.get('title') or (task.title if task else f'Report #{report_id}'),
            content=data.get('content') or report.content,
            content_type=report.content_type or 'markdown',
            atom_type=data.get('atom_type', 'D'),
            lifecycle='active',
            source='derived',
            source_detail=f'promoted from report #{report_id}, task #{report.task_id}',
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

        report.review_status = 'promoted'
        report.promoted_atom_id = atom.id
        report.reviewer_id = data.get('reviewer_id', 'human')
        report.reviewed_at = datetime.datetime.now()

        s.flush()

        result = report.to_dict()
        result['promoted_atom'] = atom.to_dict(include_tags=True)

        try:
            embed_service.embed_atom(s, atom.id)
        except Exception as e:
            logger.warning(f'Auto-embed failed for promoted atom {atom.id}: {e}')

        return jsonify(result), 201
