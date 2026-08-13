"""Stage 2 — MAPPING (the reusable knowledge layer).

Resolves a client's source columns onto the target CRM schema using:
  1. the shared ``common_patterns.yaml`` knowledge base (aliases + transforms),
  2. the per-client config's explicit overrides, and
  3. (optional) an AI *draft* for still-unmapped columns that a human validates.

The output is a deterministic "mapping plan" that the Node.js transform stage
consumes. Nothing here touches the data values themselves — this stage only
decides *which source column becomes which target field, via which transform*.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    """Canonicalise a column name for fuzzy alias matching.

    "E-mail", "email_address" and "Email Address" all collapse to a comparable
    form. We keep it conservative: lowercase + strip non-alphanumerics.
    """
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r") as fh:
        return yaml.safe_load(fh) or {}


def load_target_schema() -> dict[str, Any]:
    return load_yaml(CONFIG_DIR / "target_schema.yaml")


def _build_alias_index(patterns: dict[str, Any]) -> dict[str, str]:
    """normalized-alias -> pattern-name (e.g. 'emailaddress' -> 'email')."""
    index: dict[str, str] = {}
    for pattern_name, spec in patterns.items():
        for alias in spec.get("aliases", []):
            index[_norm(alias)] = pattern_name
    return index


# --------------------------------------------------------------------------- #
# core resolution
# --------------------------------------------------------------------------- #
def resolve_mapping(
    client_config: dict[str, Any],
    source_columns: list[str],
    *,
    use_ai: bool = False,
) -> dict[str, Any]:
    patterns = load_yaml(CONFIG_DIR / "common_patterns.yaml").get("patterns", {})
    target_schema = load_target_schema()
    target_fields = list(target_schema.get("fields", {}).keys())

    alias_index = _build_alias_index(patterns)
    overrides = {_norm(k): v for k, v in (client_config.get("mapping") or {}).items()}

    rules: list[dict[str, Any]] = []
    covered_targets: set[str] = set()
    consumed_sources: set[str] = set()

    def transform_for(target_field: str) -> str:
        spec = patterns.get(target_field, {})
        return spec.get("transform", "trim")

    # 1) explicit per-client overrides win first
    for col in source_columns:
        n = _norm(col)
        if n in overrides:
            target = overrides[n]
            rules.append({"target": target, "source": col, "transform": transform_for(target),
                          "via": "client_override"})
            covered_targets.add(target)
            consumed_sources.add(col)

    # 2) shared knowledge layer (aliases + composite splits)
    for col in source_columns:
        if col in consumed_sources:
            continue
        pattern_name = alias_index.get(_norm(col))
        if pattern_name is None:
            continue
        spec = patterns[pattern_name]

        if "split_into" in spec:
            # one source column -> multiple target fields
            for target, split_transform in spec["split_into"].items():
                if target in covered_targets:
                    continue
                rules.append({"target": target, "source": col, "transform": split_transform,
                              "via": f"common_patterns:{pattern_name}"})
                covered_targets.add(target)
            consumed_sources.add(col)
        else:
            target = pattern_name
            if target in covered_targets:
                continue
            rules.append({"target": target, "source": col, "transform": spec.get("transform", "trim"),
                          "via": f"common_patterns:{pattern_name}"})
            covered_targets.add(target)
            consumed_sources.add(col)

    unmapped_sources = [c for c in source_columns if c not in consumed_sources]
    unmapped_targets = [t for t in target_fields if t not in covered_targets]

    ai_suggestions = draft_unmapped_with_ai(
        unmapped_sources, unmapped_targets, use_ai=use_ai
    ) if unmapped_targets and unmapped_sources else []

    plan = {
        "client": client_config.get("client"),
        "target_schema": target_schema.get("schema"),
        "date_input_format": (client_config.get("source") or {}).get("date_input_format", "%Y-%m-%d"),
        "rules": rules,
        "unmapped_source_columns": unmapped_sources,
        "unmapped_target_fields": unmapped_targets,
        "ai_suggestions": ai_suggestions,
        "reuse_stats": {
            "target_fields_total": len(target_fields),
            "target_fields_from_shared_layer": sum(
                1 for r in rules if r["via"].startswith("common_patterns")
            ),
            "target_fields_from_client_override": sum(
                1 for r in rules if r["via"] == "client_override"
            ),
        },
    }
    return plan


# --------------------------------------------------------------------------- #
# optional AI-assisted draft  (SUGGESTION ONLY — never auto-applied)
# --------------------------------------------------------------------------- #
def draft_unmapped_with_ai(
    unmapped_sources: list[str],
    unmapped_targets: list[str],
    *,
    use_ai: bool = False,
) -> list[dict[str, Any]]:
    """Produce *draft* suggestions for columns the knowledge layer couldn't map.

    Design principle (matches how AI use was described to the client): the model
    proposes, a human disposes. These are never applied automatically — they are
    surfaced in the report for a human to accept, edit, or reject.

    If ``use_ai`` is set and an ANTHROPIC_API_KEY + SDK are available, we ask
    Claude for a first-pass mapping. Otherwise we fall back to a transparent
    local heuristic (fuzzy string similarity) so the toolkit is fully functional
    offline and in CI.
    """
    if use_ai and os.getenv("ANTHROPIC_API_KEY"):
        try:  # pragma: no cover - network path, exercised manually
            return _ai_suggestions_via_claude(unmapped_sources, unmapped_targets)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully to heuristic
            print(f"[mapping] AI draft unavailable ({exc}); using local heuristic.")

    suggestions: list[dict[str, Any]] = []
    for col in unmapped_sources:
        match = difflib.get_close_matches(_norm(col), [_norm(t) for t in unmapped_targets], n=1, cutoff=0.4)
        if match:
            target = unmapped_targets[[_norm(t) for t in unmapped_targets].index(match[0])]
            suggestions.append({
                "source": col,
                "suggested_target": target,
                "confidence": "low",
                "method": "local_heuristic",
                "status": "REQUIRES_HUMAN_VALIDATION",
            })
    return suggestions


def _ai_suggestions_via_claude(
    unmapped_sources: list[str], unmapped_targets: list[str]
) -> list[dict[str, Any]]:  # pragma: no cover - network path
    """Ask Claude to draft a mapping. Returns SUGGESTIONS for human validation."""
    import anthropic  # imported lazily so the SDK isn't a hard dependency

    client = anthropic.Anthropic()
    prompt = (
        "You map messy source CSV columns to a fixed target CRM schema.\n"
        f"Unmapped source columns: {unmapped_sources}\n"
        f"Available target fields: {unmapped_targets}\n"
        "Return ONLY JSON: a list of {source, suggested_target, confidence} objects. "
        "Use null for suggested_target if no good match."
    )
    msg = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text
    parsed = json.loads(raw[raw.find("["): raw.rfind("]") + 1])
    for s in parsed:
        s["method"] = "claude"
        s["status"] = "REQUIRES_HUMAN_VALIDATION"
    return parsed


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _cli() -> None:
    ap = argparse.ArgumentParser(description="MigrateForge mapping stage")
    ap.add_argument("--client", required=True, help="Client key (config file name)")
    ap.add_argument("--ingested", required=True, help="Path to ingested JSON from stage 1")
    ap.add_argument("--out", help="Optional path to write the mapping plan JSON")
    ap.add_argument("--ai", action="store_true", help="Allow AI-drafted suggestions for unmapped columns")
    args = ap.parse_args()

    cfg = load_yaml(CONFIG_DIR / f"client_{args.client}.yaml")
    ingested = json.loads(Path(args.ingested).read_text())
    source_columns = [c["name"] for c in ingested["columns"]]

    plan = resolve_mapping(cfg, source_columns, use_ai=args.ai)
    payload = json.dumps(plan, indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        print(f"Wrote mapping plan -> {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    _cli()
