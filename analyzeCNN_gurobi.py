from scipy.special import comb
from sympy import *
from numpy import linalg as LA
from numpy import pi, tanh, array, dot
from scipy.optimize import linprog
from scipy.special import expit
from multiprocessing import Pool
from functools import partial
from operator import itemgetter
from gurobipy import *
import cvxpy as cp

import numpy as np
import sympy as sp
import itertools
import math
import random
import time
import copy

##############################################################
# Data structure of a neural network
# NN.type = {'Convolutional', 'Fully_connected'}
# NN.layers: list of layers
"""
New properties:
 layer.type = {'Convolutional', 'Pooling',
               'Fully_connected', 'Flatten', 'Activation'}
 layer.weight = weight if type = 'Fully_connected', None otherwise
 layer.bias = bias if type = 'Fully_connected' or 'Convolutional'
 layer.kernal: only for type = 'Convolutional'
 layer.stride: only for type = 'Convolutional'
 layer.activation = {'ReLU', 'tanh', 'sigmoid'} if type = 'Fully_connected',
                     'Convolutional' if type = 'Convolutional',
                    {'max', 'average'} if type = 'Pooling'
 layer.filter_size: only for type = 'Pooling'
 layer.input_dim = [m, n], n==1 for fully-connected layer
 layer.output_dim = [m, n]

Keep the original properties:
 size_of_inputs: matrix (n*1 matrix for FC network)
 size_of_outputs: n*1 matrix
 num_of_hidden_layers: integer
 scale_factor: number
 offset: number
"""


##############################################################
# output range analysis by MILP relaxation for convolutional neural network
def output_range_MILP_CNN(NN, network_input_box, output_index):

    # initialization of the input range of all the neurons by naive method
    # input range is a list 'matrix'
    input_range_all = []
    input_range_layer_i = network_input_box
    output_range_layer_i_last = network_input_box
    for i in range(NN.num_of_hidden_layers):
        # in the output layer, only take the weight and
        # bias of the 'output_index'-th neuron
        if (
            i == NN.num_of_hidden_layers - 1 and
            NN.layers[i].type == 'Fully_connected'
        ):
            weight_i = np.reshape(NN.layers[i].weight[:, output_index], (-1, 1))
            bias_i = np.array([NN.layers[i].bias[output_index]])
        else:
            weight_i = NN.layers[i].weight
            bias_i = NN.layers[i].bias

        print('-------------layer: {}---------------'.format(i))
        print(NN.layers[i].type)

        if NN.layers[i].type == 'Convolutional':
            output_range_layer_i = output_range_convolutional_layer_naive_v1(
                NN.layers[i],
                input_range_layer_i,
                NN.layers[i].kernal,
                NN.layers[i].bias,
                NN.layers[i].stride
            )
        if NN.layers[i].type == 'Activation':
            print(NN.layers[i].activation)
            output_range_layer_i = output_range_activation_layer_naive(
                NN.layers[i],
                input_range_layer_i,
                NN.layers[i].activation
            )
        if NN.layers[i].type == 'Pooling':
            output_range_layer_i = output_range_pooling_layer_naive_v1(
                NN.layers[i],
                input_range_layer_i,
                NN.layers[i].filter_size,
                NN.layers[i].activation,
                NN.layers[i].stride
            )
        if NN.layers[i].type == 'Flatten':
            output_range_layer_i = output_range_flatten_layer_naive(
                NN.layers[i],
                input_range_layer_i
            )
        if NN.layers[i].type == 'Fully_connected':
            input_range_layer_i = input_range_fc_layer_naive_v1(
                weight_i,
                bias_i,
                output_range_layer_i_last
            )
            output_range_layer_i = output_range_activation_layer_naive(
                NN.layers[i],
                input_range_layer_i,
                NN.layers[i].activation
            )

        input_range_all.append(input_range_layer_i)
        print('The dimension of input range of layer ' + str(i) + ' :')
        print(input_range_layer_i.shape)

        input_range_layer_i = output_range_layer_i
        output_range_layer_i_last = output_range_layer_i

    print('-------Naive range for each neuron is generated.----------')
    print('-------MILP based range analysis begins.----------')

    # only invoke our approach once to obtain the output range
    # with the basic refinement degree
    refinement_degree_all = []
    for k in range(NN.num_of_hidden_layers):
        refinement_degree_layer = []
        if len(NN.layers[k].input_dim) == 3:
            for s in range(NN.layers[k].input_dim[2]):
                refinement_degree_layer_channel = []
                for i in range(NN.layers[k].input_dim[0]):
                    refinement_degree_layer_row = []
                    for j in range(NN.layers[k].input_dim[1]):
                        refinement_degree_layer_row.append(0)
                    refinement_degree_layer_channel.append(refinement_degree_layer_row)
                refinement_degree_layer.append(refinement_degree_layer_channel)
            refinement_degree_all.append(refinement_degree_layer)
        if len(NN.layers[k].input_dim) == 1:
            for i in range(NN.layers[k].output_dim[0]):
                refinement_degree_layer.append(0)
            refinement_degree_all.append(refinement_degree_layer)

    N = 8
    naive_input = input_range_all[N][0]
    input_range_last_neuron, _ = neuron_input_range_cnn(
        NN,
        N,
        0,
        network_input_box,
        input_range_all,
        refinement_degree_all
    )

    print('input range naive: ' + str(naive_input))
    print('output range naive: ['+ str(activate(NN.layers[N].activation, naive_input[0])) + ',' + str(activate(NN.layers[N].activation, naive_input[1])) + ']')


    lower_bound = activate(NN.layers[N].activation, input_range_last_neuron[0])
    upper_bound = activate(NN.layers[N].activation, input_range_last_neuron[1])

    print('input range: ' + str(input_range_last_neuron))
    print('output range: ['+ str(lower_bound) + ',' + str(upper_bound) + ']')

    return [lower_bound, upper_bound]


# define large positive number M to enable Big M method
M = 10e10
# Compute the input range for a specific neuron
# and return the updated input_range_all

# When layer_index = layers,
# this function outputs the output range of the neural network
def neuron_input_range_cnn(NN, layer_index, neuron_index, network_input_box, input_range_all, refinement_degree_all):
    layers = NN.layers

    model = Model('Neuron_Range_Update')


    # variables in the input layer
    if NN.type == 'Convolutional':
        network_in = []
        for s in range(NN.layers[0].input_dim[2]):
            network_in.append(model.addVars(NN.layers[0].input_dim[0],NN.layers[0].input_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
    else:
        network_in = model.addVars(NN.layers[0].input_dim[0], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS)

    # variables in previous layers
    x_in = []
    x_out = []
    z0 = []
    z1 = []

    for k in range(layer_index):
        if NN.layers[k].type == 'Convolutional':
            x_in_layer = []
            for s in range(NN.layers[k].input_dim[2]):
                x_in_layer.append(model.addVars(NN.layers[k].input_dim[0],NN.layers[k].input_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_in.append(x_in_layer)
            x_out_layer = []
            for s in range(NN.layers[k].output_dim[2]):
                x_out_layer.append(model.addVars(NN.layers[k].output_dim[0],NN.layers[k].output_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_out.append(x_out_layer)
            z0.append([])
            z1.append([])

        if NN.layers[k].type == 'Activation':
            # define input and output variables
            x_in_layer = []
            for s in range(NN.layers[k].input_dim[2]):
                x_in_layer.append(model.addVars(NN.layers[k].input_dim[0],NN.layers[k].input_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_in.append(x_in_layer)
            x_out_layer = []
            for s in range(NN.layers[k].output_dim[2]):
                x_out_layer.append(model.addVars(NN.layers[k].output_dim[0],NN.layers[k].output_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_out.append(x_out_layer)
            # define slack binary variables
            z0_layer = []
            z1_layer = []
            for s in range(NN.layers[k].input_dim[2]):
                z0_channel = []
                z1_channel = []
                for i in range(NN.layers[k].input_dim[0]):
                    z0_row = []
                    z1_row = []
                    for j in range(NN.layers[k].input_dim[1]):
                        if refinement_degree_all[k][s][i][j] == 0:
                            z0_row.append([])
                        else:
                            z0_row.append(model.addVars(refinement_degree_all[k][s][i][j], vtype=GRB.BINARY))
                            z1_row.append(model.addVars(refinement_degree_all[k][s][i][j], vtype=GRB.BINARY))
                    z0_channel.append(z0_row)
                    z1_channel.append(z1_row)
                z0_layer.append(z0_channel)
                z1_layer.append(z1_channel)
            z0.append(z0_layer)
            z1.append(z1_layer)

        if NN.layers[k].type == 'Pooling':
            # define input and output variables
            x_in_layer = []
            for s in range(NN.layers[k].input_dim[2]):
                x_in_layer.append(model.addVars(NN.layers[k].input_dim[0],NN.layers[k].input_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_in.append(x_in_layer)
            x_out_layer = []
            for s in range(NN.layers[k].output_dim[2]):
                x_out_layer.append(model.addVars(NN.layers[k].output_dim[0],NN.layers[k].output_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_out.append(x_out_layer)

            z0.append([])
            z1.append([])

        if NN.layers[k].type == 'Flatten':
            # define input and output variables
            x_in_layer = []
            for s in range(NN.layers[k].input_dim[2]):
                x_in_layer.append(model.addVars(NN.layers[k].output_dim[0].item(),NN.layers[k].input_dim[1], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
            x_in.append(x_in_layer)
            x_out_layer = model.addVars(NN.layers[k].output_dim[0].item(), lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS)
            x_out.append(x_out_layer)

            z0.append([])
            z1.append([])

        if NN.layers[k].type == 'Fully_connected':
            # Notice that here the dimension of x_in should be the same as the one of x_out, which is not the one of the output of the previous layer
            x_in_layer = model.addVars(NN.layers[k].input_dim[0], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS)
            x_in.append(x_in_layer)
            x_out_layer = model.addVars(NN.layers[k].output_dim[0], lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS)
            x_out.append(x_out_layer)
            # define slack binary variables
            z0_layer = []
            z1_layer = []
            for i in range(NN.layers[k].output_dim[0]):
                z0_layer.append(model.addVars(refinement_degree_all[k][i], vtype=GRB.BINARY))
                z1_layer.append(model.addVars(refinement_degree_all[k][i], vtype=GRB.BINARY))
            z0.append(z0_layer)
            z1.append(z1_layer)


    # variables for the specific neuron
    x_in_neuron = model.addVar(lb=-GRB.INFINITY,ub=GRB.INFINITY, vtype=GRB.CONTINUOUS)

    # add constraints for the input layer
    if NN.type == 'Convolutional':
        for s in range(NN.layers[0].input_dim[2]):
            for i in range(NN.layers[0].input_dim[0]):
                for j in range(NN.layers[0].input_dim[1]):
                    network_in[s][i,j].setAttr(GRB.Attr.LB, network_input_box[i][j][s][0])
                    network_in[s][i,j].setAttr(GRB.Attr.UB, network_input_box[i][j][s][1])
    else:
        for i in range(NN.layers[0].input_dim[0]):
            network_in[s][i].setAttr(GRB.Attr.LB, network_input_box[i][0])
            network_in[s][i].setAttr(GRB.Attr.UB, network_input_box[i][1])


    # add constraints for the layers before the neuron
    for k in range(layer_index):

        if NN.layers[k].type == 'Convolutional':
            relaxation_convolutional_layer(model, NN.layers[k], x_in[k], x_out[k], NN.layers[k].kernal, NN.layers[k].bias, NN.layers[k].stride)
            if k == 0:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(network_in[s][i,j] == x_in[k][s][i,j])
            else:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(x_out[k-1][s][i,j] == x_in[k][s][i,j])
        if NN.layers[k].type == 'Activation':
            relaxation_activation_layer(model, NN.layers[k], x_in[k], x_out[k], z0[k], z1[k], input_range_all[k], NN.layers[k].activation, refinement_degree_all[k])
            if k == 0:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(network_in[s][i,j] == x_in[k][s][i,j])
            else:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(x_out[k-1][s][i,j] == x_in[k][s][i,j])
        if NN.layers[k].type == 'Pooling':
            relaxation_pooling_layer(model, NN.layers[k], x_in[k], x_out[k], NN.layers[k].filter_size, NN.layers[k].activation, NN.layers[k].stride)
            if k == 0:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(network_in[s][i,j] == x_in[k][s][i,j])
            else:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(x_out[k-1][s][i,j] == x_in[k][s][i,j])
        if NN.layers[k].type == 'Flatten':
            relaxation_flatten_layer(model, NN.layers[k], x_in[k], x_out[k])
            if k == 0:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(network_in[s][i,j] == x_in[k][s][i,j])
            else:
                for s in range(NN.layers[k].input_dim[2]):
                    for i in range(NN.layers[k].input_dim[0]):
                        for j in range(NN.layers[k].input_dim[1]):
                            model.addConstr(x_out[k-1][s][i,j] == x_in[k][s][i,j])
        if NN.layers[k].type == 'Fully_connected':
            relaxation_activation_layer(model, NN.layers[k], x_in[k], x_out[k], z0[k], z1[k], input_range_all[k], NN.layers[k].activation, refinement_degree_all[k])
            # add constraint for linear transformation between layers
            weight_k = NN.layers[k].weight
            bias_k = NN.layers[k].bias
            if k == 0:
                for i in range(NN.layers[k].output_dim[0]):
                    weight_k_i = np.reshape(weight_k[:, i], (-1, 1))
                    weight_k_i_dic = {}
                    for j in range(weight_k_i.shape[0]):
                        weight_k_i_dic[j] = weight_k_i[j][0]
                    model.addConstr(network_in.prod(weight_k_i_dic) + bias_k[i] == x_in[k][i])
            else:
                for i in range(NN.layers[k].output_dim[0]):
                    weight_k_i = np.reshape(weight_k[:, i], (-1, 1))
                    weight_k_i_dic = {}
                    for j in range(weight_k_i.shape[0]):
                        weight_k_i_dic[j] = weight_k_i[j][0]
                    model.addConstr(x_out[k-1].prod(weight_k_i_dic) + bias_k[i] == x_in[k][i])


    # add constraint for the last layer and the neuron
    # Notice that we only need to handle activation function layer. For other layers, update the input range of the neuron does not improve the result (which is equivalant in fact)
    print(NN.layers[layer_index].type)
    if NN.layers[layer_index].type == 'Activation' or NN.layers[layer_index].type == 'Flatten':
        model.addConstr(x_in_neuron == x_out[layer_index-1][neuron_index[2]][neuron_index[0],neuron_index[1]])
    elif NN.layers[layer_index].type == 'Fully_connected':
        weight_neuron = np.reshape(NN.layers[layer_index].weight[:, neuron_index], (-1, 1))
        bias_neuron = NN.layers[layer_index].bias[neuron_index]
        if layer_index >= 1:
            weight_neuron_dic = {}
            for j in range(weight_neuron.shape[0]):
                weight_neuron_dic[j] = weight_neuron[j][0]
            model.addConstr(x_out[layer_index-1].prod(weight_neuron_dic) + bias_neuron == x_in_neuron)
        else:
            weight_neuron_dic = {}
            for j in range(weight_neuron.shape[0]):
                weight_neuron_dic[j] = weight_neuron[j][0]
            model.addConstr(network_in.prod(weight_neuron_dic) + bias_neuron == x_in_neuron)
    else:
        print('No need to update the input range of this neuron')
        return input_range_all[layer_index][neuron_index[2]][neuron_index[0]][neuron_index[1]], input_range_all


    # objective: smallest output of [layer_index, neuron_index]
    model.setObjective(x_in_neuron, GRB.MINIMIZE)
    model.optimize()

    if model.status == GRB.OPTIMAL:
        neuron_min = model.objVal
        #print('lower bound: ' + str(l_neuron))
        #for variable in prob_min.variables():
        #    print ('Variable ' + str(variable.name()) + ' value: ' + str(variable.value))
    else:
        print('prob_min.status: ' + str(model.status))
        raise ValueError('Error: No result for lower bound!')

    # define objective: biggest output of [layer_index, neuron_index]
    model.setObjective(x_in_neuron, GRB.MAXIMIZE)
    model.optimize()

    if model.status == GRB.OPTIMAL:
        neuron_max = model.objVal
        #print('lower bound: ' + str(l_neuron))
        #for variable in prob_min.variables():
        #    print ('Variable ' + str(variable.name()) + ' value: ' + str(variable.value))
    else:
        print('prob_max.status: ' + str(model.status))
        raise ValueError('Error: No result for upper bound!')

    if NN.layers[layer_index].type == 'Activation':
        input_range_all[layer_index][neuron_index[2]][neuron_index[0]][neuron_index[1]] = [neuron_min, neuron_max]
    elif (
        NN.layers[layer_index].type == 'Fully_connected' and
        layer_index < NN.num_of_hidden_layers - 1
    ):
        input_range_all[layer_index][neuron_index] = [neuron_min, neuron_max]



    return [neuron_min, neuron_max], input_range_all


#############################################################################################
# Derive the input range of a fully-connected layer by
# Only in fully-connect layer, the input of the layer is different of the output of the previous layer
#
def input_range_fc_layer_naive_v1(weight, bias, output_range_last_layer):
    # compute the input range of each neuron by solving LPs

    input_range_layer = []



    for i in range(weight.shape[1]):
        model_in_neuron = Model()

        x_out = model_in_neuron.addVars(weight.shape[0], lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS)
        # define constraints: output range of the last layer
        for j in range(output_range_last_layer.shape[0]):
            x_out[j].setAttr(GRB.Attr.LB, output_range_last_layer[j, 0])
            x_out[j].setAttr(GRB.Attr.UB, output_range_last_layer[j, 1])

        x_in = model_in_neuron.addVar(lb=-GRB.INFINITY,ub=GRB.INFINITY)

        weight_i = np.reshape(weight[:, i], (-1, 1))
        bias_i = bias[i]

        # define constraints: linear transformation by weight and bias
        # in gurobi, no matrix api for python, we need to mannally implement the matrix operation based on gurobi tupledict
        # transform a numpy array to a dictinary
        weight_i_dic = {}
        for j in range(weight_i.shape[0]):
            weight_i_dic[j] = weight_i[j][0]

##        try:
##            lt_index = model_in_neuron.getConstrByName('lt')
##            model_in_neuron.remove(lt_index)
##            model_in_neuron.addConstr(x_out.prod(weight_i_dic) + bias_i == x_in, 'lt')
##        except gurobipy.GurobiError:
##            model_in_neuron.addConstr(x_out.prod(weight_i_dic) + bias_i == x_in, 'lt')

        model_in_neuron.addConstr(x_out.prod(weight_i_dic) + bias_i == x_in, 'lt')




        # define objective: smallest output of [layer_index, neuron_index]
        # Set objective
        model_in_neuron.setObjective(x_in, GRB.MINIMIZE)
        model_in_neuron.setParam('OutputFlag', 0)
        model_in_neuron.optimize()

        if model_in_neuron.status == GRB.OPTIMAL:
            neuron_min = model_in_neuron.objVal
            #print('lower bound: ' + str(l_neuron))
            #for variable in prob_min.variables():
            #    print ('Variable ' + str(variable.name()) + ' value: ' + str(variable.value))
        else:
            print('prob_min.status: ' + str(model_in_neuron.status))
            raise ValueError('Error: No result for lower bound!')

        # define objective: biggest output of [layer_index, neuron_index]
        model_in_neuron.setObjective(x_in, GRB.MAXIMIZE)
        model_in_neuron.setParam('OutputFlag', 0)
        model_in_neuron.optimize()

        if model_in_neuron.status == GRB.OPTIMAL:
            neuron_max = model_in_neuron.objVal
            #print('lower bound: ' + str(l_neuron))
            #for variable in prob_min.variables():
            #    print ('Variable ' + str(variable.name()) + ' value: ' + str(variable.value))
        else:
            print('prob_max.status: ' + model_in_neuron.status)
            raise ValueError('Error: No result for upper bound!')

        input_range_layer.append([neuron_min, neuron_max])
    return np.array(input_range_layer)



#############################################################################################
## Derive the output ranges of different layers

# Convolutional layer
def output_range_convolutional_layer_naive_v1(layer, input_range_layer, kernal, bias, stride):
    output_range_layer = []
    print('The size of bias is: ' + str(bias.shape))

    for i in range(layer.output_dim[0]):
        output_range_layer_row = []
        for j in range(layer.output_dim[1]):
            output_range_layer_col = []
            for k in range(layer.output_dim[2]):
                model_out_neuron = Model()
                x_in = []
                for s in range(layer.input_dim[2]):
                    x_in.append(model_out_neuron.addVars(kernal.shape[0],kernal.shape[1], lb=-GRB.INFINITY, ub=GRB.INFINITY, vtype=GRB.CONTINUOUS))
                x_out = model_out_neuron.addVar(lb=-GRB.INFINITY,ub=GRB.INFINITY)
                constraints = []
                sum_expr = 0
                for s in range(layer.input_dim[2]):
                    for p in range(kernal.shape[0]):
                        for q in range(kernal.shape[1]):
                            x_in[s][p,q].setAttr(GRB.Attr.LB, input_range_layer[
                                                                    i * stride[0] + p,
                                                                    j * stride[1] + q,
                                                                    s,
                                                                    0])
                            x_in[s][p,q].setAttr(GRB.Attr.UB, input_range_layer[
                                                                    i * stride[0] + p,
                                                                    j * stride[1] + q,
                                                                    s,
                                                                    1])
                    sum_expr = sum_expr + x_in[s].prod(dict(np.ndenumerate(kernal[:,:,s,k]))) + bias[k]
                model_out_neuron.addConstr(sum_expr == x_out)

                # define objective: smallest output
                model_out_neuron.setObjective(x_out, GRB.MINIMIZE)
                model_out_neuron.setParam('OutputFlag', 0)
                model_out_neuron.optimize()

                if model_out_neuron.status == GRB.OPTIMAL:
                    neuron_min = model_out_neuron.objVal
                    #print('lower bound: ' + str(l_neuron))
                    #for variable in prob_min.variables():
                    #    print ('Variable ' + str(variable.name()) + ' value: ' + str(variable.value))
                else:
                    print('prob_min.status: ' + str(model_out_neuron.status))
                    raise ValueError("Error: No result for lower bound for " + str([i,j,s,k]))

                # define objective: biggest output
                model_out_neuron.setObjective(x_out, GRB.MAXIMIZE)
                model_out_neuron.setParam('OutputFlag', 0)
                model_out_neuron.optimize()

                if model_out_neuron.status == GRB.OPTIMAL:
                    neuron_max = model_out_neuron.objVal
                    #print('lower bound: ' + str(l_neuron))
                    #for variable in prob_min.variables():
                    #    print ('Variable ' + str(variable.name()) + ' value: ' + str(variable.value))
                else:
                    print('prob_max.status: ' + str(model_out_neuron.status))
                    print('Error: No result for upper bound!')
                output_range_layer_col.append([neuron_min, neuron_max])
            output_range_layer_row.append(output_range_layer_col)
        output_range_layer.append(output_range_layer_row)

    return np.array(output_range_layer)



# Pooling layer
def output_range_pooling_layer_naive_v1(layer, input_range_layer, filter_size, pooling_type, stride):
    output_range_layer = []

    for i in range(layer.output_dim[0]):
        output_range_layer_row = []
        for j in range(layer.output_dim[1]):
            output_range_layer_col = []
            for s in range(layer.output_dim[2]):
##                model_out_neuron = Model()
##                x_in = model_out_neuron.addVars(filter_size[0],filter_size[1], vtype=GRB.CONTINUOUS)
##                x_out = model_out_neuron.addVar()
##
##                model_out_neuron.addConstrs((x_in[s][p,q].setAttr(GRB.Attr.LB, input_range_layer[
##                                                                i * stride[0] + p,
##                                                                j * stride[1] + q,
##                                                                s,
##                                                                0])
##                                for p in range(filter_size[0])
##                                for q in range(filter_size[1])))
##                model_out_neuron.addConstrs((x_in[s][p,q].setAttr(GRB.Attr.UB, input_range_layer[
##                                                                i * stride[0] + p,
##                                                                j * stride[1] + q,
##                                                                s,
##                                                                1])
##                                for p in range(filter_size[0])
##                                for q in range(filter_size[1])))

                if pooling_type == 'max':
                    #constraints += [cp.max(x_in) == x_out] # The max operation is convex but not affine, thus can be not be used in an equation constraint in DCP.
                    # Instead, we directly derive the constraint for max pooling
                    neuron_min = np.max(input_range_layer[
                        i * stride[0] : i * stride[0] + filter_size[0],
                        j * stride[1] : j * stride[1] + filter_size[1],
                        s,
                        0
                    ])
                    neuron_max = np.max(input_range_layer[
                        i * stride[0] : i * stride[0] + filter_size[0],
                        j * stride[1] : j * stride[1] + filter_size[1],
                        s,
                        1
                    ])
                if pooling_type == 'average':
                    # Instead, we directly derive the constraint for max pooling
                    neuron_min = np.mean(input_range_layer[
                        i * stride[0] : i * stride[0] + filter_size[0],
                        j * stride[1] : j * stride[1] + filter_size[1],
                        s,
                        0
                    ])
                    neuron_max = np.mean(input_range_layer[
                        i * stride[0] : i * stride[0] + filter_size[0],
                        j * stride[1] : j * stride[1] + filter_size[1],
                        s,
                        1
                    ])
                output_range_layer_col.append([neuron_min, neuron_max])
            output_range_layer_row.append(output_range_layer_col)
        output_range_layer.append(output_range_layer_row)

    return np.array(output_range_layer)

# flatten layer: just flatten the output
def output_range_flatten_layer_naive(layer, input_range_layer):
    output_range_layer = []
    for s in range(input_range_layer.shape[2]):
        for i in range(input_range_layer.shape[0]):
            # consider the i-th row
            for j in range(input_range_layer.shape[1]):
                # add the j-th neuron
                output_range_layer.append(input_range_layer[i,j,s,:])
    return np.array(output_range_layer)

# general activation layer
def output_range_activation_layer_naive(layer, input_range_layer, activation):

    if len(layer.input_dim) == 3:
        # for convolutional layer
        # compute the out range of each neuron by activation function
        output_range_layer = []
        for i in range(input_range_layer.shape[0]):
            output_range_layer_row = []
            for j in range(input_range_layer.shape[1]): # input_range_layer.shape[1]=1 for fully-connected layer, input_range_layer.shape[2]=2 for any activation layer
                output_range_layer_col = []
                for s in range(input_range_layer.shape[2]):
                    # compute the minimal output
                    neuron_min = activate(activation, input_range_layer[i][j][s][0])
                    # compute the maximal output
                    neuron_max = activate(activation, input_range_layer[i][j][s][1])
                    output_range_layer_col.append([neuron_min,neuron_max])
                output_range_layer_row.append(output_range_layer_col)
            output_range_layer.append(output_range_layer_row)
    else:
        # for fully connected layer
        # compute the out range of each neuron by activation function
        output_range_layer = []
        for i in range(input_range_layer.shape[0]):
            # compute the minimal output
            neuron_min = activate(activation, input_range_layer[i][0])
            # compute the maximal output
            neuron_max = activate(activation, input_range_layer[i][1])
            output_range_layer.append([neuron_min,neuron_max])

    return np.array(output_range_layer)

#############################################################################################
## Constraints of MILP relaxation for different layers
# convolutional layer
# x_in should be 3-dimensional, x_out should be 3-dimensional
def relaxation_convolutional_layer(model, layer, x_in, x_out, kernal, bias, stride):
    for i in range(layer.output_dim[0]):
        for j in range(layer.output_dim[1]):
            for k in range(layer.output_dim[2]):
                sum_expr = 0
                for s in range(layer.input_dim[2]):
                    for p in range(kernal.shape[0]):
                        for q in range(kernal.shape[1]):
                            sum_expr = sum_expr + x_in[s][i*stride[0]+p, j*stride[1]+q] * kernal[p,q,s,k]
                    sum_expr = sum_expr + bias[k]
                model.addConstr(sum_expr == x_out[k][i,j])

# pooling layer
# x_in should be 3-dimensional, x_out should be 3-dimensional
def relaxation_pooling_layer(model, layer, x_in, x_out, filter_size, pooling_type, stride):
    if pooling_type == 'max':
        for s in range(layer.input_dim[2]):
            for i in range(round(layer.input_dim[0]/filter_size[0])):
                for j in range(round(layer.input_dim[1]/filter_size[1])):
                    # big-M relaxation for max operation
                    temp_list = []
                    for p in range(filter_size[0]):
                        for q in range(filter_size[1]):
                            temp_list.append(x_in[s][i*stride[0]+p, j*stride[1]+q])
                    model.addConstr(max_(temp_list) == x_out[s][i,j])
    if pooling_type == 'average':
        for s in range(layer.input_dim[2]):
            for i in range(round(layer.input_dim[0]/filter_size[0])):
                for j in range(round(layer.input_dim[1]/filter_size[1])):
                    # big-M relaxation for max operation
                    temp_list = []
                    for p in range(filter_size[0]):
                        for q in range(filter_size[1]):
                            temp_list.append(x_in[s][i*stride[0]+p, j*stride[1]+q])
                    model.addConstr(quicksum(temp_list)/(filter_size[0]*filter_size[1]) == x_out[s][i,j])

# flatten layer
# x_in should be 3-dimensional, x_out should be 1-dimensional
def relaxation_flatten_layer(model, layer, x_in, x_out):
    k = 0
    for s in range(layer.input_dim[2]):
        for i in range(layer.input_dim[0]):
            for j in range(layer.input_dim[1]):
                model.addConstr(x_in[s][i,j] == x_out[k])
                k = k + 1


# Relu/tanh/sigmoid activation layer
# Note the difference between the activation layer following the convolutional layer and the one in fully-connected layer
def relaxation_activation_layer(model, layer, x_in, x_out, z0, z1, input_range_layer, activation, refinement_degree_layer):

    if layer.type == 'Activation':
        # if x_in is three-dimensional, which means this is a convolutional layer
        for s in range(layer.input_dim[2]):
            for i in range(layer.input_dim[0]):
                for j in range(layer.input_dim[1]):
                    low = input_range_layer[i][j][s][0]
                    upp = input_range_layer[i][j][s][1]
                    #print('lower: '+str(low))
                    #print('upper: '+str(upp))
                    #print('Activation: '+activation)
                    #print('After activating: ' + str(activate(activation,upp)))
                    if activate(activation,upp)-activate(activation,low) <= 10e-6:                   
                        temp = activate(activation,upp)
                        #print('temp: ' +str(temp))
                        model.addConstr(x_out[s][i,j] == temp)
                    elif refinement_degree_layer[s][i][j] == 0:
##                    if refinement_degree_layer[s][i][j] == 0:
                        seg_left = low
                        seg_right = upp
                        segment_relaxation_basic(model, x_in[s][i,j], x_out[s][i,j], seg_left, seg_right, activation)
                    else:
                        # Stay inside one and only one region, thus sum of slack integers should be 1
                        model.addConstr(z0[s][i][j].sum()+z1[s][i][j].sum()==1)
                        if low < 0 and upp > 0:
                            neg_seg = abs(low)/refinement_degree_layer[s][i][j]
                            for k in range(refinement_degree_layer[s][i][j]):
                                seg_left = low + neg_seg * k
                                seg_right = low + neg_seg * (k+1)
                                segment_relaxation(model, x_in[s][i,j], x_out[s][i,j], z0[s][i][j][k], seg_left, seg_right, activation, 'convex')
                            pos_seg = abs(upp)/refinement_degree_layer[s][i][j]
                            for k in range(refinement_degree_layer[s][i][j]):
                                seg_left = 0 + neg_seg * k
                                seg_right = 0 + neg_seg * (k+1)
                                segment_relaxation(model, x_in[s][i,j], x_out[s][i,j], z1[s][i][j][k], seg_left, seg_right, activation, 'concave')
                        elif upp <= 0:
                            neg_seg = (upp-low)/refinement_degree_layer[s][i][j]
                            for k in range(refinement_degree_layer[s][i][j]):
                                seg_left = low + neg_seg * k
                                seg_right = low + neg_seg * (k+1)
                                segment_relaxation(model, x_in[s][i,j], x_out[s][i,j], z0[s][i][j][k], seg_left, seg_right, activation, 'convex')
                        else:
                            pos_seg = (upp-low)/refinement_degree_layer[s][i][j]
                            for k in range(refinement_degree_layer[s][i][j]):
                                seg_left = low + neg_seg * k
                                seg_right = low + neg_seg * (k+1)
                                segment_relaxation(model, x_in[s][i,j], x_out[s][i,j], z1[s][i][j][k], seg_left, seg_right, activation, 'concave')
    else:
        # if x_in is one-dimensional, which means this is a fc layer
        for i in range(layer.output_dim[0]):
            low = input_range_layer[i][0]
            upp = input_range_layer[i][1]
            if activate(activation,upp)-activate(activation,low) <= 10e-6:
                temp = activate(activation,upp)
                #print('temp: ' +str(temp))
                model.addConstr(x_out[i] == temp)
            elif refinement_degree_layer[i] == 0:
##            if refinement_degree_layer[i] == 0:
                seg_left = low
                seg_right = upp
                segment_relaxation_basic(model, x_in[i], x_out[i], seg_left, seg_right, activation)
            else:
                # any neuron can only be within a region, thus sum of slack integers should be 1
                constraints += [z0[i].sum()+z1[i].sum()==1]
                if low < 0 and upp > 0:
                    neg_seg = abs(low)/refinement_degree_layer[i]
                    for k in range(refinement_degree_layer[i]):
                        seg_left = low + neg_seg * k
                        seg_right = low + neg_seg * (k+1)
                        segment_relaxation(model, x_in[i], x_out[i], z0[i][k], seg_left, seg_right, activation, 'convex')
                    pos_seg = abs(upp)/refinement_degree_layer[i]
                    for k in range(refinement_degree_layer[i]):
                        seg_left = 0 + pos_seg * k
                        seg_right = 0 + pos_seg * (k+1)
                        segment_relaxation(model, x_in[i], x_out[i], z1[i][k], seg_left, seg_right, activation, 'concave')
                elif upp <= 0:
                    neg_seg = (upp-low)/refinement_degree_layer[i]
                    for k in range(refinement_degree_layer[i]):
                        seg_left = low + neg_seg * k
                        seg_right = low + neg_seg * (k+1)
                        segment_relaxation(model, x_in[i], x_out[i], z0[i][k], seg_left, seg_right, activation, 'convex')
                else:
                    pos_seg = (upp-low)/refinement_degree_layer[i]
                    for k in range(refinement_degree_layer[i]):
                        seg_left = low + pos_seg * k
                        seg_right = low + pos_seg * (k+1)
                        segment_relaxation(model, x_in[i], x_out[i], z1[i][k], seg_left, seg_right, activation, 'concave')

def segment_relaxation_basic(model, x_in_neuron, x_out_neuron, seg_left, seg_right, activation):
    x_in_neuron.setAttr(GRB.Attr.LB, seg_left)
    x_in_neuron.setAttr(GRB.Attr.UB, seg_right)
    if seg_left < 0 and seg_right > 0:
        if activation == 'ReLU':
            model.addConstr(-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) <= 0)
            model.addConstr(-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) <= 0)
            model.addConstr(x_out_neuron - (M*(activate(activation,seg_left)-activate(activation,seg_right)))/(M*(seg_left-seg_right))*(x_in_neuron-seg_right) - activate(activation,seg_right) <= 0)
        else:
            model.addConstr(-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) <= 0)

            neg_out = activate_de_right(activation,seg_left)*(0-seg_left) + activate(activation,seg_left)
            model.addConstr(x_out_neuron - (activate(activation,seg_right)-neg_out)/(seg_right-0)*(x_in_neuron-0) - neg_out >= 0)

            model.addConstr(-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) >= 0)
            pos_out = activate_de_left(activation,seg_right)*(0-seg_right) + activate(activation,seg_right)
            model.addConstr(x_out_neuron - (activate(activation,seg_left)-pos_out)/(seg_left-0)*(x_in_neuron-0) - pos_out <= 0)
    elif seg_right <= 0:

        # triangle relaxation
        model.addConstr(-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) <= 0)
        model.addConstr(-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) <= 0)
        temp_x_diff = M*(seg_left-seg_right)
        temp_y_diff = M*(activate(activation,seg_left)-activate(activation,seg_right))
        #print('temp_x_diff: ' + str(temp_x_diff))
        #print('temp_y_diff: ' + str(temp_y_diff))
        model.addConstr(x_out_neuron - temp_y_diff/temp_x_diff*(x_in_neuron-seg_right) - activate(activation,seg_right) <= 0)
        # polytope relaxation
        # model.addConstr(-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_right) + activate(activation,seg_right) <= 0)
        # model.addConstr(-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) >= 0)
        
    else:
        # triangle relaxation
        model.addConstr(-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) >= 0)
        model.addConstr(-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) >= 0)
        temp_x_diff = M*(seg_left-seg_right)
        temp_y_diff = M*(activate(activation,seg_left)-activate(activation,seg_right))
        #print('temp_x_diff: ' + str(temp_x_diff))
        #print('temp_y_diff: ' + str(temp_y_diff))      
        model.addConstr(x_out_neuron - temp_y_diff/temp_x_diff*(x_in_neuron-seg_right) - activate(activation,seg_right) >= 0)

        # polytope relaxation
        #model.addConstr(-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) <= 0)
        #model.addConstr(-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_left) + activate(activation,seg_left) >= 0)

# generate constraints for a neruon over a simple segment
def segment_relaxation(model, x_in_neuron, x_out_neuron, z_seg, seg_left, seg_right, activation, conv_type):
    x_in_neuron.setAttr(GRB.Attr.LB, seg_left)
    x_in_neuron.setAttr(GRB.Attr.UB, seg_right)
    if conv_type == 'convex':
        # The triangle constraints of seg_right<=0 for ReLU, sigmoid, tanh
        model.addConstr((z_seg == 1) >> (-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) <= 0))
        model.addConstr((z_seg == 1) >> (-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) <= 0))
        model.addConstr((z_seg == 1) >> (x_out_neuron - (activate(activation,seg_left)-activate(activation,seg_right))/(seg_left-seg_right)*(x_in_neuron-seg_right) - activate(activation,seg_right) <= 0))
    if conv_type == 'concave':
        # The triangle constraints of seg_left>=0 for ReLU, sigmoid, tanh
        model.addConstr((z_seg == 1) >> (-x_out_neuron + activate_de_left(activation,seg_right)*(x_in_neuron-seg_right) + activate(activation,seg_right) >= 0))
        model.addConstr((z_seg == 1) >> (-x_out_neuron + activate_de_right(activation,seg_left)*(x_in_neuron-seg_left) + activate(activation,seg_left) >= 0))
        model.addConstr((z_seg == 1) >> (x_out_neuron - (activate(activation,seg_left)-activate(activation,seg_right))/(seg_left-seg_right)*(x_in_neuron-seg_right) - activate(activation,seg_right) >= 0))

# uniformly represent the activation function and the derivative
def activate(activation, x):
    if activation == 'ReLU':
        return relu(x)
    elif activation == 'sigmoid':
        return sigmoid(x)
    elif activation == 'tanh':
        return tanh(x)

def activate_de_left(activation, x):
    if activation == 'ReLU':
        return relu_de_left(x)
    elif activation == 'sigmoid':
        return sigmoid_de_left(x)
    elif activation == 'tanh':
        return tanh_de_left(x)

def activate_de_right(activation, x):
    if activation == 'ReLU':
        return relu_de_right(x)
    elif activation == 'sigmoid':
        return sigmoid_de_right(x)
    elif activation == 'tanh':
        return tanh_de_right(x)

# define relu activation function and its left/right derivative
def relu(x):
    if x >= 0:
        r = x
    else:
        r = 0
    return r

def relu_de_left(x):
    if x <= 0:
        de_l = 0
    else:
        de_l = 1
    return de_l

def relu_de_right(x):
    if x < 0:
        de_r = 0
    else:
        de_r = 1
    return de_r

# define tanh activation function and its left/right derivative
def tanh(x):
    t = (np.exp(x) - np.exp(-x)) / (np.exp(x) + np.exp(-x))
    return t

def tanh_de_left(x):
    de_l = 1 - (tanh(x))**2
    return de_l

def tanh_de_right(x):
    de_r = tanh_de_left(x)
    return de_r

# define sigmoid activation function and its left/right derivative
def sigmoid(x):
    # s = 1. / (1. + np.exp(-x))
    s = expit(x)
    return s

def sigmoid_de_left(x):
    de_l = sigmoid(x)*(1. - sigmoid(x))
    return de_l

def sigmoid_de_right(x):
    de_r = sigmoid_de_left(x)
    return de_r
##############################################################
def lipschitz(NN_controller, network_input_box, output_index, activation):
    weight_all_layer = NN_controller.weights
    bias_all_layer = NN_controller.bias
    offset = NN_controller.offset
    scale_factor = NN_controller.scale_factor

    activation_all_layer = NN_controller.activations

    layers = len(bias_all_layer)
    lips = 1
    input_range_layer = network_input_box
    for j in range(layers):
        if j < layers - 1:
            weight_j = weight_all_layer[j]
        else:
            weight_j = np.reshape(weight_all_layer[j][output_index], (1, -1))
        if j < layers - 1:
            bias_j = bias_all_layer[j]
        else:
            bias_j = np.reshape(bias_all_layer[j][output_index], (1, -1))
        lipschitz_j = lipschitz_layer(weight_j, bias_j, input_range_layer, activation_all_layer[j])
        lips = lips * lipschitz_j
        input_range_layer, _ = output_range_layer(weight_j, bias_j, input_range_layer, activation_all_layer[j])
    return lips* scale_factor, 0

def lipschitz_layer(weight, bias, input_range_layer, activation):
    neuron_dim = bias.shape[0]
    output_range_box, new_weight = output_range_layer(weight, bias, input_range_layer, activation)
    if activation == 'ReLU':
        return LA.norm(new_weight, 2)
    if activation == 'sigmoid':
        max_singular = 0
        for j in range(neuron_dim):
            range_j = output_range_box[j]
            if range_j[0] > 0.5:
                singular_j = range_j[0]*(1-range_j[0])
            elif range_j[1] < 0.5:
                singular_j = range_j[1]*(1-range_j[1])
            else:
                singular_j = np.array([0.25])
            if max_singular < singular_j:
                max_singular = singular_j
        return max_singular*LA.norm(weight, 2)
    if activation == 'tanh':
        max_singular = 0
        for j in range(neuron_dim):
            range_j = output_range_box[j]
            if range_j[0] > 0:
                singular_j = 1 - range_j[0]**2
            elif range_j[1] < 0:
                singular_j = 1 - range_j[1]**2
            else:
                singular_j = np.array([1])
            if max_singular < singular_j:
                max_singular = singular_j
        return max_singular*LA.norm(weight, 2)




##############################################################
def degree_comb_lists(d, m):
    # generate the degree combination list
    degree_lists = []
    for j in range(m):
        degree_lists.append(range(d[j]+1))
    all_comb_lists = list(itertools.product(*degree_lists))
    return all_comb_lists

def p2c(py_b):
    str_b = str(py_b)
    c_b = str_b.replace("**", "^")
    return c_b


# a simple test case
def test_f(x):
    return math.sin(x[0])+math.cos(x[1])
