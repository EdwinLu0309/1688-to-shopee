/**
 * 「蝦皮處理狀態」分頁同步 — 通用外掛（Nail / Baby / Lady 都適用，函式完全一樣）
 *
 * 為什麼是「外掛」不是整包：這幾張主檔各自已有綁定的 Code.gs（🚀 主檔動作選單），
 * 一個專案只能有一個 onOpen()，所以本檔「不含 onOpen」，只提供 syncStatusTab()，
 * 貼進去不會蓋掉現有選單。
 *
 * 安裝（每張表各做一次）：
 *   1) 該表 → 擴充功能 → Apps Script → 左側「＋ → 指令碼」新增檔（例如「狀態同步.gs」）
 *      → 貼上本檔 → 儲存。
 *   2) 打開現有那支有 onOpen() 的 Code.gs，在「🚀 主檔動作」選單那串 .addItem(...) 的
 *      最後、.addToUi() 之前，加一行：
 *          .addItem('⑤ 同步蝦皮處理狀態', 'syncStatusTab')
 *   3)（可選，全自動）觸發條件 → 新增 → 選 syncStatusTab → 時間驅動 → 每小時。
 *   ※ 若某張表還沒裝過 Code.gs（沒有選單），可直接在 Apps Script 編輯器選 syncStatusTab
 *     按「執行」跑，或自行補一個 onOpen 建選單。
 *
 * 邏輯：以「商品編號」為 key 重建「蝦皮處理狀態」分頁 —— 手填欄（蝦皮ID/標題/詳情/
 *   圖片/選項圖/影片/優化/備註，全文字）原封帶回、新編號補空白、消失的移除，永不錯位。
 *   B/C（分類/品名）是 MAP 公式跟著 A 欄 live，不在此處理。
 */

function syncStatusTab(silent) {
  var ui = SpreadsheetApp.getUi();
  var STATUS_TAB = "蝦皮處理狀態";
  var SRC_TAB = "商品表";
  var MANUAL_START = 4;               // D 欄起（蝦皮ID）
  var MANUAL_END = 11;                // 到 K 欄（備註）
  var WIDTH = MANUAL_END - MANUAL_START + 1;   // 8 欄手填
  var EMPTY_MANUAL = ["", "", "", "", "", "", "", ""];  // 全文字，預設空白

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

  // 2) 既有手填資料 → 以編號為 key 存起來（D..K）
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

  // 3) 依商品表順序重建（手填以 key 帶回，永不錯位）
  var aVals = [], mVals = [];
  codes.forEach(function (code) {
    aVals.push([code]);
    mVals.push(store[code] ? store[code] : EMPTY_MANUAL.slice());
  });

  // 4) 先清舊資料區（A 與 D:K，B/C 是 MAP 公式不動），再寫新的
  var clearRows = Math.max(dstLast - 1, codes.length) + 5;
  if (clearRows > 0) {
    dst.getRange(2, 1, clearRows, 1).clearContent();                  // A
    dst.getRange(2, MANUAL_START, clearRows, WIDTH).clearContent();   // D:K
  }
  if (codes.length) {
    dst.getRange(2, 1, codes.length, 1).setValues(aVals);                    // A
    dst.getRange(2, MANUAL_START, codes.length, WIDTH).setValues(mVals);     // D:K
  }
  if (!silent) ss.toast("同步完成：" + codes.length + " 個商品", "⑤ 蝦皮處理狀態", 5);
}
