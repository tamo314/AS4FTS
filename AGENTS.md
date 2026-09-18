# AS4FTS agent instructions

## Mission
Run hypothesis/design -> implement once -> ALL planned parameter combinations ->
evaluate the entire strategy family -> next strategy. Optimize time and cost to
useful backtest evidence, not the number of documents or approvals.

## Research work
- Read the current task, `docs/research/QUICKSTART.md`, and the generated component
  catalog. Read infrastructure documentation only for the code being changed.
- Design a finite parameter space with values, inclusive ranges and conditional
  variants. Implement a parameterized factory ONCE, not one file per combination.
- Run the whole declared space. Never silently sample, prune, narrow, or report a
  partially executed space as complete. A resource interruption pauses the batch;
  resume the remaining trials under the same experiment definition.
- Do not add hypothesis/design approvals, whole-dataset audits, full-suite/lint
  prerequisites, or agent committees before ordinary strategy backtests.
- Record assumptions and execute. Review results after the batch. Runtime errors
  get bounded repairs; economic/rule changes become a new family revision.
- Reuse `src/n225m_bt/components/` and existing strategies before implementing a
  new primitive. Put reusable additions there immediately, with `@component`
  metadata and a docstring. Catalog generation is discovery, not approval.
- Strategies live in the shared source tree. Runs contain reproducibility
  snapshots, NOT independent copies that must be reimplemented next time.
- Keep all parameter results, including failures and negative/zero-trade results.
  Treat reused validation periods as observed, not untouched holdouts.

## Small execution boundaries
Do not modify or commit raw/licensed market data, local credentials, agent logs,
or generated results. Do not connect to brokers or place live orders. Preserve
bar-close / next-eligible-open causality and explicit transaction costs.
Do not bypass the user's CLI permission configuration. Local Python plugins are
trusted code, not an OS sandbox; use an isolated account/container when needed.

## Shared engine changes
Use targeted tests for modified economics/time behavior. Keep existing one-lot
semantics unless a task explicitly adds a capability. These are current engine
capabilities, not permanent bans on future research. Put unrelated infrastructure
work on a separate task; it must not become a prerequisite for all strategies.

## Definition of a research result
A parameter batch is recorded with explicit coverage, parameters, code/data IDs,
metrics and errors; its summary and refreshed component catalog are available to
the next designer. Profitability is not a completion criterion.
