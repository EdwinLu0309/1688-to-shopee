"""
從「日常 Google Chrome」收割現成的登入 cookie（不開瀏覽器、不登入、不碰驗證）。
移植自 listing-optimization-tool/tools/shopee-video-batch/grab_session.py（#S065 的解密法），
這裡泛化成「抓任一網域的 cookie」，供抓私有 Google Sheet 用。

macOS：`security` 取 "Chrome Safe Storage" 金鑰 → PBKDF2-SHA1(saltysalt,1003,16) →
        AES-128-CBC(v10) 解密 → 去 PKCS7 padding（新版前綴 32 byte domain hash 也處理）。
        首次會跳一次鑰匙圈授權，按「允許」。
Windows：Chrome 用 DPAPI + AES-GCM，解法不同，尚未實作（先擋，之後補）。

用法：
    profiles = list_profiles()
    cookies  = get_cookies("google.com", profile="Default")   # playwright/httpx 通用 dict
"""
import hashlib
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from loguru import logger

_IS_MAC = platform.system() == "Darwin"
CHROME_DIR = Path.home() / "Library/Application Support/Google/Chrome"  # macOS


def _mac_chrome_key() -> bytes:
    pw = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not pw:
        raise RuntimeError("拿不到 Chrome Safe Storage 金鑰（鑰匙圈授權被拒？）")
    return hashlib.pbkdf2_hmac("sha1", pw.encode(), b"saltysalt", 1003, 16)


def _decrypt(enc: bytes, key: bytes) -> str | None:
    if not enc or enc[:3] != b"v10":
        return None
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16), backend=default_backend()).decryptor()
    data = dec.update(enc[3:]) + dec.finalize()
    if data:
        data = data[:-data[-1]]  # PKCS7
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data[32:].decode("utf-8", "ignore")  # 新版 Chrome 前綴 32 byte domain hash


def list_profiles() -> list[str]:
    """列出 Chrome 有 Cookies 檔的設定檔（Default / Profile 1 …）。"""
    if not _IS_MAC:
        return []
    profiles = []
    for d in sorted(CHROME_DIR.glob("*")):
        if d.is_dir() and ((d / "Network/Cookies").exists() or (d / "Cookies").exists()):
            profiles.append(d.name)
    # Default 優先
    profiles.sort(key=lambda p: (p != "Default", p))
    return profiles


def _cookies_db(profile: str) -> Path:
    for rel in ("Network/Cookies", "Cookies"):
        p = CHROME_DIR / profile / rel
        if p.exists():
            return p
    raise FileNotFoundError(f"找不到 {profile} 的 Cookies 檔")


def get_cookies(domain_like: str, profile: str = "Default") -> list[dict]:
    """解密指定 profile 中某網域的 cookie → playwright/httpx 通用 dict 清單。

    domain_like：host_key LIKE '%{domain_like}%'（如 "google.com"）。
    """
    if not _IS_MAC:
        raise NotImplementedError("目前只實作 macOS 的 Chrome cookie 解密；Windows(DPAPI) 待補")

    src = _cookies_db(profile)
    tmp = Path(tempfile.gettempdir()) / "_grab_cookies_1688.db"
    shutil.copy2(src, tmp)  # 複製避免 Chrome 鎖檔
    key = _mac_chrome_key()
    try:
        con = sqlite3.connect(str(tmp))
        rows = con.execute(
            "SELECT host_key,name,encrypted_value,path,expires_utc,is_secure,is_httponly,samesite "
            f"FROM cookies WHERE host_key LIKE '%{domain_like}%'"
        ).fetchall()
        con.close()
    finally:
        tmp.unlink(missing_ok=True)

    sm = {0: "None", 1: "Lax", 2: "Strict", -1: "Lax"}
    cookies = []
    for host, name, enc, path, exp, sec, http, ss in rows:
        val = _decrypt(enc, key)
        if val is None:
            continue
        cookies.append({
            "name": name, "value": val, "domain": host, "path": path or "/",
            "expires": (exp / 1_000_000 - 11644473600) if exp else -1,
            "httpOnly": bool(http), "secure": bool(sec), "sameSite": sm.get(ss, "Lax"),
        })
    logger.debug(f"profile「{profile}」網域 %{domain_like}% → 解出 {len(cookies)} cookie")
    return cookies
