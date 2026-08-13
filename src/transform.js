#!/usr/bin/env node
/*
 * Stage 3 — TRANSFORM (Node.js).
 *
 * Mirrors the client's real "Python cleans, Node translates into the CRM
 * schema" split. Reads:
 *    --ingested  cleaned records from stage 1 (Python)
 *    --plan      the resolved mapping plan from stage 2 (Python)
 * and emits target-schema records (JSON) to --out.
 *
 * All transforms are DETERMINISTIC — same input always yields same output.
 * No schema decisions are made here; Node only executes the plan Python built.
 */
"use strict";

const fs = require("fs");
const path = require("path");

// --------------------------------------------------------------------------
// deterministic field transforms
// --------------------------------------------------------------------------
function trim(v) {
  return v == null ? null : String(v).trim();
}

function lowercaseTrim(v) {
  return v == null ? null : String(v).trim().toLowerCase();
}

function splitFirst(v) {
  if (v == null) return null;
  const parts = String(v).trim().split(/\s+/);
  if (parts.length <= 1) return parts[0] || null; // single token => no first/last split
  return parts.slice(0, -1).join(" ");
}

function splitLast(v) {
  if (v == null) return null;
  const parts = String(v).trim().split(/\s+/);
  if (parts.length <= 1) return null; // single-token name has no surname -> flagged downstream
  return parts[parts.length - 1];
}

/*
 * Minimal strptime-style parser supporting the tokens MigrateForge needs
 * (%Y %y %m %d %H %M %S). Returns an ISO date string (YYYY-MM-DD) or null.
 * Deliberately strict: an unparseable value returns null so validation flags
 * it rather than silently guessing.
 */
function normalizeDate(value, fmt) {
  if (value == null) return null;
  const str = String(value).trim();
  const tokens = { "%Y": "(\\d{4})", "%y": "(\\d{2})", "%m": "(\\d{1,2})",
                   "%d": "(\\d{1,2})", "%H": "(\\d{1,2})", "%M": "(\\d{1,2})", "%S": "(\\d{1,2})" };
  const order = [];
  let regex = "^";
  let i = 0;
  while (i < fmt.length) {
    const two = fmt.slice(i, i + 2);
    if (tokens[two]) {
      regex += tokens[two];
      order.push(two);
      i += 2;
    } else {
      regex += fmt[i].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      i += 1;
    }
  }
  regex += "$";
  const m = str.match(new RegExp(regex));
  if (!m) return null;

  const parts = {};
  order.forEach((tok, idx) => (parts[tok] = parseInt(m[idx + 1], 10)));
  let year = parts["%Y"] != null ? parts["%Y"] : (parts["%y"] != null ? 2000 + parts["%y"] : null);
  const month = parts["%m"];
  const day = parts["%d"];
  if (year == null || month == null || day == null) return null;
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;

  // round-trip through Date to reject impossible calendar dates (e.g. 2/30)
  const d = new Date(Date.UTC(year, month - 1, day));
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) {
    return null;
  }
  const mm = String(month).padStart(2, "0");
  const dd = String(day).padStart(2, "0");
  return `${year}-${mm}-${dd}`;
}

function applyTransform(name, value, ctx) {
  switch (name) {
    case "trim": return trim(value);
    case "lowercase_trim": return lowercaseTrim(value);
    case "normalize_date": return normalizeDate(value, ctx.dateInputFormat);
    case "split_first": return splitFirst(value);
    case "split_last": return splitLast(value);
    default: return trim(value);
  }
}

// --------------------------------------------------------------------------
// main
// --------------------------------------------------------------------------
function parseArgs(argv) {
  const args = {};
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      args[argv[i].slice(2)] = argv[i + 1];
      i++;
    }
  }
  return args;
}

function transform(ingested, plan) {
  const ctx = { dateInputFormat: plan.date_input_format || "%Y-%m-%d" };
  const out = ingested.records.map((row) => {
    const target = {};
    for (const rule of plan.rules) {
      target[rule.target] = applyTransform(rule.transform, row[rule.source], ctx);
    }
    return target;
  });
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  if (!args.ingested || !args.plan) {
    console.error("Usage: node transform.js --ingested <in.json> --plan <plan.json> [--out <out.json>]");
    process.exit(1);
  }
  const ingested = JSON.parse(fs.readFileSync(path.resolve(args.ingested), "utf8"));
  const plan = JSON.parse(fs.readFileSync(path.resolve(args.plan), "utf8"));
  const records = transform(ingested, plan);
  const payload = JSON.stringify({ client: plan.client, target_schema: plan.target_schema, records }, null, 2);

  if (args.out) {
    fs.writeFileSync(path.resolve(args.out), payload);
    console.log(`Transformed ${records.length} records -> ${args.out}`);
  } else {
    process.stdout.write(payload + "\n");
  }
}

if (require.main === module) {
  main();
}

module.exports = { normalizeDate, splitFirst, splitLast, lowercaseTrim, transform };
