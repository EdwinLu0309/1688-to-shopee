/**
 * 【Nail】商品主檔 — 綁定 Apps Script（選單 4 按鈕 + onEdit 自動記錄）
 *
 * 安裝：新主檔 → 擴充功能 → Apps Script → 貼上 → 儲存 → 重整試算表，
 *       上方出現「🚀 主檔動作」。onEdit 儲存即生效。
 * ★ 先確認 CONFIG 的資料夾 ID。
 *
 * 2026-07-27 併入「⑤ 同步蝦皮處理狀態」：把「蝦皮處理狀態」分頁依商品表以商品編號
 *   為 key 重建（新增/刪除自動對上，手填進度文字不錯位）。
 * 2026-07-29 ⑤ 擴充：保留區從 D:K 擴到 D:N（多帶 L 蝦皮折扣/M 資產包狀態/N 要產）——
 *   要產/資產包狀態已從商品表搬到「蝦皮處理狀態」當資產包程式(asset_sync)的開關，
 *   重建時必須跟著 A 欄以編號對位，否則勾選會錯位到別的商品。N 重補勾選框。
 * 2026-09-10 新增「📦 新品」獨立選單：_待貼新品 → 商品表/SKU表 自動插到正確分類位置，
 *   並把訂貨表的死值欄照品號重新對齊（見檔尾）。取代人工複製貼上。
 */

// ───────── CONFIG ─────────
var TZ = "Asia/Taipei";
var OBS_DAYS_CELL = "設定!B6";
var AMOUNT_SHEET_ID = "1ctZ4tvp6MpW5VXTODwtzAMjjTWD3nqGlyZGbISoTkNE"; // 【Nail】2-1 進貨金額記錄
var BACKUP_ORDER_FOLDER_ID = "1NccO0TqNdNMCz7B5yIHkoPEjojS_OE3O";      // 訂貨表備份夾（沿用舊，請確認）
var ORDERLIST_FOLDER_ID    = "1RXHbIUOI0NGEb8D054hd7ENP2J-QqxxH";      // 到貨核對夾（沿用舊，請確認）

var WATCH = { "商品表": ["蝦皮售價"], "SKU表": ["安全存量", "進項成本"] };
var KEY_HEADER = { "商品表": "商品編號", "SKU表": "品號" };


// ───────── 選單 ─────────
function onOpen() {
  SpreadsheetApp.getUi().createMenu("🚀 主檔動作")
    .addItem("🚀 全執行（①②③④⑥）", "runAllActions")
    .addSeparator()
    .addItem("① 畫紅線分區（目前分頁）", "applyRedBordersByNamePrefix")
    .addItem("② 訂單完成備份 → 共用硬碟", "backupOrderSheet")
    .addItem("③ 備份 Order_List → 共用硬碟", "exportOrderList")
    .addItem("④ 廠商訂單 → 進貨金額記錄", "snapshotToAmountRecord")
    .addItem("⑤ 同步蝦皮處理狀態", "syncStatusTab")
    .addItem("⑥ 寫入 _在途（J 在途自動）", "writeTransit")
    .addToUi();

  // 📦 新品：獨立選單，與「🚀 主檔動作」分開（Edwin 2026-09-10 要求兩個功能分開）
  // ⚠️ 一個試算表只能有一個 onOpen —— 兩個選單都要寫在這裡面，
  //    另外開一支 onOpen 會蓋掉上面那個，五個主檔動作會整組消失。
  SpreadsheetApp.getUi().createMenu("📦 新品")
    .addItem("🔍 檢查（只看不寫）", "npCheck")
    .addSeparator()
    .addItem("✅ 貼進 1-1", "npPaste")
    .addToUi();
}

// ───────── 🚀 全執行：依序跑 ①②③④，最後一次總結 ─────────
function runAllActions() {
  var ui = SpreadsheetApp.getUi();
  if (ui.alert("全執行", "將依序執行 ①畫紅線 ②訂單完成備份 ③商品訂貨備份 ④金額記錄 ⑥寫入_在途，確定？",
               ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
  var res = [];
  var steps = [["① 畫紅線", applyRedBordersByNamePrefix],
               ["② 訂單完成備份", backupOrderSheet],
               ["③ 商品訂貨備份", exportOrderList],
               ["④ 金額記錄", snapshotToAmountRecord],
               ["⑥ 寫入 _在途", writeTransit]];
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
  if (!BACKUP_ORDER_FOLDER_ID) { if (silent) throw new Error("未設定 BACKUP_ORDER_FOLDER_ID"); ui.alert("尚未設定 Nail 訂貨備份夾 ID"); return; }
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
  if (!ORDERLIST_FOLDER_ID) { if (silent) throw new Error("未設定 ORDERLIST_FOLDER_ID"); ui.alert("尚未設定 Nail 到貨核對夾 ID"); return; }
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


// ───────── ④ 廠商訂單 → 進貨金額記錄（一列一商品編號，按廠商排序；2026-08-06 比照 Lady 改 SUMIF 多筆對帳）─────────
// 廠商層 B付款編號/H總金額/I運費 用 TEXTJOIN+FILTER / SUMIF 對「同廠商多筆訂單」全部加總（原 XLOOKUP 只抓第一筆→金額差距大）。
// 2026-08-06 頂端加：①E~I 欄位加總（第3列）②對帳筆數（1688待付款總數/核對到/未核對）＋未核對訂單編號清單，
//   對帳以 1688_DB 卖家公司名 比對本表廠商名稱，抓廠商改名/漏列的訂單讓 Edwin 手動查。
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
    if (!silent && ui.alert("2-1 已有分頁「" + tag + "」，覆蓋？", ui.ButtonSet.YES_NO) !== ui.Button.YES) return;
    tgt.deleteSheet(ex);
  }
  var ns = tgt.insertSheet(tag);
  var rate = Number(ss.getRange("設定!B2").getValue()) || 4.9;
  // 新欄序（Edwin 2026-07-14 調整：廠商名稱+付款平台訂單編號移到最前，好核對）：
  // A廠商名稱 B付款平台訂單編號 C商品編號 D商品名稱 E訂單金額
  // F訂單金額合計 G訂單費用 H總金額 I運費 J核對 K TW L付款日 M付款狀態 N備註
  // 訂單層(A,B,F~N)每個訂單垂直合併；C~E 為逐商品編號列。上方三列：標籤在A、數值在B。
  // ⚠️ 資料區要加欄一律往 N 之後加，**絕不可插在中間**：L1 放的是「對帳訖日」，
  //    全表 SUMIFS/COUNTIFS/FILTER 都引用 $L$1 當日期上界，第 1~3 列的欄位配置一位移就散了。
  var HDR = ["廠商名稱", "付款平台訂單編號", "商品編號", "商品名稱", "訂單金額",
             "訂單金額合計", "訂單費用", "總金額", "運費", "核對", "TW", "付款日", "付款狀態", "備註"];
  var NC = HDR.length;                                  // 14 欄
  // ★對帳日期區間（2026-08-09 修）：1688_DB 是「合併累加」的待付款快照（#S072 起保留舊訂單），
  //  只用廠商名 SUMIF 會把「別批還沒付款的舊單」一起灌進本分頁（實測 0808 分頁 26 列中 14 列被 7/27
  //  舊批污染、多算 ¥10,326、核對只剩 10 個 O）。故所有對帳公式都加 1688_DB!K(訂單創建時間) 區間條件。
  //  預設區間＝建表日 ±3 天（Edwin 定：不設太緊，跨夜/隔天補單都要涵蓋）；可直接改 J1/L1 兩格微調。
  //  ⚠️ 前提是兩批訂貨相隔 > 6 天（實際約每月一批）；若某天要補的批次離上一批太近，把 J1 手動縮回來。
  // ⚠️ 一定要用「當日 00:00 的 Date 物件」：1688_DB!K 是純日期(00:00)，若 J1 帶了時分
  //    （如 14:30），當天的訂單 00:00 >= 14:30 為 false 會被整批漏掉。
  var _t = new Date();
  var dFrom = new Date(_t.getFullYear(), _t.getMonth(), _t.getDate() - 3);
  var dTo   = new Date(_t.getFullYear(), _t.getMonth(), _t.getDate() + 3);
  var KRNG = "'1688_DB'!$K$4:$K", KCOL = "'1688_DB'!$K:$K";
  var INRNG = "(" + KRNG + ">=$J$1)*(" + KRNG + "<=$L$1)";            // SUMPRODUCT 用
  var KCRIT = KCOL + ",\">=\"&$J$1," + KCOL + ",\"<=\"&$L$1";        // SUMIFS/COUNTIFS 用
  var KFLT  = KRNG + ">=$J$1," + KRNG + "<=$L$1";                    // FILTER 用
  // 頂端 1~3 列：匯率/總額/DB版本 + 對帳筆數（1688待付款 vs 本表廠商）+ E~I 欄位加總
  //  對帳：以 1688_DB 卖家公司名(D) 比對本表廠商名稱(A5:A)；比不到＝廠商可能改名或未列 → 列出訂單編號手動查
  // ★交易關閉的訂單自 2026-08-14 起「保留＋標記」不再從 1688_DB 剔除（J=交易关闭、
  //  运费/实付款已由 daemon 清空）——Edwin 要在 L 欄看得到「這張單被關了」，不能默默消失。
  //  對帳筆數/未核對清單要排除它們（帳上不存在的單不算）；B 付款編號、L 狀態照樣列出。
  var NOTCL  = "('1688_DB'!$J$4:$J<>\"交易关闭\")";
  var JCRIT  = "'1688_DB'!$J:$J,\"<>交易关闭\"";
  var f_total   = "=SUMPRODUCT(('1688_DB'!$A$4:$A<>\"\")*" + INRNG + "*" + NOTCL + ")";                                             // 1688待付款總筆數（不含已關閉）
  var f_matched = "=SUMPRODUCT(('1688_DB'!$A$4:$A<>\"\")*" + INRNG + "*" + NOTCL + "*(COUNTIF($A$5:$A,'1688_DB'!$D$4:$D)>0))";        // 核對到
  var f_unmatch = "=SUMPRODUCT(('1688_DB'!$A$4:$A<>\"\")*" + INRNG + "*" + NOTCL + "*(COUNTIF($A$5:$A,'1688_DB'!$D$4:$D)=0))";        // 未核對
  var f_unlist  = "=IFERROR(TEXTJOIN(\", \",TRUE,FILTER('1688_DB'!$A$4:$A,'1688_DB'!$A$4:$A<>\"\"," + KFLT + ",'1688_DB'!$J$4:$J<>\"交易关闭\",COUNTIF($A$5:$A,'1688_DB'!$D$4:$D)=0)),\"（全部核對到 ✅）\")"; // 未核對訂單編號（不含已關閉）
  var out = [
    ["匯率", rate, "1688待付款筆數", f_total, "核對到", f_matched, "⚠️未核對", f_unmatch, "對帳起日", dFrom, "對帳訖日", dTo, ""], // 列1：匯率 + 對帳筆數 + 對帳日期區間
    ["總額", "=SUM(K5:K)", "未核對訂單編號→", f_unlist, "", "", "", "", "", "", "", "", ""],                          // 列2：台幣總額 + 未核對清單
    ["1688_DB 對應版本", "='1688_DB'!B2", "", "", "=SUM(E5:E)", "=SUM(F5:F)", "=SUM(G5:G)", "=SUM(H5:H)", "=SUM(I5:I)", "", "", "", ""], // 列3：DB版本 + E~I 加總
    HDR].map(function (r) { while (r.length < NC) r.push(""); return r; });  // 補齊到 NC 欄
  //   ↑ setValues 要求每列等長。頂端三列是手寫字面陣列，往後加欄一定會忘記補 ——
  //     這裡自動補，就不會再因為「加了一欄」而整支掛在 setValues。
  var merges = [];                                       // 每個多品訂單要垂直合併的 {row,n}
  var ri = 5;
  var i = 0;
  while (i < rows.length) {
    var j = i;
    while (j < rows.length && String(rows[j][2]) === String(rows[i][2])) j++;  // 同廠商=同訂單
    var n = j - i, first = ri, lastRow = ri + n - 1;
    for (var g = i; g < j; g++) {
      if (g === i) {  // 群組第一列：廠商層對帳(A,B,F~M，1688_DB 用 SUMIF 對廠商含多筆訂單全加總) + 逐品(C,D,E)
        out.push([
          rows[g][2],                                                         // A 廠商名稱
          "=IFERROR(TEXTJOIN(\", \",TRUE,FILTER('1688_DB'!$A$4:$A,'1688_DB'!$D$4:$D=$A" + first + "," + KFLT + ")),\"\")",  // B 付款編號（同廠商、區間內多筆全列）
          rows[g][0], rows[g][1], rows[g][3],                                 // C商品編號 D商品名稱 E訂單金額
          "=SUM(E" + first + ":E" + lastRow + ")",                            // F 訂單金額合計
          "=IF($H" + first + "=\"\",\"\",$H" + first + "-$I" + first + ")",   // G 訂單費用=總金額-運費（折後實付貨款）
          "=IF(COUNTIFS('1688_DB'!$D:$D,$A" + first + "," + KCRIT + "," + JCRIT + ")=0,\"\",SUMIFS('1688_DB'!$I:$I,'1688_DB'!$D:$D,$A" + first + "," + KCRIT + "," + JCRIT + "))", // H 總金額=Σ实付款（同廠商、區間內多筆；不含交易关闭）
          "=IF(COUNTIFS('1688_DB'!$D:$D,$A" + first + "," + KCRIT + "," + JCRIT + ")=0,\"\",SUMIFS('1688_DB'!$G:$G,'1688_DB'!$D:$D,$A" + first + "," + KCRIT + "," + JCRIT + "))", // I 運費=Σ运费（同廠商、區間內多筆；不含交易关闭）
          "=IF(AND($F" + first + "<>\"\",$F" + first + "<>0,$G" + first + "<>\"\",$G" + first + "<=$F" + first + "),\"O\",\"\")", // J 核對: 訂單費用≤合計
          "=IF($H" + first + "=\"\",\"\",$H" + first + "*$B$1)",                                           // K TW=總金額×匯率
          // L 付款日＝1688_DB!L 订单付款时间。⚠️ 不直接用 TEXTJOIN：那一定回文字，日期就死了
          //   （不能排序、不能算「付了幾天還沒出貨」）。但也不能只取第一筆——同一廠商在對帳
          //   區間內可能有多張單。折衷＝只有一張時回真日期，多張才退成 "8/14, 8/15" 文字。
          //   先濾掉還沒付款的空白，否則「1 張付了 + 1 張沒付」會被誤判成單張而抓到空格。
          "=IFERROR(LET(d,FILTER('1688_DB'!$L$4:$L,'1688_DB'!$D$4:$D=$A" + first + "," + KFLT + "),p,FILTER(d,d<>\"\"),IF(COUNT(p)=1,INDEX(p,1),TEXTJOIN(\", \",TRUE,ARRAYFORMULA(TEXT(p,\"m/d\"))))),\"\")",  // L 付款日
          "=IFERROR(TEXTJOIN(\", \",TRUE,FILTER('1688_DB'!$J$4:$J,'1688_DB'!$D$4:$D=$A" + first + "," + KFLT + ")),\"\")",  // M 付款狀態＝1688 订单状态（等待买家付款/待发货/交易成功/交易关闭…；每次刷新回填現況）
          ""                                                                  // N 備註
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
  ns.getRange(1, 3, 1, 6).setBackground("#cfe2f3");                             // C1:H1 對帳筆數區 淺藍
  ns.getRange(2, 3, 1, 2).setBackground("#cfe2f3");                             // C2:D2 未核對清單標籤
  ns.getRange(1, 9, 1, 4).setBackground("#d9d2e9");                             // I1:L1 對帳日期區間 淺紫
  ns.getRange("J1").setNumberFormat("yyyy/m/d");                                // 對帳起日
  ns.getRange("L1").setNumberFormat("yyyy/m/d");                                // 對帳訖日
  ns.getRange("B3").setNumberFormat("yyyy/m/d hh:mm");                          // DB 版本＝時間戳（否則顯示序號）
  ns.getRange(3, 5, 1, 5).setBackground("#fff2cc");                             // E3:I3 欄位加總 淺黃
  ns.getRange(5, 6, Math.max(rows.length, 1), 2).setBackground("#fff2cc");       // F:G(訂單金額合計/訂單費用) 黃底
  // ── 幣別數字格式（Edwin 2026-08-16 定案）：RMB 兩位小數、台幣不要小數 ──
  // 判準不是「看起來像錢就套」：G 訂單費用要拿來跟 F 訂單金額合計比對，兩者必須同幣別
  //（G＝H總金額−I運費，源頭是 1688 的实付款/运费）→ E~I 全是 RMB。
  // K TW 是唯一乘過匯率的欄，連同它的加總 B2 才是台幣。B1 是匯率不是金額，不可套。
  var nData = Math.max(rows.length, 1);
  ns.getRange(5, 5, nData, 5).setNumberFormat("#,##0.00");   // E~I 資料區（RMB）
  ns.getRange(3, 5, 1, 5).setNumberFormat("#,##0.00");       // E3:I3 加總（RMB）
  ns.getRange(5, 11, nData, 1).setNumberFormat("#,##0");     // K TW（台幣）
  ns.getRange("B2").setNumberFormat("#,##0");                // B2 總額（台幣）
  ns.getRange(5, 12, nData, 1).setNumberFormat("yyyy/m/d");  // L 付款日
  ns.getRange(5, 13, nData, 1).setNumberFormat("@");         // M 付款狀態＝純文字（別被當日期解析）
   // J 欄核對=「O」→ 綠底（一眼看出已對上的訂單）
  var jRange = ns.getRange(5, 10, Math.max(rows.length, 1), 1);                 // J 欄(第10欄)資料區
  var oRule = SpreadsheetApp.newConditionalFormatRule()
    .whenTextEqualTo("O").setBackground("#b6d7a8").setFontColor("#274e13")
    .setRanges([jRange]).build();
  // 有未核對訂單（H1>0）→ ⚠️未核對 與 未核對清單 變紅底，提醒手動查
  var unmatchRule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied("=$H$1>0")
    .setBackground("#f4cccc").setFontColor("#990000")
    .setRanges([ns.getRange(1, 7, 1, 2), ns.getRange(2, 3, 1, 2)]).build();     // G1:H1 + C2:D2
  // M 付款狀態四色（Edwin 2026-08-16）：顏色對應「要不要你動手」，不是對應流程順序。
  //   紅=交易关闭(要重下) 橘=待付款(要去付錢) 綠=交易成功(結案) 藍=待发货(等出貨)
  //   待收货 留白 —— 它是最大宗的正常狀態，滿頁都上色就等於沒上色。
  // ⚠️ 陣列順序＝優先權：一個廠商多張單時 M 欄是「待发货, 交易关闭」這種合併字串，
  //    兩條規則都會中、先命中的贏 → 最該被看見的排最前面，否則單被關了卻顯示藍色。
  var mRange = ns.getRange(5, 13, Math.max(rows.length, 1), 1);
  // ⚠️ 交易关闭**不可以**用「包含」判斷（2026-08-19 實例）：被關的單重下之後，同一個廠商
  //    在對帳區間內同時有舊關閉單與新單，M 欄會變成「待收货, 交易关闭」兩個狀態並存 →
  //    用「包含」那一列會永遠紅著，事情早就處理完了卻還在喊，紅色就此失去意義。
  //    改成自訂公式：**只有「這格沒有任何活單」時才紅**（活單＝待付款/待发货/待收货/交易成功）
  //    → 重下並抓到新單後自動退紅，改由新單自己的狀態上色。
  var closedRule = SpreadsheetApp.newConditionalFormatRule()
    .whenFormulaSatisfied('=AND(ISNUMBER(SEARCH("交易关闭",$M5)),NOT(ISNUMBER(SEARCH("待",$M5))),NOT(ISNUMBER(SEARCH("交易成功",$M5))))')
    .setBackground("#f4cccc").setFontColor("#990000")
    .setRanges([mRange]).build();
  var STATUS_COLORS = [
    ["待付款",   "#fce5cd", "#b45f06"],
    ["交易成功", "#d9ead3", "#38761d"],
    ["待发货",   "#cfe2f3", "#0b5394"]
  ];
  var cfRules = ns.getConditionalFormatRules();
  cfRules.push(closedRule);
  STATUS_COLORS.forEach(function (c) {
    cfRules.push(SpreadsheetApp.newConditionalFormatRule()
      .whenTextContains(c[0]).setBackground(c[1]).setFontColor(c[2])
      .setRanges([mRange]).build());
  });
  cfRules.push(oRule);
  cfRules.push(unmatchRule);
  ns.setConditionalFormatRules(cfRules);
  ns.setFrozenRows(4);
  tgt.setActiveSheet(ns);
  if (!silent) ui.alert("✅ 已建立「" + tag + "」，" + rows.length + " 個商品編號。\n" +
    "已自動帶入 1688_DB 對帳（廠商 SUMIFS、同廠商多筆訂單自動加總 B付款編號/H總金額/I運費）；核對 O＝訂單費用 ≤ 訂貨合計，綠底。\n" +
    "⚠️ 只對帳 J1~L1 區間內（預設今天±3天）建立的 1688 訂單，避免把別批未付款的舊單算進來；區間可直接改 J1/L1。");
}

function blanks_(n) { var a = []; for (var i = 0; i < n; i++) a.push(""); return a; }


// ───────── ⑤ 同步蝦皮處理狀態（依商品表，以商品編號為 key 重建）─────────
// 手填/狀態欄以商品編號為 key 帶回、新編號補空白、消失的移除，永不錯位。B/C（分類/品名）MAP 公式跟著 A 欄 live。
// ※ 手填欄範圍「自動偵測」：D 欄到表頭最後一個有標題的欄；「要產」欄（checkbox）以標題名找 → 舊版 D:N
//   或把平台欄搬到協作檔後的精簡版 D:E（資產包狀態/要產）同一支都適用、不必改常數。
//   （2026-08 Nail D~L 平台狀態欄搬到員工上架協作檔，主表只留 資產包狀態/要產＝asset_sync 開關。）
function syncStatusTab(silent) {
  var ui = SpreadsheetApp.getUi();
  var STATUS_TAB = "蝦皮處理狀態";
  var SRC_TAB = "商品表";
  var MANUAL_START = 4;               // D 欄起（B/C＝分類/品名是 MAP 公式，不算手填）
  var WANT_HEADER = "要產";           // 要產欄用「標題名」找（checkbox 欄），不寫死欄號

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var src = ss.getSheetByName(SRC_TAB);
  var dst = ss.getSheetByName(STATUS_TAB);
  if (!src || !dst) {
    if (silent) throw new Error("找不到「" + SRC_TAB + "」或「" + STATUS_TAB + "」分頁");
    ui.alert("找不到「" + SRC_TAB + "」或「" + STATUS_TAB + "」分頁"); return;
  }

  // 0) 自動偵測手填欄範圍：讀表頭 → D 欄到最後一個有標題的欄；要產欄以標題名定位
  var lastCol = dst.getLastColumn();
  var header = lastCol >= 1 ? dst.getRange(1, 1, 1, lastCol).getValues()[0] : [];
  var MANUAL_END = MANUAL_START - 1;   // 找不到手填欄時 < MANUAL_START（WIDTH=0）
  for (var h = lastCol; h >= MANUAL_START; h--) {
    if (String(header[h - 1]).trim() !== "") { MANUAL_END = h; break; }
  }
  var WIDTH = Math.max(MANUAL_END - MANUAL_START + 1, 0);
  var WANT_COL = 0;
  for (var w = MANUAL_START; w <= MANUAL_END; w++) {
    if (String(header[w - 1]).trim() === WANT_HEADER) { WANT_COL = w; break; }
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

  // 2) 既有手填/狀態資料 → 以編號為 key 存起來（D..MANUAL_END）
  var store = {};
  var dstLast = dst.getLastRow();
  if (dstLast >= 2 && WIDTH > 0) {
    var keys = dst.getRange(2, 1, dstLast - 1, 1).getValues();
    var man = dst.getRange(2, MANUAL_START, dstLast - 1, WIDTH).getValues();
    for (var k = 0; k < keys.length; k++) {
      var kc = String(keys[k][0]).trim();
      if (kc) store[kc] = man[k];
    }
  }

  // 3) 依商品表順序重建（手填/狀態以 key 帶回，永不錯位）
  var emptyMan = [];
  for (var e = 0; e < WIDTH; e++) emptyMan.push("");
  var aVals = [], mVals = [];
  codes.forEach(function (code) {
    aVals.push([code]);
    if (WIDTH > 0) mVals.push(store[code] ? store[code] : emptyMan.slice());
  });

  // 4) 先清舊資料區（A 與 D:MANUAL_END，B/C 是 MAP 公式不動），再寫新的
  var clearRows = Math.max(dstLast - 1, codes.length) + 5;
  if (clearRows > 0) {
    dst.getRange(2, 1, clearRows, 1).clearContent();                                // A
    if (WIDTH > 0) dst.getRange(2, MANUAL_START, clearRows, WIDTH).clearContent();   // D:MANUAL_END
  }
  if (codes.length) {
    dst.getRange(2, 1, codes.length, 1).setValues(aVals);                           // A
    if (WIDTH > 0) dst.getRange(2, MANUAL_START, codes.length, WIDTH).setValues(mVals);
    // 要產欄重補勾選框：空字串→未勾、帶回的 true/false 維持（新編號預設未勾）
    if (WANT_COL) dst.getRange(2, WANT_COL, codes.length, 1).insertCheckboxes();
  }
  if (!silent) ss.toast("同步完成：" + codes.length + " 個商品", "⑤ 蝦皮處理狀態", 5);
}


// ───────── onEdit：變更Log + 價格Log（自動）─────────

// ───────── ⑥ 寫入 _在途（2026-09-10 #S234）─────────
// 「🚀 全執行」按下時，把訂貨表 O>0 的列（＝這一輪要訂的）寫進機器分頁「_在途」，
// 訂貨表 J 訂購未到貨 是 SUMIF('_在途'!F 未到量) 的公式 → 從此 J 自己會對，不用人填。
// 之後每天由 1688-order 的 order.transit 用 ERP 庫存跳升自動消帳（已進量／最近進ERP日）。
// 規則：
//   · 跳過 台幣品（SKU表 G=台幣：台灣廠 2 天到貨、刻意不記在途）
//   · 跳過 #PO_Sale 預購品（不進 ERP，永遠不會跳升，記了會永遠掛在卡住清單）
//   · 跳過 S 加購狀態 為 🚫 售完／❌ 規格不符／❌ 的列（根本沒進購物車，沒訂）
//   · 同品號、未到量>0、下單日在 ±3 天內 → 視為同一輪重按，覆蓋預定量不重複加列
//   · 下單日寫真 Date（不可寫 "0910"，會變數字 910）
var TRANSIT_TAB = "_在途";
var TRANSIT_SAME_ROUND_DAYS = 3;
var TRANSIT_SKIP_STATUS = ["🚫", "❌"];      // S 加購狀態／T 核對狀態 開頭（沒進購物車＝沒訂）
var TRANSIT_SKIP_TAG = "#PO_Sale";

function writeTransit(silent) {
  var ui = SpreadsheetApp.getUi(), ss = SpreadsheetApp.getActiveSpreadsheet();
  var od = ss.getSheetByName("訂貨表"), sk = ss.getSheetByName("SKU表"), tw = ss.getSheetByName(TRANSIT_TAB);
  var fail = function (m) { if (silent) throw new Error(m); ui.alert("⑥ 寫入 _在途", m, ui.ButtonSet.OK); };
  if (!od || !sk) return fail("找不到 訂貨表／SKU表");
  if (!tw) return fail("找不到「" + TRANSIT_TAB + "」分頁（要先由 1688-order 建好，含 B 品名／G/H 公式）");

  // 訂貨表：A品號 D標籤 O正式訂貨數（按標題找，找不到退回第 15 欄）S加購狀態（第 19 欄，標題是空的）
  var ov = od.getDataRange().getValues(), oh = ov[0];
  var iO = oh.indexOf("正式訂貨數"); if (iO < 0) iO = 14;
  var iTag = oh.indexOf("標籤"); if (iTag < 0) iTag = 3;
  // ⚠️ 欄號會漂：Edwin 搬過欄位兩次（2026-09-10），照標題找；S1/T1 的標題已補上，找不到才退回固定欄
  var iS = oh.indexOf("加購狀態"); if (iS < 0) iS = 18;
  var iT = oh.indexOf("核對狀態"); if (iT < 0) iT = 19;
  // SKU表：A品號 → G幣別
  var sv = sk.getDataRange().getValues(), shd = sv[0];
  var iCur = shd.indexOf("幣別"); if (iCur < 0) iCur = 6;
  var cur = {};
  for (var s = 1; s < sv.length; s++) { var c0 = String(sv[s][0]).trim(); if (c0) cur[c0] = String(sv[s][iCur] || "").trim(); }

  var today = new Date(); today = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  var cand = [], skipped = { tw: 0, po: 0, st: 0 };
  for (var r = 1; r < ov.length; r++) {
    var raw = ov[r][0], code = String(raw).trim(); if (!code) continue;   // raw：Baby 品號是數字，寫原值才對得上 SUMIF
    var qty = Number(ov[r][iO]); if (!(qty > 0)) continue;
    if (cur[code] === "台幣") { skipped.tw++; continue; }
    if (String(ov[r][iTag] || "").indexOf(TRANSIT_SKIP_TAG) >= 0) { skipped.po++; continue; }
    var st = String(ov[r][iS] || "").trim(), tt = String(ov[r][iT] || "").trim();
    if (TRANSIT_SKIP_STATUS.some(function (p) { return st.indexOf(p) === 0 || tt.indexOf(p) === 0; })) { skipped.st++; continue; }
    cand.push([raw, qty, code]);
  }
  if (!cand.length) return fail("訂貨表沒有 O>0 的列（先填正式訂貨數）");

  // ⚠️ 欄位配置（2026-09-10 加了 B 品名之後整排右移一格，動欄位一定要回頭改這裡）：
  //    A品號 │ B品名(公式) │ C預定量 │ D下單日 │ E已進量 │ F最近進ERP日 │ G未到量(公式) │ H狀態(公式) │ I取消(下拉)
  var C_CODE = 1, C_QTY = 3, C_DATE = 4, C_GOT = 5, C_LEFT = 7;   // 1-based
  // 既有 _在途：找「同品號、未到量>0、下單日 ±3 天」的列 → 覆蓋
  var tl = lastDataRow_(tw, C_CODE);
  var tv = tl >= 2 ? tw.getRange(2, 1, tl - 1, C_LEFT).getValues() : [];   // A~G
  var open = {}, older = {};                                    // open＝±3 天同輪；older＝>3 天還在途（真再訂？還是上輪 O 沒清？）
  for (var t = 0; t < tv.length; t++) {
    var tc = String(tv[t][0]).trim(); if (!tc) continue;
    var d = tv[t][C_DATE - 1]; var f = Number(tv[t][C_LEFT - 1]) || 0;
    if (!(d instanceof Date) || !(f > 0)) continue;
    var dd = Math.abs((today - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
    if (dd <= TRANSIT_SAME_ROUND_DAYS) open[tc] = t + 2;    // sheet row
    else older[tc] = Math.round(dd);
  }
  var updates = [], appends = [], suspect = [];
  cand.forEach(function (c) {
    if (open[c[2]]) updates.push({ row: open[c[2]], qty: c[1] });
    else {
      appends.push([c[0], c[1], today, 0]);                  // 品號＋預定量/下單日/已進量0；B 品名、G/H 是 ARRAYFORMULA 自動長
      if (older[c[2]] !== undefined) suspect.push(c[2] + "（" + older[c[2]] + " 天前那批還在途）");
    }
  });
  updates.forEach(function (u) { tw.getRange(u.row, C_QTY).setValue(u.qty); });
  if (appends.length) {
    var start = lastDataRow_(tw, C_CODE) + 1;
    tw.getRange(start, C_CODE, appends.length, 1).setValues(appends.map(function (a) { return [a[0]]; }));   // A 品號（跳過 B 品名公式）
    tw.getRange(start, C_QTY, appends.length, 3).setValues(appends.map(function (a) { return a.slice(1); })); // C~E
    tw.getRange(start, C_DATE, appends.length, 1).setNumberFormat("yyyy-mm-dd");                             // D 下單日
    // ⚠️ 已進量是「件數」不是日期：它整欄曾被設成 DATE 格式，10 件顯示成 1900-01-09、
    //    77 件顯示成 1900-03-17（值是對的、未到量也算得出來，但那一欄人完全看不懂）。
    //    它就在下單日隔壁，格式很容易被整片套過去 → 每次 append 壓一次數字格式。
    //    ⚠️ 這一行必須指 E 欄（C_GOT）不是 D —— 指到 D 會把上一行的日期格式蓋掉，
    //       下單日就變成 46275 這種序號（2026-09-10 加 B 品名右移後真的踩過）。
    tw.getRange(start, C_GOT, appends.length, 1).setNumberFormat("#,##0");
  }
  var msg = "✅ _在途：新增 " + appends.length + " 列、覆蓋 " + updates.length + " 列（同輪重按）" +
            "｜跳過 台幣 " + skipped.tw + "／預購 " + skipped.po + "／售完、規格不符、未找到 " + skipped.st;
  if (suspect.length) msg += "\n\n⚠️ 這 " + suspect.length + " 個品號在 _在途 已有 >3 天的在途列——是真的再訂一批，還是上輪的 O 沒清？\n　" +
                             suspect.slice(0, 15).join("\n　") + (suspect.length > 15 ? "\n　…還有 " + (suspect.length - 15) + " 個" : "");
  if (!silent) ui.alert("⑥ 寫入 _在途", msg, ui.ButtonSet.OK);
  return msg;
}

// 以某一欄「最後一個有值的列」當資料尾（不用 getLastRow：B/G/H 的 ARRAYFORMULA 會把整欄撐到底）
function lastDataRow_(sh, col) {
  var v = sh.getRange(1, col, sh.getMaxRows(), 1).getValues();
  for (var i = v.length - 1; i >= 0; i--) if (String(v[i][0]).trim() !== "") return i + 1;
  return 1;
}


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

// ═══════════════════════════════════════════════════════════════════
// 📦 新品：_待貼新品 → 商品表 / SKU表（2026-09-10 建）
//
// 取代「人工複製貼上」。手貼有兩個風險，這支一次拿掉：
//   ① 貼到黃底欄會把錨在第 2 列的整欄陣列公式打成 #REF!
//      （商品表 F/H/I/R~U/V/W、SKU表 K/O/P）
//   ② 要自己找分類位置，不然新品全掉在表尾（＝停售區後面）
//
// ⚠️⚠️ 為什麼用「插入列」不用「排序」（2026-09-09 開測試分頁實測）：
//   · 排序整塊（含公式溢出欄）→ 陣列公式直接死掉、末列 #REF!
//   · 只排部分欄 → 沒選到的死值欄原地不動，資料靜默錯位、畫面完全正常
//   · 插入列 → 公式完好並跟著重算、死值跟著走、連靜態格式都跟著搬
//
// ⚠️⚠️ 插進 SKU 表中間會讓訂貨表的死值欄錯位（#S217 那個災難）：
//   訂貨表 A2 是 QUERY 溢出，SKU 表一多列，A~G 整片下移而 O/S/T 原地不動
//   → 插入點以下全部對錯品號，**表面完全看不出來**。
//   所以「貼進 1-1」是一組不可分割的動作：先記下品號→O/S/T，插完再照品號寫回。
//   （J 訂購未到貨 2026-09-09 起已改成公式接 _在途，不再是死值、不用管。）
// ═══════════════════════════════════════════════════════════════════

var NP_STAGING = "_待貼新品";
var NP_PRODUCT = "商品表";
var NP_SKU     = "SKU表";
var NP_ORDER   = "訂貨表";

// 「程式會填、要貼過去」的欄＝待貼分頁表頭**綠底**那些；中間的公式欄整個跳過。
//   商品表：A編號 B分類 C子分類 D品名 E成本 ┊ G售價 ┊ J特殊% K廠商 L網址
//   SKU表 ：A品號 B品名 C分類 D標籤 ┊ F成本 G幣別 H安全存量 ┊ L規格一 M規格二
// 連續的合併成一個 range 一次寫（少幾次 API，也不會誤觸公式欄）
var NP_PROD_RANGES = [[1, 5], [7, 1], [10, 3]];     // [起始欄, 欄數]：A~E / G / J~L
var NP_SKU_RANGES  = [[1, 4], [6, 3], [12, 2]];     // A~D / F~H / L~M

var NP_ORDER_DEAD = [15, 19, 20];                   // 訂貨表死值欄：O 正式訂貨數 / S 加購狀態 / T 核對狀態
var NP_DEAD_STATUS = ["停售", "出清"];              // 商品表 M 狀態：這些算「非活躍」，新品不插到它們後面


// ───────── 選單入口 ─────────
function npCheck()  { npRun_(false); }
function npPaste()  { npRun_(true); }


// ───────── 讀待貼分頁 → 兩個區塊 ─────────
function npReadStaging_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var st = ss.getSheetByName(NP_STAGING);
  if (!st) throw new Error("找不到「" + NP_STAGING + "」分頁");
  var v = st.getDataRange().getValues();
  var marks = [];
  for (var i = 0; i < v.length; i++) {
    if (String(v[i][0] || "").indexOf("■") === 0) marks.push(i);
  }
  if (marks.length < 2) throw new Error("「" + NP_STAGING + "」看不到兩個「■」區塊標記，格式不對");
  var prod = [], sku = [];
  for (var a = marks[0] + 2; a < marks[1]; a++) if (String(v[a][0] || "").trim()) prod.push(v[a]);
  for (var b = marks[1] + 2; b < v.length; b++) if (String(v[b][0] || "").trim()) sku.push(v[b]);
  return { prod: prod, sku: sku };
}


// ───────── 找插入位置 ─────────
// 商品表：同「分類(B)」的最後一列活躍商品之後。找不到就放在活躍區最末（停售區之前）。
function npProductTarget_(sh, cat) {
  var last = sh.getLastRow();
  var d = sh.getRange(2, 1, last - 1, 13).getValues();   // A~M
  var hit = 0, lastActive = 0;
  for (var i = 0; i < d.length; i++) {
    if (!String(d[i][0]).trim()) continue;
    var dead = NP_DEAD_STATUS.indexOf(String(d[i][12]).trim()) >= 0;
    if (dead) continue;
    lastActive = i + 2;
    if (String(d[i][1]).trim() === cat) hit = i + 2;
  }
  return hit || lastActive;
}

// SKU表：同「品號前 5 碼」（賣場+分類+品牌）的最後一列之後。找不到就放最末。
function npSkuTarget_(sh, prefix) {
  var last = sh.getLastRow();
  var d = sh.getRange(2, 1, last - 1, 1).getValues();
  var hit = 0;
  for (var i = 0; i < d.length; i++) {
    var c = String(d[i][0]).trim();
    if (c && c.substring(0, 5) === prefix) hit = i + 2;
  }
  return hit || last;
}


// ───────── 主流程（check=只看不寫 / paste=真的插入）─────────
function npRun_(doWrite) {
  var ui = SpreadsheetApp.getUi();
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var msg = [];
  try {
    var stage = npReadStaging_();
    if (!stage.prod.length && !stage.sku.length) { ui.alert("📦 新品", "「" + NP_STAGING + "」沒有資料。", ui.ButtonSet.OK); return; }

    var pSh = ss.getSheetByName(NP_PRODUCT), sSh = ss.getSheetByName(NP_SKU), oSh = ss.getSheetByName(NP_ORDER);
    if (!pSh || !sSh || !oSh) throw new Error("找不到 商品表／SKU表／訂貨表");

    // ── 分組（商品表照分類、SKU 表照品號前 5 碼）──
    var pGroups = {}, sGroups = {};
    stage.prod.forEach(function (r) { var k = String(r[1]).trim() || "(無分類)"; (pGroups[k] = pGroups[k] || []).push(r); });
    stage.sku.forEach(function (r) { var k = String(r[0]).trim().substring(0, 5); (sGroups[k] = sGroups[k] || []).push(r); });

    // ── 檢查 ──
    var warn = [];
    var pExist = {}, sExist = {};
    var pd = pSh.getRange(2, 1, pSh.getLastRow() - 1, 1).getValues();
    for (var i = 0; i < pd.length; i++) { var c = String(pd[i][0]).trim(); if (c) pExist[c] = (pExist[c] || 0) + 1; }
    var sd = sSh.getRange(2, 1, sSh.getLastRow() - 1, 1).getValues();
    for (var j = 0; j < sd.length; j++) { var q = String(sd[j][0]).trim(); if (q) sExist[q] = true; }

    stage.sku.forEach(function (r) {
      var code = String(r[0]).trim();
      if (sExist[code]) warn.push("❌ 品號已存在於 SKU表：" + code);
      if (code.length !== 15) warn.push("❌ 品號不是 15 碼：" + code);
      if (!String(r[5]).trim()) warn.push("⚠️ 進項成本空白：" + code);
    });
    stage.prod.forEach(function (r) {
      var code = String(r[0]).trim();
      if (!String(r[1]).trim()) warn.push("⚠️ 分類推導不出來：" + code);
      if (!String(r[6]).trim()) warn.push("⚠️ 蝦皮售價空白：" + code);
      if (!String(r[4]).trim()) warn.push("⚠️ 成本空白：" + code);
    });
    // 品號重複（待貼分頁自己內部）
    var seen = {};
    stage.sku.forEach(function (r) {
      var c = String(r[0]).trim();
      if (seen[c]) warn.push("❌ 待貼分頁裡品號重複：" + c);
      seen[c] = true;
    });

    // ── 插入計畫 ──
    var plan = [];
    for (var cat in pGroups) plan.push({ what: "商品表", key: cat, n: pGroups[cat].length, at: npProductTarget_(pSh, cat) });
    for (var pre in sGroups) plan.push({ what: "SKU表", key: pre, n: sGroups[pre].length, at: npSkuTarget_(sSh, pre) });

    msg.push("【插入計畫】");
    plan.forEach(function (p) { msg.push("　" + p.what + "：" + p.key + "　" + p.n + " 列 → 插在第 " + p.at + " 列之後"); });
    msg.push("");
    msg.push("商品 " + stage.prod.length + " 列｜SKU " + stage.sku.length + " 列");
    msg.push("");
    if (warn.length) { msg.push("【要注意】"); warn.slice(0, 20).forEach(function (w) { msg.push("　" + w); });
      if (warn.length > 20) msg.push("　…還有 " + (warn.length - 20) + " 項"); }
    else msg.push("【檢查】沒有問題 ✅");

    var blocking = warn.filter(function (w) { return w.indexOf("❌") === 0; });

    if (!doWrite) {
      ui.alert("🔍 新品檢查", msg.join("\n"), ui.ButtonSet.OK);
      return;
    }
    if (blocking.length) {
      ui.alert("❌ 不能貼", "有 " + blocking.length + " 項阻擋問題，先處理：\n\n" + blocking.slice(0, 10).join("\n"), ui.ButtonSet.OK);
      return;
    }
    if (ui.alert("✅ 貼進 1-1", msg.join("\n") + "\n\n確定要插入嗎？", ui.ButtonSet.YES_NO) !== ui.Button.YES) return;

    // ── ① 先記下訂貨表死值（品號 → O/S/T）──
    var oLast = oSh.getLastRow();
    var oCodes = oSh.getRange(2, 1, oLast - 1, 1).getValues();
    var oDead = {};
    NP_ORDER_DEAD.forEach(function (col) {
      var vals = oSh.getRange(2, col, oLast - 1, 1).getValues();
      for (var k = 0; k < oCodes.length; k++) {
        var c = String(oCodes[k][0]).trim();
        if (!c) continue;
        (oDead[c] = oDead[c] || {})[col] = vals[k][0];
      }
    });
    var beforeFilled = 0;
    for (var cc in oDead) NP_ORDER_DEAD.forEach(function (col) { if (String(oDead[cc][col] || "").trim() !== "") beforeFilled++; });

    // ── ② 插入（由下往上，避免行號位移）──
    plan.sort(function (a, b) { return b.at - a.at; });
    plan.forEach(function (p) {
      var sh = (p.what === "商品表") ? pSh : sSh;
      var rows = (p.what === "商品表") ? pGroups[p.key] : sGroups[p.key];
      var ranges = (p.what === "商品表") ? NP_PROD_RANGES : NP_SKU_RANGES;
      sh.insertRowsAfter(p.at, p.n);
      var start = p.at + 1;
      ranges.forEach(function (rg) {
        var c0 = rg[0], w = rg[1];
        var block = rows.map(function (r) {
          var out = [];
          for (var x = 0; x < w; x++) out.push(r[c0 - 1 + x]);
          return out;
        });
        sh.getRange(start, c0, rows.length, w).setValues(block);
      });
    });
    SpreadsheetApp.flush();

    // ── ③ 訂貨表死值照品號重新對齊 ──
    var nLast = oSh.getLastRow();
    var nCodes = oSh.getRange(2, 1, nLast - 1, 1).getValues();
    var afterFilled = 0;
    NP_ORDER_DEAD.forEach(function (col) {
      var out = [];
      for (var k = 0; k < nCodes.length; k++) {
        var c = String(nCodes[k][0]).trim();
        var v = (c && oDead[c] && oDead[c][col] !== undefined) ? oDead[c][col] : "";
        if (String(v || "").trim() !== "") afterFilled++;
        out.push([v]);
      }
      oSh.getRange(2, col, out.length, 1).setValues(out);
    });
    SpreadsheetApp.flush();

    // ── ④ 驗證 ──
    var res = [];
    res.push("✅ 已插入：商品表 " + stage.prod.length + " 列、SKU表 " + stage.sku.length + " 列");
    res.push("訂貨表：" + (oLast - 1) + " → " + (nLast - 1) + " 列");
    res.push("死值(O/S/T)有值格數：" + beforeFilled + " → " + afterFilled +
             (beforeFilled === afterFilled ? "　✅ 一致" : "　⚠️ 不一致，請檢查！"));
    res.push("");
    res.push("接下來：SKU表 P 對應檢查應該全是 ✓。");
    ui.alert("📦 新品完成", res.join("\n"), ui.ButtonSet.OK);

  } catch (e) {
    ui.alert("❌ 失敗", e.message + "\n\n（沒有寫入任何東西，或已中途停止——請檢查後重跑）", ui.ButtonSet.OK);
  }
}
