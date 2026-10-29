# LLM 自动化测试工具集

## 版本历史

### v1.6.1 — 2026-10-29

- **完善性能测试预热（默认关闭，需显式开启）**
  - 压测前按「用例并发 × 用例输出长度」先打若干轮预热请求，冷请求不再计入统计
  - 新增 `warmup` 配置块（`enabled` / `rounds` / `requests` / `concurrency` / `max_out_len` / `timeout` / `sleep` / `reuse_prompts`），`performance-c` 和 `performance-n` 各自独立
  - 预热默认给 prompt 加随机后缀，避免把待测 prompt 的前缀缓存提前写进去
  - 新增 `ais_num_warmups`，可控制 ais_bench 自带的 `--num-warmups`（默认 1）
  - 命令行覆盖：`--no-warmup` / `--warmup-rounds` / `--warmup-concurrency` / `--ais-num-warmups`
  - 每轮打印预热耗时和 TTFT，并给出冷热差倍率
  - **`warmup.enabled` 默认 `false`**：不改变原有冷跑口径，需要时在配置里打开

### v1.6.0 — 2026-10-29

- **新增 LiveCodeBench 代码生成精度测试模式**
  - `--mode lcb`，评测 175 道竞赛题（easy 43 / medium 52 / hard 80）
  - 支持按难度筛选：`--lcb-difficulty easy medium`（任意组合，不传=全部）
  - 评测逻辑独立在 `livecodebench_eval.py`，`run_perf.py` 只负责调起和汇总
  - 新增 `lcb.cfg`：题库/源码目录、难度、并发、输出长度、超时和重试
  - 题库缺失时按 `data_url` 自动下载（hf-mirror，约 129MB），无需手动准备
  - 支持断点续跑（`--lcb-output-dir` 指向已有目录）和 `--lcb-reset-failed` 重跑失败题
  - 汇总 pass@1、分难度、分平台和各阶段耗时到 `results/lcb/`

### v1.5.2 — 2026-10-29

- **VLM 精度测试默认数据集从 MMMU 改为 MMMU-Pro**
  - 默认 `dataset: mmmu_pro`，评测 test split（30 个学科 / 1730 题）
  - 新增 `dataset_format` 配置和 `--vlm-dataset-format`，支持 4 选项、10 选项、vision 三种变体

### v1.5.1 — 2026-10-29

- **新增 VLM 多模态性能压测模式**
  - `--mode performance-vl`，基于 `evalscope perf`，默认使用 `random_vl` 在线生成带图请求
  - 新增 `performance-vl.cfg`：并发、请求数、输出长度、图片尺寸/数量、tokenizer 等
  - 支持 `--perf-vl-concurrency` / `--perf-vl-number` / `--perf-vl-image-width` 等命令行覆盖
  - 多并发依次压测，结束后汇总各并发吞吐、TTFT、TPOT、P99 指标，输出 CSV / JSON

### v1.5.0 — 2026-10-29

- **新增 VLM 多模态精度测试模式**
  - `--mode vlm`，基于 evalscope，默认评测 MMMU validation（30 个学科 / 900 题）
  - 新增 `vlm.cfg`：数据集源、子集筛选、limit、repeats、批次和生成参数
  - 支持 `--vlm-subset` / `--vlm-limit` / `--vlm-dataset-hub` 等命令行覆盖
  - 评测结束后自动汇总总体 acc 和各子集 acc，输出 `vlm_summary.json` / `vlm_summary.csv`

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
| `vlm.cfg` | VLM 多模态精度模式专属配置 |
| `lcb.cfg` | LiveCodeBench 代码生成精度模式专属配置 |
| `livecodebench_eval.py` | LiveCodeBench 评测脚本（供 `--mode lcb` 调用，也可单独运行） |
| `performance-vl.cfg` | VLM 多模态性能压测模式专属配置 |
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
python3 run_perf.py --mode performance-c --warmup-rounds 4   # 加强预热
python3 run_perf.py --mode performance-c --no-warmup          # 关闭预热

# 3. Performance native：AISBench 原生 ShareGPT 多轮压测
python3 run_perf.py --mode performance-n

# 4. Agent：原生 SWE-bench
python3 run_perf.py --mode agent --agent-dataset lite --agent-count 10

# 5. Accuracy：evalscope 精度测试
python3 run_perf.py --mode accuracy

# 6. VLM：evalscope MMMU-Pro 多模态精度测试
python3 run_perf.py --mode vlm
python3 run_perf.py --mode vlm --vlm-limit 10 --vlm-subset Accounting Art
python3 run_perf.py --mode vlm --vlm-dataset-format "standard (10 options)"

# 7. Performance VL：evalscope random_vl 多模态性能压测
python3 run_perf.py --mode performance-vl
python3 run_perf.py --mode performance-vl --perf-vl-concurrency 1 8 --perf-vl-number 50

# 8. LCB：LiveCodeBench 代码生成精度测试
python3 run_perf.py --mode lcb
python3 run_perf.py --mode lcb --lcb-difficulty easy medium
python3 run_perf.py --mode lcb --lcb-difficulty hard --lcb-concurrency 16

# 9. 混合运行
python3 run_perf.py --mode agent performance-c accuracy vlm
python3 run_perf.py --mode performance-n,accuracy

# 10. 可选：预生成 performance-c 数据集
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

### `vlm.cfg`

VLM 多模态精度模式专属配置：

```jsonc
{
  "dataset": "mmmu_pro",
  "dataset_format": "standard (4 options)", // MMMU-Pro: standard (4 options) / standard (10 options) / vision
  "dataset_hub": "modelscope",
  "subset_list": [],          // 空=全部 30 个子集
  "limit": 0,                 // 每个子集：0=全量；整数=前 N 条；小数=百分比
  "repeats": 1,
  "eval_batch_size": 4,
  "work_dir": "outputs/vlm",
  "generation_config": {
    "temperature": 0.0,
    "top_p": 1.0,
    "max_tokens": 16384,
    "timeout": 1800,
    "retries": 2
  },
  // 可选：覆盖公共 model_cfg_params，例如 VLM 服务和性能测试不在同一端口
  // "model_cfg_params": {"model": "Qwen3-VL-32B", "host_ip": "11.87.191.78", "host_port": 28888},
  "dataset_args": {}
}
```

`dataset_format` 仅对 MMMU-Pro 生效：`standard (4 options)` 为 evalscope 默认，`standard (10 options)` 难度更高，`vision` 把题目嵌入图片。可用 `--vlm-dataset-format` 临时覆盖。

`subset_list` 可选值（MMMU-Pro 30 个学科）：Accounting、Agriculture、Architecture_and_Engineering、Art、Art_Theory、Basic_Medical_Science、Biology、Chemistry、Clinical_Medicine、Computer_Science、Design、Diagnostics_and_Laboratory_Medicine、Economics、Electronics、Energy_and_Power、Finance、Geography、History、Literature、Manage、Marketing、Materials、Math、Mechanical_Engineering、Music、Pharmacy、Physics、Psychology、Public_Health、Sociology。

VLM 模式依赖 evalscope ≥ 1.6；缺失时 `auto_prepare` 会自动 `pip install evalscope`。首次评测会把 MMMU-Pro（`AI-ModelScope/MMMU_Pro`）下载到 `~/.cache/modelscope/datasets`。

### `performance-vl.cfg`

VLM 多模态性能压测模式专属配置：

```jsonc
{
  "dataset": "random_vl",
  "concurrencies": [1, 8, 16, 32],
  "number": 0,                // 0=自动 max(20, 并发*10)；也可写数组逐个指定
  "max_out_len": 128,
  "min_out_len": 128,
  "min_prompt_length": 100,
  "max_prompt_length": 100,
  "prefix_length": 0,
  "image_width": 512,
  "image_height": 512,
  "image_format": "RGB",
  "image_num": 1,
  "image_patch_size": 28,
  "request_rate": -1,         // -1=不限制
  "sleep_interval": 5,
  "tokenizer_path": "",       // 留空则用公共 model_cfg_params.path
  "work_dir": "outputs/performance/vl",
  "result_dir": "results/performance/vl",
  "extra_args": {"ignore_eos": true}
}
```

`random_vl` 会在本地随机生成纯色/几何图形图片并以 base64 发送，适合稳定压测多模态服务的吞吐和时延。`tokenizer_path` 用于统计 prompt token 数，未填时回退到 `model_cfg_params.path`；如果服务端模型路径在测试机不可见，需要显式指定 tokenizer 路径。

压测结束后会打印各并发的请求吞吐、输出吞吐、平均 TTFT / TPOT / Latency，并汇总 P99 指标到 `results/performance/vl/perf_vl_<timestamp>.csv` / `.json`。

Performance VL 依赖 `evalscope[perf]`；缺失且 `auto_prepare=true` 时会自动执行 `pip install evalscope[perf]`。

### `lcb.cfg`

LiveCodeBench 代码生成精度模式专属配置：

```jsonc
{
  "data_file": "",            // 题库；空=脚本同级 test6.jsonl
  "data_url": "https://hf-mirror.com/datasets/livecodebench/code_generation_lite/resolve/main/test6.jsonl",
                              // 题库缺失时自动下载；留空=不下载
  "source_dir": "",           // LiveCodeBench 源码目录；空=脚本同级 LiveCodeBench-main
  "difficulties": [],         // 空=全部 175 题；可选 easy / medium / hard 任意组合
  "limit": 0,                 // 难度过滤后再取前 N 题，0=不限制
  "concurrency": 8,           // 并发请求数
  "max_tokens": 65536,        // 单题最大生成 token 数
  "temperature": 0.6,
  "request_timeout": 1200,    // 单题请求超时（秒）
  "eval_timeout": 3600,       // 单题判题超时（秒）
  "max_retries": 10,
  "retry_base_seconds": 30,
  "retry_max_seconds": 300,
  "work_dir": "outputs/lcb",  // 每次运行按时间戳建子目录
  "result_dir": "results/lcb",// 汇总 CSV / JSON
  "auto_prepare": true        // 缺 openai / datasets 时自动 pip install
}
```

题库默认位于脚本同级的 `test6.jsonl`（175 题：easy 43 / medium 52 / hard 80），不存在时会按 `data_url` 自动下载（hf-mirror 上 `livecodebench/code_generation_lite` 的同名文件，约 129MB，`auto_prepare=false` 时不下载）。评测逻辑依赖 LiveCodeBench 源码目录（其下需有 `lcb_runner/`）；题库和源码目录都可用 `data_file` / `source_dir` 指到别处，或用 `--lcb-data-file` / `--lcb-source-dir` / `--lcb-data-url` 临时覆盖。

结果目录里会有 `state.json`（逐题状态）、`raw.json`、`predictions.json`、`evaluation.json`、`summary.json` 和 `report.md`。想断点续跑就把 `--lcb-output-dir` 指回上次的目录；配合 `--lcb-reset-failed` 可以只重跑请求失败的题。

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
  "raw_swebench_path": "",
  "warmup": {
    "enabled": false,
    "rounds": 2,          // 预热轮数；每轮并发数 = 用例并发
    "requests": 0,        // 覆盖总请求数；0 = rounds * 并发
    "concurrency": 0,     // 0 = 跟随用例并发
    "max_out_len": 0,     // 0 = 跟随用例输出长度
    "timeout": 600,
    "sleep": 2.0,
    "reuse_prompts": false
  },
  "ais_num_warmups": 1
}
```

预热说明：**默认关闭**（`warmup.enabled=false`，保持原有冷跑口径）。ais_bench 自带的 `--num-warmups` 默认只发 1 条请求、且顺序发送，在请求数小的用例里首条冷请求会把均值拉高。把 `enabled` 改成 `true` 后，每次正式压测前会按**本用例的并发数和输出长度**再打 `rounds` 轮（每轮 `并发` 条请求），把图捕获、显存池、连接池都跑热，这些请求不计入统计。`reuse_prompts=false` 时会给预热 prompt 加随机后缀，避免预热把待测 prompt 的前缀缓存写进去、让正式压测变成缓存命中。

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
  },
  "warmup": {
    "enabled": false,
    "rounds": 2,
    "requests": 0,
    "concurrency": 0,
    "max_out_len": 0,
    "timeout": 600,
    "sleep": 2.0,
    "reuse_prompts": false
  },
  "ais_num_warmups": 1
}
```

## Mode

支持七个直接模式：

```text
performance-c
performance-n
performance-vl
agent
accuracy
vlm
lcb
```

也支持任意组合：

```bash
python3 run_perf.py --mode agent performance-c accuracy vlm
python3 run_perf.py --mode performance-n,accuracy
python3 run_perf.py --mode accuracy --mode agent
python3 run_perf.py --mode vlm --vlm-limit 10
python3 run_perf.py --mode performance-vl
python3 run_perf.py --mode lcb --lcb-difficulty easy
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
outputs/vlm/{timestamp}/ # vlm 输出（含 vlm_summary.json / vlm_summary.csv）
outputs/performance/vl/{timestamp}/ # performance-vl 压测输出（evalscope perf）
outputs/lcb/{timestamp}/ # lcb 输出（state/raw/predictions/evaluation/summary/report）
results/lcb/            # lcb 汇总 CSV / JSON
results/performance/vl/ # performance-vl 汇总 CSV / JSON
outputs/agent_configs/  # agent 自动生成的 ais_bench 配置
raw_datasets/           # 自动下载的原始数据
```
