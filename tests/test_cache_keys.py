"""快取鍵回歸測試（免 pytest：`.venv/bin/python tests/test_cache_keys.py`，不連網）。

2026-09-17：①文案快取只用 1688 網址當 key → 同網址多列（HNV2/HNV5、HNV11 三列）共用第一列的文案
②「🚀 開始」抓過就跳過 → 舊版抓取器的 raw（沒規格圖）永遠不會被補。
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.batch_pipeline2 import ai_cache_path, cache_is_fresh  # noqa: E402
from scraper.playwright_scraper import SCRAPER_REV, raw_is_fresh  # noqa: E402
from scraper.shops import get_shop  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


print("文案快取：一列名單一份")
a = ai_cache_path({"item_id": "760973597185", "code": "HNV11", "name": "G1S 渦輪美甲吸塵器"})
b = ai_cache_path({"item_id": "760973597185", "code": "HNV11", "name": "吸塵器濾網", "style_filter": "濾網"})
c = ai_cache_path({"item_id": "580735119296", "code": "HNV2", "name": "濾網"})
d = ai_cache_path({"item_id": "580735119296", "code": "HNV5", "name": "濾網"})
check("同網址同編號、不同品名／款式 → 不同快取", a != b)
check("同網址不同編號 → 不同快取", c != d)
check("同一列兩次算 → 同一份", a == ai_cache_path({"item_id": "760973597185", "code": "HNV11", "name": "G1S 渦輪美甲吸塵器"}))
check("仍放在該網址的資料夾", a.parent.name == "760973597185")
check("換模板分開存", ai_cache_path({"item_id": "1", "code": "X"}, "v2") != ai_cache_path({"item_id": "1", "code": "X"}))

print("文案快取新鮮度")
sp = get_shop("nail")
tmp = Path(tempfile.mkdtemp())
f = tmp / "x.json"
check("沒檔案＝不新鮮", not cache_is_fresh(f, sp))
f.write_text(json.dumps({"title": "t"}))
check("沒版本號（舊規則）＝不新鮮", not cache_is_fresh(f, sp))
f.write_text(json.dumps({"detail_version": sp.detail_version, "title_version": sp.title_version}))
check("版本對＝新鮮", cache_is_fresh(f, sp))

print("抓取器版本")
r = tmp / "1.json"
check("沒檔案＝要抓", not raw_is_fresh(r))
r.write_text(json.dumps({"main_images": ["a"]}))
check("舊版抓取器（沒 rev）＝要重抓", not raw_is_fresh(r))
r.write_text(json.dumps({"scraper_rev": SCRAPER_REV}))
check("現行版本＝不用抓", raw_is_fresh(r))

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
