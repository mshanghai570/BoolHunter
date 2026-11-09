# BoolHunter

BoolHunter is a Binary Ninja plugin for finding likely Boolean-returning functions with weighted, deterministic heuristics.

## Features

- **Progressive HUNT:** cheap type/name checks prioritize work, then every function receives the ordinary bounded analysis.
- **Multi-signal analysis:** considers Boolean-like return types, constant 0/1 returns, comparisons, logical normalization, conditional caller use, and Boolean-style names.
- **Conversational targeted analysis:** ask for a deeper pass on a topic, such as “Double down on purchase-related booleans.” BoolHunter checks the whole binary, finds topic evidence in function names, callees/API names, and referenced strings, then deeply analyzes matching functions.
- **Purchase vocabulary:** includes receipts, entitlements, StoreKit and App Store APIs, products and product identifiers, SKUs, in-app purchases, subscriptions, transactions, checkout, payments, and billing.
- **Evidence separation:** targeted topic matches are shown separately and do not change Boolean scores or result ranking.
- **Bounded work:** HLIL analysis has per-function size, instruction-count, and time limits. Targeted scans report elapsed time, cancellation, functions that could not be fully analyzed, and failures in string-reference indexing.
- **Click-to-navigate:** select a result to inspect evidence and navigate to its function.

## Installation

Copy the `BoolHunter` plugin folder into Binary Ninja's `plugins` directory, restart Binary Ninja, and open **Plugins → BoolHunter**.

## Use the AI chat

1. Select a BinaryView and open the BoolHunter sidebar.
2. Select **Configure AI...** and enter an OpenAI-compatible base URL, API key, and model name.
3. Enter a request in **Message**, such as “Double down on purchase-related booleans,” then press Enter or **Send**.
4. BoolHunter asks the provider to interpret the request as a bounded action plan. If the request is clear, BoolHunter—not the provider—runs a targeted whole-binary pass. If it is ambiguous, the chat asks a follow-up question.
5. Matching candidates are merged into the results table. Select one to see ordinary Boolean evidence and separate topic-match evidence.

You do not need to run **HUNT** first. Use **Cancel** to stop a targeted scan. An in-flight provider request cannot be interrupted; it must finish or time out before cancellation completes, and BoolHunter will not start the scan afterward. **Clear chat** clears the in-memory conversation context. Chat history is limited to the most recent 12 user/assistant messages, is not saved, and resets when the active BinaryView changes.

The provider receives the current request and bounded chat history for intent planning; it does not receive binary-derived names, strings, pseudocode, scores, or results for chat. The separate **Analyze with AI** action on a selected result does send bounded context for that function, including its name, address, return type, deterministic evidence, available HLIL/pseudocode, and up to 16 caller names and 16 callee names. Both actions are opt-in. Credentials remain in memory for the current plugin session only.

Any provider implementing the standard OpenAI-compatible `/v1/chat/completions` request and response format can be used. The Base URL may be entered as the provider root, its `/v1` endpoint, or the complete `/chat/completions` URL.

This GitHub-based rebuild has no separate **Test connection** button. Provider errors appear when a real chat request runs.

## Categories and scoring

Categories are inferred conservatively from recognizable function-name terms. Purchase-related names may be labeled **Purchases**. Categories are informational and do not change the Boolean score.

The score is a heuristic ranking signal, not a calibrated probability:

- **Explicit Boolean return type:** +60
- **All return paths produce 0 or 1:** +35
- **Comparison return:** +30
- **Logical normalization:** +30
- **Conditional caller use:** up to +25
- **Boolean-style naming:** +10 to +15

Targeted analysis can add deterministic evidence for a return value masked to a single bit. Topic relevance remains separate from the score.

## Development tests

Run the unit suite outside Binary Ninja with:

```bash
python3 -m unittest discover -s tests -v
```

The suite uses a test-only Binary Ninja stub. It does not replace validation in Binary Ninja itself; compare ordinary-HUNT time on representative binaries before and after changes in the host application.
