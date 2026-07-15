# How This Pipeline Is Tested

Extraction here has one dominant failure mode: it fails *silently*. A misread column,
a skipped line, a wrong file — all still produce plausible-looking numbers. So the
project defends itself in three layers, each catching what the others can't.

## Layer 0: reconciliation (built into the extractors)

Every extraction run must sum back to the totals BBS itself published — the grand
total, the per-chapter totals from an independent summary table, and every product's
own printed subtotal — within 0.1%, for value *and* quantity. This is the gate that
decides whether the data deserves to exist (see `docs/DECISIONS.md`).

Reconciliation is the strongest check, but it has two limits. It only runs when the
extraction runs (the PDF years take ~10 minutes to parse), and when it fails it tells
you the totals no longer tie — not *which function* broke. The test suite fills both
gaps.

## Layer 1: unit tests on the pure parsing functions — `tests/test_pdf_parser.py`

The extractors' hard-won logic lives in small pure functions: turning a PDF text line
into tokens (`split_row`), splitting a glued unit off a description (`parse_unit`),
resolving a dotted filename (`resolve`), reading the chapter answer key
(`parse_table01`). Each of these encodes the fix for a real bug that reconciliation
caught during M2 — and a future "cleanup" could quietly undo any of them.

These tests pin each function with hand-written inputs, so they run in milliseconds
with no PDFs, no CSVs, and no re-extraction. The most important ones are **regression
tests named after the bug they guard**:

- a scientific-notation value token (`3.06704E+11`) must be accepted as a number, not
  rejected as junk — rejecting it once silently dropped country headers and
  misattributed entire countries' imports;
- `resolve("Volume2.2")` must find `Volume2.2.pdf` by appending text, because
  `Path.with_suffix` rewrites the name to `Volume2.pdf` — a *different volume* — and
  once made every import run silently re-parse exports;
- a chapter row with a page footer glued onto it must be read by the publication's own
  invariant (H1 + H2 == full year), not by trusting the last token — the naive read
  once corrupted the *answer key* itself, failing a reconciliation whose data was exact.

If one of these tests fails, someone has re-introduced a known bug; the test message
says which one and why it matters.

## Layer 2: data-contract tests on the outputs — `tests/test_extracted_data.py`

Reconciliation proves the numbers; unit tests prove the functions. Neither states
what the five interim CSVs *promise* to the next milestone. The contract tests do,
parametrized across all five fiscal years:

- **Structure:** exact column set and order; `fy` matches the filename.
- **Domains:** `flow` ∈ {X, M}; `half` ∈ {H1, H2}; every `hs8` is exactly 8 digits
  (zero-padding is a known landmine); no `UNKNOWN` products.
- **Integrity:** no negative quantities or values; no nulls in keys or measures;
  export unit-price coverage (qty > 0 and unit set) stays ≥ 99%.
- **Known residuals, asserted rather than hidden:** the 141 `UNKNOWN`-destination
  rows exist only in 2023-24 exports and stay under 0.05% of export value; the
  duplicate-grain-key rows exist only where profiled (70 in 2023-24, 1,598 in
  2024-25) and none are fully identical — the test message states the consequence
  explicitly: *M3 must aggregate on the grain.* Full detail in
  `docs/DATA_ISSUES.md`.

Row counts and duplicate counts are exact **snapshots** on purpose: extraction is a
one-time historical backfill, so the outputs should be frozen. A snapshot failure
means the data changed — usually a deliberate re-extraction, in which case you
re-profile and update the snapshot; the failure is the alert, not the verdict.

## Running the tests

```bash
# everything (fast: ~2 seconds, no PDFs parsed)
./.venv/bin/python -m pytest tests/

# just the parser unit tests / just the data contracts
./.venv/bin/python -m pytest tests/test_pdf_parser.py -v
./.venv/bin/python -m pytest tests/test_extracted_data.py -v
```

The data tests read the git-ignored CSVs in `data/interim/` and skip per-year if a
file is absent (fresh clones without the source data still get the unit tests).
`tests/conftest.py` puts `ingestion/` on `sys.path` so the test files import the
extractor modules the same way the extractors import each other.

## What is deliberately *not* tested here

The end-to-end extraction (PDF in, CSV out) is exercised by the extractors' own
reconciliation, not duplicated in pytest — re-parsing thousand-page PDFs on every
test run would make the suite too slow to be run habitually, and the reconciliation
already checks that path against a stronger oracle (BBS's own totals) than any
fixture we could write.
