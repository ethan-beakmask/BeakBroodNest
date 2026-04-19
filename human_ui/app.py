#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex -- 人類介面 Flask 入口
路由已拆分至 routes/ 子模組
"""
import argparse
import functools
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
)
from core import relations as rel_service

from human_ui.routes import ALL_BLUEPRINTS


app = Flask(__name__, static_url_path='/bc/static')
logger = logging.getLogger('beak_cortex')

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
        request.path == '/bc/login'
        or request.path == '/bc/health'
        or request.path.startswith('/bc/static/')
        or request.path.startswith('/bc/api/worker/')
    )
    if exempt:
        return

    if not session.get('authenticated'):
        if request.is_json or request.path.startswith('/bc/api/'):
            return jsonify({'error': '未登入'}), 401
        return redirect('/bc/login')


@app.route('/bc/login', methods=['GET', 'POST'])
def login_page():
    if session.get('authenticated'):
        return redirect('/bc/')

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
            return redirect('/bc/')
        else:
            error = '帳號或密碼錯誤'

    return render_template('login.html', error=error)


@app.route('/bc/logout')
def logout():
    last_slug = session.get('last_canvas_slug')
    session.clear()
    if last_slug:
        session['last_canvas_slug'] = last_slug
    return redirect('/bc/login')


@app.route('/bc/api/auth/change-password', methods=['PUT'])
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

@app.route("/bc/health")
def _health_check():
    """回傳服務狀態與知識原子數量"""
    try:
        with session_scope() as sess:
            count = sess.query(KnowledgeAtom).count()
        return jsonify({"status": "healthy", "atoms": count})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 503

# 註冊所有 Blueprint（統一前綴 /bc）
for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp, url_prefix='/bc')


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

@app.route('/bc/')
@app.route('/bc')
def index():
    """首頁：導向最後存取的白板，若無則導向第一個"""
    last_slug = session.get('last_canvas_slug')
    with session_scope() as s:
        if last_slug:
            canvas = s.query(Canvas).filter(
                Canvas.slug == last_slug, Canvas.is_archived == False
            ).first()
            if canvas:
                return redirect(f'/bc/canvas/{last_slug}')

        canvas = s.query(Canvas).filter(Canvas.is_archived == False).order_by(Canvas.id).first()
        if not canvas:
            canvas = Canvas(name='預設白板', description='', owner='ethan')
            s.add(canvas)
            s.flush()
        slug = canvas.slug
    return redirect(f'/bc/canvas/{slug}')


@app.route('/bc/canvas/<slug>')
def canvas_page(slug):
    """白板頁面"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.slug == slug).first()
        if not canvas:
            abort(404)
    session['last_canvas_slug'] = slug
    session.modified = True
    return render_template('whiteboard.html', canvas_slug=slug)


@app.route('/bc/help')
def help_page():
    """線上說明"""
    return render_template('help.html')


@app.route('/bc/card-test')
def card_test_page():
    """Card Editor 獨立測試頁"""
    return render_template('card_test.html')


@app.route('/bc/dashboard')
def dashboard_page():
    """Orchestrator 儀錶板"""
    return render_template('dashboard.html')


# ============================================================
# 啟動
# ============================================================

def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='BeakCortex 人類介面 -- 知識白板與筆記系統',
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
            username = 'cortex_' + secrets.token_hex(4)
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


def seed_test_data():
    """載入測試用的 seed 資料"""
    from core.db import session_scope as ss

    with ss() as s:
        # 標籤
        t1 = Tag(name='BeakCortex', color='#3b82f6', tag_type='domain')
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
            content='Obsidian 的雙向連結只知道「A 和 B 有關」，BeakCortex 的連結知道「A 導致了 B」。',
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
        canvas = Canvas(name='BeakCortex 規劃', description='Phase 0~1 規劃白板')
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
        print('BeakCortex -- 知識白板與 AI 共用知識庫')
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

    cfg = configparser.ConfigParser()
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
            print('  sudo systemctl restart beakcortex')
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
        # Migration: 確保 canvas slug 已填充
        ensure_canvas_slugs()

        host = args.host or cfg.get('flask', 'host', fallback='192.168.0.16')
        port = args.port or cfg.getint('flask', 'port', fallback=5170)
        debug = cfg.getboolean('flask', 'debug', fallback=True)

        # 從 DB 載入 secret key
        _init_app_secret()
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

        logger.info(f'BeakCortex 啟動於 http://{host}:{port}')
        app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
