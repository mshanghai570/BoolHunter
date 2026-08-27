import re
from dataclasses import dataclass
from typing import List, Optional
from binaryninja import (
    BinaryView, Function, HighLevelILOperation, 
    HighLevelILInstruction, BoolType, TypeVariant
)

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
    def __init__(self, bv: BinaryView):
        self.bv = bv
        # Regex for common Boolean naming patterns (includes Obj-C)
        self.bool_patterns = re.compile(
            r'^(is|has|can|should|valid|enabled|active|exists|supports|contains|allows)', 
            re.IGNORECASE
        )

    def analyze_function(self, func: Function) -> BoolResult:
        res = BoolResult(func)
        
        # Signal 1: Explicit Type (+60)
        if isinstance(func.return_type, BoolType):
            res.add(60, "Explicit Boolean return type")
        elif "bool" in str(func.return_type).lower():
            res.add(60, "Type system identifies return as Boolean-like")

        # HLIL Analysis
        hlil = func.hlil
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

    def _analyze_hlil(self, func: Function, hlil, res: BoolResult):
        returns = []
        for block in hlil:
            for instr in block:
                if instr.operation == HighLevelILOperation.HLIL_RET:
                    returns.append(instr)

        if not returns:
            return

        # Signal 2: Constant Returns 0/1 (+35)
        is_all_bool_const = True
        has_const = False
        for ret in returns:
            expr = ret.src
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
            HighLevelILOperation.HLIL_CMP_E, HighLevelILOperation.HLIL_CMP_NE,
            HighLevelILOperation.HLIL_CMP_SLT, HighLevelILOperation.HLIL_CMP_ULT,
            HighLevelILOperation.HLIL_CMP_SLE, HighLevelILOperation.HLIL_CMP_ULE,
            HighLevelILOperation.HLIL_CMP_SGT, HighLevelILOperation.HLIL_CMP_UGT,
            HighLevelILOperation.HLIL_CMP_SGE, HighLevelILOperation.HLIL_CMP_UGE
        ]
        
        normalization_ops = [HighLevelILOperation.HLIL_LNOT]

        for ret in returns:
            expr = ret.src
            # Direct comparison: return a == b
            if expr.operation in comp_ops:
                res.add(30, "Return expression is a comparison result")
                break
            # Normalization: return !!x (HLIL represents !! as a simplification or LNOT)
            if expr.operation in normalization_ops:
                res.add(30, "Return value is logically normalized (Boolean normalization)")
                break

    def _analyze_callers(self, func: Function, res: BoolResult):
        conditional_uses = 0
        # Check cross-references
        for ref in self.bv.get_code_refs(func.start):
            caller = ref.function
            c_hlil = caller.hlil
            if not c_hlil: continue
            
            # Find the instruction at the call site
            try:
                instr = c_hlil.get_instruction_at(ref.address)
                if not instr: continue
                
                # Walk up to see if the call result is used in a branch
                parent = instr.parent
                if parent and parent.operation in [
                    HighLevelILOperation.HLIL_IF, 
                    HighLevelILOperation.HLIL_WHILE, 
                    HighLevelILOperation.HLIL_FOR
                ]:
                    conditional_uses += 1
            except:
                continue

        if conditional_uses > 0:
            res.add(min(25, 10 + (conditional_uses * 2)), f"Result used conditionally by {conditional_uses} caller(s)")