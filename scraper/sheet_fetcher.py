"""抓「AI 上架名單」私有 Sheet → 落地成 CSV（供 batch2 --ai-list 讀）。

#S134：改走 Service Account（inventory-sync SA，該表已分享給它）——與其他所有 Google 表
統一走 SA，不再需要 Google 個人登入 cookie（原 google_login / chrome_cookies 繞路已退休）。
介面（fetch_ai_list / fetch_sheet_csv 簽章與回傳鍵）保持不變，呼叫端 gui.py / main.py 無感。
"""
import csv
import io
from pathlib import Path

from loguru import logger


def _sa_json() -> str:
    from config.settings import ORDER_SHEET_SA_JSON  # inventory-sync SA（該表已分享）
    return ORDER_SHEET_SA_JSON


def fetch_sheet_csv(sheet_id: str, gid: str, out_path: Path, profile=None) -> dict:
    """用 SA 讀私有 Sheet（gid → 對應分頁；預設第一個）→ 寫 CSV 到 out_path。

    回傳 {ok, profile, bytes, error, need_login}（鍵沿用舊版；profile 固定 "SA"、need_login 恆 False）。
    """
    try:
        from ecommerce_sources import gsheet

        gc = gsheet.client(sa_json=_sa_json(),
                           scopes=["https://www.googleapis.com/auth/spreadsheets"])
        sh = gc.open_by_key(sheet_id)
        ws = next((w for w in sh.worksheets() if str(w.id) == str(gid)), None) \
            or sh.get_worksheet(0)
        rows = ws.get_all_values()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "profile": "SA", "bytes": 0,
                "error": f"SA 讀取失敗：{e}（確認表已分享給 inventory-sync SA）",
                "need_login": False}

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    text = buf.getvalue()
    out_path.write_text(text, encoding="utf-8")
    logger.info(f"✓ SA 讀 AI 名單 → {out_path}（{len(rows)} 列）")
    return {"ok": True, "profile": "SA", "bytes": len(text.encode()),
            "error": "", "need_login": False}


def fetch_ai_list(out_path: Path | None = None, profile=None) -> dict:
    """抓「【Lady】AI 上架名單」→ input/lady_ai_list.csv（用 settings 的 SHEET_ID/GID）。"""
    from config.settings import AI_LIST_SHEET_GID, AI_LIST_SHEET_ID

    if out_path is None:
        out_path = Path(__file__).resolve().parent.parent / "input" / "lady_ai_list.csv"
    return fetch_sheet_csv(AI_LIST_SHEET_ID, str(AI_LIST_SHEET_GID), Path(out_path), profile)
