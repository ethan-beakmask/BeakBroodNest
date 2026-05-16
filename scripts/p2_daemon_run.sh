#!/bin/bash
# BeakBroodNest P2 daemon wrapper
#
# 由 systemd timer (beakbroodnest-p2.timer) 每 30 分鐘觸發一次，
# 每次處理 batch_size 個 topic 後退出，下次 timer 接力。
#
# 用 wrapper 包起來的原因：
#   1. 避免 systemd ExecStart 多行被誤解析
#   2. 顯式設定 PATH 確保使用 ethan 的 ~/.local/bin/claude (新版)
#      而非系統 /usr/local/bin/claude (舊版，不認 --append-system-prompt-file)
#   3. flock -E 0 取不到鎖時 exit 0，systemd 不會把該 timer 觸發標 failed

set -u

# 安裝目錄（支援自訂 INSTALL_DIR，install.sh 會在 systemd Environment 注入）
: "${BBN_INSTALL_DIR:=/opt/BeakBroodNest}"

# 自行 redirect stdout/stderr 到 log 檔，繞過 systemd StandardOutput=append:
# 在 Ubuntu 24.04 + User=ethan 組合上會回傳 status=209/STDOUT 的問題
LOG=/opt/tmp/p2_daemon.log
exec >> "$LOG" 2>&1

echo "===== $(date '+%Y-%m-%d %H:%M:%S') beakbroodnest-p2 wrapper start ====="
START_EPOCH=$(date +%s)

export PATH="/home/ethan/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/home/ethan"

cd "$BBN_INSTALL_DIR" || exit 2

# 用 sentinel 檔案明確區分「flock 取得鎖（內部命令有跑）」與「flock 沒取到鎖（直接 skip）」
# 避免單看 elapsed 時間誤判，例如 Topics: 0 也會在 1 秒內結束。
SENTINEL_DIR=$(mktemp -d /tmp/beak-p2-run.XXXXXX)
trap 'rm -rf "$SENTINEL_DIR"' EXIT

/usr/bin/flock -E 0 -n /tmp/beak-p2.lock bash -c "
    touch '$SENTINEL_DIR/acquired'
    exec '$BBN_INSTALL_DIR/venv/bin/python' \
        '$BBN_INSTALL_DIR/scripts/semantic_summarizer.py' \
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
    NOTE=""   # 拿到鎖、命令實際跑了（不論 Topics: 0 或正常處理 N 個）
else
    NOTE="(skipped: lock held by another batch)"
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') beakbroodnest-p2 wrapper end rc=$RC elapsed=${ELAPSED}s $NOTE ====="
exit "$RC"
