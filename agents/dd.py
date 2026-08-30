"""
DueDiligence — checks candidate coins flagged by earlier agents.
Because we use free APIs only, no contract audits are fetchable directly;
DD scores based on market-verifiable health signals and flags red flags.
Reads the shared signal bus and writes back scored dd_result signals.
"""
from .base import BaseAgent, api_get, coin_id_for


class DueDiligence(BaseAgent):
    name = "dd"
    emoji = "🛡️"

    def default_weights(self):
        return {
            "liquidity_health": 0.25,
            "holder_concentration": 0.25,
            "volume_depth": 0.2,
            "age_survivorship": 0.15,
            "market_traction": 0.15,
        }

    def run(self, **kwargs):
        candidates = self.read_signals()
        # Collect the coins that Phase 1 flagged, remembering their
        # authoritative CoinGecko id when the discovering agent provided one.
        coin_map = {}
        for sig in candidates:
            c = sig.get("coin")
            if not c:
                continue
            entry = coin_map.setdefault(c, {})
            entry["id"] = entry.get("id") or (sig.get("details") or {}).get("coin_id")
            entry["conf"] = max(entry.get("conf", 0), sig.get("confidence", 0))

        # DD the most-confident candidates first, capped for API politeness
        ordered = sorted(coin_map.items(), key=lambda kv: kv[1]["conf"], reverse=True)
        results = []
        for symbol, meta in ordered[:8]:
            info = self._fetch_coin_info(symbol, meta.get("id"))
            score, reasons = self._score(symbol, info)
            results.append({
                "coin": symbol,
                "signal": "dd_result",
                "confidence": round(score, 2),
                "source": "duediligence",
                "details": {"reasons": reasons, "score_breakdown": info},
            })
        return results

    def _fetch_coin_info(self, symbol: str, coin_id: str = None) -> dict:
        """CoinGecko lookup preferring the id the discovering agent saw."""
        info = {"mcap": 0, "vol": 0, "ath_change_pct": 0, "price": 0,
                "sparkline_7d_flat": True, "age_days": 0, "rank": None}
        cid = coin_id or coin_id_for(symbol)
        if not cid:
            info["rag_status"] = "unknown_to_major_indexers"
            return info
        payload = api_get(f"https://api.coingecko.com/api/v3/coins/{cid}",
                          params={"localization": "false",
                                  "tickers": "false",
                                  "market_data": "true",
                                  "community_data": "false",
                                  "developer_data": "false"})
        if not isinstance(payload, dict) or "market_data" not in payload:
            # Known id but detail fetch failed (rate-limited / error) — still indexed
            info["rag_status"] = "indexed_unverified"
            return info
        d = payload["market_data"]
        info.update({
            "mcap": d.get("market_cap", {}).get("usd") or 0,
            "vol": d.get("total_volume", {}).get("usd") or 0,
            "ath_change_pct": d.get("ath_change_percentage", {}).get("usd") or 0,
            "price": d.get("current_price", {}).get("usd") or 0,
            "rank": d.get("market_cap_rank"),
            "rag_status": "indexed",
        })
        return info

    def _score(self, symbol: str, info: dict) -> tuple[float, list[str]]:
        score = 0.0
        reasons = []

        mcap = info.get("mcap") or 0
        vol = info.get("vol") or 0

        # On CoinGecko at all (survivorship / not a token-net)
        rag = info.get("rag_status")
        if rag in ("indexed", "indexed_unverified"):
            score += 0.1
            reasons.append("found on CoinGecko")
        elif rag == "unknown_to_major_indexers":
            reasons.append("⚠ unknown to major indexers — verify contract before any purchase")

        # Liquidity health (only when real data is present)
        if rag == "indexed":
            if mcap > 5_000_000:
                score += 0.2
                reasons.append(f"mcap > $5M (${mcap/1e6:.1f}M)")
            elif mcap > 500_000:
                score += 0.1
                reasons.append(f"mcap ${mcap/1e6:.1f}M — thin, be careful")

        # Volume depth relative to mcap (only meaningful if we got real data)
        if info.get("price", 0) > 0:
            if mcap > 0 and vol / mcap > 0.05:
                score += 0.15
                reasons.append(f"healthy volume/mcap {vol/mcap:.2f}")
            elif vol < 10_000:
                reasons.append("⚠ very low volume — exit liquidity risk")

        # Drawdown from ATH (only when price data actually exists)
        ath = info.get("ath_change_pct") or 0
        if info.get("price", 0) > 0 and ath > -40:
            score += 0.15
            reasons.append(f"only {ath:.0f}% below ATH — early relative strength")

        # On CoinGecko at all (survivorship / not a token-net)
        if info.get("rag_status") == "unknown_to_major_indexers":
            reasons.append("⚠ unknown to major indexers — verify contract before any purchase")

        return min(score, 1.0), reasons