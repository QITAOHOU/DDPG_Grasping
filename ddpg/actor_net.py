# -*- coding: utf-8 -*-
"""
    -- This module is for actor network of DDPG
    -- From state -> directly output the action
"""

import os
import sys
import time
import random
import numpy as np
import tensorflow as tf
from functools import reduce

from .base import BaseModel
from .ops import linear, conv2d

class ActorNet(BaseModel):
    def __init__(self, config):
        super(ActorNet, self).__init__(config)
        
        self.g=tf.Graph()

        with self.g.as_default():
            self.sess = tf.InteractiveSession()
            self._build_actor()

    """
        ############ Build The Actor Network ############
    """
    def _build_actor(self):
        """
            Build the Actor network
        """
        print(' [*] Building Actor Network')

        initializer = tf.truncated_normal_initializer(0, 0.02)
        activation_fn = tf.nn.relu
        linear_activation_fn = tf.nn.tanh

        with tf.variable_scope('step'):
            self.step_op = tf.Variable(0, trainable=False, name='step')
            self.step_input = tf.placeholder(tf.int32, None, name='step_input')
            self.step_assign_op = self.step_op.assign(self.step_input)
        
        # Prediction Actor Network
        with tf.variable_scope('prediction'):
            if self.cnn_format == 'NHWC':
                self.s_t = tf.placeholder(tf.float32,
                    [None, self.screen_height , self.screen_width, self.inChannel*self.history_length], name='s_t')
            else:
                self.s_t = tf.placeholder(tf.float32,
                    [None, self.inChannel*self.history_length, self.screen_height, self.screen_width], name='s_t')

            # s_t = None*128*128*16(RGBD*4 previous frames)
            # downsample_1
            self.w = {}
            self.l1, self.w['l1_w'], self.w['l1_b'] = conv2d(self.s_t,
                64, [6, 6], [3, 3], initializer, activation_fn, self.cnn_format, name='_l1')
            # l1 = None*41*41*64
            self.l2, self.w['l2_w'], self.w['l2_b'] = conv2d(self.l1,
                64, [4, 4], [2, 2], initializer, activation_fn, self.cnn_format, name='_l2')
            # l2 = None*19*19*64
            self.l3, self.w['l3_w'], self.w['l3_b'] = conv2d(self.l2,
                64, [3, 3], [1, 1], initializer, activation_fn, self.cnn_format, name='_l3')
            # l3 = None*17*17*64

            shape = self.l3.get_shape().as_list()
            # 将输出沿着batch size那一层展开，为了后面可以接到全连接层里
            # dim of l3_flat = batch_size * (H*W*C)
            self.l3_flat = tf.reshape(self.l3, [-1, reduce(lambda x, y: x * y, shape[1:])])

            # Dense Connection
            self.l4, self.w['l4_w'], self.w['l4_b'] = linear(self.l3_flat, 512, activation_fn=linear_activation_fn, name='_l4')

            # Output
            self.l5, self.w['l5_w'], self.w['l5_b'] = linear(self.l4, 256, activation_fn=linear_activation_fn, name='_l5')
            
            # Action value for Current State [shape = batchsize*action_num]
            self.action, self.w['action_w'], self.w['action_b'] = linear(self.l5, self.action_num, activation_fn=None, name='action')
        print(' [*] Build Actor-Online Scope')

        # target network
        # The structure is the same with eval network
        with tf.variable_scope('target'):
            if self.cnn_format == 'NHWC':
                self.target_s_t = tf.placeholder(tf.float32,
                    [None, self.screen_height , self.screen_width, self.inChannel*self.history_length], name='target_s_t')
            else:
                self.target_s_t = tf.placeholder(tf.float32,
                    [None, self.inChannel*self.history_length, self.screen_height, self.screen_width], name='target_s_t')

            # s_t = None*128*128*16(RGBD*4 previous frames)
            # downsample_1
            self.target_w = {}
            self.target_l1, self.target_w['l1_w'], self.target_w['l1_b'] = conv2d(self.target_s_t,
                64, [6, 6], [3, 3], initializer, activation_fn, self.cnn_format, name='target_l1')
            # l1 = None*41*41*64
            self.target_l2, self.target_w['l2_w'], self.target_w['l2_b'] = conv2d(self.target_l1,
                64, [4, 4], [2, 2], initializer, activation_fn, self.cnn_format, name='target_l2')
            # l2 = None*19*19*64
            self.target_l3, self.target_w['l3_w'], self.target_w['l3_b'] = conv2d(self.target_l2,
                64, [3, 3], [1, 1], initializer, activation_fn, self.cnn_format, name='target_l3')
            # l3 = None*17*17*64

            shape = self.target_l3.get_shape().as_list()
            # 将输出沿着batch size那一层展开，为了后面可以接到全连接层里
            # dim of l3_flat = batch_size * (H*W*C)
            self.target_l3_flat = tf.reshape(self.target_l3, [-1, reduce(lambda x, y: x * y, shape[1:])])

            # Dense Connection
            self.target_l4, self.target_w['l4_w'], self.target_w['l4_b'] = linear(self.target_l3_flat, 512, activation_fn=linear_activation_fn, name='target_l4')

            # Output
            self.target_l5, self.target_w['l5_w'], self.target_w['l5_b'] = \
                linear(self.target_l4, 256, activation_fn=linear_activation_fn, name='target_l5')
            
            # Action value for Current State [shape = batchsize*action_num]
            self.target_action, self.target_w['action_w'], self.target_w['action_b'] = linear(self.target_l5, self.action_num, activation_fn=None, name='target_q')
        print(' [*] Build Actor-Target Scope')

        # Used to Set target network params from estimation network (let the t_w_input = w, then assign target_w with t_w_input)
        with tf.variable_scope('pred_to_target'):
            self.t_w_input = {}
            self.t_w_assign_op = {}

            for name in self.w.keys():
                self.t_w_input[name] = tf.placeholder(tf.float32, self.target_w[name].get_shape().as_list(), name=name)
                self.t_w_assign_op[name] = self.target_w[name].assign(self.t_w_input[name])
        print(' [*] Build Actor Weights Transform Scope')

        # optimizer
        with tf.variable_scope('optimizer'):
            self.q_gradients_in = tf.placeholder(tf.float32, [None, self.action_num], name = 'q_gradients')
            self.actor_parameters_gradients = tf.gradients(self.action, self.w, -self.q_gradients_in) # -self.q_gradients_in is initial value of actor_gradients
            self.learning_rate_step = tf.placeholder(tf.int64, None, name='learning_rate_step')
            self.learning_rate_op = tf.maximum(self.learning_rate_minimum,
                tf.train.exponential_decay(
                    self.learning_rate,
                    self.learning_rate_step,
                    self.learning_rate_decay_step,
                    self.learning_rate_decay,
                    staircase=True))

            self.optim = tf.train.RMSPropOptimizer(
                self.learning_rate_op, momentum=0.9, epsilon=0.01).apply_gradients(zip(self.actor_parameters_gradients, self.w))
        print(' [*] Build Optimize Scope')

        # display all the params in the tfboard by summary
        with tf.variable_scope('summary'):
            # save every Mini_batch GD
            scalar_summary_tags = ['average.reward', 'average.loss', 'average.q', \
                'episode.max reward', 'episode.min reward', 'episode.avg reward', 'episode.num of game', 'training.learning_rate']

            self.summary_placeholders = {}
            self.summary_ops = {}

            for tag in scalar_summary_tags:
                self.summary_placeholders[tag] = tf.placeholder(tf.float32, None, name=tag.replace(' ', '_'))
                self.summary_ops[tag]  = tf.summary.scalar("%s/%s" % (self.env_name, tag), self.summary_placeholders[tag])

            histogram_summary_tags = ['episode.rewards', 'episode.actions']

            for tag in histogram_summary_tags:
                self.summary_placeholders[tag] = tf.placeholder(tf.float32, None, name=tag.replace(' ', '_'))
                self.summary_ops[tag]  = tf.summary.histogram(tag, self.summary_placeholders[tag])

            self.writer = tf.summary.FileWriter('./ddpg/actor_logs', self.sess.graph)
        print(' [*] Build Actor Summary Scope')

        tf.global_variables_initializer().run()
        print(' [*] Initial All Actor Variables')
        self._saver = tf.train.Saver(list(self.w.values()) + [self.step_op], max_to_keep = 10, keep_checkpoint_every_n_hours=2)

        self.load_model(is_critic = False)
        self.update_target_actor_network(is_initial = True)

    def update_target_actor_network(self, is_initial = False):
        """
            Assign estimation network weights to target network. (not simultaneous)
        """
        if is_initial:
            for name in self.w.keys():
                self.t_w_assign_op[name].eval({self.t_w_input[name]: self.w[name].eval()})
        else:
            for name in self.w.keys():
                self.t_w_assign_op[name].eval({self.t_w_input[name]: self.tau*self.w[name].eval()+(1-self.tau)*self.target_w[name].eval()}) 
        print(' [*] Assign Weights from Prediction to Target')

    """
        ############ Train and Evaluation ############
    """
    def train_actor(self, state_batch, gradients_q_batch):
        self.sess.run(self.optim, feed_dict={self.s_t: state_batch, self.q_gradients_in: gradients_q_batch})
    
    def evaluate_actor(self, state_batch):
        return self.sess.run(self.action, feed_dict={self.s_t:state_batch})
    
    def evaluate_target_actor(self, target_state_batch):
        return self.sess.run(self.target_action, feed_dict={self.target_s_t:target_state_batch})

    def step_cur(self):
        return self.sess.run(self.step_op)