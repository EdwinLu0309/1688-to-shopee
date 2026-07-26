"""每日戰報分頁（#S104 Point 1）——一眼看三賣場方向。

分頁「每日戰報」：矩陣＝8 關鍵數（列）× 三賣場（每家 值/昨比/週比 三欄）。
昨比/週比帶 🟢🔴▲▼ 一眼可讀（不靠 Sheet 條件式格式，手機也看得到）。
每次跑覆蓋整頁＝永遠只呈現「最新一天」（歷史在原始日報分頁）。
"""

from __future__ import annotations

from datetime import date, datetime

from loguru import logger

from .metrics import DailyReport, fmt_delta, fmt_value
from .sheet_util import ensure_ws, overwrite

TAB = "每日戰報"


def build_matrix(report: DailyReport, updated: str) -> list[list]:
    """把 DailyReport 攤成要寫進 Sheet 的 2D 陣列。"""
    shops = report.shops
    # 標題列
    rows: list[list] = [
        [f"📊 每日戰報（前一天）", "資料日期", report.dt.isoformat(), "更新", updated],
        [],
    ]
    # 表頭：指標 | (美甲 值/昨比/週比) | (女裝 …) | (嬰幼 …)
    header = ["指標"]
    for sr in shops:
        header += [sr.name, "昨比", "週比"]
    rows.append(header)

    # 每個指標一列
    from .metrics import METRICS
    for m in METRICS:
        line = [m.label]
        for sr in shops:
            cell = sr.cells.get(m.key)
            if cell is None:
                line += ["—", "—", "—"]
                continue
            line += [
                fmt_value(cell.value, m.kind),
                fmt_delta(cell.dod, m.direction),
                fmt_delta(cell.wow, m.direction),
            ]
        rows.append(line)

    # 底部小註：缺資料的賣場提示
    missing = [sr.name for sr in shops if not sr.has_data]
    if missing:
        rows.append([])
        rows.append([f"⚠️ 無資料：{'、'.join(missing)}（該賣場當天沒抓到，或還沒登入）"])
    rows.append([])
    rows.append(["昨比＝vs 前一天　週比＝vs 7 天前　🟢好 🔴壞 ▲升 ▼降　金額單位 NT$"])
    return rows


def write_report(sh, report: DailyReport) -> None:
    updated = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws = ensure_ws(sh, TAB, rows=40, cols=1 + len(report.shops) * 3 + 2)
    overwrite(ws, build_matrix(report, updated))
    logger.info(f"每日戰報已寫入（資料日 {report.dt}，{len(report.shops)} 賣場）")
