"""
用「收割日常 Chrome 的 Google session cookie」抓私有 Google Sheet → 落地成 CSV。
（路 B：不開瀏覽器、不登入、不碰驗證；私有表公開匯出會 401，靠登入 cookie 才讀得到。）

流程：chrome_cookies.get_cookies("google.com", profile) → httpx 帶 cookie 打 gviz
     `/gviz/tq?tqx=out:csv&gid=<gid>` → 回 CSV 存檔。逐一 profile 試，第一個抓到
     合法 CSV 的就用（自動判斷哪個 Chrome 設定檔登入了名單那個 Google 帳號）。
"""
from pathlib import Path

import httpx
from loguru import logger

from scraper.chrome_cookies import get_cookies, list_profiles


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


def fetch_sheet_csv(
    sheet_id: str,
    gid: str,
    out_path: Path,
    profile: str | None = None,
) -> dict:
    """抓私有 Sheet → 存 out_path。回傳 {ok, profile, bytes, error}。

    profile 指定就只試那個；否則掃所有 Chrome 設定檔，第一個成功的就用。
    """
    profiles = [profile] if profile else list_profiles()
    if not profiles:
        return {"ok": False, "error": "找不到任何 Chrome 設定檔（只支援 macOS）"}

    tried = []
    for prof in profiles:
        try:
            cookies = get_cookies("google.com", prof)
        except NotImplementedError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # noqa: BLE001
            tried.append(f"{prof}(cookie 讀取失敗:{e})")
            continue
        if not cookies:
            tried.append(f"{prof}(無 google cookie)")
            continue
        csv_text = _fetch_with_cookies(sheet_id, gid, cookies)
        if csv_text:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(csv_text, encoding="utf-8")
            logger.info(f"✓ 用設定檔「{prof}」抓到名單 → {out_path}（{len(csv_text)} chars）")
            return {"ok": True, "profile": prof, "bytes": len(csv_text.encode()), "error": ""}
        tried.append(f"{prof}(未授權/非CSV)")

    return {"ok": False, "error": "所有設定檔都抓不到（可能都沒登入該 Google 帳號）：" + ", ".join(tried)}


def fetch_ai_list(out_path: Path | None = None, profile: str | None = None) -> dict:
    """抓「【Lady】AI 上架名單」→ input/lady_ai_list.csv（用 settings 的 SHEET_ID/GID）。"""
    from config.settings import AI_LIST_SHEET_ID, AI_LIST_SHEET_GID

    if out_path is None:
        out_path = Path(__file__).resolve().parent.parent / "input" / "lady_ai_list.csv"
    return fetch_sheet_csv(AI_LIST_SHEET_ID, str(AI_LIST_SHEET_GID), Path(out_path), profile)
