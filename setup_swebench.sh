#!/bin/bash
# SWE-bench 一键配置脚本(aarch64 容器环境)
# 用法: bash setup_swebench.sh

set -e
export PATH=/usr/local/bin:$PATH

# ============ 路径配置 ============
AIS_BENCH_DIR="/export/home/ext.liaopeiyi1/lpy/scripts/benchmark"
MINISWEAGENT_DIR="/export/home/ext.liaopeiyi1/lpy/swebench/mini-swe-agent"
SWEBENCH_DIR="/export/home/ext.liaopeiyi1/lpy/swebench/SWE-bench-v4.1.0"
SWEBENCH_REF="v4.1.0"
MINISWEAGENT_REF="e55c29834f65e8d0eb1e1ce56b1fda641cba568a"

# 从 run_perf.cfg 读取模型配置，保持和 run_perf.py 一致
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_PERF_CFG="$SCRIPT_DIR/run_perf.cfg"

if [ ! -f "$RUN_PERF_CFG" ]; then
    echo "ERROR: 找不到 run_perf.cfg: $RUN_PERF_CFG"
    exit 1
fi

MODEL_NAME=$(python3 -c 'import json5; c=json5.load(open("run_perf.cfg",encoding="utf-8")); print(c.get("model_cfg_params",{}).get("model",""))')
HOST_IP=$(python3 -c 'import json5; c=json5.load(open("run_perf.cfg",encoding="utf-8")); print(c.get("model_cfg_params",{}).get("host_ip",""))')
HOST_PORT=$(python3 -c 'import json5; c=json5.load(open("run_perf.cfg",encoding="utf-8")); print(c.get("model_cfg_params",{}).get("host_port",""))')
API_KEY=$(python3 -c 'import json5; c=json5.load(open("run_perf.cfg",encoding="utf-8")); print(c.get("model_cfg_params",{}).get("api_key","dummy"))')

if [ -z "$MODEL_NAME" ]; then
    echo "ERROR: run_perf.cfg 里 model_cfg_params.model 为空"
    exit 1
fi
if [ -z "$HOST_IP" ] || [ -z "$HOST_PORT" ]; then
    echo "ERROR: run_perf.cfg 里 model_cfg_params.host_ip / host_port 为空"
    exit 1
fi
API_URL="http://${HOST_IP}:${HOST_PORT}/v1"

# ============ 第 1 步:检查/安装 Docker ============
echo "=== 1. 检查 Docker ==="
NEED_DOCKER_INSTALL=0
if ! command -v docker >/dev/null 2>&1; then
    NEED_DOCKER_INSTALL=1
else
    DOCKER_API_MINOR=$(docker version --format '{{.Server.APIVersion}}' 2>/dev/null | cut -d. -f2)
    if [ -z "$DOCKER_API_MINOR" ] || [ "$DOCKER_API_MINOR" -lt 41 ]; then
        NEED_DOCKER_INSTALL=1
    fi
fi

if [ "$NEED_DOCKER_INSTALL" -eq 1 ]; then
    echo "Docker 缺失或 API < 1.41,安装静态版 Docker 24.0.9..."
    DOCKER_STATIC_VERSION=24.0.9
    DOCKER_STATIC_URL="https://mirrors.aliyun.com/docker-ce/linux/static/stable/aarch64/docker-${DOCKER_STATIC_VERSION}.tgz"
    DOCKER_TMP_DIR=$(mktemp -d)
    curl -fL --retry 3 --retry-delay 2 -o "$DOCKER_TMP_DIR/docker.tgz" "$DOCKER_STATIC_URL"
    tar -xzf "$DOCKER_TMP_DIR/docker.tgz" -C "$DOCKER_TMP_DIR"
    install -m 0755 "$DOCKER_TMP_DIR/docker/docker" /usr/local/bin/docker
    install -m 0755 "$DOCKER_TMP_DIR/docker/dockerd" /usr/local/bin/dockerd
    install -m 0755 "$DOCKER_TMP_DIR/docker/docker-proxy" /usr/local/bin/docker-proxy
    install -m 0755 "$DOCKER_TMP_DIR/docker/docker-init" /usr/local/bin/docker-init
    install -m 0755 "$DOCKER_TMP_DIR/docker/containerd" /usr/local/bin/containerd
    install -m 0755 "$DOCKER_TMP_DIR/docker/containerd-shim-runc-v2" /usr/local/bin/containerd-shim-runc-v2
    install -m 0755 "$DOCKER_TMP_DIR/docker/ctr" /usr/local/bin/ctr
    install -m 0755 "$DOCKER_TMP_DIR/docker/runc" /usr/local/bin/runc
    rm -rf "$DOCKER_TMP_DIR"
fi

echo "docker: $(command -v docker)"
echo "docker version: $(docker --version 2>&1 || echo 'NOT FOUND')"

# ============ 第 2 步:配 Docker 镜像加速 + 实验特性 ============
echo "=== 2. 配置 Docker daemon.json ==="
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me",
    "https://docker.m.daocloud.io"
  ],
  "experimental": true
}
EOF
echo "daemon.json 已写入"

# ============ 第 3 步:启动 dockerd ============
echo "=== 3. 启动 dockerd ==="
kill $(pgrep -f dockerd) 2>/dev/null || true
sleep 2

nohup /usr/local/bin/dockerd \
    --host=unix:///var/run/docker.sock \
    --iptables=false \
    --storage-driver=vfs \
    > /tmp/dockerd.log 2>&1 &
sleep 5

if ! docker info &>/dev/null; then
    echo "ERROR: dockerd 启动失败,查看 /tmp/dockerd.log"
    tail -20 /tmp/dockerd.log
    exit 1
fi

echo "Experimental: $(docker info 2>&1 | grep -i 'experimental' || echo 'NOT SET')"
echo "Registry Mirrors: $(docker info 2>&1 | grep -A3 'Registry Mirrors' || echo 'NOT SET')"

# ============ 第 4 步:装 binfmt(aarch64 跑 x86 镜像) ============
echo "=== 4. 安装 binfmt (x86 emulation) ==="
docker run --privileged --rm docker.1ms.run/tonistiigi/binfmt --install amd64
echo "binfmt 安装完成"

echo "验证 x86 emulation..."
docker pull --platform=linux/amd64 docker.1ms.run/library/alpine:latest 2>/dev/null
RESULT=$(docker run --rm --platform=linux/amd64 docker.1ms.run/library/alpine uname -m 2>/dev/null)
if [ "$RESULT" = "x86_64" ]; then
    echo "✅ x86 emulation 正常 (返回 x86_64)"
else
    echo "⚠️  x86 emulation 可能有问题 (返回: $RESULT)"
fi

# ============ 第 5 步:装 Python 依赖 ============
echo "=== 5. 安装 Python 依赖 ==="

pip config set global.index-url https://repo.huaweicloud.com/repository/pypi/simple 2>/dev/null || true

# ais_bench(项目根是 benchmark/ 目录)
if [ -f "$AIS_BENCH_DIR/setup.py" ] || [ -f "$AIS_BENCH_DIR/pyproject.toml" ]; then
    echo "安装 ais_bench..."
    cd "$AIS_BENCH_DIR"
    pip install -e .
else
    echo "⚠️  AIS_BENCH_DIR ($AIS_BENCH_DIR) 没有 setup.py/pyproject.toml,跳过"
fi

# mini-swe-agent
if [ ! -d "$MINISWEAGENT_DIR" ]; then
    echo "克隆 mini-swe-agent..."
    MINISWE_PARENT=$(dirname "$MINISWEAGENT_DIR")
    mkdir -p "$MINISWE_PARENT"
    git clone https://gh-proxy.com/github.com/AISBench/mini-swe-agent.git "$MINISWEAGENT_DIR"
fi
cd "$MINISWEAGENT_DIR"
git checkout -f "$MINISWEAGENT_REF"
if [ -f "$MINISWEAGENT_DIR/setup.py" ] || [ -f "$MINISWEAGENT_DIR/pyproject.toml" ]; then
    echo "安装 mini-swe-agent..."
    cd "$MINISWEAGENT_DIR"
    pip install -e .
else
    echo "⚠️  MINISWEAGENT_DIR ($MINISWEAGENT_DIR) 没有 setup.py/pyproject.toml,跳过"
fi

# SWE-bench harness
if [ ! -d "$SWEBENCH_DIR" ]; then
    echo "克隆 SWE-bench ${SWEBENCH_REF}..."
    SWEBENCH_PARENT=$(dirname "$SWEBENCH_DIR")
    mkdir -p "$SWEBENCH_PARENT"
    cd "$SWEBENCH_PARENT"
    git clone --branch "$SWEBENCH_REF" --depth 1 https://gh-proxy.com/https://github.com/SWE-bench/SWE-bench.git "$SWEBENCH_DIR"
else
    cd "$SWEBENCH_DIR"
    git checkout -f "$SWEBENCH_REF"
fi
if [ -f "$SWEBENCH_DIR/setup.py" ] || [ -f "$SWEBENCH_DIR/pyproject.toml" ]; then
    echo "安装 SWE-bench harness..."
    cd "$SWEBENCH_DIR"
    pip install -e .
else
    echo "⚠️  SWEBENCH_DIR ($SWEBENCH_DIR) 没有 setup.py/pyproject.toml,跳过"
fi

# ============ 第 6 步:Patch 源码 ============
echo "=== 6. Patch 源码 ==="

# Patch 1: mini-swe-agent 镜像源 (docker.io → docker.1ms.run)
SWEBENCH_PY="$MINISWEAGENT_DIR/src/minisweagent/run/benchmarks/swebench.py"
if [ -f "$SWEBENCH_PY" ]; then
    sed -i 's|docker.io/swebench/sweb.eval|docker.1ms.run/swebench/sweb.eval|' "$SWEBENCH_PY"
    echo "✅ Patch 1: mini-swe-agent 镜像源已改"
    grep 'docker.1ms.run/swebench' "$SWEBENCH_PY" | head -1
else
    echo "⚠️  Patch 1: $SWEBENCH_PY 不存在"
fi

# Patch 2: ais_bench docker pull 加 --platform=linux/amd64
# 注意: utils.py 在 ais_bench/benchmark/tasks/swebench/ 下,不是 benchmark/tasks/swebench/
UTILS_PY="$AIS_BENCH_DIR/ais_bench/benchmark/tasks/swebench/utils.py"
if [ -f "$UTILS_PY" ]; then
    sed -i 's|subprocess.run(\["docker", "pull", image\])|subprocess.run(["docker", "pull", "--platform=linux/amd64", image])|' "$UTILS_PY"
    echo "✅ Patch 2: ais_bench docker pull 已加 --platform"
    grep 'platform=linux/amd64' "$UTILS_PY" | head -1
else
    echo "⚠️  Patch 2: $UTILS_PY 不存在,尝试 find..."
    FOUND=$(find "$AIS_BENCH_DIR" -name 'utils.py' -path '*swebench*' -not -path '*__pycache__*' 2>/dev/null | head -1)
    if [ -n "$FOUND" ] && [ -f "$FOUND" ]; then
        sed -i 's|subprocess.run(\["docker", "pull", image\])|subprocess.run(["docker", "pull", "--platform=linux/amd64", image])|' "$FOUND"
        echo "✅ Patch 2: $FOUND 已改"
        grep 'platform=linux/amd64' "$FOUND" | head -1
    else
        echo "❌ Patch 2: 找不到 utils.py"
    fi
fi

# Patch 3: swebench harness GitHub raw 镜像
# 不同版本 URL 定义在不同文件,全部 patch
PATCH3_DONE=false
# 3a: constants/__init__.py 里的 SWE_BENCH_URL_RAW 常量
CONST_FILE="$SWEBENCH_DIR/swebench/harness/constants/__init__.py"
if [ -f "$CONST_FILE" ]; then
    sed -i 's|SWE_BENCH_URL_RAW = "https://raw.githubusercontent.com/"|SWE_BENCH_URL_RAW = "https://gh-proxy.com/https://raw.githubusercontent.com/"|' "$CONST_FILE"
    if grep -q 'gh-proxy.com' "$CONST_FILE"; then
        echo "✅ Patch 3a: constants SWE_BENCH_URL_RAW 已改"
        PATCH3_DONE=true
    fi
fi
# 3b: utils.py 里的 url 拼接(旧版本)
HARNESS_UTILS=$(find "$SWEBENCH_DIR" -name 'utils.py' -path '*harness*' -not -path '*__pycache__*' 2>/dev/null | head -1)
if [ -n "$HARNESS_UTILS" ] && [ -f "$HARNESS_UTILS" ]; then
    sed -i 's|url = f"https://raw.githubusercontent.com/{repo}/{commit}/{filepath}"|url = f"https://gh-proxy.com/https://raw.githubusercontent.com/{repo}/{commit}/{filepath}"|' "$HARNESS_UTILS" 2>/dev/null
    if grep -q 'gh-proxy.com' "$HARNESS_UTILS" 2>/dev/null; then
        echo "✅ Patch 3b: harness/utils.py GitHub raw 镜像已改"
        PATCH3_DONE=true
    fi
fi
# 3c: site-packages 里安装的版本
SITE_PKG_UTILS=$(python3 -c "import swebench; import os; print(os.path.join(os.path.dirname(swebench.__file__), 'harness', 'utils.py'))" 2>/dev/null)
if [ -n "$SITE_PKG_UTILS" ] && [ -f "$SITE_PKG_UTILS" ]; then
    sed -i 's|url = f"https://raw.githubusercontent.com/{repo}/{commit}/{filepath}"|url = f"https://gh-proxy.com/https://raw.githubusercontent.com/{repo}/{commit}/{filepath}"|' "$SITE_PKG_UTILS" 2>/dev/null
    SITE_CONST=$(python3 -c "import swebench; import os; print(os.path.join(os.path.dirname(swebench.__file__), 'harness', 'constants', '__init__.py'))" 2>/dev/null)
    if [ -n "$SITE_CONST" ] && [ -f "$SITE_CONST" ]; then
        sed -i 's|SWE_BENCH_URL_RAW = "https://raw.githubusercontent.com/"|SWE_BENCH_URL_RAW = "https://gh-proxy.com/https://raw.githubusercontent.com/"|' "$SITE_CONST" 2>/dev/null
    fi
    echo "✅ Patch 3c: site-packages swebench 已改"
    PATCH3_DONE=true
fi
if [ "$PATCH3_DONE" = false ]; then
    echo "⚠️  Patch 3: 未找到需要改的 GitHub raw URL"
fi

# ============ 第 7 步:配模型 ============
echo "=== 7. 配置模型 ==="
CONFIG_FILE="$AIS_BENCH_DIR/ais_bench/configs/swe_bench_examples/mini_swe_agent_swe_bench_lite.py"
if [ -f "$CONFIG_FILE" ]; then
    cp "$CONFIG_FILE" "${CONFIG_FILE}.bak"
    sed -i "s|model=\".*\"|model=\"$MODEL_NAME\"|" "$CONFIG_FILE"
    sed -i "s|url=\".*\"|url=\"$API_URL\"|" "$CONFIG_FILE"
    sed -i "s|api_key=\".*\"|api_key=\"$API_KEY\"|" "$CONFIG_FILE"
    echo "✅ 模型配置已更新:"
    grep -E 'model=|url=|api_key=' "$CONFIG_FILE" | head -5
else
    echo "⚠️  配置文件 $CONFIG_FILE 不存在"
fi

# ============ 第 8 步:数据集缓存 ============
echo "=== 8. 检查数据集缓存 ==="
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
python3 -c "import datasets" >/dev/null 2>&1 || pip install datasets
python3 - <<'PY'
from datasets import load_dataset
ds = load_dataset("princeton-nlp/SWE-Bench_Lite", split="test")
print("✅ SWE-bench Lite 数据集就绪, rows:", len(ds))
PY

# ============ 完成 ============
echo ""
echo "========================================"
echo "✅ 配置完成!"
echo "========================================"
echo ""
echo "验证命令:"
echo "  docker info 2>&1 | grep -iE 'experimental|registry'"
echo "  docker run --rm --platform=linux/amd64 docker.1ms.run/library/alpine uname -m"
echo "  curl -sS $API_URL/models | head -5"
echo ""
echo "开始测试:"
echo "  cd $AIS_BENCH_DIR"
echo "  ais_bench configs/swe_bench_examples/mini_swe_agent_swe_bench_lite.py -m infer"
echo ""
echo "断点续跑:"
echo "  ais_bench configs/swe_bench_examples/mini_swe_agent_swe_bench_lite.py -m infer --reuse"
echo ""
echo "结果在: outputs/default/<timestamp>/"
