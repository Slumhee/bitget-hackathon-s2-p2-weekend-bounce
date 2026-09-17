#!/usr/bin/env bash
# P2 Weekend Bounce Harvester — one-command reproduction (portable, any machine)
# Requirements: Python 3.9+ with pandas & numpy. No API key needed.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "ERROR: python3 not found (set PYTHON=... to override)"; exit 1; }

# dependency check with actionable message
"$PY" - <<'EOF_CHECK' || { echo "ERROR: missing deps. Install with:  pip install pandas numpy"; exit 1; }
import sys
try:
    import pandas, numpy
    assert sys.version_info >= (3, 9), "Python >= 3.9 required"
except AssertionError as e:
    print("ERROR:", e); sys.exit(1)
except ImportError as e:
    print("ERROR:", e); sys.exit(1)
print("deps OK: pandas", pandas.__version__, "| numpy", numpy.__version__)
EOF_CHECK

# data presence check
[ -d pair_1m ] && [ -d pair_funding ] && [ -f btc_1m.jsonl ] || {
  echo "ERROR: data dirs missing (pair_1m/, pair_funding/, btc_1m.jsonl)"; exit 1; }

echo "=== [1/5] Eligibility audit + IS symbol selection (60d) ==="
"$PY" study11_is.py

echo "=== [2/5] OOS evaluation (30d, reads frozen config only) ==="
"$PY" study11_oos.py

echo "=== [3/5] Diagnostics: cost curve / LOO / synthetic ticks / resampling ==="
"$PY" study11_extra.py

echo "=== [4/5] Monte Carlo (2000 sims) ==="
"$PY" monte_carlo.py

echo "=== [5/5] Sync results to ../data and rebuild HTML report ==="
cp -f eligible_universe.csv is_symbol_scores.csv strategy_frozen_config.json \
      trade_log.csv weekend_returns.csv portfolio_equity.csv asset_stats.csv \
      cost_sensitivity.csv loo_asset.csv loo_weekend.csv btc_beta_analysis.csv \
      resampling_diagnostics.csv synthetic_tick_stress.csv \
      is_results.json oos_results.json ../data/
( cd .. && "$PY" build_html.py )

echo ""
echo "DONE. Open $(cd .. && pwd)/index.html for the report."
