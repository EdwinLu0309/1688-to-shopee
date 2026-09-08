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
# #S134 階段4：抓取讀 cookie-hub 標準庫的 1688 服飾帳號（原 config/cookies.json 已收攏至此）
COOKIE_PATH = Path.home() / ".joyslu" / "cookies" / "1688_lady.json"

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

  // 主圖：1688 把完整圖庫存在 JS 狀態的 offerImgList（DOM 只 render 前 5 張縮圖，
  // 只抓 .od-gallery-list img 會少抓）。先從 window 遞迴找 offerImgList，去重取原圖；
  // 找不到才退回 DOM 選擇器。P-a1 實測：offerImgList 11 筆→去重 9 張（＝要的張數）。
  const findOfferImgList = () => {
    const seen = new WeakSet(); let found = null;
    const walk = (o, d) => {
      if (found || d > 6 || !o || typeof o !== "object" || seen.has(o)) return;
      seen.add(o);
      for (const k in o) {
        try {
          if (k === "offerImgList" && Array.isArray(o[k]) && o[k].length) { found = o[k]; return; }
          const v = o[k];
          if (v && typeof v === "object") walk(v, d + 1);
        } catch (e) {}
      }
    };
    for (const k of Object.keys(window)) { try { walk(window[k], 0); } catch (e) {} if (found) break; }
    return found;
  };
  let main = uniq((findOfferImgList() || []).map(orig));
  if (!main.length) {
    main = uniq([...document.querySelectorAll(
        ".od-gallery-list img, .od-gallery-list-wapper img, .od-gallery-turn-wrapper img, .detail-gallery-turn-wrapper img"
      )].map(i => orig(i.getAttribute("src")||i.getAttribute("data-src")||"")));
  }

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

  // 買區「規格 ¥價 库存N<單位>」列 → size_stock + price_cny
  // ⚠️ 單位不是只有「件」：實測美甲類多為「个」，另有 条/套/双/包/盒…
  //    寫死「件」→ 一列都篩不到 → price_cny=0、size_stock={} → 下游 0 SKU、Excel 空殼，
  //    而且完全不報錯。（同坑 1688-order/master_audit 早已修過。）
  const size_stock={}; let price_cny=0;
  [...document.querySelectorAll("*")]
    .filter(e=>e.children.length===0 && /库存\s*\d+\s*[\u4e00-\u9fa5]{0,2}/.test(e.textContent))
    .forEach(n=>{
      let row=n;
      for(let i=0;i<5&&row.parentElement;i++){row=row.parentElement;
        if(/[¥￥]/.test(row.textContent)&&/库存/.test(row.textContent))break;}
      const txt=row.textContent.replace(/\s+/g,"");
      const mm=txt.match(/^(.+?)[¥￥]([\d.]+)库存(\d+)[\u4e00-\u9fa5]{0,2}/);
      if(mm){size_stock[mm[1]]={price:parseFloat(mm[2]),stock:parseInt(mm[3],10)};
        if(!price_cny)price_cny=parseFloat(mm[2]);}
    });

  // ⚠️ 沒有色票（.sku-filter-button）時，買區那幾列**就是商品唯一的那一軸**。
  //    美甲的機器/工具類多半長這樣（規格＝美规/欧规/其他规格、容量、型號），
  //    不像女裝有「顏色色票 × 尺碼」兩軸。不補的話第一軸是空的 →
  //    Claude 回的 color_map 空 → 變體 0 個 → **Excel 產出沒有任何規格行的空殼**，
  //    而整條流程一路成功、不報錯（實測 HNV7 集塵器：價格庫存都抓到了、SKU 仍是 0）。
  if(skus.length===0){
    for(const k of Object.keys(size_stock)){
      skus.push({sku_id:"",attributes:{规格:k},price:size_stock[k].price||0,
                 stock:size_stock[k].stock||0,image_url:""});
    }
  }

  // 賣家為國內運費填的「長/寬/高/體積/重量(g)」表 → 上架 Excel 的重量欄。
  // ⚠️ 抓不到就留空、由 Python 端大聲 warning，**不可退回寫死的 0.1kg**：
  //    假重量會讓蝦皮運費與獲利表的結構版國際運費一起算錯，而且看起來像真的。
  //    同頁可能有多張表（多 offer 版面），全收給 Python 端挑。
  const weight_tables=[]; const _wseen=new Set();
  for(const el of document.querySelectorAll("td,th,div,span")){
    const wt=(el.innerText||"").trim();
    if(/^重量\s*\(?(g|克)\)?$/.test(wt) && wt.length<12){
      const holder=el.closest("table")||(el.parentElement&&el.parentElement.parentElement);
      if(!holder) continue;
      const txt=holder.innerText||"";
      if(txt && !_wseen.has(txt)){ _wseen.add(txt); weight_tables.push(txt.slice(0,30000)); }
    }
  }

  return {
    weight_tables,
    item_id:itemId,
    title:(document.title||"").replace(/ - 阿里巴巴$/,"").trim(),
    description:"", categories:[], shop_name:"", shop_url:"", shop_location:"",
    shop_ratings:{}, min_order:0, origin_price:price_cny, price_ranges:[],
    attributes, main_images:main, detail_images:uniq(detail),
    video_url:(function(){var v=document.querySelector("video");return v&&v.src?v.src:"";})(),
    sku_images, skus, sizes, size_stock, price_cny,
    // ⚠️ 判「被驗證碼擋」要看 **document.title**，不要掃 body 前 500 字。
    //    商品頁本來就常出現「滑动查看更多」「实名验证」這種字 → 舊寫法會把
    //    抓得好好的頁面標成 blocked（2026-09-08 實測誤判 2 支：資料完整、
    //    25 張主圖、20 個 SKU，卻被判成擋）。誤判的代價是雙向的：好資料被丟掉，
    //    而且會去重抓 → 反而真的把驗證碼招來。
    //    真正的攔截頁 title 就是「验证码拦截」，且整頁沒有商品資料
    //    （Python 端另有 n_main == 0 這層把關，兩層都過才算真的被擋）。
    _blocked: /验证码|拦截|滑块验证|安全验证/i.test(document.title || ""),
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


# （#S134 階段4：1688 登入碼已收進 cookie-hub 警衛室；本檔只保留「讀 cookie 抓取」，
#  登入改由 gui「🔑 登入 1688」subprocess 呼叫 cookie-hub refresh 1688_lady。）


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

    # ⚠️ 同一個 offer 只抓一次——名單常有「同編號多列共用一個 1688 網址」
    #    （HNV11 的吸塵器/二合一/濾網是同一頁的三個品項），照原樣排會變成
    #    「短時間連打同一頁三次」→ 直接換來 1688 的滑塊驗證碼，而且會連累
    #    後面幾支一起被擋（2026-09-08 實測：26 支裡 4 支 blocked，其中 3 支
    #    就是這個重複的 offer，第 4 支是它後面那一支）。
    #    下游是照 item_id 讀 output/{item_id}.json，抓一次就夠所有列用。
    seen: set[str] = set()
    uniq_ids = [x for x in (str(r).strip() for r in item_ids)
                if x and not (x in seen or seen.add(x))]
    if len(uniq_ids) != len(item_ids):
        emit(f"去重：{len(item_ids)} 筆 → {len(uniq_ids)} 個不重複 offer"
             f"（同一頁只抓一次，避免觸發驗證碼）")
    item_ids = uniq_ids

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
