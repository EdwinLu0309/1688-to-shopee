/**
 * 蝦皮上架協作檔 — 商品清單同步（獨立排程版）
 *
 * 用途：把「商品主表(1-1)」的商品清單（商品編號/分類/品名）定時同步進「共用雲的員工上架
 *   協作檔」。員工在協作檔手填的平台狀態欄（D 起：蝦皮ID/標題/詳情/圖片/選項圖/影片/優化/
 *   備註/蝦皮折扣）以「商品編號」為 key 原封保留，主表新增的商品自動補列、順序無所謂。
 *
 * 設計要點（與 syncStatusTab 同款：依主表順序重建、手填以編號帶回）：
 *   - 每次依「商品表」順序重建協作表 → 協作表排序永遠跟主表一模一樣（新商品插在對應位置）。
 *   - 手填欄(D..)以商品編號為 key 帶回，主表怎麼插列/重排都不會錯位、不丟員工資料。
 *   - 只讀主表「商品表」，不碰「蝦皮處理狀態」→ 完全不影響 master_reader / 資產包生產線。
 *   - 主表已刪、協作檔仍有的孤兒編號：不丟，移到清單最後（保留員工資料，人工再決定刪不刪）。
 *
 * ── 安裝（一次性，都在你 Google 帳號下做）──
 *   1) 在共用雲端硬碟建一張新的 Google Sheet（例：「蝦皮上架協作表(Nail)」），
 *      分頁改名為 COLLAB_TAB 的值，第 1 列表頭照這順序填：
 *        商品編號 | 分類 | 品名 | 蝦皮ID | 標題 | 詳情 | 圖片 | 選項圖 | 影片 | 優化 | 備註 | 蝦皮折扣
 *      （前 3 欄由本程式同步，D 起是員工手填。要加/減手填欄都可，程式自動抓寬度。）
 *   2) 打開這張協作檔 → 擴充功能 → Apps Script → 貼上本檔 → 把 COLLAB_ID 換成這張檔的 ID
 *      （網址 /d/ 和 /edit 之間那串）。MASTER_ID 已填好 Nail 主表，換賣場才需改。
 *   3) 編輯器上方選 syncUploadCollab → 執行 → 跳授權請同意 → 回協作檔確認清單被填好。
 *   4) 選 installSchedule → 執行 → 裝好「每小時」排程（要別的頻率改 everyHours 的數字）。
 */

var MASTER_ID  = '1eL58RfE_a5AQpSE4qGcLi0AsMKdDO_NLAsfB76NmtRc';  // 商品主表(1-1)；換賣場改這個
var MASTER_TAB = '商品表';                                        // 商品識別來源分頁
var COLLAB_ID  = '1I-xWfQg5EAil-3l17J8_lIKmaF8LW3DDAMB4hTn8E6k';   // 員工上架協作檔
var COLLAB_TAB = '蝦皮狀態';                                      // 協作檔的分頁名（跟你建的一致）

var IDENTITY_WIDTH = 3;   // A商品編號 / B分類 / C品名（由程式同步）
var MANUAL_START   = 4;   // D 欄起＝員工手填第一欄（以編號帶回、不被覆蓋）

/** 主排程函式：依主表「商品表」順序重建協作表，手填欄以商品編號帶回（不錯位、不丟資料）。 */
function syncUploadCollab(silent) {
  var src = SpreadsheetApp.openById(MASTER_ID).getSheetByName(MASTER_TAB);
  var dst = SpreadsheetApp.openById(COLLAB_ID).getSheetByName(COLLAB_TAB);
  if (!src) throw new Error('主表找不到分頁：' + MASTER_TAB);
  if (!dst) throw new Error('協作檔找不到分頁：' + COLLAB_TAB + '（檢查 COLLAB_ID / 分頁名）');

  // 1) 讀主表「商品表」：依出現順序取唯一編號 → [分類, 品名]
  //    欄位：A商品編號(1) B分類(2) C子分類(3) D品名(4)
  var mOrder = [], info = {}, mSeen = {};
  var mLast = src.getLastRow();
  if (mLast >= 2) {
    var mv = src.getRange(2, 1, mLast - 1, 4).getValues();
    for (var i = 0; i < mv.length; i++) {
      var code = String(mv[i][0]).trim();
      if (!code || mSeen[code]) continue;
      mSeen[code] = true;
      mOrder.push(code);
      info[code] = [mv[i][1], mv[i][3]];   // [分類, 品名]
    }
  }

  // 2) 讀協作檔既有列：以編號存 B:C(分類/品名) 與手填欄(D..)，供重建時帶回
  var dLast = dst.getLastRow();
  var totalW = Math.max(dst.getLastColumn(), MANUAL_START);   // 至少含到 D 欄
  var manW = totalW - (MANUAL_START - 1);                     // 手填欄數（D..）
  var store = {};   // code -> {bc:[分類,品名], man:[...手填...]}
  if (dLast >= 2) {
    var rows = dst.getRange(2, 1, dLast - 1, totalW).getValues();
    for (var k = 0; k < rows.length; k++) {
      var kc = String(rows[k][0]).trim();
      if (!kc || (kc in store)) continue;
      store[kc] = { bc: [rows[k][1], rows[k][2]], man: rows[k].slice(MANUAL_START - 1, totalW) };
    }
  }

  // 3) 依主表順序組整列（手填以編號帶回、新編號留空）；主表已無的孤兒接在最後
  var out = [];
  var emptyMan = new Array(manW).fill('');
  mOrder.forEach(function (code) {
    var man = (store[code] && store[code].man) ? store[code].man : emptyMan.slice();
    out.push([code, info[code][0], info[code][1]].concat(man));
  });
  var orphan = 0;
  for (var oc in store) {
    if (mSeen[oc]) continue;                       // 主表還有的已在上面處理
    out.push([oc, store[oc].bc[0], store[oc].bc[1]].concat(store[oc].man));
    orphan++;
  }

  // 4) 一次覆寫整區（原子性較好、不留空窗），再清掉尾端多餘的舊列
  var nOut = out.length;
  if (nOut) dst.getRange(2, 1, nOut, totalW).setValues(out);
  var tail = (dLast - 1) - nOut;
  if (tail > 0) dst.getRange(2 + nOut, 1, tail, totalW).clearContent();

  var msg = '同步完成：' + mOrder.length + ' 個商品依主表順序重建' +
            (orphan ? '；孤兒 ' + orphan + ' 列移到最後（主表已無）' : '');
  if (!silent) { try { dst.getParent().toast(msg, '上架協作同步', 6); } catch (e) {} }
  Logger.log(msg);
}

/** 安裝每小時排程（重複安裝會先清舊的，不會疊加）。要別的頻率改 everyHours()。 */
function installSchedule() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncUploadCollab') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncUploadCollab')
    .timeBased()
    .everyHours(1)   // 可改 2 / 4 / 6 / 12；或 .everyMinutes(30)
    .create();
  Logger.log('已安裝每小時排程：syncUploadCollab');
}

/** 解除排程（要停用時用）。 */
function removeSchedule() {
  var n = 0;
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncUploadCollab') { ScriptApp.deleteTrigger(t); n++; }
  });
  Logger.log('已移除 ' + n + ' 個排程');
}
