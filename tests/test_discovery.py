import unittest
from types import SimpleNamespace

from tests.support.binaryninja_stub import HighLevelILOperation as Op, install_binaryninja_stub

install_binaryninja_stub()

from engine import BoolHunterEngine


class FakeFunction:
    def __init__(self, start, name="worker", instructions=None, callees=None, raw=None):
        self.start = start
        self.name = name
        self.return_type = "int"
        self.total_bytes = len(raw or b"\x90")
        self.raw = raw or b"\x90"
        self.too_large = False
        self.analysis_skipped = False
        self.callees = callees or []
        self.hlil = FakeHLIL(instructions) if instructions is not None else None
        self.hlil_if_available = self.hlil


class FakeHLIL:
    def __init__(self, instructions):
        self.instructions = instructions

    def __iter__(self):
        return iter([self.instructions])


class FakeBinaryView:
    def __init__(self, functions, strings=None, string_refs=None):
        self.functions = functions
        self.strings = strings or []
        self.string_refs = string_refs or {}

    def read(self, address, length):
        for function in self.functions:
            if function.start == address:
                return function.raw[:length]
        return b""

    def get_strings(self):
        return self.strings

    def get_code_refs(self, address, max_items=None):
        return self.string_refs.get(address, [])


class TestDiscovery(unittest.TestCase):
    def make_engine(self, functions, strings=None, string_refs=None):
        return BoolHunterEngine(FakeBinaryView(functions, strings, string_refs))

    @staticmethod
    def comparison_return():
        expr = SimpleNamespace(operation=Op.HLIL_CMP_E)
        return SimpleNamespace(operation=Op.HLIL_RET, src=[expr])

    @staticmethod
    def mask_return(mask):
        expr = SimpleNamespace(
            operation=Op.HLIL_AND,
            left=SimpleNamespace(operation=Op.HLIL_VAR),
            right=SimpleNamespace(operation=Op.HLIL_CONST, constant=mask),
        )
        return SimpleNamespace(operation=Op.HLIL_RET, src=[expr])

    def test_purchase_signals_cover_commerce_vocabulary(self):
        names = [
            "purchase",
            "receipt",
            "receipts",
            "entitlement",
            "entitlements",
            "StoreKit",
            "transaction",
            "transactions",
            "subscription",
            "subscriptions",
            "payment",
            "payments",
            "billing",
            "checkout",
            "cart",
            "order",
            "IAP",
            "appStore",
            "productIdentifier",
            "productIdentifiers",
        ]
        funcs = [
            FakeFunction(i + 1, "worker", [self.comparison_return()], [SimpleNamespace(name=name)])
            for i, name in enumerate(names)
        ]
        result = self.make_engine(funcs).analyze_targeted(
            ["purchase-related booleans"], lambda: False
        )
        self.assertEqual(result.functions_considered, len(funcs))
        self.assertEqual(len(result.results), len(funcs))
        self.assertTrue(all(item.topic_evidence for item in result.results))

    def test_receipt_string_matches_purchase_topic(self):
        func = FakeFunction(0x1000, "check", [self.comparison_return()])
        string = SimpleNamespace(start=0x5000, value="receipt validation failed")
        ref = SimpleNamespace(function=func, address=0x1004)
        result = self.make_engine([func], [string], {string.start: [ref]}).analyze_targeted(
            ["purchase"], lambda: False
        )
        self.assertEqual(len(result.results), 1)
        self.assertTrue(any("receipt" in item.lower() for item in result.results[0].topic_evidence))

    def test_entitlement_callee_matches_purchase_topic(self):
        func = FakeFunction(
            0x1000,
            "check",
            [self.comparison_return()],
            [SimpleNamespace(name="hasEntitlement")],
        )
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(len(result.results), 1)
        self.assertTrue(result.results[0].topic_evidence)

    def test_caller_name_can_supply_topic_context(self):
        func = FakeFunction(0x1000, "check", [self.comparison_return()])
        func.callers = [SimpleNamespace(name="validateReceipts")]
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(len(result.results), 1)
        self.assertTrue(any("caller name" in item for item in result.results[0].topic_evidence))

    def test_restore_state_is_not_purchase_topic(self):
        func = FakeFunction(0x1000, "restoreState", [self.comparison_return()])
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(result.results, [])
        self.assertEqual(result.functions_considered, 1)

    def test_topic_evidence_does_not_change_final_score(self):
        func = FakeFunction(0x1000, "checkPurchase", [self.comparison_return()])
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(result.results[0].final_score, 30)
        self.assertTrue(result.results[0].topic_evidence)

    def test_targeted_scan_considers_every_function(self):
        funcs = [FakeFunction(i, f"worker{i}", [self.comparison_return()]) for i in range(1, 5)]
        result = self.make_engine(funcs).analyze_targeted(["receipt"], lambda: False)
        self.assertEqual(result.functions_considered, 4)
        self.assertEqual(result.complete, True)

    def test_one_bit_mask_return_is_candidate(self):
        func = FakeFunction(0x1000, "checkPurchase", [self.mask_return(1)])
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(len(result.results), 1)
        self.assertGreater(result.results[0].final_score, 15)

    def test_multi_bit_mask_return_is_not_boolean(self):
        func = FakeFunction(0x1000, "checkPurchase", [self.mask_return(3)])
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(result.results, [])

    def test_targeted_scan_deepens_low_score_match(self):
        func = FakeFunction(0x1000, "checkPurchase", [self.mask_return(1)])
        engine = self.make_engine([func])
        self.assertEqual(engine.analyze_function(func).final_score, 0)
        result = engine.analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(len(result.results), 1)
        self.assertIn("single-bit mask", result.results[0].evidence_list[-1].message)

    def test_cancel_reports_partial_counts(self):
        funcs = [FakeFunction(i, "receiptCheck", [self.comparison_return()]) for i in range(1, 4)]
        engine = self.make_engine(funcs)
        should_cancel = {"value": False}

        def progress(considered, total, deep):
            if considered == 1:
                should_cancel["value"] = True

        result = engine.analyze_targeted(["purchase"], lambda: should_cancel["value"], progress)
        self.assertTrue(result.cancelled)
        self.assertFalse(result.complete)
        self.assertEqual(result.functions_considered, 1)

    def test_changed_function_bytes_miss_cache(self):
        func = FakeFunction(0x1000, "check", [self.comparison_return()], raw=b"\x90")
        engine = self.make_engine([func])
        engine.analyze_function(func, deep=True)
        func.raw = b"\x91"
        engine.analyze_function(func, deep=True)
        self.assertEqual(len(engine._analysis_cache), 2)

    def test_deep_cache_key_tracks_renamed_function(self):
        func = FakeFunction(0x1000, "check", [self.comparison_return()])
        engine = self.make_engine([func])
        self.assertEqual(engine.analyze_function(func, deep=True).final_score, 30)
        func.name = "isReady"
        self.assertEqual(engine.analyze_function(func, deep=True).final_score, 40)

    def test_incomplete_deep_analysis_is_not_cached(self):
        func = FakeFunction(0x1000, "check", None)
        engine = self.make_engine([func])
        self.assertTrue(engine.analyze_function(func, deep=True).analysis_limited)
        self.assertEqual(engine._analysis_cache, {})
        func.hlil = FakeHLIL([self.comparison_return()])
        func.hlil_if_available = func.hlil
        result = engine.analyze_function(func, deep=True)
        self.assertFalse(result.analysis_limited)
        self.assertEqual(result.final_score, 30)

    def test_deep_cache_recomputes_caller_evidence(self):
        func = FakeFunction(0x1000, "check", [self.comparison_return()])
        bv = FakeBinaryView([func])
        engine = BoolHunterEngine(bv)
        self.assertEqual(engine.analyze_function(func, deep=True).final_score, 30)
        call_site = SimpleNamespace(
            address=0x2000,
            parent=SimpleNamespace(operation=Op.HLIL_IF, parent=None),
        )
        caller = FakeFunction(0x2000, "caller")
        caller.hlil_if_available = SimpleNamespace(
            traverse=lambda callback: [callback(call_site)]
        )
        bv.string_refs[func.start] = [SimpleNamespace(function=caller, address=call_site.address)]
        result = engine.analyze_function(func, deep=True)
        self.assertEqual(result.final_score, 42)

    def test_cache_evicts_oldest_entry(self):
        funcs = [FakeFunction(start, "check", [self.comparison_return()]) for start in (1, 2, 3)]
        engine = self.make_engine(funcs)
        engine.MAX_ANALYSIS_CACHE_ENTRIES = 2
        for func in funcs:
            engine.analyze_function(func, deep=True)
        self.assertEqual(len(engine._analysis_cache), 2)

    def test_ordinary_hunt_skips_hash_cache_path(self):
        func = FakeFunction(0x1000, "check", [self.comparison_return()])
        engine = self.make_engine([func])
        engine._cache_key = lambda *_: self.fail("ordinary HUNT must not hash")
        result = engine.analyze_function(func)
        self.assertEqual(result.final_score, 30)
        self.assertEqual(engine._analysis_cache, {})

    def test_unavailable_or_over_limit_hlil_is_bounded(self):
        func = FakeFunction(0x1000, "receiptCheck", None)
        func.too_large = True
        result = self.make_engine([func]).analyze_targeted(["purchase"], lambda: False)
        self.assertEqual(result.functions_limited, 1)
        self.assertFalse(result.complete)

    def test_string_reference_lookup_failure_marks_scan_incomplete(self):
        class BrokenStringBinaryView(FakeBinaryView):
            def get_strings(self):
                raise RuntimeError("string index unavailable")

        engine = BoolHunterEngine(BrokenStringBinaryView([]))
        result = engine.analyze_targeted(["purchase"], lambda: False)
        self.assertTrue(result.string_index_limited)
        self.assertFalse(result.complete)


if __name__ == "__main__":
    unittest.main()
