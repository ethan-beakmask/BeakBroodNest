#!/bin/bash
# Cross-compile BeakBroodNest Relay for Windows amd64
# -H windowsgui: 隱藏 console 視窗，純背景執行 + 系統列圖示

set -e
cd "$(dirname "$0")"

OUTPUT="BeakBroodNest.exe"

echo "正在交叉編譯 Windows amd64..."
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 \
    go build -ldflags="-H windowsgui" -o "$OUTPUT" .

echo "完成: $OUTPUT ($(stat -c%s "$OUTPUT") bytes)"

# 如果 SMB 可用，複製到共享目錄
SMB_DIR="/mnt/smb"
if mountpoint -q "$SMB_DIR" 2>/dev/null; then
    cp "$OUTPUT" "$SMB_DIR/$OUTPUT"
    cp config.yaml "$SMB_DIR/config.yaml"
    echo "已複製到 $SMB_DIR/"
fi
