from binaryninja import (
    BackgroundTaskThread, PluginCommand, BinaryView
)
from .engine import BoolHunterEngine
from .ui import BoolHunterDockWidget
from binaryninjaui import DockHandler

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
            if self.cancelled: break
            self.progress = f"Analyzing {f.name} ({i}/{len(funcs)})"
            
            res = self.engine.analyze_function(f)
            if res.final_score > 15: # Ignore noise
                results.append(res)
        
        self.callback(results)

def launch_plugin(bv):
    dock_handler = DockHandler.getActiveDockHandler()
    parent = dock_handler.parent()
    
    # Create the widget
    dock_widget = BoolHunterDockWidget(parent, "BoolHunter", bv)
    
    # Register with Binja UI
    dock_handler.addPinnedExternalView("BoolHunter", dock_widget)

PluginCommand.register("BoolHunter", "Find and index Boolean functions", launch_plugin)