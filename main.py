#!/usr/bin/env python3
"""MigrateForge — end-to-end migration pipeline orchestrator.

Chains all five stages, including the real Python -> Node.js hand-off:

    ingest.py (py)  ->  mapping.py (py)  ->  transform.js (node)
                    ->  validate.py (py)  ->  report.py (py)

Usage:
    python main.py --client acme   --input data/raw/acme.csv
    python main.py --client globex --input data/raw/globex.csv --ai

The pipeline is re-runnable and idempotent: point it at a fresh export of the
same client and it reuses the same mapping plan, so incremental loads are free.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
CONFIG_DIR = ROOT / "configs"

sys.path.insert(0, str(ROOT))
from src import ingest as ingest_mod  # noqa: E402
from src import mapping as mapping_mod  # noqa: E402
from src import report as report_mod  # noqa: E402
from src import validate as validate_mod  # noqa: E402


def _run_node_transform(ingested_path: Path, plan_path: Path, out_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError(
            "Node.js not found on PATH. Install Node 18+ to run the transform stage.\n"
            "(The transform step is intentionally Node, mirroring the target Python->Node workflow.)"
        )
    cmd = [node, str(SRC / "transform.js"),
           "--ingested", str(ingested_path),
           "--plan", str(plan_path),
           "--out", str(out_path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Node transform failed:\n{proc.stderr}")
    print(proc.stdout.strip())


def run_pipeline(client: str, input_csv: str, out_dir: Path, use_ai: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) ingest (Python)
    ing = ingest_mod.ingest(input_csv, client)
    ingested_path = out_dir / f"{client}_ingested.json"
    ingested_path.write_text(json.dumps(ing.to_dict(), indent=2))
    print(f"[1/5] ingest    : {ing.row_count} rows cleaned "
          f"({ing.duplicate_rows_dropped} dup rows dropped)")

    # 2) mapping (Python) — the reusable knowledge layer
    cfg = mapping_mod.load_yaml(CONFIG_DIR / f"client_{client}.yaml")
    source_columns = [c.name for c in ing.columns]
    plan = mapping_mod.resolve_mapping(cfg, source_columns, use_ai=use_ai)
    plan_path = out_dir / f"{client}_mapping.json"
    plan_path.write_text(json.dumps(plan, indent=2))
    reuse = plan["reuse_stats"]
    print(f"[2/5] mapping   : {len(plan['rules'])} rules "
          f"({reuse['target_fields_from_shared_layer']} from shared layer, "
          f"{reuse['target_fields_from_client_override']} overrides)")

    # 3) transform (Node.js)
    transformed_path = out_dir / f"{client}_transformed.json"
    _run_node_transform(ingested_path, plan_path, transformed_path)
    print("[3/5] transform : Node.js reshaped records into target CRM schema")

    # 4) validate (Python)
    transformed = json.loads(transformed_path.read_text())
    validation = validate_mod.validate(transformed["records"], validate_mod.load_target_schema())
    validation["client"] = client
    validation_path = out_dir / f"{client}_validation.json"
    validation_path.write_text(json.dumps(validation, indent=2))
    print(f"[4/5] validate  : {validation['summary']['valid_count']} valid, "
          f"{validation['summary']['flagged_count']} flagged")

    # 5) report (Python)
    print("[5/5] report    :")
    print(report_mod.build_terminal_report(ing.to_dict(), plan, validation))
    written = report_mod.write_outputs(out_dir, client, plan, validation)
    return {"written": written, "validation": validation, "plan": plan}


def main() -> None:
    ap = argparse.ArgumentParser(description="MigrateForge migration pipeline")
    ap.add_argument("--client", required=True, help="Client key (matches configs/client_<key>.yaml)")
    ap.add_argument("--input", required=True, help="Path to the raw client CSV export")
    ap.add_argument("--out-dir", default=str(ROOT / "data" / "output"),
                    help="Directory for pipeline output artifacts")
    ap.add_argument("--ai", action="store_true",
                    help="Allow AI-drafted mapping suggestions for unmapped columns (human-validated)")
    args = ap.parse_args()

    result = run_pipeline(args.client, args.input, Path(args.out_dir), use_ai=args.ai)
    print("\nDeliverables:")
    for k, v in result["written"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
