import logging
from datetime import date, datetime, timedelta

import httpx

from argus import config
from argus.connectors.types import DataSnapshot

logger = logging.getLogger(__name__)

FRED_RELEASES_URL = "https://api.stlouisfed.org/fred/releases/dates"

_FOMC_DATES = [
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-10",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
]

_FOMC_INSTRUMENTS = ["ZB", "ZN", "6E", "6J", "GC"]
_NFP_INSTRUMENTS = ["ES", "NQ", "RTY"]
_GDP_INSTRUMENTS = ["ES", "NQ", "CL"]

_FRED_NAME_MAP: list[tuple[str, list[str], str]] = [
    ("employment situation", _NFP_INSTRUMENTS, "high"),
    ("nonfarm payroll", _NFP_INSTRUMENTS, "high"),
    ("consumer price", _FOMC_INSTRUMENTS, "high"),
    ("producer price", _FOMC_INSTRUMENTS, "medium"),
    ("personal consumption", _FOMC_INSTRUMENTS, "high"),
    ("gross domestic product", _GDP_INSTRUMENTS, "high"),
]


def _classify_fred_release(name: str) -> tuple[list[str], str]:
    name_lower = name.lower()
    for keyword, instruments, impact in _FRED_NAME_MAP:
        if keyword in name_lower:
            return instruments, impact
    return [], "medium"


def _first_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    days_ahead = (4 - d.weekday()) % 7
    return d + timedelta(days=days_ahead)


def _last_friday(year: int, month: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    days_back = (last.weekday() - 4) % 7
    return last - timedelta(days=days_back)


def _build_hardcoded_events(today: date, window_days: int = 30) -> list[dict]:
    end = today + timedelta(days=window_days)
    events: list[dict] = []

    for ds in _FOMC_DATES:
        d = date.fromisoformat(ds)
        if today <= d <= end:
            events.append({
                "name": "FOMC Meeting",
                "date": ds,
                "days_until": (d - today).days,
                "impact": "high",
                "related_instruments": _FOMC_INSTRUMENTS,
            })

    months: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(3):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    for y, m in months:
        candidates: list[tuple[str, date, str, list[str], str]] = [
            ("NFP (Employment Situation)", _first_friday(y, m), "high", _NFP_INSTRUMENTS),
            ("CPI", date(y, m, 14), "high", _FOMC_INSTRUMENTS),
            ("PPI", date(y, m, 11), "medium", _FOMC_INSTRUMENTS),
            ("PCE", _last_friday(y, m), "high", _FOMC_INSTRUMENTS),
        ]
        if m in (1, 4, 7, 10):
            candidates.append(("GDP Advance", date(y, m, 26), "high", _GDP_INSTRUMENTS))

        for name, d, impact, instruments in candidates:
            if today <= d <= end:
                events.append({
                    "name": name,
                    "date": d.isoformat(),
                    "days_until": (d - today).days,
                    "impact": impact,
                    "related_instruments": instruments,
                })

    return sorted(events, key=lambda e: e["date"])


async def _fetch_fred_calendar(today: date) -> list[dict]:
    end = today + timedelta(days=30)
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            FRED_RELEASES_URL,
            params={
                "api_key": config.FRED_API_KEY,
                "realtime_start": today.isoformat(),
                "limit": 20,
                "file_type": "json",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("release_dates", []):
            try:
                d = date.fromisoformat(item["date"])
            except (KeyError, ValueError):
                continue
            if not (today <= d <= end):
                continue
            instruments, impact = _classify_fred_release(item.get("release_name", ""))
            events.append({
                "name": item.get("release_name", "Unknown Release"),
                "date": item["date"],
                "days_until": (d - today).days,
                "impact": impact,
                "related_instruments": instruments,
            })
    return events


async def fetch_snapshot() -> DataSnapshot:
    today = date.today()
    now = datetime.utcnow()
    hardcoded = _build_hardcoded_events(today)

    if config.FRED_API_KEY:
        try:
            fred_events = await _fetch_fred_calendar(today)
            fomc_events = [e for e in hardcoded if e["name"] == "FOMC Meeting"]
            events = sorted(fred_events + fomc_events, key=lambda e: e["date"])
            return DataSnapshot(source="calendar", timestamp=now, payload={"events": events})
        except Exception as exc:
            logger.warning("FRED calendar fetch failed, using hardcoded schedule only: %s", exc)

    return DataSnapshot(source="calendar", timestamp=now, payload={"events": hardcoded})
