# -*- coding: utf-8 -*-
"""檔案上傳 / 下載 API。

設計重點：
- token 為公開隨機識別碼（secrets.token_urlsafe），但 GET endpoint 仍受 _check_auth 保護
- 磁碟上的檔名 = token，原檔名只記在 DB
- 圖片 inline 顯示供 Tiptap Image node；一般檔案 attachment 強制下載
"""
import logging
import mimetypes
import re
import secrets
from pathlib import Path

from flask import Blueprint, request, jsonify, send_file, abort, session

from core.db import session_scope
from core.models import UploadedFile

bp = Blueprint('files', __name__)
logger = logging.getLogger('beak_cortex')

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{16,64}$')

ALLOWED_IMAGE_MIMES = {
    'image/jpeg', 'image/png', 'image/webp', 'image/gif',
    'image/svg+xml', 'image/bmp', 'image/x-icon',
}

# 黑名單：避免存入可在伺服器或瀏覽器引發風險的檔案類型
DENY_EXT = {'.html', '.htm', '.xhtml', '.svg', '.js', '.mjs', '.php',
            '.phtml', '.exe', '.dll', '.bat', '.cmd', '.sh', '.ps1',
            '.cgi', '.jsp', '.asp', '.aspx'}


def _uploads_root() -> Path:
    """專案根目錄下 data/uploads，dev 與 runtime 各自獨立。"""
    root = Path(__file__).resolve().parent.parent.parent / 'data' / 'uploads'
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except Exception:
        pass
    return root


def _store_path_for(token: str) -> Path:
    """token 前兩字元做分桶，避免單一目錄塞太多檔。"""
    bucket = token[:2]
    d = _uploads_root() / bucket
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except Exception:
        pass
    return d / token


def _safe_filename(name: str) -> str:
    """只保留可顯示字元，限制長度，禁止路徑分隔符。"""
    name = (name or 'unnamed').strip().replace('\x00', '')
    name = name.replace('/', '_').replace('\\', '_')
    if len(name) > 255:
        name = name[:255]
    return name or 'unnamed'


@bp.route('/api/files/upload', methods=['POST'])
def upload_file():
    """multipart/form-data: file=<binary>, kind=image|file (optional, 由 mime 自動推斷)"""
    if 'file' not in request.files:
        return jsonify({'error': '需要 file 欄位'}), 400

    f = request.files['file']
    if not f or not f.filename:
        return jsonify({'error': '空白檔案'}), 400

    # 大小檢查 -- werkzeug 會將整個 body 讀入記憶體後才呼叫，靠 stream 推估
    f.stream.seek(0, 2)
    size = f.stream.tell()
    f.stream.seek(0)
    if size <= 0:
        return jsonify({'error': '檔案內容為空'}), 400
    if size > MAX_UPLOAD_BYTES:
        return jsonify({
            'error': f'超過上限 {MAX_UPLOAD_BYTES // (1024*1024)} MB'
        }), 413

    orig = _safe_filename(f.filename)
    ext = Path(orig).suffix.lower()

    # 推算 mime
    mime = (f.mimetype or '').lower()
    if not mime or mime == 'application/octet-stream':
        guess, _ = mimetypes.guess_type(orig)
        if guess:
            mime = guess

    # kind 判斷：客戶端可指定，否則由 mime 推
    kind = (request.form.get('kind') or '').strip().lower()
    if kind not in ('image', 'file'):
        kind = 'image' if mime.startswith('image/') else 'file'

    # 安全檢查
    if kind == 'image':
        if mime and mime not in ALLOWED_IMAGE_MIMES:
            return jsonify({'error': f'不支援的圖片類型: {mime}'}), 415
    else:
        if ext in DENY_EXT:
            return jsonify({'error': f'禁止上傳 {ext} 類型'}), 415

    # 產生 token + 寫入磁碟
    token = secrets.token_urlsafe(24)
    target = _store_path_for(token)
    try:
        f.save(str(target))
        target.chmod(0o600)
    except Exception as e:
        logger.exception('上傳寫入失敗')
        return jsonify({'error': f'寫入失敗: {e}'}), 500

    uploader = session.get('username') or 'ethan'

    with session_scope() as s:
        rec = UploadedFile(
            token=token,
            original_filename=orig,
            stored_path=str(target),
            mime_type=mime or 'application/octet-stream',
            size_bytes=size,
            kind=kind,
            uploaded_by=uploader,
        )
        s.add(rec)
        s.flush()
        result = rec.to_dict()
        # 加上方便前端直接使用的 URL
        result['url'] = f'/beakcortex/files/{token}'

    return jsonify(result), 201


@bp.route('/files/<token>', methods=['GET'])
def download_file(token):
    """提供 inline / attachment 檔案下載。

    - 已透過 app.before_request 強制登入；未登入會被導去 /beakcortex/login
    - token 必須符合白名單字元，避免路徑遍歷
    """
    if not TOKEN_RE.match(token or ''):
        abort(404)

    with session_scope() as s:
        rec = s.query(UploadedFile).filter(
            UploadedFile.token == token,
            UploadedFile.is_deleted == False,
        ).first()
        if not rec:
            abort(404)

        path = Path(rec.stored_path)
        if not path.exists():
            logger.warning(f'uploaded_file token={token} 但磁碟檔案不存在')
            abort(404)

        as_attachment = (rec.kind != 'image')
        resp = send_file(
            str(path),
            mimetype=rec.mime_type or 'application/octet-stream',
            as_attachment=as_attachment,
            download_name=rec.original_filename,
            conditional=True,
        )
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        # token 名 = 內容 hash 等價，內容不可變，可以放心長快取
        resp.headers['Cache-Control'] = 'private, max-age=2592000, immutable'
        resp.headers['Referrer-Policy'] = 'no-referrer'
        return resp


@bp.route('/api/files/<token>', methods=['GET'])
def get_file_meta(token):
    """取得檔案 metadata（不回傳檔案內容）"""
    if not TOKEN_RE.match(token or ''):
        return jsonify({'error': 'token 格式錯誤'}), 400
    with session_scope() as s:
        rec = s.query(UploadedFile).filter(
            UploadedFile.token == token,
            UploadedFile.is_deleted == False,
        ).first()
        if not rec:
            return jsonify({'error': '找不到檔案'}), 404
        d = rec.to_dict()
        d['url'] = f'/beakcortex/files/{rec.token}'
        return jsonify(d)
