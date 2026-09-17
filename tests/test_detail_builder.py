"""Nail 詳情組裝回歸測試（免 pytest：`.venv/bin/python tests/test_detail_builder.py`，不連網）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.detail_builder import NOTICE, assemble_description, notice_kind  # noqa: E402
from scraper.shops import get_shop  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


print("注意事項分類")
check("膠類分類 ID", notice_kind("102178", "磨甲機") == "光療")
check("品名含膠", notice_kind("102031", "HNG1 貓眼膠") == "光療")
check("磨甲機＝電器", notice_kind("102031", "M50 充電磨甲機") == "電器")
check("美甲燈＝電器", notice_kind("102031", "瓷白美甲燈 298W") == "電器")
check("濾紙歸耗材（即使 1688 標題是吸塵器）",
      notice_kind("102031", "迷你版集塵器的過濾紙", "新款静音美甲吸尘器") == "工具耗材")
check("品名認得出就不看 1688 標題（機器頁標題含過濾網）",
      notice_kind("102031", "高階雙渦輪集塵器", "集尘器 带过滤网") == "電器")
check("認不出＝工具耗材", notice_kind("102031", "木座收納盒") == "工具耗材")

print("組裝")
ai = "✦ 商品特色\n好用\n\n✦ 使用方法\n1. 開機\n\n✦ 注意事項\nAI 自己寫的\n\n✦ 賣場介紹\n提供現貨"
v = {"規格1_顏色": [{"option_name": "磨甲機_白色"}, {"option_name": "磨甲機_黑色"}], "規格2_尺碼": []}
d = assemble_description(ai, v, "102031", "M50 充電磨甲機")
check("AI 多寫的注意事項/賣場介紹被切掉", "AI 自己寫的" not in d and "提供現貨" not in d, d)
check("保留 AI 三段", "✦ 商品特色" in d and "✦ 使用方法" in d)
check("款式說明列出選項", "✦ 款式說明\n・磨甲機_白色\n・磨甲機_黑色" in d, d)
check("注意事項用電器固定文案", all(x in d for x in NOTICE["電器"]))
check("只有一段注意事項", d.count("✦ 注意事項") == 1)
check("不寫退換貨/推薦", "退換貨" not in d and "推薦搭配" not in d)
v2 = {"規格1_顏色": [{"option_name": "白"}], "規格2_尺碼": [{"option_name": "8ml"}, {"option_name": "15ml"}]}
check("第二軸列成可選規格", "可選規格：8ml／15ml" in assemble_description("✦ 商品特色\nx", v2, "102178"))

print("賣場設定")
check("Nail 有詳情規則與版號", bool(get_shop("nail").detail_rule) and bool(get_shop("nail").detail_version))
check("Lady 不受影響（沿用 8 區塊）", get_shop("lady").detail_rule == "")

print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
