# xllm 自动化性能测试工具集

## 版本历史

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
| `run_perf.py` | ais_bench 自动化性能测试脚本 |
| `run_perf.cfg` | 配置文件（所有可修改参数外置） |
| `process_dataset.py` | 数据集制作脚本（GSM/ShareGPT/SWE-bench） |
| `xllm自动化性能测试.md` | 完整使用文档 |

## 快速开始

```bash
# 1. 编辑配置
vim run_perf.cfg

# 2. 运行测试
python3 run_perf.py --cases cases.json

# 或简易模式
python3 run_perf.py -i 32768 -c 1 8 16 --max-out-len 1024
```
