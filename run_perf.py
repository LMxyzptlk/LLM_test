#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ais_bench 自动性能测试脚本 (JSON 用例驱动)

用法:
    # performance 模式: 用 JSON 用例文件驱动, 支持多数据集类型/输入长度/输出长度/并发/request_rate/pfx 组合
    python3 run_perf.py --cases cases.json

    # agent 模式: 跑原生 SWE-bench, 支持 lite / verified / full / multilingual
    python3 run_perf.py --mode agent --agent-dataset lite --agent-count 10

    # performance 简易模式: 直接命令行指定 (向后兼容)
    python3 run_perf.py -i 32768 -c 1 8 16 --max-out-len 1024 --request-rate 0.5
    python3 run_perf.py -i 32768 -c 1 8 16 --dataset-type gsm sharegpt  # 多数据集类型
    python3 run_perf.py -i 32768 -c 1 8 16 --skip-run       # 只解析已有输出

JSON 用例文件格式 (序号->用例串 映射):
    {
      "1": "32768-1024-4-0.5",           # 默认 sharegpt
      "2": "gsm:32768-1024-4-0.5",       # gsm 数据集
      "3": "sharegpt:16384-1024-8-0-90", # sharegpt + pfx 前缀缓存
      "4": "swebench:16384-1024-16-1"    # swebench 数据集
    }
    也兼容列表形式: ["32768-1024-4-0.5", "gsm:32768-1024-4-0.5"]
    也兼容对象形式: {"in": 32768, "out": 1024, "concurrency": 4, "rate": 0.5, "dataset_type": "gsm"}

用例串格式:  [dataset_type:]输入长度-输出长度-并发-request_rate[-pfx]
  - dataset_type: 可选, gsm/sharegpt/swebench, 省略默认 sharegpt
  - 输入长度:    数据集名里的 in{LEN}
  - 输出长度:    写入 vllm_api_general_stream.py 的 max_out_len
  - 并发:       即 batch_size; 数据集条数 bs = 并发 * 4
  - request_rate: 写入 vllm_api_general_stream.py 的 request_rate (0=尽量打满)
  - pfx (可选): 前缀缓存重复率%, 指定则用 {数据集}-in{LEN}-bs{BS}-pfx{N}.jsonl
                省略或 0 则用普通数据集 {数据集}-in{LEN}-bs{BS}.jsonl
  序号由 JSON 的 key 提供, 仅用于排序/标识。

不带 --cases 时走简易模式: 直接改本文件顶部的 INPUT_LEN/DATASET_TYPES/CONCURRENCIES 等,
输出长度/请求速率/pfx 用命令行 --max-out-len --request-rate --pfx --dataset-type 覆盖。

数据集 jsonl 在脚本所在文件夹下查找。若找不到, 自动调用 process_dataset.py 生成。
启动前会自动检查 ais_bench benchmark 和本次用到的原始数据集；缺失时自动下载/安装，已存在则跳过。
输出(request_rate/max_out_len/path/model/host_ip/host_port)写入 vllm_api_general_stream.py。
最终所有用例结果按 (数据集类型, 输入长度, pfx) 分组写 excel, 保存在执行时的当前文件夹下。
"""

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time
import shutil
import zipfile

import openpyxl
from openpyxl.styles import Font, Alignment

# ============================================================
#  配置文件加载 (run_perf.cfg)
#  所有可修改的参数放在同目录下的 run_perf.cfg 中，不再改脚本本身。
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(SCRIPT_DIR, "run_perf.cfg")

_DEFAULT_CFG = {
    "mode": "performance",
    "agent_dataset": "lite",
    "agent_count": 1,
    "agent_step_limit": 200,
    "agent_work_dir": "outputs/agent",
    "input_len": [32768],
    "concurrencies": [1, 8, 16],
    "default_max_out_len": None,
    "default_request_rate": None,
    "default_pfx": None,
    "model_cfg_params": {},
    "dataset_types": ["sharegpt"],
    "raw_gsm_path": "",
    "raw_sharegpt_path": "",
    "raw_swebench_path": "",

    # v1.0.3: 启动前自动准备 benchmark 和原始数据集
    "auto_prepare": True,
    "benchmark_repo": "https://gh-proxy.com/https://github.com/AISBench/benchmark.git",
    "benchmark_dir": "",
    "benchmark_ref": "",
    "install_requirements": True,
    "raw_dataset_dir": "raw_datasets",
    "gsm8k_url": "http://opencompass.oss-cn-shanghai.aliyuncs.com/datasets/data/gsm8k.zip",
    "sharegpt_url": "https://hf-mirror.com/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json",
    "swebench_url": "https://hf-mirror.com/datasets/princeton-nlp/SWE-bench/resolve/main/data/test-00000-of-00001.parquet",
}


def _load_cfg():
    """从 run_perf.cfg 加载配置，合并默认值。"""
    if os.path.exists(CFG_PATH):
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}
    merged = dict(_DEFAULT_CFG)
    for k, v in cfg.items():
        if k in merged:
            merged[k] = v
    return merged


_cfg = _load_cfg()

RUN_MODE = _cfg.get("mode", "performance")
AGENT_DATASET = _cfg.get("agent_dataset", "lite")
AGENT_COUNT = int(_cfg.get("agent_count", 1))
AGENT_STEP_LIMIT = int(_cfg.get("agent_step_limit", 200))
AGENT_WORK_DIR = _cfg.get("agent_work_dir", "outputs/agent")

INPUT_LEN = _cfg["input_len"]
CONCURRENCIES = _cfg["concurrencies"]
DEFAULT_MAX_OUT_LEN = _cfg["default_max_out_len"]
DEFAULT_REQUEST_RATE = _cfg["default_request_rate"]
DEFAULT_PFX = _cfg["default_pfx"]

# 模型配置 (对应 vllm_api_general_stream.py 里的字段)
# path 同时作为 tokenizer 模型路径，不再单独设 MODEL_PATH
MODEL_CFG_PARAMS = dict(_cfg["model_cfg_params"])

# 数据集生成配置
DATASET_TYPES = _cfg["dataset_types"]

# v1.0.3: 自动准备配置
AUTO_PREPARE = bool(_cfg.get("auto_prepare", True))
BENCHMARK_REPO = _cfg.get("benchmark_repo", "")
BENCHMARK_REF = _cfg.get("benchmark_ref", "")
INSTALL_REQUIREMENTS = bool(_cfg.get("install_requirements", True))
RAW_DATASET_DIR = os.path.join(
    SCRIPT_DIR,
    _cfg.get("raw_dataset_dir", "raw_datasets"),
)
GSM8K_URL = _cfg.get("gsm8k_url", "")
SHAREGPT_URL = _cfg.get("sharegpt_url", "")
SWEBENCH_URL = _cfg.get("swebench_url", "")

_BENCHMARK_DIR_CFG = _cfg.get("benchmark_dir", "")
BENCHMARK_DIR = (
    os.path.abspath(_BENCHMARK_DIR_CFG)
    if os.path.isabs(_BENCHMARK_DIR_CFG)
    else os.path.join(SCRIPT_DIR, _BENCHMARK_DIR_CFG)
) if _BENCHMARK_DIR_CFG else os.path.join(SCRIPT_DIR, "benchmark")

# 原始数据集路径：相对路径以脚本所在目录为基准解析；未配置时落到 raw_datasets/
def _resolve_raw_path(value, default_name):
    if value:
        return value if os.path.isabs(value) else os.path.join(SCRIPT_DIR, value)
    return os.path.join(RAW_DATASET_DIR, default_name)

RAW_GSM_PATH = _resolve_raw_path(
    _cfg.get("raw_gsm_path", ""),
    os.path.join("gsm8k", "train.jsonl"),
)
RAW_SHAREGPT_PATH = _resolve_raw_path(
    _cfg.get("raw_sharegpt_path", ""),
    "ShareGPT_V3_unfiltered_cleaned_split.json",
)
RAW_SWEBENCH_PATH = _resolve_raw_path(
    _cfg.get("raw_swebench_path", ""),
    os.path.join("swe-bench", "test-00000-of-00001.parquet"),
)


def _run_checked(cmd, cwd=None, label=""):
    """执行外部命令，失败时抛 RuntimeError。"""
    print("  [exec] {}".format(" ".join(map(str, cmd))))
    proc = subprocess.run(cmd, cwd=cwd, text=True)
    if proc.returncode != 0:
        raise RuntimeError("{} 退出码 {}: {}".format(label or "命令", proc.returncode, " ".join(map(str, cmd))))
    return proc


def _download_file(url, dest):
    """下载文件到 dest；已存在且非空则跳过。优先 wget 断点续传。"""
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print("  [dl ] 已存在: {}".format(dest))
        return dest
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".part"
    print("  [dl ] {} -> {}".format(url, dest))
    if shutil.which("wget"):
        cmd = ["wget", "-c", url, "-O", tmp]
    else:
        cmd = ["curl", "-fL", "--retry", "3", "--retry-delay", "2", url, "-o", tmp]
    proc = subprocess.run(cmd, text=True)
    if proc.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        raise RuntimeError("下载失败: {} -> {}".format(url, dest))
    os.replace(tmp, dest)
    return dest


def _ensure_raw_file(path, url, label):
    """确保单个原始数据文件存在；不存在则自动下载。"""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print("  [raw ] {} 已存在: {}".format(label, path))
        return path
    if not AUTO_PREPARE:
        raise RuntimeError("{} 不存在且 auto_prepare=false: {}".format(label, path))
    if not url:
        raise RuntimeError("{} 不存在且未配置下载 URL".format(label))
    _download_file(url, path)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        raise RuntimeError("{} 下载后仍不可用: {}".format(label, path))
    print("  [raw ] {} 已下载: {}".format(label, path))
    return path


def _ensure_gsm8k(path):
    """确保 GSM8K 原始 jsonl 存在；不存在则下载 zip 并解压。"""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print("  [raw ] GSM8K 已存在: {}".format(path))
        return path
    if not AUTO_PREPARE:
        raise RuntimeError("GSM8K 不存在且 auto_prepare=false: {}".format(path))
    if not GSM8K_URL:
        raise RuntimeError("GSM8K 不存在且未配置 gsm8k_url")
    os.makedirs(RAW_DATASET_DIR, exist_ok=True)
    zip_path = os.path.join(RAW_DATASET_DIR, "gsm8k.zip")
    _download_file(GSM8K_URL, zip_path)
    print("  [raw ] 解压 GSM8K: {}".format(zip_path))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(RAW_DATASET_DIR)
    extracted = os.path.join(RAW_DATASET_DIR, "gsm8k", "train.jsonl")
    if not os.path.exists(extracted):
        extracted = os.path.join(RAW_DATASET_DIR, "gsm8k", "test.jsonl")
    if not os.path.exists(extracted):
        raise RuntimeError("GSM8K 下载解压后未找到 train.jsonl/test.jsonl")
    # 用户指定了自定义路径时，软链到解压结果，保持配置语义不变
    if path != extracted and not os.path.exists(path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        os.symlink(extracted, path)
        print("  [raw ] GSM8K symlink: {} -> {}".format(extracted, path))
        return path
    return extracted


def prepare_raw_datasets(dataset_types):
    """按本次实际用到的数据集类型准备原始文件，已存在则跳过。"""
    global RAW_GSM_PATH, RAW_SHAREGPT_PATH, RAW_SWEBENCH_PATH
    for dt in dataset_types:
        if dt == "gsm":
            RAW_GSM_PATH = _ensure_gsm8k(RAW_GSM_PATH)
        elif dt == "sharegpt":
            RAW_SHAREGPT_PATH = _ensure_raw_file(
                RAW_SHAREGPT_PATH, SHAREGPT_URL, "ShareGPT"
            )
        elif dt == "swebench":
            RAW_SWEBENCH_PATH = _ensure_raw_file(
                RAW_SWEBENCH_PATH, SWEBENCH_URL, "SWE-bench"
            )
        else:
            raise RuntimeError("未知数据集类型: {}".format(dt))

# -------------------- Agent 模式: 原生 SWE-bench --------------------
_AGENT_DATASET_HF_ID = {
    "lite": "princeton-nlp/SWE-Bench_Lite",
    "verified": "princeton-nlp/SWE-Bench_Verified",
    "full": "princeton-nlp/SWE-Bench",
    "multilingual": "SWE-bench/SWE-bench_Multilingual",
}


def _import_or_none(name):
    try:
        return __import__(name)
    except Exception:
        return None


def _ensure_agent_environment():
    '''确保 agent 模式需要的 mini-swe-agent / swebench 已安装。'''
    missing = []
    if _import_or_none("minisweagent") is None:
        missing.append("minisweagent")
    if _import_or_none("swebench") is None:
        missing.append("swebench")
    if not missing:
        print("  [agent] mini-swe-agent / swebench 环境已就绪")
        return

    if not AUTO_PREPARE:
        raise RuntimeError("agent 模式缺少依赖 {}，且 auto_prepare=false".format(missing))

    print("  [agent] 缺少依赖 {}，开始自动安装".format(missing))
    if "minisweagent" in missing:
        repo_dir = os.path.join(SCRIPT_DIR, "third_party", "mini-swe-agent")
        if not os.path.isdir(repo_dir):
            os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
            _run_checked(
                ["git", "clone", "--depth", "1",
                 "https://gh-proxy.com/https://github.com/AISBench/mini-swe-agent.git", repo_dir],
                label="git clone mini-swe-agent",
            )
        _run_checked(
            [sys.executable, "-m", "pip", "install", "-e", repo_dir],
            cwd=repo_dir,
            label="pip install mini-swe-agent",
        )
    if "swebench" in missing:
        repo_dir = os.path.join(SCRIPT_DIR, "third_party", "SWE-bench")
        if not os.path.isdir(repo_dir):
            os.makedirs(os.path.dirname(repo_dir), exist_ok=True)
            _run_checked(
                ["git", "clone", "--branch", "v4.1.0", "--depth", "1",
                 "https://gh-proxy.com/https://github.com/SWE-bench/SWE-bench.git", repo_dir],
                label="git clone SWE-bench",
            )
        _run_checked(
            [sys.executable, "-m", "pip", "install", "-e", repo_dir],
            cwd=repo_dir,
            label="pip install SWE-bench",
        )


def _load_agent_instance_ids(dataset_name, count):
    '''按数据集原始顺序取前 count 条 instance_id；count=0 表示全部。'''
    if dataset_name not in _AGENT_DATASET_HF_ID:
        raise ValueError(
            "agent_dataset 仅支持 {}，当前: {}".format(
                sorted(_AGENT_DATASET_HF_ID), dataset_name
            )
        )
    from datasets import load_dataset

    hf_id = _AGENT_DATASET_HF_ID[dataset_name]
    print("  [agent] 加载数据集: {}".format(hf_id))
    ds = load_dataset(hf_id, split="test")
    ids = list(ds["instance_id"])
    total = len(ids)
    if count is None or count <= 0:
        selected = ids
    else:
        selected = ids[:count]
    print("  [agent] 数据集总数={}，本次选择={}，取前 {} 条".format(total, len(selected), len(selected)))
    return selected


def _agent_filter_regex(instance_ids):
    '''把 instance_id 列表转成精确匹配 regex。'''
    import re as _re
    if not instance_ids:
        raise RuntimeError("agent 模式没有选中任何 instance")
    return "^(?:" + "|".join(_re.escape(x) for x in instance_ids) + ")$"


def _build_agent_config(dataset_name, instance_ids, step_limit):
    '''生成原生 SWE-bench 的 ais_bench 配置文件。'''
    from string import Template

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    cfg_dir = os.path.join(SCRIPT_DIR, "outputs", "agent_configs")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_path = os.path.join(
        cfg_dir,
        "swebench_agent_{}_{}_{}.py".format(dataset_name, len(instance_ids), timestamp),
    )

    model_name = MODEL_CFG_PARAMS.get("model", "")
    host_ip = MODEL_CFG_PARAMS.get("host_ip", "")
    host_port = MODEL_CFG_PARAMS.get("host_port", "")
    if not model_name or not host_ip or not host_port:
        raise RuntimeError(
            "agent 模式需要在 model_cfg_params 里配置 model / host_ip / host_port"
        )
    api_url = "http://{}:{}/v1".format(host_ip, host_port)
    api_key = MODEL_CFG_PARAMS.get("api_key", "dummy") or "dummy"
    filter_regex = _agent_filter_regex(instance_ids)

    template = Template('''from ais_bench.benchmark.datasets import SWEBenchDataset
from ais_bench.benchmark.partitioners import NaivePartitioner
from ais_bench.benchmark.runners import LocalRunner
from ais_bench.benchmark.tasks import SWEBenchInferTask, SWEBenchEvalTask
from ais_bench.benchmark.summarizers import SWEBenchSummarizer

STEP_LIMIT = $step_limit

models = [
    dict(
        attr="local",
        abbr="swebench",
        type="LiteLLMChat",
        model="$model_name",
        api_key="$api_key",
        url="$api_url",
        batch_size=1,
        max_out_len=16384,
        generation_kwargs=dict(
            max_tokens=32768,
            temperature=0.2,
            timeout=600,
        ),
    )
]

datasets = [
    dict(
        type=SWEBenchDataset,
        abbr="swebench_$dataset_name",
        path="",
        name="$dataset_name",
        split="test",
        filter_spec="$filter_regex",
        shuffle=False,
        step_limit=STEP_LIMIT,
    )
]

summarizer = dict(
    attr="accuracy",
    type=SWEBenchSummarizer,
)

infer = dict(
    partitioner=dict(type=NaivePartitioner),
    runner=dict(
        type=LocalRunner,
        task=dict(type=SWEBenchInferTask),
    ),
)

eval = dict(
    partitioner=dict(type=NaivePartitioner),
    runner=dict(
        type=LocalRunner,
        task=dict(type=SWEBenchEvalTask),
    ),
)
''')
    content = template.substitute(
        step_limit=step_limit,
        model_name=model_name,
        api_key=api_key,
        api_url=api_url,
        dataset_name=dataset_name,
        filter_regex=filter_regex,
    )
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  [agent] 配置文件: {}".format(cfg_path))
    return cfg_path


def run_agent_mode():
    '''执行原生 SWE-bench agent 评测。'''
    print("========== Agent 模式: 原生 SWE-bench ==========")
    print("数据集 = {}".format(AGENT_DATASET))
    print("数量 = {}".format("全部" if AGENT_COUNT <= 0 else AGENT_COUNT))
    print("step_limit = {}".format(AGENT_STEP_LIMIT))
    print("工作目录 = {}".format(AGENT_WORK_DIR))

    _ensure_agent_environment()
    instance_ids = _load_agent_instance_ids(AGENT_DATASET, AGENT_COUNT)
    if not instance_ids:
        raise RuntimeError("agent 模式没有选中任何 instance")
    print("  [agent] 选中 instance:")
    for iid in instance_ids:
        print("    - {}".format(iid))

    cfg_path = _build_agent_config(AGENT_DATASET, instance_ids, AGENT_STEP_LIMIT)
    work_dir = os.path.join(SCRIPT_DIR, AGENT_WORK_DIR)
    os.makedirs(work_dir, exist_ok=True)

    cmd = [
        "ais_bench",
        cfg_path,
        "--mode", "all",
        "--work-dir", work_dir,
        "--max-num-workers", "1",
    ]
    print("  [agent] CMD: {}".format(" ".join(cmd)))
    proc = subprocess.run(cmd, cwd=SCRIPT_DIR, text=True)
    if proc.returncode != 0:
        raise RuntimeError("ais_bench agent 模式退出码 {}".format(proc.returncode))
    print("  [agent] 原生 SWE-bench 完成")


# 路径常量
def _find_existing_ais_bench_root():
    """定位 ais_bench benchmark 安装根目录。

    支持 pip install 和 pip install -e 两种安装方式。
    通过 import 包定位，最可靠，不依赖 pip 输出格式。
    """
    import importlib as _il

    for pkg_name in ("ais_bench_benchmark", "ais_bench"):
        try:
            mod = _il.import_module(pkg_name)
            # mod.__file__ 如 /path/to/ais_bench_benchmark/__init__.py
            # pip install -e 时包目录的父目录就是源码根
            pkg_dir = os.path.dirname(getattr(mod, "__file__", ""))
            # 候选：pkg_dir 本身、pkg_dir 的父目录
            for root in (pkg_dir, os.path.dirname(pkg_dir)):
                if os.path.isdir(os.path.join(root, "benchmark", "configs", "models")):
                    return root
        except Exception:
            pass

    # 回退：pip show
    import subprocess as _sp
    _pip = [sys.executable, "-m", "pip"]
    for pkg in ("ais_bench_benchmark", "ais_bench", "ais-bench-benchmark"):
        try:
            r = _sp.run(_pip + ["show", pkg], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                continue
            loc = None
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("Editable project location:"):
                    loc = line.split(":", 1)[1].strip()
                elif line.startswith("Location:"):
                    loc = line.split(":", 1)[1].strip()
            if loc is None:
                continue
            for root in (loc, os.path.join(loc, pkg)):
                if os.path.isdir(os.path.join(root, "benchmark", "configs", "models")):
                    return root
        except Exception:
            pass

    # 回退：向上查找
    d = SCRIPT_DIR
    for _ in range(6):
        candidate = os.path.join(d, "benchmark", "configs", "models")
        if os.path.isdir(candidate):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent

    raise RuntimeError(
        "无法定位 AIS_BENCH_ROOT。请确保 ais_bench_benchmark 已安装（pip install -e ./），"
        "或脚本在 ais_bench 目录树下运行。"
    )

def _install_benchmark_repo(repo_dir):
    """安装 ais_bench benchmark 源码仓库。"""
    if not os.path.isfile(os.path.join(repo_dir, "setup.py")) and not os.path.isfile(os.path.join(repo_dir, "pyproject.toml")):
        raise RuntimeError("benchmark 目录存在但不是可用源码仓库: {}".format(repo_dir))
    print("  [bench] 安装 ais_bench: {}".format(repo_dir))
    _run_checked(
        [sys.executable, "-m", "pip", "install", "-e", repo_dir, "--use-pep517"],
        cwd=repo_dir,
        label="pip install ais_bench",
    )
    if INSTALL_REQUIREMENTS:
        for req_name in ("requirements/api.txt", "requirements/extra.txt"):
            req_path = os.path.join(repo_dir, req_name)
            if os.path.isfile(req_path):
                print("  [bench] 安装依赖: {}".format(req_path))
                _run_checked(
                    [sys.executable, "-m", "pip", "install", "-r", req_path],
                    cwd=repo_dir,
                    label="pip install {}".format(req_name),
                )


def _clone_benchmark_repo(repo_dir):
    """克隆 ais_bench benchmark 源码仓库。"""
    if os.path.isfile(os.path.join(repo_dir, "setup.py")) or os.path.isfile(os.path.join(repo_dir, "pyproject.toml")):
        print("  [bench] benchmark 源码已存在: {}".format(repo_dir))
        return
    if os.path.exists(repo_dir) and os.listdir(repo_dir):
        raise RuntimeError("benchmark_dir 非空但不是 benchmark 源码: {}".format(repo_dir))
    os.makedirs(os.path.dirname(os.path.abspath(repo_dir)), exist_ok=True)
    if not BENCHMARK_REPO:
        raise RuntimeError("ais_bench 未安装且未配置 benchmark_repo")
    cmd = ["git", "clone"]
    if BENCHMARK_REF:
        cmd += ["--branch", BENCHMARK_REF, "--depth", "1"]
    else:
        cmd += ["--depth", "1"]
    cmd += [BENCHMARK_REPO, repo_dir]
    print("  [bench] 克隆 ais_bench: {}".format(BENCHMARK_REPO))
    _run_checked(cmd, label="git clone benchmark")


def _ensure_ais_bench_root():
    """定位或自动安装 ais_bench benchmark。"""
    try:
        return _find_existing_ais_bench_root()
    except Exception as exc:
        if not AUTO_PREPARE:
            raise
        print("  [bench] 未找到已安装的 ais_bench，开始自动准备: {}".format(exc))
        _clone_benchmark_repo(BENCHMARK_DIR)
        _install_benchmark_repo(BENCHMARK_DIR)
        try:
            return _find_existing_ais_bench_root()
        except Exception:
            if os.path.isdir(os.path.join(BENCHMARK_DIR, "benchmark", "configs", "models")):
                return BENCHMARK_DIR
            raise


AIS_BENCH_ROOT = _ensure_ais_bench_root()
PROCESS_DATASET_SCRIPT = os.path.join(SCRIPT_DIR, "process_dataset.py")
MODEL_CFG = os.path.join(
    AIS_BENCH_ROOT,
    "benchmark", "configs", "models", "vllm_api", "vllm_api_general_stream.py",
)
DATASET_DIR = SCRIPT_DIR                       # 数据集 jsonl 在脚本所在文件夹下查找
RUN_CWD = SCRIPT_DIR                           # outputs/excel 统一落在脚本所在目录，不随执行位置变化
OUTPUTS_ROOT = os.path.join(RUN_CWD, "outputs", "default")
EXCEL_PATH = os.path.join(RUN_CWD, "性能测试结果.xlsx")

# 数据集类型 → (显示名, 文件前缀, 原始路径配置key, process_dataset --datasettype 值)
_DATASET_INFO = {
    "gsm":      ("GSM8K",    "GSM8K-in",    "RAW_GSM_PATH",      "GSM"),
    "sharegpt": ("ShareGPT", "ShareGPT-in", "RAW_SHAREGPT_PATH", "SHAREGPT"),
    "swebench": ("Swebench", "Swebench-in", "RAW_SWEBENCH_PATH", "SWEBENCH"),
}

# ais_bench 运行命令
AIS_BENCH_CMD = [
    "ais_bench",
    "--models", "vllm_api_general_stream",
    "--datasets", "gsm8k_gen_0_shot_cot_str_perf",
    "--mode", "perf",
    "--debug",
]


# -------------------- 工具函数 --------------------
def parse_number(s):
    """从 '25282.1 ms' / '40.5053 token/s' / '0.0396 req/s' / '4' 里取数值."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return s
    m = re.search(r"-?\d+\.?\d*", str(s))
    return float(m.group()) if m else None


# Excel 单元格不允许控制字符 (含 ANSI 转义码 \x1b), 写入前必须剥离
_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_cell(value):
    """把任意值清洗成可安全写入 Excel 的值 (剥离 ANSI/控制字符)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    return _ILLEGAL_CHARS_RE.sub("", str(value))


def _set_cfg_field(content, field, value):
    """在 vllm_api_general_stream.py 文本里把某字段替换为 value.

    字符串值加引号, 数字/布尔原样写。匹配 `field=...` 形式 (容空格)。
    返回 (new_content, 替换次数)。找不到该字段时替换次数为 0。
    """
    if isinstance(value, str):
        replacement = '{}="{}"'.format(field, value)
    elif isinstance(value, bool):
        replacement = '{}={}'.format(field, str(value))
    else:
        replacement = '{}={}'.format(field, value)
    pattern = re.compile(r'{}\s*=\s*[^,\n]+'.format(re.escape(field)))
    new_content, n = pattern.subn(replacement, content)
    return new_content, n


def set_model_cfg(params):
    """批量改 vllm_api_general_stream.py 里的字段.

    支持字段: batch_size, max_out_len, request_rate, path, model, host_ip, host_port 等。
    params: dict, 值为 None 的字段跳过。一次读、一次写, 避免重复 IO。
    """
    if not params:
        return
    with open(MODEL_CFG, "r", encoding="utf-8") as f:
        content = f.read()
    changed = []
    for field, value in params.items():
        if value is None:
            continue
        content, n = _set_cfg_field(content, field, value)
        if n == 0:
            print("  [cfg] !! 警告: 在 {} 里找不到 {}=".format(MODEL_CFG, field))
        else:
            changed.append("{}={}".format(field, repr(value)))
    with open(MODEL_CFG, "w", encoding="utf-8") as f:
        f.write(content)
    if changed:
        print("  [cfg] 配置 -> {}".format(", ".join(changed)))


def _dataset_filename(dataset_type, input_len, bs, pfx=None):
    """根据数据集类型构造文件名。

    gsm:      GSM8K-in{LEN}-bs{BS}.jsonl  (无 pfx)
    sharegpt: ShareGPT-in{LEN}-bs{BS}.jsonl 或 ShareGPT-in{LEN}-bs{BS}-pfx{N}.jsonl
    swebench: Swebench-in{LEN}-bs{BS}.jsonl 或 Swebench-in{LEN}-bs{BS}-pfx{N}.jsonl
    """
    _, prefix, _, _ = _DATASET_INFO[dataset_type]
    if pfx:
        return "{}{}-bs{}-pfx{}.jsonl".format(prefix, input_len, bs, pfx)
    else:
        return "{}{}-bs{}.jsonl".format(prefix, input_len, bs)


def find_dataset(dataset_type, input_len, concurrency, pfx=None):
    """在 DATASET_DIR 下查找数据集文件, 返回 (文件名, 绝对路径) 或 (None, None).

    bs = 并发 * 4。支持 gsm/sharegpt/swebench 三种数据集类型。
    """
    bs = concurrency * 4
    ds_name = _dataset_filename(dataset_type, input_len, bs, pfx)
    ds_path = os.path.join(DATASET_DIR, ds_name)
    if os.path.exists(ds_path):
        return ds_name, ds_path
    return None, None


def generate_dataset(dataset_type, input_len, concurrency, pfx=None):
    """调用 process_dataset.py 生成数据集, 返回 (文件名, 绝对路径)。

    生成后再次查找确认文件存在; 若仍不存在则抛异常。
    """
    bs = concurrency * 4
    ds_name = _dataset_filename(dataset_type, input_len, bs, pfx)

    _, _, raw_path_key, ds_type_arg = _DATASET_INFO[dataset_type]
    raw_path = globals().get(raw_path_key, "")
    # tokenizer 模型路径：取 model_cfg_params.path，即 cfg 里的 model_cfg_params.path
    model_path = MODEL_CFG_PARAMS.get("path", "")
    if not model_path:
        raise RuntimeError(
            "model_cfg_params.path 未配置, 无法自动生成数据集 (需要 tokenizer)。"
            "请在 run_perf.cfg 中设置 model_cfg_params.path。"
        )

    cmd = [
        "python3", PROCESS_DATASET_SCRIPT,
        "--bs", str(bs),
        "--inputlen", str(input_len),
        "--datasettype", ds_type_arg,
        "--modelpath", model_path,
    ]

    # 数据集类型特有参数
    if dataset_type == "gsm":
        # GSM 数据路径硬编码在 process_dataset.py 中为 ./GSM8K.jsonl
        if raw_path:
            gsm_link = os.path.join(SCRIPT_DIR, "GSM8K.jsonl")
            if not os.path.exists(gsm_link) and os.path.exists(raw_path):
                os.symlink(raw_path, gsm_link)
                print("  [gen] GSM 原始数据 symlink: {} -> {}".format(raw_path, gsm_link))
    elif dataset_type == "sharegpt":
        if not raw_path:
            raise RuntimeError("RAW_SHAREGPT_PATH 未配置, 无法生成 ShareGPT 数据集")
        cmd += ["--sharegptpath", raw_path]
    elif dataset_type == "swebench":
        if not raw_path:
            raise RuntimeError("RAW_SWEBENCH_PATH 未配置, 无法生成 SWE-bench 数据集")
        cmd += ["--swebenchpath", raw_path]

    # pfx 模式
    if pfx:
        cmd += ["--mode", "prefix", "--prefix_ratio", str(pfx / 100.0)]

    print("  [gen] 自动生成数据集: {}".format(ds_name))
    print("  [gen] CMD: {}".format(" ".join(str(x) for x in cmd)))
    proc = subprocess.run(
        cmd,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stdout.splitlines()[-30:])
        raise RuntimeError(
            "process_dataset.py 退出码 {}: \n{}".format(proc.returncode, tail)
        )
    # 生成后验证文件存在
    ds_name, ds_path = find_dataset(dataset_type, input_len, concurrency, pfx)
    if ds_name is None:
        raise RuntimeError("数据集生成后仍未找到: {}".format(ds_name))
    print("  [gen] 数据集已生成: {}".format(ds_path))
    return ds_name, ds_path


def bind_dataset(ds_name):
    """ln -sf {ds_name} -> test.jsonl / train.jsonl (在脚本目录和 ais_bench 期望路径下)。

    ais_bench 内部会去 AIS_BENCH_ROOT/datasets/gsm8k/ 下找 test.jsonl 和 train.jsonl，
    这里同时软链到脚本目录和该路径，避免 FileNotFoundError。
    """
    ds_path = os.path.join(DATASET_DIR, ds_name)
    # 脚本目录下的软链
    for link_name in ("test.jsonl", "train.jsonl"):
        link_path = os.path.join(DATASET_DIR, link_name)
        if os.path.islink(link_path) or os.path.exists(link_path):
            os.remove(link_path)
        os.symlink(ds_name, link_path)
        print("  [ln ] {} -> {}".format(ds_name, link_name))

    # ais_bench 期望路径：AIS_BENCH_ROOT/datasets/gsm8k/test.jsonl
    gsm8k_dir = os.path.join(AIS_BENCH_ROOT, "datasets", "gsm8k")
    os.makedirs(gsm8k_dir, exist_ok=True)
    for link_name in ("test.jsonl", "train.jsonl"):
        link_path = os.path.join(gsm8k_dir, link_name)
        if os.path.islink(link_path) or os.path.exists(link_path):
            os.remove(link_path)
        os.symlink(ds_path, link_path)
        print("  [ln ] {} -> {}".format(ds_path, link_path))


def run_ais_bench():
    """跑一次 ais_bench, 返回 (returncode, stdout+stderr).

    cwd 用 RUN_CWD (当前进程 cwd): ais_bench 输出目录是相对路径 `outputs/default/...`,
    落在哪取决于运行时工作目录, 必须和执行 run_perf.py 的位置一致。
    输出同时打到终端，方便实时观察进度。
    """
    print("  [run] {}  (cwd={})".format(" ".join(AIS_BENCH_CMD), RUN_CWD))
    proc = subprocess.run(
        AIS_BENCH_CMD,
        cwd=RUN_CWD,
        stdout=None,
        stderr=None,
        text=True,
    )
    return proc.returncode, proc.stdout


def find_latest_result(before_dirs):
    """在 OUTPUTS_ROOT 下找本次运行新生成的 timestamp 目录, 返回结果目录.

    只看 *本次新增* 的目录: 找不到含 gsm8k.csv 的就返回 None (用例记为失败),
    绝不 fallback 到历史目录——否则失败的用例会复用旧结果, 数值张冠李戴.
    """
    if not os.path.isdir(OUTPUTS_ROOT):
        return None
    cur_dirs = set(
        d for d in os.listdir(OUTPUTS_ROOT)
        if os.path.isdir(os.path.join(OUTPUTS_ROOT, d))
    )
    new_dirs = sorted(cur_dirs - before_dirs)
    for ts in reversed(new_dirs):
        csv_path = os.path.join(
            OUTPUTS_ROOT, ts, "performances", "vllm-api-general-stream", "gsm8k.csv"
        )
        if os.path.exists(csv_path):
            return os.path.join(OUTPUTS_ROOT, ts, "performances", "vllm-api-general-stream")
    return None


def parse_result(result_dir):
    """解析 gsm8k.csv + gsm8k.json, 返回 (perf_rows, common_rows, summary_dict)."""
    csv_path = os.path.join(result_dir, "gsm8k.csv")
    json_path = os.path.join(result_dir, "gsm8k.json")

    perf_rows = []  # [(param, stage, avg, min, max, median, p75, p90, p99, n), ...]
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not row or not row[0].strip():
                continue
            perf_rows.append(row)

    with open(json_path, "r", encoding="utf-8") as f:
        common = json.load(f)
    common_rows = [(k, list(v.keys())[0], list(v.values())[0]) for k, v in common.items()]

    perf_map = {r[0]: r for r in perf_rows}
    def avg(param):
        return parse_number(perf_map[param][2]) if param in perf_map else None

    summary = {
        "平均E2EL(ms)": avg("E2EL"),
        "平均TTFT(ms)": avg("TTFT"),
        "平均TPOT(ms)": avg("TPOT"),
        "平均ITL(ms)": avg("ITL"),
        "平均输出token吞吐(token/s)": avg("OutputTokenThroughput"),
        "总吞吐(token/s)": parse_number(common.get("Total Token Throughput", {}).get("total")),
        "请求吞吐(req/s)": parse_number(common.get("Request Throughput", {}).get("total")),
        "总请求数": common.get("Total Requests", {}).get("total"),
    }
    return perf_rows, common_rows, summary


# -------------------- 用例解析 --------------------
def parse_case_str(s, seq=""):
    """解析用例串 '[dataset_type:]输入-输出-并发-rate[-pfx]'。

    格式: 可选的 dataset_type: 前缀 (gsm/sharegpt/swebench), 省略默认 sharegpt。
    seq: 用例序号 (来自 JSON 的 key 或简易模式计数), 仅用于标识, 不参与解析。
    返回 dict: {seq, dataset_type, input_len, out_len, concurrency, request_rate, pfx}。
    解析失败抛 ValueError。
    """
    s = str(s).strip()
    # 检查是否带 dataset_type: 前缀
    dataset_type = "sharegpt"  # 默认
    for dt in _DATASET_INFO:
        if s.lower().startswith(dt + ":"):
            dataset_type = dt
            s = s[len(dt) + 1:]
            break
    parts = s.split("-")
    if len(parts) < 4:
        raise ValueError("用例串字段不足 (需至少 输入-输出-并发-rate): {}".format(s))
    try:
        case = {
            "seq": str(seq),
            "dataset_type": dataset_type,
            "input_len": int(parts[0]),
            "out_len": int(parts[1]),
            "concurrency": int(parts[2]),
            "request_rate": float(parts[3]),
            "pfx": None,
        }
    except ValueError as e:
        raise ValueError("用例串数值解析失败 {}: {}".format(s, e))
    if len(parts) >= 5:
        try:
            pfx_val = int(parts[4])
            case["pfx"] = pfx_val if pfx_val else None
        except ValueError:
            raise ValueError("pfx 字段不是整数: {}".format(s))
    return case


def load_cases(path):
    """从 JSON 文件加载用例列表。

    支持两种格式:
      1) 序号->用例串 映射 (推荐):
         {"1": "32768-1024-4-0.5",  "2": "32768-1024-4-0.5-90", ...}
      2) 用例串列表 (兼容):
         ["32768-1024-4-0.5", "32768-1024-4-0.5-90", ...]
    用例串格式: 输入长度-输出长度-并发-request_rate[-pfx]  (序号由 JSON key 提供)
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cases = []
    if isinstance(data, dict):
        # {"1": "...", "2": "..."}  按 key 排序保持顺序
        for seq in sorted(data.keys(), key=lambda x: (len(str(x)), str(x))):
            item = data[seq]
            if isinstance(item, str):
                cases.append(parse_case_str(item, seq=seq))
            elif isinstance(item, dict):
                cases.append(_case_from_obj(item, seq=seq))
            else:
                raise ValueError("用例值必须是字符串或对象: {}: {}".format(seq, item))
    elif isinstance(data, list):
        for i, item in enumerate(data, start=1):
            if isinstance(item, str):
                cases.append(parse_case_str(item, seq=i))
            elif isinstance(item, dict):
                cases.append(_case_from_obj(item, seq=i))
            else:
                raise ValueError("用例项必须是字符串或对象: {}".format(item))
    else:
        raise ValueError("JSON 用例文件必须是 dict 或 list: {}".format(path))
    return cases


def _case_from_obj(item, seq=""):
    """从对象 {in, out, concurrency, rate, pfx, dataset_type} 构造用例 dict."""
    return {
        "seq": str(item.get("seq", item.get("id", seq))),
        "dataset_type": str(item.get("dataset_type", item.get("ds", "sharegpt"))),
        "input_len": int(item.get("in", item.get("input_len"))),
        "out_len": int(item.get("out", item.get("out_len"))),
        "concurrency": int(item.get("concurrency", item.get("c", 0))),
        "request_rate": float(item.get("rate", item.get("request_rate", 0))),
        "pfx": int(item["pfx"]) if "pfx" in item and item["pfx"] is not None else None,
    }


# -------------------- Excel 写入 --------------------
def safe_sheet_name(name):
    """excel sheet 名最长 31 字符, 且不能含 []:*?/\\."""
    for ch in "[]:*?/\\":
        name = name.replace(ch, "_")
    return name[:31]


def write_excel(cases, out_path=None):
    """cases: list of dict(case_name, batch_size, summary, perf_rows, common_rows, status, error, ...).
    out_path: 输出路径, 默认用全局 EXCEL_PATH。
    """
    out_path = out_path or EXCEL_PATH
    wb = openpyxl.Workbook()

    # ---- 汇总 sheet ----
    ws = wb.active
    ws.title = "性能测试汇总"
    headers = [
        "配置名称", "数据集类型", "输入长度", "输出长度", "并发数", "request_rate", "pfx",
        "平均E2EL(ms)", "平均TTFT(ms)", "平均TPOT(ms)", "平均ITL(ms)",
        "平均输出token吞吐(token/s)", "总吞吐(token/s)", "请求吞吐(req/s)", "总请求数",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for case in cases:
        s = case["summary"] or {}
        ws.append([
            clean_cell(case["case_name"]),
            clean_cell(case.get("dataset_type", "sharegpt")),
            case.get("input_len"),
            case.get("out_len"),
            case.get("concurrency"),
            case.get("request_rate"),
            case.get("pfx"),
            clean_cell(s.get("平均E2EL(ms)")),
            clean_cell(s.get("平均TTFT(ms)")),
            clean_cell(s.get("平均TPOT(ms)")),
            clean_cell(s.get("平均ITL(ms)")),
            clean_cell(s.get("平均输出token吞吐(token/s)")),
            clean_cell(s.get("总吞吐(token/s)")),
            clean_cell(s.get("请求吞吐(req/s)")),
            clean_cell(s.get("总请求数")),
        ])
    for col in "ABCDEFGHIJK":
        ws.column_dimensions[col].width = 22
    for col in "LMNO":
        ws.column_dimensions[col].width = 22

    # ---- 每个用例一个明细 sheet ----
    for case in cases:
        name = safe_sheet_name(case["case_name"])
        ws = wb.create_sheet(name)
        bold = Font(bold=True)

        if case["status"] != "ok":
            ws["A1"] = clean_cell("用例失败: {}".format(case.get("error", case["status"])))
            ws["A1"].font = bold
            continue

        # 性能参数
        ws["A1"] = "性能参数"
        ws["A1"].font = bold
        perf_header = [
            "Performance Parameters", "Stage", "Average", "Min", "Max",
            "Median", "P75", "P90", "P99", "N",
        ]
        ws.append(perf_header)
        for c in ws[ws.max_row]:
            c.font = bold
        for row in case["perf_rows"]:
            out = [clean_cell(row[0]), clean_cell(row[1])]
            for cell in row[2:]:
                out.append(parse_number(cell))
            ws.append(out)

        ws.append([])
        ws.append(["通用指标"])
        ws[ws.max_row][0].font = bold
        ws.append(["Common Metric", "Stage", "Value"])
        for c in ws[ws.max_row]:
            c.font = bold
        for k, stage, v in case["common_rows"]:
            ws.append([clean_cell(k), clean_cell(stage), parse_number(v) if v is not None else v])

        for col in "ABCDEFGHIJ":
            ws.column_dimensions[col].width = 22

    wb.save(out_path)
    print("\n[done] Excel 已保存: {}".format(out_path))


# -------------------- 主流程 --------------------
def run_case(case, skip_run=False):
    """跑一个用例。case: dict from parse_case_str / load_cases."""
    dataset_type = case.get("dataset_type", "sharegpt")
    input_len = case["input_len"]
    concurrency = case["concurrency"]
    out_len = case["out_len"]
    request_rate = case["request_rate"]
    pfx = case["pfx"]

    bs = concurrency * 4
    # 用例命名: 数据集类型 + 文件名 + 并发
    ds_stub = _dataset_filename(dataset_type, input_len, bs, pfx)
    # 去掉 .jsonl 后缀
    if ds_stub.endswith(".jsonl"):
        ds_stub = ds_stub[:-6]
    case_name = "{}-{}并发".format(ds_stub, concurrency)
    print("\n========== 用例 #{}: {} ==========".format(case.get("seq", ""), case_name))

    result = {
        "case_name": case_name,
        "dataset_type": dataset_type,
        "input_len": input_len,
        "out_len": out_len,
        "concurrency": concurrency,
        "request_rate": request_rate,
        "pfx": pfx,
        "summary": None,
        "perf_rows": [],
        "common_rows": [],
        "status": "failed",
        "error": "",
    }

    try:
        # 1) 查数据集; 找不到则自动生成
        ds_name, ds_path = find_dataset(dataset_type, input_len, concurrency, pfx)
        if ds_name is None:
            print("  [ds ] 数据集不存在, 尝试自动生成...")
            ds_name, ds_path = generate_dataset(dataset_type, input_len, concurrency, pfx)
        print("  [ds ] {}".format(ds_name))

        # 2) 改动态配置 (max_out_len + request_rate + batch_size，每个用例不同)
        cfg = {"max_out_len": out_len, "request_rate": request_rate, "batch_size": concurrency}
        set_model_cfg(cfg)

        # 3) 绑定数据集
        bind_dataset(ds_name)

        before_dirs = set(
            d for d in os.listdir(OUTPUTS_ROOT)
            if os.path.isdir(os.path.join(OUTPUTS_ROOT, d))
        ) if os.path.isdir(OUTPUTS_ROOT) else set()

        if skip_run:
            # 调试: 用最新的已有输出
            result_dir = find_latest_result(set())
        else:
            rc, _ = run_ais_bench()
            if rc != 0:
                raise RuntimeError("ais_bench 退出码 {}".format(rc))
            result_dir = find_latest_result(before_dirs)

        if not result_dir:
            raise RuntimeError("找不到本次输出的结果目录 (gsm8k.csv); 可能 ais_bench 未成功生成")

        perf_rows, common_rows, summary = parse_result(result_dir)
        result["perf_rows"] = perf_rows
        result["common_rows"] = common_rows
        result["summary"] = summary
        result["status"] = "ok"
        print("  [ok ] 结果: {}".format(result_dir))
    except Exception as e:
        result["error"] = str(e)
        result["status"] = "failed"
        print("  [ERR] {}".format(e))

    return result


def main():
    ap = argparse.ArgumentParser(description="ais_bench 自动性能测试 (JSON 用例驱动)")
    ap.add_argument("--cases", help="performance 模式: JSON 用例文件路径")
    ap.add_argument("--mode", choices=["performance", "agent"], default=None,
                    help="运行模式: performance=拼接压测数据集, agent=原生 SWE-bench")
    ap.add_argument("--agent-dataset", choices=sorted(_AGENT_DATASET_HF_ID), default=None,
                    help="agent 模式: SWE-bench 数据集类型")
    ap.add_argument("--agent-count", type=int, default=None,
                    help="agent 模式: 取前 N 条; 0 表示全部")
    # 简易模式 (向后兼容)
    ap.add_argument("-i", "--input-len", type=int, nargs="+", default=None,
                    help="简易模式: 输入长度列表")
    ap.add_argument("-c", "--concurrency", type=int, nargs="+", default=None,
                    help="简易模式: 并发数列表 (batch_size)")
    ap.add_argument("--max-out-len", type=int, default=DEFAULT_MAX_OUT_LEN,
                    help="简易模式: 输出长度")
    ap.add_argument("--request-rate", type=float, default=DEFAULT_REQUEST_RATE,
                    help="简易模式: request_rate (0=尽量打满)")
    ap.add_argument("--pfx", type=int, nargs="+", default=[DEFAULT_PFX],
                    help="简易模式: 前缀缓存重复率%% 列表 (可多个); 0 或不传=普通数据集")
    ap.add_argument("--dataset-type", dest="dataset_type", nargs="+", default=None,
                    choices=["gsm", "sharegpt", "swebench"],
                    help="简易模式: 数据集类型列表 (gsm/sharegpt/swebench), 默认用脚本顶部 DATASET_TYPES")
    # 模型配置覆盖
    ap.add_argument("--path", dest="path", default=None, help="模型权重路径")
    ap.add_argument("--model", dest="model", default=None, help="模型名")
    ap.add_argument("--host-ip", dest="host_ip", default=None, help="服务 IP")
    ap.add_argument("--host-port", dest="host_port", type=int, default=None, help="服务端口")
    ap.add_argument("--excel", default=None, help="Excel 输出路径 (默认当前文件夹下)")
    ap.add_argument("--skip-run", action="store_true", help="只解析已有输出, 不重新跑")
    args = ap.parse_args()

    global EXCEL_PATH, MODEL_CFG_PARAMS, RUN_MODE, AGENT_DATASET, AGENT_COUNT, AGENT_STEP_LIMIT, AGENT_WORK_DIR
    if args.mode:
        RUN_MODE = args.mode
    if args.agent_dataset:
        AGENT_DATASET = args.agent_dataset
    if args.agent_count is not None:
        AGENT_COUNT = args.agent_count

    if RUN_MODE == "agent":
        run_agent_mode()
        return

    if args.excel:
        EXCEL_PATH = args.excel
    # 命令行模型配置覆盖脚本默认
    MODEL_CFG_PARAMS = dict(MODEL_CFG_PARAMS)
    MODEL_CFG_PARAMS.update({
        "path":        args.path or MODEL_CFG_PARAMS.get("path"),
        "model":       args.model or MODEL_CFG_PARAMS.get("model"),
        "host_ip":     args.host_ip or MODEL_CFG_PARAMS.get("host_ip"),
        "host_port":   args.host_port if args.host_port is not None else MODEL_CFG_PARAMS.get("host_port"),
    })

    print("数据集目录 = {}".format(DATASET_DIR))
    print("执行目录(cwd) = {}".format(RUN_CWD))
    print("Excel 输出 = {}".format(EXCEL_PATH))
    active = {k: v for k, v in MODEL_CFG_PARAMS.items() if v is not None}
    print("模型配置(生效) = {}".format(active if active else "(全用文件现有值)"))
    # 静态配置（path/model/host_ip/host_port）只在启动时写一次，整个测试过程不变
    set_model_cfg(MODEL_CFG_PARAMS)

    # ---- 构造用例列表 ----
    if args.cases:
        cases = load_cases(args.cases)
        print("模式: JSON 用例驱动, 共 {} 条用例".format(len(cases)))
    else:
        # 简易模式: 输入长度 × 数据集类型 × 并发 × pfx 四重笛卡尔积
        input_lens = args.input_len if args.input_len else INPUT_LEN
        dataset_types = args.dataset_type if args.dataset_type else DATASET_TYPES
        concurrencies = args.concurrency if args.concurrency else CONCURRENCIES
        pfxs = args.pfx if args.pfx else [DEFAULT_PFX]
        # pfx: 0 视为普通数据集 (None)
        pfxs = [p if p else None for p in pfxs]
        print("模式: 简易 (数据集类型 {} × 输入长度 {} × 并发 {} × pfx {})".format(
            dataset_types, input_lens, concurrencies, [p if p is not None else "无" for p in pfxs]))
        cases = []
        seq = 1
        for dt in dataset_types:
            for il in input_lens:
                for c in concurrencies:
                    for pfx in pfxs:
                        cases.append({
                            "seq": str(seq),
                            "dataset_type": dt,
                            "input_len": il,
                            "out_len": args.max_out_len,
                            "concurrency": c,
                            "request_rate": args.request_rate,
                            "pfx": pfx,
                        })
                        seq += 1

    # ---- v1.0.3: 自动准备本次用到的原始数据集 ----
    active_dataset_types = sorted({case.get("dataset_type", "sharegpt") for case in cases})
    print("自动准备 = {}".format("开启" if AUTO_PREPARE else "关闭"))
    prepare_raw_datasets(active_dataset_types)

    # ---- 跑用例 ----
    results = []
    for case in cases:
        results.append(run_case(case, skip_run=args.skip_run))

    # ---- 按 (数据集类型, 输入长度, pfx) 分组, 每组写一个 Excel ----
    groups = {}
    for r in results:
        key = (r.get("dataset_type", "sharegpt"), r["input_len"], r["pfx"])
        groups.setdefault(key, []).append(r)

    # 时间戳，避免覆盖之前的结果
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    for (dt, input_len, pfx), group_results in groups.items():
        pfx_tag = "_pfx{}".format(pfx) if pfx else ""
        group_path = os.path.join(
            RUN_CWD, "性能测试结果_{}_in{}{}_{}.xlsx".format(dt, input_len, pfx_tag, timestamp)
        )
        write_excel(group_results, out_path=group_path)

    # 终端汇总
    print("\n========== 汇总 ==========")
    print("{:<40} {:>8} {:>8} {:>10} {:>10} {:>8}".format(
        "用例", "并发", "rate", "E2EL", "总吞吐", "状态"))
    for r in results:
        s = r["summary"] or {}
        print("{:<40} {:>8} {:>8} {:>10} {:>10} {:>8}".format(
            r["case_name"][:40],
            str(r["concurrency"]),
            str(r["request_rate"]),
            str(s.get("平均E2EL(ms)", "-")),
            str(s.get("总吞吐(token/s)", "-")),
            r["status"],
        ))


if __name__ == "__main__":
    main()
