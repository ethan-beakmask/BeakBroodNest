#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex MCP Server -- AI 知識庫介面
讓 Claude Code 直接操作知識原子，取代 MEMORY.md 的讀寫流程

工具已拆分至 tools/ 子模組：
  tools/knowledge.py    -- 核心知識工具 (12 個)
  tools/schema.py       -- Schema + Overview (3 個)
  tools/orchestrator.py -- 任務派發 (4 個)
  tools/canvas.py       -- 畫布操作 (5 個)
  tools/sanitize.py     -- 脫敏/還原 (7 個)

啟動方式:
  python mcp_server.py                    顯示說明
  python mcp_server.py --stdio            以 stdio 模式啟動（供 Claude Code 使用）
  python mcp_server.py --config path.ini  指定組態檔
"""
import argparse
import sys
from pathlib import Path

# 讓 core 可以被 import
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP
from core.db import init_engine
from ai_kb.tools import register_all

# ============================================================
# MCP Server 定義
# ============================================================

mcp = FastMCP(
    "BeakCortex",
    instructions="知識白板與 AI 共用知識庫 -- 結構化知識存取，取代 MEMORY.md",
)

# 註冊所有工具
register_all(mcp)


# ============================================================
# 啟動
# ============================================================

def create_argument_parser():
    parser = argparse.ArgumentParser(
        description='BeakCortex MCP Server -- AI 知識庫介面',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用範例:
  python mcp_server.py --stdio              以 stdio 模式啟動（供 Claude Code）
  python mcp_server.py --stdio -c path.ini  指定組態檔
        """
    )
    parser.add_argument('--stdio', action='store_true', help='以 stdio 傳輸模式啟動')
    parser.add_argument('--config', '-c', type=str, default=None, help='組態檔路徑')
    return parser


def main():
    parser = create_argument_parser()

    if len(sys.argv) == 1:
        print('BeakCortex MCP Server -- AI 知識庫介面')
        print()
        print('此程式為 MCP (Model Context Protocol) 伺服器，')
        print('供 Claude Code 等 AI 工具透過 stdio 存取知識庫。')
        print()
        print('必要參數:')
        print('  --stdio     以 stdio 傳輸模式啟動')
        print()
        print('選項:')
        print('  --config    組態檔路徑 (預設: ../config.ini)')
        print()
        print('知識庫工具:')
        print('  note_store              儲存知識原子')
        print('  note_search             搜尋知識原子（keyword/semantic/hybrid）')
        print('  note_get                取得原子完整資訊（含關係與阻塞）')
        print('  note_update             更新知識原子')
        print('  note_relate             建立因果關係')
        print('  note_relate_batch       批次建立因果關係')
        print('  note_forget             歸檔/終止/刪除知識')
        print('  note_blocked            追溯阻塞鍊')
        print('  note_trace              圖譜遍歷（子圖展開）')
        print('  note_check              一致性檢查（重複/矛盾偵測）')
        print('  note_overview           知識庫概覽')
        print('  note_suggest_relations  AI 自動建議關聯')
        print()
        print('畫布工具:')
        print('  canvas_list             列出所有畫布')
        print('  canvas_create           建立新畫布')
        print('  canvas_get              取得畫布內容')
        print('  canvas_place_atom       放置/移動原子到畫布')
        print('  canvas_remove_atom      從畫布移除原子')
        print()
        print('脫敏工具:')
        print('  note_sanitize           脫敏內容（產出乾淨文本+映射表）')
        print('  note_restore            還原外部回覆（佔位符換回原始值）')
        print('  sanitize_session_get    查看脫敏會話映射表')
        print('  sanitize_session_list   列出脫敏會話')
        print('  sensitive_term_add      新增敏感詞彙')
        print('  sensitive_term_list     列出敏感詞彙')
        print('  sensitive_term_remove   移除敏感詞彙')
        print()
        print('Orchestrator 工具:')
        print('  task_dispatch           派發支線任務到 tmux')
        print('  task_status             查詢任務狀態')
        print('  task_list               列出所有任務')
        print('  task_collect            取得任務報告')
        print()
        print('Claude Code 設定範例 (~/.claude/settings.json):')
        print('  "mcpServers": {')
        print('    "beak_cortex": {')
        print('      "command": "/opt/BeakCortex/venv/bin/python",')
        print('      "args": ["/opt/BeakCortex/ai_kb/mcp_server.py", "--stdio"]')
        print('    }')
        print('  }')
        print()
        sys.exit(1)

    args = parser.parse_args()

    # 初始化資料庫
    config_path = args.config
    if config_path is None:
        config_path = str(Path(__file__).resolve().parent.parent / 'config.ini')
    init_engine(config_path)

    if args.stdio:
        mcp.run(transport='stdio')


if __name__ == '__main__':
    main()
