"""SQLite 加速副本（非真相來源；真相 = Google Sheet + raw 快照）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from loguru import logger

from .collector import DayData, FUNNEL_FIELDS, MODEL_FIELDS, PRODUCT_FIELDS, SOURCE_FIELDS

_SHOP_DAILY_COLS = (
    FUNNEL_FIELDS
    + [f"src_{f}" for f in SOURCE_FIELDS]
    + [f"src_{f}_ratio" for f in SOURCE_FIELDS]
    + ["shop_pv"]
)


def _cols(fields: list[str], prefix_skip: tuple[str, ...] = ("id", "name", "status")) -> str:
    parts = []
    for f in fields:
        typ = "TEXT" if f in ("name", "status") or f.endswith("_id") else "REAL"
        if f == "id":
            typ = "INTEGER"
        parts.append(f"{f} {typ}")
    return ", ".join(parts)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS product_daily (
    shop TEXT NOT NULL, dt TEXT NOT NULL, {_cols(PRODUCT_FIELDS)},
    PRIMARY KEY (shop, dt, id)
);
CREATE TABLE IF NOT EXISTS model_daily (
    shop TEXT NOT NULL, dt TEXT NOT NULL, product_id INTEGER, {_cols(MODEL_FIELDS)},
    PRIMARY KEY (shop, dt, id)
);
CREATE TABLE IF NOT EXISTS shop_daily (
    shop TEXT NOT NULL, dt TEXT NOT NULL,
    {", ".join(c + " REAL" for c in _SHOP_DAILY_COLS)},
    PRIMARY KEY (shop, dt)
);
"""


def save(data: DayData, db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(SCHEMA)
        dt = data.dt.isoformat()

        def upsert(table: str, cols: list[str], rows: list[dict]):
            if not rows:
                return
            all_cols = ["shop", "dt"] + cols
            sql = (
                f"INSERT OR REPLACE INTO {table} ({', '.join(all_cols)}) "
                f"VALUES ({', '.join('?' * len(all_cols))})"
            )
            con.executemany(sql, [
                tuple([data.shop, dt] + [r.get(c) for c in cols]) for r in rows
            ])

        upsert("product_daily", PRODUCT_FIELDS, data.products)
        upsert("model_daily", ["product_id"] + MODEL_FIELDS, data.models)
        upsert("shop_daily", _SHOP_DAILY_COLS, [data.shop_daily])
        con.commit()
        logger.info(
            f"SQLite 已寫入 {db_path}：product {len(data.products)} / "
            f"model {len(data.models)} / shop_daily 1"
        )
    finally:
        con.close()
