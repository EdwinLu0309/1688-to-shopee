"""上架庫存與物流頻道的回歸測試（免 pytest，直接 `.venv/bin/python tests/test_stock_channels.py`）。

Edwin 2026-09-16 定的三條：
- 預購：庫存固定 200、較長備貨天數 10、**不可**開「蝦皮店到店－隔日到貨」
- 現貨：庫存＝名單「安全存量」、較長備貨天數留空、**要開**隔日到貨
- 現貨沒填安全存量：擋下並列出編號，不可退回寫死的 10 件
"""
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.ai_list_reader import missing_safety_stock, parse_ai_list_csv  # noqa: E402
from scraper.shops import NEXT_DAY_CHANNEL, channels_for, get_shop, is_preorder  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


def _csv(rows) -> Path:
    f = Path(tempfile.mkdtemp()) / "nail_ai_list.csv"
    with open(f, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["匯率", "4.9"])
        w.writerow(["訂貨需求", "編號", "商品 or 品牌名稱", "分類", "標籤", "安全存量", "進貨網址"])
        w.writerow(["預購 或 現貨", "※ 商品編號", "", "", "", "現貨必填", ""])
        for r in rows:
            w.writerow(r)
    return f


print("名單解析")
path = _csv([
    ["預購", "HNV90", "預購集塵器", "", "", "", "https://detail.1688.com/offer/111.html"],
    ["預購", "HNV91", "預購有填也照 200", "", "", "30", "https://detail.1688.com/offer/112.html"],
    ["現貨", "HNV92", "現貨有填", "", "", "40", "https://detail.1688.com/offer/113.html"],
    ["現貨", "HNV93", "現貨沒填", "", "", "", "https://detail.1688.com/offer/114.html"],
    ["", "HNV94", "訂貨需求空白也算現貨", "", "", "", "https://detail.1688.com/offer/115.html"],
])
ps = {p["code"]: p for p in parse_ai_list_csv(path, shop="nail")}
check("預購沒填 → 200", ps["HNV90"]["stock"] == 200, ps["HNV90"]["stock"])
check("預購有填 → 仍固定 200", ps["HNV91"]["stock"] == 200, ps["HNV91"]["stock"])
check("預購 → 較長備貨 10 天", ps["HNV90"]["pre_order_days"] == 10)
check("現貨 → 安全存量", ps["HNV92"]["stock"] == 40, ps["HNV92"]["stock"])
check("現貨 → 較長備貨留空", ps["HNV92"]["pre_order_days"] is None)
check("現貨沒填 → None 不是 10", ps["HNV93"]["stock"] is None, ps["HNV93"]["stock"])
check("缺安全存量清單＝現貨沒填的那兩支",
      missing_safety_stock(list(ps.values())) == ["HNV93", "HNV94"],
      missing_safety_stock(list(ps.values())))

print("物流頻道")
sp = get_shop("nail")
check("隔日到貨是 30019", NEXT_DAY_CHANNEL == "30019")
check("現貨開隔日到貨", NEXT_DAY_CHANNEL in channels_for(sp, "現貨"))
check("空白當現貨", NEXT_DAY_CHANNEL in channels_for(sp, ""))
check("預購不開隔日到貨", NEXT_DAY_CHANNEL not in channels_for(sp, "預購"))
check("現貨＝公版 6 個＋隔日到貨", channels_for(sp, "現貨") == set(sp.enabled_channels) | {"30019"})
check("不汙染賣場設定", NEXT_DAY_CHANNEL not in sp.enabled_channels)
check("is_preorder", is_preorder("預購") and not is_preorder("現貨") and not is_preorder(None))

print("批次入口擋下")
from scraper.batch_pipeline2 import run_batch_two_tier  # noqa: E402

try:
    run_batch_two_tier(products=list(ps.values()), shop="nail", make_staging=True, make_video=False)
    check("現貨缺安全存量要擋", False, "沒有丟例外")
except ValueError as e:
    check("現貨缺安全存量要擋，訊息列出編號", "HNV93" in str(e) and "HNV94" in str(e), str(e))

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
