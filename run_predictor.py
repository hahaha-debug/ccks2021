# coding:utf-8

from genericpath import samefile
import os
import csv
import json
import time
import pickle
import warnings
import numpy as np
import pandas as pd

import torch
import torch.nn as nn
from transformers import BertTokenizer

from modeling.modeling_nezha.modeling import NeZhaPreTrainedModel, NeZhaModel
from run_classify_nezha_lstm import NezhaForSequenceClassification_LSTM
from transformers import AutoModelForTokenClassification,AutoTokenizer,pipeline

def argmax(res):
    k, tmp = 0, 0
    for i in range(len(res)):
        if res[i] > tmp:
            tmp = res[i]
            k = i

    return k


def batch_loader(config, src, seg, mask):
    ins_num = src.size()[0]
    batch_size = config['batch_size']
    for i in range(ins_num // batch_size):
        src_batch = src[i * batch_size: (i + 1) * batch_size, :]
        seg_batch = seg[i * batch_size: (i + 1) * batch_size, :]
        mask_batch = mask[i * batch_size: (i + 1) * batch_size, :]
        yield src_batch, seg_batch, mask_batch
    if ins_num > ins_num // batch_size * batch_size:
        src_batch = src[ins_num // batch_size * batch_size:, :]
        seg_batch = seg[ins_num // batch_size * batch_size:, :]
        mask_batch = mask[ins_num // batch_size * batch_size:, :]
        yield src_batch, seg_batch, mask_batch


def read_dataset(config):
    tokenizer = BertTokenizer.from_pretrained(config['init_model_path'])
    dataset, r_dataset = [], []
    seq_length = config['max_seq_len']

    with open(config['test_path'], 'r', encoding='utf-8') as f:
        for line_id, line in enumerate(f):
            if len(line.strip().split('\t'))!=2:
                sent_a=''
                sent_b=line.strip().split('\t')[0]
            else:
                sent_a, sent_b = line.strip().split('\t')
            src_a = tokenizer.convert_tokens_to_ids(["[CLS]"] + tokenizer.tokenize(sent_a) + ["[SEP]"])
            src_b = tokenizer.convert_tokens_to_ids(tokenizer.tokenize(sent_b) + ["[SEP]"])
            src = src_a + src_b
            seg = [0] * len(src_a) + [1] * len(src_b)
            mask = [1] * len(src)

            if len(src) > seq_length:
                src = src[: seq_length]
                seg = seg[: seq_length]
                mask = mask[: seq_length]

            while len(src) < seq_length:
                src.append(0)
                seg.append(0)
                mask.append(0)
            dataset.append([src, seg, mask])


    print("\n>>> loading sentences from {}, time cost:{:.2f}".
          format(config['test_path'], (time.time() - start) / 60.00))

    return dataset


def predict(dataset, pre_model, config):
    predict_logits, predictions = [], []
    p_logit = []

    src = torch.LongTensor([sample[0] for sample in dataset])
    seg = torch.LongTensor([sample[1] for sample in dataset])
    mask = torch.LongTensor([sample[2] for sample in dataset])
    
    for i, (src_batch, seg_batch, mask_batch) in \
            enumerate(batch_loader(config, src, seg, mask)):
        src_batch = src_batch.to(config['device'])
        seg_batch = seg_batch.to(config['device'])
        mask_batch = mask_batch.to(config['device'])
        with torch.no_grad():
            output = pre_model(input_ids=src_batch, token_type_ids=seg_batch, attention_mask=mask_batch)

        logits = output[0]
        logits = torch.softmax(logits, 1)
        p_logits = logits.cpu().numpy().tolist()
        for i in p_logits:
            p_logit.append(i)

    final_logit, predict_data = [], []
    for i in range(len(p_logit)):
        merge = []
        for j in range(len(p_logit[i])):
            tmp = p_logit[i][j]
            merge.append(tmp)
        final_logit.append(merge)
        res = argmax(merge)
        predictions.append(res)

    for i in final_logit:
        predict_data.append((i[0], i[1], i[2]))

    with open(config['output_logit_path'] + '.csv', 'w', newline='') as f:
        tsv_w = csv.writer(f, delimiter=',')
        tsv_w.writerow(['label0', 'label1', 'label2'])
        tsv_w.writerows(predict_data)

    if config['output_txt_path'] and config['output_txt_name'] is not None:
        if not os.path.exists(config['output_txt_path']):
            os.makedirs(config['output_txt_path'])
        out_txt = os.path.join(config['output_txt_path'], config['output_txt_name'])

        predict_data = []
        predict_k = 0

        # write results
        for i in predictions:
            predict_data.append((predict_k, i))
            predict_k += 1
        write2tsv(out_txt, predict_data)

    return predict_logits


def write(sent_list, path):
    with open(path, 'w', encoding='utf-8') as f:
        for i in sent_list:
            i = str(i)
            f.write(str(i) + '\n')

    '''print('\n>> result write done.')'''


def write2tsv(output_path, data):
    with open(output_path, 'w', newline='') as f:
        tsv_w = csv.writer(f, delimiter=',')
        tsv_w.writerow(['index', 'label'])
        tsv_w.writerows(data)


def generate_submit_result(config):
    reader = pd.read_csv(config['output_txt_path'] + config['output_txt_name'])
    label = reader['label'].tolist()
    k = 0
    all_ = []

    with open(config['origin_test_path'], 'r', encoding='utf-8') as f:
        for line_id, line in enumerate(f):
            line = line.replace('\\', '\\\\').strip()
            if line:
                sent = json.loads(line)
                candidate = sent['candidate']
                for i in candidate:
                    tgt = label[k]
                    if tgt == 0:
                        i['label'] = config['label0']
                    elif tgt == 1:
                        i['label'] = config['label1']
                    elif tgt == 2:
                        i['label'] = config['label2']
                    k += 1
                sent = json.dumps(sent, ensure_ascii=False).replace('\\\\', '\\')
                all_.append(sent)
            else:
                break

    write(all_, config['submit_path'])
    '''print('\n>> submit file write done.')'''


def main():
    config = {
        'model_type': 'mlm_model',
        'output_logit_path': 'output_result/nezha',
        'normal_data_cache_path': '',
        'normal_r_data_cache_path': '',
        'vocab_path': '',
        'init_model_path': '',
        #'origin_test_path': 'data/.txt',
        'origin_test_path': 'tcdata/test2_release.txt',
        'test_path': 'data/test2_release.txt',
        'load_model_path': 'output_model/checkpoint-2340',
        'output_txt_path': 'output_result/',
        'output_txt_name': 'predict.csv',
        'submit_path': 'result.txt',
        'batch_size': 32,
        'max_seq_len': 128,
        'label0': '不匹配',
        'label1': '部分匹配',
        'label2': '完全匹配',
        'device': 'cuda',
    }

    warnings.filterwarnings('ignore')
    start_time = time.time()
    localtime_start = time.asctime(time.localtime(time.time()))
    print(">> program start at:{}".format(localtime_start))

    config['vocab_path'] = 'pretrain_code/' + config['model_type'] + '/vocab.txt'
    config['init_model_path'] = 'pretrain_code/' + config['model_type']
    config['normal_data_cache_path'] = 'user_data/processed/' + config['model_type'] + '/test_data.pkl'

    test_file=open(config['test_path'], 'w',encoding='utf-8')

    model = NezhaForSequenceClassification_LSTM.from_pretrained(config['load_model_path'])
    model.to(config['device'])
    model.eval()

    with open(config['origin_test_path'], 'r', encoding='utf-8') as f:
        for line_id, line in enumerate(f):
            line = line.replace('\\','\\\\').strip()
            if line:
                sent = json.loads(line)
                query=sent['query']
                candidate = sent['candidate']
                for i in candidate:
                    text=i['text']
                    test_file.writelines(str(query)+'\t'+str(text)+'\n')
            else:
                break

    test_file.close()
    test_set = read_dataset(config)

    print("\n>> start predict ... ...")



    predict(dataset=test_set, pre_model=model, config=config)

    generate_submit_result(config)

    localtime_end = time.asctime(time.localtime(time.time()))
    print("\n>> program end at : {}, total cost time : {:.2f}".
          format(localtime_end, (time.time() - start_time) / 60.00))


if __name__ == '__main__':
    main()
