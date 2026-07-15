"""
Unit tests for the PURE parsing functions behind the M1/M2 extractors.

WHY these tests exist (they are NOT the reconciliation)
--------------------------------------------------------
Reconciliation proves each extraction RUN ties to BBS's published totals — but it
runs only when the 10-minute PDF parse runs, and it can't tell you WHICH function
broke, only that the totals no longer tie. These tests pin the small pure functions
(tokenizing a text line, splitting a glued unit, resolving a dotted filename) with
hand-written inputs, so a future edit that re-introduces a known bug fails in
milliseconds with a pointed message instead of a mysterious 0.4% reconciliation gap.

Several tests are REGRESSION tests for real bugs that reconciliation caught during
M2 (war stories in LEARNING.md). Each one says which bug it guards.

No PDFs, no CSVs, no network: everything here runs on literal strings.

Run:    ./.venv/bin/python -m pytest tests/test_pdf_parser.py -v
"""

from pathlib import Path

import pytest

import extract_fts_pdf as pdf_mod
from extract_fts_excel import num
from extract_fts_pdf import parse_table01, parse_unit, resolve, split_row


# ---------------------------------------------------------------------------
# num() — the shared cell/token -> float coercer (defined in the M1 module,
# reused by the PDF parser: single source of truth).
# ---------------------------------------------------------------------------

class TestNum:
    def test_normal_number(self):
        assert num(1234) == 1234.0
        assert num("1234") == 1234.0
        assert num("3.5") == 3.5

    def test_blank_and_none_mean_zero(self):
        # Empty cells in the source mean "no trade", not "missing data".
        assert num(None) == 0.0
        assert num("") == 0.0

    def test_comma_bearing_string_is_the_callers_job(self):
        # CONTRACT: num() does NOT strip thousands separators — float("1,234")
        # fails, so num() returns its garbage-default 0.0. Callers must strip
        # commas BEFORE calling (split_row does exactly that, tested below).
        # This test documents that division of labour; if someone "fixes" num()
        # to eat commas, this failing test forces them to check every caller.
        assert num("1,234") == 0.0
        assert num("1,234".replace(",", "")) == 1234.0


# ---------------------------------------------------------------------------
# split_row() — turns one PDF text line into (label_tokens, [6 numbers]),
# or None for junk. The "parse from both ends" workhorse.
# ---------------------------------------------------------------------------

class TestSplitRow:
    def test_normal_data_line(self):
        # CODE  NAME  q_h1 v_h1 q_h2 v_h2 q_fy v_fy
        label, nums = split_row("016 CANADA 10 4918 5 2000 15 6918")
        assert label == ["016", "CANADA"]
        assert nums == [10.0, 4918.0, 5.0, 2000.0, 15.0, 6918.0]

    def test_junk_header_line_returns_none(self):
        # Page headers/footers repeat mid-table in the PDFs; they lack six
        # trailing numbers, so split_row rejects them and the parser skips free.
        assert split_row("Code Description Unit Quantity Value Quantity Value Qty Val") is None
        assert split_row("Table-04 : Exports by Commodities") is None
        assert split_row("") is None

    def test_scientific_notation_token_is_accepted(self):
        # REGRESSION (M2, the big one): the revised re-print sections of the
        # older import PDFs came out of Excel with large numbers in E-notation
        # ("3.06704E+11"). The original NUM_RE only allowed plain integers, so
        # these lines were silently rejected as junk — a skipped COUNTRY HEADER
        # then dumped that country's detail under the PREVIOUS country
        # (2022-23's absurd "+488,054% CAMBODIA"), and skipped detail rows
        # explained 2020-21 imports' entire -6.9% gap.
        row = split_row("016 CANADA 3.06704E+11 0 0 0 3.06704E+11 0")
        assert row is not None, "E-notation value tokens must parse as numbers, not junk"
        label, nums = row
        assert label == ["016", "CANADA"]
        assert nums[0] == pytest.approx(3.06704e11)
        assert nums[4] == pytest.approx(3.06704e11)

    def test_commas_are_stripped_from_numbers(self):
        label, nums = split_row("010 GERMANY 1,234 0 2,000 0 3,234 0")
        assert nums == [1234.0, 0.0, 2000.0, 0.0, 3234.0, 0.0]

    def test_bare_six_number_line_yields_empty_label(self):
        # PDF text extraction occasionally drops a detail row's leading
        # "code name", leaving 6 bare numbers. split_row must still accept it
        # (empty label) so the parser can keep the VALUE under the current
        # header and mark only the lost counterpart UNKNOWN — dropping the line
        # loses reconcilable value.
        label, nums = split_row("70335 37474578 0 0 70335 37474578")
        assert label == []
        assert nums[1] == 37474578.0

    def test_too_few_tokens_returns_none(self):
        assert split_row("999 12 34") is None


# ---------------------------------------------------------------------------
# parse_unit() — separates a commodity's trailing unit from its description.
# ---------------------------------------------------------------------------

class TestParseUnit:
    def test_spaced_unit(self):
        assert parse_unit(["PRIMATES", "NUM"]) == ("NUM", "PRIMATES")

    def test_glued_unit(self):
        # In the PDF token stream the unit sometimes fuses onto the last
        # description word ("ANIMALSNUM") — no space survived extraction.
        assert parse_unit(["LIVE", "ANIMALSNUM"]) == ("NUM", "LIVE ANIMALS")

    def test_no_unit(self):
        # Some commodities carry no unit at all; the description passes through.
        assert parse_unit(["HORSES,", "PURE-BRED"]) == (None, "HORSES, PURE-BRED")

    def test_empty_middle(self):
        assert parse_unit([]) == (None, "")

    def test_longer_unit_wins_over_its_suffix(self):
        # "MTR" ends in... nothing shorter, but "MT" is a suffix-shaped trap:
        # a glued "...CLOTHMTR" must resolve as MTR, not as unit "TR"+garbage or
        # a mis-split on MT. parse_unit tries longer unit codes first.
        assert parse_unit(["COTTON", "CLOTHMTR"]) == ("MTR", "COTTON CLOTH")


# ---------------------------------------------------------------------------
# resolve() — finds a source file with or without its .pdf extension.
# ---------------------------------------------------------------------------

class TestResolve:
    def test_with_suffix_is_the_trap_this_guards(self):
        # REGRESSION (M2, the silent wrong-file bug): Path.with_suffix(".pdf")
        # treats "Volume2.2" as having extension ".2" and REWRITES it to
        # "Volume2.pdf" — which in FTS_23-24 is the EXPORT volume. Every
        # "import" run silently re-parsed exports. This assertion documents the
        # stdlib behavior that makes with_suffix unusable here.
        assert Path("Volume2.2").with_suffix(".pdf").name == "Volume2.pdf"

    def test_dotted_filename_resolves_by_appending_not_rewriting(self, tmp_path, monkeypatch):
        # The real defense: given "Volume2.2", resolve() must find
        # "Volume2.2.pdf" (string-append) even when the trap file
        # "Volume2.pdf" ALSO exists right next to it.
        monkeypatch.setattr(pdf_mod, "DATA", tmp_path)
        (tmp_path / "Volume2.2.pdf").touch()   # the file we want
        (tmp_path / "Volume2.pdf").touch()     # the wrong-file trap
        got = resolve("Volume2.2")
        assert got.name == "Volume2.2.pdf", (
            "resolve() must append '.pdf' to the full name; with_suffix-style "
            "rewriting would return the wrong volume (Volume2.pdf)"
        )

    def test_exact_path_wins_when_it_exists(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pdf_mod, "DATA", tmp_path)
        (tmp_path / "Volume1.pdf").touch()
        assert resolve("Volume1.pdf").name == "Volume1.pdf"

    def test_extensionless_file_found_from_pdf_name(self, tmp_path, monkeypatch):
        # BBS ships some files with NO extension (they are PDFs anyway);
        # asking for "Volume2.1.pdf" must fall back to the bare "Volume2.1".
        monkeypatch.setattr(pdf_mod, "DATA", tmp_path)
        (tmp_path / "Volume2.1").touch()
        assert resolve("Volume2.1.pdf").name == "Volume2.1"

    def test_missing_file_exits(self, tmp_path, monkeypatch):
        # Fail loudly at startup, not mid-parse: a missing source is a
        # configuration error, never something to guess around.
        monkeypatch.setattr(pdf_mod, "DATA", tmp_path)
        with pytest.raises(SystemExit):
            resolve("NoSuchVolume.pdf")


# ---------------------------------------------------------------------------
# parse_table01() — the chapter->value ANSWER KEY reader.
# Tested through a fake pdf_lines (production code untouched): parse_table01
# looks the generator up on its module at call time, so monkeypatching the
# module attribute swaps the PDF for a hand-written list of lines.
# ---------------------------------------------------------------------------

def _fake_lines(monkeypatch, lines):
    monkeypatch.setattr(pdf_mod, "pdf_lines", lambda path, pages=None: iter(lines))


class TestParseTable01:
    def test_clean_chapter_rows_and_grand_total(self, monkeypatch):
        _fake_lines(monkeypatch, [
            "Table-01 : Exports by Chapter",
            "01 LIVE ANIMALS 100 200 300",          # h1 + h2 == fy
            "65 HEADGEAR 40 60 100",
            "EXPORT TOTAL 140 260 400",
        ])
        chapters, grand = parse_table01(None, "X")
        assert chapters == {"01": 300.0, "65": 100.0}
        assert grand == 400.0

    def test_glued_page_footer_does_not_corrupt_the_answer_key(self, monkeypatch):
        # REGRESSION (M2, "chapter 65 = 1 taka"): the ch65 row was the last
        # line of a page and the page footer glued onto it
        # ("...31476881650Fts-Exp- 1"). Taking the LAST numeric token made the
        # ANSWER KEY wrong — our extracted data was exact, but reconciliation
        # failed against a misread key. A chapter row must satisfy the
        # publication's own invariant H1 + H2 == FY, so parse_table01 scans for
        # the a+b==c triple instead of trusting token position.
        _fake_lines(monkeypatch, [
            "65 HEADGEAR AND PARTS 100 200 300Fts-Exp- 1",
        ])
        chapters, _ = parse_table01(None, "X")
        assert chapters["65"] == 300.0, (
            "must pick the value satisfying H1+H2==FY, not the trailing "
            "footer token"
        )

    def test_stops_at_table_02_header_only_after_data(self, monkeypatch):
        # A contents-page mention of "Table 02" BEFORE any chapter row must not
        # end parsing early; the real Table 02 header AFTER data must.
        _fake_lines(monkeypatch, [
            "Contents ... Table 02 Exports by HS4 ... page 12",  # premature mention
            "01 LIVE ANIMALS 100 200 300",
            "Table 02 : Exports by HS4",                          # the real boundary
            "02 MEAT 999 999 1998",                               # must NOT be read
        ])
        chapters, _ = parse_table01(None, "X")
        assert chapters == {"01": 300.0}

    def test_import_flow_uses_import_total(self, monkeypatch):
        _fake_lines(monkeypatch, [
            "05 PRODUCTS 10 20 30",
            "IMPORT TOTAL 10 20 30",
        ])
        chapters, grand = parse_table01(None, "M")
        assert chapters == {"05": 30.0}
        assert grand == 30.0
