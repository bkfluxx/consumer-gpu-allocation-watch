#!/usr/bin/env bash
# Live smoke test of the JSON API: start the server, call every endpoint with a
# free-tier and a pro-tier key, print the responses, then stop the server.
set -u
cd "$(dirname "$0")/.."
PORT="${PORT:-8787}"
TMP="$(mktemp -d)"
python3 -m cgw.cli serve --port "$PORT" > "$TMP/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null' EXIT
for _ in $(seq 60); do
  curl -sf "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1 && break
  sleep 0.25
done

PRO_KEY=$(python3 -c "import sys; sys.path.insert(0,'.'); from cgw import store; con = store.connect(); row = con.execute(\"SELECT key FROM api_keys WHERE tier='pro' LIMIT 1\").fetchone(); print(row['key'] if row else '')")

echo "=== /v1/health (no key)"
curl -s "http://127.0.0.1:$PORT/v1/health" | python3 tools/print_api.py health

echo
echo "=== /v1/meta (no key) - source freshness"
curl -s "http://127.0.0.1:$PORT/v1/meta" | python3 tools/print_api.py meta

echo
echo "=== no key on a protected endpoint -> 401"
curl -s -o "$TMP/401.json" -w "HTTP %{http_code}\n" "http://127.0.0.1:$PORT/v1/skus"
python3 tools/print_api.py error < "$TMP/401.json"

echo
echo "=== free key on a pro endpoint -> 403"
curl -s -o "$TMP/403.json" -w "HTTP %{http_code}\n" -H "X-API-Key: demo-free-key" \
  "http://127.0.0.1:$PORT/v1/forecasts/discontinuation"
python3 tools/print_api.py error < "$TMP/403.json"

echo
echo "=== pro key: discontinuation watchlist (top 3)"
curl -s -H "X-API-Key: $PRO_KEY" \
  "http://127.0.0.1:$PORT/v1/forecasts/discontinuation?limit=3" > "$TMP/disc.json"
python3 tools/print_api.py discontinuation < "$TMP/disc.json"

echo
echo "=== pro key: trigger levels already crossed"
curl -s -H "X-API-Key: $PRO_KEY" \
  "http://127.0.0.1:$PORT/v1/forecasts/price-triggers?already_above=true&limit=4" \
  > "$TMP/trig.json"
python3 tools/print_api.py triggers < "$TMP/trig.json"

echo
echo "=== pro key: allocation"
curl -s -H "X-API-Key: $PRO_KEY" "http://127.0.0.1:$PORT/v1/allocation" > "$TMP/alloc.json"
python3 tools/print_api.py allocation < "$TMP/alloc.json"

echo
echo "=== pro key: EOL signals"
curl -s -H "X-API-Key: $PRO_KEY" "http://127.0.0.1:$PORT/v1/signals?kind=eol&limit=3" \
  > "$TMP/sig.json"
python3 tools/print_api.py signals < "$TMP/sig.json"

echo
echo "=== free key: memory prints + rate-limit header"
curl -s -D "$TMP/head.txt" -o "$TMP/mem.json" -H "X-API-Key: demo-free-key" \
  "http://127.0.0.1:$PORT/v1/memory/latest"
grep -iE "^(HTTP|X-RateLimit)" "$TMP/head.txt"
python3 tools/print_api.py memory < "$TMP/mem.json"

echo
echo "=== server log (no tracebacks expected)"
if grep -q "Traceback" "$TMP/server.log"; then
  head -20 "$TMP/server.log"
else
  echo "clean"
fi
rm -rf "$TMP"
echo "=== done"
