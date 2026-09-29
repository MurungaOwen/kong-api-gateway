import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";
import { UsageStore, type UsageEvent } from "./usage.js";

/** A store backed by an append-only JSON-lines file, replayed on startup. */
export function openStore(file?: string): UsageStore {
  if (!file) return new UsageStore();
  mkdirSync(dirname(file), { recursive: true });
  const store = new UsageStore((ev) => appendFileSync(file, JSON.stringify(ev) + "\n"));
  if (existsSync(file)) {
    for (const line of readFileSync(file, "utf8").split("\n")) {
      if (!line.trim()) continue;
      try {
        store.record(JSON.parse(line) as UsageEvent, true);
      } catch {
        // skip a torn last line rather than refusing to start
      }
    }
  }
  return store;
}
