# LLM 自动化测试工具集

## 版本历史

### v1.4.0 — 2026-09-09

- **配置文件拆分**
  - `cfg-normal.cfg`：所有模式共享的公共配置
  - `agent.cfg`：Agent 模式专属配置
  - `accuracy.cfg`：Accuracy 模式专属配置
  - `performance-c.cfg`：Performance concat 拼接压测专属配置
  - `performance-n.cfg`：Performance native 原生多轮压测专属配置
- **Performance 拆成两个独立 mode**
  - `--mode performance-c`
  - `--mode performance-n`
- **移除 `--performance-kind`**
  - 不再需要先选 `performance` 再选子类型
- **混合运行支持新的 mode 名**
  - `--mode agent performance-c accuracy`
  - `--mode performance-n,accuracy`
- **`gen_datasets.py` 和 `setup_swebench.sh` 同步改为读取拆分后的配置**

### v1.3.1 — 2026-09-03

- Performance concat / native 配置完全隔离
- 命令行默认值不再跨子类型泄漏

### v1.3.0 — 2026-09-03

- 新增 AISBench 原生 ShareGPT 多轮压测
- 支持按有效对话组截取和多轮推理模式

### v1.2.1 — 2026-09-03

- 支持混合运行
- 支持逗号、空格和重复 `--mode`

### v1.2.0 — 2026-09-03

- 新增 evalscope 精度测试模式

### v1.1.0 — 2026-09-02

- 新增原生 SWE-bench Agent 模式

### v1.0.0 — 2026-08-21

- 初始版本

## 文件说明

| 文件 | 说明 |
|------|------|
| `run_perf.py` | 自动测试入口 |
| `cfg-normal.cfg` | 公共配置 |
| `agent.cfg` | Agent 模式专属配置 |
| `accuracy.cfg` | Accuracy 模式专属配置 |
| `performance-c.cfg` | Performance concat 拼接压测配置 |
| `performance-n.cfg` | Performance native 原生多轮压测配置 |
| `gen_datasets.py` | 提前批量生成 performance-c 压测数据集 |
| `process_dataset.py` | 压测数据集制作脚本 |
| `setup_swebench.sh` | SWE-bench / mini-swe-agent / Docker 环境一键配置 |
| `xllm自动化性能测试.md` | 完整使用文档 |

## 快速开始

```bash
# 1. 编辑公共配置和当前模式配置
vim cfg-normal.cfg
vim performance-c.cfg

# 2. Performance concat：拼接压测数据集 + ais_bench
python3 run_perf.py --mode performance-c

# 3. Performance native：AISBench 原生 ShareGPT 多轮压测
python3 run_perf.py --mode performance-n

# 4. Agent：原生 SWE-bench
python3 run_perf.py --mode agent --agent-dataset lite --agent-count 10

# 5. Accuracy：evalscope 精度测试
python3 run_perf.py --mode accuracy

# 6. 混合运行
python3 run_perf.py --mode agent performance-c accuracy
python3 run_perf.py --mode performance-n,accuracy

# 7. 可选：预生成 performance-c 数据集
python3 gen_datasets.py --dry-run
python3 gen_datasets.py
```

## 配置文件结构

### `cfg-normal.cfg`

公共配置，所有模式共享：

```jsonc
{
  // 默认模式，可写成数组混合运行
  "mode": "performance-c",

  // 公共模型和服务配置
  "model_cfg_params": {
    "path": "/export/home/models/xxx",
    "model": "xxx",
    "host_ip": "11.87.191.78",
    "host_port": 28888
  },

  // 公共自动准备开关
  "auto_prepare": true,

  // 公共 benchmark 配置
  "benchmark_repo": "https://gh-proxy.com/https://github.com/AISBench/benchmark.git",
  "benchmark_dir": "",
  "benchmark_ref": "",
  "install_requirements": true,

  // 公共原始数据下载目录和地址
  "raw_dataset_dir": "raw_datasets",
  "gsm8k_url": "...",
  "sharegpt_url": "...",
  "swebench_url": "..."
}
```

### `agent.cfg`

Agent 模式专属配置：

```jsonc
{
  "dataset": "lite",
  "count": 1,
  "step_limit": 200,
  "work_dir": "outputs/agent",
  "run_mode": "all"
}
```

### `accuracy.cfg`

Accuracy 模式专属配置：

```jsonc
{
  "dataset": "gpqa_diamond",
  "eval_batch_size": 8,
  "work_dir": "outputs/accuracy",
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
}
```

### `performance-c.cfg`

Performance concat 拼接压测专属配置：

```jsonc
{
  "dataset_dir": "datasets/performance",
  "result_dir": "results/performance",
  "input_len": [16384, 65536, 200000],
  "concurrencies": [1, 8, 16, 32],
  "default_max_out_len": 1024,
  "default_request_rate": null,
  "default_pfx": null,
  "dataset_types": ["sharegpt"],
  "raw_gsm_path": "",
  "raw_sharegpt_path": "",
  "raw_swebench_path": ""
}
```

### `performance-n.cfg`

Performance native 原生多轮压测专属配置：

```jsonc
{
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
```

## Mode

支持四个直接模式：

```text
performance-c
performance-n
agent
accuracy
```

也支持任意组合：

```bash
python3 run_perf.py --mode agent performance-c accuracy
python3 run_perf.py --mode performance-n,accuracy
python3 run_perf.py --mode accuracy --mode agent
```

配置文件里的 `mode` 也支持字符串或数组：

```jsonc
"mode": "performance-c"
```

或：

```jsonc
"mode": ["agent", "performance-c", "accuracy"]
```

## 输出

```text
datasets/performance/   # performance-c 生成的 jsonl
results/performance/    # performance-c Excel
results/performance/native_multiturn/ # performance-n Excel
outputs/performance/native_multiturn/ # performance-n AISBench 输出
outputs/agent/          # agent 输出
outputs/accuracy/       # accuracy 输出
outputs/agent_configs/  # agent 自动生成的 ais_bench 配置
raw_datasets/           # 自动下载的原始数据
```
