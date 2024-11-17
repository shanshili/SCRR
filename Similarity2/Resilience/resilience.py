import torch
import torch.nn as nn
import argparse
import numpy as np
import networkx as nx
from torch.optim import Adam
import sys
import matplotlib.pyplot as plt

# 将外部包的路径添加到 sys.path
sys.path.append('D:\Tjnu-p\ML-learning\similarity2\MGC-RM')
# 现在可以导入外部包了
from utils import find_value_according_index_list, robustness_score
from model import (GAT,ranking_loss,AttentionLayer,NodeEmbeddingModule,
                   RegressionModule,ILGRModel)
from GraphConstruct2 import location_graph

from matplotlib import rcParams


# 全局修改字体
config = {
            "font.family": 'Times New Roman',
            "font.size": 10.5,
            # "mathtext.fontset": 'stix',#matplotlib渲染数学字体时使用的字体，和Times New Roman差别不大
            # "font.serif": ['SimSun'],#宋体
            'axes.unicode_minus': False # 处理负号，即-号
         }
rcParams.update(config)


parser = argparse.ArgumentParser(
    description="train", formatter_class=argparse.ArgumentDefaultsHelpFormatter
)
parser.add_argument("--max_epoch", type=int, default=21)
parser.add_argument("--lr", type=float, default=0.0001)
parser.add_argument("--hidden_dim", default=1000, type=int)
parser.add_argument("--output_dim", default=250, type=int)
parser.add_argument("--num_layer", default=2, type=int)
parser.add_argument("--weight_decay", type=int, default=1e-4)
args = parser.parse_args()
args.cuda = torch.cuda.is_available()
print("use cuda: {}".format(args.cuda))
device = torch.device("cuda" if args.cuda else "cpu")


# 读取数据
weights=[]
wpr_rank=[]
with open('..\MGC-RM\similarity score\zGP_75_node_450_data_2000model_20241102_211834.txt','r') as f:
    for line in f:
        weights.append(float(list(line.strip('\n').split(','))[0]))
with open('..\MGC-RM\WPR_result\_node_list_GP_75_node_450_data_2000.txt','r') as f:
    for line in f:
        wpr_rank.append(int(list(line.strip('\n').split(','))[0]))
Gpn = 75
node = 450
data_num = 2000
select_node = 14
adj_ori = np.load('../MGC-RM/origin_data/adj_ori'+'_node_'+str(node)+'_data_'+str(data_num)+'.npz', allow_pickle=True)
location_file = np.load('../MGC-RM/origin_data/location'+'_node_'+str(node)+'_data_'+str(data_num)+'.npz', allow_pickle=True)
fea_ori = np.load('../MGC-RM/origin_data/fea_ori'+'_node_'+str(node)+'_data_'+str(data_num)+'.npz', allow_pickle=True)
fea_o = fea_ori['arr_0']
A = adj_ori['arr_0']
G = nx.Graph(adj_ori['arr_0'])
location = location_file['arr_0']
"""
在选择图的基础上获得鲁棒图
节点临界分数：鲁棒图中去掉该节点，图鲁棒性大幅下降
"""
selected_node  = wpr_rank[:select_node]
fea_list = find_value_according_index_list(fea_o, selected_node)
location_list = find_value_according_index_list(location, selected_node)
unselected_node = wpr_rank[select_node+1:]
un_fea_list = find_value_according_index_list(fea_o, unselected_node)
un_location_list = find_value_according_index_list(location, unselected_node)

Rg_o = robustness_score(G)
print(Rg_o)

args.input_dim = data_num
print('input_dim: ',args.input_dim)
ILGR_model = ILGRModel(args.input_dim, args.hidden_dim, args.output_dim, args.num_layer, args)
optimizer = torch.optim.Adam(ILGR_model.parameters(), lr=args.lr, weight_decay=args.weight_decay)


# 重新构图
R_g = [[] for _ in range(len(unselected_node))]
R_A = [[] for _ in range(len(unselected_node))]
R_Rg = [[] for _ in range(len(unselected_node))]
location_list.append(None)
fea_list.append(None)
# print(location_list)
for i, (location, fea) in enumerate(zip(un_location_list, un_fea_list)):
    location_list[select_node] = location
    fea_list[select_node] = fea
    # print(len(fea_list))
    # print(len(fea_list[0]))
    R_g[i], R_A[i] = location_graph(location_list)
    # plt.figure()
    # nx.draw(R_g[i], pos=location_list,  alpha=0.8, node_size=8,
    #         width=0.6, edge_color='#BBD6D8', font_size=0)
    # plt.show()
    R_Rg[i] = robustness_score(R_g[i])

# 对关键性评分进行排序
# print('R_Rg',R_Rg)
criticality_scores = np.argsort(np.array(R_Rg))
# print('criticality_scores',criticality_scores)


for i, (location, fea) in enumerate(zip(un_location_list, un_fea_list)):
    location_list[select_node] = location
    fea_list[select_node] = fea
    # 训练过程
    for epoch in range(100):  # 假设训练100个epoch
        ILGR_model.train()
        optimizer.zero_grad()
        scores = ILGR_model(fea_list, R_g[i])
        loss = ranking_loss(scores, R_Rg[i])
        loss.backward()
        optimizer.step()
        if epoch % 10 == 0:
            print(f"Epoch {epoch}, Loss: {loss.item()}")

    # 测试
    # ILGR_model.eval()
    # with torch.no_grad():
    #     test_scores = ILGR_model(fea_list, R_g[i])
    #     print("Test Scores:", test_scores)


