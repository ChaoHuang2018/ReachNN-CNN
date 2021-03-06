import gurobipy as gp
from gurobipy import GRB
from nn_range_refiner import NNRangeRefiner
from nn_activation import Activation

import numpy as np
import tensorflow as tf
import itertools
import math
import random
import time
import copy


class NNDistanceEvaluator(Object):

    def __init__(
        self,
        NN,
        NN2,
        network_input_box,
        initialize_approach,
        v_name2='NN2',
        traceback=None
    ):
        self.nn_refiner = NNRangeRefiner(NN, network_input_box, initialize_approach, traceback=traceback)
        self.nn_refiner2 = NNRangeRefiner(NN2, network_input_box, initialize_approach, traceback=traceback)
        self.gre_model = None
        self.v_name2 = v_name2
        self.all_variables2 = {}

    def evaluate_global_robustness(self, output_index):
        model = gp.Model('global_robustness_update')
        v_name = self.v_name
        v_name2 = self.v_name2
        layer_index = self.NN.num_of_hidden_layers - 1
        layer_index2 = self.NN2.num_of_hidden_layers - 1

        print('Evaluate the difference over the ' + str(output_index) + '-th output.')
        # declare variables for two inputs NN and NN2. For each input variables, we need construct the LP/MILP relaxation
        # seperately with the same setting
        all_variables = self.nn_refiner.declare_variables(model, v_name, -1, layer_index)
        all_variables_NN2 = self.nn_refiner2.declare_variables(model, v_name2, -1, layer_index2)

        # add input equality constraint
        self._add_input_equality_constraints(model, all_variables, all_variables_NN2, v_name, v_name2)


        # add constraints for NN
        for k in range(layer_index, -2, -1):
            if k >= 0:
                self.nn_refiner.add_innerlayer_constraint(model, all_variables, v_name, k)
                self.nn_refiner.add_interlayers_constraint(model, all_variables, v_name, k)
            if k == -1:
                self.nn_refiner.add_input_constraint(model, all_variables, v_name)
        # add constraints for NN2
        for k in range(layer_index2, -2, -1):
            if k >= 0:
                self._add_innerlayer_constraint(model, all_variables_NN2, v_name2, k)
                self._add_interlayers_constraint(model, all_variables_NN2, v_name2, k)
            if k == -1:
                self._add_input_constraint(model, all_variables_NN2, v_name2)

        x_out_neuron = all_variables[v_name + '_2'][layer_index][output_index]
        x_out_neuron2 = all_variables_NN2[v_name2 + '_2'][layer_index][output_index]

        # model.setObjective(x_out_neuron - x_out_neuron2, GRB.MINIMIZE)
        # distance_min = self._optimize_model(model, 0)
        model.setObjective(x_out_neuron - x_out_neuron2, GRB.MAXIMIZE)
        distance_max = self._optimize_model(model, 0)

        print('Finish evaluating the global robustness.')
        print('Range: {}'.format([-distance_max, distance_max]))

        return [-distance_max, distance_max]

    # for input equality specification
    def _add_input_equality_constraints(self, model, all_variables, all_variables_NN2, v_name, v_name2):
        NN = self.nn_refiner.NN
        NN2 = self.nn_refiner2.NN2
        network_in = all_variables[v_name + '_0']
        network_in_NN2 = all_variables_NN2[v_name2 + '_0']
        if len(NN.layers[0].input_dim) == 3:
            for s in range(NN.layers[0].input_dim[2]):
                for i in range(NN.layers[0].input_dim[0]):
                    for j in range(NN.layers[0].input_dim[1]):
                        model.addConstr(network_in[s][i, j] == network_in_NN2[s][i, j])
        if len(NN.layers[0].input_dim) == 1:
            for i in range(NN.layers[0].output_dim[0]):
                model.addConstr(network_in[i] == network_in_NN2[i])
