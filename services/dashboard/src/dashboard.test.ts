import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { signJwt } from "./jwt.js";
import { buildOverview } from "./views.js";

test("jwt is a valid HS256 token with iss and exp", () => {
  const now = Date.UTC(2026, 8, 29);
  const [h, b, s] = signJwt("secret", "dashboard", 60, now).split(".");
  assert.deepEqual(JSON.parse(Buffer.from(h, "base64url").toString()), { alg: "HS256", typ: "JWT" });
  assert.deepEqual(JSON.parse(Buffer.from(b, "base64url").toString()), { iss: "dashboard", exp: now / 1000 + 60 });
  assert.equal(s, createHmac("sha256", "secret").update(`${h}.${b}`).digest("base64url"));
});

test("overview merges consumers, usage and invoices; busiest first", () => {
  const consumers = [
    { name: "quiet", plan: "free", created_at: "", keys: [] },
    { name: "busy", plan: "pro", created_at: "", keys: [] },
  ];
  const usage = [{ consumer: "busy", total: 50_000, calls: 10_000, by_route: {} }];
  const invoices = {
    quiet: { total_cents: 0, usage: { included: 1000 } },
    busy: { total_cents: 4900, usage: { included: 100_000 } },
  };
  const o = buildOverview(consumers, usage, invoices);
  assert.deepEqual(o.rows.map((r) => r.name), ["busy", "quiet"]);
  assert.equal(o.rows[0].percent_used, 50);
  assert.deepEqual(o.totals, { subscribers: 2, units: 50_000, calls: 10_000, revenue_cents: 4900 });
});
