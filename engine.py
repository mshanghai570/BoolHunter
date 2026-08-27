import re
import time
from dataclasses import dataclass
from itertools import islice
from typing import List

from binaryninja import BinaryView, BoolType, Function, HighLevelILOperation


class AnalysisLimitReached(Exception):
    """Raised internally to stop a pathological HLIL traversal."""


@dataclass
class Evidence:
    score: int
    message: str


class BoolResult:
    def __init__(self, func: Function):
        self.func = func
        self.score = 0
        self.evidence_list: List[Evidence] = []

    def add(self, score: int, message: str):
        self.score += score
        self.evidence_list.append(Evidence(score, message))

    @property
    def final_score(self) -> int:
        return min(100, self.score)


class BoolHunterEngine:
    # These limits bound pathological decompiler output without changing scoring
    # for ordinarily sized functions and caller sets.
    MAX_FUNCTION_BYTES = 64 * 1024
    MAX_HLIL_INSTRUCTIONS = 10_000
    MAX_HLIL_ANALYSIS_SECONDS = 1.0
    MAX_CALLER_REFERENCES = 64
    MAX_CALLER_ANALYSIS_SECONDS = 1.0
    MAX_CALLER_HLIL_NODES = 8_000
    MAX_CALLER_HLIL_SECONDS = 0.25
    MAX_HLIL_PARENT_DEPTH = 128
    MAX_CONDITIONAL_USES = 8

    def __init__(self, bv: BinaryView):
        self.bv = bv
        # Regex for common Boolean naming patterns (includes Obj-C)
        self.bool_patterns = re.compile(
            r'^(is|has|can|should|valid|enabled|active|exists|supports|contains|allows)',
            re.IGNORECASE,
        )

    def _should_skip_hlil(self, func: Function) -> bool:
        """Avoid forcing HLIL generation for functions known to be pathological."""
        for attribute in ("too_large", "analysis_skipped"):
            try:
                if getattr(func, attribute):
                    return True
            except (AttributeError, RuntimeError):
                # Retain compatibility with API versions that do not expose one
                # of these safeguards.
                continue

        try:
            return func.total_bytes > self.MAX_FUNCTION_BYTES
        except (AttributeError, RuntimeError):
            return False

    def analyze_function(self, func: Function) -> BoolResult:
        res = BoolResult(func)

        # Signal 1: Explicit Type (+60)
        if isinstance(func.return_type, BoolType):
            res.add(60, "Explicit Boolean return type")
        elif "bool" in str(func.return_type).lower():
            res.add(60, "Type system identifies return as Boolean-like")

        # HLIL Analysis. Accessing func.hlil can force native decompiler work,
        # so do not request it for a function Binary Ninja has already flagged
        # as oversized or skipped.
        if not self._should_skip_hlil(func):
            try:
                hlil = func.hlil
            except Exception:
                hlil = None
            if hlil:
                self._analyze_hlil(func, hlil, res)

        # Signal 4: Caller Analysis (+20)
        self._analyze_callers(func, res)

        # Signal 6: Naming (+10 to +15)
        name = func.name
        # Handle Obj-C: -[Class isActive] -> isActive
        clean_name = name.split(' ')[-1].strip(']') if ' ' in name else name
        if self.bool_patterns.match(clean_name):
            bonus = 15 if ' ' in name else 10
            res.add(bonus, f"Boolean-style naming pattern: '{clean_name}'")

        return res

    @staticmethod
    def _return_expressions(ret):
        """Normalize legacy scalar and current list-based HLIL return operands."""
        src = ret.src
        return src if isinstance(src, (list, tuple)) else [src]

    def _analyze_hlil(self, func: Function, hlil, res: BoolResult):
        returns = []
        instruction_count = 0
        deadline = time.monotonic() + self.MAX_HLIL_ANALYSIS_SECONDS
        for block in hlil:
            for instr in block:
                instruction_count += 1
                if (
                    instruction_count > self.MAX_HLIL_INSTRUCTIONS
                    or time.monotonic() > deadline
                ):
                    # Do not award partial all-return-path evidence when all
                    # returns were not inspected.
                    return
                if instr.operation == HighLevelILOperation.HLIL_RET:
                    returns.append(instr)

        if not returns:
            return

        # Current HLIL represents HighLevelILRet.src as a list. Accept a scalar as
        # well to remain compatible with earlier API releases.
        return_expressions = [
            expr for ret in returns for expr in self._return_expressions(ret)
        ]
        if not return_expressions:
            return

        # Signal 2: Constant Returns 0/1 (+35)
        is_all_bool_const = True
        has_const = False
        for expr in return_expressions:
            if expr.operation == HighLevelILOperation.HLIL_CONST:
                if expr.constant in [0, 1]:
                    has_const = True
                else:
                    is_all_bool_const = False
            else:
                is_all_bool_const = False

        if is_all_bool_const and has_const:
            res.add(35, "All return paths produce constant 0 or 1")

        # Signal 3 & 5: Comparisons / Normalization (+30)
        comp_ops = [
            HighLevelILOperation.HLIL_CMP_E,
            HighLevelILOperation.HLIL_CMP_NE,
            HighLevelILOperation.HLIL_CMP_SLT,
            HighLevelILOperation.HLIL_CMP_ULT,
            HighLevelILOperation.HLIL_CMP_SLE,
            HighLevelILOperation.HLIL_CMP_ULE,
            HighLevelILOperation.HLIL_CMP_SGT,
            HighLevelILOperation.HLIL_CMP_UGT,
            HighLevelILOperation.HLIL_CMP_SGE,
            HighLevelILOperation.HLIL_CMP_UGE,
        ]
        # Binary Ninja represents a high-level logical NOT with HLIL_NOT.
        normalization_ops = [HighLevelILOperation.HLIL_NOT]

        for expr in return_expressions:
            # Direct comparison: return a == b
            if expr.operation in comp_ops:
                res.add(30, "Return expression is a comparison result")
                break
            # Normalization: return !!x (HLIL represents logical NOT as HLIL_NOT).
            if expr.operation in normalization_ops:
                res.add(30, "Return value is logically normalized (Boolean normalization)")
                break

    def _is_conditionally_used(self, c_hlil, address: int) -> bool:
        """Return whether the current HLIL AST places an instruction at address in a branch."""
        conditional_ops = {
            HighLevelILOperation.HLIL_IF,
            HighLevelILOperation.HLIL_WHILE,
            HighLevelILOperation.HLIL_FOR,
        }
        visited_nodes = 0
        deadline = time.monotonic() + self.MAX_CALLER_HLIL_SECONDS

        def check_instruction(instr):
            nonlocal visited_nodes
            visited_nodes += 1
            if (
                visited_nodes > self.MAX_CALLER_HLIL_NODES
                or time.monotonic() > deadline
            ):
                raise AnalysisLimitReached

            if instr.address != address:
                return None

            parent = instr.parent
            parent_depth = 0
            while parent:
                parent_depth += 1
                if parent_depth > self.MAX_HLIL_PARENT_DEPTH:
                    return None
                if parent.operation in conditional_ops:
                    return True
                parent = parent.parent
            return None

        try:
            for result in c_hlil.traverse(check_instruction):
                if result:
                    return True
        except (AnalysisLimitReached, RecursionError):
            return False
        return False

    def _get_bounded_code_refs(self, address: int):
        """Use Binary Ninja's native reference cap, with an older-API fallback."""
        try:
            return self.bv.get_code_refs(address, max_items=self.MAX_CALLER_REFERENCES)
        except TypeError:
            return islice(self.bv.get_code_refs(address), self.MAX_CALLER_REFERENCES)

    @staticmethod
    def _get_available_hlil(func: Function):
        """Avoid generating a caller's HLIL solely for a heuristic bonus."""
        try:
            return func.hlil_if_available
        except AttributeError:
            # Older APIs do not offer the non-generating accessor.
            try:
                return func.hlil
            except Exception:
                return None
        except Exception:
            return None

    def _analyze_callers(self, func: Function, res: BoolResult):
        conditional_uses = 0
        seen_references = set()
        deadline = time.monotonic() + self.MAX_CALLER_ANALYSIS_SECONDS

        # Check a bounded number of cross-references. The maximum caller score
        # is reached at eight conditional references, so more work cannot alter
        # BoolHunter's final score.
        for ref in self._get_bounded_code_refs(func.start):
            if time.monotonic() > deadline:
                break

            caller = ref.function
            ref_key = (caller.start, ref.address)
            if ref_key in seen_references:
                continue
            seen_references.add(ref_key)

            if self._should_skip_hlil(caller):
                continue

            try:
                c_hlil = self._get_available_hlil(caller)
                if not c_hlil:
                    continue
                if self._is_conditionally_used(c_hlil, ref.address):
                    conditional_uses += 1
                    if conditional_uses >= self.MAX_CONDITIONAL_USES:
                        break
            except Exception:
                continue

        if conditional_uses > 0:
            res.add(
                min(25, 10 + (conditional_uses * 2)),
                f"Result used conditionally by {conditional_uses} caller(s)",
            )
