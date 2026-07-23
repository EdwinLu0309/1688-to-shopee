"""蝦皮賣家中心 mydata API client。

cookie 來源：Playwright storage_state JSON（shopee_login.py 產出，
config/shopee_cookies_{shop}.json）。關鍵 cookie `SPC_CDS` 需同時以
query 參數帶上（SPC_CDS_VER=2）。
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from loguru import logger

BASE_URL = "https://seller.shopee.tw"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class ShopeeAPIError(RuntimeError):
    def __init__(self, code: int, msg: str, path: str):
        super().__init__(f"mydata API 錯誤 code={code} msg={msg} path={path}")
        self.code = code
        self.msg = msg
        self.path = path

    @property
    def is_session_expired(self) -> bool:
        text = (self.msg or "").lower()
        return "login" in text or "session" in text or "auth" in text


class ShopeeDataClient:
    """帶登入 cookie 打 seller.shopee.tw 的 mydata API。"""

    def __init__(self, cookies_path: str | Path):
        self.cookies_path = Path(cookies_path)
        cookies = self._load_cookies(self.cookies_path)
        self.spc_cds = cookies.get("SPC_CDS", "")
        if not self.spc_cds:
            raise ValueError(f"{self.cookies_path} 裡沒有 SPC_CDS cookie，請先跑 shopee-login")
        self._http = httpx.Client(
            base_url=BASE_URL,
            cookies=cookies,
            headers={"User-Agent": USER_AGENT, "Referer": BASE_URL + "/datacenter/overview"},
            timeout=30,
        )

    @staticmethod
    def _load_cookies(path: Path) -> dict[str, str]:
        """讀 Playwright storage_state 或單純 {name: value} dict。"""
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "cookies" in data:  # storage_state 格式
            return {
                c["name"]: c["value"]
                for c in data["cookies"]
                if "shopee" in c.get("domain", "")
            }
        if isinstance(data, list):  # cookie list 格式
            return {c["name"]: c["value"] for c in data}
        return dict(data)

    def _check(self, body: dict, path: str) -> dict:
        code = body.get("code", -1)
        if code != 0:
            err = ShopeeAPIError(code, body.get("msg") or body.get("message", ""), path)
            logger.error(str(err))
            raise err
        return body.get("result") or body.get("data") or {}

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET mydata 端點，自動帶 SPC_CDS；code != 0 丟 ShopeeAPIError。"""
        q = {"SPC_CDS": self.spc_cds, "SPC_CDS_VER": "2"}
        q.update(params or {})
        resp = self._http.get(path, params=q)
        resp.raise_for_status()
        return self._check(resp.json(), path)

    def post(self, path: str, json_body: dict) -> dict:
        """POST 端點（廣告 pas 用），自動帶 SPC_CDS query；code != 0 丟 ShopeeAPIError。"""
        q = {"SPC_CDS": self.spc_cds, "SPC_CDS_VER": "2"}
        resp = self._http.post(path, params=q, json=json_body)
        resp.raise_for_status()
        return self._check(resp.json(), path)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
