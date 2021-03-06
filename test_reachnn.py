#from .NN_Tracking.code.neuralnetwork import NN
#import outputCNN as oc
import time
import keras
import os
import csv
import copy
import random

os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID";

# The GPU id to use, usually either "0" or "1";
os.environ["CUDA_VISIBLE_DEVICES"]="0";

import numpy as np
import cvxpy as cp

from network_parser import nn_controller, nn_controller_details
from numpy import pi, tanh, array, dot
from gurobipy import *
from reachnn import ReachNN
from nn_range_refiner import NNRangeRefiner

#import tensorflow as tf
def get_tests(dataset):
    csvfile = open('data/{}_test.csv'.format(dataset), 'r')
    tests = csv.reader(csvfile, delimiter=',')
    return tests


# test new approach for estimating sigmoid network's output range
eps = 0.01
NN = nn_controller_details('model_CIFAR_CNN_Medium', keras=True)
print(NN.mean)
print(NN.std)

# Normalize
mean = NN.mean
std = NN.std
input_range = []
# for mnist dataset
# tests = get_tests('mnist')
# for test in tests:
#     break
# image= np.float64(test[1:len(test)])/np.float64(255)
# data = image.reshape(28, 28, 1)
# data0 = image.reshape(1, 28, 28, 1)
# print(NN.keras_model(data0)[0][9])
# input_dim = NN.layers[0].input_dim
# # print('channel 1, row 0, column 0 of 2nd CL: ' + str(NN.keras_model_pre_softmax(data0)))
# for k in range(input_dim[2]):
#     input_range_channel = []
#     for i in range(input_dim[0]):
#         input_range_row = []
#         for j in range(input_dim[1]):
#             # input_range_row.append([data[i][j][k], data[i][j][k]])
#             input_range_row.append([max(0, data[i][j][k] - eps), min(1, data[i][j][k] + eps)])
#             # input_range_row.append(
#             #     [(max(0, data[i][j][k] - eps) - NN.mean) / NN.std, (min(1, data[i][j][k] + eps)- NN.mean) / NN.std])
#         input_range_channel.append(input_range_row)
#     input_range.append(input_range_channel)

# for cifar10 dataset
tests = get_tests('cifar10')
for test in tests:
    break
image= np.float64(test[1:len(test)])/np.float64(255)
data = image.reshape(32, 32, 3)
data0 = image.reshape(1, 32, 32, 3)
print(NN.keras_model(data0)[0][9])
# print(NN.layers[0].kernel.shape)
# print(NN.layers[0].kernel[:,:,:,3])
# print(NN.layers[0].bias[3])
input_dim = NN.layers[0].input_dim
print('channel 0, row 0, column 0 of 1nd CL: ' + str(NN.keras_model_pre_softmax(data0)))
for k in range(input_dim[2]):
    input_range_channel = []
    for i in range(input_dim[0]):
        input_range_row = []
        for j in range(input_dim[1]):
            # input_range_row.append([data[i][j][k], data[i][j][k]])
            # input_range_row.append([max(0, data[i][j][k] - eps), min(1, data[i][j][k] + eps)])
            input_range_row.append(
                [(max(0, (data[i][j][k] - eps)) - NN.mean) / NN.std, (min(1, (data[i][j][k] + eps))- NN.mean) / NN.std])
        input_range_channel.append(input_range_row)
    input_range.append(input_range_channel)

start_time = time.time()
nn_analyzer = ReachNN(NN, 'CIFAR', data0, np.array(input_range), 3, 'BASIC', global_robustness_type='L-INFINITY', perturbation_bound=0.01)
new_output_range = nn_analyzer.output_range_analysis('METRIC', 9, iteration=5, per=[0.0005, 0.2], is_test=True)
# nn_refiner = NNRangeRefiner(NN, np.array(input_range), 'ERAN', traceback=2)
# test_range = nn_refiner.update_neuron_input_range(0, 6, 9)
print("--- %s seconds ---" % (time.time() - start_time))




