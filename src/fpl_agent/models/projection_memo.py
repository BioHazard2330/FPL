"""A scope inside which per-player projection inputs are computed once.

One dashboard build projects the same ~700 players dozens of times (the squad
pool, the transfer scan, the template comparison, the build-team report each
ask again), and each ask recomputed the player's rates, minutes and rotation
risk from the database: a cold build spent about 60 of its 100 profiled seconds
repeating them. Inside `with projection_memo(conn):` those results are kept per
connection until the block ends, so a build pays each once.

It is opt-in on purpose. Outside a scope nothing is cached and behaviour is
exactly what it was, which is what the tests (and anything that edits the
database between two projections) rely on. Do not open a scope around code
that writes player, fixture, odds or news rows and then projects again."""
import functools
import sqlite3
import threading
from contextlib import contextmanager

_lock = threading.Lock()
_scopes: dict[int, tuple[sqlite3.Connection, dict, int]] = {}


@contextmanager
def projection_memo(conn: sqlite3.Connection):
    key = id(conn)
    with _lock:
        entry = _scopes.get(key)
        if entry is not None and entry[0] is conn:
            _scopes[key] = (conn, entry[1], entry[2] + 1)
        else:
            _scopes[key] = (conn, {}, 1)
    try:
        yield
    finally:
        with _lock:
            entry = _scopes.get(key)
            if entry is not None:
                if entry[2] <= 1:
                    del _scopes[key]
                else:
                    _scopes[key] = (entry[0], entry[1], entry[2] - 1)


def memoised_in_scope(fn):
    """Cache `fn(conn, *args, **kwargs)` while a `projection_memo(conn)` scope is
    open on that connection; call straight through otherwise."""

    @functools.wraps(fn)
    def wrapper(conn, *args, **kwargs):
        entry = _scopes.get(id(conn))
        if entry is None or entry[0] is not conn:
            return fn(conn, *args, **kwargs)
        cache = entry[1]
        key = (fn.__qualname__, args, tuple(sorted(kwargs.items())))
        try:
            return cache[key]
        except KeyError:
            pass
        value = fn(conn, *args, **kwargs)
        cache[key] = value
        return value

    return wrapper


def scoped(fn):
    """Run `fn(conn, ...)` inside a `projection_memo(conn)` scope."""

    @functools.wraps(fn)
    def wrapper(conn, *args, **kwargs):
        with projection_memo(conn):
            return fn(conn, *args, **kwargs)

    return wrapper
