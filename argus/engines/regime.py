import asyncio
import logging
from collections import Counter
from dataclasses import dataclass

from argus.connectors.types import DataSnapshot

logger = logging.getLogger(__name__)

regime_change_event: asyncio.Event = asyncio.Event()


@dataclass
class RegimeResult:
    regime: str
    confidence: float
    signals: list[str]
    prev_regime: str | None
    regime_change: bool


class RegimeClassifier:
    def __init__(self) -> None:
        self.prev_regime: str | None = None

    def _get_fred_release(self, fred_snapshot: DataSnapshot, series_id: str) -> dict | None:
        releases = fred_snapshot.payload.get("releases", [])
        for r in releases:
            if r.get("series_id") == series_id:
                return r
        return None

    def _get_5d_return(self, price_snapshot: DataSnapshot, instrument: str) -> float | None:
        bars = price_snapshot.payload.get("bars", [])
        inst_bars = [b for b in bars if b.get("instrument") == instrument]
        if len(inst_bars) < 2:
            return None
        first_close = inst_bars[0].get("close") or 0.0
        last_close = inst_bars[-1].get("close") or 0.0
        if first_close == 0:
            return None
        return (last_close - first_close) / first_close * 100

    def _get_latest_price(self, price_snapshot: DataSnapshot, instrument: str) -> float | None:
        bars = price_snapshot.payload.get("bars", [])
        inst_bars = [b for b in bars if b.get("instrument") == instrument]
        if not inst_bars:
            return None
        return inst_bars[-1].get("close")

    def classify(
        self, fred_snapshot: DataSnapshot, price_snapshot: DataSnapshot
    ) -> "RegimeResult | None":
        votes: list[str] = []
        signals: list[str] = []

        # VIX (VX futures)
        vix = self._get_latest_price(price_snapshot, "VX")
        if vix is not None:
            if vix < 18:
                votes.append("Risk-On")
                signals.append(f"VIX {vix:.1f} < 18")
            elif vix > 25:
                votes.append("Risk-Off")
                signals.append(f"VIX {vix:.1f} > 25")

        # T10Y2Y (FRED)
        t10y2y = self._get_fred_release(fred_snapshot, "T10Y2Y")
        if t10y2y is not None:
            val = t10y2y.get("value") or 0.0
            prev = t10y2y.get("previous")
            rising = prev is not None and val > prev
            if val > 0.3:
                votes.append("Risk-On")
                signals.append(f"T10Y2Y {val:.2f} > 0.3")
            elif val < 0:
                votes.append("Risk-Off")
                signals.append(f"T10Y2Y {val:.2f} inverting")
            elif val > 0 and rising:
                votes.append("Reflation")
                signals.append(f"T10Y2Y {val:.2f} rising")

        # DFF (FRED): stable/falling → Risk-On; falling → also Reflation
        dff = self._get_fred_release(fred_snapshot, "DFF")
        if dff is not None:
            val = dff.get("value") or 0.0
            prev = dff.get("previous")
            falling = prev is not None and val < prev
            stable_or_falling = prev is None or val <= prev
            if stable_or_falling:
                direction = "falling" if falling else "stable"
                votes.append("Risk-On")
                signals.append(f"DFF {direction}")
            if falling:
                votes.append("Reflation")
                signals.append(f"DFF falling")

        # ES 5d return (price)
        es_ret = self._get_5d_return(price_snapshot, "ES")
        if es_ret is not None:
            if es_ret > 0:
                votes.append("Risk-On")
                signals.append(f"ES 5d return {es_ret:+.1f}%")
            elif es_ret < -1:
                votes.append("Risk-Off")
                signals.append(f"ES 5d return {es_ret:+.1f}%")

        # UNRATE (FRED): rising → Stagflation; falling → Reflation
        unrate = self._get_fred_release(fred_snapshot, "UNRATE")
        if unrate is not None:
            val = unrate.get("value") or 0.0
            prev = unrate.get("previous")
            if prev is not None:
                if val > prev:
                    votes.append("Stagflation")
                    signals.append(f"UNRATE rising {prev:.1f}→{val:.1f}")
                elif val < prev:
                    votes.append("Reflation")
                    signals.append(f"UNRATE falling {prev:.1f}→{val:.1f}")

        # CPIAUCSL mom (FRED)
        cpi = self._get_fred_release(fred_snapshot, "CPIAUCSL")
        if cpi is not None:
            val = cpi.get("value") or 0.0
            prev = cpi.get("previous")
            if prev is not None and prev != 0:
                mom = (val - prev) / abs(prev) * 100
                if mom > 0.3:
                    votes.append("Stagflation")
                    signals.append(f"CPI MoM {mom:+.2f}%")
                elif mom < 0.2:
                    votes.append("Reflation")
                    signals.append(f"CPI MoM {mom:+.2f}%")

        # CL 5d return (price): > 1% → Stagflation AND Reflation
        cl_ret = self._get_5d_return(price_snapshot, "CL")
        if cl_ret is not None and cl_ret > 1:
            votes.append("Stagflation")
            signals.append(f"CL 5d return {cl_ret:+.1f}%")
            votes.append("Reflation")
            signals.append(f"CL 5d return {cl_ret:+.1f}%")

        # 6E 5d return (price): > 0.5% → Reflation
        e6_ret = self._get_5d_return(price_snapshot, "6E")
        if e6_ret is not None and e6_ret > 0.5:
            votes.append("Reflation")
            signals.append(f"6E 5d return {e6_ret:+.1f}%")

        if len(votes) < 3:
            return None

        counts = Counter(votes)
        winner, winner_count = counts.most_common(1)[0]
        confidence = winner_count / len(votes)

        prev_regime = self.prev_regime
        regime_change = winner != prev_regime

        if regime_change:
            self.prev_regime = winner
            regime_change_event.set()
            regime_change_event.clear()

        return RegimeResult(
            regime=winner,
            confidence=confidence,
            signals=signals,
            prev_regime=prev_regime,
            regime_change=regime_change,
        )
