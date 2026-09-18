Implement the supplied strategy family ONCE for ALL declared parameter combinations.
Use existing shared components first; consult the catalog and relevant source only.
Do not redesign the hypothesis, narrow the parameter grid, or run a review/audit.
The Python controller will execute all cases and evaluate them after implementation.

Return ONLY JSON: {"files":[{"path":"src/n225m_bt/...py","content":"complete UTF-8 file"}],
"uses":["component_id"],"note":"brief implementation note"}.
An empty files array is valid when the factory already exists. Do not edit files
using agent tools: return complete file contents for the controller to apply.
Allowed paths: src/n225m_bt/components/ and src/n225m_bt/strategies/ only.

Reusable logic belongs directly in components, with a literal @component(id=...,
kind=...,summary=...,tags=[...],uses=[...]) decorator and a useful API docstring.
A strategy module exposes create_strategy(parameters: dict) returning a fresh
Strategy. on_bar(ctx, bar) sees only available history and returns Signal or None.
Do not use module-global mutable trading state. Keep features causal and bounded.
Stop/target anchors must be explicit. Preserve the engine's next-bar execution and
transaction costs. New shared code is retained for future families, not copied into
run-specific folders. Existing shared interfaces should remain compatible.

For execution errors, repair the shared implementation with the smallest practical
change. Do not fit parameters until the backtest becomes profitable. Do not run full
lint/test suites as a prerequisite, modify raw data, invoke brokers, or change the
engine to hide an error. Required engine extensions must be reported as unsupported.
