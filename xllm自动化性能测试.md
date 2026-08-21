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

<details open>
<summary>process_dataset.py</summary>

```python
# -*- coding: utf-8 -*-
import json
import argparse
import os
import sys
import time


################################自定义函数区域#############################################
#参数化函数
def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bs', type=int, default=4096, help="Number of dataset")
    parser.add_argument("--inputlen", type=int, default=2048, help="Input token lenth")
    parser.add_argument("--datasettype", type=str, default='GSM',
                        help="dataset generator type: GSM/SHAREGPT/SWEBENCH/VQA/VID/VSD")
    parser.add_argument("--datapath", type=str, default='/workspace/benchmark/', help="dataset sample path")
    parser.add_argument("--modelpath", type=str, default="", help="model path")
    #ShareGPT专用参数
    parser.add_argument("--sharegptpath", type=str, default='./ShareGPT_V3_unfiltered_cleaned_split.json',
                        help="ShareGPT json path (SHAREGPT only)")
    parser.add_argument("--swebenchpath", type=str, default="./SWE-bench/data/test-00000-of-00001.parquet",
                        help="SWE-bench parquet path or its data dir (SWEBENCH only)")
    parser.add_argument("--mode", type=str, default='concat', choices=['concat', 'tile', 'prefix'],
                        help="SHAREGPT/SWEBENCH sample build mode: concat=拼接多条不同对话, tile=重复单条, "
                             "prefix=前缀共享(前prefix_ratio比例token跨样本相同,后缀变化)")
    parser.add_argument("--prefix_ratio", type=float, default=0.9,
                        help="prefix模式下共享前缀占比(0~1),默认0.9即前90%%token相同")
    parser.add_argument("--role", type=str, default='human', choices=['human', 'all'],
                        help="SHAREGPT source turns: human=仅用户提问, all=全部角色")
    return parser.parse_args()

#########################################################################################
#TextVQA数据集的annotation.json文件生成函数
def generate_annotations_file(batch_size, start_question_id=3602, output_file="textvqa_val_annotations.json"):
    # 创建基础结构
    data = {
        "annotations": []
    }

    # 生成指定数量的结构体
    for i in range(batch_size):
        annotation = {
          "image_id": 0,
          "answer_type": "other",
          "question_type": "other",
          "question_id": start_question_id + i,  # question_id递增
          "answers": [
            {
                  "answer_id": 1023,
                  "answer": "None",
                  "answer_confidence": "yes"
            }
          ]
        }
        data["annotations"].append(annotation)

    # 写入文件，确保格式正确
    with open(output_file, 'w', encoding='utf-8') as f:
        # 写入annotations文件head
        f.write('{\n  "annotations": [\n')

        for i, annotation in enumerate(data["annotations"]):
            # 将结构体转换为JSON字符串
            annotation_str = json.dumps(annotation, indent=2, ensure_ascii=False)
            # 调整缩进以匹配目标格式
            lines = annotation_str.split('\n')
            indented_lines = ['    ' + line for line in lines]
            indented_str = '\n'.join(indented_lines)
            # 写入结构体，最后一个不加逗号
            if i < len(data["annotations"]) - 1:
                f.write(indented_str + ',\n')
            else:
                f.write(indented_str + '\n')

        f.write('  ]\n}')

    print(f"[process_dataset]: 已生成文件: {output_file}")
    print(f"[process_dataset]: 包含 {batch_size} 个结构体，question_id 从 {start_question_id} 到 {start_question_id + batch_size - 1}")

#########################################################################################
#数据集问题文本生成函数
def datatmp_generator(input_len, tokenizer, dataset, batch_size):
    dataset_tmp = []
    for sentence in dataset:
        words = tokenizer.tokenize(sentence)
        if len(words) == 0:
            continue
        len_num = len(words) // input_len
        if len_num == 0:
            multiplier = (input_len // len(words)) + 1
            repeated_len = words * multiplier
            words = repeated_len[:input_len]
            decoded_text = tokenizer.convert_tokens_to_string(words)
            dataset_tmp.append(decoded_text)
        else:
            words = words[:input_len]
            decoded_text = tokenizer.convert_tokens_to_string(words)
            dataset_tmp.append(decoded_text)

    batch_num = len(dataset_tmp) // batch_size
    if batch_num == 0:
        multiplier = (batch_size // len(dataset_tmp)) + 1
        repeat_batch = dataset_tmp * multiplier
        dataset_tmp = repeat_batch[:batch_size]
    else:
        dataset_tmp = dataset_tmp[:batch_size]
    return dataset_tmp

#########################################################################################
#tokenizer轻量封装;仅暴露本脚本用到的tokenize与convert_tokens_to_string
class _JsonTokenizer(object):
    def __init__(self, tokenizer_json):
        from tokenizers import Tokenizer
        self._tk = Tokenizer.from_file(tokenizer_json)

    def tokenize(self, text):
        return self._tk.encode(text, add_special_tokens=False).tokens

    def convert_tokens_to_string(self, tokens):
        ids = [self._tk.token_to_id(t) for t in tokens]
        return self._tk.decode([i for i in ids if i is not None])


#########################################################################################
#tokenizer加载函数;优先transformers,失败则回退tokenizers直接读tokenizer.json
def load_tokenizer(model_path):
    try:
        from transformers import AutoTokenizer
        return AutoTokenizer.from_pretrained(f"{model_path}", trust_remote_code=True)
    except Exception as e:
        print(f"[process_dataset]: transformers加载失败({type(e).__name__}: {str(e)[:100]})")
        candidate = model_path if model_path.endswith('.json') \
            else os.path.join(model_path, 'tokenizer.json')
        if not os.path.exists(candidate):
            raise RuntimeError(
                f"[process_dataset]: transformers不可用且找不到{candidate};"
                f"请修复transformers或提供tokenizer.json") from e
        print(f"[process_dataset]: 回退tokenizers后端,读取{candidate}")
        return _JsonTokenizer(candidate)


#########################################################################################
#ShareGPT语料加载函数;从conversations中按角色抽取文本
def sharegpt_loader(json_path, role='human'):
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"[process_dataset]: 找不到ShareGPT数据集: {json_path}")
    with open(json_path, 'r', encoding='utf-8') as f:
        raw = json.load(f)

    texts = []
    for item in raw:
        for turn in item.get('conversations', []):
            if role == 'human' and turn.get('from') != 'human':
                continue
            value = turn.get('value')
            if value and value.strip():
                texts.append(value)
    if not texts:
        raise ValueError(f"[process_dataset]: ShareGPT语料为空,role={role}")
    print(f"[process_dataset]: ShareGPT语料加载完成,可用文本{len(texts)}条(role={role})")
    return texts

#########################################################################################
#SWE-bench语料加载函数;从parquet读取problem_statement(代码类issue文本)作为压测语料
def swebench_loader(parquet_path):
    import os as _os
    import pyarrow.parquet as pq
    path = parquet_path
    if _os.path.isdir(path):
        cands = sorted(_os.path.join(path, f) for f in _os.listdir(path) if f.endswith(".parquet"))
        if not cands:
            sub = _os.path.join(path, "data")
            if _os.path.isdir(sub):
                cands = sorted(_os.path.join(sub, f) for f in _os.listdir(sub) if f.endswith(".parquet"))
        if not cands:
            raise FileNotFoundError(f"[process_dataset]: 目录下找不到parquet: {path}")
        path = cands[0]
        print(f"[process_dataset]: SWE-bench自动选用parquet: {path}")
    if not _os.path.exists(path):
        raise FileNotFoundError(f"[process_dataset]: 找不到SWE-bench parquet: {path}")
    texts = []
    table = pq.read_table(path)
    col = "problem_statement" if "problem_statement" in table.schema.names else table.schema.names[0]
    for v in table.column(col).to_pylist():
        if v and str(v).strip():
            texts.append(str(v))
    if not texts:
        raise ValueError(f"[process_dataset]: SWE-bench语料为空(列={col})")
    print(f"[process_dataset]: SWE-bench语料加载完成,可用文本{len(texts)}条(列={col})")
    return texts


#########################################################################################
#把文本精确修正到target_len个token;拼接接缝会引起BPE重编码漂移,需要收敛校正
def fit_to_token_len(text, target_len, tokenizer, supply=None):
    MAX_ROUND = 64
    for _ in range(MAX_ROUND):
        words = tokenizer.tokenize(text)
        cur = len(words)
        if cur == target_len:
            return text, True
        if cur > target_len:
            #偏长:按token截断后重新解码,再回到循环复核
            text = tokenizer.convert_tokens_to_string(words[:target_len])
        else:
            #偏短:补充语料;无补充源时用自身平铺兜底
            if supply is not None:
                text = text + "\n\n" + supply(target_len - cur)
            else:
                base = tokenizer.convert_tokens_to_string(words) if words else text
                if not base:
                    raise ValueError("[process_dataset]: 无法从空文本构造样本")
                multiplier = (target_len // max(cur, 1)) + 2
                text = (base + "\n\n") * multiplier
    #收敛失败时做最后一次硬截断,保证不超长
    words = tokenizer.tokenize(text)
    return tokenizer.convert_tokens_to_string(words[:target_len]), len(words) >= target_len


#########################################################################################
#ShareGPT样本生成函数;支持任意inputlen与bs,concat=拼接不同对话,tile=重复单条
def sharegpt_generator(input_len, tokenizer, texts, batch_size, mode='concat'):
    total = len(texts)
    cursor = [0]

    def next_text():
        t = texts[cursor[0] % total]
        cursor[0] += 1
        return t

    #按需供给语料;approx_tok为还差的token数,按语料平均密度换算取几条
    def supply(approx_tok):
        chunk = []
        got = 0
        while got < approx_tok:
            t = next_text()
            chunk.append(t)
            got += max(len(t) // 4, 1)
        return "\n\n".join(chunk)

    dataset_tmp = []
    exact = 0
    for i in range(batch_size):
        if mode == 'tile':
            #重复单条种子直到够长,与GSM分支行为一致
            seed = next_text()
            text, ok = fit_to_token_len(seed, input_len, tokenizer, supply=None)
        else:
            #拼接不同对话直到够长
            text, ok = fit_to_token_len(supply(input_len), input_len, tokenizer, supply=supply)
        dataset_tmp.append(text)
        exact += 1 if ok else 0
        if (i + 1) % 8 == 0 or (i + 1) == batch_size:
            print(f"[process_dataset]: 已生成 {i + 1}/{batch_size} 条")

    print(f"[process_dataset]: 长度校验 {exact}/{batch_size} 条精确命中{input_len}tokens")
    if cursor[0] > total:
        print(f"[process_dataset]: 提示:语料已循环复用({cursor[0]}次取用/{total}条可用),"
              f"条目间会出现重复文本")
    return dataset_tmp


#########################################################################################
#ShareGPT前缀共享样本生成函数;固定前缀(prefix_ratio比例)跨样本相同,后缀各自变化
#用于压测prefix-cache命中率;前缀文本只构建一次,每条样本拼接不同后缀后整体收敛到input_len
def sharegpt_prefix_generator(input_len, tokenizer, texts, batch_size, prefix_ratio=0.9):
    prefix_len = int(input_len * prefix_ratio)
    suffix_len = input_len - prefix_len
    if prefix_len <= 0 or suffix_len <= 0:
        raise ValueError(f"[process_dataset]: prefix_ratio={prefix_ratio}导致前缀/后缀长度为0,"
                         f"prefix_len={prefix_len}, suffix_len={suffix_len}")

    total = len(texts)
    cursor = [0]

    def next_text():
        t = texts[cursor[0] % total]
        cursor[0] += 1
        return t

    def supply(approx_tok):
        chunk = []
        got = 0
        while got < approx_tok:
            t = next_text()
            chunk.append(t)
            got += max(len(t) // 4, 1)
        return "\n\n".join(chunk)

    #共享前缀只构建一次;取语料拼接直到prefix_len并收敛校正
    prefix_text, prefix_ok = fit_to_token_len(supply(prefix_len), prefix_len, tokenizer, supply=supply)
    print(f"[process_dataset]: 共享前缀已构建,{prefix_len}tokens(精确={prefix_ok}),"
          f"占比{prefix_ratio:.0%}")

    dataset_tmp = []
    exact = 0
    for i in range(batch_size):
        #后缀按suffix_len构建,每条不同
        suffix_text = fit_to_token_len(supply(suffix_len), suffix_len, tokenizer, supply=supply)[0]
        #拼接前缀+后缀,再整体收敛到input_len;fit截断只动尾部,前缀token保持不变
        combined = prefix_text + "\n\n" + suffix_text
        final_text, ok = fit_to_token_len(combined, input_len, tokenizer, supply=supply)
        dataset_tmp.append(final_text)
        exact += 1 if ok else 0
        if (i + 1) % 8 == 0 or (i + 1) == batch_size:
            print(f"[process_dataset]: 已生成 {i + 1}/{batch_size} 条")

    print(f"[process_dataset]: 长度校验 {exact}/{batch_size} 条精确命中{input_len}tokens")
    print(f"[process_dataset]: 前{prefix_len}tokens(占比{prefix_ratio:.0%})跨样本共享")
    return dataset_tmp


################################自定义函数区域#############################################

if __name__ == '__main__':
    args = parse_arguments()
    # 以DeekSeek为例,权重路径更换
    batch_size = args.bs
    input_len = args.inputlen
    dataset_type = args.datasettype
    data_path = args.datapath
    model_path = args.modelpath
    #调用tokenizer;transformers不可用或版本不匹配时自动回退tokenizers
    #tokenizer = AutoTokenizer.from_pretrained(f"{model_path}", trust_remote_code=True, use_fast=False)
    tokenizer = load_tokenizer(model_path)
    print(f"[process_dataset]: 数据集生成基于该权重产生:{model_path}")
    #不同类型的数据集分类执行，函数模块反复调用;Support Dataset Type: GSM,SHAREGPT,SWEBENCH,VQA、VID
    if ( dataset_type == 'GSM' ):

        if os.path.exists(f'{dataset_type}-in{input_len}-bs{batch_size}.jsonl'):
            print("[process_dataset]: GSM8K jsonl already exists...")
            exit(0)

        dataset = []
        dataset_path = "./GSM8K.jsonl"
        with open(dataset_path, 'r', encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                dataset.append(data['question'])

        dataset_tmp = []
        dataset_tmp = datatmp_generator(input_len, tokenizer, dataset, batch_size)
        print("=== 生成GSM8K.jsonl文件 ===")
        json_str = json.dumps(dataset_tmp, ensure_ascii=False, indent=4)
        with open(f'GSM8K-in{input_len}-bs{batch_size}.jsonl', 'w', encoding='utf-8') as f:
            print("[process_dataset]: start generating")
            for i in range(len(dataset_tmp)):
                f.write(json.dumps({"question": dataset_tmp[i], "answer": "none"}, ensure_ascii=False))
                f.write("\n")
        print(f"[process_dataset]: 已生成文件:GSM8K-in{input_len}-bs{batch_size}.jsonl")

#ShareGPT数据集生成
    elif (dataset_type == 'SHAREGPT' ):

        #prefix模式文件名带-pfx后缀,避免与普通模式产物冲突/误判已存在
        if args.mode == 'prefix':
            out_name = f'ShareGPT-in{input_len}-bs{batch_size}-pfx{int(args.prefix_ratio*100)}.jsonl'
        else:
            out_name = f'ShareGPT-in{input_len}-bs{batch_size}.jsonl'
        if os.path.exists(out_name):
            print(f"[process_dataset]: {out_name} already exists...")
            exit(0)

        texts = sharegpt_loader(args.sharegptpath, role=args.role)

        dataset_tmp = []
        if args.mode == 'prefix':
            dataset_tmp = sharegpt_prefix_generator(input_len, tokenizer, texts, batch_size,
                                                    prefix_ratio=args.prefix_ratio)
        else:
            dataset_tmp = sharegpt_generator(input_len, tokenizer, texts, batch_size, mode=args.mode)
        print("=== 生成ShareGPT.jsonl文件 ===")
        with open(out_name, 'w', encoding='utf-8') as f:
            print("[process_dataset]: start generating")
            for i in range(len(dataset_tmp)):
                f.write(json.dumps({"question": dataset_tmp[i], "answer": "none"}, ensure_ascii=False))
                f.write("\n")
        print(f"[process_dataset]: 已生成文件:{out_name}")

#SWE-bench数据集生成(代码类语料,复用ShareGPT的收敛与前缀共享逻辑)
    elif (dataset_type == 'SWEBENCH' ):

        if args.mode == 'prefix':
            out_name = f'Swebench-in{input_len}-bs{batch_size}-pfx{int(args.prefix_ratio*100)}.jsonl'
        else:
            out_name = f'Swebench-in{input_len}-bs{batch_size}.jsonl'
        if os.path.exists(out_name):
            print(f"[process_dataset]: {out_name} already exists...")
            exit(0)

        texts = swebench_loader(args.swebenchpath)

        dataset_tmp = []
        if args.mode == 'prefix':
            dataset_tmp = sharegpt_prefix_generator(input_len, tokenizer, texts, batch_size,
                                                    prefix_ratio=args.prefix_ratio)
        else:
            dataset_tmp = sharegpt_generator(input_len, tokenizer, texts, batch_size, mode=args.mode)
        print("=== 生成Swebench.jsonl文件 ===")
        with open(out_name, 'w', encoding='utf-8') as f:
            print("[process_dataset]: start generating")
            for i in range(len(dataset_tmp)):
                f.write(json.dumps({"question": dataset_tmp[i], "answer": "none"}, ensure_ascii=False))
                f.write("\n")
        print(f"[process_dataset]: 已生成文件:{out_name}")

#VQA数据集生成
    elif (dataset_type == 'VQA' ):

        if os.path.exists(f'Textvqa-in{input_len}-bs{batch_size}.jsonl'):
            print("[process_dataset]: VQA dataset already exists...")
            exit(0)

        dataset = []
        vqa_question = "Explain the contents of the picture"
        dataset.append(vqa_question)

        dataset_tmp = []
        dataset_tmp = datatmp_generator(input_len, tokenizer, dataset, batch_size)
        print("=== 生成textvqa_val.json文件 ===")
        start_question_id= 34602
        json_str = json.dumps(dataset_tmp, ensure_ascii=False, indent=4)
        with open(f'Textvqa-in{input_len}-bs{batch_size}.jsonl', 'w', encoding='utf-8') as f:
            print("[process_dataset]: start generating")
            for i in range(len(dataset_tmp)):
                question_id = start_question_id + i
                f.write(json.dumps({"image": data_path, "question": dataset_tmp[i], "question_id": question_id, "answer": "None"}))
                f.write("\n")

        print(f"[process_dataset]: 已生成文件:Textvqa-in{input_len}-bs{batch_size}.jsonl")
        #生成annotations.json文件
        print("=== 生成textvqa_val_annotations.json文件中 ===")
        generate_annotations_file(batch_size, start_question_id=34602, output_file=f'Textvqa-in{input_len}-bs{batch_size}-annotation.json')


#数据集测试VID
    elif (dataset_type == 'VID' ):

        if os.path.exists(f'Videobench-in{input_len}-bs{batch_size}-qa.json'):
            print("[process_dataset]: VID dataset already exists...")
            exit(0)

        dataset = []
        video_question = "Explain the contents of the video"
        dataset.append(video_question)

        dataset_tmp = []
        dataset_tmp = datatmp_generator(input_len, tokenizer, dataset, batch_size)

        print("=== 生成videobench_qa_new.json文件中 ===")

        json_str = json.dumps(dataset_tmp, ensure_ascii=False, indent=4)
        with open(f'Videobench-in{input_len}-bs{batch_size}-qa.json', 'w', encoding='utf-8') as f:
            print("[process_dataset]: start generating")
            f.write('{\n')
            i = 0
            for i in range(len(dataset_tmp)):
                line_content = f'  "{i}": {json.dumps({"vid_path": data_path, "video_id": "1", "question": dataset_tmp[i], "choices": {"A": "win", "B": "or", "C": "lose", "D": "sss"}}, ensure_ascii=False)}'
                if i < len(dataset_tmp) - 1:
                    line_content += ','
                line_content += '\n'
                f.write(line_content)
            f.write('}')
        print(f"[process_dataset]: 已生成文件:Videobench-in{input_len}-bs{batch_size}-qa.json")

        with open(f'Videobench-in{input_len}-bs{batch_size}-answer.json', 'w', encoding='utf-8') as f:
            print("[process_dataset]: start generating")
            f.write('{\n  "TEST": {\n')
            i = 0
            for i in range(len(dataset_tmp)):
                line_content = f'    "{i}": {json.dumps({"answer": "A"})}'
                if i < len(dataset_tmp) - 1:
                    line_content += ','
                line_content += '\n'
                f.write(line_content)
            f.write('  }\n}')
        print(f"[process_dataset]: 已生成文件:Videobench-in{input_len}-bs{batch_size}-answer.json")

    #数据集测试VSD
    elif (dataset_type == 'VSD' ): 
        #使用音频数据集时需要依赖 pydub，位置调整至该if语句中。  
        from pydub import AudioSegment
        BASE_LENGTH = 15
        number = int(batch_size)
        length  = int(data_path)         
        if os.path.exists(f'./dataset/Vocalsound/{data_path}second/{batch_size}'):
            print("[process_dataset]: VSD dataset already exists...")
            exit(0)      
        if number < 2:
            raise ValueError('[peocess_dataset]: The number of the audio should be at least 2.')
        if not data_path.isdigit():
            raise ValueError('[peocess_dataset]: The length of the audio must be an integer.')
        if length < 15:
            raise ValueError('[peocess_dataset]: The length The audio length must not be less than 15 seconds.')
       
        print("=== 生成Vocalsound文件中 ===")
        audio_15s = AudioSegment.from_wav("./dataset/Vocalsound/m15_0_throatclearing.wav")
        audio_1s = audio_15s[:1000]
        audio_output = audio_15s * (length // BASE_LENGTH) + audio_1s * (length % BASE_LENGTH)
        duration_path = f'./dataset/Vocalsound/{length}second'
        concurrency_path = f'{duration_path}/{number}'
        try:
            os.mkdir(duration_path)
        except FileExistsError:
            pass
        try:
            os.mkdir(concurrency_path)
        except FileExistsError:
            pass

        for i in range(number):
            audio_output.export(f'{concurrency_path}/m{length}_{i}_throatclearing.wav', format='wav')
        print(f"[process_dataset]: 已生成文件vocalsound测试文件，文件路径{concurrency_path}")
```

</details>

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

所有可修改的参数放在脚本同目录下的 `run_perf.cfg` 中，**不再需要改脚本本身**。脚本启动时自动读取。

```json
{
  "input_len": [32768],
  "concurrencies": [1, 8, 16],
  "default_max_out_len": null,
  "default_request_rate": null,
  "default_pfx": null,

  "model_cfg_params": {
    "path": "/export/home/models/DeepSeek-V4-Flash-w8a8-mtp",
    "model": "DeepSeek-V4-Flash-w8a8-mtp",
    "host_ip": "11.87.191.83",
    "host_port": 18004
  },

  "dataset_types": ["gsm", "sharegpt", "swebench"],
  "raw_gsm_path": "/data/GSM8K.jsonl",
  "raw_sharegpt_path": "/data/ShareGPT_V3_unfiltered_cleaned_split.json",
  "raw_swebench_path": "/data/SWE-bench/data/test-00000-of-00001.parquet"
}
```

| 字段 | 说明 |
|------|------|
| `input_len` | 简易模式输入长度列表 |
| `concurrencies` | 简易模式并发数列表（batch_size） |
| `default_max_out_len` | 默认输出长度（null = 不改，用 vllm py 现有值） |
| `default_request_rate` | 默认 request_rate（null = 不改，0 = 打满） |
| `default_pfx` | 默认 pfx（null = 普通数据集） |
| `model_cfg_params` | 模型配置，写入 `vllm_api_general_stream.py`。其中 `path` 同时用作 tokenizer 模型路径 |
| `dataset_types` | 数据集类型列表：gsm / sharegpt / swebench |
| `raw_gsm_path` | GSM8K.jsonl 原始路径 |
| `raw_sharegpt_path` | ShareGPT 原始 JSON 路径 |
| `raw_swebench_path` | SWE-bench parquet 路径 |

> 💡 **路径自动定位**：`AIS_BENCH_ROOT` 通过 `import ais_bench_benchmark` 自动定位安装目录，支持标准安装和 `pip install -e` 开发安装。脚本放任意位置都能跑。
>
> 💡 **数据集 jsonl** 在脚本所在文件夹下查找。若找不到，**自动调用 process_dataset.py 生成**（需配置 `model_cfg_params.path` 和对应的原始数据路径）。
>
> 💡 **outputs 和 Excel** 统一落在脚本所在目录，不随执行位置变化。
>
> 💡 `model_cfg_params.path` 同时作为 tokenizer 模型路径，不再需要单独配置 `MODEL_PATH`。

## 3、启动测试

run_perf.py 支持两种模式：

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
| `--cases` | JSON 用例文件路径（主模式） |
| `-i / --input-len` | 输入长度列表（简易模式） |
| `-c / --concurrency` | 并发数列表（简易模式） |
| `--dataset-type` | 数据集类型列表：gsm / sharegpt / swebench（简易模式） |
| `--max-out-len` | 输出长度 |
| `--request-rate` | 请求速率（0 = 打满） |
| `--pfx` | 前缀缓存重复率% 列表（简易模式），0 或不传 = 普通数据集 |
| `--path` | 模型权重路径 |
| `--model` | 模型名 |
| `--host-ip` | 服务 IP |
| `--host-port` | 服务端口 |
| `--excel` | Excel 输出路径（默认脚本所在目录下） |
| `--skip-run` | 只解析已有输出，不重新跑 |

## 4、输出

执行完毕后，outputs 和 Excel 统一落在**脚本所在目录**下。按 `(数据集类型, 输入长度, pfx)` 分组生成 Excel：

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
- **配置外置**：所有可修改参数放在 `run_perf.cfg` 中，不再需要改脚本本身；`model_cfg_params.path` 同时作为 tokenizer 模型路径
- **配置注入靠正则改文件**：`set_model_cfg()` 用正则把参数写进 ais_bench 的模型配置 py，不侵入 ais_bench 代码；**静态配置**（path/model/host_ip/host_port）启动时写一次，**动态配置**（batch_size/max_out_len/request_rate）每个用例跑之前单独写
- **数据集绑定靠软链**：`ln -sf 选中.jsonl test.jsonl train.jsonl`，同时软链 test 和 train（ais_bench 启动会检查 train.jsonl 是否存在），切换用例零拷贝
- **结果目录只认"本次新增"**：运行前快照 outputs 目录，运行后只在新目录里找 gsm8k.csv —— **防止失败用例复用历史结果、数值张冠李戴**
- **失败不中断**：单用例异常被捕获记为 failed，继续跑下一个；失败原因写入 Excel 明细 sheet
- **数据集自动生成**：找不到数据集时自动调用 process_dataset.py 生成，无需手动分步操作
- **ais_bench 输出实时可见**：stdout/stderr 不捕获，直接透传到终端