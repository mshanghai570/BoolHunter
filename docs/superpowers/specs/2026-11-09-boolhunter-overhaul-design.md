# BoolHunter Overhaul Design

**Date:** 2026-11-09

**Baseline:** Public GitHub `main`, commit `82226d4`

**Status:** Approved by user; sandbox implementation complete, with host validation and performance measurements pending

## Intent

Improve BoolHunter's ability to find Boolean-returning functions consistently and let a user express follow-up analysis requests conversationally—for example, “double down on purchase-related booleans.” The plugin should keep its ordinary hunt lightweight, while a user-requested intent can trigger a deeper targeted pass over the whole binary.

The overhaul starts from the public GitHub repository. The locally installed Mac copy is out of scope and will not be changed or reconciled.

## Goals

- Improve Boolean candidate recall and consistency without hiding false positives or weakening the meaning of evidence.
- Keep ordinary **HUNT** responsive and independent of AI/network availability.
- Support conversational requests and follow-ups that create an actionable, safe analysis plan.
- For a targeted request, cheaply triage all eligible functions, then spend deeper-analysis effort on functions whose code or context is relevant to the request; report coverage and cancellation/partial status clearly.
- Keep ranking and evidence deterministic and inspectable. AI may interpret intent and explain results, but may not fabricate evidence or change scores.
- Avoid new runtime dependencies and avoid an LLM request per function.

## Non-goals

- Automatically renaming functions, changing types/comments, or executing model-generated code.
- Sending every function's pseudocode to an LLM.
- Replacing Binary Ninja's analysis or promising semantic certainty where the available IL/context is insufficient.
- Reworking or installing over the user's Mac plugin during this task.
- Integrating Binary Ninja's separate native AI feature; the configured OpenAI-compatible provider is retained.

## Anti-goals

- Making every hunt use the expensive targeted path.
- Treating the displayed heuristic score as a calibrated probability.
- Silently truncating a targeted whole-binary pass and presenting it as complete.
- Adding a large framework or persistent service for this plugin.

## Approaches considered

1. **Always deep-scan:** run the expensive analysis for all functions on every hunt. This may find more candidates, but imposes the cost on every user and conflicts with the speed requirement.
2. **Staged, on-demand analysis — selected:** retain a cheap ordinary hunt; use a bounded/cancellable whole-binary triage only when a request calls for it, and deepen relevant candidates. Reuse cached per-function work. This balances recall, speed, and responsiveness.
3. **LLM-driven review of every function:** ask a model to inspect the whole binary function-by-function. This is slower, costs more, leaks more code context, and makes results less repeatable, so it is not the chosen design.

The user selected the staged approach and explicitly approved a targeted deeper whole-binary pass for requests such as “double down on purchase-related booleans.”

## Approved capability map and build order

| Module | Responsibility | Depends on |
|---|---|---|
| `baseline-and-bench` | Small labeled regression corpus and lightweight baseline measurements for recall/precision and ordinary-hunt time. | — |
| `discovery-core` | Fast ordinary hunt plus deterministic, cancellable, bounded targeted analysis over the whole binary; evidence and result caching. | `baseline-and-bench` as its validation gate |
| `intent-chat` | Conversational intent interpretation, constrained action plans, chat state, dispatch to discovery, and result explanations. No per-function LLM calls. | `discovery-core` |

Build order: baseline/benchmark → discovery core → intent chat. The benchmark is a development/test artifact and adds no runtime cost.

## Proposed behavior

### Ordinary hunt

- Preserve a low-cost first pass and current asynchronous/cancellable UI behavior.
- Improve deterministic recognition incrementally using representative Boolean patterns in the fixture corpus, rather than making an unmeasured rewrite.
- Keep Boolean confidence separate from behavioral categorization and preserve explanatory evidence for every score contribution.
- Do not contact an AI provider during ordinary hunts.

### Conversational intent and targeted pass

- Maintain a short in-memory conversation scoped to the active BinaryView so follow-ups such as “only purchase validation” can refer to the preceding request.
- Use BoolHunter's existing configurable OpenAI-compatible provider to convert a user message into a validated, constrained action plan (for example: topic `purchase`, scope `whole_binary`, mode `targeted_deep_scan`). A malformed or ambiguous plan must not launch an unbounded scan; ask for clarification or report the issue.
- The deterministic executor triages all eligible functions using bounded, inexpensive information such as symbols, strings, return/type signals, calls, and caller/callee context. It performs deeper IL/data-flow analysis only on candidates relevant to both Boolean behavior and the requested topic.
- For purchase-focused requests, broaden deterministic topic signals beyond the current category labels to include terms and evidence for receipts, entitlements, store APIs, transactions, in-app purchases/products/SKUs, billing, orders, subscriptions, checkout, carts, and payment/verification flows. Look at bounded symbol names, string constants, imported/called APIs, and relevant caller/callee or local data-flow context. These topic matches prioritize/select candidates; they do not independently increase Boolean confidence.
- Include positive and negative examples in the regression corpus to distinguish commerce concepts from unrelated names such as generic state restoration or generic store operations.
- Report functions considered, candidates deeply analyzed, matches returned, elapsed time, and whether the pass completed or was cancelled/limited. The UI must not label an incomplete pass as complete.
- Keep provider requests bounded to intent/context needed for a plan. Do not send the whole binary or every function's pseudocode. Treat all binary-derived text as untrusted input.
- Present matched functions with deterministic evidence and the reason each one matched the requested topic. AI explanations must be visibly distinct from deterministic evidence.

### Performance and resource limits

- The ordinary hunt stays on the fast path and makes zero AI/network calls.
- Deeper analysis is opt-in through user intent, cancellable, and subject to per-function traversal/time bounds.
- Cache function-level deterministic analysis in a bounded, per-session cache keyed by binary/function identity and analysis version; invalidate stale entries when code identity or analysis version changes. Do not persist large analysis blobs to the BNDB in this design.
- **Approved ordinary-hunt performance ceiling:** no more than 10% median runtime regression versus the public-main baseline, measured before/after on the same representative input and environment. The test harness must record the measurements and report the baseline; the threshold is not permission to spend that full budget if a smaller cost is practical.
- Exact targeted-pass time limits and cache size should be set after measuring representative binaries; do not silently invent a hard candidate cap that contradicts whole-binary coverage. If a user or platform limit stops deep analysis, show partial status and counts.

## Technical boundaries and decisions

- Python and Binary Ninja APIs already used by the repository; retain the declared minimum Binary Ninja build (`3500`) unless verified API requirements force a documented change.
- Retain the existing configurable OpenAI-compatible provider; do not switch to Binary Ninja's separate native AI integration in this overhaul.
- Keep provider credentials session-only unless there is a separately approved reason to change storage. Never log credentials or authorization headers.
- No additional runtime Python packages are planned. Tests should use Python's standard `unittest` unless the repository demonstrates a strong reason otherwise.
- Binary Ninja is not installed in the implementation sandbox. Pure logic and API-boundary tests can run there; final UI/native-API behavior will require a host Binary Ninja validation step.

## Testing strategy and success criteria

1. Establish a baseline with labeled positive and negative fixtures covering current heuristics and newly targeted patterns. Report precision and recall separately; do not disguise a precision/recall tradeoff in a single score.
2. No previously passing labeled Boolean fixture may regress without an explained and approved tradeoff; all negative fixtures must remain in the report so added recall cannot silently mask false positives.
3. A targeted chat plan must visit every eligible function in the cheap whole-binary triage unless the user cancels or an explicit resource limit is hit; outcomes must distinguish complete, cancelled, and partial scans.
4. The same targeted request must not require an LLM call per function. Repeated analysis of unchanged functions should reuse the bounded cache and produce identical deterministic evidence.
5. Purchase-targeted fixtures must cover receipts, entitlements, store APIs, transaction-related strings, and representative negative lookalikes. These terms must not change Boolean confidence unless independent Boolean evidence exists.
6. Invalid model output, prompt-injection-like binary strings, transport failures, and empty provider responses must fail safely with a useful explanation and no unintended binary modification.
7. Ordinary hunts make no AI request and meet the approved ≤10% median regression ceiling on the same representative inputs/environment.
8. Tests and syntax checks run without Binary Ninja where feasible; UI/threading and supported API signatures receive a manual validation on the declared Binary Ninja minimum/target version before release.

## Boundaries

- **Always:** Preserve deterministic evidence; make long analysis cancellable and off the UI thread; bound IL traversal and AI context; validate model plans against a strict schema; state incomplete coverage honestly; keep local Mac files untouched.
- **Ask first:** Adding dependencies; persisting chat or large analysis data; automatic symbol/type/comment edits; changing the minimum Binary Ninja version; changing the selected provider integration or approved performance ceiling.
- **Never:** Send credentials in logs; execute model-generated code; let a model invent addresses/results; claim a partial pass is complete; issue one AI request per function.

## Project structure and commands

Current source modules are `engine.py` (detection), `ai.py` (provider and prompt handling), `main.py` (background tasks), and `ui.py` (sidebar). The public repository currently has no test suite or test command.

Proposed verification after implementation:

- Syntax: `python3 -m py_compile __init__.py ai.py engine.py main.py ui.py`
- Unit/regression tests: `python3 -m unittest discover -s tests -v`
- Binary Ninja integration: manual load and test on the repository's declared minimum version or a documented newer test build; this cannot run in the current sandbox because Binary Ninja is not installed.

## Current findings informing the design

The public `main` branch currently scores explicit Boolean return types, simple 0/1 returns, direct comparison/logical-NOT returns, Boolean-style naming, and conditional caller use. It runs a completeness pass over the remaining functions, but the semantic evidence remains narrow. The optional AI search currently selects from existing results and does not initiate a targeted deeper scan. The repository has no checked-in tests or labeled fixtures. These are observations from public commit `82226d4`, not claims about the user's separate installed copy.

## Validation still required

- Measure ordinary-HUNT median runtime against public-main on the same representative Binary Ninja binary; the approved 10% ceiling is not yet verified.
- The 128-entry per-session analysis-cache bound is provisional until representative Binary Ninja memory/runtime measurements are available.
- The checked-in fixtures verify deterministic positive/negative cases, but do not yet establish real-binary precision/recall.
- Manually validate sidebar behavior, cancellation, BinaryView changes, provider requests, and the declared Binary Ninja minimum (`3500`).
