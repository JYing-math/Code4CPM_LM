import torch
import torch.nn as nn
import numpy as np
import matplotlib.pyplot as plt
import functools
from pyDOE import lhs

from functorch import make_functional, vmap, grad, jacrev, hessian

from collections import namedtuple, OrderedDict
import datetime
import time
from IPython.display import clear_output

import warnings
warnings.filterwarnings('ignore')

'''  Solve the following PDE

'''
'''-------------------------Empty cache and check devices-------------------------'''
torch.cuda.empty_cache()
torch.set_default_dtype(torch.float64)
device = 'cuda' if torch.cuda.is_available() else 'cpu'
print('device = ', device)
'''-------------------------Pre-setup-------------------------'''
# iteration counts and check
tr_iter_max    = 10000                      # max. iteration
ts_input_new   = 1000                       # renew testing points
ls_check       = 1000
ls_check0      = ls_check - 1
# number of training points and testing points
N_tsd_final = 250000 #100*N_trd
N_tsg_final = 1000   #10*N_trg
# tolerence for LM
tol_main    = 10**(-12)
tol_machine = 10**(-15)
mu_max      = 10**8
mu_ini      = 10**8
'''-------------------------Data generator-------------------------'''
# Ω内取点，即六维半径为0.6的球内随机取点
def get_omega_points(num):
    x1 = 2 * torch.rand(num, 1) - 1
    x2 = 2 * torch.rand(num, 1) - 1
    x3 = 2 * torch.rand(num, 1) - 1
    x4 = 2 * torch.rand(num, 1) - 1
    x5 = 2 * torch.rand(num, 1) - 1
    x6 = 2 * torch.rand(num, 1) - 1
    x = torch.cat((x1, x2, x3, x4, x5, x6), dim=1)
    r = torch.pow(torch.sum(torch.pow(x, 2), 1), 0.5)
    r = torch.unsqueeze(r, 1)
    R = 0.6 * torch.rand(num, 1)
    xo = R * x / r
    return xo

# 边界上取点
def get_boundary_points(num):
    x1 = 2 * torch.rand(num, 1) - 1
    x2 = 2 * torch.rand(num, 1) - 1
    x3 = 2 * torch.rand(num, 1) - 1
    x4 = 2 * torch.rand(num, 1) - 1
    x5 = 2 * torch.rand(num, 1) - 1
    x6 = 2 * torch.rand(num, 1) - 1
    x = torch.cat((x1, x2, x3, x4, x5, x6), dim=1)
    r = torch.pow(torch.sum(torch.pow(x, 2), 1), 0.5)
    r = torch.unsqueeze(r, 1)
    xb = 0.6 * x / r
    return xb


# Γ上取点
def get_interface_points(num):
    x1 = 2 * torch.rand(num, 1) - 1
    x2 = 2 * torch.rand(num, 1) - 1
    x3 = 2 * torch.rand(num, 1) - 1
    x4 = 2 * torch.rand(num, 1) - 1
    x5 = 2 * torch.rand(num, 1) - 1
    x6 = 2 * torch.rand(num, 1) - 1
    x = torch.cat((x1, x2, x3, x4, x5, x6), dim=1)
    r = torch.pow(torch.sum(torch.pow(x, 2), 1), 0.5)
    r = torch.unsqueeze(r, 1)
    xif = 0.5 * x / r
    return xif

def get_omega_p_points(x):
    m = mark(x)
    index = m > 0
    xo1 = x[index, :]
    return xo1

def get_omega_n_points(x):
    m = mark(x)
    index = m < 0
    xo2 = x[index, :]
    return xo2

def add_dimension(x):
    m = mark(x)
    index1 = m >= 0
    index2 = m < 0
    index1 = index1.float()
    index2 = index2.float()
    index1 = torch.unsqueeze(index1, 1)
    index2 = torch.unsqueeze(index2, 1)
    lf = level_set_fuction(x) * (index1 - index2)
    x_3 = torch.cat((x, lf), 1)
    return x_3

def mark(x):
    lf = level_set_fuction(x)
    m = torch.squeeze(lf ,1)
    return m
'''-------------------------Functions-------------------------'''
# 获取界面处的法向导数
def get_normal_interface(x):
    r = torch.sqrt(torch.sum(torch.pow(x, 2), 1))
    n1 = x[:, 0] / r
    n2 = x[:, 1] / r
    n3 = x[:, 2] / r
    n4 = x[:, 3] / r
    n5 = x[:, 4] / r
    n6 = x[:, 5] / r
    n1 = torch.unsqueeze(n1, 1)
    n2 = torch.unsqueeze(n2, 1)
    n3 = torch.unsqueeze(n3, 1)
    n4 = torch.unsqueeze(n4, 1)
    n5 = torch.unsqueeze(n5, 1)
    n6 = torch.unsqueeze(n6, 1)
    n = torch.cat((n1, n2, n3, n4, n5, n6),dim=1)
    return n

#水平集函数
def level_set_fuction(x):
    lf = torch.sum(torch.pow(x, 2), 1) - 0.5 ** 2
    lf = torch.unsqueeze(lf, 1)
    return lf

def u_x(x):
    m = mark(x)
    index = m
    r = torch.sqrt(torch.sum(torch.pow(x, 2), 1))
    u1 = torch.exp(0.25 - torch.pow(r,2)) + \
         torch.sin(x[:,0]) + torch.sin(x[:,1]) + torch.sin(x[:,2]) + torch.sin(x[:,3]) + torch.sin(x[:,4])
    u2 = 1 + 2*torch.sin(0.25 - torch.pow(r, 2)) + \
         torch.sin(x[:,0]) + torch.sin(x[:,1]) + torch.sin(x[:,2]) + torch.sin(x[:,3]) + torch.sin(x[:,4])
    u_x = torch.where(index >= 0, u1, u2)
    u_x = torch.unsqueeze(u_x, 1)
    return u_x

def g_x(x):
    r = torch.sqrt(torch.sum(torch.pow(x, 2), 1))
    g = torch.exp(0.25 - torch.pow(r, 2)) + \
         torch.sin(x[:, 0]) + torch.sin(x[:, 1]) + torch.sin(x[:, 2]) + torch.sin(x[:, 3]) + torch.sin(x[:, 4])
    g = torch.unsqueeze(g, 1)
    return g

def f_x(x):
    m = mark(x)
    index = m
    r = torch.sqrt(torch.sum(torch.pow(x, 2), 1))
    f1 = -12 * torch.exp(0.25 - r ** 2) + 4 * torch.pow(r, 2) * torch.exp(0.25 - r ** 2) - \
         torch.sin(x[:, 0]) - torch.sin(x[:, 1]) - torch.sin(x[:, 2]) - torch.sin(x[:, 3]) - torch.sin(x[:, 4])
    f2 = -24 * torch.cos(0.25 - r ** 2) - 8 * torch.pow(r, 2) * torch.sin(0.25 - r ** 2) - \
         torch.sin(x[:, 0]) - torch.sin(x[:, 1]) - torch.sin(x[:, 2]) - torch.sin(x[:, 3]) - torch.sin(x[:, 4])
    f_x = torch.where(index >= 0, f1, f2)
    f_x = torch.unsqueeze(f_x, 1)
    return f_x
'''-------------------------Define networks-------------------------'''
class NeuralNet_Shallow(torch.nn.Module):

    ### in_dim: dimension of input; h_dim: number of neurons; out_dim: dimension of output

    def __init__(self, in_dim, h_dim, out_dim):
        super(NeuralNet_Shallow, self).__init__()
        self.ln1 = nn.Linear(in_dim, h_dim)
        self.act1 = nn.Sigmoid()
        # self.act1 = nn.Tanh()
        # self.act1 = nn.ReLU()

        self.ln2 = nn.Linear(h_dim, out_dim, bias=False)

    def forward(self, x):
        out = self.ln1(x)
        out = self.act1(out)
        out = self.ln2(out)
        return out


class NeuralNet_Deep(torch.nn.Module):

    ### in_dim: dimension of input; h_dim: number of neurons; out_dim: dimension of output
    ### depth: depth of the network
    def __init__(self, in_dim, h_dim, out_dim, depth):
        super(NeuralNet_Deep, self).__init__()
        self.depth = depth - 1
        self.list = nn.ModuleList()
        self.ln1 = nn.Linear(in_dim, h_dim)
        #self.act1 = nn.Sigmoid()
        self.act1 = nn.Tanh()
        # self.act1 = nn.ReLU()

        for i in range(self.depth):
            self.list.append(nn.Linear(h_dim, h_dim))

        self.lnd = nn.Linear(h_dim, out_dim, bias=False)

    def forward(self, x):
        out = self.ln1(x)
        out = self.act1(out)
        for i in range(self.depth):
            out = self.list[i](out)
            out = self.act1(out)
        out = self.lnd(out)
        return out
'''-------------------------Loss functions-------------------------'''
def func_loss_op(func_params, x_op, f_op):
    def f(x, func_params):
        fx = func_model(func_params, x)
        return fx.squeeze(0).squeeze(0)
        # derivatives of u wrt inputs

    d1u = jacrev(f)(x_op, func_params)
    d2u = jacrev(jacrev(f))(x_op, func_params)

    f_op = f_op[0]
    u_z = d1u[6]
    u_zz = d2u[6][6]
    u_aa = d2u[0][0]
    u_az = d2u[0][6]
    u_bb = d2u[1][1]
    u_bz = d2u[1][6]
    u_cc = d2u[2][2]
    u_cz = d2u[2][6]
    u_dd = d2u[3][3]
    u_dz = d2u[3][6]
    u_ee = d2u[4][4]
    u_ez = d2u[4][6]
    u_ff = d2u[5][5]
    u_fz = d2u[5][6]
    phi_a = 2. * x_op[0]
    phi_b = 2. * x_op[1]
    phi_c = 2. * x_op[2]
    phi_d = 2. * x_op[3]
    phi_e = 2. * x_op[4]
    phi_f = 2. * x_op[5]
    phi_aa = 2. * torch.ones_like(phi_a)
    phi_bb = 2. * torch.ones_like(phi_b)
    phi_cc = 2. * torch.ones_like(phi_c)
    phi_dd = 2. * torch.ones_like(phi_d)
    phi_ee = 2. * torch.ones_like(phi_e)
    phi_ff = 2. * torch.ones_like(phi_f)
    U_aa = u_aa + u_az * phi_a + u_az * phi_a + u_zz * phi_a * phi_a + u_z * phi_aa
    U_bb = u_bb + u_bz * phi_b + u_bz * phi_b + u_zz * phi_b * phi_b + u_z * phi_bb
    U_cc = u_cc + u_cz * phi_c + u_cz * phi_c + u_zz * phi_c * phi_c + u_z * phi_cc
    U_dd = u_dd + u_dz * phi_d + u_dz * phi_d + u_zz * phi_d * phi_d + u_z * phi_dd
    U_ee = u_ee + u_ez * phi_e + u_ez * phi_e + u_zz * phi_e * phi_e + u_z * phi_ee
    U_ff = u_ff + u_fz * phi_f + u_fz * phi_f + u_zz * phi_f * phi_f + u_z * phi_ff

    loss_op = U_aa + U_bb + U_cc + U_dd + U_ee + U_ff - f_op
    return loss_op

def func_loss_on(func_params, x_on, f_on):
    def f(x, func_params):
        fx = func_model(func_params, x)
        return fx.squeeze(0).squeeze(0)
        # derivatives of u wrt inputs

    d1u = jacrev(f)(x_on, func_params)
    d2u = jacrev(jacrev(f))(x_on, func_params)

    f_on = f_on[0]
    u_z = d1u[6]
    u_zz = d2u[6][6]
    u_aa = d2u[0][0]
    u_az = d2u[0][6]
    u_bb = d2u[1][1]
    u_bz = d2u[1][6]
    u_cc = d2u[2][2]
    u_cz = d2u[2][6]
    u_dd = d2u[3][3]
    u_dz = d2u[3][6]
    u_ee = d2u[4][4]
    u_ez = d2u[4][6]
    u_ff = d2u[5][5]
    u_fz = d2u[5][6]
    phi_a = -2. * x_on[0]
    phi_b = -2. * x_on[1]
    phi_c = -2. * x_on[2]
    phi_d = -2. * x_on[3]
    phi_e = -2. * x_on[4]
    phi_f = -2. * x_on[5]
    phi_aa = -2. * torch.ones_like(phi_a)
    phi_bb = -2. * torch.ones_like(phi_b)
    phi_cc = -2. * torch.ones_like(phi_c)
    phi_dd = -2. * torch.ones_like(phi_d)
    phi_ee = -2. * torch.ones_like(phi_e)
    phi_ff = -2. * torch.ones_like(phi_f)
    U_aa = u_aa + u_az * phi_a + u_az * phi_a + u_zz * phi_a * phi_a + u_z * phi_aa
    U_bb = u_bb + u_bz * phi_b + u_bz * phi_b + u_zz * phi_b * phi_b + u_z * phi_bb
    U_cc = u_cc + u_cz * phi_c + u_cz * phi_c + u_zz * phi_c * phi_c + u_z * phi_cc
    U_dd = u_dd + u_dz * phi_d + u_dz * phi_d + u_zz * phi_d * phi_d + u_z * phi_dd
    U_ee = u_ee + u_ez * phi_e + u_ez * phi_e + u_zz * phi_e * phi_e + u_z * phi_ee
    U_ff = u_ff + u_fz * phi_f + u_fz * phi_f + u_zz * phi_f * phi_f + u_z * phi_ff

    loss_on = U_aa + U_bb + U_cc + U_dd + U_ee + U_ff - f_on
    return loss_on

def func_loss_b(func_params, x_b, f_b):
    def f(x, func_params):
        fx = func_model(func_params, x)
        return fx.squeeze(0).squeeze(0)

    f_b = f_b[0]
    # function value at the boundary (Dirichlet)
    u = f(x_b, func_params)
    loss_b = u - f_b
    return 100*loss_b

def func_loss_if(func_params, x_if, nor):
    def f(x, func_params):
        fx = func_model(func_params, x)
        return fx.squeeze(0).squeeze(0)

    # derivatives of u wrt inputs
    d1u = jacrev(f)(x_if, func_params)
    u_z = d1u[6]
    nor1 = nor[0]
    nor2 = nor[1]
    nor3 = nor[2]
    nor4 = nor[3]
    nor5 = nor[4]
    nor6 = nor[5]
    phi_a = 4. * x_if[0]
    phi_b = 4. * x_if[1]
    phi_c = 4. * x_if[2]
    phi_d = 4. * x_if[3]
    phi_e = 4. * x_if[4]
    phi_f = 4. * x_if[5]
    loss_if = u_z * phi_a * nor1 + u_z * phi_b * nor2 + u_z * phi_c * nor3 + u_z * phi_d * nor4 + u_z * phi_e * nor5  + u_z * phi_f * nor6 - 1

    return 10*loss_if
'''-------------------------Levenberg-Marquardt (LM) optimizer-------------------------'''
# parameters counter
def count_parameters(func_params):
    return sum(p.numel() for p in func_params if p.requires_grad)

# get the model's parameter
def get_p_vec(func_params):
    p_vec = []
    cnt = 0
    for p in func_params:
        p_vec = p.contiguous().view(-1) if cnt == 0 else torch.cat([p_vec, p.contiguous().view(-1)])
        cnt = 1
    return p_vec

# Initialization of LM method
def generate_initial_LM(func_params, Xo1_len, Xo2_len, Xb_len, Xg_len):
    # data_length
    data_length = Xo1_len + Xo2_len + Xb_len + Xg_len # 输入数据长度和

    # p_vector p向量自然为model参数
    with torch.no_grad():
        p_vec_old = get_p_vec(func_params).double().to(device)

    # dp 初始所有参量搜索方向设置为0，其size应当和model参数一致
    dp_old = torch.zeros([count_parameters(func_params), 1]).double().to(device)

    # Loss 损失函数值同样设置为0
    L_old = torch.zeros([data_length, 1]).double().to(device)

    # Jacobian J矩阵同样
    J_old = torch.zeros([data_length, count_parameters(func_params)]).double().to(device)

    return p_vec_old, dp_old, L_old, J_old


def train_PINNs_LM(func_params, LM_setup, tr_input, lossval, lossval_dbg):
    # assign tuple elements of LM_set_up
    p_vec_o, dp_o, L_o, J_o, mu, criterion = LM_setup # old参数导入
    I_pvec = torch.eye(len(p_vec_o)).to(device) # 单位阵

    # assign tuple elements of data_input
    [X_op, F_op, X_on, F_on, X_b, F_b, X_if, nor, NL, NL_sqrt] = tr_input #训练参数

    # iteration counts and check
    Comput_old = True
    step = 0

    # try-except statement to avoid jam in the code
    try:
        while (lossval[-1] > tol_main) and (step <= tr_iter_max):

            torch.cuda.empty_cache()

            ############################################################
            # LM_optimizer
            if (Comput_old == True):  # need to compute loss_old and J_old

                ### computation of loss 计算各部分损失函数
                Lop = vmap((func_loss_op), (None, 0, 0))(func_params, X_op, F_op).flatten().detach()
                Lon = vmap((func_loss_on), (None, 0, 0))(func_params, X_on, F_on).flatten().detach()
                Lb = vmap((func_loss_b), (None, 0, 0))(func_params, X_b, F_b).flatten().detach()
                Lif = vmap((func_loss_if), (None, 0, 0))(func_params, X_if, nor).flatten().detach()
                L = torch.cat((Lop / NL_sqrt[1], Lon / NL_sqrt[2], Lb / NL_sqrt[3], Lif / NL_sqrt[4]))
                L = L.reshape(NL[0], 1).detach()
                lsdp_sum = torch.sum(Lop * Lop) / NL[1]
                lsdn_sum = torch.sum(Lon * Lon) / NL[2]
                lsb_sum = torch.sum(Lb * Lb) / NL[3]
                lsif_sum = torch.sum(Lif * Lif) / NL[4]
                loss_dbg_old = [lsdp_sum.item(), lsdn_sum.item(), lsb_sum.item(), lsif_sum.item()]

            loss_old = lossval[-1]
            loss_dbg_old = lossval_dbg[-1]

            ### compute the gradinet of loss function for each point
            with torch.no_grad():
                p_vec = get_p_vec(func_params).detach()  # get p_vec for p_vec_old if neccessary

            if criterion:
                per_sample_grads = vmap(jacrev(func_loss_op), (None, 0, 0))(func_params, X_op, F_op)
                cnt = 0
                for g in per_sample_grads:
                    g = g.detach()
                    J_op = g.reshape(len(g), -1) if cnt == 0 else torch.hstack([J_op, g.reshape(len(g), -1)])
                    cnt = 1

                per_sample_grads = vmap(jacrev(func_loss_on), (None, 0, 0))(func_params, X_on, F_on)
                cnt = 0
                for g in per_sample_grads:
                    g = g.detach()
                    J_on = g.reshape(len(g), -1) if cnt == 0 else torch.hstack([J_on, g.reshape(len(g), -1)])
                    cnt = 1

                per_sample_grads = vmap(jacrev(func_loss_b), (None, 0, 0))(func_params, X_b, F_b)
                cnt = 0
                for g in per_sample_grads:
                    g = g.detach()
                    J_b = g.reshape(len(g), -1) if cnt == 0 else torch.hstack([J_b, g.reshape(len(g), -1)])
                    cnt = 1

                per_sample_grads = vmap(jacrev(func_loss_if), (None, 0, 0))(func_params, X_if, nor)
                cnt = 0
                for g in per_sample_grads:
                    g = g.detach()
                    J_if = g.reshape(len(g), -1) if cnt == 0 else torch.hstack([J_if, g.reshape(len(g), -1)])
                    cnt = 1

                J = torch.cat((J_op / NL_sqrt[1], J_on / NL_sqrt[2], J_b / NL_sqrt[3], J_if / NL_sqrt[4])).detach()
                # 组装好了J矩阵
                ### info. normal equation of J
                J_product = J.t() @ J
                rhs = - J.t() @ L

            with torch.no_grad():
                ### solve the linear system
                dp = torch.linalg.solve(J_product + mu * I_pvec, rhs)
                cnt = 0
                for p in func_params:
                    mm = torch.Tensor([p.shape]).tolist()[0]
                    num = int(functools.reduce(lambda x, y: x * y, mm, 1))
                    p += dp[cnt:cnt + num].reshape(p.shape)
                    cnt += num

            ### Compute loss_new
            Lop = vmap((func_loss_op), (None, 0, 0))(func_params, X_op, F_op).flatten().detach()
            Lon = vmap((func_loss_on), (None, 0, 0))(func_params, X_on, F_on).flatten().detach()
            Lb = vmap((func_loss_b), (None, 0, 0))(func_params, X_b, F_b).flatten().detach()
            Lif = vmap((func_loss_if), (None, 0, 0))(func_params, X_if, nor).flatten().detach()
            L = torch.cat((Lop / NL_sqrt[1], Lon / NL_sqrt[2], Lb / NL_sqrt[3], Lif / NL_sqrt[4]))
            L = L.reshape(NL[0], 1).detach()
            loss_new = torch.sum(L * L).item()
            lsdp_sum = torch.sum(Lop * Lop) / NL[1]
            lsdn_sum = torch.sum(Lon * Lon) / NL[2]
            lsb_sum = torch.sum(Lb * Lb) / NL[3]
            lsif_sum = torch.sum(Lif * Lif) / NL[4]
            loss_dbg_new = [lsdp_sum.item(), lsdn_sum.item(), lsb_sum.item(), lsif_sum.item()]

            # strategy to update mu
            if (step > 0):

                with torch.no_grad():

                    # accept update
                    if loss_new < loss_old:
                        p_vec_old = p_vec.detach()
                        dp_old = dp
                        L_old = L
                        J_old = J
                        mu = max(mu / mu_div, tol_machine)
                        criterion = True  # False
                        Comput_old = False
                        lossval.append(loss_new)
                        lossval_dbg.append(loss_dbg_new)

                    else:
                        cosine = nn.functional.cosine_similarity(dp, dp_old, dim=0, eps=1e-15)
                        cosine_check = (1. - cosine) * loss_new > min(lossval)  # loss_old
                        if cosine_check:  # give up the direction
                            cnt = 0
                            for p in func_params:
                                mm = torch.Tensor([p.shape]).tolist()[0]
                                num = int(functools.reduce(lambda x, y: x * y, mm, 1))
                                p -= dp[cnt:cnt + num].reshape(p.shape)
                                cnt += num
                            mu = min(mu_mul * mu, mu_max)
                            criterion = False
                            Comput_old = False
                        else:  # accept
                            p_vec_old = p_vec.detach()
                            dp_old = dp
                            L_old = L
                            J_old = J
                            mu = max(mu / mu_div, tol_machine)
                            criterion = True
                            Comput_old = False
                        lossval.append(loss_old)
                        lossval_dbg.append(loss_dbg_old)

            else:  # for old info.

                with torch.no_grad():

                    p_vec_old = p_vec.detach()
                    dp_old = dp
                    L_old = L
                    J_old = J
                    mu = max(mu / mu_div, tol_machine)
                    criterion = True
                    Comput_old = False
                    lossval.append(loss_new)
                    lossval_dbg.append(loss_dbg_new)

            if step % ls_check == ls_check0:
                print("Step %s: " % (step))
                print(f" training loss: {lossval[-1]:.4e}")

            step += 1

        print("Step %s: " % (step - 1))
        print(f" training loss: {lossval[-1]:.4e}")
        print('finished')
        lossval = lossval[1:]
        lossval_dbg = lossval_dbg[1:]
        relerr_loss = lossval[-1]
        return lossval, lossval_dbg, relerr_loss

    except KeyboardInterrupt:
        print('Interrupt')
        print('steps = ', step)
        lossval = lossval[1:]
        lossval_dbg = lossval_dbg[1:]
        relerr_loss = lossval[-1]
        return lossval, lossval_dbg, relerr_loss



'''-------------------------Train-------------------------'''
def generate_data(num_omega, num_b, num_if):
    xo = get_omega_points(num_omega)
    xop = get_omega_p_points(xo)
    xon = get_omega_n_points(xo)
    xb = get_boundary_points(num_b)
    xif = get_interface_points(num_if)

    xop_tr = add_dimension(xop)
    xon_tr = add_dimension(xon)
    xb_tr = add_dimension(xb)
    xif_tr = add_dimension(xif)
    fop_tr = f_x(xop)
    fon_tr = f_x(xon)
    fb_tr = g_x(xb)
    nor = get_normal_interface(xif)
    len_xop = len(xop)
    len_xon = len(xon)
    len_sum = num_omega + num_b + num_if

    NL = [len_sum, len_xop, len_xon, num_b, num_if]
    NL_sqrt = np.sqrt(NL)

    xop_tr = torch.tensor(xop_tr, requires_grad=True).double().to(device)
    xon_tr = torch.tensor(xon_tr, requires_grad=True).double().to(device)
    xb_tr = torch.tensor(xb_tr, requires_grad=True).double().to(device)
    xif_tr = torch.tensor(xif_tr, requires_grad=True).double().to(device)
    fop_tr = torch.tensor(fop_tr).double().to(device)
    fon_tr = torch.tensor(fon_tr).double().to(device)
    fb_tr = torch.tensor(fb_tr).double().to(device)
    nor = torch.tensor(nor).double().to(device)

    return xop_tr, fop_tr, xon_tr, fon_tr, xb_tr, fb_tr, xif_tr, nor, NL, NL_sqrt
# Essential namedtuples in the model
DataInput = namedtuple( "DataInput" , [ "X_op" , "F_op" , "X_on" , "F_on", "X_b" , "F_b" , "X_if" , "nor", "NL" , "NL_sqrt"] )
LM_Setup  = namedtuple( "LM_Setup" , [ 'p_vec_o' , 'dp_o' , 'L_o' , 'J_o' , 'mu0' , 'criterion' ] )

# create names for storages
fname = 'test'
char_id = 'a'

# Network size
n_input = 7
n_hidden = 40
n_output = 1
n_depth = 2  # only used in deep NN
mu_div = 3.
mu_mul = 2.

# number of training and test data points
c_addpt = 1.
num_omega = 1000
num_b = 300 #注意此处设置的为每个边取点数量
num_if = 200


# storages for errors, time instants, and IRK stages
relerr_loss = []
for char in char_id:
    # file name
    fname_char = fname + char

    torch.cuda.empty_cache()  # 清理变量

    # NN structure
    if n_depth == 1:  # Shallow NN
        model = NeuralNet_Shallow(n_input, n_hidden, n_output).double().to(device)
    else:  # Deep NN
        model = NeuralNet_Deep(n_input, n_hidden, n_output, n_depth).double().to(device)

    # use Pytorch and functorch
    func_model, func_params = make_functional(model)  # 获取model及其参数

    xop_tr, fop_tr, xon_tr, fon_tr, xb_tr, fb_tr, xif_tr, nor, NL_tr, NL_sqrt_tr = generate_data(num_omega, num_b, num_if)
    tr_input = DataInput(X_op=xop_tr, F_op=fop_tr, X_on=xon_tr, F_on=fon_tr, X_b=xb_tr, F_b=fb_tr, X_if=xif_tr, nor=nor, NL=NL_tr, NL_sqrt=NL_sqrt_tr)

    # initialization of LM
    p_vec_old, dp_old, L_old, J_old = generate_initial_LM(func_params, NL_tr[1], NL_tr[2], NL_tr[3], NL_tr[4])  # 初始化LM算法
    print(f"No. of parameters = {len(p_vec_old)}")

    # LM_setup
    mu = 10 ** (8)  # 初始mu值设置大一点，有利于快速下降
    criterion = True
    LM_setup = LM_Setup(p_vec_o=p_vec_old, dp_o=dp_old, L_o=L_old, J_o=J_old, mu0=mu, criterion=criterion)  # 初始化参数导入

    # allocate loss
    lossval = []  # 总损失函数平均值
    lossval_dbg = []  # 各部分损失函数平均值
    lossval.append(1.)
    lossval_dbg.append([1., 1., 1.])

    # start the timer
    cnt_start = time.time()

    # train the model by LM optimizer
    lossval, lossval_dbg, relerr_loss_char = train_PINNs_LM(func_params, LM_setup, tr_input, lossval, lossval_dbg)
    relerr_loss.append(relerr_loss_char)

    end_start = time.time()
    total_T = str(datetime.timedelta(seconds=end_start - cnt_start))
    print(f"total time : {total_T}")

    print('ok')


# plot evolution of loss
N_loss = len(lossval)
lossval        = np.array(lossval).reshape(N_loss,1)
epochcol = np.linspace(1, N_loss, N_loss).reshape(N_loss,1)

plt.figure(figsize = (5,5))

plt.semilogy(epochcol, lossval)
plt.title('loss')
plt.xlabel('epoch')
plt.show()

'''-------------------------Error-------------------------'''
point_r = get_omega_points(10000)
point_p = add_dimension(point_r)
pred_u = func_model(func_params, point_p).cpu().detach().numpy().flatten()
pred_u = torch.tensor(pred_u).double()
pred_u = torch.unsqueeze(pred_u, 1)
loss_l2 = torch.sqrt(torch.mean(torch.pow(pred_u - u_x(point_r),2)))
loss_rel_l2 = loss_l2 / torch.sqrt(torch.mean(torch.pow(u_x(point_r), 2)))
loss_inf = torch.max(torch.abs(pred_u - u_x(point_r)))
loss_rel_inf = loss_inf / torch.max(u_x(point_r))
print('l2相对误差:', loss_rel_l2.item())
print('无穷范数相对误差:', loss_rel_inf.item())




