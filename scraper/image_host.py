"""
圖床：把本機圖片上傳 Supabase Storage public bucket → 回公開 https URL。

用途：GPT 生的電商圖是本機 PNG，但蝦皮大量上架 Excel 圖片欄要 https 網址，
本機檔塞不進 → 上傳 Supabase 拿 URL 再填 Excel。1688 路線不需要（直接用 1688 URL）。

環境變數（.env）：SUPABASE_URL / SUPABASE_SERVICE_KEY（sb_secret_…）/ SUPABASE_BUCKET。
REST API：POST /storage/v1/object/{bucket}/{path}（Bearer service key）；
公開網址 = /storage/v1/object/public/{bucket}/{path}。只用 httpx，無需 supabase SDK。
"""
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from loguru import logger

load_dotenv(override=True)

_EXT_CT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
           ".webp": "image/webp", ".gif": "image/gif"}


def _config() -> tuple[str, str, str]:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    url = url.replace("/rest/v1", "").rstrip("/")   # 容錯：有人貼到 Data API endpoint
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    bucket = os.environ.get("SUPABASE_BUCKET", "joyslu-images").strip()
    return url, key, bucket


def is_configured() -> bool:
    url, key, _ = _config()
    return bool(url and key)


def upload_image(local_path: Path, dest_path: str, upsert: bool = True) -> str | None:
    """上傳一張圖 → 回公開 URL。dest_path 是 bucket 內路徑（如 P14AE1/gpt_highwaist.png）。"""
    url, key, bucket = _config()
    if not (url and key):
        logger.error("Supabase 未設定（SUPABASE_URL / SUPABASE_SERVICE_KEY）")
        return None
    local_path = Path(local_path)
    if not local_path.exists():
        logger.warning(f"圖片不存在，跳過上傳：{local_path}")
        return None

    ct = _EXT_CT.get(local_path.suffix.lower(), "application/octet-stream")
    headers = {"Authorization": f"Bearer {key}", "apikey": key,
               "Content-Type": ct, "x-upsert": "true" if upsert else "false"}
    put_url = f"{url}/storage/v1/object/{bucket}/{dest_path}"
    try:
        r = httpx.post(put_url, headers=headers, content=local_path.read_bytes(), timeout=60)
    except Exception as e:  # noqa: BLE001
        logger.error(f"上傳失敗（{local_path.name}）：{e}")
        return None
    if r.status_code not in (200, 201):
        logger.error(f"上傳失敗（{local_path.name}）：HTTP {r.status_code} {r.text[:120]}")
        return None
    pub = f"{url}/storage/v1/object/public/{bucket}/{dest_path}"
    logger.info(f"上傳圖床：{dest_path} → {pub}")
    return pub


def upload_images(paths: list[Path], code: str, subdir: str = "gpt") -> list[str]:
    """批次上傳一支商品的圖 → [公開 URL]。dest = {code}/{subdir}/{檔名}。"""
    urls = []
    for p in paths:
        p = Path(p)
        dest = f"{code}/{subdir}/{p.name}"
        u = upload_image(p, dest)
        if u:
            urls.append(u)
    return urls
