/**
 * 【Nail】商品主檔 — 綁定 Apps Script（選單 4 按鈕 + onEdit 自動記錄）
 *
 * 安裝：新主檔 → 擴充功能 → Apps Script → 貼上 → 儲存 → 重整試算表，
 *       上方出現「🚀 主檔動作」。onEdit 儲存即生效。
 * ★ 先確認 CONFIG 的資料夾 ID / 填 EMP_SHEET_ID。
 *
 * 2026-07-27 併入「⑤ 同步蝦皮處理狀態」：把「蝦皮處理狀態」分頁依商品表以商品編號
 *   為 key 重建（新增/刪除自動對上，手填進度文字不錯位）。
 * 2026-07-29 ⑤ 擴充：保留區從 D:K 擴到 D:N（多帶 L 蝦皮折扣/M 資產包狀態/N 要產）——
 *   要產/資產包狀態已從商品表搬到「蝦皮處理狀態」當資產包程式(asset_sync)的開關，
 *   重建時必須跟著 A 欄以編號對位，否則勾選會錯位到別的商品。N 重補勾選框。
 */

// ───────── CONFIG ─────────
var TZ = "Asia/Taipei";
var OBS_DAYS_CELL = "設定!B6";
var AMOUNT_SHEET_ID = "1ctZ4tvp6MpW5VXTODwtzAMjjTWD3nqGlyZGbISoTkNE"; // 2-2 進貨金額記錄
var BACKUP_ORDER_FOLDER_ID = "1NccO0TqNdNMCz7B5yIHkoPEjojS_OE3O";      // 訂貨表備份夾（沿用舊，請確認）
var ORDERLIST_FOLDER_ID    = "1RXHbIUOI0NGEb8D054hd7ENP2J-QqxxH";      // 到貨核對夾（沿用舊，請確認）
var EMP_SHEET_ID = "";                                                 // TODO 員工售價表（選配）

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
    .addItem("⑤ 同步蝦皮處理狀態", "syncStatusTab")
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
  var tag = Utilities.formatDate(new Date(), TZ, "yyyyMMdd");
  try {
    var newSs = SpreadsheetApp.create("【Nail】訂單完成備份_" + tag);
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
  var src = ss.getSheetByName("Order_List");
  if (!src) { if (silent) throw new Error("找不到 Order_List"); ui.alert("找不到 Order_List"); return; }
  var tag = Utilities.formatDate(new Date(), TZ, "yyyyMMdd");
  try {
    var newSs = SpreadsheetApp.create("【Nail】商品訂貨_" + tag);
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


// ───────── ④ 廠商訂單 → 進貨金額記錄（一列一商品編號，按廠商排序）─────────
function snapshotToAmountRecord(silent) {
  var ui = SpreadsheetApp.getUi(), ss = SpreadsheetApp.getActiveSpreadsheet();
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
    if (!silent && ui.alert("2-2 已有分頁「" + tag + "」，覆蓋？", ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
    tgt.deleteSheet(ex);
  }
  var ns = tgt.insertSheet(tag);
  var rate = Number(ss.getRange("設定!B2").getValue()) || 4.9;
  // 新欄序（Edwin 2026-07-14 調整：廠商名稱+付款平台訂單編號移到最前，好核對）：
  // A廠商名稱 B付款平台訂單編號 C商品編號 D商品名稱 E訂單金額
  // F訂單金額合計 G訂單費用 H總金額 I運費 J核對 K TW L付款狀態 M備註
  // 訂單層(A,B,F~M)每個訂單垂直合併；C~E 為逐商品編號列。上方三列：標籤在A、數值在B。
  var HDR = ["廠商名稱", "付款平台訂單編號", "商品編號", "商品名稱", "訂單金額",
             "訂單金額合計", "訂單費用", "總金額", "運費", "核對", "TW", "付款狀態", "備註"];
  var NC = HDR.length;                                  // 13 欄
  var out = [["匯率", rate].concat(blanks_(NC - 2)),                        // B1=匯率
             ["總額", "=SUM(K5:K)"].concat(blanks_(NC - 2)),                // B2=台幣總額(TW=K)
             ["1688_DB 對應版本", "='1688_DB'!B2"].concat(blanks_(NC - 2)), // B3=DB版本
             HDR];
  var merges = [];                                       // 每個多品訂單要垂直合併的 {row,n}
  var ri = 5;
  var i = 0;
  while (i < rows.length) {
    var j = i;
    while (j < rows.length && String(rows[j][2]) === String(rows[i][2])) j++;  // 同廠商=同訂單
    var n = j - i, first = ri, lastRow = ri + n - 1;
    for (var g = i; g < j; g++) {
      if (g === i) {  // 群組第一列：填訂單層公式(A,B,F~M) + 逐品(C,D,E)；其餘列僅 C~E
        out.push([
          rows[g][2],                                                     // A 廠商名稱
          "=IFERROR(XLOOKUP($A" + first + ",'1688_DB'!$D:$D,'1688_DB'!$A:$A,\"\"),\"\")",                 // B 訂單編號←廠商
          rows[g][0], rows[g][1], rows[g][3],                             // C商品編號 D商品名稱 E訂單金額
          "=SUM(E" + first + ":E" + lastRow + ")",                        // F 訂單金額合計
          "=IF($B" + first + "=\"\",\"\",H" + first + "-I" + first + ")",                                  // G 訂單費用=總金額-運費
          "=IFERROR(IF($B" + first + "<>\"\",XLOOKUP($B" + first + ",'1688_DB'!$A:$A,'1688_DB'!$I:$I,\"\"),\"\"),\"\")", // H 總金額(实付款)
          "=IFERROR(IF($B" + first + "<>\"\",XLOOKUP($B" + first + ",'1688_DB'!$A:$A,'1688_DB'!$G:$G,\"\"),\"\"),\"\")", // I 運費
          "=IF(AND($F" + first + "<>\"\",$F" + first + "<>0,$G" + first + "<>\"\",$G" + first + "<=$F" + first + "),\"O\",\"\")", // J 核對: 訂單費用≤合計
          "=IF($H" + first + "=\"\",\"\",$H" + first + "*$B$1)",                                           // K TW=總金額×匯率
          "=IFERROR(IF($B" + first + "<>\"\",XLOOKUP($B" + first + ",'1688_DB'!$A:$A,'1688_DB'!$L:$L,\"\"),\"\"),\"\")", // L 付款狀態
          ""                                                              // M 備註
        ]);
      } else {
        out.push(["", "", rows[g][0], rows[g][1], rows[g][3]].concat(blanks_(NC - 5)));
      }
      ri++;
    }
    if (n > 1) merges.push({ row: first, n: n });
    i = j;
  }
  var last = out.length;
  ns.getRange(1, 1, last, NC).setValues(out);
  // 訂單層垂直合併：A~B(廠商/訂單編號) 與 F~M(金額欄)；C~E 逐商品不合併
  merges.forEach(function (m) {
    ns.getRange(m.row, 1, m.n, 2).mergeVertically();        // A~B
    ns.getRange(m.row, 6, m.n, NC - 5).mergeVertically();   // F~M
  });
  // 版面
  var all = ns.getRange(1, 1, last, NC);
  all.setFontFamily("Arial").setFontSize(14).setVerticalAlignment("middle");
  all.setBorder(true, true, true, true, true, true, "#000000", SpreadsheetApp.BorderStyle.SOLID);
  ns.getRange(4, 1, 1, NC).setBackground("#d9ead3").setFontWeight("bold").setHorizontalAlignment("center");
  ns.getRange(1, 1, 3, 2).setBackground("#fce5cd");
  ns.getRange(5, 12, Math.max(rows.length, 1), 1).setNumberFormat("yyyy/m/d");  // L 付款狀態=付款日期
   // J 欄核對=「O」→ 綠底（一眼看出已對上的訂單）
  var jRange = ns.getRange(5, 10, Math.max(rows.length, 1), 1);                 // J 欄(第10欄)資料區
  var oRule = SpreadsheetApp.newConditionalFormatRule()
    .whenTextEqualTo("O").setBackground("#b6d7a8").setFontColor("#274e13")
    .setRanges([jRange]).build();
  var cfRules = ns.getConditionalFormatRules();
  cfRules.push(oRule);
  ns.setConditionalFormatRules(cfRules);
  ns.setFrozenRows(4);
  tgt.setActiveSheet(ns);
  if (!silent) ui.alert("✅ 已建立「" + tag + "」，" + rows.length + " 個商品編號。\n" +
           "同廠商(同訂單)已垂直合併：F=訂單金額合計，核對用「訂單費用 ≤ 合計」比對；B2=台幣總額。");
}

function blanks_(n) { var a = []; for (var i = 0; i < n; i++) a.push(""); return a; }


// ───────── ⑤ 同步蝦皮處理狀態（依商品表，以商品編號為 key 重建）─────────
// 手填/狀態欄（D:N＝蝦皮ID/標題/詳情/圖片/選項圖/影片/優化/備註 + 蝦皮折扣/資產包狀態/要產）
// 以編號為 key 帶回，新編號補空白、消失的移除，永不錯位。B/C（分類/品名）是 MAP 公式跟著 A 欄 live。
// ※ 2026-07-29：L:N（蝦皮折扣/資產包狀態/要產）也按編號帶回——要產/資產包狀態是資產包程式
//   (asset_sync) 的開關，重建時必須跟著 A 欄以編號對位，否則勾選會錯位到別的商品。N 重補勾選框。
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
