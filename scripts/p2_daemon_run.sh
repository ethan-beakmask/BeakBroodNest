#!/bin/bash
# BeakCortex P2 daemon wrapper
#
# 由 systemd timer (beakcortex-p2.timer) 每 30 分鐘觸發一次，
# 每次處理 batch_size 個 topic 後退出，下次 timer 接力。
#
# 用 wrapper 包起來的原因：
#   1. 避免 systemd ExecStart 多行被誤解析
#   2. 顯式設定 PATH 確保使用 ethan 的 ~/.local/bin/claude (新版)
#      而非系統 /usr/local/bin/claude (舊版，不認 --append-system-prompt-file)
#   3. flock -E 0 取不到鎖時 exit 0，systemd 不會把該 timer 觸發標 failed

set -u

# 自行 redirect stdout/stderr 到 log 檔，繞過 systemd StandardOutput=append:
# 在 Ubuntu 24.04 + User=ethan 組合上會回傳 status=209/STDOUT 的問題
LOG=/opt/tmp/p2_daemon.log
exec >> "$LOG" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') beakcortex-p2 wrapper start ====="

export PATH="/home/ethan/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/home/ethan"

cd /opt/BeakCortex || exit 2

exec /usr/bin/flock -E 0 -n /tmp/beak-p2.lock \
    /opt/BeakCortex/venv/bin/python \
    /opt/BeakCortex/scripts/semantic_summarizer.py \
    --all \
    --skip-subagents \
    --since-days 14 \
    --gap 50 \
    --batch-size 20 \
    --verbose
