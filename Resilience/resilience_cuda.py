import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
import argparse
import numpy as np
import torch
import networkx as nx
import torch.nn as nn
# from keras.src.ops import dtype
import matplotlib.pyplot as plt
import time
from torch.optim.lr_scheduler import ReduceLROnPlateau

from utils.utils import find_value_according_index_list, robustness_score
from utils.model_cuda import (ILGRModel, softsort)
from utils.GraphConstruct import location_graph

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
parser.add_argument("--max_epoch", type=int, default=200)
parser.add_argument("--lr", type=float, default=1e-6)
parser.add_argument("--hidden_dim", default=1000, type=int)
parser.add_argument("--output_dim", default=50, type=int)
parser.add_argument("--num_layer", default=2, type=int)
parser.add_argument("--weight_decay", type=int, default=1e-4)
args = parser.parse_args()
args.cuda = torch.cuda.is_available()
print("use cuda: {}".format(args.cuda))
device = torch.device("cuda" if args.cuda else "cpu")


# 读取数据
weights=[]
wpr_rank=[]
with open('../MGC-RM/similarity score/zGP_75_node_450_data_2000model_20241102_211834.txt', 'r') as f:
    for line in f:
        weights.append(float(list(line.strip('\n').split(','))[0]))
with open('../MGC-RM/WPR_result/_node_list_GP_75_node_450_data_2000.txt', 'r') as f:
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
unselected_node = wpr_rank[select_node+1:114]
un_fea_list = find_value_according_index_list(fea_o, unselected_node)
un_location_list = find_value_according_index_list(location, unselected_node)

# Rg_o = robustness_score(G)

args.input_dim = data_num
print('input_dim: ',args.input_dim)
ILGR_model = ILGRModel(args.input_dim, args.hidden_dim, args.output_dim, args.num_layer, args).to(device)
optimizer = torch.optim.Adam(ILGR_model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
loss_CrossEntropy = nn.CrossEntropyLoss()
scheduler = ReduceLROnPlateau(optimizer, mode='min', factor=0.1, patience=1, cooldown = 1,verbose=True)

# 重新构图，摘取特征值，计算关键性评分（弹性分数）
R_g = [[] for _ in range(len(unselected_node))]
R_A = [[] for _ in range(len(unselected_node))]
R_Rg = []
location_list.append(None)
fea_list.append(None)
for i, (location, fea) in enumerate(zip(un_location_list, un_fea_list)):
    location_list[select_node] = location
    fea_list[select_node] = fea
    R_g[i], R_A[i] = location_graph(location_list)
    R_Rg.append(torch.tensor(robustness_score(R_g[i]))) # n*1

# fea_list_tensor = torch.tensor(np.array(fea_list), requires_grad=True).requires_grad_(True).to(device)
R_Rg_tensor = torch.stack(R_Rg, dim=0).requires_grad_(True).to(device)

# 真实值
# 关键性评分的排序
# criticality_scores = torch.argsort(R_Rg_tensor).to(device)
criticality_scores = softsort(R_Rg_tensor)
criticality_scores_normal = (criticality_scores - torch.min(criticality_scores)) / (
             torch.max(criticality_scores) - torch.min(criticality_scores))
# 关键性评分的分数
# criticality_scores_normal = (R_Rg_tensor - torch.min(R_Rg_tensor)) / (
#             torch.max(R_Rg_tensor) - torch.min(R_Rg_tensor))

# np.savetxt('./robustness_score/R_Rg_tensor_'+str(len(unselected_node))+'.txt', R_Rg_tensor.detach().numpy())
# np.savetxt('./robustness_score/criticality_scores_normal_'+str(len(unselected_node))+'.txt', criticality_scores_normal.detach().numpy())



scores=[[] for _ in range(len(unselected_node))]
loss_history = []
# 训练过程
for epoch in range(args.max_epoch):  # 假设训练100个epoch
    tensors = []
    for i, (location, fea) in enumerate(zip(un_location_list, un_fea_list)):
        location_list[select_node] = location
        fea_list[select_node] = fea
        fea_list_tensor = torch.tensor(np.array(fea_list), requires_grad=True).requires_grad_(True).to(device)
        ILGR_model.train()
        R_g_tensor = R_g[i]
        scores[i] = ILGR_model(fea_list_tensor, R_g_tensor)
        tensors.append(scores[i])
    scores_tensor = torch.stack(tensors, dim=0).requires_grad_(True).to(device)
    # 预测分数的排序
    scores_tensor_scores = softsort(scores_tensor)
    optimizer.zero_grad()

    # 排序，排序
    # loss = ranking_loss2(scores_tensor_scores, criticality_scores)
    # 分数，分数
    # loss = ranking_loss(scores_tensor, R_Rg_tensor)
    # 分数，排序
    # loss = ranking_loss(scores_tensor, criticality_scores)

    # CrossEntropy loss
    # 预测分数的排序值
    scores_tensor_normal = (scores_tensor_scores - torch.min(scores_tensor_scores)) / (torch.max(scores_tensor_scores) - torch.min(scores_tensor_scores))
    # 预测分数的分数值
    #scores_tensor_normal = (scores_tensor - torch.min(scores_tensor)) / (torch.max(scores_tensor) - torch.min(scores_tensor))
    r_ij = [] # 真实值
    y_hat_ij = []  # 预测值
    for i in range(len(scores_tensor_normal)-1):
        for j in range(i + 1, len(scores_tensor_normal)-1):
            r_ij.append(criticality_scores_normal[i] - criticality_scores_normal[j])
            y_hat_ij.append(scores_tensor_normal[i] - scores_tensor_normal[j])
    r_ij_tensor = torch.stack(r_ij, dim=0).requires_grad_(True).to(device)
    y_hat_ij_tensor = torch.stack(y_hat_ij, dim=0).requires_grad_(True).to(device)
    loss = loss_CrossEntropy(y_hat_ij_tensor, r_ij_tensor)
    # print(loss.item())

    loss.backward(retain_graph=True)
    optimizer.step()
    loss_history.append(loss.item())
    scheduler.step(loss.item())
    print('epoch:{}, loss:{}'.format(epoch, loss))


fig = plt.figure()
ax1 = fig.add_subplot(111)
ax1.plot(range(len(loss_history)), loss_history)
plt.ylabel('Loss')
plt.xlabel('Epoch : {}'.format(args.max_epoch))
plt.title('Training Loss: epoch' + str(args.max_epoch)+' lr'+ str(args.lr)+' '+str(device))
plt.text(0, loss_history[0], str(format(loss_history[0],'.8f')))
print(format(loss_history[(args.max_epoch - 1)],'.15f'))
plt.text(round(args.max_epoch/10*9) , loss_history[(args.max_epoch - 1)], str(format(loss_history[(args.max_epoch - 1)],'.10f')),
         horizontalalignment='left')

# time stamp
timestamp = time.time()
localtime = time.localtime(timestamp)
formatted_time = time.strftime('%Y%m%d_%H%M%S',localtime)

# Save
plt.savefig('./training_loss/_Training_Loss_epoch_' + str(args.max_epoch) + '_lr_'+ str(args.lr)+'_'+str(formatted_time)+'.svg', format='svg')
plt.show()
torch.save(ILGR_model, './model_save/_e_' + str(args.max_epoch) + '_l_'+ str(args.lr)+'_'+str(formatted_time)+'.pth')
np.savetxt('./scores_save/scores_epoch_' + str(args.max_epoch) + '_lr_'+ str(args.lr)+'_'+str(formatted_time)+'.txt', scores_tensor.cpu().detach().numpy())
np.savetxt('./scores_save/softsort_normal_epoch_' + str(args.max_epoch) + '_lr_'+ str(args.lr)+'_'+str(formatted_time)+'.txt', scores_tensor_scores.cpu().detach().numpy())


location_list_a = np.array(location_list)
un_location_list_a = np.array(un_location_list)
plt.scatter(un_location_list_a[:,0], un_location_list_a[:,1], s=15, c=scores_tensor_scores.cpu().detach().numpy(), cmap='Greens')
plt.scatter(location_list_a[:select_node,0], location_list_a[:select_node,1], s=20, c='#f44336')  # selected_node
plt.xlabel('Longitude')
plt.ylabel('Latitude')
plt.colorbar()
plt.title('softsort_normal')
plt.savefig('./scores_save/_softsort_normal_epoch_' + str(args.max_epoch) + '_lr_'+ str(args.lr)+'_'+str(formatted_time)+'.svg', format='svg')
plt.show()