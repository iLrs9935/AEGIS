"""Run-owned context. Values are detached; compound updates must be explicit."""
from collections.abc import MutableMapping
from contextlib import contextmanager
from copy import deepcopy
from functools import wraps
from threading import RLock


class ContextConflict(RuntimeError):
    pass


def _copy(value):
    # Context contains workflow data, never handles, Qt objects or callbacks.
    if type(value) in (str, int, float, bool, type(None)):
        return value
    if type(value) in (list, tuple):
        return type(value)(_copy(item) for item in value)
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise TypeError("Context dictionary keys must be strings")
        return {key: _copy(item) for key, item in value.items()}
    raise TypeError(f"Unsupported context value: {type(value).__name__}")


class ExecutionContext(MutableMapping):
    def __init__(self):
        self._lock = RLock()
        self._data = {}
        self._version = 0
        self._epoch = 0
        self._closed = False
        self._reserved = set()

    def _writable(self, keys=()):
        if self._closed:
            raise ContextConflict("Execution context is closed")
        if self._reserved.intersection(keys):
            raise ContextConflict("Concurrent stateful node update; serialize this branch")

    def __getitem__(self, key):
        with self._lock:
            return _copy(self._data[key])

    def __setitem__(self, key, value):
        self.update({key: value})

    def __delitem__(self, key):
        with self._lock:
            self._writable([key])
            del self._data[key]
            self._version += 1

    def __iter__(self):
        return iter(self.snapshot())

    def __len__(self):
        with self._lock:
            return len(self._data)

    def __contains__(self, key):
        with self._lock:
            return key in self._data

    def keys(self):
        return self.snapshot().keys()

    def values(self):
        return self.snapshot().values()

    def items(self):
        return self.snapshot().items()

    def popitem(self):
        with self._lock:
            self._writable(self._data)
            result = self._data.popitem()
            self._version += 1
            return _copy(result)

    def snapshot(self):
        with self._lock:
            return _copy(self._data)

    def get(self, key, default=None):
        with self._lock:
            return _copy(self._data[key]) if key in self._data else default

    def update(self, *args, **kwargs):
        values = _copy(dict(*args, **kwargs))
        with self._lock:
            self._writable(values)
            self._data.update(values)
            self._version += 1

    def setdefault(self, key, default=None):
        value = _copy(default)
        with self._lock:
            if key not in self._data:
                self._writable([key])
                self._data[key] = value
                self._version += 1
            return _copy(self._data[key])

    def pop(self, key, *default):
        with self._lock:
            self._writable([key])
            value = self._data.pop(key, *default)
            self._version += 1
            return _copy(value)

    def clear(self):
        with self._lock:
            self._writable()
            self._data.clear()
            self._epoch += 1
            self._version += 1

    def close(self):
        """Keep results readable, reject late writes from an obsolete run."""
        with self._lock:
            self._closed = True
            self._epoch += 1
            self._version += 1

    def mutate(self, transform):
        """Retry a PURE data transformation outside the lock; commit atomically.

        transform(snapshot) returns its result and may be called more than once.
        Never perform I/O, emit signals or change external state in transform.
        """
        while True:
            with self._lock:
                self._writable(self._data)
                version, epoch = self._version, self._epoch
                data = _copy(self._data)
            result = transform(data)
            replacement = _copy(data)
            with self._lock:
                self._writable(replacement)
                if epoch != self._epoch:
                    raise ContextConflict("Context was cleared during update")
                if version != self._version:
                    continue
                self._data = replacement
                self._version += 1
                return result

    @contextmanager
    def edit(self, *keys):
        """Reserve state keys without holding a mutex over I/O or Qt callbacks.

        Overlapping stateful operations fail closed instead of losing updates.
        Unrelated keys remain usable. Clear/close invalidate pending commits.
        """
        with self._lock:
            self._writable(keys)
            self._reserved.update(keys)
            epoch = self._epoch
            data = {key: _copy(self._data[key]) for key in keys if key in self._data}
        try:
            yield data
            replacement = _copy(data)
            if set(replacement) - set(keys):
                raise ContextConflict("State edit wrote an unreserved key")
            with self._lock:
                if self._closed or epoch != self._epoch:
                    raise ContextConflict("Context expired during stateful operation")
                for key in keys:
                    if key in replacement:
                        self._data[key] = replacement[key]
                    else:
                        self._data.pop(key, None)
                self._version += 1
        finally:
            with self._lock:
                self._reserved.difference_update(keys)


def snapshot(context):
    return context.snapshot() if isinstance(context, ExecutionContext) else deepcopy(context)


def mutate(context, transform):
    # Plain dictionaries are retained for standalone legacy node callers only.
    return context.mutate(transform) if isinstance(context, ExecutionContext) else transform(context)


def stateful(*keys):
    """Adapt legacy nested-dictionary state to a detached reserved edit."""
    def decorate(func):
        @wraps(func)
        def wrapped(config, inputs):
            context = inputs.get("__global_context__")
            if not isinstance(context, ExecutionContext):
                return func(config, inputs)
            with context.edit(*keys) as data:
                return func(config, {**inputs, "__global_context__": data})
        return wrapped
    return decorate
