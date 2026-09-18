# User Data Placement

Do not commit downloaded market data.

Suggested local layout:

```text
data/raw/225labo/
  center/
    2020/
    2021/
    2021/
    2022/
    2023/
    2024/
    2025/
    2026/
  forward/
    2020/
    ...
```

After placing a file locally:

```bash
n225m-bt data inspect <path-to-file>
```

Use the inspection output to confirm encoding, header and source mapping before running full ingestion.

This package intentionally contains no 225Labo data rows because the provider prohibits redistribution/third-party provision of downloaded data.
