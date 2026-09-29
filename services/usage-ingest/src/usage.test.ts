import test from "node:test";
import assert from "node:assert/strict";
import { UsageStore, fromMeter, normalize, toEvent } from "./usage.js";

const t = Date.UTC(2026, 8, 29);

test("only identified, non-error calls are billable", () => {
  assert.equal(toEvent({ response: { status: 200 } }), null);
  assert.equal(toEvent({ consumer: { username: "a" }, response: { status: 429 } }), null);
  assert.deepEqual(
    toEvent({ consumer: { username: "a" }, route: { name: "r" }, response: { status: 200 }, started_at: t }),
    { consumer: "a", route: "r", month: "2026-09", status: 200, units: 1 },
  );
});

test("normalize handles object and array bodies", () => {
  assert.equal(normalize({}).length, 1);
  assert.equal(normalize([{}, {}]).length, 2);
  assert.equal(normalize("x").length, 0);
});

test("store aggregates per consumer/month/route", () => {
  const s = new UsageStore();
  for (const route of ["r1", "r1", "r2"]) s.record({ consumer: "a", route, month: "2026-09", status: 200, units: 1 });
  assert.deepEqual(s.summary("a", "2026-09"), { consumer: "a", month: "2026-09", total: 3, by_route: { r1: 2, r2: 1 } });
  assert.equal(s.summary("a", "2026-08").total, 0);
});

test("meter events carry weighted units", () => {
  assert.equal(fromMeter({}), null);
  const ev = fromMeter({ consumer: "a", route: "r", units: 5, ts: t })!;
  assert.equal(ev.units, 5);
  assert.equal(fromMeter({ consumer: "a", units: -3 })!.units, 1);
  const s = new UsageStore();
  s.record(ev);
  s.record(fromMeter({ consumer: "a", route: "r", ts: t })!);
  assert.equal(s.summary("a", "2026-09").total, 6);
});
