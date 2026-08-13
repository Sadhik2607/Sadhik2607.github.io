"""Tests for the validation stage."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import validate  # noqa: E402

SCHEMA = validate.load_target_schema()


def _rec(first="Ada", last="Lovelace", email="ada@example.com", join="2021-03-07"):
    return {"first_name": first, "last_name": last, "email": email, "join_date": join}


def test_valid_record_passes():
    result = validate.validate([_rec()], SCHEMA)
    assert result["summary"]["valid_count"] == 1
    assert result["summary"]["flagged_count"] == 0


def test_missing_required_field_is_flagged():
    result = validate.validate([_rec(email=None)], SCHEMA)
    assert result["summary"]["flagged_count"] == 1
    assert any("required" in e for e in result["flagged"][0]["errors"])


def test_bad_email_and_bad_date_flagged():
    result = validate.validate([_rec(email="nope"), _rec(join="03/07/2021")], SCHEMA)
    assert result["summary"]["flagged_count"] == 2


def test_duplicate_email_flagged_once():
    result = validate.validate([_rec(), _rec(first="Ada2")], SCHEMA)
    # second record shares the email -> flagged as duplicate
    assert result["summary"]["valid_count"] == 1
    assert result["summary"]["flagged_count"] == 1
    assert any("duplicate" in e for e in result["flagged"][0]["errors"])
