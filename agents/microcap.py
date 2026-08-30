"""
MicroCapFinder — hunts for small-cap coins with early-stage signals.
Uses CoinGecko markets (sorted by market cap) + DEXScreener new pairs.
"""
import requests
from .base import BaseAgent, api_get


class MicroCapFinder(BaseAgent):
    name = "microcap"
    emoji = "🔬"

    def default_weights(self):
        return {
            "strong_volume_ratio": 0.3,
            "low_liquidity_risk": 0.2,
            "age_signal": 0.15,
            "trending_boost": 0.2,
            "dex_listing": 0.15,
        }

    def run(self, **kwargs):
        signals = []
        found = self._scan_trending() + self._scan_dex()

        # Cap per run to avoid flooding the bus
        for coin in found[:20]:
            score, reasons = coin["score"], coin["reasons"]
            if score >= 0.5:
                signals.append({
                    "coin": coin["symbol"],
                    "signal": "microcap_opportunity",
                    "confidence": round(score, 2),
                    "source": coin["source"],
                    "details": {"mcap": coin.get("mcap"), "vol": coin.get("vol24"),
                                "age_days": coin.get("age_days"), "reasons": reasons,
                                "price": coin.get("price"),
                                "coin_id": coin.get("coin_id")},
                })
        return signals

    def _scan_trending(self):
        """Discovery scans: currently-trending coins + the real micro-cap band
        (rank ~750–1000). Lowest-cap coins are mostly dead with $0 volume,
        so we target coins with actual trading activity."""
        found = []

        # 1) What is trending on CoinGecko right now
        try:
            payload = api_get("https://api.coingecko.com/api/v3/search/trending")
            if isinstance(payload, dict):
                for item in payload.get("coins", [])[:20]:
                    d = item.get("item", {})
                    data = d.get("data", {}) or {}
                    mcap = data.get("market_cap")
                    price = data.get("price")
                    score = 0.55
                    reasons = ["trending on CoinGecko right now"]
                    if isinstance(mcap, (int, float)) and mcap < 20_000_000:
                        score += 0.15
                        reasons.append("early mcap < $20M")
                    found.append({
                        "symbol": d.get("symbol", "?").upper(),
                        "coin_id": d.get("id"),
                        "source": "coingecko_trending",
                        "score": min(score, 1.0),
                        "mcap": mcap, "vol24": None, "age_days": None,
                        "price": price,
                        "reasons": reasons,
                    })
        except Exception as e:
            print(f"          trending scan failed: {e}")

        # 2) Micro-cap band with real volume (approx ranks 751–1000)
        try:
            coins = api_get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "market_cap_desc",
                        "per_page": 250, "page": 4, "sparkline": "false"},
            ) or []
            if not isinstance(coins, list):
                coins = []
            for c in coins:
                mcap = c.get("market_cap") or 0
                vol = c.get("total_volume") or 0
                price = c.get("current_price") or 0
                if not (mcap < 50_000_000 and vol > 50_000 and price > 0.00000001):
                    continue
                vol_ratio = vol / mcap if mcap > 0 else 0
                score = 0.0
                reasons = []
                if vol_ratio > 0.3:
                    score += 0.3
                    reasons.append(f"volume/mcap {vol_ratio:.2f} (>0.3)")
                if mcap < 10_000_000:
                    score += 0.2
                    reasons.append("very early mcap")
                change = c.get("price_change_percentage_24h") or 0
                if change > 15:
                    score += 0.15
                    reasons.append(f"24h momentum +{change:.1f}%")
                rank = c.get("market_cap_rank")
                if rank and rank < 2000:
                    score += 0.1
                    reasons.append(f"ranked #{rank}")
                found.append({
                    "symbol": c["symbol"].upper(),
                    "coin_id": c.get("id"),
                    "source": "coingecko_microcap",
                    "score": min(score, 1.0),
                    "mcap": mcap, "vol24": vol, "age_days": None,
                    "price": price,
                    "reasons": reasons,
                })
        except Exception as e:
            print(f"          microcap band scan failed: {e}")
        return found

    def _scan_dex(self):
        """Recently-listed pairs on DEXscreener with sane liquidity."""
        found = []
        try:
            # Top new pairs by liquidity (default endpoint returns latest)
            r = requests.get("https://api.dexscreener.com/latest/dex/search",
                             params={"q": "new"}, timeout=15)
            pairs = r.json().get("pairs", [])
            for p in pairs[:100]:
                liq = (p.get("liquidity") or {}).get("usd") or 0
                vol = (p.get("volume") or {}).get("h24") or 0
                createdAt = p.get("pairCreatedAt")
                age_days = None
                if createdAt:
                    age_days = max(0, (self._now_ms() - createdAt) / 86400000)
                # New pair, some liquidity, minimal volume consistency check
                if liq > 50_000 and age_days is not None and age_days < 30:
                    price_usd = float(p.get("priceUsd") or 0)
                    if price_usd < 0.001 and vol > 5_000:
                        score = 0.5
                        reasons = [f"listed {age_days:.0f}d ago on {p.get('dexId', 'dex')}"]
                        if liq > 200_000:
                            score += 0.2
                            reasons.append("liquidity > $200k")
                        if p.get("fdv", 0) and p["fdv"] < 20_000_000:
                            score += 0.15
                            reasons.append("small FDV")
                        symbol = (p.get("baseToken") or {}).get("symbol", "?").upper()
                        found.append({
                            "symbol": symbol,
                            "source": "dexscreener",
                            "score": min(score, 1.0),
                            "mcap": p.get("fdv"), "vol24": vol,
                            "age_days": round(age_days, 1),
                            "price": price_usd,
                            "reasons": reasons,
                        })
        except Exception as e:
            print(f"          dexscreener scan failed: {e}")
        return found

    def _now_ms(self):
        import time
        return int(time.time() * 1000)