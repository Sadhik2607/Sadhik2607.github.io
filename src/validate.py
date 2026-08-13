"""Stage 4 — VALIDATE.

Enforces the target CRM schema against the transformed records. Bad records are
*flagged with reasons*, never silently dropped or coerced — a migration you
can't audit is a migration you can't trust.

Checks:
  * required fields present and non-empty
  * type conformance (email shape, ISO date, string length)
  * uniqueness constraints (e.g. email) across the batch
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_target_schema() -> dict[str, Any]:
    with open(CONFIG_DIR / "target_schema.yaml", "r") as fh:
        return yaml.safe_load(fh)


def _check_field(field: str, spec: dict[str, Any], value: Any) -> list[str]:
    errors: list[str] = []
    is_empty = value is None or (isinstance(value, str) and value.strip() == "")

    if spec.get("required") and is_empty:
        errors.append(f"{field}: required field is missing")
        return errors  # nothing more to check on an empty value

    if is_empty:
        return errors

    ftype = spec.get("type", "string")
    if ftype == "email" and not EMAIL_RE.match(str(value)):
        errors.append(f"{field}: '{value}' is not a valid email")
    elif ftype == "date" and not ISO_DATE_RE.match(str(value)):
        errors.append(f"{field}: '{value}' is not a valid ISO (YYYY-MM-DD) date")
    elif ftype == "string":
        max_len = spec.get("max_length")
        if max_len and len(str(value)) > max_len:
            errors.append(f"{field}: exceeds max length {max_len}")
    return errors


def validate(records: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, Any]:
    fields = schema.get("fields", {})
    unique_fields = [f for f, s in fields.items() if s.get("unique")]

    valid: list[dict[str, Any]] = []
    flagged: list[dict[str, Any]] = []
    seen: dict[str, set[str]] = {f: set() for f in unique_fields}
    error_counts: dict[str, int] = {}

    for idx, rec in enumerate(records):
        errors: list[str] = []
        for field, spec in fields.items():
            errors.extend(_check_field(field, spec, rec.get(field)))

        # uniqueness (only meaningful for otherwise-valid values)
        for f in unique_fields:
            val = rec.get(f)
            if not val:
                continue
            # for typed emails, only dedupe values that are actually valid emails
            if fields[f].get("type") == "email" and not EMAIL_RE.match(str(val)):
                continue
            key = str(val).lower()
            if key in seen[f]:
                errors.append(f"{f}: duplicate value '{val}'")
            else:
                seen[f].add(key)

        if errors:
            for e in errors:
                reason = e.split(":")[1].strip().split(" '")[0] if ":" in e else e
                error_counts[reason] = error_counts.get(reason, 0) + 1
            flagged.append({"row_index": idx, "record": rec, "errors": errors})
        else:
            valid.append(rec)

    return {
        "client": None,
        "total": len(records),
        "valid": valid,
        "flagged": flagged,
        "summary": {
            "valid_count": len(valid),
            "flagged_count": len(flagged),
            "error_counts": error_counts,
        },
    }


def _cli() -> None:
    ap = argparse.ArgumentParser(description="MigrateForge validate stage")
    ap.add_argument("--transformed", required=True, help="Path to transformed JSON from stage 3")
    ap.add_argument("--out", help="Optional path to write validation result JSON")
    args = ap.parse_args()

    data = json.loads(Path(args.transformed).read_text())
    result = validate(data["records"], load_target_schema())
    result["client"] = data.get("client")

    payload = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        print(f"Validated: {result['summary']['valid_count']} ok, "
              f"{result['summary']['flagged_count']} flagged -> {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    _cli()
