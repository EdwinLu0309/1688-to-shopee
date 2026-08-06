/**
 * 【Nail】2-1 進貨金額記錄 — 綁定 Apps Script（2-1 自己的功能）
 * 安裝：開 2-1 → 擴充功能 → Apps Script → 貼上 → 儲存 → 重整，出現「🚀 金額核對」選單。
 * 責任分界：1-1 到「產出 2-1 金額分頁」為止；2-1 核對完由本腳本傳到 2-2 做收尾。
 *
 * 2026-08-06 修「一廠商多訂單」：2-1 的 B 付款平台訂單編號現在是 TEXTJOIN 出來的多筆字串
 *   （"O1, O2, O3"），本腳本改成「拆開每個訂單編號、各自一列、各自 XLOOKUP 運送單號」，到 2-2
 *   才抓得到每筆訂單的運送單號（原本把整串當一個訂單去查 → 查不到、只記到其中一筆或空）。
 *   每組列數 = max(商品數, 訂單數)：商品(A/B)、訂單(D)/運送單號(E)各自逐列排，C 廠商整組合併。
 */
var TZ = "Asia/Taipei";
var ARRIVAL_SHEET_ID = "1Ojmd8-2VtX1qloCP5xmrncNRlQajhHuMgtXO-VffQ_A"; // 2-2 商品到貨記錄
var SKIP_TABS = { "1688_DB": 1, "🔄刷新控制": 1 };

function onOpen() {
  SpreadsheetApp.getUi().createMenu("🚀 金額核對")
    .addItem("① 核對完 → 傳到 2-2 到貨記錄", "transferToArrival")
    .addToUi();
}

// ① 2-1 核對完 → 傳到 2-2：讀目前開著的核對分頁(A廠商 B訂單編號 C商品編號 D商品名稱，第5列起，
// 廠商/訂單編號合併往下補)，傳到 2-2 同名分頁。2-2 欄序 A商品編號|B商品名稱|C廠商|D訂單編號|E運送單號|…
// ★ 一廠商多訂單：B(訂單編號)是 TEXTJOIN 多筆字串 → 拆開，每個訂單編號各一列、各自帶運送單號+物流公式。
function transferToArrival() {
  var ui = SpreadsheetApp.getUi();
  var sh = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
  var tag = sh.getName();
  if (SKIP_TABS[tag]) { ui.alert("請先切到要傳送的「日期核對分頁」（例如 0713）再按。目前在「" + tag + "」。"); return; }

  var n1 = Math.max(sh.getLastRow() - 4, 0);
  if (!n1) { ui.alert("「" + tag + "」第5列起沒有資料。"); return; }
  var v = sh.getRange(5, 1, n1, 4).getValues();   // A廠商 B訂單編號 C商品編號 D商品名稱
  var items = [], lastVend = "", lastOno = "";
  for (var i = 0; i < v.length; i++) {
    var vend = String(v[i][0]).trim(), ono = String(v[i][1]).trim(),
        code = String(v[i][2]).trim(), name = v[i][3];
    if (vend) { lastVend = vend; lastOno = ono; }  // 廠商/訂單編號在群組首列，往下補
    if (!code) continue;
    items.push({ code: code, name: name, vend: lastVend, ono: lastOno });
  }
  if (!items.length) { ui.alert("「" + tag + "」沒有商品編號。"); return; }

  var tgt = SpreadsheetApp.openById(ARRIVAL_SHEET_ID);
  var ex = tgt.getSheetByName(tag);
  if (ex) { if (ui.alert("2-2 已有分頁「" + tag + "」，覆蓋？", ui.ButtonSet.YES_NO) !== ui.Button.YES) return; tgt.deleteSheet(ex); }
  var ns = tgt.insertSheet(tag);

  var HDR = ["商品編號", "商品名稱", "廠商名稱", "付款平台訂單編號",
             "運送單號\n填表後2日開始確認\n沒出貨要旺信催一下", "狀態紀錄", "件數", "總重量",
             "包裹狀態", "預計到達時間", "查詢包裹現況", "實際到貨時間", "預開處理", "調整蝦皮數量",
             "到貨備註", "處理"];
  var NC = HDR.length;   // 16 欄
  ns.getRange(1, 1, 1, NC).setValues([HDR]);

  var out = [], merges = [], ri = 2, i = 0;
  while (i < items.length) {
    var j = i;
    while (j < items.length && items[j].vend === items[i].vend && items[j].ono === items[i].ono) j++;
    var prods = items.slice(i, j);
    // 訂單編號：把 TEXTJOIN 字串拆開、去重、去空
    var orders = String(items[i].ono).split(/[,，]/).map(function (s) { return s.trim(); }).filter(String);
    var uniq = [], seenO = {};
    orders.forEach(function (o) { if (!seenO[o]) { seenO[o] = 1; uniq.push(o); } });
    orders = uniq;

    var numRows = Math.max(prods.length, orders.length, 1);
    var first = ri;
    for (var r = 0; r < numRows; r++) {
      var R = ri;
      var code = r < prods.length ? prods[r].code : "";
      var name = r < prods.length ? prods[r].name : "";
      var ono  = r < orders.length ? orders[r] : "";
      var hasO = ono !== "";
      out.push([
        code, name,
        r === 0 ? items[i].vend : "",                                          // C 廠商（整組合併）
        ono,                                                                   // D 訂單編號（每筆一列）
        hasO ? "=XLOOKUP(D" + R + ",'1688_DB'!A:A,'1688_DB'!AF:AF,\"\")" : "", // E 運送單號（對該訂單）
        "",                                                                    // F 狀態紀錄
        hasO ? "=IF(E" + R + "=\"\",, COUNTIF(ARRAYFORMULA(TO_TEXT(Kkren_DB!$E:$E)), \"*\"&E" + R + "&\"*\"))" : "",                                 // G 件數
        hasO ? "=IF(E" + R + "=\"\",, SUMPRODUCT(ISNUMBER(SEARCH(E" + R + ", TO_TEXT(Kkren_DB!$E:$E))) * IFERROR(VALUE(Kkren_DB!$F:$F), 0)))" : "",   // H 總重量
        hasO ? "=IF(E" + R + "=\"\",, IFERROR(INDEX(SORT(FILTER(Kkren_DB!$B:$C, SEARCH(E" + R + ", TO_TEXT(Kkren_DB!$E:$E))), 1, FALSE), 1, 2), \"\"))" : "",           // I 包裹狀態
        hasO ? "=IF(E" + R + "=\"\",, IFERROR(INDEX(SORT(FILTER({Kkren_DB!$B:$B, Kkren_DB!$D:$D}, SEARCH(E" + R + ", TO_TEXT(Kkren_DB!$E:$E))), 1, FALSE), 1, 2), \"\"))" : "",  // J 預計到達時間
        hasO ? "=IF(E" + R + "=\"\",, IFERROR(INDEX(SORT(FILTER(Kkren_DB!$G:$G, SEARCH(E" + R + ", TO_TEXT(Kkren_DB!$E:$E))), 1, FALSE), 1, 1), \"\"))" : "",           // K 查詢包裹現況
        "", "", "", "", ""                                                     // L實際到貨 M預開 N調整蝦皮數量 O備註 P處理
      ]);
      ri++;
    }
    if (numRows > 1) merges.push({ row: first, n: numRows });
    i = j;
  }
  ns.getRange(2, 1, out.length, NC).setValues(out);
  merges.forEach(function (m) { ns.getRange(m.row, 3, m.n, 1).mergeVertically(); });   // 只合併 C 廠商

  ns.getRange(1, 1, out.length + 1, NC)
    .setFontFamily("Arial").setFontSize(14).setVerticalAlignment("middle")
    .setBorder(true, true, true, true, true, true, "#000000", SpreadsheetApp.BorderStyle.SOLID);
  ns.getRange(1, 1, 1, NC).setBackground("#d9ead3").setFontWeight("bold")
    .setHorizontalAlignment("center").setWrap(true);
  ns.setFrozenRows(1);
  tgt.setActiveSheet(ns);
  ui.alert("✅ 已把「" + tag + "」傳到 2-2 到貨記錄，" + out.length + " 列。\n" +
    "一廠商多訂單已拆成多列，每個訂單編號各自帶運送單號 → 到 2-2「🔄刷新控制」打勾更新待收貨即生效。");
}
