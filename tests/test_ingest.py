"""Tests for the ingest (clean + profile) stage."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import ingest  # noqa: E402


def test_ingest_drops_exact_duplicate_rows():
    # globex.csv contains one byte-identical duplicate (Donald Knuth)
    result = ingest.ingest(ROOT / "data" / "raw" / "globex.csv", "globex")
    assert result.duplicate_rows_dropped == 1


def test_ingest_trims_whitespace():
    # acme rows are NOT exact dupes (email casing/whitespace differs); the
    # semantic duplicate is caught later at validation, not here.
    result = ingest.ingest(ROOT / "data" / "raw" / "acme.csv", "acme")
    emails = [r["E-mail"] for r in result.records if r["E-mail"]]
    assert all(e == e.strip() for e in emails)


def test_ingest_blank_becomes_none():
    result = ingest.ingest(ROOT / "data" / "raw" / "acme.csv", "acme")
    # Dennis Ritchie row has an empty email -> should be None, not ""
    ritchie = [r for r in result.records if r["Last"] == "Ritchie"][0]
    assert ritchie["E-mail"] is None


def test_profile_reports_columns():
    result = ingest.ingest(ROOT / "data" / "raw" / "acme.csv", "acme")
    names = {c.name for c in result.columns}
    assert names == {"First", "Last", "E-mail", "Joined"}
