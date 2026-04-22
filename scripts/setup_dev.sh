#!/bin/bash
# =============================================================================
# BeakCortex 開發環境設定
# 在 /opt/BeakCortex-dev/ 建立獨立的開發環境
# =============================================================================
# 用法:
#   bash setup_dev.sh               初始化開發環境
#   bash setup_dev.sh --reset-db    重建開發資料庫（清除所有資料）
#   bash setup_dev.sh --run         啟動 Flask dev server
#   bash setup_dev.sh --stop        停止 Flask dev server
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEV_DIR="$(dirname "$SCRIPT_DIR")"
DB_NAME="beak_cortex_dev"
DB_USER="beak_cortex"
DB_PASS="postgres123"
DEV_PORT=5175

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[$1]${NC} $2"; }

# === 參數處理 ===
ACTION="setup"

case "${1:-}" in
    --reset-db)  ACTION="reset_db" ;;
    --run)       ACTION="run" ;;
    --stop)      ACTION="stop" ;;
    "")          ACTION="setup" ;;
    *)
        echo "BeakCortex 開發環境設定"
        echo ""
        echo "用法:"
        echo "  bash setup_dev.sh               初始化開發環境"
        echo "  bash setup_dev.sh --reset-db    重建開發資料庫"
        echo "  bash setup_dev.sh --run         啟動 Flask dev server"
        echo "  bash setup_dev.sh --stop        停止 Flask dev server"
        exit 1
        ;;
esac


# =========================================================================
#  --run
# =========================================================================
if [ "$ACTION" = "run" ]; then
    if [ ! -d "$DEV_DIR/venv" ]; then
        log_error "venv 不存在，請先執行: bash setup_dev.sh"
        exit 1
    fi
    log_info "啟動 Flask dev server (port $DEV_PORT)..."
    cd "$DEV_DIR"
    source venv/bin/activate
    python human_ui/app.py --serve --port "$DEV_PORT" --host 192.168.0.16
    exit 0
fi


# =========================================================================
#  --stop
# =========================================================================
if [ "$ACTION" = "stop" ]; then
    PID=$(lsof -ti ":$DEV_PORT" 2>/dev/null || true)
    if [ -n "$PID" ]; then
        kill "$PID"
        log_info "已停止 dev server (PID: $PID)"
    else
        log_info "dev server 未在運行"
    fi
    exit 0
fi


# =========================================================================
#  --reset-db
# =========================================================================
if [ "$ACTION" = "reset_db" ]; then
    echo "=== 重建開發資料庫 ==="
    log_warn "這將刪除 $DB_NAME 中的所有資料!"
    read -p "確定要繼續？(y/N) " confirm
    if [[ ! "$confirm" =~ ^[yY]$ ]]; then
        echo "取消"
        exit 0
    fi

    sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB_NAME' AND pid <> pg_backend_pid();" > /dev/null 2>&1 || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS $DB_NAME;"
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    log_info "資料庫 $DB_NAME 已重建"

    # 建表
    cd "$DEV_DIR"
    source venv/bin/activate
    python -c "
import sys
sys.path.insert(0, '.')
from core.db import init_engine, create_all_tables
init_engine('config.ini')
create_all_tables()
print('  資料表建立完成')
"
    log_info "開發資料庫就緒"
    exit 0
fi


# =========================================================================
#  初始化開發環境
# =========================================================================
echo "============================================"
echo "  BeakCortex 開發環境設定"
echo "============================================"
echo ""
echo "  開發目錄: $DEV_DIR"
echo "  資料庫:   $DB_NAME"
echo "  Port:     $DEV_PORT (Flask dev server)"
echo ""

# [1] Python venv
log_step "1/3" "建立 Python 虛擬環境..."

if [ -d "$DEV_DIR/venv" ]; then
    log_info "venv 已存在，更新依賴"
else
    python3 -m venv "$DEV_DIR/venv"
    log_info "venv 已建立"
fi

source "$DEV_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$DEV_DIR/requirements.txt" -q
log_info "Python 依賴已安裝"


# [2] config.ini
log_step "2/3" "設定組態檔..."

if [ -f "$DEV_DIR/config.ini" ]; then
    log_info "config.ini 已存在，保留現有設定"
else
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    RELAY_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(16))")

    cat > "$DEV_DIR/config.ini" << CFGEOF
# BeakCortex 開發環境組態
# 指向 beak_cortex_dev 資料庫，與生產環境完全隔離

[postgresql]
host = localhost
port = 5432
database = $DB_NAME
username = $DB_USER
password = $DB_PASS

[flask]
host = 192.168.0.16
port = $DEV_PORT
debug = true
secret_key = $SECRET_KEY

[relay]
host = 127.0.0.1
port = 5200
token = $RELAY_TOKEN

[logging]
level = DEBUG
CFGEOF

    log_info "config.ini 已建立 (指向 $DB_NAME)"
fi


# [3] 資料庫
log_step "3/3" "確認開發資料庫..."

# 確保 DB user 存在
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true

# 確保 DB 存在
if sudo -u postgres psql -lqt | cut -d'|' -f1 | grep -qw "$DB_NAME"; then
    log_info "資料庫 $DB_NAME 已存在"
else
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
    log_info "資料庫 $DB_NAME 已建立"
fi

# 確保 owner 正確
sudo -u postgres psql -c "ALTER DATABASE $DB_NAME OWNER TO $DB_USER;" 2>/dev/null || true

# 建表（冪等）
cd "$DEV_DIR"
python -c "
import sys
sys.path.insert(0, '.')
from core.db import init_engine, create_all_tables
init_engine('config.ini')
create_all_tables()
print('  資料表就緒')
"

atom_count=$(sudo -u postgres psql -d "$DB_NAME" -t -c "SELECT count(*) FROM knowledge_atoms;" 2>/dev/null | tr -d ' \n' || echo "0")

echo ""
echo "============================================"
log_info "開發環境就緒"
echo ""
echo "  知識原子: $atom_count (開發資料庫)"
echo ""
echo "  啟動 dev server:"
echo "    bash scripts/setup_dev.sh --run"
echo "    或"
echo "    source venv/bin/activate"
echo "    python human_ui/app.py --serve --port $DEV_PORT"
echo ""
echo "  開發環境 URL: http://192.168.0.16:$DEV_PORT"
echo "  生產環境 URL: http://192.168.0.16:5170"
echo "============================================"
