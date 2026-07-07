"""
抓私有 Google Sheet → 落地成 CSV（私有表公開匯出會 401，靠登入 cookie 才讀得到）。

cookie 來源有兩條，依序試（見 _cookie_sources）：
  1. config/google_cookies.json —— Playwright 登入一次存下的 session（跨平台，Windows 主力）。
  2. 收割日常 Chrome 的 Google cookie（chrome_cookies）—— macOS 免登入零點擊；
     Windows 因 App-Bound(v20) 多半收不到，當備援。
拿到 cookie → httpx 帶著打 gviz `/gviz/tq?tqx=out:csv&gid=<gid>` → 回合法 CSV 就存檔。
"""
from pathlib import Path

import httpx
from loguru import logger

from scraper.chrome_cookies import get_cookies, list_profiles
from scraper.google_login import load_saved_cookies


def _gviz_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"


def _looks_like_csv(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    if head.startswith("<") or "doctype" in head or "accounts.google" in head:
        return False
    return ("," in head) or ("\n" in text)


def _fetch_with_cookies(sheet_id: str, gid: str, cookies: list[dict]) -> str | None:
    jar = httpx.Cookies()
    for c in cookies:
        try:
            jar.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
        except Exception:  # noqa: BLE001
            continue
    try:
        r = httpx.get(_gviz_url(sheet_id, gid), cookies=jar,
                      follow_redirects=True, timeout=30)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"httpx 抓取失敗：{e}")
        return None
    if r.status_code == 200 and _looks_like_csv(r.text):
        return r.text
    logger.debug(f"非合法 CSV：HTTP {r.status_code} ct={r.headers.get('content-type','?')[:30]}")
    return None


def _cookie_sources(profile: str | None):
    """依序 yield (來源標籤, cookie 清單)，可靠/便宜的先試。"""
    # 1. Playwright 登入存下的 session（跨平台，最可靠；Windows 唯一實際可行的路）
    saved = load_saved_cookies()
    if saved:
        yield ("已登入 session", saved)

    # 2. 收割日常 Chrome 的 cookie（macOS 免登入；Windows v20 多半收不到 → 自動略過）
    profiles = [profile] if profile else list_profiles()
    for prof in profiles:
        try:
            cookies = get_cookies("google.com", prof)
        except NotImplementedError:
            break  # 平台不支援收割 → 不再試 Chrome，交給上面的 saved
        except Exception as e:  # noqa: BLE001
            logger.debug(f"設定檔「{prof}」cookie 讀取失敗：{e}")
            continue
        if cookies:
            yield (f"Chrome:{prof}", cookies)


def fetch_sheet_csv(
    sheet_id: str,
    gid: str,
    out_path: Path,
    profile: str | None = None,
) -> dict:
    """抓私有 Sheet → 存 out_path。回傳 {ok, profile, bytes, error, need_login}。

    依序試「已登入 session」與各 Chrome 設定檔，第一個抓到合法 CSV 的就用。
    全都拿不到時 need_login=True，提示使用者去按「🔑 Google 登入」。
    """
    tried = []
    for label, cookies in _cookie_sources(profile):
        csv_text = _fetch_with_cookies(sheet_id, gid, cookies)
        if csv_text:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(csv_text, encoding="utf-8")
            logger.info(f"✓ 用「{label}」抓到名單 → {out_path}（{len(csv_text)} chars）")
            return {"ok": True, "profile": label, "bytes": len(csv_text.encode()),
                    "error": "", "need_login": False}
        tried.append(f"{label}(未授權/非CSV/過期)")

    if not tried:
        err = "沒有可用的 Google 登入資訊——請先按「🔑 Google 登入」登入一次"
    else:
        err = "現有登入都抓不到（可能過期或無此表存取權）：" + "、".join(tried) + \
              "。請按「🔑 Google 登入」重新登入"
    return {"ok": False, "error": err, "need_login": True}


def fetch_ai_list(out_path: Path | None = None, profile: str | None = None) -> dict:
    """抓「【Lady】AI 上架名單」→ input/lady_ai_list.csv（用 settings 的 SHEET_ID/GID）。"""
    from config.settings import AI_LIST_SHEET_ID, AI_LIST_SHEET_GID

    if out_path is None:
        out_path = Path(__file__).resolve().parent.parent / "input" / "lady_ai_list.csv"
    return fetch_sheet_csv(AI_LIST_SHEET_ID, str(AI_LIST_SHEET_GID), Path(out_path), profile)
