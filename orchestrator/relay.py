"""
relay.py -- 中間層（主線與支線之間的審查/匯整層）

Pipeline 依序執行各 RelayStage，任一 reject 即停止。

Level 1: BasicQualityStage -- 空 output / 錯誤關鍵字檢查
Level 2: SecretScanStage  -- API key / password / token 正則掃描
未來:
  - Level 3: AI 語意審查（用 claude -p 檢查偏題/幻覺）
  - Level 4: 多支線匯整（同 session 合併報告）
"""
import datetime
import logging
import re

from core.db import session_scope
from core.models import KnowledgeAtom  # noqa: F401 -- FK 依賴
from orchestrator.models import WorkerReport

logger = logging.getLogger('orchestrator.relay')


class RelayStage:
    """中間層處理階段的基底類別"""

    name: str = 'base'

    def process(self, report: WorkerReport, session) -> dict:
        """
        處理一份 worker report。
        回傳 {'action': 'approve'|'reject'|'hold', 'notes': str}
        """
        raise NotImplementedError


# ============================================================
# Level 1: 基本品質檢查
# ============================================================

class BasicQualityStage(RelayStage):
    """檢查 output 是否為空、是否含嚴重錯誤跡象"""

    name = 'basic_quality'

    # 明確的致命錯誤模式（不誤殺正常 debug 討論）
    FATAL_PATTERNS = [
        re.compile(r'^Traceback \(most recent call last\):', re.MULTILINE),
        re.compile(r'^FATAL:', re.MULTILINE | re.IGNORECASE),
        re.compile(r'^panic:', re.MULTILINE),  # Go panic
    ]

    def process(self, report: WorkerReport, session) -> dict:
        content = (report.content or '').strip()

        # 空 output
        if not content:
            return {
                'action': 'reject',
                'notes': '[basic_quality] output 為空',
            }

        # 極短 output（可能 claude 拒答或立即失敗）
        if len(content) < 20 and report.exit_code != 0:
            return {
                'action': 'reject',
                'notes': f'[basic_quality] output 過短 ({len(content)} chars) 且 exit_code={report.exit_code}',
            }

        # 致命錯誤模式
        for pat in self.FATAL_PATTERNS:
            match = pat.search(content)
            if match:
                # 僅在 exit_code != 0 時才 reject（正常討論中可能引用 traceback）
                if report.exit_code != 0:
                    snippet = content[match.start():match.start()+100]
                    return {
                        'action': 'reject',
                        'notes': f'[basic_quality] 偵測到致命錯誤 (exit_code={report.exit_code}): {snippet}...',
                    }

        return {'action': 'approve', 'notes': '[basic_quality] pass'}


# ============================================================
# Level 2: 敏感資訊掃描
# ============================================================

class SecretScanStage(RelayStage):
    """掃描 output 是否洩漏敏感資訊（API key / password / token）"""

    name = 'secret_scan'

    # 高信度模式：明確的 key 格式
    SECRET_PATTERNS = [
        # AWS
        (re.compile(r'AKIA[0-9A-Z]{16}'), 'AWS Access Key'),
        # Generic long hex/base64 secrets (assignment pattern)
        (re.compile(
            r'''(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)'''
            r'''[\s]*[=:]\s*['"]?[A-Za-z0-9+/=_\-]{20,}['"]?''',
            re.IGNORECASE,
        ), 'API Key/Secret assignment'),
        # password= in code (not in URL params or discussion)
        (re.compile(
            r'''password\s*[=:]\s*['"][^'"]{8,}['"]''',
            re.IGNORECASE,
        ), 'Hardcoded password'),
        # GitHub/GitLab tokens
        (re.compile(r'gh[ps]_[A-Za-z0-9_]{36,}'), 'GitHub Token'),
        (re.compile(r'glpat-[A-Za-z0-9\-_]{20,}'), 'GitLab Token'),
    ]

    def process(self, report: WorkerReport, session) -> dict:
        content = report.content or ''

        findings = []
        for pat, label in self.SECRET_PATTERNS:
            matches = pat.findall(content)
            if matches:
                findings.append(f'{label} ({len(matches)} match)')

        if findings:
            return {
                'action': 'hold',
                'notes': f'[secret_scan] 偵測到可能的敏感資訊: {"; ".join(findings)}。需人工確認。',
            }

        return {'action': 'approve', 'notes': '[secret_scan] pass'}


# ============================================================
# Pipeline 組裝
# ============================================================

PIPELINE: list[RelayStage] = [
    BasicQualityStage(),
    SecretScanStage(),
]


def process_report(report_id: int) -> dict:
    """
    將 worker_report 送過中間層 pipeline。

    依序通過 PIPELINE 中各 stage:
      - reject: 立即停止，標記 rejected
      - hold: 立即停止，保持 pending（等人工介入）
      - approve: 繼續下一個 stage
    全部 approve 後標記 approved。
    """
    with session_scope() as s:
        report = s.query(WorkerReport).filter(WorkerReport.id == report_id).first()
        if not report:
            return {'error': f'report #{report_id} 不存在'}

        all_notes = []
        final_action = 'approve'

        for stage in PIPELINE:
            result = stage.process(report, s)
            all_notes.append(result['notes'])

            if result['action'] == 'reject':
                report.review_status = 'rejected'
                report.review_notes = ' | '.join(all_notes)
                report.reviewed_at = datetime.datetime.now()
                report.reviewer_id = 'relay'
                final_action = 'reject'
                logger.info(f'report #{report_id} rejected by {stage.name}: {result["notes"]}')
                break
            elif result['action'] == 'hold':
                # 保持 pending，不改 review_status，等人工介入
                report.review_notes = ' | '.join(all_notes)
                final_action = 'hold'
                logger.info(f'report #{report_id} held by {stage.name}: {result["notes"]}')
                break

        if final_action == 'approve':
            report.review_status = 'approved'
            report.review_notes = ' | '.join(all_notes)
            report.reviewed_at = datetime.datetime.now()
            report.reviewer_id = 'relay'

        return {
            'report_id': report_id,
            'review_status': report.review_status,
            'notes': report.review_notes,
        }
