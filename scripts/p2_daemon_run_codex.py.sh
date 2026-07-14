#!/bin/bash
# BeakBroodNest P2 daemon wrapper (Codex CLI version)
#
# 由 systemd timer (beakbroodnest-p2-codex.timer) 觸發，
# 每次處理 batch_size 個 topic 後退出，下次 timer 接力。
#
# 用 wrapper 包起來的原因：
#   1. 避免 systemd ExecStart 多行被誤解析
#   2. 顯式設定 PATH 確保可找到 codex CLI
#   3. flock -E 0 取不到鎖時 exit 0，systemd 不會把該 timer 觸發標 failed

set -u

# 安裝目錄（支援自訂 INSTALL_DIR，systemd Environment 可注入）
: "${BBN_INSTALL_DIR:=/opt/BeakBroodNest}"

# 自行 redirect stdout/stderr 到 log 檔，繞過 systemd StandardOutput=append:
# 在 Ubuntu 24.04 + User=ethan 組合上會回傳 status=209/STDOUT 的問題
LOG=/opt/tmp/p2_daemon_codex.log
exec >> "$LOG" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') beakbroodnest-p2-codex wrapper start ====="
START_EPOCH=$(date +%s)

export PATH="/home/ethan/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/home/ethan"

cd "$BBN_INSTALL_DIR" || exit 2

# 與舊 Claude 版共用 lock，避免兩個 P2 pipeline 同時回寫同一批 conversation_turns。
SENTINEL_DIR=$(mktemp -d /tmp/beak-p2-codex-run.XXXXXX)
trap 'rm -rf "$SENTINEL_DIR"' EXIT

/usr/bin/flock -E 0 -n /tmp/beak-p2.lock bash -c "
    touch '$SENTINEL_DIR/acquired'
    exec '$BBN_INSTALL_DIR/venv/bin/python' \
        '$BBN_INSTALL_DIR/scripts/semantic_summarizer_codex.py' \
        --all \
        --skip-subagents \
        --since-days 14 \
        --gap 50 \
        --batch-size 15 \
        --verbose
"
RC=$?
ELAPSED=$(( $(date +%s) - START_EPOCH ))

if [ -e "$SENTINEL_DIR/acquired" ]; then
    NOTE=""
else
    NOTE="(skipped: lock held by another batch)"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') beakbroodnest-p2-codex wrapper end rc=$RC elapsed=${ELAPSED}s $NOTE ====="
exit "$RC"
