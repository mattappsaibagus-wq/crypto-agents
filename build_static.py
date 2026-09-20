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
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "data", "reports")
SIGNALS_FILE = os.path.join(BASE_DIR, "data", "signals.json")
DOCS_DIR = os.path.join(BASE_DIR, "docs")
# The market cache lives inside docs/ so the CI workflow (which only commits
# docs/) carries it between runs. It holds the per-coin 30-day daily series,
# which is the one thing the batch endpoint cannot supply.
MARKET_CACHE_FILE = os.path.join(DOCS_DIR, "market-cache.json")

GECKO_API = "https://api.coingecko.com/api/v3"
# Price, 24h high/low, 24h/7d change and the 7d hourly sparkline all arrive in
# ONE /coins/markets batch call, so charts never depend on per-coin requests.
# Only the 30d daily series still needs a per-coin call: cache it for a day and
# top up a handful of coins per run so a single build never exhausts the free
# tier's rate limit.
MARKET_TTL_SECONDS = 30 * 60          # in-build snapshot reuse
MARKET_30D_TTL_SECONDS = 24 * 60 * 60  # 30d series is refreshed once a day
MARKET_30D_MAX_PER_RUN = 6
# Wall-clock budget for the optional 30d top-up. Charts must never block the
# scan; the batch above already covers price, stats and 1d/7d candles.
MARKET_BUDGET_SECONDS = 90


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


def _gecko_json(path, params=None, tries=3):
    """GET CoinGecko JSON with backoff. Returns None on failure/rate-limit."""
    try:
        import requests
    except Exception:
        return None
    for attempt in range(tries):
        try:
            r = requests.get(GECKO_API + path, params=params or {}, timeout=20,
                             headers={"accept": "application/json"})
            if r.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            time.sleep(0.8 * (attempt + 1))
    return None


def _series(prices, limit=None, nd=10):
    """Normalise CoinGecko [[ms, price], ...] into compact JSON-friendly rows."""
    out = []
    for p in prices or []:
        try:
            out.append([int(p[0]), round(float(p[1]), nd)])
        except Exception:
            continue
    if limit:
        out = out[-limit:]
    return out


def _pct_change(series):
    if not series or len(series) < 2:
        return None
    first, last = series[0][1], series[-1][1]
    if not first:
        return None
    return round((last - first) / first * 100.0, 2)


def _spark_series(prices, now_ms=None):
    """CoinGecko's 7d sparkline is 168 hourly prices with no timestamps.

    Synthesise [ms, price] rows ending "now" so the dashboard can bucket the
    series into candlesticks exactly like the market_chart payload.
    """
    vals = [p for p in (prices or []) if isinstance(p, (int, float)) and p > 0]
    if not vals:
        return []
    step = 3600 * 1000
    end = int(now_ms if now_ms is not None else time.time() * 1000)
    end -= end % step
    start = end - (len(vals) - 1) * step
    return [[start + i * step, round(float(v), 10)] for i, v in enumerate(vals)]


def fetch_market_batch(coin_ids):
    """ONE CoinGecko call covering every coin on the dashboard.

    Returns {coin_id: {price, h24, l24, c24, c7, s7}} where s7 is the 7-day
    hourly series. This replaces the per-coin market_chart calls that the free
    tier rate-limits — the reason charts came back blank and 24H HIGH/LOW
    showed N/A for most visitors.
    """
    ids = [c for c in dict.fromkeys(coin_ids) if c]
    if not ids:
        return {}
    out = {}
    chunk = 100  # keep the request URL comfortably inside API limits
    for i in range(0, len(ids), chunk):
        rows = _gecko_json("/coins/markets", {
            "vs_currency": "usd",
            "ids": ",".join(ids[i:i + chunk]),
            "sparkline": "true",
            "price_change_percentage": "24h,7d",
        })
        if not isinstance(rows, list):
            continue
        now_ms = time.time() * 1000
        for row in rows:
            cid = row.get("id")
            if not cid:
                continue
            snap = {}
            if row.get("current_price") is not None:
                snap["price"] = row["current_price"]
            if row.get("high_24h") is not None:
                snap["h24"] = row["high_24h"]
            if row.get("low_24h") is not None:
                snap["l24"] = row["low_24h"]
            if row.get("price_change_percentage_24h") is not None:
                snap["c24"] = round(float(row["price_change_percentage_24h"]), 2)
            c7 = row.get("price_change_percentage_7d_in_currency")
            if c7 is not None:
                snap["c7"] = round(float(c7), 2)
            s7 = _spark_series((row.get("sparkline_in_7d") or {}).get("price"), now_ms)
            if s7:
                snap["s7"] = s7        # 7d hourly series -> 7 daily candles
                snap["d1"] = s7[-24:]  # last 24 hourly points -> 24 hourly candles
            if snap:
                out[cid] = snap
        if i + chunk < len(ids):
            time.sleep(1.0)
    return out


def fetch_market_30d(coin_id, ticker=None):
    """Optional 30-day daily series (one per-coin call), with ticker fallback."""
    candidates = [coin_id]
    if ticker and str(ticker).lower() != str(coin_id).lower():
        candidates.append(str(ticker).lower())
    for cid in candidates:
        daily = _gecko_json(f"/coins/{cid}/market_chart",
                            {"vs_currency": "usd", "days": 30, "interval": "daily"})
        time.sleep(1.0)
        if daily and daily.get("prices"):
            return _series(daily["prices"], nd=10)
    return []


def load_market_cache():
    """Whole-cache read: {coin_id: {"fetched_at": ts, "d30": [[ms, px], ...]}}."""
    if not os.path.exists(MARKET_CACHE_FILE):
        return {}
    try:
        with open(MARKET_CACHE_FILE, "r") as f:
            blob = json.load(f)
        coins = blob.get("coins")
        return coins if isinstance(coins, dict) else {}
    except Exception:
        return {}


def save_market_cache(coins):
    try:
        os.makedirs(DOCS_DIR, exist_ok=True)
        with open(MARKET_CACHE_FILE, "w") as f:
            json.dump({"updated_at": int(time.time()), "coins": coins}, f)
    except Exception as e:
        print(f"  note: could not write market cache: {e}")


def enrich_with_market(cards):
    """Attach card['market'] — price series, stats and changes — for the dashboard.

    ONE /coins/markets batch call covers every coin on the page: price, 24h
    high/low, 24h + 7d change and the 7d hourly sparkline (which yields both the
    1d and 7d candlesticks). That removes the per-visitor CoinGecko calls the
    free tier rate-limits — the reason charts came back blank and 24H HIGH/LOW
    showed N/A.

    Only the 30-day daily series needs a per-coin call, so it is cached in
    docs/market-cache.json (committed by CI) and topped up for at most
    MARKET_30D_MAX_PER_RUN coins per run to stay inside the rate limit.
    """
    started = time.time()

    ids = [c.get("coin_id") for c in cards if c.get("coin_id")]
    unique_ids = list(dict.fromkeys(ids))
    batch = fetch_market_batch(unique_ids)
    print(f"  market batch: {len(batch)}/{len(unique_ids)} coins returned data")

    cache = load_market_cache()
    cache_dirty = False

    # Refresh the 30d series for coins whose cache entry is missing or stale,
    # newest-scanned first, within the per-run count and wall-clock budget.
    stale = []
    for card in cards:
        cid = card.get("coin_id")
        if not cid:
            continue
        entry = cache.get(cid) or {}
        age = time.time() - float(entry.get("fetched_at") or 0)
        if not entry.get("d30") or age > MARKET_30D_TTL_SECONDS:
            stale.append((cid, card.get("coin")))

    refreshed = 0
    for cid, ticker in stale:
        if refreshed >= MARKET_30D_MAX_PER_RUN:
            break
        if time.time() - started > MARKET_BUDGET_SECONDS:
            print("  market 30d budget reached — remainder served from cache")
            break
        series = fetch_market_30d(cid, ticker)
        refreshed += 1
        if series:
            cache[cid] = {"fetched_at": time.time(), "d30": series}
            cache_dirty = True

    enriched = 0
    for card in cards:
        cid = card.get("coin_id")
        if not cid:
            continue
        market = dict(batch.get(cid) or {})
        d30 = (cache.get(cid) or {}).get("d30") or []
        if d30:
            market["d30"] = d30
        if market:
            card["market"] = market
            enriched += 1
        else:
            print(f"  note: no market data for {card.get('coin')} ({cid})")

    if cache_dirty:
        save_market_cache(cache)

    print(f"  market enrichment: {enriched}/{len(cards)} cards embedded "
          f"({refreshed} 30d series refreshed, {len(cache)} cached)")
    return cards


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-run", action="store_true",
                    help="don't run the pipeline, just re-render last report")
    ap.add_argument("--no-market", action="store_true",
                    help="skip CoinGecko price/24h-high-low enrichment")
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

    # Embed price series + 24h high/low so the dashboard renders candlesticks
    # and market stats without depending on per-visitor CoinGecko calls
    # (the free tier rate-limits browsers, which left charts empty / N/A).
    if not args.no_market:
        enrich_with_market(cards)

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
