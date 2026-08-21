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
                        help="dataset generator type: GSM/SHAREGPT/VQA/VID/VSD")
    parser.add_argument("--datapath", type=str, default='/workspace/benchmark/', help="dataset sample path")
    parser.add_argument("--modelpath", type=str, default="", help="model path")
    #ShareGPT专用参数
    parser.add_argument("--sharegptpath", type=str, default='./ShareGPT_V3_unfiltered_cleaned_split.json',
                        help="ShareGPT json path (SHAREGPT only)")
    parser.add_argument("--swebenchpath", type=str, default="./SWE-bench/data/test-00000-of-00001.parquet",
                        help="SWE-bench parquet path or its data dir (SWEBENCH only)")
    parser.add_argument("--mode", type=str, default='concat', choices=['concat', 'tile', 'prefix'],
                        help="SHAREGPT sample build mode: concat=拼接多条不同对话, tile=重复单条, "
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
    #不同类型的数据集分类执行，函数模块反复调用;Support Dataset Type: GSM,SHAREGPT,VQA、VID
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





