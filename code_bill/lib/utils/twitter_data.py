from typing import List, Union, Mapping
import os
from dataclasses import dataclass

import numpy as np
import pytorch_lightning as pl
import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader
from transformers import AutoTokenizer
from anytree import Node, RenderTree, PreOrderIter, LevelOrderIter
import ast
from lib.settings.config import settings
from tqdm import tqdm
import pickle


@dataclass
class MyNode():
    id: int
    sid: int
    t: float
    def __init__(self, id, sid, t):
        if id == 'ROOT': 
            self.id = 0
        else:
            self.id = int(id)
        if sid == 'ROOT':
            self.sid = 0
        else:
            self.sid = int(sid)
        self.t = float(t)

    def __repr__(self):
        return str(self.sid) + '_' + str(self.t)

class TwitterData():
    def __init__(
        self,
        rootpath=settings.data,
        pretrain_tokenizer_model='bert-base-cased',
        tree=True,
        max_seq_length=128,
        max_tree_length=100,
        train_batch_size=32,
        val_batch_size=32,
        test_batch_size=32,
        split_type='tvt',
        **kwargs
    ):
        super().__init__()
        self.rootpath = rootpath
        self.pretrain_tokenizer_model = pretrain_tokenizer_model
        self.tokenizer = AutoTokenizer.from_pretrained(
            pretrain_tokenizer_model, use_fast=True)
        self.max_seq_length = max_seq_length
        self.tree = tree
        self.max_tree_length = max_tree_length
        self.train_batch_size = train_batch_size
        self.val_batch_size = val_batch_size
        self.test_batch_size = test_batch_size
        self.n_class = 4
        self.split_type = split_type
        if self.split_type not in ['1516','tv','tvt','15_tvt','16_tvt']:
            print('warning: split_type invalid!')
            self.split_type = '641620'
        self.feature_dim = 1
        self.setup_flag = True

    def setup(self):
        if not self.setup_flag:
            return

        self.setup_flag = False
        print('***** setup dataset *****')
        self.train, self.val, self.test = None, None, None
        self._load_data()
        self._data_split(self.split_type)
        self._to_tensor()
        self._set_dataloader()
        print('***** finish *****')

    def prepare_data(self):
        AutoTokenizer.from_pretrained(
            self.pretrain_tokenizer_model, use_fast=True)

    def _to_tensor(self):
        self.dataset = {'train': self.train, 'val': self.val, 'test': self.test}
        for split in self.dataset.keys():
            d = self.dataset[split]
            if d is None:
                continue
            
            self.dataset[split] = self._convert_to_features(d)

    def _convert_to_features(self, example, indices=None):
        source = []
        tree = []
        label = []
        for x, y in example:
            source.append(x[0])
            tree.append(x[1])
            label.append(y)

        features = self.tokenizer.batch_encode_plus(
            list(source),
            max_length=self.max_seq_length,
            padding=True,
            truncation=True,
        )

        features_ = []
        if self.tree:
            for i in range(len(label)):
                features_.append((torch.tensor(features['input_ids'][i]), torch.tensor(features['token_type_ids'][i]),
                                torch.tensor(features['attention_mask'][i]), torch.tensor(tree[i],dtype=torch.float32), torch.tensor(label[i])))
        else:
            for i in range(len(label)):
                features_.append((torch.tensor(features['input_ids'][i]), torch.tensor(features['token_type_ids'][i]),
                                torch.tensor(features['attention_mask'][i]), torch.tensor(label[i])))
        
        return features_

    def _load_data(self):
        tw = ['twitter15','twitter16']
        data, trees = {}, {}
        for t in tw:
            source_p = os.path.join(self.rootpath,t,'source_tweets.txt')
            label_p = os.path.join(self.rootpath,t,'label.txt')
            tree_p = os.path.join(self.rootpath,t,'tree')
            #data[t] = self._combine_text_label(self._read_text(source_p), self._read_label(label_p))

            tree_map = self._read_tree(t, tree_p)
            trees, mean, std = self._encode_tree(tree_map,self.max_tree_length,padding=True)
            data[t] = self._combine_data(self._read_text(source_p), trees, self._read_label(label_p))

        self.tw15_X, self.tw15_y = data[tw[0]]
        self.tw16_X, self.tw16_y = data[tw[1]]

        self._find_class(self.tw15_y, self.tw16_y)

        self.tw15_y = self._class_to_index(self.tw15_y)
        self.tw16_y = self._class_to_index(self.tw16_y)

    def _find_class(self, label1, label2):
        label = np.concatenate((label1, label2))
        classes = sorted(np.unique(label))
        self.class_to_index = {classname: i for i,
                               classname in enumerate(classes)}
        self.class_names = classes
        self.n_class = len(classes)
        self.classes = [i for i in range(len(self.class_names))]

    def _class_to_index(self, label):
        index = np.vectorize(self.class_to_index.__getitem__)(label)
        return index

    def _data_split(self, split_type):
        if split_type == '1516':
            self.train = [[data, label]
                          for data, label in zip(self.tw15_X, self.tw15_y)]
            self.test = [[data, label]
                         for data, label in zip(self.tw16_X, self.tw16_y)]
        if split_type == 'tt':
            X = np.concatenate((self.tw15_X, self.tw16_X))
            y = np.concatenate((self.tw15_y, self.tw16_y))
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=1, stratify=self.self.classes)

            self.train = [[data, label]
                          for data, label in zip(X_train, y_train)]
            self.test = [[data, label] for data, label in zip(X_test, y_test)]
        if split_type == 'tvt':
            X = np.concatenate((self.tw15_X, self.tw16_X))
            y = np.concatenate((self.tw15_y, self.tw16_y))

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, train_size=0.8, random_state=1, shuffle=True, stratify=y)

            X_train, X_val, y_train, y_val = train_test_split(
                X_train, y_train, train_size=0.8, random_state=1, shuffle=True, stratify=y_train)

            
            self.train = [[data, label] for data, label in zip(X_train, y_train)]
            self.val = [[data, label] for data, label in zip(X_val, y_val)]
            self.test = [[data, label] for data, label in zip(X_test, y_test)]
        if split_type == '15_tvt':
            X_train, X_test, y_train, y_test = train_test_split(
                self.tw15_X, self.tw15_y, train_size=0.8, random_state=1, shuffle=True, stratify= self.tw15_y)

            X_train, X_val, y_train, y_val = train_test_split(
                X_train, y_train, train_size=0.8, random_state=1, shuffle=True, stratify=y_train)

            self.train = [[data, label] for data, label in zip(X_train, y_train)]
            self.val = [[data, label] for data, label in zip(X_val, y_val)]
            self.test = [[data, label] for data, label in zip(X_test, y_test)]

        if split_type == '16_tvt':
            X_train, X_test, y_train, y_test = train_test_split(
                self.tw16_X, self.tw16_y, train_size=0.8, random_state=1, shuffle=True, stratify=self.tw16_y)

            X_train, X_val, y_train, y_val = train_test_split(
                X_train, y_train, train_size=0.8, random_state=1, shuffle=True, stratify=y_train)

            self.train = [[data, label] for data, label in zip(X_train, y_train)]
            self.val = [[data, label] for data, label in zip(X_val, y_val)]
            self.test = [[data, label] for data, label in zip(X_test, y_test)]

    def _set_dataloader(self, shuffle=True):
        
        self._train_data = DataLoader(self.dataset['train'],
                                      batch_size=self.train_batch_size,
                                      shuffle=shuffle,
                                      num_workers=4)
        self._test_data = DataLoader(self.dataset['test'],
                                     batch_size=self.test_batch_size,
                                     shuffle=False,
                                     num_workers=4)
        if self.dataset['val'] is not None:
            self._val_data = DataLoader(self.dataset['val'],
                                        batch_size=self.val_batch_size,
                                        shuffle=False,
                                        num_workers=4)

    @property
    def train_dataloader(self) -> DataLoader:
        return self._train_data

    @property
    def test_dataloader(self) -> Union[DataLoader, List[DataLoader]]:
        return self._test_data

    @property
    def val_dataloader(self) -> Union[DataLoader, List[DataLoader]]:
        return self._val_data

    def _combine_text_label(self, texts, labels):
        text_label = []
        for id, text in texts.items():
            label = labels[id]
            text_label.append([text, label])

        text_label = np.array(text_label)

        return text_label[:, 0], text_label[:, 1]

    def _combine_data(self, texts, trees, labels):
        data = []

        for id, text in texts.items():
            label = labels[id]
            tree = trees[id]
            data.append([text, tree, label])

        data = np.array(data)
        data = self._normalize_data(data)
        
        return data[:, 0:2], data[:,2]

    def _normalize_data(self, data):
        return data

    def _read_text(self, path):
        pairs = {}
        with open(path, mode='r') as f:
            for line in f:
                id, text = line.split('\t')
                if id not in pairs.keys():

                    pairs[int(id)] = text
                else:
                    print('error')
        return pairs

    def _read_label(self, path):
        pairs = {}
        with open(path, mode='r') as f:
            for line in f:
                label, id = line.split(':')
                if id not in pairs.keys():

                    pairs[int(id)] = label
                else:
                    print('error')
        return pairs

    def _read_tree(self, t, path):
        pickle_fn = f"tree_maps_{t}.p"
        if os.path.isfile(os.path.join(settings.checkpoint,pickle_fn)):
            tree_map = pickle.load(open(os.path.join(settings.checkpoint,pickle_fn), "rb" ))
            print(f'load {pickle_fn}')
            return tree_map
        tree_map = {}
        for fn in tqdm(os.listdir(path)):
            index = fn.split('.')[0]
            tree_map[int(index)] = self._build_tree(os.path.join(path,fn))
        
        pickle.dump(tree_map, open(os.path.join(settings.checkpoint,pickle_fn), "wb"))
        print(f'saved {pickle_fn}')
        return tree_map

    def _build_tree(self, fn):
        root = None
        nodemap = {}
        with open(fn, mode='r') as f:
            for line in f:
                splited = line.split('->')
                p = ast.literal_eval(splited[0])
                c = ast.literal_eval(splited[1])
                np = Node(MyNode(*p))
                
                if root is None and np.name.id == 0:
                    root = Node(MyNode(*c))
                    nodemap[root.name.id] = root
                    continue
                    
                if np.name.id not in nodemap:
                    nodemap[np.name.id] = np
                myp = nodemap[np.name.id]

                nc = Node(MyNode(*c), parent=myp)
                nodemap[nc.name.id] = nc
        
        return root

    def _encode_tree(self, tree_map: Mapping[str, Node], max_length=500, padding=False, deduct_first=False):
        encoded_trees = {}
        for index in sorted(tree_map.keys()):
            root = tree_map[index]
            root_t = root.name.t
            encoding = []

            for i, node in enumerate(LevelOrderIter(root)):
                if max_length != -1 and i >= max_length:
                    break
                
                if node.name.t-root_t < 0:
                   continue
                encoding.append(node.name.t-root_t)
                
            if deduct_first:
                encoding = encoding - encoding[1]
                encoding[0] = 0.0
            
            en_log = np.log10(np.array(encoding)+1)

            encoding = en_log
            if padding:
                len_e = len(encoding)
                if max_length - len_e > 0:
                   encoding = np.pad(encoding, (0, max_length-len_e))
            
            encoded_trees[index] = encoding
        
        avg = []
        for k, v in encoded_trees.items():
            avg.append(np.average(v))
        
        my_mean = np.average(avg)
        my_std = np.std(avg)

        avg = []
        for k in encoded_trees.keys():
            encoded_trees[k] = (encoded_trees[k] - my_mean)
            avg.append(np.average(encoded_trees[k]))
        
        '''
        print('my_mean ', my_mean, ' my_std', my_std)
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(5,5))
        ax.hist(avg,bins=list(np.arange(-5,5,0.1)))
        plt.savefig('twitter_avg.png')
        plt.close()
        '''

        return encoded_trees, my_mean, my_std