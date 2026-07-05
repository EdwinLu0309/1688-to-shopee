"""
去風險測試：用 Playwright + 登入 cookie + stealth 抓一頁 1688 detail，
驗證「不靠 Chrome MCP、靠 1688-order 同款登入法」能不能過反爬抓到資料。

跑法：
    .venv/bin/python tools/scrape_playwright_test.py [item_id]
- 有 config/cookies.json 就帶著抓；抓到 0 圖（過期/被擋）會開瀏覽器讓你登入後存檔重抓。
- 對照組：P-a1 (784712770291) 已知 9 主圖 / 31 細節 / 6 色。
"""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
COOKIE_PATH = ROOT / "config" / "cookies.json"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# extract_1688.js 的抽取邏輯（回傳完整 data，不做 Blob 下載）
EXTRACT_JS = r"""() => {
  const norm = (u) => { if(!u) return ""; u=String(u).trim(); if(u.startsWith("//")) u="https:"+u; return u.startsWith("http")?u:""; };
  const orig = (u) => { u=norm(u); if(!u) return ""; const m=u.match(/\.(jpg|jpeg|png|webp|gif)/i); return m?u.slice(0,m.index)+m[0]:u; };
  const uniq = (a) => [...new Set(a.filter(Boolean))];
  const itemId = (location.href.match(/offer\/(\d+)\.html/)||[])[1] || "unknown";
  const main = uniq([...document.querySelectorAll(".od-gallery-list img, .od-gallery-list-wapper img")].map(i=>orig(i.getAttribute("src")||i.getAttribute("data-src")||"")));
  const sku_images={}, skus=[];
  document.querySelectorAll(".sku-filter-button").forEach(btn=>{const img=btn.querySelector("img");const nameEl=btn.querySelector(".label-name");const name=(nameEl?nameEl.textContent:btn.textContent||"").trim();const u=img?orig(img.getAttribute("src")||img.getAttribute("data-src")||""):"";if(name&&u)sku_images[name]=u;if(name)skus.push({sku_id:"",attributes:{规格:name},price:0,stock:0,image_url:u});});
  const detailHtml=(window.offer_details&&window.offer_details.content)||"";
  const detail=[];const re=/<img[^>]+(?:data-lazyload-src|data-src|src)=["']([^"']+)["']/gi;let m;
  while((m=re.exec(detailHtml))){const u=orig(m[1]);if(u&&/alicdn/.test(u))detail.push(u);}
  const attributes={};
  document.querySelectorAll(".ant-table-tbody tr").forEach(tr=>{const td=[...tr.querySelectorAll("td")].map(x=>x.textContent.trim());if(td.length>=2&&td[0])attributes[td[0]]=td[1];});
  const sizes=(attributes["尺码"]||attributes["尺碼"]||"").split(/[、,，]/).map(s=>s.trim()).filter(Boolean);
  return {item_id:itemId, title:(document.title||"").replace(/ - 阿里巴巴$/,"").trim(),
    attributes, main_images:main, detail_images:uniq(detail), sku_images, skus, sizes,
    _blocked: /验证|verify|滑动|安全验证|robot/i.test(document.body?document.body.innerText.slice(0,500):"")};
}"""


async def scrape(item_id: str, login_if_needed: bool = True) -> dict:
    url = f"https://detail.1688.com/offer/{item_id}.html"
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = await browser.new_context(
            user_agent=UA, viewport={"width": 1440, "height": 900},
            locale="zh-CN", timezone_id="Asia/Shanghai",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        if COOKIE_PATH.exists():
            try:
                await context.add_cookies(json.loads(COOKIE_PATH.read_text()))
                print(f"  已載入 {COOKIE_PATH} 的 cookie")
            except Exception as e:
                print(f"  cookie 載入失敗：{e}")

        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await _scroll(page)
        data = await page.evaluate(EXTRACT_JS)

        if (not data["main_images"] or data.get("_blocked")) and login_if_needed:
            print("\n  ⚠ 抓到 0 圖或偵測到驗證頁 → cookie 可能過期。")
            print("  開登入頁，請在瀏覽器手動登入 1688（最多等 5 分鐘）…")
            await page.goto("https://login.1688.com/member/signin.htm", wait_until="domcontentloaded")
            try:
                await page.wait_for_url(lambda u: "login.1688.com" not in u and "1688.com" in u, timeout=300_000)
                cookies = await context.cookies()
                COOKIE_PATH.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
                print(f"  ✓ 登入成功，cookie 已存 {COOKIE_PATH}（{len(cookies)} 筆）")
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await _scroll(page)
                data = await page.evaluate(EXTRACT_JS)
            except Exception as e:
                print(f"  登入等待逾時/失敗：{e}")

        await browser.close()
        return data


async def _scroll(page):
    """慢慢往下捲，觸發 lazy-load 的圖庫/細節圖/屬性表。"""
    for _ in range(8):
        await page.mouse.wheel(0, 1400)
        await page.wait_for_timeout(700)
    await page.wait_for_timeout(1200)


def main():
    item_id = sys.argv[1] if len(sys.argv) > 1 else "784712770291"
    print(f"抓取測試：{item_id}")
    data = asyncio.run(scrape(item_id))
    print("\n=== 結果 ===")
    print(f"  標題：{data.get('title','')[:40]}")
    print(f"  主圖 {len(data.get('main_images',[]))} / 細節 {len(data.get('detail_images',[]))} "
          f"/ 色 {len(data.get('sku_images',{}))} / 尺碼 {len(data.get('sizes',[]))}")
    print(f"  色名：{list(data.get('sku_images',{}).keys())}")
    print(f"  被擋?：{data.get('_blocked')}")
    ok = len(data.get("main_images", [])) > 0
    print(f"\n  {'✅ 抓取成功 — Playwright+cookie 這條路可行，可做全包 GUI' if ok else '❌ 抓不到 — 退回只包下游（抓取續用 Chrome MCP）'}")


if __name__ == "__main__":
    main()
