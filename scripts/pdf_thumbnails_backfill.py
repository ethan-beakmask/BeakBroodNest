#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest 一次性回填：為缺 thumbnailToken 的 PDF 媒體卡片生成第一頁縮圖。

掃描 knowledge_atoms (content_type='media', is_deleted=false) 中
content_json.content[0].type='pdfThumbnail' 但 attrs.thumbnailToken 為空 的原子，
用 pdftoppm 渲染第一頁為 PNG，存入 uploaded_files，更新 atom.content_json。

使用範例:
  python pdf_thumbnails_backfill.py --run            真的跑
  python pdf_thumbnails_backfill.py --dry-run        試跑列表
"""
import argparse
import logging
import os
import secrets
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import KnowledgeAtom, UploadedFile

LOG_PATH = '/opt/tmp/scripts-pdf_thumbnails_backfill.log'
PDFTOPPM = shutil.which('pdftoppm') or '/usr/bin/pdftoppm'


def _uploads_root() -> Path:
    return Path(__file__).resolve().parent.parent / 'data' / 'uploads'


def _store_path_for(token: str) -> Path:
    bucket = token[:2]
    d = _uploads_root() / bucket
    d.mkdir(parents=True, exist_ok=True)
    try: d.chmod(0o700)
    except Exception: pass
    return d / token


def _render_first_page_png(pdf_path: Path, target_png: Path, max_width: int = 480):
    """用 pdftoppm 把 PDF 第一頁輸出為 PNG。"""
    # pdftoppm 需要 stem 作 prefix，輸出檔名 = <stem>-1.png
    stem = target_png.with_suffix('')
    cmd = [
        PDFTOPPM, '-f', '1', '-l', '1',
        '-scale-to', str(max_width),
        '-png',
        str(pdf_path), str(stem),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    # pdftoppm 輸出: <stem>-1.png  或  <stem>-01.png（依頁數位數）
    candidates = sorted(stem.parent.glob(stem.name + '-*.png'))
    if not candidates:
        raise RuntimeError(f'pdftoppm 無輸出: {cmd}')
    candidates[0].rename(target_png)
    # 清掉其他可能的衍生檔
    for c in candidates[1:]:
        try: c.unlink()
        except Exception: pass


def run_backfill(dry_run: bool = False, config_path: str | None = None):
    logger = logging.getLogger('pdf_thumbs_backfill')
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    init_engine(config_path)

    targets = []
    with session_scope() as s:
        rows = s.query(KnowledgeAtom).filter(
            KnowledgeAtom.is_deleted == False,
            KnowledgeAtom.content_type == 'media',
            KnowledgeAtom.content_json.isnot(None),
        ).all()
        for atom in rows:
            cj = atom.content_json or {}
            content = cj.get('content') or []
            if not content: continue
            first = content[0]
            if not isinstance(first, dict): continue
            if first.get('type') != 'pdfThumbnail': continue
            attrs = first.get('attrs') or {}
            if attrs.get('thumbnailToken'): continue
            pdf_token = attrs.get('token')
            if not pdf_token: continue
            # 找實體 PDF 檔
            pdf_rec = s.query(UploadedFile).filter(
                UploadedFile.token == pdf_token,
                UploadedFile.is_deleted == False,
            ).first()
            if not pdf_rec or not Path(pdf_rec.stored_path).exists():
                logger.warning(f'#{atom.id} PDF 實體檔不存在 token={pdf_token}，跳過')
                continue
            targets.append({
                'atom_id': atom.id,
                'title': atom.title,
                'pdf_token': pdf_token,
                'pdf_path': pdf_rec.stored_path,
                'orig_filename': pdf_rec.original_filename,
            })

    logger.info(f'待處理 PDF 數: {len(targets)}')
    if not targets:
        return

    success = 0
    failed = 0
    for t in targets:
        if dry_run:
            logger.info(f'[DRY-RUN] 會處理 #{t["atom_id"]} {t["title"]}')
            continue

        # 產 token + 路徑
        thumb_token = secrets.token_urlsafe(24)
        target = _store_path_for(thumb_token)
        try:
            _render_first_page_png(Path(t['pdf_path']), target, max_width=480)
            target.chmod(0o600)
        except Exception as e:
            logger.error(f'#{t["atom_id"]} pdftoppm 失敗: {e}')
            failed += 1
            continue

        size = target.stat().st_size
        thumb_filename = (t['orig_filename'].rsplit('.', 1)[0] + '.thumb.png')

        # 寫 DB
        try:
            with session_scope() as s:
                rec = UploadedFile(
                    token=thumb_token,
                    original_filename=thumb_filename,
                    stored_path=str(target),
                    mime_type='image/png',
                    size_bytes=size,
                    kind='image',
                    uploaded_by='system:backfill',
                )
                s.add(rec)
                s.flush()

                # 更新 atom.content_json
                atom = s.query(KnowledgeAtom).filter(KnowledgeAtom.id == t['atom_id']).first()
                if atom and atom.content_json:
                    cj = dict(atom.content_json)
                    content = list(cj.get('content') or [])
                    if content and isinstance(content[0], dict) and content[0].get('type') == 'pdfThumbnail':
                        attrs = dict(content[0].get('attrs') or {})
                        attrs['thumbnailToken'] = thumb_token
                        content[0] = dict(content[0], attrs=attrs)
                        cj['content'] = content
                        atom.content_json = cj
            success += 1
            logger.info(f'#{t["atom_id"]} 完成 ({thumb_token})')
        except Exception as e:
            logger.error(f'#{t["atom_id"]} DB 寫入失敗: {e}')
            failed += 1
            try: target.unlink()
            except Exception: pass

    logger.info(f'完成: 成功 {success}, 失敗 {failed}, 待處理 {len(targets)}')


def main():
    parser = argparse.ArgumentParser(
        description='PDF 縮圖回填（一次性，補老 PDF 缺的 thumbnailToken）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python pdf_thumbnails_backfill.py --run        執行回填
  python pdf_thumbnails_backfill.py --dry-run    試跑列出待處理
        """,
    )
    parser.add_argument('--run', action='store_true', help='執行')
    parser.add_argument('--dry-run', action='store_true', help='試跑')
    parser.add_argument('--config', '-c', default=None, help='組態檔')

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

    run_backfill(dry_run=args.dry_run, config_path=args.config)


if __name__ == '__main__':
    main()
