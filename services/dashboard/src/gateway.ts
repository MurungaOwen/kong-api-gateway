import { signJwt } from "./jwt.js";

export interface Config {
  kongUrl: string; // Kong proxy, e.g. http://kong:8000
  ingestUrl: string; // usage-ingest, read directly (internal service)
  jwtSecret: string;
}

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call(url: string, init: RequestInit = {}): Promise<unknown> {
  let res: Response;
  try {
    res = await fetch(url, { ...init, signal: AbortSignal.timeout(10_000) });
  } catch (e) {
    throw new HttpError(502, `upstream unreachable: ${url} (${(e as Error).message})`);
  }
  const text = await res.text();
  if (!res.ok) throw new HttpError(res.status === 401 ? 502 : res.status, `${url} -> ${res.status} ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : null;
}

export class Gateway {
  constructor(private cfg: Config) {}

  /** Billing admin calls go THROUGH Kong, authenticated with a short-lived JWT. */
  billing(method: string, path: string, body?: unknown) {
    return call(`${this.cfg.kongUrl}/billing${path}`, {
      method,
      headers: {
        authorization: `Bearer ${signJwt(this.cfg.jwtSecret)}`,
        ...(body ? { "content-type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  }

  ingest(path: string) {
    return call(`${this.cfg.ingestUrl}${path}`);
  }

  /** Call the metered API as a customer (uses their API key) and return the status code. */
  async asCustomer(apiKey: string, path: string): Promise<number> {
    try {
      const res = await fetch(`${this.cfg.kongUrl}${path}`, {
        headers: { apikey: apiKey },
        signal: AbortSignal.timeout(10_000),
      });
      await res.arrayBuffer();
      return res.status;
    } catch {
      return 0;
    }
  }
}
