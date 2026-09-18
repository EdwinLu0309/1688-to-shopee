"""上架核對表：自動上架產出後，把「真正要傳上去的內容」寫給員工逐支核對。

Edwin 2026-09-17 定版（【Nail】上架核對表，與 AI 上架名單同資料夾、另開一個檔）：
- **一次產出＝一個分頁，分頁名＝產出日期 MMDD**。
- **一列＝一個蝦皮商品（一個編號）**：HNV11 三個 1688 網址合成一支就是一列，
  選項／售價／SKU 品號在格子裡換行、同順序。
- 左邊灰底 A~K 程式寫；右邊黃底 L~T 員工核對（打勾＋核對日＋問題備註）。
- ⚠️ **資料來源是產出的上架檔**，不是 AI 上架名單——員工要對的是「真正傳上去的東西」
  （標題是程式生的、選項是挑過的），只有現貨/預購與 1688 網址取自這批的處理紀錄。

為什麼程式寫死值、不用 IMPORTRANGE 帶名單：帶過來的左半邊會跟著名單變，員工打的勾
是原地不動的死值 → 名單一插列／排序，勾就整片對到別支（同 1-1 訂貨表 J/O/S/T 錯位）。
現行：寫了就不動；**同一天重產第 2 版，照「編號」找到原列只更新 A~K，員工的勾保留**。

試跑（沒建檔）不寫：那份上架檔不能傳。寫入失敗不擋批次（上架檔已產好），但要大聲講。
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from loguru import logger

# 賣場 → 核對表 ID（檔案由 Edwin 建在自己的 Drive、分享給 inventory-sync SA 編輯；
# SA 沒有 Drive 容量，不能自己建檔）。沒設的賣場跳過並 warning。
CHECK_SHEETS = {
    "nail": os.environ.get("CHECK_SHEET_ID_NAIL", "1FnCcR7Ie0Qxm0ypwXMhDRKLWb3_dxEl0AKNSAtE-pjo"),
    "lady": os.environ.get("CHECK_SHEET_ID_LADY", "1yTkrDfKsqmWvk0i-sN09lEjBJJkLccHIv6qtoQTdpHI"),
    "baby": os.environ.get("CHECK_SHEET_ID_BABY", ""),
}

PROG_HEADERS = ["產出日", "版本", "編號", "蝦皮標題", "現貨/預購", "選項數", "售價",
                "選項名稱", "SKU 品號", "規格圖", "1688 網址"]
EMP_CHECKS = ["待上架區有看到", "標題 OK", "詳情 OK", "選項/價格 OK", "規格圖 OK",
              "已正式上架", "美編換圖完成"]
EMP_HEADERS = EMP_CHECKS + ["核對日", "問題備註"]
HEADERS = PROG_HEADERS + EMP_HEADERS
NP, NC, NB = len(PROG_HEADERS), len(HEADERS), len(EMP_CHECKS)
CODE_COL = PROG_HEADERS.index("編號")                       # C
URL_COL = PROG_HEADERS.index("1688 網址")                   # K
IMG_COL = PROG_HEADERS.index("規格圖")                      # J
DONE_COL = NP + EMP_CHECKS.index("已正式上架")               # Q → 整列變綠
DATA_START = 2                                              # 第 3 列起（0-based 2）
MAX_LIST = 12               # 一格最多列幾個選項；超過就壓成「幾色 × 幾尺碼」（服飾動輒 72 個）

_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


# ── 讀上架檔 ────────────────────────────────────────────────────
def _col_index(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_upload_rows(xlsx_path: Path) -> list[dict]:
    """上架檔「上傳模板」資料列 → [{模板內部 key: 值}]。

    直接讀 xlsx 的 XML：蝦皮模板帶有 openpyxl 解析不了的 sheetView（activePane 非法值）。
    """
    z = zipfile.ZipFile(xlsx_path)
    ss = [''.join(t.text or '' for t in si.iter(_M + 't'))
          for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(_M + 'si')]
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    names = [s.get('name') for s in wb.iter(_M + 'sheet')]
    idx = names.index("上傳模板") + 1 if "上傳模板" in names else 2
    sh = ET.fromstring(z.read(f'xl/worksheets/sheet{idx}.xml'))
    rows: dict[int, dict] = {}
    for r in sh.iter(_M + 'row'):
        d = {}
        for c in r.findall(_M + 'c'):
            v = c.find(_M + 'v')
            if v is None:
                continue
            d[_col_index(c.get('r'))] = ss[int(v.text)] if c.get('t') == 's' else v.text
        rows[int(r.get('r'))] = d
    keys = {i: str(k).split('|')[0] for i, k in rows.get(1, {}).items()}
    return [{keys[i]: v for i, v in rows[n].items() if i in keys}
            for n in sorted(rows) if n >= 7 and rows[n]]


# ── 組列（純函式，可離線測）─────────────────────────────────────
def build_check_rows(upload_rows: list[dict], prepared_meta: list[dict],
                     produced: str, version: str) -> list[list]:
    """上架檔資料列 ＋ 這批的處理紀錄 → 核對表程式區 A~K（一個編號一列）。

    prepared_meta：[{code, item_id, demand}]（同編號可多筆＝多個 1688 來源）。
    K 欄回傳網址 list（寫入時轉成可點的連結文字）。
    """
    by_code: dict[str, list[dict]] = {}
    for r in upload_rows:
        code = (r.get("ps_sku_parent_short") or "").strip()
        if code:
            by_code.setdefault(code, []).append(r)
    src: dict[str, dict] = {}
    for m in prepared_meta:
        s = src.setdefault(str(m["code"]), {"urls": [], "demand": ""})
        u = f"https://detail.1688.com/offer/{m['item_id']}.html"
        if u not in s["urls"]:
            s["urls"].append(u)
        s["demand"] = s["demand"] or ("預購" if "預購" in str(m.get("demand") or "") else "現貨")

    out = []
    for code, rs in by_code.items():
        def opt(r):
            a, b = r.get("et_title_option_for_variation_1", ""), r.get("et_title_option_for_variation_2", "")
            return f"{a} / {b}" if b else a
        n_img = sum(1 for r in rs if r.get("et_title_image_per_variation"))
        s = src.get(code, {"urls": [], "demand": ""})
        prices = [r.get("ps_price", "") for r in rs]
        skus = [r.get("ps_sku_short", "") for r in rs]
        if len(rs) <= MAX_LIST:
            price_cell, opt_cell, sku_cell = "\n".join(prices), "\n".join(opt(r) for r in rs), "\n".join(skus)
        else:
            # ⚠️ 服飾常常 4 色 × 6 尺碼 ＝ 72 個選項（Lady P14AE1 實況）→ 一格塞 72 行沒人看得完。
            #    壓成「兩軸各有哪些值」，員工照樣對得到，細項到蝦皮後台看。
            a1 = list(dict.fromkeys(r.get("et_title_option_for_variation_1", "") for r in rs))
            a2 = [x for x in dict.fromkeys(r.get("et_title_option_for_variation_2", "") for r in rs) if x]
            uniq_p = sorted({p for p in prices if p}, key=lambda v: float(v or 0))
            price_cell = uniq_p[0] if len(uniq_p) == 1 else f"{uniq_p[0]}~{uniq_p[-1]}" if uniq_p else ""
            opt_cell = (f"{len(rs)} 個選項＝{len(a1)} × {len(a2) or 1}\n"
                        + "\n".join(f"・{x}" for x in a1[:MAX_LIST])
                        + (f"\n…共 {len(a1)} 個" if len(a1) > MAX_LIST else "")
                        + (f"\n尺碼／規格：{'／'.join(a2)}" if a2 else ""))
            sku_cell = "\n".join(skus[:3]) + f"\n…共 {len(skus)} 個（細項看蝦皮後台）"
        out.append([
            produced, version, code, rs[0].get("ps_product_name", ""), s["demand"], len(rs),
            price_cell, opt_cell, sku_cell,
            "✅ 全有" if n_img == len(rs) else f"缺 {len(rs) - n_img}/{len(rs)}",
            s["urls"],
        ])
    return out


def plan_rows(existing_codes: list[str], rows: list[list]) -> tuple[dict[int, list], list[list]]:
    """已在分頁上的編號 → 更新原列（回 {0-based 列: 值}）；沒有的 → 接在最後面。"""
    pos = {c: i for i, c in enumerate(existing_codes) if c}
    upd, add = {}, []
    for r in rows:
        code = r[CODE_COL]
        if code in pos:
            upd[DATA_START + pos[code]] = r
        else:
            add.append(r)
    return upd, add


# ── 寫入 ────────────────────────────────────────────────────────
_GRAY = {"red": 0.85, "green": 0.87, "blue": 0.9}
_GRAY2 = {"red": 0.95, "green": 0.95, "blue": 0.96}
_YEL = {"red": 1, "green": 0.9, "blue": 0.6}
_YEL2 = {"red": 1, "green": 0.97, "blue": 0.85}
_LINE = {"style": "SOLID", "color": {"red": 0.55, "green": 0.55, "blue": 0.55}}
_THICK = {"style": "SOLID_MEDIUM", "color": {"red": 0.3, "green": 0.3, "blue": 0.3}}
_WIDTHS = [120, 85, 90, 380, 100, 80, 90, 320, 210, 95, 110] + [110] * NB + [120, 300]
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def _rng(sid, r0, r1, c0, c1):
    r = {"sheetId": sid, "startColumnIndex": c0, "endColumnIndex": c1}
    if r0 is not None:
        r["startRowIndex"] = r0
    if r1 is not None:
        r["endRowIndex"] = r1
    return r


def _fill(rng, bg, bold=False, va="TOP"):
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": {
        "backgroundColor": bg, "textFormat": {"bold": bold, "fontSize": 14},
        "verticalAlignment": va, "wrapStrategy": "WRAP"}},
        "fields": "userEnteredFormat(backgroundColor,textFormat,verticalAlignment,wrapStrategy)"}}


def _link_cell(urls: list[str]) -> dict:
    """一個網址一行「開 1688 ①」，每行各自是超連結（長網址員工看不懂也難點）。"""
    text, runs = "", []
    for i, u in enumerate(urls):
        label = f"開 1688 {_CIRCLED[i]}" if len(urls) > 1 else "開 1688"
        if text:
            text += "\n"
        runs.append({"startIndex": len(text), "format": {
            "link": {"uri": u}, "fontSize": 14, "underline": True,
            "foregroundColor": {"red": 0.07, "green": 0.33, "blue": 0.8}}})
        text += label
    cell = {"userEnteredValue": {"stringValue": text}}
    if runs:
        cell["textFormatRuns"] = runs
    return cell


def _new_tab_requests(sid: int) -> list[dict]:
    req = [
        {"mergeCells": {"range": _rng(sid, 0, 1, 0, NP), "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": _rng(sid, 0, 1, NP, NC), "mergeType": "MERGE_ALL"}},
        _fill(_rng(sid, 0, 2, 0, NP), _GRAY, True, "MIDDLE"),
        _fill(_rng(sid, 0, 2, NP, NC), _YEL, True, "MIDDLE"),
        {"updateBorders": {"range": _rng(sid, 0, 2, 0, NC), "top": _LINE, "bottom": _THICK,
                           "left": _LINE, "right": _LINE, "innerHorizontal": _LINE, "innerVertical": _LINE}},
        {"updateBorders": {"range": _rng(sid, 0, 2, NP, NP + 1), "left": _THICK}},
        {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 2}},
                                   "fields": "gridProperties(frozenRowCount)"}},
        {"setBasicFilter": {"filter": {"range": _rng(sid, 1, None, 0, NC)}}},
        # 條件式格式開到整欄：空白列不會命中（沒有「缺」、沒有打勾），所以不會多出底色
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [_rng(sid, DATA_START, None, IMG_COL, IMG_COL + 1)],
            "booleanRule": {"condition": {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "缺"}]},
                            "format": {"backgroundColor": {"red": 1, "green": 0.8, "blue": 0.8}}}}}},
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [_rng(sid, DATA_START, None, 0, NC)],
            "booleanRule": {"condition": {"type": "CUSTOM_FORMULA", "values": [{
                "userEnteredValue": f"=${_letter(DONE_COL)}{DATA_START + 1}=TRUE"}]},
                "format": {"backgroundColor": {"red": 0.84, "green": 0.93, "blue": 0.83}}}}}},
    ]
    for i, w in enumerate(_WIDTHS):
        req.append({"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS",
                    "startIndex": i, "endIndex": i + 1}, "properties": {"pixelSize": w}, "fields": "pixelSize"}})
    return req


def _row_format_requests(sid: int, r0: int, r1: int) -> list[dict]:
    """商品列才有底色、框線、勾選框（空白列保持乾淨，Edwin 2026-09-17）。"""
    return [
        _fill(_rng(sid, r0, r1, 0, NP), _GRAY2),
        _fill(_rng(sid, r0, r1, NP, NC), _YEL2),
        {"updateBorders": {"range": _rng(sid, r0, r1, 0, NC), "top": _LINE, "bottom": _LINE,
                           "left": _LINE, "right": _LINE, "innerHorizontal": _LINE, "innerVertical": _LINE}},
        {"updateBorders": {"range": _rng(sid, r0, r1, NP, NP + 1), "left": _THICK}},
        {"setDataValidation": {"range": _rng(sid, r0, r1, NP, NP + NB), "rule": {"condition": {"type": "BOOLEAN"}}}},
        {"setDataValidation": {"range": _rng(sid, r0, r1, NP + NB, NP + NB + 1),
                               "rule": {"condition": {"type": "DATE_IS_VALID"}, "inputMessage": "填日期"}}},
    ]


def _letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def write_check_sheet(shop: str, rows: list[list], tab: str, sa_json=None) -> dict:
    """寫進該賣場核對表的日期分頁。回 {sheet_id, tab, added, updated}。"""
    import gspread
    from config.settings import ORDER_SHEET_SA_JSON

    sid_sheet = CHECK_SHEETS.get(shop, "")
    if not sid_sheet:
        raise RuntimeError(f"{shop} 還沒有上架核對表（.env 設 CHECK_SHEET_ID_{shop.upper()}）")
    gc = gspread.service_account(str(sa_json or ORDER_SHEET_SA_JSON))
    ss = gc.open_by_key(sid_sheet)
    try:
        ws = ss.worksheet(tab)
        fresh = False
    except gspread.WorksheetNotFound:
        # 多開一列：分頁不能「凍結全部列」（只有 2 列又凍結 2 列會被擋）
        ws = ss.add_worksheet(tab, DATA_START + 1, NC, index=0)
        try:
            ws.update(values=[["程式寫入（不要改）"] + [""] * (NP - 1) + ["員工核對"] + [""] * (NC - NP - 1),
                              HEADERS], range_name="A1")
            ss.batch_update({"requests": _new_tab_requests(ws.id)})
        except Exception:
            ss.del_worksheet(ws)       # 半套的分頁留著，下次會被當成「已存在」而沒有表頭格式
            raise
        fresh = True

    codes = [] if fresh else ws.col_values(CODE_COL + 1)[DATA_START:]
    upd, add = plan_rows(codes, rows)
    sid = ws.id
    req = []

    def put(r0: int, row: list):
        values = [{"userEnteredValue": ({"numberValue": v} if isinstance(v, (int, float)) and not isinstance(v, bool)
                                        else {"stringValue": str(v)})} for v in row[:URL_COL]]
        req.append({"updateCells": {"range": _rng(sid, r0, r0 + 1, 0, NP),
                                    "rows": [{"values": values + [_link_cell(row[URL_COL])]}],
                                    "fields": "userEnteredValue,textFormatRuns"}})

    for r0, row in upd.items():
        put(r0, row)                                  # 只動 A~K，員工區不碰
    if add:
        start = DATA_START + len(codes)
        need = start + len(add)
        if ws.row_count < need:
            req.append({"appendDimension": {"sheetId": sid, "dimension": "ROWS", "length": need - ws.row_count}})
        for i, row in enumerate(add):
            put(start + i, row)
        req += _row_format_requests(sid, start, need)
        # 勾選欄要真的是 FALSE，勾選框才會出現
        req.append({"repeatCell": {"range": _rng(sid, start, need, NP, NP + NB),
                                   "cell": {"userEnteredValue": {"boolValue": False}},
                                   "fields": "userEnteredValue"}})
    if req:
        req.append({"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "ROWS",
                                                            "startIndex": 0, "endIndex": DATA_START + len(codes) + len(add)}}})
        ss.batch_update({"requests": req})
    return {"sheet_id": sid_sheet, "tab": tab, "added": len(add), "updated": len(upd)}


def sync_check_sheet(shop: str, xlsx_path: Path, prepared: list[dict], version: str,
                     when: datetime | None = None) -> dict:
    """批次入口：讀剛產出的上架檔 → 寫核對表（分頁＝產出日期 MMDD）。"""
    when = when or datetime.now()
    meta = [{"code": p["_meta"]["code"], "item_id": p["_meta"]["item_id"],
             "demand": p.get("config", {}).get("demand", "")} for p in prepared]
    rows = build_check_rows(read_upload_rows(Path(xlsx_path)), meta,
                            when.strftime("%Y-%m-%d"), version)
    # 標題檢查的提醒掛在標題格下一行（程式區，員工核「標題 OK」時一眼看到）
    warns: dict[str, list[str]] = {}
    for p in prepared:
        for w in (p.get("ai_content") or {}).get("title_warnings") or []:
            warns.setdefault(str(p["_meta"]["code"]), []).append(w)
    ti = PROG_HEADERS.index("蝦皮標題")
    for r in rows:
        if warns.get(r[CODE_COL]):
            r[ti] = r[ti] + "\n" + "\n".join(f"⚠️ {w}" for w in dict.fromkeys(warns[r[CODE_COL]]))
    res = write_check_sheet(shop, rows, when.strftime("%m%d"))
    logger.info(f"上架核對表：分頁「{res['tab']}」新增 {res['added']} 支、更新 {res['updated']} 支")
    return res
