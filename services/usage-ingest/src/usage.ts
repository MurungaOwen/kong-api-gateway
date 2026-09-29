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
  units: number; // billing weight; 1 for http-log
}

export type Source = "http-log" | "billing-meter";

/** Event emitted by the Lua billing-meter plugin (already filtered to billable). */
export interface MeterEvent {
  consumer?: string;
  route?: string;
  units?: number;
  status?: number;
  ts?: number;
}

export function fromMeter(e: MeterEvent): UsageEvent | null {
  if (!e.consumer) return null;
  return {
    consumer: e.consumer,
    route: e.route ?? "unknown",
    month: new Date(e.ts ?? Date.now()).toISOString().slice(0, 7),
    status: e.status ?? 200,
    units: Number.isFinite(e.units) && (e.units as number) > 0 ? (e.units as number) : 1,
  };
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
    units: 1,
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
    routes.set(ev.route, (routes.get(ev.route) ?? 0) + ev.units);
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
