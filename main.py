import time
from typing import Callable, List

from binaryninja import BackgroundTaskThread, BinaryView, PluginCommand
from binaryninjaui import Sidebar

from .engine import BoolHunterEngine, BoolResult
from .ui import BoolHunterSidebarWidget, BoolHunterSidebarWidgetType


class HunterTask(BackgroundTaskThread):
    """Analyze BoolHunter candidates in progressive, UI-friendly batches."""

    PROGRESS_UPDATE_INTERVAL = 0.20
    RESULT_BATCH_SIZE = 32

    def __init__(
        self,
        bv: BinaryView,
        on_progress: Callable,
        on_results: Callable,
        on_complete: Callable,
    ):
        super().__init__("Running BoolHunter...", True)
        self.bv = bv
        self.on_progress = on_progress
        self.on_results = on_results
        self.on_complete = on_complete
        self.engine = BoolHunterEngine(bv)

    def _publish_progress(
        self,
        phase: str,
        scanned: int,
        total: int,
        priority_candidates: int,
        analyzed: int,
        results_found: int,
    ):
        self.progress = (
            f"{phase}: {scanned}/{total} functions, "
            f"{priority_candidates} priority candidates, {results_found} results"
        )
        self.on_progress(
            phase,
            scanned,
            total,
            priority_candidates,
            analyzed,
            results_found,
        )

    def _screen_functions(self, funcs: List) -> tuple[List, List]:
        """Split functions into cheap-heuristic priorities and a complete remainder."""
        priority_candidates = []
        remaining_functions = []
        total = len(funcs)
        last_publish = 0.0

        for index, func in enumerate(funcs, start=1):
            if self.cancelled:
                break

            if self.engine.is_fast_candidate(func):
                priority_candidates.append(func)
            else:
                remaining_functions.append(func)

            now = time.monotonic()
            if now - last_publish >= self.PROGRESS_UPDATE_INTERVAL or index == total:
                self._publish_progress(
                    "Screening",
                    index,
                    total,
                    len(priority_candidates),
                    0,
                    0,
                )
                last_publish = now

        return priority_candidates, remaining_functions

    def _analyze_functions(
        self,
        funcs: List,
        phase: str,
        total: int,
        priority_candidates: int,
        results: List[BoolResult],
        analyzed: int,
    ) -> int:
        """Run full bounded analysis and stream qualifying results in small batches."""
        pending_results = []
        last_publish = 0.0

        for func in funcs:
            if self.cancelled:
                break

            res = self.engine.analyze_function(func)
            analyzed += 1
            if res.final_score > 15:  # Ignore noise; unchanged result threshold.
                results.append(res)
                pending_results.append(res)

            now = time.monotonic()
            if (
                len(pending_results) >= self.RESULT_BATCH_SIZE
                or now - last_publish >= self.PROGRESS_UPDATE_INTERVAL
            ):
                if pending_results:
                    self.on_results(pending_results)
                    pending_results = []
                self._publish_progress(
                    phase,
                    analyzed,
                    total,
                    priority_candidates,
                    analyzed,
                    len(results),
                )
                last_publish = now

        if pending_results:
            self.on_results(pending_results)

        return analyzed

    def run(self):
        results: List[BoolResult] = []
        funcs = list(self.bv.functions)
        total = len(funcs)

        priority_candidates, remaining_functions = self._screen_functions(funcs)
        analyzed = 0

        if not self.cancelled:
            # The fast pass only changes ordering. Every function receives the
            # same full analysis in either this priority pass or the remainder.
            analyzed = self._analyze_functions(
                priority_candidates,
                "Analyzing priority candidates",
                total,
                len(priority_candidates),
                results,
                analyzed,
            )

        if not self.cancelled:
            analyzed = self._analyze_functions(
                remaining_functions,
                "Completeness pass",
                total,
                len(priority_candidates),
                results,
                analyzed,
            )

        self._publish_progress(
            "Cancelled" if self.cancelled else "Complete",
            analyzed,
            total,
            len(priority_candidates),
            analyzed,
            len(results),
        )
        self.on_complete(results, self.cancelled)


def launch_plugin(bv: BinaryView):
    """Open the BoolHunter sidebar for the active Binary Ninja UI context."""
    sidebar = Sidebar.current()
    if sidebar is None:
        return

    sidebar.activate("BoolHunter")
    sidebar.focus("BoolHunter")

    widget = sidebar.widget("BoolHunter")
    if isinstance(widget, BoolHunterSidebarWidget):
        widget.bind_to_active_view()


PluginCommand.register("BoolHunter", "Find and index Boolean functions", launch_plugin)
