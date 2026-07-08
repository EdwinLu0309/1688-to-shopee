"""（vendored from ~/projects/1688-order/order/cart_adder.py，僅改 OrderItem import 來源。
1688 改版時兩邊選擇器都要同步。）"""
"""Playwright 自動加入 1688 購物車模組。"""

import asyncio
import json
import random
from pathlib import Path

from loguru import logger
from typing import Callable, Optional

from playwright.async_api import BrowserContext, Locator, Page, async_playwright

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
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) =>
        parameters.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(parameters);
"""

# 狀態常數（同步寫回 Sheet R 欄）
STATUS_ADDED = "✅ 已加入"
STATUS_SPEC_MISMATCH = "❌ 規格不符"
STATUS_PAGE_ERROR = "❌ 頁面錯誤"
STATUS_SOLD_OUT = "🚫 已售完"
STATUS_INQUIRY_ONLY = "📞 廠商詢單"


class CartAdder:
    """透過 Playwright 將商品加入 1688 購物車。"""

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

    async def add_to_cart(self, item: OrderItem) -> str:
        """薄 wrapper：單筆呼叫走 add_multi_to_cart 保持介面一致。"""
        results = await self.add_multi_to_cart([item])
        return results.get(item.row_index, STATUS_PAGE_ERROR)

    async def add_multi_to_cart(self, items: list[OrderItem]) -> dict[int, str]:
        """同商品多規格一次處理：一個頁面填完所有數量 → 一次加采购车。

        items 必須共用同一個 url_1688（呼叫端負責 groupby）。
        回傳 {row_index: status}。
        """
        if not items:
            return {}

        url = items[0].url_1688
        statuses: dict[int, str] = {}
        page = await self._context.new_page()
        try:
            # ── 1. 導航 + 頁面層檢查 ──
            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(random.uniform(2, 4))
            except Exception as e:
                logger.error(f"商品頁載入失敗（{items[0].product_code}）：{e}")
                return {it.row_index: STATUS_PAGE_ERROR for it in items}

            # 驗證碼 → 輪詢等待（超時會 raise，整組中止）
            if await self._check_captcha(page):
                self._notify("⚠️ 偵測到驗證碼！請在瀏覽器中手動解題（最多 180 秒）")
                if not await self._wait_captcha_pass(page, timeout=180):
                    raise RuntimeError("CAPTCHA timeout")
                self._notify("✅ 驗證碼已通過，繼續處理")
                await asyncio.sleep(1.5)

            # Cookie 失效 → raise 整組中止
            if "login.1688.com" in page.url:
                raise RuntimeError("Cookie expired")

            # 詢單頁 → 整組標 INQUIRY_ONLY
            if await self._check_inquiry_only(page):
                logger.warning(f"品號 {items[0].product_code}：僅供詢單，整組標記")
                return {it.row_index: STATUS_INQUIRY_ONLY for it in items}

            # 展開售罄區塊讓售完規格進入 DOM
            await self._expand_sold_out_section(page)

            # ── 2. 填規格數量 ──
            has_spec2 = any(it.spec2 for it in items)
            pending_added: list[int] = []  # 成功填完數量、等加購按鈕一起生效

            if not has_spec2:
                # 單規格：每個 item 對 spec1 找列填數量
                for it in items:
                    await self._fill_one_item_quantity(
                        page, it, spec_text=it.spec1, statuses=statuses,
                        pending_added=pending_added, is_spec2=False,
                    )
            else:
                # 雙規格：按 spec1 分組，切換顏色後逐 spec2 填
                from collections import OrderedDict
                by_spec1: OrderedDict[str, list[OrderItem]] = OrderedDict()
                for it in items:
                    by_spec1.setdefault(it.spec1, []).append(it)

                for spec1, sub_items in by_spec1.items():
                    if not await self._click_spec_tag(page, spec1):
                        if await self._is_spec_sold_out(page, spec1):
                            logger.warning(f"規格1「{spec1}」已售完，該組 {len(sub_items)} 筆標 SOLD_OUT")
                            for sub in sub_items:
                                statuses[sub.row_index] = STATUS_SOLD_OUT
                        else:
                            logger.warning(f"規格1「{spec1}」標籤找不到，該組 {len(sub_items)} 筆標 SPEC_MISMATCH")
                            for sub in sub_items:
                                statuses[sub.row_index] = STATUS_SPEC_MISMATCH
                        continue
                    await asyncio.sleep(random.uniform(0.5, 1.5))

                    for sub in sub_items:
                        await self._fill_one_item_quantity(
                            page, sub, spec_text=sub.spec2, statuses=statuses,
                            pending_added=pending_added, is_spec2=True,
                        )

            # ── 3. 全部填完 → 點一次加采购车 ──
            if not pending_added:
                logger.warning(f"品號 {items[0].product_code}：沒有成功填入任何數量，跳過加購")
                return statuses

            await asyncio.sleep(random.uniform(0.5, 1.0))
            if not await self._click_add_cart(page):
                logger.warning(f"品號 {items[0].product_code}：加购按鈕失敗，pending {len(pending_added)} 筆改 PAGE_ERROR")
                for rid in pending_added:
                    statuses[rid] = STATUS_PAGE_ERROR
                return statuses

            await asyncio.sleep(random.uniform(1, 2))
            for rid in pending_added:
                statuses[rid] = STATUS_ADDED
            logger.info(f"品號 {items[0].product_code}：已加入購物車（共 {len(pending_added)} 個規格）")
            return statuses

        except RuntimeError:
            # CAPTCHA timeout / Cookie expired → 往上丟給 run_project 處理
            raise
        except Exception as e:
            logger.error(f"品號 {items[0].product_code} 處理時發生未預期錯誤：{e}")
            for it in items:
                statuses.setdefault(it.row_index, STATUS_PAGE_ERROR)
            return statuses
        finally:
            await page.close()

    async def _fill_one_item_quantity(
        self,
        page: Page,
        item: OrderItem,
        spec_text: str,
        statuses: dict[int, str],
        pending_added: list[int],
        is_spec2: bool,
    ) -> None:
        """找 spec_text 對應的規格列並填數量，結果寫進 statuses / pending_added。"""
        spec_label = f"規格{'2' if is_spec2 else ''}"
        spec_row = await self._find_spec_row(page, spec_text)
        if not spec_row:
            if await self._is_spec_sold_out(page, spec_text):
                logger.warning(f"品號 {item.product_code}：{spec_label}「{spec_text}」已售完")
                statuses[item.row_index] = STATUS_SOLD_OUT
            else:
                logger.warning(f"品號 {item.product_code}：{spec_label}「{spec_text}」列找不到")
                statuses[item.row_index] = STATUS_SPEC_MISMATCH
            return

        await asyncio.sleep(random.uniform(0.3, 0.8))
        if not await self._set_quantity_in_row(spec_row, item.quantity):
            logger.warning(f"品號 {item.product_code}：數量填寫失敗（{spec_text}）")
            statuses[item.row_index] = STATUS_PAGE_ERROR
            return

        pending_added.append(item.row_index)
        logger.debug(f"品號 {item.product_code}：{spec_label}「{spec_text}」填入 {item.quantity}")

    async def _click_spec_tag(self, page: Page, spec_text: str) -> bool:
        """點擊規格標籤按鈕（用於雙規格商品的第一維度，如顏色）。

        策略 1（優先）：用 1688 標準 SKU 結構 selector + Playwright wait_for，
        解決 React/Vue 漸進渲染的時序問題；用 text-is 精確匹配，避免
        「肉色」誤中「肉色【套装】」。
        策略 2（fallback）：1688 改版時退回原本的 JS 廣搜邏輯。
        """
        # ── 策略 1：1688 標準 SKU 結構 ──
        # <button class="sku-filter-button"><span class="label-name">肉色</span></button>
        try:
            sel = (
                f'button.sku-filter-button:has(span.label-name:text-is("{spec_text}"))'
            )
            locator = page.locator(sel).first
            await locator.wait_for(state="visible", timeout=8000)
            await locator.click()
            logger.debug(f"已點擊規格標籤（locator）：{spec_text}")
            return True
        except Exception as e:
            logger.debug(f"locator 找不到 sku-filter-button「{spec_text}」: {e}")

        # ── 策略 2：fallback 到 JS 廣搜（保留給結構不同的商品頁）──
        try:
            # 用 JS 找到正確的標籤元素並點擊
            clicked = await page.evaluate("""(specText) => {
                // 策略：找到所有包含目標文字的元素，
                // 篩選出尺寸小（像標籤按鈕）且可見的那一個
                const allElements = document.querySelectorAll('span, div, a, li, button, label');
                let bestMatch = null;
                let bestArea = Infinity;

                for (const el of allElements) {
                    // 只匹配直接文字內容（不含子元素文字），避免匹配到大容器
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');

                    // 也檢查整體 textContent（但要求元素夠小）
                    const fullText = (el.textContent || '').trim();

                    if (!directText.includes(specText) && !fullText.includes(specText)) {
                        continue;
                    }

                    // 必須可見
                    if (!el.offsetParent && el.style.display !== 'fixed') continue;
                    const rect = el.getBoundingClientRect();
                    if (rect.width === 0 || rect.height === 0) continue;

                    // 標籤按鈕通常較小（寬 < 200px, 高 < 80px）
                    const area = rect.width * rect.height;
                    if (rect.width > 300 || rect.height > 100) continue;

                    // 優先選最小的匹配元素
                    if (area < bestArea) {
                        bestArea = area;
                        bestMatch = el;
                    }
                }

                if (bestMatch) {
                    bestMatch.click();
                    return bestMatch.textContent.trim().substring(0, 30);
                }
                return null;
            }""", spec_text)

            if clicked:
                logger.debug(f"已點擊規格標籤：{spec_text}（元素文字：{clicked}）")
                return True

            logger.debug(f"JS 找不到規格標籤：{spec_text}")
        except Exception as e:
            logger.debug(f"點擊規格標籤時發生錯誤：{e}")

        return False

    async def _find_spec_row(self, page: Page, spec_text: str) -> Optional[Locator]:
        """找到包含規格文字的那一整列，回傳該列的 input locator。

        用 JS 精準定位：找到所有可見 input，逐一往上檢查最近的兄弟/父層
        是否包含目標規格文字，避免容器太大的問題。
        """
        try:
            # 用 JS 找到正確的 input 索引
            # normalize 空白：把 SKU_DB 與頁面兩邊的多個連續空白都壓成單空格再比對，
            # 避開 1688 頁面渲染成多空格（例：「权杖瓶   镭射碎钻猫眼-01」 vs SKU_DB 的單空格版）造成誤判
            input_index = await page.evaluate("""(specText) => {
                const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
                const target = norm(specText);
                const inputs = document.querySelectorAll('input');
                for (let i = 0; i < inputs.length; i++) {
                    const input = inputs[i];
                    if (!input.offsetParent) continue;  // 跳過不可見的

                    // 從 input 往上找，檢查每一層父元素
                    let el = input.parentElement;
                    let depth = 0;
                    while (el && depth < 8) {
                        const text = norm(el.textContent);
                        // 找到包含規格文字的層
                        if (text.includes(target)) {
                            // 確認這一層不會太大：只包含一個可見 input
                            const rowInputs = el.querySelectorAll('input');
                            const visibleInputs = Array.from(rowInputs).filter(
                                inp => inp.offsetParent !== null
                            );
                            if (visibleInputs.length === 1) {
                                return i;  // 回傳 input 在所有 input 中的索引
                            }
                        }
                        el = el.parentElement;
                        depth++;
                    }
                }
                return -1;
            }""", spec_text)

            if input_index >= 0:
                logger.debug(f"找到規格列 input index={input_index}：{spec_text}")
                return page.locator('input').nth(input_index)

            logger.debug(f"JS 找不到規格列：{spec_text}")
        except Exception as e:
            logger.debug(f"尋找規格列時發生錯誤：{e}")

        return None

    async def _set_quantity_in_row(self, qty_input: Locator, quantity: int) -> bool:
        """在數量輸入框填入數量。

        qty_input 是已定位到正確規格列的 input 元素。
        頁面上的數量控制是：「-」按鈕 + 數量輸入框(預設0) + 「+」按鈕
        """
        try:
            if not await qty_input.is_visible(timeout=2000):
                logger.warning("數量輸入框不可見")
                return False

            # 方法 1：點擊 → 全選 → 填入
            await qty_input.click()
            await asyncio.sleep(0.2)
            await qty_input.press("Control+a")
            await asyncio.sleep(0.1)
            await qty_input.type(str(quantity), delay=50)
            await asyncio.sleep(0.2)
            await qty_input.press("Tab")

            # 驗證
            await asyncio.sleep(0.3)
            value = await qty_input.input_value()
            if value == str(quantity):
                logger.debug(f"已填入數量：{quantity}")
                return True

            # 方法 2：用 fill()
            await qty_input.click()
            await asyncio.sleep(0.1)
            await qty_input.fill(str(quantity))
            await qty_input.press("Tab")

            await asyncio.sleep(0.3)
            value = await qty_input.input_value()
            if value == str(quantity):
                logger.debug(f"已填入數量（方法2）：{quantity}")
                return True

            # 方法 3：用 + 按鈕（小數量）
            if quantity <= 30:
                logger.debug(f"嘗試用 + 按鈕填入數量：{quantity}")
                # 找到 input 旁邊的 + 按鈕（通常是下一個兄弟元素）
                plus_btn = qty_input.locator('xpath=following-sibling::*[1]')
                if await plus_btn.is_visible(timeout=1000):
                    # 先歸零
                    await qty_input.fill("0")
                    await qty_input.press("Tab")
                    await asyncio.sleep(0.2)
                    for _ in range(quantity):
                        await plus_btn.click()
                        await asyncio.sleep(0.08)
                    logger.debug(f"已用 + 按鈕填入數量：{quantity}")
                    return True

            logger.warning(f"數量填入失敗，期望 {quantity}，實際 {value}")
            return False

        except Exception as e:
            logger.error(f"填入數量時發生錯誤：{e}")
            return False

    async def _click_add_cart(self, page: Page) -> bool:
        """點擊加入購物車按鈕。

        1688 新版頁面按鈕文字是「加采购车」。
        """
        cart_selectors = [
            '//button[contains(text(), "加采购车")]',
            '//a[contains(text(), "加采购车")]',
            '//div[contains(text(), "加采购车")]',
            '//span[contains(text(), "加采购车")]',
            '//button[contains(text(), "加入购物车")]',
            '//a[contains(text(), "加入购物车")]',
            '//div[contains(text(), "加入购物车")]',
            '//span[contains(text(), "加入购物车")]',
            '[class*="cart"] button',
            '[class*="addCart"]',
            '[data-spm*="cart"]',
        ]

        for selector in cart_selectors:
            try:
                el = page.locator(selector).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    logger.debug("已點擊加入購物車按鈕")
                    return True
            except Exception:
                continue

        return False

    async def _check_captcha(self, page: Page) -> bool:
        """偵測是否出現驗證碼。"""
        captcha_indicators = [
            "#nc_1_wrapper",
            ".nc-container",
            "#nocaptcha",
            'iframe[src*="captcha"]',
            ".baxia-dialog",
        ]
        for selector in captcha_indicators:
            try:
                if await page.locator(selector).is_visible(timeout=1000):
                    return True
            except Exception:
                continue
        return False

    async def _wait_captcha_pass(self, page: Page, timeout: int = 180) -> bool:
        """輪詢等待驗證碼消失（使用者手動解題）。

        每 2 秒檢查一次，連續 2 次偵測不到驗證碼才判定通過（避免 DOM 過渡狀態）。
        回傳 True 表示已通過、False 表示超時。
        """
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
                # 每 30 秒提醒一次剩餘時間
                if elapsed % 30 == 0:
                    remaining = int(deadline - asyncio.get_event_loop().time())
                    self._notify(f"⏳ 仍在等待驗證碼通過（剩 {remaining} 秒）")
        return False

    async def _check_inquiry_only(self, page: Page) -> bool:
        """偵測商品頁是否僅供詢單（整頁沒有加購按鈕，只有立即詢單）。

        判斷邏輯：頁面可見區域有「立即詢單/询盘/咨询」且沒有「加采购车/加入购物车」按鈕。
        """
        try:
            result = await page.evaluate(r"""() => {
                const cartKws = ['加采购车', '加入购物车', '加入購物車', '加入购物車'];
                const inquiryKws = ['立即询单', '立即詢單', '立即询盘', '立即詢盤',
                                    '立即咨询', '立即諮詢', '询盘下单', '询价下单', '去询盘'];

                function isVisible(el) {
                    if (!el.offsetParent) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }

                let hasCart = false;
                let hasInquiry = false;
                const all = document.querySelectorAll('button, a, span, div');
                let scanned = 0;
                for (const el of all) {
                    if (scanned++ > 8000) break;
                    if (!isVisible(el)) continue;
                    const text = (el.textContent || '').trim();
                    if (!text || text.length > 30) continue;
                    for (const kw of cartKws) {
                        if (text.includes(kw)) { hasCart = true; break; }
                    }
                    if (hasCart) break;  // 早退：有加購就代表可下單
                    for (const kw of inquiryKws) {
                        if (text.includes(kw)) { hasInquiry = true; break; }
                    }
                }
                return { hasCart, hasInquiry };
            }""")
            return bool(result.get("hasInquiry")) and not bool(result.get("hasCart"))
        except Exception as e:
            logger.debug(f"檢查詢單狀態時發生錯誤：{e}")
            return False

    async def _expand_sold_out_section(self, page: Page) -> bool:
        """點擊「展开已售罄商品」折疊按鈕，讓售完規格出現在 DOM 中。

        1688 預設會把售完規格折疊，要點一下 `∨` 箭頭才會顯示。
        若按鈕不存在（整頁都沒售完規格）直接略過。
        """
        try:
            clicked = await page.evaluate(r"""() => {
                const kws = ['展开已售罄', '展開已售罄', '展开已售完', '展開已售完',
                             '查看已售罄', '已售罄商品'];
                const all = document.querySelectorAll('*');
                let scanned = 0;
                for (const el of all) {
                    if (scanned++ > 8000) break;
                    // 用直接文字避免匹配到大容器
                    const directText = Array.from(el.childNodes)
                        .filter(n => n.nodeType === 3)
                        .map(n => n.textContent.trim())
                        .join('');
                    if (!directText) continue;
                    let matched = false;
                    for (const kw of kws) {
                        if (directText.includes(kw)) { matched = true; break; }
                    }
                    if (!matched) continue;
                    if (!el.offsetParent) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if (r.width > 400 || r.height > 80) continue;  // 排除大容器
                    el.click();
                    return directText.substring(0, 40);
                }
                return null;
            }""")
            if clicked:
                logger.debug(f"已展開售罄區塊：{clicked}")
                await asyncio.sleep(0.6)
                return True
        except Exception as e:
            logger.debug(f"展開售罄區塊時發生錯誤：{e}")
        return False

    async def _is_spec_sold_out(self, page: Page, spec_text: str) -> bool:
        """偵測指定規格是否已售完。

        判斷邏輯：
        1. 找所有直接含 spec_text 的小容器（< 80 字）
        2. 對每個候選往上最多 4 層，檢查是否含「售罄/已售完」等字樣
        3. 或該層帶 disabled/sold-out 樣式且透明度偏低
        """
        try:
            result = await page.evaluate(r"""(specText) => {
                const soldKws = ['售罄', '已售完', '售完', '无货', '缺货', '已下架',
                                 '暂无库存', '補貨中', '补货中', '無庫存', '无库存'];
                const all = document.querySelectorAll('*');
                const candidates = [];
                let scanned = 0;
                for (const el of all) {
                    if (scanned++ > 10000) break;
                    const t = (el.textContent || '').trim();
                    if (!t.includes(specText)) continue;
                    if (t.length > 80) continue;  // 只保留最靠近規格文字的小節點
                    candidates.push(el);
                }

                for (const c of candidates) {
                    let el = c;
                    for (let depth = 0; depth < 4 && el; depth++) {
                        const t = (el.textContent || '').trim();
                        if (t.length < 400) {  // 避免整頁 body 都掃進來
                            for (const kw of soldKws) {
                                if (t.includes(kw)) return true;
                            }
                        }
                        const cls = typeof el.className === 'string' ? el.className : '';
                        if (cls.match(/disabled|sold|unavailable/i)) {
                            const cs = getComputedStyle(el);
                            if (cs.opacity && parseFloat(cs.opacity) < 0.7) return true;
                            if (el.getAttribute('aria-disabled') === 'true') return true;
                        }
                        el = el.parentElement;
                    }
                }
                return false;
            }""", spec_text)
            return bool(result)
        except Exception as e:
            logger.debug(f"檢查售完狀態時發生錯誤：{e}")
            return False

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
