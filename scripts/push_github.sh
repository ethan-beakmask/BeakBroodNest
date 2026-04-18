#!/bin/bash
# =============================================================================
# push_github.sh - 過濾推送到 GitHub
# =============================================================================
# 將 master 分支推送到 GitHub，排除內部文件和開發工具。
# 使用臨時分支移除排除檔案後 force push。
#
# 用法: ./scripts/push_github.sh
# =============================================================================
set -e

REMOTE="github"
BRANCH="master"
TEMP_BRANCH="_github_filtered"

# === 排除清單 ===
# 個別檔案
EXCLUDE_FILES=(
    "CLAUDE.md"
    # scripts - 內部工具
    "scripts/push_github.sh"
    "scripts/setup_dev.sh"
    "scripts/schedule.json"
)

echo "=== 過濾推送到 GitHub ==="

# 確保在 master 分支且工作區乾淨
current=$(git branch --show-current)
if [ "$current" != "$BRANCH" ]; then
    echo "錯誤: 請在 $BRANCH 分支執行"
    exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "錯誤: 工作區有未提交的變更，請先 commit"
    exit 1
fi

# 刪除舊的臨時分支（如有）
git branch -D "$TEMP_BRANCH" 2>/dev/null || true

# 從 master 建立臨時分支
git checkout -b "$TEMP_BRANCH" "$BRANCH" --quiet

excluded=0

# 移除排除的檔案
for item in "${EXCLUDE_FILES[@]}"; do
    if git ls-files --error-unmatch "$item" &>/dev/null; then
        git rm --cached "$item" --quiet 2>/dev/null
        echo "  排除檔案: $item"
        excluded=$((excluded + 1))
    fi
done

if [ "$excluded" -eq 0 ]; then
    echo "  無需排除的檔案"
    git checkout "$BRANCH" --quiet
    git branch -D "$TEMP_BRANCH" 2>/dev/null || true
    echo "  直接推送..."
    git push "$REMOTE" "$BRANCH"
else
    # 提交移除
    git commit -m "chore: exclude internal files from public repository" --quiet

    # Force push 到 GitHub
    git push "$REMOTE" "$TEMP_BRANCH:$BRANCH" --force
fi

# 回到 master，清理
git checkout "$BRANCH" --force --quiet
git branch -D "$TEMP_BRANCH" 2>/dev/null || true

echo "=== GitHub 推送完成 (排除 ${excluded} 項) ==="
