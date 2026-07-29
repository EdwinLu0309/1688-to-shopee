/**
 * 【Lady】商品主檔 — 綁定 Apps Script（選單 + onEdit 自動記錄）
 *
 * 由 nail_master/Code.gs 改成 Lady 版：
 *   - 名稱【Nail】→【Lady】；分級標籤 #N_* → #LM_*（無品牌維度）。
 *   - 資料夾/檔案 ID 是 Nail 的 → 下面 CONFIG 標 ★TODO 的請 Edwin 換成 Lady 的，
 *     或先留空（留空時對應選單動作會提示未設定，不會誤寫到 Nail 的夾子）。
 *
 * 安裝：Lady 副本 → 擴充功能 → Apps Script → 貼上 → 儲存 → 重整試算表，
 *       上方出現「🚀 主檔動作」。onEdit 儲存即生效。
 *
 * 2026-07-27 併入「⑤ 同步蝦皮處理狀態」：把「蝦皮處理狀態」分頁依商品表以商品編號
 *   為 key 重建（新增/刪除自動對上，手填的進度文字不錯位）。
 */

// ───────── CONFIG ─────────
var TZ = "Asia/Taipei";
var OBS_DAYS_CELL = "設定!B6";
var AMOUNT_SHEET_ID = "1B2WwAhJb84Ykc5tKIIYHr419HAd66ZSSA5dQBQJsDGo";  // 【Lady】2-1 進貨金額記錄
var BACKUP_ORDER_FOLDER_ID = "19jNcLpSK1kBAgdx2wlAmihe3v8mHQynU";  // Lady 訂單完成備份夾
var ORDERLIST_FOLDER_ID    = "1W4FUSII9SKJn7ALkzhEQ59_o-C8iw26_";  // Lady 商品訂貨(到貨核對)夾
var EMP_SHEET_ID = "";            // Lady 員工售價表（跳過，留空）

var WATCH = { "商品表": ["蝦皮售價"], "SKU表": ["安全存量", "進項成本"] };
var KEY_HEADER = { "商品表": "商品編號", "SKU表": "品號" };


// ───────── 選單 ─────────
function onOpen() {
  SpreadsheetApp.getUi().createMenu("🚀 主檔動作")
    .addItem("🚀 全執行（①②③④）", "runAllActions")
    .addSeparator()
    .addItem("① 畫紅線分區（目前分頁）", "applyRedBordersByNamePrefix")
    .addItem("② 訂單完成備份 → 共用硬碟", "backupOrderSheet")
    .addItem("③ 備份 Order_List → 共用硬碟", "exportOrderList")
    .addItem("④ 廠商訂單 → 進貨金額記錄", "snapshotToAmountRecord")
    .addItem("⑤ 同步蝦皮處理狀態（依商品表）", "syncStatusTab")
    .addSeparator()
    .addItem("（選配）推送售價 → 員工表", "pushToEmployeeSheet")
    .addToUi();
}

// ───────── 🚀 全執行：依序跑 ①②③④，最後一次總結 ─────────
function runAllActions() {
  var ui = SpreadsheetApp.getUi();
  if (ui.alert("全執行", "將依序執行 ①畫紅線 ②訂單完成備份 ③商品訂貨備份 ④金額記錄，確定？",
               ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
  var res = [];
  var steps = [["① 畫紅線", applyRedBordersByNamePrefix],
               ["② 訂單完成備份", backupOrderSheet],
               ["③ 商品訂貨備份", exportOrderList],
               ["④ 金額記錄", snapshotToAmountRecord]];
  steps.forEach(function (s) {
    try { s[1](true); res.push("✅ " + s[0]); }
    catch (e) { res.push("❌ " + s[0] + "：" + e.message); }
  });
  ui.alert("🚀 全執行完成\n\n" + res.join("\n"));
}


// ───────── ① 畫紅線分區（品名前 6 字變化畫粗紅線）─────────
function applyRedBordersByNamePrefix(silent) {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var lastRow = sh.getLastRow(), lastCol = sh.getLastColumn();
  if (lastRow <= 1) return;
  var head = sh.getRange(1, 1, 1, lastCol).getValues()[0];
  var col = head.indexOf("品名") + 1;
  if (col === 0) { if (silent) return; SpreadsheetApp.getUi().alert("這個分頁沒有「品名」欄"); return; }
  sh.getRange(1, 1, lastRow, lastCol)
    .setBorder(true, true, true, true, true, true, "#000000", SpreadsheetApp.BorderStyle.SOLID);
  var vals = sh.getRange(1, col, lastRow, 1).getValues();
  for (var i = 1; i < vals.length; i++) {
    var cur = String(vals[i][0] || ""), prev = String(vals[i - 1][0] || "");
    if (cur.substring(0, 6) !== prev.substring(0, 6) && cur.trim() !== "") {
      sh.getRange(i + 1, 1, 1, lastCol)
        .setBorder(true, null, null, null, null, null, "#FF0000", SpreadsheetApp.BorderStyle.SOLID_THICK);
    }
  }
  SpreadsheetApp.getActiveSpreadsheet().toast("✅ 已畫分區線", "", 3);
}


// ───────── ② 訂單完成備份 → 共用硬碟（訂貨表 + 訂貨彙總，轉純值）─────────
function backupOrderSheet(silent) {
  var ui = SpreadsheetApp.getUi(), ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!BACKUP_ORDER_FOLDER_ID) { if (silent) throw new Error("未設定 BACKUP_ORDER_FOLDER_ID"); ui.alert("尚未設定 Lady 訂貨備份夾 ID"); return; }
  var tag = Utilities.formatDate(new Date(), TZ, "yyyyMMdd");
  try {
    var newSs = SpreadsheetApp.create("【Lady】訂單完成備份_" + tag);
    DriveApp.getFileById(newSs.getId()).moveTo(DriveApp.getFolderById(BACKUP_ORDER_FOLDER_ID));
    ["訂貨表", "訂貨彙總"].forEach(function (name) {
      var src = ss.getSheetByName(name);
      if (!src) return;
      var tmp = src.copyTo(ss);
      var rng = tmp.getDataRange(); rng.copyTo(rng, { contentsOnly: true });
      tmp.copyTo(newSs).setName(name);
      ss.deleteSheet(tmp);
    });
    var def = newSs.getSheetByName("工作表1") || newSs.getSheetByName("Sheet1");
    if (def && newSs.getSheets().length > 1) newSs.deleteSheet(def);
    if (!silent) ui.alert("✅ 訂單完成備份_" + tag + "（訂貨表 + 訂貨彙總）已存到共用硬碟。");
  } catch (e) { if (silent) throw e; ui.alert("❌ 備份失敗：" + e.message); }
}


// ───────── ③ 備份 Order_List → 共用硬碟（到貨核對）─────────
function exportOrderList(silent) {
  var ui = SpreadsheetApp.getUi(), ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ORDERLIST_FOLDER_ID) { if (silent) throw new Error("未設定 ORDERLIST_FOLDER_ID"); ui.alert("尚未設定 Lady 到貨核對夾 ID"); return; }
  var src = ss.getSheetByName("Order_List");
  if (!src) { if (silent) throw new Error("找不到 Order_List"); ui.alert("找不到 Order_List"); return; }
  var tag = Utilities.formatDate(new Date(), TZ, "yyyyMMdd");
  try {
    var newSs = SpreadsheetApp.create("【Lady】商品訂貨_" + tag);
    DriveApp.getFileById(newSs.getId()).moveTo(DriveApp.getFolderById(ORDERLIST_FOLDER_ID));
    var tmp = src.copyTo(ss);
    var rng = tmp.getDataRange(); rng.setValues(rng.getValues());
    tmp.copyTo(newSs).setName("到貨核對");
    ss.deleteSheet(tmp);
    var def = newSs.getSheetByName("工作表1") || newSs.getSheetByName("Sheet1");
    if (def && newSs.getSheets().length > 1) newSs.deleteSheet(def);
    if (!silent) ui.alert("✅ 商品訂貨_" + tag + " 已匯出到共用硬碟。");
  } catch (e) { if (silent) throw e; ui.alert("❌ 匯出失敗：" + e.message); }
}


// ───────── ④ 廠商訂單 → 進貨金額記錄 ─────────
function snapshotToAmountRecord(silent) {
  var ui = SpreadsheetApp.getUi(), ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!AMOUNT_SHEET_ID) { if (silent) throw new Error("未設定 AMOUNT_SHEET_ID"); ui.alert("尚未設定 Lady 進貨金額記錄表 ID（沒有此表可略過此動作）"); return; }
  var fo = ss.getSheetByName("廠商訂單");
  if (!fo) { if (silent) throw new Error("找不到 廠商訂單"); ui.alert("找不到 廠商訂單"); return; }
  var d = fo.getDataRange().getValues(), h = d[0];
  var iCode = h.indexOf("商品編號"), iName = h.indexOf("商品名稱"),
      iRMB = h.indexOf("正式RMB"), iVend = h.indexOf("廠商名稱");
  if (iCode < 0 || iRMB < 0) { if (silent) throw new Error("廠商訂單缺欄"); ui.alert("廠商訂單找不到 商品編號／正式RMB 欄"); return; }
  var rows = [];
  for (var r = 1; r < d.length; r++) {
    var code = String(d[r][iCode]).trim();
    if (!code || code.indexOf("尚無") >= 0) continue;
    rows.push([code, d[r][iName], d[r][iVend], d[r][iRMB]]);
  }
  if (!rows.length) { if (silent) throw new Error("廠商訂單無資料"); ui.alert("廠商訂單目前無資料（先在訂貨表填正式訂貨數）"); return; }
  rows.sort(function (a, b) { return String(a[2]) < String(b[2]) ? -1 : String(a[2]) > String(b[2]) ? 1 : 0; });

  var tgt = SpreadsheetApp.openById(AMOUNT_SHEET_ID);
  var tag = Utilities.formatDate(new Date(), TZ, "MMdd");
  var ex = tgt.getSheetByName(tag);
  if (ex) {
    if (!silent && ui.alert("已有分頁「" + tag + "」，覆蓋？", ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
    tgt.deleteSheet(ex);
  }
  var ns = tgt.insertSheet(tag);
  var rate = Number(ss.getRange("設定!B2").getValue()) || 4.9;
  var HDR = ["商品編號", "商品名稱", "訂單金額", "訂單金額合計", "廠商名稱", "付款平台訂單編號",
             "訂單費用", "總金額", "運費", "核對", "TW", "付款狀態", "備註"];
  var NC = HDR.length;
  var out = [["匯率", "", rate].concat(blanks_(NC - 3)),
             ["總額", "", "=SUM(K5:K)"].concat(blanks_(NC - 3)),
             ["", "", ""].concat(blanks_(NC - 3)),
             HDR];
  var merges = [];
  var ri = 5, i = 0;
  while (i < rows.length) {
    var j = i;
    while (j < rows.length && String(rows[j][2]) === String(rows[i][2])) j++;
    var n = j - i, first = ri, lastRow = ri + n - 1;
    for (var g = i; g < j; g++) {
      if (g === i) {
        out.push([rows[g][0], rows[g][1], rows[g][3],
          "=SUM(C" + first + ":C" + lastRow + ")", rows[g][2],
          "", "", "", "", "", "=IF($H" + first + "=\"\",\"\",$H" + first + "*$C$1)", "", ""]);
      } else {
        out.push([rows[g][0], rows[g][1], rows[g][3]].concat(blanks_(NC - 3)));
      }
      ri++;
    }
    if (n > 1) merges.push({ row: first, n: n });
    i = j;
  }
  var last = out.length;
  ns.getRange(1, 1, last, NC).setValues(out);
  merges.forEach(function (m) { ns.getRange(m.row, 4, m.n, NC - 3).mergeVertically(); });
  var all = ns.getRange(1, 1, last, NC);
  all.setFontFamily("Arial").setFontSize(14).setVerticalAlignment("middle");
  all.setBorder(true, true, true, true, true, true, "#000000", SpreadsheetApp.BorderStyle.SOLID);
  ns.getRange(4, 1, 1, NC).setBackground("#d9ead3").setFontWeight("bold").setHorizontalAlignment("center");
  ns.getRange(1, 1, 3, 3).setBackground("#fce5cd");
  ns.setFrozenRows(4);
  tgt.setActiveSheet(ns);
  if (!silent) ui.alert("✅ 已建立「" + tag + "」，" + rows.length + " 個商品編號。");
}

function blanks_(n) { var a = []; for (var i = 0; i < n; i++) a.push(""); return a; }


// ───────── ⑤ 同步蝦皮處理狀態（依商品表，以商品編號為 key 重建）─────────
// 解決：以前用 mapping 公式，商品表新增/刪除列 → 前面編號位移、後面手填不跟著 → 對錯行。
// 本函式以商品編號為 key 重建：手填欄（蝦皮ID/標題/詳情/圖片/選項圖/影片/優化/備註）原封帶回，
// 新編號→空白、消失的→移除。B/C（分類/品名）是 MAP 公式跟著 A 欄 live，不在此處理。
function syncStatusTab(silent) {
  var ui = SpreadsheetApp.getUi();
  var STATUS_TAB = "蝦皮處理狀態";
  var SRC_TAB = "商品表";
  var MANUAL_START = 4;               // D 欄起（蝦皮ID）
  var MANUAL_END = 14;                // 到 N 欄（要產）——含 L 蝦皮折扣/M 資產包狀態/N 要產
  var WANT_COL = 14;                  // N 欄＝要產（checkbox，重建後重補勾選框）
  var WIDTH = MANUAL_END - MANUAL_START + 1;   // 11 欄（D:N）
  var EMPTY_MANUAL = ["", "", "", "", "", "", "", "", "", "", ""];  // 預設空白（新編號）

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var src = ss.getSheetByName(SRC_TAB);
  var dst = ss.getSheetByName(STATUS_TAB);
  if (!src || !dst) {
    if (silent) throw new Error("找不到「" + SRC_TAB + "」或「" + STATUS_TAB + "」分頁");
    ui.alert("找不到「" + SRC_TAB + "」或「" + STATUS_TAB + "」分頁"); return;
  }

  // 1) 商品表 唯一編號（依出現順序，忽略空白與重複）
  var codes = [], seen = {};
  var srcLast = src.getLastRow();
  if (srcLast >= 2) {
    var col = src.getRange(2, 1, srcLast - 1, 1).getValues();
    for (var i = 0; i < col.length; i++) {
      var c = String(col[i][0]).trim();
      if (c && !seen[c]) { seen[c] = true; codes.push(c); }
    }
  }

  // 2) 既有手填/狀態資料 → 以編號為 key 存起來（D..N）
  var store = {};
  var dstLast = dst.getLastRow();
  if (dstLast >= 2) {
    var keys = dst.getRange(2, 1, dstLast - 1, 1).getValues();
    var man = dst.getRange(2, MANUAL_START, dstLast - 1, WIDTH).getValues();
    for (var k = 0; k < keys.length; k++) {
      var kc = String(keys[k][0]).trim();
      if (kc) store[kc] = man[k];
    }
  }

  // 3) 依商品表順序重建（手填/狀態以 key 帶回，永不錯位）
  var aVals = [], mVals = [];
  codes.forEach(function (code) {
    aVals.push([code]);
    mVals.push(store[code] ? store[code] : EMPTY_MANUAL.slice());
  });

  // 4) 先清舊資料區（A 與 D:N，B/C 是 MAP 公式不動），再寫新的
  var clearRows = Math.max(dstLast - 1, codes.length) + 5;
  if (clearRows > 0) {
    dst.getRange(2, 1, clearRows, 1).clearContent();                  // A
    dst.getRange(2, MANUAL_START, clearRows, WIDTH).clearContent();   // D:N
  }
  if (codes.length) {
    dst.getRange(2, 1, codes.length, 1).setValues(aVals);                    // A
    dst.getRange(2, MANUAL_START, codes.length, WIDTH).setValues(mVals);     // D:N
    // N（要產）重補勾選框：空字串→未勾、帶回的 true/false 維持（新編號預設未勾）
    dst.getRange(2, WANT_COL, codes.length, 1).insertCheckboxes();
  }
  if (!silent) ss.toast("同步完成：" + codes.length + " 個商品", "⑤ 蝦皮處理狀態", 5);
}


// ───────── （選配）推送售價 → 員工表 ─────────
function pushToEmployeeSheet() {
  var ui = SpreadsheetApp.getUi();
  if (!EMP_SHEET_ID) { ui.alert("尚未設定 EMP_SHEET_ID（員工售價表）"); return; }
  var src = SpreadsheetApp.getActiveSpreadsheet().getSheetByName("商品表");
  var data = src.getDataRange().getValues(), header = data[0];
  var iCode = header.indexOf("商品編號"), iName = header.indexOf("品名"), iPrice = header.indexOf("蝦皮售價");
  var out = [["商品編號", "品名", "蝦皮售價"]];
  for (var i = 1; i < data.length; i++) {
    if (!String(data[i][iCode]).trim()) continue;
    out.push([data[i][iCode], data[i][iName], data[i][iPrice]]);
  }
  var dst = SpreadsheetApp.openById(EMP_SHEET_ID).getSheets()[0];
  dst.clearContents();
  dst.getRange(1, 1, out.length, out[0].length).setValues(out);
  ui.alert("✅ 已推送 " + (out.length - 1) + " 筆售價到員工表。");
}


// ───────── onEdit：變更Log + 價格Log（自動）─────────
function onEdit(e) {
  try {
    if (!e || !e.range) return;
    var sh = e.range.getSheet(), name = sh.getName(), fields = WATCH[name];
    if (!fields) return;
    if (e.range.getNumRows() > 1 || e.range.getNumColumns() > 1) return;
    var row = e.range.getRow(); if (row < 2) return;
    var header = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
    var field = String(header[e.range.getColumn() - 1] || "").trim();
    if (fields.indexOf(field) < 0) return;
    var keyIdx = header.indexOf(KEY_HEADER[name]);
    var key = sh.getRange(row, (keyIdx >= 0 ? keyIdx + 1 : 1)).getValue();
    var oldV = (e.oldValue === undefined) ? "" : e.oldValue;
    var newV = (e.value === undefined) ? "" : e.value;
    var ts = Utilities.formatDate(new Date(), TZ, "yyyy-MM-dd HH:mm:ss");
    appendRow_("變更Log", [ts, name, key, field, oldV, newV]);
    if (name === "商品表" && field === "蝦皮售價") {
      var obs = Number(e.source.getRange(OBS_DAYS_CELL).getValue()) || 30;
      var eff = Utilities.formatDate(new Date(), TZ, "yyyy-MM-dd");
      var chk = Utilities.formatDate(new Date(Date.now() + obs * 86400000), TZ, "yyyy-MM-dd");
      appendRow_("價格Log", [key, oldV, newV, eff, "", "", chk, "", ""]);
    }
  } catch (err) {}
}

function appendRow_(tab, values) {
  var ws = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(tab);
  if (ws) ws.appendRow(values);
}
