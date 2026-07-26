"""改動追蹤日誌（#S104 Point 3）——把「改了什麼」跟「有沒有變好」閉環起來。

一張分頁，左半 Edwin 手填、右半系統每天自動算：
  [Edwin 填] 改動日 | 賣場 | 對象 | 類型 | 改了什麼 | 想改善的指標
  [系統填]   追蹤狀態 | 改前3天 | 改後3天 | 3天變化% | 改前7天 | 改後7天 | 7天變化% | AI判定 | 更新時間

系統無法自己歸因（看得到某商品 CTR 掉、但不知道是因為改了標題），所以「改了什麼」要人填；
系統負責「改動前後的目標指標對比」這件人算很累的事。

對象欄：填「商品ID」→ 追該商品的指標；留空或填賣場名 → 追整個賣場大盤。
指標：領先指標(CTR/加購/轉換)改動後 3-7 天可判；落後指標(營收)要拉長，故同時給 3 天與 7 天兩窗。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from loguru import logger

from . import metrics as M
from .sheet_util import ensure_ws

TAB = "改動追蹤日誌"

HEADER = [
    "改動日", "賣場", "對象(商品ID或留空=整店)", "類型", "改了什麼", "想改善的指標",
    "追蹤狀態", "改前3天", "改後3天", "3天變化%", "改前7天", "改後7天", "7天變化%",
    "AI判定", "更新時間",
]
FIRST_SYS_COL = 7   # G 欄起是系統填（1-based）

# 想改善的指標（自由文字）→ metric key
_METRIC_ALIAS = {
    "confirmed_sales": ["成交額", "營收", "銷售", "業績", "銷售額"],
    "confirmed_orders": ["訂單", "成交數", "成交筆數", "單量"],
    "conv_rate": ["轉換", "轉單", "成交轉換", "轉化"],
    "ctr": ["ctr", "點擊率", "點擊"],
    "uv_to_placed": ["下單率", "訪客下單"],
    "ad_cost": ["廣告花費", "花費", "廣告費"],
    "ad_roi": ["roas", "投報", "投產", "廣告roas", "roi"],
    "ad_share": ["廣告佔比", "佔營收", "廣告占比"],
}
_SHOP_ALIAS = {"nail": ["nail", "美甲"], "lady": ["lady", "女裝", "女性"], "baby": ["baby", "嬰幼", "母嬰"]}

# 判定門檻
JUDGE_GOOD = 0.10   # 目標方向改善 ≥10% → 有效
JUDGE_BAD = -0.10   # 反方向 ≤-10% → 無效
MIN_AFTER_DAYS = 3  # 改動後至少幾天資料才判


@dataclass
class Change:
    row: int          # 1-based sheet 列號
    change_day: date | None
    shop: str | None
    target: str       # 對象原文
    metric_key: str | None
    raw: list[str]     # 原始整列（左半）


def _parse_shop(text: str) -> str | None:
    t = (text or "").strip().lower()
    for shop, names in _SHOP_ALIAS.items():
        if any(n.lower() in t for n in names):
            return shop
    return None


def _parse_metric(text: str) -> str | None:
    t = (text or "").strip().lower()
    for key, names in _METRIC_ALIAS.items():
        if any(n.lower() in t for n in names):
            return key
    return None


def _parse_day(text: str) -> date | None:
    t = (text or "").strip().replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d", "%m-%d"):
        try:
            d = datetime.strptime(t, fmt)
            if fmt == "%m-%d":
                d = d.replace(year=date.today().year)
            return d.date()
        except ValueError:
            continue
    return None


# ── 指標取值（某 scope 某天）───────────────────────────────────────

def _metric_fn(key: str):
    for m in M.METRICS:
        if m.key == key:
            return m
    return None


def _shop_raw(con, shop, dt):
    return M._read_raw(con, shop, dt)


def _product_raw(con, shop, pid: int, dt: str) -> dict | None:
    r = con.execute(
        "SELECT confirmed_sales, uv, placed_buyers, confirmed_orders, "
        "product_card_impressions, product_card_clicks "
        "FROM product_daily WHERE shop=? AND id=? AND dt=?",
        (shop, pid, dt),
    ).fetchone()
    if r is None:
        return None
    return {
        "confirmed_sales": r[0], "shop_uv": r[1], "placed_buyers": r[2],
        "sum_confirmed_orders": r[3], "sum_impressions": r[4], "sum_clicks": r[5],
        "ad_cost": None, "ad_roi": None, "ad_gmv": None,
    }


def _value_on(con, shop, pid, metric_key, dt: str):
    m = _metric_fn(metric_key)
    if m is None:
        return None
    raw = _product_raw(con, shop, pid, dt) if pid else _shop_raw(con, shop, dt)
    if raw is None:
        return None
    return m.fn(raw)


def _window_avg(con, shop, pid, metric_key, days: list[str]) -> tuple[float | None, int]:
    """對一串日期取指標平均；回 (平均, 有資料天數)。"""
    vals = [v for v in (_value_on(con, shop, pid, metric_key, d) for d in days) if v is not None]
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


def _daterange(d0: date, n: int, after: bool) -> list[str]:
    if after:
        return [(d0 + timedelta(days=i)).isoformat() for i in range(1, n + 1)]
    return [(d0 - timedelta(days=i)).isoformat() for i in range(1, n + 1)]


def _pct(before, after):
    if before in (None, 0) or after is None:
        return None
    return (after - before) / before


def _judge(pct3, direction: str, after_days: int) -> str:
    if after_days < MIN_AFTER_DAYS:
        return f"待觀察（資料 {after_days}/{MIN_AFTER_DAYS} 天）"
    if pct3 is None:
        return "待觀察（無足夠資料）"
    good = pct3 if direction != "down" else -pct3
    if good >= JUDGE_GOOD:
        return "✅ 有效"
    if good <= JUDGE_BAD:
        return "❌ 無效"
    return "➖ 待觀察（變化不明顯）"


def _fmt_pct(p):
    if p is None:
        return "—"
    return f"{'+' if p >= 0 else ''}{p*100:.1f}%"


def _compute_row(con, ch: Change, today: date) -> list:
    """算某一列的系統欄 G..O（8 欄）。"""
    if ch.change_day is None:
        return ["⚠️ 改動日格式錯誤", "", "", "", "", "", "", ""]
    if ch.shop is None:
        return ["⚠️ 賣場無法辨識（填 美甲/女裝/嬰幼）", "", "", "", "", "", "", ""]
    if ch.metric_key is None:
        return ["⚠️ 指標無法對應（填 成交額/轉換率/CTR/ROAS…）", "", "", "", "", "", "", ""]

    pid = None
    t = ch.target.strip()
    if t and t.isdigit():
        # 對象是商品ID：確認該商品有資料
        exists = con.execute(
            "SELECT 1 FROM product_daily WHERE shop=? AND id=? LIMIT 1", (ch.shop, int(t))
        ).fetchone()
        if exists:
            pid = int(t)
    # ad_* 指標在商品層拿不到 → 退回整店
    m = _metric_fn(ch.metric_key)
    note = ""
    if pid and ch.metric_key in ("ad_cost", "ad_roi", "ad_share"):
        pid = None
        note = "（廣告指標改看整店）"

    before3, _ = _window_avg(con, ch.shop, pid, ch.metric_key, _daterange(ch.change_day, 3, False))
    after3, ad3 = _window_avg(con, ch.shop, pid, ch.metric_key,
                              [d for d in _daterange(ch.change_day, 3, True) if d <= today.isoformat()])
    before7, _ = _window_avg(con, ch.shop, pid, ch.metric_key, _daterange(ch.change_day, 7, False))
    after7, _ = _window_avg(con, ch.shop, pid, ch.metric_key,
                            [d for d in _daterange(ch.change_day, 7, True) if d <= today.isoformat()])

    pct3 = _pct(before3, after3)
    pct7 = _pct(before7, after7)
    status = f"追蹤中{note}" if ad3 >= MIN_AFTER_DAYS else f"資料累積中 {ad3}/{MIN_AFTER_DAYS} 天{note}"
    verdict = _judge(pct3, m.direction, ad3)

    def f(v):
        return M.fmt_value(v, m.kind) if v is not None else "—"

    return [status, f(before3), f(after3), _fmt_pct(pct3),
            f(before7), f(after7), _fmt_pct(pct7), verdict,
            datetime.now().strftime("%Y-%m-%d %H:%M")]


def update_change_log(sh, db_path: str | Path, today: date | None = None) -> int:
    """掃改動追蹤日誌，把每列的系統欄重算填回。回處理列數。"""
    today = today or date.today()
    ws = ensure_ws(sh, TAB, rows=400, cols=len(HEADER))
    values = ws.get_all_values()
    if not values:
        ws.update(values=[HEADER], range_name="A1", raw=True)
        logger.info("改動追蹤日誌：建好表頭（等 Edwin 填）")
        return 0
    if values[0] != HEADER:
        ws.update(values=[HEADER], range_name="A1", raw=True)

    con = sqlite3.connect(str(db_path))
    processed = 0
    try:
        updates = []  # (row_index, [G..O])
        for i, row in enumerate(values[1:], start=2):
            left = (row + [""] * 6)[:6]
            if not any(left):   # 整列空 → 跳過
                continue
            ch = Change(
                row=i,
                change_day=_parse_day(left[0]),
                shop=_parse_shop(left[1]),
                target=left[2],
                metric_key=_parse_metric(left[5]),
                raw=left,
            )
            sys_cols = _compute_row(con, ch, today)
            updates.append((i, sys_cols))
            processed += 1
        # 一次 batch 寫回 G..O
        if updates:
            data = [{"range": f"G{r}:O{r}", "values": [cols]} for r, cols in updates]
            ws.batch_update(data, value_input_option="RAW")
    finally:
        con.close()
    logger.info(f"改動追蹤日誌：更新 {processed} 列")
    return processed
