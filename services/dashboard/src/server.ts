import { timingSafeEqual } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { Gateway, HttpError } from "./gateway.js";
import { buildOverview, type Consumer, type Invoice, type UsageSummary } from "./views.js";

const gw = new Gateway({
  kongUrl: process.env.KONG_URL ?? "http://kong:8000",
  ingestUrl: process.env.INGEST_URL ?? "http://usage-ingest:8100",
  jwtSecret: process.env.JWT_SECRET ?? "dev-secret-change-me-please-32b!",
});
const password = process.env.DASHBOARD_PASSWORD ?? ""; // empty = no login (local demo only)
const page = readFileSync(new URL("../public/index.html", import.meta.url), "utf8");
const month = (u: URL) => u.searchParams.get("month") ?? new Date().toISOString().slice(0, 7);

function send(res: ServerResponse, code: number, body: unknown, type = "application/json") {
  res.writeHead(code, { "content-type": type });
  res.end(type === "application/json" ? JSON.stringify(body) : String(body));
}

async function readJson(req: IncomingMessage): Promise<Record<string, unknown>> {
  let s = "";
  for await (const chunk of req) s += chunk;
  return s ? JSON.parse(s) : {};
}

async function findConsumer(name: string): Promise<Consumer> {
  return (await gw.billing("GET", `/consumers/${encodeURIComponent(name)}`)) as Consumer;
}

/** Optional HTTP Basic auth (any username, the configured password). /healthz stays open for probes. */
function authorized(req: IncomingMessage): boolean {
  if (!password) return true;
  const given = Buffer.from((req.headers.authorization ?? "").replace(/^Basic /i, ""), "base64").toString();
  const supplied = Buffer.from(given.slice(given.indexOf(":") + 1));
  const expected = Buffer.from(password);
  return supplied.length === expected.length && timingSafeEqual(supplied, expected);
}

async function route(req: IncomingMessage, res: ServerResponse) {
  const url = new URL(req.url ?? "/", "http://x");
  if (url.pathname !== "/healthz" && !authorized(req)) {
    res.writeHead(401, { "www-authenticate": 'Basic realm="billing dashboard"' });
    return res.end("login required");
  }
  const m = month(url);
  const p = url.pathname;
  let match: RegExpMatchArray | null;

  if (req.method === "GET" && p === "/") return send(res, 200, page, "text/html; charset=utf-8");
  if (req.method === "GET" && p === "/healthz") return send(res, 200, { status: "ok" });

  if (req.method === "GET" && p === "/api/overview") {
    const consumers = (await gw.billing("GET", "/consumers")) as Consumer[];
    const usage = (await gw.ingest(`/overview?month=${m}`)) as UsageSummary[];
    const invoices: Record<string, Invoice> = {};
    await Promise.all(
      consumers.map(async (c) => {
        invoices[c.name] = (await gw.billing("GET", `/invoices/${encodeURIComponent(c.name)}?month=${m}`)) as Invoice;
      }),
    );
    const [plans, endpoints, upstreams] = await Promise.all([gw.billing("GET", "/plans"), gw.billing("GET", "/endpoints"), gw.billing("GET", "/upstreams")]);
    return send(res, 200, { month: m, plans, endpoints, upstreams, ...buildOverview(consumers, usage, invoices) });
  }

  if ((match = p.match(/^\/api\/subscribers\/([^/]+)$/)) && req.method === "GET") {
    const name = decodeURIComponent(match[1]);
    const c = await findConsumer(name);
    const q = encodeURIComponent(name);
    const [daily, recent, invoice] = await Promise.all([
      gw.ingest(`/usage/${q}/daily?month=${m}`),
      gw.ingest(`/usage/${q}/recent?limit=25`),
      gw.billing("GET", `/invoices/${q}?month=${m}`),
    ]);
    return send(res, 200, { month: m, name, plan: c.plan, created_at: c.created_at, keys: c.keys, daily, recent, invoice });
  }

  if (req.method === "POST" && p === "/api/subscribers") {
    const body = await readJson(req);
    return send(res, 201, await gw.billing("POST", "/consumers", { name: body.name, plan: body.plan ?? "free" }));
  }

  if ((match = p.match(/^\/api\/subscribers\/([^/]+)\/plan$/)) && req.method === "PUT") {
    const body = await readJson(req);
    return send(res, 200, await gw.billing("PUT", `/consumers/${match[1]}/plan`, { plan: body.plan }));
  }

  if ((match = p.match(/^\/api\/subscribers\/([^/]+)\/traffic$/)) && req.method === "POST") {
    const body = await readJson(req);
    const path = String(body.path ?? "/api/quote");
    const catalog = (await gw.billing("GET", "/endpoints")) as { path: string }[];
    if (!catalog.some((e) => e.path === path)) throw new HttpError(422, `path must be one of ${catalog.map((e) => e.path).join(", ")}`);
    const count = Math.min(Math.max(Number(body.count) || 1, 1), 50);
    const c = await findConsumer(decodeURIComponent(match[1]));
    if (!c.keys.length) throw new HttpError(409, "subscriber has no active API key; generate one first");
    const tally: Record<string, number> = {};
    for (let i = 0; i < count; i++) {
      const code = String(await gw.asCustomer(c.keys[0].api_key, path));
      tally[code] = (tally[code] ?? 0) + 1;
    }
    return send(res, 200, { path, count, statuses: tally });
  }

  if ((match = p.match(/^\/api\/subscribers\/([^/]+)$/)) && req.method === "DELETE") {
    await gw.billing("DELETE", `/consumers/${match[1]}`);
    return send(res, 200, { deleted: decodeURIComponent(match[1]) });
  }

  if ((match = p.match(/^\/api\/subscribers\/([^/]+)\/keys$/)) && req.method === "POST") {
    const body = await readJson(req);
    return send(res, 201, await gw.billing("POST", `/consumers/${match[1]}/keys`, { label: body.label || "generated" }));
  }

  if ((match = p.match(/^\/api\/subscribers\/([^/]+)\/keys\/(\d+)$/)) && req.method === "DELETE") {
    await gw.billing("DELETE", `/consumers/${match[1]}/keys/${match[2]}`);
    return send(res, 200, { revoked: Number(match[2]) });
  }

  if (req.method === "POST" && p === "/api/plans") {
    return send(res, 201, await gw.billing("POST", "/plans", await readJson(req)));
  }

  if ((match = p.match(/^\/api\/plans\/([^/]+)$/))) {
    if (req.method === "PUT") return send(res, 200, await gw.billing("PUT", `/plans/${match[1]}`, await readJson(req)));
    if (req.method === "DELETE") {
      await gw.billing("DELETE", `/plans/${match[1]}`);
      return send(res, 200, { deleted: decodeURIComponent(match[1]) });
    }
  }

  if (req.method === "POST" && p === "/api/endpoints") {
    return send(res, 201, await gw.billing("POST", "/endpoints", await readJson(req)));
  }

  if ((match = p.match(/^\/api\/endpoints\/([^/]+)$/))) {
    if (req.method === "PUT") return send(res, 200, await gw.billing("PUT", `/endpoints/${match[1]}`, await readJson(req)));
    if (req.method === "DELETE") {
      await gw.billing("DELETE", `/endpoints/${match[1]}`);
      return send(res, 200, { deleted: decodeURIComponent(match[1]) });
    }
  }

  if (req.method === "POST" && p === "/api/upstreams") {
    return send(res, 201, await gw.billing("POST", "/upstreams", await readJson(req)));
  }

  if ((match = p.match(/^\/api\/upstreams\/([^/]+)$/))) {
    if (req.method === "PUT") return send(res, 200, await gw.billing("PUT", `/upstreams/${match[1]}`, await readJson(req)));
    if (req.method === "DELETE") {
      await gw.billing("DELETE", `/upstreams/${match[1]}`);
      return send(res, 200, { deleted: decodeURIComponent(match[1]) });
    }
  }

  // What Kong is actually running: the generated declarative config plus live target health.
  if (req.method === "GET" && p === "/api/gateway") {
    const [config, health, upstreams] = await Promise.all([
      gw.billing("GET", "/kong/config"),
      gw.billing("GET", "/kong/health"),
      gw.billing("GET", "/upstreams"),
    ]);
    return send(res, 200, { yaml: (config as { yaml: string }).yaml, health, upstreams });
  }
  if (req.method === "POST" && p === "/api/gateway/sync") return send(res, 200, await gw.billing("POST", "/kong/sync"));

  send(res, 404, { error: "not found" });
}

export const server = createServer((req, res) => {
  route(req, res).catch((e) => {
    const status = e instanceof HttpError ? e.status : e instanceof SyntaxError ? 400 : 500;
    send(res, status, { error: (e as Error).message });
  });
});

if (process.env.NODE_ENV !== "test") server.listen(Number(process.env.PORT ?? 3000));
