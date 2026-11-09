# BoolHunter Intent Chat Implementation Plan

> **For agentic workers:** Use the approved design and this plan after `discovery-core` is complete.

**Goal:** Let users ask follow-up requests in natural language and trigger safe targeted scans through BoolHunter's existing provider.

**Architecture:** One provider request turns each message and bounded intent history into a strict `IntentPlan`. A background task validates the plan, runs deterministic discovery, and returns evidence and counts. The UI shows chat, progress, and matching results; function pseudocode never goes to the model.

**Tech Stack:** Existing OpenAI-compatible client, Python standard library, existing PySide6/Binary Ninja UI APIs.

**Spec:** `docs/superpowers/specs/2026-11-09-boolhunter-overhaul-design.md`

## Global Constraints

- Retain declared minimum Binary Ninja build (`3500`) unless verified API requirements force a documented change.
- No additional runtime Python packages are planned.
- Use BoolHunter's existing configurable OpenAI-compatible provider; do not switch to Binary Ninja's native AI integration.
- Keep provider credentials session-only; never log credentials or authorization headers.
- The ordinary hunt makes zero AI/network calls.
- No more than 10% median ordinary-hunt regression versus public-main baseline.
- Keep local Mac files untouched.
- Confirmed `BackgroundTask.cancel()` and `BackgroundTaskThread.finish()` in [Binary Ninja's official plugin API docs](https://api.binary.ninja/binaryninja.plugin-module.html).

## Review Focus

1. Invalid or unsupported model actions: reject before scanning; test `test_reject_unknown_action_and_extra_keys`.
2. Empty or malformed provider responses: show a useful error and start no scan; test `test_empty_provider_content_raises_safe_error`.
3. Binary-derived strings or results: never send them in intent prompts; test `test_intent_prompt_omits_binary_context`.
4. Long conversations: send no more than 12 user/assistant intent messages; test `test_history_is_limited_to_12_messages`.
5. Active BinaryView changes or cancellation: cancel the old task and discard stale rows; test task cancellation and manually check tab switching in Binary Ninja.

---

### Task 1: Add the constrained intent plan

**Files:**
- Modify: `ai.py`
- Create: `tests/test_intent_plan.py`

**Interfaces:**
- Add frozen `IntentPlan(action: str, topic: str, terms: Tuple[str, ...], reply: str)`.
- Add `build_intent_messages(query: str, history: Sequence[Dict[str, str]]) -> List[Dict[str, str]]`.
- Add `parse_intent_plan(response: str) -> IntentPlan`; allowed actions: `targeted_scan`, `clarify`.
- Require exact JSON keys `action`, `topic`, `terms`, `reply`; cap topic at 80 characters, terms at 16 items/64 characters each, reply at 400 characters, and history at 12 user/assistant intent messages.

- [x] Add `test_parse_valid_targeted_scan_plan`, `test_parse_clarify_plan`, `test_reject_invalid_json`, `test_reject_unknown_action_and_extra_keys`, and `test_reject_oversized_terms`.
- [x] Add `test_history_is_limited_to_12_messages` and `test_intent_prompt_omits_binary_context`.
- [x] Run new plan tests before implementation; they exposed the missing intent-plan API.
- [x] Implement intent prompt construction and strict parsing in `ai.py`; reject malformed output with `AIAnalystError`.
- [x] Add `test_empty_provider_content_raises_safe_error` for the existing client response parser; show a useful error and never start a scan.
- [x] Re-run unit tests and `python3 -m py_compile __init__.py ai.py engine.py main.py ui.py`.

### Task 2: Connect intent plans to discovery and chat UI

**Files:**
- Modify: `main.py`
- Modify: `ui.py`
- Create: `tests/test_intent_task.py`

**Interfaces:**
- Add `AIChatResult(plan: IntentPlan, scan: Optional[TargetedScanResult])`.
- Add `AIChatTask(engine: BoolHunterEngine, query: str, history: Sequence[Dict[str, str]], config: AIProviderConfig, on_progress: Callable[[str, int, int, int], None], on_complete: Callable[[Optional[AIChatResult], Optional[str], bool], None], client_factory: Callable = OpenAICompatibleClient)`.
- `on_progress` receives `(phase, considered, total, deeply_analyzed)`; `on_complete` receives `(result, error, cancelled)`.
- `AIChatTask` sends one intent request; `clarify` starts no scan; `targeted_scan` calls `engine.analyze_targeted(...)` with task cancellation and progress callbacks.

- [x] Add `test_chat_task_targeted_plan_scans_once`, `test_chat_task_clarify_does_not_scan`, `test_malformed_plan_does_not_scan`, and `test_cancelled_scan_returns_partial_status` using fake provider and engine.
- [x] Implement `AIChatTask` as a cancellable `BackgroundTaskThread`; call `finish()` on every exit path.
- [x] Keep one `BoolHunterEngine` on the sidebar widget; pass it to `HunterTask` and `AIChatTask` so its cache is reused; replace it when the active BinaryView changes.
- [x] Replace one-shot AI Search controls with transcript, message field, send, cancel, and clear-chat controls. Preserve provider settings and selected-result analysis.
- [x] Keep the displayed transcript separate from intent history. Intent history contains only user text and validated plan replies; never append function names, addresses, or result details.
- [x] Display AI reply, deterministic match evidence, counts, and complete/partial/cancelled state separately. Keep table navigation behavior.
- [x] Cancel an in-flight chat task when the active BinaryView changes; discard any late callback from the old view.
- [x] Route all UI updates through `execute_on_main_thread`; ignore stale task callbacks.
- [x] Run unit tests and syntax checks: 45 tests pass; Python compilation and `git diff --check` pass.
- [ ] In Binary Ninja, manually test configure/send, purchase query, clarification, cancellation, tab switch, and ordinary HUNT without a provider call. Not run: this sandbox has no Binary Ninja or PySide6 installation.

### Task 3: Document the rebuilt workflow

**Files:**
- Modify: `README.md`

- [x] Document provider setup, conversational requests, targeted-scan coverage/progress, cancellation, session-only credentials, and bounded data sent to the provider.
- [x] State that this GitHub-based rebuild does not add the separate locally installed “Test connection” control; document errors from actual chat requests instead.
- [x] Run `git diff --check` and verify every README claim matches the implementation.
