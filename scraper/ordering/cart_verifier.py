"""（vendored from ~/projects/1688-order/order/cart_verifier.py，僅改 OrderItem import 來源。
1688 改版時兩邊選擇器都要同步。）"""
"""1688 購物車二次核對模組 — 讀取購物車內容，與預期訂單比對。"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from loguru import logger
from playwright.async_api import BrowserContext, Page, async_playwright

from .models import OrderItem

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0.0.0 Safari/537.36"
)

ANTI_DETECT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
    window.chrome = { runtime: {} };
"""

CART_URL = "https://cart.1688.com/cart.htm"


@dataclass
class CartItem:
    """購物車中的一個規格行。"""

    spec_text: str
    quantity: int
    unit_price: str = ""


@dataclass
class CartProduct:
    """購物車中的一個商品（含多個規格行）。"""

    title: str
    product_url: str
    offer_id: str
    items: list[CartItem] = field(default_factory=list)


@dataclass
class VerifyResult:
    """單筆核對結果。"""

    row_index: int
    product_code: str
    sku_name: str
    spec1: str
    spec2: str
    expected_qty: int
    actual_qty: Optional[int]
    status: str


def extract_offer_id(url: str) -> str:
    """從 1688 商品 URL 提取 offer ID。

    URL 格式範例：
    - https://detail.1688.com/offer/123456789.html
    - https://m.1688.com/offer/123456789.html
    """
    if not url:
        return ""
    match = re.search(r"offer/(\d+)\.html", url)
    return match.group(1) if match else ""


def spec_in_text(spec: str, text: str) -> bool:
    """規格字串比對：按 spec 首尾字元類型決定需要的邊界。

    觀察自 1688 實際購物車文字（logs/cart_dump.json）：
    - 規格名後面常直接接價格數字，例如 "L72.00" / "XL52.50"
      → 邊界不能包含數字，否則 "L" 無法匹到 "L72.00"
    - 但規格字母間會誤配："L" 會被 "XL"、"XXL" 左邊包住
      → 字母規格要避免兩側出現字母
    - 中文也會誤配："小熊" 是 "花和小熊" 的子串
      → CJK 規格要避免兩側出現 CJK 字
    - 規格與價格 / 分隔符（¥、;、【、空格）相鄰是 OK 的

    規則：按首尾字元的類型要求對應邊界
    - 英文字母：左側不能是字母或數字（避免 XL 誤中 2XL、3XL 這種數字前綴複合尺碼）
               右側只擋字母（因為 1688 cart 格式是 `XL52.50` 規格後直接接價格數字）
    - 數字：兩側不能是數字
    - CJK：兩側不能是 CJK
    - 其他符號：不加限制
    """
    if not spec:
        return True

    def is_cjk(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff"

    def left_class(ch: str) -> str:
        if ch.isascii() and ch.isalpha():
            # 擋字母 + 數字：避免 "XL" 誤中 "2XL" / "3XL"
            return r"(?:^|[^A-Za-z0-9])"
        if ch.isascii() and ch.isdigit():
            return r"(?:^|[^0-9])"
        if is_cjk(ch):
            return r"(?:^|[^\u4e00-\u9fff])"
        return ""

    def right_class(ch: str) -> str:
        if ch.isascii() and ch.isalpha():
            # 只擋字母，不擋數字：允許 "XL52.50" 這種規格後接價格的格式
            return r"(?:[^A-Za-z]|$)"
        if ch.isascii() and ch.isdigit():
            return r"(?:[^0-9]|$)"
        if is_cjk(ch):
            return r"(?:[^\u4e00-\u9fff]|$)"
        return ""

    left = left_class(spec[0])
    right = right_class(spec[-1])
    if not left and not right:
        return spec in text
    pattern = left + re.escape(spec) + right
    return bool(re.search(pattern, text))


def matched_extended_token(spec: str, text: str) -> Optional[str]:
    """嚴格匹配 spec 後，回傳實際抓到的「規格 + 右側延伸字元」token。

    用於分辨「精確匹配」vs「子串延伸匹配」（解決 spec1 子串包含問題）：
    - spec='经典自然肤', text='经典自然肤; 均码...' → '经典自然肤'（exact）
    - spec='经典自然肤', text='经典自然肤/15D; 均码...' → '经典自然肤/15D'（延伸）

    延伸字元：A-Z, a-z, 0-9, `/` `-` `.` `_` `%`（涵蓋型號變體常見字元）
    遇到 CJK 字、空白、分號、`【`、`(` 等分隔符即停止。

    若嚴格匹配失敗回 None。
    """
    if not spec or not spec_in_text(spec, text):
        return None

    def is_cjk(ch: str) -> bool:
        return "\u4e00" <= ch <= "\u9fff"

    def left_class(ch: str) -> str:
        if ch.isascii() and ch.isalpha():
            return r"(?:^|[^A-Za-z0-9])"
        if ch.isascii() and ch.isdigit():
            return r"(?:^|[^0-9])"
        if is_cjk(ch):
            return r"(?:^|[^\u4e00-\u9fff])"
        return ""

    left = left_class(spec[0])
    ext = r"[A-Za-z0-9/\-\._%]*"
    pattern = left + re.escape(spec) + ext
    m = re.search(pattern, text)
    if not m:
        return None
    matched = m.group()
    idx = matched.find(spec)
    return matched[idx:] if idx >= 0 else None


class CartVerifier:
    """讀取 1688 購物車，與 Sheet 預期訂單比對。"""

    def __init__(
        self,
        cookie_path: str,
        headless: bool = False,
        callback: Optional[Callable[[str], None]] = None,
    ):
        self.cookie_path = Path(cookie_path)
        self.headless = headless
        self.callback = callback
        self._pw = None
        self._browser = None
        self._context: Optional[BrowserContext] = None

    def _notify(self, msg: str) -> None:
        """透過 callback 即時回饋給 GUI（若有）。"""
        logger.info(msg)
        if self.callback:
            try:
                self.callback(msg)
            except Exception as e:
                logger.debug(f"callback 執行失敗：{e}")

    async def _check_captcha(self, page: Page) -> bool:
        """偵測是否出現驗證碼（與 CartAdder 相同邏輯）。"""
        for selector in [
            "#nc_1_wrapper",
            ".nc-container",
            "#nocaptcha",
            'iframe[src*="captcha"]',
            ".baxia-dialog",
        ]:
            try:
                if await page.locator(selector).is_visible(timeout=1000):
                    return True
            except Exception:
                continue
        return False

    async def _wait_captcha_pass(self, page: Page, timeout: int = 180) -> bool:
        """輪詢等待驗證碼消失（使用者手動解題）。"""
        deadline = asyncio.get_event_loop().time() + timeout
        clear_count = 0
        elapsed = 0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2)
            elapsed += 2
            if not await self._check_captcha(page):
                clear_count += 1
                if clear_count >= 2:
                    return True
            else:
                clear_count = 0
                if elapsed % 30 == 0:
                    remaining = int(deadline - asyncio.get_event_loop().time())
                    self._notify(f"⏳ 仍在等待驗證碼通過（剩 {remaining} 秒）")
        return False

    async def start(self) -> None:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        await self._context.add_init_script(ANTI_DETECT_SCRIPT)
        await self._load_cookies()

    async def _load_cookies(self) -> None:
        if not self.cookie_path.exists():
            raise FileNotFoundError(f"Cookie 檔案不存在：{self.cookie_path}")
        cookies = json.loads(self.cookie_path.read_text(encoding="utf-8"))
        if not cookies:
            raise ValueError("Cookie 檔案是空的，請重新匯出")
        await self._context.add_cookies(cookies)
        logger.info(f"載入 {len(cookies)} 個 cookies")

    async def read_cart_products(self) -> list[CartProduct]:
        """開啟購物車頁面，邊滾邊解析（避免虛擬滾動遺漏）。"""
        page = await self._context.new_page()
        try:
            await page.goto(CART_URL, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(3)

            # 偵測驗證碼 → 輪詢等待使用者手動解題
            if await self._check_captcha(page):
                self._notify("⚠️ 偵測到驗證碼！請在瀏覽器中手動解題（最多 180 秒）")
                if not await self._wait_captcha_pass(page, timeout=180):
                    raise RuntimeError("CAPTCHA timeout")
                self._notify("✅ 驗證碼已通過，繼續讀取購物車")
                await asyncio.sleep(2)

            # 檢查 cookie 是否失效
            if "login.1688.com" in page.url:
                raise RuntimeError("Cookie expired")

            # 邊滾邊收集（處理虛擬滾動）
            products = await self._incremental_scroll_collect(page)

            # Debug dump
            await self._debug_dump(page)
            self._dump_products(products)

            logger.info(
                f"購物車共 {len(products)} 個商品，合計 {sum(len(p.items) for p in products)} 個規格行"
            )
            return products
        finally:
            await page.close()

    async def _find_scroll_container(self, page: Page) -> str:
        """尋找頁面中實際的滾動容器（可能不是 window）。"""
        info = await page.evaluate(r"""() => {
            const candidates = [];
            // window 本身
            candidates.push({
                selector: 'window',
                scrollHeight: document.documentElement.scrollHeight,
                clientHeight: window.innerHeight,
                scrollable: document.documentElement.scrollHeight > window.innerHeight,
            });
            // 找所有有 overflow:auto/scroll 且內容超出的容器
            const all = document.querySelectorAll('*');
            let idx = 0;
            for (const el of all) {
                if (idx++ > 5000) break;
                const cs = getComputedStyle(el);
                const oy = cs.overflowY;
                if (oy !== 'auto' && oy !== 'scroll') continue;
                if (el.scrollHeight <= el.clientHeight + 10) continue;
                // 粗略識別
                candidates.push({
                    selector: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className ? '.' + String(el.className).split(' ').slice(0, 2).join('.') : ''),
                    scrollHeight: el.scrollHeight,
                    clientHeight: el.clientHeight,
                });
                if (candidates.length > 10) break;
            }
            return candidates;
        }""")
        logger.info(f"[DEBUG] 滾動容器候選：{info}")
        return "window"

    async def _incremental_scroll_collect(self, page: Page) -> list[CartProduct]:
        """邊滾邊收集商品資料，合併去重。

        1688 購物車可能使用虛擬滾動，滾下去時上面的 DOM 元素會被移除，
        所以必須每滾一段就收集一次，用 offer_id 去重合併。
        """
        # 尋找實際的滾動容器
        await self._find_scroll_container(page)

        accumulated: dict[str, CartProduct] = {}
        seen_specs: dict[str, set] = {}

        no_progress_count = 0

        for step in range(120):
            # 解析目前可見商品
            batch = await self._parse_cart(page)
            for p in batch:
                if p.offer_id not in accumulated:
                    accumulated[p.offer_id] = CartProduct(
                        title=p.title,
                        product_url=p.product_url,
                        offer_id=p.offer_id,
                        items=[],
                    )
                    seen_specs[p.offer_id] = set()

                for ci in p.items:
                    key = (ci.spec_text, ci.quantity)
                    if key in seen_specs[p.offer_id]:
                        continue
                    seen_specs[p.offer_id].add(key)
                    accumulated[p.offer_id].items.append(ci)

            # 記錄滾動狀態
            scroll_info = await page.evaluate(r"""() => {
                // 嘗試多個滾動來源
                return {
                    windowScrollY: window.scrollY,
                    windowInnerHeight: window.innerHeight,
                    documentScrollHeight: document.documentElement.scrollHeight,
                    bodyScrollHeight: document.body.scrollHeight,
                };
            }""")

            logger.info(
                f"  滾動 {step}: 累積 {len(accumulated)} 商品 / "
                f"{sum(len(p.items) for p in accumulated.values())} 規格 | "
                f"scrollY={scroll_info['windowScrollY']} "
                f"viewHeight={scroll_info['windowInnerHeight']} "
                f"docHeight={scroll_info['documentScrollHeight']}"
            )

            # 嘗試多種滾動方式
            curr_scroll = scroll_info['windowScrollY']
            await page.evaluate(r"""() => {
                // 方式 1：window scroll
                window.scrollBy(0, 600);
                // 方式 2：document element
                if (document.documentElement) document.documentElement.scrollTop += 600;
                // 方式 3：所有可能的捲動容器
                const scrollables = document.querySelectorAll('*');
                let count = 0;
                for (const el of scrollables) {
                    if (count++ > 2000) break;
                    if (el.scrollHeight > el.clientHeight + 10) {
                        const cs = getComputedStyle(el);
                        if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') {
                            el.scrollTop += 600;
                        }
                    }
                }
            }""")
            # 鍵盤 End 鍵也觸發一下
            try:
                await page.keyboard.press("PageDown")
            except Exception:
                pass
            await asyncio.sleep(1.5)

            new_scroll = await page.evaluate("window.scrollY")
            if new_scroll == curr_scroll:
                no_progress_count += 1
                if no_progress_count >= 5:
                    logger.info(f"滾動停止於第 {step} 步（scrollY 無變化）")
                    break
            else:
                no_progress_count = 0

        # 最後滾回頂部
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

        return list(accumulated.values())

    async def _debug_dump(self, page: Page) -> None:
        """Dump 頁面上所有可能的商品連結與購物車容器資訊到 log。"""
        debug_info = await page.evaluate(r"""() => {
            const info = {
                url: window.location.href,
                title: document.title,
                bodyTextPreview: (document.body.textContent || '').substring(0, 500),
                allLinks: [],
                iframes: [],
            };
            // 所有可能的商品連結（不限定格式）
            const allA = document.querySelectorAll('a');
            const hrefs = new Set();
            for (const a of allA) {
                const href = a.href || '';
                if (href.includes('1688.com') && href.includes('offer')) {
                    hrefs.add(href);
                }
            }
            info.allLinks = Array.from(hrefs).slice(0, 30);

            // iframe 檢查（購物車可能在 iframe 內）
            const iframes = document.querySelectorAll('iframe');
            for (const f of iframes) {
                info.iframes.push({
                    src: f.src || '',
                    id: f.id || '',
                    className: f.className || '',
                });
            }

            // 所有 input 數量
            info.totalInputs = document.querySelectorAll('input').length;
            info.visibleInputs = Array.from(document.querySelectorAll('input')).filter(i => i.offsetParent).length;

            return info;
        }""")

        logger.info(f"[DEBUG] 頁面 URL：{debug_info.get('url')}")
        logger.info(f"[DEBUG] 頁面標題：{debug_info.get('title')}")
        logger.info(f"[DEBUG] 含 offer 的連結數：{len(debug_info.get('allLinks', []))}")
        for link in debug_info.get('allLinks', [])[:10]:
            logger.info(f"[DEBUG]   連結：{link}")
        logger.info(f"[DEBUG] iframe 數：{len(debug_info.get('iframes', []))}")
        for f in debug_info.get('iframes', []):
            logger.info(f"[DEBUG]   iframe src={f.get('src')} id={f.get('id')} class={f.get('className')[:50]}")
        logger.info(f"[DEBUG] input 總數：{debug_info.get('totalInputs')}，可見：{debug_info.get('visibleInputs')}")

        # 寫入檔案供詳細檢查
        dump_path = Path(__file__).parent.parent / "logs" / "cart_debug.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(
            json.dumps(debug_info, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[DEBUG] 診斷資訊已寫入：{dump_path}")

    def _dump_products(self, products: list[CartProduct]) -> None:
        """把解析結果寫到 logs/cart_dump.json 供檢查。"""
        dump = []
        for p in products:
            dump.append({
                "title": p.title,
                "offer_id": p.offer_id,
                "product_url": p.product_url,
                "items": [{"spec_text": ci.spec_text, "quantity": ci.quantity} for ci in p.items],
            })
        dump_path = Path(__file__).parent.parent / "logs" / "cart_dump.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(
            json.dumps(dump, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[DEBUG] 解析結果已寫入：{dump_path}")

    async def _scroll_to_bottom(self, page: Page) -> None:
        """滾動到底部觸發懶加載。"""
        prev_height = 0
        for _ in range(20):
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            prev_height = curr_height
        # 滾回頂部
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)

    async def _parse_cart(self, page: Page) -> list[CartProduct]:
        """用 JS 解析目前可見範圍內的購物車商品。

        策略：從每個數量 input 往上找最近的 offer 連結 → 這個 input 屬於該商品。
        這樣避免把整個 cart 容器誤當成單一商品容器。
        """
        raw = await page.evaluate(r"""() => {
            // 收集所有可見的數量 input
            const qtyInputs = Array.from(document.querySelectorAll('input')).filter(inp => {
                if (!inp.offsetParent) return false;
                const t = (inp.type || '').toLowerCase();
                if (!(t === '' || t === 'text' || t === 'number' || t === 'tel')) return false;
                const v = inp.value || '';
                // 必須是數字值
                return /^\d+$/.test(v);
            });

            // 以 offer_id 為 key
            const productMap = {};

            for (const qtyInput of qtyInputs) {
                const qty = parseInt(qtyInput.value || '0', 10);
                if (isNaN(qty) || qty < 1) continue;

                // 從 input 往上找到最近的一個 offer 連結（代表這個 input 屬於該商品）
                let el = qtyInput.parentElement;
                let offerId = null;
                let offerTitle = '';
                let offerUrl = '';
                let depth = 0;
                while (el && depth < 20) {
                    const link = el.querySelector('a[href*="/offer/"]');
                    if (link) {
                        const m = (link.href || '').match(/offer\/(\d+)\.html/);
                        if (m) {
                            offerId = m[1];
                            offerTitle = (link.textContent || '').trim();
                            offerUrl = link.href;
                            break;
                        }
                    }
                    el = el.parentElement;
                    depth++;
                }

                if (!offerId) continue;

                // 往上找規格文字 — 關鍵：只在「只包含當前這一個 qty input」
                // 的容器中取文字，避免跨越多個 row 的父容器造成
                // 不同 row 共享同一段文字（會導致 L/XL/XXL 互相誤配）。
                // 策略：從 input 的 parent 往上爬，只要容器仍是「單 row」
                // 就持續更新 bestText（取到最大的單 row 容器），一旦遇到
                // 含 2+ 個 qty input 的容器就停止。
                let specEl = qtyInput.parentElement;
                let bestText = '';
                let specDepth = 0;
                while (specEl && specDepth < 8) {
                    let containedQty = 0;
                    for (const inp of qtyInputs) {
                        if (specEl.contains(inp)) {
                            containedQty++;
                            if (containedQty > 1) break;
                        }
                    }
                    if (containedQty > 1) break;  // 已橫跨多個 row，停止往上

                    const text = (specEl.textContent || '').replace(/\s+/g, ' ').trim();
                    const titleKey = offerTitle ? offerTitle.substring(0, 8) : '';
                    if (text.length > 3 && text.length < 150) {
                        if (!titleKey || !text.includes(titleKey)) {
                            bestText = text;  // 更新為目前最完整的單 row 文字
                        }
                    }
                    specEl = specEl.parentElement;
                    specDepth++;
                }
                const specText = bestText;

                if (!productMap[offerId]) {
                    productMap[offerId] = {
                        title: offerTitle,
                        product_url: offerUrl,
                        offer_id: offerId,
                        items: [],
                    };
                }

                productMap[offerId].items.push({
                    spec_text: specText,
                    quantity: qty,
                });
            }

            return Object.values(productMap);
        }""")

        products: list[CartProduct] = []
        for p in raw:
            items = [
                CartItem(spec_text=it["spec_text"], quantity=it["quantity"])
                for it in p["items"]
            ]
            products.append(
                CartProduct(
                    title=p["title"],
                    product_url=p["product_url"],
                    offer_id=p["offer_id"],
                    items=items,
                )
            )
        return products

    def verify(
        self, expected: list[OrderItem], cart: list[CartProduct]
    ) -> list[VerifyResult]:
        """兩層比對：商品 offer ID → 規格文字 + 數量。"""
        # 以 offer_id 建立索引
        cart_map: dict[str, CartProduct] = {p.offer_id: p for p in cart}

        # Debug：dump 雙邊 offer_id 與 URL 比對
        debug = {
            "cart_offer_ids": sorted(cart_map.keys()),
            "expected_sample": [
                {
                    "product_code": e.product_code,
                    "url_1688": e.url_1688,
                    "offer_id": extract_offer_id(e.url_1688),
                }
                for e in expected[:15]
            ],
        }
        dump_path = Path(__file__).parent.parent / "logs" / "verify_match.json"
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(
            json.dumps(debug, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"[DEBUG] 比對資訊已寫入：{dump_path}")
        logger.info(f"[DEBUG] 購物車 offer_ids：{list(cart_map.keys())[:5]}...")
        for e in expected[:3]:
            logger.info(
                f"[DEBUG] Sheet {e.product_code}: url={e.url_1688} offer_id={extract_offer_id(e.url_1688)}"
            )

        results: list[VerifyResult] = []
        for item in expected:
            offer_id = extract_offer_id(item.url_1688)
            result = VerifyResult(
                row_index=item.row_index,
                product_code=item.product_code,
                sku_name=item.sku_name,
                spec1=item.spec1,
                spec2=item.spec2,
                expected_qty=item.quantity,
                actual_qty=None,
                status="",
            )

            # 第一層：商品匹配
            product = cart_map.get(offer_id)
            if not product:
                result.status = "❌ 商品未找到"
                results.append(result)
                continue

            # 第二層：規格匹配 — per-row 綜合評分
            #
            # 為何改用 per-row score：
            #   舊版 per-spec fallback（spec1/spec2 各自獨立選 exact/strict/loose）
            #   會出現「兩個 spec 都找到 strict 命中，但命中的 row 不是同一筆」導致
            #   交集為空，判為「規格未找到」。例如：
            #     spec1="黑色【单件】" strict 命中 row[2,5,8]
            #     spec2="36/80"       strict 命中 row[0]（因為 row[0] 的 36/80 右邊接 ≥）
            #     其他 row 的 36/80 右邊接數字 9 → strict 失敗 → 但 spec1 有 strict 就強制用 strict
            #     → 交集空 → ❌ 規格未找到
            #
            # 改法：每個 row 計算 score = spec1_level + spec2_level（exact=3/strict=2/loose=1/miss=0）
            #       選最高分且 > 0 的 row；多個最高分視為重複項目。
            #       這樣 row[8]（spec1=exact=3 + spec2=loose=1 = 4）會正確被選中。
            def _level_score(spec: str, text: str) -> int:
                if not spec:
                    return 3  # 空 spec 視為 exact 命中
                if spec_in_text(spec, text):
                    if matched_extended_token(spec, text) == spec:
                        return 3  # exact
                    return 2  # strict
                if spec in text:
                    return 1  # loose
                return 0  # miss

            scores = []
            for ci in product.items:
                s1_s = _level_score(item.spec1, ci.spec_text)
                s2_s = _level_score(item.spec2, ci.spec_text)
                # 兩個 spec 都要至少 loose 命中，否則整 row 0 分
                scores.append(s1_s + s2_s if s1_s > 0 and s2_s > 0 else 0)

            max_score = max(scores) if scores else 0
            if max_score == 0:
                matches = []
            else:
                matches = [ci for ci, sc in zip(product.items, scores) if sc == max_score]

            if not matches:
                result.status = "❌ 規格未找到"
            elif len(matches) > 1:
                total = sum(m.quantity for m in matches)
                result.actual_qty = total
                result.status = f"⚠️ 重複項目(共{len(matches)}行/{total}件)"
            else:
                actual_qty = matches[0].quantity
                result.actual_qty = actual_qty
                if actual_qty == item.quantity:
                    result.status = "✅ 核對正確"
                else:
                    result.status = f"⚠️ 數量不符(預期{item.quantity}/實際{actual_qty})"

            results.append(result)

        return results

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
