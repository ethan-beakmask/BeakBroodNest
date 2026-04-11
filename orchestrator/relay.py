"""
relay.py -- 中間層（主線與支線之間的審查/匯整層）

MVP 階段: 純 passthrough，不做任何審查，直接標記為 approved。
未來擴充點:
  - 語意審查: 派另一個 claude process 審查支線結果是否偏離主題
  - 品質評分: 檢查程式碼品質、測試覆蓋率
  - 多支線匯整: 等所有子任務完成後合併成單一報告
  - 安全檢查: 掃描支線產出是否包含敏感資訊
"""
import datetime
import logging

from core.db import session_scope
from core.models import KnowledgeAtom  # noqa: F401 -- FK 依賴
from orchestrator.models import WorkerReport

logger = logging.getLogger('orchestrator.relay')


class RelayStage:
    """中間層處理階段的基底類別（未來擴充用）"""

    def process(self, report: WorkerReport, session) -> dict:
        """
        處理一份 worker report。
        回傳 {'action': 'approve'|'reject'|'hold', 'notes': str}
        """
        raise NotImplementedError


class PassthroughStage(RelayStage):
    """MVP 階段: 直接通過，不做審查"""

    def process(self, report: WorkerReport, session) -> dict:
        return {
            'action': 'approve',
            'notes': 'passthrough (MVP: 未經審查)',
        }


# 中間層 pipeline -- 未來可串接多個 stage
PIPELINE: list[RelayStage] = [
    PassthroughStage(),
]


def process_report(report_id: int) -> dict:
    """
    將 worker_report 送過中間層 pipeline。

    MVP 行為: 直接將 review_status 設為 approved。
    未來: 依序通過 PIPELINE 中各 stage，任一 reject 即停止。
    """
    with session_scope() as s:
        report = s.query(WorkerReport).filter(WorkerReport.id == report_id).first()
        if not report:
            return {'error': f'report #{report_id} 不存在'}

        final_result = {'action': 'approve', 'notes': ''}

        for stage in PIPELINE:
            result = stage.process(report, s)
            if result['action'] == 'reject':
                report.review_status = 'rejected'
                report.review_notes = result['notes']
                report.reviewed_at = datetime.datetime.now()
                report.reviewer_id = 'relay'
                final_result = result
                break
            elif result['action'] == 'hold':
                final_result = result
                break
            else:
                final_result = result

        if final_result['action'] == 'approve':
            report.review_status = 'approved'
            report.review_notes = final_result['notes']
            report.reviewed_at = datetime.datetime.now()
            report.reviewer_id = 'relay'

        return {
            'report_id': report_id,
            'review_status': report.review_status,
            'notes': report.review_notes,
        }
