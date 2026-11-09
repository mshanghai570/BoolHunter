# BoolHunter Discovery Core Implementation Plan

> **For agentic workers:** Use the approved design and this plan after the baseline harness passes.

**Goal:** Improve deterministic Boolean detection and add a bounded, cancellable, topic-focused deep pass over the whole binary.

**Architecture:** Keep `BoolHunterEngine` and existing scores. Add separate topic evidence, targeted-only Boolean signals, and a bounded per-engine cache. The engine stays UI-agnostic; the chat worker calls it off the UI thread.

**Tech Stack:** Python, Binary Ninja Python API, standard-library `hashlib`, `collections.OrderedDict`, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-09-boolhunter-overhaul-design.md`

## Global Constraints

- Retain declared minimum Binary Ninja build (`3500`) unless verified API requirements force a documented change.
- No additional runtime Python packages are planned.
- The ordinary hunt stays on the fast path and makes zero AI/network calls.
- No more than 10% median runtime regression versus public-main baseline.
- Topic relevance must not add Boolean confidence points.
- Keep local Mac files untouched.

## Review Focus

1. Non-Boolean functions with commerce-like names: topic evidence must not raise Boolean score; test `test_restore_state_is_not_purchase_topic`.
2. Boolean functions with commerce strings or API/callee names: targeted pass must consider them; test `test_receipt_string_matches_purchase_topic` and `test_entitlement_callee_matches_purchase_topic`.
3. Functions below the ordinary result threshold: deepen topic-relevant functions; test `test_targeted_scan_deepens_low_score_match`.
4. Pathological/unavailable HLIL: keep bounds and report limited work; test `test_unavailable_or_over_limit_hlil_is_bounded`.
5. Cancellation and changed code: return partial counts and invalidate stale entries; test `test_cancel_reports_partial_counts` and `test_changed_function_bytes_miss_cache`.

---

### Task 1: Specify targeted-discovery behavior in tests

**Files:**
- Create: `tests/test_discovery.py`
- Use: `tests/support/binaryninja_stub.py`

**Interfaces:**
- `TargetedScanResult` fields: `results`, `functions_considered`, `functions_deeply_analyzed`, `functions_limited`, and `cancelled`.
- `TargetedScanResult.complete -> bool` returns `not cancelled and functions_limited == 0`.

- [ ] Add failing topic tests for receipts, entitlements, store APIs, transactions, subscriptions, and payments, plus generic `restoreState` as a negative.
- [ ] Add paired Boolean fixtures: `test_one_bit_mask_return_is_candidate` and `test_multi_bit_mask_return_is_not_boolean`. Keep any new score conservative and targeted-only; retain the rule only if the pair demonstrates useful separation.
- [ ] Add `test_topic_evidence_does_not_change_final_score`, `test_targeted_scan_considers_every_function`, `test_targeted_scan_deepens_low_score_match`, `test_cancel_reports_partial_counts`, `test_changed_function_bytes_miss_cache`, and `test_cache_evicts_oldest_entry`.
- [ ] Run `python3 -m unittest discover -s tests -v`; expected: new discovery tests fail before implementation.

### Task 2: Implement bounded deterministic targeted discovery

**Files:**
- Modify: `engine.py`
- Modify: `tests/test_discovery.py`

**Interfaces:**
- Add `BoolResult.topic_evidence: List[str]`; do not add topic points to `score`.
- Use `analyze_function(func: Function, *, deep: bool = False) -> BoolResult`; `deep=False` preserves ordinary-hunt behavior.
- Add `TargetedScanResult(results: List[BoolResult], functions_considered: int, functions_deeply_analyzed: int, functions_limited: int, cancelled: bool)` with the `complete` property above.
- Add `analyze_targeted(topic_terms: Sequence[str], is_cancelled: Callable[[], bool], on_progress: Optional[Callable[[int, int, int], None]] = None) -> TargetedScanResult` to `BoolHunterEngine`. Progress values are `(considered, total, deeply_analyzed)`.
- Cache results in a per-engine LRU keyed by function address, SHA-256 of bounded function bytes, return type, analysis version, and deep/ordinary mode. Select and record the LRU capacity after representative measurements, as the spec requires. Skip caching if bytes cannot be read.

- [ ] Implement cheap topic triage over bounded function/callee names, referenced strings, and imported/called API names; consider every eligible function once.
- [ ] Add deeper deterministic Boolean signals only to the targeted path. Every new Boolean score contribution must add explicit evidence.
- [ ] Deep-analyze topic-relevant functions even when their ordinary score is below the existing threshold; retain the existing final result threshold.
- [ ] Check cancellation between functions and reuse existing per-function traversal/time limits. Count limited functions rather than presenting partial analysis as complete.
- [ ] Run `python3 -m unittest discover -s tests -v` and `python3 -m py_compile __init__.py ai.py engine.py main.py ui.py`.
- [ ] Compare five-run ordinary-hunt medians against Task 1's baseline on the same Binary Ninja build and binary; require ≤10% regression.
- [ ] Run `git diff --check`; confirm the ordinary path sends no network request and topic terms do not alter scores.
