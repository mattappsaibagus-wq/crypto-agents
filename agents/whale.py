"""
WhaleDetector — spots big price moves and volume anomalies.
Flags divergences (price up + volume spike), large 24h moves,
and unusual momentum that could precede a whale event.
"""
import requests
from .base import BaseAgent, api_get


class WhaleDetector(BaseAgent):
    name = "whale"
    emoji = "⚡"

    def default_weights(self):
        return {
            "volume_spike": 0.35,
            "price_move": 0.25,
            "momentum": 0.15,
            "liquidity_depth": 0.15,
            "sustainability": 0.1,
        }

    def run(self, **kwargs):
        signals = []
        top = self._fetch_market()

        for c in top:
            sym = c["symbol"].upper()
            change = c.get("change_pct") or 0
            vol_ratio = c.get("vol_ratio") or 0
            vol = c.get("vol") or 0

            score = 0.0
            reasons = []
            direction = "up"

            # Big price move (>15%)
            if change > 15:
                score += 0.25
                reasons.append(f"24h +{change:.1f}%")
            elif change < -15:
                score += 0.2
                direction = "down"
                reasons.append(f"24h {change:.1f}%")

            # Volume spike
            if vol_ratio > 3:
                score += 0.35
                reasons.append(f"volume {vol_ratio:.1f}x normal")
            elif vol_ratio > 2:
                score += 0.2
                reasons.append(f"volume {vol_ratio:.1f}x normal")

            # Momentum streak (price change * volume interaction)
            if change > 5 and vol_ratio > 2:
                score += 0.15
                reasons.append("momentum + volume confirmed")

            # Not a junk microcap with $0 volume
            if vol >= 500_000:
                score += 0.1
                reasons.append("real liquidity")

            if score >= 0.5:
                c["signal_type"] = "whale_up" if direction == "up" else "whale_down"
                c["reasons"] = reasons
                signals.append({
                    "coin": sym,
                    "signal": c["signal_type"],
                    "confidence": round(min(score, 1.0), 2),
                    "source": "coingecko_market",
                    "details": {"change_24h": change, "vol": vol,
                                "vol_ratio": vol_ratio, "reasons": reasons,
                                "price": c.get("price"), "coin_id": c.get("coin_id")},
                })
        return signals

    def _fetch_market(self):
        coins = []
        try:
            data = api_get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "volume_desc",
                        "per_page": 100, "page": 1, "sparkline": "false"},
            )
            if not isinstance(data, list):
                return coins
            for c in data:
                vol = c.get("total_volume") or 0
                mcap = c.get("market_cap") or 0
                change = c.get("price_change_percentage_24h") or 0
                ratio = None
                if mcap > 0:
                    ratio = vol / mcap
                coins.append({
                    "symbol": c["symbol"].upper(),
                    "coin_id": c.get("id"),
                    "change_pct": change,
                    "vol": vol,
                    "vol_ratio": ratio if ratio is not None else 0,
                    "mcap": mcap,
                    "price": c.get("current_price") or 0,
                })
        except Exception as e:
            print(f"          whale market fetch failed: {e}")
        return coins