#!/usr/bin/env python3
"""
Build the static dashboard data for GitHub Pages.

Runs the agent pipeline (unless --no-run), then converts the latest report
and signals into a single docs/data.json that docs/index.html consumes.

Run locally:   python3 build_static.py            (runs a fresh scan)
               python3 build_static.py --no-run   (just re-render from last scan)
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")
SIGNALS_FILE = os.path.join(BASE_DIR, "data", "signals.json")
DOCS_DIR = os.path.join(BASE_DIR, "docs")


import re


def _clean_md(text):
    """Strip markdown emphasis (**...**) from a string."""
    return re.sub(r"\*\*([^*]*)\*\*", r"\1", text).strip()


def _parse_details(lines):
    """Extract structured fields from report detail lines, return (fields, cleaned).

        Recognised lines:
      Score: 0.167 | Signals: 1 | DD score: 0.6
      Suggested size: up to 1.0% of portfolio
      Why: ...
    """
    fields = {}
    cleaned = []
    for line in lines:
        text = _clean_md(line)
        if not text:
            continue
        # A single bullet may carry several pipe-separated fields, e.g.
        # "Score: 0.167 | Signals: 1 | DD score: 0.6". Parse each segment.
        segments = [s.strip() for s in text.split("|")]
        matched_any = False
        for seg in segments:
            m = re.match(r"Score:\s*([+-]?[\d.]+)", seg)
            if m:
                fields["score"] = float(m.group(1))
                matched_any = True
                continue
            m = re.match(r"Signals:\s*(\d+)", seg)
            if m:
                fields["signals"] = int(m.group(1))
                matched_any = True
                continue
            m = re.match(r"DD score:\s*([+-]?[\d.]+)", seg)
            if m:
                fields["dd"] = float(m.group(1))
                matched_any = True
                continue
            m = re.match(r"Suggested size:\s*(.+)", seg)
            if m:
                fields["size"] = m.group(1).strip()
                matched_any = True
                continue
            m = re.match(r"Why:\s*(.+)", seg)
            if m:
                cleaned.append(m.group(1).strip())
                matched_any = True
                continue
        if not matched_any:
            cleaned.append(text)
    return fields, cleaned


def parse_report_cards(md, signals=None):
    """Convert the markdown report into structured card objects for the frontend."""
    cards = []
    current = None
    for line in md.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            if current:
                cards.append(current)
            title = line[3:].strip()
            action = "WATCH"
            if "BUY" in title:
                action = "BUY"
            elif "AVOID" in title:
                action = "AVOID"
            coin = title.split("—")[0].strip() if "—" in title else title
            coin = coin.lstrip("🟢🟡🔴 ").strip()
            current = {"coin": coin, "action": action, "details": []}
        elif current and (line.startswith("- **") or line.startswith("- ")):
            current["details"].append(line[2:].strip())
    if current:
        cards.append(current)

    # Parse markdown detail lines into structured fields so the dashboard
    # gets numeric score / signals / dd values and clean prose details.
    for card in cards:
        fields, details = _parse_details(card.pop("details"))
        card["score"] = fields.get("score", 0.0)
        if "signals" in fields:
            card["signals"] = fields["signals"]
        if "dd" in fields:
            card["dd"] = fields["dd"]
        if "size" in fields:
            card["size"] = fields["size"]
        card["details"] = details
    # Attach the CoinGecko id from signals.json so the dashboard can fetch
    # charts/stats with the correct id (tickers alone 404 on CoinGecko).
    if signals:
        ticker_to_id = {}
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            sym = str(sig.get("coin") or "").upper()
            cid = (sig.get("details") or {}).get("coin_id")
            if sym and cid and sym not in ticker_to_id:
                ticker_to_id[sym] = cid
        for card in cards:
            sym = str(card.get("coin") or "").upper()
            if sym in ticker_to_id:
                card["coin_id"] = ticker_to_id[sym]
    return cards


def get_latest_report():
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "report_*.md")))
    if not files:
        return None, None
    with open(files[-1], "r") as f:
        return f.read(), files[-1]


def run_pipeline():
    """Run the full agent pipeline. Non-fatal on failure (returns last report)."""
    print("Running agent pipeline...")
    try:
        subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "run_pipeline.py")],
            capture_output=True, text=True, timeout=180, cwd=BASE_DIR,
        )
    except Exception as e:
        print(f"  pipeline issue (continuing with last report): {e}")


def workflow_url():
    """GitHub Actions sets GITHUB_REPOSITORY=owner/repo. Local runs fall back."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        return f"https://github.com/{repo}/actions/workflows/scan.yml"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", action="store_true",
                    help="don't run the pipeline, just re-render last report")
    args = ap.parse_args()

    if not args.no_run:
        run_pipeline()

    md, path = get_latest_report()
    if md is None:
        print("No report found. Run a scan first.")
        sys.exit(1)

    # Timestamp from the report filename if possible
    ts = None
    fname = os.path.basename(path).replace("report_", "").replace(".md", "")
    try:
        ts = datetime.strptime(fname, "%Y%m%d_%H%M%S").isoformat()
    except Exception:
        ts = datetime.now().isoformat()

    signals = []
    if os.path.exists(SIGNALS_FILE):
        with open(SIGNALS_FILE, "r") as f:
            signals = json.load(f)

    # Map ticker -> CoinGecko id from the pipeline's own resolution
    # (signals[].details.coin_id). The dashboard needs the *id*
    # (e.g. "celer-network"), not the ticker ("CELR"), for chart/stats calls.
    # First occurrence wins: later duplicate signals from other agents may
    # carry coin_id=None and must not overwrite a real mapping.
    coin_id_map = {}
    for s in signals:
        sym = (s.get("coin") or "").upper()
        cid = (s.get("details") or {}).get("coin_id")
        if sym and cid and sym not in coin_id_map:
            coin_id_map[sym] = cid

    # Fallback for tickers the current signals.json doesn't cover:
    # reuse the pipeline's own resolver (curated KNOWN_IDS + ranked list).
    try:
        sys.path.insert(0, BASE_DIR)
        from agents.base import coin_id_for as _coin_id_for
        _fallback_ok = True
    except Exception as e:
        print(f"  coin_id fallback resolver unavailable: {e}")
        _fallback_ok = False

    cards = parse_report_cards(md)
    for c in cards:
        sym = (c.get("coin") or "").upper()
        cid = coin_id_map.get(sym)
        if not cid and _fallback_ok:
            try:
                cid = _coin_id_for(sym)
            except Exception:
                cid = None
        if cid:
            c["coin_id"] = cid
        else:
            print(f"  note: no CoinGecko id resolved for {sym} (chart will try ticker)")

    data = {
        "timestamp": ts,
        "cards": cards,
        "signals": len(signals),
        "workflow_url": workflow_url(),
    }

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "data.json"), "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote docs/data.json: {len(data['cards'])} cards, {data['signals']} signals")


if __name__ == "__main__":
    main()
