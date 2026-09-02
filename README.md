# xllm 自动化性能测试工具集

## 版本历史

### v1.1.0 — 2026-09-02

- **`run_perf.py` 新增 `agent` 模式**
  - `mode=performance`：保留原有拼接压测数据集流程
  - `mode=agent`：直接跑原生 SWE-bench
- **Agent 模式支持官方数据集**
  - `lite`
  - `verified`
  - `full`
  - `multilingual`
- **Agent 模式支持按顺序取前 N 条**
  - `agent_count=1`：只跑第 1 条
  - `agent_count=10`：跑前 10 条
  - `agent_count=0`：跑全部
- **Agent 模式自动准备环境**
  - 自动检查 `mini-swe-agent`
  - 自动检查 `swebench`
  - 缺失时自动克隆并安装
- **Agent 模式自动生成原生 SWE-bench 配置**
  - 自动读取 `run_perf.cfg` 里的模型服务信息
  - 自动生成 `outputs/agent_configs/` 下的配置文件
  - 自动调用 `ais_bench --mode all`
- **新增命令行参数**
  - `--mode performance|agent`
  - `--agent-dataset lite|verified|full|multilingual`
  - `--agent-count N`

### v1.0.3 — 2026-09-02

- **`run_perf.py` 启动前自动准备环境**
  - 自动检测 `ais_bench` / benchmark 是否已安装
  - 缺失时自动 clone `AISBench/benchmark`
  - 自动执行 `pip install -e . --use-pep517`
  - 可选自动安装 `requirements/api.txt` 和 `requirements/extra.txt`
  - 已安装则直接跳过，不重复下载/安装
- **自动准备原始数据集**
  - GSM8K：缺失时自动下载并解压 `gsm8k.zip`
  - ShareGPT：缺失时自动下载 `ShareGPT_V3_unfiltered_cleaned_split.json`
  - SWE-bench：缺失时自动下载 `test-00000-of-00001.parquet`
  - 只下载本次实际用到的数据集类型
  - 已存在则直接复用
- **新增自动准备配置项**
  - `auto_prepare`
  - `benchmark_repo`
  - `benchmark_dir`
  - `benchmark_ref`
  - `install_requirements`
  - `raw_dataset_dir`
  - `gsm8k_url`
  - `sharegpt_url`
  - `swebench_url`
- **默认下载目录**
  - 原始数据集默认放在脚本同目录的 `raw_datasets/` 下
- **保持原有流程不变**
  - 原始数据准备完成后，继续调用 `process_dataset.py` 生成压测数据集
  - 已生成的 jsonl 数据集仍然自动跳过

### v1.0.2 — 2026-08-31

- **新增 `gen_datasets.py`**：提前批量生成压测数据集
  - 读取同一个 `run_perf.cfg`，无需额外配置
  - 按 `dataset_types × input_len × concurrencies × pfx` 笛卡尔积生成
  - 已存在的数据集自动跳过（幂等，可重复跑）
  - 支持 `--dry-run` 只打印计划不实际执行
  - GSM/ShareGPT/SWE-bench 全支持，原始路径从 cfg 读取
  - 生成到脚本同目录，`run_perf.py` 跑的时候直接用

### v1.0.1 — 2026-08-24

- **run_perf.py**
  - Excel 输出文件名带时间戳，避免重跑覆盖之前的结果
  - `bind_dataset` 同时软链 `test.jsonl` 和 `train.jsonl` 到 ais_bench 期望的 `datasets/gsm8k/` 路径
  - `AIS_BENCH_ROOT` 通过 `import ais_bench_benchmark` 自动定位，支持标准安装和 `pip install -e`
  - 配置外置到 `run_perf.cfg`，不再需要改脚本本身
  - `model_cfg_params.path` 同时作为 tokenizer 模型路径，去掉单独的 `MODEL_PATH`
  - 数据集找不到时自动调用 `process_dataset.py` 生成
  - 支持 gsm / sharegpt / swebench 三种数据集类型
  - 用例串格式 `[dataset_type:]输入-输出-并发-rate[-pfx]`
  - JSON 用例驱动 + 简易模式（笛卡尔积）
  - ais_bench stdout/stderr 直接透传到终端
  - outputs 和 Excel 统一落在脚本所在目录

### v1.0.0 — 2026-08-21

- 初始版本
- 包含 `run_perf.py`、`run_perf.cfg`、`process_dataset.py`、`xllm自动化性能测试.md`
- ais_bench 自动性能测试脚本（JSON 用例驱动）
- 数据集制作脚本（GSM / ShareGPT / SWE-bench）
- 完整使用文档

## 文件说明

| 文件 | 说明 |
|------|------|
| `run_perf.py` | ais_bench 自动化测试脚本，支持 performance 压测和 agent 原生 SWE-bench |
| `run_perf.cfg` | 配置文件（所有可修改参数外置） |
| `gen_datasets.py` | 提前批量生成压测数据集（准备环境用） |
| `process_dataset.py` | 数据集制作脚本（GSM/ShareGPT/SWE-bench） |
| `xllm自动化性能测试.md` | 完整使用文档 |

## 快速开始

```bash
# 1. 编辑配置；run_perf.cfg 里已内置中文注释
vim run_perf.cfg

# 2. performance 模式：直接运行；缺失的 benchmark / 原始数据集会自动准备
python3 run_perf.py --mode performance --cases cases.json

# 3. agent 模式：原生 SWE-bench，取 Lite 前 10 条
python3 run_perf.py --mode agent --agent-dataset lite --agent-count 10

# 4. （可选）提前批量生成数据集
python3 gen_datasets.py --dry-run   # 先看计划
python3 gen_datasets.py             # 实际生成

# 或简易模式
python3 run_perf.py -i 32768 -c 1 8 16 --max-out-len 1024
```
