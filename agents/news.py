"""
NewsScanner — detects market-moving news on monitored coins.
Uses CoinPaprika news API for new articles mentioning watchlist coins.
(CoinGecko's /news endpoint was retired; CoinPaprika is the free fallback.)
"""
import re
import requests
from .base import BaseAgent

WATCH_COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "MATIC"]

# CoinPaprika coin_slug guess from symbol (common ones)
SLUGS = {
    "BTC": "btc-bitcoin", "ETH": "eth-ethereum", "BNB": "bnb-binance-coin",
    "SOL": "sol-solana", "XRP": "xrp-xrp", "ADA": "ada-cardano",
    "DOGE": "doge-dogecoin", "AVAX": "avax-avalanche", "LINK": "link-chainlink",
    "MATIC": "matic-polygon", "USDT": "usdt-tether", "USDC": "usdc-usd-coin",
}


class NewsScanner(BaseAgent):
    name = "news"
    emoji = "📰"

    def default_weights(self):
        return {
            "big_ticker_mentions": 0.3,
            "regulatory": 0.25,
            "partnership": 0.2,
            "exchange_listing": 0.15,
            "sentiment": 0.1,
        }

    def run(self, **kwargs):
        coins = kwargs.get("coins") or WATCH_COINS
        signals = []

        # Build the API query once
        query = " ".join(SLUGS.get(c, c.lower()) for c in coins)
        try:
            r = requests.get(
                "https://api.coinpaprika.com/v1/search",
                params={"q": query, "c": "events,news"}, timeout=15,
            )
            news = r.json().get("news", [])
            # CoinPaprika search news sometimes empty; fall back to per-coin
            for item in news[:30]:
                title = item.get("title", "")
                body = item.get("article", "") or title
                text = f"{title} {body}".lower()
                # Which coin does it concern?
                coin_hit = next((c for c in coins if c.lower() in text), None)
                if not coin_hit:
                    continue
                sent, reasons = self._classify(text, title)
                if sent:
                    signals.append({
                        "coin": coin_hit,
                        "signal": "news_event",
                        "confidence": round(sent, 2),
                        "source": "coinpaprika_news",
                        "details": {"headline": title,
                                    "url": item.get("link", ""),
                                    "reasons": reasons},
                    })
        except Exception as e:
            print(f"          news scan failed: {e}")

        return signals

    def _classify(self, text: str, title: str) -> tuple[float, list]:
        """Very simple keyphrase sentiment classifier. Returns (confidence, reasons)."""
        score = 0.0
        reasons = []

        bullish = ["surges", "rallies", "all-time high", "ath", "adopts", "etf approved",
                    "partnership", "integrates", "wins", "record", "bullish", "buys"]
        bearish = ["crash", "plummets", "dips", "hacked", "exploit", "sued", "banned",
                    "crackdown", "dumps", "bearish", "delisted", "ponzi", "freeze"]

        big = ["bitcoin", "ethereum", "sec", "federal", "exchange", "billion", "major"]

        for w in bullish:
            if w in text:
                score += 0.15
                reasons.append(f"bullish: '{w}'")
        for w in bearish:
            if w in text:
                score -= 0.15
                reasons.append(f"bearish: '{w}'")
        for w in big:
            if w in text:
                score += 0.05
        if not reasons:
            return 0.0, []

        # Normalize to ±1.0 scale, keep grain
        score = max(-1.0, min(1.0, score))
        return abs(score), reasons