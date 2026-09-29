/** Shapes the dashboard API returns; pure so they can be unit-tested. */
export interface ApiKey { id: number; label: string; api_key: string; created_at: string }
export interface Consumer { name: string; plan: string; created_at: string; keys: ApiKey[] }
export interface UsageSummary { consumer: string; total: number; calls: number; by_route: Record<string, number> }
export interface Invoice { total_cents: number; usage: { included: number } }

export interface Row {
  name: string;
  plan: string;
  units: number;
  calls: number;
  included: number;
  percent_used: number;
  invoice_cents: number;
}

export function buildOverview(consumers: Consumer[], usage: UsageSummary[], invoices: Record<string, Invoice>) {
  const byName = new Map(usage.map((u) => [u.consumer, u]));
  const rows: Row[] = consumers.map((c) => {
    const u = byName.get(c.name);
    const inv = invoices[c.name];
    const included = inv?.usage.included ?? 0;
    const units = u?.total ?? 0;
    return {
      name: c.name,
      plan: c.plan,
      units,
      calls: u?.calls ?? 0,
      included,
      percent_used: included ? Math.round((units / included) * 1000) / 10 : 0,
      invoice_cents: inv?.total_cents ?? 0,
    };
  });
  rows.sort((a, b) => b.units - a.units || a.name.localeCompare(b.name));
  return {
    totals: {
      subscribers: rows.length,
      units: rows.reduce((s, r) => s + r.units, 0),
      calls: rows.reduce((s, r) => s + r.calls, 0),
      revenue_cents: rows.reduce((s, r) => s + r.invoice_cents, 0),
    },
    rows,
  };
}

