import { createServer } from "node:http";
import { UsageStore, normalize, toEvent } from "./usage.js";

const store = new UsageStore();

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
          store.record(ev);
          accepted++;
        }
      }
      return json(res, 202, { received: entries.length, billable: accepted });
    } catch {
      return json(res, 400, { error: "invalid json" });
    }
  }
  const m = url.pathname.match(/^\/usage\/([^/]+)$/);
  if (req.method === "GET" && m) {
    const month = url.searchParams.get("month") ?? new Date().toISOString().slice(0, 7);
    return json(res, 200, store.summary(decodeURIComponent(m[1]), month));
  }
  if (req.method === "GET" && url.pathname === "/usage") return json(res, 200, store.consumers());
  if (url.pathname === "/health") return json(res, 200, { status: "ok" });
  json(res, 404, { error: "not found" });
});

if (process.env.NODE_ENV !== "test") {
  server.listen(Number(process.env.PORT ?? 8100));
}
