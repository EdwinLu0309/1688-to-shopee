"""抓 1688「待付款」訂單 → 結構化訂單列（給金流核對表 1688_DB 用）。

做法（#S072 去風險定案）：Playwright 帶登入 cookie 進「已买到的货品」訂單頁，
**在頁內用該站自己的 `lib.mtop` JS 呼叫訂單清單 API**（自動簽章、可翻頁），
完全不刮脆弱的 shadow DOM。API：
  mtop.1688.trading.dataline.service
  POST data={"serviceId":"OrderListDataLineService.buyerOrderList",
             "param":"{\\"tradeStatus\\":\\"waitbuyerpay\\",\\"page\\":1,\\"pageSize\\":100}"}
回傳 res.data.data.result（JSON 字串）→ {data:{data:[...訂單...], total, pages}}。

⚠️ 1688 金額單位是「分」→ ÷100 才是人民幣元。
⚠️ 清單 API 的收貨地址/電話被遮罩（核對用不到，留空）。
⚠️ 選擇器/API 若被 1688 改版：改本檔 CALL_JS 的 serviceId/param。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from loguru import logger
from playwright.async_api import async_playwright

# 進頁只為建立 mtop session（帶 token cookie），不靠頁面渲染
ORDER_PAGE_URL = (
    "https://air.1688.com/app/ctf-page/trade-order-list/"
    "buyer-order-list.html?tradeStatus=waitbuyerpay&pageSize=100"
)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ANTI_DETECT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
    window.chrome = { runtime: {} };
"""

# 頁內：用站方 lib.mtop 呼叫訂單清單（自動簽章）。回傳外層 res，Python 端再解 result 字串。
CALL_JS = r"""
async ({status, page, pageSize}) => {
  const mtop = (window.lib && window.lib.mtop) || window.mtop;
  if (!mtop) return {err: 'no mtop global'};
  const param = JSON.stringify({tradeStatus: status, page: page, pageSize: pageSize});
  try {
    const res = await mtop.request({
      api: 'mtop.1688.trading.dataline.service',
      v: '1.0',
      data: { serviceId: 'OrderListDataLineService.buyerOrderList', param: param },
      dataType: 'json',
      type: 'POST',
    });
    return {ok: true, res: res};
  } catch (e) { return {err: String(e)}; }
}
"""


@dataclass
class OrderEntry:
    """訂單裡的一個品項（對應 1688_DB 品項欄）。"""
    title: str = ""
    unit_price: float = 0.0   # 单价(元)
    qty: str = ""             # 数量
    unit: str = ""            # 单位
    product_number: str = ""  # 货号（賣家自訂）
    offer_id: str = ""        # Offer ID
    sku_id: str = ""          # SKU ID


@dataclass
class OrderRecord:
    """一張 1688 訂單（對應 1688_DB 訂單級欄位）。"""
    order_no: str = ""          # 订单编号（idStr）
    buyer_login: str = ""       # 买家会员名
    seller_company: str = ""    # 卖家公司名 ← 核對 key（廠商）
    seller_login: str = ""      # 卖家会员名
    goods_total: float = 0.0    # 货品总价(元)
    freight: float = 0.0        # 运费(元)
    discount: float = 0.0       # 涨价或折扣(元)
    actual_pay: float = 0.0     # 实付款(元)
    status_label: str = ""      # 订单状态（等待买家付款…）
    create_time: str = ""       # 订单创建时间（原始 'YYYY-MM-DD HH:MM:SS'）
    pay_time: str = ""          # 订单付款时间
    entries: list[OrderEntry] = field(default_factory=list)

    @property
    def create_date(self) -> str:
        """'YYYY-MM-DD'（給日期篩選比較）。"""
        return (self.create_time or "")[:10].replace("/", "-")


def _yuan(cents) -> float:
    """1688 金額（分）→ 元。容錯 None/字串。"""
    try:
        return round(float(cents) / 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


def _fmt_date_slash(raw: str) -> str:
    """'2026-07-05 07:14:47' → '2026/7/5'（比照 1688_DB 既有格式）。"""
    d = (raw or "")[:10].replace("-", "/")
    parts = d.split("/")
    if len(parts) == 3:
        try:
            return f"{int(parts[0])}/{int(parts[1])}/{int(parts[2])}"
        except ValueError:
            pass
    return d


def _fmt_ms(ms) -> str:
    """付款時間毫秒 → 'YYYY/M/D'（無則空）。純字串化不引入 tz 麻煩。"""
    if not ms:
        return ""
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y/%-m/%-d")
    except Exception:
        return ""


def _parse_order(o: dict) -> OrderRecord:
    seller = o.get("sellerInfo") or {}
    buyer = o.get("buyerInfo") or {}
    promo = o.get("promotionFeeMap") or {}
    rec = OrderRecord(
        order_no=str(o.get("idStr") or o.get("id") or ""),
        buyer_login=str(buyer.get("loginId") or ""),
        seller_company=str(seller.get("companyName") or ""),
        seller_login=str(seller.get("loginId") or ""),
        goods_total=_yuan(o.get("sumProductPayment")),
        freight=_yuan(o.get("carriage")),
        discount=_yuan(o.get("allPromotionFee") or promo.get("allPromotion")),
        actual_pay=_yuan(o.get("sumPayment")),
        status_label=str(o.get("statusLabel") or ""),
        create_time=str(o.get("gmtCreate") or ""),
        pay_time=_fmt_ms(o.get("gmtPayment")),
    )
    for e in (o.get("orderEntries") or []):
        qty = e.get("quantity") or {}
        rec.entries.append(OrderEntry(
            title=str(e.get("productName") or ""),
            unit_price=_yuan(e.get("price")),
            qty=str(qty.get("realAmountStr") or qty.get("calAmount") or ""),
            unit=str(e.get("unit") or ""),
            product_number=str(e.get("productNumber") or ""),
            offer_id=str(e.get("sourceId") or ""),
            sku_id=str(e.get("skuId") or ""),
        ))
    return rec


async def _evaluate_retry(page, js, arg, tries: int = 3):
    """頁內 evaluate；遇 SPA 自我導航把執行環境打掉時，settle 後重試。"""
    last = None
    for _ in range(tries):
        try:
            return await page.evaluate(js, arg)
        except Exception as e:
            last = e
            if "context was destroyed" in str(e) or "navigation" in str(e).lower():
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(1.5)
                continue
            raise
    raise last


def _unwrap(res: dict) -> tuple[list[dict], int]:
    """res.data.data.result（JSON 字串）→ (訂單 list, total)。"""
    try:
        result = res["data"]["data"]["result"]
        parsed = json.loads(result) if isinstance(result, str) else result
        d = parsed.get("data", {})
        return d.get("data", []) or [], int(d.get("total", 0) or 0)
    except (KeyError, TypeError, ValueError) as e:
        logger.warning(f"訂單清單回傳解不開：{e}")
        return [], 0


async def scrape_pending_orders(
    cookie_path: str,
    status: str = "waitbuyerpay",
    since_date: Optional[str] = None,
    headless: bool = False,
    page_size: int = 100,
    max_pages: int = 30,
    callback: Optional[Callable[[str], None]] = None,
) -> list[OrderRecord]:
    """抓某狀態的訂單（預設 waitbuyerpay 待付款），翻頁抓完。

    since_date（'YYYY-MM-DD'）：只留 gmtCreate >= 此日的訂單（None＝不篩）。
    回傳 OrderRecord list（依 create_time 新→舊）。
    """
    def notify(msg: str) -> None:
        logger.info(msg)
        if callback:
            try:
                callback(msg)
            except Exception:
                pass

    cookies = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
    if not cookies:
        raise ValueError("Cookie 檔案是空的，請重新登入 1688")

    records: list[OrderRecord] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled",
                  "--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            user_agent=USER_AGENT, viewport={"width": 1440, "height": 900},
            locale="zh-CN", timezone_id="Asia/Shanghai",
            extra_http_headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        await ctx.add_init_script(ANTI_DETECT_SCRIPT)
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()
        try:
            notify("開啟 1688 訂單頁…")
            await page.goto(ORDER_PAGE_URL, wait_until="domcontentloaded", timeout=60000)
            if "login" in page.url:
                raise RuntimeError("Cookie 失效（被導向登入頁），請用主程式「🔑 登入 1688」重登")
            # SPA 載入後會自我導航（補 &page=1）會打掉執行環境 → 先等頁面安定
            try:
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(3)
            # 等 lib.mtop 載入
            for _ in range(20):
                try:
                    has = await page.evaluate("() => !!((window.lib && window.lib.mtop) || window.mtop)")
                except Exception:
                    has = False
                if has:
                    break
                await asyncio.sleep(0.5)

            total = None
            for p in range(1, max_pages + 1):
                r = await _evaluate_retry(page, CALL_JS,
                                          {"status": status, "page": p, "pageSize": page_size})
                if r.get("err"):
                    raise RuntimeError(f"訂單 API 呼叫失敗：{r['err']}")
                rows, total = _unwrap(r["res"])
                if not rows:
                    break
                for o in rows:
                    records.append(_parse_order(o))
                notify(f"已抓第 {p} 頁：{len(rows)} 筆（累計 {len(records)}／共 {total}）")
                if len(records) >= total or len(rows) < page_size:
                    break
                await asyncio.sleep(0.8)
        finally:
            await browser.close()

    if since_date:
        before = len(records)
        records = [r for r in records if r.create_date >= since_date]
        notify(f"日期篩選 >= {since_date}：{before} → {len(records)} 筆")
    records.sort(key=lambda r: r.create_time, reverse=True)
    return records


# 1688_DB 表頭（26 欄，逐字比照既有分頁）
DB_HEADERS = [
    "订单编号", "买家公司名", "买家会员名", "卖家公司名", "卖家会员名",
    "货品总价(元)", "运费(元)", "涨价或折扣(元)", "实付款(元)", "订单状态",
    "订单创建时间", "订单付款时间", "发货方", "收货人姓名", "收货地址",
    "邮编", "联系电话", "联系手机", "货品标题", "单价(元)",
    "数量", "单位", "货号", "型号", "Offer ID", "SKU ID",
]


def to_db_grid(records: list[OrderRecord]) -> list[list]:
    """OrderRecord list → 1688_DB 資料列（26 欄）。

    一張訂單多列：第一列填訂單級欄位＋第一個品項；後續列只填品項欄（訂單級留空），
    比照 1688 官方訂單報表匯出格式（各日期核對分頁靠此結構）。
    """
    grid: list[list] = []
    for r in records:
        entries = r.entries or [OrderEntry()]
        for i, e in enumerate(entries):
            if i == 0:
                head = [
                    r.order_no, "", r.buyer_login, r.seller_company, r.seller_login,
                    r.goods_total, r.freight, r.discount, r.actual_pay, r.status_label,
                    _fmt_date_slash(r.create_time), r.pay_time, "", "", "", "", "", "",
                ]
            else:
                head = [""] * 18
            item = [e.title, e.unit_price, e.qty, e.unit,
                    e.product_number, "", e.offer_id, e.sku_id]
            grid.append(head + item)
    return grid
