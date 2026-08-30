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


def parse_report_cards(md):
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

    data = {
        "timestamp": ts,
        "cards": parse_report_cards(md),
        "signals": len(signals),
        "workflow_url": workflow_url(),
    }

    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(os.path.join(DOCS_DIR, "data.json"), "w") as f:
        json.dump(data, f, indent=2)
    print(f"Wrote docs/data.json: {len(data['cards'])} cards, {data['signals']} signals")


if __name__ == "__main__":
    main()
