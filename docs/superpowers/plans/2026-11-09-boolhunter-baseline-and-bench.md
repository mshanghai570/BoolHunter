# BoolHunter Baseline and Bench Implementation Plan

> **For agentic workers:** Use the approved design and this plan task-by-task. Verify each task before moving on.

**Goal:** Capture current detection behavior and runtime before changing the engine.

**Architecture:** Use `unittest` with a tiny Binary Ninja import stub for engine tests. Add a manual benchmark callable for a real `BinaryView`; no runtime changes or dependencies.

**Tech Stack:** Python standard library; Binary Ninja Python API for the manual benchmark only.

**Spec:** `docs/superpowers/specs/2026-11-09-boolhunter-overhaul-design.md`

## Global Constraints

- Retain declared minimum Binary Ninja build (`3500`) unless verified API requirements force a documented change.
- No additional runtime Python packages are planned.
- The ordinary hunt stays on the fast path and makes zero AI/network calls.
- No more than 10% median runtime regression versus public-main baseline.
- Keep provider credentials session-only; never log credentials or authorization headers.
- Keep local Mac files untouched.

## Review Focus

1. Binary Ninja is absent in sandbox: test doubles cover only import-time names; `test_engine_imports_with_stub` verifies isolation.
2. Boolean return types vary: `test_explicit_bool_return_scores_60` and `test_bool_like_type_string_scores_60` cover both.
3. All current evidence paths matter: tests pin constant, comparison, logical-NOT, naming, Objective-C, and conditional-caller behavior.
4. Timing is noisy: benchmark uses five full runs and reports median plus every run.
5. Baselines are host-specific: record Binary Ninja version and binary identity with the result; never compare different inputs.

---

### Task 1: Lock down current engine behavior

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/support/__init__.py`
- Create: `tests/support/binaryninja_stub.py`
- Create: `tests/test_engine_baseline.py`

**Interfaces:**
- `install_binaryninja_stub() -> None` installs only the minimal `binaryninja` import names needed by `engine.py` tests.
- Fake functions and HLIL nodes stay in tests; production modules never import the stub.

- [ ] Add `test_explicit_bool_return_scores_60`, `test_bool_like_type_string_scores_60`, `test_all_zero_one_returns_score_35`, `test_comparison_return_scores_30`, and `test_logical_not_return_scores_30`.
- [ ] Add `test_bool_name_adds_10`, `test_objc_bool_name_adds_15`, `test_conditional_caller_adds_evidence`, and `test_purchase_category_does_not_change_score`.
- [ ] Assert each test's expected score/evidence; category-only matches must leave `final_score` unchanged.
- [ ] Run `python3 -m unittest discover -s tests -v`; expected: all baseline tests pass against the unmodified public-main engine.
- [ ] Run `python3 -m py_compile __init__.py ai.py engine.py main.py ui.py tests/test_engine_baseline.py`.

### Task 2: Add a repeatable hunt benchmark

**Files:**
- Create: `tests/benchmark_hunt.py`

**Interface:**
- `benchmark_binary_view(bv: BinaryView, repeats: int = 5) -> Tuple[int, List[float], float]` returns function count, all run times in seconds, and their median.

- [ ] Measure five full ordinary-hunt-equivalent runs with `BoolHunterEngine` and `time.perf_counter`.
- [ ] In Binary Ninja's Python environment, run `benchmark_binary_view(bv)` on a representative binary before and after engine changes.
- [ ] Record Binary Ninja version, binary identity, function count, all five times, and median in review notes.
- [ ] Confirm the result includes every run and uses `statistics.median`; do not discard slow runs.
- [ ] Run `python3 -m unittest discover -s tests -v` and `git diff --check`.
