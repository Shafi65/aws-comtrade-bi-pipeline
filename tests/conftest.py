"""
Shared pytest setup.

The ingestion scripts live in `ingestion/` and import each other as plain modules
(`extract_fts_pdf` does `from extract_fts_excel import num, reconcile`) — they were
written to be RUN from that directory, not installed as a package. Rather than
restructure working extraction code into a package just to test it, we put
`ingestion/` on sys.path here so the tests can import the modules exactly as they
import each other. conftest.py is imported by pytest before any test module, so
every test file gets this for free.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingestion"))
