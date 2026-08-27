# BoolHunter

BoolHunter is a Binary Ninja plugin that identifies Boolean-returning functions using weighted heuristics.

## Features
- **IL-Aware**: Analyzes High-Level IL for comparisons and constant returns.
- **Context-Aware**: Checks if callers use the return value in conditional branches.
- **Objective-C Support**: Automatically identifies common Boolean selector patterns.
- **Confidence Scoring**: Each function is assigned a 0-100% score with detailed evidence.

## Installation
1. Copy the `boolhunter` directory into your Binary Ninja `plugins` folder.
2. Restart Binary Ninja.
3. Access via `Plugins -> BoolHunter`.

## Scoring Algorithm
- **Explicit Type**: +60 (e.g., `bool` or `BOOL`)
- **All paths return 0/1**: +35
- **Comparison Return**: +30 (e.g., `return x > y`)
- **Boolean Normalization**: +30 (e.g., `return !!x`)
- **Conditional Callers**: up to +25 (if used in `if/while` statements)
- **Naming Patterns**: +10 to +15 (e.g., `isEnabled`)