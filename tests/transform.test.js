"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { normalizeDate, splitFirst, splitLast, lowercaseTrim, transform } =
  require("../src/transform.js");

test("normalizeDate handles US M/D/YYYY", () => {
  assert.strictEqual(normalizeDate("3/7/2021", "%m/%d/%Y"), "2021-03-07");
});

test("normalizeDate handles ISO passthrough", () => {
  assert.strictEqual(normalizeDate("2020-04-15", "%Y-%m-%d"), "2020-04-15");
});

test("normalizeDate rejects garbage and impossible dates", () => {
  assert.strictEqual(normalizeDate("not-a-date", "%Y-%m-%d"), null);
  assert.strictEqual(normalizeDate("2/30/2021", "%m/%d/%Y"), null);
});

test("split_first / split_last split a full name", () => {
  assert.strictEqual(splitFirst("Barbara Liskov"), "Barbara");
  assert.strictEqual(splitLast("Barbara Liskov"), "Liskov");
  // multi-token first name
  assert.strictEqual(splitFirst("Tim Berners Lee"), "Tim Berners");
  assert.strictEqual(splitLast("Tim Berners Lee"), "Lee");
});

test("single-token name yields null last name", () => {
  assert.strictEqual(splitFirst("Cher"), "Cher");
  assert.strictEqual(splitLast("Cher"), null);
});

test("lowercase_trim normalises email", () => {
  assert.strictEqual(lowercaseTrim("  ADA@Example.COM "), "ada@example.com");
});

test("transform applies a full plan end-to-end", () => {
  const ingested = { records: [{ full_name: "Grace Hopper", mail: "G@X.com", d: "12/9/2019" }] };
  const plan = {
    date_input_format: "%m/%d/%Y",
    rules: [
      { target: "first_name", source: "full_name", transform: "split_first" },
      { target: "last_name", source: "full_name", transform: "split_last" },
      { target: "email", source: "mail", transform: "lowercase_trim" },
      { target: "join_date", source: "d", transform: "normalize_date" },
    ],
  };
  const out = transform(ingested, plan);
  assert.deepStrictEqual(out[0], {
    first_name: "Grace", last_name: "Hopper",
    email: "g@x.com", join_date: "2019-12-09",
  });
});
