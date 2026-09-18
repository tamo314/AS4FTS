# N225M backtesting platform

Research-grade, deterministic one-minute Nikkei 225 mini futures backtesting.

## Strategy-family research (AS4FTS)

One loop = hypothesis/design + one parameterized implementation + the **entire declared parameter space** + family-level evaluation. Shared components accumulate across loops and are automatically cataloged for the next designer.

```powershell
uv sync --group dev
uv run python -m n225m_bt.research dataset-register demo --synthetic-days 3
uv run python -m n225m_bt.research run examples/research/breakout.yaml --workers 2
uv run python -m n225m_bt.research catalog
```

The example runs 48 synthetic-data cases, not a claim of profitable trading. Read [the Japanese quickstart](docs/research/QUICKSTART.md), [implementation plan](docs/research/IMPLEMENTATION_PLAN.md), and [validation scope](docs/research/VALIDATION.md).

Copy `config/research_agents.example.yaml` to `config/research_agents.local.yaml`, choose already configured CLI commands/models, then run:

```powershell
uv run python -m n225m_bt.research loop --config config/research_agents.local.yaml
```

The research module is the new entry point. The original `n225m-bt backtest run` below remains an always-flat baseline, not the strategy-family runner. No agent installation/login or pre-backtest hypothesis/design approval is part of ordinary research.

## Original platform commands

```powershell
python -m pip install -e .
pytest
ruff check .
ruff format --check .
mypy
n225m-bt --help
```

Use `uv sync --group dev` for the development tools above. Actual 225Labo files remain local under `data/raw/` and are never read directly by the backtest engine.

## Local-data onboarding

Inspect a downloaded file first. The adapter reports its detected encoding,
delimiter, headers, and candidate mapping without modifying the file.

```powershell
n225m-bt data inspect data/raw/225labo/center/N225minif_2024.xlsx
n225m-bt data build-calendar `
  --source-root data/raw/225labo/center `
  --source-root data/raw/225labo/forward `
  --output config/local_calendar.yaml
n225m-bt data ingest data/raw/225labo/center/N225minif_2024.xlsx `
  --calendar-override config/local_calendar.yaml
n225m-bt backtest run `
  --calendar-override config/local_calendar.yaml `
  --run-id research-2024-baseline
```

`data build-calendar` reads only the date column of all supplied local source
files and writes a local YAML calendar. It never changes `data/raw/`; the
generated `config/local_calendar.yaml` is ignored by Git.

For the 225Labo forward/next-continuous series, retain a separate dataset
namespace and series label:

```powershell
n225m-bt data ingest data/raw/225labo/forward/N225minif_2024_Forward.xlsx `
  --calendar-override config/local_calendar.yaml `
  --dataset forward `
  --series-type next_continuous
```

For night-session data, provide the explicit OSE calendar to both ingest and
backtest commands. The platform never derives an evening calendar date through
a simple one-day subtraction. A conflicting duplicate timestamp or incomplete
calendar mapping is preserved in the quality report and blocks strict Gold
generation rather than being silently repaired.
