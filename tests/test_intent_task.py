import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from ai import AIAnalystError, AIProviderConfig, IntentPlan
from tests.support.binaryninja_stub import install_binaryninja_stub


ROOT = Path(__file__).resolve().parents[1]
install_binaryninja_stub()
from engine import TargetedScanResult


class FakeBackgroundTaskThread:
    def __init__(self, label, can_cancel):
        self.label = label
        self.can_cancel = can_cancel
        self.cancelled = False
        self.finished = False
        self.progress = ""

    def cancel(self):
        self.cancelled = True

    def finish(self):
        self.finished = True


class FakePluginCommand:
    @staticmethod
    def register(*args):
        pass


class FakeEngine:
    def __init__(self, scan_result=None):
        self.scan_result = scan_result or TargetedScanResult([], 3, 2, 0, False)
        self.calls = []

    def analyze_targeted(self, terms, is_cancelled, on_progress):
        self.calls.append(tuple(terms))
        on_progress(1, 3, 1)
        return self.scan_result


def load_main_module():
    install_binaryninja_stub()
    binaryninja = sys.modules["binaryninja"]
    binaryninja.BackgroundTaskThread = FakeBackgroundTaskThread
    binaryninja.PluginCommand = FakePluginCommand
    binaryninja.BinaryView = type("BinaryView", (), {})
    ui_module = types.ModuleType("binaryninjaui")
    ui_module.Sidebar = type("Sidebar", (), {})
    sys.modules["binaryninjaui"] = ui_module

    package = types.ModuleType("boolhunter_test")
    package.__path__ = [str(ROOT)]
    sys.modules["boolhunter_test"] = package
    sys.modules["boolhunter_test.ai"] = sys.modules["ai"]
    engine_module = types.ModuleType("boolhunter_test.engine")
    engine_module.BoolHunterEngine = FakeEngine
    engine_module.BoolResult = type("BoolResult", (), {})
    engine_module.TargetedScanResult = TargetedScanResult
    sys.modules["boolhunter_test.engine"] = engine_module
    ui_stub = types.ModuleType("boolhunter_test.ui")
    ui_stub.BoolHunterSidebarWidget = type("BoolHunterSidebarWidget", (), {})
    ui_stub.BoolHunterSidebarWidgetType = type("BoolHunterSidebarWidgetType", (), {})
    sys.modules["boolhunter_test.ui"] = ui_stub

    name = "boolhunter_test.main"
    spec = importlib.util.spec_from_file_location(name, ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MAIN = load_main_module()


class FakeProvider:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def analyze(self, messages):
        self.messages = messages
        return self.response


class TestAIChatTask(unittest.TestCase):
    def setUp(self):
        self.config = AIProviderConfig("https://provider.example/v1", "secret", "test-model")
        self.targeted_response = json.dumps({
            "action": "targeted_scan",
            "topic": "purchase",
            "terms": ["purchase", "receipt"],
            "reply": "I will search purchase-related Boolean candidates.",
        })

    def run_task(self, response, engine=None, cancelled=False):
        provider = FakeProvider(response)
        engine = engine or FakeEngine()
        events = {"progress": [], "complete": []}
        task = MAIN.AIChatTask(
            engine,
            "double down on purchase booleans",
            [],
            self.config,
            lambda *args: events["progress"].append(args),
            lambda *args: events["complete"].append(args),
            client_factory=lambda config: provider,
        )
        task.cancelled = cancelled
        task.run()
        return task, provider, engine, events

    def test_chat_task_targeted_plan_scans_once(self):
        task, provider, engine, events = self.run_task(self.targeted_response)
        result, error, cancelled = events["complete"][0]
        self.assertIsInstance(result.plan, IntentPlan)
        self.assertEqual(engine.calls, [("purchase", "receipt")])
        self.assertIsNone(error)
        self.assertFalse(cancelled)
        self.assertTrue(task.finished)
        self.assertEqual(len(provider.messages), 2)

    def test_chat_task_clarify_does_not_scan(self):
        response = json.dumps({
            "action": "clarify", "topic": "", "terms": [],
            "reply": "Which purchase behavior should I focus on?",
        })
        task, _, engine, events = self.run_task(response)
        result, error, cancelled = events["complete"][0]
        self.assertIsNone(result.scan)
        self.assertEqual(engine.calls, [])
        self.assertIsNone(error)
        self.assertFalse(cancelled)
        self.assertTrue(task.finished)

    def test_malformed_plan_does_not_scan(self):
        task, _, engine, events = self.run_task('{"action":"rename"}')
        result, error, cancelled = events["complete"][0]
        self.assertIsNone(result)
        self.assertIsNotNone(error)
        self.assertEqual(engine.calls, [])
        self.assertFalse(cancelled)
        self.assertTrue(task.finished)

    def test_cancelled_scan_returns_partial_status(self):
        partial = TargetedScanResult([], 1, 1, 0, True)
        engine = FakeEngine(partial)
        task, _, engine, events = self.run_task(self.targeted_response, engine)
        result, error, cancelled = events["complete"][0]
        self.assertTrue(result.scan.cancelled)
        self.assertTrue(cancelled)
        self.assertIsNone(error)
        self.assertEqual(len(engine.calls), 1)
        self.assertTrue(task.finished)

    def test_cancelled_provider_failure_reports_cancellation(self):
        task = None

        class ProviderThatFailsAfterCancel:
            def analyze(self, messages):
                task.cancelled = True
                raise AIAnalystError("request timed out")

        events = []
        task = MAIN.AIChatTask(
            FakeEngine(),
            "double down on purchase booleans",
            [],
            self.config,
            lambda *args: None,
            lambda *args: events.append(args),
            client_factory=lambda config: ProviderThatFailsAfterCancel(),
        )
        task.run()
        result, error, cancelled = events[0]
        self.assertIsNone(result)
        self.assertIsNone(error)
        self.assertTrue(cancelled)
        self.assertTrue(task.finished)


if __name__ == "__main__":
    unittest.main()
