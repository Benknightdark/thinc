from .base import Model
from ..neural import util


def forward(model, X, is_train):
    Ys, callbacks = zip(*[lyr(X, is_train=is_train) for lyr in model._layers])
    widths = [Y.shape[1] for Y in Ys]
    output = model.ops.xp.hstack(Ys)

    def finish_update_concatenate(d_output):
        layer_grad = None
        start = 0
        for bwd, width in zip(callbacks, widths):
            d = bwd(d_output[:, start : start + width])
            if hasattr(X, "shape"):
                if layer_grad is None:
                    layer_grad = d
                else:
                    layer_grad += d
            start += width
        return layer_grad

    return output, finish_update_concatenate


def init(model, X=None, Y=None):
    if X is not None:
        X_width = util.get_width(X)
        model.set_dim("nI", X_width)
        for layer in model._layers:
            layer.set_dim("nI", X_width)
    for layer in model._layers:
        layer.initialize(X=X)
    model.set_dim("nO", sum(layer.get_dim("nO") for layer in model._layers))


def make_Concatenate(layers):
    if layers and layers[0].name == "concatenate":
        layers[0]._layers.extend(layers[1:])
        return layers[0]
    return Model(
        "concatenate",
        forward,
        init=init,
        dims={"nO": None, "nI": None},
        params={},
        layers=[],
        attrs={},
    )