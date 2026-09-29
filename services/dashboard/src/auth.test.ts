import test from "node:test";
import assert from "node:assert/strict";
import type { AddressInfo } from "node:net";

process.env.NODE_ENV = "test";
process.env.DASHBOARD_PASSWORD = "s3cret";
const { server } = await import("./server.js"); // read after the env is set

test("dashboard requires the password when DASHBOARD_PASSWORD is set", async (t) => {
  await new Promise<void>((r) => server.listen(0, r));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const basic = (pw: string) => ({ authorization: "Basic " + Buffer.from(`admin:${pw}`).toString("base64") });

  assert.equal((await fetch(`${base}/healthz`)).status, 200); // probes stay open
  const anon = await fetch(`${base}/`);
  assert.equal(anon.status, 401);
  assert.match(anon.headers.get("www-authenticate") ?? "", /Basic/);
  assert.equal((await fetch(`${base}/`, { headers: basic("wrong") })).status, 401);
  assert.equal((await fetch(`${base}/api/overview`, { headers: basic("") })).status, 401);
  assert.equal((await fetch(`${base}/`, { headers: basic("s3cret") })).status, 200);
});
