import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any

from argus import config
from argus.connectors.types import DataSnapshot
from argus.engines.types import AnomalyFlag

INSTRUMENT_PAIRS = [
    ("ES", "NQ"),
    ("CL", "NG"),
    ("ZB", "ZN"),
    ("GC", "SI"),
    ("6E", "6J"),
]

KALSHI_INSTRUMENT_MAP: dict[str, list[str]] = {
    "FED-25DEC": ["ZB", "ZN"],
    "CPI-25DEC": ["GC", "ZB"],
    "NFP-25DEC": ["ES", "ZB"],
    "OIL-25DEC": ["CL", "NG"],
}


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class AnomalyEngine:
    def __init__(self) -> None:
        # tsmom state: instrument -> {"ewm_mean": float, "ewm_var": float, "n": int}
        self._tsmom_state: dict[str, dict[str, Any]] = {}
        # cross-asset state: instrument -> deque of close prices
        self._price_history: dict[str, deque[float]] = {}
        # cross-asset ewm correlation: pair_key -> float
        self._corr_ewm: dict[str, float] = {}
        # kalshi state: ticker -> prev yes_price
        self._kalshi_prev: dict[str, float] = {}

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _ewm_update(self, state: dict[str, Any], value: float, span: int) -> tuple[float, float]:
        """Online exponential weighted mean and variance update.
        Returns (ewm_mean, ewm_std)."""
        alpha = 2.0 / (span + 1)
        if state.get("n", 0) == 0:
            state["ewm_mean"] = value
            state["ewm_var"] = 0.0
            state["n"] = 1
        else:
            prev_mean = state["ewm_mean"]
            state["ewm_mean"] = alpha * value + (1 - alpha) * prev_mean
            state["ewm_var"] = (1 - alpha) * (state["ewm_var"] + alpha * (value - prev_mean) ** 2)
            state["n"] += 1
        std = state["ewm_var"] ** 0.5
        return state["ewm_mean"], std

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float | None:
        n = len(xs)
        if n < 3:
            return None
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
        den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
        if den_x == 0 or den_y == 0:
            return None
        return num / (den_x * den_y)

    # ------------------------------------------------------------------
    # detection methods
    # ------------------------------------------------------------------

    async def check_tsmom_deviation(
        self,
        price_snapshot: DataSnapshot,
        prev_snapshot: DataSnapshot | None,
    ) -> list[AnomalyFlag]:
        flags: list[AnomalyFlag] = []
        if prev_snapshot is None:
            return flags

        ts = price_snapshot.timestamp
        for instrument, bar in price_snapshot.payload.items():
            prev_bar = prev_snapshot.payload.get(instrument)
            if prev_bar is None:
                continue
            close = bar.get("close") if isinstance(bar, dict) else getattr(bar, "close", None)
            prev_close = prev_bar.get("close") if isinstance(prev_bar, dict) else getattr(prev_bar, "close", None)
            if close is None or prev_close is None or prev_close == 0:
                continue

            ret = (close - prev_close) / prev_close

            state = self._tsmom_state.setdefault(instrument, {})
            ewm_mean, ewm_std = self._ewm_update(state, ret, span=20)

            if ewm_std == 0:
                continue
            z = (ret - ewm_mean) / ewm_std

            if abs(z) > config.SIGMA_THRESHOLD:
                return_pct = ret * 100
                if abs(z) > 3.0:
                    severity = "high"
                elif abs(z) > 2.5:
                    severity = "medium"
                else:
                    severity = "low"
                flags.append(
                    AnomalyFlag(
                        instrument=instrument,
                        type="tsmom_deviation",
                        severity=severity,
                        description=(
                            f"{instrument}: {return_pct:+.2f}% move, z={z:.2f}σ vs rolling baseline"
                        ),
                        timestamp=ts,
                    )
                )
        return flags

    async def check_cross_asset_divergence(
        self,
        price_snapshot: DataSnapshot,
    ) -> list[AnomalyFlag]:
        flags: list[AnomalyFlag] = []
        ts = price_snapshot.timestamp

        # Update rolling price histories
        for instrument, bar in price_snapshot.payload.items():
            close = bar.get("close") if isinstance(bar, dict) else getattr(bar, "close", None)
            if close is None:
                continue
            if instrument not in self._price_history:
                self._price_history[instrument] = deque(maxlen=20)
            self._price_history[instrument].append(close)

        for a, b in INSTRUMENT_PAIRS:
            hist_a = self._price_history.get(a)
            hist_b = self._price_history.get(b)
            if hist_a is None or hist_b is None:
                continue
            n = min(len(hist_a), len(hist_b))
            if n < 3:
                continue
            corr = self._pearson(list(hist_a)[-n:], list(hist_b)[-n:])
            if corr is None:
                continue

            pair_key = f"{a}_{b}"
            if pair_key not in self._corr_ewm:
                self._corr_ewm[pair_key] = corr
                continue

            prev_ewm = self._corr_ewm[pair_key]
            alpha = 2.0 / (10 + 1)
            self._corr_ewm[pair_key] = alpha * corr + (1 - alpha) * prev_ewm

            deviation = abs(corr - prev_ewm)
            if deviation > config.CORR_THRESHOLD:
                if deviation > 0.5:
                    severity = "high"
                elif deviation > 0.3:
                    severity = "medium"
                else:
                    severity = "low"
                desc = (
                    f"{a}/{b} correlation diverged: current={corr:.2f}, "
                    f"ewm_baseline={prev_ewm:.2f}, Δ={deviation:+.2f}"
                )
                for instrument in (a, b):
                    flags.append(
                        AnomalyFlag(
                            instrument=instrument,
                            type="cross_asset_divergence",
                            severity=severity,
                            description=desc,
                            timestamp=ts,
                        )
                    )
        return flags

    async def check_kalshi_gap(
        self,
        price_snapshot: DataSnapshot,
        kalshi_snapshot: DataSnapshot,
    ) -> list[AnomalyFlag]:
        flags: list[AnomalyFlag] = []
        ts = kalshi_snapshot.timestamp

        for ticker, market in kalshi_snapshot.payload.items():
            yes_price = (
                market.get("yes_price")
                if isinstance(market, dict)
                else getattr(market, "yes_price", None)
            )
            if yes_price is None:
                continue

            if ticker not in self._kalshi_prev:
                self._kalshi_prev[ticker] = yes_price
                continue

            prev_yes = self._kalshi_prev[ticker]
            delta = yes_price - prev_yes
            self._kalshi_prev[ticker] = yes_price

            if abs(delta) > config.KALSHI_GAP_THRESHOLD:
                if abs(delta) > 0.1:
                    severity = "high"
                elif abs(delta) > 0.05:
                    severity = "medium"
                else:
                    severity = "low"
                desc = f"{ticker} probability shifted {delta:+.1%} → {yes_price:.1%}"
                for instrument in KALSHI_INSTRUMENT_MAP.get(ticker, []):
                    flags.append(
                        AnomalyFlag(
                            instrument=instrument,
                            type="kalshi_probability_shift",
                            severity=severity,
                            description=desc,
                            timestamp=ts,
                        )
                    )
        return flags

    async def check_options_flow(
        self,
        options_snapshot: DataSnapshot | None,
    ) -> list[AnomalyFlag]:
        flags: list[AnomalyFlag] = []
        if options_snapshot is None:
            return flags

        flows: list[dict] = options_snapshot.payload.get("flows", [])
        if not flows:
            return flags

        ts = options_snapshot.timestamp

        for flow in flows:
            try:
                premium = float(flow.get("premium", 0) or 0)
                instrument = str(flow.get("instrument", flow.get("ticker", "UNKNOWN")) or "UNKNOWN")
                side = str(flow.get("side", "") or "")
                sentiment = str(flow.get("sentiment", "neutral") or "neutral")
                expiry = str(flow.get("expiry", "") or "")
                strike = float(flow.get("strike", 0) or 0)
                dte = int(flow.get("dte", 0) or 0)
                ticker = str(flow.get("ticker", instrument) or instrument)

                if premium > 2_000_000:
                    severity = "high"
                elif premium > 1_000_000:
                    severity = "medium"
                elif premium > 500_000:
                    severity = "low"
                else:
                    continue

                premium_k = int(premium) // 1000
                desc = (
                    f"{ticker} {side.upper()} ${premium_k}k"
                    f" @ {strike:g} exp {expiry} ({dte}d) — {sentiment}"
                )
                flags.append(
                    AnomalyFlag(
                        instrument=instrument,
                        type="options_flow",
                        severity=severity,
                        description=desc,
                        timestamp=ts,
                    )
                )
            except (TypeError, ValueError):
                continue

        total = len(flows)
        if total > 0:
            put_count = sum(
                1 for f in flows if str(f.get("side", "") or "").lower() == "put"
            )
            call_count = sum(
                1 for f in flows if str(f.get("side", "") or "").lower() == "call"
            )

            if put_count / total > 0.70:
                flags.append(
                    AnomalyFlag(
                        instrument="OPTIONS",
                        type="bearish_sweep",
                        severity="medium",
                        description=(
                            f"Bearish options sweep: {put_count}/{total} flows are puts"
                            f" ({put_count / total:.0%})"
                        ),
                        timestamp=ts,
                    )
                )
            elif call_count / total > 0.70:
                flags.append(
                    AnomalyFlag(
                        instrument="OPTIONS",
                        type="bullish_sweep",
                        severity="medium",
                        description=(
                            f"Bullish options sweep: {call_count}/{total} flows are calls"
                            f" ({call_count / total:.0%})"
                        ),
                        timestamp=ts,
                    )
                )

        return flags

    # ------------------------------------------------------------------
    # orchestrator
    # ------------------------------------------------------------------

    async def run_all(
        self,
        price_snapshot: DataSnapshot,
        prev_price_snapshot: DataSnapshot | None,
        kalshi_snapshot: DataSnapshot,
    ) -> list[AnomalyFlag]:
        results = await asyncio.gather(
            self.check_tsmom_deviation(price_snapshot, prev_price_snapshot),
            self.check_cross_asset_divergence(price_snapshot),
            self.check_kalshi_gap(price_snapshot, kalshi_snapshot),
        )

        seen: set[tuple[str, str]] = set()
        deduped: list[AnomalyFlag] = []
        for flag in (f for batch in results for f in batch):
            key = (flag.instrument, flag.type)
            if key not in seen:
                seen.add(key)
                deduped.append(flag)
        return deduped
