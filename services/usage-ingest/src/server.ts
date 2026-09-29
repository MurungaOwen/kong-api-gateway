import { createServer } from "node:http";
import { type Source, UsageStore, fromMeter, normalize, toEvent } from "./usage.js";

const stores: Record<Source, UsageStore> = {
  "http-log": new UsageStore(),
  "billing-meter": new UsageStore(),
};
const currentMonth = () => new Date().toISOString().slice(0, 7);

function readBody(req: import("node:http").IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let s = "";
    req.on("data", (c) => (s += c));
    req.on("end", () => resolve(s));
    req.on("error", reject);
  });
}

const json = (res: import("node:http").ServerResponse, code: number, body: unknown) => {
  res.writeHead(code, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};

export const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://x");
  if (req.method === "POST" && url.pathname === "/ingest") {
    try {
      const entries = normalize(JSON.parse(await readBody(req)));
      let accepted = 0;
      for (const e of entries) {
        const ev = toEvent(e);
        if (ev) {
          stores["http-log"].record(ev);
          accepted++;
        }
      }
      return json(res, 202, { received: entries.length, billable: accepted });
    } catch {
      return json(res, 400, { error: "invalid json" });
    }
  }
  if (req.method === "POST" && url.pathname === "/events") {
    try {
      const events = normalize(JSON.parse(await readBody(req)));
      let accepted = 0;
      for (const e of events) {
        const ev = fromMeter(e as never);
        if (ev) {
          stores["billing-meter"].record(ev);
          accepted++;
        }
      }
      return json(res, 202, { received: events.length, billable: accepted });
    } catch {
      return json(res, 400, { error: "invalid json" });
    }
  }
  const cmp = url.pathname.match(/^\/compare\/([^/]+)$/);
  if (req.method === "GET" && cmp) {
    const c = decodeURIComponent(cmp[1]);
    const month = url.searchParams.get("month") ?? currentMonth();
    return json(res, 200, {
      "http-log": stores["http-log"].summary(c, month),
      "billing-meter": stores["billing-meter"].summary(c, month),
    });
  }
  const m = url.pathname.match(/^\/usage\/([^/]+)$/);
  if (req.method === "GET" && m) {
    const month = url.searchParams.get("month") ?? currentMonth();
    const source = (url.searchParams.get("source") ?? "http-log") as Source;
    if (!stores[source]) return json(res, 400, { error: "unknown source" });
    return json(res, 200, stores[source].summary(decodeURIComponent(m[1]), month));
  }
  if (req.method === "GET" && url.pathname === "/usage") return json(res, 200, [...new Set(Object.values(stores).flatMap((x) => x.consumers()))].sort());
  if (url.pathname === "/health") return json(res, 200, { status: "ok" });
  json(res, 404, { error: "not found" });
});

if (process.env.NODE_ENV !== "test") {
  server.listen(Number(process.env.PORT ?? 8100));
}
