# 一、测试前准备

## 1、benchmark 下载

```shell
# 安装 ais_bench
git clone https://github.com/AISBench/benchmark.git
cd benchmark
pip3 install -e ./ --use-pep517

pip3 install -r requirements/api.txt
pip3 install -r requirements/extra.txt
```

## 2、数据集下载

### （1）GSM8K

```shell
cd /usr/local/python3.11.15/lib/python3.11/site-packages/ais_bench/datasets/
wget http://opencompass.oss-cn-shanghai.aliyuncs.com/datasets/data/gsm8k.zip
unzip gsm8k.zip
```

### （2）ShareGPT

```shell
wget -c https://hf-mirror.com/datasets/anon8231489123/ShareGPT_Vicuna_unfiltered/resolve/main/ShareGPT_V3_unfiltered_cleaned_split.json -O ./ShareGPT_V3_unfiltered_cleaned_split.json
```

### （3）SWE-bench

```shell
# 下载 SWE-bench 测试集 (parquet 格式)
wget https://huggingface.co/datasets/princeton-nlp/SWE-bench/resolve/main/data/test-00000-of-00001.parquet
```

## 3、数据集解释

本体系涉及三类数据集，分别服务**性能测试、推理精度、Agent 落地能力**三个维度。

### （1）三类数据集特征与目的

| 维度 | 💬 ShareGPT | 🧮 GSM8K | 💻 SWE-bench |
|------|------------|----------|-------------|
| **数据形态** | 多轮自然对话 | 数学题 + 分步答案 | 代码库 + issue + 补丁 + 测试 |
| **来源** | ShareGPT.com 用户与 ChatGPT 的真实对话，约 9 万组多轮对话 | 人工撰写的小学数学应用题，每题附分步推理答案 | 12 个热门 Python 开源仓库的真实 GitHub issue + 对应 PR |
| **特征** | 自然语言、多轮、长度分布极不均匀，贴近真实线上流量 | 题干短、答案唯一且为数字，**可精确判分** | 输入是代码库快照 + issue 描述，输出要求生成**代码补丁 (patch)** |
| **判分方式** | 不判分（压测语料） | 最终数字精确匹配 | 单元测试执行结果 |
| **主要指标** | 吞吐 / TTFT / TPOT | Accuracy + 性能指标 | 解决率 pass@1 |
| **典型规模** | ~9 万组对话 | 8.5K / 1K | 2294（完整版） |
| **在本体系中角色** | 性能数据集语料源 ⭐ | 性能数据集种子 + ais_bench 插件 | 能力评测（独立体系） |

### （2）ShareGPT 数据结构

```json
[
  {
    "id": "...",
    "conversations": [
      { "from": "human", "value": "怎么学编程？" },
      { "from": "gpt",   "value": "建议从……" },
      ...
    ]
  }, ...
]
```

- 多轮对话，角色交替 `human / gpt`
- 制作为性能数据集时，可按 `--role human|all` 只取用户提问或全部角色作为语料
- 在本体系中用作**语料池**：process_dataset.py 从中抽取真实文本，拼接出精确 `input_len` 的压测样本
- 三种构型：**concat 拼接**、**tile 平铺**、**prefix 前缀共享**（详见第 7 节）

### （3）GSM8K 数据结构

```json
{
  "question": "Natalia sold clips to 48 friends...",
  "answer": "48/2 = 24\n24*3 = 72\n#### 72"
}
```

- 答案以 `#### 数字` 结尾，抽取最终数字即可**精确判分**
- 8.5K 训练集 + 1K 测试集；测试集即可作为性能数据集的种子文本
- ais_bench 自带 `gsm8k_gen_0_shot_cot_str` 数据集插件，统计答题正确率
- process_dataset.py 的 `--datasettype GSM` 分支把 question 文本用 tokenizer 补齐/截断到固定长度

### （4）SWE-bench 数据结构

```json
{
  "repo": "django/django",
  "instance_id": "django__django-12345",
  "problem_statement": "issue 描述...",
  "patch": "gold patch（标准答案补丁）",
  "test_patch": "测试补丁",
  "FAIL_TO_PASS": ["修复前失败、修复后应通过的测试"],
  "PASS_TO_PASS": ["修复前后都应通过的测试"]
}
```

- 模型需在**完整仓库环境**中理解 issue、定位文件、生成 diff 补丁
- 把模型补丁打进代码库 → 跑 FAIL_TO_PASS + PASS_TO_PASS 测试 → 全部通过才算解决 (Solved)
- 子集 SWE-bench Lite (300 题) / Verified (500 题) 降低评测成本
- **与 ShareGPT/GSM8K 差异**：输入是整个代码仓库上下文（超长上下文），输出是结构化代码而非自然语言
- 不进 ais_bench 的 `--datasets` 插件体系，用**SWE-bench 官方 harness** 独立评测

### （5）评测原理

#### 精度评测

- **GSM8K · 规则判分**：提示词让模型 "逐步推理，最后以 `#### 答案` 结尾"；评测时用正则抽取末尾数字，与标注精确比对 → Accuracy = 正确题数 / 总题数
- **GSM8K · 0-shot CoT**：不给示例，靠指令触发思维链；ais_bench 中的数据集名 `gsm8k_gen_0_shot_cot_str_perf` 即此模式
- **SWE-bench · 执行判分**：无固定答案，模型输出补丁 → 打入代码库 → 运行 `FAIL_TO_PASS` 与 `PASS_TO_PASS` 测试集 → 全绿记为 Solved

#### 性能评测（所有数据集通用）

| 指标 | 含义 |
|------|------|
| **TTFT** | 首 token 延迟，含排队 + Prefill，决定"首字快不快" |
| **TPOT** | 每输出 token 平均时间，决定"打字机速度"，由 Decode 主导 |
| **ITL** | 平均 token 间隔 |
| **E2EL** | 端到端总延迟 = TTFT + 输出长度 × TPOT，用户感知"总耗时" |
| **token/s** | 输出吞吐 / 总吞吐 / 请求吞吐，决定"机器吞吐量"与成本 |

分位数统计：除平均值外还输出 P50/P75/P90/P99，长尾更能暴露调度问题。

### （6）为什么不同数据集 / 不同构型测出的性能不一样？

同一模型、同并发、同标称长度，换数据集或换构型，数字可能差好几倍 —— **根因不在模型，而在数据是否触发缓存复用**。

- **16 条全相同（tile 平铺）→ 命中率飙到 ~99%**：前缀完全相同 → Prefix-Cache 命中率直冲 ~99%；Prefill 几乎被缓存"白嫖"，TTFT 虚低、吞吐虚高 —— 测的是**缓存复用性能，不是真实推理性能**
- **16 条各不同（concat 拼接）→ 缓存基本不命中**：前缀互异 → Prefix-Cache 命中率回归正常低水平；每次请求都真实做完整 Prefill，TTFT / 吞吐反映**真实 decode + prefill 成本**

**控制变量的本质**：性能数字 = 模型能力 × 数据形状 × 缓存命中。只有数据形状（长度、并发、**重复率**）固定且**不意外触发缓存**，差异才能归因于模型/版本。

| 数据集 | 典型长度 | 内容重复率 | Prefill 占比 | 对缓存敏感度 | 结果倾向 |
|--------|---------|-----------|-------------|-------------|---------|
| **GSM8K（平铺）** | 短 | 极高（同一题重复） | 低，但易被缓存吃掉 | 极高 | 易出现虚高假象 |
| **ShareGPT（concat）** | 分布广 | 低（不同对话拼接） | 中 | 中 | 贴近真实，最适合作通用基线 |
| **ShareGPT（prefix）** | 长 | 前 90% 相同 | 高，但前缀显式缓存 | 显式专项 | 专测缓存命中收益 |
| **SWE-bench** | 超长（整库上下文） | 低 | 极高 | 低（无前缀复用） | Prefill 成本主导，吞吐偏低 |

> 💡 **结论**：不要跨数据集 / 跨构型直接比绝对数字。要比，就在**同一数据集、同一构型、同一定长、同并发**下比。

## 4、数据集制作

> 脚本源码见仓库 `process_dataset.py`，下文仅说明参数与用法。

### process_dataset.py 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--bs` | int | 4096 | 数据集条数，约定为 `并发 × 4` |
| `--inputlen` | int | 2048 | 每条样本目标输入 token 长度 |
| `--datasettype` | str | GSM | 数据集类型：GSM / SHAREGPT / SWEBENCH / VQA / VID / VSD |
| `--datapath` | str | /workspace/benchmark/ | VQA/VID/VSD 的样本路径 |
| `--modelpath` | str | "" | 模型路径（用于加载 tokenizer） |
| `--sharegptpath` | str | ./ShareGPT_V3...json | ShareGPT 原始 JSON 路径（SHAREGPT 专用） |
| `--swebenchpath` | str | ./SWE-bench/...parquet | SWE-bench parquet 路径（SWEBENCH 专用） |
| `--mode` | str | concat | 构型：concat=拼接不同对话 / tile=重复单条 / prefix=前缀共享 |
| `--prefix_ratio` | float | 0.9 | prefix 模式下共享前缀占比 (0~1)，默认 90% |
| `--role` | str | human | ShareGPT 抽取角色：human=仅用户提问 / all=全部角色 |

### 产物命名规则

| 数据集类型 | 普通模式 | prefix 模式 |
|-----------|---------|------------|
| GSM | `GSM8K-in{LEN}-bs{BS}.jsonl` | —（无 pfx） |
| ShareGPT | `ShareGPT-in{LEN}-bs{BS}.jsonl` | `ShareGPT-in{LEN}-bs{BS}-pfx{N}.jsonl` |
| SWE-bench | `Swebench-in{LEN}-bs{BS}.jsonl` | `Swebench-in{LEN}-bs{BS}-pfx{N}.jsonl` |

> 共同约定：**幂等生成**（产物存在即跳过）、**tokenizer 必须与被测模型一致**（token 长度才有意义）、**条数 = 并发 × 4**（与 run_perf.py 的 `bs = concurrency * 4` 对齐）。

### 使用示例

```shell
# 生成 GSM8K 数据集（输入长度 32768，条数 16）
python3 process_dataset.py --datasettype GSM --bs 16 --inputlen 32768 --modelpath /models/DeepSeek-V4-Flash

# 生成 ShareGPT concat 数据集
python3 process_dataset.py --datasettype SHAREGPT --bs 64 --inputlen 32768 \
    --mode concat --modelpath /models/DeepSeek-V4-Flash \
    --sharegptpath ./ShareGPT_V3_unfiltered_cleaned_split.json

# 生成 ShareGPT prefix 数据集（前缀 90% 共享，压测 Prefix-Cache）
python3 process_dataset.py --datasettype SHAREGPT --bs 16 --inputlen 32768 \
    --mode prefix --prefix_ratio 0.9 --modelpath /models/DeepSeek-V4-Flash \
    --sharegptpath ./ShareGPT_V3_unfiltered_cleaned_split.json

# 生成 SWE-bench 数据集
python3 process_dataset.py --datasettype SWEBENCH --bs 32 --inputlen 32768 \
    --mode concat --modelpath /models/DeepSeek-V4-Flash \
    --swebenchpath ./test-00000-of-00001.parquet
```

### ShareGPT 三种构型对比

| 构型 | mode | 做法 | 用途 |
|------|------|------|------|
| 🔗 **concat** | concat | 每条样本由多条不同对话拼接，token 分布最接近真实 | 常规吞吐/延迟压测，最适合作通用基线 |
| 🔁 **tile** | tile | 取一条种子对话重复到目标长度，内容单一 | 对照实验：排除内容多样性的干扰 |
| 📐 **prefix** | prefix | 前 `prefix_ratio`（默认 90%）token 跨样本相同，后缀各自变化 | 专压 Prefix-Cache 命中率，验证缓存收益 |

### 各数据集制作方式差异

| 类型 | 种子语料 | 定长方法 | 产物 | 用途 |
|------|---------|---------|------|------|
| **GSM** | GSM8K.jsonl 的 question | `datatmp_generator`：短文本重复补齐，长文本截断 | GSM8K-in{LEN}-bs{BS}.jsonl | 文本推理压测 |
| **SHAREGPT** | ShareGPT_V3 多轮对话（按角色抽取） | `fit_to_token_len` 迭代收敛；concat/tile/prefix 三构型 | ShareGPT-in{LEN}-bs{BS}[-pfx{N}].jsonl | 真实负载/前缀缓存压测 |
| **SWEBENCH** | SWE-bench parquet 的 problem_statement | 复用 ShareGPT 的收敛与前缀共享逻辑 | Swebench-in{LEN}-bs{BS}[-pfx{N}].jsonl | 代码类语料压测 |
| **VQA** | 固定问题 | 同 GSM（单条平铺）；额外生成 annotation.json | Textvqa-in{LEN}-bs{BS}.jsonl + annotation | 多模态图文压测 |
| **VID** | 固定问题 + A/B/C/D 选项 | 同 GSM；生成 qa.json + answer.json 成对文件 | Videobench-in{LEN}-bs{BS}-qa/answer.json | 视频理解压测 |
| **VSD** | 15s 音频切片 (pydub) | 音频按秒拼接（≥15s 整数倍），按并发数复制 | {N}second/{bs}/m{len}_*.wav | 语音压测（不入 LLM 请求） |

---

# 二、开始测试

## 1、启动好 xllm 服务

## 2、配置 run_perf.cfg

所有可修改参数放在脚本同目录下的 `run_perf.cfg` 中，支持中文注释。**最外层固定只有四个 key：`mode`、`agent`、`accuracy`、`performance`**。`mode` 支持单个模式或 `performance / agent / accuracy` 任意组合；各模式各自的模型配置、benchmark 配置和自动准备开关完全分开，互不混用。

```jsonc
{
  // 支持单个、逗号字符串或数组；混合模式按数组/字符串顺序执行
  "mode": ["agent", "performance", "accuracy"],

  // Agent 模式专用配置
  "agent": {
    "dataset": "lite",              // lite / verified / full / multilingual
    "count": 10,                    // 1=第 1 条，10=前 10 条，0=全部
    "step_limit": 200,
    "work_dir": "outputs/agent",
    "run_mode": "all",              // infer / eval / all
    "model_cfg_params": {
      "path": "/export/home/models/DeepSeek-V4-Flash-w8a8-mtp",
      "model": "DeepSeek-V4-Flash-w8a8-mtp",
      "host_ip": "11.87.191.83",
      "host_port": 18004
    },
    "auto_prepare": true,
    "benchmark_repo": "https://gh-proxy.com/https://github.com/AISBench/benchmark.git",
    "benchmark_dir": "",
    "benchmark_ref": "",
    "install_requirements": true
  },

  // Accuracy 精度测试专用配置
  "accuracy": {
    "dataset": "gpqa_diamond",
    "eval_batch_size": 8,
    "work_dir": "outputs/accuracy",
    "auto_prepare": true,
    "model_cfg_params": {
      "model": "DeepSeek-V4-Flash-w8a8-mtp",
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

  // Performance 模式专用配置
  "performance": {
    // concat=拼接压测；native_multiturn=AISBench 原生 ShareGPT 多轮压测
    "kind": "concat",

    "model_cfg_params": {
      "path": "/export/home/models/DeepSeek-V4-Flash-w8a8-mtp",
      "model": "DeepSeek-V4-Flash-w8a8-mtp",
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
      "dataset_types": ["gsm", "sharegpt", "swebench"],
      "raw_gsm_path": "/data/GSM8K.jsonl",
      "raw_sharegpt_path": "/data/ShareGPT_V3_unfiltered_cleaned_split.json",
      "raw_swebench_path": "/data/SWE-bench/data/test-00000-of-00001.parquet"
    },

    "native_multiturn": {
      "conversation_count": 100, // 取前 N 组有效多轮对话；0=全量
      "infer_mode": "every",    // every / last / every_with_gt
      "concurrencies": [1, 8, 16], // 原生多轮专属并发
      "max_out_len": 512,       // 原生多轮专属输出长度
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
| `mode` | 单个模式或混合模式：performance / agent / accuracy 任意组合，支持字符串和数组 |

### Agent 节点字段

| 字段 | 说明 |
|------|------|
| `agent.dataset` | 官方 SWE-bench 数据集：lite / verified / full / multilingual |
| `agent.count` | 按数据集原始顺序取前 N 条；0 表示全部 |
| `agent.step_limit` | 单个 instance 的最大步数 |
| `agent.work_dir` | Agent 输出目录 |
| `agent.run_mode` | infer=只推理，eval=只评测，all=推理 + 评测 |
| `agent.model_cfg_params` | Agent 模式专用模型配置，写入自动生成的 SWE-bench 配置 |
| `agent.auto_prepare` | 是否自动执行 `setup_swebench.sh` |
| `agent.benchmark_repo` | benchmark 源码仓库 |
| `agent.benchmark_dir` | benchmark 本地目录；留空使用脚本旁的 `benchmark/` |
| `agent.benchmark_ref` | benchmark 分支或 tag |
| `agent.install_requirements` | 是否自动安装 benchmark requirements |

### Accuracy 节点字段

| 字段 | 说明 |
|------|------|
| `accuracy.dataset` | evalscope 数据集，当前默认 `gpqa_diamond` |
| `accuracy.eval_batch_size` | evalscope `--eval-batch-size` |
| `accuracy.work_dir` | 精度测试输出目录 |
| `accuracy.auto_prepare` | 缺失 evalscope 时是否自动 `pip install evalscope` |
| `accuracy.model_cfg_params` | 精度测试专用模型和服务配置 |
| `accuracy.generation_config` | 生成参数，等价于 `--generation-config` |
| `accuracy.dataset_args` | 数据集参数，等价于 `--dataset-args` |

### Performance 公共字段

| 字段 | 说明 |
|------|------|
| `performance.kind` | performance 子类型：concat=拼接压测，native_multiturn=AISBench 原生 ShareGPT 多轮压测 |
| `performance.model_cfg_params` | Performance 两种子类型共用的模型和服务配置；`path` 同时用于 tokenizer |
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
| `performance.native_multiturn.max_out_len` | 原生多轮专属单次请求最大输出 token |
| `performance.native_multiturn.request_rate` | 原生多轮专属请求发送速率；0=打满 |
| `performance.native_multiturn.work_dir` | AISBench 原生多轮输出目录 |
| `performance.native_multiturn.result_dir` | 原生多轮 Excel 输出目录 |
| `performance.native_multiturn.raw_sharegpt_path` | 原生多轮专属原始 ShareGPT 路径；留空使用公共 `raw_dataset_dir` |
| `performance.native_multiturn.generation_kwargs` | 原生多轮生成参数 |

> 💡 **路径自动定位**：`AIS_BENCH_ROOT` 通过 `import ais_bench_benchmark` 自动定位安装目录，支持标准安装和 `pip install -e` 开发安装。
>
> 💡 **Performance 数据集**：优先从 `performance.concat.dataset_dir` 查找；缺失时自动下载原始数据并调用 `process_dataset.py` 生成。
>
> 💡 **Agent 模式**：读取 `agent.model_cfg_params`，自动生成原生 SWE-bench 配置；`agent.count` 按官方数据集原始顺序截取。
>
> 💡 **Accuracy 模式**：读取 `accuracy.model_cfg_params`，自动安装 evalscope 并执行 GPQA Diamond 精度测试。
>
> 💡 `performance.model_cfg_params.path` 同时作为 tokenizer 模型路径，不再需要单独配置 `MODEL_PATH`。

## 3、启动测试

run_perf.py 支持三种模式：performance（性能压测）、agent（原生 SWE-bench）、accuracy（evalscope 精度测试），并支持任意组合混合运行。Performance 内部支持 `concat` 拼接压测和 `native_multiturn` 原生 ShareGPT 多轮压测。

### 模式三：Accuracy 精度测试

```shell
python3 run_perf.py --mode accuracy \
    --model DeepSeek-V4-Flash-w8a8-mtp \
    --host-ip 11.87.191.83 \
    --host-port 18004
```

等价于原来的 `gpqa.sh`：

```shell
evalscope eval \
  --model DeepSeek-V4-Flash-w8a8-mtp \
  --api-url http://11.87.191.83:18004/v1 \
  --api-key EMPTY \
  --eval-type openai_api \
  --datasets gpqa_diamond \
  --eval-batch-size 8 \
  --generation-config '{"temperature":1.0,"top_p":0.95,"max_tokens":130000,"timeout":900,"retries":2}' \
  --dataset-args '{"gpqa_diamond":{"filters":{"remove_until":"</think>"}}}'
```

### Performance 子类型：原生 ShareGPT 多轮

使用 AISBench 原生 `sharegpt_gen` 数据集和 `vllm_api_stream_chat_multiturn` 模型任务：

```shell
python3 run_perf.py --mode performance \
    --performance-kind native_multiturn \
    --native-conversation-count 100 \
    -c 1 8 16 \
    --max-out-len 512 \
    --request-rate 0
```

配置文件等价写法：

```jsonc
"performance": {
  "kind": "native_multiturn",
  "native_multiturn": {
    "conversation_count": 100,
    "infer_mode": "every",
    "concurrencies": [1, 8, 16],
    "max_out_len": 512,
    "request_rate": 0
  }
}
```

说明：

- `conversation_count=100` 表示截取前 100 组有效多轮对话；`0` 表示全量
- 有效对话会按 AISBench 规则过滤：轮数 ≥ 2、总轮数为偶数、第一轮来自 human
- `infer_mode=every` 会按多轮请求统计性能指标
- 原生多轮不生成 `ShareGPT-in{LEN}-bs{BS}.jsonl`，也不经过 `process_dataset.py`
- 原生多轮没有固定 `input_len`，不能和 concat 模式的固定输入长度直接做同维度对比
- concat 的 `performance.concat.input_len` / `performance.concat.concurrencies` / `performance.concat.default_max_out_len` / `performance.concat.default_request_rate` / `performance.concat.default_pfx` 在 native_multiturn 下全部忽略
- native_multiturn 使用自己的 `performance.native_multiturn.concurrencies` / `max_out_len` / `request_rate`
- `performance.model_cfg_params`、benchmark 环境配置、`raw_dataset_dir` 和下载 URL 是两种子类型的公共配置
- 命令行 `-c` / `--max-out-len` / `--request-rate` 只覆盖当前 performance 子类型；不传时分别读取各自 cfg 默认值
- 输出目录：
  - AISBench：`outputs/performance/native_multiturn/`
  - Excel：`results/performance/native_multiturn/`

### 模式四：混合运行


`mode` 支持一个、两个或三个模式的任意组合，并按给定顺序执行。

配置文件写法：

```jsonc
"mode": ["agent", "performance", "accuracy"]
```

等价字符串写法：

```jsonc
"mode": "agent,performance,accuracy"
```

命令行写法：

```shell
# 空格分隔
python3 run_perf.py --mode agent performance accuracy

# 逗号分隔
python3 run_perf.py --mode agent,performance,accuracy

# 重复 --mode
python3 run_perf.py --mode accuracy --mode agent
```

混合运行时会自动切换配置节点：

```text
agent       -> agent 节点
performance -> performance 节点
accuracy    -> accuracy 节点
```

同一模式会自动去重，不会重复执行。

### 模式一：JSON 用例驱动（推荐）

用例文件 `cases.json`：

```json
{
  "1": "32768-1024-4-0.5",
  "2": "gsm:32768-1024-4-0.5",
  "3": "sharegpt:16384-1024-8-0-90",
  "4": "swebench:16384-1024-16-1"
}
```

用例串格式：`[dataset_type:]输入长度-输出长度-并发-request_rate[-pfx]`

- `dataset_type`：可选，`gsm` / `sharegpt` / `swebench`，省略默认 `sharegpt`
- `输入长度`：数据集名里的 in{LEN}
- `输出长度`：写入 `max_out_len`
- `并发`：即 batch_size；数据集条数 bs = 并发 × 4
- `request_rate`：0 = 尽量打满
- `pfx`（可选）：前缀缓存重复率%，如 90 表示前缀 90% 共享

也兼容对象形式：

```json
{
  "1": {"in": 32768, "out": 1024, "concurrency": 4, "rate": 0.5, "dataset_type": "gsm"},
  "2": {"in": 16384, "out": 2048, "concurrency": 8, "rate": 0, "pfx": 90}
}
```

运行：

```shell
python3 run_perf.py --cases cases.json \
    --path /export/home/models/xxx \
    --model xxx \
    --host-ip 11.87.191.83 \
    --host-port 18004
```

### 模式二：简易模式（命令行笛卡尔积）

```shell
# 单数据集类型（默认 sharegpt）
python3 run_perf.py -i 30000 -c 1 8 16 \
    --max-out-len 1024 \
    --request-rate 0.5 \
    --path /export/home/models/xxx \
    --model xxx \
    --host-ip 11.87.191.83 \
    --host-port 18004

# 多数据集类型
python3 run_perf.py -i 32768 -c 1 8 16 \
    --dataset-type gsm sharegpt swebench \
    --max-out-len 1024 \
    --path /export/home/models/xxx \
    --host-ip 11.87.191.83 --host-port 18004

# 带 pfx 前缀缓存压测
python3 run_perf.py -i 32768 -c 4 8 --pfx 90 \
    --max-out-len 1024 \
    --path /export/home/models/xxx \
    --host-ip 11.87.191.83 --host-port 18004

# 只解析已有输出（不重新跑）
python3 run_perf.py -i 32768 -c 1 8 16 --skip-run
```

简易模式笛卡尔积：**数据集类型 × 输入长度 × 并发 × pfx**，自动生成所有组合。

### 全部命令行参数

| 参数 | 说明 |
|------|------|
| `--mode` | 单个或混合模式：performance / agent / accuracy；支持空格、逗号和重复传参 |
| `--performance-kind` | performance 子类型：concat / native_multiturn |
| `--native-conversation-count` | 原生多轮取前 N 组有效对话；0=全量 |
| `--native-infer-mode` | 原生多轮推理模式：every / last / every_with_gt |
| `--native-work-dir` | 原生多轮 AISBench 输出目录 |
| `--native-result-dir` | 原生多轮 Excel 输出目录 |
| `--cases` | concat JSON 用例文件路径；native_multiturn 不支持 |
| `-i / --input-len` | concat 输入长度列表；native_multiturn 忽略 |
| `-c / --concurrency` | performance 通用并发覆盖；concat/native 分别使用各自默认值 |
| `--dataset-type` | concat 数据集类型列表：gsm / sharegpt / swebench；native_multiturn 忽略 |
| `--max-out-len` | performance 通用输出长度覆盖；concat/native 分别使用各自默认值 |
| `--request-rate` | performance 通用请求速率覆盖；concat/native 分别使用各自默认值 |
| `--pfx` | concat 前缀缓存重复率% 列表；native_multiturn 忽略 |
| `--path` | 模型权重路径 |
| `--model` | 模型名 |
| `--host-ip` | 服务 IP |
| `--host-port` | 服务端口 |
| `--api-key` | agent / accuracy / native_multiturn OpenAI API Key |
| `--accuracy-dataset` | accuracy 模式 evalscope 数据集 |
| `--accuracy-batch-size` | accuracy 模式并发批次大小 |
| `--accuracy-work-dir` | accuracy 模式输出目录 |
| `--excel` | Excel 输出路径（默认脚本所在目录下） |
| `--skip-run` | 只解析已有输出，不重新跑 |

## 4、输出

Performance concat 的 outputs 和 Excel 统一落在**脚本所在目录**下，按 `(数据集类型, 输入长度, pfx)` 分组生成 Excel；原生多轮输出在 `outputs/performance/native_multiturn/` 和 `results/performance/native_multiturn/`；Agent 输出在 `outputs/agent/`；Accuracy 输出在 `outputs/accuracy/`。

```
性能测试结果_sharegpt_in32768.xlsx
性能测试结果_gsm_in32768.xlsx
性能测试结果_swebench_in32768.xlsx
性能测试结果_sharegpt_in32768_pfx90.xlsx
```

每个 Excel 包含：
- **汇总 sheet**：配置名称、数据集类型、输入长度、输出长度、并发数、request_rate、pfx、平均E2EL/TTFT/TPOT/ITL、吞吐、请求数
- **每用例明细 sheet**：P50/P75/P90/P99 分位数据、通用指标

## 5、自动化流水线关键设计

- **路径自动定位**：`AIS_BENCH_ROOT` 通过 `import ais_bench_benchmark` 自动定位安装目录，支持标准安装和 `pip install -e` 开发安装；脚本放任意位置都能跑，outputs 和 Excel 统一落在脚本所在目录
- **配置外置**：所有可修改参数放在 `run_perf.cfg` 的 `mode / agent / accuracy / performance` 四个节点中，不再需要改脚本本身；`performance.model_cfg_params.path` 同时作为 tokenizer 模型路径
- **配置注入靠正则改文件**：`set_model_cfg()` 用正则把参数写进 ais_bench 的模型配置 py，不侵入 ais_bench 代码；**静态配置**（path/model/host_ip/host_port）启动时写一次，**动态配置**（batch_size/max_out_len/request_rate）每个用例跑之前单独写
- **数据集绑定靠软链**：`ln -sf 选中.jsonl test.jsonl train.jsonl`，同时软链 test 和 train（ais_bench 启动会检查 train.jsonl 是否存在），切换用例零拷贝
- **结果目录只认"本次新增"**：运行前快照 outputs 目录，运行后只在新目录里找 gsm8k.csv —— **防止失败用例复用历史结果、数值张冠李戴**
- **失败不中断**：单用例异常被捕获记为 failed，继续跑下一个；失败原因写入 Excel 明细 sheet
- **数据集自动生成**：找不到数据集时自动调用 process_dataset.py 生成，无需手动分步操作
- **ais_bench 输出实时可见**：stdout/stderr 不捕获，直接透传到终端
