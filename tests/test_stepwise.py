"""分步重生＋圖片模板回歸測試（免 pytest：`.venv/bin/python tests/test_stepwise.py`，不連網、不花錢）。

守的是 Edwin 2026-09-19 定的規格：
- 分步重生「只換一樣、其餘沿用上一版」，沒按過 🚀 開始的商品一律擋
- 上架檔與 1-1 的選項品號必須一對一（多了／少了／改號都要擋）
- 圖片模板＝一份 md 一個下拉選項，檔頭宣告張數；只生封面時 1688 第 2~9 張要留著
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scraper.batch_pipeline2 as bp  # noqa: E402
from scraper.image_templates import merge_images, parse_template  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


tmp = Path(tempfile.mkdtemp())

print("圖片模板：檔頭設定")
md = tmp / "九宮格.md"
md.write_text("""---
張數: 9      # 九宮格
輸入: 對應原圖
板娘: 用
---
# 規範

共用規則。

### 第 1 張｜封面
封面要求

### 第 2～3 張｜賣點
賣點要求

---

## 其他
不屬於任何一張
""", encoding="utf-8")
t = parse_template(md)
check("張數 9", t.count == 9)
check("對應原圖", t.input_mode == "對應原圖")
check("板娘用、對手參考沒寫＝不用", t.use_persona and not t.use_reference)
check("設定區不進規範", "張數" not in t.spec and "共用規則" in t.spec)
check("第 1 張有自己的段落", "封面要求" in t.slot_notes.get(1, ""))
check("第 2～3 張共用一段", "賣點要求" in t.slot_notes.get(2, "") and t.slot_notes.get(2) == t.slot_notes.get(3))
check("段尾分隔線與下一個大標不算進去", "不屬於" not in t.slot_notes.get(3, "") and not t.slot_notes[3].rstrip().endswith("---"))
check("沒寫段落的張次沒有 note", 4 not in t.slot_notes)
check("指令點名第幾張", "第 3 張（共 9 張）" in t.prompt_for(3) and "賣點要求" in t.prompt_for(3))

plain = tmp / "舊版.md"
plain.write_text("# 只有規範、沒有檔頭\n內容", encoding="utf-8")
t2 = parse_template(plain)
check("沒檔頭＝封面 1 張、板娘不用（不再三家混用板娘臉）",
      t2.count == 1 and not t2.use_persona and not t2.use_reference and t2.label == "封面 1 張")
check("封面指令沿用舊措辭", "封面（Cover）" in t2.prompt_for(1))
huge = tmp / "太多.md"
huge.write_text("---\n張數: 30\n---\n x", encoding="utf-8")
check("張數上限 9（蝦皮最多 9 張）", parse_template(huge).count == 9)

print("圖片合併：GPT × 1688")
base = [f"1688_{i}" for i in range(1, 10)]
cover = {"slots": [{"n": 1, "url": "gpt_1"}]}
m = merge_images(cover, base)
check("只生封面 → 1688 第 2~9 張保留（舊版只剩 1 張）", m == ["gpt_1"] + base[1:], m)
nine = {"slots": [{"n": i, "url": (f"gpt_{i}" if i != 4 else None)} for i in range(1, 10)]}
m = merge_images(nine, base)
check("九張：失敗那格沿用 1688 同位置", m[3] == "1688_4" and m[0] == "gpt_1" and m[8] == "gpt_9", m)
check("沒有 GPT → 原樣 1688", merge_images(None, base) == base)
check("1688 圖不足也不會掉 GPT 圖", merge_images(nine, ["1688_1"])[:3] == ["gpt_1", "gpt_2", "gpt_3"])

print("選項 ↔ 品號一對一")
variants = {"規格1_顏色": [{"src_1688": "黑色"}, {"src_1688": "白色"}],
            "規格2_尺碼": [{"size": "S"}, {"size": "M"}]}
keys = bp.variant_keys(variants)
check("選項 key＝顏色×尺碼", keys == {("黑色", "S"), ("黑色", "M"), ("白色", "S"), ("白色", "M")})
check("單軸商品尺碼為空字串",
      bp.variant_keys({"規格1_顏色": [{"src_1688": "美規"}], "規格2_尺碼": []}) == {("美規", "")})
have = {("黑色", "S"): "B1", ("黑色", "M"): "B2", ("白色", "S"): "B3", ("白色", "M"): "B4"}
check("完全一致＝沒有差異", not any(bp.compare_option_maps(dict(have), have).values()))
d = bp.compare_option_maps({**have, ("紅色", "S"): "B5"}, have)
check("多了一個選項要抓到", d["多了"] == ["紅色／S"] and not d["少了"])
d = bp.compare_option_maps({k: v for k, v in have.items() if k != ("白色", "M")}, have)
check("少了一個選項要抓到", d["少了"] == ["白色／M"])
d = bp.compare_option_maps({**have, ("黑色", "S"): "B9"}, have)
check("同一選項配到不同品號要抓到", d["改號"] == ["黑色／S B1→B9"])
msg = bp.option_mismatch_message({"H-c2": bp.compare_option_maps({**have, ("紅色", "S"): "B5"}, have)}, "提示")
check("訊息列出編號與差異", "H-c2" in msg and "紅色／S" in msg and "提示" in msg)
check("map ↔ list 來回不變", bp._list_to_map(bp._map_to_list(have)) == have)

print("上一版紀錄與防呆")
root = tmp / "batch"
orig_raw, orig_batch = bp.RAW_DIR, bp.BATCH_DIR
bp.RAW_DIR, bp.BATCH_DIR = tmp / "raw", root
(tmp / "raw").mkdir()
for item in ("111", "222", "333"):
    (tmp / "raw" / f"{item}.json").write_text("{}", encoding="utf-8")


def make_version(day, n, items, excel="上架檔.xlsx"):
    d = root / "lady" / day / f"文案_v{n}"
    d.mkdir(parents=True)
    (d / excel).write_text("x", encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps(
        {"上架檔": excel, "商品": items}, ensure_ascii=False), encoding="utf-8")


make_version("20260918", 1, [
    {"code": "A1", "item_id": "111", "option_map": None,
     "option_sku_map": bp._map_to_list(have), "staged": True, "gpt_set": None, "sop": None}])
make_version("20260919", 2, [
    {"code": "A1", "item_id": "111", "option_sku_map": bp._map_to_list(have),
     "staged": True, "gpt_set": "/x/set", "sop": None}])
make_version("20260919", 1, [                      # 同一天的較舊版本，不可蓋掉 v2
    {"code": "A1", "item_id": "111", "option_sku_map": [], "staged": False}])
make_version("20260919", 3, [
    {"code": "B2", "item_id": "222", "option_sku_map": [], "staged": False}], excel="上架檔_試跑.xlsx")
make_version("20260910", 1, [                      # 9/19 以前的舊格式：只有品號清單
    {"code": "L9", "item_id": "333", "skus": ["AL1", "AL2"]}])
recs = bp.latest_records("lady", root)
old_rec = recs[("L9", "333")]
check("舊版 manifest＝legacy、當作有建檔", old_rec["legacy"] and old_rec["staged"] and old_rec["skus"] == ["AL1", "AL2"])
check("舊版紀錄的商品不會被防呆誤擋",
      "L9" not in bp.missing_prereqs("lady", [{"code": "L9", "item_id": "333"}], "copy", recs))
check("取最新一版（日期＋版號都比）", recs[("A1", "111")]["version"] == "文案_v2"
      and recs[("A1", "111")]["gpt_set"] == "/x/set", recs.get(("A1", "111")))
check("品號對照讀得回來", recs[("A1", "111")]["option_map"] == have)

sel = [{"code": "A1", "item_id": "111"}, {"code": "B2", "item_id": "222"},
       {"code": "C3", "item_id": "333"}, {"code": "D4", "item_id": "444"}]
miss = bp.missing_prereqs("lady", sel, "copy", recs)
check("齊全的不擋", "A1" not in miss, miss.get("A1"))
check("試跑版（沒建 1-1）要擋", "上一版沒建 1-1（沒有品號）" in miss.get("B2", []), miss.get("B2"))
check("沒產過上架檔要擋", "還沒產過上架檔" in miss.get("C3", []))
check("沒抓過 1688 要擋", "沒抓過 1688" in miss.get("D4", []))
check("重生圖片要求文案還在（A1 沒有文案快取）",
      any("文案" in w for w in bp.missing_prereqs("lady", sel[:1], "images", recs).get("A1", [])))
try:
    bp.run_batch_two_tier(products=sel[1:2], shop="lady", mode="copy", make_video=False)
    check("run_batch 分步模式也自己擋（不只靠 GUI）", False, "沒有丟例外")
except ValueError as e:
    check("run_batch 分步模式也自己擋（不只靠 GUI）", "B2" in str(e) and "🚀 開始" in str(e), str(e))

print("圖從哪來")
rec = {"gpt_set": "/prior"}
check("重生文案：圖沿用上一版", bp._image_plan({"item_id": "111"}, "copy", rec, "T").get("_gpt_set_dir") == "/prior")
check("重生文案：上一版是 1688 圖就維持 1688",
      "_gpt_set_dir" not in bp._image_plan({"item_id": "111"}, "copy", {"gpt_set": None}, "T"))
check("重生圖片：一定重生（用選的模板）", bp._image_plan({"item_id": "111"}, "images", rec, "T").get("_gen_template") == "T")
try:
    bp._image_plan({"item_id": "111"}, "images", rec, None)
    check("重生圖片沒選模板要擋", False)
except ValueError:
    check("重生圖片沒選模板要擋", True)
check("🚀 開始：上一版有 GPT 圖就沿用（不因沒勾 ✨ 退回 1688）",
      bp._image_plan({"item_id": "111", "route": "1688"}, "start", rec, "T").get("_gpt_set_dir") == "/prior")
e = bp._image_plan({"item_id": "999", "route": "gpt"}, "start", None, "T")
check("🚀 開始：勾 ✨ 且沒生過 → 生", e.get("_gen_template") == "T")
check("🚀 開始：沒勾 ✨ 也沒上一版 → 1688",
      not {"_gen_template", "_gpt_set_dir"} & set(bp._image_plan({"item_id": "999"}, "start", None, "T")))

bp.RAW_DIR, bp.BATCH_DIR = orig_raw, orig_batch
print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
