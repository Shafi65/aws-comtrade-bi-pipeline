# Known Data Issues — Read Before M3

Every issue that exists in the extracted interim data (`data/interim/fts_*_facts.csv`),
what it costs, and who owns the fix. All eight year-flows reconcile to BBS's published
totals — nothing here changes that. But "reconciled" is not "modeled": some issues were
resolved during extraction, and some are deliberately handed to M3. This page is the
handoff list, so nothing gets rediscovered as a surprise.

Numbers below were re-verified against the CSVs on 2026-07-14 (not just carried
forward from the extraction logs), and the open ones are pinned by
`tests/test_extracted_data.py` so they can't drift silently.

---

## Open — M3 must handle these

### 1. Duplicate grain keys: the fact-table grain is not yet unique (the main M3 action)

**What.** The declared grain is one row = (flow, fy, half, hs8, country_code, unit) —
but some source line items are *finer* than HS8 (sub-codes or repeated commodity
sections in the publication) and collapse to the same HS8 when padded. Result: rows
that share a grain key but each carry their own quantity and value.

**Scale.** Exactly two years are affected:

| Year | Rows sharing a key | Distinct keys | Where | Share of file value |
|---|---|---|---|---|
| 2023-24 | 70 | 35 | all exports | 0.11% |
| 2024-25 | 1,598 | 799 | all imports | 1.19% |
| other three years | 0 | — | — | — |

**Why it's not corruption.** No two rows are fully identical (verified: zero exact
duplicates in any file), and every affected year still reconciles to BBS's totals at
grand, chapter, and product level — so these are legitimate line items, not parser
double-counts. A parser bug would duplicate *identical* rows; these differ in their
measures.

**M3 action.** `GROUP BY` the grain and `SUM(quantity), SUM(value_bdt)` when building
`fact_trade`. Do **not** de-duplicate or drop — that would delete real trade value.
Aggregation is lossless here because the collapsing rows share the same unit. After
this, assert the grain is unique (it becomes the fact table's key).

### 2. `UNKNOWN` destinations: 141 rows where the label was lost but the value kept

**What.** In the 2023-24 export PDF, text extraction occasionally dropped a detail
row's leading `code name`, leaving six bare numbers. The parser keeps such a row under
its current commodity header — the product, value, and chapter are all still correct —
and marks only the unrecoverable destination as `UNKNOWN`.

**Scale.** 141 rows, *only* in 2023-24, *only* exports: ৳517.5M ≈ **0.008%** of that
year's export value. Zero in all other files.

**M3 action.** Keep the rows (they carry reconciled value); give `dim_country` an
explicit "Unknown" member rather than a null. Downstream, question 3 (per-destination
deviation) should exclude them — 0.008% cannot move any result, but an "UNKNOWN"
destination in a dashboard needs a footnote, not an apology.

### 3. Quantity-zero rows: value without a unit price

**What.** Some rows report value but zero quantity (and some commodities carry no
unit at all), so unit price = value/quantity does not exist for them. Export rows
usable for unit price (qty > 0 **and** unit set) are 99.1–99.7% per year.

**Scale (exports).** qty=0 rows: 111 (2020-21), 72 (2021-22), 118 (2022-23),
337 (2023-24), 255 (2024-25) — at most **0.003%** of any year's export value.

**M3/M5 action.** Keep them in the fact table (they belong in value totals and
diversification counts); the price *views* filter `quantity > 0 AND unit IS NOT NULL`.
This is exactly why unit price lives in SQL views, not in the fact table.

### 4. One HS8 in 2022-23 exports where parent ≠ children

**What.** The finest reconciliation check (each commodity's printed subtotal vs the
sum of its country rows) passes 1,535 of 1,536 commodities in 2022-23 exports; one
HS8 disagrees. Grand-total, chapter-level, and Table 01 checks all still pass, so the
discrepancy nets out and is confined to that single product's country split.

**M3 action.** Nothing structural — but exclude (or footnote) that product if it ever
surfaces in a per-destination result for 2022-23. Known blemish, stated honestly.

### 5. No FX yet: "price improvement" is still entangled with the taka

**What.** All values are BDT, and the taka fell from ~85 to ~120 per USD across the
window (~30%). In taka, almost everything looks like a price improvement.

**M3 action.** Build `dim_fx_rate` (Bangladesh Bank rate per fiscal half) and expose
every price in BDT *and* USD. Until this exists, no trend conclusion from this data
is meaningful. This is the analytical blocker, not a cosmetic one.

### 6. `country_name` still denormalized inline

**What.** The interim CSVs repeat the country name on every row (readability during
extraction), and spellings drift across years ("UNTD ARAB EM" etc.). A handful of
countries have *no numeric code* in the source (e.g. WEST.SAHARA) and are keyed by
name.

**M3 action.** Split out `dim_country` (one authoritative name per code, name-keyed
countries assigned stable surrogate codes) and drop `country_name` from the fact
table. Same for `dim_hs` from the commodity descriptions.

---

## Closed — fixed during M2, listed so they don't get rediscovered

These four were *source-level* defects, each caught by reconciliation, diagnosed, and
fixed in the extractor (details and the debugging story: `docs/DECISIONS.md`, "When
the source contradicts itself"). They need no M3 work.

1. **Scientific-notation tokens.** Sections of the older import PDFs render big
   numbers as `1.04518E+12`; the parser initially rejected those lines as junk, which
   silently dropped country headers (misattributing whole countries) and detail rows.
   Fixed: the number pattern accepts E-notation. Regression-tested.
2. **2022-23 imports = original + revision concatenated.** The file contains the full
   original print *plus* a re-print of 41 countries with revised numbers. Rule: when a
   section header appears twice, the last print wins — matching BBS's own total to
   +0.0003%.
3. **The 2022-23 India print splice.** India's section was physically interrupted by
   its own revision, with the original's tail misprinted 500 pages later. Repaired by
   config-declared surgery (drop the splice, reattach the tail), arbitrated by
   Table 01: the kept reading matches 97/97 chapter totals.
4. **Older export files omit the ~1,100 smallest commodities.** The 2020-21 → 2022-23
   export Table 04s genuinely lack them; the country-major mirror (Table 05) itemizes
   all of them. Filled *only* the missing codes from Table 05, keeping Table 04 the
   source of record. Nothing was estimated.

---

## The one-line summary for M3

The data is proven against BBS but not yet modeled: **aggregate to the grain, split
out the dimensions, add FX** — everything else above is either already handled or a
footnote-sized residual (< 0.01% of value).
