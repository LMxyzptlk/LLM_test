#!/bin/bash
# xllm 自动拉取最新代码并编译脚本
# 用法: bash build_xllm.sh [branch]
# 定时任务: crontab -e 添加 0 5 * * * bash /export/home/ext.liaopeiyi1/lpy/build_xllm.sh >> /export/home/ext.liaopeiyi1/lpy/build_cron.log 2>&1

set -e

BRANCH="${1:-release/v0.11.0}"
XLLM_DIR="/export/home/ext.liaopeiyi1/lpy/xllm"
LOCK_FILE="/tmp/build_xllm.lock"
CRON_LOG="/export/home/ext.liaopeiyi1/lpy/build_cron.log"

# 防重入：已有编译在跑则跳过
if [ -f "$LOCK_FILE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已有编译进程运行中, 跳过本次定时任务"
    exit 0
fi
trap "rm -f $LOCK_FILE" EXIT
touch "$LOCK_FILE"

echo "========================================="
echo " xllm 自动编译脚本"
echo " 分支: $BRANCH"
echo " 目标: $XLLM_DIR"
echo " 时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="

cd "$XLLM_DIR"

echo "[1/4] git fetch..."
git fetch origin

echo "[2/4] git checkout + pull $BRANCH ..."
git checkout "$BRANCH"
git pull origin "$BRANCH"

echo "[3/4] git submodule update..."
git submodule update --init --recursive

echo "[4/4] 开始编译 (后台运行)..."
nohup python3 setup.py build --enable-ha true > build.log 2>&1 &
BUILD_PID=$!
echo "编译进程 PID: $BUILD_PID"
echo "日志文件: $XLLM_DIR/build.log"
echo ""
echo "监控编译进度: tail -f $XLLM_DIR/build.log"
echo "检查是否完成: ps -p $BUILD_PID"
echo "========================================="
echo " 启动完成, 编译在后台运行中"
echo "========================================="