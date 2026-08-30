# ⚡ Crypto Agent Team

A personal multi-agent system for cryptocurrency research and analysis. Specialized agents watch the market, do due diligence on candidates, and consolidate everything into a clear **BUY / WATCH / AVOID** report.

## The agents

| Agent | Emoji | Job |
|-------|-------|-----|
| **Micro-Cap Finder** | 🔬 | Finds micro-caps with real volume and early momentum |
| **Whale Detector** | ⚡ | Spots big 24h moves, volume spikes, and momentum |
| **News Scanner** | 📰 | Keys off crypto news for breaking sentiment |
| **Due Diligence** | 🛡️ | Verifies candidates (liquidity, drawdown, survivorship) |
| **Investment Advisor** | 💰 | Consolidates all signals into BUY/WATCH/AVOID |

The agents talk through a shared **signal bus** (`data/signals.json`) and **learn over time** — each predicting with a confidence score, then adjusting its strategy based on what actually happened later.

## Dashboard

A mobile-friendly dashboard is served by **GitHub Pages** (auto-updated by GitHub Actions), so it's reachable from any device without your computer running:

- Auto-scans every **6 hours** on GitHub's servers
- Tap **Run Full Scan Now** in the Actions tab to scan on demand
- See BUY/WATCH/AVOID counts + per-coin cards with reasons and DD scores

## Run locally

```bash
python3 run_pipeline.py        # one full scan from the CLI
python3 server.py              # local web dashboard on http://localhost:8080
python3 server.py --interval 3 # auto-scan every 3h (0 = off)
```

## Data sources (free, no API keys)

CoinGecko `/api/v3/`, CoinPaprika, DEXScreener.

---

*Personal research tool only — not financial advice.*
