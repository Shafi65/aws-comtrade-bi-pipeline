"""
Data-contract tests over the five extracted interim CSVs (data/interim/).

WHY this layer exists (vs the unit tests, vs reconciliation)
------------------------------------------------------------
Reconciliation (built into the extractors) proves the NUMBERS tie to BBS's own
published totals at extraction time. The unit tests (test_pdf_parser.py) pin the
parsing FUNCTIONS. Neither states what the OUTPUT FILES promise to downstream
consumers. These tests are that promise — the structural contract M3 (clean/dims/
Parquet) is allowed to build on: exact schema, valid domains, declared grain,
non-negative measures, and an explicit, quantified record of the known residual
issues (documented in docs/DATA_ISSUES.md) so a re-extraction that silently
changes the data trips a test instead of surprising M3.

Several tests are SNAPSHOT tests (exact row counts, exact duplicate counts).
That is deliberate: extraction is a one-time historical backfill, so the outputs
should be frozen. If you legitimately re-extract (e.g. after a parser fix),
re-profile and update the snapshots — the failure is the alert, not the verdict.

Run:    ./.venv/bin/python -m pytest tests/test_extracted_data.py -v
(Files are git-ignored; tests skip per-year if a CSV is absent.)
"""

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
INTERIM = ROOT / "data" / "interim"

# The declared schema — column names AND order, as written by both extractors.
EXPECTED_COLUMNS = ["flow", "fy", "half", "hs8", "country_code",
                    "country_name", "unit", "quantity", "value_bdt"]

# The declared grain: one row = one (flow, fy, half, product, destination, unit).
GRAIN = ["flow", "fy", "half", "hs8", "country_code", "unit"]

# Snapshot of the frozen M1/M2 outputs (profiled 2026-07-14, post-reconciliation).
EXPECTED_ROWS = {
    "2020-21": 145_343,
    "2021-22": 143_371,
    "2022-23": 139_872,
    "2023-24": 141_434,
    "2024-25": 135_717,
}

# Duplicate-grain-key snapshot: rows sharing a grain key (all occurrences counted).
# These are legitimate finer-than-HS8 line items in the SOURCE that collapse to the
# same HS8 — NOT parser double-counts (values reconcile; no two rows are identical).
EXPECTED_DUP_KEY_ROWS = {
    "2020-21": 0,
    "2021-22": 0,
    "2022-23": 0,
    "2023-24": 70,      # all exports
    "2024-25": 1_598,   # all imports
}

FISCAL_YEARS = list(EXPECTED_ROWS)


@pytest.fixture(scope="module", params=FISCAL_YEARS)
def year_df(request):
    """One (fy, DataFrame) per fiscal year; skips cleanly if the CSV is absent.

    module-scoped + params: each CSV is read ONCE and shared across all tests,
    instead of once per test. hs8/country_code are read as strings — they are
    CODES (leading zeros matter), and letting pandas infer them as ints is
    exactly the bug the extractors' zfill exists to prevent.
    """
    fy = request.param
    path = INTERIM / f"fts_{fy}_facts.csv"
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} not present — run the extractors first")
    return fy, pd.read_csv(path, dtype={"hs8": str, "country_code": str})


class TestSchemaContract:
    def test_exact_columns(self, year_df):
        _, df = year_df
        assert list(df.columns) == EXPECTED_COLUMNS

    def test_row_count_snapshot(self, year_df):
        fy, df = year_df
        assert len(df) == EXPECTED_ROWS[fy], (
            f"{fy}: row count changed from the frozen extraction snapshot — "
            "if you re-extracted intentionally, re-profile and update EXPECTED_ROWS"
        )

    def test_fy_column_matches_filename(self, year_df):
        fy, df = year_df
        assert (df["fy"] == fy).all()


class TestDomains:
    def test_flow_domain(self, year_df):
        _, df = year_df
        assert set(df["flow"].unique()) <= {"X", "M"}

    def test_half_domain(self, year_df):
        _, df = year_df
        assert set(df["half"].unique()) <= {"H1", "H2"}

    def test_hs8_is_eight_digits(self, year_df):
        # Zero-padding is a known landmine (Excel strips leading zeros); every
        # code must be exactly 8 digit characters, or HS2/HS4 rollups misfile.
        _, df = year_df
        bad = df[~df["hs8"].str.fullmatch(r"\d{8}")]
        assert bad.empty, f"non-8-digit hs8 values: {bad['hs8'].unique()[:10]}"

    def test_no_unknown_hs8(self, year_df):
        # UNKNOWN products would be unanalyzable (no chapter, no price series).
        # The extractors only emit hs8=UNKNOWN for import rows whose commodity
        # label was lost — and none survived into the final outputs.
        _, df = year_df
        assert (df["hs8"] == "UNKNOWN").sum() == 0


class TestMeasures:
    def test_no_negative_quantity_or_value(self, year_df):
        _, df = year_df
        assert (df["quantity"] < 0).sum() == 0
        assert (df["value_bdt"] < 0).sum() == 0

    def test_no_null_keys_or_measures(self, year_df):
        # `unit` is legitimately nullable (some commodities carry none);
        # everything else that identifies or measures a fact must be present.
        _, df = year_df
        for col in ["flow", "fy", "half", "hs8", "country_code",
                    "quantity", "value_bdt"]:
            assert df[col].notna().all(), f"null values in {col}"

    def test_export_unit_price_coverage(self, year_df):
        # The headline questions need unit price = value / quantity, which only
        # exists where quantity > 0 and a unit is set. Profiled at 99.1-99.7%
        # per year; guard the floor so a regression in unit parsing shows up.
        _, df = year_df
        exp = df[df["flow"] == "X"]
        usable = exp[(exp["quantity"] > 0) & exp["unit"].notna()]
        assert len(usable) / len(exp) >= 0.99


class TestKnownResiduals:
    """The issues extraction knowingly hands to M3 — asserted, not hidden."""

    def test_unknown_destinations_confined_and_bounded(self, year_df):
        # PDF text extraction dropped the code+name on some 2023-24 export
        # detail lines; the 6 numbers survived, so the VALUE was kept and only
        # the destination label was lost. Contract: this occurs ONLY in
        # 2023-24, ONLY in exports, and stays immaterial (<0.05% of export
        # value; actual ~0.008%).
        fy, df = year_df
        unk = df[df["country_code"] == "UNKNOWN"]
        if fy != "2023-24":
            assert unk.empty, f"{fy}: UNKNOWN destinations expected only in 2023-24"
            return
        assert len(unk) == 141
        assert set(unk["flow"].unique()) == {"X"}
        export_value = df.loc[df["flow"] == "X", "value_bdt"].sum()
        assert unk["value_bdt"].sum() / export_value < 0.0005

    def test_duplicate_grain_keys_documented_not_corrupt(self, year_df):
        # Some source line items are FINER than HS8 (sub-codes / repeated
        # commodity sections) and collapse to the same grain key. They are
        # legitimate — each carries its own quantity+value and the totals
        # reconcile to BBS — but they mean the interim files' grain is NOT yet
        # unique. M3 MUST aggregate on the grain (GROUP BY flow, fy, half,
        # hs8, country_code, unit and SUM quantity/value) before building the
        # fact table; do NOT de-duplicate/drop, that would lose real value.
        fy, df = year_df
        dup_rows = df[df.duplicated(GRAIN, keep=False)]
        assert len(dup_rows) == EXPECTED_DUP_KEY_ROWS[fy], (
            f"{fy}: duplicate-grain-key rows changed "
            f"({len(dup_rows)} vs expected {EXPECTED_DUP_KEY_ROWS[fy]}). "
            "M3 must aggregate on the grain; re-profile before updating."
        )
        # None may be FULLY identical rows — that would be parser double-
        # counting (corruption), not sub-HS8 line items (a modeling task).
        assert df.duplicated().sum() == 0, (
            f"{fy}: fully identical rows found — parser double-count, "
            "not a legitimate sub-HS8 line item. Fix extraction, don't aggregate."
        )
