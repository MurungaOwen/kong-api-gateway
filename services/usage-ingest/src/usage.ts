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
  ts: number; // epoch ms
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
    ts: e.ts ?? Date.now(),
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
    ts,
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

/** Keeps every event in memory (fine at demo scale) and hands each new one to `persist`. */
export class UsageStore {
  private events: UsageEvent[] = [];

  constructor(private persist?: (ev: UsageEvent) => void) {}

  record(ev: UsageEvent, replay = false): void {
    this.events.push(ev);
    if (!replay) this.persist?.(ev);
  }

  private select(consumer: string, month: string): UsageEvent[] {
    return this.events.filter((e) => e.consumer === consumer && e.month === month);
  }

  summary(consumer: string, month: string) {
    const by_route: Record<string, number> = {};
    let total = 0;
    const evs = this.select(consumer, month);
    for (const e of evs) {
      by_route[e.route] = (by_route[e.route] ?? 0) + e.units;
      total += e.units;
    }
    return { consumer, month, total, calls: evs.length, by_route };
  }

  /** Units and calls per UTC day, oldest first (only days with traffic). */
  daily(consumer: string, month: string) {
    const days = new Map<string, { day: string; units: number; calls: number }>();
    for (const e of this.select(consumer, month)) {
      const day = new Date(e.ts).toISOString().slice(0, 10);
      const d = days.get(day) ?? { day, units: 0, calls: 0 };
      d.units += e.units;
      d.calls += 1;
      days.set(day, d);
    }
    return [...days.values()].sort((a, b) => a.day.localeCompare(b.day));
  }

  /** Newest first. */
  recent(consumer: string, limit = 25): UsageEvent[] {
    return this.events
      .filter((e) => e.consumer === consumer)
      .slice(-limit)
      .reverse();
  }

  overview(month: string) {
    return this.consumers().map((c) => this.summary(c, month));
  }

  consumers(): string[] {
    return [...new Set(this.events.map((e) => e.consumer))].sort();
  }
}
