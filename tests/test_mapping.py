"""Tests for the reusable knowledge / mapping layer."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import mapping  # noqa: E402


def test_acme_fully_resolved_from_shared_layer():
    cfg = mapping.load_yaml(ROOT / "configs" / "client_acme.yaml")
    cols = ["First", "Last", "E-mail", "Joined"]
    plan = mapping.resolve_mapping(cfg, cols)

    targets = {r["target"] for r in plan["rules"]}
    assert targets == {"first_name", "last_name", "email", "join_date"}
    # ACME declares no explicit mapping -> everything comes from shared patterns
    assert plan["reuse_stats"]["target_fields_from_client_override"] == 0
    assert plan["reuse_stats"]["target_fields_from_shared_layer"] == 4
    assert plan["unmapped_target_fields"] == []


def test_globex_full_name_splits_into_two_fields():
    cfg = mapping.load_yaml(ROOT / "configs" / "client_globex.yaml")
    cols = ["full_name", "primary_contact", "signup_date"]
    plan = mapping.resolve_mapping(cfg, cols)

    by_target = {r["target"]: r for r in plan["rules"]}
    # composite split
    assert by_target["first_name"]["source"] == "full_name"
    assert by_target["last_name"]["source"] == "full_name"
    assert by_target["first_name"]["transform"] == "split_first"
    assert by_target["last_name"]["transform"] == "split_last"
    # explicit client override for the oddly-named email column
    assert by_target["email"]["source"] == "primary_contact"
    assert by_target["email"]["via"] == "client_override"


def test_alias_normalisation_is_fuzzy():
    # different header spellings must resolve to the same target field
    cfg = {"client": "x", "mapping": {}}
    for header in ["e-mail", "Email Address", "EMAIL_ADDRESS", "mail"]:
        plan = mapping.resolve_mapping(cfg, [header])
        assert plan["rules"][0]["target"] == "email"


def test_unmapped_column_produces_ai_draft_suggestion():
    cfg = {"client": "x", "mapping": {}}
    # 'first_nm' is close to first_name; heuristic should suggest it
    plan = mapping.resolve_mapping(cfg, ["first_nm"], use_ai=False)
    assert plan["unmapped_source_columns"] == ["first_nm"]
    assert any(s["suggested_target"] == "first_name" for s in plan["ai_suggestions"])
    # suggestions must never be silently trusted
    assert all(s["status"] == "REQUIRES_HUMAN_VALIDATION" for s in plan["ai_suggestions"])
