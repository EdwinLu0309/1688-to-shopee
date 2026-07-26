"""
商品資產包「一鍵同步」編排器（2026-07-26 #S103）。

運轉方式（Edwin 定）：主表「商品表」有 `要產`(checkbox) 與 `資產包狀態` 兩欄。
Edwin 在主表勾要跑的商品 → 觸發本流程：
  讀主表勾選 → （沒抓過才）抓 1688 → 產資產包（下載圖+vision 賣點+主表編號+繁體）→ 寫雲端
  → 回寫主表：資產包狀態＝✓、清掉要產勾選。
增量：只跑「勾了要產」的（或 only_missing 時＝資產包狀態還空的），已完成的不重跑。

在 Edwin 的機器跑（要 Playwright / SA / OPENAI_API_KEY / 掛好的雲端硬碟）。抓取被擋
（主圖 0）的商品會**跳過、不標完成**，留著下次重跑。
"""
import asyncio
import json
from pathlib import Path

from loguru import logger


def sync_assets(
    shop: str,
    out_base: str | Path,
    sa_json: str | None = None,
    only_missing: bool = False,
    analyze: bool = True,
    headless: bool = False,
    progress=logger.info,
) -> dict:
    """一鍵同步。

    Args:
        shop:         賣場代號（nail/lady/baby）
        out_base:     雲端「商品資產」根（如 G:\\…\\【Nail】1. 商品\\商品資產）
        sa_json:      主表 SA 憑證（預設自動找）
        only_missing: True＝跑所有「資產包狀態還空」的（不看勾選）；False＝只跑勾了「要產」的
        analyze:      是否跑 vision 賣點解析（要 OPENAI_API_KEY）
        headless:     抓取瀏覽器是否無頭（預設 False，被擋時 Edwin 看得到可登入）

    Returns:
        {total, done, failed, blocked, results:[{code, ok, note}]}
    """
    from config.settings import OUTPUT_DIR
    from scraper.master_reader import open_for_sync, write_status
    from scraper.playwright_scraper import scrape_many
    from scraper.product_card import generate_asset_packs

    ws, colmap, records = open_for_sync(sa_json)
    if only_missing:
        targets = [r for r in records if not r["asset_done"]]
    else:
        targets = [r for r in records if r["want"]]

    if not targets:
        msg = "沒有要跑的商品（勾『要產』或用 --all 跑所有未完成的）。"
        progress(msg)
        return {"total": 0, "done": 0, "failed": 0, "blocked": 0, "results": []}

    progress(f"要處理 {len(targets)} 個商品（{'所有未完成' if only_missing else '勾選要產'}）")
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 抓取（沒有 output/{item_id}.json 才抓；一個瀏覽器批次抓完）
    need = [r["item_id"] for r in targets if not (out_dir / f"{r['item_id']}.json").exists()]
    blocked_ids: set[str] = set()
    if need:
        progress(f"抓取 {len(need)} 個（其餘已抓過）…")
        res = asyncio.run(scrape_many(need, headless=headless,
                                      progress_cb=lambda m: progress(m)))
        for r in res.get("results", []):
            if r.get("blocked") or not r.get("ok") or r.get("main", 0) == 0:
                blocked_ids.add(str(r["item_id"]))

    # 2. 逐一產資產包 + 回寫狀態
    done = failed = 0
    results = []
    for r in targets:
        iid, code, row = r["item_id"], r["code"], r["_row"]
        if iid in blocked_ids or not (out_dir / f"{iid}.json").exists():
            failed += 1
            results.append({"code": code, "ok": False, "note": "抓取被擋/失敗（下次重跑）"})
            progress(f"[{code}] ⚠ 抓取被擋，跳過（保留勾選下次再跑）")
            continue
        try:
            generate_asset_packs(
                json_dir=out_dir, shop=shop, out_base=Path(out_base),
                item_ids=[iid], download_media=True, analyze_highlights=analyze,
                use_master=True, sa_json=sa_json, shop_subdir=False,
            )
            write_status(ws, colmap, row, done=True, clear_want=True)
            done += 1
            results.append({"code": code, "ok": True, "note": ""})
            progress(f"[{code}] ✓ 完成，主表已標 ✓")
        except Exception as e:  # noqa: BLE001
            failed += 1
            results.append({"code": code, "ok": False, "note": str(e)})
            progress(f"[{code}] ✗ 產包失敗：{e}")

    progress(f"完成 {done} / 失敗或被擋 {failed}（共 {len(targets)}）")
    return {"total": len(targets), "done": done, "failed": failed,
            "blocked": len(blocked_ids), "results": results}
