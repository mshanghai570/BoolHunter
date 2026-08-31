# BoolHunter

BoolHunter is a Binary Ninja plugin that identifies Boolean-returning functions using weighted heuristics.

## Features
- **IL-Aware**: Analyzes High-Level IL for comparisons and constant returns.
- **Context-Aware**: Checks if callers use the return value in conditional branches.
- **Objective-C Support**: Automatically identifies common Boolean selector patterns.
- **Confidence Scoring**: Each function is assigned a 0-100% score with detailed evidence.
- **Behavioral Categories**: Results are labeled using conservative function-name heuristics, including Purchases, Authentication & Security, Network & Communication, Files & Storage, UI & Interaction, Navigation & Location, Media, Validation & State, and Other.

## Installation
1. Copy the `boolhunter` directory into your Binary Ninja `plugins` folder.
2. Restart Binary Ninja.
3. Access via `Plugins -> BoolHunter`.

## Function Categories

Categories are inferred from recognizable words in the function symbol, including common `camelCase`, underscore, Objective-C, and hyphenated naming styles. Purchase-related terms such as `purchase`, `checkout`, `cart`, `order`, `transaction`, `payment`, `billing`, `subscription`, and `receipt` map to **Purchases**. The category is informational only and does not change the Boolean confidence score or result ranking. Search filtering also matches category labels.

## Optional AI Search

After running **HUNT**, configure an OpenAI-compatible provider with **Configure AI...** and enter its base URL, API key, and model name. Then type a conversational request into the **Ask AI** field, such as `find purchase related functions`, `show functions that validate payments`, or another natural-language description, and press **Enter** or select **Ask AI**. BoolHunter sends a bounded list of current candidates containing function names, addresses, categories, and deterministic scores; the provider returns matching candidate addresses, which BoolHunter uses to filter the table.

AI Search is opt-in and runs separately from deterministic analysis. It does not change scores, evidence, categories, or result ranking. Credentials are held only for the current plugin session, and the response is restricted to addresses already present in the candidate list. After a search completes, a dedicated **AI SEARCH RESULTS** panel lists the matched functions, category, score, and address; matched table rows are highlighted and the first match is selected automatically so its full analysis is visible. Use **Clear AI Search** to restore the complete deterministic result set.

Any provider implementing the standard OpenAI-compatible `/v1/chat/completions` request and response format can be used. The Base URL may be entered as the provider root, its `/v1` endpoint, or the complete `/chat/completions` URL.

## Scoring Algorithm
- **Explicit Type**: +60 (e.g., `bool` or `BOOL`)
- **All paths return 0/1**: +35
- **Comparison Return**: +30 (e.g., `return x > y`)
- **Boolean Normalization**: +30 (e.g., `return !!x`)
- **Conditional Callers**: up to +25 (if used in `if/while` statements)
- **Naming Patterns**: +10 to +15 (e.g., `isEnabled`)