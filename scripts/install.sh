#!/bin/bash
# =============================================================================
# BeakBroodNest 安裝與升級腳本
# 適用於 Ubuntu 22.04/24.04 LTS
# =============================================================================
# 用法:
#   sudo bash install.sh                         全新安裝
#   sudo bash install.sh --update                升級更新 (保留資料)
#   sudo bash install.sh --status                查看服務狀態
#   sudo bash install.sh --start                 啟動服務
#   sudo bash install.sh --stop                  停止服務
#
# 環境變數 (可選):
#   INSTALL_DIR            安裝目錄 (預設: /opt/BeakBroodNest)
#   DB_NAME                資料庫名稱 (預設: beak_broodnest)
#   DB_USER                資料庫使用者 (預設: beak_broodnest)
#   DB_PASS                資料庫密碼（無預設值，安裝時必須提供）
#                          全新安裝且未設定環境變數時，會互動式要求輸入（兩次確認、至少 8 字元）
#                          非互動環境（無 TTY）必須以環境變數提供：DB_PASS='強密碼' sudo -E bash install.sh
#                          升級（--update）會自動從既有 config.ini 讀取，不需重新輸入
#                          最終密碼會寫入不入版控的 config.ini，由應用程式從該檔讀取
#   BEAKBROODNEST_PORT     外部存取 port (預設: 5170)
#   SERVICE_NAME           systemd / nginx site / log 檔前綴 (預設: beakbroodnest)
#                          同機部署多份時必須改，避免互相覆蓋
#   INSTALL_CRON           是否寫入 5 條排程到 /etc/crontab
#                          yes/no/(空)；空值時互動詢問（非互動環境預設 yes）
#   GITHUB_TOKEN           GitHub Personal Access Token (私有 repo 時需要)
#   GITHUB_REPO            GitHub clone URL (預設: ethan-beakmask/BeakBroodNest)
#
#   INSTANCE               多實例簡寫；設定後自動推導未明確指定的變數：
#                            INSTALL_DIR=/opt/BeakBroodNest-${INSTANCE}
#                            DB_NAME=beak_broodnest_${INSTANCE}
#                            DB_USER=beak_broodnest_${INSTANCE}
#                            SERVICE_NAME=beakbroodnest-${INSTANCE}
#                            MCP server key=beak_broodnest_${INSTANCE}
#                            identity=project:beakbroodnest_${INSTANCE}
#                          BEAKBROODNEST_PORT 仍須各自指定（自動推導風險高）
#                          使用者顯式設的個別變數優先於 INSTANCE 推導
# =============================================================================
set -e

# === 自動偵測安裝路徑 ===
# 當 install.sh 從已安裝目錄執行（e.g. /opt/BeakBroodNest-staging/scripts/install.sh）
# 且使用者未顯式指定 INSTALL_DIR / INSTANCE 時，從 script 位置反推
_SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")"
_SCRIPT_PARENT_DIR="$(dirname "$(dirname "$_SCRIPT_PATH")")"
if [ -z "${INSTALL_DIR:-}" ] && [ -z "${INSTANCE:-}" ] && [[ "$_SCRIPT_PARENT_DIR" == /opt/BeakBroodNest-* ]]; then
    # /opt/BeakBroodNest-staging -> INSTANCE=staging
    INSTANCE="${_SCRIPT_PARENT_DIR#/opt/BeakBroodNest-}"
    echo "[INFO] 從 script 路徑自動推導 INSTANCE=$INSTANCE"
fi

# === 設定 ===
INSTANCE="${INSTANCE:-}"

# 有 INSTANCE 時，未顯式指定的變數自動套上後綴
if [ -n "$INSTANCE" ]; then
    INSTALL_DIR="${INSTALL_DIR:-/opt/BeakBroodNest-${INSTANCE}}"
    DB_NAME="${DB_NAME:-beak_broodnest_${INSTANCE}}"
    DB_USER="${DB_USER:-beak_broodnest_${INSTANCE}}"
    SERVICE_NAME="${SERVICE_NAME:-beakbroodnest-${INSTANCE}}"
fi

INSTALL_DIR="${INSTALL_DIR:-/opt/BeakBroodNest}"
DB_NAME="${DB_NAME:-beak_broodnest}"
DB_USER="${DB_USER:-beak_broodnest}"
# DB_PASS：無後備值。環境變數未設且為全新安裝時，會在 [2/7] 互動式要求輸入。
# 設計理由：避免任何可被搜尋到的預設密碼字串進入版本歷史。
DB_PASS="${DB_PASS:-}"
BEAKBROODNEST_PORT="${BEAKBROODNEST_PORT:-5170}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/ethan-beakmask/BeakBroodNest.git}"
SERVICE_NAME="${SERVICE_NAME:-beakbroodnest}"
HEALTH_TIMEOUT=30

# MCP server name 與 identity（依 SERVICE_NAME 推導，預設安裝保持 beak_broodnest）
if [ "$SERVICE_NAME" = "beakbroodnest" ]; then
    MCP_SERVER_NAME="beak_broodnest"
    IDENTITY_PROJECT_ID="beakbroodnest"
else
    # 從 SERVICE_NAME 取後綴（beakbroodnest-staging -> staging）
    _SVC_SUFFIX="${SERVICE_NAME#beakbroodnest-}"
    _SVC_SUFFIX="${_SVC_SUFFIX#beakbroodnest_}"
    if [ "$_SVC_SUFFIX" = "$SERVICE_NAME" ]; then
        # SERVICE_NAME 不以 beakbroodnest- 開頭，整段當後綴
        _SVC_SUFFIX="$SERVICE_NAME"
    fi
    MCP_SERVER_NAME="beak_broodnest_${_SVC_SUFFIX}"
    IDENTITY_PROJECT_ID="beakbroodnest_${_SVC_SUFFIX}"
fi

# === 顏色 ===
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[$1]${NC} $2"; }

# === 共用函式 ===

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "此腳本需要 root 權限執行"
        echo ""
        echo "  正確用法（推薦 one-liner，直接從遠端執行）："
        echo "    sudo bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/ethan-beakmask/BeakBroodNest/master/scripts/install.sh)\""
        echo ""
        echo "  或下載到 /tmp 後執行："
        echo "    curl -fsSL https://raw.githubusercontent.com/ethan-beakmask/BeakBroodNest/master/scripts/install.sh -o /tmp/install.sh"
        echo "    sudo bash /tmp/install.sh"
        echo ""
        echo "  常見錯誤："
        echo "    ./install.sh           -> Permission denied（檔案無 x 執行位）"
        echo "    sudo ./install.sh      -> command not found（sudo PATH 不含 .）"
        echo "    請改用 sudo bash <檔案路徑>"
        exit 1
    fi
}

check_ubuntu() {
    if ! grep -q "Ubuntu" /etc/os-release 2>/dev/null; then
        log_warn "此腳本針對 Ubuntu 22.04/24.04 設計，其他系統可能需要調整"
    fi
}

# Gunicorn 內部 port = 外部 port + 1
resolve_ports() {
    NGINX_PORT="$BEAKBROODNEST_PORT"
    APP_PORT=$((BEAKBROODNEST_PORT + 1))
    HEALTH_URL="http://127.0.0.1:${APP_PORT}/beakbroodnest/health"
}

health_check() {
    log_info "健康檢查 (等待最多 ${HEALTH_TIMEOUT}s)..."
    local elapsed=0
    while [ $elapsed -lt $HEALTH_TIMEOUT ]; do
        if curl -sf "$HEALTH_URL" 2>/dev/null | grep -q '"status"'; then
            log_info "健康檢查通過"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
        printf "."
    done
    echo ""
    log_error "健康檢查逾時 (${HEALTH_TIMEOUT}s)"
    log_warn "最近日誌:"
    journalctl -u "$SERVICE_NAME" -n 20 --no-pager 2>/dev/null || true
    return 1
}

# 取得知識原子數量（資料庫完整性檢查）
get_atom_count() {
    sudo -u postgres psql -d "$DB_NAME" -t -c "SELECT count(*) FROM knowledge_atoms;" 2>/dev/null | tr -d ' \n' || echo "N/A"
}

# 決定安裝目錄擁有者，並判斷 AI 對話分析 pipeline 是否啟用
#
# 影響：
#   1. 目錄擁有者 -> /etc/crontab 自動寫入的 user 欄位
#   2. config.ini [pipeline] claude_projects_dir -> db_importer 找 Claude Code 對話的路徑
#
# 結果寫入兩個全域變數：
#   INSTALL_OWNER    最終 chown 目標（root / 實際使用者）
#   PIPELINE_DISABLED  非空表示純白板模式，不寫 claude_projects_dir
#
# 決策順序：
#   - 環境變數 INSTALL_OWNER 直接採用（自動化部署）
#   - SUDO_USER 非 root 且存在 -> 自動採用
#   - 互動詢問：列出 /home 下偵測到 ~/.claude/projects 的候選 + 純白板選項
#   - 非互動且無 SUDO_USER -> root（純白板模式），印警告
detect_install_owner() {
    INSTALL_OWNER="${INSTALL_OWNER:-}"
    PIPELINE_DISABLED=""

    if [ -n "$INSTALL_OWNER" ]; then
        if [ "$INSTALL_OWNER" = "root" ]; then
            PIPELINE_DISABLED=1
        elif ! id "$INSTALL_OWNER" &>/dev/null; then
            log_error "INSTALL_OWNER='$INSTALL_OWNER' 不存在"
            exit 1
        fi
        log_info "安裝擁有者: $INSTALL_OWNER (由環境變數指定)"
        return
    fi

    if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] && id "$SUDO_USER" &>/dev/null; then
        INSTALL_OWNER="$SUDO_USER"
        log_info "安裝擁有者: $INSTALL_OWNER (由 SUDO_USER 偵測)"
        return
    fi

    if [ ! -t 0 ]; then
        log_warn "非互動環境且無 SUDO_USER，安裝擁有者保留為 root"
        log_warn "AI 對話分析將停用，僅可使用白板功能"
        log_warn "完整模式請以 INSTALL_OWNER=<使用者> 環境變數重跑"
        INSTALL_OWNER="root"
        PIPELINE_DISABLED=1
        return
    fi

    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │ 安裝模式選擇                                                │"
    echo "  ├─────────────────────────────────────────────────────────────┤"
    echo "  │ 完整模式：分析 Claude Code 對話 + 白板筆記                  │"
    echo "  │   需指定 Claude Code 使用者，pipeline 會讀取                │"
    echo "  │   /home/<user>/.claude/projects/ 內的對話紀錄               │"
    echo "  │                                                             │"
    echo "  │ 純白板模式：僅使用白板筆記功能                              │"
    echo "  │   不分析 AI 對話，適合純當記事本/知識白板使用               │"
    echo "  │   隨時可手動編輯 config.ini 啟用完整模式（見下方說明）      │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""

    local candidates=()
    while IFS= read -r h; do
        local u
        u=$(basename "$h")
        if [ -d "$h/.claude/projects" ]; then
            candidates+=("$u")
        fi
    done < <(find /home -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort)

    if [ ${#candidates[@]} -eq 0 ]; then
        echo "  未偵測到任何 /home/*/.claude/projects 目錄"
        echo "    [1] 純白板模式（推薦）"
        echo "    [2] 手動輸入 Claude Code 使用者帳號"
        echo ""
        while true; do
            read -p "  選擇 [1-2]: " choice
            case "$choice" in
                1)
                    INSTALL_OWNER="root"
                    PIPELINE_DISABLED=1
                    log_info "已選擇純白板模式"
                    return ;;
                2)
                    read -p "  使用者帳號: " manual_user
                    if id "$manual_user" &>/dev/null; then
                        INSTALL_OWNER="$manual_user"
                        log_info "安裝擁有者: $INSTALL_OWNER (手動輸入)"
                        return
                    else
                        echo "  使用者 '$manual_user' 不存在"
                    fi ;;
                *) echo "  無效選項" ;;
            esac
        done
    fi

    echo "  偵測到以下 Claude Code 使用者："
    local i=1
    for u in "${candidates[@]}"; do
        echo "    [$i] $u  (/home/$u/.claude/projects)"
        i=$((i+1))
    done
    echo "    [s] 純白板模式（不分析 AI 對話）"
    echo ""
    while true; do
        read -p "  選擇 [1-${#candidates[@]}/s]: " choice
        if [ "$choice" = "s" ] || [ "$choice" = "S" ]; then
            INSTALL_OWNER="root"
            PIPELINE_DISABLED=1
            log_info "已選擇純白板模式"
            return
        fi
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#candidates[@]} ]; then
            INSTALL_OWNER="${candidates[$((choice-1))]}"
            log_info "安裝擁有者: $INSTALL_OWNER"
            return
        fi
        echo "  無效選項，請重新輸入"
    done
}

# === 參數處理 ===
ACTION="fresh"

case "${1:-}" in
    --update)    ACTION="update" ;;
    --status)    ACTION="status" ;;
    --start)     ACTION="start" ;;
    --stop)      ACTION="stop" ;;
    "")          ACTION="fresh" ;;
    *)
        echo "BeakBroodNest 安裝與升級腳本"
        echo ""
        echo "用法:"
        echo "  sudo bash install.sh                  全新安裝"
        echo "  sudo bash install.sh --update         升級更新 (保留資料)"
        echo "  sudo bash install.sh --status         查看服務狀態"
        echo "  sudo bash install.sh --start          啟動服務"
        echo "  sudo bash install.sh --stop           停止服務"
        echo ""
        echo "環境變數:"
        echo "  INSTALL_DIR=$INSTALL_DIR"
        echo "  DB_NAME=$DB_NAME"
        echo "  BEAKBROODNEST_PORT=$BEAKBROODNEST_PORT"
        exit 1
        ;;
esac


# =========================================================================
#  --status
# =========================================================================
if [ "$ACTION" = "status" ]; then
    echo "=== BeakBroodNest 服務狀態 ==="
    echo ""

    # systemd service
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        log_info "服務狀態: 運行中"
        systemctl status "$SERVICE_NAME" --no-pager -l 2>/dev/null | head -15
    else
        log_warn "服務狀態: 未運行"
    fi

    echo ""

    # PostgreSQL
    if systemctl is-active --quiet postgresql 2>/dev/null; then
        log_info "PostgreSQL: 運行中"
        atom_count=$(get_atom_count)
        log_info "知識原子數量: $atom_count"
    else
        log_warn "PostgreSQL: 未運行"
    fi

    # Nginx
    if systemctl is-active --quiet nginx 2>/dev/null; then
        log_info "Nginx: 運行中"
    else
        log_warn "Nginx: 未運行"
    fi

    # 版本資訊
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo ""
        cd "$INSTALL_DIR"
        log_info "版本: $(git log --oneline -1 2>/dev/null || echo '無法取得')"
    fi

    exit 0
fi


# =========================================================================
#  --start
# =========================================================================
if [ "$ACTION" = "start" ]; then
    check_root
    resolve_ports
    log_info "啟動 BeakBroodNest..."
    systemctl start "$SERVICE_NAME"
    health_check
    exit 0
fi


# =========================================================================
#  --stop
# =========================================================================
if [ "$ACTION" = "stop" ]; then
    check_root
    log_info "停止 BeakBroodNest..."
    systemctl stop "$SERVICE_NAME"
    log_info "服務已停止"
    exit 0
fi


# =========================================================================
#  --update 升級更新（資料庫安全保護）
# =========================================================================
if [ "$ACTION" = "update" ]; then
    check_root
    resolve_ports

    echo "============================================"
    echo "  BeakBroodNest 升級更新"
    echo "============================================"

    if [ ! -d "$INSTALL_DIR/.git" ]; then
        log_error "安裝目錄不存在或不是 git repo: $INSTALL_DIR"
        log_error "請先執行全新安裝: sudo bash install.sh"
        exit 1
    fi

    cd "$INSTALL_DIR"

    # [安全檢查] 記錄更新前的原子數量
    atom_before=$(get_atom_count)
    log_info "資料庫安全檢查: 更新前知識原子數量 = $atom_before"

    # 若是 re-exec 進來（git reset 後），直接跳過拉取，從 schema 補丁繼續
    if [ -n "${BBN_UPDATE_REEXEC:-}" ]; then
        log_info "（接續上一輪 git reset 後流程）"
        goto_schema_patch=1
    fi

    if [ -z "${goto_schema_patch:-}" ]; then
    # [1] 拉取最新程式碼
    log_step "1/3" "拉取最新程式碼..."

    git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

    # 此 repo 已公開，預設 origin 重設為純 public URL，避免舊安裝殘留的過期 token 卡住
    # 仍保留 PAT fallback：若 public URL 也連不上（網路問題 / repo 被改回私有），才提示輸入
    git remote set-url origin "$GITHUB_REPO"
    if ! git ls-remote origin HEAD &>/dev/null; then
        log_warn "無法以公開方式存取 $GITHUB_REPO"
        if [ -z "${GITHUB_TOKEN:-}" ]; then
            read -s -p "請輸入 GitHub Personal Access Token（或 Ctrl+C 中止）: " GITHUB_TOKEN
            echo ""
            if [ -z "$GITHUB_TOKEN" ]; then
                log_error "未輸入 Token，無法繼續"
                exit 1
            fi
        fi
        repo_path=$(echo "$GITHUB_REPO" | sed 's|.*github.com/||' | sed 's|\.git$||')
        git remote set-url origin "https://${GITHUB_TOKEN}@github.com/${repo_path}.git"
    fi

    git fetch origin master
    local_hash=$(git rev-parse HEAD)
    remote_hash=$(git rev-parse origin/master)

    if [ "$local_hash" = "$remote_hash" ]; then
        log_info "程式碼已是最新版本 ($(git log --oneline -1))"
        log_info "無需更新"
        exit 0
    fi

    git reset --hard origin/master
    log_info "更新至: $(git log --oneline -1)"

    # 拉完後 exec 自己重啟，避免 bash 邊讀邊執行被改寫過的腳本檔造成偏移錯位
    # （上一次此 bug 導致 schema patch 用了舊版 awk 解析，DB_PASS 落到預設值認證失敗）
    export BBN_UPDATE_REEXEC=1
    log_info "重新載入新版 install.sh 繼續..."
    exec "$0" "$@"
    fi  # end "if [ -z goto_schema_patch ]"

    # [2] 更新 Python 依賴（強制 HOME=/root 讓 pip cache 落到 root，避免 sudo -E 帶入用戶 HOME 導致 cache 被禁用）
    log_step "2/4" "更新 Python 依賴..."
    HOME=/root "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
    HOME=/root "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

    # [3] Schema 補丁：對既有 DB 重跑 idempotent 的結構性 SQL（CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE VIEW）
    #     僅補結構，不動 seed 資料；既有原子完全不會被影響（最後仍會比對 atom_count 雙重保險）
    log_step "3/4" "套用 Schema 補丁..."

    # 從 config.ini 讀 DB 連線（升級情境用既有設定，不依賴環境變數）
    # 改用 python configparser 解析，避免 awk -F= 在密碼含 '=' / '#' / 前導空白等特殊字元時誤判
    if [ -f "$INSTALL_DIR/config.ini" ] && [ -x "$INSTALL_DIR/venv/bin/python3" ]; then
        CFG_VARS=$("$INSTALL_DIR/venv/bin/python3" - "$INSTALL_DIR/config.ini" <<'PYEOF'
import configparser, shlex, sys
c = configparser.RawConfigParser()
c.read(sys.argv[1])
if c.has_section('postgresql'):
    s = c['postgresql']
    print(f"CFG_DB_NAME={shlex.quote(s.get('database',''))}")
    print(f"CFG_DB_USER={shlex.quote(s.get('username',''))}")
    print(f"CFG_DB_PASS={shlex.quote(s.get('password',''))}")
    print(f"CFG_DB_HOST={shlex.quote(s.get('host','127.0.0.1'))}")
    print(f"CFG_DB_PORT={shlex.quote(s.get('port','5432'))}")
PYEOF
)
        eval "$CFG_VARS"
        DB_NAME="${CFG_DB_NAME:-$DB_NAME}"
        DB_USER="${CFG_DB_USER:-$DB_USER}"
        DB_PASS="${CFG_DB_PASS:-$DB_PASS}"
        DB_HOST="${CFG_DB_HOST:-127.0.0.1}"
        DB_PORT="${CFG_DB_PORT:-5432}"
    else
        DB_HOST="${DB_HOST:-127.0.0.1}"
        DB_PORT="${DB_PORT:-5432}"
    fi

    # 同步 ORM schema（補上新版本新增的欄位/表），等同全新安裝 [6/7] 第一步
    "$INSTALL_DIR/venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from core.db import init_engine, create_all_tables
from core import models  # noqa: F401
from orchestrator import models as _om  # noqa: F401
init_engine('$INSTALL_DIR/config.ini')
create_all_tables()
print('  ORM 結構同步完成')
" || log_warn "  ORM 結構同步失敗（請檢查 config.ini 與 DB 連線）"

    # Pipeline 表（conversations / conversation_turns / pipeline_runs / session_logs / p2_failures）
    if [ -f "$INSTALL_DIR/scripts/init_pipeline_tables.sql" ]; then
        PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" \
            -f "$INSTALL_DIR/scripts/init_pipeline_tables.sql" -v ON_ERROR_STOP=1 -q \
            && log_info "  Pipeline 表結構補丁完成" \
            || log_warn "  Pipeline 表結構補丁失敗（observe 對話拓樸可能空白）"
    fi

    # seed_baseline 也是 idempotent（INSERT ... ON CONFLICT DO NOTHING / CREATE OR REPLACE VIEW）
    if [ -f "$INSTALL_DIR/scripts/seed_baseline.sql" ]; then
        PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" \
            -f "$INSTALL_DIR/scripts/seed_baseline.sql" -v ON_ERROR_STOP=1 -q \
            && log_info "  基線 seed 補丁完成（主選單 / view 等）" \
            || log_warn "  基線 seed 補丁失敗"
    fi

    # [4] 重啟服務
    log_step "4/4" "重啟服務..."
    systemctl restart "$SERVICE_NAME"
    health_check

    # [安全檢查] 驗證原子數量未變動
    atom_after=$(get_atom_count)
    if [ "$atom_before" != "$atom_after" ]; then
        log_error "原子數量變動! 更新前: $atom_before, 更新後: $atom_after"
        log_error "請立即檢查資料庫完整性!"
    else
        log_info "資料庫完整性確認: 原子數量不變 ($atom_before)"
    fi

    # [診斷] cron user 與 INSTALL_DIR owner 一致性檢查
    if [ -f /etc/crontab ] && grep -qF "$INSTALL_DIR/scripts/db_importer.py" /etc/crontab 2>/dev/null; then
        CRON_DBIMP_USER=$(grep -F "$INSTALL_DIR/scripts/db_importer.py" /etc/crontab | head -1 | awk '{print $6}')
        DIR_OWNER=$(stat -c '%U' "$INSTALL_DIR" 2>/dev/null)
        if [ -n "$CRON_DBIMP_USER" ] && [ -n "$DIR_OWNER" ] && [ "$CRON_DBIMP_USER" != "$DIR_OWNER" ]; then
            echo ""
            log_warn "偵測到 /etc/crontab 的 db_importer 跑在帳號 '$CRON_DBIMP_USER'，但 $INSTALL_DIR 的擁有者是 '$DIR_OWNER'"
            log_warn "若 '$CRON_DBIMP_USER' 沒有 ~/.claude/projects 目錄，P0 對話匯入將永遠匯入 0 筆"
            log_warn "建議：將 /etc/crontab 內 db_importer 那行的 user 欄位改為 '$DIR_OWNER'，或在 config.ini [pipeline] claude_projects_dir 明確指定路徑"
        fi
    fi

    echo ""
    echo "============================================"
    log_info "升級更新完成"
    echo "  版本: $(git log --oneline -1)"
    echo "============================================"
    exit 0
fi


# =========================================================================
#  全新安裝
# =========================================================================
check_root
check_ubuntu
resolve_ports

echo "============================================"
echo "  BeakBroodNest 全新安裝"
echo "============================================"
echo ""
echo "  安裝目錄: $INSTALL_DIR"
echo "  資料庫:   $DB_NAME"
echo "  Port:     $NGINX_PORT (Nginx) / $APP_PORT (Gunicorn)"
echo "  來源:     $GITHUB_REPO"
echo ""

# 防呆：如果已安裝且資料庫有資料，拒絕全新安裝
if [ -f "$INSTALL_DIR/config.ini" ]; then
    existing_count=$(get_atom_count)
    if [ "$existing_count" != "N/A" ] && [ "$existing_count" -gt 0 ] 2>/dev/null; then
        log_error "偵測到既有安裝，資料庫含 $existing_count 筆知識原子"
        log_error "全新安裝會清除所有資料，請改用: sudo bash install.sh --update"
        echo ""
        read -p "確定要覆蓋安裝嗎？所有知識原子將被刪除 (輸入 YES 確認): " CONFIRM
        if [ "$CONFIRM" != "YES" ]; then
            echo "取消安裝"
            exit 0
        fi
        log_warn "使用者確認覆蓋安裝"
    fi
fi


# === [1/7] 系統依賴 ===
log_step "1/7" "檢查系統依賴..."

REQUIRED_PKGS=(python3 python3-venv python3-pip postgresql postgresql-contrib nginx git curl)
MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    if dpkg -l "$pkg" 2>/dev/null | grep -q "^ii"; then
        printf "  %-25s %s\n" "$pkg" "OK"
    else
        printf "  %-25s %s\n" "$pkg" "缺少"
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -eq 0 ]; then
    log_info "所有系統依賴已安裝"
else
    log_info "需要安裝: ${MISSING_PKGS[*]}"
    timeout 120 apt-get update -q || log_warn "apt update 逾時，嘗試直接安裝..."
    apt-get install -y -q "${MISSING_PKGS[@]}"
fi

systemctl enable --now postgresql 2>/dev/null || true
systemctl enable --now nginx 2>/dev/null || true
log_info "系統依賴就緒"


# === [2/7] PostgreSQL ===
log_step "2/7" "設定 PostgreSQL..."

# 取得 DB 密碼：環境變數優先；否則互動式輸入；無 TTY 時直接報錯退出
if [ -z "$DB_PASS" ]; then
    if [ -t 0 ]; then
        echo ""
        echo "  請設定 PostgreSQL 使用者 $DB_USER 的密碼"
        echo "  此密碼會寫入 $INSTALL_DIR/config.ini（不入版控），由應用程式讀取"
        while true; do
            read -sp "  密碼（至少 8 字元）: " DB_PASS
            echo ""
            if [ ${#DB_PASS} -lt 8 ]; then
                echo "  密碼至少 8 個字元，請重新輸入"
                DB_PASS=""
                continue
            fi
            read -sp "  確認密碼: " DB_PASS2
            echo ""
            if [ "$DB_PASS" != "$DB_PASS2" ]; then
                echo "  密碼不一致，請重新輸入"
                DB_PASS=""
                continue
            fi
            break
        done
        unset DB_PASS2
    else
        log_error "未提供 DB_PASS 環境變數，且非互動式環境無法提示輸入"
        log_error "請改為：DB_PASS='強密碼' sudo -E bash install.sh"
        exit 1
    fi
fi

# 偵測 PostgreSQL 主版本，安裝對應的 pgvector 擴充套件
PG_MAJOR=$(sudo -u postgres psql -tAc "SHOW server_version_num" 2>/dev/null | awk '{print int($1/10000)}')
if [ -n "$PG_MAJOR" ]; then
    PGVECTOR_PKG="postgresql-${PG_MAJOR}-pgvector"
    if ! dpkg -l "$PGVECTOR_PKG" 2>/dev/null | grep -q "^ii"; then
        log_info "安裝 $PGVECTOR_PKG ..."
        apt-get install -y -q "$PGVECTOR_PKG" || log_warn "$PGVECTOR_PKG 安裝失敗，語意搜尋將不可用"
    else
        log_info "$PGVECTOR_PKG 已安裝"
    fi
else
    log_warn "無法偵測 PostgreSQL 版本，請手動安裝對應的 pgvector 套件"
fi

sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true
sudo -u postgres psql -c "ALTER USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true

# 檢查資料庫是否已存在
if sudo -u postgres psql -lqt | cut -d'|' -f1 | grep -qw "$DB_NAME"; then
    log_info "資料庫 $DB_NAME 已存在"
else
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    log_info "資料庫 $DB_NAME 已建立"
fi

# 啟用必要的 PostgreSQL extensions（vector 必須，pg_trgm 用於關鍵字搜尋）
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" 2>/dev/null \
    && log_info "extension vector 已啟用" \
    || log_warn "extension vector 啟用失敗（請確認 $PGVECTOR_PKG 已正確安裝）"
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null 2>&1 \
    && log_info "extension pg_trgm 已啟用" \
    || log_warn "extension pg_trgm 啟用失敗"


# === [3/7] 取得程式碼 ===
log_step "3/7" "取得程式碼..."

# 私有 repo 需要 token
if [ -z "${GITHUB_TOKEN:-}" ]; then
    # 先嘗試不帶 token，公開 repo 不需要
    if ! git ls-remote "$GITHUB_REPO" HEAD &>/dev/null; then
        echo ""
        echo "  需要 GitHub Personal Access Token（私有 repo）"
        read -s -p "請輸入 GitHub PAT: " GITHUB_TOKEN
        echo ""
        if [ -z "$GITHUB_TOKEN" ]; then
            log_error "未輸入 Token，無法繼續"
            exit 1
        fi
    fi
fi

# 組成 clone URL
if [ -n "${GITHUB_TOKEN:-}" ]; then
    repo_path=$(echo "$GITHUB_REPO" | sed 's|.*github.com/||' | sed 's|\.git$||')
    CLONE_URL="https://${GITHUB_TOKEN}@github.com/${repo_path}.git"
else
    CLONE_URL="$GITHUB_REPO"
fi

git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR"
    git remote set-url origin "$CLONE_URL"
    git fetch origin master 2>/dev/null
    git reset --hard origin/master
    log_info "程式碼已同步至最新版本"
else
    if [ -d "$INSTALL_DIR" ]; then
        # 目錄存在但不是 git repo，備份
        mv "$INSTALL_DIR" "${INSTALL_DIR}.bak.$(date +%Y%m%d_%H%M%S)"
        log_warn "既有目錄已備份"
    fi
    git clone "$CLONE_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    log_info "程式碼 clone 完成: $(git log --oneline -1)"
fi


# 在 [3/7] clone 完成後立即決定擁有者，因為 [5/7] 寫 config.ini 時需要它
# 才能正確設定 [pipeline] claude_projects_dir。實際 chown 延後到 [7/7] 之後執行，
# 避免 [4]/[5]/[6] 中 root 寫入的新檔案讓擁有權混亂。
detect_install_owner


# === [4/7] Python 虛擬環境 ===
log_step "4/7" "建立 Python 虛擬環境..."

if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
# 強制 HOME=/root 讓 pip cache 落到 /root/.cache/pip。
# 之前 sudo -E 帶入用戶 HOME 但 root 無寫權，pip 會 disable cache，
# 每次重裝都得重新下載 ~2GB 的 torch/transformers wheel。
HOME=/root "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
HOME=/root "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
log_info "Python 環境就緒"


# === [5/7] 組態檔 ===
log_step "5/7" "設定組態檔..."

if [ -f "$INSTALL_DIR/config.ini" ]; then
    log_info "config.ini 已存在，保留現有設定"
else
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    RELAY_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")

    if [ -n "$PIPELINE_DISABLED" ]; then
        # 純白板模式：以註解形式留下完整模式啟用說明，使用者隨時可手動補上
        PIPELINE_SECTION="[pipeline]
; ──────────────────────────────────────────────────────────────────
; 純白板模式 - AI 對話分析已停用
; ──────────────────────────────────────────────────────────────────
; 若要啟用「分析 Claude Code 對話 -> 萃取為知識原子」的完整功能：
;   1. 移除以下這行開頭的分號，並改成你的實際路徑
;      （路徑為 Claude Code 對話檔目錄，通常是 ~/.claude/projects）
;   2. 將安裝目錄擁有者改為該使用者：
;        sudo chown -R <使用者>:<使用者> $INSTALL_DIR
;   3. 重新匯入：cd $INSTALL_DIR && sudo -u <使用者> venv/bin/python scripts/db_importer.py -convertall
;
; claude_projects_dir = /home/YOUR-USER/.claude/projects"
    else
        PIPELINE_SECTION="[pipeline]
claude_projects_dir = /home/${INSTALL_OWNER}/.claude/projects"
    fi

    cat > "$INSTALL_DIR/config.ini" << CFGEOF
[postgresql]
host = localhost
port = 5432
database = $DB_NAME
username = $DB_USER
password = $DB_PASS

[flask]
host = 127.0.0.1
port = $APP_PORT
debug = false
secret_key = $SECRET_KEY

[relay]
host = 127.0.0.1
port = 5200
token = $RELAY_TOKEN

[logging]
level = INFO

[identity]
project_id = $IDENTITY_PROJECT_ID

${PIPELINE_SECTION}
CFGEOF

    chmod 600 "$INSTALL_DIR/config.ini"
    log_info "config.ini 已建立"
fi


# === [6/7] 初始化資料庫 ===
log_step "6/7" "初始化資料庫..."

"$INSTALL_DIR/venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from core.db import init_engine, create_all_tables
# 載入所有 ORM 類別讓它們註冊到 Base.metadata（單純 import 即可）
from core import models  # noqa: F401
from orchestrator import models as _om  # noqa: F401
init_engine('$INSTALL_DIR/config.ini')
create_all_tables()
print('  資料表建立完成')
"

# 載入基線 seed（主選單、relation_type_registry、atom_schemas、tag_categories、pending_outputs view）
if [ -f "$INSTALL_DIR/scripts/seed_baseline.sql" ]; then
    PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" \
        -f "$INSTALL_DIR/scripts/seed_baseline.sql" -v ON_ERROR_STOP=1 -q \
        && log_info "  基線 seed 載入完成（主選單、因果鍊類型等）" \
        || log_warn "  基線 seed 載入失敗（系統可能缺主選單，請手動執行 seed_baseline.sql）"
fi

# 載入 Pipeline 表結構（conversations / conversation_turns / pipeline_runs / session_logs / p2_failures）
# 這些表是 P0~P3 復盤管線 + observe 對話拓樸所需，SQL 內全為 CREATE TABLE IF NOT EXISTS，可安全重跑
if [ -f "$INSTALL_DIR/scripts/init_pipeline_tables.sql" ]; then
    PGPASSWORD="$DB_PASS" psql -U "$DB_USER" -d "$DB_NAME" -h "${DB_HOST:-127.0.0.1}" -p "${DB_PORT:-5432}" \
        -f "$INSTALL_DIR/scripts/init_pipeline_tables.sql" -v ON_ERROR_STOP=1 -q \
        && log_info "  Pipeline 表結構載入完成（conversations 等 5 張表）" \
        || log_warn "  Pipeline 表結構載入失敗（P1/P2/P3 與 observe 將無法運作）"
fi

atom_count=$(get_atom_count)
log_info "資料庫就緒 (知識原子: $atom_count)"

# 建立 Standalone 登入帳密
log_info "設定 Web UI 登入帳號..."
echo ""
echo "  請設定 BeakBroodNest Web UI 的登入帳號與密碼"
echo "  （整合 BeakPlatform 後此帳號將停用）"
echo ""

read -p "  帳號: " AUTH_USER
while [ -z "$AUTH_USER" ]; do
    echo "  帳號不可為空"
    read -p "  帳號: " AUTH_USER
done

while true; do
    read -sp "  密碼（至少 8 字元）: " AUTH_PASS
    echo ""
    if [ ${#AUTH_PASS} -lt 8 ]; then
        echo "  密碼至少 8 個字元，請重新輸入"
        continue
    fi
    read -sp "  確認密碼: " AUTH_PASS2
    echo ""
    if [ "$AUTH_PASS" != "$AUTH_PASS2" ]; then
        echo "  密碼不一致，請重新輸入"
        continue
    fi
    break
done

"$INSTALL_DIR/venv/bin/python3" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from core.db import init_engine
init_engine('$INSTALL_DIR/config.ini')
from human_ui.app import generate_auth_credentials
u, p = generate_auth_credentials('$AUTH_USER', '$AUTH_PASS')
if u:
    print('  帳號建立完成: ' + u)
else:
    print('  帳號已存在，跳過')
"


# === [7/7] systemd + Nginx ===
log_step "7/7" "設定服務..."

# systemd service
cat > "/etc/systemd/system/${SERVICE_NAME}.service" << SVCEOF
[Unit]
Description=BeakBroodNest Gunicorn Service
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=exec
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/gunicorn \
    --bind 127.0.0.1:${APP_PORT} \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile /opt/tmp/${SERVICE_NAME}-gunicorn-access.log \
    --error-logfile /opt/tmp/${SERVICE_NAME}-gunicorn-error.log \
    "human_ui.app:app"
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=30
Environment=PYTHONPATH=$INSTALL_DIR
Environment=BBN_INSTALL_DIR=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
log_info "systemd 服務已建立: ${SERVICE_NAME}.service"

# Nginx
SERVER_IP=$(ip -4 route get 8.8.8.8 2>/dev/null | awk '/src/ {print $7; exit}')
SERVER_IP="${SERVER_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"

cat > "/etc/nginx/sites-available/$SERVICE_NAME" << NGXEOF
# === BeakBroodNest 知識庫 (${SERVICE_NAME}) ===

upstream ${SERVICE_NAME} {
    server 127.0.0.1:${APP_PORT};
}

server {
    listen ${SERVER_IP}:${NGINX_PORT};

    location / {
        proxy_pass http://${SERVICE_NAME};
        proxy_http_version 1.1;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;
    }

    location /beakbroodnest/health {
        proxy_pass http://${SERVICE_NAME};
        access_log off;
    }
}
NGXEOF

ln -sf "/etc/nginx/sites-available/$SERVICE_NAME" "/etc/nginx/sites-enabled/"
nginx -t && systemctl reload nginx
log_info "Nginx 設定完成 (${SERVER_IP}:${NGINX_PORT} -> 127.0.0.1:${APP_PORT})"

# 確保 log 目錄存在
mkdir -p /opt/tmp

# === 排程任務 ===
# 偵測 INSTALL_DIR 擁有者作為 cron 執行帳號（通常是 ethan / 部署用帳號）
CRON_USER=$(stat -c '%U' "$INSTALL_DIR" 2>/dev/null)
CRON_USER="${CRON_USER:-root}"

# 已安裝過則跳過（用 BEGIN marker 或 INSTALL_DIR 偵測，後者涵蓋 marker 出現前的舊安裝）
CRON_BEGIN_MARKER="# BEGIN BeakBroodNest ${SERVICE_NAME}"
CRON_END_MARKER="# END BeakBroodNest ${SERVICE_NAME}"

if grep -qF "$CRON_BEGIN_MARKER" /etc/crontab 2>/dev/null; then
    log_info "排程任務已存在於 /etc/crontab（marker: ${SERVICE_NAME}），跳過"
elif grep -qF "$INSTALL_DIR/" /etc/crontab 2>/dev/null; then
    log_info "排程任務疑似已存在於 /etc/crontab（含 $INSTALL_DIR 路徑），跳過避免重複"
else
    # 決定是否啟用：環境變數 INSTALL_CRON > 互動詢問 > 預設 yes（非互動環境）
    if [ -n "${INSTALL_CRON:-}" ]; then
        case "$INSTALL_CRON" in yes|y|Y|true|1) ENABLE_CRON=y ;; *) ENABLE_CRON=n ;; esac
    elif [ -t 0 ]; then
        read -p "  啟用排程任務（recommended，含 P1 訊號掃描、JSONL 匯入等）(Y/n): " ENABLE_CRON
        ENABLE_CRON="${ENABLE_CRON:-y}"
    else
        ENABLE_CRON=y
    fi

    case "$ENABLE_CRON" in
        y|Y|yes)
            log_info "寫入 5 條 cron 條目到 /etc/crontab（user=${CRON_USER}）..."
            cp /etc/crontab "/etc/crontab.bak.$(date +%Y%m%d_%H%M%S)"
            cat >> /etc/crontab << CRONEOF

${CRON_BEGIN_MARKER}
# BeakBroodNest 排程任務（由 install.sh 自動產生，移除請連同 END marker 一併刪除）
* * * * * ${CRON_USER} BBN_INSTALL_DIR=${INSTALL_DIR} flock -n /tmp/${SERVICE_NAME}-monitor.lock ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/orchestrator/monitor.py --start >> /opt/tmp/${SERVICE_NAME}-orchestrator-monitor.log 2>&1
*/5 * * * * ${CRON_USER} BBN_INSTALL_DIR=${INSTALL_DIR} ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/scripts/scheduler.py --tick >> /opt/tmp/${SERVICE_NAME}-scheduler.log 2>&1
* * * * * ${CRON_USER} cd ${INSTALL_DIR} && BBN_INSTALL_DIR=${INSTALL_DIR} flock -n /tmp/${SERVICE_NAME}-embed.lock venv/bin/python scripts/embed_worker.py >> /opt/tmp/${SERVICE_NAME}-embed_worker.log 2>&1
* * * * * ${CRON_USER} BBN_INSTALL_DIR=${INSTALL_DIR} ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/scripts/session_watchdog.py --check --alert >> /opt/tmp/${SERVICE_NAME}-session_watchdog.log 2>&1
*/10 * * * * ${CRON_USER} BBN_INSTALL_DIR=${INSTALL_DIR} flock -n /tmp/${SERVICE_NAME}-db-importer.lock ${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/scripts/db_importer.py -convertall >> /opt/tmp/${SERVICE_NAME}-db_importer.log 2>&1
${CRON_END_MARKER}
CRONEOF
            log_info "  排程已寫入；下個整點開始啟動（如要立即測試：sudo bash -c 'tail -f /opt/tmp/${SERVICE_NAME}-*.log'）"
            ;;
        *)
            log_info "略過排程任務設定（要啟用請見 docs/SERVICES_AND_SCHEDULES.md）"
            ;;
    esac
fi

# === 自訂 INSTALL_DIR 時，把 .claude/settings.json 內的硬寫 hook 路徑改寫 ===
# .claude/settings.json 的 command 欄位必須是絕對路徑，Claude Code 不支援相對路徑或 env var 展開
if [ "$INSTALL_DIR" != "/opt/BeakBroodNest" ] && [ -f "$INSTALL_DIR/.claude/settings.json" ]; then
    if grep -qF '/opt/BeakBroodNest/orchestrator/hooks/' "$INSTALL_DIR/.claude/settings.json"; then
        log_info "改寫 .claude/settings.json 內的硬寫 hook 路徑為 $INSTALL_DIR"
        sed -i.bak "s|/opt/BeakBroodNest/orchestrator/hooks/|${INSTALL_DIR}/orchestrator/hooks/|g" \
            "$INSTALL_DIR/.claude/settings.json"
    fi
fi

# === 註冊/更新 /opt/.mcp.json ===
# 多實例共存時，每個實例註冊獨立的 MCP server key (beak_broodnest_<suffix>)
# 預設安裝保持 beak_broodnest 不變，向後相容
log_info "註冊 MCP server 到 /opt/.mcp.json (key=${MCP_SERVER_NAME})"
python3 - "$INSTALL_DIR" "$MCP_SERVER_NAME" <<'PYEOF'
import json
import os
import sys

install_dir, server_name = sys.argv[1], sys.argv[2]
mcp_path = '/opt/.mcp.json'
data = {'mcpServers': {}}
if os.path.isfile(mcp_path):
    try:
        with open(mcp_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('mcpServers', {})
    except Exception as e:
        print(f'[WARN] 既有 /opt/.mcp.json 無法解析（{e}），改寫為新檔', file=sys.stderr)
        data = {'mcpServers': {}}

data['mcpServers'][server_name] = {
    'type': 'stdio',
    'command': f'{install_dir}/venv/bin/python',
    'args': [f'{install_dir}/ai_kb/mcp_server.py', '--stdio'],
}

tmp = mcp_path + '.tmp'
with open(tmp, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write('\n')
os.replace(tmp, mcp_path)
print(f'[OK] /opt/.mcp.json 已更新（server: {server_name}）')
PYEOF

# === 啟動服務 ===
log_info "啟動 BeakBroodNest..."
systemctl restart "$SERVICE_NAME"
health_check || true

# 統一處理目錄擁有權
# 注意：systemd unit 與 cron 條目皆以 root 跑（service 沒 User= 欄位、cron 已從 INSTALL_DIR
# 擁有者反推），所以即使 chown 給非 root 使用者，service 仍能讀寫 config.ini（root 可讀任何檔）
if [ -n "$INSTALL_OWNER" ] && [ "$INSTALL_OWNER" != "root" ]; then
    chown -R "$INSTALL_OWNER:$INSTALL_OWNER" "$INSTALL_DIR"
    log_info "目錄擁有者已設為 $INSTALL_OWNER"
fi

echo ""
echo "============================================"
log_info "全新安裝完成"
echo ""
echo "  URL:     http://${SERVER_IP}:${NGINX_PORT}/beakbroodnest/login"
echo "  帳號:    ${AUTH_USER}"
echo "  原子數:  $(get_atom_count)"
if [ -n "$PIPELINE_DISABLED" ]; then
echo "  模式:    純白板模式（AI 對話分析停用）"
echo ""
echo "  啟用完整模式（分析 Claude Code 對話）的方法："
echo "    1. 編輯 $INSTALL_DIR/config.ini 的 [pipeline] 段"
echo "    2. 取消 'claude_projects_dir = ...' 那行的註解並填入正確路徑"
echo "    3. sudo chown -R <使用者>:<使用者> $INSTALL_DIR"
echo "    4. sudo systemctl restart $SERVICE_NAME"
else
echo "  模式:    完整模式（擁有者: $INSTALL_OWNER，pipeline 已啟用）"
fi
echo ""
echo "  服務管理:"
echo "    sudo bash $INSTALL_DIR/scripts/install.sh --status"
echo "    sudo bash $INSTALL_DIR/scripts/install.sh --update"
echo "    sudo bash $INSTALL_DIR/scripts/install.sh --start"
echo "    sudo bash $INSTALL_DIR/scripts/install.sh --stop"
echo ""
echo "  重設帳密:"
echo "    cd $INSTALL_DIR && venv/bin/python human_ui/app.py --reset-auth"
echo ""
echo "  日誌查看:"
echo "    journalctl -u $SERVICE_NAME -f"
echo "============================================"
