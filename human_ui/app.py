#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex -- 人類介面 Flask 入口
路由已拆分至 routes/ 子模組
"""
import argparse
import sys
import configparser
import logging
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Flask, render_template, redirect, request, abort

from core.db import init_engine, get_session, session_scope, create_all_tables, Base
from core.models import KnowledgeAtom, Canvas, CanvasAtom, Tag
from core import relations as rel_service

from human_ui.routes import ALL_BLUEPRINTS


app = Flask(__name__)
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
# 健康檢查端點
# ============================================================

@app.route("/health")
def _health_check():
    """回傳服務狀態與知識原子數量"""
    from flask import jsonify
    try:
        with session_scope() as sess:
            count = sess.query(KnowledgeAtom).count()
        return jsonify({"status": "healthy", "atoms": count})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 503

# 註冊所有 Blueprint
for bp in ALL_BLUEPRINTS:
    app.register_blueprint(bp)


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

@app.route('/')
def index():
    """首頁：導向第一個白板，若無則自動建立"""
    with session_scope() as s:
        canvas = s.query(Canvas).filter(Canvas.is_archived == False).order_by(Canvas.id).first()
        if not canvas:
            canvas = Canvas(name='預設白板', description='', owner='ethan')
            s.add(canvas)
            s.flush()
        canvas_id = canvas.id
    return redirect(f'/canvas/{canvas_id}')


@app.route('/canvas/<int:canvas_id>')
def canvas_page(canvas_id):
    """白板頁面"""
    return render_template('whiteboard.html', canvas_id=canvas_id)


@app.route('/help')
def help_page():
    """線上說明"""
    return render_template('help.html')


@app.route('/card-test')
def card_test_page():
    """Card Editor 獨立測試頁"""
    return render_template('card_test.html')


@app.route('/dashboard')
def dashboard_page():
    """Orchestrator 儀錶板"""
    return render_template('dashboard.html')


@app.route('/health')
def health():
    """健康檢查端點（供 Nginx / install.sh 使用）"""
    from flask import jsonify
    try:
        with session_scope() as s:
            count = s.query(KnowledgeAtom).count()
        return jsonify({"status": "healthy", "atoms": count})
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500


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
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')
    return parser


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
        print('  --serve      啟動 Web 伺服器')
        print('  --init-db    初始化資料庫')
        print()
        print('選項:')
        print('  --port N     伺服器埠號')
        print('  --host ADDR  綁定位址')
        print('  --reset      重置資料庫（搭配 --init-db）')
        print('  --seed       載入測試資料（搭配 --init-db）')
        print('  --config     組態檔路徑 (預設: ../config.ini)')
        print()
        print('使用範例:')
        print('  python app.py --init-db --seed')
        print('  python app.py --serve')
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

    if args.init_db:
        if args.reset:
            logger.warning('正在重置資料庫...')
            from core.db import drop_all_tables
            drop_all_tables()
            logger.info('所有表已刪除')

        logger.info('正在建立資料表...')
        create_all_tables()
        logger.info('資料表建立完成')

        if args.seed:
            seed_test_data()

        if not args.serve:
            sys.exit(0)

    if args.serve:
        host = args.host or cfg.get('flask', 'host', fallback='192.168.0.16')
        port = args.port or cfg.getint('flask', 'port', fallback=5170)
        debug = cfg.getboolean('flask', 'debug', fallback=True)
        app.config['SECRET_KEY'] = cfg.get('flask', 'secret_key', fallback='dev')

        logger.info(f'BeakCortex 啟動於 http://{host}:{port}')
        app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()
