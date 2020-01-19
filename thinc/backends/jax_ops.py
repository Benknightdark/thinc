from .ops import Ops
import numpy
from ..types import Array, Array2d, Array1d, ArrayT, DTypes, Array3d, Wrapper
from ..types import Padded
from typing import Sequence, Optional, List, Tuple, Callable, cast

try:  # pragma: no cover
    import jax
    import jax.ops
    import jax.random
    import jax.tree_util
    from jax.ops import index_update, index

    has_jax = True
except ImportError:  # pragma: no cover
    has_jax = False


class JaxOps(Ops):
    xp = jax.numpy if has_jax else None

    def as_contig(self, data: ArrayT, dtype: Optional[DTypes] = None) -> ArrayT:
        return data if dtype is None else data.astype(dtype)

    def to_numpy(self, data):
        if isinstance(data, numpy.ndarray):
            return data
        else:
            return jax.device_get(data)

    def seq2col(self, seq: ArrayT, nW: int) -> ArrayT:
        """Given an (M, N) sequence of vectors, return an (M, N*(nW*2+1))
        sequence. The new sequence is constructed by concatenating nW preceding
        and succeeding vectors onto each column in the sequence, to extract a
        window of features.
        """
        if nW == 1:
            return seq2col_one(seq)
        else:  # pragma: no cover
            raise ValueError("Currently only nW=1 supported.")

    def backprop_seq2col(self, dY: ArrayT, nW: int) -> Array:
        if nW == 1:
            return backprop_seq2col_one(dY)
        else:  # pragma: no cover
            raise ValueError("Currently only nW=1 supported.")

    def gemm(
        self,
        x: Array2d,
        y: Array2d,
        out: Optional[Array2d] = None,
        trans1: bool = False,
        trans2: bool = False,
    ) -> Array2d:
        if trans1:
            x = x.T
        if trans2:
            y = y.T
        return self.xp.dot(x, y)

    def affine(self, X, W, b):
        return affine(X, W, b)

    def flatten(
        self,
        X: Sequence[ArrayT],
        dtype: Optional[DTypes] = None,
        pad: int = 0,
        ndim_if_empty: int = 2,
    ) -> ArrayT:
        if X is None or len(X) == 0:
            return self.alloc((0,) * ndim_if_empty, dtype=dtype or "f")
        X = [x for x in X if x.size != 0]
        if int(pad) >= 1:
            return flatten_with_padding(X, pad)
        else:
            result = self.xp.concatenate(X)

        result = self.xp.concatenate(X)
        if dtype is not None:
            result = self.xp.asarray(result, dtype=dtype)
        return result

    def unflatten(self, X: ArrayT, lengths: Array1d, pad: int = 0) -> List[ArrayT]:
        if not len(lengths):
            return []
        elif not X.size:
            empty_shape = (0,) + tuple(X.shape[1:])
            return [self.alloc(empty_shape) for _ in lengths]
        elif pad == 0:
            return unflatten_no_padding(X, self.asarray(lengths))
        else:
            return unflatten_with_padding(X, self.asarray(lengths), pad)

    def maxout(self, X):
        return maxout(X)

    def backprop_maxout(self, dY, which, P):
        return backprop_maxout(dY, which, P)

    def mish(self, X, threshold=20.0):
        return mish(X, threshold)

    def backprop_mish(
        self,
        dY: Array2d,
        X: Array2d,
        threshold: float = 20.0,
        out: Optional[Array2d] = None,
    ):
        return backprop_mish(dY, X, threshold)

    def relu(self, X, inplace=False):
        return relu(X)

    def backprop_relu(self, dY, Y, inplace=False):
        return backprop_relu(dY, Y)

    def update_averages(
        self, ema: Array, weights: Array, t: int, max_decay: float = 0.9999
    ) -> None:
        decay = (1.0 + t) / (10.0 + t)
        if decay > max_decay:
            decay = max_decay
        return update_averages(ema, weights, decay)

    def adam(
        self,
        weights: Array1d,
        gradient: Array1d,
        mom1: Array1d,
        mom2: Array1d,
        beta1: float,
        beta2: float,
        eps: float,
        learn_rate: float,
        mod_rate: float = 1.0,
    ) -> Tuple[Array1d, Array1d, Array1d, Array1d]:
        return adam(
            weights, gradient, mom1, mom2, beta1, beta2, eps, learn_rate * mod_rate
        )

    def clip_gradient(self, gradient: Array, threshold: float) -> Array:
        xp = self.xp
        grad_norm = xp.linalg.norm(gradient)
        if grad_norm >= threshold:
            gradient = gradient * (threshold / grad_norm)
        return gradient

    def logloss(self, y_true: Array, y_pred: Array):
        return logloss

    def sum_pool(self, X: Array2d, lengths: Array1d) -> Array2d:
        return sum_pool(X, lengths)

    def mean_pool(self, X: Array2d, lengths: Array1d) -> Array2d:
        return mean_pool(X, lengths)

    def max_pool(self, X: Array2d, lengths: Array1d) -> Tuple[Array2d, Array2d]:
        return max_pool(X, lengths)

    def backprop_sum_pool(self, d_sums: Array2d, lengths: Array1d) -> Array2d:
        return backprop_sum_pool(d_sums, lengths)

    def backprop_mean_pool(self, d_means: Array2d, lengths: Array1d) -> Array2d:
        return backprop_mean_pool(d_means, lengths)

    def backprop_max_pool(
        self, d_maxes: Array2d, which: Array2d, lengths: Array1d
    ) -> Array2d:
        return backprop_max_pool(d_maxes, which, lengths)

    def list2padded(self, seqs: List[Array2d]) -> Padded:
        """Pack a sequence of 2d arrays into a Padded datatype."""
        lengths: Array1d
        batch_size_at_t: Array1d
        indices: Array1d
        if not seqs:
            empty = self.alloc_i1d(0)
            return Padded(self.alloc_f3d(0, 0, 0), empty, empty, empty)
        elif len(seqs) == 1:
            data = seqs[0].reshape((seqs[0].shape[0], 1) + seqs[0].shape[1:])
            batch_size_at_t = self.asarray([1] * data.shape[0], dtype="i")
            lengths = self.asarray([data.shape[0]], dtype="i")
            indices = self.asarray([0], dtype="i")
            return Padded(data, batch_size_at_t, lengths, indices)
        lengths_indices = [(len(seq), i) for i, seq in enumerate(seqs)]
        lengths_indices.sort(reverse=True)
        indices_ = [i for length, i in lengths_indices]
        lengths_ = [length for length, i in lengths_indices]
        nB = len(seqs)
        nS = max([len(seq) for seq in seqs])
        arr: Array3d = self.alloc_f3d(nB, nS, seqs[0].shape[1])
        for arr_i, (length, seqs_i) in enumerate(lengths_indices):
            arr = index_update(arr, index[arr_i, :length], self.asarray(seqs[seqs_i]))
        arr = self.as_contig(arr.transpose((1, 0, 2)))
        # Build a lookup table so we can find how big the batch is at point t.
        batch_size_at_t_ = numpy.zeros((nS,), dtype="i")
        batch_size_at_t_ += 1
        i = len(lengths_)
        for t in range(nS):
            if t == lengths_[i - 1]:
                i -= 1
                if i == 0:
                    break
            batch_size_at_t_[t] = i
        batch_size_at_t = self.asarray(batch_size_at_t_, dtype="i")
        lengths = self.asarray(lengths_, dtype="i")
        indices = self.asarray(indices_, dtype="i")
        return Padded(arr, batch_size_at_t, lengths, indices)

    def padded2list(self, padded: Padded) -> List[Array2d]:
        indices = padded.indices
        data = padded.data
        lengths = padded.lengths
        unpadded = [None] * len(lengths)
        data = self.as_contig(data.transpose((1, 0, 2)))
        for i in range(data.shape[0]):
            index_update(unpadded, index[indices[i]], data[i, : lengths[i]])
        return cast(List[Array2d], unpadded)

    def sigmoid(self, X: ArrayT, *, inplace: bool = False) -> ArrayT:
        return sigmoid(X)

    def dsigmoid(self, Y: ArrayT, *, inplace: bool = False) -> ArrayT:
        return Y * (1.0 - Y)

    def cosine(self, X: Array, Y: ArrayT) -> float:
        # Add a small constant to avoid 0 vectors
        X = X + 1e-8
        Y = Y + 1e-8
        normX = self.xp.linalg.norm(X, axis=1, keepdims=True)
        normY = self.xp.linalg.norm(Y, axis=1, keepdims=True)
        mul_norms = normX * normY
        cosine = (X * Y).sum(axis=1, keepdims=True) / mul_norms
        return cosine

    def cosine_abs_loss(
        self, X: Array, Y: ArrayT, *, ignore_zeros: bool = False
    ) -> float:
        cosine = self.cosine(X, Y)
        losses = self.xp.abs(cosine - 1)
        if ignore_zeros:
            # If the target was a zero vector, don't count it in the loss.
            zero_indices = self.xp.abs(Y).sum(axis=1) == 0
            losses[zero_indices] = 0
        loss = losses.sum()
        return loss

    def get_norm(self, X: Array) -> Array:
        norms = self.xp.linalg.norm(X, axis=1)
        norms[norms == 0] = 1
        return norms

    def dtanh(self, Y: ArrayT, *, inplace: bool = False) -> ArrayT:
        if inplace:
            Y **= 2
            Y *= -1.0
            Y += 1.0
            return Y
        else:
            return 1 - Y ** 2

    def softmax(self, x: Array, *, inplace: bool = False, axis: int = -1) -> Array:
        maxes = self.xp.max(x, axis=axis, keepdims=True)
        shifted = x - maxes
        new_x = self.xp.exp(shifted)
        new_x /= new_x.sum(axis=axis, keepdims=True)
        return new_x

    def softmax_sequences(
        self, Xs: Array2d, lengths: Array1d, *, inplace: bool = False, axis: int = -1
    ) -> Array2d:
        if Xs.ndim >= 3:
            err = f"Softmax currently only supports 2d. Got: {Xs.ndim}"
            raise NotImplementedError(err)
        # This loses almost no fidelity, and helps the numerical stability.
        Xs = self.xp.clip(Xs, -20.0, 20.0)
        new_x = self.xp.exp(Xs)
        summed = self.backprop_sum_pool(self.sum_pool(new_x, lengths), lengths)
        new_x /= summed
        return new_x

    def backprop_softmax(self, Y: Array, dY: Array, *, axis: int = -1) -> Array:
        dX = Y * dY
        dX -= Y * dX.sum(axis=axis, keepdims=True)
        return dX

    def backprop_softmax_sequences(
        self, dY: Array2d, Y: Array2d, lengths: Array1d
    ) -> Array2d:
        dX = Y * dY
        sum_dX = self.backprop_sum_pool(self.sum_pool(dX, lengths), lengths)
        dX -= Y * sum_dX
        return dX

    def recurrent_lstm(
        self, W: Array2d, b: Array1d, h_init: Array2d, c_init: Array2d, inputs: Array2d
    ) -> Tuple[Array2d, Array2d, Array3d]:
        return recurrent_lstm_forward(W, b, h_init, c_init, inputs)

    def recurrent_lstm_backward(self, dY, fwd_state, params):
        dCt = model.ops.alloc_f2d(dY.shape[1], dY.shape[2])
        dW, db, dX, dY, dC0 = backprop_recurrent_lstm(dY, dCt, (fwd_state, params))
        return dX, (dW, db, dY[0], dC0)

    def insert_into(self, shape, Xs):
        output = self.alloc(shape, dtype=Xs[0].dtype)
        for i, x in enumerate(Xs):
            output = index_update(output, index[i, : x.shape[0]], x)
        return output


class JaxRandom:
    """Perform randomization functions for Jax."""

    def shuffle(self, array):
        key = jax.random.PRNGKey(0)
        return jax.random.shuffle(key, array)

    def uniform(self, minval, maxval, shape):
        key = jax.random.PRNGKey(0)
        return jax.random.uniform(key, minval=0.0, maxval=1.0, shape=shape, dtype="f")

    def normal(self, scale, size):
        key = jax.random.PRNGKey(0)
        return jax.random.normal(key, shape=(size,)).astype("float32")


def jax_jit(*static_args) -> Wrapper:
    def wrapper(func: Callable) -> Callable:
        return jax.jit(func, static_argnums=static_args) if has_jax else func

    return wrapper


@jax_jit()
def seq2col_one(seq):
    # This is a test implementation that only supports nW=1
    nW = 1
    B = seq.shape[0]
    I = seq.shape[1]
    cols: Array3d = jax.numpy.zeros((B, (nW * 2 + 1), I))
    # Copy left contexts. The last words aren't the left-context for anything.
    cols = index_update(cols, index[nW:, :nW], seq[:-nW].reshape((-1, nW, I)))
    cols = index_update(cols, index[:, nW], seq)
    cols = index_update(cols, index[:-nW, nW + 1 :], seq[nW:].reshape((-1, nW, I)))
    return cols.reshape((B, I * (2 * nW + 1)))


@jax_jit()
def backprop_seq2col_one(dY):
    xp = jax.numpy
    nW = 1
    nF = nW * 2 + 1
    B = dY.shape[0]
    I = dY.shape[1] // nF
    dX = xp.zeros((B, I), dtype="f")
    dY = dY.reshape((B, nF, I))
    dX = index_update(dX, index[:-nW], dX[:-nW] + dY[nW:, :nW].reshape((-1, I)))
    dX += dY[:, nW]
    dX = index_update(dX, index[nW:], dX[nW:] + dY[:-nW, nW + 1 :].reshape((-1, I)))
    return dX


@jax_jit()
def affine(X, W, b):
    return X @ W.T + b


@jax_jit()
def relu(X):
    return X * (X > 0)


@jax_jit()
def backprop_relu(delta, signal_out):
    return delta * (signal_out > 0)


@jax_jit(1)
def flatten_with_padding(X, pad):
    xp = jax.numpy
    padded = []
    for x in X:
        padded.append(xp.zeros((pad,) + x.shape[1:], dtype=x.dtype))
        padded.append(x)
    padded.append(xp.zeros((pad,) + x.shape[1:], dtype=x.dtype))
    return xp.concatenate(padded)


def unflatten_no_padding(X, lengths):
    # Couldn't get the JIT version right here yet.
    start = 0
    unflat = []
    for length in lengths:
        unflat.append(X[start : start + length])
        start += length
    return unflat


def unflatten_with_padding(X, lengths, pad):
    # Couldn't get the JIT version right here yet.
    unflat = []
    for length in lengths:
        X = X[pad:]
        unflat.append(X[:length])
        X = X[length:]
    X = X[pad:]
    return unflat


@jax_jit()
def maxout(X):
    which = X.argmax(axis=-1)
    return X.max(axis=-1), which


@jax_jit(2)
def backprop_maxout(dY, which, P):
    dX = jax.numpy.zeros((dY.shape[0], dY.shape[1], P), dtype="float32")
    for b in range(dY.shape[0]):
        for o in range(dY.shape[1]):
            dX = index_update(dX, index[b, o, which[b, o]], dY[b, o])
    return dX


@jax_jit()
def adam(
    weights: Array1d,
    gradient: Array1d,
    mom1: Array1d,
    mom2: Array1d,
    beta1: float,
    beta2: float,
    eps: float,
    learn_rate: float,
) -> Tuple[Array, Array, Array, Array]:
    mom1 *= beta1
    mom2 *= beta2
    mom1 += gradient * (1.0 - beta1)
    mom2 += gradient * gradient * (1.0 - beta2)
    # Here we assume learn rate is calculated by the caller.
    # cdef weight_t a_t = learn_rate * sqrt(1-beta2**hp.t) / (1-beta1**hp.t);
    weights -= learn_rate * mom1 / (1.0 + eps)
    return weights, gradient, mom1, mom2


@jax_jit()
def update_averages(ema, weights, decay):
    return ema - (1 - decay) * (ema - weights)


@jax_jit()
def logloss(y_true: Array, y_pred: Array):
    log_yp = jax.numpy.log(y_pred + 1e-8)
    loss = (y_true * log_yp) + (1 - y_true) * jax.numpy.log((1 - y_pred) + 1e-8)
    return -loss


@jax_jit()
def sum_pool(X: Array2d, lengths: Array1d) -> Array2d:
    Y = jax.numpy.zeros((lengths.shape[0], X.shape[1]), dtype="f")
    start = 0
    for i, length in enumerate(lengths):
        Y = jax.ops.index_update(
            Y, jax.ops.index[i], X[start : start + length].sum(axis=0)
        )
        start += length
    return Y


@jax_jit()
def mean_pool(X: Array2d, lengths: Array1d) -> Array2d:
    Y = jax.numpy.zeros((lengths.shape[0], X.shape[1]), dtype="f")
    start = 0
    for i, length in enumerate(lengths):
        Y = jax.ops.index_update(
            Y, jax.ops.index[i], X[start : start + length].mean(axis=0)
        )
        start += length
    return Y


@jax_jit()
def max_pool(self, X: Array2d, lengths: Array1d) -> Array2d:
    Y = jax.numpy.zeros((lengths.shape[0], X.shape[1]), dtype="f")
    start = 0
    for i, length in enumerate(lengths):
        Y = jax.ops.index_update(
            Y, jax.ops.index[i], X[start : start + length].max(axis=0)
        )
        start += length
    return Y


@jax_jit()
def backprop_sum_pool(self, d_sums: Array2d, lengths: Array1d) -> Array2d:
    dX = self.alloc_f2d(lengths.sum(), d_sums.shape[1])
    start = 0
    for i, length in enumerate(lengths):
        dX[start : start + length] = d_sums[i]
        start += length
    return dX


@jax_jit()
def backprop_mean_pool(self, d_means: Array2d, lengths: Array1d) -> Array2d:
    dX = self.alloc_f2d(lengths.sum(), d_means.shape[1])
    start = 0
    for i, length in enumerate(lengths):
        dX[start : start + length] = d_means[i] / length
        start += length
    return dX


@jax_jit()
def backprop_max_pool(d_maxes: Array2d, which: Array2d, lengths: Array1d) -> Array2d:
    dX = numpy.jax.zeros((lengths.sum(), d_maxes.shape[1]))
    start = 0
    for i, length in enumerate(lengths):
        dX = index_update(dX, index[start : start + length, which[i]], d_maxes[i])
        start += length
    return dX


@jax_jit(1)
def mish(X: Array2d, threshold: float = 20.0) -> Array2d:
    Y = X * jax.numpy.tanh(jax.numpy.log(1.0 + jax.numpy.exp(X)))
    return jax.numpy.where(X >= threshold, X, Y)


@jax_jit(2)
def backprop_mish(X, dY, threshold=20.0):
    xp = jax.numpy
    exp_x = xp.exp(X)
    exp_2x = xp.exp(2 * X)
    exp_3x = xp.exp(3 * X)
    omega = (4.0 * (X + 1)) + (4 * exp_2x) + exp_3x + exp_x * (4.0 * X + 6)
    delta = 2.0 * exp_x + exp_2x + 2.0
    dX = dY * ((exp_x * omega) / (delta * delta))
    # Gradient when above threshold will ignore softplus.
    return jax.numpy.where(X >= threshold, dY, dX)


@jax_jit()
def sigmoid(X):
    return 1.0 / (1.0 + jax.numpy.exp(-X))


@jax_jit()
def dsigmoid(Y: ArrayT) -> ArrayT:
    return Y * (1.0 - Y)


@jax_jit()
def cosine(X: Array, Y: ArrayT) -> float:
    xp = jax.numpy
    # Add a small constant to avoid 0 vectors
    X = X + 1e-8
    Y = Y + 1e-8
    normX = xp.linalg.norm(X, axis=1, keepdims=True)
    normY = xp.linalg.norm(Y, axis=1, keepdims=True)
    mul_norms = normX * normY
    cosine = (X * Y).sum(axis=1, keepdims=True) / mul_norms
    return cosine


@jax_jit()
def dtanh(Y: ArrayT) -> ArrayT:
    return 1 - Y ** 2


@jax_jit(1)
def softmax(X: Array, axis: int) -> Array:
    xp = jax.numpy
    maxes = xp.max(X, axis=axis, keepdims=True)
    shifted = X - maxes
    new_x = xp.exp(shifted)
    new_x /= new_x.sum(axis=axis, keepdims=True)
    return new_x


@jax_jit(2)
def softmax_sequences(Xs: Array2d, lengths: Array1d, axis: int) -> Array2d:
    xp = jax.numpy
    # This loses almost no fidelity, and helps the numerical stability.
    Xs = xp.clip(Xs, -20.0, 20.0)
    new_x = xp.exp(Xs)
    summed = backprop_sum_pool(sum_pool(new_x, lengths), lengths)
    new_x /= summed
    return new_x


@jax_jit(2)
def backprop_softmax(Y: Array, dY: Array, axis: int) -> Array:
    dX = Y * dY
    dX -= Y * dX.sum(axis=axis, keepdims=True)
    return dX


@jax_jit(2)
def backprop_softmax_sequences(dY: Array2d, Y: Array2d, lengths: Array1d) -> Array2d:
    dX = Y * dY
    sum_dX = backprop_sum_pool(sum_pool(dX, lengths), lengths)
    dX -= Y * sum_dX
    return dX


"""
LSTM Notation (kind of involved, but made it a lot easier to write)

X: Inputs
Y: Outputs (aka hiddens)
C: Cells
G: Gates (Output of non-linearity, i.e. lstm_gates(X @ W.T)
A: Activations (X @ W.T, before non-linearity)

Imagine we have the input:
batch = [
    ["apple", "banana", "cantaloupe", "date", "elderberry"],
    ["aardvark", "bat", "capybara", "dingo", "elephant"]
]

The input variable X will have one vector per word, so X[0, 1] will be banana's
vector, X[0, 1, 0] will be a float, the first element of that vector.

We're computing an output variable Y of shape (nL, nB, nO), so that Y[0, 1] is
the output variable of banana.

A problem with variables for RNNs is keeping the timesteps straight. It's hard
to distinguish the current, previous, and next timesteps. To solve this problem,
we follow the convention that **we are at timestep 3**.

Additionally, the variables for Y and C are offset by one, as the 0th elements
have the initial hiddens and initial cells. So:

    t=3
    Xt3: The input vectors for 'dingo' and 'date', i.e. X[t]
    Yt3: The output vectors for 'dingo' and 'date', i.e. Y[t+1] (Y is offset.)
    Ct2: The cells calculated at 'c...', that are the input for 'd...'
    Ct3: The cells calculated at 'd...', that are the input for 'e...'
    At3: The activations at 'd...'
    Gt3: The gates at 'd...'
"""

@jax_jit()
def recurrent_lstm_forward(W, b, c_init, h_init, X):
    xp = jax.numpy
    nL, nB, nI = X.shape
    nO = h_init.shape[1]
    # Preallocate these so we can pass them through for loop.
    Y = xp.zeros((nL + 1, nB, nO), dtype="f")
    G = xp.zeros((nL, nB, nO * 4), dtype="f")
    C = xp.zeros((nL + 1, nB, nO), dtype="f")
    # Set initial hidden and cell states. The Y and C will be shifted 1,
    # so that we can have fewer arrays.
    Y = index_update(Y, index[0], h_init)
    C = index_update(C, index[0], c_init)
    state = ((W, b, X), (Y, C, G))
    state = jax.lax.fori_loop(0, X.shape[0], lstm_stepper_forward, state)
    (W, b, X), (Y, C, G) = state
    # Recall that Y and C are both offset by 1. Y[1] is the output for
    # X[1], while Y[0] was used as an input for Y[1]. We use
    # the S values to backprop the weights, so we need X the previous Ys.
    S = xp.concatenate((X, Y[:-1]), axis=-1)
    return Y[1:], (G, C, S)


@jax_jit()
def lstm_stepper_forward(t, state):
    (W, b, X), (Y, C, G) = state
    # Get the activations for this timestep.
    At3 = lstm_weights_forward(X[t], Y[t], W, b)
    # The offsets here are a bit unintuitive, because Y and C are 1-offset.
    Ct2 = C[t]
    Yt3, Ct3, Gt3 = lstm_gates_forward(At3, Ct2)
    Y = index_update(Y, index[t + 1], Yt3)
    C = index_update(C, index[t + 1], Ct3)
    G = index_update(G, index[t], Gt3)
    return (W, b, X), (Y, C, G)


@jax_jit()
def backprop_recurrent_lstm(dY, dCt, fwd_vars):
    (G, C, S), (W, b) = fwd_vars
    xp = jax.numpy
    nL = dY.shape[0]
    nB = dY.shape[1]
    nI = S.shape[2] - dY.shape[2]
    # Preallocate these so we can pass them through for loop.
    dX = xp.zeros((nL, nB, nI), dtype="f")
    dW = xp.zeros(W.shape, dtype="f")
    db = xp.zeros(b.shape, dtype="f")
    state = (
        (dW, db, dX),  # The gradi-outs (Write-only)
        (dY, dCt),  # The gradi-ins  (Read and write)
        (G, C, S),  # Forward state  (Read-only)
        (W, b),  # Params         (Read-only)
    )
    state = jax.lax.fori_loop(0, nL, backprop_lstm_stepper, state)
    (dW, db, dX), (dY, dCt), (G, C, S), (W, b) = state
    return dW, db, dX, dY, dCt


@jax_jit()
def backprop_lstm_stepper(i, state):
    (dW, db, dX), (dY, dCt3), (G, C, S), (W, b) = state
    t = S.shape[0] - i
    # Recall, we're at step 3, Y and C are offset by 1. See above.
    dYt3 = dY[t + 1]
    Ct3 = C[t + 1]
    St3 = S[t]
    Gt3 = G[t]
    Ct2 = C[t]
    dAt3, dCt2 = backprop_lstm_gates(dCt3, dYt3, Gt3, Ct3, Ct2)
    dXt3, dYt2, dW3, db3 = backprop_lstm_weights(dAt3, (St3, W, b))
    dX = index_update(dX, index[t], dXt3)
    dY = index_update(dY, index[t], dYt2)
    return (dW + dW3, db + db3, dX), (dY, dCt2), (G, C, S), (W, b)


@jax_jit()
def lstm_weights_forward(Xt3, Yt2, W, b):
    xp = jax.numpy
    St3 = xp.hstack((Xt3, Yt2))
    At3 = St3 @ W.T + b
    return At3


@jax_jit()
def backprop_lstm_weights(dAt3, fwd_state):
    St3, W, b = fwd_state
    xp = jax.numpy
    dW = dAt3.T @ St3
    db = dAt3.sum(axis=0)
    dSt3 = dAt3 @ W
    nO = W.shape[0] // 4
    nI = St3.shape[1] - nO
    dXt3 = dSt3[:, :nI]
    dYt2 = dSt3[:, nI:]
    return dXt3, dYt2, dW, db


@jax_jit()
def lstm_gates_forward(At3, Ct2):
    xp = jax.numpy
    # hf, hi, ho, hc: Forget, input, output, cell gates.
    At3_hf, At3_hi, At3_ho, At3_hc = xp.split(At3, 4, axis=-1)
    # Number the steps here, to refer back for backward pass.
    # 1. Activations
    hf = sigmoid(At3_hf)  # 1a
    hi = sigmoid(At3_hi)  # 1b
    ho = sigmoid(At3_ho)  # 1c
    hc = xp.tanh(At3_hc)  # 1d

    Ct3 = hf * Ct2  # 2a
    Ct3 += hi * hc  # 2b
    tanhCt3 = xp.tanh(Ct3)  # 3a
    Yt3 = tanhCt3 * ho  # 3b
    # We don't need the gradient for this, it's just for backprop calculation.
    Gt3 = xp.concatenate((hf, hi, ho, hc), axis=-1)
    return Yt3, Ct3, Gt3


@jax_jit()
def backprop_lstm_gates(
    dYt3: Array2d, dCt3: Array2d, Gt3: Array2d, Ct3: Array2d, Ct2: Array2d
) -> Tuple[Array3d, Array2d]:
    # See above for notation. Step numbering refers to forward_lstm_gates
    xp = jax.numpy
    hf, hi, ho, hc = xp.split(Gt3, 4, axis=-1)
    tanhCt3 = xp.tanh(Ct3)
    # 3b: Yt3 = tanhCt3 * ho
    d_ho = dYt3 * tanhCt3
    d_tanhCt3 = dYt3 * ho
    # 3a: tanhCt3 = tanh(Ct3)
    dCt3 += d_tanhCt3 * dtanh(tanhCt3)
    # 2b: Ct3 += hi * hc
    d_hi = dCt3 * hc
    d_hc = dCt3 * hi
    # 2a: Ct3 = hf * Ct2
    d_hf = dCt3 * Ct2
    dCt2 = dCt3 * hf
    d_At3_hc = d_hc * dtanh(hc)  # 1d
    d_At3_ho = d_ho * dsigmoid(ho)  # 1c
    d_At3_hi = d_hi * dsigmoid(hi)  # 1b
    d_At3_hf = d_hf * dsigmoid(hf)  # 1a
    dAt3 = xp.concatenate((d_At3_hf, d_At3_hi, d_At3_ho, d_At3_hc), axis=-1)
    return dAt3, dCt2


JaxOps.xp.random = JaxRandom()
JaxOps.xp.testing = numpy.testing

if has_jax:
    jax.tree_util.register_pytree_node(
        JaxOps, lambda ops: ([], None), lambda info, values: JaxOps()
    )

__all__ = ["JaxOps", "has_jax"]
