# Open specification items

The following items are intentionally represented as explicit configuration,
quality state, or TODOs. They do not block Phases 0--8.

| Item | Treatment |
|---|---|
| Complete OSE trading-day/holiday calendar | A user-supplied CSV/YAML override is supported. Missing mappings fail normalization instead of assuming Japanese bank holidays. |
| 225Labo CSV headers and date/time representation | The adapter detects encoding, delimiter, headers, and candidate mappings; unresolved required columns fail with candidates. |
| Precise historic auction record convention | Session boundaries are classification rules; expected-minute checks do not invent bars. Fine-grained historic auction definitions remain TODO. |
| Center-series rollover/SQ definition | `roll_risk` is a conservative, injectable marker. No contract code or fabricated contract month is inferred. |
| Stop execution rule beyond V1 stop-market default | V1 uses adverse stop-market behaviour and exposes the policy in configuration. |
| Exact treatment of an entry on force-flat cutoff | V1 cancels new entries at the cutoff and queues a forced exit on the next eligible observed bar. |
