from numpy import prod


class Memory(object):
    def __init__(self, ops, size=128):
        if size < 0:
            raise ValueError("TODO error re negative size %d" % size)
        self.ops = ops
        self._mem = self.ops.allocate((2, size))
        self._offsets = {}
        self._sizes = {}
        self._i = 0

    @property
    def weights(self):
        return self._mem[0, : self._i]

    @property
    def gradient(self):
        return self._mem[1, : self._i]

    def __contains__(self, name):
        return name in self._offsets

    def __getitem__(self, name):
        offset, col, shape = self._offsets[name]
        size = self._sizes[name]
        return self._mem[col, offset : offset + size].reshape(shape)

    def get(self, name, default=None):
        return self[name] if name in self._offsets else default

    def set(self, value):
        self._mem[0, : self._i] = value

    def add(self, name, shape):
        assert name not in self._offsets, "TODO error"
        self._offsets[name] = (self._i, 0, shape)
        size = prod(shape)
        self._sizes[name] = size
        blob = self._get_blob(size)
        return blob[0].reshape(shape)

    def add_gradient(self, grad_name, param_name):
        assert grad_name not in self._offsets, "TODO error"
        offset, _, shape = self._offsets[param_name]
        size = self._sizes[param_name]
        self._offsets[grad_name] = (offset, 1, shape)
        self._sizes[grad_name] = size
        return self._mem[1, offset : offset + size].reshape(shape)

    def _get_blob(self, nr_req):
        nr_avail = self._mem.shape[1] - (self._i + 1)
        if nr_avail < nr_req:
            self._realloc(max(self._mem.shape[1], nr_req) * 2)
        blob = self._mem[:, self._i : self._i + nr_req]
        self._i += nr_req
        return blob

    def _realloc(self, new_size):
        new_mem = self.ops.allocate((self._mem.shape[0], new_size))
        new_mem[:, : self._i + 1] = self._mem[:, : self._i + 1]
        self._mem = new_mem
