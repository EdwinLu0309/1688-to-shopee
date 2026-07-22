"""Cookie 健康檢查：判斷 1688 登入 cookie「快過期／已過期」，回傳一眼可見的狀態字串。

兩個訊號（見 CLAUDE.md「常駐監聽」cookie 過期段）：
1. **檔案到期日（便宜、無網路）**：讀登入態關鍵 cookie 的 expires，取最早到期者算距今天數。
   1688 session 名目壽命約 7 天（實測 7/14 存→7/21 死），剩 ≤ WARN_DAYS 天就標黃燈。
   ⚠️ 這是「上限」：1688 伺服器可能提早作廢（風控／異地登入），故再配探測。
2. **輕量探測（每日一次、要網路）**：帶 cookie 打一次 1688 訂單 API（page=1,pageSize=1），
   回 SESSION_EXPIRED＝已死 → 紅燈。補「檔案還沒到期但伺服器已殺」的情況。

狀態字串附「該用哪個程式重登」提示（relogin_hint），Edwin 一看就知道去點哪顆按鈕。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

# 登入態關鍵 cookie（最早到期者決定 session 實際壽命；避開 cna/aui 這種長效非登入 cookie）
_LOGIN_COOKIES = {"cookie2", "_tb_token_", "unb", "sgcookie", "t", "_nk_", "_l_g_"}
WARN_DAYS = 2.0   # 最早登入 cookie 剩 ≤ 此天數 → 黃燈「快過期」


def _load(cookie_path: str) -> list:
    data = json.loads(Path(cookie_path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("cookies", data)


def expiry_days(cookie_path: str) -> Optional[float]:
    """最早到期的『登入態』cookie 距今天數；讀不到／無此類 cookie 回 None。"""
    try:
        cookies = _load(cookie_path)
    except Exception:
        return None
    now = time.time()
    exps = [
        c.get("expires", c.get("expiry"))
        for c in cookies
        if c.get("name") in _LOGIN_COOKIES
    ]
    exps = [e for e in exps if isinstance(e, (int, float)) and e > 0]
    if not exps:
        return None
    return (min(exps) - now) / 86400.0


def relogin_hint(cookie_path: str) -> str:
    """依 cookie 檔名回「該用哪個程式／按鈕重登」。"""
    name = Path(cookie_path).name
    if name == "cookies_nail.json":
        return "雙擊 run_reconcile_mac.command → 按「🔑 登入美甲帳號」(帳號 jiaorong0826)"
    if name == "cookies_baby.json":
        return "登入 Baby 帳號 luwei03090826 重產 cookies_baby.json"
    if name == "cookies.json":
        return "雙擊 run_mac.command → 按「🔑 登入 1688」(服飾 joyslunailshop)"
    return f"重新登入產生 {name}"


async def probe_alive(cookie_path: str) -> tuple[bool, str]:
    """帶 cookie 輕量打一次 1688 訂單 API（page=1,pageSize=1）看 session 活不活。

    回 (alive, detail)。SESSION_EXPIRED／被導登入頁＝False；限流／網路錯不算過期＝True（避免誤報）。
    """
    from .pending_scraper import scrape_pending_orders
    try:
        await scrape_pending_orders(
            cookie_path=cookie_path, status="waitbuyerpay",
            headless=True, page_size=1, max_pages=1,
        )
        return True, "ok"
    except Exception as e:
        s = str(e)
        if "SESSION_EXPIRED" in s or "Session过期" in s or "登入頁" in s or "login" in s.lower():
            return False, s[:120]
        return True, f"非過期錯誤（不判死）：{s[:100]}"


def status_line(cookie_path: str, probe_dead: Optional[bool] = None) -> str:
    """組出給人看的 cookie 狀態字串。

    ⚠️ 實測發現：讀檔案到期日會**誤報**——短命 cookie(cookie2 等)名目過期，但 1688 伺服器端
    session 常還有效（靠長命 cookie 撐）。故**探測(實打 1688)是權威**，檔案到期日只當軟提示，
    絕不單憑檔案報紅（避免叫人白重登）。

    probe_dead：探測結果。True＝實測已死（權威）；False＝實測仍活（權威）；None＝這輪沒探測。
    """
    hint = relogin_hint(cookie_path)
    if not Path(cookie_path).exists():
        return f"🔴 沒有 cookie（尚未登入）→ {hint}"
    days = expiry_days(cookie_path)
    days_txt = f"名目剩 {days:.1f} 天" if days is not None else "名目到期未知"

    if probe_dead is True:                       # 探測確認死 → 權威紅燈
        return f"🔴 已過期（1688 實測 session 失效）→ {hint}"
    if probe_dead is False:                       # 探測確認活 → 權威綠燈（名目快到期時附提醒）
        if days is not None and days <= WARN_DAYS:
            return f"🟢 有效（1688 實測 OK）；但 {days_txt}，建議近日重登：{hint}"
        return f"🟢 正常（1688 實測 OK，{days_txt}）"

    # 這輪沒探測（CLI 快查／反應式）→ 只憑檔案，不報硬紅，過期只給「待探測確認」
    if days is None:
        return "⚪ 無法判斷（cookie 檔異常，建議重登確認）"
    if days <= 0:
        return f"🟡 名目已到期（待每日探測確認是否仍有效；如抓取失敗再重登）→ {hint}"
    if days <= WARN_DAYS:
        return f"🟡 名目快到期（約剩 {days:.1f} 天）→ 建議趁在 Mac 前重登：{hint}"
    return f"🟢 名目正常（約剩 {days:.1f} 天，未實測）"
