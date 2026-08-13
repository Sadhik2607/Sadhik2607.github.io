"""Stage 1 — INGEST.

Load a raw client CSV with pandas, profile every column, and apply a set of
safe, source-agnostic cleaning steps (whitespace, empty-string -> null, exact
duplicate rows). No schema knowledge lives here on purpose: ingest only makes
the data *tidy*, mapping decides what it *means*.

Output: a dict with cleaned records (list of row dicts) plus a column profile.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class ColumnProfile:
    name: str
    non_null: int
    null: int
    unique: int
    sample_values: list[str] = field(default_factory=list)


@dataclass
class IngestResult:
    client: str
    source_file: str
    row_count: int
    duplicate_rows_dropped: int
    columns: list[ColumnProfile]
    records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Trim strings, blank -> NaN, drop fully-duplicate rows."""
    # Normalise column headers (strip only; casing is handled by the mapping layer)
    df = df.rename(columns=lambda c: str(c).strip())

    # Trim whitespace on all object (string) columns
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)

    # Treat empty strings as missing so validation catches them consistently
    df = df.replace({"": None})

    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    dupes = before - len(df)
    return df, dupes


def _profile(df: pd.DataFrame) -> list[ColumnProfile]:
    profiles: list[ColumnProfile] = []
    for col in df.columns:
        series = df[col]
        non_null = int(series.notna().sum())
        samples = [str(v) for v in series.dropna().unique()[:3]]
        profiles.append(
            ColumnProfile(
                name=col,
                non_null=non_null,
                null=int(series.isna().sum()),
                unique=int(series.nunique(dropna=True)),
                sample_values=samples,
            )
        )
    return profiles


def ingest(source_file: str | Path, client: str) -> IngestResult:
    path = Path(source_file)
    if not path.exists():
        raise FileNotFoundError(f"Raw data file not found: {path}")

    df = pd.read_csv(path, dtype=str, keep_default_na=True, na_values=[""])
    df, dupes = _clean_frame(df)
    profiles = _profile(df)

    # Records with NaN -> None so the JSON handed to Node is clean
    records = df.where(pd.notna(df), None).to_dict(orient="records")

    return IngestResult(
        client=client,
        source_file=str(path),
        row_count=len(df),
        duplicate_rows_dropped=dupes,
        columns=profiles,
        records=records,
    )


def _cli() -> None:
    ap = argparse.ArgumentParser(description="MigrateForge ingest stage")
    ap.add_argument("--input", required=True, help="Path to raw client CSV")
    ap.add_argument("--client", required=True, help="Client key (e.g. acme)")
    ap.add_argument("--out", help="Optional path to write ingested JSON")
    args = ap.parse_args()

    result = ingest(args.input, args.client)
    payload = json.dumps(result.to_dict(), indent=2)
    if args.out:
        Path(args.out).write_text(payload)
        print(f"Wrote {result.row_count} cleaned rows -> {args.out}")
    else:
        print(payload)


if __name__ == "__main__":
    _cli()
