"""Manual ordinary-hunt timing helper; run inside Binary Ninja's Python host."""

import statistics
import time
from typing import List, Tuple

from engine import BoolHunterEngine


def benchmark_binary_view(bv, repeats: int = 5) -> Tuple[int, List[float], float]:
    """Return function count, every complete-pass time, and their median."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")

    functions = list(bv.functions)
    elapsed_seconds = []
    for _ in range(repeats):
        engine = BoolHunterEngine(bv)
        started = time.perf_counter()
        for function in functions:
            engine.analyze_function(function)
        elapsed_seconds.append(time.perf_counter() - started)

    return len(functions), elapsed_seconds, statistics.median(elapsed_seconds)
