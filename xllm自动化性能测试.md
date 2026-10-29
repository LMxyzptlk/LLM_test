# LLM 自动化测试工具集

## 1. 配置文件

配置已拆分为一个公共文件和六个模式专属文件：

```text
cfg-normal.cfg       公共配置
agent.cfg            Agent 模式专属配置
accuracy.cfg         Accuracy 模式专属配置
vlm.cfg              VLM 多模态精度模式专属配置
performance-vl.cfg   VLM 多模态性能压测模式专属配置
performance-c.cfg    Performance concat 拼接压测配置
performance-n.cfg    Performance native 原生多轮压测配置
```

### 1.1 `cfg-normal.cfg`

```jsonc
{
  // 默认模式，可写成数组混合运行
  "mode": "performance-c",

  // 公共模型和服务配置
  "model_cfg_params": {
    "path": "/export/home/models/GLM-5.2-w8a8",
    "model": "GLM-5.2-w8a8",
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
  "gsm8k_url": "http://opencompass.oss-cn-shanghai.aliyuncs.com/datasets/data/gsm8k.zip",
  "sharegpt_url": "https://hf-mirror.com/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json",
  "swebench_url": "https://hf-mirror.com/datasets/princeton-nlp/SWE-bench/resolve/main/data/test-00000-of-00001.parquet"
}
```

### 1.2 `agent.cfg`

```jsonc
{
  "dataset": "lite",
  "count": 1,
  "step_limit": 200,
  "work_dir": "outputs/agent",
  "run_mode": "all"
}
```

### 1.3 `accuracy.cfg`

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

### 1.4 `performance-c.cfg`

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

### 1.5 `performance-n.cfg`

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

### 1.6 `vlm.cfg`

```jsonc
{
  "dataset": "mmmu",
  "dataset_hub": "modelscope",
  "subset_list": [],
  "limit": 0,
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
  "dataset_args": {}
}
```

- `dataset`：默认 `mmmu`，评测 MMMU validation split（30 个学科 / 900 题）
- `dataset_hub`：`modelscope` 或 `huggingface`
- `subset_list`：留空跑全部；可填 `Accounting`、`Art`、`Math` 等 30 个子集
- `limit`：按子集生效；`0` 全量；整数为前 N 条；小数为百分比 `(0, 1]`
- `work_dir`：evalscope 会在其下按时间戳建子目录

### 1.7 `performance-vl.cfg`

```jsonc
{
  "dataset": "random_vl",
  "concurrencies": [1, 8, 16, 32],
  "number": 0,
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
  "request_rate": -1,
  "sleep_interval": 5,
  "tokenizer_path": "",
  "work_dir": "outputs/performance/vl",
  "result_dir": "results/performance/vl",
  "extra_args": {"ignore_eos": true}
}
```

- `dataset`：默认 `random_vl`，evalscope 在线生成随机图片请求
- `number`：每个并发的请求数；`0` 自动取 `max(20, 并发*10)`，也可写成与 `concurrencies` 等长的数组
- `image_*`：图片尺寸、格式、数量和 patch 大小，直接决定视觉 token 量
- `tokenizer_path`：留空时回退到 `model_cfg_params.path`；测试机看不到模型路径时需显式指定
- `extra_args`：传给 `evalscope perf --extra-args`，`ignore_eos=true` 保证输出长度固定

## 2. 运行模式

支持六个直接模式：

```text
performance-c
performance-n
performance-vl
agent
accuracy
vlm
```

### 2.1 Performance concat

```bash
python3 run_perf.py --mode performance-c
```

用于拼接压测数据集和 ais_bench 性能测试。

### 2.2 Performance native

```bash
python3 run_perf.py --mode performance-n
```

用于 AISBench 原生 ShareGPT 多轮对话性能测试。

### 2.3 Agent

```bash
python3 run_perf.py --mode agent
```

用于原生 SWE-bench 推理与评测。

### 2.4 Accuracy

```bash
python3 run_perf.py --mode accuracy
```

用于 evalscope 精度测试。

### 2.5 VLM

```bash
python3 run_perf.py --mode vlm
```

用于 evalscope 多模态精度测试，默认 MMMU。评测完成后会打印总体 acc 和各子集 acc，并在评测目录下生成 `vlm_summary.json` / `vlm_summary.csv`。

### 2.6 Performance VL

```bash
python3 run_perf.py --mode performance-vl
```

用于 evalscope 多模态性能压测，默认 `random_vl`。会按 `concurrencies` 依次压测，结束后打印各并发的吞吐、TTFT、TPOT、Latency，并把含 P99 的汇总写到 `results/performance/vl/`。

### 2.7 混合运行

支持任意组合：

```bash
python3 run_perf.py --mode agent performance-c accuracy vlm
python3 run_perf.py --mode performance-n,accuracy
python3 run_perf.py --mode accuracy --mode agent
```

配置文件中的 `mode` 也支持字符串或数组：

```jsonc
"mode": "performance-c"
```

或：

```jsonc
"mode": ["agent", "performance-c", "accuracy"]
```

## 3. 常用命令

### 3.1 Performance concat

```bash
python3 run_perf.py \
  --mode performance-c \
  --cases cases.json
```

或简易模式：

```bash
python3 run_perf.py \
  --mode performance-c \
  -i 32768 \
  -c 1 8 16 \
  --max-out-len 1024 \
  --request-rate 0
```

### 3.2 Performance native

```bash
python3 run_perf.py \
  --mode performance-n \
  --native-conversation-count 100 \
  -c 1 8 16 \
  --max-out-len 512 \
  --request-rate 0
```

### 3.3 Agent

```bash
python3 run_perf.py \
  --mode agent \
  --agent-dataset lite \
  --agent-count 10
```

### 3.4 Accuracy

```bash
python3 run_perf.py \
  --mode accuracy \
  --accuracy-dataset gpqa_diamond \
  --accuracy-batch-size 8
```

### 3.5 VLM

```bash
# 全量 MMMU
python3 run_perf.py --mode vlm

# 冒烟：只跑每个子集的前 10 题，并限制到 2 个子集
python3 run_perf.py \
  --mode vlm \
  --vlm-limit 10 \
  --vlm-subset Accounting Art \
  --vlm-batch-size 4

# 切换数据集源
python3 run_perf.py --mode vlm --vlm-dataset-hub huggingface
```

注意：被测 VLM 服务需要支持 OpenAI 兼容的多模态消息（`image_url` 传入 base64 data URL）。VLM 模式依赖 evalscope ≥ 1.6，首次评测会把 MMMU 数据集下载到 `~/.cache/modelscope/datasets`。

### 3.6 Performance VL

```bash
# 默认：1/8/16/32 并发，各并发请求数自动取 max(20, 并发*10)
python3 run_perf.py --mode performance-vl

# 冒烟：1、8 并发，各 50 条请求，512x512 单图
python3 run_perf.py \
  --mode performance-vl \
  --perf-vl-concurrency 1 8 \
  --perf-vl-number 50 \
  --perf-vl-image-width 512 \
  --perf-vl-image-height 512

# 测试机看不到模型路径时显式指定 tokenizer
python3 run_perf.py \
  --mode performance-vl \
  --perf-vl-tokenizer-path /export/home/models/Qwen3-VL-32B
```

注意：`random_vl` 依赖 tokenizer 统计 prompt 长度，默认回退到公共 `model_cfg_params.path`；图片会以 base64 发送，带宽和显存占用随图片数量/尺寸增长。该模式依赖 `evalscope[perf]`，`auto_prepare=true` 时缺失会自动安装。

### 3.7 预生成 performance-c 数据集

```bash
python3 gen_datasets.py --dry-run
python3 gen_datasets.py
```

## 4. 输出目录

```text
datasets/performance/   # performance-c 生成的 jsonl
results/performance/    # performance-c Excel
results/performance/native_multiturn/ # performance-n Excel
outputs/performance/native_multiturn/ # performance-n AISBench 输出
outputs/agent/          # agent 输出
outputs/accuracy/       # accuracy 输出
outputs/vlm/{timestamp}/ # vlm 输出（含 vlm_summary.json / vlm_summary.csv）
outputs/performance/vl/{timestamp}/ # performance-vl 压测输出
results/performance/vl/ # performance-vl 汇总 CSV / JSON
outputs/agent_configs/  # agent 自动生成的 ais_bench 配置
raw_datasets/           # 自动下载的原始数据
```

## 5. 版本

- v1.5.1：新增 VLM 多模态性能压测模式（random_vl）
- v1.5.0：新增 VLM 多模态精度模式（MMMU）
- v1.4.0：配置拆分为公共文件和模式专属文件，Performance 拆分为 `performance-c` / `performance-n`
- v1.3.1：Performance concat / native 配置完全隔离
- v1.3.0：新增 AISBench 原生 ShareGPT 多轮压测
- v1.2.1：支持混合运行
- v1.2.0：新增 evalscope 精度测试
- v1.1.0：新增原生 SWE-bench Agent 模式
- v1.0.0：初始版本
