#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性腳本：將 BeakCortex 公開前盤點清單灌入資料庫。

建立「Cortex專案」白板，灌入 todo 原子 + blocks 依賴關係。
冪等：重複執行不會重複建立（以白板名稱 + 原子標題判斷）。

用法:
  python scripts/seed_project_audit.py              # 執行灌入
  python scripts/seed_project_audit.py --dry-run     # 只印出，不寫入
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.db import init_engine, session_scope
from core.models import (
    KnowledgeAtom, Canvas, CanvasAtom, AtomRelation,
    AtomEntry, EntrySchema, EntrySchemaField, EntryFieldValue,
    NavMenu, _gen_canvas_slug,
)


# ============================================================
# 盤點清單定義
# ============================================================

CANVAS_NAME = 'Cortex專案'

# category 選項（將寫入 todo schema 的 category field）
CATEGORIES = ['安全性', '文件', '測試', '功能', '復盤Pipeline', '基建']

# 每筆 todo: (title, category, urgency, description)
# urgency: H=公開前必做, M=公開前建議, L=可延後
TODOS = [
    # -- 安全性 --
    ('Worker API sensitivity 篩選',        '安全性', 'H', 'confidential/restricted 原子不回傳給支線'),
    ('Worker API atom_type 限制',           '安全性', 'H', '強制 atom_type=F，不得建立 C/D/E 結構型原子'),
    ('Worker API content 長度限制',         '安全性', 'H', '上限 64KB，對齊 Security Red Lines 第 8 條'),
    ('Worker API 寫入頻率限制',             '安全性', 'M', '同一 worker 每分鐘最多 10 次寫入'),
    ('暫存檔案權限修正',                    '安全性', 'M', 'dispatcher.py 暫存檔從 0644 改為 0600'),
    # -- 文件 --
    ('撰寫 README.md',                      '文件', 'H', '公開專案的門面，含專案簡介、安裝、使用方式'),
    ('新增 LICENSE',                         '文件', 'H', '缺少等於 all rights reserved'),
    ('撰寫 CHANGELOG.md',                   '文件', 'M', '版本歷程記錄'),
    ('config.ini.example 補全',             '文件', 'M', '補上 embedding/MCP/進階設定範例'),
    # -- 測試 --
    ('核心 API 單元測試',                   '測試', 'M', '知識原子 CRUD 的 happy path'),
    ('MCP 工具整合測試',                    '測試', 'M', 'note_store/search/get/update 端到端測試'),
    ('Relay pipeline 測試',                 '測試', 'M', 'L1/L2 stage 的 approve/reject 驗證'),
    # -- 功能 --
    ('Relay L3 ContentPolicyStage',         '功能', 'H', '掃描可執行程式碼 + prompt injection 模式'),
    ('Relay L4 AISemanticsStage',           '功能', 'L', '偏題/幻覺/與任務指令不符偵測'),
    ('Canvas 多類型渲染',                   '功能', 'L', 'mindmap/flowchart/cornell 前端渲染'),
    ('Lifecycle UI 視覺弱化',               '功能', 'L', 'aging 原子降低對比度顯示'),
    ('ai_contexts 表建立',                  '功能', 'L', 'VISION.md 5.6 節的 AI 上下文優先度管理'),
    ('AI 輔助分類',                         '功能', 'L', '自動判斷 atom_type (B/C/D/E/F)'),
    ('知識導引 B->C->D',                    '功能', 'L', '系統提示從發散收斂到歸納的引導'),
    # -- 復盤 Pipeline --
    ('P1 訊號掃描器完善',                   '復盤Pipeline', 'L', 'signal_scanner.py 完整度提升'),
    ('P2 語意摘要器完善',                   '復盤Pipeline', 'L', 'semantic_summarizer.py 依賴 P1 輸出'),
    ('P3 復盤分析器完善',                   '復盤Pipeline', 'L', 'review_analyzer.py 待辦偵測與儲存'),
    # -- 基建 --
    ('排程任務定義 schedule.json',           '基建', 'M', 'scheduler.py 框架完成但無任務配置'),
    ('.gitignore 補全',                     '基建', 'H', '排除 data/、scripts/*.json 等'),
    ('git history 敏感資訊掃描',            '基建', 'H', '確認無 API key/密碼殘留在歷史紀錄'),
]

# blocks 關係: (blocker_title, blocked_title)
# 表示 blocker 未完成前 blocked 不能開始
BLOCKS = [
    # P1 -> P2 -> P3
    ('P1 訊號掃描器完善', 'P2 語意摘要器完善'),
    ('P2 語意摘要器完善', 'P3 復盤分析器完善'),
    # sensitivity 篩選是其他 worker 限制的前置
    ('Worker API sensitivity 篩選', 'Worker API atom_type 限制'),
    ('Worker API sensitivity 篩選', 'Worker API content 長度限制'),
    # README 需要 LICENSE 先決定
    ('新增 LICENSE', '撰寫 README.md'),
    # git history 掃描要在公開前做，先於 README
    ('git history 敏感資訊掃描', '撰寫 README.md'),
    ('.gitignore 補全', 'git history 敏感資訊掃描'),
    # L3 是 L4 的前置
    ('Relay L3 ContentPolicyStage', 'Relay L4 AISemanticsStage'),
]

# 白板上的卡片排列（依 category 分區）
LAYOUT = {
    '安全性':       {'start_x': 100,  'start_y': 100},
    '文件':         {'start_x': 600,  'start_y': 100},
    '測試':         {'start_x': 1100, 'start_y': 100},
    '功能':         {'start_x': 100,  'start_y': 500},
    '復盤Pipeline': {'start_x': 600,  'start_y': 500},
    '基建':         {'start_x': 1100, 'start_y': 500},
}
CARD_SPACING_Y = 120
CARD_WIDTH = 380
CARD_HEIGHT = 80


def seed(dry_run=False):
    cfg_path = Path(__file__).resolve().parent.parent / 'config.ini'
    init_engine(str(cfg_path))

    with session_scope() as s:
        # 1. 確保 todo schema 存在並取得 field mapping
        todo_schema = s.query(EntrySchema).filter_by(code='task').first()
        if not todo_schema:
            print('ERROR: todo schema 不存在，請先執行 app.py --init-db --seed')
            return

        fields = {
            f.name: f for f in
            s.query(EntrySchemaField).filter_by(schema_id=todo_schema.id).all()
        }

        # 2. 更新 category 選項
        cat_field = fields.get('category')
        if cat_field:
            existing_opts = json.loads(cat_field.options) if cat_field.options else []
            merged = list(dict.fromkeys(existing_opts + CATEGORIES))
            cat_field.options = json.dumps(merged, ensure_ascii=False)
            if not dry_run:
                print(f'  category 選項更新: {merged}')

        # 3. 建立白板（冪等）
        canvas = s.query(Canvas).filter_by(name=CANVAS_NAME).first()
        if canvas:
            print(f'  白板已存在: id={canvas.id} slug={canvas.slug}')
        else:
            canvas = Canvas(name=CANVAS_NAME, description='公開前盤點專案管理', owner='ethan')
            if not dry_run:
                s.add(canvas)
                s.flush()
                print(f'  建立白板: id={canvas.id} slug={canvas.slug}')
            else:
                print(f'  [dry-run] 將建立白板: {CANVAS_NAME}')

        # 4. 建立 todo 原子（冪等）
        title_to_atom = {}  # title -> KnowledgeAtom
        category_counter = {}  # category -> count (for layout)

        for title, category, urgency, description in TODOS:
            existing = (
                s.query(KnowledgeAtom)
                .filter_by(title=title, is_deleted=False)
                .first()
            )
            if existing:
                title_to_atom[title] = existing
                category_counter[category] = category_counter.get(category, 0) + 1
                if not dry_run:
                    print(f'  原子已存在: id={existing.id} "{title}"')
                continue

            if dry_run:
                print(f'  [dry-run] 將建立原子: "{title}" [{category}] urgency={urgency}')
                continue

            atom = KnowledgeAtom(
                title=title,
                content=description,
                content_type='text',
                atom_type='F',
                source='human',
                owner='ethan',
            )
            s.add(atom)
            s.flush()

            # 建立 entry (todo)
            entry = AtomEntry(
                atom_id=atom.id,
                schema_id=todo_schema.id,
                sort_order=0,
                raw_text=description,
                summary=title,
            )
            s.add(entry)
            s.flush()

            # 寫入欄位值
            field_vals = {
                'urgency': urgency,
                'category': category,
                'status': 'pending',
            }
            for fname, fval in field_vals.items():
                if fname in fields:
                    fv = EntryFieldValue(
                        entry_id=entry.id,
                        field_id=fields[fname].id,
                        value=str(fval),
                    )
                    s.add(fv)

            title_to_atom[title] = atom

            # 放上白板
            if canvas.id:
                layout = LAYOUT.get(category, {'start_x': 100, 'start_y': 900})
                idx = category_counter.get(category, 0)
                ca = CanvasAtom(
                    canvas_id=canvas.id,
                    atom_id=atom.id,
                    pos_x=layout['start_x'],
                    pos_y=layout['start_y'] + idx * CARD_SPACING_Y,
                    width=CARD_WIDTH,
                    height=CARD_HEIGHT,
                )
                s.add(ca)

            category_counter[category] = category_counter.get(category, 0) + 1
            print(f'  建立原子: id={atom.id} "{title}" [{category}]')

        s.flush()

        # 5. 建立 blocks 關係（冪等）
        for blocker_title, blocked_title in BLOCKS:
            blocker = title_to_atom.get(blocker_title)
            blocked = title_to_atom.get(blocked_title)
            if not blocker or not blocked:
                if dry_run:
                    print(f'  [dry-run] blocks: "{blocker_title}" -> "{blocked_title}"')
                continue

            existing_rel = (
                s.query(AtomRelation)
                .filter_by(
                    from_atom_id=blocker.id,
                    to_atom_id=blocked.id,
                    relation_type='blocks',
                )
                .first()
            )
            if existing_rel:
                print(f'  關係已存在: "{blocker_title}" blocks "{blocked_title}"')
                continue

            if dry_run:
                print(f'  [dry-run] blocks: "{blocker_title}" -> "{blocked_title}"')
                continue

            rel = AtomRelation(
                from_atom_id=blocker.id,
                to_atom_id=blocked.id,
                relation_type='blocks',
                created_by='human',
            )
            s.add(rel)
            print(f'  建立關係: "{blocker_title}" blocks "{blocked_title}"')

        # 6. 導覽列加入 Dashboard（冪等）
        if not dry_run:
            existing_nav = (
                s.query(NavMenu)
                .filter(NavMenu.url.like('%/project/%'))
                .first()
            )
            if not existing_nav and canvas.id:
                nav = NavMenu(
                    name='專案',
                    url=f'/beakcortex/project/{canvas.slug}',
                    icon='',
                    sort_order=15,
                    is_active=True,
                )
                s.add(nav)
                print(f'  建立導覽: "專案" -> /beakcortex/project/{canvas.slug}')

    print('Done.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='灌入 BeakCortex 公開前盤點清單')
    parser.add_argument('--dry-run', action='store_true', help='只印出，不寫入')
    args = parser.parse_args()
    seed(dry_run=args.dry_run)
