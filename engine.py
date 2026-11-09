import re
import time
import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from itertools import islice
from typing import Callable, List, Optional, Sequence

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
        self.category = "Other"
        self.topic_evidence: List[str] = []
        self.analysis_limited = False

    def add(self, score: int, message: str):
        self.score += score
        self.evidence_list.append(Evidence(score, message))

    @property
    def final_score(self) -> int:
        return min(100, self.score)


@dataclass
class TargetedScanResult:
    results: List[BoolResult]
    functions_considered: int
    functions_deeply_analyzed: int
    functions_limited: int
    cancelled: bool
    string_index_limited: bool = False
    elapsed_seconds: float = 0.0

    @property
    def complete(self) -> bool:
        return (
            not self.cancelled
            and self.functions_limited == 0
            and not self.string_index_limited
        )


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
    # shortcut: 128 entries, tune after representative Binary Ninja measurements.
    MAX_ANALYSIS_CACHE_ENTRIES = 128
    ANALYSIS_VERSION = 1
    MAX_TOPIC_SOURCES_PER_FUNCTION = 64
    MAX_TOPIC_STRING_CHARS = 512
    MAX_TOPIC_EVIDENCE_CHARS = 96
    PURCHASE_TOPIC_TERMS = (
        "purchase", "purchases", "buy", "checkout", "cart", "carts", "order", "orders",
        "transaction", "transactions", "payment", "payments", "billing",
        "subscription", "subscriptions", "receipt", "receipts", "entitlement",
        "entitlements", "storekit", "store kit", "appstore", "app store",
        "storefront", "skpayment", "skproduct", "product", "products", "product id",
        "product ids", "productid", "productids", "product identifier",
        "product identifiers", "iap", "in app", "inapp", "sku", "skus",
    )

    # Categories are intentionally conservative and based on recognizable
    # function-name vocabulary. The Boolean confidence score remains separate
    # from categorization so labels never affect candidate ranking.
    CATEGORY_PATTERNS = (
        ("Purchases", re.compile(
            r"(?:purchases?|buy|checkout|carts?|orders?|transactions?|payments?|pay|"
            r"billing|subscriptions?|receipts?|entitlements?|in[_-]?app|store)",
            re.IGNORECASE,
        )),
        ("Authentication & Security", re.compile(
            r"(?:login|log[_-]?in|logout|log[_-]?out|auth|password|credential|"
            r"token|session|secure|encrypt|decrypt|permission|authorize|biometric)",
            re.IGNORECASE,
        )),
        ("Network & Communication", re.compile(
            r"(?:http|https|url|request|response|fetch|download|upload|socket|"
            r"network|connect|connection|wifi|bluetooth|message|send|receive|sync)",
            re.IGNORECASE,
        )),
        ("Files & Storage", re.compile(
            r"(?:file|read|write|save|load|cache|document|path|directory|folder|"
            r"storage|database|sqlite|persist|serialize|deserialize)", re.IGNORECASE
        )),
        ("UI & Interaction", re.compile(
            r"(?:view|window|screen|button|menu|dialog|display|render|draw|click|"
            r"tap|gesture|touch|highlight|focus|visible)", re.IGNORECASE
        )),
        ("Navigation & Location", re.compile(
            r"(?:navigate|navigation|route|redirect|location|coordinate|map|gps|"
            r"latitude|longitude|address)", re.IGNORECASE
        )),
        ("Media", re.compile(
            r"(?:audio|video|image|photo|camera|microphone|record|play|pause|"
            r"stream|media|frame)", re.IGNORECASE
        )),
        ("Validation & State", re.compile(
            r"(?:valid|invalid|check|verify|validate|is[_-]?ready|enabled|active|"
            r"available|exists|empty|contains|supports|allows)", re.IGNORECASE
        )),
    )

    @classmethod
    def _category_for_name(cls, name: str) -> str:
        # Split camelCase while preserving underscores used by common symbol
        # names, then require term boundaries to avoid labels such as
        # Purchases for unrelated names like ``restoreState``.
        normalized_name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
        for category, pattern in cls.CATEGORY_PATTERNS:
            for match in pattern.finditer(normalized_name):
                before = normalized_name[match.start() - 1] if match.start() else ""
                after = normalized_name[match.end()] if match.end() < len(normalized_name) else ""
                if not before.isalnum() and not after.isalnum():
                    return category
        return "Other"

    def __init__(self, bv: BinaryView):
        self.bv = bv
        self._analysis_cache = OrderedDict()
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

    def _add_fast_evidence(self, func: Function, res: BoolResult):
        """Apply the existing inexpensive type and naming heuristics."""
        # Signal 1: Explicit Type (+60)
        if isinstance(func.return_type, BoolType):
            res.add(60, "Explicit Boolean return type")
        elif "bool" in str(func.return_type).lower():
            res.add(60, "Type system identifies return as Boolean-like")

        # Signal 6: Naming (+10 to +15)
        name = func.name
        # Handle Obj-C: -[Class isActive] -> isActive
        clean_name = name.split(' ')[-1].strip(']') if ' ' in name else name
        res.category = self._category_for_name(clean_name)
        if self.bool_patterns.match(clean_name):
            bonus = 15 if ' ' in name else 10
            res.add(bonus, f"Boolean-style naming pattern: '{clean_name}'")

    def fast_candidate_score(self, func: Function) -> int:
        """Return only the existing cheap type and naming heuristic score.

        A non-zero score is used to prioritize expensive analysis. Functions with
        no cheap evidence remain eligible for the later completeness pass.
        """
        res = BoolResult(func)
        self._add_fast_evidence(func, res)
        return res.final_score

    def is_fast_candidate(self, func: Function) -> bool:
        """Whether the cheap existing heuristics identify a priority candidate."""
        return self.fast_candidate_score(func) > 0

    def _cache_key(self, func: Function, deep: bool):
        try:
            size = max(0, int(func.total_bytes))
            if not size or size > self.MAX_FUNCTION_BYTES:
                return None
            raw = self.bv.read(func.start, size)
            if not raw:
                return None
            digest = hashlib.sha256(raw).digest()
            return (
                func.start,
                digest,
                str(func.return_type),
                str(func.name),
                self.ANALYSIS_VERSION,
                bool(deep),
            )
        except Exception:
            return None

    @staticmethod
    def _copy_result(source: BoolResult, func: Function) -> BoolResult:
        result = BoolResult(func)
        result.score = source.score
        result.evidence_list = list(source.evidence_list)
        result.category = source.category
        result.analysis_limited = source.analysis_limited
        return result

    def _remember_result(self, key, result: BoolResult):
        if key is None:
            return
        self._analysis_cache[key] = self._copy_result(result, result.func)
        self._analysis_cache.move_to_end(key)
        while len(self._analysis_cache) > self.MAX_ANALYSIS_CACHE_ENTRIES:
            self._analysis_cache.popitem(last=False)

    def analyze_function(self, func: Function, *, deep: bool = False) -> BoolResult:
        # Ordinary HUNT stays off the hash/cache path; targeted deep scans are opt-in.
        cache_key = self._cache_key(func, deep) if deep else None
        if cache_key in self._analysis_cache:
            self._analysis_cache.move_to_end(cache_key)
            result = self._copy_result(self._analysis_cache[cache_key], func)
            self._analyze_callers(func, result)
            return result

        res = BoolResult(func)
        self._add_fast_evidence(func, res)

        # HLIL Analysis. Accessing func.hlil can force native decompiler work,
        # so do not request it for a function Binary Ninja has already flagged
        # as oversized or skipped.
        if not self._should_skip_hlil(func):
            try:
                hlil = func.hlil
            except Exception:
                hlil = None
            if hlil:
                try:
                    res.analysis_limited = not self._analyze_hlil(func, hlil, res, deep=deep)
                except Exception:
                    res.analysis_limited = True
            else:
                res.analysis_limited = True
        else:
            res.analysis_limited = True

        # Cache local signals only; caller evidence depends on changing references.
        if not res.analysis_limited:
            self._remember_result(cache_key, res)
        self._analyze_callers(func, res)
        return res

    @staticmethod
    def _return_expressions(ret):
        """Normalize legacy scalar and current list-based HLIL return operands."""
        src = ret.src
        return src if isinstance(src, (list, tuple)) else [src]

    def _analyze_hlil(self, func: Function, hlil, res: BoolResult, *, deep=False):
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
                    return False
                if instr.operation == HighLevelILOperation.HLIL_RET:
                    returns.append(instr)

        if not returns:
            return True

        # Current HLIL represents HighLevelILRet.src as a list. Accept a scalar as
        # well to remain compatible with earlier API releases.
        return_expressions = [
            expr for ret in returns for expr in self._return_expressions(ret)
        ]
        if not return_expressions:
            return True

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

        if deep and all(
            expr.operation == getattr(HighLevelILOperation, "HLIL_AND", None)
            and self._has_single_bit_constant(expr)
            for expr in return_expressions
        ):
            res.add(20, "All return paths use a single-bit mask")
        return True

    @staticmethod
    def _has_single_bit_constant(expr) -> bool:
        for operand in (getattr(expr, "left", None), getattr(expr, "right", None)):
            if getattr(operand, "operation", None) == HighLevelILOperation.HLIL_CONST:
                value = getattr(operand, "constant", 0)
                if isinstance(value, int) and value > 0 and value & (value - 1) == 0:
                    return True
        return False

    @staticmethod
    def _normalize_topic_text(text: str) -> str:
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        return re.sub(r"[^a-zA-Z0-9]+", " ", text).casefold().strip()

    @classmethod
    def _topic_terms(cls, terms: Sequence[str]) -> List[str]:
        normalized = [cls._normalize_topic_text(term) for term in terms if isinstance(term, str)]
        normalized = [term for term in normalized if term]
        purchase_terms = set(cls.PURCHASE_TOPIC_TERMS)
        if any(purchase_terms.intersection(term.split()) for term in normalized):
            normalized.extend(cls.PURCHASE_TOPIC_TERMS)
        return list(dict.fromkeys(normalized))

    @classmethod
    def _match_topic(cls, text: str, terms: Sequence[str]) -> Optional[str]:
        normalized_text = " " + cls._normalize_topic_text(text) + " "
        for term in terms:
            if " " + term + " " in normalized_text:
                return term
        return None

    def _referenced_strings(self, terms: Sequence[str], is_cancelled: Callable[[], bool]):
        by_function = {}
        index_limited = False
        try:
            strings = self.bv.get_strings()
        except Exception:
            return by_function, False, True

        try:
            for string in strings:
                if is_cancelled():
                    return by_function, True, index_limited
                try:
                    value = string.value
                    if isinstance(value, bytes):
                        value = value[:self.MAX_TOPIC_STRING_CHARS * 4].decode(
                            "utf-8", errors="replace"
                        )
                    text = str(value).split("\x00", 1)[0][:self.MAX_TOPIC_STRING_CHARS]
                    if not self._match_topic(text, terms):
                        continue
                    refs = self._get_bounded_code_refs(string.start)
                except Exception:
                    index_limited = True
                    continue

                for ref in refs:
                    if is_cancelled():
                        return by_function, True, index_limited
                    try:
                        function = getattr(ref, "function", None)
                        if function is None or not text:
                            continue
                        sources = by_function.setdefault(function.start, [])
                        if len(sources) < self.MAX_TOPIC_SOURCES_PER_FUNCTION - 1:
                            sources.append(text)
                    except Exception:
                        index_limited = True
        except Exception:
            index_limited = True
        return by_function, False, index_limited

    def _topic_evidence(self, func: Function, terms: Sequence[str], referenced_strings) -> List[str]:
        sources = [("function name", getattr(func, "name", ""))]
        for value in referenced_strings.get(func.start, ())[:self.MAX_TOPIC_SOURCES_PER_FUNCTION - 1]:
            sources.append(("referenced string", value))
        for attribute, source in (("callees", "callee/API name"), ("callers", "caller name")):
            remaining_sources = self.MAX_TOPIC_SOURCES_PER_FUNCTION - len(sources)
            if remaining_sources <= 0:
                break
            try:
                functions = getattr(func, attribute)
            except Exception:
                functions = ()
            for related_function in islice(functions or (), remaining_sources):
                sources.append((source, getattr(related_function, "name", "")))

        evidence = []
        for source, text in sources[:self.MAX_TOPIC_SOURCES_PER_FUNCTION]:
            matched_term = self._match_topic(str(text), terms)
            if matched_term:
                excerpt = str(text).replace("\n", " ")[:self.MAX_TOPIC_EVIDENCE_CHARS]
                evidence.append(f"{source} matched '{matched_term}': {excerpt}")
        return list(dict.fromkeys(evidence))

    def analyze_targeted(
        self,
        topic_terms: Sequence[str],
        is_cancelled: Callable[[], bool],
        on_progress: Optional[Callable[[int, int, int], None]] = None,
    ) -> TargetedScanResult:
        """Triage every function, then deeply analyze topic-relevant candidates."""
        started = time.monotonic()
        functions = list(self.bv.functions)
        total = len(functions)
        terms = self._topic_terms(topic_terms)
        referenced_strings, cancelled, string_index_limited = self._referenced_strings(
            terms, is_cancelled
        )
        results = []
        considered = 0
        deeply_analyzed = 0
        limited = 0

        if cancelled:
            return TargetedScanResult(
                results, 0, 0, 0, True, string_index_limited,
                time.monotonic() - started,
            )

        for func in functions:
            if is_cancelled():
                cancelled = True
                break
            considered += 1
            topic_evidence = self._topic_evidence(func, terms, referenced_strings)
            if topic_evidence:
                deeply_analyzed += 1
                result = self.analyze_function(func, deep=True)
                result.topic_evidence = topic_evidence
                if result.analysis_limited:
                    limited += 1
                if result.final_score > 15:
                    results.append(result)
            if on_progress is not None:
                on_progress(considered, total, deeply_analyzed)

        return TargetedScanResult(
            results,
            considered,
            deeply_analyzed,
            limited,
            cancelled,
            string_index_limited,
            time.monotonic() - started,
        )

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
