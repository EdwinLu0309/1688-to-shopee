"""規格圖片抓取回歸測試（真 Chromium 開靜態頁，免 pytest：`.venv/bin/python tests/test_sku_images.py`）。

2026-09-17：美甲的機器/耗材頁是「一列一個規格」版面，沒有色票按鈕 →
舊抓取器 sku_images 全空（9/9 那批 26 支規格圖片欄一格都沒有）。
守住：①頁面狀態 skuProps 的原圖 ②買區列 <img>＋.item-label 補位
③「去空白」key 對得上 size_stock 的名稱 ④色票版面（女裝）照舊 ⑤沒圖的選項不亂塞。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.playwright_scraper import EXTRACT_JS  # noqa: E402

FAILED = []


def check(name, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {name} {'' if cond else extra}")
    if not cond:
        FAILED.append(name)


IMG = "https://cbu01.alicdn.com/img/ibank/O1CN01{}_!!1-0-cib.jpg"


def row(name, img):
    im = f'<div class="ant-image"><img src="{IMG.format(img)}_sum.jpg"></div>' if img else ""
    return (f'<div class="expand-view-item v-flex"><div class="v-flex">{im}'
            f'<span class="item-label" title="{name}">{name}</span></div>'
            f'<span class="item-price-stock">¥23</span>'
            f'<span class="item-price-stock"><od-text>库存83671个</od-text></span></div>')


ROW_PAGE = """<html><head><title>集塵器 - 阿里巴巴</title></head><body>
<script>window.__STATE__ = {data: {skuModel: {skuProps: [{prop: "规格", value: [
  {name: "蓝色", imageUrl: "%s"},
  {name: "5包-M3 吸尘器【过滤纸*10pcs/包】", imageUrl: "%s"}]}]}}};</script>
<div class="module-od-sku-selection">%s</div></body></html>""" % (
    IMG.format("blue"), IMG.format("pack"),
    row("蓝色", "blue") + row("5包-M3 吸尘器【过滤纸*10pcs/包】", "pack")
    + row("只有列圖", "rowonly") + row("其他定制，旺旺咨询", None))

BTN_PAGE = """<html><head><title>褲子 - 阿里巴巴</title></head><body>
<div class="module-od-sku-selection">
<button class="sku-filter-button"><img src="%s_sum.jpg"><span class="label-name">黑色【常规款】</span></button>
</div></body></html>""" % IMG.format("black")


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True)
        page = await b.new_page()

        print("一列一個規格（美甲機器／耗材）")
        await page.set_content(ROW_PAGE)
        d = await page.evaluate(EXTRACT_JS)
        si = d["sku_images"]
        names = [s["attributes"]["规格"] for s in d["skus"]]
        check("skus 從買區列長出來", "蓝色" in names, names)
        check("狀態原圖（不是 _sum 縮圖）", si.get("蓝色") == IMG.format("blue"), si.get("蓝色"))
        check("去空白的名稱也對得到", si.get("5包-M3吸尘器【过滤纸*10pcs/包】") == IMG.format("pack"),
              json.dumps(si, ensure_ascii=False))
        check("狀態沒有的，用買區列的圖補", si.get("只有列圖") == IMG.format("rowonly"), si.get("只有列圖"))
        check("沒圖的選項不亂塞", "其他定制，旺旺咨询" not in si)
        by = {s["attributes"]["规格"]: s["image_url"] for s in d["skus"]}
        check("skus 的 image_url 也帶上", by.get("蓝色") == IMG.format("blue"), by)

        print("色票按鈕（女裝）")
        await page.set_content(BTN_PAGE)
        d = await page.evaluate(EXTRACT_JS)
        check("色票版面照舊", d["sku_images"].get("黑色【常规款】") == IMG.format("black"), d["sku_images"])
        await b.close()


asyncio.run(main())
print()
if FAILED:
    print(f"❌ {len(FAILED)} 項失敗：{FAILED}")
    sys.exit(1)
print("✅ 全部通過")
