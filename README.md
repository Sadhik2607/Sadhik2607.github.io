# MigrateForge — Client Data Migration Toolkit

**Ingest messy client tabular data from any source schema → map it into a target CRM schema → validate it → and reuse prior mapping logic across clients through a shared knowledge layer.**

MigrateForge solves the "one script per client" problem head-on: instead of a bespoke, throwaway migration for every customer, it maintains a growing library of reusable field-mapping patterns. Client #5 reuses ~80% of what was learned from clients #1–4. The common-patterns layer is the knowledge base; each client config is just the *delta*.

```
Raw client data (CSV export, inconsistent columns, messy values)
        │
        ▼
[1] ingest.py ........ Python / pandas — load, profile, clean (trim, blanks→null, de-dupe)
        │
        ▼
[2] mapping.py ....... reusable knowledge layer ── common_patterns.yaml + client_<x>.yaml
        │              maps source columns → target CRM fields, reusing shared patterns;
        │              optional AI drafts a mapping for unknown columns (human-validated)
        ▼
[3] transform.js ..... Node.js — apply the plan, reshape records into the target schema
        │              (deterministic: format dates, split names, normalize emails)
        ▼
[4] validate.py ...... Python — required fields, types, uniqueness; flag bad records w/ reasons
        │
        ▼
[5] report.py ........ clean JSON + CSV ready to load  +  migration report (terminal / JSON / HTML)
```

The Python → Node.js split is deliberate: **Python works the raw tabular data, Node.js translates it into the CRM schema** — the exact workflow this tool is modelled on.

---

## Why the architecture looks like this

| Design choice | Reason |
|---|---|
| **Python for ingest + validate** | pandas is the right tool for profiling and cleaning arbitrary tabular exports. |
| **Node.js for the schema translation** | Mirrors a real "Python cleans, Node maps into our CRM schema" division of labour. The two processes hand off via plain JSON, so either side can be swapped. |
| **YAML knowledge layer** | The reusable asset. A migration's value is the *accumulated mapping knowledge*, not the one-off script. Patterns are promoted up; clients only declare their diff. |
| **AI as a draft, never an autopilot** | For columns the knowledge layer can't place, an optional AI step *suggests* a mapping that a human accepts/edits/rejects. The pipeline is fully functional without it. |
| **Flag, don't silently coerce** | Bad records are rejected with explicit reasons. A migration you can't audit is one you can't trust. |

---

## The reusable knowledge layer (the centerpiece)

`configs/common_patterns.yaml` is a growing library of field-mapping rules. Each pattern maps many messy real-world column names onto one canonical target field:

```yaml
email:
  aliases: [email, e-mail, email_address, mail, "email address", contact_email]
  transform: lowercase_trim
full_name:                      # a composite: one source column → two target fields
  aliases: [full_name, "full name", name, contact_name]
  split_into: {first_name: split_first, last_name: split_last}
```

A client config inherits all of it and only declares what's unique:

```yaml
# client_acme.yaml — First/Last columns, US dates
client: acme
extends: common_patterns
source: {date_input_format: "%m/%d/%Y"}
mapping: {}                     # ← empty. ACME is fully covered by shared patterns.
```

```yaml
# client_globex.yaml — one full_name column, ISO dates, oddly-named email
client: globex
extends: common_patterns
source: {date_input_format: "%Y-%m-%d"}
mapping: {primary_contact: email}   # ← the only bespoke line
```

Two totally different source shapes, the **same target schema**, the **same reused patterns**. That is the whole point.

---

## Quick Start

```bash
# 1. install
pip install -r requirements.txt          # Python: pandas, PyYAML, tabulate
# Node 18+ must be on PATH for the transform stage (no npm deps needed)

# 2. run a migration end-to-end
python main.py --client acme   --input data/raw/acme.csv
python main.py --client globex --input data/raw/globex.csv

# 3. (optional) let AI draft mappings for columns the knowledge layer can't place
python main.py --client acme --input data/raw/acme.csv --ai   # needs ANTHROPIC_API_KEY

# outputs land in data/output/:
#   <client>_clean.json / .csv            ← ready to load into the CRM
#   <client>_migration_report.html/.json  ← what mapped, what flagged, and why
```

### Docker

```bash
docker build -t migrateforge .
docker run --rm -v "$PWD/data:/app/data" migrateforge --client globex --input data/raw/globex.csv
```

---

## CLI reference

| Command | Purpose |
|---|---|
| `python main.py --client <k> --input <csv>` | Run all five stages end-to-end |
| `python main.py ... --ai` | Allow AI-drafted mapping suggestions (human-validated) |
| `python main.py ... --out-dir <dir>` | Change output directory (default `data/output/`) |
| `python -m src.ingest --input <csv> --client <k> --out <json>` | Run just the ingest/clean stage |
| `python -m src.mapping --client <k> --ingested <json> --out <json>` | Resolve the mapping plan only |
| `node src/transform.js --ingested <json> --plan <json> --out <json>` | Run just the Node transform |
| `python -m src.validate --transformed <json> --out <json>` | Validate transformed records |

Each stage reads/writes JSON, so you can run, inspect, and debug any single step in isolation.

---

## Example output (real run on the sample data)

`python main.py --client globex --input data/raw/globex.csv`:

```
[1/5] ingest    : 7 rows cleaned (1 dup rows dropped)
[2/5] mapping   : 4 rules (3 from shared layer, 1 overrides)
[3/5] transform : Node.js reshaped records into target CRM schema
[4/5] validate  : 4 valid, 3 flagged

 Mapping (source -> target CRM field):
| source column   | target field | transform      | resolved via              |
|-----------------|--------------|----------------|---------------------------|
| primary_contact | email        | lowercase_trim | client_override           |
| full_name       | first_name   | split_first    | common_patterns:full_name |
| full_name       | last_name    | split_last     | common_patterns:full_name |
| signup_date     | join_date    | normalize_date | common_patterns:join_date |

 Knowledge-layer reuse: 3/4 target fields resolved from the shared layer; 1 override.

 Flagged records:
   row 3: last_name: required field is missing        (single-token name "Cher")
   row 5: email: 'invalid_email_here' is not a valid email
   row 6: join_date: required field is missing        (unparseable "not-a-date")
```

Clean, load-ready output (`data/output/globex_clean.csv`):

```csv
email,first_name,last_name,join_date
barbara.liskov@example.com,Barbara,Liskov,2020-04-15
donald.knuth@example.com,Donald,Knuth,2015-11-02
radia.perlman@example.com,Radia,Perlman,2018-07-30
tim.berners-lee@example.com,Tim Berners,Lee,2016-05-20
```

Note how the **ACME** run (separate `First`/`Last` columns, `M/D/YYYY` dates) and the **GLOBEX** run (single `full_name`, ISO dates) both land in the identical `{first_name, last_name, email, join_date}` schema — driven by the same shared patterns.

---

## Project structure

```
day-11-migrateforge/
├── README.md
├── Dockerfile                    # Python + Node in one image
├── requirements.txt / package.json
├── main.py                       # pipeline orchestrator (Python↔Node hand-off)
├── configs/
│   ├── target_schema.yaml        # the destination CRM schema
│   ├── common_patterns.yaml      # ← the reusable knowledge layer
│   ├── client_acme.yaml          # example client 1 (delta only)
│   └── client_globex.yaml        # example client 2 (delta only)
├── data/
│   ├── raw/                      # messy sample CSVs (deliberately inconsistent)
│   └── output/                   # clean results + migration reports
├── src/
│   ├── ingest.py                 # [1] clean + profile
│   ├── mapping.py                # [2] resolve patterns + optional AI draft
│   ├── transform.js              # [3] Node.js schema translation
│   ├── validate.py               # [4] schema/type/uniqueness checks
│   └── report.py                 # [5] terminal / JSON / CSV / HTML report
├── tests/                        # pytest (Python) + node:test (JS)
└── .github/workflows/ci.yml      # tests + e2e smoke test on every push
```

## Testing

```bash
pytest -q          # 12 Python tests: ingest, mapping/inheritance, validation
node --test        # 7 Node tests: date parsing, name splitting, transforms
```

CI (GitHub Actions) runs both suites plus a full end-to-end run of both sample clients on every push.

## Tech stack

`Python 3.11` · `pandas` · `PyYAML` · `Node.js 18+` · `Docker` · `GitHub Actions` · optional `Anthropic API`

---

## Honesty notes

- This is a **portfolio/demo** toolkit, not a production system handling real PII. The sample "client" data is fictional.
- The AI step **drafts a mapping suggestion that a human validates** — it does not autonomously migrate data. Every AI suggestion is tagged `REQUIRES_HUMAN_VALIDATION` and surfaced in the report, never auto-applied.
- Everything documented here is implemented and covered by tests: Python core (ingest/validate/report), the config-driven knowledge layer with inheritance + overrides, the Node.js transform stage, and the optional AI draft (with a transparent local heuristic fallback so it runs offline and in CI).

> Part of a daily build series — one production-quality tool per day. Day 11.
