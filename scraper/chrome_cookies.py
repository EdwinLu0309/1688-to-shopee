"""
從「日常 Google Chrome」收割現成的登入 cookie（不開瀏覽器、不登入、不碰驗證）。
移植自 listing-optimization-tool/tools/shopee-video-batch/grab_session.py（#S065 的解密法），
這裡泛化成「抓任一網域的 cookie」，供抓私有 Google Sheet 用。

macOS：`security` 取 "Chrome Safe Storage" 金鑰 → PBKDF2-SHA1(saltysalt,1003,16) →
        AES-128-CBC(v10) 解密 → 去 PKCS7 padding（新版前綴 32 byte domain hash 也處理）。
        首次會跳一次鑰匙圈授權，按「允許」。
Windows：金鑰在 `Local State` 的 os_crypt.encrypted_key（DPAPI 加密）→ CryptUnprotectData →
        AES-256-GCM 解 v10/v11 cookie。
        ⚠️ Chrome 127+ 的 **App-Bound Encryption（v20）**無法只靠 DPAPI 解（金鑰再被包一層，
        要 SYSTEM 權限或 Chrome 的 IElevator COM），本模組**遇 v20 直接跳過**。現代 Chrome 的
        cookie 幾乎全是 v20 → Windows 上這條路通常收不到料，改走 scraper/google_login.py
        （Playwright 登入一次存 session）。詳見 sheet_fetcher 的多來源 fallback。

用法：
    profiles = list_profiles()
    cookies  = get_cookies("google.com", profile="Default")   # playwright/httpx 通用 dict
"""
import base64
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import tempfile
from pathlib import Path

from loguru import logger

_IS_MAC = platform.system() == "Darwin"
_IS_WIN = platform.system() == "Windows"

if _IS_MAC:
    CHROME_DIR = Path.home() / "Library/Application Support/Google/Chrome"
elif _IS_WIN:
    CHROME_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/User Data"
else:
    CHROME_DIR = Path.home() / ".config/google-chrome"  # Linux（未驗證）


# ── macOS 金鑰 + CBC 解密 ────────────────────────────────
def _mac_chrome_key() -> bytes:
    import subprocess

    pw = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        capture_output=True, text=True,
    ).stdout.strip()
    if not pw:
        raise RuntimeError("拿不到 Chrome Safe Storage 金鑰（鑰匙圈授權被拒？）")
    return hashlib.pbkdf2_hmac("sha1", pw.encode(), b"saltysalt", 1003, 16)


def _mac_decrypt(enc: bytes, key: bytes) -> str | None:
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


# ── Windows 金鑰（DPAPI）+ GCM 解密 ────────────────────────
def _dpapi_unprotect(data: bytes) -> bytes:
    """呼叫 Win32 CryptUnprotectData（走 ctypes，免 pywin32 相依）。"""
    import ctypes
    import ctypes.wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    blob_in = DATA_BLOB(len(data),
                        ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                    ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise RuntimeError("CryptUnprotectData 失敗（金鑰非本使用者/機器加密？）")
    n = blob_out.cbData
    buf = ctypes.create_string_buffer(n)
    ctypes.memmove(buf, blob_out.pbData, n)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return buf.raw


def _win_chrome_key() -> bytes:
    ls_path = CHROME_DIR / "Local State"
    local_state = json.loads(ls_path.read_text(encoding="utf-8"))
    enc_key = base64.b64decode(local_state["os_crypt"]["encrypted_key"])
    if enc_key[:5] != b"DPAPI":
        raise RuntimeError("Local State encrypted_key 前綴非 DPAPI，格式不符")
    return _dpapi_unprotect(enc_key[5:])  # 去掉 "DPAPI" 前綴後 DPAPI 解 → 32 byte AES 金鑰


def _win_decrypt(enc: bytes, key: bytes) -> str | None:
    prefix = enc[:3]
    if prefix in (b"v10", b"v11"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce, ct = enc[3:15], enc[15:]  # 12 byte nonce + (ciphertext || 16 byte GCM tag)
        try:
            data = AESGCM(key).decrypt(nonce, ct, None)
        except Exception:  # noqa: BLE001
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data[32:].decode("utf-8", "ignore")  # 新版前綴 32 byte domain hash
    if prefix == b"v20":
        # App-Bound Encryption：金鑰被 Chrome 服務再包一層，DPAPI 解不開 → 跳過。
        return None
    # 舊格式（無版本前綴）：整段就是 DPAPI 密文
    try:
        return _dpapi_unprotect(enc).decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None


# ── 共用：列 profile、讀 DB、解密 ──────────────────────────
def list_profiles() -> list[str]:
    """列出 Chrome 有 Cookies 檔的設定檔（Default / Profile 1 …）。"""
    if not CHROME_DIR.exists():
        return []
    profiles = []
    for d in sorted(CHROME_DIR.glob("*")):
        if d.is_dir() and ((d / "Network/Cookies").exists() or (d / "Cookies").exists()):
            profiles.append(d.name)
    profiles.sort(key=lambda p: (p != "Default", p))  # Default 優先
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
    Windows 上遇 v20（App-Bound）cookie 會被跳過，可能回空清單 → 改走 google_login。
    """
    if _IS_MAC:
        key = _mac_chrome_key()
        decrypt = _mac_decrypt
    elif _IS_WIN:
        key = _win_chrome_key()
        decrypt = _win_decrypt
    else:
        raise NotImplementedError("Chrome cookie 解密只支援 macOS / Windows")

    src = _cookies_db(profile)
    tmp = Path(tempfile.gettempdir()) / f"_grab_cookies_1688_{os.getpid()}.db"
    shutil.copy2(src, tmp)  # 複製避免 Chrome 鎖檔（Chrome 執行中仍可能 copy 失敗 → 由呼叫端處理）
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
    cookies, skipped_v20 = [], 0
    for host, name, enc, path, exp, sec, http, ss in rows:
        enc = bytes(enc)
        if _IS_WIN and enc[:3] == b"v20":
            skipped_v20 += 1
        val = decrypt(enc, key)
        if val is None:
            continue
        cookies.append({
            "name": name, "value": val, "domain": host, "path": path or "/",
            "expires": (exp / 1_000_000 - 11644473600) if exp else -1,
            "httpOnly": bool(http), "secure": bool(sec), "sameSite": sm.get(ss, "Lax"),
        })
    msg = f"profile「{profile}」網域 %{domain_like}% → 解出 {len(cookies)} cookie"
    if skipped_v20:
        msg += f"（另跳過 {skipped_v20} 個 v20/App-Bound，Windows 無法解 → 請改用 Google 登入）"
    logger.debug(msg)
    return cookies
