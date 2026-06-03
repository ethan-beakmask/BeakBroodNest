#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakBroodNest -- 人類介面 Flask 入口
路由已拆分至 routes/ 子模組
"""
import argparse
import base64
import functools
import json
import secrets
import string
import sys
import configparser
import logging
from datetime import timedelta
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, render_template, redirect, request, abort, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

from core.db import init_engine, get_engine, get_session, session_scope, create_all_tables, Base
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, Tag,
    SystemConfig, _gen_canvas_slug,
    EntrySchema, EntrySchemaField,
)
from core import relations as rel_service

from human_ui.routes import ALL_BLUEPRINTS
from human_ui.crypto_utils import generate_key, aes_gcm_decrypt


app = Flask(__name__, static_url_path='/beakbroodnest/static')
logger = logging.getLogger('beak_broodnest')

# ============================================================
# IP 白名單（僅限內網）
# ============================================================

ALLOWED_IPS = {'127.0.0.1', '192.168.0.10', '192.168.0.12', '192.168.0.13', '192.168.0.16'}


@app.before_request
def _check_ip_whitelist():
    """拒絕白名單以外的 IP"""
    remote = request.remote_addr
    if remote not in ALLOWED_IPS:
        logger.warning(f'IP 拒絕: {remote} -> {request.path}')
        abort(403)


# ============================================================
# Standalone 認證
# ============================================================

def _load_auth_config():
    """從 system_config 表載入認證設定"""
    with session_scope() as s:
        rows = s.query(SystemConfig).filter(
            SystemConfig.key.in_([
                'auth_username', 'auth_password_hash',
                'flask_secret_key', 'deployment_mode',
            ])
        ).all()
        return {r.key: r.value for r in rows}


def _init_app_secret():
    """啟動時從 DB 載入 Flask secret key"""
    try:
        cfg = _load_auth_config()
        app.secret_key = cfg.get('flask_secret_key', 'dev-fallback-not-secure')
    except Exception:
        app.secret_key = 'dev-fallback-not-secure'


# 模組載入時即初始化 secret key（gunicorn import 時觸發）
try:
    _init_app_secret()
except Exception:
    app.secret_key = 'dev-fallback-not-secure'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)
# 上傳上限 50 MB（routes/files.py 內另有應用層檢查）
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

_migrations_done = False


@app.before_request
def _check_auth():
    """登入檢查（IP 白名單通過後）"""
    global _migrations_done
    if not _migrations_done:
        try:
            ensure_canvas_slugs()
        except Exception:
            pass
        _migrations_done = True

    exempt = (
        request.path == '/beakbroodnest/login'
        or request.path == '/beakbroodnest/health'
        or request.path.startswith('/beakbroodnest/static/')
        or request.path.startswith('/beakbroodnest/api/worker/')
        or request.path.startswith('/beakbroodnest/gantt-mvp')
    )
    if exempt:
        return

    if not session.get('authenticated'):
        if request.is_json or request.path.startswith('/beakbroodnest/api/'):
            return jsonify({'error': '未登入'}), 401
        return redirect('/beakbroodnest/login')


@app.before_request
def _decrypt_request():
    """AES-GCM 透明解密：將加密 body 還原為明文 JSON 再交給路由處理"""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return
    if 'application/json' not in (request.content_type or ''):
        return

    raw = request.get_data()
    if not raw:
        return

    try:
        obj = json.loads(raw)
    except Exception:
        return

    if '_enc' not in obj:
        return

    key_b64 = session.get('_aes_key')
    if not key_b64:
        abort(400)

    try:
        decrypted = aes_gcm_decrypt(base64.b64decode(key_b64), obj['_enc'])
        request._cached_data = decrypted
    except Exception:
        abort(400)


@app.route('/beakbroodnest/api/session-key', methods=['GET'])
def get_session_key():
    """提供/產生當前 session 的 AES-256-GCM 金鑰（需已登入）"""
    if '_aes_key' not in session:
        session['_aes_key'] = base64.b64encode(generate_key()).decode()
        session.modified = True
    return jsonify({'key': session['_aes_key']})


@app.route('/beakbroodnest/login', methods=['GET', 'POST'])
def login_page():
    if session.get('authenticated'):
        return redirect('/beakbroodnest/')

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        try:
            cfg = _load_auth_config()
        except Exception:
            error = '系統錯誤，無法讀取認證設定'
            return render_template('login.html', error=error)

        if cfg.get('deployment_mode') != 'standalone':
            error = '認證系統尚未初始化，請先執行 python app.py --init-db'
            return render_template('login.html', error=error)

        stored_user = cfg.get('auth_username', '')
        stored_hash = cfg.get('auth_password_hash', '')

        if not stored_user or not stored_hash:
            error = '尚未初始化帳號，請先執行 python app.py --init-db'
            return render_template('login.html', error=error)

        if username == stored_user and check_password_hash(stored_hash, password):
            session.permanent = True
            session['authenticated'] = True
            session['username'] = username
            return redirect('/beakbroodnest/')
        else:
            error = '帳號或密碼錯誤'

    return render_template('login.html', error=error)


@app.route('/beakbroodnest/logout')
def logout():
    last_slug = session.get('last_canvas_slug')
    session.clear()
    if last_slug:
        session['last_canvas_slug'] = last_slug
    return redirect('/beakbroodnest/login')


@app.route('/beakbroodnest/api/auth/change-password', methods=['PUT'])
def change_password():
    """變更密碼"""
    data = request.get_json()
    if not data:
        return jsonify({'error': '需要 JSON body'}), 400

    old_pw = data.get('old_password', '')
    new_pw = data.get('new_password', '')

    if not old_pw or not new_pw:
        return jsonify({'error': '需要 old_password 和 new_password'}), 400
    if len(new_pw) < 8:
        return jsonify({'error': '新密碼至少 8 個字元'}), 400

    try:
        cfg = _load_auth_config()
    except Exception:
        return jsonify({'error': '無法讀取認證設定'}), 500

    stored_hash = cfg.get('auth_password_hash', '')
    if not check_password_hash(stored_hash, old_pw):
        return jsonify({'error': '舊密碼錯誤'}), 403

    new_hash = generate_password_hash(new_pw)
    with session_scope() as s:
        row = s.query(SystemConfig).filter(SystemConfig.key == 'auth_password_hash').first()
        if row:
            row.value = new_hash

    return jsonify({'message': '密碼已變更'})


# ============================================================
# 健康檢查端點
# ============================================================

@app.route("/beakbroodnest/health")
def _health_check():
    """回傳服務狀態與知識原子數量"""
    try:
        with session_scope() as sess:
            count = sess.query(KnowledgeAtom).count()
        return jsonify({"status": "healthy", "atoms": count})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 503

# 註冊所有 Blueprint（統一前綴 /beakbroodnest）
for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp, url_prefix='/beakbroodnest')


@app.context_processor
def inject_cache_ver():
    """靜態檔快取破除：用 static/ 目錄最新修改時間當版本號"""
    try:
        static_dir = Path(app.static_folder)
        mtime = max(f.stat().st_mtime for f in static_dir.rglob('*') if f.is_file())
        return {'cache_ver': int(mtime)}
    except (ValueError, OSError):
        return {'cache_ver': 0}


# ============================================================
# 頁面路由
# ============================================================

def _resolve_canvas(s, slug=None, only_projects=False):
    """白板解析：slug 參數 > session['last_canvas_slug'] > is_archived=false 中 id 最大者。

    only_projects=True 時 fallback 限定 is_project=true（slug 參數本身不受此限）。
    """
    if slug:
        canvas = s.query(Canvas).filter(
            Canvas.slug == slug, Canvas.is_archived == False
        ).first()
        if canvas:
            return canvas

    last = session.get('last_canvas_slug')
    if last:
        q = s.query(Canvas).filter(Canvas.slug == last, Canvas.is_archived == False)
        if only_projects:
            q = q.filter(Canvas.is_project == True)
        canvas = q.first()
        if canvas:
            return canvas

    q = s.query(Canvas).filter(Canvas.is_archived == False)
    if only_projects:
        q = q.filter(Canvas.is_project == True)
    return q.order_by(Canvas.id.desc()).first()


@app.route('/beakbroodnest/')
@app.route('/beakbroodnest')
def index():
    """首頁：導向最後存取的白板，若無則導向 id 最大的白板。
    保留 query string 讓 ?open=<atom_id> 之類的指令能傳到白板頁面（卡片搜尋對話框→在白板編輯用）。"""
    with session_scope() as s:
        canvas = _resolve_canvas(s)
        if not canvas:
            canvas = Canvas(name='預設白板', description='', owner='ethan')
            s.add(canvas)
            s.flush()
        slug = canvas.slug
    qs = request.query_string.decode()
    target = f'/beakbroodnest/canvas/{slug}'
    if qs:
        target = f'{target}?{qs}'
    return redirect(target)


@app.route('/beakbroodnest/canvas/<slug>')
def canvas_page(slug):
    """白板頁面"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            abort(404)
    session['last_canvas_slug'] = slug
    session.modified = True
    return render_template('whiteboard.html', canvas_slug=slug)


@app.route('/beakbroodnest/help')
def help_page():
    """線上說明"""
    return render_template('help.html')


@app.route('/beakbroodnest/card-test')
def card_test_page():
    """Card Editor 獨立測試頁"""
    return render_template('card_test.html')


@app.route('/beakbroodnest/orchestrator')
def orchestrator_page():
    """Orchestrator 儀錶板"""
    return render_template('dashboard.html')


@app.route('/beakbroodnest/observe')
def observe_page():
    """Pipeline 觀察儀表板"""
    return render_template('observe.html')


@app.route('/beakbroodnest/project/')
@app.route('/beakbroodnest/project')
def project_index():
    """專案頁無 slug：呈現空狀態頁，由用戶從下拉選單明確選取"""
    return render_template('project.html', canvas_slug='',
                           username=session.get('username', 'default'))


@app.route('/beakbroodnest/project/<slug>')
def project_page(slug):
    """專案 Dashboard（唯讀進度總覽）。slug 不存在時導回空狀態頁，避免錯誤頁誤導"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(
            Canvas.slug == slug, Canvas.is_archived == False
        ).first()
        if not canvas:
            return redirect('/beakbroodnest/project/')
        session['last_canvas_slug'] = slug
        session.modified = True
    return render_template('project.html', canvas_slug=slug,
                           username=session.get('username', 'default'))


# ============================================================
# 啟動
# ============================================================

def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='BeakBroodNest 人類介面 -- 知識白板與筆記系統',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python app.py --serve                    啟動 Web 伺服器
  python app.py --serve --port 5170        指定埠號啟動
  python app.py --init-db                  初始化資料庫（建表）
  python app.py --init-db --seed           初始化並載入測試資料
  python app.py --reset                    重置資料庫（刪除所有表後重建）
        """
    )
    parser.add_argument('--serve', action='store_true', help='啟動 Web 伺服器')
    parser.add_argument('--port', type=int, default=None, help='伺服器埠號 (預設讀取 config.ini)')
    parser.add_argument('--host', type=str, default=None, help='伺服器綁定位址')
    parser.add_argument('--init-db', action='store_true', help='初始化資料庫（建立所有表）')
    parser.add_argument('--reset', action='store_true', help='重置資料庫（刪除後重建）')
    parser.add_argument('--seed', action='store_true', help='載入測試資料')
    parser.add_argument('--reset-auth', action='store_true', help='重設登入帳號與密碼')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')
    return parser


def generate_auth_credentials(username=None, password=None):
    """產生或指定 standalone 模式的登入帳密，寫入 system_config。
    若 username/password 為 None，則自動產生。
    """
    with session_scope() as s:
        existing = s.query(SystemConfig).filter(
            SystemConfig.key == 'auth_username'
        ).first()
        if existing:
            print(f'  帳號已存在: {existing.value}（密碼不再顯示）')
            return None, None

        if not username:
            username = 'broodnest_' + secrets.token_hex(4)
        if not password:
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(12))

        password_hash = generate_password_hash(password)
        flask_secret = secrets.token_hex(32)

        configs = [
            SystemConfig(
                key='auth_username', value=username,
                description='Standalone 登入帳號',
            ),
            SystemConfig(
                key='auth_password_hash', value=password_hash,
                description='Standalone 登入密碼 hash',
            ),
            SystemConfig(
                key='flask_secret_key', value=flask_secret,
                description='Flask session secret key',
            ),
            SystemConfig(
                key='deployment_mode', value='standalone',
                description='部署模式: standalone / platform',
            ),
        ]
        s.add_all(configs)
        return username, password


def reset_auth_credentials(username=None, password=None):
    """重設 standalone 帳密（覆蓋既有）。
    若 username/password 為 None，則互動式詢問。
    """
    if not username:
        username = input('  新帳號: ').strip()
    if not username:
        print('  帳號不可為空')
        return False
    if not password:
        import getpass
        password = getpass.getpass('  新密碼: ')
        confirm = getpass.getpass('  確認密碼: ')
        if password != confirm:
            print('  密碼不一致')
            return False
    if len(password) < 8:
        print('  密碼至少 8 個字元')
        return False

    password_hash = generate_password_hash(password)

    with session_scope() as s:
        for key, value, desc in [
            ('auth_username', username, 'Standalone 登入帳號'),
            ('auth_password_hash', password_hash, 'Standalone 登入密碼 hash'),
            ('deployment_mode', 'standalone', '部署模式: standalone / platform'),
        ]:
            row = s.query(SystemConfig).filter(SystemConfig.key == key).first()
            if row:
                row.value = value
            else:
                s.add(SystemConfig(key=key, value=value, description=desc))

        # 確保 flask_secret_key 存在
        if not s.query(SystemConfig).filter(SystemConfig.key == 'flask_secret_key').first():
            s.add(SystemConfig(
                key='flask_secret_key',
                value=secrets.token_hex(32),
                description='Flask session secret key',
            ))

    print(f'  帳號已重設: {username}')
    return True


def ensure_canvas_slugs():
    """Migration: 確保所有 canvas 都有 slug"""
    from sqlalchemy import text, inspect as sa_inspect

    engine = get_engine()
    inspector = sa_inspect(engine)

    # 檢查 canvases 表是否存在
    if 'canvases' not in inspector.get_table_names():
        return

    # 檢查 slug 欄位是否存在
    columns = [c['name'] for c in inspector.get_columns('canvases')]
    if 'slug' not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE canvases ADD COLUMN slug VARCHAR(20)"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_canvas_slug ON canvases(slug)"
            ))
            conn.commit()
        logger.info('Migration: canvases 表已加入 slug 欄位')

    # needs_embedding 欄位（背景 embedding 用）
    if 'knowledge_atoms' in inspector.get_table_names():
        atom_cols = [c['name'] for c in inspector.get_columns('knowledge_atoms')]
        if 'needs_embedding' not in atom_cols:
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE knowledge_atoms ADD COLUMN needs_embedding BOOLEAN DEFAULT FALSE"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_atoms_needs_embedding "
                    "ON knowledge_atoms(needs_embedding)"
                ))
                conn.commit()
            logger.info('Migration: knowledge_atoms 表已加入 needs_embedding 欄位')

    # snapshot 欄位（歸檔快照用）
    columns = [c['name'] for c in inspector.get_columns('canvases')]
    if 'snapshot' not in columns:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE canvases ADD COLUMN snapshot JSONB"))
            conn.commit()
        logger.info('Migration: canvases 表已加入 snapshot 欄位')

    # 為缺少 slug 的 canvas 補上
    with session_scope() as s:
        nulls = s.query(Canvas).filter(
            (Canvas.slug == None) | (Canvas.slug == '')
        ).all()
        for c in nulls:
            c.slug = _gen_canvas_slug()
        if nulls:
            logger.info(f'Migration: 已為 {len(nulls)} 個 canvas 產生 slug')

    # gantt 配色：建立新表 + 從 system_config 搬遷個人預設
    _ensure_gantt_colors_tables()


def _ensure_gantt_colors_tables():
    """Migration: 建立 gantt_colors_default / gantt_colors_project 兩張表，
    並把 system_config 中 key='gantt_colors_<username>' 的舊資料搬到 gantt_colors_default。
    冪等：已搬過的不重複處理。
    """
    import json as _json
    from sqlalchemy import text, inspect as sa_inspect
    from core.models import GanttColorsDefault, SystemConfig

    engine = get_engine()
    # create_all 只會建立缺少的表
    from core.db import Base
    Base.metadata.create_all(engine, tables=[
        GanttColorsDefault.__table__,
        # GanttColorsProject 也一併建立
        __import__('core.models', fromlist=['GanttColorsProject']).GanttColorsProject.__table__,
    ])

    # 從 system_config 搬遷舊個人預設
    with session_scope() as s:
        rows = s.query(SystemConfig).filter(
            SystemConfig.key.like('gantt_colors_%')
        ).all()
        moved = 0
        for row in rows:
            username = row.key[len('gantt_colors_'):]
            if not username:
                continue
            try:
                colors = _json.loads(row.value) if row.value else None
            except (ValueError, TypeError):
                continue
            if not colors:
                continue
            existing = s.query(GanttColorsDefault).filter_by(username=username).first()
            if existing:
                continue  # 已搬過
            s.add(GanttColorsDefault(username=username, colors=colors))
            s.delete(row)
            moved += 1
        if moved:
            logger.info(f'Migration: 已從 system_config 搬遷 {moved} 筆 gantt 個人預設配色')


def ensure_entry_schemas():
    """確保系統預設 Entry Schema 存在（冪等，不重複建立）。"""
    from core.db import session_scope as ss

    SYSTEM_SCHEMAS = [
        {
            'code': 'freetext', 'name': '自由文字', 'icon': 'bi-text-left',
            'color': '#6b7280', 'slash_alias': None, 'sort_order': 0,
            'fields': [],
        },
        {
            'code': 'task', 'name': '待辦事項', 'icon': 'bi-check2-square',
            'color': '#3b82f6', 'slash_alias': 'td', 'sort_order': 1,
            'fields': [
                {'name': 'urgency', 'label': '緊急度', 'field_type': 'select',
                 'options': '["H","M","L"]', 'required': False, 'sort_order': 0, 'dimension': 'Y'},
                {'name': 'category', 'label': '類別', 'field_type': 'select',
                 'options': '[]', 'required': False, 'sort_order': 1, 'dimension': 'H'},
                # 預計（forecast，可隨進度滾動）
                {'name': 'planned_start', 'label': '預計開始', 'field_type': 'datetime',
                 'options': '', 'required': False, 'sort_order': 2, 'dimension': 'T'},
                {'name': 'planned_end', 'label': '預計結束', 'field_type': 'datetime',
                 'options': '', 'required': False, 'sort_order': 3, 'dimension': 'T'},
                {'name': 'planned_duration', 'label': '預估耗時', 'field_type': 'duration',
                 'options': '', 'required': False, 'sort_order': 4, 'dimension': 'T'},
                # 實際（一次性填寫）
                {'name': 'actual_start', 'label': '實際開始', 'field_type': 'datetime',
                 'options': '', 'required': False, 'sort_order': 5, 'dimension': 'T'},
                {'name': 'actual_end', 'label': '實際結束', 'field_type': 'datetime',
                 'options': '', 'required': False, 'sort_order': 6, 'dimension': 'T'},
                {'name': 'status', 'label': '狀態', 'field_type': 'select',
                 'options': '["planning","in_progress","paused","completed","cancelled"]',
                 'required': False, 'sort_order': 7, 'dimension': None},
                {'name': 'location', 'label': '地點', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 8, 'dimension': 'P'},
                {'name': 'attendees', 'label': '出席者', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 9, 'dimension': 'W'},
                # 原計畫（baseline，建立後鎖定，re-baseline 才能改）
                {'name': 'baseline_start', 'label': '原計畫開始', 'field_type': 'datetime',
                 'options': '', 'required': False, 'sort_order': 10, 'dimension': 'T'},
                {'name': 'baseline_end', 'label': '原計畫結束', 'field_type': 'datetime',
                 'options': '', 'required': False, 'sort_order': 11, 'dimension': 'T'},
                {'name': 'progress', 'label': '進度', 'field_type': 'number',
                 'options': '', 'required': False, 'sort_order': 12, 'dimension': None},
                {'name': 'note', 'label': '備註', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 13, 'dimension': None},
                # 暫停 / 取消 / 重啟歷史，存 JSON 字串：
                #   pause_log: [{paused_at, resumed_at|null, reason}, ...]
                #   cancel_info: {cancelled_at, reason} or '' when not cancelled
                #   reopen_log: [{reopened_at, reason}, ...]
                # NodeView / gantt 用專屬控件處理，不走通用 text input
                {'name': 'pause_log', 'label': '暫停紀錄', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 14, 'dimension': None},
                {'name': 'cancel_info', 'label': '取消資訊', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 15, 'dimension': None},
                {'name': 'reopen_log', 'label': '重啟紀錄', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 16, 'dimension': None},
            ],
        },
        {
            'code': 'expense', 'name': '記帳', 'icon': 'bi-wallet2',
            'color': '#10b981', 'slash_alias': 'exp', 'sort_order': 2,
            'fields': [
                {'name': 'date', 'label': '日期', 'field_type': 'date',
                 'options': '', 'required': True, 'sort_order': 0, 'dimension': 'T'},
                {'name': 'cat_major', 'label': '大類', 'field_type': 'select',
                 'options': '[]', 'required': False, 'sort_order': 1, 'dimension': 'H'},
                {'name': 'cat_mid', 'label': '中類', 'field_type': 'select',
                 'options': '[]', 'required': False, 'sort_order': 2, 'dimension': 'H'},
                {'name': 'cat_minor', 'label': '小類', 'field_type': 'select',
                 'options': '[]', 'required': False, 'sort_order': 3, 'dimension': 'H'},
                {'name': 'amount', 'label': '金額', 'field_type': 'decimal',
                 'options': '', 'required': True, 'sort_order': 4, 'dimension': 'H'},
                {'name': 'payment', 'label': '付款方式', 'field_type': 'select',
                 'options': '[]', 'required': False, 'sort_order': 5, 'dimension': None},
                {'name': 'note', 'label': '備註', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 6, 'dimension': None},
            ],
        },
        # calendar schema 已合併入 task（2026-04-25），;;cal 由前端虛擬別名處理
        {
            'code': 'diary', 'name': '日記', 'icon': 'bi-journal-text',
            'color': '#a855f7', 'slash_alias': 'diary', 'sort_order': 4,
            'fields': [
                {'name': 'date', 'label': '日期', 'field_type': 'date',
                 'options': '', 'required': True, 'sort_order': 0, 'dimension': 'T'},
                {'name': 'weather', 'label': '天氣', 'field_type': 'select',
                 'options': '["sunny","cloudy","rainy","snowy","windy","foggy"]',
                 'required': False, 'sort_order': 1, 'dimension': None},
                {'name': 'mood', 'label': '心情', 'field_type': 'select',
                 'options': '["1","2","3","4","5"]',
                 'required': False, 'sort_order': 2, 'dimension': None},
                {'name': 'body', 'label': '內容', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 3, 'dimension': None},
            ],
        },
        {
            'code': 'file', 'name': '檔案', 'icon': 'bi-paperclip',
            'color': '#64748b', 'slash_alias': 'file', 'sort_order': 6,
            'fields': [
                # 描述（說明）直接以 raw_text 呈現（inline 可編輯），
                # 此處只保留識別檔案實體所需的不可變欄位
                {'name': 'filename', 'label': '檔名', 'field_type': 'text',
                 'options': '', 'required': True, 'sort_order': 0, 'dimension': 'H'},
                {'name': 'file_token', 'label': '識別碼', 'field_type': 'text',
                 'options': '', 'required': True, 'sort_order': 1, 'dimension': None},
                {'name': 'mime_type', 'label': '類型', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 2, 'dimension': None},
                {'name': 'size_bytes', 'label': '大小(B)', 'field_type': 'number',
                 'options': '', 'required': False, 'sort_order': 3, 'dimension': None},
            ],
        },
        {
            'code': 'health', 'name': '健康記錄', 'icon': 'bi-heart-pulse',
            'color': '#ef4444', 'slash_alias': 'hp', 'sort_order': 5,
            'fields': [
                {'name': 'date', 'label': '日期', 'field_type': 'date',
                 'options': '', 'required': True, 'sort_order': 0, 'dimension': 'T'},
                {'name': 'measure_type', 'label': '量測類型', 'field_type': 'select',
                 'options': '["blood_pressure","blood_sugar","weight","heart_rate","temperature","other"]',
                 'required': True, 'sort_order': 1, 'dimension': 'H'},
                {'name': 'value_num', 'label': '數值', 'field_type': 'decimal',
                 'options': '', 'required': True, 'sort_order': 2, 'dimension': 'H'},
                {'name': 'unit', 'label': '單位', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 3, 'dimension': None},
                {'name': 'note', 'label': '備註', 'field_type': 'text',
                 'options': '', 'required': False, 'sort_order': 4, 'dimension': None},
            ],
        },
    ]

    with ss() as s:
        created = 0
        for schema_def in SYSTEM_SCHEMAS:
            existing = s.query(EntrySchema).filter_by(code=schema_def['code']).first()
            if existing:
                continue

            fields_data = schema_def.pop('fields')
            es = EntrySchema(is_system=True, **schema_def)
            s.add(es)
            s.flush()

            for fd in fields_data:
                esf = EntrySchemaField(schema_id=es.id, **fd)
                s.add(esf)

            created += 1

        if created:
            logger.info(f'Entry Schema: 建立 {created} 個系統預設類型')
        else:
            logger.info('Entry Schema: 系統預設類型已存在，跳過')


def seed_test_data():
    """載入測試用的 seed 資料"""
    from core.db import session_scope as ss

    with ss() as s:
        # 標籤
        t1 = Tag(name='BeakBroodNest', color='#3b82f6', tag_type='domain')
        t2 = Tag(name='架構設計', color='#10b981', tag_type='tag')
        t3 = Tag(name='待討論', color='#f59e0b', tag_type='tag')
        s.add_all([t1, t2, t3])
        s.flush()

        # 知識原子
        a1 = KnowledgeAtom(
            title='知識原子是最小知識單位',
            content='每一筆紀錄就是一個最小知識單位，可以是文字、清單、圖片參考、URL 等。',
            atom_type='D',
            source='human',
        )
        a2 = KnowledgeAtom(
            title='因果鍊讓知識有方向性',
            content='Obsidian 的雙向連結只知道「A 和 B 有關」，BeakBroodNest 的連結知道「A 導致了 B」。',
            atom_type='D',
            source='human',
        )
        a3 = KnowledgeAtom(
            title='建立 PostgreSQL 資料層',
            content='Phase 0 的第一步：建資料庫、核心表、基本 CRUD API。',
            atom_type='C',
            source='human',
        )
        a4 = KnowledgeAtom(
            title='建立白板 UI',
            content='Phase 1A：白板渲染、拖拉、縮放、平移、B/C/D 類型視覺區分。',
            atom_type='C',
            source='human',
        )
        s.add_all([a1, a2, a3, a4])
        s.flush()

        # 標籤關聯
        a1.tags.append(t1)
        a1.tags.append(t2)
        a2.tags.append(t1)
        a2.tags.append(t2)
        a3.tags.append(t1)
        a4.tags.append(t1)
        a4.tags.append(t3)

        # 因果關係
        rel_service.create_relation(s, a1.id, a2.id, 'supports', label='概念基礎')
        rel_service.create_relation(s, a3.id, a4.id, 'blocks', label='資料層是 UI 的前置條件')

        # 白板
        canvas = Canvas(name='BeakBroodNest 規劃', description='Phase 0~1 規劃白板')
        s.add(canvas)
        s.flush()

        # 放置原子到白板
        positions = [(a1, 100, 100), (a2, 500, 100), (a3, 100, 350), (a4, 500, 350)]
        for atom, px, py in positions:
            ca = CanvasAtom(canvas_id=canvas.id, atom_id=atom.id, pos_x=px, pos_y=py)
            s.add(ca)

    logger.info('測試資料載入完成')


def main():
    parser = create_argument_parser()

    if len(sys.argv) == 1:
        print('BeakBroodNest -- 知識白板與 AI 共用知識庫')
        print()
        print('必要動作（擇一）:')
        print('  --serve        啟動 Web 伺服器')
        print('  --init-db      初始化資料庫')
        print('  --reset-auth   重設登入帳號與密碼')
        print()
        print('選項:')
        print('  --port N       伺服器埠號')
        print('  --host ADDR    綁定位址')
        print('  --reset        重置資料庫（搭配 --init-db）')
        print('  --seed         載入測試資料（搭配 --init-db）')
        print('  --config       組態檔路徑 (預設: ../config.ini)')
        print()
        print('使用範例:')
        print('  python app.py --init-db --seed')
        print('  python app.py --serve')
        print('  python app.py --reset-auth')
        print()
        sys.exit(1)

    args = parser.parse_args()

    # 載入組態
    config_path = args.config
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')

    cfg = configparser.RawConfigParser()
    cfg.read(config_path, encoding='utf-8')

    # 設定 logging
    log_level = cfg.get('logging', 'level', fallback='INFO')
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    # 初始化資料庫引擎
    init_engine(config_path)

    if args.reset_auth:
        print()
        print('重設 Standalone 登入帳密')
        print('-' * 40)
        if reset_auth_credentials():
            print()
            print('請重啟服務使變更生效:')
            print('  sudo systemctl restart beakbroodnest')
        sys.exit(0)

    if args.init_db:
        if args.reset:
            logger.warning('正在重置資料庫...')
            from core.db import drop_all_tables
            drop_all_tables()
            logger.info('所有表已刪除')

        logger.info('正在建立資料表...')
        create_all_tables()
        logger.info('資料表建立完成')

        # 確保 Entry Schema 系統預設類型存在
        ensure_entry_schemas()

        # Migration: 既有 canvas 補 slug
        ensure_canvas_slugs()

        # 產生 standalone 認證帳密
        username, password = generate_auth_credentials()
        if username and password:
            print()
            print('=' * 55)
            print('  Standalone Web UI 登入帳號（僅顯示一次）')
            print('=' * 55)
            print(f'  帳號: {username}')
            print(f'  密碼: {password}')
            print()
            print('  * 此密碼不會再次顯示，不提供密碼救援')
            print('  * 整合 BeakPlatform 後此帳號將永久失效')
            print('=' * 55)

        if args.seed:
            seed_test_data()

        if not args.serve:
            sys.exit(0)

    if args.serve:
        # Migration: 確保 canvas slug 已填充 + Entry Schema 預設類型
        ensure_canvas_slugs()
        ensure_entry_schemas()

        host = args.host or cfg.get('flask', 'host', fallback='192.168.0.16')
        port = args.port or cfg.getint('flask', 'port', fallback=5170)
        debug = cfg.getboolean('flask', 'debug', fallback=True)

        # 從 DB 載入 secret key
        _init_app_secret()
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

        logger.info(f'BeakBroodNest 啟動於 http://{host}:{port}')
        app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
