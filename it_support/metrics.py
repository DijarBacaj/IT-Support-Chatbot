"""Content-free process-local aggregates; no identity or model labels."""

import threading
import time
from collections import Counter
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

_lock = threading.Lock()
_totals: Counter[str] = Counter()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def record(provider: str, elapsed: float, failed: bool) -> None:
    if provider not in {"openai", "ollama"}:
        return
    with _lock:
        _totals[f"{provider}.requests"] += 1
        _totals[f"{provider}.errors"] += int(failed)
        _totals[f"{provider}.seconds"] += max(0, elapsed)


def snapshot() -> dict[str, int | float]:
    with _lock:
        return dict(_totals)


def measured(provider: str) -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorate(function: Callable[_P, _R]) -> Callable[_P, _R]:
        @wraps(function)
        def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            started = time.perf_counter()
            failed = True
            try:
                result = function(*args, **kwargs)
                failed = False
                return result
            finally:
                record(provider, time.perf_counter() - started, failed)

        return wrapped

    return decorate


def usage(provider: str, input_tokens: object, output_tokens: object) -> None:
    if provider not in {"openai", "ollama"}:
        return
    with _lock:
        for label, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens)):
            if type(value) is int and value >= 0:
                _totals[f"{provider}.{label}"] += value
                _totals[f"{provider}.{label}_observations"] += 1
