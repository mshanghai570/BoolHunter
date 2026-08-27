from binaryninja import BackgroundTaskThread, BinaryView, PluginCommand
from binaryninjaui import Sidebar

from .engine import BoolHunterEngine
from .ui import BoolHunterSidebarWidgetType


class HunterTask(BackgroundTaskThread):
    def __init__(self, bv: BinaryView, callback):
        super().__init__("Running BoolHunter...", True)
        self.bv = bv
        self.callback = callback
        self.engine = BoolHunterEngine(bv)

    def run(self):
        results = []
        funcs = self.bv.functions
        for i, f in enumerate(funcs):
            if self.cancelled:
                break
            self.progress = f"Analyzing {f.name} ({i}/{len(funcs)})"

            res = self.engine.analyze_function(f)
            if res.final_score > 15:  # Ignore noise
                results.append(res)

        self.callback(results)


def launch_plugin(bv: BinaryView):
    """Open the BoolHunter sidebar for the active Binary Ninja UI context."""
    sidebar = Sidebar.current()
    if sidebar is None:
        return

    sidebar.activate("BoolHunter")
    sidebar.focus("BoolHunter")


PluginCommand.register("BoolHunter", "Find and index Boolean functions", launch_plugin)
