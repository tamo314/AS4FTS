# N225M backtesting platform

Research-grade, deterministic one-minute Nikkei 225 mini futures backtesting.

```powershell
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
mypy
n225m-bt --help
```

Actual 225Labo files remain local under `data/raw/` and are never read directly
by the backtest engine.

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
