# Bangladesh Import Dependency & Value-Added Analysis

An end-to-end analytics pipeline on **AWS** quantifying how dependent Bangladesh's
ready-made garment (RMG) export engine is on **imported inputs** — cotton, yarn,
and man-made fibres — and how much value the country adds per export dollar.

> **Status:** 🚧 In progress. Building one milestone per day (see commit history).

## The business questions

1. **Supplier concentration** — how reliant is Bangladesh on a few countries (China, India) for textile inputs, and is it diversifying? *(Herfindahl-Hirschman Index)*
2. **Import bill trend** — which import categories (textile inputs, machinery, fuel) drive growth?
3. **Value-added ratio (headline)** — cents of imported textile input behind each dollar of apparel exports, trended over time.
4. **Price vs. volume** — is the cotton import bill rising because Bangladesh buys *more* or pays *more* per kg?
5. **Supplier leaderboard** — year-over-year share shifts by partner country.
6. **Seasonality** — do input imports lead export peaks?

## Architecture

_(diagram added on Day 7 — `docs/architecture.png`)_

```
UN Comtrade API
      │  (Lambda, scheduled via EventBridge)
      ▼
S3  raw/    ── raw JSON, source of truth, never edited
      │  (Python transform → Parquet, partitioned by year)
      ▼
S3  processed/  ── cleaned Parquet
      │
      ▼
Glue Data Catalog (manual DDL)  ──►  Athena (SQL analysis)  ──►  QuickSight (dashboard)
                                              │
                                              ▼
                                    GenAI executive trade brief (LLM)
```

**Design choices (the "why"):**
- **S3 + Glue + Athena instead of Redshift** — a serverless *data-lake* pattern: pay only per query, no cluster to run, free-tier friendly.
- **Parquet, partitioned by year** — columnar + partition pruning slashes the bytes Athena scans (cost is per-byte-scanned).
- **SSM Parameter Store, not Secrets Manager** — free vs. per-secret monthly cost.

## Repo layout

| Folder | Contents |
|---|---|
| `scripts/` | Day 0 data-coverage verification |
| `ingestion/` | Lambda ingestion code + deploy script |
| `transform/` | Raw JSON → cleaned Parquet |
| `sql/` | Glue DDL + Athena analysis queries |
| `genai/` | LLM trade-brief generator |
| `docs/` | Architecture diagram, screenshots |

## Data source

[UN Comtrade](https://comtradeplus.un.org/) — official international trade statistics.
Reporter: **Bangladesh (code 50)**. See `.env.example` for the required API key.

## Findings & cost

_(populated as the project progresses)_

## Limitations

_(reporter-vs-mirror data caveat, provisional-month handling — documented on Day 4+)_
