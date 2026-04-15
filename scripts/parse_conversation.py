#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BeakCortex 復盤系統 - 對話轉換器 (P0 階段)

將 Claude Code JSONL 對話記錄轉為結構化 Markdown，
供後續訊號掃描及語意摘要處理。

改造自公司版 parse_claude_conversation.py，針對復盤需求做六項修正：
  1. thinking 區塊完整輸出（支援 full/summary/none）
  2. Agent 支線分離（isSidechain / parentUuid）
  3. tool_result 角色修正（顯示為「工具回傳」）
  4. 過濾非對話行（summary/system/permission-mode 等）
  5. 截斷長度可配置（--tool-limit）
  6. 路徑解碼修復（從 JSONL 的 cwd 欄位取得正確路徑）

零外部依賴，僅使用 Python 標準庫。
"""

import json
import argparse
import sys
import os
import glob
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple


# ============================================================
# 常數
# ============================================================

# 預設截斷長度
DEFAULT_TOOL_LIMIT = 2000

# 靜默跳過的 type 清單
SILENT_SKIP_TYPES = frozenset([
    'system',
    'permission-mode',
    'file-history-snapshot',
    'last-prompt',
    'queue-operation',
])

# ============================================================
# 工具函式
# ============================================================

def format_timestamp(timestamp_str: str) -> str:
    """將 ISO 時間戳記轉為可讀格式"""
    if not timestamp_str:
        return ''
    try:
        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S UTC')
    except (ValueError, TypeError):
        return timestamp_str


def get_current_user() -> str:
    """取得目前使用者名稱（支援 sudo）"""
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return sudo_user
    return os.environ.get('USER') or os.environ.get('LOGNAME') or 'unknown'


def get_claude_projects_path() -> Tuple[Optional[str], str]:
    """取得 Claude 對話記錄的實際路徑

    Returns:
        (projects_dir_or_None, full_path_for_display)
    """
    user = get_current_user()
    projects_dir = f"/home/{user}/.claude/projects"
    if os.path.exists(projects_dir):
        return projects_dir, projects_dir
    return None, projects_dir


def extract_cwd_from_jsonl(jsonl_file: str) -> Optional[str]:
    """從 JSONL 檔案中提取專案 cwd 路徑（前 5 行內找）"""
    try:
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for _ in range(5):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if data.get('type') == 'summary':
                        continue
                    cwd = data.get('cwd')
                    if cwd:
                        return cwd
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return None


def get_project_path_from_file(file_path: str) -> str:
    """從 JSONL 檔案路徑取得專案路徑（優先從 JSONL 內容讀取 cwd）

    公司版用字串替換反推路徑，但 Claude Code 的編碼規則不可逆
    （例如 -opt-BeakNote-temp -> /opt/BeakNote/temp，而非 /opt/BeakNote-temp）。
    正確做法是從 JSONL 的 cwd 欄位讀取。
    """
    cwd = extract_cwd_from_jsonl(file_path)
    if cwd:
        return cwd
    return "Unknown"


# ============================================================
# 訊息格式化
# ============================================================

def format_tool_call(tool_call: Dict[str, Any], param_limit: int) -> str:
    """格式化 tool_use 呼叫"""
    tool_name = tool_call.get('name', 'Unknown')
    tool_id = tool_call.get('id', '')
    parameters = tool_call.get('input', tool_call.get('parameters', {}))

    output = f"**[Tool Call]** `{tool_name}`"
    if tool_id:
        output += f"  (id: `{tool_id[:12]}...`)"
    output += "\n"

    if parameters:
        output += "```\n"
        for key, value in parameters.items():
            val_str = str(value)
            if len(val_str) > param_limit:
                output += f"{key}: {val_str[:param_limit]}... [truncated, total {len(val_str)} chars]\n"
            else:
                output += f"{key}: {val_str}\n"
        output += "```\n"

    return output


def format_tool_result(tool_result: Dict[str, Any], result_limit: int) -> str:
    """格式化 tool_result 回傳"""
    is_error = tool_result.get('is_error', False)
    label = "Tool Error" if is_error else "Tool Result"
    output = f"**[{label}]**"

    tool_use_id = tool_result.get('tool_use_id', '')
    if tool_use_id:
        output += f"  (for: `{tool_use_id[:12]}...`)"
    output += "\n"

    content = tool_result.get('content', '')
    if isinstance(content, list):
        # content 可能是 list of {type: text, text: ...}
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(item.get('text', json.dumps(item, ensure_ascii=False)))
            else:
                parts.append(str(item))
        content = '\n'.join(parts)

    if isinstance(content, str):
        if len(content) > result_limit:
            output += f"```\n{content[:result_limit]}... [truncated, total {len(content)} chars]\n```\n"
        else:
            output += f"```\n{content}\n```\n"
    elif content:
        text = json.dumps(content, ensure_ascii=False)
        if len(text) > result_limit:
            output += f"```\n{text[:result_limit]}... [truncated]\n```\n"
        else:
            output += f"```\n{text}\n```\n"

    return output


def format_thinking(thinking_text: str, mode: str) -> str:
    """格式化 thinking 區塊

    Args:
        thinking_text: thinking 內容
        mode: full / summary / none
    """
    if mode == 'none':
        return ''
    if not thinking_text:
        return ''

    if mode == 'summary' and len(thinking_text) > 500:
        text = thinking_text[:500]
        # 加上引用格式，每行前面加 >
        lines = text.split('\n')
        quoted = '\n'.join(f"> {line}" for line in lines)
        return f"> **[Thinking]**\n{quoted}\n> ... [truncated, total {len(thinking_text)} chars]\n\n"
    else:
        lines = thinking_text.split('\n')
        quoted = '\n'.join(f"> {line}" for line in lines)
        return f"> **[Thinking]**\n{quoted}\n\n"


def content_has_tool_result(content: Any) -> bool:
    """檢查 content 中是否包含 tool_result 類型"""
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'tool_result':
                return True
    return False


# ============================================================
# 核心解析邏輯
# ============================================================

class ConversationParser:
    """JSONL 對話解析器"""

    def __init__(self, thinking_mode: str = 'full',
                 sidechain_mode: str = 'include',
                 tool_limit: int = DEFAULT_TOOL_LIMIT):
        self.thinking_mode = thinking_mode
        self.sidechain_mode = sidechain_mode
        self.tool_limit = tool_limit
        self.param_limit = tool_limit // 2  # tool_use 參數上限 = N/2

        # 統計
        self.total_messages = 0
        self.total_tool_calls = 0
        self.has_sidechain = False

        # UUID -> line data 的映射（用於支線關聯）
        self.uuid_map: Dict[str, Dict] = {}

        # 支線內容收集（sidechain_mode=separate 時使用）
        self.sidechain_segments: List[str] = []

    def parse_file(self, input_file: str) -> Tuple[str, List[str]]:
        """解析 JSONL 檔案

        Returns:
            (main_markdown, list_of_sidechain_markdowns)
        """
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 第一遍：建立 UUID 映射和分類
        records = []
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                data['_line_num'] = line_num
                records.append(data)

                uuid = data.get('uuid')
                if uuid:
                    self.uuid_map[uuid] = data
            except json.JSONDecodeError:
                records.append({
                    '_line_num': line_num,
                    '_parse_error': True,
                    '_raw': line
                })

        # 第二遍：分類並格式化
        main_parts = []
        sidechain_parts = []
        current_sidechain_group = []  # 連續的支線訊息

        project_path = get_project_path_from_file(input_file)

        for data in records:
            if data.get('_parse_error'):
                # JSON 解析失敗行
                continue

            rec_type = data.get('type', '')

            # 靜默跳過的類型
            if rec_type in SILENT_SKIP_TYPES:
                continue

            # attachment：提取檔名和類型，一行輸出
            if rec_type == 'attachment':
                att = data.get('attachment', {})
                att_type = att.get('type', 'unknown')
                att_names = att.get('addedNames', [])
                if att_names:
                    names_str = ', '.join(att_names[:5])
                    if len(att_names) > 5:
                        names_str += f" ... (+{len(att_names) - 5})"
                    main_parts.append(f"*[Attachment: {att_type}] {names_str}*\n\n")
                else:
                    main_parts.append(f"*[Attachment: {att_type}]*\n\n")
                continue

            # summary：提取摘要文字
            if rec_type == 'summary':
                summary_text = data.get('summary', '')
                if not summary_text:
                    # 嘗試從 message.content 取
                    msg = data.get('message', {})
                    if isinstance(msg, dict):
                        summary_text = msg.get('content', '')
                        if isinstance(summary_text, list):
                            parts = []
                            for item in summary_text:
                                if isinstance(item, dict):
                                    parts.append(item.get('text', ''))
                                else:
                                    parts.append(str(item))
                            summary_text = '\n'.join(parts)
                if summary_text:
                    main_parts.append(f"### [Summary] (auto-compressed)\n\n{summary_text}\n\n---\n\n")
                continue

            # 主要訊息類型：user / assistant
            if rec_type not in ('user', 'assistant'):
                continue

            is_sidechain = data.get('isSidechain', False)
            if is_sidechain:
                self.has_sidechain = True

            formatted = self._format_record(data)
            if not formatted:
                continue

            if is_sidechain:
                if self.sidechain_mode == 'exclude':
                    continue
                elif self.sidechain_mode == 'separate':
                    current_sidechain_group.append(formatted)
                    continue
                else:
                    # include 模式：加入主線但有標記
                    main_parts.append(formatted)
            else:
                # 若之前有累積的支線群組，先結束它
                if current_sidechain_group and self.sidechain_mode == 'separate':
                    sidechain_parts.append('\n'.join(current_sidechain_group))
                    current_sidechain_group = []
                main_parts.append(formatted)

        # 處理尾部殘留的支線群組
        if current_sidechain_group and self.sidechain_mode == 'separate':
            sidechain_parts.append('\n'.join(current_sidechain_group))

        # 組裝 metadata
        metadata = self._build_metadata(input_file, project_path)

        main_md = metadata + '\n'.join(main_parts)
        return main_md, sidechain_parts

    def _build_metadata(self, input_file: str, project_path: str) -> str:
        """產生 YAML front matter metadata"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return (
            f"---\n"
            f"source: {input_file}\n"
            f"project: {project_path}\n"
            f"converted_at: {now}\n"
            f"total_messages: {self.total_messages}\n"
            f"total_tool_calls: {self.total_tool_calls}\n"
            f"has_sidechain: {'true' if self.has_sidechain else 'false'}\n"
            f"---\n\n"
            f"# Claude Code 對話記錄\n\n"
        )

    def _format_record(self, data: Dict[str, Any]) -> str:
        """格式化一筆 user/assistant 記錄"""
        rec_type = data.get('type', '')
        timestamp = data.get('timestamp', '')
        is_sidechain = data.get('isSidechain', False)
        parent_uuid = data.get('parentUuid')

        msg = data.get('message', {})
        if not isinstance(msg, dict):
            return ''

        role = msg.get('role', rec_type)
        content = msg.get('content', '')

        # 判斷是否為 tool_result（role=user 但內容全是 tool_result）
        is_tool_return = (role == 'user' and content_has_tool_result(content))

        # 標題
        ts_str = format_timestamp(timestamp)
        if is_sidechain and self.sidechain_mode == 'include':
            if role == 'assistant':
                header = f"### [Agent] Claude ({ts_str})\n\n"
            elif is_tool_return:
                header = f"### [Agent] 工具回傳 ({ts_str})\n\n"
            else:
                header = f"### [Agent] 用戶 ({ts_str})\n\n"
        else:
            if role == 'assistant':
                header = f"### Claude ({ts_str})\n\n"
            elif is_tool_return:
                header = f"### 工具回傳 ({ts_str})\n\n"
            elif role == 'user':
                header = f"### 用戶 ({ts_str})\n\n"
            else:
                header = f"### {role} ({ts_str})\n\n"

        # 支線關聯提示
        relation_note = ''
        if is_sidechain and parent_uuid:
            parent_data = self.uuid_map.get(parent_uuid)
            if parent_data:
                parent_ts = format_timestamp(parent_data.get('timestamp', ''))
                relation_note = f"*[支線起點，關聯主線位置: {parent_ts}]*\n\n"

        self.total_messages += 1

        # 內容格式化
        body = self._format_content(content)

        return header + relation_note + body + "---\n\n"

    def _format_content(self, content: Any) -> str:
        """格式化訊息內容"""
        if isinstance(content, str):
            return f"{content}\n\n" if content else ''

        if not isinstance(content, list):
            return f"{content}\n\n" if content else ''

        parts = []
        for item in content:
            if not isinstance(item, dict):
                parts.append(f"{item}\n\n")
                continue

            item_type = item.get('type', '')

            if item_type == 'text':
                text = item.get('text', '')
                if text:
                    parts.append(f"{text}\n\n")

            elif item_type == 'thinking':
                thinking_text = item.get('thinking', '')
                formatted = format_thinking(thinking_text, self.thinking_mode)
                if formatted:
                    parts.append(formatted)

            elif item_type == 'tool_use':
                self.total_tool_calls += 1
                parts.append(format_tool_call(item, self.param_limit) + "\n")

            elif item_type == 'tool_result':
                parts.append(format_tool_result(item, self.tool_limit) + "\n")

            else:
                # 未知類型，保留原始 JSON
                parts.append(f"*[{item_type}]*\n```json\n{json.dumps(item, ensure_ascii=False, indent=2)[:500]}\n```\n\n")

        return ''.join(parts)


# ============================================================
# 檔案列表與輸入處理
# ============================================================

def list_jsonl_files() -> List[str]:
    """列出所有可用的 JSONL 檔案"""
    projects_dir, display_path = get_claude_projects_path()

    if not projects_dir:
        print(f"[ERROR] 找不到 Claude 對話記錄目錄: {display_path}")
        return []

    pattern = os.path.join(projects_dir, "**", "*.jsonl")
    files = glob.glob(pattern, recursive=True)

    if not files:
        print(f"[INFO] {projects_dir} 中沒有找到 .jsonl 檔案")
        return []

    # 按修改時間排序（最新在最後）
    files.sort(key=lambda x: os.path.getmtime(x))

    print(f"[INFO] 可用的 Claude Code 對話記錄檔案 ({len(files)} 個)：")
    print("=" * 140)
    print(f"{'No.':<5} | {'專案路徑':<35} | {'修改時間':<20} | {'大小':<8} | {'檔名'}")
    print("-" * 140)

    for i, file_path in enumerate(files):
        display_index = len(files) - i
        filename = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)
        mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
        project_path = get_project_path_from_file(file_path)

        if file_size < 1024:
            size_str = f"{file_size}B"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f}KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f}MB"

        print(f"[{display_index:<4}] | {project_path:<35} | "
              f"{mod_time.strftime('%Y-%m-%d %H:%M'):<20} | "
              f"{size_str:<8} | {filename}")

    print("=" * 140)
    print(f"[INFO] 對話路徑: {display_path}")
    return files


def resolve_input_file(input_arg: str, file_list: List[str]) -> str:
    """解析輸入參數，支援檔案編號或完整路徑"""
    if input_arg.isdigit():
        user_index = int(input_arg)
        actual_index = len(file_list) - user_index
        if 0 <= actual_index < len(file_list):
            return file_list[actual_index]
        else:
            print(f"[ERROR] 檔案編號 [{input_arg}] 超出範圍 (1-{len(file_list)})")
            sys.exit(1)
    else:
        if os.path.exists(input_arg):
            return input_arg
        else:
            print(f"[ERROR] 找不到檔案: {input_arg}")
            sys.exit(1)


def generate_output_path(input_file: str, output_arg: Optional[str],
                         output_dir: Optional[str]) -> str:
    """產生輸出檔案完整路徑"""
    if output_arg:
        if not output_arg.lower().endswith('.md'):
            output_arg += '.md'
        if output_dir and not os.path.isabs(output_arg):
            return os.path.join(output_dir, output_arg)
        return output_arg

    basename = os.path.splitext(os.path.basename(input_file))[0]
    target_dir = output_dir if output_dir else os.getcwd()
    return os.path.join(target_dir, f"{basename}.md")


# ============================================================
# 單檔轉換
# ============================================================

def convert_single(input_file: str, output_file: str,
                   thinking_mode: str, sidechain_mode: str,
                   tool_limit: int) -> None:
    """轉換單一 JSONL 檔案"""
    parser = ConversationParser(
        thinking_mode=thinking_mode,
        sidechain_mode=sidechain_mode,
        tool_limit=tool_limit,
    )

    main_md, sidechain_segments = parser.parse_file(input_file)

    # 寫入主檔
    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(main_md)

    print(f"[OK] 主檔: {output_file}")
    print(f"     訊息數: {parser.total_messages}, "
          f"工具呼叫數: {parser.total_tool_calls}, "
          f"含支線: {'Y' if parser.has_sidechain else 'N'}")

    # separate 模式：輸出支線檔案
    if sidechain_mode == 'separate' and sidechain_segments:
        base, ext = os.path.splitext(output_file)
        for idx, segment in enumerate(sidechain_segments, 1):
            sc_file = f"{base}_sidechain_{idx}{ext}"
            with open(sc_file, 'w', encoding='utf-8') as f:
                f.write(f"---\nsidechain_index: {idx}\nparent_file: {output_file}\n---\n\n")
                f.write(segment)
            print(f"     支線 #{idx}: {sc_file}")


# ============================================================
# 批次轉換
# ============================================================

def process_convertall(output_dir: Optional[str],
                       thinking_mode: str, sidechain_mode: str,
                       tool_limit: int) -> None:
    """批次轉換所有 JSONL 檔案"""
    projects_dir, display_path = get_claude_projects_path()

    if not projects_dir:
        print(f"[ERROR] 找不到 Claude 對話記錄目錄: {display_path}")
        return

    target_dir = output_dir if output_dir else os.path.join(os.getcwd(), "convertall")
    os.makedirs(target_dir, exist_ok=True)

    pattern = os.path.join(projects_dir, "**", "*.jsonl")
    files = glob.glob(pattern, recursive=True)

    if not files:
        print(f"[INFO] {projects_dir} 中沒有找到 .jsonl 檔案")
        return

    print(f"[INFO] 開始批次轉換 {len(files)} 個檔案")
    print(f"[INFO] 輸出目錄: {target_dir}")
    print("-" * 60)

    success = 0
    failed = []

    for i, source_file in enumerate(files, 1):
        try:
            # 生成輸出檔名：專案目錄_uuid.md
            parts = source_file.split('/')
            if 'projects' in parts:
                proj_idx = parts.index('projects')
                if proj_idx + 1 < len(parts):
                    proj_dir = parts[proj_idx + 1]
                    if proj_dir.startswith('-'):
                        proj_dir = proj_dir[1:]
                    fname = os.path.splitext(os.path.basename(source_file))[0]
                    base_name = f"{proj_dir}_{fname}"
                else:
                    base_name = os.path.splitext(os.path.basename(source_file))[0]
            else:
                base_name = os.path.splitext(os.path.basename(source_file))[0]

            target_md = os.path.join(target_dir, f"{base_name}.md")

            print(f"[{i}/{len(files)}] {os.path.basename(source_file)}")
            convert_single(source_file, target_md,
                           thinking_mode, sidechain_mode, tool_limit)
            success += 1

        except Exception as e:
            failed.append((source_file, str(e)))
            print(f"  [FAIL] {os.path.basename(source_file)}: {e}")

    print("\n" + "=" * 60)
    print(f"[DONE] 成功: {success}, 失敗: {len(failed)}")
    print(f"[INFO] 輸出目錄: {target_dir}")

    if failed:
        report_file = os.path.join(target_dir, "conversion_failures.txt")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"批次轉換失敗報告\n")
            f.write(f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"失敗: {len(failed)} / {len(files)}\n")
            f.write("=" * 50 + "\n\n")
            for idx, (fpath, err) in enumerate(failed, 1):
                f.write(f"{idx}. {fpath}\n   {err}\n\n")
        print(f"[INFO] 失敗報告: {report_file}")


# ============================================================
# 使用說明
# ============================================================

USAGE_TEXT = """BeakCortex 復盤系統 - 對話轉換器

將 Claude Code JSONL 對話記錄轉為結構化 Markdown。

用法:
  {prog}                          列出所有可用的 JSONL 檔案
  {prog} -i <編號|路徑>           轉換單一檔案（輸出到當前目錄）
  {prog} -i <編號> -o output.md   轉換並指定輸出檔名
  {prog} -convertall              批次轉換所有檔案

參數:
  -i, --input FILE          輸入的 JSONL 檔案路徑或清單編號
  -o, --output FILE         輸出的 Markdown 檔案路徑
  -convertall               批次轉換所有 JSONL 到 convertall/ 目錄
  --output-dir DIR          指定輸出目錄（取代當前目錄）
  --thinking MODE           thinking 區塊處理方式
                              full    = 完整輸出（預設）
                              summary = 前 500 字 + 截斷提示
                              none    = 跳過（向後相容）
  --sidechain MODE          Agent 支線處理方式
                              include  = 主線支線都輸出，支線有標記（預設）
                              separate = 支線輸出到獨立檔案
                              exclude  = 只輸出主線
  --tool-limit N            工具截斷長度（預設 2000）
                              tool_use 參數上限 = N/2
                              tool_result 上限 = N

範例:
  {prog}
  {prog} -i 1
  {prog} -i 1 -o review_session.md --thinking summary
  {prog} -i /path/to/file.jsonl --sidechain exclude --tool-limit 5000
  {prog} -convertall --output-dir /opt/BeakCortex/temp/reviews
"""


# ============================================================
# 主程式
# ============================================================

def main():
    prog = os.path.basename(sys.argv[0])

    # 無參數時顯示使用說明 + 檔案清單
    if len(sys.argv) == 1:
        print(USAGE_TEXT.format(prog=prog))
        file_list = list_jsonl_files()
        if file_list:
            print(f"\n使用方式: {prog} -i [編號] [-o 輸出檔名.md]")
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description='BeakCortex 復盤系統 - JSONL 對話轉 Markdown',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('-i', '--input',
                        help='輸入的 JSONL 檔案路徑或編號')
    parser.add_argument('-o', '--output',
                        help='輸出的 Markdown 檔案路徑')
    parser.add_argument('-convertall', action='store_true',
                        help='批次轉換所有檔案')
    parser.add_argument('--output-dir',
                        help='指定輸出目錄')
    parser.add_argument('--thinking', default='full',
                        choices=['full', 'summary', 'none'],
                        help='thinking 區塊處理方式 (預設: full)')
    parser.add_argument('--sidechain', default='include',
                        choices=['include', 'separate', 'exclude'],
                        help='Agent 支線處理方式 (預設: include)')
    parser.add_argument('--tool-limit', type=int, default=DEFAULT_TOOL_LIMIT,
                        help=f'工具截斷長度 (預設: {DEFAULT_TOOL_LIMIT})')

    args = parser.parse_args()

    # 批次轉換
    if args.convertall:
        process_convertall(args.output_dir, args.thinking,
                           args.sidechain, args.tool_limit)
        sys.exit(0)

    # 單檔轉換
    if not args.input:
        print("[ERROR] 必須指定 -i 參數")
        parser.print_help()
        sys.exit(1)

    # 取得檔案清單（用於編號解析）
    file_list = list_jsonl_files()

    input_file = resolve_input_file(args.input, file_list)
    output_file = generate_output_path(input_file, args.output, args.output_dir)

    print(f"[INFO] 輸入: {input_file}")
    print(f"[INFO] 輸出: {output_file}")
    print(f"[INFO] thinking={args.thinking}, sidechain={args.sidechain}, tool-limit={args.tool_limit}")
    print("-" * 60)

    convert_single(input_file, output_file,
                   args.thinking, args.sidechain, args.tool_limit)


if __name__ == "__main__":
    main()
