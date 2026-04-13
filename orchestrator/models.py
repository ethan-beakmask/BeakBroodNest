"""
Orchestrator ORM -- worker_tasks 與 worker_reports
支線任務管理與結果收集，獨立於知識原子表（knowledge_atoms）
"""
import datetime
import uuid
from sqlalchemy import (
    Integer, String, Text, Float, DateTime,
    ForeignKey, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db import Base


def _short_uuid() -> str:
    return uuid.uuid4().hex[:8]


class WorkerTask(Base):
    """主線派發給支線的任務"""
    __tablename__ = 'worker_tasks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(
        String(36), default=_short_uuid, nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(30), default='sonnet', nullable=False)
    working_dir: Mapped[str] = mapped_column(Text, default='/opt/BeakCortex')

    # pending -> dispatched -> running -> completed/failed/timeout/cancelled
    status: Mapped[str] = mapped_column(String(20), default='pending', nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5)

    # 對話級別識別碼（同一主線對話內所有 dispatch 共用）
    session_id: Mapped[str] = mapped_column(String(100), default='')

    # tmux 座標
    tmux_session: Mapped[str] = mapped_column(String(100), default='')
    tmux_pane: Mapped[str] = mapped_column(String(50), default='')
    main_pane: Mapped[str] = mapped_column(String(100), default='')

    # 時間
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now,
    )
    dispatched_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=600)

    # 關聯
    reports: Mapped[list['WorkerReport']] = relationship(
        back_populates='task', cascade='all, delete-orphan',
    )

    VALID_STATUSES = (
        'pending', 'dispatched', 'running',
        'completed', 'failed', 'timeout', 'cancelled',
    )

    __table_args__ = (
        Index('idx_worker_tasks_status', 'status'),
        Index('idx_worker_tasks_worker_id', 'worker_id'),
        Index('idx_worker_tasks_session', 'session_id'),
    )

    def to_dict(self, brief: bool = False) -> dict:
        d = {
            'id': self.id,
            'worker_id': self.worker_id,
            'title': self.title,
            'model': self.model,
            'status': self.status,
            'priority': self.priority,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'dispatched_at': self.dispatched_at.isoformat() if self.dispatched_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }
        if not brief:
            d['instruction'] = self.instruction
            d['working_dir'] = self.working_dir
            d['tmux_session'] = self.tmux_session
            d['tmux_pane'] = self.tmux_pane
            d['main_pane'] = self.main_pane
            d['timeout_seconds'] = self.timeout_seconds
        return d


class WorkerReport(Base):
    """支線執行結果（未經審查的報告）"""
    __tablename__ = 'worker_reports'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey('worker_tasks.id', ondelete='CASCADE'), nullable=False,
    )
    worker_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model: Mapped[str] = mapped_column(String(30), default='')

    # 對話級別識別碼（從 WorkerTask 繼承）
    session_id: Mapped[str] = mapped_column(String(100), default='')

    # 內容
    content: Mapped[str] = mapped_column(Text, default='')
    content_type: Mapped[str] = mapped_column(String(20), default='text')
    raw_output: Mapped[str] = mapped_column(Text, default='')
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 審查狀態: pending -> approved/rejected -> promoted
    review_status: Mapped[str] = mapped_column(String(20), default='pending')
    promoted_atom_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('knowledge_atoms.id'), nullable=True,
    )
    reviewer_id: Mapped[str] = mapped_column(String(36), default='')
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    review_notes: Mapped[str] = mapped_column(Text, default='')

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.now,
    )

    task: Mapped['WorkerTask'] = relationship(back_populates='reports')

    VALID_REVIEW_STATUSES = ('pending', 'approved', 'rejected', 'promoted')

    __table_args__ = (
        Index('idx_worker_reports_task_id', 'task_id'),
        Index('idx_worker_reports_review_status', 'review_status'),
        Index('idx_worker_reports_session', 'session_id'),
    )

    def to_dict(self, include_raw: bool = False) -> dict:
        d = {
            'id': self.id,
            'task_id': self.task_id,
            'worker_id': self.worker_id,
            'session_id': self.session_id,
            'model': self.model,
            'content': self.content,
            'content_type': self.content_type,
            'exit_code': self.exit_code,
            'review_status': self.review_status,
            'promoted_atom_id': self.promoted_atom_id,
            'reviewer_id': self.reviewer_id,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_raw:
            d['raw_output'] = self.raw_output
        return d
