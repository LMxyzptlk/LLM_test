# LLM 自动化测试工具集

## 1. 配置文件

配置已拆分为一个公共文件和七个模式专属文件：

```text
cfg-normal.cfg       公共配置
agent.cfg            Agent 模式专属配置
accuracy.cfg         Accuracy 模式专属配置
vlm.cfg              VLM 多模态精度模式专属配置
lcb.cfg              LiveCodeBench 代码生成精度模式专属配置
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
  "raw_swebench_path": "",

  // 压测前预热（详见 6. 预热）
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

### 1.6 `vlm.cfg`

```jsonc
{
  "dataset": "mmmu_pro",
  "dataset_format": "standard (4 options)",
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

- `dataset`：默认 `mmmu_pro`，评测 MMMU-Pro test split（30 个学科 / 1730 题）
- `dataset_format`：MMMU-Pro 格式变体，`standard (4 options)` / `standard (10 options)` / `vision`
- `dataset_hub`：`modelscope` 或 `huggingface`
- `subset_list`：留空跑全部；可填 `Accounting`、`Art`、`Math` 等 30 个子集
- `limit`：按子集生效；`0` 全量；整数为前 N 条；小数为百分比 `(0, 1]`
- `work_dir`：evalscope 会在其下按时间戳建子目录

### 1.7 `lcb.cfg`

```jsonc
{
  "data_file": "",            // 题库；空=脚本同级 test6.jsonl
  "data_url": "https://hf-mirror.com/datasets/livecodebench/code_generation_lite/resolve/main/test6.jsonl",
  "source_dir": "",           // LiveCodeBench 源码目录；空=脚本同级 LiveCodeBench-main
  "difficulties": [],         // 空=全部 175 题；可选 easy / medium / hard 任意组合
  "limit": 0,                 // 难度过滤后再取前 N 题，0=不限制
  "concurrency": 8,
  "max_tokens": 65536,
  "temperature": 0.6,
  "request_timeout": 1200,
  "eval_timeout": 3600,
  "max_retries": 10,
  "retry_base_seconds": 30,
  "retry_max_seconds": 300,
  "work_dir": "outputs/lcb",
  "result_dir": "results/lcb",
  "auto_prepare": true
}
```

- `data_file`：题库默认是脚本同级的 `test6.jsonl`，175 题（easy 43 / medium 52 / hard 80）
- `data_url`：题库缺失时自动下载（hf-mirror 上 `livecodebench/code_generation_lite` 的同名文件，约 129MB）；留空或不设 `auto_prepare` 则不下载
- `source_dir`：LiveCodeBench 源码目录，其下需要有 `lcb_runner/`
- `difficulties`：留空跑全部；也可以写 `["easy", "medium"]`
- `concurrency` / `request_timeout` / `eval_timeout`：并发、单题请求超时、单题判题超时
- `auto_prepare`：缺少 `openai` / `datasets` 时自动 pip install

### 1.8 `performance-vl.cfg`

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

用于 evalscope 多模态精度测试，默认 MMMU-Pro。评测完成后会打印总体 acc 和各子集 acc，并在评测目录下生成 `vlm_summary.json` / `vlm_summary.csv`。

### 2.6 Performance VL

```bash
python3 run_perf.py --mode performance-vl
```

用于 evalscope 多模态性能压测，默认 `random_vl`。会按 `concurrencies` 依次压测，结束后打印各并发的吞吐、TTFT、TPOT、Latency，并把含 P99 的汇总写到 `results/performance/vl/`。

### 2.7 LiveCodeBench 代码生成精度

```bash
python3 run_perf.py --mode lcb
```

用于 LiveCodeBench 代码生成精度测试，默认跑全部 175 道竞赛题。评测逻辑在独立的 `livecodebench_eval.py` 里，`run_perf.py` 只负责调起和汇总。结束后会打印 pass@1、分难度 / 分平台通过率以及 TTFT / TPOT / token 分布，并把汇总写到 `results/lcb/`。

### 2.8 混合运行

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
# 全量 MMMU-Pro（默认 4 选项）
python3 run_perf.py --mode vlm

# 10 选项变体（更难）
python3 run_perf.py --mode vlm --vlm-dataset-format "standard (10 options)"

# 冒烟：只跑每个子集的前 10 题，并限制到 2 个子集
python3 run_perf.py \
  --mode vlm \
  --vlm-limit 10 \
  --vlm-subset Accounting Art \
  --vlm-batch-size 4

# 切换数据集源
python3 run_perf.py --mode vlm --vlm-dataset-hub huggingface
```

注意：被测 VLM 服务需要支持 OpenAI 兼容的多模态消息（`image_url` 传入 base64 data URL）。VLM 模式依赖 evalscope ≥ 1.6，首次评测会把 MMMU-Pro（`AI-ModelScope/MMMU_Pro`）下载到 `~/.cache/modelscope/datasets`。

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

### 3.7 LiveCodeBench

```bash
# 全量 175 题（easy 43 / medium 52 / hard 80）
python3 run_perf.py --mode lcb

# 只跑 easy + medium
python3 run_perf.py --mode lcb --lcb-difficulty easy medium

# 冒烟：hard 里取前 5 题，并发 16
python3 run_perf.py \
  --mode lcb \
  --lcb-difficulty hard \
  --lcb-limit 5 \
  --lcb-concurrency 16

# 断点续跑：指回上次的结果目录，只补没跑完的题
python3 run_perf.py --mode lcb --lcb-output-dir outputs/lcb/20261029_195525

# 连带重跑上次请求失败的题
python3 run_perf.py --mode lcb \
  --lcb-output-dir outputs/lcb/20261029_195525 \
  --lcb-reset-failed

# 题库 / 源码不在脚本同级时显式指定
python3 run_perf.py --mode lcb \
  --lcb-data-file /data/lcb/test6.jsonl \
  --lcb-source-dir /opt/LiveCodeBench

# 禁掉自动下载（题库必须已存在）
python3 run_perf.py --mode lcb --lcb-data-url ""
```

注意：题库（约 129MB）不存在时会自动从 `lcb.data_url` 下载，已有文件不再重复下载。判题会在本机执行模型生成的代码，需要 LiveCodeBench 的判题依赖齐全；单题请求超时和判题超时分别由 `request_timeout` / `eval_timeout` 控制。

### 3.8 预生成 performance-c 数据集
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
outputs/lcb/{timestamp}/ # lcb 输出（state/raw/predictions/evaluation/summary/report）
results/lcb/            # lcb 汇总 CSV / JSON
outputs/agent_configs/  # agent 自动生成的 ais_bench 配置
raw_datasets/           # 自动下载的原始数据
```

## 5. 预热

`performance-c` / `performance-n` 支持在正式压测前预热，目的是把冷启动的影响挡在统计之外。

**默认关闭**（`warmup.enabled: false`），保持和之前一样的冷跑口径；需要时把它改成 `true`。

- ais_bench 自带的 `--num-warmups` 默认只发 **1 条**请求、而且是顺序发送，请求数少的用例里首条冷请求对均值影响很大
- 内置预热会按**本用例的并发数和输出长度**打 `rounds` 轮，每轮 `并发` 条请求并发发出，预热完成后再等 `sleep` 秒让服务侧队列收敛

```jsonc
"warmup": {
  "enabled": false,     // 总开关，默认关闭
  "rounds": 2,          // 预热轮数
  "requests": 0,        // 覆盖总请求数；0 = rounds * 并发
  "concurrency": 0,     // 0 = 跟随用例并发
  "max_out_len": 0,     // 0 = 跟随用例输出长度
  "timeout": 600,       // 单条预热请求超时（秒）
  "sleep": 2.0,         // 预热后等待秒数
  "reuse_prompts": false
}
```

`reuse_prompts=false`（默认）会给预热 prompt 加随机后缀。原因是预热如果直接复用语料里的 prompt，服务端会把这段前缀缓存写进去，正式压测时这些题就变成缓存命中，指标会偏乐观。加上后缀后 prompt 长度基本不变，但前缀不可复用，只起到「把服务和图跑热」的作用。如果想复现 ais_bench 原有行为，把它设为 `true`。

预热日志示例：

```text
  [warm] ShareGPT-in16384-bs32-8并发 预热: 16 请求 / 2 轮, 并发 8, 输出上限 1024 tokens
  [warm] 第 1/2 轮: 8/8 成功, 平均 12.41s, TTFT 1.83s
  [warm] 第 2/2 轮: 8/8 成功, 平均 4.06s, TTFT 1.79s
  [warm] 冷热差: 首轮 12.41s -> 末轮 4.06s (3.1x)
  [warm] 等待 2.0s 让服务侧队列收敛
```

命令行覆盖：

```bash
python3 run_perf.py --mode performance-c --warmup-rounds 4      # 加长预热
python3 run_perf.py --mode performance-c --warmup-concurrency 32 # 预热并发另设
python3 run_perf.py --mode performance-c --no-warmup            # 关闭内置预热
python3 run_perf.py --mode performance-c --ais-num-warmups 0     # 只保留内置预热
```

预热失败只告警、不中断压测；`--skip-run` 时不会预热。`performance-vl` 走 evalscope perf，目前没有接入这套预热。

## 6. 版本

- v1.6.1：完善性能测试预热，按用例并发预热多轮，新增 warmup 配置与冷热差输出
- v1.6.0：新增 LiveCodeBench 代码生成精度模式，支持按难度筛选，题库自动下载
- v1.5.2：VLM 精度默认数据集改为 MMMU-Pro，支持 4 选项 / 10 选项 / vision
- v1.5.1：新增 VLM 多模态性能压测模式（random_vl）
- v1.5.0：新增 VLM 多模态精度模式（MMMU）
- v1.4.0：配置拆分为公共文件和模式专属文件，Performance 拆分为 `performance-c` / `performance-n`
- v1.3.1：Performance concat / native 配置完全隔离
- v1.3.0：新增 AISBench 原生 ShareGPT 多轮压测
- v1.2.1：支持混合运行
- v1.2.0：新增 evalscope 精度测试
- v1.1.0：新增原生 SWE-bench Agent 模式
- v1.0.0：初始版本
