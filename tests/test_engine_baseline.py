import unittest
from types import SimpleNamespace

from tests.support.binaryninja_stub import (
    BoolType,
    HighLevelILOperation as Op,
    install_binaryninja_stub,
)

install_binaryninja_stub()

from engine import BoolHunterEngine


class FakeBinaryView:
    def get_code_refs(self, address, max_items=None):
        return []


class FakeFunction:
    start = 0x1000
    total_bytes = 8
    too_large = False
    analysis_skipped = False
    hlil = None

    def __init__(self, name="ordinary", return_type="int"):
        self.name = name
        self.return_type = return_type


class FakeHLIL:
    def __init__(self, instructions):
        self.blocks = [instructions]

    def __iter__(self):
        return iter(self.blocks)


class TestEngineBaseline(unittest.TestCase):
    def setUp(self):
        self.engine = BoolHunterEngine(FakeBinaryView())

    def score(self, func, instructions=None):
        func.hlil = FakeHLIL(instructions) if instructions is not None else None
        return self.engine.analyze_function(func)

    @staticmethod
    def ret(operation, constant=None):
        if operation == Op.HLIL_CONST:
            src = SimpleNamespace(operation=operation, constant=constant)
        else:
            src = SimpleNamespace(operation=operation)
        return SimpleNamespace(operation=Op.HLIL_RET, src=[src])

    def test_explicit_bool_return_scores_60(self):
        result = self.score(FakeFunction(return_type=BoolType()))
        self.assertEqual(result.final_score, 60)
        self.assertIn("Explicit Boolean return type", [item.message for item in result.evidence_list])

    def test_bool_like_type_string_scores_60(self):
        result = self.score(FakeFunction(return_type="BOOL"))
        self.assertEqual(result.final_score, 60)
        self.assertIn("Type system identifies return as Boolean-like", [item.message for item in result.evidence_list])

    def test_all_zero_one_returns_score_35(self):
        result = self.score(FakeFunction(), [self.ret(Op.HLIL_CONST, 0), self.ret(Op.HLIL_CONST, 1)])
        self.assertEqual(result.final_score, 35)

    def test_comparison_return_scores_30(self):
        result = self.score(FakeFunction(), [self.ret(Op.HLIL_CMP_E)])
        self.assertEqual(result.final_score, 30)
        self.assertIn("Return expression is a comparison result", [item.message for item in result.evidence_list])

    def test_logical_not_return_scores_30(self):
        result = self.score(FakeFunction(), [self.ret(Op.HLIL_NOT)])
        self.assertEqual(result.final_score, 30)
        self.assertIn("Boolean normalization", result.evidence_list[0].message)

    def test_bool_name_adds_10(self):
        result = self.score(FakeFunction(name="isReady"))
        self.assertEqual(result.final_score, 10)
        self.assertIn("Boolean-style naming pattern", result.evidence_list[0].message)

    def test_objc_bool_name_adds_15(self):
        result = self.score(FakeFunction(name="-[PurchaseController isReady]"))
        self.assertEqual(result.final_score, 15)
        self.assertIn("Boolean-style naming pattern", result.evidence_list[0].message)

    def test_conditional_caller_adds_evidence(self):
        result = self.score(FakeFunction())
        call_site = SimpleNamespace(address=0x2000, parent=SimpleNamespace(operation=Op.HLIL_IF, parent=None))
        caller_hlil = SimpleNamespace(traverse=lambda callback: [callback(call_site)])
        self.engine._get_bounded_code_refs = lambda address: [
            SimpleNamespace(function=FakeFunction(name="caller"), address=0x2000)
        ]
        self.engine._get_available_hlil = lambda func: caller_hlil
        self.engine._analyze_callers(result.func, result)
        self.assertEqual(result.final_score, 12)
        self.assertIn("used conditionally by 1 caller", result.evidence_list[-1].message)

    def test_purchase_category_does_not_change_score(self):
        result = self.score(FakeFunction(name="purchaseProcess"))
        self.assertEqual(result.category, "Purchases")
        self.assertEqual(result.final_score, 0)


if __name__ == "__main__":
    unittest.main()
