#!/usr/bin/env bash
# Seed the running stack with subscribers and traffic so the dashboard has something to show.
#   scripts/demo.sh            # then open http://localhost:3000
set -euo pipefail
BASE=${BASE:-http://localhost:8000}
TOKEN=$(python3 "$(dirname "$0")/token.py")

admin() { curl -fsS -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' "$@"; }

# create <name> <plan>  -> prints the subscriber's first API key (creates the subscriber if new)
create() {
  admin -X POST "$BASE/billing/consumers" -d "{\"name\":\"$1\",\"plan\":\"$2\"}" >/dev/null 2>&1 || true
  admin "$BASE/billing/consumers/$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["keys"][0]["api_key"])'
}

# hit <key> <path> <count>  -> prints a status-code tally, e.g. "200x3 429x2"
# Calls are paced (~15/s) so the pro plan's 20/s burst limit isn't what we trip.
hit() {
  for _ in $(seq "$3"); do curl -s -o /dev/null -w '%{http_code}\n' "$BASE$2" -H "apikey: $1"; sleep 0.06; done \
    | sort | uniq -c | awk '{printf "%sx%s ", $2, $1}'
  echo
}

echo "Creating subscribers..."
ACME=$(create acme pro); GLOBEX=$(create globex free); INITECH=$(create initech enterprise)

echo "acme (pro)         quote x40:  $(hit "$ACME" /api/quote 40)"
echo "acme (pro)         report x10: $(hit "$ACME" /api/report 10)"
echo "globex (free)      quote x15:  $(hit "$GLOBEX" /api/quote 15)   <- free is 10/min: expect 10x200 then 429s"
echo "globex (free)      report x4:  $(hit "$GLOBEX" /api/report 4)   <- report is not in the free plan: expect 403"
echo "initech (enterprise) echo x20: $(hit "$INITECH" /api/echo 20)"
echo "initech (enterprise) report x25: $(hit "$INITECH" /api/report 25)"
echo
echo "Usage events land ~2s after the calls. Open http://localhost:3000"
