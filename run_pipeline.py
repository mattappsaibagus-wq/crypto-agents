#!/usr/bin/env python3
"""
run_pipeline.py — Crypto Multi-Agent Team orchestrator.

Pipeline:
  Phase 1 (parallel concept): microcap, whale, news each scan independently
  Phase 2: due diligence reviews everything Phase 1 wrote to the bus
  Phase 3: advisor reads the full bus + DD + memory, writes the report

Usage:
  python3 run_pipeline.py          # full run
  python3 run_pipeline.py --coin BTC   # add a coin to the watch scan
  python3 run_pipeline.py --quiet  # suppress per-agent chatter
"""
import argparse
import json
import os
import sys
import time
import warnings

# System Python uses LibreSSL; quiet the irrelevant urllib3 notice
warnings.filterwarnings("ignore", message=r"urllib3 v2 only supports.*")

sys.path.insert(0, os.path.dirname(__file__))

from agents.microcap import MicroCapFinder   # noqa: E402
from agents.whale import WhaleDetector      # noqa: E402
from agents.news import NewsScanner         # noqa: E402
from agents.dd import DueDiligence          # noqa: E402
from agents.advisor import InvestmentAdvisor  # noqa: E402


def clear_bus():
    """Start a fresh run with an empty signal bus."""
    bus = os.path.join(os.path.dirname(__file__), "data", "signals.json")
    if not os.path.exists(bus):
        return
    with open(bus, "w") as f:
        json.dump([], f)


def main():
    ap = argparse.ArgumentParser(description="Crypto multi-agent team")
    ap.add_argument("--coin", help="Extra coin symbol to focus news on")
    ap.add_argument("--no-clear", action="store_true",
                    help="Keep previous signals before this run")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not args.no_clear:
        clear_bus()

    banner = "╔══════════════════════════════════════════╗\n" \
             "║   Crypto Agent Team — market scan        ║\n" \
             "╚══════════════════════════════════════════╝"
    print(banner)

    # ── Phase 1 — parallel-ish agents ─────────────────────────────
    print("\n▶ Phase 1: discovery")
    t0 = time.time()
    agents = [
        MicroCapFinder(),
        WhaleDetector(),
        NewsScanner(),
    ]
    if args.coin:
        news_results = agents[2].execute(coins=[args.coin.upper()])
    else:
        news_results = agents[2].execute(coins=None)

    micro_results = agents[0].execute()
    time.sleep(0.4)  # be a gracious free-API citizen
    whale_results = agents[1].execute()
    t1 = time.time()
    print(f"  ✓ Phase 1 complete in {t1 - t0:.1f}s")

    # ── Phase 2 — due diligence ──────────────────────────────────
    print("\n▶ Phase 2: due diligence")
    dd = DueDiligence()
    dd_results = dd.execute()
    print(f"  ✓ Phase 2 complete")

    # ── Phase 3 — advisor ─────────────────────────────────────────
    print("\n▶ Phase 3: investment advisor")
    advisor = InvestmentAdvisor()
    results = advisor.execute()
    t2 = time.time()
    print(f"  ✓ Phase 3 complete — total {t2 - t0:.1f}s")

    # Signal counts
    from collections import Counter
    with open(os.path.join(os.path.dirname(__file__), "data", "signals.json")) as f:
        bus = json.load(f)
    counts = Counter(s.get("agent", "?") for s in bus)
    print(f"\n📡 Signal bus: {len(bus)} signals — " +
          ", ".join(f"{k}={v}" for k, v in counts.items()))

    # Top verdicts summary
    print("\nTop verdicts:")
    for v in results[:8]:
        mark = {"BUY": "🟢", "WATCH": "🟡", "AVOID": "🔴"}[v["action"]]
        dd_s = f" dd={v['dd']}" if v["dd"] else ""
        print(f"  {mark} {v['coin']:10s} {v['action']:6s} score={v['score']:+.3f} signals={v['signals']}{dd_s}")

    print("\nDone. Full report in data/reports/")
    return 0


if __name__ == "__main__":
    sys.exit(main())