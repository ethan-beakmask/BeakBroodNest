#!/bin/bash
# ============================================================
# wrapper.sh -- 支線 claude process 包裝器
#
# 由 dispatcher.py 在 tmux window 中啟動。
# 執行 claude -p，擷取輸出，呼叫 collector.py 儲存結果。
#
# 用法: wrapper.sh <task_id> <model> <working_dir> <instruction_file> <main_pane> <session_id>
# ============================================================
set -uo pipefail

TASK_ID="$1"
MODEL="$2"
WORKING_DIR="$3"
INSTRUCTION_FILE="$4"
MAIN_PANE="${5:-}"
SESSION_ID="${6:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="/opt/BeakBroodNest/venv/bin/python"
COLLECTOR="${SCRIPT_DIR}/collector.py"

OUTPUT_FILE="/tmp/beak-output-${TASK_ID}.txt"

echo "[BeakBroodNest Worker] Task #${TASK_ID} starting (model: ${MODEL})"
echo "[BeakBroodNest Worker] Working dir: ${WORKING_DIR}"

cd "$WORKING_DIR" || {
    echo "ERROR: cannot cd to ${WORKING_DIR}" > "$OUTPUT_FILE"
    "$VENV_PYTHON" "$COLLECTOR" \
        --task-id "$TASK_ID" \
        --exit-code 1 \
        --output-file "$OUTPUT_FILE" \
        --main-pane "$MAIN_PANE" \
        --session-id "$SESSION_ID"
    rm -f "$INSTRUCTION_FILE" "$OUTPUT_FILE"
    exit 1
}

# 讀取指令
INSTRUCTION=$(cat "$INSTRUCTION_FILE")

# 執行 claude -p (print mode, 非互動)
#   --no-session-persistence: 不寫入 ~/.claude/projects/ 對話記錄，避免與主線衝突
EXIT_CODE=0
claude -p \
    --permission-mode bypassPermissions \
    --model "$MODEL" \
    --output-format text \
    --no-session-persistence \
    "$INSTRUCTION" > "$OUTPUT_FILE" 2>&1 || EXIT_CODE=$?

echo ""
echo "[BeakBroodNest Worker] claude exited with code ${EXIT_CODE}"

# 收集結果
"$VENV_PYTHON" "$COLLECTOR" \
    --task-id "$TASK_ID" \
    --exit-code "$EXIT_CODE" \
    --output-file "$OUTPUT_FILE" \
    --main-pane "$MAIN_PANE" \
    --session-id "$SESSION_ID"

# 清理
rm -f "$INSTRUCTION_FILE" "$OUTPUT_FILE"

echo "[BeakBroodNest Worker] Task #${TASK_ID} done."
