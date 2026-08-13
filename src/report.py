"""Stage 5 — REPORT.

Turns the run artifacts into deliverables a stakeholder can actually use:
  * a terminal summary (what happened, at a glance)
  * clean target-schema output as JSON *and* CSV (ready to load into the CRM)
  * an HTML migration report (records processed / mapped / flagged + reasons)

Nothing here mutates data; it only presents what the earlier stages produced.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

try:
    from tabulate import tabulate
except Exception:  # pragma: no cover - tabulate is optional at runtime
    tabulate = None


def _fmt_table(rows: list[list[Any]], headers: list[str]) -> str:
    if tabulate:
        return tabulate(rows, headers=headers, tablefmt="github")
    # minimal fallback if tabulate isn't installed
    line = " | ".join(headers)
    body = "\n".join(" | ".join(str(c) for c in r) for r in rows)
    return f"{line}\n{body}"


def build_terminal_report(ingest: dict, plan: dict, validation: dict) -> str:
    s = validation["summary"]
    reuse = plan.get("reuse_stats", {})
    lines: list[str] = []
    lines.append("=" * 64)
    lines.append(f" MigrateForge migration report — client: {plan.get('client')}")
    lines.append("=" * 64)
    lines.append("")
    lines.append(f" Source file        : {ingest.get('source_file')}")
    lines.append(f" Rows ingested      : {ingest.get('row_count')} "
                 f"(dropped {ingest.get('duplicate_rows_dropped')} duplicate rows)")
    lines.append(f" Records valid      : {s['valid_count']}")
    lines.append(f" Records flagged    : {s['flagged_count']}")
    lines.append("")
    lines.append(" Mapping (source -> target CRM field):")
    map_rows = [[r["source"], r["target"], r["transform"], r["via"]] for r in plan["rules"]]
    lines.append(_fmt_table(map_rows, ["source column", "target field", "transform", "resolved via"]))
    lines.append("")
    lines.append(" Knowledge-layer reuse:")
    lines.append(f"   {reuse.get('target_fields_from_shared_layer', 0)}/"
                 f"{reuse.get('target_fields_total', 0)} target fields resolved from the shared "
                 f"common_patterns layer; "
                 f"{reuse.get('target_fields_from_client_override', 0)} from client overrides.")
    if plan.get("unmapped_source_columns"):
        lines.append(f"   Unmapped source columns: {plan['unmapped_source_columns']}")
    if plan.get("ai_suggestions"):
        lines.append("   AI draft suggestions (REQUIRE HUMAN VALIDATION):")
        for sug in plan["ai_suggestions"]:
            lines.append(f"     - {sug['source']} -> {sug.get('suggested_target')} "
                         f"({sug.get('confidence')}, {sug.get('method')})")
    lines.append("")
    if validation["flagged"]:
        lines.append(" Flagged records:")
        for f in validation["flagged"]:
            lines.append(f"   row {f['row_index']}: {'; '.join(f['errors'])}")
    lines.append("=" * 64)
    return "\n".join(lines)


def write_outputs(out_dir: Path, client: str, plan: dict, validation: dict) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    target_fields = [r["target"] for r in plan["rules"]]
    # preserve target-schema order, de-duped
    seen: list[str] = []
    for f in target_fields:
        if f not in seen:
            seen.append(f)

    valid = validation["valid"]
    written: dict[str, str] = {}

    # clean JSON
    json_path = out_dir / f"{client}_clean.json"
    json_path.write_text(json.dumps(valid, indent=2))
    written["clean_json"] = str(json_path)

    # clean CSV
    csv_path = out_dir / f"{client}_clean.csv"
    with open(csv_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=seen)
        writer.writeheader()
        for rec in valid:
            writer.writerow({k: rec.get(k, "") for k in seen})
    written["clean_csv"] = str(csv_path)

    # full report JSON
    report_json = out_dir / f"{client}_migration_report.json"
    report_json.write_text(json.dumps({
        "client": client,
        "mapping_plan": plan,
        "validation": validation["summary"],
        "flagged": validation["flagged"],
    }, indent=2))
    written["report_json"] = str(report_json)

    # HTML report
    html_path = out_dir / f"{client}_migration_report.html"
    html_path.write_text(_render_html(client, plan, validation))
    written["report_html"] = str(html_path)

    return written


def _render_html(client: str, plan: dict, validation: dict) -> str:
    s = validation["summary"]
    rows = "".join(
        f"<tr><td>{r['source']}</td><td>{r['target']}</td><td><code>{r['transform']}</code></td>"
        f"<td>{r['via']}</td></tr>"
        for r in plan["rules"]
    )
    flagged = "".join(
        f"<tr><td>{f['row_index']}</td><td>{'; '.join(f['errors'])}</td></tr>"
        for f in validation["flagged"]
    ) or "<tr><td colspan='2'>None 🎉</td></tr>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>MigrateForge — {client}</title>
<style>
 body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;color:#1a1a2e;}}
 h1{{margin-bottom:0}} .sub{{color:#666}}
 .cards{{display:flex;gap:1rem;margin:1.5rem 0}}
 .card{{flex:1;padding:1rem;border-radius:10px;background:#f5f6fa;text-align:center}}
 .card .n{{font-size:2rem;font-weight:700}} .ok{{color:#0a7d33}} .bad{{color:#c0392b}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0}}
 th,td{{border:1px solid #ddd;padding:.5rem;text-align:left;font-size:.92rem}}
 th{{background:#1a1a2e;color:#fff}} code{{background:#eee;padding:1px 5px;border-radius:4px}}
</style></head><body>
<h1>MigrateForge migration report</h1>
<div class="sub">Client: <strong>{client}</strong> &middot; target schema: {plan.get('target_schema')}</div>
<div class="cards">
 <div class="card"><div class="n">{s['valid_count']+s['flagged_count']}</div>records processed</div>
 <div class="card"><div class="n ok">{s['valid_count']}</div>valid &amp; loadable</div>
 <div class="card"><div class="n bad">{s['flagged_count']}</div>flagged</div>
</div>
<h2>Column mapping</h2>
<table><tr><th>Source column</th><th>Target field</th><th>Transform</th><th>Resolved via</th></tr>{rows}</table>
<h2>Flagged records &amp; reasons</h2>
<table><tr><th>Row</th><th>Reasons</th></tr>{flagged}</table>
</body></html>"""


def _cli() -> None:
    ap = argparse.ArgumentParser(description="MigrateForge report stage")
    ap.add_argument("--ingested", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--validation", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    ingest = json.loads(Path(args.ingested).read_text())
    plan = json.loads(Path(args.plan).read_text())
    validation = json.loads(Path(args.validation).read_text())
    client = plan.get("client")

    print(build_terminal_report(ingest, plan, validation))
    written = write_outputs(Path(args.out_dir), client, plan, validation)
    print("\nWrote:")
    for k, v in written.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    _cli()
