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
#   DB_PASS                資料庫密碼 (預設: postgres123)
#   BEAKBROODNEST_PORT            外部存取 port (預設: 5170)
#   GITHUB_TOKEN           GitHub Personal Access Token (私有 repo 時需要)
#   GITHUB_REPO            GitHub clone URL (預設: ethan-beakmask/BeakBroodNest)
# =============================================================================
set -e

# === 設定 ===
INSTALL_DIR="${INSTALL_DIR:-/opt/BeakBroodNest}"
DB_NAME="${DB_NAME:-beak_broodnest}"
DB_USER="${DB_USER:-beak_broodnest}"
DB_PASS="${DB_PASS:-postgres123}"
BEAKBROODNEST_PORT="${BEAKBROODNEST_PORT:-5170}"
GITHUB_REPO="${GITHUB_REPO:-https://github.com/ethan-beakmask/BeakBroodNest.git}"
SERVICE_NAME="beakbroodnest"
HEALTH_TIMEOUT=30

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
        echo "  用法: sudo bash $0 $*"
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

    # [1] 拉取最新程式碼
    log_step "1/3" "拉取最新程式碼..."

    git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true

    # 檢查 remote URL 是否帶有 token
    current_url=$(git remote get-url origin 2>/dev/null)
    if ! echo "$current_url" | grep -q '@github.com'; then
        if [ -z "${GITHUB_TOKEN:-}" ]; then
            read -s -p "請輸入 GitHub Personal Access Token: " GITHUB_TOKEN
            echo ""
            if [ -z "$GITHUB_TOKEN" ]; then
                log_error "未輸入 Token，無法繼續"
                exit 1
            fi
        fi
        # 從 GITHUB_REPO 提取 user/repo 路徑
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

    # [2] 更新 Python 依賴
    log_step "2/3" "更新 Python 依賴..."
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q

    # [3] 重啟服務
    log_step "3/3" "重啟服務..."
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


# === [4/7] Python 虛擬環境 ===
log_step "4/7" "建立 Python 虛擬環境..."

if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip -q
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" -q
log_info "Python 環境就緒"


# === [5/7] 組態檔 ===
log_step "5/7" "設定組態檔..."

if [ -f "$INSTALL_DIR/config.ini" ]; then
    log_info "config.ini 已存在，保留現有設定"
else
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    RELAY_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")

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
init_engine('$INSTALL_DIR/config.ini')
create_all_tables()
print('  資料表建立完成')
"

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
    --access-logfile /opt/tmp/beakbroodnest-gunicorn-access.log \
    --error-logfile /opt/tmp/beakbroodnest-gunicorn-error.log \
    "human_ui.app:app"
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=30
Environment=PYTHONPATH=$INSTALL_DIR

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
# === BeakBroodNest 知識庫 ===

upstream beakbroodnest {
    server 127.0.0.1:${APP_PORT};
}

server {
    listen ${SERVER_IP}:${NGINX_PORT};

    location / {
        proxy_pass http://beakbroodnest;
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
        proxy_pass http://beakbroodnest;
        access_log off;
    }
}
NGXEOF

ln -sf "/etc/nginx/sites-available/$SERVICE_NAME" "/etc/nginx/sites-enabled/"
nginx -t && systemctl reload nginx
log_info "Nginx 設定完成 (${SERVER_IP}:${NGINX_PORT} -> 127.0.0.1:${APP_PORT})"

# 確保 log 目錄存在
mkdir -p /opt/tmp

# === 啟動服務 ===
log_info "啟動 BeakBroodNest..."
systemctl restart "$SERVICE_NAME"
health_check || true

echo ""
echo "============================================"
log_info "全新安裝完成"
echo ""
echo "  URL:     http://${SERVER_IP}:${NGINX_PORT}/beakbroodnest/login"
echo "  帳號:    ${AUTH_USER}"
echo "  原子數:  $(get_atom_count)"
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
