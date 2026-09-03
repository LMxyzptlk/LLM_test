# LLM 自动化测试工具集

## 版本历史

### v1.3.1 — 2026-09-03

- **Performance 两个子类型配置完全隔离**
  - `concat` 专属配置统一放在 `performance.concat`
  - `native_multiturn` 专属配置统一放在 `performance.native_multiturn`
  - 公共配置只保留模型服务、benchmark 环境、自动准备、原始数据下载目录和下载 URL
- **命令行默认值不再跨子类型泄漏**
  - 不传 `--max-out-len` / `--request-rate` / `-c` 时，concat 和 native_multiturn 分别读取自己的配置
  - 传入这些参数时，只覆盖当前 performance 子类型

### v1.3.0 — 2026-09-03

- **Performance 模式新增 `native_multiturn` 子类型**
  - `performance.kind=concat`：保留原有拼接压测数据集流程
  - `performance.kind=native_multiturn`：接入 AISBench 原生 ShareGPT 多轮对话性能测试
- **原生多轮支持按有效对话组截取**
  - `conversation_count=100`：取前 100 组有效多轮对话
  - `conversation_count=0`：全量 ShareGPT
- **支持多轮推理模式**
  - `infer_mode=every`
  - `infer_mode=last`
  - `infer_mode=every_with_gt`
- **自动生成 AISBench 原生多轮配置**
  - 使用 `vllm_api_stream_chat_multiturn`
  - 使用 `sharegpt_gen`
  - 输出到 `outputs/performance_configs/`
- **原生多轮结果单独落盘**
  - AISBench 输出：`outputs/performance/native_multiturn/`
  - Excel 输出：`results/performance/native_multiturn/`
- **新增命令行参数**
  - `--performance-kind concat|native_multiturn`
  - `--native-conversation-count N`
  - `--native-infer-mode every|last|every_with_gt`
  - `--native-work-dir`
  - `--native-result-dir`
  - `--native-raw-sharegpt-path`

### v1.2.1 — 2026-09-03

- **支持混合运行**
  - `mode` 可以设置为 `performance` / `agent` / `accuracy` 的任意组合
  - 支持一个、两个或三个模式
  - 支持逗号字符串和 JSON 数组两种写法
  - 按配置或命令行给出的顺序依次执行
  - 自动去重，避免同一模式重复跑
- **命令行 `--mode` 支持组合**
  - `--mode agent performance`
  - `--mode agent,performance,accuracy`
  - `--mode accuracy --mode agent`
- **混合运行时自动切换各模式专属配置**
  - agent 使用 `agent` 节点
  - accuracy 使用 `accuracy` 节点
  - performance 使用 `performance` 节点

### v1.2.0 — 2026-09-03

- **新增 `accuracy` 精度测试模式**
  - `mode=accuracy`：通过 `evalscope` 跑精度测试
  - 默认数据集：`gpqa_diamond`
  - 默认并发批次：`eval_batch_size=8`
  - 缺失 `evalscope` 时自动执行 `pip install evalscope`
- **新增独立 `accuracy` 配置节点**
  - 精度测试的模型、服务、数据集、生成参数全部与 agent / performance 分离
- **新增命令行参数**
  - `--mode accuracy`
  - `--accuracy-dataset`
  - `--accuracy-batch-size`
  - `--accuracy-work-dir`
  - `--api-key`

### v1.1.0 — 2026-09-02

- **新增 `agent` 模式**
  - `mode=performance`：拼接压测数据集 + ais_bench 性能测试
  - `mode=agent`：原生 SWE-bench 推理与评测
- **配置文件按模式完全拆分**
  - 最外层只保留 `mode`、`agent`、`performance` 三个 key
  - 两套模式各自维护模型配置、benchmark 配置和自动准备开关
- **Agent 模式支持官方数据集**
  - `lite` / `verified` / `full` / `multilingual`
- **Agent 模式支持按数据集顺序取前 N 条**
  - `agent.count=1`：只跑第 1 条
  - `agent.count=10`：跑前 10 条
  - `agent.count=0`：跑全部
- **Agent 模式支持选择运行阶段**
  - `agent.run_mode=infer`：只推理
  - `agent.run_mode=eval`：只评测
  - `agent.run_mode=all`：推理 + 评测
- **自动准备环境**
  - Performance：自动准备 benchmark 和原始压测数据集
  - Agent：自动执行 `setup_swebench.sh`，准备 Docker、mini-swe-agent、SWE-bench 和数据集缓存
- **新增命令行参数**
  - `--mode performance|agent`
  - `--agent-dataset lite|verified|full|multilingual`
  - `--agent-count N`
  - `--agent-run-mode infer|eval|all`

### v1.0.3 — 2026-09-02

- 自动检测并安装 `AISBench/benchmark`
- 自动下载 GSM8K / ShareGPT / SWE-bench 原始数据
- 已存在的 benchmark 和数据集直接复用
- Performance 数据集统一输出到 `datasets/performance/`
- Performance Excel 统一输出到 `results/performance/`

### v1.0.2 — 2026-08-31

- 新增 `gen_datasets.py`，支持批量预生成压测数据集和 `--dry-run`

### v1.0.1 — 2026-08-24

- 支持配置外置、JSON 用例驱动、多数据集类型、自动生成缺失数据集
- `AIS_BENCH_ROOT` 自动定位，支持标准安装和 `pip install -e`

### v1.0.0 — 2026-08-21

- 初始版本

## 文件说明

| 文件 | 说明 |
|------|------|
| `run_perf.py` | 自动测试入口，支持 performance、agent、accuracy 三种模式及任意组合；performance 支持 concat 和 native_multiturn |
| `run_perf.cfg` | JSONC 配置文件，支持中文注释 |
| `gen_datasets.py` | 提前批量生成 performance 压测数据集 |
| `process_dataset.py` | 压测数据集制作脚本 |
| `setup_swebench.sh` | SWE-bench / mini-swe-agent / Docker 环境一键配置 |
| `xllm自动化性能测试.md` | 完整使用文档 |

## 快速开始

```bash
# 1. 编辑配置；最外层只有 mode / agent / accuracy / performance
vim run_perf.cfg

# 2. performance：拼接压测数据集 + ais_bench
python3 run_perf.py --mode performance --cases cases.json

# 3. agent：原生 SWE-bench，取 Lite 前 10 条
python3 run_perf.py --mode agent --agent-dataset lite --agent-count 10

# 4. performance 原生 ShareGPT 多轮压测
python3 run_perf.py --mode performance --performance-kind native_multiturn

# 5. accuracy：evalscope 精度测试，默认 GPQA Diamond
python3 run_perf.py --mode accuracy

# 6. 混合运行：agent -> performance -> accuracy
python3 run_perf.py --mode agent performance accuracy

# 7. 逗号写法等价
python3 run_perf.py --mode agent,performance,accuracy

# 8. 可选：只推理 / 评测
python3 run_perf.py --mode agent --agent-run-mode infer
python3 run_perf.py --mode agent --agent-run-mode eval

# 9. 可选：预生成 performance concat 数据集
python3 gen_datasets.py --dry-run
python3 gen_datasets.py
```

## run_perf.cfg 配置结构

配置最外层固定为四个 key：`mode`、`agent`、`accuracy`、`performance`。`mode` 支持单个模式或混合模式，各模式自己的参数分别放在同名节点下，互不混用。

```jsonc
{
  // 支持单个、逗号字符串或数组；混合模式按数组/字符串顺序执行
  "mode": ["agent", "performance", "accuracy"],

  "agent": {
    // lite / verified / full / multilingual
    "dataset": "lite",
    // 1=第 1 条；10=前 10 条；0=全部
    "count": 10,
    "step_limit": 200,
    "work_dir": "outputs/agent",
    // infer / eval / all
    "run_mode": "all",
    "model_cfg_params": {
      "path": "/export/home/models/xxx",
      "model": "xxx",
      "host_ip": "11.87.191.83",
      "host_port": 18004
    },
    "auto_prepare": true,
    "benchmark_repo": "https://gh-proxy.com/https://github.com/AISBench/benchmark.git",
    "benchmark_dir": "",
    "benchmark_ref": "",
    "install_requirements": true
  },

  "accuracy": {
    "dataset": "gpqa_diamond",
    "eval_batch_size": 8,
    "work_dir": "outputs/accuracy",
    "auto_prepare": true,
    "model_cfg_params": {
      "model": "xxx",
      "host_ip": "11.87.191.83",
      "host_port": 18004,
      "api_key": "EMPTY"
    },
    "generation_config": {
      "temperature": 1.0,
      "top_p": 0.95,
      "max_tokens": 130000,
      "timeout": 900,
      "retries": 2
    },
    "dataset_args": {
      "gpqa_diamond": {
        "filters": {
          "remove_until": "</think>"
        }
      }
    }
  },

  "performance": {
    // concat=拼接压测；native_multiturn=AISBench 原生 ShareGPT 多轮压测
    "kind": "concat",

    "model_cfg_params": {
      "path": "/export/home/models/xxx",
      "model": "xxx",
      "host_ip": "11.87.191.83",
      "host_port": 18004
    },
    "auto_prepare": true,
    "benchmark_repo": "https://gh-proxy.com/https://github.com/AISBench/benchmark.git",
    "benchmark_dir": "",
    "benchmark_ref": "",
    "install_requirements": true,
    "raw_dataset_dir": "raw_datasets",
    "gsm8k_url": "http://opencompass.oss-cn-shanghai.aliyuncs.com/datasets/data/gsm8k.zip",
    "sharegpt_url": "https://hf-mirror.com/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json",
    "swebench_url": "https://hf-mirror.com/datasets/princeton-nlp/SWE-bench/resolve/main/data/test-00000-of-00001.parquet",

    "concat": {
      "dataset_dir": "datasets/performance",
      "result_dir": "results/performance",
      "input_len": [32768],
      "concurrencies": [1, 8, 16],
      "default_max_out_len": null,
      "default_request_rate": null,
      "default_pfx": null,
      "dataset_types": ["sharegpt"],
      "raw_gsm_path": "",
      "raw_sharegpt_path": "",
      "raw_swebench_path": ""
    },

    "native_multiturn": {
      "conversation_count": 100,
      "infer_mode": "every",
      "concurrencies": [1, 8, 16],
      "max_out_len": 512,
      "request_rate": 0,
      "work_dir": "outputs/performance/native_multiturn",
      "result_dir": "results/performance/native_multiturn",
      "raw_sharegpt_path": "",
      "generation_kwargs": {
        "temperature": 0.01,
        "ignore_eos": false
      }
    }
  }
}
```

### Mode 字段

| 字段 | 说明 |
|------|------|
| `mode` | 单个模式或混合模式；支持字符串、逗号字符串和数组 |

### Agent 节点

| 字段 | 说明 |
|------|------|
| `agent.dataset` | 官方数据集：lite / verified / full / multilingual |
| `agent.count` | 按数据集原始顺序取前 N 条；0 表示全部 |
| `agent.step_limit` | 单个 instance 的最大步数 |
| `agent.work_dir` | Agent 输出目录 |
| `agent.run_mode` | infer / eval / all |
| `agent.model_cfg_params` | Agent 模式专用模型和服务配置 |
| `agent.auto_prepare` | 是否自动执行环境配置 |
| `agent.benchmark_repo` | benchmark 仓库地址 |
| `agent.benchmark_dir` | benchmark 本地目录；空值使用脚本旁的 `benchmark/` |
| `agent.benchmark_ref` | benchmark 分支或 tag |
| `agent.install_requirements` | 是否自动安装 benchmark requirements |

### Accuracy 节点

| 字段 | 说明 |
|------|------|
| `accuracy.dataset` | evalscope 数据集，默认 `gpqa_diamond` |
| `accuracy.eval_batch_size` | evalscope `--eval-batch-size` |
| `accuracy.work_dir` | 精度测试输出目录 |
| `accuracy.auto_prepare` | 缺失 evalscope 时是否自动安装 |
| `accuracy.model_cfg_params` | 精度测试专用模型和服务配置 |
| `accuracy.generation_config` | 生成参数，等价于 `--generation-config` |
| `accuracy.dataset_args` | 数据集参数，等价于 `--dataset-args` |

### Performance 公共字段

| 字段 | 说明 |
|------|------|
| `performance.kind` | performance 子类型：concat / native_multiturn |
| `performance.model_cfg_params` | Performance 两种子类型共用的模型和服务配置 |
| `performance.auto_prepare` | 是否自动准备 benchmark 和原始数据 |
| `performance.benchmark_repo` / `performance.benchmark_dir` / `performance.benchmark_ref` / `performance.install_requirements` | benchmark 环境公共配置 |
| `performance.raw_dataset_dir` | 公共原始数据下载目录 |
| `performance.gsm8k_url` / `performance.sharegpt_url` / `performance.swebench_url` | 公共原始数据下载地址 |

### Performance concat 专属字段

| 字段 | 说明 |
|------|------|
| `performance.concat.dataset_dir` | concat 生成的压测数据集目录 |
| `performance.concat.result_dir` | concat Excel 结果目录 |
| `performance.concat.input_len` | concat 输入 token 长度列表；native_multiturn 忽略 |
| `performance.concat.concurrencies` | concat 并发列表；native_multiturn 忽略 |
| `performance.concat.default_max_out_len` | concat 默认输出长度；native_multiturn 忽略 |
| `performance.concat.default_request_rate` | concat 默认请求速率；native_multiturn 忽略 |
| `performance.concat.default_pfx` | concat 前缀缓存比例；native_multiturn 忽略 |
| `performance.concat.dataset_types` | concat 数据集类型：gsm / sharegpt / swebench |
| `performance.concat.raw_gsm_path` / `performance.concat.raw_sharegpt_path` / `performance.concat.raw_swebench_path` | concat 原始数据路径 |

### Performance native_multiturn 专属字段

| 字段 | 说明 |
|------|------|
| `performance.native_multiturn.conversation_count` | 取前 N 组有效多轮对话；0=全量 |
| `performance.native_multiturn.infer_mode` | every / last / every_with_gt |
| `performance.native_multiturn.concurrencies` | 原生多轮专属并发列表 |
| `performance.native_multiturn.max_out_len` | 原生多轮专属单次请求最大输出 |
| `performance.native_multiturn.request_rate` | 原生多轮专属请求速率；0=打满 |
| `performance.native_multiturn.work_dir` | AISBench 原生多轮输出目录 |
| `performance.native_multiturn.result_dir` | 原生多轮 Excel 目录 |
| `performance.native_multiturn.raw_sharegpt_path` | 原生多轮专属原始 ShareGPT 路径；留空使用公共 `raw_dataset_dir` |
| `performance.native_multiturn.generation_kwargs` | 原生多轮生成参数 |

## 输出

```text
datasets/performance/   # performance concat 生成的 jsonl
results/performance/    # performance concat Excel
results/performance/native_multiturn/ # 原生多轮 Excel
outputs/performance/native_multiturn/ # 原生多轮 AISBench 输出
outputs/agent/          # agent 原生 SWE-bench 输出
outputs/accuracy/       # accuracy 精度测试输出
outputs/agent_configs/  # agent 自动生成的 ais_bench 配置
raw_datasets/           # 自动下载的原始数据
```
