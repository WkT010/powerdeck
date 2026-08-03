#!/usr/bin/env bash
# ============================================================
#  多链私钥扫描器 - Ubuntu 一键安装脚本
#  用法:  bash install.sh
#  可选环境变量:
#    PORT=8080              web 查看器端口
#    SCAN_INTERVAL=0.3      扫描间隔秒数
#    ALCHEMY_API_KEY=xxx    启用 Alchemy 全量代币扫描
# ============================================================
set -e

# ---------- 颜色 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

# ---------- 变量 ----------
INSTALL_DIR="${INSTALL_DIR:-$HOME/eth-scanner}"
PORT="${PORT:-8080}"
SCAN_INTERVAL="${SCAN_INTERVAL:-0.3}"

info "多链私钥扫描器 - Ubuntu 一键安装"
info "安装目录: $INSTALL_DIR"
info "Web 端口: $PORT  扫描间隔: ${SCAN_INTERVAL}s"
echo ""

# ---------- 1. 检测系统 ----------
if [ "$(uname -s)" != "Linux" ]; then
    warn "当前系统非 Linux，本脚本面向 Ubuntu。继续可能出错。"
fi
if ! grep -iq ubuntu /etc/os-release 2>/dev/null; then
    warn "未检测到 Ubuntu，但只要是 Debian 系通常也可用。"
fi

# ---------- 2. 安装系统依赖 ----------
info "检查并安装系统依赖（python3 python3-pip curl）..."
sudo apt-get update -qq 2>/dev/null || warn "apt update 失败（可能无 sudo 或网络问题）"
sudo apt-get install -y -qq python3 python3-pip curl 2>/dev/null || {
    warn "sudo 安装失败，尝试不带 sudo..."
    apt-get install -y -qq python3 python3-pip curl 2>/dev/null || warn "系统依赖安装失败，假设已存在"
}
ok "系统依赖检查完成"

# ---------- 3. 创建安装目录 ----------
mkdir -p "$INSTALL_DIR/output"
cd "$INSTALL_DIR"

# ---------- 4. 复制服务文件 ----------
# 脚本假设与 install.sh 同目录有服务文件；若不存在则从当前目录拷贝
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
info "复制服务文件到 $INSTALL_DIR ..."

copy_file() {
    local src="$SCRIPT_DIR/$1"
    if [ -f "$src" ]; then
        cp -f "$src" "$INSTALL_DIR/$1"
        ok "  $1"
    else
        warn "  $1 源文件不存在，跳过"
    fi
}

copy_file scanner.py
copy_file web_log_viewer.py
copy_file run.sh
copy_file start_viewer.sh
copy_file requirements.txt

# 若服务文件不存在（用户只下载了 install.sh），从同目录再找一次
if [ ! -f "$INSTALL_DIR/scanner.py" ]; then
    fail "找不到 scanner.py，请把 install.sh 与服务文件放在同一目录后重试。"
fi

chmod +x run.sh start_viewer.sh 2>/dev/null || true
ok "服务文件就位"

# ---------- 5. 安装 Python 依赖 ----------
info "安装 Python 依赖..."
pip3 install -q -r requirements.txt 2>&1 | tail -5 || {
    warn "pip 安装失败，尝试 --user"
    pip3 install --user -q -r requirements.txt 2>&1 | tail -5 || fail "Python 依赖安装失败"
}
ok "Python 依赖就绪"

# ---------- 6. 启动 scanner ----------
info "启动 scanner..."
SCAN_INTERVAL="$SCAN_INTERVAL" bash run.sh
sleep 6

if ps -p "$(cat .scanner.pid 2>/dev/null)" > /dev/null 2>&1; then
    ok "scanner 已启动, PID=$(cat .scanner.pid)"
else
    warn "scanner 启动可能失败，查看 output/scanner.log"
fi

# ---------- 7. 启动 viewer ----------
info "启动 web 查看器 (端口 $PORT)..."
PORT="$PORT" bash start_viewer.sh
sleep 2

if ps -p "$(cat .viewer.pid 2>/dev/null)" > /dev/null 2>&1; then
    ok "viewer 已启动, PID=$(cat .viewer.pid)"
else
    warn "viewer 启动可能失败，查看 output/viewer.log"
fi

# ---------- 8. 验证 HTTP ----------
info "验证 web 查看器..."
if command -v curl > /dev/null; then
    HTTP_CODE=$(curl -s -m 5 -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        ok "Web 查看器响应正常 (HTTP 200)"
    else
        warn "Web 查看器响应码: $HTTP_CODE（可能还在启动中）"
    fi
fi

# ---------- 9. 完成 ----------
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  安装完成！${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  安装目录:  $INSTALL_DIR"
echo "  Scanner:   $( [ -f .scanner.pid ] && echo "运行中 PID=$(cat .scanner.pid)" || echo "未运行" )"
echo "  Viewer:    $( [ -f .viewer.pid ] && echo "运行中 PID=$(cat .viewer.pid)" || echo "未运行" )"
echo ""
echo "  访问地址:  http://localhost:$PORT/"
if [ -n "$ALCHEMY_API_KEY" ]; then
    echo "  Alchemy:   已启用全量代币扫描"
else
    echo "  Alchemy:   未启用（可选 export ALCHEMY_API_KEY=xxx 增强）"
fi
echo ""
echo "  常用命令:"
echo "    cd $INSTALL_DIR"
echo "    bash run.sh            # 重启 scanner"
echo "    bash start_viewer.sh   # 重启 viewer"
echo "    tail -f output/scanner.log   # 看扫描日志"
echo ""
echo -e "${YELLOW}  注意: 私钥空间 2^256，碰撞概率≈0，仅供学习/演示。${NC}"
