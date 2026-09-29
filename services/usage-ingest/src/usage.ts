/** One Kong http-log entry, reduced to the fields we use. */
export interface KongLogEntry {
  consumer?: { username?: string };
  route?: { name?: string };
  response?: { status?: number };
  started_at?: number; // epoch ms
}

export interface UsageEvent {
  consumer: string;
  route: string;
  month: string; // YYYY-MM (UTC)
  status: number;
}

/** Billable = identified consumer and non-error response (401/429/5xx are free). */
export function toEvent(e: KongLogEntry): UsageEvent | null {
  const consumer = e.consumer?.username;
  const status = e.response?.status;
  if (!consumer || status === undefined || status >= 400) return null;
  const ts = e.started_at ?? Date.now();
  return {
    consumer,
    route: e.route?.name ?? "unknown",
    month: new Date(ts).toISOString().slice(0, 7),
    status,
  };
}

/** http-log sends an object, or an array once queue batching is on. */
export function normalize(body: unknown): KongLogEntry[] {
  if (Array.isArray(body)) return body as KongLogEntry[];
  if (body && typeof body === "object") return [body as KongLogEntry];
  return [];
}

export class UsageStore {
  // consumer -> month -> route -> count
  private data = new Map<string, Map<string, Map<string, number>>>();

  record(ev: UsageEvent): void {
    const months = this.data.get(ev.consumer) ?? new Map();
    const routes = months.get(ev.month) ?? new Map();
    routes.set(ev.route, (routes.get(ev.route) ?? 0) + 1);
    months.set(ev.month, routes);
    this.data.set(ev.consumer, months);
  }

  summary(consumer: string, month: string) {
    const routes = this.data.get(consumer)?.get(month) ?? new Map<string, number>();
    const by_route = Object.fromEntries(routes);
    const total = [...routes.values()].reduce((a, b) => a + b, 0);
    return { consumer, month, total, by_route };
  }

  consumers(): string[] {
    return [...this.data.keys()].sort();
  }
}
