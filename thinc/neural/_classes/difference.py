from __future__ import division
import numpy as np
from thinc.api import layerize
from thinc.neural import Model


def inverse(total):
    inverse = 1. / (1+total)
    def backward(d_inverse):
        result = d_inverse * (-1 / (total+1)**2)
        return result
    return inverse, backward


def Siamese(layer, similarity):
    def begin_update(inputs, drop=0.):
        input1, input2 = zip(*inputs)
        vec1, bp_vec1 = layer.begin_update(input1, drop=drop)
        vec2, bp_vec2 = layer.begin_update(input2, drop=drop)
        output, bp_output = similarity.begin_update(zip(vec1, vec2), drop=drop)
        def finish_update(d_output, sgd=None):
            d_vec1, d_vec2 = zip(*bp_output(d_output, sgd))
            d_input1 = bp_vec1(d_vec1, sgd)
            d_input2 = bp_vec2(d_vec2, sgd)
            return (d_input1, d_input2)
        return output, finish_update
    model = layerize(begin_update)

    model._layers.append(layer)
    model._layers.append(similarity)
    def on_data(self, X, y):
        input1, input2 = zip(*X)
        for hook in layer.on_data_hooks:
            hook(layer, input1, y)
    model.on_data_hooks.append(on_data)
    return model


def WordMoversSimilarity(ops):
    def forward(input_pairs, drop=0.):
        bp_sims = []
        sims = []
        for mat1, mat2 in input_pairs:
            sim, bp_sim = word_movers_similarity(mat1, mat2)
            sims.append(sim)
            bp_sims.append(bp_sim)

        def backward(d_sim, sgd=None):
            d_input_pairs = []
            for bp_sim in bp_sims:
                d_mat1, d_mat2 = bp_sim(d_sim, sgd)
                d_input_pairs.append((d_mat1, d_mat2))
            return d_input_pairs
        return ops.asarray(sims), backward
    model = layerize(forward)
    return model


def word_movers_similarity(mat1, mat2):
    N1 = mat1.shape[0]
    N2 = mat2.shape[0]
    similarities = np.tensordot(mat1, mat2, axes=[[1], [1]])
    flows1 = similarities.argmax(axis=1)
    flows2 = similarities.argmax(axis=0)
    def backward(d_sim, sgd=None):
        d_sim /= (N1+N2)
        d_mat1 = np.asarray(d_sim * mat2[flows1], dtype='f')
        d_mat2 = np.asarray(d_sim * mat1[flows2], dtype='f')
        #for i in range(N1):
        #    d_mat1[i] = d_sim * mat2[flows1[i]]
        #for i in range(N2):
        #    d_mat2[i] = d_sim * mat1[flows2[i]]
        return d_mat1, d_mat2
    sim = (similarities.max(axis=0).sum() + similarities.max(axis=1).sum()) / (N1+N2)
    return sim, backward


# From chen (2013)
def CauchySimilarity(ops, length):
    weights = ops.allocate((1, length))
    weights += 1.
    Model.id += 1
    id_ = Model.id
    def begin_update(vec1_vec2, drop=0.):
        vec1, vec2 = vec1_vec2
        diff = vec1-vec2
        square_diff = diff ** 2
        total = ops.batch_dot(weights, square_diff)
        sim, bp_sim = inverse(total)
        def finish_update(d_sim, sgd=None):
            d_total = ops.asarray(bp_sim(d_sim), dtype='float32')
            d_total = d_total.reshape(total.shape)
            d_weights = d_total * square_diff
            d_square_diff = weights * d_total
            d_diff = 2 * d_square_diff * diff
            d_vec1 = d_diff
            d_vec2 = -d_diff
            sgd(weights.ravel(), d_weights.ravel(), key=id_)
            assert len(d_vec1.shape) == 2
            assert len(d_vec2.shape) == 2
            return (d_vec1, d_vec2)
        return sim, finish_update
    return layerize(begin_update)
