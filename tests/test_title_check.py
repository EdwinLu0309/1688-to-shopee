"""Nail 標題 v2.2 檢查回歸測試（免 pytest：`.venv/bin/python tests/test_title_check.py`，不連網）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.keyword_pool import CATEGORY_RULES, Pool, Word, first_line_candidates, needs_pif  # noqa: E402
from scraper.title_check import check_title, display_width  # noqa: E402
from scraper.shops import get_shop  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


def cat(name):
    for keys, c in CATEGORY_RULES:
        if any(k in name for k in keys):
            return c
    return ""


print("自動修正")
t, fixed, warn = check_title("貓眼膠 貓眼指甲油 冰透晶石貓眼 ✅PIF合規 【現貨】 Vendeeni 24色 HNG1 過濾棉 貓眼 美甲",
                             code="HNG1", pif=True, banned={"過濾棉"})
check("拿掉【】但留 ✅", "【" not in t and "✅PIF合規" in t, t)
check("拿掉現貨", "現貨" not in t)
check("拿掉商品編號", "HNG1" not in t)
check("拿掉泛用詞", "過濾棉" not in t)
long = "磨甲機 美甲打磨機 充電式電動磨甲機 EN101MAX 卸甲機 電動磨甲器 指甲打磨機 美甲機 磨指甲機 美甲工具 美甲材料 美甲"
t2, f2, w2 = check_title(long)
check("超過 60 字從尾巴砍到 ≤60", len(t2) <= 60 and t2.startswith("磨甲機 美甲打磨機 充電式電動磨甲機 EN101MAX"), (len(t2), t2))
check("砍掉的有記錄", any("尾串" in x for x in f2), f2)

t3, f3, _ = check_title("封層 底膠 美甲功能膠 ✅PIF合規 AS 甲油膠 美甲 封層 底膠")
check("重複的詞拿掉（保留前面那個）", t3 == "封層 底膠 美甲功能膠 ✅PIF合規 AS 甲油膠 美甲", t3)

print("要人看")
_, _, w = check_title("光療指甲油 貓眼膠 ✅PIF合規 美甲", pif=True)
check("化粧品出現療", any("療" in x for x in w), w)
check("✅ 前寬度不足（會在第一行）", any("寬度" in x for x in w), w)
_, _, w = check_title("貓眼膠 貓眼指甲油 美甲", pif=True)
check("化粧品沒放 PIF", any("沒有「✅PIF合規」" in x for x in w), w)
_, _, w = check_title("美甲燈 光療燈 手持一字燈 ✅PIF合規 美甲", pif=False)
check("器材不該有 ✅", any("✅" in x for x in w), w)
_, _, w = check_title("美甲燈 光療燈 手持一字燈 96W 美甲", spec_sources=["48W 手持燈"])
check("規格找不到出處", any("96W" in x for x in w), w)
check("短標題提醒", any("字" in x for x in w), w)
check("顯示寬度：中文 1、英數 0.5", display_width("貓眼 AB") == 3.5)

print("分類與 PIF")
check("貓眼膠落膠池（不是磁鐵那池）", cat("冰透晶石貓眼膠") == "膠")
check("貓眼磁鐵落貓眼池", cat("貓眼磁鐵棒") == "貓眼")
check("凝膠清潔液是溶劑不是膠", cat("凝膠清潔液") == "溶劑")
check("指緣油是保養", cat("筆型指緣油") == "保養")
check("卸甲膠是卸甲", cat("Vendeeni 卸甲膠") == "卸甲")
check("膠／保養要 PIF", needs_pif("膠") and needs_pif("保養"))
check("卸甲膠要 PIF、卸甲包不用", needs_pif("卸甲", "卸甲膠") and not needs_pif("卸甲", "卸甲包"))
check("器材不用 PIF", not needs_pif("美甲燈") and not needs_pif("打磨機"))
pool = Pool("膠", [Word("貓眼指甲油", 16963, "膠", "品類"), Word("底膠", 13130, "膠", "品類"),
                   Word("美甲", 42007, "廣域", "廣域"), Word("封層", 7739, "膠", "品類")])
check("大詞候選：和品名有共同字眼的排前面", first_line_candidates(pool, "高階底膠 封層")[:2] == ["底膠", "封層"],
      first_line_candidates(pool, "高階底膠 封層"))
check("大詞候選不含廣域詞", "美甲" not in first_line_candidates(pool, "美甲底膠"))

print("賣場設定")
check("Nail 走 v2.2", get_shop("nail").title_version == "nail_title_v2.2" and bool(get_shop("nail").title_rule))
check("Lady 走自己的 v1（大詞開頭、零符號、不放品牌與品號）",
      get_shop("lady").title_version == "lady_title_v1" and "不放品牌標籤" in get_shop("lady").title_rule)
check("Baby 仍沿用舊規則", get_shop("baby").title_rule == "")
t4, f4, _ = check_title("🏆免運隔日到貨!【冰絲丁字褲】無痕內褲 丁字褲 H-c53", code="H-c53")
check("emoji 與符號都拿掉、促銷詞與編號也拿掉", t4 == "冰絲丁字褲 無痕內褲 丁字褲", t4)
_, _, w4 = check_title("闊腿褲 亞麻寬褲 深灰長褲 褲子", pool={"闊腿褲", "褲子"})
check("詞庫外又沒依據的詞會提醒（第一個形態詞除外）", any("深灰長褲" in x for x in w4), w4)
_, _, w5 = check_title("闊腿褲 亞麻寬褲 高腰 垂感 薄款", pool={"闊腿褲"},
                       product_words="高腰直筒 垂感自然 薄款無彈 亞麻混紡")
check("商品資料裡找得到的特徵詞不提醒", not any("零搜尋量" in x for x in w5), w5)
_, _, w6 = check_title("闊腿褲 亞麻寬褲 薄款垂感無彈", pool={"闊腿褲"},
                       product_words="垂感自然 薄款 無彈 亞麻")
check("串成一長串的特徵詞也認得（拆兩字比對）", not any("零搜尋量" in x for x in w6), w6)

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
