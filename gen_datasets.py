#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_datasets.py — 提前批量生成压测数据集

读取 run_perf.cfg，按 dataset_types × input_len × concurrencies × pfx 笛卡尔积
调用 process_dataset.py 生成数据集到脚本所在目录。跑 run_perf.py 时直接复用。

用法:
    python3 gen_datasets.py              # 按 cfg 全量生成
    python3 gen_datasets.py --dry-run    # 只打印要生成什么，不实际执行
"""

import argparse
import json5
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(SCRIPT_DIR, "run_perf.cfg")
PROCESS_DATASET = os.path.join(SCRIPT_DIR, "process_dataset.py")

# 数据集类型 → (文件前缀, 原始路径配置key, process_dataset --datasettype 值)
_DATASET_INFO = {
    "gsm":      ("GSM8K-in",    "raw_gsm_path",      "GSM"),
    "sharegpt": ("ShareGPT-in", "raw_sharegpt_path", "SHAREGPT"),
    "swebench": ("Swebench-in", "raw_swebench_path", "SWEBENCH"),
}


def load_cfg():
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return json5.load(f)


def dataset_filename(dt, input_len, bs, pfx=None):
    prefix = _DATASET_INFO[dt][0]
    if pfx:
        return "{}{}-bs{}-pfx{}.jsonl".format(prefix, input_len, bs, pfx)
    return "{}{}-bs{}.jsonl".format(prefix, input_len, bs)


def main():
    ap = argparse.ArgumentParser(description="提前批量生成压测数据集")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不实际生成")
    args = ap.parse_args()

    cfg = load_cfg()
    perf_cfg = cfg.get("performance", {})
    concat_cfg = perf_cfg.get("concat", {})
    dataset_dir = os.path.join(
        SCRIPT_DIR,
        concat_cfg.get("dataset_dir", "datasets/performance"),
    )
    os.makedirs(dataset_dir, exist_ok=True)
    dataset_types = concat_cfg.get("dataset_types", ["sharegpt"])
    input_lens = concat_cfg.get("input_len", [32768])
    concurrencies = concat_cfg.get("concurrencies", [1, 8, 16])
    pfx_list = [p for p in ([concat_cfg.get("default_pfx")] if concat_cfg.get("default_pfx") else [None])]
    model_path = perf_cfg.get("model_cfg_params", {}).get("path", "")

    if not model_path:
        print("错误: run_perf.cfg 里 performance.model_cfg_params.path 未配置")
        sys.exit(1)

    # 展开 (dt, input_len, bs, pfx) 组合，去重并跳过已存在文件
    tasks = []
    for dt in dataset_types:
        if dt not in _DATASET_INFO:
            print("警告: 未知数据集类型 {}，跳过".format(dt))
            continue
        for il in input_lens:
            for c in concurrencies:
                bs = c * 4
                for pfx in pfx_list:
                    fname = dataset_filename(dt, il, bs, pfx)
                    fpath = os.path.join(dataset_dir, fname)
                    if os.path.exists(fpath):
                        print("[skip] 已存在: {}".format(fname))
                        continue
                    tasks.append((dt, il, bs, pfx, fname, fpath))

    if not tasks:
        print("所有数据集都已存在，无需生成")
        return

    print("计划生成 {} 个数据集:".format(len(tasks)))
    for dt, il, bs, pfx, fname, _ in tasks:
        pfx_str = " pfx={}%".format(pfx) if pfx else ""
        print("  {}  (in={} bs={}{})".format(fname, il, bs, pfx_str))
    print()

    if args.dry_run:
        print("[dry-run] 未实际执行")
        return

    ok, fail = 0, 0
    for dt, il, bs, pfx, fname, _ in tasks:
        _, raw_key, ds_arg = _DATASET_INFO[dt]
        raw_path = concat_cfg.get(raw_key, "")

        cmd = [
            "python3", PROCESS_DATASET,
            "--datasettype", ds_arg,
            "--inputlen", str(il),
            "--bs", str(bs),
            "--modelpath", model_path,
        ]
        if dt == "sharegpt":
            if not raw_path:
                print("[fail] performance.concat.raw_sharegpt_path 未配置，跳过 {}".format(fname))
                fail += 1
                continue
            cmd += ["--sharegptpath", raw_path]
        elif dt == "swebench":
            if not raw_path:
                print("[fail] performance.concat.raw_swebench_path 未配置，跳过 {}".format(fname))
                fail += 1
                continue
            cmd += ["--swebenchpath", raw_path]
        elif dt == "gsm":
            # GSM 原始数据 process_dataset.py 硬编码为 ./GSM8K.jsonl，做软链
            if raw_path and not os.path.exists(os.path.join(dataset_dir, "GSM8K.jsonl")):
                if os.path.exists(raw_path):
                    os.symlink(raw_path, os.path.join(dataset_dir, "GSM8K.jsonl"))
                    print("  [ln ] GSM8K.jsonl -> {}".format(raw_path))

        if pfx:
            cmd += ["--mode", "prefix", "--prefix_ratio", str(pfx / 100.0)]

        print("[gen] {} ...".format(fname))
        proc = subprocess.run(cmd, cwd=dataset_dir, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-10:])
            print("  [fail] 退出码 {}\n{}".format(proc.returncode, tail))
            fail += 1
        else:
            print("  [ok ]")
            ok += 1

    print("\n========== 完成 ==========")
    print("成功: {}  失败: {}".format(ok, fail))


if __name__ == "__main__":
    main()
