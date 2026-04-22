import csv
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from argus import config
from argus.connectors.types import DataSnapshot, OHLCVBar

logger = logging.getLogger(__name__)


def _bar_from_norgatedata(instrument: str) -> OHLCVBar | None:
    import norgatedata  # type: ignore[import]

    df = norgatedata.price_timeseries(
        instrument,
        stock_price_adjustment_setting=norgatedata.StockPriceAdjustmentType.NONE,
        padding_setting=norgatedata.PaddingType.NONE,
    )
    if df is None or df.empty:
        return None
    row = df.iloc[-1]
    return OHLCVBar(
        instrument=instrument,
        timestamp=row.name.to_pydatetime() if hasattr(row.name, "to_pydatetime") else datetime.utcnow(),
        open=float(row["Open"]),
        high=float(row["High"]),
        low=float(row["Low"]),
        close=float(row["Close"]),
        volume=float(row["Volume"]),
    )


def _bar_from_csv(data_path: Path, instrument: str) -> OHLCVBar | None:
    candidates = list(data_path.glob(f"{instrument}*.csv")) + list(data_path.glob(f"{instrument}*.CSV"))
    if not candidates:
        return None
    csv_path = sorted(candidates)[-1]
    last_row: dict | None = None
    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            last_row = row
    if last_row is None:
        return None

    def _col(*keys: str) -> str:
        for k in keys:
            for candidate_key in last_row:
                if candidate_key.strip().lower() == k.lower():
                    return last_row[candidate_key].strip()
        return "0"

    raw_date = _col("date", "Date", "timestamp", "Timestamp")
    try:
        ts = datetime.fromisoformat(raw_date)
    except ValueError:
        ts = datetime.utcnow()

    return OHLCVBar(
        instrument=instrument,
        timestamp=ts,
        open=float(_col("open", "Open")),
        high=float(_col("high", "High")),
        low=float(_col("low", "Low")),
        close=float(_col("close", "Close")),
        volume=float(_col("volume", "Volume")),
    )


async def fetch_snapshot() -> DataSnapshot:
    now = datetime.utcnow()
    bars: list[dict] = []

    use_norgate = False
    try:
        import norgatedata  # noqa: F401  # type: ignore[import]
        use_norgate = True
    except ImportError:
        pass

    data_path = Path(config.NORGATE_DATA_PATH) if config.NORGATE_DATA_PATH else None

    for instrument in config.INSTRUMENTS:
        try:
            bar: OHLCVBar | None = None
            if use_norgate:
                bar = _bar_from_norgatedata(instrument)
            elif data_path and data_path.exists():
                bar = _bar_from_csv(data_path, instrument)

            if bar is not None:
                d = asdict(bar)
                d["timestamp"] = bar.timestamp.isoformat()
                bars.append(d)
            else:
                logger.debug("No data found for instrument %s", instrument)
        except Exception as exc:
            logger.warning("Failed to fetch Norgate data for %s: %s", instrument, exc)

    return DataSnapshot(source="norgate", timestamp=now, payload={"bars": bars})
