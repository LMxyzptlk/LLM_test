#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LiveCodeBench 代码生成精度评测。

独立脚本：由 run_perf.py --mode lcb 调用，也可以直接执行。

流程：
  1. 读取 LiveCodeBench 题库（默认同目录 test6.jsonl，175 道竞赛题）
  2. 按难度过滤（easy / medium / hard 任意组合；不传则全部）
  3. 并发调用 OpenAI 兼容的 /v1/completions 接口流式生成代码
  4. 用 LiveCodeBench 官方判题逻辑跑测试用例，统计 pass@1
  5. 写出 state/raw/predictions/evaluation/summary/report

依赖：
  - LiveCodeBench 源码目录（--source-dir，目录下应有 lcb_runner/）
  - pip 包：openai、datasets 等（见 LiveCodeBench 的依赖声明）

输出目录结构：
  <output-dir>/
    state.json        逐题状态，支持断点续跑
    raw.json          原始生成记录（含 ttft / tpot / usage）
    predictions.json  抽出的代码
    evaluation.json   判题明细
    summary.json      汇总指标（pass@1、分难度、分平台、token 分布）
    report.md         人读报告

示例：
  python3 livecodebench_eval.py \\
      --base-url http://11.87.191.78:28888/v1 --model glm5 \\
      --output-dir outputs/lcb/demo

  # 只跑 easy + medium，每题少生成一点，先冒烟
  python3 livecodebench_eval.py ... --difficulties easy medium --limit 5
"""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DIFFICULTY_CHOICES = ("easy", "medium", "hard")

# 运行时从 LiveCodeBench 源码目录导入的符号，main() 里填充
LCB = SimpleNamespace()


# ------------------------------
# 参数解析
# ------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="LiveCodeBench 代码生成精度评测",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    data = parser.add_argument_group("数据")
    data.add_argument(
        "--source-dir",
        default=os.path.join(SCRIPT_DIR, "LiveCodeBench-main"),
        help="LiveCodeBench 源码目录（其下应有 lcb_runner/）",
    )
    data.add_argument(
        "--data-file",
        default=os.path.join(SCRIPT_DIR, "test6.jsonl"),
        help="题库文件（每行一道 CodeGenerationProblem 题目）",
    )
    data.add_argument(
        "--difficulties",
        nargs="+",
        choices=DIFFICULTY_CHOICES,
        default=None,
        help="只评测指定难度；不传表示全部题目",
    )
    data.add_argument(
        "--limit",
        type=int,
        default=0,
        help="难度过滤后再取前 N 题，0 表示不限制（冒烟用）",
    )

    model = parser.add_argument_group("模型服务")
    model.add_argument("--base-url", required=True, help="OpenAI 兼容服务地址，如 http://ip:port/v1")
    model.add_argument("--model", required=True, help="模型名")
    model.add_argument("--api-key", default="EMPTY", help="API Key")
    model.add_argument("--max-tokens", type=int, default=65536, help="单题最大生成 token 数")
    model.add_argument("--temperature", type=float, default=0.6, help="采样温度")
    model.add_argument("--request-timeout", type=int, default=1200, help="单题请求超时（秒）")
    model.add_argument("--concurrency", type=int, default=8, help="并发请求数")

    retry = parser.add_argument_group("重试")
    retry.add_argument("--max-retries", type=int, default=10, help="单题最大重试次数")
    retry.add_argument("--retry-base-seconds", type=int, default=30, help="首次重试等待秒数")
    retry.add_argument("--retry-max-seconds", type=int, default=300, help="重试等待上限秒数")

    output = parser.add_argument_group("输出")
    output.add_argument(
        "--output-dir",
        default="",
        help="结果目录；留空则自动生成 outputs/lcb_<时间戳>",
    )
    output.add_argument("--eval-timeout", type=int, default=3600, help="单题判题超时（秒）")
    output.add_argument(
        "--reset-failed",
        action="store_true",
        help="重跑上次请求失败的题（断点续跑时使用）",
    )
    return parser.parse_args(argv)


# ------------------------------
# 依赖导入
# ------------------------------


def load_runner_modules(source_dir):
    """从 LiveCodeBench 源码目录导入所需符号。"""
    source_dir = os.path.abspath(source_dir)
    if not os.path.isdir(os.path.join(source_dir, "lcb_runner")):
        raise SystemExit(
            "找不到 LiveCodeBench 源码目录: {}\n"
            "该目录下应有 lcb_runner/，请用 --source-dir 指定，"
            "或把 LiveCodeBench 仓库放到脚本同级目录。".format(source_dir)
        )

    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)

    try:
        from openai import OpenAI
        from lcb_runner.benchmarks.code_generation import CodeGenerationProblem
        from lcb_runner.evaluation import extract_instance_results
        from lcb_runner.evaluation.compute_code_generation_metrics import codegen_metrics
        from lcb_runner.lm_styles import LMStyle
        from lcb_runner.prompts.code_generation import format_prompt_generation
        from lcb_runner.utils.extraction_utils import extract_code
    except ImportError as exc:
        raise SystemExit(
            "导入 LiveCodeBench 依赖失败: {}\n"
            "请先安装依赖，例如: pip install openai datasets".format(exc)
        )

    LCB.OpenAI = OpenAI
    LCB.CodeGenerationProblem = CodeGenerationProblem
    LCB.extract_instance_results = extract_instance_results
    LCB.codegen_metrics = codegen_metrics
    LCB.LMStyle = LMStyle
    LCB.format_prompt_generation = format_prompt_generation
    LCB.extract_code = extract_code
    return source_dir


# ------------------------------
# 通用工具
# ------------------------------


def save_json(path, value):
    """原子写 JSON，避免中断后留下半个文件。"""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2, default=str)
    os.replace(temporary, path)


def load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as file:
            value = json.load(file)
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        print("Warning: cannot read {}: {}".format(path, exc))
        return {}


def to_jsonable(value):
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    return str(value)


def percentile(values, ratio):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def describe_distribution(values):
    values = [value for value in values if isinstance(value, (int, float))]
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "p99": None, "max": None}
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "p50": percentile(values, 0.50),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def prompt_to_completion_text(prompt):
    """把 prompt（字符串或 chat 消息列表）拍平成 completions 接口的纯文本。"""
    if isinstance(prompt, str):
        return prompt

    parts = []
    for message in prompt:
        if isinstance(message, dict):
            content = message.get("content", "")
        else:
            content = getattr(message, "content", "")
        if isinstance(content, list):
            content = "\n".join(
                str(item.get("text", item)) if isinstance(item, dict) else str(item)
                for item in content
            )
        parts.append(str(content))

    return "\n\n".join(parts)


# ------------------------------
# 题库
# ------------------------------


def load_problems(data_file, difficulties=None, limit=0):
    """读取题库，按难度过滤并按日期排序。"""
    if not os.path.exists(data_file):
        raise SystemExit(
            "找不到题库文件: {}\n"
            "用 --data-file 指定，或通过 run_perf.py --mode lcb 运行"
            "（题库缺失时会按 lcb.data_url 自动下载）".format(data_file)
        )

    problems_by_id = {}
    rows = 0
    with open(data_file, "r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            rows += 1
            try:
                problem = LCB.CodeGenerationProblem(**json.loads(line))
            except Exception as exc:
                print(
                    "Warning: skipping malformed record {}:{}: {}".format(
                        data_file, line_number, exc
                    ),
                    file=sys.stderr,
                )
                continue
            problems_by_id.setdefault(problem.question_id, problem)

    problems = sorted(
        problems_by_id.values(),
        key=lambda item: (item.contest_date, item.question_id),
    )
    total_before_filter = len(problems)

    if difficulties:
        wanted = {item.lower() for item in difficulties}
        problems = [
            problem
            for problem in problems
            if problem.difficulty.value.lower() in wanted
        ]
        print(
            "难度过滤 {}: 保留 {}/{} 题".format(
                sorted(wanted), len(problems), total_before_filter
            )
        )

    if limit and limit > 0:
        problems = problems[:limit]
        print("限制前 {} 题".format(len(problems)))

    if not problems:
        raise SystemExit("过滤后没有题目可评测，请检查 --difficulties / --data-file")

    duplicate_ids = rows - len(problems_by_id)
    return problems, rows, duplicate_ids


# ------------------------------
# 模型调用
# ------------------------------


def _call_model_once(client, args, prompt):
    started = time.time()
    stream = client.completions.create(
        model=args.model,
        prompt=prompt_to_completion_text(prompt),
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        n=1,
        timeout=args.request_timeout,
        stream=True,
        stream_options={"include_usage": True},
    )

    content_parts = []
    usage = {}
    finish_reason = None
    first_token_at = None
    chunk_count = 0

    for chunk in stream:
        if args.request_timeout and time.time() - started > args.request_timeout:
            close_stream = getattr(stream, "close", None)
            if callable(close_stream):
                close_stream()
            raise TimeoutError(
                "hard_request_deadline_exceeded:{}s".format(args.request_timeout)
            )
        if getattr(chunk, "usage", None) is not None:
            usage_value = to_jsonable(chunk.usage)
            usage = usage_value if isinstance(usage_value, dict) else {}

        if not chunk.choices:
            continue

        choice = chunk.choices[0]
        text_piece = getattr(choice, "text", "") or ""

        if text_piece:
            if first_token_at is None:
                first_token_at = time.time()
            chunk_count += 1
            content_parts.append(text_piece)

        if choice.finish_reason is not None:
            finish_reason = choice.finish_reason

    finished_at = time.time()
    if first_token_at is None:
        raise RuntimeError("Streaming response contained no output tokens")

    completion_tokens = usage.get("completion_tokens")
    tpot_seconds = None
    if isinstance(completion_tokens, int) and completion_tokens > 1:
        tpot_seconds = (finished_at - first_token_at) / (completion_tokens - 1)

    return {
        "content": "".join(content_parts),
        "reasoning_content": "",
        "finish_reason": finish_reason,
        "ttft_seconds": first_token_at - started,
        "tpot_seconds": tpot_seconds,
        "elapsed_seconds": finished_at - started,
        "usage": usage,
        "raw_response": {
            "stream": True,
            "endpoint_type": "completions",
            "output_chunk_count": chunk_count,
        },
    }


def call_model(client, args, prompt):
    last_error = None
    for attempt in range(1, args.max_retries + 1):
        try:
            result = _call_model_once(client, args, prompt)
            if not result.get("content", "").strip():
                raise RuntimeError("empty_content")
            result["attempts"] = attempt
            return result
        except Exception as exc:
            last_error = exc
            if attempt >= args.max_retries:
                break
            delay = min(
                args.retry_base_seconds * (2 ** (attempt - 1)),
                args.retry_max_seconds,
            )
            print(
                "Request attempt {}/{} failed: {}: {}; retrying in {}s".format(
                    attempt, args.max_retries, type(exc).__name__, exc, delay
                ),
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError(
        "request failed after {} attempts: {}: {}".format(
            args.max_retries, type(last_error).__name__, last_error
        )
    )


def generate_one(client, args, index, total, problem):
    question_id = problem.question_id
    print(
        "[{}/{}] {} | {} | {}".format(
            index, total, question_id, problem.platform.value,
            problem.difficulty.value,
        ),
        flush=True,
    )

    prompt = LCB.format_prompt_generation(problem, LCB.LMStyle.OpenAIChat)
    record = {
        "question_id": question_id,
        "question_title": problem.question_title,
        "platform": problem.platform.value,
        "difficulty": problem.difficulty.value,
        "contest_date": problem.contest_date.isoformat(),
        "content": "",
        "reasoning_content": "",
        "parsed_code": "",
        "finish_reason": None,
        "ttft_seconds": None,
        "tpot_seconds": None,
        "elapsed_seconds": None,
        "usage": {},
        "raw_response": None,
        "attempts": 0,
        "error": None,
        "completed": False,
        "request_failed": False,
    }

    try:
        result = call_model(client, args, prompt)
        record.update(result)
        if not record["content"].strip():
            record["error"] = "empty_content"
        else:
            record["parsed_code"] = LCB.extract_code(
                record["content"], LCB.LMStyle.OpenAIChat
            )
            if not record["parsed_code"].strip():
                record["error"] = "code_parse_error"
    except Exception as exc:
        record["error"] = "{}: {}".format(type(exc).__name__, exc)
        record["request_failed"] = True

    record["completed"] = True
    return record


# ------------------------------
# 主流程
# ------------------------------


def accuracy_breakdown(problems, graded, attribute):
    groups = {}
    for problem, item in zip(problems, graded):
        value = getattr(problem, attribute)
        key = value.value if hasattr(value, "value") else str(value)
        group = groups.setdefault(key, {"passed": 0, "total": 0, "pass_at_1": 0})
        group["total"] += 1
        if item and item[0] is True:
            group["passed"] += 1

    for group in groups.values():
        group["pass_at_1"] = group["passed"] / group["total"] if group["total"] else 0
    return groups


def reset_failed_records(state):
    """保留请求成功的记录，丢弃请求失败的，下一轮重跑。"""

    def request_succeeded(record):
        if not record.get("completed"):
            return False
        if record.get("request_failed") is True:
            return False
        if "request_failed" not in record:
            error = record.get("error")
            if error and error != "code_parse_error":
                return False
        return True

    return {
        question_id: record
        for question_id, record in state.items()
        if request_succeeded(record)
    }


def write_report(path, args, problems, passed, summary):
    accuracy = summary["metrics"]["accuracy"]
    lines = [
        "# LiveCodeBench 评测报告",
        "",
        "- 模型: {}".format(args.model),
        "- 服务地址: {}".format(args.base_url),
        "- 题库: {}".format(os.path.basename(args.data_file)),
        "- 难度: {}".format(", ".join(args.difficulties) if args.difficulties else "全部"),
        "- 并发: {}".format(args.concurrency),
        "- 题目数: {}".format(len(problems)),
        "- 通过数: {}".format(passed),
        "- pass@1: {:.6f}".format(accuracy["pass_at_1"]),
        "- 代码解析率: {:.6f}".format(accuracy["parsed_success_rate"]),
        "",
        "## 分难度",
        "",
        "| 难度 | 通过 / 总数 | pass@1 |",
        "| --- | --- | --- |",
    ]
    for name in DIFFICULTY_CHOICES:
        group = accuracy["by_difficulty"].get(name)
        if not group:
            continue
        lines.append(
            "| {} | {} / {} | {:.6f} |".format(
                name, group["passed"], group["total"], group["pass_at_1"]
            )
        )

    lines.extend([
        "",
        "## 分平台",
        "",
        "| 平台 | 通过 / 总数 | pass@1 |",
        "| --- | --- | --- |",
    ])
    for name, group in sorted(accuracy["by_platform"].items()):
        lines.append(
            "| {} | {} / {} | {:.6f} |".format(
                name, group["passed"], group["total"], group["pass_at_1"]
            )
        )

    with open(path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")


def main(argv=None):
    args = parse_args(argv)

    # lcb_runner 里用相对路径读 few_shot 示例，必须先切到源码目录再导入
    requested_source_dir = os.path.abspath(args.source_dir)
    if os.path.isdir(requested_source_dir):
        os.chdir(requested_source_dir)

    source_dir = load_runner_modules(requested_source_dir)
    data_file = os.path.abspath(args.data_file)

    output_dir = args.output_dir or os.path.join(
        SCRIPT_DIR, "outputs", "lcb_{}".format(time.strftime("%Y%m%d_%H%M%S"))
    )
    output_dir = os.path.abspath(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    paths = {
        "state": os.path.join(output_dir, "state.json"),
        "raw": os.path.join(output_dir, "raw.json"),
        "predictions": os.path.join(output_dir, "predictions.json"),
        "evaluation": os.path.join(output_dir, "evaluation.json"),
        "summary": os.path.join(output_dir, "summary.json"),
        "report": os.path.join(output_dir, "report.md"),
    }

    print("LiveCodeBench 源码: {}".format(source_dir))
    print("题库: {}".format(data_file))
    print("结果目录: {}".format(output_dir))

    problems, rows, duplicate_ids = load_problems(
        data_file, args.difficulties, args.limit
    )

    state = load_state(paths["state"])
    if args.reset_failed:
        before = len(state)
        state = reset_failed_records(state)
        removed = before - len(state)
        if removed:
            print("重置 {} 条请求失败记录，下一轮重跑".format(removed))
            save_json(paths["state"], state)

    pending = [
        (index, problem)
        for index, problem in enumerate(problems, start=1)
        if state.get(problem.question_id, {}).get("completed") is not True
    ]

    print("题目数: {}".format(len(problems)))
    print("待生成: {}".format(len(pending)))
    print("并发: {}".format(args.concurrency))
    print("最大重试: {}".format(args.max_retries))
    print("单题超时: {}s".format(args.request_timeout))

    thread_local = threading.local()

    def worker(item):
        if not hasattr(thread_local, "client"):
            thread_local.client = LCB.OpenAI(
                api_key=args.api_key,
                base_url=args.base_url,
                max_retries=0,
            )
        index, problem = item
        return generate_one(
            thread_local.client, args, index, len(problems), problem
        )

    if pending:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
            futures = {executor.submit(worker, item): item for item in pending}
            for future in as_completed(futures):
                index, problem = futures[future]
                try:
                    record = future.result()
                except Exception as exc:
                    record = {
                        "question_id": problem.question_id,
                        "question_title": problem.question_title,
                        "platform": problem.platform.value,
                        "difficulty": problem.difficulty.value,
                        "contest_date": problem.contest_date.isoformat(),
                        "content": "",
                        "reasoning_content": "",
                        "parsed_code": "",
                        "finish_reason": None,
                        "ttft_seconds": None,
                        "tpot_seconds": None,
                        "elapsed_seconds": None,
                        "usage": {},
                        "raw_response": None,
                        "attempts": 1,
                        "error": "worker_exception:{}: {}".format(
                            type(exc).__name__, exc
                        ),
                        "completed": True,
                        "request_failed": True,
                    }
                state[record["question_id"]] = record
                save_json(paths["state"], state)
                if record["error"]:
                    print(
                        "{} error={}".format(record["question_id"], record["error"]),
                        flush=True,
                    )
                else:
                    print(
                        "{} done ttft={:.2f}s tpot={} elapsed={:.1f}s".format(
                            record["question_id"],
                            record["ttft_seconds"] or 0.0,
                            record["tpot_seconds"]
                            if record["tpot_seconds"] is not None
                            else "n/a",
                            record["elapsed_seconds"] or 0.0,
                        ),
                        flush=True,
                    )

    raw_results = []
    predictions = []
    samples = []
    generations = []

    for problem in problems:
        record = state.get(problem.question_id, {})
        code = record.get("parsed_code", "") or ""
        raw_results.append(record)
        predictions.append({"question_id": problem.question_id, "code_list": [code]})
        samples.append(problem.get_evaluation_sample())
        generations.append([code])

    save_json(paths["raw"], raw_results)
    save_json(paths["predictions"], predictions)

    print("判题中，共 {} 题...".format(len(problems)), flush=True)
    graded = [None] * len(problems)
    try:
        metrics = LCB.codegen_metrics(
            samples,
            generations,
            k_list=[1],
            num_process_evaluate=1,
            timeout=args.eval_timeout,
            debug=False,
        )
        graded = LCB.extract_instance_results(metrics[1])
        passed = sum(bool(item and item[0] is True) for item in graded)
        evaluation = {
            "success": True,
            "metrics": metrics[0],
            "results": metrics[1],
            "metadata": metrics[2],
        }
    except Exception as exc:
        passed = 0
        evaluation = {
            "success": False,
            "error": "{}: {}".format(type(exc).__name__, exc),
        }

    save_json(paths["evaluation"], evaluation)

    errors = {}
    for item in raw_results:
        if item.get("error"):
            category = item["error"].split(":", 1)[0]
            errors[category] = errors.get(category, 0) + 1

    prompt_tokens = []
    completion_tokens = []
    ttft_seconds = []
    tpot_seconds = []
    elapsed_seconds = []
    for item in raw_results:
        usage = item.get("usage") or {}
        prompt_tokens.append(usage.get("prompt_tokens"))
        completion_tokens.append(usage.get("completion_tokens"))
        ttft_seconds.append(item.get("ttft_seconds"))
        tpot_seconds.append(item.get("tpot_seconds"))
        elapsed_seconds.append(item.get("elapsed_seconds"))

    parsed_count = sum(
        bool(item.get("parsed_code", "").strip()) for item in raw_results
    )

    summary = {
        "file": os.path.basename(data_file),
        "rows": rows,
        "unique_problems": len(problems),
        "duplicate_ids": duplicate_ids,
        "difficulties": list(args.difficulties) if args.difficulties else list(DIFFICULTY_CHOICES),
        "completed": sum(bool(item.get("completed")) for item in raw_results),
        "nonempty": sum(bool(item.get("content", "").strip()) for item in raw_results),
        "parsed": parsed_count,
        "passed": passed,
        "total": len(problems),
        "errors": errors,
        "metrics": {
            "accuracy": {
                "passed": passed,
                "total": len(problems),
                "pass_at_1": passed / len(problems) if problems else 0,
                "parsed": parsed_count,
                "parsed_success_rate": (
                    parsed_count / len(problems) if problems else 0
                ),
                "pass_rate_among_parsed": (
                    passed / parsed_count if parsed_count else 0
                ),
                "by_difficulty": accuracy_breakdown(problems, graded, "difficulty"),
                "by_platform": accuracy_breakdown(problems, graded, "platform"),
            },
            "prompt_tokens": describe_distribution(prompt_tokens),
            "completion_tokens": describe_distribution(completion_tokens),
            "ttft_seconds": describe_distribution(ttft_seconds),
            "tpot_seconds": describe_distribution(tpot_seconds),
            "elapsed_seconds": describe_distribution(elapsed_seconds),
            "actual_request_concurrency": args.concurrency,
            "max_sustainable_pressure": None,
            "max_sustainable_pressure_note": (
                "需要单独的分级压测；本次精度评测只记录实际并发。"
            ),
        },
        "evaluation": evaluation,
    }
    save_json(paths["summary"], summary)
    write_report(paths["report"], args, problems, passed, summary)

    print("")
    print("========== LiveCodeBench 评测结果 ==========")
    print("题目数: {}".format(len(problems)))
    print("通过数: {}".format(passed))
    print("pass@1: {:.6f}".format(summary["metrics"]["accuracy"]["pass_at_1"]))
    print("代码解析率: {:.6f}".format(
        summary["metrics"]["accuracy"]["parsed_success_rate"]
    ))
    for name in DIFFICULTY_CHOICES:
        group = summary["metrics"]["accuracy"]["by_difficulty"].get(name)
        if not group:
            continue
        print(
            "  {}: {}/{} pass@1={:.6f}".format(
                name, group["passed"], group["total"], group["pass_at_1"]
            )
        )
    if errors:
        print("错误统计: {}".format(
            ", ".join("{}={}".format(k, v) for k, v in sorted(errors.items()))
        ))
    print("结果目录: {}".format(output_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
