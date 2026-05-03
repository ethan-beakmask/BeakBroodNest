#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest Uploaded Files GC -- 上傳檔案孤兒清理排程

掃描 uploaded_files 表，找出沒被任何卡片或結構化 entry 引用的檔案，
若超過 grace period（預設 7 天），實體 unlink 並標記 is_deleted=true。

引用來源：
1. knowledge_atoms.content_json -- Tiptap doc tree 中的 image src（圖片）
2. canvases.snapshot           -- 歸檔白板凍結時保存的 image src
3. entry_field_values          -- file schema 的 file_token 欄位（檔案附件）

設計原則：
- 由 scheduler.py 觸發（schedule.json），不直接寫入 /etc/crontab
- 軟刪除窗口 7 天，避免使用者誤刪 entry 後反悔時 src 變 404
- 已 is_deleted=true 且超過 hard_delete_days（預設 30 天）才從 DB 移除 row
- 死刪除前嚴格遵循「找不到實體檔才允許 DROP DB row」順序

使用範例:
  python uploads_gc.py --run                  執行清理
  python uploads_gc.py --dry-run              試跑，僅顯示將清理的檔案
  python uploads_gc.py --run --grace-days 14  孤兒寬限期 14 天
"""
import argparse
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import (
    UploadedFile, KnowledgeAtom, Canvas,
    EntrySchema, EntrySchemaField, EntryFieldValue, AtomEntry,
)

# ============================================================
# 常數
# ============================================================

HEARTBEAT_DIR = '/opt/tmp/heartbeat'
HEARTBEAT_BASE = 'uploads_gc'
LOG_PATH = '/opt/tmp/scripts-uploads_gc.log'

# /beakbroodnest/files/<token> 的 token 抓取（與 routes/files.py 的 TOKEN_RE 一致）
TOKEN_URL_RE = re.compile(r'/beakbroodnest/files/([A-Za-z0-9_-]{16,64})')

# 預設參數
DEFAULT_GRACE_DAYS = 7        # 孤兒檔案保留天數（軟刪除窗口）
DEFAULT_HARD_DELETE_DAYS = 30 # 軟刪除後多久才從 DB 移除


def _write_heartbeat():
    name = f'{HEARTBEAT_BASE}.ok'
    Path(os.path.join(HEARTBEAT_DIR, name)).write_text(
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


# ============================================================
# 引用掃描
# ============================================================

def _walk_image_tokens(node, out: set):
    """遞迴走訪 Tiptap doc tree，提取所有引用 token：
       - image node 的 src（圖片）
       - pdfThumbnail node 的 token + thumbnailToken（PDF 媒體卡片）
    """
    if not isinstance(node, dict):
        return
    ntype = node.get('type')
    attrs = node.get('attrs') or {}
    if ntype == 'image':
        src = attrs.get('src') or ''
        m = TOKEN_URL_RE.search(src)
        if m:
            out.add(m.group(1))
    elif ntype == 'pdfThumbnail':
        if attrs.get('token'):
            out.add(attrs['token'])
        if attrs.get('thumbnailToken'):
            out.add(attrs['thumbnailToken'])
    # 遞迴子節點
    children = node.get('content')
    if isinstance(children, list):
        for c in children:
            _walk_image_tokens(c, out)


def _scan_atom_image_tokens(session) -> set:
    """掃描所有未刪除原子的 content_json，回傳被引用的 image token 集合。"""
    tokens: set = set()
    rows = session.query(KnowledgeAtom.content_json).filter(
        KnowledgeAtom.is_deleted == False,
        KnowledgeAtom.content_json.isnot(None),
    ).all()
    for (content_json,) in rows:
        if content_json:
            _walk_image_tokens(content_json, tokens)
    return tokens


def _scan_canvas_snapshot_tokens(session) -> set:
    """掃描 canvas.snapshot（歸檔白板凍結內容）內的 image token。"""
    tokens: set = set()
    rows = session.query(Canvas.snapshot).filter(Canvas.snapshot.isnot(None)).all()
    for (snap,) in rows:
        if snap:
            _walk_image_tokens(snap, tokens)
    return tokens


def _scan_file_token_field_values(session) -> set:
    """掃描 file schema 的 file_token 欄位值，回傳所有被引用的 token。

    跳過所屬 atom 已被 hard delete 的 entry（依靠 cascade 已清掉，
    這裡只看 active entry 的引用 -- soft delete 的 atom 仍視為引用，避免提前清理）。
    """
    # 先找 file schema 的 file_token field id
    field = (
        session.query(EntrySchemaField)
        .join(EntrySchema, EntrySchema.id == EntrySchemaField.schema_id)
        .filter(EntrySchema.code == 'file', EntrySchemaField.name == 'file_token')
        .first()
    )
    if not field:
        return set()

    rows = (
        session.query(EntryFieldValue.value)
        .join(AtomEntry, AtomEntry.id == EntryFieldValue.entry_id)
        .join(KnowledgeAtom, KnowledgeAtom.id == AtomEntry.atom_id)
        .filter(
            EntryFieldValue.field_id == field.id,
            EntryFieldValue.value.isnot(None),
            KnowledgeAtom.is_deleted == False,
        )
        .all()
    )
    return {r[0] for r in rows if r[0]}


def collect_referenced_tokens(session) -> set:
    """合併所有引用來源，回傳活躍引用 token 集合。"""
    tokens = set()
    tokens |= _scan_atom_image_tokens(session)
    tokens |= _scan_canvas_snapshot_tokens(session)
    tokens |= _scan_file_token_field_values(session)
    return tokens


# ============================================================
# 核心清理邏輯
# ============================================================

def run_gc(
    grace_days: int = DEFAULT_GRACE_DAYS,
    hard_delete_days: int = DEFAULT_HARD_DELETE_DAYS,
    dry_run: bool = False,
    config_path: str | None = None,
):
    """主流程"""
    logger = logging.getLogger('uploads_gc')

    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    init_engine(config_path)

    now = datetime.now()
    grace_cutoff = now - timedelta(days=grace_days)
    hard_cutoff = now - timedelta(days=hard_delete_days)

    soft_deleted = 0
    hard_deleted = 0
    physical_unlinked = 0
    skipped_protected = 0
    missing_file_count = 0

    with session_scope() as s:
        referenced = collect_referenced_tokens(s)
        logger.info(f'活躍引用 token 數: {len(referenced)}')

        all_files = s.query(UploadedFile).all()
        logger.info(f'uploaded_files 總筆數: {len(all_files)}')

        for rec in all_files:
            ref = rec.token in referenced
            stored = Path(rec.stored_path) if rec.stored_path else None

            # ---- 階段一：軟刪除尚未軟刪 + 未引用 + 超過 grace ----
            if not rec.is_deleted:
                if ref:
                    # 仍被引用，跳過
                    skipped_protected += 1
                    continue
                if rec.uploaded_at and rec.uploaded_at > grace_cutoff:
                    # 還在寬限期，保留
                    continue

                # 標記軟刪除 + 嘗試 unlink 實體檔
                if dry_run:
                    logger.info(
                        f'[DRY-RUN] 軟刪除 #{rec.id} token={rec.token} '
                        f'kind={rec.kind} file={rec.original_filename} '
                        f'uploaded={rec.uploaded_at}'
                    )
                else:
                    rec.is_deleted = True
                    soft_deleted += 1
                    if stored and stored.exists():
                        try:
                            stored.unlink()
                            physical_unlinked += 1
                            # 嘗試清空殘留的桶資料夾（rmdir 失敗代表還有別的檔，OK）
                            try:
                                stored.parent.rmdir()
                            except OSError:
                                pass
                            logger.info(
                                f'軟刪除 + unlink #{rec.id} {rec.original_filename} '
                                f'({rec.token})'
                            )
                        except Exception as e:
                            logger.warning(
                                f'unlink 失敗 #{rec.id} {stored}: {e}'
                            )
                    else:
                        missing_file_count += 1
                        logger.info(
                            f'軟刪除 #{rec.id}（實體檔不存在 {stored}）'
                        )
                continue

            # ---- 階段二：已軟刪 + 超過 hard_delete -> 移除 DB row ----
            if rec.is_deleted and rec.uploaded_at and rec.uploaded_at < hard_cutoff:
                # 確保實體檔已不存在，避免「DB 沒了但檔還在」造成 dangling
                if stored and stored.exists():
                    if dry_run:
                        logger.info(
                            f'[DRY-RUN] 已軟刪但實體檔仍存在 #{rec.id}，先 unlink'
                        )
                    else:
                        try:
                            stored.unlink()
                            physical_unlinked += 1
                        except Exception as e:
                            logger.warning(
                                f'hard delete 前 unlink 失敗 #{rec.id}: {e}'
                            )
                            continue
                if dry_run:
                    logger.info(f'[DRY-RUN] 移除 DB row #{rec.id} ({rec.token})')
                else:
                    s.delete(rec)
                    hard_deleted += 1
                    logger.info(f'hard delete #{rec.id} ({rec.token})')

        if not dry_run:
            s.flush()

    logger.info(
        f'完成: 軟刪除 {soft_deleted} 筆, '
        f'unlink {physical_unlinked} 個檔, '
        f'hard delete {hard_deleted} 筆 row, '
        f'引用中跳過 {skipped_protected} 筆, '
        f'實體已遺失 {missing_file_count} 筆'
    )


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest 上傳檔案孤兒清理排程',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python uploads_gc.py --run                        執行清理
  python uploads_gc.py --dry-run                    試跑模式
  python uploads_gc.py --run --grace-days 14        孤兒寬限期改 14 天
  python uploads_gc.py --run -c /path/config.ini    指定組態檔
        """,
    )
    parser.add_argument('--run', action='store_true', help='執行清理')
    parser.add_argument('--dry-run', action='store_true', help='試跑模式，不實際刪除')
    parser.add_argument('--grace-days', type=int, default=DEFAULT_GRACE_DAYS,
                        help=f'孤兒檔案寬限天數（預設 {DEFAULT_GRACE_DAYS}）')
    parser.add_argument('--hard-delete-days', type=int, default=DEFAULT_HARD_DELETE_DAYS,
                        help=f'軟刪除後多久從 DB 移除 row（預設 {DEFAULT_HARD_DELETE_DAYS}）')
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='組態檔路徑（預設: ../config.ini）')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_PATH, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )

    if not args.run and not args.dry_run:
        parser.print_help()
        sys.exit(1)

    run_gc(
        grace_days=args.grace_days,
        hard_delete_days=args.hard_delete_days,
        dry_run=args.dry_run,
        config_path=args.config,
    )

    if not args.dry_run:
        _write_heartbeat()


if __name__ == '__main__':
    main()
