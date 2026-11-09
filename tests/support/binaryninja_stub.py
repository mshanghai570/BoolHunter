"""Minimal Binary Ninja import stub used only by pure Python unit tests."""

import sys
from types import SimpleNamespace


class BoolType:
    pass


class BinaryView:
    pass


class Function:
    pass


HighLevelILOperation = SimpleNamespace(
    HLIL_RET=1,
    HLIL_CONST=2,
    HLIL_CMP_E=3,
    HLIL_CMP_NE=4,
    HLIL_CMP_SLT=5,
    HLIL_CMP_ULT=6,
    HLIL_CMP_SLE=7,
    HLIL_CMP_ULE=8,
    HLIL_CMP_SGT=9,
    HLIL_CMP_UGT=10,
    HLIL_CMP_SGE=11,
    HLIL_CMP_UGE=12,
    HLIL_NOT=13,
    HLIL_IF=14,
    HLIL_WHILE=15,
    HLIL_FOR=16,
    HLIL_AND=17,
    HLIL_VAR=18,
)


def install_binaryninja_stub():
    """Install only names imported by engine.py; production never imports this."""
    sys.modules["binaryninja"] = SimpleNamespace(
        BinaryView=BinaryView,
        BoolType=BoolType,
        Function=Function,
        HighLevelILOperation=HighLevelILOperation,
    )
