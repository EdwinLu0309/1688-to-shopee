"""
Playwright + 登入 cookie + stealth 版 1688 抓取器（供 GUI「🔍 抓取」用）。

背景（#S066 去風險驗證）：#S064 曾下結論「Playwright 開 1688 被反爬擋」——但那是
在「沒帶登入 cookie」的情況。實測帶上 config/cookies.json（1688-order 同款登入法）+
stealth（改 navigator.webdriver / UA / locale）後，detail 頁可正常抓，未被擋。
tools/scrape_playwright_test.py 是當時的驗證腳本，本模組是它的正式化 + 補全：

- 產出的 JSON schema 與 extract_1688.js（Chrome MCP 版）對齊，故下游
  images / batch2 / generate2 完全不用改就能吃。
- 主圖補強：1688 圖庫縮圖是 lazy-load，只 scroll 常只抓到 5 張；本模組逐一 hover
  縮圖觸發載入後再抽，能補齊（P-a1 目標 9 張）。

⚠️ EXTRACT_JS 與 scraper/extract_1688.js 是「兩份平行實作、同一套選擇器」：
   1688 改版時兩邊都要改。extract_1688.js 走 Blob 下載（Chrome MCP 注入），
   本檔走 page.evaluate 直接回傳 data。選擇器邏輯務必保持一致。
"""
import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

from loguru import logger

from config.settings import OUTPUT_DIR

ROOT = Path(__file__).resolve().parent.parent
COOKIE_PATH = ROOT / "config" / "cookies.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 抽取邏輯：與 extract_1688.js 同一套選擇器，但回傳完整 data（不做 Blob 下載）。
EXTRACT_JS = r"""() => {
  const norm = (u) => { if(!u) return ""; u=String(u).trim(); if(u.startsWith("//")) u="https:"+u; return u.startsWith("http")?u:""; };
  const orig = (u) => { u=norm(u); if(!u) return ""; const m=u.match(/\.(jpg|jpeg|png|webp|gif)/i); return m?u.slice(0,m.index)+m[0]:u; };
  const uniq = (a) => [...new Set(a.filter(Boolean))];
  const itemId = (location.href.match(/offer\/(\d+)\.html/)||[])[1] || "unknown";

  // 主圖：圖庫縮圖（多選擇器容錯）
  const main = uniq([...document.querySelectorAll(
      ".od-gallery-list img, .od-gallery-list-wapper img, .od-gallery-turn-wrapper img, .detail-gallery-turn-wrapper img"
    )].map(i => orig(i.getAttribute("src")||i.getAttribute("data-src")||"")));

  // SKU 色卡（第一軸）name -> 圖 + skus 清單
  const sku_images={}, skus=[];
  document.querySelectorAll(".sku-filter-button").forEach(btn=>{
    const img=btn.querySelector("img");
    const nameEl=btn.querySelector(".label-name");
    const name=(nameEl?nameEl.textContent:btn.textContent||"").trim();
    const u=img?orig(img.getAttribute("src")||img.getAttribute("data-src")||""):"";
    if(name&&u)sku_images[name]=u;
    if(name)skus.push({sku_id:"",attributes:{规格:name},price:0,stock:0,image_url:u});
  });

  // 細節圖：商品描述 HTML 內的 <img>
  const detailHtml=(window.offer_details&&window.offer_details.content)||"";
  const detail=[];
  const re=/<img[^>]+(?:data-lazyload-src|data-src|src)=["']([^"']+)["']/gi; let m;
  while((m=re.exec(detailHtml))){const u=orig(m[1]);if(u&&/alicdn/.test(u))detail.push(u);}

  // 商品屬性表（Ant Design）→ attributes dict（材質/版型/厚薄/彈力 + 第二軸尺碼來源）
  const attributes={};
  document.querySelectorAll(".ant-table-tbody tr").forEach(tr=>{
    const td=[...tr.querySelectorAll("td")].map(x=>x.textContent.trim());
    if(td.length>=2&&td[0])attributes[td[0]]=td[1];
  });
  const sizes=(attributes["尺码"]||attributes["尺碼"]||"").split(/[、,，]/).map(s=>s.trim()).filter(Boolean);

  // 買區「尺碼 ¥價 库存N件」列 → size_stock + price_cny
  const size_stock={}; let price_cny=0;
  [...document.querySelectorAll("*")]
    .filter(e=>e.children.length===0 && /库存\d+件/.test(e.textContent))
    .forEach(n=>{
      let row=n;
      for(let i=0;i<5&&row.parentElement;i++){row=row.parentElement;
        if(/[¥￥]/.test(row.textContent)&&/库存/.test(row.textContent))break;}
      const txt=row.textContent.replace(/\s+/g,"");
      const mm=txt.match(/^(.+?)[¥￥]([\d.]+)库存(\d+)件/);
      if(mm){size_stock[mm[1]]={price:parseFloat(mm[2]),stock:parseInt(mm[3],10)};
        if(!price_cny)price_cny=parseFloat(mm[2]);}
    });

  return {
    item_id:itemId,
    title:(document.title||"").replace(/ - 阿里巴巴$/,"").trim(),
    description:"", categories:[], shop_name:"", shop_url:"", shop_location:"",
    shop_ratings:{}, min_order:0, origin_price:price_cny, price_ranges:[],
    attributes, main_images:main, detail_images:uniq(detail), video_url:"",
    sku_images, skus, sizes, size_stock, price_cny,
    _blocked: /验证|滑动|安全验证|robot|captcha/i.test(document.body?document.body.innerText.slice(0,500):""),
  };
}"""


def _apply_stealth_context_kwargs() -> dict:
    return {
        "user_agent": USER_AGENT,
        "viewport": {"width": 1440, "height": 900},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
    }


async def _prep_context(pw, cookie_path: Path, headless: bool):
    browser = await pw.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context(**_apply_stealth_context_kwargs())
    await context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    if cookie_path.exists():
        try:
            await context.add_cookies(json.loads(cookie_path.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"cookie 載入失敗：{e}")
    return browser, context


async def _scroll(page) -> None:
    """慢慢往下捲，觸發 lazy-load 的圖庫 / 細節圖 / 屬性表。"""
    for _ in range(8):
        await page.mouse.wheel(0, 1400)
        await page.wait_for_timeout(650)
    await page.wait_for_timeout(1000)


async def _hover_thumbnails(page) -> None:
    """逐一 hover 圖庫縮圖，觸發 lazy-load 主圖（只 scroll 常漏抓，只拿到 5 張）。"""
    try:
        thumbs = await page.query_selector_all(
            ".od-gallery-list img, .od-gallery-list-wapper img"
        )
        for t in thumbs[:20]:
            try:
                await t.hover(timeout=800)
                await page.wait_for_timeout(120)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass


async def save_cookies(cookie_path: Path = COOKIE_PATH) -> int:
    """開瀏覽器讓使用者手動登入 1688，登入後存 cookie。回傳 cookie 筆數。

    偵測跳離 login.1688.com 視為登入成功；最多等 5 分鐘。抄自 1688-order launcher。
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    context = await browser.new_context(**_apply_stealth_context_kwargs())
    await context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    page = await context.new_page()
    await page.goto("https://login.1688.com/member/signin.htm", wait_until="domcontentloaded")
    try:
        await page.wait_for_url(
            lambda url: "login.1688.com" not in url and "1688.com" in url,
            timeout=300_000,
        )
    except Exception:  # noqa: BLE001
        pass  # 逾時也嘗試存檔

    cookies = await context.cookies()
    cookie_path.parent.mkdir(parents=True, exist_ok=True)
    cookie_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    await browser.close()
    await pw.stop()
    return len(cookies)


async def scrape_offer(
    item_id: str,
    cookie_path: Path = COOKIE_PATH,
    headless: bool = False,
) -> dict:
    """抓單一 1688 offer → data dict（schema 對齊 extract_1688.js）。"""
    from playwright.async_api import async_playwright

    url = f"https://detail.1688.com/offer/{item_id}.html"
    async with async_playwright() as pw:
        browser, context = await _prep_context(pw, cookie_path, headless)
        try:
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await _scroll(page)
            await _hover_thumbnails(page)
            data = await page.evaluate(EXTRACT_JS)
            return data
        finally:
            await browser.close()


async def scrape_many(
    item_ids: list[str],
    cookie_path: Path = COOKIE_PATH,
    out_dir: Path = Path(OUTPUT_DIR),
    headless: bool = False,
    progress_cb: Callable[[str], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    """批次抓多個 offer（共用一個瀏覽器），逐一存 output/{item_id}.json。

    回傳 {total, success, blocked, failed, results:[{item_id, ok, main, detail, sku, blocked}]}。
    progress_cb 收進度字串（給 GUI 狀態列）；cancel_check() 回 True 時中止。
    """
    from playwright.async_api import async_playwright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def emit(msg: str) -> None:
        logger.info(msg)
        if progress_cb:
            progress_cb(msg)

    results: list[dict] = []
    blocked = failed = success = 0

    async with async_playwright() as pw:
        browser, context = await _prep_context(pw, cookie_path, headless)
        try:
            for i, raw in enumerate(item_ids, 1):
                if cancel_check and cancel_check():
                    emit("已取消抓取")
                    break
                item_id = str(raw).strip()
                emit(f"[{i}/{len(item_ids)}] 抓取 {item_id} …")
                try:
                    page = await context.new_page()
                    await page.goto(
                        f"https://detail.1688.com/offer/{item_id}.html",
                        wait_until="domcontentloaded", timeout=45000,
                    )
                    await _scroll(page)
                    await _hover_thumbnails(page)
                    data = await page.evaluate(EXTRACT_JS)
                    await page.close()
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    results.append({"item_id": item_id, "ok": False, "error": str(e)})
                    emit(f"  ✗ {item_id} 抓取失敗：{e}")
                    continue

                n_main = len(data.get("main_images", []))
                n_detail = len(data.get("detail_images", []))
                n_sku = len(data.get("sku_images", {}))
                is_blocked = bool(data.get("_blocked")) or n_main == 0

                (out_dir / f"{item_id}.json").write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )

                if is_blocked:
                    blocked += 1
                    emit(f"  ⚠ {item_id} 疑似被擋/cookie 過期（主圖 0）→ 請重新登入")
                else:
                    success += 1
                    emit(f"  ✓ {item_id}：主圖 {n_main} / 細節 {n_detail} / 色 {n_sku}")
                results.append({
                    "item_id": item_id, "ok": not is_blocked, "blocked": is_blocked,
                    "main": n_main, "detail": n_detail, "sku": n_sku,
                })
        finally:
            await browser.close()

    return {
        "total": len(item_ids), "success": success,
        "blocked": blocked, "failed": failed, "results": results,
    }
