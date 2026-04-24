from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argus.connectors.types import DataSnapshot

last_fired: dict[str, datetime] = {}
_DEDUP_WINDOW = timedelta(minutes=10)

_SPIKE_THRESHOLD: dict[str, float] = {
    "ES": 0.015, "NQ": 0.015, "GC": 0.015, "CL": 0.015,
    "ZB": 0.008, "ZN": 0.008, "6E": 0.008, "6J": 0.008,
}


@dataclass
class EventSignal:
    instrument: str
    trigger_type: str
    magnitude: float
    timestamp: datetime


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _can_fire(key: str, now: datetime) -> bool:
    last = last_fired.get(key)
    return last is None or (now - last) >= _DEDUP_WINDOW


def _mark_fired(key: str, now: datetime) -> None:
    last_fired[key] = now


class EventDetector:
    def check(self, price_snapshot: DataSnapshot) -> list[EventSignal]:
        signals: list[EventSignal] = []
        now = _now()

        bars_list: list[dict] = price_snapshot.payload.get("bars", [])
        if not bars_list:
            return signals

        by_instrument: dict[str, list[dict]] = {}
        for bar in bars_list:
            inst = bar.get("instrument")
            if inst:
                by_instrument.setdefault(inst, []).append(bar)

        # ISO timestamps sort lexicographically, so max() gives the latest bar
        latest: dict[str, dict] = {
            inst: max(bars, key=lambda b: b.get("timestamp", ""))
            for inst, bars in by_instrument.items()
        }

        signals.extend(self._price_spikes(latest, now))
        signals.extend(self._volume_anomaly(latest, by_instrument, now))
        signals.extend(self._vix_spike(latest, now))
        signals.extend(self._cross_asset_divergence(latest, now))
        return signals

    def _price_spikes(self, latest: dict[str, dict], now: datetime) -> list[EventSignal]:
        signals: list[EventSignal] = []
        for inst, threshold in _SPIKE_THRESHOLD.items():
            bar = latest.get(inst)
            if bar is None:
                continue
            open_ = bar.get("open") or 0.0
            close = bar.get("close")
            if close is None or open_ == 0:
                continue
            ret = (close - open_) / abs(open_)
            if abs(ret) < threshold:
                continue
            key = f"{inst}_price_spike"
            if _can_fire(key, now):
                _mark_fired(key, now)
                signals.append(EventSignal(inst, "price_spike", ret, now))
        return signals

    def _volume_anomaly(
        self,
        latest: dict[str, dict],
        by_instrument: dict[str, list[dict]],
        now: datetime,
    ) -> list[EventSignal]:
        signals: list[EventSignal] = []
        for inst, bar in latest.items():
            vol = bar.get("volume")
            if not vol:
                continue
            history = by_instrument.get(inst, [])
            if len(history) < 2:
                continue
            # rolling average over up to 20 bars prior to the current bar
            prior_vols = [
                b["volume"] for b in history[:-1][-20:]
                if b.get("volume")
            ]
            if not prior_vols:
                continue
            avg = sum(prior_vols) / len(prior_vols)
            if avg == 0:
                continue
            ratio = vol / avg
            if ratio <= 2.5:
                continue
            key = f"{inst}_volume_anomaly"
            if _can_fire(key, now):
                _mark_fired(key, now)
                signals.append(EventSignal(inst, "volume_anomaly", ratio, now))
        return signals

    def _vix_spike(self, latest: dict[str, dict], now: datetime) -> list[EventSignal]:
        bar = latest.get("VX")
        if bar is None:
            return []
        open_ = bar.get("open")
        close = bar.get("close")
        if open_ is None or close is None:
            return []
        move = close - open_
        if abs(move) <= 2.0:
            return []
        key = "VX_vix_spike"
        if not _can_fire(key, now):
            return []
        _mark_fired(key, now)
        return [EventSignal("VX", "vix_spike", move, now)]

    def _cross_asset_divergence(
        self, latest: dict[str, dict], now: datetime
    ) -> list[EventSignal]:
        es_bar = latest.get("ES")
        zb_bar = latest.get("ZB")
        if es_bar is None or zb_bar is None:
            return []

        es_open = es_bar.get("open") or 0.0
        es_close = es_bar.get("close")
        zb_open = zb_bar.get("open") or 0.0
        zb_close = zb_bar.get("close")

        if es_close is None or zb_close is None or es_open == 0 or zb_open == 0:
            return []

        es_ret = (es_close - es_open) / abs(es_open)
        zb_ret = (zb_close - zb_open) / abs(zb_open)

        if not (es_ret > 0.005 and zb_ret > 0.003):
            return []

        signals: list[EventSignal] = []
        for inst, magnitude in (("ES", es_ret), ("ZB", zb_ret)):
            key = f"{inst}_cross_asset_divergence"
            if _can_fire(key, now):
                _mark_fired(key, now)
                signals.append(EventSignal(inst, "cross_asset_divergence", magnitude, now))
        return signals
